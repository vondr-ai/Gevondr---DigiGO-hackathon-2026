"""HTTP-only Weaviate client adapter for environments where gRPC is unavailable.

This is a drop-in replacement for weaviate.WeaviateClient that uses Weaviate's
REST API (v1) and GraphQL endpoint instead of gRPC. Designed for Azure Container
Apps which only support one transport protocol per ingress.

Usage:
    client = WeaviateHttpClient(base_url="https://weaviate:8080", api_key="...")
    # Use exactly like weaviate.WeaviateClient:
    client.collections.exists("MyCollection")
    collection = client.collections.get("MyCollection")
    collection.query.hybrid(query="...", vector=[...], alpha=0.5, limit=10)
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx

from src.database.weaviate.connection.weaviate_http_types import (
    HttpMetadata,
    HttpQueryResponse,
    HttpWeaviateObject,
)

log = logging.getLogger(__name__)


class _GraphQLEnum(str):
    """Marker for values that must be emitted as unquoted GraphQL enums."""

    pass


def _raise_for_status_with_body(resp: httpx.Response, context: str) -> None:
    """Raise an informative error that includes the response body."""
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = resp.text.strip()
        if body:
            raise RuntimeError(
                f"{context}: HTTP {resp.status_code} - {body}"
            ) from exc
        raise


def _find_schema_class(
    schema: dict[str, Any], class_name: str
) -> dict[str, Any] | None:
    """Find a class in a full /v1/schema response."""
    classes = schema.get("classes", [])
    for cls in classes:
        if cls.get("class") == class_name:
            return cls

    lowered_name = class_name.lower()
    for cls in classes:
        existing_name = cls.get("class")
        if isinstance(existing_name, str) and existing_name.lower() == lowered_name:
            return cls

    return None


# Weaviate REST API GraphQL value types per filter operator
_GRAPHQL_VALUE_KEY = {
    "Equal": "valueText",
    "NotEqual": "valueText",
    "LessThan": "valueText",
    "LessThanEqual": "valueText",
    "GreaterThan": "valueText",
    "GreaterThanEqual": "valueText",
    "ContainsAny": "valueText",
    "ContainsAll": "valueText",
}


def _graphql_value_key_for(operator: str, value: Any) -> str:
    """Determine the correct GraphQL where-filter valueXxx key."""
    if operator in ("ContainsAny", "ContainsAll"):
        if isinstance(value, list) and value:
            sample = value[0]
        else:
            sample = value
    else:
        sample = value

    if isinstance(sample, bool):
        return "valueBoolean"
    if isinstance(sample, int):
        return "valueInt"
    if isinstance(sample, float):
        return "valueNumber"
    if isinstance(sample, datetime):
        return "valueDate"
    return "valueText"


def _format_value(value: Any) -> Any:
    """Format a filter value for the GraphQL where clause."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_format_value(v) for v in value]
    return value


def _filter_to_where(filt: Any) -> dict[str, Any]:
    """Convert a weaviate Filter object tree to a GraphQL where dict.

    Supports:
    - _FilterValue: single condition (operator, target property, value)
    - _FilterAnd / _FilterOr: composite with .filters list
    """
    class_name = type(filt).__name__

    if class_name == "_FilterAnd":
        return {
            "operator": _GraphQLEnum("And"),
            "operands": [_filter_to_where(f) for f in filt.filters],
        }

    if class_name == "_FilterOr":
        return {
            "operator": _GraphQLEnum("Or"),
            "operands": [_filter_to_where(f) for f in filt.filters],
        }

    # _FilterValue
    op = filt.operator.value  # e.g. "Equal", "ContainsAny"
    target = filt.target if isinstance(filt.target, str) else str(filt.target)
    value = _format_value(filt.value)
    value_key = _graphql_value_key_for(op, value)

    return {
        "path": [target],
        "operator": _GraphQLEnum(op),
        value_key: value,
    }


def _build_properties_selection(properties: list[dict[str, Any]]) -> str:
    """Build the GraphQL property selection string from schema properties."""
    return " ".join(p["name"] for p in properties)


