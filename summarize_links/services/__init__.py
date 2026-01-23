"""Service layer for shared summarization workflows.

This package centralizes core business logic used by both CLI commands and
chat tools, enabling maximum code reuse and consistent behavior.
"""

from .summaries import SummaryMetadata, find_summary_metadata
from .summarization import (
    ERROR_TYPE_API,
    ERROR_TYPE_EXTRACTION,
    ERROR_TYPE_FETCH,
    ERROR_TYPE_INVALID_URL,
    ERROR_TYPE_MODEL_NOT_INSTALLED,
    ERROR_TYPE_OLLAMA,
    ERROR_TYPE_RATE_LIMIT,
    ProcessOutcome,
    process_url,
    process_urls,
    resummarize,
)

__all__ = [
    # Error type constants
    "ERROR_TYPE_API",
    "ERROR_TYPE_EXTRACTION",
    "ERROR_TYPE_FETCH",
    "ERROR_TYPE_INVALID_URL",
    "ERROR_TYPE_MODEL_NOT_INSTALLED",
    "ERROR_TYPE_OLLAMA",
    "ERROR_TYPE_RATE_LIMIT",
    # Core types and functions
    "ProcessOutcome",
    "process_url",
    "process_urls",
    "resummarize",
    "SummaryMetadata",
    "find_summary_metadata",
]
