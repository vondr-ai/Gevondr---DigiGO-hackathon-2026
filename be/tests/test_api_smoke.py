from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


os.environ["DATABASE_URL"] = "sqlite:///./data/test_smoke.db"
os.environ["TASKS_EAGER"] = "1"
os.environ["JWT_SECRET"] = "test-secret-with-at-least-32-bytes"
os.environ["JINA_API_KEY"] = "test-jina-key"
os.environ["GEMINI_API_KEY"] = "test-gemini-key"


def _build_client() -> TestClient:
    from src.database.session_manager import _session_manager  # type: ignore[attr-defined]
    from src.settings import get_settings

    if Path("./data/test_smoke.db").exists():
        Path("./data/test_smoke.db").unlink()
    get_settings.cache_clear()
    if _session_manager is not None:
        _session_manager.close()
    import src.database.session_manager as session_manager_module

    session_manager_module._session_manager = None
    from src.app import create_app

    app = create_app()
    return TestClient(app)


def test_provider_project_upload_flow() -> None:
    with _build_client() as client:
        login = client.post("/api/v1/auth/provider/login")
        assert login.status_code == 200
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        project = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"name": "Smoke Project", "status": "draft"},
        )
        assert project.status_code == 201
        project_id = project.json()["id"]

        datasource = client.post(
            f"/api/v1/projects/{project_id}/datasources",
            headers=headers,
            json={"type": "upload", "config": {"displayName": "Uploads"}},
        )
        assert datasource.status_code == 201
        datasource_id = datasource.json()["id"]

        upload = client.post(
            f"/api/v1/projects/{project_id}/datasources/{datasource_id}/uploads",
            headers=headers,
            files={"files": ("hello.txt", b"hello world", "text/plain")},
            data={"targetPath": ""},
        )
        assert upload.status_code == 201
        uploaded = upload.json()["uploaded"]
        assert len(uploaded) == 1

        ai_config = client.get(
            f"/api/v1/projects/{project_id}/ai-config",
            headers=headers,
        )
        assert ai_config.status_code == 200
        ai_payload = ai_config.json()
        assert ai_payload["provider"] == "gemini"

        summary = client.get(
            f"/api/v1/projects/{project_id}/indexing/summary",
            headers=headers,
        )
        assert summary.status_code == 200
        payload = summary.json()
        assert payload["project"]["id"] == project_id
        assert payload["readyToStart"] is False

        not_ready = client.post(
            f"/api/v1/projects/{project_id}/indexing-jobs",
            headers=headers,
            json={"mode": "full", "reindex": True},
        )
        assert not_ready.status_code == 409


def test_provider_upload_flow_keeps_nested_relative_paths() -> None:
    with _build_client() as client:
        login = client.post("/api/v1/auth/provider/login")
        assert login.status_code == 200
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        project = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"name": "Nested Upload Project", "status": "draft"},
        )
        assert project.status_code == 201
        project_id = project.json()["id"]

        datasource = client.post(
            f"/api/v1/projects/{project_id}/datasources",
            headers=headers,
            json={"type": "upload", "config": {"displayName": "Uploads"}},
        )
        assert datasource.status_code == 201
        datasource_id = datasource.json()["id"]

        upload = client.post(
            f"/api/v1/projects/{project_id}/datasources/{datasource_id}/uploads",
            headers=headers,
            files=[("files", ("report.pdf", b"nested file", "application/pdf"))],
            data={"relativePaths": "contracts/2026/report.pdf", "targetPath": ""},
        )
        assert upload.status_code == 201
        uploaded = upload.json()["uploaded"]
        assert uploaded == [
            {
                "documentId": uploaded[0]["documentId"],
                "fileName": "report.pdf",
                "size": 11,
                "path": "contracts/2026/report.pdf",
            }
        ]


def test_provider_reuses_active_indexing_job_and_can_fetch_latest(monkeypatch) -> None:
    with _build_client() as client:
        login = client.post("/api/v1/auth/provider/login")
        assert login.status_code == 200
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        project = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"name": "Index Resume Project", "status": "draft"},
        )
        assert project.status_code == 201
        project_id = project.json()["id"]

        datasource = client.post(
            f"/api/v1/projects/{project_id}/datasources",
            headers=headers,
            json={"type": "upload", "config": {"displayName": "Uploads"}},
        )
        assert datasource.status_code == 201
        datasource_id = datasource.json()["id"]

        upload = client.post(
            f"/api/v1/projects/{project_id}/datasources/{datasource_id}/uploads",
            headers=headers,
            files={"files": ("hello.txt", b"hello world", "text/plain")},
            data={"targetPath": ""},
        )
        assert upload.status_code == 201

        ai_config = client.put(
            f"/api/v1/projects/{project_id}/ai-config",
            headers=headers,
            json={
                "provider": "gemini",
                "model": "gemini-test",
                "apiKey": "project-test-key",
                "chunking": {"size": 800, "overlap": 120},
            },
        )
        assert ai_config.status_code == 200

        norms = client.put(
            f"/api/v1/projects/{project_id}/norms",
            headers=headers,
            json={
                "selectedNorms": ["NEN 2580"],
                "indexingInstructions": "Classificeer documenten.",
            },
        )
        assert norms.status_code == 200

        import src.api.routers.projects as project_routes

        async def _fake_enqueue_task(*args, **kwargs) -> str:
            _ = args
            _ = kwargs
            return "queued-job-id"

        monkeypatch.setattr(project_routes, "enqueue_task", _fake_enqueue_task)

        first = client.post(
            f"/api/v1/projects/{project_id}/indexing-jobs",
            headers=headers,
            json={"mode": "full", "reindex": True},
        )
        assert first.status_code == 202
        first_payload = first.json()
        assert first_payload["status"] == "queued"
        assert first_payload["progress"] == 0

        second = client.post(
            f"/api/v1/projects/{project_id}/indexing-jobs",
            headers=headers,
            json={"mode": "full", "reindex": True},
        )
        assert second.status_code == 202
        second_payload = second.json()
        assert second_payload["jobId"] == first_payload["jobId"]
        assert second_payload["status"] == "queued"

        latest = client.get(
            f"/api/v1/projects/{project_id}/indexing-jobs/latest",
            headers=headers,
        )
        assert latest.status_code == 200
        latest_payload = latest.json()
        assert latest_payload["jobId"] == first_payload["jobId"]
        assert latest_payload["status"] == "queued"
