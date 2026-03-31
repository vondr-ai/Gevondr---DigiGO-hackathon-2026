from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def _build_client(*, db_name: str, storage_name: str, audit_admin_ids: str = "") -> TestClient:
    db_path = Path(f"./data/{db_name}")
    storage_root = Path(f"./data/{storage_name}")
    if db_path.exists():
        db_path.unlink()
    if storage_root.exists():
        for child in sorted(storage_root.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        storage_root.rmdir()

    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["TASKS_EAGER"] = "1"
    os.environ["JWT_SECRET"] = "test-secret-with-at-least-32-bytes"
    os.environ["AUDIT_ADMIN_PARTY_IDS"] = audit_admin_ids
    os.environ["STORAGE_ROOT"] = storage_root.as_posix()

    existing_session_manager = sys.modules.get("src.database.session_manager")
    if existing_session_manager is not None:
        manager = getattr(existing_session_manager, "_session_manager", None)
        if manager is not None:
            manager.close()

    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)

    from src.app import create_app

    return TestClient(create_app())


def _provider_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/provider/login")
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _consumer_headers(client: TestClient, provider_headers: dict[str, str]) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/consumer/simulate",
        headers=provider_headers,
        json={"consumerPartyId": "did:ishare:EU.NL.NTRNL-09036504"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_provider_audit_reads_are_owner_scoped() -> None:
    with _build_client(db_name="test_audit_scope.db", storage_name="test_audit_scope") as client:
        from src.database.session_manager import get_session_manager
        from src.services.audit_service import record_event

        headers = _provider_headers(client)

        project = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"name": "Audit Scope Project", "status": "draft"},
        )
        assert project.status_code == 201

        with get_session_manager().get_pg_session() as session:
            record_event(
                session,
                owner_party_id="foreign-owner",
                event_domain="project",
                event_action="create",
                summary="Foreign owned event",
                resource_type="project",
                resource_id="foreign-project",
            )

        logs = client.get("/api/v1/audit-logs", headers=headers)
        assert logs.status_code == 200
        summaries = {item["summary"] for item in logs.json()["items"]}
        assert "Project Audit Scope Project aangemaakt." in summaries
        assert "Provider login gestart." in summaries
        assert "Foreign owned event" not in summaries

        create_event = next(
            item for item in logs.json()["items"] if item["eventAction"] == "create"
        )
        detail = client.get(f"/api/v1/audit-logs/{create_event['id']}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["payload"]["after"]["name"] == "Audit Scope Project"


def test_upload_and_search_are_logged_and_consumers_cannot_read_audit(monkeypatch) -> None:
    with _build_client(db_name="test_audit_search.db", storage_name="test_audit_search") as client:
        provider_headers = _provider_headers(client)
        project_response = client.post(
            "/api/v1/projects",
            headers=provider_headers,
            json={"name": "Search Audit Project", "status": "draft"},
        )
        project_id = project_response.json()["id"]

        datasource_response = client.post(
            f"/api/v1/projects/{project_id}/datasources",
            headers=provider_headers,
            json={"type": "upload", "config": {"displayName": "Uploads"}},
        )
        datasource_id = datasource_response.json()["id"]

        delegation_response = client.put(
            f"/api/v1/projects/{project_id}/delegations",
            headers=provider_headers,
            json={
                "items": [
                    {
                        "roleCode": "Aannemer",
                        "partyId": "did:ishare:EU.NL.NTRNL-09036504",
                    }
                ]
            },
        )
        assert delegation_response.status_code == 200

        upload = client.post(
            f"/api/v1/projects/{project_id}/datasources/{datasource_id}/uploads",
            headers=provider_headers,
            files={"files": ("hello.txt", b"hello world", "text/plain")},
            data={"targetPath": "inbox"},
        )
        assert upload.status_code == 201

        from src.services.search_service import SearchResultBundle

        def _fake_search(*args, **kwargs):
            _ = args, kwargs
            return SearchResultBundle(
                access_context={
                    "consumerPartyId": "did:ishare:EU.NL.NTRNL-09036504",
                    "resolvedRole": "Aannemer",
                },
                results=[
                    {
                        "documentId": "doc-1",
                        "title": "hello.txt",
                        "snippet": "hello world",
                        "access": "allowed",
                        "path": "inbox/hello.txt",
                    }
                ],
                totals={"allowed": 1, "blocked": 0},
            )

        monkeypatch.setattr("src.api.routers.consumer.search_consumer_project", _fake_search)

        consumer_headers = _consumer_headers(client, provider_headers)
        search = client.post(
            f"/api/v1/consumer/projects/{project_id}/search",
            headers=consumer_headers,
            json={
                "query": "hello",
                "filters": {"norms": ["NEN 2580"]},
                "page": 1,
                "pageSize": 20,
                "includeBlocked": True,
            },
        )
        assert search.status_code == 200

        consumer_logs = client.get("/api/v1/audit-logs", headers=consumer_headers)
        assert consumer_logs.status_code == 403

        document_logs = client.get(
            f"/api/v1/audit-logs?eventDomain=document",
            headers=provider_headers,
        )
        assert document_logs.status_code == 200
        document_actions = {item["eventAction"] for item in document_logs.json()["items"]}
        assert "create" in document_actions
        assert "upload_batch" in document_actions

        datasource_logs = client.get(
            f"/api/v1/audit-logs?eventDomain=datasource&eventAction=sync_completed",
            headers=provider_headers,
        )
        assert datasource_logs.status_code == 200
        assert datasource_logs.json()["total"] == 1

        search_logs = client.get(
            f"/api/v1/audit-logs?projectId={project_id}&eventDomain=search",
            headers=provider_headers,
        )
        assert search_logs.status_code == 200
        assert search_logs.json()["total"] == 1
        search_detail = client.get(
            f"/api/v1/audit-logs/{search_logs.json()['items'][0]['id']}",
            headers=provider_headers,
        )
        assert search_detail.status_code == 200
        assert search_detail.json()["payload"]["query"] == "hello"
        assert search_detail.json()["payload"]["totals"] == {"allowed": 1, "blocked": 0}


def test_admin_can_read_all_logs_and_indexing_and_forbidden_search_are_logged(monkeypatch) -> None:
    provider_party_id = "did:ishare:EU.NL.NTRNL-98499327"
    with _build_client(
        db_name="test_audit_admin.db",
        storage_name="test_audit_admin",
        audit_admin_ids=provider_party_id,
    ) as client:
        from src.database.session_manager import get_session_manager
        from src.services.audit_service import record_event
        from src.services.indexing_service import IndexingRunResult

        provider_headers = _provider_headers(client)
        project_response = client.post(
            "/api/v1/projects",
            headers=provider_headers,
            json={"name": "Admin Audit Project", "status": "draft"},
        )
        project_id = project_response.json()["id"]

        datasource_response = client.post(
            f"/api/v1/projects/{project_id}/datasources",
            headers=provider_headers,
            json={"type": "upload", "config": {"displayName": "Uploads"}},
        )
        assert datasource_response.status_code == 201

        monkeypatch.setattr(
            "src.api.routers.projects.get_indexing_readiness_warnings",
            lambda **kwargs: [],
        )
        async def _fake_run_indexing_job_service(session, job_id):
            _ = session, job_id
            return IndexingRunResult(processed=1, failed=0)

        monkeypatch.setattr(
            "src.worker.tasks.run_indexing_job_service",
            _fake_run_indexing_job_service,
        )

        start = client.post(
            f"/api/v1/projects/{project_id}/indexing-jobs",
            headers=provider_headers,
            json={"mode": "full", "reindex": True},
        )
        assert start.status_code == 202

        consumer_headers = _consumer_headers(client, provider_headers)

        def _forbidden_search(*args, **kwargs):
            _ = args, kwargs
            raise PermissionError("No delegation for this consumer")

        monkeypatch.setattr("src.api.routers.consumer.search_consumer_project", _forbidden_search)

        forbidden_search = client.post(
            f"/api/v1/consumer/projects/{project_id}/search",
            headers=consumer_headers,
            json={"query": "fundering"},
        )
        assert forbidden_search.status_code == 403

        with get_session_manager().get_pg_session() as session:
            record_event(
                session,
                owner_party_id="foreign-owner",
                event_domain="project",
                event_action="update",
                summary="Foreign admin-visible event",
                resource_type="project",
                resource_id="foreign-project",
            )

        all_logs = client.get("/api/v1/audit-logs", headers=provider_headers)
        assert all_logs.status_code == 200
        summaries = {item["summary"] for item in all_logs.json()["items"]}
        assert "Foreign admin-visible event" in summaries

        indexing_logs = client.get(
            f"/api/v1/audit-logs?projectId={project_id}&eventDomain=indexing",
            headers=provider_headers,
        )
        assert indexing_logs.status_code == 200
        indexing_actions = {item["eventAction"] for item in indexing_logs.json()["items"]}
        assert {"requested", "completed"} <= indexing_actions

        search_logs = client.get(
            f"/api/v1/audit-logs?projectId={project_id}&eventDomain=search",
            headers=provider_headers,
        )
        assert search_logs.status_code == 200
        assert search_logs.json()["total"] == 1
        assert search_logs.json()["items"][0]["outcome"] == "forbidden"
