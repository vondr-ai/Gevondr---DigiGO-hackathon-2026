from __future__ import annotations

import asyncio
import sys
import types
from datetime import UTC
from datetime import datetime
from uuid import uuid4

from src.database.models import IndexRevisionORM
from src.database.models import IndexingJobORM
from src.database.models import ProjectAIConfigORM
from src.database.models import ProjectNormConfigORM
from src.database.models import ProjectORM
from src.database.models import StagedDocumentORM
from src.database.postgres.document_index_models import DocumentProcessingStatus
from src.database.postgres.document_index_models import DocumentUnit

if "pydantic_ai.models.google" not in sys.modules:
    google_models_module = types.ModuleType("pydantic_ai.models.google")
    google_models_module.GoogleModel = type("GoogleModel", (), {})
    sys.modules["pydantic_ai.models.google"] = google_models_module

if "pydantic_ai.providers.google" not in sys.modules:
    google_providers_module = types.ModuleType("pydantic_ai.providers.google")
    google_providers_module.GoogleProvider = type("GoogleProvider", (), {})
    sys.modules["pydantic_ai.providers.google"] = google_providers_module

from src.services import indexing_service


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeSession:
    def __init__(
        self,
        *,
        job: IndexingJobORM,
        project: ProjectORM,
        ai_config: ProjectAIConfigORM,
        norm_config: ProjectNormConfigORM,
        revision: IndexRevisionORM,
        staged_documents: list[StagedDocumentORM],
    ) -> None:
        self.job = job
        self.project = project
        self.ai_config = ai_config
        self.norm_config = norm_config
        self.revision = revision
        self.staged_documents = staged_documents
        self.commit_count = 0

    def get(self, model, _identifier):
        mapping = {
            IndexingJobORM: self.job,
            ProjectORM: self.project,
            ProjectAIConfigORM: self.ai_config,
            ProjectNormConfigORM: self.norm_config,
            IndexRevisionORM: self.revision,
        }
        return mapping.get(model)

    def scalar(self, _statement):
        return len(self.staged_documents)

    def scalars(self, _statement):
        return _ScalarResult(self.staged_documents)

    def commit(self) -> None:
        self.commit_count += 1


class _FakePipeline:
    active = 0
    max_active = 0
    received_instructions: list[str | None] = []

    def __init__(self, *, index, llm) -> None:
        self.index = index
        self.llm = llm

    async def process_document(self, *, document, local_path, indexing_instructions=None):
        type(self).active += 1
        type(self).max_active = max(type(self).max_active, type(self).active)
        type(self).received_instructions.append(indexing_instructions)
        try:
            await asyncio.sleep(0.01)
            return DocumentUnit(
                id=document.id,
                integration_id=document.integration_id,
                document_index_id=document.document_index_id,
                external_id=document.external_id,
                filename=document.filename,
                path=document.path,
                size=document.size,
                web_url=document.web_url,
                external_created_at=document.external_created_at,
                external_modified_at=document.external_modified_at,
                created_at=document.created_at,
                folder_id=document.folder_id,
                download_url=document.download_url,
                metadata=document.metadata,
                pages=1,
                processed_at=datetime.now(UTC),
                retry_count=document.retry_count,
                run_ocr=document.run_ocr,
                ocr_status=document.ocr_status,
                ocr_error_message=document.ocr_error_message,
                ocr_requested_at=document.ocr_requested_at,
                ocr_completed_at=document.ocr_completed_at,
                content_hash=document.content_hash,
                canonical_document_id=document.canonical_document_id,
                revision_group_id=document.revision_group_id,
                revision_rank=document.revision_rank,
                is_latest_revision=document.is_latest_revision,
                status=DocumentProcessingStatus.PROCESSED,
                full_text=f"text for {local_path}",
                short_summary=document.filename,
                summary=document.filename,
                document_type="Rapport",
                value_streams=["Registratie en administratie"],
                index_values=[],
                error_message=None,
            )
        finally:
            type(self).active -= 1


