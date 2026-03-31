from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.postgres.connection.base import Base
from src.database.postgres.document_index_models import (
    DocumentProcessingStatus,
    DocumentUnit,
    DocumentUnitBase,
    IndexValue,
)
from src.database.postgres.py_models import OCRStatus

if TYPE_CHECKING:
    from src.database.postgres.models.document_index.document_index import (
        DocumentIndexORM,
    )
    from src.database.postgres.models.document_index.folder import FolderORM


class DocumentUnitORM(Base):
    """
    Represents a document in various stages of processing.
    Single table approach with nullable processed fields.
    """

    __tablename__ = "document_units"

    # === PRIMARY KEY ===
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)

    # === FOREIGN KEYS ===
    # Reference to source integration (SharePoint or VondrDocumentDB)
    # No FK constraint since it can point to different tables
    integration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    document_index_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_indexes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    folder_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    canonical_document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revision_group_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    revision_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_latest_revision: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # === ALWAYS PRESENT (filled at discovery) ===
    external_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    web_url: Mapped[str] = mapped_column(Text, nullable=False)
    external_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    external_modified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[DocumentProcessingStatus] = mapped_column(
        Enum(DocumentProcessingStatus), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # === OPTIONAL (filled at discovery) ===
    download_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # === FILLED AFTER PROCESSING ===
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    run_ocr: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    ocr_status: Mapped[OCRStatus] = mapped_column(
        Enum(OCRStatus),
        nullable=False,
        default=OCRStatus.NOT_REQUESTED,
        server_default=OCRStatus.NOT_REQUESTED.name,
        index=True,
    )
    ocr_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ocr_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # === METADATA (stored as JSONB) ===
    # IndexValues stored as list of dicts in JSONB
    index_values: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    # Note: renamed to doc_metadata to avoid conflict with SQLAlchemy's reserved 'metadata' attribute
    doc_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # === ERROR TRACKING ===
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # === RELATIONSHIPS ===
    folder: Mapped["FolderORM | None"] = relationship(back_populates="documents")
    document_index: Mapped["DocumentIndexORM | None"] = relationship(
        "DocumentIndexORM", back_populates="documents"
    )

    def to_domain(self) -> DocumentUnit:
        """Convert ORM model to domain model"""
        # Deserialize index_values from JSONB to list[IndexValue]
        index_values_list = (
            [IndexValue.from_serialized(iv) for iv in self.index_values]
            if self.index_values
            else None
        )

        return DocumentUnit(
            id=self.id,
            integration_id=self.integration_id,
            document_index_id=self.document_index_id,
            external_id=self.external_id,
            filename=self.filename,
            path=self.path,
            size=self.size,
            web_url=self.web_url,
            external_created_at=self.external_created_at,
            external_modified_at=self.external_modified_at,
            status=self.status,
            created_at=self.created_at,
            folder_id=self.folder_id,
            download_url=self.download_url,
            full_text=self.full_text,
            short_summary=self.short_summary,
            summary=self.summary,
            pages=self.pages,
            processed_at=self.processed_at,
            index_values=index_values_list,
            metadata=self.doc_metadata,
            error_message=self.error_message,
            retry_count=self.retry_count,
            run_ocr=self.run_ocr,
            ocr_status=self.ocr_status,
            ocr_error_message=self.ocr_error_message,
            ocr_requested_at=self.ocr_requested_at,
            ocr_completed_at=self.ocr_completed_at,
            content_hash=self.content_hash,
            canonical_document_id=self.canonical_document_id,
            revision_group_id=self.revision_group_id,
            revision_rank=self.revision_rank,
            is_latest_revision=self.is_latest_revision,
        )

    def to_base_domain(self) -> DocumentUnitBase:
        return DocumentUnitBase(
            id=self.id,
            integration_id=self.integration_id,
            document_index_id=self.document_index_id,
            external_id=self.external_id,
            filename=self.filename,
            path=self.path,
            size=self.size,
            web_url=self.web_url,
            external_created_at=self.external_created_at,
            external_modified_at=self.external_modified_at,
            status=self.status,
            created_at=self.created_at,
            folder_id=self.folder_id,
            download_url=self.download_url,
            metadata=self.doc_metadata,
            content_hash=self.content_hash,
            canonical_document_id=self.canonical_document_id,
            revision_group_id=self.revision_group_id,
            revision_rank=self.revision_rank,
            is_latest_revision=self.is_latest_revision,
            run_ocr=self.run_ocr,
            ocr_status=self.ocr_status,
            ocr_error_message=self.ocr_error_message,
            ocr_requested_at=self.ocr_requested_at,
            ocr_completed_at=self.ocr_completed_at,
        )

    @classmethod
    def from_base_domain(cls, doc: DocumentUnitBase) -> "DocumentUnitORM":
        """Create ORM model from base domain model (for queue insertion)"""
        return cls(
            id=doc.id,
            integration_id=doc.integration_id,
            document_index_id=doc.document_index_id,
            external_id=doc.external_id,
            filename=doc.filename,
            path=doc.path,
            size=doc.size,
            web_url=doc.web_url,
            external_created_at=doc.external_created_at,
            external_modified_at=doc.external_modified_at,
            status=doc.status,
            created_at=doc.created_at,
            folder_id=doc.folder_id,
            download_url=doc.download_url,
            pages=doc.pages,
            processed_at=doc.processed_at,
            content_hash=doc.content_hash,
            canonical_document_id=doc.canonical_document_id,
            revision_group_id=doc.revision_group_id,
            revision_rank=doc.revision_rank,
            is_latest_revision=doc.is_latest_revision,
            full_text=None,
            short_summary=None,
            summary=None,
            index_values=None,
            doc_metadata=doc.metadata,
            error_message=None,
            retry_count=0,
            run_ocr=doc.run_ocr,
            ocr_status=doc.ocr_status,
            ocr_error_message=doc.ocr_error_message,
            ocr_requested_at=doc.ocr_requested_at,
            ocr_completed_at=doc.ocr_completed_at,
        )

    @classmethod
    def from_domain(cls, doc: DocumentUnit) -> "DocumentUnitORM":
        """Create ORM model from domain model"""
        # Serialize index_values to JSONB-compatible format
        index_values_dict = (
            [iv.to_serializable_dict() for iv in doc.index_values]
            if doc.index_values
            else None
        )

        return cls(
            id=doc.id,
            integration_id=doc.integration_id,
            document_index_id=doc.document_index_id,
            external_id=doc.external_id,
            filename=doc.filename,
            path=doc.path,
            size=doc.size,
            web_url=doc.web_url,
            external_created_at=doc.external_created_at,
            external_modified_at=doc.external_modified_at,
            status=doc.status,
            created_at=doc.created_at,
            folder_id=doc.folder_id,
            download_url=doc.download_url,
            full_text=doc.full_text,
            short_summary=doc.short_summary,
            summary=doc.summary,
            pages=doc.pages,
            processed_at=doc.processed_at,
            index_values=index_values_dict,
            doc_metadata=doc.metadata,
            error_message=doc.error_message,
            retry_count=doc.retry_count,
            run_ocr=doc.run_ocr,
            ocr_status=doc.ocr_status,
            ocr_error_message=doc.ocr_error_message,
            ocr_requested_at=doc.ocr_requested_at,
            ocr_completed_at=doc.ocr_completed_at,
            content_hash=doc.content_hash,
            canonical_document_id=doc.canonical_document_id,
            revision_group_id=doc.revision_group_id,
            revision_rank=doc.revision_rank,
            is_latest_revision=doc.is_latest_revision,
        )
