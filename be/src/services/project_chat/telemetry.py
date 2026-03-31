from __future__ import annotations

from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Any

EventNotifier = Callable[[dict[str, Any]], Awaitable[None]]
ToolEventNotifier = EventNotifier
RetrievalProgressNotifier = EventNotifier


@dataclass(slots=True)
class ProjectChatTelemetryState:
    presented_document_ids: set[str] = field(default_factory=set)

    def register_documents(self, document_ids: list[str]) -> int:
        self.presented_document_ids.update(document_ids)
        return len(self.presented_document_ids)

    @property
    def unique_document_count(self) -> int:
        return len(self.presented_document_ids)


def build_retrieval_progress_event(
    *,
    phase: str,
    query_count: int,
    sources_used: int,
    completed_queries: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "phase": phase,
        "queryCount": query_count,
        "sourcesUsed": sources_used,
    }
    if completed_queries is not None:
        payload["completedQueries"] = completed_queries
    return payload
