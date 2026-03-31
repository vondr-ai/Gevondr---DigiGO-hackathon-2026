from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from sqlalchemy import select

from src.database.models import DatasourceORM
from src.database.models import DelegationORM
from src.database.models import IndexedDocumentORM
from src.database.models import IndexRevisionORM
from src.database.models import ProjectAIConfigORM
from src.database.models import ProjectORM
from src.database.models import StagedDocumentORM


os.environ["DATABASE_URL"] = "sqlite:///./data/test_project_chat_api.db"
os.environ["TASKS_EAGER"] = "1"
os.environ["JWT_SECRET"] = "test-secret-with-at-least-32-bytes"

CONSUMER_PARTY_ID = "did:ishare:EU.NL.NTRNL-09036504"


def _build_client() -> TestClient:
    from src.database.session_manager import _session_manager  # type: ignore[attr-defined]
    from src.settings import get_settings

    db_path = Path("./data/test_project_chat_api.db")
    if db_path.exists():
        db_path.unlink()
    get_settings.cache_clear()
    if _session_manager is not None:
        _session_manager.close()
    import src.database.session_manager as session_manager_module

    session_manager_module._session_manager = None
    from src.app import create_app

    return TestClient(create_app())


def _seed_indexed_document(
    project_id: str,
    *,
    allowed_role_codes: list[str],
) -> tuple[str, str]:
    from src.database.session_manager import get_session_manager

    with get_session_manager().get_pg_session() as session:
        project = session.get(ProjectORM, UUID(project_id))
        assert project is not None
        datasource = session.scalars(
            select(DatasourceORM).where(DatasourceORM.project_id == project.id)
        ).first()
        staged_document = session.scalars(
            select(StagedDocumentORM).where(StagedDocumentORM.project_id == project.id)
        ).first()
        assert datasource is not None
        assert staged_document is not None

        revision = IndexRevisionORM(
            project_id=project.id,
            datasource_id=datasource.id,
            status="active",
            document_count=1,
        )
        session.add(revision)
        session.flush()
        project.active_index_revision_id = revision.id
        session.add(
            ProjectAIConfigORM(
                project_id=project.id,
                provider="gemini",
                model="gemini-test",
                api_key="test-key",
            )
        )
        document = IndexedDocumentORM(
            id=UUID(int=revision.id.int ^ 12345),
            project_id=project.id,
            datasource_id=datasource.id,
            staged_document_id=staged_document.id,
            index_revision_id=revision.id,
            title=staged_document.filename,
            path=staged_document.path,
            storage_path=staged_document.storage_path,
            mime_type=staged_document.mime_type,
            size=staged_document.size,
            pages=1,
            status="processed",
            full_text="Roof inspected on 2019-01-01.",
            summary="Roof inspected in 2019.",
            short_summary="Roof inspection",
            index_values=[],
            doc_metadata={"source": "test"},
            selected_norms=["NEN-2580"],
            allowed_role_codes=allowed_role_codes,
            error_message=None,
        )
        session.add(document)
        return str(document.id), staged_document.storage_path


def _prepare_project_with_document(client: TestClient) -> tuple[str, dict[str, str], str, str]:
    provider_login = client.post("/api/v1/auth/provider/login")
    provider_headers = {"Authorization": f"Bearer {provider_login.json()['token']}"}
    project = client.post(
        "/api/v1/projects",
        headers=provider_headers,
        json={"name": "Chat Project", "status": "draft"},
    )
    project_id = project.json()["id"]
    datasource = client.post(
        f"/api/v1/projects/{project_id}/datasources",
        headers=provider_headers,
        json={"type": "upload", "config": {"displayName": "Uploads"}},
    )
    datasource_id = datasource.json()["id"]
    upload = client.post(
        f"/api/v1/projects/{project_id}/datasources/{datasource_id}/uploads",
        headers=provider_headers,
        files={"files": ("roof.txt", b"Roof inspected on 2019-01-01.", "text/plain")},
        data={"targetPath": ""},
    )
    assert upload.status_code == 201
    document_id, storage_path = _seed_indexed_document(
        project_id,
        allowed_role_codes=["Aannemer"],
    )
    return project_id, provider_headers, document_id, storage_path


