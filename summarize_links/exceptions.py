"""
Custom exceptions for the Obsidian Link Summarizer.

This module defines specific exception classes for different error scenarios,
enabling clearer error handling and more informative error messages throughout
the application.
"""

__all__ = [
    "SummarizerError",
    "ConfigError",
    "URLExtractionError",
    "URLValidationError",
    "ContentFetchError",
    "ContentExtractionError",
    "GeminiAPIError",
    "RateLimitError",
    "NoteReadError",
    "NoteWriteError",
]


class SummarizerError(Exception):
    """Base exception for all summarizer errors."""

    pass


class ConfigError(SummarizerError):
    """Raised when there's a configuration error (missing keys, invalid values)."""

    pass


class URLExtractionError(SummarizerError):
    """Raised when URL extraction from a note fails."""

    pass


class URLValidationError(SummarizerError):
    """Raised when a URL fails validation (invalid scheme, malformed, etc.)."""

    pass


class ContentFetchError(SummarizerError):
    """Raised when fetching web content fails (network errors, timeouts, etc.)."""

    pass


class ContentExtractionError(SummarizerError):
    """Raised when extracting readable content from HTML fails."""

    pass


class GeminiAPIError(SummarizerError):
    """Raised when the Gemini API call fails."""

    pass


class RateLimitError(GeminiAPIError):
    """Raised when Gemini API rate limit is hit (HTTP 429)."""

    pass


class NoteReadError(SummarizerError):
    """Raised when reading an Obsidian note fails."""

    pass


class NoteWriteError(SummarizerError):
    """Raised when writing a summary note fails."""

    pass
