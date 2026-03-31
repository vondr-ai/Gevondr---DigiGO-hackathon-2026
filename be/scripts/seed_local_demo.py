from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from uuid import UUID

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.storage import copy_tree_into_staging
from src.services.storage import datasource_staging_root
from src.services.storage import stored_file_path
from src.settings import settings


DEFAULT_SOURCE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "OneDrive_2026-03-30"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a local DigiGO demo project.")
    parser.add_argument(
        "--api-base-url",
        default="http://localhost:8000/api/v1",
    )
    parser.add_argument(
        "--source-path",
        default=str(DEFAULT_SOURCE_PATH),
    )
    parser.add_argument("--subpath", default="")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def copy_source_tree(
    *,
    project_id: UUID,
    datasource_id: UUID,
    source_root: Path,
    limit: int,
) -> int:
    if limit <= 0:
        copy_tree_into_staging(
            project_id=project_id,
            datasource_id=datasource_id,
            source_root=source_root,
        )
        return sum(1 for path in source_root.rglob("*") if path.is_file())

    staging_root = datasource_staging_root(project_id, datasource_id)
    shutil.rmtree(staging_root, ignore_errors=True)
    staging_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    for file_path in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative_path = file_path.relative_to(source_root).as_posix()
        target = stored_file_path(project_id, datasource_id, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target)
        copied += 1
        if copied >= limit:
            break
    return copied


def wait_for_indexing_readiness(
    session: requests.Session,
    *,
    api_base_url: str,
    project_id: UUID,
    timeout_seconds: int = 120,
) -> dict:
    deadline = time.time() + timeout_seconds
    last_payload: dict | None = None
    while time.time() < deadline:
        response = session.get(
            f"{api_base_url}/projects/{project_id}/indexing/summary",
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        last_payload = payload
        if payload.get("readyToStart"):
            return payload
        time.sleep(2)
    raise TimeoutError(
        f"Project {project_id} did not become ready for indexing in time. "
        f"Last summary: {json.dumps(last_payload, ensure_ascii=False)}"
    )


def main() -> None:
    args = parse_args()
    source_path = Path(args.source_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Source path does not exist: {source_path}")
    session = requests.Session()

    login_response = session.post(f"{args.api_base_url}/auth/provider/login", timeout=30)
    login_response.raise_for_status()
    token = login_response.json()["token"]
    session.headers["Authorization"] = f"Bearer {token}"

    project_response = session.post(
        f"{args.api_base_url}/projects",
        json={
            "name": "Gebied Zuid-West - Best Spoortunnel",
            "description": "Local seed project",
            "nenLabel": "NEN 2580",
            "status": "draft",
        },
        timeout=30,
    )
    project_response.raise_for_status()
    project = project_response.json()
    project_id = UUID(project["id"])

    datasource_response = session.post(
        f"{args.api_base_url}/projects/{project_id}/datasources",
        json={"type": "upload", "config": {"displayName": "Local OneDrive import"}},
        timeout=30,
    )
    datasource_response.raise_for_status()
    datasource = datasource_response.json()
    datasource_id = UUID(datasource["id"])

    effective_source = source_path / args.subpath if args.subpath else source_path
    imported_count = copy_source_tree(
        project_id=project_id,
        datasource_id=datasource_id,
        source_root=effective_source,
        limit=args.limit,
    )

    discover_response = session.post(
        f"{args.api_base_url}/projects/{project_id}/datasources/{datasource_id}/discover",
        json={"rootPath": None},
        timeout=30,
    )
    discover_response.raise_for_status()

    session.put(
        f"{args.api_base_url}/projects/{project_id}/ai-config",
        json={
            "provider": "gemini",
            "model": settings.gemini_model,
            "apiKey": None,
            "chunking": {"size": 800, "overlap": 120},
        },
        timeout=30,
    ).raise_for_status()
    session.put(
        f"{args.api_base_url}/projects/{project_id}/norms",
        json={
            "selectedNorms": ["NEN 2580", "NEN 2767"],
            "indexingInstructions": "Focus on fundering, brandveiligheid en oppervlakten.",
        },
        timeout=30,
    ).raise_for_status()
    session.put(
        f"{args.api_base_url}/projects/{project_id}/roles/access-matrix",
        json={
            "entries": [
                {
                    "roleCode": "Aannemer",
                    "resourceType": "folder",
                    "resourceId": "root",
                    "path": "",
                    "allowRead": True,
                },
                {
                    "roleCode": "Toezichthouder",
                    "resourceType": "folder",
                    "resourceId": "root",
                    "path": "",
                    "allowRead": True,
                },
            ]
        },
        timeout=30,
    ).raise_for_status()
    session.put(
        f"{args.api_base_url}/projects/{project_id}/delegations",
        json={
            "items": [
                {
                    "roleCode": "Aannemer",
                    "partyId": "did:ishare:EU.NL.NTRNL-09036504",
                }
            ]
        },
        timeout=30,
    ).raise_for_status()

    readiness = wait_for_indexing_readiness(
        session,
        api_base_url=args.api_base_url,
        project_id=project_id,
    )
    print(
        json.dumps(
            {
                "projectId": str(project_id),
                "datasourceId": str(datasource_id),
                "importedFiles": imported_count,
                "readyToStart": readiness["readyToStart"],
                "warnings": readiness["warnings"],
            },
            indent=2,
        )
    )

    index_response = session.post(
        f"{args.api_base_url}/projects/{project_id}/indexing-jobs",
        json={"mode": "full", "reindex": True},
        timeout=30,
    )
    if index_response.status_code == 409:
        raise RuntimeError(
            f"Indexing start rejected: {index_response.text}"
        )
    index_response.raise_for_status()
    job_id = index_response.json()["jobId"]

    print(
        json.dumps(
            {
                "indexingJobId": job_id,
            },
            indent=2,
        )
    )

    while True:
        status_response = session.get(
            f"{args.api_base_url}/projects/{project_id}/indexing-jobs/{job_id}",
            timeout=30,
        )
        status_response.raise_for_status()
        payload = status_response.json()
        print(json.dumps(payload, indent=2))
        if payload["status"] in {"completed", "failed"}:
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
