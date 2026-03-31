from __future__ import annotations

import asyncio
import io
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator
from enum import StrEnum
from pathlib import Path
from uuid import UUID

import fitz
from attrs import define, field, frozen
from PIL import Image as PILImage

from src.services.document_database.accepted_types import AcceptedDocumentFileType
from src.services.document_database.ocr.doc_router import DocumentProcessRouter
from src.services.document_database.ocr.types.image import ImageReader

logger = logging.getLogger(__name__)


def build_page_s3_key(document_id: UUID | str, page_num: int) -> str:
    return f"page/{document_id}/{page_num}"


class PreviewMode(StrEnum):
    HIGH_COLOR = "high_color"
    CHEAP_COLOR = "cheap_color"
    ADAPTIVE = "adaptive"


@frozen
class PreviewProfile:
    name: str
    render_dpi: int
    max_size: int
    jpeg_quality: int
    jpeg_optimize: bool = True
    grayscale: bool = False


HIGH_COLOR_PREVIEW_PROFILE = PreviewProfile(
    name="high_color",
    render_dpi=220,
    max_size=4096,
    jpeg_quality=92,
    jpeg_optimize=True,
    grayscale=False,
)
CHEAP_COLOR_PREVIEW_PROFILE = PreviewProfile(
    name="cheap_color",
    render_dpi=144,
    max_size=2048,
    jpeg_quality=80,
    jpeg_optimize=False,
    grayscale=False,
)


@define
class DocumentPage:
    page_num: int
    image: bytes


