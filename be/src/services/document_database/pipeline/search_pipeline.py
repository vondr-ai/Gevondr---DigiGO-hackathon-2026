from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from attrs import define
from attrs import field

from src.database.weaviate.repos.document_index_repo import VectorDocumentIndexRepository
from src.database.weaviate.repos.document_index_repo import get_vector_document_index_repo
from src.monitoring import INDEX_SEARCH_STAGE_DURATION
from src.monitoring import INDEX_SEARCH_STAGE_EVENTS
from src.services.document_database.logging.search_logging import log_search_event
from src.services.llm_services.providers.jina.jina import JinaReranker
from src.settings import settings

logger = logging.getLogger(__name__)

SUMMARY_STAGE = "vector_summary_search"
CHUNK_STAGE = "vector_chunk_search"
RERANK_STAGE = "jina_rerank"
OVERALL_STAGE = "overall"


def _record_search_stage(stage: str, duration: float, status: str) -> None:
    INDEX_SEARCH_STAGE_DURATION.labels(stage, status).observe(max(duration, 0.0))
    INDEX_SEARCH_STAGE_EVENTS.labels(stage, status).inc()


@define
class ProjectSearchPipeline:
    repo: VectorDocumentIndexRepository = field(factory=get_vector_document_index_repo)

    def search(
        self,
        *,
        project_id: UUID,
        query: str,
        active_revision: str,
        selected_norms: list[str] | None = None,
        allowed_role_codes: list[str] | None = None,
        include_document_ids: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"index_revision": active_revision}
        if selected_norms:
            filters["selected_norms"] = selected_norms
        if allowed_role_codes:
            filters["allowed_role_codes"] = allowed_role_codes

        overall_start = time.perf_counter()
        stage_durations: dict[str, float] = {}
        top_results: list[dict[str, Any]] = []
        try:
            summary_start = time.perf_counter()
            summary_results = self.repo.search(
                project_id=project_id,
                query=query,
                search_in="summaries",
                filters=filters,
                document_ids=include_document_ids,
                limit=max(limit, 30),
            )
            stage_durations[SUMMARY_STAGE] = time.perf_counter() - summary_start
            _record_search_stage(SUMMARY_STAGE, stage_durations[SUMMARY_STAGE], "success")

            chunk_start = time.perf_counter()
            chunk_results = self.repo.search(
                project_id=project_id,
                query=query,
                search_in="chunks",
                filters=filters,
                document_ids=include_document_ids,
                limit=max(limit, 30),
            )
            stage_durations[CHUNK_STAGE] = time.perf_counter() - chunk_start
            _record_search_stage(CHUNK_STAGE, stage_durations[CHUNK_STAGE], "success")

            combined = self._combine_results(summary_results, chunk_results)
            reranked = self._maybe_rerank(query, combined, stage_durations)
            top_results = reranked[:limit]
            return top_results
        finally:
            total_duration = time.perf_counter() - overall_start
            _record_search_stage(OVERALL_STAGE, total_duration, "success")
            log_search_event(
                project_id,
                UUID(int=0),
                query,
                stage_durations,
                total_duration,
                top_results,
            )

    def _combine_results(
        self,
        summary_results: list[dict[str, Any]],
        chunk_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        combined = []
        for item in summary_results:
            item = dict(item)
            item["type"] = "summary"
            combined.append(item)
        for item in chunk_results:
            item = dict(item)
            item["type"] = "chunk"
            combined.append(item)
        combined.sort(key=lambda item: item.get("score") or 0.0, reverse=True)
        return combined

    def _maybe_rerank(
        self,
        query: str,
        combined_results: list[dict[str, Any]],
        stage_durations: dict[str, float],
    ) -> list[dict[str, Any]]:
        if not combined_results or not settings.jina_api_key:
            return combined_results
        texts = [item.get("text", "") for item in combined_results[:30]]
        if not any(texts):
            return combined_results
        reranker = JinaReranker()
        start = time.perf_counter()
        try:
            rerank_results = reranker.rerank(
                query=query,
                text_list=texts,
                top_n=min(len(texts), 30),
            )
        except Exception as exc:
            logger.warning("Reranker failed: %s", exc)
            stage_durations[RERANK_STAGE] = time.perf_counter() - start
            _record_search_stage(RERANK_STAGE, stage_durations[RERANK_STAGE], "failure")
            return combined_results

        stage_durations[RERANK_STAGE] = time.perf_counter() - start
        _record_search_stage(RERANK_STAGE, stage_durations[RERANK_STAGE], "success")

        reranked: list[dict[str, Any]] = []
        used_indices: set[int] = set()
        for result in rerank_results:
            if result.index >= len(combined_results):
                continue
            entry = dict(combined_results[result.index])
            entry["rerank_score"] = result.relevance_score
            reranked.append(entry)
            used_indices.add(result.index)
        reranked.extend(
            combined_results[index]
            for index in range(len(combined_results))
            if index not in used_indices
        )
        return reranked
