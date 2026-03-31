from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

from src.services.project_chat.access import ProjectChatAccessScope
from src.services.project_chat.models import ProjectChatAgentDeps
from src.services.project_chat.streaming import stream_agent_markdown
from src.services.project_chat.telemetry import ProjectChatTelemetryState


async def _collect_events(stream) -> list[str]:
    events: list[str] = []
    async for item in stream:
        events.append(item)
    return events


class _FakeStreamResult:
    def __init__(self, deps: ProjectChatAgentDeps) -> None:
        self._deps = deps

    async def __aenter__(self) -> "_FakeStreamResult":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def stream_text(self, *, delta: bool = True):
        assert delta is True
        assert self._deps.retrieval_progress_notifier is not None
        await self._deps.retrieval_progress_notifier(
            {"phase": "started", "queryCount": 4, "completedQueries": 0, "sourcesUsed": 0}
        )
        await asyncio.sleep(0)
        await self._deps.retrieval_progress_notifier(
            {
                "phase": "progress",
                "queryCount": 4,
                "completedQueries": 2,
                "sourcesUsed": 5,
            }
        )
        await self._deps.retrieval_progress_notifier(
            {
                "phase": "completed",
                "queryCount": 4,
                "completedQueries": 4,
                "sourcesUsed": 2,
            }
        )
        yield "Hello"
        yield " world"

    async def get_output(self) -> str:
        return "Hello world"

    def usage(self):
        return SimpleNamespace(requests=1, input_tokens=2, output_tokens=3)


class _FakeAgent:
    def run_stream(self, prompt: str, *, deps: ProjectChatAgentDeps, message_history):
        assert prompt == "When?"
        assert message_history == []
        return _FakeStreamResult(deps)


def _build_deps() -> ProjectChatAgentDeps:
    return ProjectChatAgentDeps(
        project_id=uuid4(),
        project_name="Chat Project",
        project_description=None,
        active_revision=str(uuid4()),
        access_scope=ProjectChatAccessScope(
            project_id=uuid4(),
            actor_type="provider",
            party_id="provider-1",
            owner_party_id="provider-1",
            resolved_role=None,
            allowed_role_codes=None,
        ),
        selected_norms=[],
        include_document_ids=[],
        api_base_path="/api/v1",
        session_factory=lambda: nullcontext(),
        retrieval_service=object(),
        telemetry_state=ProjectChatTelemetryState(),
        tool_event_notifier=None,
        retrieval_progress_notifier=None,
    )


def test_telemetry_state_tracks_unique_documents_across_multiple_tool_calls() -> None:
    state = ProjectChatTelemetryState()

    assert state.register_documents(["doc-a", "doc-b"]) == 2
    assert state.register_documents(["doc-b", "doc-c"]) == 3
    assert state.unique_document_count == 3


def test_stream_agent_markdown_emits_retrieval_events_before_tokens() -> None:
    deps = _build_deps()

    events = asyncio.run(
        _collect_events(
            stream_agent_markdown(
                agent=_FakeAgent(),
                prompt="When?",
                deps=deps,
                message_history=[],
            )
        )
    )

    payload = "".join(events)
    assert "event: status" in payload
    assert '"phase": "started"' in payload
    assert 'event: retrieval\ndata: {"phase": "started", "queryCount": 4' in payload
    assert '"completedQueries": 0' in payload
    assert '"sourcesUsed": 0' in payload
    assert 'event: retrieval\ndata: {"phase": "progress", "queryCount": 4' in payload
    assert '"completedQueries": 2' in payload
    assert '"sourcesUsed": 5' in payload
    assert 'event: retrieval\ndata: {"phase": "completed", "queryCount": 4' in payload
    assert '"completedQueries": 4' in payload
    assert '"sourcesUsed": 2' in payload
    assert 'event: token\ndata: {"text": "Hello"}' in payload
    assert 'event: token\ndata: {"text": " world"}' in payload
    assert payload.index("event: retrieval") < payload.index("event: token")
    assert 'event: done' in payload
