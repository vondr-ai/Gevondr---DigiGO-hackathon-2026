from __future__ import annotations

import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

from html_to_markdown import ConversionOptions, convert

from src.services.document_database.ocr.doc_router import ProcessDecision
from src.services.document_database.ocr.page_format import format_document_with_pages
from src.services.document_database.ocr.types.interface import FileReader


class EmlReader(FileReader):
    async def read(
        self,
        filename: str,
        path: str,
        fate: ProcessDecision,
    ) -> str:
        if fate == ProcessDecision.OCR:
            raise ValueError("OCR is not applicable for EML files")

        file_path = self._resolve_file_path(path, filename)

        with open(file_path, "rb") as handle:
            message = BytesParser(policy=policy.default).parse(handle)

        sections = [self._format_headers(message)]

        body_text = self._extract_richest_body(message)
        if body_text:
            sections.append("Body:\n" + body_text)

        attachment_sections = self._extract_text_attachments(message)
        if attachment_sections:
            sections.extend(attachment_sections)

        content = "\n\n".join(section for section in sections if section.strip())
        return format_document_with_pages(filename, [content])

    def get_page_count(self, filename: str, path: str) -> int:
        _ = filename, path
        return 1

    def _format_headers(self, message: EmailMessage) -> str:
        return "\n".join(
            [
                f"Subject: {message.get('subject', '')}",
                f"From: {message.get('from', '')}",
                f"To: {message.get('to', '')}",
                f"Date: {message.get('date', '')}",
            ]
        ).strip()

    def _extract_richest_body(self, message: EmailMessage) -> str:
        best_text = ""
        best_score = -1

        for part in message.walk():
            if part.is_multipart():
                continue
            if part.get_content_disposition() == "attachment":
                continue

            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue

            text = self._decode_text_part(part)
            if not text:
                continue

            if content_type == "text/html":
                text = self._html_to_markdown(text)

            score = self._text_score(text)
            if score > best_score:
                best_text = text
                best_score = score

        return best_text.strip()

    def _extract_text_attachments(self, message: EmailMessage) -> list[str]:
        sections: list[str] = []

        for part in message.walk():
            if part.is_multipart():
                continue
            if part.get_content_disposition() != "attachment":
                continue
            if part.get_content_maintype() != "text":
                continue

            text = self._decode_text_part(part)
            if not text:
                continue

            if part.get_content_type() == "text/html":
                text = self._html_to_markdown(text)

            attachment_name = part.get_filename() or "unnamed_attachment"
            sections.append(f"Attachment: {attachment_name}\n{text.strip()}")

        return sections

    def _decode_text_part(self, part: EmailMessage) -> str:
        try:
            content = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True)
            if payload is None:
                return ""
            if not isinstance(payload, bytes):
                return str(payload)
            return self._decode_bytes(payload, part)

        if isinstance(content, bytes):
            return self._decode_bytes(content, part)
        if isinstance(content, str):
            return content
        return str(content)

    def _decode_bytes(self, payload: bytes, part: EmailMessage) -> str:
        charset = part.get_content_charset()
        encodings = [charset, "utf-8", "latin-1"]
        for encoding in encodings:
            if not encoding:
                continue
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        return payload.decode("utf-8", errors="replace")

    def _html_to_markdown(self, html_content: str) -> str:
        return convert(html_content, ConversionOptions()).strip()

    def _text_score(self, text: str) -> int:
        return len(re.sub(r"\s+", "", text))
