from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import select

from src.api.deps import ensure_project_owner
from src.api.deps import require_provider
from src.api.middleware.identity import IdentityUserContext
from src.database.models import AccessMatrixEntryORM
from src.database.models import DatasourceORM
from src.database.models import DelegationORM
from src.database.models import IndexedDocumentORM
from src.database.models import IndexingJobORM
from src.database.models import ProjectAIConfigORM
from src.database.models import ProjectNormConfigORM
from src.database.models import ProjectORM
from src.database.models import StagedDocumentORM
from src.database.models import StagedFolderORM
from src.database.session_manager import get_session_manager
from src.services.audit_service import build_async_audit_context
from src.services.audit_service import compute_set_diff
from src.services.audit_service import record_event
from src.services.audit_service import record_many
from src.services.indexing_service import create_indexing_job
from src.services.indexing_service import get_ready_summary
from src.services.indexing_service import get_indexing_readiness_warnings
from src.services.job_queue import enqueue_task
from src.services.participant_registry import registry
from src.services.staging_service import build_datasource_tree
from src.services.storage import save_upload_bytes
from src.settings import settings

router = APIRouter(tags=["projects"])
SUPPORTED_AI_PROVIDER = "gemini"


class ProjectCreateRequest(BaseModel):
    name: str
    description: str | None = None
    nenLabel: str | None = None
    status: str = "draft"


class ProjectPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class DatasourceCreateRequest(BaseModel):
    type: str
    config: dict = {}


class DiscoverRequest(BaseModel):
    rootPath: str | None = None


class AIConfigRequest(BaseModel):
    provider: str
    model: str
    apiKey: str | None = None
    chunking: dict


class NormConfigRequest(BaseModel):
    selectedNorms: list[str]
    indexingInstructions: str | None = None


def _serialize_indexing_job(job: IndexingJobORM) -> dict:
    return {
        "jobId": str(job.id),
        "status": job.status,
        "progress": job.progress,
        "totalFiles": job.total_files,
        "indexedFiles": job.indexed_files,
        "failedFiles": job.failed_files,
        "startedAt": job.started_at.isoformat() if job.started_at else None,
        "finishedAt": job.finished_at.isoformat() if job.finished_at else None,
        "errorMessage": job.error_message,
    }


def _get_latest_indexing_job(
    session,
    project_id: UUID,
    *,
    statuses: tuple[str, ...] | None = None,
) -> IndexingJobORM | None:
    statement = select(IndexingJobORM).where(IndexingJobORM.project_id == project_id)
    if statuses:
        statement = statement.where(IndexingJobORM.status.in_(statuses))
    statement = statement.order_by(IndexingJobORM.created_at.desc())
    return session.scalars(statement).first()


class AccessMatrixEntryRequest(BaseModel):
    roleCode: str
    resourceType: str
    resourceId: str
    path: str
    allowRead: bool


class AccessMatrixPutRequest(BaseModel):
    entries: list[AccessMatrixEntryRequest]


class DelegationRequest(BaseModel):
    roleCode: str
    partyId: str


class DelegationsPutRequest(BaseModel):
    items: list[DelegationRequest]


class IndexingStartRequest(BaseModel):
    mode: str = "full"
    reindex: bool = True


def _mask_api_key(api_key: str | None) -> bool:
    return bool(api_key)


def _get_project_or_404(project_id: UUID) -> ProjectORM:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": "Project not found."}},
            )
        session.expunge(project)
        return project


def _serialize_access_matrix_items(items: list[AccessMatrixEntryORM | AccessMatrixEntryRequest]) -> list[dict]:
    serialized: list[dict] = []
    for item in items:
        serialized.append(
            {
                "roleCode": item.role_code if isinstance(item, AccessMatrixEntryORM) else item.roleCode,
                "resourceType": item.resource_type if isinstance(item, AccessMatrixEntryORM) else item.resourceType,
                "resourceId": item.resource_id if isinstance(item, AccessMatrixEntryORM) else item.resourceId,
                "path": item.path,
                "allowRead": item.allow_read if isinstance(item, AccessMatrixEntryORM) else item.allowRead,
            }
        )
    return serialized


