from __future__ import annotations

import json
import logging
from datetime import datetime
from datetime import timezone
from typing import Optional

from src.monitoring import PIPELINE_STAGE_DURATION
from src.monitoring import PIPELINE_STAGE_EVENTS


class PipelineLogger:
    """
    Central logger for document pipeline events.

    The original implementation persisted data inside a local SQLite database,
    which made it difficult to aggregate metrics in Prometheus or ship logs to Loki.
    This refactor keeps the singleton interface but routes each event to:
      1. Prometheus metrics (histogram + counter) for low-cardinality aggregation.
      2. Structured JSON logs that Loki/Promtail can ingest.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PipelineLogger, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._logger = logging.getLogger("document_pipeline")
        self._logger.setLevel(logging.INFO)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
        self._logger.propagate = False
        self._initialized = True

    def log_stage(
        self,
        doc_id: str,
        filename: str,
        stage: str,
        duration: float,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
        parent_stage: Optional[str] = None,
    ) -> None:
        """
        Emit a pipeline stage event to Prometheus and structured logs.
        """
        stage_label = stage or "unknown"
        parent_label = parent_stage or "unspecified"
        status_label = status or "UNKNOWN"
        safe_duration = max(duration, 0.0)

        # Prometheus metrics
        PIPELINE_STAGE_DURATION.labels(stage_label, parent_label, status_label).observe(
            safe_duration
        )
        PIPELINE_STAGE_EVENTS.labels(stage_label, parent_label, status_label).inc()

        # Loki-friendly structured log
        event = {
            "event": "pipeline_stage",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "doc_id": str(doc_id),
            "filename": filename,
            "stage": stage_label,
            "parent_stage": parent_label,
            "duration_seconds": safe_duration,
            "status": status_label,
            "error_message": error_message,
        }

        try:
            self._logger.info(json.dumps(event, ensure_ascii=True))
        except Exception:
            # Fall back to repr if JSON serialization fails
            self._logger.info(repr(event))
