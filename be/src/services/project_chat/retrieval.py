from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import IndexedDocumentORM
from src.services.document_database.pipeline.search_pipeline import ProjectSearchPipeline
from src.services.project_chat.access import ProjectChatAccessScope
from src.services.project_chat.models import RetrievedChunk
from src.services.project_chat.models import RetrievedDocument
from src.services.project_chat.models import RetrievalPayload
from src.services.project_chat.telemetry import RetrievalProgressNotifier
from src.services.project_chat.telemetry import build_retrieval_progress_event


@dataclass(slots=True)
class ProjectChatRetrievalService:
    search_pipeline: ProjectSearchPipeline

    def __init__(self, search_pipeline: ProjectSearchPipeline | None = None) -> None:
        self.search_pipeline = search_pipeline or ProjectSearchPipeline()

    async def retrieve(
        self,
        *,
        session: Session,
        project_id: UUID,
        active_revision: str,
        query: str,
        scope: ProjectChatAccessScope,
        selected_norms: list[str] | None,
        include_document_ids: list[str] | None,
        api_base_path: str,
        progress_notifier: RetrievalProgressNotifier | None = None,
        limit_per_query: int = 12,
        max_documents: int = 8,
        max_chunks_per_document: int = 3,
    ) -> RetrievalPayload:
        expanded_queries = self._expand_queries(query)
        if progress_notifier is not None:
            await progress_notifier(
                build_retrieval_progress_event(
                    phase="started",
                    query_count=len(expanded_queries),
                    completed_queries=0,
                    sources_used=0,
                )
            )

        pending_batches = [
            asyncio.create_task(
                asyncio.to_thread(
                    self.search_pipeline.search,
                    project_id=project_id,
                    query=expanded_query,
                    active_revision=active_revision,
                    selected_norms=selected_norms,
                    allowed_role_codes=scope.allowed_role_codes,
                    include_document_ids=include_document_ids,
                    limit=limit_per_query,
                )
            )
            for expanded_query in expanded_queries
        ]

        running_document_ids: set[str] = set()
        batches: list[list[dict[str, Any]]] = []
        for completed_queries, batch_task in enumerate(asyncio.as_completed(pending_batches), start=1):
            hits = await batch_task
            batches.append(hits)
            for hit in hits:
                document_id = hit.get("document_id")
                if document_id:
                    running_document_ids.add(document_id)
            if progress_notifier is not None:
                await progress_notifier(
                    build_retrieval_progress_event(
                        phase="progress",
                        query_count=len(expanded_queries),
                        completed_queries=completed_queries,
                        sources_used=len(running_document_ids),
                    )
                )

        seen_pairs: set[tuple[str, int | None, str | None]] = set()
        grouped_hits: dict[str, list[dict[str, Any]]] = {}
        for hits in batches:
            for hit in hits:
                document_id = hit.get("document_id")
                if not document_id:
                    continue
                dedupe_key = (
                    document_id,
                    hit.get("chunk_id"),
                    hit.get("type"),
                )
                if dedupe_key in seen_pairs:
                    continue
                seen_pairs.add(dedupe_key)
                grouped_hits.setdefault(document_id, []).append(dict(hit))

        if not grouped_hits:
            if progress_notifier is not None:
                await progress_notifier(
                    build_retrieval_progress_event(
                        phase="completed",
                        query_count=len(expanded_queries),
                        completed_queries=len(expanded_queries),
                        sources_used=0,
                    )
                )
            return RetrievalPayload(queries=expanded_queries, documents=[])

        orm_documents = session.scalars(
            select(IndexedDocumentORM).where(
                IndexedDocumentORM.project_id == project_id,
                IndexedDocumentORM.index_revision_id == UUID(active_revision),
                IndexedDocumentORM.id.in_([UUID(document_id) for document_id in grouped_hits]),
            )
        ).all()

        documents: list[RetrievedDocument] = []
        for orm_document in orm_documents:
            if not scope.is_provider_owner and scope.allowed_role_codes:
                if not set(scope.allowed_role_codes).intersection(orm_document.allowed_role_codes or []):
                    continue
            hits = grouped_hits.get(str(orm_document.id), [])
            chunks = [
                RetrievedChunk(
                    chunk_id=hit.get("chunk_id"),
                    text=hit.get("text") or "",
                    score=hit.get("score"),
                    kind=hit.get("type"),
                )
                for hit in sorted(
                    hits,
                    key=lambda item: item.get("score") or 0.0,
                    reverse=True,
                )[:max_chunks_per_document]
                if (hit.get("text") or "").strip()
            ]
            documents.append(
                RetrievedDocument(
                    document_id=str(orm_document.id),
                    title=orm_document.title,
                    path=orm_document.path,
                    browser_url=f"{api_base_path}/projects/{project_id}/documents/{orm_document.id}/open",
                    summary=orm_document.summary,
                    short_summary=orm_document.short_summary,
                    doc_metadata=orm_document.doc_metadata or {},
                    chunks=chunks,
                )
            )

        documents.sort(key=self._document_score, reverse=True)
        final_documents = documents[:max_documents]
        if progress_notifier is not None:
            await progress_notifier(
                build_retrieval_progress_event(
                    phase="completed",
                    query_count=len(expanded_queries),
                    completed_queries=len(expanded_queries),
                    sources_used=len(final_documents),
                )
            )
        return RetrievalPayload(
            queries=expanded_queries,
            documents=final_documents,
        )

    def _expand_queries(self, query: str) -> list[str]:
        base = query.strip()
        variants = [
            base,
            f"{base} summary",
            f"{base} evidence",
            f"{base} key findings",
        ]
        expanded: list[str] = []
        for variant in variants:
            normalized = variant.strip()
            if normalized and normalized not in expanded:
                expanded.append(normalized)
        if len(expanded) < 2:
            expanded.append(f"{base} details")
        return expanded[:4]

    @staticmethod
    def _document_score(document: RetrievedDocument) -> float:
        if not document.chunks:
            return 0.0
        return max(chunk.score or 0.0 for chunk in document.chunks)
