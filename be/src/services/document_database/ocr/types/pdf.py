from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Type

import fitz  # PyMuPDF
import pymupdf4llm

from src.services.document_database.ocr.doc_router import ProcessDecision
from src.services.document_database.ocr.ms_document_intelligence import (
    AzureDocumentIntelligenceClient,
)
from src.services.document_database.ocr.page_format import format_document_with_pages
from src.services.document_database.ocr.types.image import ImageReader
from src.services.document_database.ocr.types.interface import FileReader

logger = logging.getLogger(__name__)


class PdfReader(FileReader):
    def __init__(self, max_pages: int | None = None) -> None:
        self.max_pages = max_pages

    doc_intel_client_class: Type[AzureDocumentIntelligenceClient] = (
        AzureDocumentIntelligenceClient
    )

    async def read(self, filename: str, path: str, fate: ProcessDecision) -> str:
        if fate == ProcessDecision.READ:
            return await self.process_markdown(filename, path)
        if fate == ProcessDecision.OCR:
            return await self.process_with_llm(filename, path)
        if fate == ProcessDecision.DOC_INTEL:
            return await self.process_with_doc_intel(filename, path)
        raise ValueError(f"Unsupported PDF processing decision: {fate}")

    async def process_markdown(self, filename: str, path: str):
        file_path = self._resolve_file_path(path, filename)
        processing_path, temp_path = await self._prepare_pdf_path(file_path)
        processing_path_str = str(processing_path)
        # 1. Extract page-by-page text to preserve boundaries in output.
        try:
            try:
                page_texts = await asyncio.to_thread(
                    self._extract_page_texts_sync, processing_path_str
                )
                return format_document_with_pages(filename, page_texts)
            except Exception as e:
                logger.debug("fitz paged extraction failed for %s: %s", filename, e)

            try:
                md_text = await asyncio.to_thread(
                    pymupdf4llm.to_markdown, processing_path_str
                )
                return format_document_with_pages(filename, [md_text])
            except Exception as e:
                logger.debug("pymupdf4llm failed for %s: %s", filename, e)

            try:
                from markitdown import MarkItDown

                md = MarkItDown()
                result = await asyncio.to_thread(md.convert, processing_path_str)
                if result and result.text_content:
                    return format_document_with_pages(filename, [result.text_content])
            except Exception as e:
                logger.debug("MarkItDown failed for %s: %s", filename, e)

            return format_document_with_pages(
                filename, ["[Error: Could not extract text from PDF]"]
            )
        finally:
            if temp_path is not None:
                await asyncio.to_thread(os.remove, temp_path)

    async def process_with_llm(
        self,
        filename: str,
        path: str,
    ) -> str:
        file_path = self._resolve_file_path(path, filename)
        processing_path, temp_path = await self._prepare_pdf_path(file_path)
        image_reader = ImageReader(max_pages=self.max_pages)

        try:
            return await image_reader.read(
                filename=filename,
                path=str(processing_path),
                fate=ProcessDecision.OCR,
            )
        finally:
            if temp_path is not None:
                await asyncio.to_thread(os.remove, temp_path)

    async def process_with_doc_intel(
        self,
        filename: str,
        path: str,
    ) -> str:
        file_path = self._resolve_file_path(path, filename)
        processing_path, temp_path = await self._prepare_pdf_path(file_path)
        client = self.doc_intel_client_class()
        try:
            markdown = await client.analyze_pdf(processing_path)
            return format_document_with_pages(filename, [markdown])
        finally:
            if temp_path is not None:
                await asyncio.to_thread(os.remove, temp_path)

    async def get_page_count(self, filename: str, path: str) -> int:
        """
        Get the number of pages in a PDF document.

        Uses PyMuPDF (fitz) to accurately count pages in the PDF.
        Falls back to 1 if the PDF cannot be read.
        """
        file_path = self._resolve_file_path(path, filename)
        try:
            # Run the blocking file open in a separate thread
            return await asyncio.to_thread(self._get_page_count_sync, file_path)
        except Exception:
            return 1  # Default to 1 if we can't read the PDF

    def _get_page_count_sync(self, file_path: Path) -> int:
        """Synchronous helper for get_page_count to be run in a thread."""
        with fitz.open(file_path) as doc:
            return doc.page_count

    def _extract_page_texts_sync(self, file_path: str) -> list[str]:
        page_texts: list[str] = []
        with fitz.open(file_path) as doc:
            if doc.page_count == 0:
                return [""]
            for page in doc:
                text = page.get_text()
                # Appease the type checker by confirming it is a string
                page_texts.append(text if isinstance(text, str) else "")
        return page_texts

    async def _prepare_pdf_path(self, file_path: Path) -> tuple[Path, str | None]:
        if self.max_pages is None:
            return file_path, None

        try:
            limited_path = await asyncio.to_thread(
                self._create_limited_pdf_copy_if_needed,
                file_path,
                self.max_pages,
            )
        except Exception as exc:
            logger.debug(
                "Failed to prepare limited PDF copy for %s: %s",
                file_path,
                exc,
            )
            return file_path, None
        if limited_path == file_path:
            return file_path, None
        return limited_path, str(limited_path)

    def _create_limited_pdf_copy_if_needed(
        self,
        file_path: Path,
        max_pages: int,
    ) -> Path:
        with fitz.open(file_path) as doc:
            if doc.page_count <= max_pages:
                return file_path

            limited_doc = fitz.open()
            try:
                limited_doc.insert_pdf(doc, from_page=0, to_page=max_pages - 1)
                handle, temp_path = tempfile.mkstemp(suffix=".pdf")
                os.close(handle)
                limited_doc.save(temp_path)
                return Path(temp_path)
            finally:
                limited_doc.close()