class _HttpBatchContext:
    """Accumulates objects and flushes them via POST /v1/batch/objects."""

    def __init__(
        self,
        http: httpx.Client,
        collection_name: str | None,
        batch_size: int,
    ):
        self._http = http
        self._collection_name = collection_name
        self._batch_size = batch_size
        self._buffer: list[dict[str, Any]] = []

    def add_object(
        self,
        uuid: UUID | None = None,
        properties: dict[str, Any] | None = None,
        vector: list[float] | None = None,
        collection: str | None = None,
    ) -> None:
        obj: dict[str, Any] = {
            "class": collection or self._collection_name,
            "properties": properties or {},
        }
        if uuid is not None:
            obj["id"] = str(uuid)
        if vector is not None:
            obj["vector"] = vector
        self._buffer.append(obj)

        if len(self._buffer) >= self._batch_size:
            self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        resp = self._http.post(
            "/v1/batch/objects",
            json={"objects": self._buffer},
        )
        _raise_for_status_with_body(resp, "Failed to batch insert Weaviate objects")
        self._buffer.clear()

    def __enter__(self) -> _HttpBatchContext:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._flush()


class _HttpBatchProxy:
    """Proxy for collection.batch.fixed_size() / dynamic() context managers."""

    def __init__(self, http: httpx.Client, collection_name: str | None):
        self._http = http
        self._collection_name = collection_name

    @contextmanager
    def fixed_size(
        self,
        batch_size: int = 1000,
        concurrent_requests: int = 4,
    ):
        ctx = _HttpBatchContext(self._http, self._collection_name, batch_size)
        try:
            yield ctx
        finally:
            ctx._flush()

    @contextmanager
    def dynamic(self):
        ctx = _HttpBatchContext(self._http, self._collection_name, batch_size=100)
        try:
            yield ctx
        finally:
            ctx._flush()


class _HttpDataProxy:
    """Proxy for collection.data operations (insert, update, delete)."""

    def __init__(self, http: httpx.Client, collection_name: str):
        self._http = http
        self._collection_name = collection_name

    def insert(
        self,
        uuid: UUID,
        properties: dict[str, Any],
        vector: list[float] | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "class": self._collection_name,
            "id": str(uuid),
            "properties": properties,
        }
        if vector is not None:
            body["vector"] = vector
        resp = self._http.post("/v1/objects", json=body)
        _raise_for_status_with_body(resp, "Failed to insert Weaviate object")

    def update(self, uuid: UUID, properties: dict[str, Any]) -> None:
        resp = self._http.patch(
            f"/v1/objects/{self._collection_name}/{uuid}",
            json={"properties": properties},
        )
        _raise_for_status_with_body(resp, "Failed to update Weaviate object")

    def delete_by_id(self, uuid: UUID) -> None:
        resp = self._http.delete(
            f"/v1/objects/{self._collection_name}/{uuid}",
        )
        # 404 is fine — object may already be deleted
        if resp.status_code != 404:
            _raise_for_status_with_body(resp, "Failed to delete Weaviate object")

    def delete_many(self, where: Any) -> None:
        where_filter = _filter_to_where(where)
        body = {
            "match": {
                "class": self._collection_name,
                "where": where_filter,
            },
        }
        resp = self._http.delete("/v1/batch/objects", json=body)
        _raise_for_status_with_body(resp, "Failed to delete Weaviate objects")


