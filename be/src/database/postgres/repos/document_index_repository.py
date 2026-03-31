from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from attrs import define, field
from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.orm import Session

from src.api.middleware.identity import IdentityUserContext
from src.database.exceptions import (
    InsufficientPermissionsError,
    InvalidProjectConfigError,
)
from src.database.postgres.document_index_models import (
    DocumentDatabaseIndex,
    DocumentProcessingStatus,
    DocumentUnit,
    DocumentUnitBase,
    ExternalDocument,
    FilenameSearchResult,
    Folder,
    FolderHierarchy,
)
from src.database.postgres.models.document_index import DocumentIndexORM
from src.database.postgres.models.document_unit import DocumentUnitORM
from src.database.postgres.models.folder import FolderORM
from src.database.postgres.models.document_user_access import DocumentUserAccessORM

from src.database.postgres.py_models import IntegrationType, OCRStatus
from src.database.postgres.repos.permission_repo import PermissionRepository
from src.database.session_manager import SessionManager, get_session_manager
from src.database.weavite.repos.document_index_repo import (
    get_vector_document_index_repo,
)

logger = logging.getLogger(__name__)


def get_document_index_repo() -> "DocumentIndexRepository":
    return DocumentIndexRepository(get_session_manager())


@define
class DocumentSyncStats:
    documents_added: int = 0
    documents_updated: int = 0
    documents_deleted: int = 0
    added_documents: list[DocumentUnitBase] = field(factory=list)
    all_synced_document_ids: list[UUID] = field(factory=list)
    errors: list[str] = field(factory=list)


