from __future__ import annotations

import datetime
import logging
import re
from typing import Any
from uuid import UUID
from uuid import uuid4

import weaviate
from attrs import define
from attrs import field
from weaviate.classes.query import Filter
from weaviate.classes.query import MetadataQuery
from weaviate.collections.classes.config import Configure
from weaviate.collections.classes.config import DataType
from weaviate.collections.classes.config import Property
from weaviate.util import get_valid_uuid

from src.database.postgres.document_index_models import DocumentUnit
from src.database.postgres.document_index_models import IndexKey
from src.database.session_manager import get_session_manager
from src.database.session_manager import SessionManager
from src.database.weaviate.connection.weaviate_config import BATCH_SIZE
from src.database.weaviate.connection.weaviate_config import VECTOR_DIMENSION
from src.database.weaviate.utils.document_chunker import chonk_text
from src.services.llm_services.providers.jina.jina import get_jina_embedding

logger = logging.getLogger(__name__)


def get_vector_document_index_repo() -> "VectorDocumentIndexRepository":
    return VectorDocumentIndexRepository(session_manager=get_session_manager())


@define
class VectorDocumentIndexRepository:
    session_manager: SessionManager = field(factory=get_session_manager)
    vector_dimension: int = field(default=VECTOR_DIMENSION)
    _client: weaviate.WeaviateClient | None = field(init=False, default=None, repr=False)

    @property
    def client(self) -> weaviate.WeaviateClient:
        if self._client is None:
            self._client = self.session_manager.get_weaviate_client()
        return self._client

    def add_collections(self, project_id: UUID, index_keys: list[IndexKey]) -> None:
        self.create_collection(index_keys, self._summary_collection_name(project_id))
        self.create_collection(index_keys, self._chunk_collection_name(project_id))

    def delete_collections(self, project_id: UUID) -> None:
        self.remove_collection(self._summary_collection_name(project_id))
        self.remove_collection(self._chunk_collection_name(project_id))

    def cleanup_other_revisions(self, project_id: UUID, keep_revision: str) -> None:
        revision_filter = Filter.by_property("index_revision").not_equal(keep_revision)
        for collection_name in (
            self._summary_collection_name(project_id),
            self._chunk_collection_name(project_id),
        ):
            if self.client.collections.exists(collection_name):
                collection = self.client.collections.get(collection_name)
                collection.data.delete_many(where=revision_filter)

    def remove_collection(self, collection_name: str) -> None:
        if self.client.collections.exists(collection_name):
            self.client.collections.delete(collection_name)

    def create_collection(self, index_keys: list[IndexKey], collection_name: str) -> None:
        if self.client.collections.exists(collection_name):
            return

        properties = [
            self._property("project_id", DataType.TEXT),
            self._property("datasource_id", DataType.TEXT),
            self._property("document_id", DataType.TEXT),
            self._property("index_revision", DataType.TEXT),
            self._property("path", DataType.TEXT),
            self._property("title", DataType.TEXT),
            self._property("text", DataType.TEXT),
            self._property("chunk_id", DataType.INT),
            self._property("selected_norms", DataType.TEXT_ARRAY),
            self._property("allowed_role_codes", DataType.TEXT_ARRAY),
            self._property("document_type", DataType.TEXT),
            self._property("value_streams", DataType.TEXT_ARRAY),
        ]
        for key in index_keys:
            safe_key_name = self._sanitize_key(key.key)
            properties.append(self._property(safe_key_name, DataType.TEXT))

        self.client.collections.create(
            name=collection_name,
            vectorizer_config=Configure.Vectorizer.none(),
            properties=properties,
        )

    def insert(self, documents: list[DocumentUnit], index_keys: list[IndexKey]) -> None:
        if not documents:
            return
        metadata = documents[0].metadata or {}
        project_id = UUID(str(metadata["project_id"]))
        self.add_collections(project_id, index_keys)
        self._insert_summaries(documents, index_keys, self._summary_collection_name(project_id))
        self._insert_full_text(documents, index_keys, self._chunk_collection_name(project_id))

    def search(
        self,
        *,
        project_id: UUID,
        query: str,
        search_in: str = "chunks",
        filters: dict[str, Any] | None = None,
        document_ids: list[str] | None = None,
        limit: int = 10,
        alpha: float = 0.4,
    ) -> list[dict]:
        collection_name = (
            self._chunk_collection_name(project_id)
            if search_in == "chunks"
            else self._summary_collection_name(project_id)
        )
        if not self.client.collections.exists(collection_name):
            return []

        query_embedding = get_jina_embedding([query])[0]
        filter_parts: list[Any] = []
        if filters:
            for key, value in filters.items():
                if isinstance(value, list):
                    filter_parts.append(Filter.by_property(key).contains_any(value))
                else:
                    filter_parts.append(Filter.by_property(key).equal(value))
        if document_ids:
            filter_parts.append(Filter.by_property("document_id").contains_any(document_ids))

        where_filter = Filter.all_of(filter_parts) if filter_parts else None
        collection = self.client.collections.get(collection_name)
        response = collection.query.hybrid(
            query=query,
            vector=query_embedding,
            alpha=alpha,
            filters=where_filter,
            limit=limit,
            return_metadata=MetadataQuery(score=True),
        )
        return [
            {
                "text": obj.properties.get("text"),
                "document_id": obj.properties.get("document_id"),
                "chunk_id": obj.properties.get("chunk_id"),
                "path": obj.properties.get("path"),
                "title": obj.properties.get("title"),
                "score": getattr(obj.metadata, "score", None) if obj.metadata else None,
            }
            for obj in response.objects
        ]

    def _insert_summaries(
        self,
        documents: list[DocumentUnit],
        index_keys: list[IndexKey],
        collection_name: str,
    ) -> None:
        summaries = [doc.summary for doc in documents if doc.summary]
        if not summaries:
            return
        embeddings = get_jina_embedding([summary for summary in summaries if summary])
        embedding_index = 0
        with self.client.batch.fixed_size(batch_size=BATCH_SIZE) as batch:
            for document in documents:
                if not document.summary:
                    continue
                metadata = document.metadata or {}
                self._delete_existing_document_revision(
                    collection_name,
                    document_id=str(document.id),
                    index_revision=str(metadata.get("index_revision")),
                )
                properties = self._base_properties(document, metadata, chunk_id=0)
                properties["text"] = document.summary
                self._apply_index_values(properties, document, index_keys)
                batch.add_object(
                    collection=collection_name,
                    properties=properties,
                    uuid=get_valid_uuid(uuid4()),
                    vector=embeddings[embedding_index],
                )
                embedding_index += 1

    def _insert_full_text(
        self,
        documents: list[DocumentUnit],
        index_keys: list[IndexKey],
        collection_name: str,
    ) -> None:
        with self.client.batch.fixed_size(batch_size=BATCH_SIZE) as batch:
            for document in documents:
                if not document.full_text:
                    continue
                metadata = document.metadata or {}
                self._delete_existing_document_revision(
                    collection_name,
                    document_id=str(document.id),
                    index_revision=str(metadata.get("index_revision")),
                )
                chunks = chonk_text(document.full_text)
                if not chunks:
                    continue
                embeddings = get_jina_embedding(chunks)
                for chunk_index, chunk in enumerate(chunks):
                    properties = self._base_properties(document, metadata, chunk_id=chunk_index)
                    properties["text"] = chunk
                    self._apply_index_values(properties, document, index_keys)
                    batch.add_object(
                        collection=collection_name,
                        properties=properties,
                        uuid=get_valid_uuid(uuid4()),
                        vector=embeddings[chunk_index],
                    )

    def _delete_existing_document_revision(
        self,
        collection_name: str,
        *,
        document_id: str,
        index_revision: str,
    ) -> None:
        if not self.client.collections.exists(collection_name):
            return
        collection = self.client.collections.get(collection_name)
        collection.data.delete_many(
            where=Filter.all_of(
                [
                    Filter.by_property("document_id").equal(document_id),
                    Filter.by_property("index_revision").equal(index_revision),
                ]
            )
        )

    def _base_properties(
        self,
        document: DocumentUnit,
        metadata: dict[str, Any],
        *,
        chunk_id: int,
    ) -> dict[str, Any]:
        return {
            "project_id": str(metadata.get("project_id")),
            "datasource_id": str(metadata.get("datasource_id")),
            "document_id": str(document.id),
            "index_revision": str(metadata.get("index_revision")),
            "path": metadata.get("path", document.path),
            "title": metadata.get("title", document.filename),
            "chunk_id": chunk_id,
            "selected_norms": list(metadata.get("selected_norms", [])),
            "allowed_role_codes": list(metadata.get("allowed_role_codes", [])),
            "document_type": str(metadata.get("document_type", "")),
            "value_streams": list(metadata.get("value_streams", [])),
        }

    def _apply_index_values(
        self,
        properties: dict[str, Any],
        document: DocumentUnit,
        index_keys: list[IndexKey],
    ) -> None:
        valid_keys = {self._sanitize_key(key.key) for key in index_keys}
        for index_value in document.index_values or []:
            safe_key = self._sanitize_key(index_value.key)
            if safe_key in valid_keys:
                properties[safe_key] = index_value.value

    def _summary_collection_name(self, project_id: UUID) -> str:
        return f"P{project_id.hex}_summary"

    def _chunk_collection_name(self, project_id: UUID) -> str:
        return f"P{project_id.hex}_chunk"

    def _sanitize_key(self, key: str) -> str:
        safe_key = key.lower()
        safe_key = re.sub(r"[^a-z0-9_]", "_", safe_key)
        if not safe_key or not safe_key[0].isalpha():
            safe_key = f"p_{safe_key}"
        if safe_key in {"id", "vector", "creationtimeunix", "lastupdatetimeunix"}:
            safe_key = f"{safe_key}_val"
        return safe_key

    def _property(self, name: str, data_type: DataType) -> Property:
        return Property(name=name, data_type=data_type)  # type: ignore[arg-type]
