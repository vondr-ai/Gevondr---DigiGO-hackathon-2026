from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from src.api.middleware.identity import IdentityUserContext
from src.database.postgres.connection.base import Base
from src.services.audit_service import compute_set_diff
from src.services.audit_service import get_event
from src.services.audit_service import list_events
from src.services.audit_service import purge_expired_events
from src.services.audit_service import record_event


def _identity(*, actor_type: str, party_id: str, audit_admin: bool = False) -> IdentityUserContext:
    return IdentityUserContext(
        actor_type=actor_type,
        party_id=party_id,
        party_name=party_id.upper(),
        audit_admin=audit_admin,
        token_id=str(UUID(int=1)),
    )


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_audit_service_scopes_reads_and_excludes_expired_records(session: Session) -> None:
    owner_identity = _identity(actor_type="provider", party_id="owner-a")
    admin_identity = _identity(actor_type="provider", party_id="admin", audit_admin=True)

    owner_event = record_event(
        session,
        owner_party_id="owner-a",
        event_domain="project",
        event_action="create",
        summary="Owner event",
        actor=owner_identity,
        resource_type="project",
        resource_id="project-1",
    )
    foreign_event = record_event(
        session,
        owner_party_id="owner-b",
        event_domain="project",
        event_action="update",
        summary="Foreign event",
        actor=owner_identity,
        resource_type="project",
        resource_id="project-2",
    )
    expired_event = record_event(
        session,
        owner_party_id="owner-a",
        event_domain="search",
        event_action="execute",
        summary="Expired event",
        actor=owner_identity,
        occurred_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2),
    )
    expired_event.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
    session.commit()

    owner_result = list_events(session, identity=owner_identity)
    assert [item["summary"] for item in owner_result.items] == ["Owner event"]

    admin_result = list_events(session, identity=admin_identity)
    assert {item["summary"] for item in admin_result.items} == {"Owner event", "Foreign event"}

    owner_detail = get_event(session, identity=owner_identity, event_id=owner_event.id)
    assert owner_detail is not None
    assert owner_detail["resource"]["id"] == "project-1"

    hidden_detail = get_event(session, identity=owner_identity, event_id=foreign_event.id)
    assert hidden_detail is None


def test_audit_service_enforces_provider_access_and_supports_retention_cleanup(session: Session) -> None:
    provider_identity = _identity(actor_type="provider", party_id="owner-a")
    consumer_identity = _identity(actor_type="consumer", party_id="consumer-a")

    expired_event = record_event(
        session,
        owner_party_id="owner-a",
        event_domain="document",
        event_action="view",
        summary="Document viewed",
        actor=provider_identity,
    )
    expired_event.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    session.commit()

    with pytest.raises(PermissionError):
        list_events(session, identity=consumer_identity)

    deleted = purge_expired_events(session)
    session.commit()

    assert deleted == 1
    assert list_events(session, identity=provider_identity).total == 0


def test_compute_set_diff_returns_added_and_removed_items() -> None:
    before = [{"roleCode": "Aannemer", "partyId": "old"}]
    after = [{"roleCode": "Aannemer", "partyId": "new"}]

    diff = compute_set_diff(before, after, keys=("roleCode", "partyId"))

    assert diff == {
        "added": [{"roleCode": "Aannemer", "partyId": "new"}],
        "removed": [{"roleCode": "Aannemer", "partyId": "old"}],
    }