@define
class DocumentIndexRepository:
    """Repository for managing document indexes and their assets."""

    session_manager: SessionManager

    # --------------------------------------------------------------------- #
    # INDEX LIFECYCLE                                                       #
    # --------------------------------------------------------------------- #

    def add(self, index: DocumentDatabaseIndex) -> DocumentDatabaseIndex:
        """
        Create a new document index.

        Raises:
            InvalidProjectConfigError: When the source integration already has an index.
            InsufficientPermissionsError: When the creator cannot access the source integration.
        """
        with self.session_manager.get_pg_session() as session:
            self._assert_index_absent(session, index.source_integration_id)

            source = self._get_source_integration(
                session, index.source_integration_id, index.source_integration_type
            )
            self._ensure_user_has_access(source, index.created_by, session)

            orm = DocumentIndexORM.from_domain(index)
            session.add(orm)
            session.flush()
            self._attach_existing_assets_to_index(session, orm)
            self._recalculate_index_stats(session, orm)
            session.refresh(orm)
            return self._to_domain(orm, session)

    def get(
        self,
        user_id: UUID,
        index_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> Optional[DocumentDatabaseIndex]:
        """Retrieve a document index after verifying that the user can access its source integration."""

        with self.session_manager.get_pg_session() as session:
            orm = self._verify_index_access(session, index_id, user_id, user)
            return self._to_domain(orm, session)

    def get_index_by_source_integration(
        self,
        source_integration_id: UUID,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> Optional[DocumentDatabaseIndex]:
        """Return the index for a specific source integration, if present."""
        with self.session_manager.get_pg_session() as session:
            stmt = select(DocumentIndexORM).filter(
                DocumentIndexORM.source_integration_id == source_integration_id
            )
            orm = session.scalar(stmt)
            if not orm:
                return None

            source = self._get_source_integration(
                session,
                orm.source_integration_id,
                IntegrationType(orm.source_integration_type),
            )
            self._ensure_user_has_access(source, user_id, session, user)
            attachments = self._attach_existing_assets_to_index(session, orm)
            if attachments:
                self._recalculate_index_stats(session, orm)
            return self._to_domain(orm, session)

    def update(
        self,
        user_id: UUID,
        index: DocumentDatabaseIndex,
        user: IdentityUserContext | None = None,
    ) -> DocumentDatabaseIndex:
        """Persist changes to an existing document index."""
        with self.session_manager.get_pg_session() as session:
            orm = self._verify_index_access(session, index.id, user_id, user)

            index.modified_at = datetime.now(timezone.utc)
            orm.update_from_domain(index)
            self._recalculate_index_stats(session, orm)

            session.flush()
            session.refresh(orm)
            return self._to_domain(orm, session)

    def delete(
        self,
        index_id: UUID,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> None:
        """
        Hard delete a document index and all associated data.

        This will:
        1. Delete vector DB collections for the integration
        2. Hard delete all documents in the index (CASCADE)
        3. Hard delete all folders in the index (CASCADE)
        4. Hard delete the index itself
        """
        with self.session_manager.get_pg_session() as session:
            orm = self._verify_index_access(session, index_id, user_id, user)
            integration_id = orm.source_integration_id

            # Delete vector DB collections
            try:
                vector_repo = get_vector_document_index_repo()
                vector_repo.delete_collections(integration_id)
                logger.info(
                    f"Deleted vector DB collections for integration {integration_id}"
                )
            except Exception as e:
                logger.warning(f"Failed to delete vector DB collections: {e}")

            # Hard delete all documents in this index
            doc_count = (
                session.query(DocumentUnitORM)
                .filter(DocumentUnitORM.document_index_id == index_id)
                .delete(synchronize_session=False)
            )

            # Hard delete all folders in this index
            folder_count = (
                session.query(FolderORM)
                .filter(FolderORM.document_index_id == index_id)
                .delete(synchronize_session=False)
            )

            # Hard delete the index itself
            session.delete(orm)
            session.flush()

            logger.info(
                f"Hard deleted index {index_id}: {doc_count} documents, {folder_count} folders"
            )

    def list_all(
        self, user_id: UUID, user: IdentityUserContext | None = None
    ) -> list[DocumentDatabaseIndex]:
        """List every document index the user is allowed to see."""
        with self.session_manager.get_pg_session() as session:
            stmt = select(DocumentIndexORM)
            orms = session.scalars(stmt).all()

            visible_indexes: list[DocumentDatabaseIndex] = []
            for orm in orms:
                attachments = self._attach_existing_assets_to_index(session, orm)
                if attachments:
                    self._recalculate_index_stats(session, orm)
                source = self._get_source_integration(
                    session,
                    orm.source_integration_id,
                    IntegrationType(orm.source_integration_type),
                )
                if self._user_has_access(source, user_id, session, user):
                    visible_indexes.append(self._to_domain(orm, session))
            return visible_indexes

    # --------------------------------------------------------------------- #
    # FOLDER OPERATIONS                                                     #
    # --------------------------------------------------------------------- #

    # --------------------------------------------------------------------- #
    # DOCUMENT OPERATIONS                                                   #
    # --------------------------------------------------------------------- #

    def get_unindexed_document_count(self, integration_id: UUID) -> int:
        """
        Count documents in staging area for an integration.

        Returns count of documents where integration_id matches and document_index_id is NULL.
        """
        with self.session_manager.get_pg_session() as session:
            count = (
                session.query(func.count(DocumentUnitORM.id))
                .filter(
                    and_(
                        DocumentUnitORM.integration_id == integration_id,
                        DocumentUnitORM.document_index_id.is_(None),
                    )
                )
                .scalar()
            ) or 0
            return int(count)

    def get_unindexed_total_size(self, integration_id: UUID) -> int:
        """
        Get total size of documents in staging area for an integration.

        Returns sum of sizes where integration_id matches and document_index_id is NULL.
        """
        with self.session_manager.get_pg_session() as session:
            total = (
                session.query(func.sum(DocumentUnitORM.size))
                .filter(
                    and_(
                        DocumentUnitORM.integration_id == integration_id,
                        DocumentUnitORM.document_index_id.is_(None),
                    )
                )
                .scalar()
            ) or 0
            return int(total)

    def get_total_document_count(self, integration_id: UUID) -> int:
        """
        Count ALL documents for an integration regardless of indexing state.

        Returns count of all documents where integration_id matches (both indexed and staging).
        This represents the total discovered documents from the integration source.
        """
        with self.session_manager.get_pg_session() as session:
            count = (
                session.query(func.count(DocumentUnitORM.id))
                .filter(DocumentUnitORM.integration_id == integration_id)
                .scalar()
            ) or 0
            return int(count)

    def get_total_size(self, integration_id: UUID) -> int:
        """
        Get total size of ALL documents for an integration regardless of indexing state.

        Returns sum of sizes for all documents where integration_id matches (both indexed and staging).
        This represents the total size of discovered documents from the integration source.
        """
        with self.session_manager.get_pg_session() as session:
            total = (
                session.query(func.sum(DocumentUnitORM.size))
                .filter(DocumentUnitORM.integration_id == integration_id)
                .scalar()
            ) or 0
            return int(total)

    def get_processing_stats(self, index_id: UUID) -> dict[str, int]:
        """
        Get processing progress statistics for a document index.

        Returns counts of documents by processing status and the total number of
        documents expected to reach a terminal sync state. Unsupported files are
        indexed as SKIPPED, so they still count toward progress.

        Returns:
            Dictionary with keys:
            - total_documents: Total documents in index
            - processable_documents: Documents counted in progress tracking
            - processed: Documents with status PROCESSED
            - in_progress: Documents with status IN_PROGRESS
            - failed: Documents with status FAILED
            - skipped: Documents with status SKIPPED
            - not_processed: Documents with status NOT_PROCESSED
        """
        with self.session_manager.get_pg_session() as session:
            # Get status counts
            status_counts_stmt = (
                select(
                    DocumentUnitORM.status,
                    func.count(DocumentUnitORM.id).label("count"),
                )
                .where(DocumentUnitORM.document_index_id == index_id)
                .group_by(DocumentUnitORM.status)
            )
            status_rows = session.execute(status_counts_stmt).all()

            # Initialize status counts
            status_counts: dict[DocumentProcessingStatus, int] = {
                DocumentProcessingStatus.PROCESSED: 0,
                DocumentProcessingStatus.PROCESSING: 0,
                DocumentProcessingStatus.FAILED: 0,
                DocumentProcessingStatus.NOT_PROCESSED: 0,
                DocumentProcessingStatus.SKIPPED: 0,
            }

            total_documents = 0
            for row in status_rows:
                # row is a tuple: (status, count)
                row_status = row[0]
                row_count = row[1]
                status_counts[row_status] = int(row_count)
                total_documents += int(row_count)

            return {
                "total_documents": total_documents,
                "processable_documents": total_documents,
                "processed": status_counts[DocumentProcessingStatus.PROCESSED],
                "in_progress": status_counts[DocumentProcessingStatus.PROCESSING],
                "failed": status_counts[DocumentProcessingStatus.FAILED],
                "skipped": status_counts[DocumentProcessingStatus.SKIPPED],
                "not_processed": status_counts[DocumentProcessingStatus.NOT_PROCESSED],
            }

    def attach_unindexed_documents_to_index(
        self, integration_id: UUID, document_index_id: UUID
    ) -> int:
        """
        Attach all unindexed documents from an integration to a document index.

        Updates all documents where integration_id matches and document_index_id is NULL
        to set document_index_id to the provided index.

        Returns count of attached documents.
        """
        with self.session_manager.get_pg_session() as session:
            # Verify index exists and belongs to this integration
            index_orm = session.get(DocumentIndexORM, document_index_id)
            if not index_orm:
                raise InvalidProjectConfigError(
                    f"Document index {document_index_id} not found"
                )
            if index_orm.source_integration_id != integration_id:
                raise InvalidProjectConfigError(
                    f"Document index {document_index_id} does not belong to integration {integration_id}"
                )

            # Update all unindexed documents
            updated_count = (
                session.query(DocumentUnitORM)
                .filter(
                    and_(
                        DocumentUnitORM.integration_id == integration_id,
                        DocumentUnitORM.document_index_id.is_(None),
                    )
                )
                .update(
                    {"document_index_id": document_index_id}, synchronize_session=False
                )
            )

            # Recalculate index stats
            self._recalculate_index_stats(session, index_orm)
            session.flush()

            logger.info(
                f"Attached {updated_count} documents from staging area to index {document_index_id}"
            )
            return updated_count

    def reset_processing_documents(self, document_index_id: UUID) -> int:
        """Reset documents stuck in PROCESSING back to NOT_PROCESSED.

        Used after sync cancellation to unlock documents that were being
        processed but never completed.
        """
        with self.session_manager.get_pg_session() as session:
            docs = (
                session.query(DocumentUnitORM)
                .filter(
                    DocumentUnitORM.document_index_id == document_index_id,
                    DocumentUnitORM.status == DocumentProcessingStatus.PROCESSING,
                )
                .all()
            )
            for doc in docs:
                doc.status = DocumentProcessingStatus.NOT_PROCESSED
                if doc.run_ocr:
                    doc.ocr_status = OCRStatus.NOT_REQUESTED
            session.flush()
            logger.info(
                "Reset %d PROCESSING documents back to NOT_PROCESSED for index %s",
                len(docs),
                document_index_id,
            )
            return len(docs)

    def reset_documents_to_staging(
        self, document_index_id: UUID, integration_id: UUID
    ) -> int:
        """
        Reset all documents from an index back to staging area.

        Sets document_index_id to NULL and clears processed fields for all documents
        belonging to the given index.

        Returns count of documents reset.
        """
        with self.session_manager.get_pg_session() as session:
            # Get all documents for this index
            docs = (
                session.query(DocumentUnitORM)
                .filter(DocumentUnitORM.document_index_id == document_index_id)
                .all()
            )

            reset_count = 0
            for doc in docs:
                # Reset to staging
                doc.document_index_id = None
                doc.status = DocumentProcessingStatus.NOT_PROCESSED
                doc.processed_at = None
                doc.full_text = None
                doc.summary = None
                doc.short_summary = None
                doc.index_values = None
                doc.pages = None
                doc.ocr_status = OCRStatus.NOT_REQUESTED
                doc.ocr_error_message = None
                doc.ocr_completed_at = None
                reset_count += 1

            session.flush()

            logger.info(
                f"Reset {reset_count} documents from index {document_index_id} back to staging"
            )
            return reset_count

    def add_document(
        self,
        document: DocumentUnit,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> DocumentUnit:
        if document.document_index_id is None:
            raise InvalidProjectConfigError(
                "document.document_index_id must be set when adding a document to an index"
            )
        with self.session_manager.get_pg_session() as session:
            index_orm = self._verify_index_access(
                session, document.document_index_id, user_id, user
            )
            if document.integration_id != index_orm.source_integration_id:
                document.integration_id = index_orm.source_integration_id
            document.document_index_id = index_orm.id

            document_orm = DocumentUnitORM.from_domain(document)
            session.add(document_orm)
            session.flush()
            self._recalculate_index_stats(session, index_orm)
            session.refresh(document_orm)
            return document_orm.to_domain()

    def add_document_base(
        self,
        document: DocumentUnitBase,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> DocumentUnitBase:
        if document.document_index_id is None:
            raise InvalidProjectConfigError(
                "document.document_index_id must be set when adding a document to an index"
            )
        with self.session_manager.get_pg_session() as session:
            index_orm = self._verify_index_access(
                session, document.document_index_id, user_id, user
            )
            if document.integration_id != index_orm.source_integration_id:
                document.integration_id = index_orm.source_integration_id
            document.document_index_id = index_orm.id

            document_orm = DocumentUnitORM.from_base_domain(document)
            session.add(document_orm)
            session.flush()
            self._recalculate_index_stats(session, index_orm)
            session.refresh(document_orm)
            return document_orm.to_base_domain()

    def get_document_by_id(
        self,
        document_id: UUID,
        user_id: Optional[UUID] = None,
        user: IdentityUserContext | None = None,
    ) -> Optional[DocumentUnit]:
        with self.session_manager.get_pg_session() as session:
            doc_orm = session.get(DocumentUnitORM, document_id)
            if not doc_orm:
                return None
            if user_id is not None:
                assert doc_orm.document_index_id
                index_orm = self._verify_index_access(
                    session, doc_orm.document_index_id, user_id, user
                )
                if not self._user_has_document_access(
                    session=session,
                    index_orm=index_orm,
                    document_id=document_id,
                    user_id=user_id,
                    user=user,
                ):
                    return None
            return doc_orm.to_domain()

    def get_documents_by_status(
        self,
        index_id: UUID,
        status: DocumentProcessingStatus,
        limit: int | None = None,
    ) -> list[DocumentUnitBase]:
        with self.session_manager.get_pg_session() as session:
            stmt = (
                select(DocumentUnitORM)
                .where(DocumentUnitORM.document_index_id == index_id)
                .where(DocumentUnitORM.status == status)
                .order_by(DocumentUnitORM.created_at)
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            docs = session.scalars(stmt).all()
            return [doc.to_base_domain() for doc in docs]

    def sync_documents(
        self,
        integration_id: UUID,
        document_index_id: UUID | None,
        external_documents: list[ExternalDocument],
        deleted_external_ids: list[str],
        folder_hierarchy: FolderHierarchy | None = None,
        prune_missing_existing: bool = False,
        prune_missing_existing_folder_ids: list[UUID] | None = None,
    ) -> DocumentSyncStats:
        stats = DocumentSyncStats()
        with self.session_manager.get_pg_session() as session:
            try:
                # Folder IDs in external documents may come from a transient in-memory hierarchy.
                # Remap them to persisted folder IDs after folder sync.
                folder_id_remap: dict[UUID, UUID] = {}
                if folder_hierarchy:
                    for original_id, folder in folder_hierarchy.folders.items():
                        if original_id and folder.id:
                            folder_id_remap[original_id] = folder.id

                # Validate document index if provided
                index_orm = None
                if document_index_id:
                    index_orm = session.get(DocumentIndexORM, document_index_id)
                    if (
                        not index_orm
                        or index_orm.source_integration_id != integration_id
                    ):
                        raise InvalidProjectConfigError(
                            f"Document index {document_index_id} does not belong to integration {integration_id}"
                        )

                # Query for existing documents (either by index_id or integration_id for staging)
                if document_index_id:
                    existing_stmt = select(DocumentUnitORM).where(
                        DocumentUnitORM.document_index_id == document_index_id
                    )
                else:
                    # Staging mode: query by integration_id where document_index_id is NULL
                    existing_stmt = select(DocumentUnitORM).where(
                        and_(
                            DocumentUnitORM.integration_id == integration_id,
                            DocumentUnitORM.document_index_id.is_(None),
                        )
                    )
                existing_docs = {
                    doc.external_id: doc for doc in session.scalars(existing_stmt)
                }

                if prune_missing_existing or prune_missing_existing_folder_ids:
                    external_ids = {doc.id for doc in external_documents}
                    if prune_missing_existing_folder_ids:
                        scoped_folder_ids = set(prune_missing_existing_folder_ids)
                        missing_external_ids = [
                            external_id
                            for external_id, existing_doc in existing_docs.items()
                            if existing_doc.folder_id in scoped_folder_ids
                            and external_id not in external_ids
                        ]
                    else:
                        missing_external_ids = [
                            external_id
                            for external_id in existing_docs
                            if external_id not in external_ids
                        ]
                    deleted_external_ids = list(
                        {
                            *deleted_external_ids,
                            *missing_external_ids,
                        }
                    )

                if deleted_external_ids:
                    for external_id in deleted_external_ids:
                        doc = existing_docs.get(external_id)
                        if not doc:
                            continue
                        session.delete(doc)
                        stats.documents_deleted += 1

                for external_doc in external_documents:
                    resolved_folder_id = external_doc.folder_id
                    if resolved_folder_id is not None:
                        resolved_folder_id = folder_id_remap.get(
                            resolved_folder_id, resolved_folder_id
                        )

                    existing = existing_docs.get(external_doc.id)
                    if existing:
                        updated = False

                        if existing.folder_id != resolved_folder_id:
                            existing.folder_id = resolved_folder_id
                            updated = True

                        basic_fields = {
                            "filename": external_doc.filename,
                            "path": external_doc.path,
                            "size": external_doc.size,
                            "web_url": external_doc.web_url,
                            "download_url": external_doc.download_url,
                            "doc_metadata": external_doc.metadata,
                            "content_hash": external_doc.metadata.get("hash")
                            if external_doc.metadata
                            else None,
                        }
                        for attr, value in basic_fields.items():
                            if getattr(existing, attr) != value:
                                setattr(existing, attr, value)
                                updated = True

                        # Backfill path: previously unsupported files were SKIPPED with empty
                        # content and never reached the vector index. Requeue once so they
                        # can be processed into searchable placeholder content.
                        if (
                            existing.status == DocumentProcessingStatus.SKIPPED
                            and existing.error_message == "Unsupported file type"
                            and not existing.summary
                        ):
                            existing.status = DocumentProcessingStatus.NOT_PROCESSED
                            existing.processed_at = None
                            existing.full_text = None
                            existing.summary = None
                            existing.short_summary = None
                            existing.index_values = None
                            existing.ocr_error_message = None
                            if not existing.run_ocr:
                                existing.ocr_status = OCRStatus.NOT_REQUESTED
                                existing.ocr_completed_at = None
                            updated = True

                        if external_doc.modified_at > existing.external_modified_at:
                            existing.external_modified_at = external_doc.modified_at
                            existing.status = DocumentProcessingStatus.NOT_PROCESSED
                            existing.processed_at = None
                            existing.full_text = None
                            existing.summary = None
                            existing.short_summary = None
                            existing.index_values = None
                            existing.ocr_error_message = None
                            existing.ocr_completed_at = None
                            existing.ocr_status = OCRStatus.NOT_REQUESTED
                            updated = True

                        if updated:
                            stats.documents_updated += 1
                        stats.all_synced_document_ids.append(existing.id)
                        continue

                    doc_unit_base = external_doc.to_unit(
                        integration_id=integration_id,
                        document_index_id=document_index_id,
                        doc_process_status=DocumentProcessingStatus.NOT_PROCESSED,
                    )
                    doc_orm = DocumentUnitORM.from_base_domain(doc_unit_base)
                    doc_orm.folder_id = resolved_folder_id
                    session.add(doc_orm)
                    stats.documents_added += 1
                    stats.added_documents.append(doc_orm.to_base_domain())
                    stats.all_synced_document_ids.append(doc_orm.id)

                # Only recalculate stats if we have an index (not staging mode)
                if index_orm:
                    self._recalculate_index_stats(session, index_orm)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error(
                    "Failed to sync documents for index %s: %s",
                    document_index_id,
                    exc,
                    exc_info=True,
                )
                stats.errors.append(str(exc))
        return stats

    def bulk_update_processed_documents(self, documents: list[DocumentUnit]) -> None:
        if not documents:
            return

        with self.session_manager.get_pg_session() as session:
            index_ids: set[UUID | None] = {doc.document_index_id for doc in documents}
            index_map: dict[UUID, DocumentIndexORM] = {}
            for index_id in index_ids:
                index_orm = session.get(DocumentIndexORM, index_id)
                if not index_orm:
                    raise InvalidProjectConfigError(
                        f"Document index {index_id} not found for processed document update"
                    )
                if index_id:
                    index_map[index_id] = index_orm
                else:
                    logger.error(
                        "Encountered processed document without document_index_id during bulk update"
                    )

            for doc in documents:
                doc_orm = session.get(DocumentUnitORM, doc.id)
                if not doc_orm:
                    raise InvalidProjectConfigError(
                        f"Document {doc.id} not found for bulk update"
                    )
                updated = DocumentUnitORM.from_domain(doc)
                for key, value in updated.__dict__.items():
                    if key.startswith("_"):
                        continue
                    setattr(doc_orm, key, value)

            for index_orm in index_map.values():
                self._recalculate_index_stats(session, index_orm)

    def update_document_status(
        self,
        document_id: UUID,
        status: DocumentProcessingStatus,
        error_message: str | None = None,
    ) -> None:
        with self.session_manager.get_pg_session() as session:
            doc_orm = session.get(DocumentUnitORM, document_id)
            if not doc_orm:
                raise InvalidProjectConfigError(f"Document {document_id} not found")
            doc_orm.status = status
            doc_orm.error_message = error_message
            if status == DocumentProcessingStatus.PROCESSED:
                doc_orm.processed_at = datetime.now(timezone.utc)
            else:
                doc_orm.processed_at = None

    def mark_ocr_processing(self, document_id: UUID) -> bool:
        with self.session_manager.get_pg_session() as session:
            updated_count = (
                session.query(DocumentUnitORM)
                .filter(
                    DocumentUnitORM.id == document_id,
                    DocumentUnitORM.ocr_status != OCRStatus.PROCESSING,
                )
                .update(
                    {
                        "run_ocr": True,
                        "ocr_status": OCRStatus.PROCESSING,
                        "ocr_error_message": None,
                        "ocr_requested_at": datetime.now(timezone.utc),
                        "ocr_completed_at": None,
                    },
                    synchronize_session=False,
                )
            )
            return updated_count > 0

    def get_document_by_external_id(
        self,
        index_id: UUID,
        external_id: str,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> Optional[DocumentUnit]:
        with self.session_manager.get_pg_session() as session:
            self._verify_index_access(session, index_id, user_id, user)

            stmt = select(DocumentUnitORM).filter(
                and_(
                    DocumentUnitORM.document_index_id == index_id,
                    DocumentUnitORM.external_id == external_id,
                )
            )
            doc_orm = session.scalar(stmt)
            return doc_orm.to_domain() if doc_orm else None

    def get_documents_by_index(
        self, index_id: UUID, user_id: UUID, user: IdentityUserContext | None = None
    ) -> list[DocumentUnit]:
        with self.session_manager.get_pg_session() as session:
            index_orm = self._verify_index_access(session, index_id, user_id, user)

            stmt = select(DocumentUnitORM).filter(
                DocumentUnitORM.document_index_id == index_id
            )
            if self._should_enforce_document_access(index_orm, user_id, user):
                stmt = stmt.where(
                    self._build_document_access_exists_clause(
                        document_id_column=DocumentUnitORM.id,
                        user_id=user_id,
                    )
                )
            return [doc_orm.to_domain() for doc_orm in session.scalars(stmt)]

    def search_filenames(
        self,
        index_id: UUID,
        user_id: UUID,
        query: str,
        limit: int = 10,
        user: IdentityUserContext | None = None,
    ) -> list[FilenameSearchResult]:
        if limit <= 0:
            return []

        with self.session_manager.get_pg_session() as session:
            index_orm = self._verify_index_access(session, index_id, user_id, user)

            stmt = (
                select(
                    DocumentUnitORM.id.label("document_id"),
                    DocumentUnitORM.filename.label("filename"),
                    DocumentUnitORM.external_modified_at.label("modified_at"),
                )
                .where(DocumentUnitORM.document_index_id == index_id)
                .where(DocumentUnitORM.is_latest_revision.is_(True))
                .where(
                    or_(
                        DocumentUnitORM.canonical_document_id.is_(None),
                        DocumentUnitORM.canonical_document_id == DocumentUnitORM.id,
                    )
                )
            )
            if self._should_enforce_document_access(index_orm, user_id, user):
                stmt = stmt.where(
                    self._build_document_access_exists_clause(
                        document_id_column=DocumentUnitORM.id,
                        user_id=user_id,
                    )
                )

            normalized_query = query.strip().lower()
            if normalized_query:
                lower_filename = func.lower(DocumentUnitORM.filename)
                contains_pattern = f"%{normalized_query}%"
                prefix_pattern = f"{normalized_query}%"
                stmt = stmt.where(lower_filename.like(contains_pattern))

                priority_case = case(
                    (lower_filename.like(prefix_pattern), 0),
                    else_=1,
                )

                stmt = stmt.order_by(
                    priority_case,
                    func.length(DocumentUnitORM.filename),
                    DocumentUnitORM.external_modified_at.desc(),
                )
            else:
                stmt = stmt.order_by(DocumentUnitORM.external_modified_at.desc())

            stmt = stmt.limit(limit)
            rows = session.execute(stmt).all()

            results: list[FilenameSearchResult] = []
            for row in rows:
                filename = row.filename
                document_id = row.document_id
                if not normalized_query:
                    score = 0.0
                else:
                    filename_lower = filename.lower()
                    if filename_lower.startswith(normalized_query):
                        score = 1.0
                    elif normalized_query in filename_lower:
                        score = 0.5
                    else:
                        score = 0.0

                results.append(
                    FilenameSearchResult(
                        document_id=document_id,
                        filename=filename,
                        score=score,
                    )
                )

            return results

    def get_all_document_ids_and_filenames(
        self, index_id: UUID
    ) -> list[tuple[UUID, str]]:
        """
        Retrieves the ID and filename for all documents for a given index_id.

        This query is optimized to only select the specific columns needed (id, filename)
        at the database level, avoiding loading the entire DocumentUnitORM object
        into memory for each row.

        Args:
            index_id: The UUID of the document index.

        Returns:
            A list of tuples, where each tuple contains the document's UUID (id)
            and its filename.
        """
        with self.session_manager.get_pg_session() as session:
            # 1. Select specific columns instead of the whole object
            stmt = select(DocumentUnitORM.id, DocumentUnitORM.filename).filter(
                # 2. The 'and_' function is not necessary for a single condition
                DocumentUnitORM.document_index_id == index_id
            )

            # 3. Execute the statement and fetch all results directly
            results = session.execute(stmt).all()

            # FIX: Explicitly convert each Row object to a tuple
            return [tuple(row) for row in results]

    def get_documents_by_ids(self, document_ids: list[UUID]) -> list[DocumentUnit]:
        """
        Retrieve multiple DocumentUnit objects by their IDs.

        This is optimized for batch fetching and returns full DocumentUnit
        objects with all fields including full_text.
        """
        with self.session_manager.get_pg_session() as session:
            stmt = select(DocumentUnitORM).where(DocumentUnitORM.id.in_(document_ids))
            docs = session.scalars(stmt).all()
            return [doc.to_domain() for doc in docs]

    def list_documents_for_integration_system(
        self,
        integration_id: UUID,
    ) -> list[DocumentUnit]:
        with self.session_manager.get_pg_session() as session:
            stmt = (
                select(DocumentUnitORM)
                .where(DocumentUnitORM.integration_id == integration_id)
                .where(DocumentUnitORM.is_latest_revision.is_(True))
                .order_by(DocumentUnitORM.path, DocumentUnitORM.filename)
            )
            docs = session.scalars(stmt).all()
            return [doc.to_domain() for doc in docs]

    def get_documents_by_hashes(
        self, hashes: list[str], integration_id: UUID
    ) -> list[DocumentUnit]:
        """
        Retrieve documents that match any of the provided content hashes.

        Args:
            hashes: List of content hash strings to search for
            integration_id: Restrict search to this integration

        Returns:
            List of DocumentUnit objects matching the hashes
        """
        if not hashes:
            return []

        with self.session_manager.get_pg_session() as session:
            stmt = (
                select(DocumentUnitORM)
                .where(DocumentUnitORM.integration_id == integration_id)
                .where(DocumentUnitORM.content_hash.in_(hashes))
            )
            docs = session.scalars(stmt).all()
            return [doc.to_domain() for doc in docs]

    def get_documents_by_folder(
        self,
        index_id: UUID,
        folder_id: UUID,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> list[DocumentUnit]:
        with self.session_manager.get_pg_session() as session:
            index_orm = self._verify_index_access(session, index_id, user_id, user)

            stmt = select(DocumentUnitORM).filter(
                and_(
                    DocumentUnitORM.document_index_id == index_id,
                    DocumentUnitORM.folder_id == folder_id,
                )
            )
            if self._should_enforce_document_access(index_orm, user_id, user):
                stmt = stmt.where(
                    self._build_document_access_exists_clause(
                        document_id_column=DocumentUnitORM.id,
                        user_id=user_id,
                    )
                )
            return [doc_orm.to_domain() for doc_orm in session.scalars(stmt)]

    def search_folders_and_documents(
        self,
        index_id: UUID,
        query: str,
        search_type: Optional[str] = None,
        max_results: int = 30,
        offset: int = 0,
        user_id: Optional[UUID] = None,
        user: IdentityUserContext | None = None,
    ) -> tuple[list[Folder], list[DocumentUnit], int, int]:
        """
        Search folders and documents by path/filename using unified syntax.

        PATH FORMAT: No leading slash (e.g., 'General/*' not '/General/*')

        GLOB SYNTAX:
        - 'folder/*' matches ONLY direct children (1 level deep) - * does NOT cross /
        - 'folder/**' matches ALL descendants (recursive) - ** crosses path separators
        - '*.pdf' matches files ending with .pdf at any depth
        - Plain text is case-insensitive substring search

        Args:
            index_id: The document index to search in
            query: Search pattern (glob or text). NO leading slash.
            search_type: Optional filter - 'folder', 'document', or None for both
            max_results: Maximum results to return (default 30, max 30)
            offset: Offset for pagination (0 for first page, 30 for second, etc.)
            user_id: User ID for access verification
            user: User context for access verification

        Returns:
            Tuple of (folders list, documents list, total_folder_count, total_document_count)
        """
        max_results = min(max_results, 30)
        offset = max(0, offset)

        with self.session_manager.get_pg_session() as session:
            index_orm = self._verify_index_access(session, index_id, user_id, user)

            is_glob = "*" in query or "?" in query
            is_recursive = "**" in query

            glob_info = self._parse_glob_pattern(query, is_glob, is_recursive)

            folders: list[Folder] = []
            documents: list[DocumentUnit] = []
            total_folder_count = 0
            total_document_count = 0

            if search_type != "document":
                folders, total_folder_count = self._search_folders_sql(
                    session,
                    index_orm,
                    glob_info,
                    max_results,
                    offset,
                    user_id=user_id,
                    user=user,
                )

            if search_type != "folder":
                remaining = max_results - (len(folders) if search_type is None else 0)
                if remaining > 0:
                    documents, total_document_count = self._search_documents_sql(
                        session,
                        index_orm,
                        glob_info,
                        remaining,
                        offset,
                        user_id=user_id,
                        user=user,
                    )

            return folders, documents, total_folder_count, total_document_count

    def _parse_glob_pattern(
        self, query: str, is_glob: bool, is_recursive: bool
    ) -> dict:
        """
        Parse glob pattern into SQL LIKE conditions.

        * matches within a single path segment (does not cross /)
        ** matches across path separators (recursive)
        """
        if not is_glob:
            search_lower = query.lower()
            return {
                "name_pattern": f"%{search_lower}%",
                "path_pattern": f"%{search_lower}%",
                "exclude_pattern": None,
                "is_glob": False,
            }

        if is_recursive:
            sql_pattern = query.replace("**", "___RECURSIVE___")
            sql_pattern = sql_pattern.replace("*", "%")
            sql_pattern = sql_pattern.replace("___RECURSIVE___", "%")
            sql_pattern = sql_pattern.replace("?", "_")
            exclude_pattern = None
        else:
            sql_pattern = query.replace("*", "%").replace("?", "_")
            exclude_pattern = query.replace("*", "%/%").replace("?", "_")

        return {
            "name_pattern": sql_pattern,
            "path_pattern": sql_pattern,
            "exclude_pattern": exclude_pattern,
            "is_glob": True,
            "is_recursive": is_recursive,
        }

    def _search_folders_sql(
        self,
        session: Session,
        index_orm: DocumentIndexORM,
        glob_info: dict,
        max_results: int,
        offset: int = 0,
        user_id: UUID | None = None,
        user: IdentityUserContext | None = None,
    ) -> tuple[list[Folder], int]:
        name_condition = FolderORM.name.ilike(glob_info["name_pattern"])
        path_condition = FolderORM.path.ilike(glob_info["path_pattern"])

        base_filter = and_(
            FolderORM.document_index_id == index_orm.id,
            or_(name_condition, path_condition),
        )

        if self._should_enforce_document_access(index_orm, user_id, user):
            base_filter = and_(
                base_filter,
                self._build_folder_access_exists_clause(
                    index_id=index_orm.id,
                    user_id=user_id,
                ),
            )

        exclude = glob_info.get("exclude_pattern")
        if exclude:
            base_filter = and_(base_filter, ~FolderORM.path.ilike(exclude))

        total_count = (
            session.query(func.count(FolderORM.id)).filter(base_filter).scalar() or 0
        )

        stmt = select(FolderORM).filter(base_filter).offset(offset).limit(max_results)

        folders = [folder_orm.to_domain() for folder_orm in session.scalars(stmt)]
        return folders, total_count

    def _search_documents_sql(
        self,
        session: Session,
        index_orm: DocumentIndexORM,
        glob_info: dict,
        max_results: int,
        offset: int = 0,
        user_id: UUID | None = None,
        user: IdentityUserContext | None = None,
    ) -> tuple[list[DocumentUnit], int]:
        filename_condition = DocumentUnitORM.filename.ilike(glob_info["name_pattern"])
        path_condition = DocumentUnitORM.path.ilike(glob_info["path_pattern"])

        base_filter = and_(
            DocumentUnitORM.document_index_id == index_orm.id,
            or_(filename_condition, path_condition),
        )

        if self._should_enforce_document_access(index_orm, user_id, user):
            base_filter = and_(
                base_filter,
                self._build_document_access_exists_clause(
                    document_id_column=DocumentUnitORM.id,
                    user_id=user_id,
                ),
            )

        exclude = glob_info.get("exclude_pattern")
        if exclude:
            base_filter = and_(base_filter, ~DocumentUnitORM.path.ilike(exclude))

        total_count = (
            session.query(func.count(DocumentUnitORM.id)).filter(base_filter).scalar()
            or 0
        )

        stmt = (
            select(DocumentUnitORM)
            .filter(base_filter)
            .offset(offset)
            .limit(max_results)
        )

        documents = [doc_orm.to_domain() for doc_orm in session.scalars(stmt)]
        return documents, total_count

    def update_document(
        self,
        document: DocumentUnit,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> DocumentUnit:
        if document.document_index_id is None:
            raise InvalidProjectConfigError(
                "document.document_index_id must be set when updating a document"
            )
        with self.session_manager.get_pg_session() as session:
            index_orm = self._verify_index_access(
                session, document.document_index_id, user_id, user
            )
            if document.integration_id != index_orm.source_integration_id:
                document.integration_id = index_orm.source_integration_id

            doc_orm = session.get(DocumentUnitORM, document.id)
            if not doc_orm:
                raise InvalidProjectConfigError(f"Document {document.id} not found")

            updated = DocumentUnitORM.from_domain(document)
            for key, value in updated.__dict__.items():
                if not key.startswith("_"):
                    setattr(doc_orm, key, value)

            session.flush()
            self._recalculate_index_stats(session, index_orm)
            session.refresh(doc_orm)
            return doc_orm.to_domain()

    def update_document_base(
        self,
        document: DocumentUnitBase,
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> DocumentUnitBase:
        if document.document_index_id is None:
            raise InvalidProjectConfigError(
                "document.document_index_id must be set when updating a document"
            )
        with self.session_manager.get_pg_session() as session:
            index_orm = self._verify_index_access(
                session, document.document_index_id, user_id, user
            )
            if document.integration_id != index_orm.source_integration_id:
                document.integration_id = index_orm.source_integration_id

            doc_orm = session.get(DocumentUnitORM, document.id)
            if not doc_orm:
                raise InvalidProjectConfigError(f"Document {document.id} not found")

            updated = DocumentUnitORM.from_base_domain(document)
            for key, value in updated.__dict__.items():
                if not key.startswith("_"):
                    setattr(doc_orm, key, value)

            session.flush()
            self._recalculate_index_stats(session, index_orm)
            session.refresh(doc_orm)
            return doc_orm.to_base_domain()

    def delete_document(
        self, document_id: UUID, user_id: UUID, user: IdentityUserContext | None = None
    ) -> None:
        with self.session_manager.get_pg_session() as session:
            doc_orm = session.get(DocumentUnitORM, document_id)
            if not doc_orm:
                return
            assert doc_orm.document_index_id
            index_orm = self._verify_index_access(
                session, doc_orm.document_index_id, user_id, user
            )
            session.delete(doc_orm)
            self._recalculate_index_stats(session, index_orm)
            session.flush()

    def delete_documents_by_external_ids(
        self,
        index_id: UUID,
        external_ids: list[str],
        user_id: UUID,
        user: IdentityUserContext | None = None,
    ) -> int:
        if not external_ids:
            return 0

        with self.session_manager.get_pg_session() as session:
            index_orm = self._verify_index_access(session, index_id, user_id, user)

            delete_stmt = (
                select(DocumentUnitORM)
                .filter(DocumentUnitORM.document_index_id == index_id)
                .filter(DocumentUnitORM.external_id.in_(external_ids))
            )
            docs = session.scalars(delete_stmt).all()
            deleted = len(docs)

            for doc in docs:
                session.delete(doc)

            self._recalculate_index_stats(session, index_orm)
            session.flush()
            return deleted

    def delete_documents_by_folder_ids_system(
        self,
        integration_id: UUID,
        folder_ids: list[UUID],
    ) -> int:
        if not folder_ids:
            return 0

        with self.session_manager.get_pg_session() as session:
            stmt = delete(DocumentUnitORM).where(
                DocumentUnitORM.integration_id == integration_id,
                DocumentUnitORM.folder_id.in_(folder_ids),
            )
            result = session.execute(stmt)
            return result.rowcount  # type: ignore[return-value]

    def update_index_stats(
        self, index_id: UUID, user_id: UUID, user: IdentityUserContext | None = None
    ) -> None:
        """Refresh doc_count, total_size and page_count stored on the index."""
        with self.session_manager.get_pg_session() as session:
            orm = self._verify_index_access(session, index_id, user_id, user)

            self._recalculate_index_stats(session, orm)
            session.flush()

    # --------------------------------------------------------------------- #
    # INTERNAL HELPERS                                                      #
    # --------------------------------------------------------------------- #

    def _assert_index_absent(
        self, session: Session, source_integration_id: UUID
    ) -> None:
        stmt = select(DocumentIndexORM).filter(
            DocumentIndexORM.source_integration_id == source_integration_id
        )
        if session.scalar(stmt):
            raise InvalidProjectConfigError(
                f"A document index already exists for source integration {source_integration_id}."
            )

    def _verify_index_access(
        self,
        session: Session,
        index_id: UUID,
        user_id: UUID | None,
        user: IdentityUserContext | None = None,
    ) -> DocumentIndexORM:
        stmt = select(DocumentIndexORM).filter(DocumentIndexORM.id == index_id)
        orm = session.scalar(stmt)
        if not orm:
            raise InvalidProjectConfigError(f"Document index {index_id} not found")

        source = self._get_source_integration(
            session,
            orm.source_integration_id,
            IntegrationType(orm.source_integration_type),
        )
        self._ensure_user_has_access(source, user_id, session, user)
        attachments = self._attach_existing_assets_to_index(session, orm)
        if attachments:
            self._recalculate_index_stats(session, orm)
        return orm

    def _should_enforce_document_access(
        self,
        index_orm: DocumentIndexORM,
        user_id: UUID | None,
        user: IdentityUserContext | None,
    ) -> bool:
        if user_id is None:
            return False
        if user and (user.is_admin or user.is_system):
            return False
        return index_orm.source_integration_type in {
            IntegrationType.SHAREPOINT.value,
            IntegrationType.ACC.value,
        }

    def _build_document_access_exists_clause(
        self,
        *,
        document_id_column,
        user_id: UUID | None,
    ):
        if user_id is None:
            raise ValueError("user_id is required when enforcing document access")

        return (
            select(DocumentUserAccessORM.document_id)
            .where(
                DocumentUserAccessORM.document_id == document_id_column,
                DocumentUserAccessORM.user_id == user_id,
            )
            .exists()
        )

    def _build_folder_access_exists_clause(
        self,
        *,
        index_id: UUID,
        user_id: UUID | None,
    ):
        if user_id is None:
            raise ValueError("user_id is required when enforcing folder access")

        return (
            select(DocumentUnitORM.id)
            .where(DocumentUnitORM.document_index_id == index_id)
            .where(
                or_(
                    DocumentUnitORM.folder_id == FolderORM.id,
                    DocumentUnitORM.path.like(func.concat(FolderORM.path, "/%")),
                )
            )
            .where(
                self._build_document_access_exists_clause(
                    document_id_column=DocumentUnitORM.id,
                    user_id=user_id,
                )
            )
            .exists()
        )

    def _user_has_document_access(
        self,
        *,
        session: Session,
        index_orm: DocumentIndexORM,
        document_id: UUID,
        user_id: UUID | None,
        user: IdentityUserContext | None,
    ) -> bool:
        if not self._should_enforce_document_access(index_orm, user_id, user):
            return True
        stmt = select(
            self._build_document_access_exists_clause(
                document_id_column=document_id,
                user_id=user_id,
            )
        )
        return bool(session.scalar(stmt))

    def _get_source_integration(
        self,
        session: Session,
        source_integration_id: UUID,
        source_type: IntegrationType,
    ):
        orm_cls_map = {
            IntegrationType.SHAREPOINT: SharePointMetadataORM,
            IntegrationType.ACC: AccMetadataORM,
        }
        orm_cls = orm_cls_map.get(source_type)
        if not orm_cls:
            raise InvalidProjectConfigError(
                f"Integration type {source_type} does not support document indexes"
            )

        source = session.get(orm_cls, source_integration_id)
        if not source:
            raise InvalidProjectConfigError(
                f"Source integration {source_integration_id} not found"
            )
        return source

    def _ensure_user_has_access(
        self,
        source_integration,
        user_id: UUID | None,
        session: Session,
        user: IdentityUserContext | None = None,
    ) -> None:
        if not self._user_has_access(source_integration, user_id, session, user):
            raise InsufficientPermissionsError(
                f"User {user_id or (user.id if user else 'unknown')} does not have access to integration {source_integration.id}"
            )

    def _user_has_access(
        self,
        source_integration,
        user_id: UUID | None,
        session: Session,
        user: IdentityUserContext | None = None,
    ) -> bool:
        permission_repo = PermissionRepository(self.session_manager)

        if user and (user.is_admin or user.is_system):
            return True

        effective_user_id = user.id if user else user_id
        if effective_user_id and source_integration.created_by == effective_user_id:
            return True

        if user:
            raw_perms = permission_repo.get_integration_permissions_for_groups(
                user.group_ids, source_integration.id
            )
            if raw_perms:
                return True

            project_ids = permission_repo.list_projects_for_groups(user.group_ids)
            if project_ids:
                linked_projects = {p.id for p in source_integration.project_omgevingen}
                if linked_projects.intersection(project_ids):
                    return True

        return False

    def _attach_existing_assets_to_index(
        self, session: Session, index_orm: DocumentIndexORM
    ) -> bool:
        """Ensure folders/documents discovered before index creation are linked to the index."""
        folder_updates = (
            session.query(FolderORM)
            .filter(FolderORM.integration_id == index_orm.source_integration_id)
            .filter(FolderORM.document_index_id.is_(None))
            .update(
                {"document_index_id": index_orm.id},
                synchronize_session=False,
            )
        )
        document_updates = (
            session.query(DocumentUnitORM)
            .filter(DocumentUnitORM.integration_id == index_orm.source_integration_id)
            .filter(DocumentUnitORM.document_index_id.is_(None))
            .update(
                {"document_index_id": index_orm.id},
                synchronize_session=False,
            )
        )
        if folder_updates or document_updates:
            session.flush()
            return True
        return False

    def _recalculate_index_stats(
        self, session: Session, index_orm: DocumentIndexORM
    ) -> None:
        """Recompute cached statistics for the index."""
        doc_count = (
            session.query(func.count(DocumentUnitORM.id))
            .filter(DocumentUnitORM.document_index_id == index_orm.id)
            .scalar()
        ) or 0

        total_size = (
            session.query(func.sum(DocumentUnitORM.size))
            .filter(DocumentUnitORM.document_index_id == index_orm.id)
            .scalar()
        ) or 0

        page_count = (
            session.query(func.sum(DocumentUnitORM.pages))
            .filter(DocumentUnitORM.document_index_id == index_orm.id)
            .scalar()
        ) or 0

        index_orm.doc_count = int(doc_count)
        index_orm.total_size = int(total_size)
        index_orm.page_count = int(page_count)
        index_orm.modified_at = datetime.now(timezone.utc)

    def _to_domain(
        self, orm: DocumentIndexORM, session: Session | None = None
    ) -> DocumentDatabaseIndex:
        domain = orm.to_domain()
        if session:
            folders_stmt = select(FolderORM).filter(
                FolderORM.document_index_id == orm.id
            )
            folders = [
                folder_orm.to_domain() for folder_orm in session.scalars(folders_stmt)
            ]
            if folders:
                domain.rebuild_folder_hierarchy(folders)
        return domain