def test_chat_stream_emits_status_token_and_done(monkeypatch) -> None:
    with _build_client() as client:
        project_id, provider_headers, document_id, _ = _prepare_project_with_document(client)
        link = f"/api/v1/projects/{project_id}/documents/{document_id}/open"

        def _fake_build_agent(**_kwargs):
            return Agent(TestModel(custom_output_text=f"See [Roof inspection]({link})"))

        monkeypatch.setattr(
            "src.api.routers.project_chat.build_project_chat_agent",
            _fake_build_agent,
        )

        response = client.post(
            f"/api/v1/projects/{project_id}/chat/stream",
            headers=provider_headers,
            json={"messages": [{"role": "user", "content": "When was the roof inspected?"}]},
        )

        assert response.status_code == 200
        assert "event: status" in response.text
        assert "event: token" in response.text
        assert "event: done" in response.text
        assert link in response.text


def test_chat_stream_can_emit_tool_events(monkeypatch) -> None:
    with _build_client() as client:
        project_id, provider_headers, _, _ = _prepare_project_with_document(client)

        async def _fake_stream_agent_markdown(*, agent, prompt, deps, message_history):
            yield 'event: status\ndata: {"phase": "started"}\n\n'
            yield 'event: tool\ndata: {"tool": "search_project", "phase": "started"}\n\n'
            yield (
                'event: tool\ndata: '
                '{"tool": "search_project", "phase": "completed", "uniqueDocumentCount": 3}\n\n'
            )
            yield 'event: done\ndata: {"output": "done", "usage": {"requests": 1, "inputTokens": 1, "outputTokens": 1}}\n\n'

        monkeypatch.setattr(
            "src.api.routers.project_chat.stream_agent_markdown",
            _fake_stream_agent_markdown,
        )
        monkeypatch.setattr(
            "src.api.routers.project_chat.build_project_chat_agent",
            lambda **_kwargs: Agent(TestModel(custom_output_text="unused")),
        )

        response = client.post(
            f"/api/v1/projects/{project_id}/chat/stream",
            headers=provider_headers,
            json={"messages": [{"role": "user", "content": "Search for inspection evidence"}]},
        )

        assert response.status_code == 200
        assert "event: tool" in response.text
        assert '"uniqueDocumentCount": 3' in response.text


def test_chat_stream_without_active_index_returns_conflict(monkeypatch) -> None:
    with _build_client() as client:
        provider_login = client.post("/api/v1/auth/provider/login")
        provider_headers = {"Authorization": f"Bearer {provider_login.json()['token']}"}
        project = client.post(
            "/api/v1/projects",
            headers=provider_headers,
            json={"name": "No Index Project", "status": "draft"},
        )
        project_id = project.json()["id"]

        def _unused_agent(**_kwargs):
            return Agent(TestModel(custom_output_text="unused"))

        monkeypatch.setattr(
            "src.api.routers.project_chat.build_project_chat_agent",
            _unused_agent,
        )

        response = client.post(
            f"/api/v1/projects/{project_id}/chat/stream",
            headers=provider_headers,
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )

        assert response.status_code == 409


def test_inline_open_route_allows_delegated_consumer() -> None:
    with _build_client() as client:
        project_id, provider_headers, document_id, storage_path = _prepare_project_with_document(client)
        put_delegations = client.put(
            f"/api/v1/projects/{project_id}/delegations",
            headers=provider_headers,
            json={"items": [{"roleCode": "Aannemer", "partyId": CONSUMER_PARTY_ID}]},
        )
        assert put_delegations.status_code == 200

        consumer_login = client.post(
            "/api/v1/auth/consumer/simulate",
            headers=provider_headers,
            json={"consumerPartyId": CONSUMER_PARTY_ID},
        )
        consumer_headers = {"Authorization": f"Bearer {consumer_login.json()['token']}"}

        response = client.get(
            f"/api/v1/projects/{project_id}/documents/{document_id}/open",
            headers=consumer_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("inline;")
        assert response.content == Path(storage_path).read_bytes()
