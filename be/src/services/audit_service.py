from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any
from uuid import UUID
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.middleware.identity import IdentityUserContext
from src.database.models import AuditLogORM
from src.settings import settings


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(slots=True)
class AuditListResult:
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


def actor_snapshot_from_identity(identity: IdentityUserContext | None) -> dict[str, Any]:
    if identity is None:
        return {
            "actorType": "system",
            "partyId": None,
            "partyName": None,
            "tokenId": None,
            "auditAdmin": False,
        }
    return {
        "actorType": identity.actor_type,
        "partyId": identity.party_id,
        "partyName": identity.party_name,
        "tokenId": identity.token_id,
        "auditAdmin": identity.is_audit_admin,
    }


def build_async_audit_context(
    identity: IdentityUserContext | None,
    *,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "actor": actor_snapshot_from_identity(identity),
        "correlationId": correlation_id or str(uuid4()),
        "source": "worker",
    }


def ensure_can_read_audit_logs(identity: IdentityUserContext) -> None:
    if not identity.is_provider:
        raise PermissionError("Audit log access requires a provider session.")


def record_event(
    session: Session,
    *,
    owner_party_id: str,
    event_domain: str,
    event_action: str,
    summary: str,
    actor: IdentityUserContext | dict[str, Any] | None = None,
    project_id: UUID | None = None,
    datasource_id: UUID | None = None,
    job_id: UUID | None = None,
    target_party_id: str | None = None,
    target_role_code: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    resource_path: str | None = None,
    outcome: str = "success",
    source: str = "api",
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> AuditLogORM:
    actor_snapshot = _normalize_actor(actor)
    event_time = occurred_at or utcnow()
    row = AuditLogORM(
        owner_party_id=owner_party_id,
        project_id=project_id,
        datasource_id=datasource_id,
        job_id=job_id,
        actor_type=str(actor_snapshot.get("actorType") or "system"),
        actor_party_id=actor_snapshot.get("partyId"),
        actor_party_name=actor_snapshot.get("partyName"),
        actor_token_id=actor_snapshot.get("tokenId"),
        target_party_id=target_party_id,
        target_role_code=target_role_code,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_path=resource_path,
        event_domain=event_domain,
        event_action=event_action,
        outcome=outcome,
        source=source,
        summary=summary,
        payload=payload or {},
        occurred_at=event_time,
        expires_at=event_time + timedelta(days=settings.audit_retention_days),
    )
    session.add(row)
    session.flush()
    return row


def record_many(session: Session, *, events: list[dict[str, Any]]) -> list[AuditLogORM]:
    rows = [record_event(session, **event) for event in events]
    return rows


def list_events(
    session: Session,
    *,
    identity: IdentityUserContext,
    project_id: UUID | None = None,
    actor_party_id: str | None = None,
    target_party_id: str | None = None,
    event_domain: str | None = None,
    event_action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> AuditListResult:
    ensure_can_read_audit_logs(identity)
    page = max(page, 1)
    page_size = max(1, min(page_size, 200))

    filters = _build_filters(
        identity=identity,
        project_id=project_id,
        actor_party_id=actor_party_id,
        target_party_id=target_party_id,
        event_domain=event_domain,
        event_action=event_action,
        date_from=date_from,
        date_to=date_to,
    )
    total = session.scalar(select(func.count()).select_from(AuditLogORM).where(*filters)) or 0
    rows = session.scalars(
        select(AuditLogORM)
        .where(*filters)
        .order_by(AuditLogORM.occurred_at.desc(), AuditLogORM.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return AuditListResult(
        items=[serialize_event_summary(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_event(
    session: Session,
    *,
    identity: IdentityUserContext,
    event_id: UUID,
) -> dict[str, Any] | None:
    ensure_can_read_audit_logs(identity)
    filters = _build_filters(identity=identity)
    row = session.scalars(
        select(AuditLogORM).where(AuditLogORM.id == event_id, *filters)
    ).first()
    if row is None:
        return None
    return serialize_event_detail(row)


def purge_expired_events(session: Session, *, now: datetime | None = None) -> int:
    current_time = now or utcnow()
    result = session.execute(
        delete(AuditLogORM).where(AuditLogORM.expires_at <= current_time)
    )
    return int(result.rowcount or 0)


def compute_set_diff(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    *,
    keys: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    before_map = {_diff_key(item, keys=keys): item for item in before}
    after_map = {_diff_key(item, keys=keys): item for item in after}
    added_keys = sorted(set(after_map) - set(before_map))
    removed_keys = sorted(set(before_map) - set(after_map))
    return {
        "added": [after_map[key] for key in added_keys],
        "removed": [before_map[key] for key in removed_keys],
    }


def serialize_event_summary(row: AuditLogORM) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "occurredAt": row.occurred_at.isoformat(),
        "projectId": str(row.project_id) if row.project_id else None,
        "datasourceId": str(row.datasource_id) if row.datasource_id else None,
        "jobId": str(row.job_id) if row.job_id else None,
        "eventDomain": row.event_domain,
        "eventAction": row.event_action,
        "outcome": row.outcome,
        "source": row.source,
        "summary": row.summary,
        "actor": {
            "actorType": row.actor_type,
            "partyId": row.actor_party_id,
            "partyName": row.actor_party_name,
        },
        "target": {
            "partyId": row.target_party_id,
            "roleCode": row.target_role_code,
        },
        "resource": {
            "type": row.resource_type,
            "id": row.resource_id,
            "path": row.resource_path,
        },
    }


def serialize_event_detail(row: AuditLogORM) -> dict[str, Any]:
    data = serialize_event_summary(row)
    data["ownerPartyId"] = row.owner_party_id
    data["expiresAt"] = row.expires_at.isoformat()
    data["actor"]["tokenId"] = row.actor_token_id
    data["payload"] = row.payload or {}
    return data


def _build_filters(
    *,
    identity: IdentityUserContext,
    project_id: UUID | None = None,
    actor_party_id: str | None = None,
    target_party_id: str | None = None,
    event_domain: str | None = None,
    event_action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[Any]:
    filters: list[Any] = [AuditLogORM.expires_at > utcnow()]
    if not identity.is_audit_admin:
        filters.append(AuditLogORM.owner_party_id == identity.party_id)
    if project_id is not None:
        filters.append(AuditLogORM.project_id == project_id)
    if actor_party_id:
        filters.append(AuditLogORM.actor_party_id == actor_party_id)
    if target_party_id:
        filters.append(AuditLogORM.target_party_id == target_party_id)
    if event_domain:
        filters.append(AuditLogORM.event_domain == event_domain)
    if event_action:
        filters.append(AuditLogORM.event_action == event_action)
    if date_from is not None:
        filters.append(AuditLogORM.occurred_at >= _coerce_naive(date_from))
    if date_to is not None:
        filters.append(AuditLogORM.occurred_at <= _coerce_naive(date_to))
    return filters


def _normalize_actor(actor: IdentityUserContext | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(actor, IdentityUserContext) or actor is None:
        return actor_snapshot_from_identity(actor)
    return {
        "actorType": actor.get("actorType", "system"),
        "partyId": actor.get("partyId"),
        "partyName": actor.get("partyName"),
        "tokenId": actor.get("tokenId"),
        "auditAdmin": bool(actor.get("auditAdmin", False)),
    }


def _coerce_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _diff_key(item: dict[str, Any], *, keys: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(item.get(key) for key in keys)
