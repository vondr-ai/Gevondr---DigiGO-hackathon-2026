from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# Stub classes to replace prometheus_client functionality directly
class MetricStub:
    def __init__(self, name, documentation, labelnames=None):
        self.name = name
        self.documentation = documentation
        self.labelnames = labelnames or []

    def labels(self, *args, **kwargs):
        return self

    def inc(self, amount=1):
        pass

    def observe(self, value):
        pass


class Counter(MetricStub):
    pass


class Histogram(MetricStub):
    pass


# Define metrics as stubs so imports don't break
FUNCTION_LATENCY = Histogram(
    "function_execution_seconds", "Time spent processing a function", ["function_name"]
)

TOOL_LATENCY = Histogram(
    "tool_execution_seconds", "Time spent processing a tool call", ["tool_name"]
)

TOOL_ERRORS = Counter(
    "tool_execution_errors_total", "Errors during tool execution", ["tool_name"]
)

TOOL_SUCCESSES = Counter(
    "tool_execution_success_total", "Successful tool executions", ["tool_name"]
)

API_ERRORS = Counter("api_errors_total", "Total API errors", ["endpoint", "error_type"])

AGENT_TOOL_CALLS_PER_RUN = Histogram(
    "agent_tool_calls_per_run",
    "Distribution of the number of tool calls per agent run",
    ["agent_model"],
)

AGENT_RESPONSE_LENGTH = Histogram(
    "agent_response_length_chars",
    "Distribution of the final agent response length in characters",
    ["agent_model"],
)

SUB_AGENT_INPUT_TOKENS = Counter(
    "sub_agent_input_tokens_total",
    "Total input tokens used by sub-agents",
    ["tool_name", "model"],
)

SUB_AGENT_OUTPUT_TOKENS = Counter(
    "sub_agent_output_tokens_total",
    "Total output tokens used by sub-agents",
    ["tool_name", "model"],
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint", "status_code"],
)

HTTP_REQUEST_COUNT = Counter(
    "http_request_total", "Total HTTP requests", ["method", "endpoint", "status_code"]
)

PIPELINE_STAGE_DURATION = Histogram(
    "pipeline_stage_duration_seconds",
    "Document pipeline stage duration in seconds",
    ["stage", "parent_stage", "status"],
)

PIPELINE_STAGE_EVENTS = Counter(
    "pipeline_stage_events_total",
    "Total document pipeline stage events grouped by status",
    ["stage", "parent_stage", "status"],
)

INDEX_SEARCH_STAGE_DURATION = Histogram(
    "index_search_stage_duration_seconds",
    "Vector search pipeline stage duration in seconds",
    ["stage", "status"],
)

INDEX_SEARCH_STAGE_EVENTS = Counter(
    "index_search_stage_events_total",
    "Total vector search pipeline stage executions grouped by status",
    ["stage", "status"],
)
