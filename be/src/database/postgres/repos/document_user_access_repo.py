from __future__ import annotations

import logging
from uuid import UUID

from attrs import define
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.database.postgres.models.document_index.document_unit import DocumentUnitORM
from src.database.postgres.models.document_user_access import DocumentUserAccessORM
from src.database.postgres.py_models import DocumentUserAccess
from src.database.session_manager import get_session_manager
from src.database.session_manager import SessionManager

logger = logging.getLogger(__name__)


@define
class DocumentUserAccessRepository:
    """Repository for managing document-user access records."""

    session_manager: SessionManager

    def bulk_upsert(self, records: list[DocumentUserAccess]) -> int:
        """Insert access records, skipping duplicates. Returns count inserted."""
        if not records:
            return 0

        with self.session_manager.get_pg_session() as session:
            stmt = insert(DocumentUserAccessORM).values(
                [
                    {
                        "id": r.id,
                        "document_id": r.document_id,
                        "user_id": r.user_id,
                    }
                    for r in records
                ]
            )
            stmt = stmt.on_conflict_do_nothing(constraint="uq_document_user_access")
            result = session.execute(stmt)
            return result.rowcount  # type: ignore[return-value]

    def get_accessible_document_ids(
        self, user_id: UUID, integration_id: UUID
    ) -> set[UUID]:
        """Get all document IDs that a user has access to within an integration."""
        with self.session_manager.get_pg_session() as session:
            stmt = (
                select(DocumentUserAccessORM.document_id)
                .join(
                    DocumentUnitORM,
                    DocumentUnitORM.id == DocumentUserAccessORM.document_id,
                )
                .where(
                    DocumentUserAccessORM.user_id == user_id,
                    DocumentUnitORM.integration_id == integration_id,
                )
            )
            return set(session.scalars(stmt).all())

    def delete_by_user_and_documents(
        self, user_id: UUID, document_ids: list[UUID]
    ) -> int:
        """Delete access records for a user and specific documents."""
        if not document_ids:
            return 0

        with self.session_manager.get_pg_session() as session:
            stmt = delete(DocumentUserAccessORM).where(
                DocumentUserAccessORM.user_id == user_id,
                DocumentUserAccessORM.document_id.in_(document_ids),
            )
            result = session.execute(stmt)
            return result.rowcount  # type: ignore[return-value]

    def delete_by_document_id(self, document_id: UUID) -> int:
        """Delete all access records for a document (cascade cleanup)."""
        with self.session_manager.get_pg_session() as session:
            stmt = delete(DocumentUserAccessORM).where(
                DocumentUserAccessORM.document_id == document_id,
            )
            result = session.execute(stmt)
            return result.rowcount  # type: ignore[return-value]


def get_document_user_access_repo() -> DocumentUserAccessRepository:
    return DocumentUserAccessRepository(get_session_manager())
