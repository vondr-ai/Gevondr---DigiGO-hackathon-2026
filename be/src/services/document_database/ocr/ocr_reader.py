from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Type

from attrs import define, frozen

from src.services.document_database.accepted_types import AcceptedDocumentFileType
from src.services.document_database.ocr.doc_router import (
    DocumentProcessRouter,
    ExtractionPolicy,
    ProcessDecision,
)
from src.services.document_database.ocr.page_format import count_formatted_pages
from src.services.document_database.ocr.types.docx import DocxReader
from src.services.document_database.ocr.types.eml import EmlReader
from src.services.document_database.ocr.types.excel import ExcelReader
from src.services.document_database.ocr.types.html import HtmlReader
from src.services.document_database.ocr.types.image import ImageReader
from src.services.document_database.ocr.types.interface import FileReader
from src.services.document_database.ocr.types.pdf import PdfReader
from src.services.document_database.ocr.types.pptw import PptwReader
from src.services.document_database.ocr.types.txt import TxtReader

logger = logging.getLogger(__name__)


@frozen
class DocumentReadResult:
    transcription: str
    page_count: int | None = None


@define
class OCReader:
    type_to_processor_map: dict[AcceptedDocumentFileType, Type[FileReader]] = {
        AcceptedDocumentFileType.PNG: ImageReader,
        AcceptedDocumentFileType.JPG: ImageReader,
        AcceptedDocumentFileType.JPEG: ImageReader,
        AcceptedDocumentFileType.PDF: PdfReader,
        AcceptedDocumentFileType.DOCX: DocxReader,
        AcceptedDocumentFileType.EXCEL: ExcelReader,
        AcceptedDocumentFileType.PPTX: PptwReader,
        AcceptedDocumentFileType.HTML: HtmlReader,
        AcceptedDocumentFileType.TXT: TxtReader,
        AcceptedDocumentFileType.CSV: ExcelReader,
        AcceptedDocumentFileType.EML: EmlReader,
    }

    async def read(
        self,
        path: str,
        filename: str,
        extraction_policy: ExtractionPolicy = ExtractionPolicy.AUTO,
        max_pages: int | None = None,
    ) -> str:
        """
        Reads and processes a document file using the appropriate adapter.

        Args:
            path: The file path or directory path
            filename: The name of the file

        Returns:
            The processed text content from the document

        Raises:
            ValueError: If the file type is not supported or cannot be determined
        """
        result = await self.read_with_metadata(
            path=path,
            filename=filename,
            extraction_policy=extraction_policy,
            max_pages=max_pages,
        )
        return result.transcription

    async def read_with_metadata(
        self,
        path: str,
        filename: str,
        extraction_policy: ExtractionPolicy = ExtractionPolicy.AUTO,
        max_pages: int | None = None,
    ) -> DocumentReadResult:
        router = DocumentProcessRouter()

        file_type = router.get_document_file_type(filename=filename, path=path)
        if file_type is None:
            raise ValueError(
                f"Unsupported file type for file: {filename}. "
                f"Supported types: {', '.join([ft.value for ft in AcceptedDocumentFileType])}"
            )

        processor_class = self.type_to_processor_map.get(file_type)
        if processor_class is None:
            raise ValueError(
                f"No processor configured for file type: {file_type.value}. "
                f"File: {filename}"
            )

        if extraction_policy == ExtractionPolicy.LIGHT_ONLY and file_type in {
            AcceptedDocumentFileType.PNG,
            AcceptedDocumentFileType.JPG,
            AcceptedDocumentFileType.JPEG,
        }:
            logger.info(
                "[Performance] Skipping heavy OCR for image file %s due to LIGHT_ONLY policy",
                filename,
            )
            return DocumentReadResult(transcription="", page_count=1)

        process_fate: ProcessDecision = await router.decide_fate(
            filename=filename,
            path=path,
            extraction_policy=extraction_policy,
        )
        s = f"[Performance] Reading file {filename} (Type: {file_type.value}, Fate: {process_fate.name})"
        logger.info(s)
        t0 = time.perf_counter()

        processor = self._build_processor(processor_class, max_pages=max_pages)

        page_count: int | None = None
        if max_pages is not None:
            page_count = await self._get_page_count(
                processor, path=path, filename=filename
            )
        content = await processor.read(filename=filename, path=path, fate=process_fate)
        if page_count is None:
            page_count = self._infer_page_count_from_content(content)

        logger.info(
            f"[Performance] Processor {processor_class.__name__} took {time.perf_counter() - t0:.4f}s"
        )

        return DocumentReadResult(transcription=content, page_count=page_count)

    async def get_document_info(self, path: str, filename: str) -> tuple[int, int]:
        """
        Get document size and page count.

        Args:
            path: The file path or directory path
            filename: The name of the file

        Returns:
            Tuple of (size_in_bytes, page_count)
        """
        router = DocumentProcessRouter()

        # Determine the file type
        file_type = router.get_document_file_type(filename=filename, path=path)

        if file_type is None:
            return (0, 1)  # Default for unsupported types

        # Get the appropriate processor for this file type
        processor_class = self.type_to_processor_map.get(file_type)

        if processor_class is None:
            return (0, 1)

        processor = processor_class()

        # Calculate size
        full_path = Path(path)
        if not full_path.is_file():
            full_path = full_path / filename

        size = 0
        if full_path.exists():
            size = full_path.stat().st_size

        # Get page count
        try:
            # Check if the processor has an async get_page_count method
            if asyncio.iscoroutinefunction(processor.get_page_count):
                page_count = await processor.get_page_count(
                    path=path, filename=filename
                )
            else:
                # Fallback for synchronous implementations (if any remain)
                page_count = processor.get_page_count(path=path, filename=filename)
        except Exception as e:
            logger.warning(f"Failed to get page count for {filename}: {e}")
            page_count = 1

        return (size, page_count)

    def _infer_page_count_from_content(self, content: str) -> int:
        page_count = count_formatted_pages(content)
        if page_count > 0:
            return page_count
        return 1

    def _build_processor(
        self,
        processor_class: Type[FileReader],
        *,
        max_pages: int | None,
    ) -> FileReader:
        try:
            return processor_class(max_pages=max_pages)
        except TypeError:
            return processor_class()

    async def _get_page_count(
        self,
        processor: FileReader,
        *,
        path: str,
        filename: str,
    ) -> int | None:
        try:
            if asyncio.iscoroutinefunction(processor.get_page_count):
                return await processor.get_page_count(path=path, filename=filename)
            return processor.get_page_count(path=path, filename=filename)
        except Exception as exc:
            logger.warning("Failed to get page count for %s: %s", filename, exc)
            return None
