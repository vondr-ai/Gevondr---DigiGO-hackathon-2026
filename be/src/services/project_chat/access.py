from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.middleware.identity import IdentityUserContext
from src.database.models import DelegationORM
from src.database.models import IndexedDocumentORM
from src.database.models import ProjectORM


class ProjectChatAccessError(PermissionError):
    pass


@dataclass(slots=True)
class ProjectChatAccessScope:
    project_id: UUID
    actor_type: str
    party_id: str
    owner_party_id: str
    resolved_role: str | None
    allowed_role_codes: list[str] | None

    @property
    def is_provider_owner(self) -> bool:
        return self.actor_type == "provider" and self.party_id == self.owner_party_id


def resolve_project_chat_access(
    session: Session,
    *,
    project_id: UUID,
    identity: IdentityUserContext | None,
) -> ProjectChatAccessScope:
    project = session.get(ProjectORM, project_id)
    if project is None:
        raise ValueError("Project not found")
    if identity is None:
        raise ProjectChatAccessError("Authenticated session required.")

    if identity.is_provider:
        if identity.party_id != project.owner_party_id:
            raise ProjectChatAccessError("Project ownership required.")
        return ProjectChatAccessScope(
            project_id=project.id,
            actor_type=identity.actor_type,
            party_id=identity.party_id,
            owner_party_id=project.owner_party_id,
            resolved_role=None,
            allowed_role_codes=None,
        )

    if identity.is_consumer:
        delegation = session.scalars(
            select(DelegationORM).where(
                DelegationORM.project_id == project.id,
                DelegationORM.party_id == identity.party_id,
            )
        ).first()
        if delegation is None:
            raise ProjectChatAccessError("No delegation for this consumer.")
        return ProjectChatAccessScope(
            project_id=project.id,
            actor_type=identity.actor_type,
            party_id=identity.party_id,
            owner_party_id=project.owner_party_id,
            resolved_role=delegation.role_code,
            allowed_role_codes=[delegation.role_code],
        )

    raise ProjectChatAccessError("Unsupported actor type.")


def ensure_document_open_access(
    scope: ProjectChatAccessScope,
    *,
    document: IndexedDocumentORM,
) -> None:
    if scope.is_provider_owner:
        return
    if not scope.allowed_role_codes:
        raise ProjectChatAccessError("Document access denied.")
    if not set(scope.allowed_role_codes).intersection(document.allowed_role_codes or []):
        raise ProjectChatAccessError("Document access denied.")
