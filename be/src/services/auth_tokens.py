from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from uuid import uuid4

import jwt

from src.api.middleware.identity import IdentityUserContext
from src.settings import settings


def create_session_token(
    *,
    actor_type: str,
    party_id: str,
    party_name: str,
    dsgo_roles: list[str],
    simulation: bool,
    audit_admin: bool | None = None,
) -> str:
    issued_at = datetime.now(UTC)
    resolved_audit_admin = (
        audit_admin
        if audit_admin is not None
        else party_id in settings.audit_admin_party_ids
    )
    payload = {
        "sub": party_id,
        "token_id": str(uuid4()),
        "actor_type": actor_type,
        "party_id": party_id,
        "party_name": party_name,
        "dsgo_roles": dsgo_roles,
        "simulation": simulation,
        "audit_admin": resolved_audit_admin,
        "iat": int(issued_at.timestamp()),
        "exp": int(
            (issued_at + timedelta(minutes=settings.jwt_expiration_minutes)).timestamp()
        ),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_session_token(token: str) -> IdentityUserContext:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    issued_at = datetime.fromtimestamp(payload["iat"], tz=UTC)
    party_id = payload["party_id"]
    return IdentityUserContext(
        actor_type=payload["actor_type"],
        party_id=party_id,
        party_name=payload["party_name"],
        dsgo_roles=list(payload.get("dsgo_roles", [])),
        simulation=bool(payload.get("simulation", False)),
        audit_admin=bool(payload.get("audit_admin", party_id in settings.audit_admin_party_ids)),
        token_id=payload.get("token_id"),
        issued_at=issued_at.replace(tzinfo=None),
    )