def test_run_indexing_job_processes_documents_in_batches_of_20(monkeypatch) -> None:
    project_id = uuid4()
    datasource_id = uuid4()
    revision_id = uuid4()
    job_id = uuid4()
    now = datetime.now(UTC)

    project = ProjectORM(
        id=project_id,
        name="Batch Test",
        description="Batch test project",
        status="draft",
        owner_party_id="owner",
        owner_party_name="Owner",
    )
    ai_config = ProjectAIConfigORM(
        project_id=project_id,
        provider="gemini",
        model="gemini-test",
        api_key="test-key",
    )
    norm_config = ProjectNormConfigORM(
        project_id=project_id,
        selected_norms=["NEN-1"],
        indexing_instructions="Gebruik projectcontext uit normselectie.",
    )
    revision = IndexRevisionORM(
        id=revision_id,
        project_id=project_id,
        datasource_id=datasource_id,
    )
    job = IndexingJobORM(
        id=job_id,
        project_id=project_id,
        datasource_id=datasource_id,
        index_revision_id=revision_id,
        mode="full",
        reindex=True,
        status="queued",
    )
    staged_documents = [
        StagedDocumentORM(
            id=uuid4(),
            datasource_id=datasource_id,
            project_id=project_id,
            folder_id=None,
            filename=f"document-{index}.pdf",
            path=f"/docs/document-{index}.pdf",
            storage_path=f"/tmp/document-{index}.pdf",
            size=100 + index,
            created_at=now,
            updated_at=now,
        )
        for index in range(25)
    ]
    session = _FakeSession(
        job=job,
        project=project,
        ai_config=ai_config,
        norm_config=norm_config,
        revision=revision,
        staged_documents=staged_documents,
    )

    persisted_documents: list[DocumentUnit] = []
    inserted_documents: list[DocumentUnit] = []
    cleaned_revisions: list[tuple] = []
    activated_revisions: list[tuple] = []

    class _FakeVectorRepo:
        def insert(self, *, documents, index_keys) -> None:
            _ = index_keys
            inserted_documents.extend(documents)

        def cleanup_other_revisions(self, project_id_arg, revision_id_arg) -> None:
            cleaned_revisions.append((project_id_arg, revision_id_arg))

    def _fake_persist(*args, **kwargs) -> None:
        _ = args
        persisted_documents.extend(kwargs["documents"])

    monkeypatch.setattr(
        indexing_service,
        "get_indexing_readiness_warnings",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        indexing_service,
        "_build_allowed_roles_map",
        lambda session_arg, project_id: {},
    )
    monkeypatch.setattr(indexing_service, "build_project_llm", lambda *args, **kwargs: object())
    monkeypatch.setattr(indexing_service, "DocumentIndexPipeline", _FakePipeline)
    monkeypatch.setattr(
        indexing_service,
        "VectorDocumentIndexRepository",
        _FakeVectorRepo,
    )
    monkeypatch.setattr(
        indexing_service,
        "_persist_indexed_documents",
        _fake_persist,
    )
    monkeypatch.setattr(
        indexing_service,
        "activate_index_revision",
        lambda session_arg, project_id_arg, revision_id_arg: activated_revisions.append(
            (session_arg, project_id_arg, revision_id_arg)
        ),
    )

    _FakePipeline.active = 0
    _FakePipeline.max_active = 0
    _FakePipeline.received_instructions = []

    result = asyncio.run(indexing_service.run_indexing_job(session, job_id))

    assert result.processed == 25
    assert result.failed == 0
    assert _FakePipeline.max_active == 20
    assert len(persisted_documents) == 25
    assert len(inserted_documents) == 25
    assert all(
        document.metadata and document.metadata["document_type"] == "Rapport"
        for document in inserted_documents
    )
    assert all(
        document.metadata
        and document.metadata["value_streams"] == ["Registratie en administratie"]
        for document in inserted_documents
    )
    assert _FakePipeline.received_instructions == [norm_config.indexing_instructions] * 25
    assert revision.document_count == 25
    assert job.total_files == 25
    assert job.indexed_files == 25
    assert job.failed_files == 0
    assert job.progress == 100
    assert job.status == "completed"
    assert session.commit_count == 4
    assert cleaned_revisions == [(project_id, str(revision_id))]
    assert activated_revisions == [(session, project_id, revision_id)]
