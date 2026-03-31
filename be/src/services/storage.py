from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path
from uuid import UUID

from src.settings import settings


def project_root(project_id: UUID) -> Path:
    return settings.storage_root / "projects" / str(project_id)


def datasource_staging_root(project_id: UUID, datasource_id: UUID) -> Path:
    path = project_root(project_id) / "datasources" / str(datasource_id) / "staging"
    path.mkdir(parents=True, exist_ok=True)
    return path


def stored_file_path(
    project_id: UUID,
    datasource_id: UUID,
    relative_path: str,
) -> Path:
    safe_parts = [part for part in Path(relative_path).parts if part not in {"..", "."}]
    target = datasource_staging_root(project_id, datasource_id).joinpath(*safe_parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def save_upload_bytes(
    *,
    project_id: UUID,
    datasource_id: UUID,
    relative_path: str,
    content: bytes,
) -> tuple[Path, str, str | None]:
    target = stored_file_path(project_id, datasource_id, relative_path)
    target.write_bytes(content)
    return target, sha256_for_path(target), mimetypes.guess_type(target.name)[0]


def copy_tree_into_staging(
    *,
    project_id: UUID,
    datasource_id: UUID,
    source_root: Path,
    target_subpath: str = "",
) -> Path:
    destination = stored_file_path(project_id, datasource_id, target_subpath or ".")
    if destination.is_file():
        destination = destination.parent
    destination.mkdir(parents=True, exist_ok=True)
    if target_subpath:
        destination = datasource_staging_root(project_id, datasource_id) / target_subpath
        destination.mkdir(parents=True, exist_ok=True)
    for item in source_root.rglob("*"):
        rel = item.relative_to(source_root)
        target = destination / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
    return destination


def sha256_for_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
