from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.services.project_chat.access import ProjectChatAccessScope
from src.services.project_chat.telemetry import ProjectChatTelemetryState
from src.services.project_chat.telemetry import RetrievalProgressNotifier
from src.services.project_chat.telemetry import ToolEventNotifier


@dataclass(slots=True)
class ProjectChatAgentDeps:
    project_id: UUID
    project_name: str
    project_description: str | None
    active_revision: str
    access_scope: ProjectChatAccessScope
    selected_norms: list[str]
    include_document_ids: list[str]
    api_base_path: str
    session_factory: Callable[[], AbstractContextManager[Session]]
    retrieval_service: object
    telemetry_state: ProjectChatTelemetryState
    tool_event_notifier: ToolEventNotifier | None
    retrieval_progress_notifier: RetrievalProgressNotifier | None


class RetrievedChunk(BaseModel):
    chunk_id: int | None = None
    text: str
    score: float | None = None
    kind: str | None = None


class RetrievedDocument(BaseModel):
    document_id: str
    title: str
    path: str
    browser_url: str
    summary: str | None
    short_summary: str | None
    doc_metadata: dict
    chunks: list[RetrievedChunk]


class RetrievalPayload(BaseModel):
    queries: list[str]
    documents: list[RetrievedDocument]
