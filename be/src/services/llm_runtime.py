from __future__ import annotations

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from src.services.llm_services.providers.gemini.async_gemini import AsyncGeminiProvider
from src.settings import settings


def build_project_llm(provider: str, model: str, *, api_key: str | None = None) -> AsyncGeminiProvider:
    normalized = provider.lower().strip()
    if normalized == "gemini":
        return AsyncGeminiProvider(model_name=model, api_key=api_key)
    raise ValueError(f"Unsupported AI provider for indexing: {provider}")


def build_project_chat_model(
    provider: str,
    model: str,
    *,
    api_key: str | None = None,
) -> GoogleModel:
    normalized = provider.lower().strip()
    if normalized != "gemini":
        raise ValueError(f"Unsupported AI provider for chat: {provider}")
    return GoogleModel(
        model_name=model,
        provider=GoogleProvider(api_key=api_key or settings.gemini_api_key),
    )
