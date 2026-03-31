from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from itertools import batched
from uuid import UUID
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import AccessMatrixEntryORM
from src.database.models import DatasourceORM
from src.database.models import DelegationORM
from src.database.models import IndexedDocumentORM
from src.database.models import IndexingJobORM
from src.database.models import IndexRevisionORM
from src.database.models import ProjectAIConfigORM
from src.database.models import ProjectNormConfigORM
from src.database.models import ProjectORM
from src.database.models import StagedDocumentORM
from src.database.postgres.document_index_models import DocumentDatabaseIndex
from src.database.postgres.document_index_models import DocumentProcessingStatus
from src.database.postgres.document_index_models import DocumentUnit
from src.database.postgres.document_index_models import DocumentUnitBase
from src.database.postgres.py_models import IntegrationType
from src.database.weaviate.repos.document_index_repo import VectorDocumentIndexRepository
from src.services.document_database.pipeline.index_pipeline import DocumentIndexPipeline
from src.services.llm_runtime import build_project_llm
from src.settings import settings

INDEXING_BATCH_SIZE = 20


@dataclass(slots=True)
class IndexingRunResult:
    processed: int
    failed: int


def get_indexing_readiness_warnings(
    *,
    ai_config: ProjectAIConfigORM | None,
    norm_config: ProjectNormConfigORM | None,
    staged_file_count: int,
) -> list[str]:
    warnings: list[str] = []
    if staged_file_count == 0:
        warnings.append("No staged documents available.")
    if ai_config is None:
        warnings.append("AI config is missing.")
    else:
        if ai_config.provider.lower().strip() != "gemini":
            warnings.append("Only the Gemini AI provider is supported in v1.")
        if not ai_config.model.strip():
            warnings.append("Gemini model is missing.")
        if not (ai_config.api_key or settings.gemini_api_key):
            warnings.append("Gemini API key is missing.")
    if not settings.jina_api_key:
        warnings.append("Jina API key is missing.")
    if norm_config is None or not norm_config.selected_norms:
        warnings.append("No norms selected.")
    return warnings


def get_ready_summary(session: Session, project_id: UUID) -> dict:
    project = session.get(ProjectORM, project_id)
    if project is None:
        raise ValueError("Project not found")
    datasources = session.scalars(
        select(DatasourceORM).where(DatasourceORM.project_id == project_id)
    ).all()
    norm_config = session.get(ProjectNormConfigORM, project_id)
    ai_config = session.get(ProjectAIConfigORM, project_id)
    staged_file_count = session.scalar(
        select(func.count())
        .select_from(StagedDocumentORM)
        .where(StagedDocumentORM.project_id == project_id)
    ) or 0
    delegation_count = session.scalar(
        select(func.count()).select_from(DelegationORM).where(
            DelegationORM.project_id == project_id
        )
    )
    warnings = get_indexing_readiness_warnings(
        ai_config=ai_config,
        norm_config=norm_config,
        staged_file_count=staged_file_count,
    )
    ready = not warnings
    return {
        "project": {"id": str(project.id), "name": project.name, "status": project.status},
        "datasources": [
            {
                "id": str(datasource.id),
                "type": datasource.type,
                "status": datasource.status,
                "displayName": datasource.display_name,
            }
            for datasource in datasources
        ],
        "norms": {
            "selectedNorms": norm_config.selected_norms if norm_config else [],
            "instructions": norm_config.indexing_instructions if norm_config else None,
        },
        "delegations": {"count": delegation_count or 0},
        "accessMatrix": {
            "count": session.scalar(
                select(func.count()).select_from(AccessMatrixEntryORM).where(
                    AccessMatrixEntryORM.project_id == project_id
                )
            )
            or 0
        },
        "readyToStart": ready,
        "warnings": warnings,
    }


def create_indexing_job(
    session: Session,
    *,
    project_id: UUID,
    datasource_id: UUID | None,
    mode: str,
    reindex: bool,
) -> IndexingJobORM:
    revision = IndexRevisionORM(project_id=project_id, datasource_id=datasource_id)
    session.add(revision)
    session.flush()
    job = IndexingJobORM(
        project_id=project_id,
        datasource_id=datasource_id,
        index_revision_id=revision.id,
        mode=mode,
        reindex=reindex,
        status="queued",
    )
    session.add(job)
    session.flush()
    return job