@define
class DocumentPageHandler:
    accepted_types: set[AcceptedDocumentFileType] = {
        AcceptedDocumentFileType.DOCX,
        AcceptedDocumentFileType.PDF,
        AcceptedDocumentFileType.PPTX,
        AcceptedDocumentFileType.PNG,
        AcceptedDocumentFileType.JPG,
        AcceptedDocumentFileType.JPEG,
    }
    preview_mode: PreviewMode = PreviewMode.ADAPTIVE
    max_pages: int | None = None
    pdf_preview_page_cutoff: int = 10
    max_parallel_pdf_pages: int = 4
    high_color_profile: PreviewProfile = field(
        factory=lambda: HIGH_COLOR_PREVIEW_PROFILE
    )
    cheap_color_profile: PreviewProfile = field(
        factory=lambda: CHEAP_COLOR_PREVIEW_PROFILE
    )

    async def get_pages(self, filename: str, path: str) -> list[DocumentPage]:
        pages: list[DocumentPage] = []
        async for page_batch in self.iter_page_batches(filename=filename, path=path):
            pages.extend(page_batch)
        pages.sort(key=lambda page: page.page_num)
        logger.info(
            "Page extraction finished for '%s' with %d page image(s)",
            filename,
            len(pages),
        )
        return pages

    async def iter_page_batches(
        self,
        filename: str,
        path: str,
    ) -> AsyncIterator[list[DocumentPage]]:
        router = DocumentProcessRouter()
        file_type = router.get_document_file_type(filename=filename, path=path)
        logger.info(
            "Page extraction started for '%s' (path=%s, detected_type=%s)",
            filename,
            path,
            file_type.value if file_type else None,
        )

        if file_type not in self.accepted_types:
            supported = ", ".join(
                sorted(accepted_type.value for accepted_type in self.accepted_types)
            )
            raise ValueError(
                f"Unsupported file type for page extraction: '{filename}'. "
                f"Supported types: {supported}"
            )

        source_path = self._resolve_file_path(path=path, filename=filename)
        if not source_path.exists():
            raise FileNotFoundError(f"Document file not found: {source_path}")

        yielded_pages = 0
        if file_type is AcceptedDocumentFileType.PDF:
            page_count = await asyncio.to_thread(
                self._get_pdf_page_count,
                source_path,
            )
            preview_profile = self._select_pdf_preview_profile(page_count)
            logger.info(
                "Page extraction using PDF renderer for '%s' with profile=%s, page_count=%d, max_parallel_pages=%d",
                filename,
                preview_profile.name,
                page_count,
                self.max_parallel_pdf_pages,
            )
            async for page_batch in self._iter_pdf_page_batches(
                source_path,
                preview_profile=preview_profile,
            ):
                yielded_pages += len(page_batch)
                yield page_batch
        elif file_type in {
            AcceptedDocumentFileType.PNG,
            AcceptedDocumentFileType.JPG,
            AcceptedDocumentFileType.JPEG,
        }:
            logger.info("Page extraction using image conversion for '%s'", filename)
            image_bytes = await asyncio.to_thread(
                self._convert_image_to_jpeg, source_path
            )
            yielded_pages = 1
            yield [DocumentPage(page_num=1, image=image_bytes)]
        else:
            logger.info(
                "Page extraction using LibreOffice conversion for '%s'", filename
            )
            with tempfile.TemporaryDirectory(prefix="page_to_image_") as temp_dir:
                generated_pdf = await asyncio.to_thread(
                    self._convert_office_to_pdf,
                    source_path,
                    Path(temp_dir),
                )
                page_count = await asyncio.to_thread(
                    self._get_pdf_page_count,
                    generated_pdf,
                )
                preview_profile = self._select_pdf_preview_profile(page_count)
                async for page_batch in self._iter_pdf_page_batches(
                    generated_pdf,
                    preview_profile=preview_profile,
                ):
                    yielded_pages += len(page_batch)
                    yield page_batch

        if yielded_pages == 0:
            raise ValueError(f"No pages could be extracted from '{filename}'")

    def _resolve_file_path(self, path: str, filename: str) -> Path:
        candidate = Path(path)
        if candidate.is_file():
            return candidate
        if candidate.suffix:
            return candidate
        return candidate / filename

    async def _iter_pdf_page_batches(
        self,
        pdf_path: Path,
        *,
        preview_profile: PreviewProfile,
    ) -> AsyncIterator[list[DocumentPage]]:
        image_reader = ImageReader(max_pages=self.max_pages)
        async for rendered_batch in image_reader.iter_rendered_pdf_page_batches(
            str(pdf_path),
            max_size=preview_profile.max_size,
            quality=preview_profile.jpeg_quality,
            render_dpi=preview_profile.render_dpi,
            grayscale=preview_profile.grayscale,
            jpeg_optimize=preview_profile.jpeg_optimize,
            max_parallel_pages=self.max_parallel_pdf_pages,
            max_pages=self.max_pages,
        ):
            yield [
                DocumentPage(page_num=page_num + 1, image=image_bytes)
                for page_num, image_bytes in rendered_batch
            ]

    def _convert_image_to_jpeg(self, image_path: Path) -> bytes:
        profile = self.high_color_profile
        with PILImage.open(image_path) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            elif img.mode == "L":
                img = img.convert("RGB")
            if img.width > profile.max_size or img.height > profile.max_size:
                img.thumbnail((profile.max_size, profile.max_size))

            output = io.BytesIO()
            img.save(
                output,
                format="JPEG",
                quality=profile.jpeg_quality,
                optimize=profile.jpeg_optimize,
            )
            return output.getvalue()

    def _get_pdf_page_count(self, pdf_path: Path) -> int:
        with fitz.open(pdf_path) as pdf_document:
            return pdf_document.page_count

    def _select_pdf_preview_profile(self, page_count: int) -> PreviewProfile:
        if self.preview_mode is PreviewMode.HIGH_COLOR:
            return self.high_color_profile
        if self.preview_mode is PreviewMode.CHEAP_COLOR:
            return self.cheap_color_profile
        if page_count <= self.pdf_preview_page_cutoff:
            return self.high_color_profile
        return self.cheap_color_profile

    @property
    def page_render_dpi(self) -> int:
        return self.high_color_profile.render_dpi

    @property
    def page_image_max_size(self) -> int:
        return self.high_color_profile.max_size

    @property
    def page_image_jpeg_quality(self) -> int:
        return self.high_color_profile.jpeg_quality

    def _convert_office_to_pdf(self, file_path: Path, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)

        command = shutil.which("soffice") or shutil.which("libreoffice")
        if command is None:
            raise RuntimeError(
                "Could not convert document to PDF: LibreOffice CLI "
                "('soffice' or 'libreoffice') is not available."
            )

        converted_file = output_dir / f"{file_path.stem}.pdf"
        home_dir = output_dir / "libreoffice-home"
        runtime_dir = output_dir / "xdg-runtime"
        user_installation_dir = output_dir / "libreoffice-profile"
        for directory in (home_dir, runtime_dir, user_installation_dir):
            directory.mkdir(parents=True, exist_ok=True)

        command_args = [
            command,
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--norestore",
            f"-env:UserInstallation={user_installation_dir.resolve().as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(file_path),
        ]
        env = os.environ.copy()
        env["HOME"] = str(home_dir)
        env["XDG_RUNTIME_DIR"] = str(runtime_dir)
        command_display = shlex.join(command_args)
        logger.info(
            "Starting LibreOffice conversion for '%s' using '%s'",
            file_path.name,
            command_display,
        )
        process = subprocess.run(
            command_args,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        stdout = process.stdout.strip() if process.stdout else "no stdout output"
        stderr = process.stderr.strip() if process.stderr else "no stderr output"
        output_exists = converted_file.exists()
        output_size = converted_file.stat().st_size if output_exists else 0
        logger.info(
            "LibreOffice conversion finished for '%s' with returncode=%s, output_exists=%s, output_size=%s",
            file_path.name,
            process.returncode,
            output_exists,
            output_size,
        )
        if output_exists and output_size > 0:
            if stdout != "no stdout output":
                logger.info(
                    "LibreOffice conversion stdout for '%s': %s",
                    file_path.name,
                    stdout,
                )
            if stderr != "no stderr output":
                logger.info(
                    "LibreOffice conversion stderr for '%s' (non-fatal): %s",
                    file_path.name,
                    stderr,
                )
            return converted_file

        raise RuntimeError(
            f"Failed converting '{file_path.name}' to PDF via LibreOffice: "
            f"returncode={process.returncode}; "
            f"command={command_display}; "
            f"output_exists={output_exists}; "
            f"output_size={output_size}; "
            f"stdout={stdout}; "
            f"stderr={stderr}"
        )
