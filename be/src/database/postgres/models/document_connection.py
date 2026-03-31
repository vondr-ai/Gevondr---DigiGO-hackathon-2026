from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.database.postgres.connection.base import Base
from src.database.postgres.document_index_models import DocumentConnection
from src.database.postgres.document_index_models import DocumentConnectionType


class DocumentConnectionORM(Base):
    """ORM model representing relationships between document units."""

    __tablename__ = "document_connections"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[DocumentConnectionType] = mapped_column(
        Enum(DocumentConnectionType),
        nullable=False,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def to_domain(self) -> DocumentConnection:
        return DocumentConnection(
            id=self.id,
            source_id=self.source_id,
            target_id=self.target_id,
            type=self.type,
            description=self.description,
            created_by=self.created_by,
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(cls, connection: DocumentConnection) -> "DocumentConnectionORM":
        return cls(
            id=connection.id,
            source_id=connection.source_id,
            target_id=connection.target_id,
            type=connection.type,
            description=connection.description,
            created_by=connection.created_by,
            created_at=connection.created_at,
        )
