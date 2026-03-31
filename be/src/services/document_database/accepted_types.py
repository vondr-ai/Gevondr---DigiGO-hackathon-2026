from __future__ import annotations

from enum import StrEnum


class AcceptedDocumentFileType(StrEnum):
    PNG = "png"
    JPG = "jpg"
    JPEG = "jpeg"
    PDF = "pdf"
    DOCX = "docx"
    EXCEL = "excel"
    PPTX = "pptx"
    HTML = "html"
    TXT = "txt"
    CSV = "csv"
    EML = "eml"

    @classmethod
    def as_set(cls) -> set[str]:
        return {item.value for item in cls}
