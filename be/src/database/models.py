from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from uuid import UUID
from uuid import uuid4

from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from src.database.postgres.connection.base import Base
from src.settings import settings


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ProjectORM(Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    nen_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="draft")
    owner_party_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    owner_party_name: Mapped[str] = mapped_column(String(255), nullable=False)
    active_index_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("index_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    datasources: Mapped[list["DatasourceORM"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class DatasourceORM(Base):
    __tablename__ = "datasources"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="connected")
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    project: Mapped["ProjectORM"] = relationship(back_populates="datasources")
    staged_folders: Mapped[list["StagedFolderORM"]] = relationship(
        back_populates="datasource",
        cascade="all, delete-orphan",
    )
    staged_documents: Mapped[list["StagedDocumentORM"]] = relationship(
        back_populates="datasource",
        cascade="all, delete-orphan",
    )


class ProjectAIConfigORM(Base):
    __tablename__ = "project_ai_configs"

    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="gemini")
    model: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default=settings.gemini_model,
    )
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class ProjectNormConfigORM(Base):
    __tablename__ = "project_norm_configs"

    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    selected_norms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    indexing_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class StagedFolderORM(Base):
    __tablename__ = "staged_folders"
    __table_args__ = (
        UniqueConstraint("datasource_id", "path", name="uq_staged_folders_datasource_path"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    datasource_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("datasources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("staged_folders.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utcnow,
        onupdate=utcnow,
    )

    datasource: Mapped["DatasourceORM"] = relationship(back_populates="staged_folders")
    parent: Mapped["StagedFolderORM | None"] = relationship(
        remote_side=[id],
        back_populates="children",
    )
    children: Mapped[list["StagedFolderORM"]] = relationship(back_populates="parent")


class StagedDocumentORM(Base):
    __tablename__ = "staged_documents"
    __table_args__ = (
        UniqueConstraint("datasource_id", "path", name="uq_staged_documents_datasource_path"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    datasource_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("datasources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    folder_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("staged_folders.id", ondelete="SET NULL"),
        nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="ready")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=utcnow,
        onupdate=utcnow,
    )

    datasource: Mapped["DatasourceORM"] = relationship(back_populates="staged_documents")


class AccessMatrixEntryORM(Base):
    __tablename__ = "access_matrix_entries"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_code: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    allow_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)


class DelegationORM(Base):
    __tablename__ = "delegations"
    __table_args__ = (
        UniqueConstraint("project_id", "role_code", "party_id", name="uq_delegations_project_role_party"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_code: Mapped[str] = mapped_column(String(255), nullable=False)
    party_id: Mapped[str] = mapped_column(String(255), nullable=False)
    party_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)


class IndexRevisionORM(Base):
    __tablename__ = "index_revisions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    datasource_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("datasources.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="building")
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))


class IndexingJobORM(Base):
    __tablename__ = "indexing_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    datasource_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("datasources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    index_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("index_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    queue_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="full")
    reindex: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)


class IndexedDocumentORM(Base):
    __tablename__ = "indexed_documents"
    __table_args__ = (
        UniqueConstraint("project_id", "index_revision_id", "path", name="uq_indexed_documents_revision_path"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    datasource_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("datasources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    staged_document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("staged_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    index_revision_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("index_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="processed")
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    value_streams: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    index_values: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    doc_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selected_norms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_role_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=utcnow)


class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=utcnow,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=lambda: utcnow() + timedelta(days=settings.audit_retention_days),
    )
    owner_party_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    project_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    datasource_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("datasources.id", ondelete="SET NULL"),
        nullable=True,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("indexing_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_party_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    actor_party_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_token_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_party_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    target_role_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resource_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
