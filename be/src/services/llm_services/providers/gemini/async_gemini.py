"""
Async Gemini provider using the google-genai package.

Simple prompt-in / text-out interface, mirroring AsyncGroqProvider so it can be
used anywhere a basic text LLM provider is required (e.g. fast inference, heads,
document pipeline). For full agent behaviour (tools, thread history) use
AsyncGeminiAgent instead.
"""

from __future__ import annotations

import json
import logging
from functools import cached_property
from pathlib import Path
from typing import Any, Optional, Union

try:
    from google import genai
    from google.genai.types import Content
    from google.genai.types import GenerateContentConfig
    from google.genai.types import Part
    from google.genai.types import ThinkingConfig
except Exception:  # pragma: no cover - optional import
    genai = None  # type: ignore[assignment]
    Content = Any  # type: ignore[misc,assignment]
    GenerateContentConfig = Any  # type: ignore[misc,assignment]
    Part = Any  # type: ignore[misc,assignment]
    ThinkingConfig = Any  # type: ignore[misc,assignment]

from src.settings import settings

logger = logging.getLogger(__name__)

# Mime types for image file extensions (for image_paths as file paths).
_EXT_TO_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class AsyncGeminiProvider:
    """
    Simple async Gemini provider using the google-genai package.

    Mirrors the shape of AsyncGroqProvider: single prompt in, text (or JSON)
    out. Supports optional image inputs (file paths or raw bytes). Uses the same
    client setup as AsyncGeminiAgent (api_key via settings).
    """

    def __init__(
        self,
        model_name: str = "gemini-2.5-flash",
        *,
        api_key: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.input_tokens: int = 0
        self.output_tokens: int = 0

    @cached_property
    def client(self) -> genai.Client:
        if genai is None:
            raise ImportError("google-genai is not available in this environment.")
        api_key = self.api_key or settings.gemini_api_key
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY environment variable not set.")
        return genai.Client(api_key=api_key)

    def _build_parts(
        self,
        prompt: str,
        image_paths: Optional[list[str] | list[bytes]] = None,
    ) -> list[Part]:
        parts: list[Part] = [Part.from_text(text=prompt.strip())]
        if not image_paths:
            return parts

        for item in image_paths:
            if isinstance(item, str):
                path = Path(item)
                if not path.exists():
                    logger.warning("Image path does not exist: %s", item)
                    continue
                data = path.read_bytes()
                suffix = path.suffix.lower()
                mime = _EXT_TO_MIME.get(suffix, "image/png")
                parts.append(Part.from_bytes(data=data, mime_type=mime))
            elif isinstance(item, bytes):
                parts.append(Part.from_bytes(data=item, mime_type="image/png"))
            else:
                logger.warning("Skipping unsupported image_paths item type: %s", type(item))
        return parts

    async def get_response(
        self,
        prompt: str,
        temperature: float = 0.0,
        full_response: bool = False,
        image_paths: Optional[list[str] | list[bytes]] = None,
        format: bool = False,
        return_tokens: bool = False,
        stream: bool = False,
        thinking_level: Optional[str] = None,
    ) -> Union[str, dict[str, Any], Any]:
        """
        Non-streaming text response, similar to AsyncGroqProvider.get_response.

        Supports optional image_paths (file paths or raw bytes). When format=True,
        response is requested as JSON and parsed before return (unless
        full_response=True). thinking_level: optional Gemini thinking level
        (e.g. "low", "medium", "high", "minimal"); only applies to thinking-capable models.
        """
        if stream:
            # Simple provider: only non-streaming. Use AsyncGeminiAgent for streaming.
            pass

        parts = self._build_parts(prompt, image_paths)
        contents = [Content(role="user", parts=parts)]

        config = GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json" if format else None,
        )
        if thinking_level is not None:
            config.thinking_config = ThinkingConfig(thinking_level=thinking_level)  # pyright: ignore[assignment]

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
        except Exception as e:
            logger.exception("Gemini API error: %s", e)
            raise

        in_tok = 0
        out_tok = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            in_tok = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            out_tok = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        self.input_tokens += in_tok
        self.output_tokens += out_tok

        if full_response:
            return response

        content = (response.text or "").strip()

        if format:
            try:
                parsed: Union[str, dict[str, Any]] = json.loads(content)
            except json.JSONDecodeError:
                parsed = content
            if return_tokens:
                return (parsed, in_tok, out_tok)
            return parsed

        if return_tokens:
            return (content, in_tok, out_tok)
        return content

    def __repr__(self) -> str:
        return f"AsyncGeminiProvider(model_name='{self.model_name}')"