async def run_indexing_job(session: Session, job_id: UUID) -> IndexingRunResult:
    job = session.get(IndexingJobORM, job_id)
    if job is None:
        raise ValueError("Indexing job not found")
    project = session.get(ProjectORM, job.project_id)
    if project is None:
        raise ValueError("Project not found")
    ai_config = session.get(ProjectAIConfigORM, project.id)
    norm_config = session.get(ProjectNormConfigORM, project.id)
    warnings = get_indexing_readiness_warnings(
        ai_config=ai_config,
        norm_config=norm_config,
        staged_file_count=session.scalar(
            select(func.count())
            .select_from(StagedDocumentORM)
            .where(StagedDocumentORM.project_id == project.id)
        )
        or 0,
    )
    if warnings:
        raise ValueError("; ".join(warnings))
    assert ai_config is not None
    assert norm_config is not None
    indexing_instructions = norm_config.indexing_instructions

    staged_documents = session.scalars(
        select(StagedDocumentORM)
        .where(StagedDocumentORM.project_id == project.id)
        .order_by(StagedDocumentORM.path)
    ).all()

    job.status = "running"
    job.started_at = datetime.utcnow()
    job.total_files = len(staged_documents)
    session.commit()

    index_definition = DocumentDatabaseIndex(
        id=job.index_revision_id or uuid4(),
        name=project.name,
        description=project.description or project.name,
        source_integration_id=job.datasource_id or uuid4(),
        source_integration_type=IntegrationType.UPLOAD,
        created_by=project.id,
        created_at=datetime.utcnow(),
        modified_at=datetime.utcnow(),
        keys=[],
    )
    llm = build_project_llm(
        ai_config.provider,
        ai_config.model,
        api_key=ai_config.api_key,
    )
    pipeline = DocumentIndexPipeline(index=index_definition, llm=llm)
    vector_repo = VectorDocumentIndexRepository()

    allowed_roles_by_path = _build_allowed_roles_map(
        session,
        project_id=project.id,
    )

    processed_documents: list[DocumentUnit] = []
    failed_count = 0
    for staged_batch in batched(staged_documents, INDEXING_BATCH_SIZE):
        batch_results = await asyncio.gather(
            *[
                _process_staged_document(
                    staged=staged,
                    project_id=project.id,
                    datasource_id=job.datasource_id,
                    revision_id=job.index_revision_id,
                    selected_norms=norm_config.selected_norms,
                    indexing_instructions=indexing_instructions,
                    allowed_roles_by_path=allowed_roles_by_path,
                    pipeline=pipeline,
                )
                for staged in staged_batch
            ]
        )
        processed_documents.extend(batch_results)
        failed_count += sum(
            1
            for document in batch_results
            if document.status == DocumentProcessingStatus.FAILED
        )
        job.indexed_files = len(processed_documents) - failed_count
        job.failed_files = failed_count
        job.progress = int((len(processed_documents) / max(1, job.total_files)) * 100)
        session.commit()

    _persist_indexed_documents(
        session,
        project_id=project.id,
        datasource_id=job.datasource_id,
        revision_id=job.index_revision_id,
        norm_config=norm_config,
        documents=processed_documents,
    )
    searchable_documents = [
        document
        for document in processed_documents
        if document.status != DocumentProcessingStatus.FAILED
    ]
    revision = session.get(IndexRevisionORM, job.index_revision_id) if job.index_revision_id else None
    if not searchable_documents:
        raise ValueError("No documents were indexed successfully.")
    vector_repo.insert(
        documents=searchable_documents,
        index_keys=index_definition.keys,
    )
    if revision is not None:
        revision.document_count = len(searchable_documents)
    activate_index_revision(session, project.id, job.index_revision_id)
    vector_repo.cleanup_other_revisions(project.id, str(job.index_revision_id))

    job.status = "completed"
    job.finished_at = datetime.utcnow()
    job.progress = 100
    job.warnings = (
        [f"{failed_count} document(s) failed during indexing."]
        if failed_count
        else []
    )
    session.commit()
    return IndexingRunResult(
        processed=len(processed_documents) - failed_count,
        failed=failed_count,
    )


def activate_index_revision(session: Session, project_id: UUID, revision_id: UUID | None) -> None:
    if revision_id is None:
        return
    session.execute(
        select(IndexRevisionORM).where(IndexRevisionORM.project_id == project_id)
    )
    revisions = session.scalars(
        select(IndexRevisionORM).where(IndexRevisionORM.project_id == project_id)
    ).all()
    for revision in revisions:
        if revision.id == revision_id:
            revision.status = "active"
            revision.activated_at = datetime.utcnow()
        elif revision.status == "active":
            revision.status = "superseded"
            revision.superseded_at = datetime.utcnow()
    project = session.get(ProjectORM, project_id)
    if project:
        project.active_index_revision_id = revision_id


