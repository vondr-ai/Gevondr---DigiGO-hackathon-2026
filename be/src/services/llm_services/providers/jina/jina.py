# src\services\llm_services\providers\jina.py
from __future__ import annotations

import logging
import math
import time
from typing import Any

import requests
from attr import define
from requests import HTTPError, Response
from tqdm import tqdm
from src.settings import settings


# Define a constant for the maximum batch size allowed by the Jina Embeddings API
JINA_EMBEDDING_MAX_BATCH_SIZE = 500

# Retry config for transient Jina API errors (5xx, 429)
JINA_EMBEDDING_MAX_RETRIES = 4
JINA_EMBEDDING_INITIAL_BACKOFF_SEC = 2.0
JINA_EMBEDDING_BACKOFF_MULTIPLIER = 2.0

logger = logging.getLogger(__name__)


@define
class RerankerResult:
    """Represents a reranked item with its index, relevance score, and associated text.

    Attributes:
        index (int): The position of the item in the original list.
        relevance_score (float): The relevance score assigned by the reranker.
        text (str): The content of the item.
    """

    index: int
    relevance_score: float
    text: str


@define
class JinaReranker:
    """A reranker that uses Jina's API to rerank a list of documents based on their relevance to a query.

    Methods:
        rerank(query: str, text_list: list[str], top_n: int) -> Optional[list[RerankerResult]]:
            Sends a request to Jina's API to rerank the provided text list according to the query.
        get_model_name() -> str: returns the string of the model name
    """

    required_credentials: list[str] = ["JINA_API_KEY"]
    model: str = "jina-reranker-v3"

    def get_model_name(self) -> str:
        """Returns the name of the model."""
        return self.model

    def rerank(
        self, query: str, text_list: list[str], top_n: int
    ) -> list[RerankerResult]:
        """Reranks a list of text documents based on their relevance to the query using Jina's API.

        Args:
            query (str): The query string for which documents are being reranked.
            text_list (list[str]): The list of documents (texts) to be reranked.
            top_n (int): The number of top relevant documents to return.

        Returns:
            Optional[list[RerankerResult]]: A list of reranked items with their relevance scores and text,
            or None if the request fails.
        """
        if not text_list:
            return []

        api_key: str | None = settings.jina_api_key
        assert api_key
        if not api_key:
            raise ValueError("No API key for the Jina Reranker has been set")

        url = "https://api.jina.ai/v1/rerank"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        data = {
            "model": self.model,
            "query": query,
            "documents": text_list,
            "top_n": top_n,
        }

        try:
            response: Response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            response_json: Any = response.json()

            return [
                RerankerResult(
                    index=r["index"],
                    relevance_score=r["relevance_score"],
                    text=text_list[r["index"]],
                )
                for r in response_json.get("results", [])
            ]

        except requests.RequestException as e:
            raise ValueError(f"Request failed: {e}")
        except ValueError as e:
            raise ValueError(f"Something went wrong parsing the resulf: {e}")


def _is_retryable_status(status_code: int) -> bool:
    """True for 5xx server errors and 429 rate limit."""
    return status_code >= 500 or status_code == 429


def _get_jina_embedding_batch(batch: list[str], late_chunking: bool = False) -> list[list[float]]:
    """Get Jina embeddings for a single batch with retries for transient errors (5xx, 429)."""
    url = "https://api.jina.ai/v1/embeddings"
    api_key: str | None = settings.jina_api_key
    assert api_key, "JINA_API_KEY environment variable not set"

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    assert isinstance(batch, list), "Batch must be a list"
    for i in batch:
        assert isinstance(i, str), "All batch items must be strings"

    data = {
        "model": "jina-embeddings-v3",
        "task": "retrieval.query",
        "dimensions": 1024,
        "late_chunking": late_chunking,
        "embedding_type": "float",
        "input": batch,
    }

    last_error: Exception | None = None
    backoff = JINA_EMBEDDING_INITIAL_BACKOFF_SEC

    for attempt in range(JINA_EMBEDDING_MAX_RETRIES):
        try:
            response = requests.post(url, headers=headers, json=data)
            if not response.ok:
                if _is_retryable_status(response.status_code) and attempt < JINA_EMBEDDING_MAX_RETRIES - 1:
                    logger.warning(
                        "Jina API %s (attempt %s/%s), retrying in %.1fs: %s",
                        response.status_code,
                        attempt + 1,
                        JINA_EMBEDDING_MAX_RETRIES,
                        backoff,
                        response.text[:200],
                    )
                    time.sleep(backoff)
                    backoff *= JINA_EMBEDDING_BACKOFF_MULTIPLIER
                    continue
                logger.error("Jina API error: %s - %s", response.status_code, response.text[:500])
            response.raise_for_status()
            response_json = response.json()

            if "data" not in response_json:
                raise ValueError(f"Unexpected API response: {response_json}")

            return [e["embedding"] for e in response_json["data"]]
        except HTTPError as http_err:
            last_error = http_err
            if _is_retryable_status(getattr(http_err.response, "status_code", 0)) and attempt < JINA_EMBEDDING_MAX_RETRIES - 1:
                logger.warning(
                    "Jina API HTTP error (attempt %s/%s), retrying in %.1fs: %s",
                    attempt + 1,
                    JINA_EMBEDDING_MAX_RETRIES,
                    backoff,
                    http_err,
                )
                time.sleep(backoff)
                backoff *= JINA_EMBEDDING_BACKOFF_MULTIPLIER
            else:
                logger.error("Jina API HTTP error: %s", http_err)
                raise
        except Exception as err:
            last_error = err
            logger.exception("Jina embedding batch error: %s", err)
            raise

    if last_error:
        raise last_error
    raise RuntimeError("Jina embedding batch failed after retries")


def get_jina_embedding(input: list[str]) -> list[list[float]]:
    """Get Jina embeddings, handling API batch size limits.

    Args:
        input (list[str]): The list of strings to embed.

    Returns:
        list[list[float]]: A list containing lists of floats as vectors.
    """
    if not input:
        return []

    api_key: str | None = settings.jina_api_key
    if not api_key:
        raise EnvironmentError("JINA_API_KEY environment variable not set.")

    num_batches = math.ceil(len(input) / JINA_EMBEDDING_MAX_BATCH_SIZE)

    all_embeddings: list[list[float]] = []
    
    # Using tqdm to show progress per batch
    for i in tqdm(range(0, len(input), JINA_EMBEDDING_MAX_BATCH_SIZE), desc="Processing Jina Batches", total=num_batches):
        batch = input[i : i + JINA_EMBEDDING_MAX_BATCH_SIZE]
        try:
            batch_embeddings = _get_jina_embedding_batch(batch, False)
            all_embeddings.extend(batch_embeddings)
        except Exception as e:
            logger.exception("Failed to process Jina batch starting at index %s: %s", i, e)
            raise

    return all_embeddings
