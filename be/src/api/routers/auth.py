from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from pydantic import BaseModel

from src.api.deps import get_optional_identity
from src.api.deps import require_provider
from src.api.middleware.identity import IdentityUserContext
from src.database.session_manager import get_session_manager
from src.services.audit_service import record_event
from src.services.auth_tokens import create_session_token
from src.services.auth_tokens import decode_session_token
from src.services.participant_registry import registry

router = APIRouter(prefix="/auth", tags=["auth"])


class ConsumerSimulateRequest(BaseModel):
    consumerPartyId: str


def _user_payload(identity: IdentityUserContext) -> dict:
    return {
        "actorType": identity.actor_type,
        "partyId": identity.party_id,
        "partyName": identity.party_name,
        "simulation": identity.simulation,
        "dsgoRoles": identity.dsgo_roles,
        "certificateStatus": "mocked-valid",
    }


@router.post("/provider/login")
def provider_login() -> dict:
    participant = registry.get_participant("did:ishare:EU.NL.NTRNL-98499327")
    if participant is None:
        raise HTTPException(status_code=500, detail="Mock provider missing")
    token = create_session_token(
        actor_type="provider",
        party_id=participant.party_id,
        party_name=participant.name,
        dsgo_roles=participant.dsgo_roles,
        simulation=False,
    )
    identity = decode_session_token(token)
    with get_session_manager().get_pg_session() as session:
        record_event(
            session,
            owner_party_id=identity.party_id,
            event_domain="auth",
            event_action="login",
            summary="Provider login gestart.",
            actor=identity,
            resource_type="session",
            resource_id=identity.token_id,
            payload={"simulation": identity.simulation, "dsgoRoles": identity.dsgo_roles},
        )
    return {"token": token, "user": _user_payload(identity)}


@router.get("/session")
def current_session(
    identity: Annotated[IdentityUserContext | None, Depends(get_optional_identity)],
) -> dict:
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "unauthorized", "message": "No active session."}},
        )
    return {"user": _user_payload(identity)}


@router.post("/consumer/simulate")
def consumer_simulate(
    body: ConsumerSimulateRequest,
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    participant = registry.get_participant(body.consumerPartyId)
    if participant is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Participant not found."}},
        )
    token = create_session_token(
        actor_type="consumer",
        party_id=participant.party_id,
        party_name=participant.name,
        dsgo_roles=participant.dsgo_roles,
        simulation=True,
    )
    consumer_identity = decode_session_token(token)
    with get_session_manager().get_pg_session() as session:
        record_event(
            session,
            owner_party_id=identity.party_id,
            event_domain="auth",
            event_action="consumer_simulate",
            summary=f"Consumer-simulatie gestart voor {consumer_identity.party_name}.",
            actor=identity,
            target_party_id=consumer_identity.party_id,
            resource_type="session",
            resource_id=consumer_identity.token_id,
            payload={
                "consumerPartyId": consumer_identity.party_id,
                "consumerPartyName": consumer_identity.party_name,
                "consumerRoles": consumer_identity.dsgo_roles,
            },
        )
    return {"token": token, "user": _user_payload(consumer_identity)}


@router.post("/logout", status_code=204)
def logout() -> Response:
    return Response(status_code=204)
