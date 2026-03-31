from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from pydantic_ai import Agent

from src.services.project_chat.models import ProjectChatAgentDeps

logger = logging.getLogger(__name__)


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_agent_markdown(
    *,
    agent: Agent[ProjectChatAgentDeps, str],
    prompt: str,
    deps: ProjectChatAgentDeps,
    message_history,
) -> AsyncIterator[str]:
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        await queue.put(sse_event(event, data))

    async def emit_tool_event(payload: dict) -> None:
        await emit("tool", payload)

    async def emit_retrieval_event(payload: dict) -> None:
        await emit("retrieval", payload)

    original_notifier = deps.tool_event_notifier
    original_retrieval_notifier = deps.retrieval_progress_notifier

    async def notify_tool_event(payload: dict) -> None:
        if original_notifier is not None:
            await original_notifier(payload)
        await emit_tool_event(payload)

    async def notify_retrieval_event(payload: dict) -> None:
        if original_retrieval_notifier is not None:
            await original_retrieval_notifier(payload)
        await emit_retrieval_event(payload)

    deps.tool_event_notifier = notify_tool_event
    deps.retrieval_progress_notifier = notify_retrieval_event

    async def run_agent() -> None:
        await emit("status", {"phase": "started"})
        try:
            async with agent.run_stream(prompt, deps=deps, message_history=message_history) as result:
                async for chunk in result.stream_text(delta=True):
                    if chunk:
                        await emit("token", {"text": chunk})
                output = await result.get_output()
                usage = result.usage()
                await emit(
                    "done",
                    {
                        "output": output,
                        "usage": {
                            "requests": usage.requests,
                            "inputTokens": usage.input_tokens,
                            "outputTokens": usage.output_tokens,
                        },
                    },
                )
        except Exception as exc:
            logger.exception("Project chat stream failed")
            await emit("error", {"message": str(exc)})
        finally:
            await queue.put(None)

    task = asyncio.create_task(run_agent())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        deps.tool_event_notifier = original_notifier
        deps.retrieval_progress_notifier = original_retrieval_notifier
        await task
