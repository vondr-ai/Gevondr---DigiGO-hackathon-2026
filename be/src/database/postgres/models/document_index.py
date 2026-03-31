from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import func
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from src.database.postgres.connection.base import Base
from src.database.postgres.document_index_models import DocumentDatabaseIndex
from src.database.postgres.document_index_models import IndexKey
from src.database.postgres.py_models import IntegrationType

if TYPE_CHECKING:
    from src.database.postgres.models.document_index.document_unit import (
        DocumentUnitORM,
    )
    from src.database.postgres.models.document_index.folder import FolderORM


class DocumentIndexORM(Base):
    """ORM model representing a document index configuration."""

    __tablename__ = "document_indexes"
    __table_args__ = (
        UniqueConstraint(
            "source_integration_id",
            name="uq_document_indexes_source_integration",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    source_integration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    source_integration_type: Mapped[str] = mapped_column(String, nullable=False)

    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Identity service user ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    modified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    doc_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    keys: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Relationships
    folders: Mapped[list["FolderORM"]] = relationship(
        "FolderORM", back_populates="document_index", cascade="all, delete-orphan"
    )
    documents: Mapped[list["DocumentUnitORM"]] = relationship(
        "DocumentUnitORM", back_populates="document_index", cascade="all, delete-orphan"
    )

    def to_domain(self) -> DocumentDatabaseIndex:
        """Convert ORM instance to domain model."""
        structured_keys = (
            [IndexKey.from_dict(k) for k in self.keys] if self.keys else []
        )
        return DocumentDatabaseIndex(
            id=self.id,
            name=self.name,
            description=self.description,
            source_integration_id=self.source_integration_id,
            source_integration_type=IntegrationType(self.source_integration_type),
            created_by=self.created_by,
            created_at=self.created_at,
            modified_at=self.modified_at,
            last_synced_at=self.last_synced_at,
            doc_count=self.doc_count,
            size=self.total_size,
            page_count=self.page_count,
            keys=structured_keys,
            is_locked=self.is_locked,
        )

    def update_from_domain(self, index: DocumentDatabaseIndex) -> None:
        """Synchronize ORM fields from a domain model."""
        self.name = index.name
        self.description = index.description
        self.source_integration_id = index.source_integration_id
        self.source_integration_type = index.source_integration_type.value
        self.last_synced_at = index.last_synced_at
        self.doc_count = index.doc_count
        self.total_size = index.size
        self.page_count = index.page_count
        self.modified_at = index.modified_at
        self.is_locked = index.is_locked
        self.keys = [k.to_dict() for k in index.keys] if index.keys else None

    @classmethod
    def from_domain(cls, index: DocumentDatabaseIndex) -> "DocumentIndexORM":
        """Create ORM instance from domain model."""
        return cls(
            id=index.id,
            name=index.name,
            description=index.description,
            source_integration_id=index.source_integration_id,
            source_integration_type=index.source_integration_type.value,
            created_by=index.created_by,
            created_at=index.created_at,
            modified_at=index.modified_at,
            last_synced_at=index.last_synced_at,
            doc_count=index.doc_count,
            total_size=index.size,
            page_count=index.page_count,
            keys=[k.to_dict() for k in index.keys] if index.keys else None,
            is_locked=index.is_locked,
        )
