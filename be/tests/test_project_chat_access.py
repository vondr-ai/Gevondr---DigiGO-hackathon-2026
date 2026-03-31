from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.api.middleware.identity import IdentityUserContext
from src.services.project_chat.access import ProjectChatAccessError
from src.services.project_chat.access import ensure_document_open_access
from src.services.project_chat.access import resolve_project_chat_access


class _ScalarResult:
    def __init__(self, item):
        self._item = item

    def first(self):
        return self._item


class _FakeSession:
    def __init__(self, *, project, delegation=None) -> None:
        self.project = project
        self.delegation = delegation

    def get(self, model, _identifier):
        if model.__name__ == "ProjectORM":
            return self.project
        return None

    def scalars(self, _statement):
        return _ScalarResult(self.delegation)


def test_provider_owner_is_allowed() -> None:
    project = SimpleNamespace(id=uuid4(), owner_party_id="owner-1")
    session = _FakeSession(project=project)
    identity = IdentityUserContext(
        actor_type="provider",
        party_id="owner-1",
        party_name="Owner",
    )

    scope = resolve_project_chat_access(
        session,
        project_id=project.id,
        identity=identity,
    )

    assert scope.is_provider_owner is True
    assert scope.allowed_role_codes is None


def test_non_owner_provider_is_rejected() -> None:
    project = SimpleNamespace(id=uuid4(), owner_party_id="owner-1")
    session = _FakeSession(project=project)
    identity = IdentityUserContext(
        actor_type="provider",
        party_id="owner-2",
        party_name="Other",
    )

    with pytest.raises(ProjectChatAccessError):
        resolve_project_chat_access(
            session,
            project_id=project.id,
            identity=identity,
        )


def test_consumer_without_delegation_is_rejected() -> None:
    project = SimpleNamespace(id=uuid4(), owner_party_id="owner-1")
    session = _FakeSession(project=project, delegation=None)
    identity = IdentityUserContext(
        actor_type="consumer",
        party_id="consumer-1",
        party_name="Consumer",
    )

    with pytest.raises(ProjectChatAccessError):
        resolve_project_chat_access(
            session,
            project_id=project.id,
            identity=identity,
        )


def test_delegated_consumer_can_open_allowed_document() -> None:
    project = SimpleNamespace(id=uuid4(), owner_party_id="owner-1")
    delegation = SimpleNamespace(role_code="Aannemer")
    session = _FakeSession(project=project, delegation=delegation)
    identity = IdentityUserContext(
        actor_type="consumer",
        party_id="consumer-1",
        party_name="Consumer",
    )

    scope = resolve_project_chat_access(
        session,
        project_id=project.id,
        identity=identity,
    )

    document = SimpleNamespace(allowed_role_codes=["Aannemer"])
    ensure_document_open_access(scope, document=document)


def test_delegated_consumer_cannot_open_blocked_document() -> None:
    project = SimpleNamespace(id=uuid4(), owner_party_id="owner-1")
    delegation = SimpleNamespace(role_code="Aannemer")
    session = _FakeSession(project=project, delegation=delegation)
    identity = IdentityUserContext(
        actor_type="consumer",
        party_id="consumer-1",
        party_name="Consumer",
    )

    scope = resolve_project_chat_access(
        session,
        project_id=project.id,
        identity=identity,
    )

    document = SimpleNamespace(allowed_role_codes=["Toezichthouder"])
    with pytest.raises(ProjectChatAccessError):
        ensure_document_open_access(scope, document=document)