def _persist_indexed_documents(
    session: Session,
    *,
    project_id: UUID,
    datasource_id: UUID | None,
    revision_id: UUID | None,
    norm_config: ProjectNormConfigORM,
    documents: list[DocumentUnit],
) -> None:
    if revision_id is None or datasource_id is None:
        return
    for document in documents:
        row = IndexedDocumentORM(
            project_id=project_id,
            datasource_id=datasource_id,
            id=document.id,
            staged_document_id=UUID(document.external_id),
            index_revision_id=revision_id,
            title=document.filename,
            path=document.path,
            storage_path=str((document.metadata or {}).get("storage_path", document.path)),
            mime_type=None,
            size=document.size,
            pages=document.pages,
            status=document.status.value,
            full_text=document.full_text,
            summary=document.summary,
            short_summary=document.short_summary,
            document_type=document.document_type,
            value_streams=document.value_streams or [],
            index_values=[
                value.to_serializable_dict() for value in (document.index_values or [])
            ],
            doc_metadata=document.metadata or {},
            selected_norms=norm_config.selected_norms,
            allowed_role_codes=list(
                (document.metadata or {}).get("allowed_role_codes", [])
            ),
            error_message=document.error_message,
        )
        session.add(row)


async def _process_staged_document(
    *,
    staged: StagedDocumentORM,
    project_id: UUID,
    datasource_id: UUID | None,
    revision_id: UUID | None,
    selected_norms: list[str],
    indexing_instructions: str | None,
    allowed_roles_by_path: dict[str, list[str]],
    pipeline: DocumentIndexPipeline,
) -> DocumentUnit:
    base_document = DocumentUnitBase(
        id=uuid4(),
        integration_id=datasource_id or UUID(int=0),
        document_index_id=revision_id,
        external_id=str(staged.id),
        filename=staged.filename,
        path=staged.path,
        size=staged.size,
        web_url=staged.path,
        folder_id=staged.folder_id,
        external_created_at=staged.created_at,
        external_modified_at=staged.updated_at,
        status=DocumentProcessingStatus.NOT_PROCESSED,
        metadata={
            "project_id": str(project_id),
            "datasource_id": str(staged.datasource_id),
            "selected_norms": selected_norms,
            "allowed_role_codes": allowed_roles_by_path.get(staged.path, []),
            "index_revision": str(revision_id),
            "title": staged.filename,
            "path": staged.path,
            "storage_path": staged.storage_path,
        },
    )
    try:
        processed = await pipeline.process_document(
            document=base_document,
            local_path=staged.storage_path,
            indexing_instructions=indexing_instructions,
        )
        if processed is None:
            raise ValueError("Pipeline returned no document")
        if processed.metadata:
            processed.metadata["document_type"] = processed.document_type or ""
            processed.metadata["value_streams"] = processed.value_streams or []
        return processed
    except Exception as exc:
        return DocumentUnit(
            id=base_document.id,
            integration_id=base_document.integration_id,
            document_index_id=base_document.document_index_id,
            external_id=base_document.external_id,
            filename=base_document.filename,
            path=base_document.path,
            size=base_document.size,
            web_url=base_document.web_url,
            external_created_at=base_document.external_created_at,
            external_modified_at=base_document.external_modified_at,
            status=DocumentProcessingStatus.FAILED,
            created_at=base_document.created_at,
            folder_id=base_document.folder_id,
            download_url=base_document.download_url,
            metadata=base_document.metadata,
            pages=None,
            processed_at=datetime.utcnow(),
            retry_count=base_document.retry_count,
            run_ocr=base_document.run_ocr,
            ocr_status=base_document.ocr_status,
            ocr_error_message=base_document.ocr_error_message,
            ocr_requested_at=base_document.ocr_requested_at,
            ocr_completed_at=base_document.ocr_completed_at,
            content_hash=base_document.content_hash,
            canonical_document_id=base_document.canonical_document_id,
            revision_group_id=base_document.revision_group_id,
            revision_rank=base_document.revision_rank,
            is_latest_revision=base_document.is_latest_revision,
            full_text=None,
            short_summary=None,
            summary=None,
            index_values=[],
            error_message=str(exc),
        )


def _build_allowed_roles_map(session: Session, *, project_id: UUID) -> dict[str, list[str]]:
    entries = session.scalars(
        select(AccessMatrixEntryORM).where(AccessMatrixEntryORM.project_id == project_id)
    ).all()
    documents = session.scalars(
        select(StagedDocumentORM).where(StagedDocumentORM.project_id == project_id)
    ).all()
    grouped: dict[str, list[str]] = {}
    for document in documents:
        roles: list[str] = []
        for entry in entries:
            if not entry.allow_read:
                continue
            if entry.resource_type == "file" and entry.path == document.path:
                roles.append(entry.role_code)
            elif entry.resource_type == "folder" and (
                not entry.path
                or document.path == entry.path
                or document.path.startswith(entry.path.rstrip("/") + "/")
            ):
                roles.append(entry.role_code)
        grouped[document.path] = sorted(set(roles))
    return grouped
