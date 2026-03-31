from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse

from src.api.deps import get_optional_identity
from src.api.middleware.identity import IdentityUserContext
from src.api.schemas.project_chat import ProjectChatStreamRequest
from src.database.models import IndexedDocumentORM
from src.database.models import ProjectAIConfigORM
from src.database.models import ProjectORM
from src.database.session_manager import get_session_manager
from src.services.project_chat.access import ProjectChatAccessError
from src.services.project_chat.access import ensure_document_open_access
from src.services.project_chat.access import resolve_project_chat_access
from src.services.project_chat.agent import build_message_history
from src.services.project_chat.agent import build_project_chat_agent
from src.services.project_chat.models import ProjectChatAgentDeps
from src.services.project_chat.retrieval import ProjectChatRetrievalService
from src.services.project_chat.streaming import stream_agent_markdown
from src.services.project_chat.telemetry import ProjectChatTelemetryState
from src.settings import settings

router = APIRouter(tags=["project-chat"])


@router.post("/projects/{project_id}/chat/stream")
async def stream_project_chat(
    project_id: UUID,
    body: ProjectChatStreamRequest,
    identity: Annotated[IdentityUserContext | None, Depends(get_optional_identity)],
) -> StreamingResponse:
    with get_session_manager().get_pg_session() as session:
        try:
            scope = resolve_project_chat_access(
                session,
                project_id=project_id,
                identity=identity,
            )
        except ProjectChatAccessError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "forbidden", "message": str(exc)}},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": str(exc)}},
            ) from exc

        project = session.get(ProjectORM, project_id)
        if project is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": "Project not found."}},
            )
        if project.active_index_revision_id is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "index_not_ready",
                        "message": "Project has no active index.",
                    }
                },
            )

        ai_config = session.get(ProjectAIConfigORM, project_id)
        provider = ai_config.provider if ai_config else "gemini"
        model_name = ai_config.model if ai_config else settings.gemini_model
        api_key = ai_config.api_key if ai_config else None
        deps = ProjectChatAgentDeps(
            project_id=project.id,
            project_name=project.name,
            project_description=project.description,
            active_revision=str(project.active_index_revision_id),
            access_scope=scope,
            selected_norms=list(body.filters.norms) if body.filters and body.filters.norms else [],
            include_document_ids=list(body.filters.document_ids)
            if body.filters and body.filters.document_ids
            else [],
            api_base_path=settings.api_base_path,
            session_factory=get_session_manager().get_pg_session,
            retrieval_service=ProjectChatRetrievalService(),
            telemetry_state=ProjectChatTelemetryState(),
            tool_event_notifier=None,
            retrieval_progress_notifier=None,
        )
        message_history = build_message_history(
            [message.model_dump() for message in body.messages[:-1]]
        )
        prompt = body.messages[-1].content
        agent = build_project_chat_agent(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
        )

    return StreamingResponse(
        stream_agent_markdown(
            agent=agent,
            prompt=prompt,
            deps=deps,
            message_history=message_history,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/projects/{project_id}/documents/{document_id}/open")
def open_project_document(
    project_id: UUID,
    document_id: UUID,
    identity: Annotated[IdentityUserContext | None, Depends(get_optional_identity)],
) -> FileResponse:
    with get_session_manager().get_pg_session() as session:
        try:
            scope = resolve_project_chat_access(
                session,
                project_id=project_id,
                identity=identity,
            )
        except ProjectChatAccessError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "forbidden", "message": str(exc)}},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": str(exc)}},
            ) from exc

        document = session.get(IndexedDocumentORM, document_id)
        if document is None or document.project_id != project_id:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": "Document not found."}},
            )

        try:
            ensure_document_open_access(scope, document=document)
        except ProjectChatAccessError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "forbidden", "message": str(exc)}},
            ) from exc

        return FileResponse(
            document.storage_path,
            filename=document.title,
            media_type=document.mime_type,
            content_disposition_type="inline",
        )
