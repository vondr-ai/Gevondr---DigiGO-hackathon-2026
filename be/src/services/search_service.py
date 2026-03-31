from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import DelegationORM
from src.database.models import IndexedDocumentORM
from src.database.models import ProjectORM
from src.services.document_database.pipeline.search_pipeline import ProjectSearchPipeline


@dataclass(slots=True)
class SearchResultBundle:
    access_context: dict
    results: list[dict]
    totals: dict


def resolve_consumer_role(
    session: Session,
    *,
    project_id: UUID,
    consumer_party_id: str,
) -> str | None:
    delegation = session.scalars(
        select(DelegationORM).where(
            DelegationORM.project_id == project_id,
            DelegationORM.party_id == consumer_party_id,
        )
    ).first()
    return delegation.role_code if delegation else None


def list_consumer_projects(session: Session, consumer_party_id: str) -> list[dict]:
    delegations = session.scalars(
        select(DelegationORM).where(DelegationORM.party_id == consumer_party_id)
    ).all()
    items = []
    for delegation in delegations:
        project = session.get(ProjectORM, delegation.project_id)
        if project is None:
            continue
        accessible_count = session.scalars(
            select(IndexedDocumentORM).where(
                IndexedDocumentORM.project_id == project.id,
                IndexedDocumentORM.index_revision_id == project.active_index_revision_id,
            )
        ).all()
        accessible_count = [
            document
            for document in accessible_count
            if delegation.role_code in (document.allowed_role_codes or [])
        ]
        items.append(
            {
                "id": str(project.id),
                "name": project.name,
                "status": project.status,
                "resolvedRole": delegation.role_code,
                "accessibleFileCount": len(accessible_count),
            }
        )
    return items


def search_consumer_project(
    session: Session,
    *,
    project_id: UUID,
    consumer_party_id: str,
    query: str,
    selected_norms: list[str] | None,
    include_blocked: bool,
    page: int,
    page_size: int,
) -> SearchResultBundle:
    project = session.get(ProjectORM, project_id)
    if project is None:
        raise ValueError("Project not found")
    if project.active_index_revision_id is None:
        return SearchResultBundle(
            access_context={
                "consumerPartyId": consumer_party_id,
                "resolvedRole": None,
            },
            results=[],
            totals={"allowed": 0, "blocked": 0},
        )
    resolved_role = resolve_consumer_role(
        session,
        project_id=project_id,
        consumer_party_id=consumer_party_id,
    )
    if resolved_role is None:
        raise PermissionError("No delegation for this consumer")

    pipeline = ProjectSearchPipeline()
    allowed_hits = pipeline.search(
        project_id=project.id,
        query=query,
        active_revision=str(project.active_index_revision_id),
        selected_norms=selected_norms,
        allowed_role_codes=[resolved_role],
        limit=page * page_size,
    )
    allowed_hits = _dedupe_hits(allowed_hits)
    allowed_doc_ids = {UUID(hit["document_id"]) for hit in allowed_hits if hit.get("document_id")}
    blocked_hits: list[dict] = []
    if include_blocked:
        all_hits = pipeline.search(
            project_id=project.id,
            query=query,
            active_revision=str(project.active_index_revision_id),
            selected_norms=selected_norms,
            limit=page * page_size * 2,
        )
        blocked_hits = [
            hit
            for hit in all_hits
            if UUID(hit["document_id"]) not in allowed_doc_ids
        ]
        blocked_hits = _dedupe_hits(blocked_hits)

    doc_ids = list(
        {
            UUID(hit["document_id"])
            for hit in allowed_hits + blocked_hits
            if hit.get("document_id")
        }
    )
    documents = session.scalars(
        select(IndexedDocumentORM).where(IndexedDocumentORM.id.in_(doc_ids))
    ).all()
    documents_by_id = {document.id: document for document in documents}

    results: list[dict] = []
    for hit in allowed_hits:
        document = documents_by_id.get(UUID(hit["document_id"]))
        if document is None:
            continue
        results.append(
            {
                "documentId": str(document.id),
                "title": document.title,
                "snippet": hit.get("text") or document.short_summary,
                "access": "allowed",
                "path": document.path,
                "documentType": document.document_type,
                "valueStreams": document.value_streams or [],
            }
        )
    for hit in blocked_hits:
        document = documents_by_id.get(UUID(hit["document_id"]))
        if document is None:
            continue
        results.append(
            {
                "documentId": str(document.id),
                "title": document.title,
                "snippet": None,
                "access": "blocked",
                "path": document.path,
                "documentType": document.document_type,
                "valueStreams": document.value_streams or [],
            }
        )

    start = max((page - 1) * page_size, 0)
    end = start + page_size
    paged = results[start:end]
    return SearchResultBundle(
        access_context={
            "consumerPartyId": consumer_party_id,
            "resolvedRole": resolved_role,
        },
        results=paged,
        totals={
            "allowed": len(allowed_hits),
            "blocked": len(blocked_hits),
        },
    )


def _dedupe_hits(hits: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for hit in hits:
        document_id = hit.get("document_id")
        if not document_id or document_id in seen:
            continue
        seen.add(document_id)
        deduped.append(hit)
    return deduped


def get_consumer_document(
    session: Session,
    *,
    project_id: UUID,
    document_id: UUID,
    consumer_party_id: str,
) -> dict:
    project = session.get(ProjectORM, project_id)
    if project is None:
        raise ValueError("Project not found")
    resolved_role = resolve_consumer_role(
        session,
        project_id=project_id,
        consumer_party_id=consumer_party_id,
    )
    if resolved_role is None:
        raise PermissionError("No delegation for this consumer")
    document = session.get(IndexedDocumentORM, document_id)
    if document is None or document.project_id != project_id:
        raise ValueError("Document not found")
    if resolved_role not in (document.allowed_role_codes or []):
        raise PermissionError("Document access denied")
    return {
        "documentId": str(document.id),
        "title": document.title,
        "path": document.path,
        "snippet": document.short_summary,
        "documentType": document.document_type,
        "valueStreams": document.value_streams or [],
        "downloadUrl": f"/api/v1/consumer/projects/{project_id}/documents/{document.id}/download",
    }
