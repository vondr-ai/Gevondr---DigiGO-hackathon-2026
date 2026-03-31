from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query

from src.api.deps import require_audit_reader
from src.api.middleware.identity import IdentityUserContext
from src.database.session_manager import get_session_manager
from src.services.audit_service import get_event
from src.services.audit_service import list_events

router = APIRouter(tags=["audit"])


@router.get("/audit-logs")
def get_audit_logs(
    identity: Annotated[IdentityUserContext, Depends(require_audit_reader)],
    projectId: UUID | None = Query(default=None),
    actorPartyId: str | None = Query(default=None),
    targetPartyId: str | None = Query(default=None),
    eventDomain: str | None = Query(default=None),
    eventAction: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=200),
) -> dict:
    with get_session_manager().get_pg_session() as session:
        try:
            result = list_events(
                session,
                identity=identity,
                project_id=projectId,
                actor_party_id=actorPartyId,
                target_party_id=targetPartyId,
                event_domain=eventDomain,
                event_action=eventAction,
                date_from=from_,
                date_to=to,
                page=page,
                page_size=pageSize,
            )
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "forbidden", "message": str(exc)}},
            ) from exc
        return {
            "items": result.items,
            "page": result.page,
            "pageSize": result.page_size,
            "total": result.total,
        }


@router.get("/audit-logs/{event_id}")
def get_audit_log_detail(
    event_id: UUID,
    identity: Annotated[IdentityUserContext, Depends(require_audit_reader)],
) -> dict:
    with get_session_manager().get_pg_session() as session:
        try:
            item = get_event(session, identity=identity, event_id=event_id)
        except PermissionError as exc:
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "forbidden", "message": str(exc)}},
            ) from exc
        if item is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": "Audit event not found."}},
            )
        return item
