from __future__ import annotations

import asyncio
from datetime import UTC
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from src.database.postgres.document_index_models import DocumentDatabaseIndex
from src.database.postgres.document_index_models import DocumentProcessingStatus
from src.database.postgres.document_index_models import DocumentUnitBase
from src.database.postgres.py_models import IntegrationType
from src.services.document_database.pipeline.index_pipeline import DocumentIndexPipeline
from src.services.document_database.ocr.doc_router import ExtractionPolicy


def _build_pipeline() -> DocumentIndexPipeline:
    index = DocumentDatabaseIndex(
        id=uuid4(),
        name="Test Index",
        description="Test",
        source_integration_id=uuid4(),
        source_integration_type=IntegrationType.UPLOAD,
        created_by=uuid4(),
        created_at=datetime.now(UTC),
        modified_at=datetime.now(UTC),
        keys=[],
    )
    return DocumentIndexPipeline(index=index, llm=object())


def test_format_llm_response_ignores_generated_index_values_when_schema_empty() -> None:
    pipeline = _build_pipeline()

    summary, short_summary, index_values, document_type, value_streams = pipeline._format_llm_response(
        {
            "summary": "Full summary",
            "short_summary": "Short summary",
            "document_type": "Rapport",
            "value_streams": ["Technisch beheer en onderhoud"],
            "index_values": [{"Projectnaam": "Spoortunnel"}],
        }
    )

    assert summary == "Full summary"
    assert short_summary == "Short summary"
    assert index_values == []
    assert document_type == "Rapport"
    assert value_streams == ["Technisch beheer en onderhoud"]


def test_format_llm_response_parses_json_string_when_schema_empty() -> None:
    pipeline = _build_pipeline()

    summary, short_summary, index_values, document_type, value_streams = pipeline._format_llm_response(
        """```json
        {"summary":"Full summary","short_summary":"Short summary","document_type":"Rapport","value_streams":["Registratie en administratie"],"index_values":[{"Project":"X"}]}
        ```"""
    )

    assert summary == "Full summary"
    assert short_summary == "Short summary"
    assert index_values == []
    assert document_type == "Rapport"
    assert value_streams == ["Registratie en administratie"]


def test_validate_classification_rejects_invalid_value_stream() -> None:
    pipeline = _build_pipeline()

    error = pipeline._validate_classification(
        document_type="Rapport",
        value_streams=["Onbekend"],
        valid_types={"Rapport"},
        valid_streams={"Registratie en administratie"},
    )

    assert error == "value_stream 'Onbekend' is not valid"


def test_intelligently_process_document_retries_invalid_classification() -> None:
    class _FakeLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def get_response(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return (
                    {
                        "summary": "Volledige samenvatting",
                        "short_summary": "Korte samenvatting",
                        "document_type": "Onjuist type",
                        "value_streams": ["Registratie en administratie"],
                        "index_values": [],
                    },
                    0,
                    0,
                )
            return (
                {
                    "summary": "Volledige samenvatting",
                    "short_summary": "Korte samenvatting",
                    "document_type": "Rapport",
                    "value_streams": ["Registratie en administratie"],
                    "index_values": [],
                },
                0,
                0,
            )

    llm = _FakeLLM()
    pipeline = _build_pipeline()
    pipeline.llm = llm

    with patch.object(
        DocumentIndexPipeline,
        "_truncate_text_for_llm",
        return_value=("Inspectierapport inhoud", 21, 21),
    ):
        summary, short_summary, index_values, document_type, value_streams = asyncio.run(
            pipeline.intelligently_process_document(
                full_text="Inspectierapport inhoud",
                filename="inspectie.pdf",
                metadata=None,
                images=None,
            )
        )

    assert llm.calls == 2
    assert summary == "Volledige samenvatting"
    assert short_summary == "Korte samenvatting"
    assert index_values == []
    assert document_type == "Rapport"
    assert value_streams == ["Registratie en administratie"]


def test_process_document_without_text_returns_empty_classification() -> None:
    class _FakeReader:
        async def read(self, *, path, filename, extraction_policy):
            _ = path, filename, extraction_policy
            return "   "

        async def get_document_info(self, *, path, filename):
            _ = path, filename
            return 123, 2

    pipeline = _build_pipeline()
    pipeline.ocreader = _FakeReader()

    document = DocumentUnitBase(
        id=uuid4(),
        integration_id=uuid4(),
        external_id="external-1",
        filename="empty.pdf",
        path="/docs/empty.pdf",
        size=0,
        web_url="/docs/empty.pdf",
        external_created_at=datetime.now(UTC),
        external_modified_at=datetime.now(UTC),
        status=DocumentProcessingStatus.NOT_PROCESSED,
        metadata={},
    )

    processed = asyncio.run(
        pipeline.process_document(
            document=document,
            local_path="/tmp/empty.pdf",
            extraction_policy=ExtractionPolicy.AUTO,
        )
    )

    assert processed is not None
    assert processed.document_type is None
    assert processed.value_streams == []
