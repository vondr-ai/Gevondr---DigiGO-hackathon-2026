from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

from pydantic_ai.messages import ModelRequest
from pydantic_ai.messages import ModelResponse

from src.services.project_chat.access import ProjectChatAccessScope
from src.services.project_chat.agent import build_message_history
from src.services.project_chat.prompting import render_project_chat_system_prompt
from src.services.project_chat.retrieval import ProjectChatRetrievalService


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _FakeSession:
    def __init__(self, documents) -> None:
        self.documents = documents

    def scalars(self, _statement):
        return _ScalarResult(self.documents)


class _FakePipeline:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        self._document_id = str(uuid4())

    def search(self, **kwargs):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.calls.append(kwargs["query"])
        try:
            time.sleep(0.05)
            return [
                {
                    "document_id": self._document_id,
                    "title": "Roof inspection.txt",
                    "text": f"hit for {kwargs['query']}",
                    "chunk_id": len(self.calls),
                    "path": "/docs/roof-inspection.txt",
                    "score": 0.9 - (0.01 * len(self.calls)),
                    "type": "chunk",
                }
            ]
        finally:
            with self._lock:
                self.active -= 1


def test_retrieval_expands_queries_runs_concurrently_and_hydrates_documents() -> None:
    pipeline = _FakePipeline()
    service = ProjectChatRetrievalService(search_pipeline=pipeline)
    project_id = uuid4()
    revision_id = uuid4()
    document_id = uuid4()
    scope = ProjectChatAccessScope(
        project_id=project_id,
        actor_type="consumer",
        party_id="consumer-1",
        owner_party_id="owner-1",
        resolved_role="Aannemer",
        allowed_role_codes=["Aannemer"],
    )
    document = SimpleNamespace(
        id=document_id,
        project_id=project_id,
        index_revision_id=revision_id,
        title="Roof inspection.txt",
        path="/docs/roof-inspection.txt",
        summary="Roof was inspected in 2019.",
        short_summary="Roof inspection",
        doc_metadata={"source": "test"},
        allowed_role_codes=["Aannemer"],
    )
    session = _FakeSession([document])
    pipeline._document_id = str(document_id)

    result = asyncio.run(
        service.retrieve(
            session=session,
            project_id=project_id,
            active_revision=str(revision_id),
            query="When was the roof inspected?",
            scope=scope,
            selected_norms=["NEN-2580"],
            include_document_ids=None,
            api_base_path="/api/v1",
        )
    )

    assert 2 <= len(result.queries) <= 4
    assert len(pipeline.calls) == len(result.queries)
    assert pipeline.max_active >= 2
    assert len(result.documents) == 1
    hydrated = result.documents[0]
    assert hydrated.summary == "Roof was inspected in 2019."
    assert hydrated.short_summary == "Roof inspection"
    assert hydrated.doc_metadata == {"source": "test"}
    assert hydrated.browser_url == f"/api/v1/projects/{project_id}/documents/{document_id}/open"
    assert 1 <= len(hydrated.chunks) <= 3


def test_retrieval_emits_progress_as_query_batches_finish() -> None:
    pipeline = _FakePipeline()
    service = ProjectChatRetrievalService(search_pipeline=pipeline)
    project_id = uuid4()
    revision_id = uuid4()
    document_id = uuid4()
    scope = ProjectChatAccessScope(
        project_id=project_id,
        actor_type="consumer",
        party_id="consumer-1",
        owner_party_id="owner-1",
        resolved_role="Aannemer",
        allowed_role_codes=["Aannemer"],
    )
    document = SimpleNamespace(
        id=document_id,
        project_id=project_id,
        index_revision_id=revision_id,
        title="Roof inspection.txt",
        path="/docs/roof-inspection.txt",
        summary="Roof was inspected in 2019.",
        short_summary="Roof inspection",
        doc_metadata={"source": "test"},
        allowed_role_codes=["Aannemer"],
    )
    session = _FakeSession([document])
    pipeline._document_id = str(document_id)
    progress_events: list[dict] = []

    async def _progress(payload: dict) -> None:
        progress_events.append(payload)

    result = asyncio.run(
        service.retrieve(
            session=session,
            project_id=project_id,
            active_revision=str(revision_id),
            query="When was the roof inspected?",
            scope=scope,
            selected_norms=["NEN-2580"],
            include_document_ids=None,
            api_base_path="/api/v1",
            progress_notifier=_progress,
        )
    )

    assert len(result.documents) == 1
    assert progress_events[0]["phase"] == "started"
    assert progress_events[0]["sourcesUsed"] == 0
    progress_updates = [event for event in progress_events if event["phase"] == "progress"]
    assert len(progress_updates) == len(result.queries)
    assert all(event["completedQueries"] >= 1 for event in progress_updates)
    assert progress_events[-1]["phase"] == "completed"
    assert progress_events[-1]["sourcesUsed"] == len(result.documents)


def test_system_prompt_contains_required_rules() -> None:
    prompt = render_project_chat_system_prompt(
        project_name="Stationsplein",
        project_description="Renovation archive",
        actor_type="consumer",
        resolved_role="Aannemer",
        selected_norms=["NEN-2580"],
    )

    assert "always perform 2 to 4 search variations" in prompt.lower()
    assert "always cite documents with markdown links" in prompt.lower()
    assert "never mention a document that was not retrieved" in prompt.lower()


def test_message_history_preserves_prior_assistant_turns() -> None:
    history = build_message_history(
        [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
        ]
    )

    assert len(history) == 2
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)
    assert history[0].parts[0].content == "First question"
    assert history[1].parts[0].content == "First answer"
