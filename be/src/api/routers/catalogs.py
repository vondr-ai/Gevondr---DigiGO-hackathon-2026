from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query

from src.api.deps import require_provider
from src.api.middleware.identity import IdentityUserContext
from src.services.catalogs import GEBORA_ROLES
from src.services.catalogs import GEBORA_VALUE_STREAMS
from src.services.catalogs import NEN_2084_DOCUMENT_TYPES
from src.services.catalogs import NORMS_CATALOG
from src.services.participant_registry import registry

router = APIRouter(tags=["catalogs"])


@router.get("/norms/catalog")
def get_norms_catalog(
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    _ = identity
    return {"items": NORMS_CATALOG}


@router.get("/roles/gebora")
def get_gebora_roles(
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    _ = identity
    return {"items": GEBORA_ROLES}


@router.get("/document-types/nen2084")
def get_nen_2084_document_types(
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    _ = identity
    return {"items": NEN_2084_DOCUMENT_TYPES}


@router.get("/value-streams/gebora")
def get_gebora_value_streams(
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
) -> dict:
    _ = identity
    return {"items": GEBORA_VALUE_STREAMS}


@router.get("/delegations/participants")
def find_delegation_participants(
    identity: Annotated[IdentityUserContext, Depends(require_provider)],
    search: str | None = Query(default=None),
    requiredDsgoRole: str | None = Query(default=None),
) -> dict:
    _ = identity
    items = registry.list_participants(
        search=search,
        required_dsgo_role=requiredDsgoRole,
    )
    return {
        "items": [
            {
                "partyId": item.party_id,
                "name": item.name,
                "membershipStatus": item.membership_status,
                "dsgoRoles": item.dsgo_roles,
            }
            for item in items
        ]
    }
