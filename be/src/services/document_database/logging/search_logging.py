from __future__ import annotations

import json
import logging
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Dict
from typing import List
from typing import Optional
from uuid import UUID

_logger = logging.getLogger("search_pipeline")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    formatter = logging.Formatter("%(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    _logger.addHandler(stream_handler)

    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "search_pipeline.log")
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)

_logger.propagate = False


def _serialize_top_results(results: List[Dict]) -> List[Dict]:
    top_entries = []
    for idx, res in enumerate(results[:8], start=1):
        text_preview = (res.get("text") or "").strip()
        top_entries.append(
            {
                "rank": idx,
                "document_id": res.get("document_id"),
                "type": res.get("type"),
                "score": res.get("score"),
                "text_preview": text_preview[:200],
            }
        )
    return top_entries


def log_search_event(
    integration_id: UUID,
    user_id: UUID,
    query: str,
    stage_durations: Dict[str, float],
    total_duration: float,
    top_results: List[Dict],
    reranker_info: Optional[Dict] = None,
) -> None:
    payload = {
        "event": "index_vector_search",
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "integration_id": str(integration_id),
        "user_id": str(user_id),
        "query": query,
        "total_duration_seconds": round(total_duration, 6),
        "stage_durations_ms": {
            stage: round(duration * 1000, 3)
            for stage, duration in stage_durations.items()
        },
        "result_count": len(top_results),
        "top_results": _serialize_top_results(top_results),
    }
    if reranker_info is not None:
        payload["reranker"] = reranker_info
    _logger.info(json.dumps(payload, ensure_ascii=True))
