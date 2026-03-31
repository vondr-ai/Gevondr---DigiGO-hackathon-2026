from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from datetime import timezone
from typing import Optional
from uuid import UUID
from uuid import uuid4

from attrs import define
from sqlalchemy import select

from src.api.middleware.identity import IdentityUserContext
from src.database.exceptions import InsufficientPermissionsError
from src.database.exceptions import InvalidProjectConfigError
from src.database.postgres.document_index_models import DocumentConnection
from src.database.postgres.document_index_models import DocumentConnectionType
from src.database.postgres.repos.document_index_repository import (
    DocumentIndexRepository,
)
from src.database.postgres.models.document_connection import (
    DocumentConnectionORM,
)
from src.database.postgres.models.document_unit import DocumentUnitORM
from src.database.session_manager import get_session_manager
from src.database.session_manager import SessionManager


def get_document_connection_repo() -> "DocumentConnectionRepository":
    return DocumentConnectionRepository(get_session_manager())


@define
class DocumentConnectionRepository:
    """Repository for managing relationships between document units."""

    session_manager: SessionManager

    # ---- Query helpers -------------------------------------------------
    def list_connections(
        self,
        document_id: UUID,
        user_id: UUID,
        connection_types: Optional[Iterable[DocumentConnectionType]] = None,
        expected_index_id: Optional[UUID] = None,
        user: IdentityUserContext | None = None,
    ) -> list[DocumentConnection]:
        with self.session_manager.get_pg_session() as session:
            document = session.get(DocumentUnitORM, document_id)
            if not document:
                raise InvalidProjectConfigError(f"Document {document_id} not found")

            self._ensure_user_can_access_document(
                session, document, user_id, expected_index_id, user
            )

            stmt = select(DocumentConnectionORM).where(
                (DocumentConnectionORM.source_id == document_id)
                | (DocumentConnectionORM.target_id == document_id)
            )
            if connection_types:
                stmt = stmt.where(
                    DocumentConnectionORM.type.in_(list(connection_types))
                )

            connections = session.scalars(stmt).all()
            return [conn.to_domain() for conn in connections]

    def get_connection(
        self,
        connection_id: UUID,
        user_id: UUID,
        expected_index_id: Optional[UUID] = None,
        user: IdentityUserContext | None = None,
    ) -> DocumentConnection | None:
        with self.session_manager.get_pg_session() as session:
            connection = session.get(DocumentConnectionORM, connection_id)
            if not connection:
                return None

            document = session.get(DocumentUnitORM, connection.source_id)
            if not document:
                raise InvalidProjectConfigError(
                    f"Document {connection.source_id} referenced by connection missing"
                )

            self._ensure_user_can_access_document(
                session, document, user_id, expected_index_id, user
            )
            return connection.to_domain()

    # ---- Mutations -----------------------------------------------------
    def create_connection(
        self,
        connection: DocumentConnection,
        user_id: UUID,
        expected_index_id: Optional[UUID] = None,
        user: IdentityUserContext | None = None,
    ) -> DocumentConnection:
        with self.session_manager.get_pg_session() as session:
            source = session.get(DocumentUnitORM, connection.source_id)
            target = session.get(DocumentUnitORM, connection.target_id)

            if not source or not target:
                raise InvalidProjectConfigError("Source or target document not found")

            if connection.source_id == connection.target_id:
                raise InvalidProjectConfigError(
                    "Cannot create a connection referencing the same document"
                )

            if source.integration_id != target.integration_id:
                raise InvalidProjectConfigError(
                    "Documents must belong to the same integration to connect"
                )

            self._ensure_user_can_access_document(
                session, source, user_id, expected_index_id, user
            )
            self._ensure_user_can_access_document(
                session, target, user_id, expected_index_id, user
            )

            if (
                source.document_index_id
                and target.document_index_id
                and source.document_index_id != target.document_index_id
            ):
                raise InvalidProjectConfigError(
                    "Documents must belong to the same document index to connect"
                )

            # Avoid duplicate edges (same source, target, type)
            existing_stmt = select(DocumentConnectionORM).where(
                DocumentConnectionORM.source_id == connection.source_id,
                DocumentConnectionORM.target_id == connection.target_id,
                DocumentConnectionORM.type == connection.type,
            )
            existing = session.scalars(existing_stmt).first()
            if existing:
                # Update description and timestamps if user provided a new description
                if connection.description is not None:
                    existing.description = connection.description
                    existing.created_at = datetime.now(timezone.utc)
                    existing.created_by = user_id
                session.flush()
                session.refresh(existing)
                return existing.to_domain()

            orm = DocumentConnectionORM.from_domain(connection)
            session.add(orm)
            session.flush()
            session.refresh(orm)
            return orm.to_domain()

    def upsert_system_connection(
        self,
        source_id: UUID,
        target_id: UUID,
        connection_type: DocumentConnectionType,
        created_by: UUID,
        description: Optional[str] = None,
    ) -> DocumentConnection:
        """Create or update a connection generated by automated processes."""
        with self.session_manager.get_pg_session() as session:
            stmt = select(DocumentConnectionORM).where(
                DocumentConnectionORM.source_id == source_id,
                DocumentConnectionORM.target_id == target_id,
                DocumentConnectionORM.type == connection_type,
            )
            existing = session.scalars(stmt).first()
            if existing:
                if description is not None:
                    existing.description = description
                session.flush()
                session.refresh(existing)
                return existing.to_domain()

            now = datetime.now(timezone.utc)
            new_domain = DocumentConnection(
                id=uuid4(),
                source_id=source_id,
                target_id=target_id,
                type=connection_type,
                description=description,
                created_by=created_by,
                created_at=now,
            )
            orm = DocumentConnectionORM.from_domain(new_domain)
            session.add(orm)
            session.flush()
            session.refresh(orm)
            return orm.to_domain()

    def update_connection_description(
        self,
        connection_id: UUID,
        description: Optional[str],
        user_id: UUID,
        expected_index_id: Optional[UUID] = None,
        user: IdentityUserContext | None = None,
    ) -> DocumentConnection:
        with self.session_manager.get_pg_session() as session:
            connection = session.get(DocumentConnectionORM, connection_id)
            if not connection:
                raise InvalidProjectConfigError(f"Connection {connection_id} not found")

            source_doc = session.get(DocumentUnitORM, connection.source_id)
            if not source_doc:
                raise InvalidProjectConfigError(
                    f"Document {connection.source_id} referenced by connection missing"
                )
            self._ensure_user_can_access_document(
                session, source_doc, user_id, expected_index_id, user
            )

            connection.description = description
            connection.created_at = datetime.now(timezone.utc)
            connection.created_by = user_id
            session.flush()
            session.refresh(connection)
            return connection.to_domain()

    def delete_connection(
        self,
        connection_id: UUID,
        user_id: UUID,
        expected_index_id: Optional[UUID] = None,
        user: IdentityUserContext | None = None,
    ) -> bool:
        with self.session_manager.get_pg_session() as session:
            connection = session.get(DocumentConnectionORM, connection_id)
            if not connection:
                return False

            source_doc = session.get(DocumentUnitORM, connection.source_id)
            if not source_doc:
                raise InvalidProjectConfigError(
                    f"Document {connection.source_id} referenced by connection missing"
                )
            self._ensure_user_can_access_document(
                session, source_doc, user_id, expected_index_id, user
            )

            session.delete(connection)
            session.flush()
            return True

    # ---- Internal helpers ---------------------------------------------
    def _ensure_user_can_access_document(
        self,
        session,
        document: DocumentUnitORM,
        user_id: UUID,
        expected_index_id: Optional[UUID] = None,
        user: IdentityUserContext | None = None,
    ) -> None:
        if not document.document_index_id:
            raise InvalidProjectConfigError(
                f"Document {document.id} is not associated with a document index"
            )

        if expected_index_id and document.document_index_id != expected_index_id:
            raise InvalidProjectConfigError(
                f"Document {document.id} does not belong to index {expected_index_id}"
            )

        doc_index_repo = DocumentIndexRepository(self.session_manager)
        try:
            doc_index_repo._verify_index_access(  # type: ignore[attr-defined]
                session, document.document_index_id, user_id, user
            )
        except InsufficientPermissionsError as exc:
            raise InsufficientPermissionsError(
                f"User {user_id} does not have access to document {document.id}"
            ) from exc