def _serialize_delegation_items(items: list[DelegationORM]) -> list[dict]:
    return [
        {
            "roleCode": item.role_code,
            "partyId": item.party_id,
            "partyName": item.party_name,
        }
        for item in items
    ]


@router.get("/projects")
def list_projects(
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        projects = session.scalars(
            select(ProjectORM).where(ProjectORM.owner_party_id == identity.party_id)
        ).all()
        items = []
        for project in projects:
            file_count = session.scalar(
                select(func.count()).select_from(StagedDocumentORM).where(
                    StagedDocumentORM.project_id == project.id
                )
            ) or 0
            norm_count = 0
            norm_config = session.get(ProjectNormConfigORM, project.id)
            if norm_config:
                norm_count = len(norm_config.selected_norms)
            datasource_count = session.scalar(
                select(func.count()).select_from(DatasourceORM).where(
                    DatasourceORM.project_id == project.id
                )
            ) or 0
            last_indexed_at = session.scalar(
                select(func.max(IndexedDocumentORM.indexed_at)).where(
                    IndexedDocumentORM.project_id == project.id
                )
            )
            items.append(
                {
                    "id": str(project.id),
                    "name": project.name,
                    "status": project.status,
                    "fileCount": file_count,
                    "normCount": norm_count,
                    "datasourceCount": datasource_count,
                    "lastIndexedAt": last_indexed_at.isoformat() if last_indexed_at else None,
                }
            )
        return {"items": items}


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectCreateRequest,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = ProjectORM(
            name=body.name,
            description=body.description,
            nen_label=body.nenLabel,
            status=body.status,
            owner_party_id=identity.party_id,
            owner_party_name=identity.party_name,
        )
        session.add(project)
        session.flush()
        record_event(
            session,
            owner_party_id=project.owner_party_id,
            project_id=project.id,
            event_domain="project",
            event_action="create",
            summary=f"Project {project.name} aangemaakt.",
            actor=identity,
            resource_type="project",
            resource_id=str(project.id),
            payload={
                "after": {
                    "name": project.name,
                    "description": project.description,
                    "nenLabel": project.nen_label,
                    "status": project.status,
                }
            },
        )
        return {
            "id": str(project.id),
            "name": project.name,
            "status": project.status,
            "ownerPartyId": project.owner_party_id,
        }


@router.get("/projects/{project_id}")
def get_project(
    project_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        files = session.scalar(
            select(func.count()).select_from(StagedDocumentORM).where(
                StagedDocumentORM.project_id == project.id
            )
        ) or 0
        indexed = session.scalar(
            select(func.count()).select_from(IndexedDocumentORM).where(
                IndexedDocumentORM.project_id == project.id,
                IndexedDocumentORM.index_revision_id == project.active_index_revision_id,
            )
        ) or 0
        return {
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "ownerPartyId": project.owner_party_id,
            "stats": {"files": files, "indexedFiles": indexed},
        }


@router.patch("/projects/{project_id}")
def patch_project(
    project_id: UUID,
    body: ProjectPatchRequest,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        before = {
            "name": project.name,
            "description": project.description,
            "status": project.status,
        }
        if body.name is not None:
            project.name = body.name
        if body.description is not None:
            project.description = body.description
        if body.status is not None:
            project.status = body.status
        project.updated_at = datetime.utcnow()
        record_event(
            session,
            owner_party_id=project.owner_party_id,
            project_id=project.id,
            event_domain="project",
            event_action="update",
            summary=f"Project {project.name} bijgewerkt.",
            actor=identity,
            resource_type="project",
            resource_id=str(project.id),
            payload={
                "before": before,
                "after": {
                    "name": project.name,
                    "description": project.description,
                    "status": project.status,
                },
            },
        )
        return {"id": str(project.id), "name": project.name, "status": project.status}


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> None:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        record_event(
            session,
            owner_party_id=project.owner_party_id,
            project_id=project.id,
            event_domain="project",
            event_action="delete",
            summary=f"Project {project.name} verwijderd.",
            actor=identity,
            resource_type="project",
            resource_id=str(project.id),
        )
        session.delete(project)


@router.get("/projects/{project_id}/datasources")
def list_datasources(
    project_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        items = session.scalars(
            select(DatasourceORM).where(DatasourceORM.project_id == project_id)
        ).all()
        return {
            "items": [
                {
                    "id": str(item.id),
                    "type": item.type,
                    "status": item.status,
                    "displayName": item.display_name,
                    "lastSyncAt": item.last_sync_at.isoformat() if item.last_sync_at else None,
                }
                for item in items
            ]
        }


@router.post("/projects/{project_id}/datasources", status_code=201)
def create_datasource(
    project_id: UUID,
    body: DatasourceCreateRequest,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    if body.type != "upload":
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "unsupported", "message": "Only upload datasources are supported in v1."}},
        )
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        datasource = DatasourceORM(
            project_id=project.id,
            type=body.type,
            status="connected",
            display_name=body.config.get("displayName", "Upload datasource"),
            config=body.config,
        )
        session.add(datasource)
        session.flush()
        record_event(
            session,
            owner_party_id=project.owner_party_id,
            project_id=project.id,
            datasource_id=datasource.id,
            event_domain="datasource",
            event_action="create",
            summary=f"Datasource {datasource.display_name} aangemaakt.",
            actor=identity,
            resource_type="datasource",
            resource_id=str(datasource.id),
            payload={"type": datasource.type, "config": datasource.config},
        )
        return {
            "id": str(datasource.id),
            "type": datasource.type,
            "status": datasource.status,
            "configMasked": datasource.config,
        }


@router.post("/projects/{project_id}/datasources/{datasource_id}/discover", status_code=202)
async def discover_datasource(
    project_id: UUID,
    datasource_id: UUID,
    body: DiscoverRequest,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        datasource = session.get(DatasourceORM, datasource_id)
        if project is None or datasource is None or datasource.project_id != project_id:
            raise HTTPException(status_code=404, detail="Datasource not found")
        ensure_project_owner(identity, project.owner_party_id)
        datasource.status = "discovering"
        audit_context = build_async_audit_context(identity)
        record_event(
            session,
            owner_party_id=project.owner_party_id,
            project_id=project.id,
            datasource_id=datasource.id,
            event_domain="datasource",
            event_action="discover_started",
            summary=f"Discover gestart voor datasource {datasource.display_name}.",
            actor=identity,
            resource_type="datasource",
            resource_id=str(datasource.id),
            payload={
                "rootPath": body.rootPath,
                "correlationId": audit_context["correlationId"],
            },
        )
    job_id = await enqueue_task(
        "discover_datasource_tree",
        str(datasource_id),
        body.rootPath,
        audit_context=audit_context,
    )
    return {"jobId": job_id, "status": "discovering"}


@router.get("/projects/{project_id}/datasources/{datasource_id}/tree")
def get_datasource_tree(
    project_id: UUID,
    datasource_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        datasource = session.get(DatasourceORM, datasource_id)
        if project is None or datasource is None or datasource.project_id != project.id:
            raise HTTPException(status_code=404, detail="Datasource not found")
        ensure_project_owner(identity, project.owner_party_id)
        folders = session.scalars(
            select(StagedFolderORM)
            .where(StagedFolderORM.datasource_id == datasource_id)
            .order_by(StagedFolderORM.path)
        ).all()
        documents = session.scalars(
            select(StagedDocumentORM)
            .where(StagedDocumentORM.datasource_id == datasource_id)
            .order_by(StagedDocumentORM.path)
        ).all()
        return build_datasource_tree(folders, documents)


@router.post("/projects/{project_id}/datasources/{datasource_id}/uploads", status_code=201)
async def upload_documents(
    project_id: UUID,
    datasource_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
    files: Annotated[list[UploadFile], File()],
    relativePaths: Annotated[list[str] | None, Form()] = None,
    targetPath: Annotated[str, Form()] = "",
) -> dict:
    uploaded: list[dict] = []
    audit_events: list[dict] = []
    if relativePaths is not None and len(relativePaths) != len(files):
        raise HTTPException(status_code=400, detail="Relative paths do not match uploaded files")
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        datasource = session.get(DatasourceORM, datasource_id)
        if project is None or datasource is None or datasource.project_id != project.id:
            raise HTTPException(status_code=404, detail="Datasource not found")
        ensure_project_owner(identity, project.owner_party_id)
        for index, file in enumerate(files):
            content = await file.read()
            source_path = (relativePaths[index] if relativePaths is not None else file.filename) or "upload.bin"
            normalized_source_path = source_path.replace("\\", "/").strip("/")
            relative_path = "/".join(
                part for part in [targetPath.strip("/"), normalized_source_path] if part
            )
            filename = Path(normalized_source_path).name or Path(file.filename or source_path).name
            stored_path, sha256, mime_type = save_upload_bytes(
                project_id=project_id,
                datasource_id=datasource_id,
                relative_path=relative_path,
                content=content,
            )
            staged_document = session.scalars(
                select(StagedDocumentORM).where(
                    StagedDocumentORM.datasource_id == datasource_id,
                    StagedDocumentORM.path == relative_path,
                )
            ).first()
            action = "update" if staged_document is not None else "create"
            if staged_document is None:
                staged_document = StagedDocumentORM(
                    datasource_id=datasource_id,
                    project_id=project_id,
                    folder_id=None,
                    filename=filename or stored_path.name,
                    path=relative_path,
                    storage_path=str(stored_path.resolve()),
                    mime_type=mime_type,
                    size=len(content),
                    sha256=sha256,
                    status="uploaded",
                )
                session.add(staged_document)
            else:
                staged_document.filename = filename or stored_path.name
                staged_document.storage_path = str(stored_path.resolve())
                staged_document.mime_type = mime_type
                staged_document.size = len(content)
                staged_document.sha256 = sha256
                staged_document.status = "uploaded"
            session.flush()
            uploaded.append(
                {
                    "documentId": str(staged_document.id),
                    "fileName": staged_document.filename,
                    "size": staged_document.size,
                    "path": staged_document.path,
                }
            )
            audit_events.append(
                {
                    "owner_party_id": project.owner_party_id,
                    "project_id": project.id,
                    "datasource_id": datasource.id,
                    "event_domain": "document",
                    "event_action": action,
                    "summary": f"Document {staged_document.filename} geupload.",
                    "actor": identity,
                    "resource_type": "document",
                    "resource_id": str(staged_document.id),
                    "resource_path": staged_document.path,
                    "payload": {
                        "fileName": staged_document.filename,
                        "mimeType": staged_document.mime_type,
                        "size": staged_document.size,
                        "targetPath": targetPath,
                    },
                }
            )
        record_many(session, events=audit_events)
        audit_context = build_async_audit_context(identity)
        record_event(
            session,
            owner_party_id=project.owner_party_id,
            project_id=project.id,
            datasource_id=datasource.id,
            event_domain="document",
            event_action="upload_batch",
            summary=f"{len(uploaded)} document(en) geupload.",
            actor=identity,
            resource_type="datasource",
            resource_id=str(datasource.id),
            payload={
                "uploadedCount": len(uploaded),
                "documents": uploaded,
                "correlationId": audit_context["correlationId"],
            },
        )
    await enqueue_task(
        "sync_staging_documents",
        str(datasource_id),
        audit_context=audit_context,
    )
    return {"uploaded": uploaded}


@router.get("/projects/{project_id}/ai-config")
def get_ai_config(
    project_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        config = session.get(ProjectAIConfigORM, project_id)
        has_env_key = False
        try:
            has_env_key = bool(settings.gemini_api_key)
        except Exception:
            pass
        if config is None:
            return {
                "provider": SUPPORTED_AI_PROVIDER,
                "model": settings.gemini_model,
                "apiKeySet": has_env_key,
                "chunking": {"size": 800, "overlap": 120},
            }
        return {
            "provider": config.provider,
            "model": config.model,
            "apiKeySet": bool(_mask_api_key(config.api_key)) or has_env_key,
            "chunking": {"size": config.chunk_size, "overlap": config.chunk_overlap},
        }


@router.put("/projects/{project_id}/ai-config")
def put_ai_config(
    project_id: UUID,
    body: AIConfigRequest,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    if body.provider.lower().strip() != SUPPORTED_AI_PROVIDER:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "unsupported",
                    "message": "Only the Gemini AI provider is supported in v1.",
                }
            },
        )
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        config = session.get(ProjectAIConfigORM, project_id)
        if config is None:
            config = ProjectAIConfigORM(project_id=project_id)
            session.add(config)
        config.provider = SUPPORTED_AI_PROVIDER
        config.model = body.model
        config.api_key = body.apiKey
        config.chunk_size = int(body.chunking.get("size", 800))
        config.chunk_overlap = int(body.chunking.get("overlap", 120))
        config.updated_at = datetime.utcnow()
        has_env_key = False
        try:
            has_env_key = bool(settings.gemini_api_key)
        except Exception:
            pass
        return {
            "provider": config.provider,
            "model": config.model,
            "apiKeySet": bool(_mask_api_key(config.api_key)) or has_env_key,
            "updatedAt": config.updated_at.isoformat(),
        }


@router.put("/projects/{project_id}/norms")
def put_norms(
    project_id: UUID,
    body: NormConfigRequest,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        config = session.get(ProjectNormConfigORM, project_id)
        if config is None:
            config = ProjectNormConfigORM(project_id=project_id)
            session.add(config)
        config.selected_norms = body.selectedNorms
        config.indexing_instructions = body.indexingInstructions
        config.updated_at = datetime.utcnow()
        return {
            "selectedNorms": config.selected_norms,
            "instructionsPreview": (config.indexing_instructions or "")[:200],
        }


@router.get("/projects/{project_id}/roles/access-matrix")
def get_access_matrix(
    project_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        entries = session.scalars(
            select(AccessMatrixEntryORM).where(AccessMatrixEntryORM.project_id == project_id)
        ).all()
        return {
            "entries": [
                {
                    "roleCode": entry.role_code,
                    "resourceType": entry.resource_type,
                    "resourceId": entry.resource_id,
                    "path": entry.path,
                    "allowRead": entry.allow_read,
                    "inherited": entry.resource_type == "folder",
                }
                for entry in entries
            ]
        }


@router.put("/projects/{project_id}/roles/access-matrix")
def put_access_matrix(
    project_id: UUID,
    body: AccessMatrixPutRequest,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        before_entries = session.scalars(
            select(AccessMatrixEntryORM).where(AccessMatrixEntryORM.project_id == project_id)
        ).all()
        before_serialized = _serialize_access_matrix_items(before_entries)
        after_serialized = _serialize_access_matrix_items(body.entries)
        diff = compute_set_diff(
            before_serialized,
            after_serialized,
            keys=("roleCode", "resourceType", "resourceId", "path", "allowRead"),
        )
        session.query(AccessMatrixEntryORM).filter(
            AccessMatrixEntryORM.project_id == project_id
        ).delete()
        for item in body.entries:
            session.add(
                AccessMatrixEntryORM(
                    project_id=project_id,
                    role_code=item.roleCode,
                    resource_type=item.resourceType,
                    resource_id=item.resourceId,
                    path=item.path,
                    allow_read=item.allowRead,
                )
            )
        access_events: list[dict] = []
        for added in diff["added"]:
            access_events.append(
                {
                    "owner_party_id": project.owner_party_id,
                    "project_id": project.id,
                    "event_domain": "access_matrix",
                    "event_action": "grant" if added["allowRead"] else "deny",
                    "summary": f"Toegangsregel voor rol {added['roleCode']} opgeslagen.",
                    "actor": identity,
                    "target_role_code": added["roleCode"],
                    "resource_type": added["resourceType"],
                    "resource_id": added["resourceId"],
                    "resource_path": added["path"],
                    "payload": {"entry": added},
                }
            )
        for removed in diff["removed"]:
            access_events.append(
                {
                    "owner_party_id": project.owner_party_id,
                    "project_id": project.id,
                    "event_domain": "access_matrix",
                    "event_action": "revoke",
                    "summary": f"Toegangsregel voor rol {removed['roleCode']} verwijderd.",
                    "actor": identity,
                    "target_role_code": removed["roleCode"],
                    "resource_type": removed["resourceType"],
                    "resource_id": removed["resourceId"],
                    "resource_path": removed["path"],
                    "payload": {"entry": removed},
                }
            )
        record_many(session, events=access_events)
        record_event(
            session,
            owner_party_id=project.owner_party_id,
            project_id=project.id,
            event_domain="access_matrix",
            event_action="replace",
            summary="Access matrix vervangen.",
            actor=identity,
            resource_type="project",
            resource_id=str(project.id),
            payload={"before": before_serialized, "after": after_serialized, "diff": diff},
        )
        return {
            "updatedCount": len(body.entries),
            "documentAclVersion": datetime.utcnow().isoformat(),
        }


@router.get("/projects/{project_id}/delegations")
def get_delegations(
    project_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        items = session.scalars(
            select(DelegationORM).where(DelegationORM.project_id == project_id)
        ).all()
        return {
            "items": [
                {
                    "roleCode": item.role_code,
                    "partyId": item.party_id,
                    "partyName": item.party_name,
                }
                for item in items
            ]
        }


@router.put("/projects/{project_id}/delegations")
def put_delegations(
    project_id: UUID,
    body: DelegationsPutRequest,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        before_items = session.scalars(
            select(DelegationORM).where(DelegationORM.project_id == project_id)
        ).all()
        before_serialized = _serialize_delegation_items(before_items)
        session.query(DelegationORM).filter(DelegationORM.project_id == project_id).delete()
        session.flush()
        saved = []
        for item in body.items:
            participant = registry.get_participant(item.partyId)
            if participant is None:
                raise HTTPException(
                    status_code=400,
                    detail={"error": {"code": "invalid_participant", "message": f"Unknown participant {item.partyId}."}},
                )
            delegation = DelegationORM(
                project_id=project_id,
                role_code=item.roleCode,
                party_id=participant.party_id,
                party_name=participant.name,
            )
            session.add(delegation)
            saved.append(
                {
                    "roleCode": delegation.role_code,
                    "partyId": delegation.party_id,
                    "partyName": delegation.party_name,
                }
            )
        diff = compute_set_diff(
            before_serialized,
            saved,
            keys=("roleCode", "partyId"),
        )
        delegation_events: list[dict] = []
        for added in diff["added"]:
            delegation_events.append(
                {
                    "owner_party_id": project.owner_party_id,
                    "project_id": project.id,
                    "event_domain": "delegation",
                    "event_action": "assign",
                    "summary": f"Rol {added['roleCode']} toegewezen aan {added['partyName']}.",
                    "actor": identity,
                    "target_party_id": added["partyId"],
                    "target_role_code": added["roleCode"],
                    "resource_type": "project",
                    "resource_id": str(project.id),
                    "payload": {"delegation": added},
                }
            )
        for removed in diff["removed"]:
            delegation_events.append(
                {
                    "owner_party_id": project.owner_party_id,
                    "project_id": project.id,
                    "event_domain": "delegation",
                    "event_action": "revoke",
                    "summary": f"Rol {removed['roleCode']} weggehaald bij {removed['partyName']}.",
                    "actor": identity,
                    "target_party_id": removed["partyId"],
                    "target_role_code": removed["roleCode"],
                    "resource_type": "project",
                    "resource_id": str(project.id),
                    "payload": {"delegation": removed},
                }
            )
        record_many(session, events=delegation_events)
        record_event(
            session,
            owner_party_id=project.owner_party_id,
            project_id=project.id,
            event_domain="delegation",
            event_action="replace",
            summary="Delegaties vervangen.",
            actor=identity,
            resource_type="project",
            resource_id=str(project.id),
            payload={"before": before_serialized, "after": saved, "diff": diff},
        )
        return {"items": saved, "validation": {"allParticipantsExist": True}}


@router.get("/projects/{project_id}/indexing/summary")
def get_indexing_summary(
    project_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        return get_ready_summary(session, project_id)


@router.post("/projects/{project_id}/indexing-jobs", status_code=202)
async def start_indexing_job(
    project_id: UUID,
    body: IndexingStartRequest,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    job_id: UUID | None = None
    audit_context: dict | None = None
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        active_job = _get_latest_indexing_job(
            session,
            project_id,
            statuses=("queued", "running"),
        )
        if active_job is not None:
            return _serialize_indexing_job(active_job)
        datasource = session.scalars(
            select(DatasourceORM).where(DatasourceORM.project_id == project_id)
        ).first()
        if datasource is None:
            raise HTTPException(status_code=400, detail="No datasource configured")
        warnings = get_indexing_readiness_warnings(
            ai_config=session.get(ProjectAIConfigORM, project_id),
            norm_config=session.get(ProjectNormConfigORM, project_id),
            staged_file_count=session.scalar(
                select(func.count())
                .select_from(StagedDocumentORM)
                .where(StagedDocumentORM.project_id == project_id)
            )
            or 0,
        )
        if warnings:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "indexing_not_ready",
                        "message": "Project staging/config is not ready for indexing.",
                        "warnings": warnings,
                    }
                },
            )
        job = create_indexing_job(
            session,
            project_id=project_id,
            datasource_id=datasource.id,
            mode=body.mode,
            reindex=body.reindex,
        )
        audit_context = build_async_audit_context(identity)
        record_event(
            session,
            owner_party_id=project.owner_party_id,
            project_id=project.id,
            datasource_id=datasource.id,
            job_id=job.id,
            event_domain="indexing",
            event_action="requested",
            summary=f"Indexing job {job.id} aangevraagd.",
            actor=identity,
            resource_type="indexing_job",
            resource_id=str(job.id),
            payload={
                "mode": body.mode,
                "reindex": body.reindex,
                "correlationId": audit_context["correlationId"],
            },
        )
        job_id = job.id
    assert job_id is not None
    assert audit_context is not None
    queue_job_id = await enqueue_task(
        "run_indexing_job",
        str(job_id),
        audit_context=audit_context,
    )
    with get_session_manager().get_pg_session() as session:
        queued_job = session.get(IndexingJobORM, job_id)
        if queued_job is not None:
            queued_job.queue_job_id = queue_job_id
            return _serialize_indexing_job(queued_job)
    return {"jobId": str(job_id), "status": "queued"}


@router.get("/projects/{project_id}/indexing-jobs/latest")
def get_latest_indexing_job(
    project_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ensure_project_owner(identity, project.owner_party_id)
        job = _get_latest_indexing_job(session, project_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _serialize_indexing_job(job)


@router.get("/projects/{project_id}/indexing-jobs/{job_id}")
def get_indexing_job(
    project_id: UUID,
    job_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, project_id)
        job = session.get(IndexingJobORM, job_id)
        if project is None or job is None or job.project_id != project.id:
            raise HTTPException(status_code=404, detail="Job not found")
        ensure_project_owner(identity, project.owner_party_id)
        return _serialize_indexing_job(job)