class _HttpQueryProxy:
    """Proxy for collection.query operations (hybrid, fetch_object_by_id, fetch_objects)."""

    def __init__(self, http: httpx.Client, collection_name: str):
        self._http = http
        self._collection_name = collection_name
        self._schema_cache: list[dict[str, Any]] | None = None

    def _get_schema_properties(self) -> list[dict[str, Any]]:
        if self._schema_cache is not None:
            return self._schema_cache
        resp = self._http.get(f"/v1/schema/{self._collection_name}")
        if resp.status_code == 200:
            self._schema_cache = resp.json().get("properties", [])
            return self._schema_cache

        schema_resp = self._http.get("/v1/schema")
        _raise_for_status_with_body(
            schema_resp,
            f"Failed to fetch schema for collection {self._collection_name}",
        )
        class_schema = _find_schema_class(schema_resp.json(), self._collection_name)
        if class_schema is None:
            raise RuntimeError(
                f"Collection '{self._collection_name}' not found in Weaviate schema"
            )
        self._schema_cache = class_schema.get("properties", [])
        return self._schema_cache

    def fetch_object_by_id(
        self,
        uuid: UUID,
        include_vector: bool = False,
    ) -> HttpWeaviateObject | None:
        params = {}
        if include_vector:
            params["include"] = "vector"
        resp = self._http.get(
            f"/v1/objects/{self._collection_name}/{uuid}",
            params=params,
        )
        if resp.status_code == 404:
            return None
        _raise_for_status_with_body(resp, "Failed to fetch Weaviate object by ID")
        data = resp.json()
        vector_data: dict[str, list[float]] | list[float] = {}
        if include_vector and "vector" in data:
            vector_data = {"default": data["vector"]}
        return HttpWeaviateObject(
            uuid=UUID(data["id"]),
            properties=data.get("properties", {}),
            vector=vector_data,
        )

    def hybrid(
        self,
        query: str,
        vector: list[float] | None = None,
        alpha: float = 0.5,
        limit: int = 10,
        filters: Any = None,
        return_metadata: Any = None,
    ) -> HttpQueryResponse:
        props = self._get_schema_properties()
        prop_selection = _build_properties_selection(props)

        # Build hybrid args
        hybrid_parts = [
            f'query: {json.dumps(query)}',
            f"alpha: {alpha}",
        ]
        if vector is not None:
            hybrid_parts.append(f"vector: {json.dumps(vector)}")
        hybrid_str = ", ".join(hybrid_parts)

        # Build where clause
        where_str = ""
        if filters is not None:
            where_dict = _filter_to_where(filters)
            where_str = f", where: {_dict_to_graphql(where_dict)}"

        gql = (
            "{ Get {"
            f" {self._collection_name}"
            f"(hybrid: {{{hybrid_str}}}"
            f"{where_str}"
            f", limit: {limit}"
            f") {{ {prop_selection}"
            " _additional { id score vector }"
            " } } }"
        )

        resp = self._http.post("/v1/graphql", json={"query": gql})
        _raise_for_status_with_body(resp, "Failed to execute Weaviate hybrid query")
        result = resp.json()

        if "errors" in result:
            raise RuntimeError(f"GraphQL errors: {result['errors']}")

        items = (
            result.get("data", {}).get("Get", {}).get(self._collection_name) or []
        )
        return self._parse_objects(items)

    def fetch_objects(
        self,
        filters: Any = None,
        limit: int = 100,
    ) -> HttpQueryResponse:
        props = self._get_schema_properties()
        prop_selection = _build_properties_selection(props)

        where_str = ""
        if filters is not None:
            where_dict = _filter_to_where(filters)
            where_str = f"where: {_dict_to_graphql(where_dict)}, "

        gql = (
            "{ Get {"
            f" {self._collection_name}"
            f"({where_str}limit: {limit})"
            f" {{ {prop_selection}"
            " _additional { id }"
            " } } }"
        )

        resp = self._http.post("/v1/graphql", json={"query": gql})
        _raise_for_status_with_body(resp, "Failed to execute Weaviate fetch query")
        result = resp.json()

        if "errors" in result:
            raise RuntimeError(f"GraphQL errors: {result['errors']}")

        items = (
            result.get("data", {}).get("Get", {}).get(self._collection_name) or []
        )
        return self._parse_objects(items)

    @staticmethod
    def _parse_objects(items: list[dict[str, Any]]) -> HttpQueryResponse:
        objects = []
        for item in items:
            additional = item.pop("_additional", {})
            obj_uuid = UUID(additional["id"]) if "id" in additional else UUID(int=0)
            score = additional.get("score")
            vector = additional.get("vector")

            obj = HttpWeaviateObject(
                uuid=obj_uuid,
                properties=item,
                vector={"default": vector} if vector else {},
                metadata=HttpMetadata(
                    score=float(score) if score is not None else None
                ),
            )
            objects.append(obj)
        return HttpQueryResponse(objects=objects)


class _HttpCollection:
    """Proxy for a single Weaviate collection with .query, .data, .batch."""

    def __init__(self, http: httpx.Client, collection_name: str):
        self.query = _HttpQueryProxy(http, collection_name)
        self.data = _HttpDataProxy(http, collection_name)
        self.batch = _HttpBatchProxy(http, collection_name)


