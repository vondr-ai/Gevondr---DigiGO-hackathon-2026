from __future__ import annotations

import asyncio
import io
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from src.services.document_database.ocr.doc_router import ProcessDecision
from src.services.document_database.ocr.page_format import format_document_with_pages
from src.services.document_database.ocr.types.interface import FileReader
from src.services.llm_services.jinja_helper import process_template
from src.services.llm_services.providers.gemini.async_gemini import AsyncGeminiProvider

PDF_PAGE_OCR_MAX_CONCURRENCY = 3
logger = logging.getLogger(__name__)


class ImageReader(FileReader):
    basic_llm = AsyncGeminiProvider("gemini-3-flash-preview")

    def __init__(self, max_pages: int | None = None) -> None:
        self.max_pages = max_pages

    async def read(self, filename: str, path: str, fate: ProcessDecision) -> str:
        if fate == ProcessDecision.READ:
            # not possible
            raise

        prompt = process_template(
            template_file="extract_image.jinja",
            data={"filename": filename},
            parent_path=str(Path(__file__).parent.parent.absolute()),
        )

        images_to_process: list[str] | list[bytes]

        # Check if the file is a PDF and convert it to images if so
        if path.lower().endswith(".pdf"):
            images_to_process = await self.render_pdf_to_images(
                path,
            )
            # If conversion fails, return an empty string or handle the error
            if not images_to_process:
                logger.warning("Could not process PDF file: %s", filename)
                return format_document_with_pages(
                    filename, ["[Error: Could not convert PDF pages to images]"]
                )
            return await self._read_pdf_with_page_context(
                filename, prompt, images_to_process
            )

        # If it's not a PDF, treat it as a single image file path
        images_to_process = [path]

        response, prompt_tokens, completion_tokens = await self.basic_llm.get_response(
            prompt=prompt,
            image_paths=images_to_process,
            temperature=1,
            return_tokens=True,
            thinking_level="LOW",
        )
        assert isinstance(response, str)

        return response

    async def _read_pdf_with_page_context(
        self,
        filename: str,
        prompt: str,
        images_to_process: list[bytes],
    ) -> str:
        semaphore = asyncio.Semaphore(PDF_PAGE_OCR_MAX_CONCURRENCY)
        tasks = [
            asyncio.create_task(
                self._ocr_pdf_page(
                    prompt=prompt,
                    page_image=page_image,
                    semaphore=semaphore,
                )
            )
            for page_image in images_to_process
        ]
        page_texts = await asyncio.gather(*tasks)

        return format_document_with_pages(filename, page_texts)

    async def _ocr_pdf_page(
        self,
        prompt: str,
        page_image: bytes,
        semaphore: asyncio.Semaphore,
    ) -> str:
        async with semaphore:
            (
                response,
                prompt_tokens,
                completion_tokens,
            ) = await self.basic_llm.get_response(
                prompt=prompt,
                image_paths=[page_image],
                temperature=1,
                return_tokens=True,
                thinking_level="LOW",
            )
        _ = prompt_tokens
        _ = completion_tokens
        assert isinstance(response, str)
        return response

    async def render_pdf_to_images(
        self,
        pdf_path: str,
        *,
        max_size: int = 2048,
        quality: int = 70,
        render_dpi: int = 72,
        grayscale: bool = False,
        jpeg_optimize: bool = True,
        max_parallel_pages: int = 1,
        max_pages: int | None = None,
    ) -> list[bytes]:
        rendered_pages: list[tuple[int, bytes]] = []
        async for rendered_batch in self.iter_rendered_pdf_page_batches(
            pdf_path,
            max_size=max_size,
            quality=quality,
            render_dpi=render_dpi,
            grayscale=grayscale,
            jpeg_optimize=jpeg_optimize,
            max_parallel_pages=max_parallel_pages,
            max_pages=max_pages,
        ):
            rendered_pages.extend(rendered_batch)
        rendered_pages.sort(key=lambda item: item[0])
        return [image_bytes for _, image_bytes in rendered_pages]

    async def iter_rendered_pdf_page_batches(
        self,
        pdf_path: str,
        *,
        max_size: int = 2048,
        quality: int = 70,
        render_dpi: int = 72,
        grayscale: bool = False,
        jpeg_optimize: bool = True,
        max_parallel_pages: int = 1,
        max_pages: int | None = None,
    ) -> AsyncIterator[list[tuple[int, bytes]]]:
        page_count = await asyncio.to_thread(self._get_pdf_page_count_sync, pdf_path)
        effective_max_pages = max_pages if max_pages is not None else self.max_pages
        if effective_max_pages is not None:
            page_count = min(page_count, effective_max_pages)
        if page_count <= 0:
            return

        worker_count = max(1, min(max_parallel_pages, page_count))
        page_batches = self._build_page_groups(page_count, worker_count)
        pending_tasks: set[asyncio.Task[list[tuple[int, bytes]]]] = set()
        next_batch_index = 0

        def schedule_next_batch() -> bool:
            nonlocal next_batch_index
            if next_batch_index >= len(page_batches):
                return False
            page_numbers = page_batches[next_batch_index]
            next_batch_index += 1
            pending_tasks.add(
                asyncio.create_task(
                    asyncio.to_thread(
                        self._render_pdf_pages_sync,
                        pdf_path,
                        page_numbers,
                        max_size=max_size,
                        quality=quality,
                        render_dpi=render_dpi,
                        grayscale=grayscale,
                        jpeg_optimize=jpeg_optimize,
                    )
                )
            )
            return True

        while len(pending_tasks) < worker_count and schedule_next_batch():
            pass

        while pending_tasks:
            done, pending = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            pending_tasks = set(pending)
            for completed_task in done:
                rendered_batch = completed_task.result()
                rendered_batch.sort(key=lambda item: item[0])
                if rendered_batch:
                    yield rendered_batch
                schedule_next_batch()

    def _convert_pdf_to_image(
        self,
        pdf_path: str,
        max_size: int = 2048,
        quality: int = 70,
        render_dpi: int = 72,
        grayscale: bool = False,
        jpeg_optimize: bool = True,
        max_parallel_pages: int = 1,
    ) -> list[bytes]:
        """
        Convert PDF pages to JPEG images using PyMuPDF.
        Pages are rendered at `render_dpi` before optional max-size downscaling.
        """
        try:
            return asyncio.run(
                self.render_pdf_to_images(
                    pdf_path,
                    max_size=max_size,
                    quality=quality,
                    render_dpi=render_dpi,
                    grayscale=grayscale,
                    jpeg_optimize=jpeg_optimize,
                    max_parallel_pages=max_parallel_pages,
                )
            )
        except Exception as e:
            logger.warning(
                "Error converting PDF to images '%s': %s",
                os.path.basename(pdf_path),
                e,
            )
            # Log specific MuPDF errors for debugging
            if "syntax error" in str(e).lower():
                logger.warning(
                    "PDF file appears to be corrupted or non-standard: %s",
                    pdf_path,
                )
            return []  # Return empty list on error

    def _build_page_groups(
        self,
        page_count: int,
        worker_count: int,
    ) -> list[list[int]]:
        groups = [[] for _ in range(worker_count)]
        for page_num in range(page_count):
            groups[page_num % worker_count].append(page_num)
        return groups

    def _render_pdf_pages_sync(
        self,
        pdf_path: str,
        page_numbers: list[int],
        *,
        max_size: int,
        quality: int,
        render_dpi: int,
        grayscale: bool,
        jpeg_optimize: bool,
    ) -> list[tuple[int, bytes]]:
        rendered_pages: list[tuple[int, bytes]] = []
        with fitz.open(pdf_path) as pdf_document:
            for page_num in page_numbers:
                page = pdf_document[page_num]
                rendered_pages.append(
                    (
                        page_num,
                        self._render_pdf_page_to_jpeg(
                            page,
                            max_size=max_size,
                            quality=quality,
                            render_dpi=render_dpi,
                            grayscale=grayscale,
                            jpeg_optimize=jpeg_optimize,
                        ),
                    )
                )
        return rendered_pages

    def _render_pdf_page_to_jpeg(
        self,
        page: fitz.Page,
        *,
        max_size: int,
        quality: int,
        render_dpi: int,
        grayscale: bool,
        jpeg_optimize: bool,
    ) -> bytes:
        scale = max(render_dpi, 72) / 72.0
        matrix = fitz.Matrix(scale, scale)
        colorspace = fitz.csGRAY if grayscale else fitz.csRGB
        pix = page.get_pixmap(matrix=matrix, colorspace=colorspace, alpha=False)
        img_bytes = pix.tobytes("png")

        with Image.open(io.BytesIO(img_bytes)) as img:
            if grayscale:
                if img.mode != "L":
                    img = img.convert("L")
            elif img.mode != "RGB":
                img = img.convert("RGB")
            if img.width > max_size or img.height > max_size:
                img.thumbnail((max_size, max_size))

            img_byte_arr = io.BytesIO()
            img.save(
                img_byte_arr,
                format="JPEG",
                quality=quality,
                optimize=jpeg_optimize,
            )
            return img_byte_arr.getvalue()

    def _get_pdf_page_count_sync(self, pdf_path: str) -> int:
        with fitz.open(pdf_path) as pdf_document:
            return pdf_document.page_count

    def get_page_count(self, filename: str, path: str) -> int:
        """
        Count pages in an image file.
        Supports multi-page formats like TIFF, otherwise returns 1.
        """
        file_path = self._resolve_file_path(path, filename)
        try:
            with Image.open(file_path) as img:
                # Check if the image has multiple frames (like TIFF)
                if hasattr(img, "n_frames"):
                    return img.n_frames  # type: ignore
                return 1
        except Exception:
            return 1
