# src/services/document_database/async_processer.py
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import cast
from uuid import UUID

from attrs import define

from src.database.postgres.document_index_models import (
    DocumentDatabaseIndex,
    DocumentProcessingStatus,
    DocumentUnit,
    DocumentUnitBase,
    IndexValue,
)
from src.database.postgres.integrations.acc_repo import AccRepository
from src.database.postgres.integrations.document_db.document_index_repository import (
    DocumentIndexRepository,
)
from src.database.postgres.integrations.integration_repo import (
    IntegrationMetadataReposiory,
)
from src.database.postgres.integrations.sharepoint_repo import SharepointRepository
from src.database.postgres.py_models import (
    IntegrationMetadata,
    IntegrationType,
    OCRStatus,
)
from src.database.s3.core_repo import get_core_s3_repository
from src.database.session_manager import SessionManager
from src.database.vector_db.repos.document_index_repo import (
    VectorDocumentIndexRepository,
)
from src.services.document_database.connector.acc_connector import AccConnector
from src.services.document_database.connector.sharepoint_connector import (
    SharePointConnector,
)
from src.services.document_database.logging.pipeline_logger import PipelineLogger
from src.services.document_database.ocr.doc_router import (
    DocumentProcessRouter,
    ExtractionPolicy,
)
from src.services.document_database.ocr.document_page_handler import DocumentPageHandler
from src.services.document_database.pipeline.index_pipeline import DocumentIndexPipeline
from src.services.identity.autodesk_identity_service import (
    get_autodesk_identity_service,
)
from src.services.identity.microsoft_identity_service import (
    SHAREPOINT_GRAPH_SCOPES,
    get_microsoft_identity_service,
)

logger = logging.getLogger(__name__)

PAGE_IMAGE_MAX_CONCURRENCY = 4
PAGE_IMAGE_SEMAPHORE = asyncio.Semaphore(PAGE_IMAGE_MAX_CONCURRENCY)


