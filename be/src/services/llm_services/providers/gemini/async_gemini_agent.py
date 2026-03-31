from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Optional, Union

from attrs import define, field

# Google GenAI SDK imports
from google import genai
from google.genai.types import (
    Content,
    FunctionDeclaration,
    GenerateContentConfig,
    Part,
    ThinkingConfig,
    Tool,
)

from src.services.llm_services.models import (
    Message,
    MessageRole,
    MessageThread,
    ToolCall,
    ToolResponse,
    VondrTool,
)
from src.services.llm_services.tool_call_ids import generate_tool_call_id
from src.settings import settings

logger = logging.getLogger(__name__)


@define
class AsyncGeminiAgent:
    """
    An agent that interacts with the Google Gemini API asynchronously.
    """

    model_name: str
    log_results: bool = field(default=False)
    _client: genai.Client | None = field(default=None, init=False)

    @property
    def client(self) -> genai.Client:
        """Initializes and returns the Gemini API client."""
        if self._client is None:
            # Set credentials explicitly

            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    def _save_response_log(self, response: Any, method: str) -> None:
        """
        Saves the complete API response object to a JSON file in data/gemini_logs.

        Args:
            response: The complete response object from the Gemini API
            method: The method name that generated this response (e.g., 'get_response', 'get_response_stream')
        """
        if not self.log_results:
            return

        try:
            # Create the logs directory if it doesn't exist
            logs_dir = Path("data/gemini_logs")
            logs_dir.mkdir(parents=True, exist_ok=True)

            # Generate a unique filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{method}_{timestamp}_{uuid.uuid4().hex[:8]}.json"
            filepath = logs_dir / filename

            # Convert response to a serializable format
            # The Gemini response objects have a to_dict() or similar method
            try:
                if hasattr(response, "__dict__"):
                    response_dict = {
                        "timestamp": timestamp,
                        "method": method,
                        "model_name": self.model_name,
                        "response": str(response),  # Fallback to string representation
                        "response_attributes": {
                            k: str(v) for k, v in vars(response).items()
                        },
                    }
                else:
                    response_dict = {
                        "timestamp": timestamp,
                        "method": method,
                        "model_name": self.model_name,
                        "response": str(response),
                    }
            except Exception as e:
                # If conversion fails, log what we can
                response_dict = {
                    "timestamp": timestamp,
                    "method": method,
                    "model_name": self.model_name,
                    "response_str": str(response),
                    "error": f"Failed to serialize response: {str(e)}",
                }

            # Write to file
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(response_dict, f, indent=2, ensure_ascii=False)

            logger.debug("[LOG] Saved Gemini response to %s", filepath)

        except Exception as e:
            logger.error("[ERROR] Failed to save Gemini response log: %s", e)

    async def count_tokens_for_text(self, text: str) -> int:
        """
        Count tokens for a text string using Gemini's native tokenizer.

        Args:
            text: The text to count tokens for

        Returns:
            The number of tokens
        """
        try:
            # Use Gemini's count_tokens API - pass text directly
            response = await self.client.aio.models.count_tokens(
                model=self.model_name, contents=text
            )

            token_count = response.total_tokens or 0
            return token_count

        except Exception:
            # Fallback: rough estimation (4 chars per token)
            return len(text) // 4

    async def get_response(
        self,
        history: Optional[MessageThread] = None,
        tools: Optional[list[VondrTool]] = None,
        temperature: float = 1,
        format: bool = False,
        message_window_size: int = 10,
        return_tokens: bool = False,
        thinking_level: Optional[str] = None,
    ) -> Union[str, dict[str, Any], tuple[Union[str, dict[str, Any]], int, int]]:
        """
        Gets a non-streaming response from the Gemini model.

        If the model returns a text response, this method returns a string.
        If the model requests a tool call, it returns a dictionary with the tool call information.

        Args:
            history: The conversation history.
            tools: A list of available tools for the model to use.
            temperature: The sampling temperature for the model.
            thinking_level: Optional Gemini thinking level (e.g. "low", "medium", "high", "minimal");
                only applies to thinking-capable models.

        Returns:
            - str: The text response from the model.
            - dict: A dictionary containing tool calls if requested by the model.
        """
        _tool = self.map_vondr_tools_to_gemini_tool(tools) if tools else None
        gemini_tools: list[Tool] | None = [_tool] if _tool is not None else None
        gemini_history, system_instruction = self._convert_thread_to_gemini_history(
            history, message_window_size
        )

        if not gemini_history:
            raise ValueError(
                "Cannot start a request with no initial message in the history."
            )

        config = GenerateContentConfig(
            tools=gemini_tools,  # ty: ignore[invalid-argument-type]
            temperature=temperature,
        )

        if thinking_level is not None:
            config.thinking_config = ThinkingConfig(thinking_level=thinking_level)  # pyright: ignore[assignment]  # ty: ignore[invalid-argument-type]

        if system_instruction:
            config.system_instruction = system_instruction.content

        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=gemini_history,  # ty: ignore[invalid-argument-type]
            config=config,
        )

        # Log the complete response if logging is enabled
        self._save_response_log(response, "get_response")

        full_text_content = response.text or ""
        final_tool_calls = self._extract_tool_calls_with_signatures(response)

        # Extract token counts from response
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0)
            output_tokens = getattr(
                response.usage_metadata, "candidates_token_count", 0
            )

        if final_tool_calls:
            for func_call in final_tool_calls:
                logger.debug("function args: %s", func_call["function"]["arguments"])

        result: Union[str, dict[str, Any]]
        if final_tool_calls:
            result = {
                "role": "assistant",
                "content": full_text_content if full_text_content else None,
                "tool_calls": final_tool_calls,
            }
        else:
            result = full_text_content

        return (result, input_tokens, output_tokens) if return_tokens else result

    async def get_response_stream(
        self,
        history: Optional[MessageThread] = None,
        tools: Optional[list[VondrTool]] = None,
        temperature: float = 0.5,
        message_window_size: int = 30,
        thinking_level: Optional[str] = None,
    ) -> AsyncGenerator[Union[str, dict[str, Any]], None]:
        """
        Gets a streaming response from the Gemini model, yielding text chunks and a final tool call dictionary.
        This method is adapted to match the output format of the AsyncAzureOpenAIAgent.

        Args:
            history: The conversation history.
            tools: A list of available tools for the model to use.
            temperature: The sampling temperature for the model.
            thinking_level: Optional Gemini thinking level (e.g. "low", "medium", "high", "minimal");
                only applies to thinking-capable models.

        Yields:
            - str: Chunks of the text response.
            - dict: A single dictionary at the end if tool calls are present.
        """
        _tool = self.map_vondr_tools_to_gemini_tool(tools) if tools else None
        gemini_tools: list[Tool] | None = [_tool] if _tool is not None else None

        gemini_history, system_instruction = self._convert_thread_to_gemini_history(
            history, message_window_size
        )

        if not gemini_history:
            raise ValueError(
                "Cannot start a stream with no initial message in the history."
            )

        config = GenerateContentConfig(
            tools=gemini_tools,  # ty: ignore[invalid-argument-type]
            temperature=temperature,
        )

        if thinking_level is not None:
            config.thinking_config = ThinkingConfig(thinking_level=thinking_level)  # pyright: ignore[assignment]  # ty: ignore[invalid-argument-type]

        # Handle system instructions if they exist
        if system_instruction:
            config.system_instruction = system_instruction.content

        stream = await self.client.aio.models.generate_content_stream(
            model=self.model_name,
            contents=gemini_history,  # ty: ignore[invalid-argument-type]
            config=config,
        )

        full_text_content = ""
        final_tool_calls = []
        input_tokens = 0
        output_tokens = 0
        cached_input_tokens = 0
        all_chunks = []  # Store all chunks for logging

        async for chunk in stream:
            # Store chunk for logging if enabled
            if self.log_results:
                all_chunks.append(chunk)

            # Extract token usage if available
            if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                input_tokens = getattr(chunk.usage_metadata, "prompt_token_count", 0)
                output_tokens = getattr(
                    chunk.usage_metadata, "candidates_token_count", 0
                )
                cached_input_tokens = getattr(
                    chunk.usage_metadata, "cached_content_token_count", 0
                )

            if chunk.text:
                full_text_content += chunk.text
                yield chunk.text

            chunk_tool_calls = self._extract_tool_calls_with_signatures(chunk)
            if chunk_tool_calls:
                final_tool_calls.extend(chunk_tool_calls)

        # Log all chunks if logging is enabled
        if self.log_results and all_chunks:
            self._save_response_log(all_chunks, "get_response_stream")

        if final_tool_calls:
            yield {
                "content": full_text_content if full_text_content else None,
                "tool_calls": final_tool_calls,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_input_tokens": cached_input_tokens,
            }
        else:
            # Yield final dict with tokens even if no tool calls
            yield {
                "content": full_text_content if full_text_content else None,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_input_tokens": cached_input_tokens,
            }

    def _convert_thread_to_gemini_history(
        self, thread: Optional[MessageThread], message_window_size: int = 10
    ) -> tuple[list[Content], Message | None]:
        """
        Converts our internal MessageThread into the list of Content objects
        and extracts the system prompt as expected by the Gemini API.
        Limits history to the last N messages plus system prompt.
        """
        try:
            if not thread or not thread.messages:
                return [], None

            # Limit the history window first
            from src.agent.utils.prep_llm_history import _limit_history_window

            limited_thread = _limit_history_window(thread, message_window_size)

            gemini_history: list[Content] = []
            system_prompt: Message | None = None

            # Extract system prompt first
            for msg in limited_thread.messages:
                if msg.role == MessageRole.SYSTEM:
                    system_prompt = msg  # pyright: ignore[assignment]  # ty: ignore[invalid-assignment]
                    break

            # This list will hold the parts for the current model's turn
            model_parts = []

            for msg in limited_thread.messages:
                if msg.role == MessageRole.SYSTEM:
                    continue

                if msg.role == MessageRole.USER:
                    assert isinstance(msg, Message)
                    # Finalize any pending model turn before starting a user turn
                    if model_parts:
                        gemini_history.append(Content(role="model", parts=model_parts))
                        model_parts = []

                    text_content = msg.content or ""
                    if msg.documents:
                        doc_str = "\nUser Uploaded documents:"
                        for d in msg.documents:
                            doc_str += f"\n- {d.filename}"
                        text_content += doc_str

                    if msg.tool_options:
                        doc_str = "\nPressed tool buttons:"
                        for t_o in msg.tool_options:
                            doc_str += f"\n- {t_o.value}"
                        text_content += doc_str

                    parts = [Part.from_text(text=text_content)]
                    if msg.images:
                        from io import BytesIO

                        from PIL import Image as PILImage

                        for image in msg.images:
                            try:
                                # Handle both base64 strings and raw bytes
                                image_bytes = image.content
                                logger.debug(
                                    "Original image_bytes type: %s", type(image_bytes)
                                )
                                logger.debug("First 100 bytes: %s", image_bytes[:100])

                                if isinstance(image_bytes, str):
                                    # Remove data URL prefix if present
                                    if "," in image_bytes and image_bytes.startswith(
                                        "data:"
                                    ):
                                        image_bytes = image_bytes.split(",", 1)[1]
                                    # Decode base64
                                    image_bytes = base64.b64decode(image_bytes)
                                elif isinstance(image_bytes, bytes):
                                    # Check if it's base64-encoded bytes that need decoding
                                    try:
                                        # Try to decode as base64 if it looks like base64
                                        if image_bytes.startswith(b"data:"):
                                            # It's a data URL in bytes form
                                            image_bytes = image_bytes.split(b",", 1)[1]
                                        # Try base64 decode
                                        decoded = base64.b64decode(image_bytes)
                                        # Verify it's actually image data by checking magic bytes
                                        if decoded.startswith(
                                            b"\x89PNG"
                                        ) or decoded.startswith(b"\xff\xd8\xff"):
                                            image_bytes = decoded
                                    except Exception:
                                        # If decode fails, assume it's already raw image bytes
                                        pass

                                logger.debug(
                                    "After processing, first 20 bytes: %s",
                                    image_bytes[:20],
                                )
                                logger.debug("Total length: %s", len(image_bytes))

                                # Validate and potentially reprocess the image
                                image_buffer = BytesIO(image_bytes)
                                pil_image = PILImage.open(image_buffer)

                                # Convert to RGB if necessary (removes alpha channel issues)
                                if pil_image.mode not in ("RGB", "RGBA"):
                                    pil_image = pil_image.convert("RGB")

                                # Re-encode to ensure proper format
                                output_buffer = BytesIO()
                                image_format = (
                                    "JPEG"
                                    if "jpeg" in image.mime_type.lower()
                                    else "PNG"
                                )
                                pil_image.save(
                                    output_buffer, format=image_format, quality=95
                                )
                                clean_image_bytes = output_buffer.getvalue()

                                parts.append(
                                    Part.from_bytes(
                                        data=clean_image_bytes,
                                        mime_type=image.mime_type,
                                    )
                                )
                            except Exception as e:
                                logger.error("Error processing image: %s", e)
                                logger.error(
                                    "Image type: %s, mime_type: %s",
                                    type(image.content),
                                    image.mime_type,
                                )
                                # Try to use original bytes as last resort
                                try:
                                    img_data = (
                                        image.content
                                        if isinstance(image.content, bytes)
                                        else base64.b64decode(image.content)
                                    )
                                    parts.append(
                                        Part.from_bytes(
                                            data=img_data, mime_type=image.mime_type
                                        )
                                    )
                                except Exception as fallback_error:
                                    logger.error(
                                        "Fallback also failed: %s", fallback_error
                                    )

                    gemini_history.append(Content(role="user", parts=parts))

                elif msg.role == MessageRole.ASSISTANT:
                    assert isinstance(msg, Message)
                    if msg.content:
                        model_parts.append(Part.from_text(text=msg.content))

                elif msg.role == MessageRole.TOOL_CALL:
                    try:
                        assert isinstance(msg, ToolCall)
                        # FIX 1: Extract the actual arguments dictionary from the tool_call object
                        arguments_dict = json.loads(
                            msg.tool_call["function"]["arguments"]
                        )
                        part = Part.from_function_call(
                            name=msg.name, args=arguments_dict
                        )
                        signature_str = msg.thought_signature
                        if not signature_str and isinstance(msg.tool_call, dict):
                            signature_str = msg.tool_call.get("thought_signature")
                        decoded_signature = self._decode_thought_signature(
                            signature_str
                        )
                        if decoded_signature:
                            part.thought_signature = decoded_signature
                        model_parts.append(part)
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.error(
                            "[ERROR] Could not parse tool call arguments: %s", e
                        )
                        logger.error("[ERROR] Tool call data: %s", msg.tool_call)  # ty: ignore[unresolved-attribute]

                    except ValueError as e:
                        logger.error(
                            "[ERROR] ValueError in tool call processing: %s", e
                        )
                        raise e

                elif msg.role == MessageRole.TOOL_RESPONSE:
                    assert isinstance(msg, ToolResponse)
                    # Finalize the model turn that made the tool call before adding the tool response
                    if model_parts:
                        gemini_history.append(Content(role="model", parts=model_parts))
                        model_parts = []

                    # FIX 2: Find the original tool's NAME to use in the response.
                    tool_name_for_response = None
                    for prev_msg in reversed(limited_thread.messages):
                        if (
                            isinstance(prev_msg, ToolCall)
                            and prev_msg.tool_call_id == msg.tool_call_id
                        ):
                            tool_name_for_response = prev_msg.name
                            break

                    if not tool_name_for_response:
                        logger.warning(
                            "[WARNING] Could not find matching ToolCall for ToolResponse ID %s",
                            msg.tool_call_id,
                        )
                        continue

                    part = Part.from_function_response(
                        name=tool_name_for_response,  # Use the found function name
                        response={"result": msg.content or ""},
                    )
                    gemini_history.append(Content(role="tool", parts=[part]))

            # Append any remaining model parts at the end of the history
            if model_parts:
                gemini_history.append(Content(role="model", parts=model_parts))

            self._append_persistent_page_images(gemini_history, thread)
            return gemini_history, system_prompt

        except Exception as e:
            logger.exception(
                "[ERROR] Exception in _convert_thread_to_gemini_history: %s: %s",
                type(e).__name__,
                e,
            )
            raise

    def _append_persistent_page_images(
        self,
        gemini_history: list[Content],
        thread: Optional[MessageThread],
        max_images: int = 12,
    ) -> None:
        if not thread or not thread.messages:
            return

        persistent_images = []
        for msg in reversed(thread.messages):
            if isinstance(msg, ToolResponse) and msg.images:
                for img in reversed(msg.images):
                    persistent_images.append(img)
                    if len(persistent_images) >= max_images:
                        break
            elif isinstance(msg, Message) and msg.images:
                for img in reversed(msg.images):
                    persistent_images.append(img)
                    if len(persistent_images) >= max_images:
                        break
            if len(persistent_images) >= max_images:
                break

        if not persistent_images:
            return

        persistent_images = list(reversed(persistent_images))

        last_user_content = None
        for item in reversed(gemini_history):
            if getattr(item, "role", None) == "user":
                last_user_content = item
                break

        if last_user_content is None:
            text_part = Part.from_text(
                text=(
                    "Persistent page image context from read_pages tool calls. "
                    "Use these images as additional document context."
                )
            )
            parts = [text_part]
            for img in persistent_images:
                image_bytes = self._normalize_image_bytes(img.content)
                if image_bytes:
                    parts.append(
                        Part.from_bytes(data=image_bytes, mime_type=img.mime_type)
                    )
            gemini_history.append(Content(role="user", parts=parts))
            return

        parts = list(last_user_content.parts or [])
        parts.append(
            Part.from_text(
                text="Additional persistent page images from read_pages are attached."
            )
        )
        for img in persistent_images:
            image_bytes = self._normalize_image_bytes(img.content)
            if image_bytes:
                parts.append(Part.from_bytes(data=image_bytes, mime_type=img.mime_type))
        last_user_content.parts = parts

    @staticmethod
    def _normalize_image_bytes(content: bytes | str) -> bytes | None:
        try:
            if isinstance(content, bytes):
                return content
            if isinstance(content, str):
                raw = content
                if raw.startswith("data:") and "," in raw:
                    raw = raw.split(",", 1)[1]
                return base64.b64decode(raw)
        except Exception:
            return None
        return None

    def _extract_tool_calls_with_signatures(
        self, response: Any
    ) -> list[dict[str, Any]]:
        """Converts Gemini function call parts into the dict structure our agent expects."""
        tool_calls: list[dict[str, Any]] = []

        for part in self._iter_function_call_parts(response):
            func_call = getattr(part, "function_call", None)
            if not func_call:
                continue
            call_dict: dict[str, Any] = {
                "id": generate_tool_call_id(),
                "type": "function",
                "function": {
                    "name": func_call.name,
                    "arguments": json.dumps(func_call.args),
                },
            }
            encoded_signature = self._encode_thought_signature(
                getattr(part, "thought_signature", None)
            )
            if encoded_signature:
                call_dict["thought_signature"] = encoded_signature
            tool_calls.append(call_dict)

        if not tool_calls and getattr(response, "function_calls", None):
            for func_call in response.function_calls:
                call_dict = {
                    "id": generate_tool_call_id(),
                    "type": "function",
                    "function": {
                        "name": func_call.name,
                        "arguments": json.dumps(func_call.args),
                    },
                }
                tool_calls.append(call_dict)

        return tool_calls

    @staticmethod
    def _encode_thought_signature(signature: Optional[bytes]) -> Optional[str]:
        if not signature:
            return None
        try:
            return base64.b64encode(signature).decode("ascii")
        except Exception:
            return None

    @staticmethod
    def _decode_thought_signature(signature: Optional[str]) -> Optional[bytes]:
        if not signature:
            return None
        try:
            return base64.b64decode(signature.encode("ascii"))
        except Exception:
            return None

    @staticmethod
    def _iter_function_call_parts(response: Any) -> list[Part]:
        """Returns parts that contain function calls for the first candidate, if any."""
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return []
        first_candidate = candidates[0]
        content = getattr(first_candidate, "content", None)
        if not content:
            return []
        parts = getattr(content, "parts", None)
        if not parts:
            return []
        return [part for part in parts if getattr(part, "function_call", None)]

    def map_vondr_tools_to_gemini_tool(
        self, tools: Optional[list[VondrTool]]
    ) -> Tool | None:
        """Aggregates multiple VondrTool definitions into a single Gemini Tool object."""
        if not tools:
            return None

        declarations = [self.vondr_to_function_declaration(t) for t in tools]
        return Tool(function_declarations=declarations)

    @staticmethod
    def vondr_to_function_declaration(tool: VondrTool) -> FunctionDeclaration:
        """Converts a single VondrTool into a Google GenAI FunctionDeclaration."""

        def map_type(py_type: type) -> str:
            if py_type is str:
                return "string"
            if py_type is int:
                return "integer"
            if py_type is float:
                return "number"
            if py_type is bool:
                return "boolean"
            if py_type is list:
                return "array"  # Handle plain list
            if hasattr(py_type, "__origin__") and py_type.__origin__ is list:
                return "array"
            if hasattr(py_type, "__origin__") and py_type.__origin__ is dict:
                return "object"
            return "string"

        properties = {}
        required = []

        for arg in tool.arguments:
            type_str = map_type(arg.datatype)
            prop_schema: dict[str, Any] = {"type": type_str}

            if type_str == "array":
                prop_schema["items"] = {"type": "string"}

            if arg.description:
                prop_schema["description"] = arg.description

            properties[arg.arg] = prop_schema
            if arg.required:
                required.append(arg.arg)

        parameters_schema = {
            "type": "object",
            "properties": properties,
            "required": required,
        }
        return FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters=parameters_schema,  # pyright: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        )
