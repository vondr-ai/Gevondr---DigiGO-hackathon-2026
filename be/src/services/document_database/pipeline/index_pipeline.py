# src/services/document_database/pipeline/index_pipeline.py
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import tiktoken
from attrs import asdict, define, field

from src.database.postgres.document_index_models import (
    DocumentDatabaseIndex,
    DocumentProcessingStatus,
    DocumentUnit,
    DocumentUnitBase,
    IndexValue,
)
from src.database.postgres.py_models import OCRStatus
from src.services.catalogs import GEBORA_VALUE_STREAMS
from src.services.catalogs import NEN_2084_DOCUMENT_TYPES
from src.services.document_database.excel.excel_table_extractor import (
    ExcelTableExtractor,
)
from src.services.document_database.logging.pipeline_logger import PipelineLogger
from src.services.document_database.ocr.doc_router import ExtractionPolicy
from src.services.document_database.ocr.ocr_reader import OCReader
from src.services.llm_services.jinja_helper import process_template

logger = logging.getLogger(__name__)


@define
class DocumentIndexPipeline:
    """
    A pipeline for processing a single document unit, including OCR,
    intelligent analysis via LLM for summarization and index value extraction,
    and validation with a retry mechanism.
    """

    index: DocumentDatabaseIndex
    llm: Any
    ocreader: OCReader = field(factory=OCReader)
    excel_extractor: ExcelTableExtractor = field(factory=ExcelTableExtractor)
    MAX_RETRIES = 3
    MAX_PROMPT_TEXT_TOKENS = 100_000
    TOKENIZER_MODEL = "gpt-5.4"

    async def process_document(
        self,
        document: DocumentUnitBase,
        local_path: str,
        images: Optional[list[str] | list[bytes]] = None,
        extraction_policy: ExtractionPolicy = ExtractionPolicy.AUTO,
        indexing_instructions: str | None = None,
    ) -> DocumentUnit | None:
        """
        Processes a given document unit by performing OCR, extracting intelligent summaries
        and index values using an LLM, and validating the results.

        Returns a processed DocumentUnit on success or None on failure after retries.
        """
        try:
            pipeline_logger = PipelineLogger()
            doc_id = str(document.id)
            t0 = time.perf_counter()
            extension = Path(document.filename).suffix.lower().lstrip(".")
            if extension in {"xlsx", "xlsm", "xls", "xlsb", "csv"}:
                excel_result = self.excel_extractor.extract_and_store(
                    path=local_path,
                    filename=document.filename,
                    document_id=document.id,
                    project_omgeving_id=None,
                )
                full_text = excel_result.full_text
            else:
                full_text = await self.ocreader.read(
                    path=local_path,
                    filename=document.filename,
                    extraction_policy=extraction_policy,
                )
            duration = time.perf_counter() - t0
            logger.info(f"[Performance] OCR/Read took {duration:.4f}s")
            self._log_pipeline_sub_stage(
                pipeline_logger,
                doc_id,
                document.filename,
                "OCR/Read",
                duration,
            )

            metrics_start = time.perf_counter()
            size, pages = await self._count_size_and_pages(
                local_path, document.filename
            )
            metrics_duration = time.perf_counter() - metrics_start
            self._log_pipeline_sub_stage(
                pipeline_logger,
                doc_id,
                document.filename,
                "Document Metrics",
                metrics_duration,
            )
            now = datetime.now(timezone.utc)

            if not (full_text or "").strip():
                if extraction_policy == ExtractionPolicy.FORCE_HEAVY:
                    summary = "Heavy OCR completed, but no readable text could be extracted from this document."
                    short_summary = "Heavy OCR completed without readable text"
                else:
                    summary = (
                        "No extractable text was found with light extraction. "
                        "Heavy OCR has not been run yet for this document."
                    )
                    short_summary = "Heavy OCR available on demand"
                index_values = self._build_index_values_from_metadata(document.metadata)
                document_type = None
                value_streams: list[str] = []
            else:
                t0 = time.perf_counter()
                (
                    summary,
                    short_summary,
                    index_values,
                    document_type,
                    value_streams,
                ) = await self.intelligently_process_document(
                    full_text,
                    document.filename,
                    document.metadata,
                    images,
                    indexing_instructions=indexing_instructions,
                    pipeline_logger=pipeline_logger,
                    doc_id=doc_id,
                )
                duration = time.perf_counter() - t0
                logger.info(f"[Performance] LLM processing took {duration:.4f}s")
                self._log_pipeline_sub_stage(
                    pipeline_logger,
                    doc_id,
                    document.filename,
                    "LLM Processing",
                    duration,
                )

            assembly_start = time.perf_counter()
            processed_document = DocumentUnit(
                id=document.id,
                integration_id=document.integration_id,
                document_index_id=document.document_index_id,
                external_id=document.external_id,
                filename=document.filename,
                path=document.path,
                web_url=document.web_url,
                external_created_at=document.external_created_at,
                external_modified_at=document.external_modified_at,
                created_at=document.created_at,
                folder_id=document.folder_id,
                download_url=document.download_url,
                metadata=document.metadata,
                status=DocumentProcessingStatus.PROCESSED,
                size=size,
                pages=pages,
                processed_at=now,
                full_text=full_text,
                short_summary=short_summary,
                summary=summary,
                document_type=document_type,
                value_streams=value_streams,
                index_values=index_values,
                error_message=None,
                retry_count=document.retry_count,
                run_ocr=document.run_ocr,
                ocr_status=(
                    OCRStatus.COMPLETED
                    if extraction_policy == ExtractionPolicy.FORCE_HEAVY
                    else document.ocr_status
                ),
                ocr_error_message=document.ocr_error_message,
                ocr_requested_at=document.ocr_requested_at,
                ocr_completed_at=document.ocr_completed_at,
                is_latest_revision=document.is_latest_revision,
                revision_group_id=document.revision_group_id,
                revision_rank=document.revision_rank,
                canonical_document_id=document.canonical_document_id,
            )
            assembly_duration = time.perf_counter() - assembly_start
            self._log_pipeline_sub_stage(
                pipeline_logger,
                doc_id,
                document.filename,
                "Document Assembly",
                assembly_duration,
            )

            return processed_document

        except Exception as e:
            # On failure, return a new DocumentUnit with FAILED status and error message
            # Fix: vars() does not work on attrs classes with slots=True. Use asdict.
            # Fix: Filter out fields we are explicitly providing to avoid TypeError
            doc_dict = asdict(document, recurse=False)
            for key in ["status", "error_message", "retry_count", "processed_at"]:
                doc_dict.pop(key, None)

            return DocumentUnit(
                **doc_dict,
                status=DocumentProcessingStatus.FAILED,
                error_message=str(e),
                retry_count=self.MAX_RETRIES,  # Max retries attempted
                processed_at=datetime.now(timezone.utc),
            )

    def _build_index_values_from_metadata(
        self,
        metadata: Optional[dict],
    ) -> list[IndexValue]:
        if not metadata:
            return []

        values: list[IndexValue] = []
        lower_map = {str(k).lower(): v for k, v in metadata.items()}
        manifest_map = metadata.get("manifest") if isinstance(metadata, dict) else None
        manifest_lower_map: dict[str, object] = {}
        if isinstance(manifest_map, dict):
            manifest_lower_map = {str(k).lower(): v for k, v in manifest_map.items()}

        for key in self.index.keys:
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

    async def _count_size_and_pages(self, path: str, filename: str) -> tuple[int, int]:
        """
        Counts the size (in bytes) and pages of a document using the OCReader.
        """
        return await self.ocreader.get_document_info(path=path, filename=filename)

    async def intelligently_process_document(
        self,
        full_text: str,
        filename: str,
        metadata: Optional[dict],
        images: Optional[list[str] | list[bytes]],
        indexing_instructions: str | None = None,
        pipeline_logger: PipelineLogger | None = None,
        doc_id: Optional[str] = None,
    ) -> tuple[str, str, list[IndexValue], str | None, list[str]]:
        """
        Uses an LLM to generate summaries and extract index values from the document text.
        It includes a retry loop to handle validation or formatting errors.
        """
        prompt_text, original_tokens, used_tokens = self._truncate_text_for_llm(
            full_text
        )
        if original_tokens > used_tokens:
            logger.warning(
                "Truncated LLM input for %s from %s to %s tokens",
                filename,
                original_tokens,
                used_tokens,
            )
            self._log_pipeline_sub_stage(
                pipeline_logger,
                doc_id,
                filename,
                "Token Truncation",
                0.0,
            )

        error_string = None
        _ = filename
        valid_types = {item["label"] for item in NEN_2084_DOCUMENT_TYPES}
        valid_streams = {item["label"] for item in GEBORA_VALUE_STREAMS}
        for attempt in range(self.MAX_RETRIES):
            _ = attempt
            image_text = (
                "Images from the document are also attached for context."
                if images
                else ""
            )

            index_info = (
                f"Index Name: {self.index.name}. Description: {self.index.description}"
            )
            index_keys_details = "\n".join(
                f"- Key: '{key.key}', Description: {key.description or 'N/A'}, Type: {key.datatype.__name__ if key.datatype else 'Enum'}, Options: {key.options or 'N/A'}"
                for key in self.index.keys
            )
            index_key_names = ", ".join(f"'{k.key}'" for k in self.index.keys)

            prompt_start = time.perf_counter()
            prompt = process_template(
                template_file="indexing.jinja",
                data={
                    "metadata": json.dumps(metadata, indent=2)
                    if metadata
                    else "Not available.",
                    "index_info": index_info,
                    "full_text": prompt_text,
                    "image_text": image_text,
                    "indexing_instructions": indexing_instructions,
                    "index_key_names": index_key_names,
                    "index_keys_details": index_keys_details,
                    "has_index_keys": bool(self.index.keys),
                    "error_string": error_string,
                },
                parent_path=str(Path(__file__).parent.parent.absolute()),
            )
            prompt_duration = time.perf_counter() - prompt_start
            self._log_pipeline_sub_stage(
                pipeline_logger,
                doc_id,
                filename,
                "LLM Prompt Render",
                prompt_duration,
            )
            response: dict[str, Any]

            llm_start = time.perf_counter()
            try:
                response, _, _ = await self.llm.get_response(
                    prompt=prompt,
                    temperature=0.5,
                    return_tokens=True,
                    image_paths=images,
                    format=True,
                )  # pyright:ignore
            except Exception as e:
                llm_duration = time.perf_counter() - llm_start
                self._log_pipeline_sub_stage(
                    pipeline_logger,
                    doc_id,
                    filename,
                    "LLM API Call",
                    llm_duration,
                    status="FAILED",
                    error_message=str(e),
                )
                raise
            llm_duration = time.perf_counter() - llm_start
            self._log_pipeline_sub_stage(
                pipeline_logger,
                doc_id,
                filename,
                "LLM API Call",
                llm_duration,
            )

            try:
                parse_start = time.perf_counter()
                (
                    summary,
                    short_summary,
                    index_values,
                    document_type,
                    value_streams,
                ) = self._format_llm_response(response)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
                parse_duration = time.perf_counter() - parse_start
                self._log_pipeline_sub_stage(
                    pipeline_logger,
                    doc_id,
                    filename,
                    "LLM Response Parse",
                    parse_duration,
                    status="FAILED",
                    error_message=str(e),
                )
                error_string = f"Failed to parse the LLM response. Error: {e}. The response was: {response}"
                continue
            else:
                parse_duration = time.perf_counter() - parse_start
                self._log_pipeline_sub_stage(
                    pipeline_logger,
                    doc_id,
                    filename,
                    "LLM Response Parse",
                    parse_duration,
                )

            validation_start = time.perf_counter()
            validation_error = self._validate_index_values(index_values)
            classification_error = self._validate_classification(
                document_type=document_type,
                value_streams=value_streams,
                valid_types=valid_types,
                valid_streams=valid_streams,
            )
            validation_error = validation_error or classification_error
            validation_duration = time.perf_counter() - validation_start
            self._log_pipeline_sub_stage(
                pipeline_logger,
                doc_id,
                filename,
                "Index Validation",
                validation_duration,
                status="FAILED" if validation_error else "SUCCESS",
                error_message=validation_error,
            )

            if not validation_error:
                return (
                    summary,
                    short_summary,
                    index_values,
                    document_type,
                    value_streams,
                )
            error_string = f"Validation failed: {validation_error}"

        raise ValueError(
            f"Failed to process document after {self.MAX_RETRIES} attempts. Last error: {error_string}"
        )

    def _truncate_text_for_llm(self, full_text: str) -> tuple[str, int, int]:
        text = full_text or ""
        encoding = self._get_token_encoding()
        tokens = encoding.encode(text)
        original_count = len(tokens)
        if original_count <= self.MAX_PROMPT_TEXT_TOKENS:
            return text, original_count, original_count

        trimmed_text = encoding.decode(tokens[: self.MAX_PROMPT_TEXT_TOKENS])
        return (
            f"{trimmed_text}\n\n[Document text truncated for indexing token budget.]",
            original_count,
            self.MAX_PROMPT_TEXT_TOKENS,
        )

    def _get_token_encoding(self):
        try:
            return tiktoken.encoding_for_model(self.TOKENIZER_MODEL)
        except Exception:
            try:
                return tiktoken.get_encoding("o200k_base")
            except Exception:
                return tiktoken.get_encoding("cl100k_base")

    def _format_llm_response(
        self,
        response: dict,
    ) -> tuple[str, str, list[IndexValue], str | None, list[str]]:
        """
        Parses the JSON response from the LLM and converts it into the required data objects.
        """
        response = self._coerce_response_dict(response)
        if not isinstance(response, dict):
            raise TypeError(
                f"LLM response must be a dictionary, but got {type(response).__name__}."
            )

        summary = response["summary"]
        short_summary = response["short_summary"]
        raw_document_type = response.get("document_type")
        if raw_document_type is None:
            document_type = None
        elif isinstance(raw_document_type, str):
            document_type = raw_document_type.strip() or None
        else:
            raise TypeError(
                "LLM document_type must be a string or null, "
                f"but got {type(raw_document_type).__name__}."
            )

        raw_value_streams = response.get("value_streams", [])
        if not isinstance(raw_value_streams, list):
            raise TypeError(
                "LLM value_streams must be a list, "
                f"but got {type(raw_value_streams).__name__}."
            )
        value_streams: list[str] = []
        for item in raw_value_streams:
            if not isinstance(item, str):
                raise TypeError(
                    "Each LLM value_streams item must be a string, "
                    f"but got {type(item).__name__}."
                )
            normalized = item.strip()
            if normalized:
                value_streams.append(normalized)

        if not self.index.keys:
            return summary, short_summary, [], document_type, value_streams

        raw_index_values = response.get(
            "index_values",
            [],
        )  # This is a list of dicts: [{"key": "value"}, ...]
        if not isinstance(raw_index_values, list):
            raise TypeError(
                f"LLM index_values must be a list, but got {type(raw_index_values).__name__}."
            )

        key_map = {key.key: key for key in self.index.keys}
        formatted_values = []

        for item in raw_index_values:
            if not isinstance(item, dict):
                raise TypeError(
                    f"Each LLM index_values item must be a dictionary, but got {type(item).__name__}."
                )
            for key_name, value in item.items():
                index_key = key_map.get(key_name)
                if not index_key:
                    raise ValueError(
                        f"LLM returned an invalid key: '{key_name}' which is not in the defined index keys."
                    )
                assert index_key.id

                formatted_values.append(
                    IndexValue(key=index_key.key, value=str(value), key_id=index_key.id)
                )

        return (
            summary,
            short_summary,
            formatted_values,
            document_type,
            value_streams,
        )

    def _coerce_response_dict(self, response: Any) -> Any:
        if isinstance(response, dict):
            return response
        if not isinstance(response, str):
            return response

        candidate = response.strip()
        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if (
                len(lines) >= 3
                and lines[0].strip().startswith("```")
                and lines[-1].strip().startswith("```")
            ):
                candidate = "\n".join(line.strip() for line in lines[1:-1]).strip()

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return response
        return parsed

    def _validate_index_values(self, index_values: list[IndexValue]) -> Optional[str]:
        """
        Validates the extracted index values against the schema defined in the DocumentDatabaseIndex.


        Returns an error string if validation fails, otherwise None.
        """
        key_map = {key.key: key for key in self.index.keys}

        for value_obj in index_values:
            key_schema = key_map.get(value_obj.key)
            if not key_schema:
                return f"The key '{value_obj.key}' is not a valid key for this index."

            # Check against predefined options if they exist
            if key_schema.options:
                # Ensure the value is one of the allowed options
                str_options = [str(opt) for opt in key_schema.options]
                if value_obj.value not in str_options:
                    return f"The value '{value_obj.value}' for key '{value_obj.key}' is not in the allowed options: {str_options}."

            # Check data type if specified
            if key_schema.datatype:
                try:
                    # Attempt to cast the value to the required type
                    key_schema.datatype(value_obj.value)
                except (ValueError, TypeError):
                    return f"The value '{value_obj.value}' for key '{value_obj.key}' could not be converted to the required type: {key_schema.datatype.__name__}."

        return None

    def _validate_classification(
        self,
        document_type: str | None,
        value_streams: list[str] | None,
        valid_types: set[str],
        valid_streams: set[str],
    ) -> Optional[str]:
        if document_type and document_type not in valid_types:
            return f"document_type '{document_type}' is not valid"
        if not isinstance(value_streams, list):
            return "value_streams must be a list"
        if len(value_streams) > 3:
            return "value_streams max 3"
        for value_stream in value_streams:
            if value_stream not in valid_streams:
                return f"value_stream '{value_stream}' is not valid"
        return None

    def _log_pipeline_sub_stage(
        self,
        pipeline_logger: PipelineLogger | None,
        doc_id: Optional[str],
        filename: str,
        stage_name: str,
        duration: float,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
    ) -> None:
        """
        Records a fine-grained pipeline stage duration under the Pipeline Processing umbrella.
        """
        if not pipeline_logger or not doc_id:
            return

        pipeline_logger.log_stage(
            doc_id=doc_id,
            filename=filename,
            stage=stage_name,
            duration=duration,
            status=status,
            error_message=error_message,
            parent_stage="Pipeline Processing",
        )
