from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import JSON
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from src.database.postgres.connection.base import Base
from src.database.postgres.document_index_models import Folder

if TYPE_CHECKING:
    from src.database.postgres.models.document_index.document_index import (
        DocumentIndexORM,
    )
    from src.database.postgres.models.document_index.document_unit import (
        DocumentUnitORM,
    )


class FolderORM(Base):
    """Represents a folder in the document database hierarchy"""

    __tablename__ = "folders"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    external_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    # Reference to source integration (SharePoint or VondrDocumentDB)
    # No FK constraint since it can point to different tables
    integration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    document_index_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_indexes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Self-referential foreign key for parent folder
    parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Optional fields
    web_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Note: renamed to folder_metadata to avoid conflict with SQLAlchemy's reserved 'metadata' attribute
    folder_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    modified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Relationships
    parent: Mapped["FolderORM | None"] = relationship(
        "FolderORM", remote_side=[id], back_populates="children"
    )
    children: Mapped[list["FolderORM"]] = relationship(
        "FolderORM", back_populates="parent"
    )
    documents: Mapped[list["DocumentUnitORM"]] = relationship(
        "DocumentUnitORM", back_populates="folder"
    )
    document_index: Mapped["DocumentIndexORM | None"] = relationship(
        "DocumentIndexORM", back_populates="folders"
    )

    def to_domain(self) -> Folder:
        """Convert ORM model to domain model"""
        return Folder(
            id=self.id,
            external_id=self.external_id,
            name=self.name,
            path=self.path,
            integration_id=self.integration_id,
            document_index_id=self.document_index_id,
            parent_id=self.parent_id,
            web_url=self.web_url,
            metadata=self.folder_metadata,
            created_at=self.created_at,
            modified_at=self.modified_at,
        )

    @classmethod
    def from_domain(cls, folder: Folder) -> "FolderORM":
        """Create ORM model from domain model"""
        return cls(
            id=folder.id,
            external_id=folder.external_id,
            name=folder.name,
            path=folder.path,
            integration_id=folder.integration_id,
            document_index_id=folder.document_index_id,
            parent_id=folder.parent_id,
            web_url=folder.web_url,
            folder_metadata=folder.metadata,
            created_at=folder.created_at,
            modified_at=folder.modified_at,
        )
