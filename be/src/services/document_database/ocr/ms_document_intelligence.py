from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import httpx
from attrs import define


@define
class AzureDocumentIntelligenceClient:
    endpoint: str | None = None
    api_key: str | None = None
    api_version: str = "2024-11-30"
    poll_interval_seconds: float = 2.0
    max_poll_attempts: int = 60
    request_timeout_seconds: float = 120.0

    def __attrs_post_init__(self) -> None:
        if self.endpoint is None or self.api_key is None:
            from src.settings import settings

            if self.endpoint is None:
                self.endpoint = settings.ms_doc_intel_endpoint
            if self.api_key is None:
                self.api_key = settings.ms_doc_intel_key

        assert self.endpoint is not None
        assert self.api_key is not None

    async def analyze_pdf(self, file_path: str | Path) -> str:
        pdf_path = Path(file_path)
        pdf_bytes = await asyncio.to_thread(pdf_path.read_bytes)
        return await self.analyze_pdf_bytes(pdf_bytes)

    async def analyze_pdf_bytes(self, pdf_bytes: bytes) -> str:
        analyze_url = (
            f"{self.endpoint.rstrip('/')}"
            "/documentintelligence/documentModels/prebuilt-layout:analyze"
            f"?_overload=analyzeDocument&api-version={self.api_version}"
            "&outputContentFormat=markdown"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "base64Source": base64.b64encode(pdf_bytes).decode("ascii"),
        }

        timeout = httpx.Timeout(self.request_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            submit_response = await client.post(
                analyze_url,
                headers=headers,
                json=payload,
            )
            if submit_response.status_code != 202:
                raise RuntimeError(
                    "Document Intelligence submit failed: "
                    f"{submit_response.status_code} {submit_response.text}"
                )

            operation_location = submit_response.headers.get("Operation-Location")
            if not operation_location:
                raise RuntimeError(
                    "Document Intelligence submit succeeded without Operation-Location"
                )

            for _ in range(self.max_poll_attempts):
                poll_response = await client.get(
                    operation_location,
                    headers={"Ocp-Apim-Subscription-Key": self.api_key},
                )
                if poll_response.status_code != 200:
                    raise RuntimeError(
                        "Document Intelligence poll failed: "
                        f"{poll_response.status_code} {poll_response.text}"
                    )

                payload = poll_response.json()
                status = str(payload.get("status", "")).lower()

                if status == "succeeded":
                    analyze_result = payload.get("analyzeResult", {})
                    content = analyze_result.get("content", "")
                    return content.strip()
                if status in {"failed", "canceled"}:
                    raise RuntimeError(
                        f"Document Intelligence analysis {status}: {payload}"
                    )

                await asyncio.sleep(self.poll_interval_seconds)

        raise RuntimeError("Document Intelligence analysis timed out before completion")
