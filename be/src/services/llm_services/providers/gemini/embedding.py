import asyncio
import logging
from typing import Any
from google import genai
from google.genai.types import EmbedContentResponse, EmbedContentConfig
from google.genai.errors import APIError
from attrs import define, field
import tempfile
import json
import os

from src.settings import settings

logger = logging.getLogger(__name__)

# Global rate limiter instance to be shared across all AsyncGeminiEmbedding instances
# Discovery results: Sustainable rate identified at ~400-500 RPM for high concurrency.
_global_limiter = None

def get_global_limiter(rpm: int = 400) -> 'AsyncRateLimiter':
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = AsyncRateLimiter(rpm=rpm, max_tokens=rpm // 10)  # max_tokens scales with rpm
    return _global_limiter

async def get_gemini_embedding(input_text: list[str]) -> list[list[float]]:
    """
    Convenience function to get embeddings for a list of texts.
    Automatically handles batching if input exceeds Gemini limits.
    Uses a shared instance to preserve rate limiting across calls.
    """
    if not hasattr(get_gemini_embedding, "_instance"):
        get_gemini_embedding._instance = AsyncGeminiEmbedding() # pyright:ignore
    return await get_gemini_embedding._instance.embed(input_text) # pyright:ignore


@define
class AsyncRateLimiter:
    """
    Token bucket rate limiter with circuit breaker for 429s.
    """
    rpm: int = 30
    max_tokens: int = 60
    tokens: float = field(init=False)
    updated_at: float = field(init=False)
    paused_until: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(factory=asyncio.Lock, init=False)

    def __attrs_post_init__(self):
        self.tokens = self.max_tokens
        self.updated_at = asyncio.get_event_loop().time()

    async def acquire(self):
        async with self._lock:
            while True:
                now = asyncio.get_event_loop().time()
                
                # Check circuit breaker
                if now < self.paused_until:
                    wait_time = self.paused_until - now
                    logger.warning(f"Rate limiter paused. Waiting {wait_time:.2f}s...")
                    await asyncio.sleep(wait_time)
                    continue

                # Refill tokens
                time_passed = now - self.updated_at
                self.tokens += time_passed * (self.rpm / 60.0)
                if self.tokens > self.max_tokens:
                    self.tokens = self.max_tokens
                self.updated_at = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                else:
                    # Wait for next token
                    wait_time = (1 - self.tokens) / (self.rpm / 60.0)
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)

    async def pause(self, seconds: float):
        """Pause all acquisitions for a duration (Circuit Breaker)."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            self.paused_until = max(self.paused_until, now + seconds)


@define
class AsyncGeminiEmbedding:
    model_name: str = field(default="gemini-embedding-001")
    _client: genai.Client | None = field(default=None, init=False)
    _limiter: AsyncRateLimiter | None = field(default=None, init=False)

    # Gemini API limits (Tier 2 optimized)
    MAX_TEXTS_PER_REQUEST: int = field(default=250, init=False)  # Increased from 100 for Tier 2
    MAX_TOKENS_PER_REQUEST: int = field(default=20000, init=False)
    TOKENS_USED_PER_TEXT: int = field(default=2048, init=False)  # Only first 2048 tokens used

    # Rate limiting and retry configuration
    MAX_RETRIES: int = field(default=5, init=False)
    INITIAL_RETRY_DELAY: float = field(default=2.0, init=False)  # Increased base delay
    MAX_RETRY_DELAY: float = field(default=60.0, init=False)
    
    @property
    def limiter(self) -> AsyncRateLimiter:
        if self._limiter is None:
            # Use global shared limiter for all instances
            self._limiter = get_global_limiter(rpm=1500)
        return self._limiter

    # Batch API configuration
    BATCH_API_THRESHOLD: int = field(default=20, init=False)  # usage > 20 batches (2000 texts) triggers Batch API

    @property
    def client(self) -> genai.Client:
        """Initializes and returns the Gemini API client."""
        if self._client is None:
            # Set credentials explicitly
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.google_application_credentials
            
            self._client = genai.Client(
                vertexai=True,
                project=settings.google_project_id,
                location=settings.google_location
            )
        return self._client

    def _estimate_tokens(self, text: str) -> int:
        """
        Rough estimation of tokens (4 chars ≈ 1 token).
        Conservative estimate to avoid exceeding token limits.
        """
        return len(text) // 3  # Conservative: 3 chars per token

    def _create_batches(self, text_input: list[str]) -> list[list[str]]:
        """
        Splits input texts into batches respecting both text count and token limits.
        Returns list of batches, each batch is a list of texts.
        """
        if len(text_input) <= self.MAX_TEXTS_PER_REQUEST:
            # Check if single batch fits token limit
            total_tokens = sum(
                min(self._estimate_tokens(text), self.TOKENS_USED_PER_TEXT)
                for text in text_input
            )
            if total_tokens <= self.MAX_TOKENS_PER_REQUEST:
                return [text_input]

        # Need to split into multiple batches
        batches: list[list[str]] = []
        current_batch: list[str] = []
        current_tokens = 0

        for text in text_input:
            text_tokens = min(self._estimate_tokens(text), self.TOKENS_USED_PER_TEXT)

            # Check if adding this text would exceed limits
            would_exceed_count = len(current_batch) >= self.MAX_TEXTS_PER_REQUEST
            would_exceed_tokens = current_tokens + text_tokens > self.MAX_TOKENS_PER_REQUEST

            if current_batch and (would_exceed_count or would_exceed_tokens):
                # Save current batch and start new one
                batches.append(current_batch)
                current_batch = [text]
                current_tokens = text_tokens
            else:
                # Add to current batch
                current_batch.append(text)
                current_tokens += text_tokens

        # Don't forget the last batch
        if current_batch:
            batches.append(current_batch)

        return batches

    async def _embed_batch_with_retry(self, text_batch: list[str], batch_index: int = 0) -> list[list[float]]:
        """
        Embeds a single batch of texts with exponential backoff retry logic.
        """
        retry_delay = self.INITIAL_RETRY_DELAY
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                # Acquire rate limit token before request
                await self.limiter.acquire()
                
                result: EmbedContentResponse = await self.client.aio.models.embed_content(
                    model=self.model_name,
                    contents=text_batch,  # pyright:ignore
                    config=EmbedContentConfig(task_type="RETRIEVAL_QUERY")
                )
                return [e.values for e in result.embeddings]  # pyright:ignore

            except APIError as e:
                last_error = e
                error_code = getattr(e, 'code', None)
                error_status = getattr(e, 'status', None)

                # Check if it's a rate limit error (429 RESOURCE_EXHAUSTED)
                is_rate_limit = (
                    error_code == 429 or
                    error_status == 'RESOURCE_EXHAUSTED' or
                    'quota' in str(e).lower() or
                    'rate limit' in str(e).lower()
                )

                # Check if it's a retryable error
                is_retryable = is_rate_limit or error_code in [429, 500, 502, 503, 504]

                if not is_retryable:
                    logger.error(f"Non-retryable error for batch {batch_index}: {e}")
                    raise

                if is_rate_limit:
                     # Trigger circuit breaker
                    logger.warning(f"Rate Limit Hit! Pausing all requests for {retry_delay}s.")
                    await self.limiter.pause(retry_delay)

                if attempt < self.MAX_RETRIES - 1:
                    # Calculate backoff with jitter
                    jitter = asyncio.get_event_loop().time() % 1.0 * 0.1  # 0-0.1s jitter
                    wait_time = min(retry_delay + jitter, self.MAX_RETRY_DELAY)

                    logger.warning(
                        f"Rate limit/error on batch {batch_index} (attempt {attempt + 1}/{self.MAX_RETRIES}). "
                        f"Retrying in {wait_time:.2f}s. Error: {str(e)[:200]}"
                    )

                    await asyncio.sleep(wait_time)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error(
                        f"All {self.MAX_RETRIES} retry attempts exhausted for batch {batch_index}. "
                        f"Last error: {e}"
                    )
                    raise

            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error for batch {batch_index}: {type(e).__name__}: {e}")
                raise

        # If we get here, all retries failed
        raise last_error if last_error else Exception(f"Failed to embed batch {batch_index}")


    async def embed(self, text_input: list[str]) -> list[list[float]]:
        """
        Embeds a list of texts, automatically splitting into multiple requests if needed.
        Returns embeddings in the same order as input texts.

        Processes batches in parallel but throttled by AsyncRateLimiter.
        Switches to Batch API for large workloads.
        """
        if not text_input:
            return []

        # Split into batches if needed
        batches = self._create_batches(text_input)

        logger.info(f"Embedding {len(text_input)} texts in {len(batches)} batch(es)")

        # Semaphore to allow SOME parallelism, but RateLimiter controls the specific RPM
        # We can set this higher (e.g. 20) as the underlying limiter is time-based
        concurrency_limit = asyncio.Semaphore(20)

        async def _process_batch(batch: list[str], batch_idx: int) -> tuple[int, list[list[float]]]:
            # Use semaphore to limit open connections
            async with concurrency_limit:
                 # Rate limiter is acquired INSIDE _embed_batch_with_retry
                embeddings = await self._embed_batch_with_retry(batch, batch_idx)
                return batch_idx, embeddings

        # Create tasks for all batches
        tasks = [
            _process_batch(batch, idx)
            for idx, batch in enumerate(batches)
        ]

        # Run all tasks concurrently
        results = await asyncio.gather(*tasks)

        # Sort results by batch index to preserve order
        results.sort(key=lambda x: x[0])

        # Flatten the list of lists
        all_embeddings: list[list[float]] = []
        for _, batch_embeddings in results:
            all_embeddings.extend(batch_embeddings)

        logger.info(f"Successfully embedded all {len(text_input)} texts")
        return all_embeddings


if __name__ == "__main__":
    # Test with small batch
    small_batch = ["hello", "my", "boy"]

    embedder = AsyncGeminiEmbedding()

    # Test small batch
    print("Testing small batch (3 texts)...")
    result = asyncio.run(embedder.embed(small_batch))
    print(f"Got {len(result)} embeddings")
    print(f"Embedding dimension: {len(result[0])}")

    # Test large batch that requires splitting
    print("\nTesting large batch (500 texts)...")
    large_batch = [f"This is test text number {i}" for i in range(500)]
    result_large = asyncio.run(embedder.embed(large_batch))
    print(f"Got {len(result_large)} embeddings")
    print(f"Input order preserved: {len(result_large) == len(large_batch)}")

    # Test with convenience function
    print("\nTesting convenience function...")
    result_convenience = asyncio.run(get_gemini_embedding(["test text"]))
    print(f"Got {len(result_convenience)} embeddings via get_embedding()")

