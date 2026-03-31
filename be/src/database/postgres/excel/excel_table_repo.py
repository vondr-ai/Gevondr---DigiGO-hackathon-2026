from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class ExcelTableMetadata:
    document_id: UUID
    project_omgeving_id: UUID | None
    filename: str
    sheet_name: str
    table_name: str
    column_definitions: list[dict[str, str]]
    row_count: int
    column_count: int


class ExcelTableRepository:
    def upsert_document_tables(
        self,
        *,
        document_id: UUID,
        project_omgeving_id: UUID | None,
        filename: str,
        tables: list[ExcelTableMetadata],
        rows_by_table: dict[str, list[list[object | None]]],
    ) -> None:
        _ = document_id
        _ = project_omgeving_id
        _ = filename
        _ = tables
        _ = rows_by_table


def get_excel_table_repo() -> ExcelTableRepository:
    return ExcelTableRepository()
