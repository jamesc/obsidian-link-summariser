"""
Fallback logic for Playwright-based fetching.

This module contains the logic for determining when to fallback to
Playwright browser automation based on HTTP errors.
"""

import logging

from summarize_links.exceptions import ContentFetchError

__all__ = [
    "should_retry_with_playwright",
    "should_retry_with_extraction_fallback",
    "get_error_category",
    "PLAYWRIGHT_RETRYABLE_ERRORS",
]

logger = logging.getLogger(__name__)

# ----- Error Patterns that Trigger Playwright Fallback -----

# Error patterns that indicate bot detection or blocking that Playwright may bypass
PLAYWRIGHT_RETRYABLE_ERRORS = [
    "HTTP 401",  # Unauthorized - often bot detection masquerading as auth
    "HTTP 403",  # Forbidden - most common bot blocking (Cloudflare, etc.)
    "HTTP 429",  # Too Many Requests - may be bot detection vs true rate limit
    "requires JavaScript",  # JavaScript-only SPAs that need rendering
    "No readable content",  # Extraction failed - may be JS-rendered or bot-blocked
]


def get_error_category(error: ContentFetchError) -> str:
    """
    Categorize ContentFetchError for logging and metrics.

    Args:
        error: The ContentFetchError that occurred.

    Returns:
        Error category string: bot_detection, rate_limit, timeout,
        connection_error, server_error, not_found, content_type_mismatch,
        javascript_required, or unknown.
    """
    error_msg = str(error).lower()

    # Check for specific error patterns
    if "404" in error_msg:
        return "not_found"
    elif "401" in error_msg or "403" in error_msg:
        return "bot_detection"
    elif "429" in error_msg:
        return "rate_limit"
    elif "timeout" in error_msg:
        return "timeout"
    elif "connection" in error_msg:
        return "connection_error"
    elif any(code in error_msg for code in ["500", "502", "503", "504"]):
        return "server_error"
    elif "content type" in error_msg or "content-type" in error_msg:
        return "content_type_mismatch"
    elif "javascript" in error_msg:
        return "javascript_required"
    elif "no readable content" in error_msg or "extraction" in error_msg:
        return "extraction_failed"
    else:
        return "unknown"


def should_retry_with_playwright(error: ContentFetchError) -> bool:
    """
    Check if error should trigger Playwright fallback.

    Retries on errors that indicate bot detection or blocking:
    - HTTP 401/403 (often bot detection)
    - HTTP 429 (rate limiting, may be bot-specific)
    - JavaScript requirements
    - Content extraction failures

    Args:
        error: The ContentFetchError that occurred.

    Returns:
        True if error matches retryable patterns, False otherwise.
    """
    error_msg = str(error)
    error_lower = error_msg.lower()

    # Check if error matches any retryable pattern (case-insensitive)
    result = any(pattern.lower() in error_lower for pattern in PLAYWRIGHT_RETRYABLE_ERRORS)

    # Log decision for debugging
    if result:
        logger.debug(f"Error matches Playwright retry pattern: {error_msg[:100]}")
    else:
        logger.debug(f"Error does NOT match Playwright retry pattern: {error_msg[:100]}")

    return result


def should_retry_with_extraction_fallback(error: Exception) -> bool:
    """
    Check if extraction error should trigger Playwright fallback.

    This is used when HTTP fetch succeeds but content extraction fails.
    Common causes include JavaScript-rendered content or bot-blocked HTML.

    Args:
        error: The ContentExtractionError that occurred.

    Returns:
        True if error matches retryable patterns, False otherwise.
    """
    error_msg = str(error)
    error_lower = error_msg.lower()

    # Check if error matches any retryable pattern (case-insensitive)
    result = any(pattern.lower() in error_lower for pattern in PLAYWRIGHT_RETRYABLE_ERRORS)

    # Log decision for debugging
    if result:
        logger.debug(f"Extraction error matches Playwright retry pattern: {error_msg[:100]}")
    else:
        logger.debug(f"Extraction error does NOT match Playwright retry pattern: {error_msg[:100]}")

    return result
