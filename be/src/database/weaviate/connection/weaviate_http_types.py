"""Response types compatible with the Weaviate v4 Python client's return shapes.

These dataclasses mirror the objects returned by the Weaviate v4 client so that
the repository classes (weaviate_repo, document_index_repo, email_vector_repo)
can work with either the real gRPC client or the HTTP-only adapter without changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from uuid import UUID


@dataclass
class HttpMetadata:
    """Mirrors weaviate response object metadata."""

    score: float | None = None


@dataclass
class HttpWeaviateObject:
    """Mirrors a single Weaviate response object.

    Attributes match the access patterns used in the repos:
    - obj.uuid
    - obj.properties["key"]
    - obj.vector (dict with "default" key, or list)
    - obj.metadata.score
    """

    uuid: UUID
    properties: dict[str, Any]
    vector: dict[str, list[float]] | list[float] = field(default_factory=dict)
    metadata: HttpMetadata = field(default_factory=HttpMetadata)


@dataclass
class HttpQueryResponse:
    """Mirrors the response from collection.query.hybrid() / fetch_objects().

    Repos iterate: for obj in response.objects:
    """

    objects: list[HttpWeaviateObject] = field(default_factory=list)
