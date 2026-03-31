from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi import Header
from fastapi import HTTPException
from fastapi import status

from src.api.middleware.identity import IdentityUserContext
from src.services.auth_tokens import decode_session_token


def get_optional_identity(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> IdentityUserContext | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Invalid token."}},
        )
    try:
        return decode_session_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Invalid session."}},
        ) from exc


def require_provider(
    identity: Annotated[IdentityUserContext | None, Depends(get_optional_identity)],
) -> IdentityUserContext:
    if identity is None or not identity.is_provider:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Provider session required."}},
        )
    return identity


def require_audit_reader(
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> IdentityUserContext:
    if not identity.is_provider:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Audit reader session required."}},
        )
    return identity


def require_consumer(
    identity: Annotated[IdentityUserContext | None, Depends(get_optional_identity)],
) -> IdentityUserContext:
    if identity is None or not identity.is_consumer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Consumer session required."}},
        )
    return identity


def ensure_project_owner(identity: IdentityUserContext, owner_party_id: str) -> None:
    if identity.party_id != owner_party_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Project ownership required."}},
        )


def parse_uuid_or_404(value: UUID | None, message: str = "Resource not found") -> UUID:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": message}},
        )
    return value
