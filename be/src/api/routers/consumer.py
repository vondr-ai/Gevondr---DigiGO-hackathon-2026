from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.api.deps import require_consumer
from src.api.middleware.identity import IdentityUserContext
from src.database.models import IndexedDocumentORM
from src.database.models import ProjectORM
from src.database.session_manager import get_session_manager
from src.services.audit_service import record_event
from src.services.search_service import get_consumer_document
from src.services.search_service import list_consumer_projects
from src.services.search_service import resolve_consumer_role
from src.services.search_service import search_consumer_project

router = APIRouter(prefix="/consumer", tags=["consumer"])


class SearchRequest(BaseModel):
    query: str
    filters: dict | None = None
    page: int = 1
    pageSize: int = 20
    includeBlocked: bool = False


def _resolve_project_owner(session, project_id: UUID, fallback_owner: str) -> tuple[str, ProjectORM | None]:
    project = session.get(ProjectORM, project_id)
    if project is None:
        return fallback_owner, None
    return project.owner_party_id, project


@router.get("/projects")
def get_consumer_projects(
    identity: Annotated[IdentityUserContext, Depends(require_consumer)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        return {"items": list_consumer_projects(session, identity.party_id)}


@router.post("/projects/{project_id}/search")
def search_project(
    project_id: UUID,
    body: SearchRequest,
    identity: Annotated[IdentityUserContext, Depends(require_consumer)],
) -> dict:
    filters = body.filters or {}
    selected_norms = filters.get("norms")
    with get_session_manager().get_pg_session() as session:
        owner_party_id, project = _resolve_project_owner(session, project_id, identity.party_id)
        resolved_role = (
            resolve_consumer_role(
                session,
                project_id=project_id,
                consumer_party_id=identity.party_id,
            )
            if project is not None
            else None
        )
        try:
            result = search_consumer_project(
                session,
                project_id=project_id,
                consumer_party_id=identity.party_id,
                query=body.query,
                selected_norms=selected_norms,
                include_blocked=body.includeBlocked,
                page=body.page,
                page_size=body.pageSize,
            )
            record_event(
                session,
                owner_party_id=owner_party_id,
                project_id=project_id if project is not None else None,
                event_domain="search",
                event_action="execute",
                summary=f"Zoekopdracht uitgevoerd in project {project_id}.",
                actor=identity,
                target_party_id=identity.party_id,
                target_role_code=result.access_context.get("resolvedRole"),
                resource_type="project",
                resource_id=str(project_id),
                payload={
                    "query": body.query,
                    "filters": filters,
                    "page": body.page,
                    "pageSize": body.pageSize,
                    "includeBlocked": body.includeBlocked,
                    "totals": result.totals,
                },
            )
        except PermissionError as exc:
            record_event(
                session,
                owner_party_id=owner_party_id,
                project_id=project_id if project is not None else None,
                event_domain="search",
                event_action="execute",
                summary=f"Zoekopdracht geweigerd in project {project_id}.",
                actor=identity,
                target_party_id=identity.party_id,
                target_role_code=resolved_role,
                resource_type="project",
                resource_id=str(project_id),
                outcome="forbidden",
                payload={
                    "query": body.query,
                    "filters": filters,
                    "page": body.page,
                    "pageSize": body.pageSize,
                    "includeBlocked": body.includeBlocked,
                    "error": str(exc),
                },
            )
            session.commit()
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "forbidden", "message": str(exc)}},
            ) from exc
        except ValueError as exc:
            record_event(
                session,
                owner_party_id=owner_party_id,
                project_id=project_id if project is not None else None,
                event_domain="search",
                event_action="execute",
                summary=f"Zoekopdracht faalde voor project {project_id}.",
                actor=identity,
                target_party_id=identity.party_id,
                target_role_code=resolved_role,
                resource_type="project",
                resource_id=str(project_id),
                outcome="not_found",
                payload={
                    "query": body.query,
                    "filters": filters,
                    "page": body.page,
                    "pageSize": body.pageSize,
                    "includeBlocked": body.includeBlocked,
                    "error": str(exc),
                },
            )
            session.commit()
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": str(exc)}},
            ) from exc
        return {
            "accessContext": result.access_context,
            "results": result.results,
            "totals": result.totals,
        }


