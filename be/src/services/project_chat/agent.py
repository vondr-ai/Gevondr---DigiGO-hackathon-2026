from __future__ import annotations

from typing import Any

from pydantic_ai import Agent
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.messages import ModelRequest
from pydantic_ai.messages import ModelResponse
from pydantic_ai.messages import TextPart
from pydantic_ai.messages import UserPromptPart

from src.services.llm_runtime import build_project_chat_model
from src.services.project_chat.models import ProjectChatAgentDeps
from src.services.project_chat.prompting import render_project_chat_system_prompt
from src.services.project_chat.retrieval import ProjectChatRetrievalService


def build_project_chat_agent(
    *,
    provider: str,
    model_name: str,
    api_key: str | None,
) -> Agent[ProjectChatAgentDeps, str]:
    agent = Agent(
        build_project_chat_model(provider, model_name, api_key=api_key),
        deps_type=ProjectChatAgentDeps,
        output_type=str,
    )

    @agent.instructions
    def project_chat_prompt(ctx: RunContext[ProjectChatAgentDeps]) -> str:
        return render_project_chat_system_prompt(
            project_name=ctx.deps.project_name,
            project_description=ctx.deps.project_description,
            actor_type=ctx.deps.access_scope.actor_type,
            resolved_role=ctx.deps.access_scope.resolved_role,
            selected_norms=ctx.deps.selected_norms,
        )

    @agent.tool
    async def search_project(
        ctx: RunContext[ProjectChatAgentDeps],
        question: str,
    ) -> dict[str, Any]:
        retrieval_service = ctx.deps.retrieval_service
        assert isinstance(retrieval_service, ProjectChatRetrievalService)
        notifier = ctx.deps.tool_event_notifier
        if notifier is not None:
            await notifier({"tool": "search_project", "phase": "started"})
        with ctx.deps.session_factory() as session:
            payload = await retrieval_service.retrieve(
                session=session,
                project_id=ctx.deps.project_id,
                active_revision=ctx.deps.active_revision,
                query=question,
                scope=ctx.deps.access_scope,
                selected_norms=ctx.deps.selected_norms,
                include_document_ids=ctx.deps.include_document_ids,
                api_base_path=ctx.deps.api_base_path,
                progress_notifier=ctx.deps.retrieval_progress_notifier,
            )
        unique_document_count = ctx.deps.telemetry_state.register_documents(
            [document.document_id for document in payload.documents]
        )
        if notifier is not None:
            await notifier(
                {
                    "tool": "search_project",
                    "phase": "completed",
                    "uniqueDocumentCount": unique_document_count,
                }
            )
        return payload.model_dump(mode="json")

    return agent


def build_message_history(messages: list[dict[str, str]]) -> list[ModelMessage]:
    history: list[ModelMessage] = []
    for item in messages:
        role = item["role"]
        content = item["content"]
        if role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=content)]))
    return history
