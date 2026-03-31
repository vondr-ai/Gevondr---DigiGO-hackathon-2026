from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class IdentityUserContext:
    actor_type: str
    party_id: str
    party_name: str
    dsgo_roles: list[str] = field(default_factory=list)
    simulation: bool = False
    audit_admin: bool = False
    token_id: str | None = None
    issued_at: datetime | None = None

    @property
    def is_provider(self) -> bool:
        return self.actor_type == "provider"

    @property
    def is_consumer(self) -> bool:
        return self.actor_type == "consumer"

    @property
    def is_admin(self) -> bool:
        return self.audit_admin

    @property
    def is_audit_admin(self) -> bool:
        return self.audit_admin

    @property
    def is_system(self) -> bool:
        return False

    @property
    def id(self) -> UUID:
        return UUID(self.token_id) if self.token_id else UUID(int=0)
