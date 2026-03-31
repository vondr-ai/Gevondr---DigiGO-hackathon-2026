from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import DatasourceORM
from src.database.models import StagedDocumentORM
from src.database.models import StagedFolderORM
from src.services.storage import datasource_staging_root
from src.services.storage import sha256_for_path


@dataclass(slots=True)
class StagingSyncResult:
    folders: int
    documents: int
    created_documents: list[dict[str, Any]]
    updated_documents: list[dict[str, Any]]
    deleted_documents: list[dict[str, Any]]


def sync_datasource_staging(
    session: Session,
    *,
    datasource: DatasourceORM,
    root_path: str | None = None,
) -> StagingSyncResult:
    base_root = datasource_staging_root(datasource.project_id, datasource.id).resolve()
    scan_root = (base_root / root_path).resolve() if root_path else base_root.resolve()
    if not scan_root.exists():
        scan_root.mkdir(parents=True, exist_ok=True)

    folder_rows = session.scalars(
        select(StagedFolderORM).where(StagedFolderORM.datasource_id == datasource.id)
    ).all()
    doc_rows = session.scalars(
        select(StagedDocumentORM).where(StagedDocumentORM.datasource_id == datasource.id)
    ).all()
    folder_by_path = {row.path: row for row in folder_rows}
    doc_by_path = {row.path: row for row in doc_rows}

    discovered_folders: list[tuple[Path, str]] = []
    discovered_docs: list[tuple[Path, str]] = []
    for item in sorted(scan_root.rglob("*")):
        rel = item.relative_to(base_root).as_posix()
        if item.is_dir():
            discovered_folders.append((item, rel))
        elif item.is_file():
            discovered_docs.append((item, rel))
    discovered_folder_paths: set[str] = {
        rel for _, rel in discovered_folders
    }
    discovered_doc_paths: set[str] = {
        rel for _, rel in discovered_docs
    }
    for file_path, rel in discovered_docs:
        _ = file_path
        parent_rel = str(Path(rel).parent).replace("\\", "/")
        if parent_rel != "." and parent_rel:
            discovered_folder_paths.add(parent_rel)

    discovered_folder_paths.update(rel for _, rel in discovered_folders)
    deleted_documents = [
        {
            "documentId": str(row.id),
            "fileName": row.filename,
            "path": row.path,
        }
        for row in doc_rows
        if row.path not in discovered_doc_paths
    ]

    if discovered_doc_paths:
        session.execute(
            delete(StagedDocumentORM).where(
                StagedDocumentORM.datasource_id == datasource.id,
                StagedDocumentORM.path.not_in(discovered_doc_paths),
            )
        )
    else:
        session.execute(
            delete(StagedDocumentORM).where(
                StagedDocumentORM.datasource_id == datasource.id,
            )
        )
    if discovered_folder_paths:
        session.execute(
            delete(StagedFolderORM).where(
                StagedFolderORM.datasource_id == datasource.id,
                StagedFolderORM.path.not_in(discovered_folder_paths),
            )
        )
    else:
        session.execute(
            delete(StagedFolderORM).where(
                StagedFolderORM.datasource_id == datasource.id,
            )
        )

    folder_mapping: dict[str, StagedFolderORM] = {}
    for _, rel in sorted(discovered_folders, key=lambda item: item[1].count("/")):
        discovered_folder_paths.add(rel)
        existing = folder_by_path.get(rel)
        parent_path = str(Path(rel).parent).replace("\\", "/")
        if parent_path == ".":
            parent_path = ""
        parent_row = folder_mapping.get(parent_path) or folder_by_path.get(parent_path)
        if existing is None:
            existing = StagedFolderORM(
                datasource_id=datasource.id,
                project_id=datasource.project_id,
                name=Path(rel).name,
                path=rel,
                parent_id=parent_row.id if parent_row else None,
            )
            session.add(existing)
            session.flush()
        else:
            existing.name = Path(rel).name
            existing.parent_id = parent_row.id if parent_row else None
        folder_mapping[rel] = existing

    created_documents: list[dict[str, Any]] = []
    updated_documents: list[dict[str, Any]] = []
    for file_path, rel in discovered_docs:
        discovered_doc_paths.add(rel)
        folder_path = str(Path(rel).parent).replace("\\", "/")
        if folder_path == ".":
            folder_path = ""
        folder_row = folder_mapping.get(folder_path) or folder_by_path.get(folder_path)
        existing = doc_by_path.get(rel)
        if existing is None:
            file_sha256 = sha256_for_path(file_path)
            existing = StagedDocumentORM(
                datasource_id=datasource.id,
                project_id=datasource.project_id,
                folder_id=folder_row.id if folder_row else None,
                filename=file_path.name,
                path=rel,
                storage_path=str(file_path.resolve()),
                size=file_path.stat().st_size,
                sha256=file_sha256,
                mime_type=None,
                status="ready",
            )
            session.add(existing)
            session.flush()
            created_documents.append(
                {
                    "documentId": str(existing.id),
                    "fileName": existing.filename,
                    "path": existing.path,
                }
            )
        else:
            new_storage_path = str(file_path.resolve())
            new_size = file_path.stat().st_size
            new_sha256 = sha256_for_path(file_path)
            changed = (
                existing.folder_id != (folder_row.id if folder_row else None)
                or existing.filename != file_path.name
                or existing.storage_path != new_storage_path
                or existing.size != new_size
                or existing.sha256 != new_sha256
                or existing.status != "ready"
                or existing.error_message is not None
            )
            existing.folder_id = folder_row.id if folder_row else None
            existing.filename = file_path.name
            existing.storage_path = new_storage_path
            existing.size = new_size
            existing.sha256 = new_sha256
            existing.status = "ready"
            existing.error_message = None
            if changed:
                updated_documents.append(
                    {
                        "documentId": str(existing.id),
                        "fileName": existing.filename,
                        "path": existing.path,
                    }
                )

    datasource.status = "synced"
    return StagingSyncResult(
        folders=len(discovered_folder_paths),
        documents=len(discovered_doc_paths),
        created_documents=created_documents,
        updated_documents=updated_documents,
        deleted_documents=deleted_documents,
    )


def build_datasource_tree(
    folders: list[StagedFolderORM],
    documents: list[StagedDocumentORM],
) -> dict[str, Any]:
    folder_nodes: dict[UUID, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []

    for folder in folders:
        folder_nodes[folder.id] = {
            "id": str(folder.id),
            "path": folder.path,
            "type": "folder",
            "name": folder.name,
            "children": [],
        }

    for folder in folders:
        node = folder_nodes[folder.id]
        if folder.parent_id and folder.parent_id in folder_nodes:
            folder_nodes[folder.parent_id]["children"].append(node)
        else:
            roots.append(node)

    for doc in documents:
        node = {
            "id": str(doc.id),
            "path": doc.path,
            "type": "file",
            "name": doc.filename,
            "size": doc.size,
        }
        if doc.folder_id and doc.folder_id in folder_nodes:
            folder_nodes[doc.folder_id]["children"].append(node)
        else:
            roots.append(node)

    if len(roots) == 1:
        return {"root": roots[0]}
    return {
        "root": {
            "id": "root",
            "path": "/",
            "type": "folder",
            "name": "root",
            "children": roots,
        }
    }