@define
class AsyncDocumentProcessor:
    session_manager: SessionManager

    async def get_document_db_client(
        self,
        integration_id: UUID,
        user_id: UUID,
        membership_id: UUID | None = None,
    ) -> SharePointConnector | AccConnector:
        integration_repo = IntegrationMetadataReposiory(self.session_manager)
        raw = integration_repo.get_by_id_system(integration_id)
        if raw is None:
            raise ValueError(f"Integration {integration_id} not found")
        integration_md: IntegrationMetadata
        if isinstance(raw, list):
            integration_md = cast(IntegrationMetadata, raw[0])
        else:
            integration_md = cast(IntegrationMetadata, raw)

        if integration_md.type == IntegrationType.SHAREPOINT:
            sharepoint_repo = SharepointRepository(self.session_manager)
            sharepoint_md = sharepoint_repo.get_by_id_system(integration_id)
            if sharepoint_md is None:
                raise ValueError(f"SharePoint metadata {integration_id} not found")
            token_service = get_microsoft_identity_service()
            if membership_id is None:
                raise ValueError(
                    "SharePoint document processing requires membership_id"
                )
            access_token = await token_service.get_valid_graph_token(
                user_id=user_id,
                membership_id=membership_id,
                required_scopes=SHAREPOINT_GRAPH_SCOPES,
            )

            return SharePointConnector(
                site_id=sharepoint_md.site_id,
                access_token=access_token,
                session_manager=self.session_manager,
            )

        if integration_md.type == IntegrationType.ACC:
            acc_repo = AccRepository(
                self.session_manager,
                integration_permission_client=None,
                project_permission_client=None,
            )
            acc_md = acc_repo.get_by_id_system(integration_id)
            if acc_md is None:
                raise ValueError(f"ACC metadata {integration_id} not found")
            token_service = get_autodesk_identity_service()
            access_token = await token_service.get_valid_acc_token(
                user_id=user_id,
                membership_id=membership_id,
            )
            return AccConnector(
                hub_id=acc_md.hub_id,
                project_id=acc_md.project_id,
                access_token=access_token,
                session_manager=self.session_manager,
            )

        raise ValueError("Integration must be SharePoint or ACC")

    def fetch_and_lock_batch(
        self,
        index_id: UUID,
        num: int,
        docs_repo: DocumentIndexRepository,
    ) -> list[DocumentUnitBase]:
        """
        Fetches 'NOT_PROCESSED' documents and immediately updates them to 'PROCESSING'
        in the database. This prevents the producer from re-fetching the same docs
        while the queue is being worked on.
        """
        docs = docs_repo.get_documents_by_status(
            index_id=index_id,
            status=DocumentProcessingStatus.NOT_PROCESSED,
            limit=num,
        )

        if not docs:
            return []

        # Mark as processing immediately to lock them
        for doc in docs:
            docs_repo.update_document_status(
                document_id=doc.id,
                status=DocumentProcessingStatus.PROCESSING,
                error_message=None,
            )
            if doc.run_ocr:
                docs_repo.mark_ocr_processing(doc.id)
            # Update the local object state as well
            doc.status = DocumentProcessingStatus.PROCESSING
            if doc.run_ocr:
                doc.ocr_status = OCRStatus.PROCESSING

        return docs

    async def process_single_document_safe(
        self,
        doc: DocumentUnitBase,
        index: DocumentDatabaseIndex,
        connector: SharePointConnector | AccConnector,
        pipeline: DocumentIndexPipeline,
        timeout_seconds: int = 600,  # 10 minutes max per document
    ) -> DocumentUnit:
        """
        Wraps the processing logic in a timeout and exception handler.
        Guarantees a DocumentUnit return (either processed or failed).
        """
        try:
            return await asyncio.wait_for(
                self._process_one_document_logic(doc, index, connector, pipeline),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"Processing timed out for doc {doc.id} ({doc.filename}) after {timeout_seconds}s"
            )
            return self._create_failed_doc(doc, "Processing timed out")
        except Exception as e:
            logger.error(
                f"Unexpected error processing doc {doc.id}: {e}", exc_info=True
            )
            return self._create_failed_doc(doc, f"Processing exception: {str(e)}")

    async def _process_one_document_logic(
        self,
        doc: DocumentUnitBase,
        index: DocumentDatabaseIndex,
        connector: SharePointConnector | AccConnector,
        pipeline: DocumentIndexPipeline,
    ) -> DocumentUnit:
        pipeline_logger = PipelineLogger()
        start_total = time.perf_counter()
        logger.info(
            f"[Performance] Starting processing for doc {doc.id} ({doc.filename})"
        )

        # 0. Check if file type is supported
        router = DocumentProcessRouter()
        if not router.get_document_file_type(doc.filename, doc.path):
            logger.info(f"Skipping unsupported file type: {doc.filename}")
            pipeline_logger.log_stage(
                doc_id=str(doc.id),
                filename=doc.filename,
                stage="Validation",
                duration=0,
                status="SKIPPED",
                error_message="Unsupported file type",
            )
            return self._create_skipped_doc(doc, "Unsupported file type", index)

        try:
            # 1. Get Download URL
            t0 = time.perf_counter()
            await connector.get_download_url([doc])
            duration = time.perf_counter() - t0
            logger.info(f"[Performance] Metadata & URL fetch took {duration:.4f}s")
            pipeline_logger.log_stage(
                str(doc.id), doc.filename, "Metadata Fetch", duration
            )

            # 3. Download Content
            t0 = time.perf_counter()
            doc_bytes = await connector.download(doc)
            duration = time.perf_counter() - t0
            logger.info(f"[Performance] Download took {duration:.4f}s")
            pipeline_logger.log_stage(str(doc.id), doc.filename, "Download", duration)

            if not doc_bytes:
                pipeline_logger.log_stage(
                    str(doc.id),
                    doc.filename,
                    "Download",
                    duration,
                    status="FAILED",
                    error_message="Empty document bytes",
                )
                return self._create_failed_doc(
                    doc, "Failed to download document from source connector"
                )

            # 4. Save to Temp File
            t0 = time.perf_counter()
            safe_filename = self._sanitize_filename(doc.filename)
            file_extension = os.path.splitext(safe_filename)[1]

            def _write_temp_file(suffix: str, data: bytes) -> str:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
                    tf.write(data)
                    return tf.name

            temp_file = await asyncio.to_thread(
                _write_temp_file, file_extension, doc_bytes
            )
            duration = time.perf_counter() - t0
            logger.info(f"[Performance] Temp file creation took {duration:.4f}s")
            pipeline_logger.log_stage(
                str(doc.id), doc.filename, "Temp File Creation", duration
            )

            try:
                # 5. Run Pipeline (OCR -> LLM -> Indexing)
                t0 = time.perf_counter()
                processed_document = await pipeline.process_document(
                    document=doc,
                    local_path=temp_file,
                    extraction_policy=(
                        ExtractionPolicy.FORCE_HEAVY
                        if doc.run_ocr
                        else ExtractionPolicy.LIGHT_ONLY
                    ),
                )
                duration = time.perf_counter() - t0
                logger.info(f"[Performance] Pipeline processing took {duration:.4f}s")

                if not processed_document:
                    pipeline_logger.log_stage(
                        str(doc.id),
                        doc.filename,
                        "Pipeline Processing",
                        duration,
                        status="FAILED",
                        error_message="Pipeline returned None",
                    )
                    return self._create_failed_doc(doc, "Pipeline returned None")

                if processed_document.status == DocumentProcessingStatus.FAILED:
                    pipeline_logger.log_stage(
                        str(doc.id),
                        doc.filename,
                        "Pipeline Processing",
                        duration,
                        status="FAILED",
                        error_message=processed_document.error_message,
                    )
                else:
                    # Sanitize text fields to remove NUL bytes
                    processed_document.full_text = self._sanitize_text(
                        processed_document.full_text
                    )
                    processed_document.summary = self._sanitize_text(
                        processed_document.summary
                    )
                    processed_document.short_summary = self._sanitize_text(
                        processed_document.short_summary
                    )

                    pipeline_logger.log_stage(
                        str(doc.id),
                        doc.filename,
                        "Pipeline Processing",
                        duration,
                        status="SUCCESS",
                    )

                    logger.info(
                        "Starting page image extraction/upload for doc %s (%s)",
                        doc.id,
                        doc.filename,
                    )
                    await self._store_page_images_best_effort(
                        document_id=doc.id,
                        filename=doc.filename,
                        local_path=temp_file,
                    )
                    logger.info(
                        "Finished page image extraction/upload for doc %s (%s)",
                        doc.id,
                        doc.filename,
                    )

                logger.info(
                    f"[Performance] Total processing time for doc {doc.id}: {time.perf_counter() - start_total:.4f}s"
                )
                return processed_document

            finally:
                # Cleanup temp file
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except OSError:
                        pass
        except Exception as e:
            logger.error(f"Critical error in document processor: {e}", exc_info=True)
            pipeline_logger.log_stage(
                str(doc.id),
                doc.filename,
                "Overall Processing",
                time.perf_counter() - start_total,
                status="CRITICAL_FAILURE",
                error_message=str(e),
            )
            return self._create_failed_doc(doc, f"Critical error: {str(e)}")

    def save_batch(
        self,
        docs: list[DocumentUnit],
        index: DocumentDatabaseIndex,
    ) -> None:
        """
        Bulk writes the processed documents to Postgres and Vector DB.
        """
        docs_repo = DocumentIndexRepository(self.session_manager)
        vector_repo = VectorDocumentIndexRepository(self.session_manager)
        pipeline_logger = PipelineLogger()
        doc_info = [(str(doc.id), doc.filename) for doc in docs if doc.id]
        logger.info(
            "Saving batch for index %s with %d document(s)",
            index.id,
            len(docs),
        )

        # 1. Update Postgres (Metadata, status, errors, full text)
        postgres_start = time.perf_counter()
        try:
            logger.info(
                "Starting Postgres batch write for index %s with %d document(s)",
                index.id,
                len(docs),
            )
            docs_repo.bulk_update_processed_documents(documents=docs)
        except Exception as exc:  # pragma: no cover - logging path
            duration = time.perf_counter() - postgres_start
            self._log_persistence_stage(
                pipeline_logger,
                doc_info,
                "Postgres Write",
                duration,
                status="FAILED",
                error_message=str(exc),
            )
            raise
        else:
            duration = time.perf_counter() - postgres_start
            self._log_persistence_stage(
                pipeline_logger,
                doc_info,
                "Postgres Write",
                duration,
            )
            logger.info(
                "Finished Postgres batch write for index %s in %.4fs",
                index.id,
                duration,
            )

        # 2. Insert into Weaviate (Only successful ones)
        searchable_docs = [
            d
            for d in docs
            if d.status
            in {DocumentProcessingStatus.PROCESSED, DocumentProcessingStatus.SKIPPED}
            and (d.summary or d.full_text)
        ]
        if searchable_docs:
            vector_info = [
                (str(doc.id), doc.filename) for doc in searchable_docs if doc.id
            ]
            vector_start = time.perf_counter()
            try:
                logger.info(
                    "Starting vector batch write for index %s with %d searchable document(s)",
                    index.id,
                    len(searchable_docs),
                )
                vector_repo.insert(documents=searchable_docs, index_keys=index.keys)
            except Exception as exc:  # pragma: no cover - logging path
                duration = time.perf_counter() - vector_start
                self._log_persistence_stage(
                    pipeline_logger,
                    vector_info,
                    "Vector Write",
                    duration,
                    status="FAILED",
                    error_message=str(exc),
                )
                raise
            else:
                duration = time.perf_counter() - vector_start
                self._log_persistence_stage(
                    pipeline_logger,
                    vector_info,
                    "Vector Write",
                    duration,
                )
                logger.info(
                    "Finished vector batch write for index %s in %.4fs",
                    index.id,
                    duration,
                )
        else:
            logger.info(
                "Skipping vector batch write for index %s because no searchable documents were produced",
                index.id,
            )

        logger.info(
            "Finished saving batch for index %s with %d document(s)",
            index.id,
            len(docs),
        )

    def _create_failed_doc(self, doc: DocumentUnitBase, error_msg: str) -> DocumentUnit:
        """Helper to create a DocumentUnit in FAILED state preserving base info."""
        return DocumentUnit(
            id=doc.id,
            integration_id=doc.integration_id,
            document_index_id=doc.document_index_id,
            external_id=doc.external_id,
            filename=doc.filename,
            path=doc.path,
            size=doc.size,
            web_url=doc.web_url,
            external_created_at=doc.external_created_at,
            external_modified_at=doc.external_modified_at,
            created_at=doc.created_at,
            status=DocumentProcessingStatus.FAILED,
            error_message=error_msg,
            processed_at=datetime.now(timezone.utc),
            folder_id=doc.folder_id,
            download_url=doc.download_url,
            metadata=doc.metadata,
            # Empty processing fields
            full_text=None,
            short_summary=None,
            summary=None,
            index_values=[],
            pages=0,
            retry_count=doc.retry_count + 1,
            run_ocr=doc.run_ocr,
            ocr_status=OCRStatus.FAILED if doc.run_ocr else doc.ocr_status,
            ocr_error_message=doc.ocr_error_message,
            ocr_requested_at=doc.ocr_requested_at,
            ocr_completed_at=doc.ocr_completed_at,
        )

    def _create_skipped_doc(
        self,
        doc: DocumentUnitBase,
        reason: str,
        index: DocumentDatabaseIndex,
    ) -> DocumentUnit:
        """Helper to create a DocumentUnit in SKIPPED state."""
        metadata_blob = "Not available."
        if doc.metadata:
            try:
                metadata_blob = json.dumps(doc.metadata, indent=2, ensure_ascii=False)
            except Exception:
                metadata_blob = str(doc.metadata)

        full_text = (
            f"Filename: {doc.filename}\n"
            f"Path: {doc.path}\n"
            f"Web URL: {doc.web_url}\n"
            f"Status: {reason}\n"
            "This file type is not supported for content reading.\n"
            f"Metadata:\n{metadata_blob}"
        )
        summary = (
            f"Unsupported document type for reading. "
            f"Filename: {doc.filename}. Path: {doc.path}. "
            f"The document is indexed by filename/path/metadata only."
        )
        short_summary = f"Unsupported type: {doc.filename} ({doc.path})"
        index_values = self._build_index_values_from_metadata(index, doc.metadata)

        return DocumentUnit(
            id=doc.id,
            integration_id=doc.integration_id,
            document_index_id=doc.document_index_id,
            external_id=doc.external_id,
            filename=doc.filename,
            path=doc.path,
            size=doc.size,
            web_url=doc.web_url,
            external_created_at=doc.external_created_at,
            external_modified_at=doc.external_modified_at,
            created_at=doc.created_at,
            status=DocumentProcessingStatus.SKIPPED,
            error_message=reason,
            processed_at=datetime.now(timezone.utc),
            folder_id=doc.folder_id,
            download_url=doc.download_url,
            metadata=doc.metadata,
            full_text=full_text,
            short_summary=short_summary,
            summary=summary,
            index_values=index_values,
            pages=0,
            retry_count=doc.retry_count,
            run_ocr=doc.run_ocr,
            ocr_status=doc.ocr_status,
            ocr_error_message=doc.ocr_error_message,
            ocr_requested_at=doc.ocr_requested_at,
            ocr_completed_at=doc.ocr_completed_at,
        )

    @staticmethod
    def _build_index_values_from_metadata(
        index: DocumentDatabaseIndex,
        metadata: dict | None,
    ) -> list[IndexValue]:
        if not metadata:
            return []

        values: list[IndexValue] = []
        lower_map = {str(k).lower(): v for k, v in metadata.items()}
        manifest_map = metadata.get("manifest") if isinstance(metadata, dict) else None
        manifest_lower_map: dict[str, object] = {}
        if isinstance(manifest_map, dict):
            manifest_lower_map = {str(k).lower(): v for k, v in manifest_map.items()}

        for key in index.keys:
            if not key.id:
                continue
            candidates = [
                key.key,
                key.key.lower(),
                key.key.replace(" ", "_"),
                key.key.lower().replace(" ", "_"),
            ]
            raw = None
            for candidate in candidates:
                if candidate in metadata:
                    raw = metadata[candidate]
                    break
                if candidate.lower() in lower_map:
                    raw = lower_map[candidate.lower()]
                    break
                if candidate.lower() in manifest_lower_map:
                    raw = manifest_lower_map[candidate.lower()]
                    break
            if raw is None:
                continue
            values.append(IndexValue(key=key.key, value=str(raw), key_id=key.id))

        return values

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Sanitize filename for safe storage on filesystem."""
        invalid_chars = '<>:"/\\|?*+'
        for char in invalid_chars:
            filename = filename.replace(char, "_")
        if len(filename) > 255:
            name, ext = os.path.splitext(filename)
            filename = name[: 255 - len(ext)] + ext
        return filename

    @staticmethod
    def _log_persistence_stage(
        pipeline_logger: PipelineLogger,
        doc_info: list[tuple[str, str]],
        stage_name: str,
        duration: float,
        status: str = "SUCCESS",
        error_message: str | None = None,
    ) -> None:
        """
        Log Postgres/Vector persistence durations for each document in the batch.
        """
        if not doc_info:
            return

        per_doc_duration = duration / len(doc_info)
        for doc_id, filename in doc_info:
            pipeline_logger.log_stage(
                doc_id=doc_id,
                filename=filename,
                stage=stage_name,
                duration=per_doc_duration,
                status=status,
                error_message=error_message,
                parent_stage="Persistence",
            )

    @staticmethod
    def _sanitize_text(text: str | None) -> str | None:
        """Remove NUL (0x00) characters from text to prevent Postgres errors."""
        if text is None:
            return None
        return text.replace("\x00", "")

    async def _store_page_images_best_effort(
        self,
        document_id: UUID,
        filename: str,
        local_path: str,
    ) -> None:
        """
        Extract page images for supported document types and store them in S3.

        This is intentionally best-effort: failures must not fail document indexing.
        """
        file_type = None
        try:
            router = DocumentProcessRouter()
            file_type = router.get_document_file_type(
                filename=filename,
                path=local_path,
            )
            logger.info(
                "Page image best-effort flow started for document %s (%s), detected_type=%s",
                document_id,
                filename,
                file_type.value if file_type else None,
            )
            page_handler = DocumentPageHandler()
            if file_type not in page_handler.accepted_types:
                logger.info(
                    "Skipping page image extraction for document %s (%s); unsupported preview type",
                    document_id,
                    filename,
                )
                return

            async with PAGE_IMAGE_SEMAPHORE:
                pages = await page_handler.get_pages(
                    filename=filename,
                    path=local_path,
                )
                if not pages:
                    logger.warning(
                        "No page images extracted for document %s (%s)",
                        document_id,
                        filename,
                    )
                    return

                s3_repo = get_core_s3_repository()
                logger.info(
                    "Uploading %d extracted page image(s) for document %s (%s)",
                    len(pages),
                    document_id,
                    filename,
                )
                await s3_repo.add_pages_to_s3(document_id=document_id, pages=pages)
                logger.info(
                    "Uploaded page images for document %s (%s)",
                    document_id,
                    filename,
                )
        except Exception as exc:
            logger.warning(
                "Page image extraction/upload failed for document %s (%s), detected_type=%s: %s",
                document_id,
                filename,
                file_type.value if file_type else None,
                exc,
                exc_info=True,
            )