class _HttpCollectionsManager:
    """Proxy for client.collections operations."""

    def __init__(self, http: httpx.Client):
        self._http = http

    def exists(self, name: str) -> bool:
        resp = self._http.get(f"/v1/schema/{name}")
        if resp.status_code == 200:
            return True
        if resp.status_code != 404:
            _raise_for_status_with_body(
                resp, f"Failed to check Weaviate collection '{name}'"
            )

        schema_resp = self._http.get("/v1/schema")
        _raise_for_status_with_body(
            schema_resp, f"Failed to list Weaviate schema for collection '{name}'"
        )
        return _find_schema_class(schema_resp.json(), name) is not None

    def get(self, name: str) -> _HttpCollection:
        return _HttpCollection(self._http, name)

    def create(
        self,
        name: str,
        vectorizer_config: Any = None,
        properties: list | None = None,
        vector_index_config: Any = None,
    ) -> None:
        schema: dict[str, Any] = {"class": name}

        # vectorizer
        if vectorizer_config is not None:
            vectorizer_val = getattr(vectorizer_config, "vectorizer", None)
            if vectorizer_val is not None:
                schema["vectorizer"] = vectorizer_val.value

        # vector index config
        if vector_index_config is not None:
            vi_cfg: dict[str, Any] = {}
            class_name = type(vector_index_config).__name__
            if "Flat" in class_name:
                vi_cfg["distance"] = "cosine"
                schema["vectorIndexType"] = "flat"
                quantizer = getattr(vector_index_config, "quantizer", None)
                if quantizer is not None:
                    vi_cfg["bq"] = {"enabled": True}
            if vi_cfg:
                schema["vectorIndexConfig"] = vi_cfg

        # properties
        if properties:
            schema["properties"] = []
            for prop in properties:
                p: dict[str, Any] = {"name": prop.name}
                dt = prop.dataType if hasattr(prop, "dataType") else prop.data_type
                if hasattr(dt, "value"):
                    p["dataType"] = [dt.value]
                else:
                    p["dataType"] = [str(dt)]
                schema["properties"].append(p)

        resp = self._http.post("/v1/schema", json=schema)
        if resp.status_code == 422 and self.exists(name):
            log.info("Weaviate collection '%s' already exists; continuing", name)
            return
        _raise_for_status_with_body(
            resp, f"Failed to create Weaviate collection '{name}'"
        )

    def delete(self, name: str) -> None:
        resp = self._http.delete(f"/v1/schema/{name}")
        if resp.status_code != 404:
            _raise_for_status_with_body(
                resp, f"Failed to delete Weaviate collection '{name}'"
            )

    def delete_all(self) -> None:
        resp = self._http.get("/v1/schema")
        _raise_for_status_with_body(resp, "Failed to list Weaviate schema")
        schema = resp.json()
        for cls in schema.get("classes", []):
            self.delete(cls["class"])


def _dict_to_graphql(d: dict[str, Any]) -> str:
    """Convert a Python dict to a GraphQL-style object string (unquoted keys).

    GraphQL where clauses use: {operator: And, operands: [...]}
    NOT JSON:                  {"operator": "And", "operands": [...]}
    """
    parts = []
    for key, value in d.items():
        parts.append(f"{key}: {_value_to_graphql(value)}")
    return "{" + ", ".join(parts) + "}"


def _value_to_graphql(value: Any) -> str:
    """Convert a Python value to its GraphQL literal representation."""
    if isinstance(value, _GraphQLEnum):
        return str(value)  # unquoted enum value
    if isinstance(value, dict):
        return _dict_to_graphql(value)
    if isinstance(value, list):
        items = [_value_to_graphql(v) for v in value]
        return "[" + ", ".join(items) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)  # properly quoted and escaped
    return json.dumps(str(value))


class WeaviateHttpClient:
    """Drop-in replacement for weaviate.WeaviateClient using REST/GraphQL only.

    Designed for environments where gRPC is unavailable (e.g. Azure Container Apps).
    """

    def __init__(self, base_url: str, api_key: str | None = None):
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        self._http = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        self.collections = _HttpCollectionsManager(self._http)
        self.batch = _HttpBatchProxy(self._http, collection_name=None)

    def connect(self) -> None:
        """No-op — httpx connections are established on demand."""

    def is_ready(self) -> bool:
        resp = self._http.get("/v1/.well-known/ready")
        _raise_for_status_with_body(resp, "Weaviate readiness check failed")
        return True

    def close(self) -> None:
        self._http.close()