@router.get("/projects/{project_id}/documents/{document_id}/download")
def download_document(
    project_id: UUID,
    document_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_consumer)],
) -> FileResponse:
    with get_session_manager().get_pg_session() as session:
        owner_party_id, project = _resolve_project_owner(session, project_id, identity.party_id)
        resolved_role = (
            resolve_consumer_role(
                session,
                project_id=project_id,
                consumer_party_id=identity.party_id,
            )
            if project is not None
            else None
        )
        try:
            get_consumer_document(
                session,
                project_id=project_id,
                document_id=document_id,
                consumer_party_id=identity.party_id,
            )
        except PermissionError as exc:
            record_event(
                session,
                owner_party_id=owner_party_id,
                project_id=project_id if project is not None else None,
                event_domain="document",
                event_action="download",
                summary=f"Download geweigerd voor document {document_id}.",
                actor=identity,
                target_party_id=identity.party_id,
                target_role_code=resolved_role,
                resource_type="document",
                resource_id=str(document_id),
                outcome="forbidden",
                payload={"error": str(exc)},
            )
            session.commit()
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "forbidden", "message": str(exc)}},
            ) from exc
        document = session.get(IndexedDocumentORM, document_id)
        if document is None:
            record_event(
                session,
                owner_party_id=owner_party_id,
                project_id=project_id if project is not None else None,
                event_domain="document",
                event_action="download",
                summary=f"Document {document_id} niet gevonden voor download.",
                actor=identity,
                target_party_id=identity.party_id,
                target_role_code=resolved_role,
                resource_type="document",
                resource_id=str(document_id),
                outcome="not_found",
                payload={},
            )
            session.commit()
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": "Document not found."}},
            )
        record_event(
            session,
            owner_party_id=owner_party_id,
            project_id=project_id if project is not None else None,
            event_domain="document",
            event_action="download",
            summary=f"Document {document.title} gedownload.",
            actor=identity,
            target_party_id=identity.party_id,
            target_role_code=resolved_role,
            resource_type="document",
            resource_id=str(document_id),
            resource_path=document.path,
            payload={"title": document.title},
        )
        return FileResponse(document.storage_path, filename=document.title)


@router.get("/projects/{project_id}/documents/{document_id}")
def get_document(
    project_id: UUID,
    document_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_consumer)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        owner_party_id, project = _resolve_project_owner(session, project_id, identity.party_id)
        resolved_role = (
            resolve_consumer_role(
                session,
                project_id=project_id,
                consumer_party_id=identity.party_id,
            )
            if project is not None
            else None
        )
        try:
            payload = get_consumer_document(
                session,
                project_id=project_id,
                document_id=document_id,
                consumer_party_id=identity.party_id,
            )
            record_event(
                session,
                owner_party_id=owner_party_id,
                project_id=project_id if project is not None else None,
                event_domain="document",
                event_action="view",
                summary=f"Documentmetadata opgevraagd voor {document_id}.",
                actor=identity,
                target_party_id=identity.party_id,
                target_role_code=resolved_role,
                resource_type="document",
                resource_id=str(document_id),
                resource_path=payload["path"],
                payload={"title": payload["title"]},
            )
            return payload
        except PermissionError as exc:
            record_event(
                session,
                owner_party_id=owner_party_id,
                project_id=project_id if project is not None else None,
                event_domain="document",
                event_action="view",
                summary=f"Documenttoegang geweigerd voor {document_id}.",
                actor=identity,
                target_party_id=identity.party_id,
                target_role_code=resolved_role,
                resource_type="document",
                resource_id=str(document_id),
                outcome="forbidden",
                payload={"error": str(exc)},
            )
            session.commit()
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "forbidden", "message": str(exc)}},
            ) from exc
        except ValueError as exc:
            record_event(
                session,
                owner_party_id=owner_party_id,
                project_id=project_id if project is not None else None,
                event_domain="document",
                event_action="view",
                summary=f"Document {document_id} niet gevonden.",
                actor=identity,
                target_party_id=identity.party_id,
                target_role_code=resolved_role,
                resource_type="document",
                resource_id=str(document_id),
                outcome="not_found",
                payload={"error": str(exc)},
            )
            session.commit()
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": str(exc)}},
            ) from exc
