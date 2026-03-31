from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID
from uuid import uuid4

from attrs import define
from attrs import field
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.middelware.identity import IdentityUserContext
from src.database.exceptions import InsufficientPermissionsError
from src.database.exceptions import InvalidProjectConfigError
from src.database.postgres.document_index_models import Folder
from src.database.postgres.document_index_models import FolderHierarchy
from src.database.postgres.models.document_index.document_index import DocumentIndexORM
from src.database.postgres.models.document_index.folder import FolderORM
from src.database.postgres.models.integration import AccMetadataORM
from src.database.postgres.models.integration import SharePointMetadataORM
from src.database.postgres.py_models import IntegrationMetadata
from src.database.postgres.repos.permission_repo import PermissionRepository
from src.database.session_manager import SessionManager

logger = logging.getLogger(__name__)


@define
class FolderSyncStats:
    folders_added: int = 0
    folders_updated: int = 0
    folders_deleted: int = 0
    errors: list[str] = field(factory=list)


@define
class FolderRepository:
    session_manager: SessionManager

    # ------------------------------------------------------------------ #
    # READ                                                               #
    # ------------------------------------------------------------------ #

    def get_folders_by_integration(
        self,
        integration_id: UUID,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> list[Folder]:
        with self.session_manager.get_pg_session() as session:
            self._verify_integration_access(session, integration_id, user_id, user)
            stmt = (
                select(FolderORM)
                .where(FolderORM.integration_id == integration_id)
                .order_by(FolderORM.path)
            )
            return [folder_orm.to_domain() for folder_orm in session.scalars(stmt)]

    def get_folder_hierarchy(
        self,
        integration_id: UUID,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> FolderHierarchy:
        folders = self.get_folders_by_integration(integration_id, user_id, user)
        hierarchy = FolderHierarchy(integration_id=integration_id)
        for folder in folders:
            if folder.id is None:
                folder.id = uuid4()
            hierarchy.add_folder(folder)
        return hierarchy

    def get_folder_by_id(
        self, folder_id: UUID, user_id: UUID, user: IdentityUserContext | None = None
    ) -> Optional[Folder]:
        with self.session_manager.get_pg_session() as session:
            folder_orm = session.get(FolderORM, folder_id)
            if not folder_orm:
                return None
            self._verify_integration_access(
                session, folder_orm.integration_id, user_id, user
            )
            return folder_orm.to_domain()

    # ------------------------------------------------------------------ #
    # SYNC                                                               #
    # ------------------------------------------------------------------ #

    def sync_folders(
        self,
        integration_id: UUID,
        document_index_id: UUID | None,
        folder_hierarchy: FolderHierarchy,
        user_id: UUID,
        delete_missing_existing: bool = True,
        user: IdentityUserContext | None = None,
    ) -> FolderSyncStats:
        stats = FolderSyncStats()
        with self.session_manager.get_pg_session() as session:
            try:
                integration = self._verify_integration_access(
                    session, integration_id, user_id, user
                )
                self._verify_index_belongs_to_integration(
                    session, document_index_id, integration.id
                )

                existing_stmt = select(FolderORM).where(
                    FolderORM.integration_id == integration_id,
                    FolderORM.document_index_id == document_index_id,
                )
                existing_folders = {
                    folder.external_id: folder
                    for folder in session.scalars(existing_stmt)
                }

                # Build stable id mapping for incoming folder graph so parent pointers
                # always target ids that exist in the current transaction.
                incoming_by_id = {
                    folder.id: folder
                    for folder in folder_hierarchy.folders.values()
                    if folder.id is not None
                }
                target_ids_by_external_id: dict[str, UUID] = {}
                for folder in folder_hierarchy.folders.values():
                    existing = existing_folders.get(folder.external_id)
                    if existing:
                        target_ids_by_external_id[folder.external_id] = existing.id
                    elif folder.id is not None:
                        target_ids_by_external_id[folder.external_id] = folder.id
                    else:
                        target_ids_by_external_id[folder.external_id] = uuid4()

                for folder in folder_hierarchy.folders.values():
                    folder.integration_id = integration_id
                    folder.document_index_id = document_index_id

                    # Remap folder id to target id (existing row id if present).
                    folder.id = target_ids_by_external_id[folder.external_id]

                    # Remap parent id using external-id relationship from source hierarchy.
                    if folder.parent_id is not None:
                        parent_folder = incoming_by_id.get(folder.parent_id)
                        if parent_folder:
                            folder.parent_id = target_ids_by_external_id.get(
                                parent_folder.external_id
                            )

                    existing = existing_folders.get(folder.external_id)
                    if existing:
                        if self._folder_needs_update(existing, folder):
                            self._update_folder(session, existing, folder)
                            stats.folders_updated += 1
                        continue

                    session.add(FolderORM.from_domain(folder))
                    stats.folders_added += 1

                if delete_missing_existing:
                    source_external_ids = set(
                        folder_hierarchy.folders_by_external_id.keys()
                    )

                    # Database CASCADE on FK constraint handles child folder deletion automatically.
                    obsolete_folders = [
                        folder
                        for folder in existing_folders.values()
                        if folder.external_id not in source_external_ids
                    ]
                    for folder in obsolete_folders:
                        session.delete(folder)
                        stats.folders_deleted += 1

                logger.info(
                    "Synced folders for integration %s: +%s ~%s -%s",
                    integration_id,
                    stats.folders_added,
                    stats.folders_updated,
                    stats.folders_deleted,
                )
            except Exception as exc:  # pragma: no cover - logged for observability
                session.rollback()
                logger.error("Failed to sync folders: %s", exc, exc_info=True)
                stats.errors.append(str(exc))
        return stats

    def delete_by_external_ids_system(
        self,
        integration_id: UUID,
        external_ids: list[str],
        document_index_id: UUID | None = None,
    ) -> int:
        if not external_ids:
            return 0

        with self.session_manager.get_pg_session() as session:
            stmt = delete(FolderORM).where(
                FolderORM.integration_id == integration_id,
                FolderORM.external_id.in_(external_ids),
            )
            if document_index_id is None:
                stmt = stmt.where(FolderORM.document_index_id.is_(None))
            else:
                stmt = stmt.where(FolderORM.document_index_id == document_index_id)
            result = session.execute(stmt)
            return result.rowcount  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    # WRITE                                                              #
    # ------------------------------------------------------------------ #

    def create_folder(
        self, folder: Folder, user_id: UUID, user: IdentityUserContext | None = None
    ) -> Folder:
        with self.session_manager.get_pg_session() as session:
            integration = self._verify_integration_access(
                session, folder.integration_id, user_id, user
            )
            self._ensure_can_write(integration)
            self._verify_index_belongs_to_integration(
                session, folder.document_index_id, integration.id
            )
            if folder.id is None:
                folder.id = uuid4()
            folder_orm = FolderORM.from_domain(folder)
            session.add(folder_orm)
            session.flush()
            session.refresh(folder_orm)
            return folder_orm.to_domain()

    def update_folder(
        self, folder: Folder, user_id: UUID, user: IdentityUserContext | None = None
    ) -> Folder:
        with self.session_manager.get_pg_session() as session:
            if folder.id is None:
                raise InvalidProjectConfigError("Cannot update folder without an id")
            integration = self._verify_integration_access(
                session, folder.integration_id, user_id, user
            )
            self._ensure_can_write(integration)
            self._verify_index_belongs_to_integration(
                session, folder.document_index_id, integration.id
            )

            folder_orm = session.get(FolderORM, folder.id)
            if not folder_orm:
                raise InvalidProjectConfigError(f"Folder {folder.id} not found")

            updated = FolderORM.from_domain(folder)
            for key, value in updated.__dict__.items():
                if key.startswith("_"):
                    continue
                setattr(folder_orm, key, value)

            session.flush()
            session.refresh(folder_orm)
            return folder_orm.to_domain()

    def delete_folder(
        self, folder_id: UUID, user_id: UUID, user: IdentityUserContext | None = None
    ) -> None:
        with self.session_manager.get_pg_session() as session:
            folder_orm = session.get(FolderORM, folder_id)
            if not folder_orm:
                return

            integration = self._verify_integration_access(
                session, folder_orm.integration_id, user_id, user
            )
            self._ensure_can_write(integration)
            session.delete(folder_orm)

    # ------------------------------------------------------------------ #
    # INTERNAL HELPERS                                                   #
    # ------------------------------------------------------------------ #

    def _verify_integration_access(
        self,
        session: Session,
        integration_id: UUID,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> IntegrationMetadata:
        integration_orm = self._get_integration_orm(session, integration_id)
        if not integration_orm:
            raise InvalidProjectConfigError(f"Integration {integration_id} not found")
        if not self._user_has_access(integration_orm, user_id, session, user):
            raise InsufficientPermissionsError(
                f"User {user_id} does not have access to integration {integration_id}"
            )
        return integration_orm.to_domain()

    def _get_integration_orm(
        self, session: Session, integration_id: UUID
    ) -> Optional[SharePointMetadataORM | AccMetadataORM]:
        return session.get(SharePointMetadataORM, integration_id) or session.get(
            AccMetadataORM, integration_id
        )

    def _user_has_access(
        self,
        integration_orm,
        user_id: UUID,
        session: Session,
        user: IdentityUserContext | None = None,
    ) -> bool:
        permission_repo = PermissionRepository(self.session_manager)

        if user and (user.is_admin or user.is_system):
            return True

        effective_user_id = user.id if user else user_id

        if integration_orm.created_by == effective_user_id:
            return True

        if user:
            raw_perms = permission_repo.get_integration_permissions_for_groups(
                user.group_ids, integration_orm.id
            )
            if raw_perms:
                return True

            project_ids = permission_repo.list_projects_for_groups(user.group_ids)
            if project_ids:
                linked_projects = {p.id for p in integration_orm.project_omgevingen}
                if linked_projects.intersection(project_ids):
                    return True

        return False

    def _ensure_can_write(self, integration: IntegrationMetadata) -> None:
        if integration.read_only:
            raise InvalidProjectConfigError(
                f"Integration {integration.id} is read-only; folder writes are not allowed."
            )

    def _verify_index_belongs_to_integration(
        self, session: Session, index_id: UUID | None, integration_id: UUID
    ) -> None:
        """
        Verify that a document index belongs to the given integration.

        Args:
            index_id: The document index UUID, or None for staging mode
            integration_id: The integration UUID to verify against

        Raises:
            InvalidProjectConfigError: If index_id is provided but doesn't belong to integration

        Note:
            index_id=None is valid and represents staging mode (discovery before index creation).
            Folders and documents can exist in staging with document_index_id=NULL, and will be
            attached to an index when one is created via _attach_existing_assets_to_index().
        """
        # Allow None for staging mode (discovery before index creation)
        if index_id is None:
            return

        # Verify provided index belongs to integration
        index_orm = session.get(DocumentIndexORM, index_id)
        if not index_orm or index_orm.source_integration_id != integration_id:
            raise InvalidProjectConfigError(
                f"Document index {index_id} does not belong to integration {integration_id}"
            )

    @staticmethod
    def _folder_needs_update(existing: FolderORM, incoming: Folder) -> bool:
        return any(
            [
                existing.name != incoming.name,
                existing.path != incoming.path,
                existing.parent_id != incoming.parent_id,
                existing.web_url != incoming.web_url,
                existing.folder_metadata != incoming.metadata,
            ]
        )

    @staticmethod
    def _update_folder(
        session: Session, folder_orm: FolderORM, incoming: Folder
    ) -> None:
        folder_orm.name = incoming.name
        folder_orm.path = incoming.path
        folder_orm.parent_id = incoming.parent_id
        folder_orm.web_url = incoming.web_url
        folder_orm.folder_metadata = incoming.metadata
