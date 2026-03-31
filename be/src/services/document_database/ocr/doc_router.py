from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path

import fitz
from attrs import define

from src.services.document_database.accepted_types import AcceptedDocumentFileType


class ProcessDecision(StrEnum):
    READ = "read"
    OCR = "ocr"
    DOC_INTEL = "doc_intel"


class ExtractionPolicy(StrEnum):
    AUTO = "auto"
    LIGHT_ONLY = "light_only"
    FORCE_HEAVY = "force_heavy"


@define
class DocumentProcessRouter:
    async def decide_fate(
        self,
        filename: str,
        path: str,
        extraction_policy: ExtractionPolicy = ExtractionPolicy.AUTO,
    ) -> ProcessDecision:
        """
        Determines if a document should be processed by reading its text directly
        or by performing OCR.
        """
        file_type = self.get_document_file_type(filename, path)

        if file_type in {
            AcceptedDocumentFileType.PNG,
            AcceptedDocumentFileType.JPG,
            AcceptedDocumentFileType.JPEG,
        }:
            return ProcessDecision.OCR

        if (
            file_type is AcceptedDocumentFileType.EXCEL
            or file_type is AcceptedDocumentFileType.CSV
        ):
            return ProcessDecision.READ

        if file_type is AcceptedDocumentFileType.PDF:
            file_path = self._resolve_path(path, filename)
            return await self._decide_pdf_fate(file_path, extraction_policy)

        # Default decision for other document types like DOCX, TXT, etc.
        return ProcessDecision.READ

    def get_document_file_type(
        self, filename: str, path: str
    ) -> AcceptedDocumentFileType | None:
        """
        Determines the file type based on its extension.

        Args:
            filename: The name of the file.
            path: The path to the file or its containing directory.

        Returns:
            The corresponding AcceptedDocumentFileType enum member if the extension
            is supported, otherwise None.
        """
        file_path = self._resolve_path(path, filename)
        extension = self._determine_extension(filename, file_path)
        return self._map_extension(extension)

    def _resolve_path(self, path: str, filename: str) -> Path:
        """Resolves the full path to the file."""
        candidate = Path(path)
        if candidate.is_file():
            return candidate
        # If path is a directory, append the filename
        if candidate.is_dir():
            return candidate
        # If path itself has a suffix, assume it's the full path
        if candidate.suffix:
            return candidate
        # Fallback to joining directory and filename
        return Path(path) / filename

    def _determine_extension(self, filename: str, file_path: Path) -> str:
        """Determines the file extension, giving precedence to the filename."""
        suffix = Path(filename).suffix.lstrip(".").lower()
        if suffix:
            return suffix
        return file_path.suffix.lstrip(".").lower()

    def _map_extension(self, extension: str) -> AcceptedDocumentFileType | None:
        """Maps a file extension string to an AcceptedDocumentFileType enum."""
        mapping = {
            "png": AcceptedDocumentFileType.PNG,
            "jpg": AcceptedDocumentFileType.JPG,
            "jpeg": AcceptedDocumentFileType.JPEG,
            "pdf": AcceptedDocumentFileType.PDF,
            "docx": AcceptedDocumentFileType.DOCX,
            "xls": AcceptedDocumentFileType.EXCEL,
            "xlsx": AcceptedDocumentFileType.EXCEL,
            "xlsm": AcceptedDocumentFileType.EXCEL,
            "xlsb": AcceptedDocumentFileType.EXCEL,
            "pptx": AcceptedDocumentFileType.PPTX,
            "ppt": AcceptedDocumentFileType.PPTX,
            "html": AcceptedDocumentFileType.HTML,
            "htm": AcceptedDocumentFileType.HTML,
            "txt": AcceptedDocumentFileType.TXT,
            "csv": AcceptedDocumentFileType.CSV,
            "eml": AcceptedDocumentFileType.EML,
        }
        return mapping.get(extension)

    async def _decide_pdf_fate(
        self,
        file_path: Path,
        extraction_policy: ExtractionPolicy,
    ) -> ProcessDecision:
        """
        Route PDFs based on extractable text and total page count.
        """
        if not file_path.exists():
            return ProcessDecision.READ

        try:
            page_count, has_extractable_text = await asyncio.to_thread(
                self._analyze_pdf_sync, file_path
            )
        except Exception:
            return ProcessDecision.OCR

        if extraction_policy == ExtractionPolicy.LIGHT_ONLY:
            return ProcessDecision.READ
        if extraction_policy == ExtractionPolicy.FORCE_HEAVY:
            if page_count == 0:
                return ProcessDecision.READ
            if page_count <= 3:
                return ProcessDecision.OCR
            return ProcessDecision.DOC_INTEL
        if has_extractable_text:
            return ProcessDecision.READ
        if page_count == 0:
            return ProcessDecision.READ
        if page_count <= 3:
            return ProcessDecision.OCR
        return ProcessDecision.DOC_INTEL

    def _analyze_pdf_sync(self, file_path: Path) -> tuple[int, bool]:
        with fitz.open(file_path) as document:
            page_count = document.page_count
            pages_to_check = min(page_count, 3)
            for page_num in range(pages_to_check):
                page = document.load_page(page_num)
                text_content: str = page.get_text("text") or ""  # pyright:ignore
                if text_content.strip():
                    return page_count, True
            return page_count, False
