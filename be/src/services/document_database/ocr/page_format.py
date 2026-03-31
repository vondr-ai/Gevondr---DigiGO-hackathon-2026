from __future__ import annotations

import re

PAGE_SEPARATOR_TEMPLATE = "============= Page {page_num} ============="
EMPTY_PAGE_TEXT = "[No text extracted on this page.]"
PAGE_SEPARATOR_PREFIX = "============= Page "


def format_document_with_pages(filename: str, page_texts: list[str]) -> str:
    """
    Build a single transcription string with explicit page boundaries.
    """
    normalized_pages = [(text or "").strip() for text in page_texts]
    if not normalized_pages:
        normalized_pages = [""]

    parts: list[str] = [f"Filename: {filename}"]
    for page_num, page_text in enumerate(normalized_pages, start=1):
        parts.append(PAGE_SEPARATOR_TEMPLATE.format(page_num=page_num))
        parts.append(page_text if page_text else EMPTY_PAGE_TEXT)

    return "\n\n".join(parts)


def count_formatted_pages(content: str) -> int:
    """
    Count explicit page markers in formatted document content.
    """
    if not content:
        return 0
    return content.count(PAGE_SEPARATOR_PREFIX)


def truncate_formatted_pages(content: str, max_pages: int) -> str:
    """
    Keep only the first `max_pages` explicit page blocks in formatted content.
    """
    if max_pages <= 0 or not content:
        return content

    markers = [
        match.start()
        for match in re.finditer(re.escape(PAGE_SEPARATOR_PREFIX), content)
    ]
    if len(markers) <= max_pages:
        return content

    return content[: markers[max_pages]].rstrip()
