"""
Fallback logic for Playwright-based fetching.

This module contains the logic for determining when to fallback to
Playwright browser automation based on HTTP errors and configured phase.
"""

import logging
from typing import Literal

from summarize_links.exceptions import ContentFetchError

__all__ = [
    "should_retry_with_playwright",
    "should_retry_with_extraction_fallback",
    "get_error_category",
    "PLAYWRIGHT_RETRYABLE_ERRORS",
    "PhaseType",
    "VALID_PHASES",
]

logger = logging.getLogger(__name__)

# ----- Error Patterns by Phase -----

# Valid phase names - single source of truth
PhaseType = Literal["phase1", "phase2", "phase3", "phase4"]
VALID_PHASES: tuple[str, ...] = ("phase1", "phase2", "phase3", "phase4")

# Tiered error patterns that trigger Playwright fallback
# Each phase includes errors from previous phases
PLAYWRIGHT_RETRYABLE_ERRORS = {
    "phase1": [
        "HTTP 401",  # Unauthorized - often bot detection
        "HTTP 403",  # Forbidden - most common bot blocking
        "requires JavaScript",  # JavaScript-only SPAs that need rendering
        "No readable content",  # Extraction failed - may be JS-rendered or bot-blocked
    ],
    "phase2": [
        "HTTP 429",  # Too Many Requests - may be bot detection vs true rate limit
    ],
    "phase3": [
        "Timeout",  # After retries - bot detection may delay indefinitely
        "Connection",  # Connection errors - aggressive bot blockers
    ],
    "phase4": [
        "unsupported content type",  # Servers return different content to bots
    ],
}


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


def should_retry_with_playwright(
    error: ContentFetchError,
    phase: PhaseType = "phase1",
) -> bool:
    """
    Check if error should trigger Playwright fallback based on configured phase.

    Phase 1 (default): 401, 403 only - High confidence bot detection
    Phase 2: Phase 1 + 429 - Add rate limiting
    Phase 3: Phase 2 + timeout/connection errors - Network-level blocking
    Phase 4: Phase 3 + content-type mismatches - All retryable cases

    Args:
        error: The ContentFetchError that occurred.
        phase: Configured fallback phase (default: "phase1").

    Returns:
        True if error matches patterns for configured phase, False otherwise.

    Raises:
        ValueError: If phase is not one of the valid phase values.
    """
    # Validate phase parameter
    if phase not in VALID_PHASES:
        raise ValueError(f"Invalid phase: {phase!r}. Valid phases: {', '.join(VALID_PHASES)}")

    error_msg = str(error)

    # Collect all patterns up to configured phase
    patterns_to_check: list[str] = []

    # Add patterns for each phase up to the configured one
    # Use VALID_PHASES as single source of truth
    for p in VALID_PHASES:
        patterns_to_check.extend(PLAYWRIGHT_RETRYABLE_ERRORS[p])
        if p == phase:
            break

    # Check if error matches any pattern (case-insensitive)
    error_lower = error_msg.lower()
    matches = [pattern.lower() in error_lower for pattern in patterns_to_check]
    result = any(matches)

    # Log decision for debugging
    if result:
        logger.debug(f"Error matches Playwright retry pattern (phase={phase}): {error_msg[:100]}")
    else:
        logger.debug(
            f"Error does NOT match Playwright retry pattern (phase={phase}): {error_msg[:100]}"
        )

    return result


def should_retry_with_extraction_fallback(
    error: Exception,
    phase: PhaseType = "phase1",
) -> bool:
    """
    Check if extraction error should trigger Playwright fallback.

    This is used when HTTP fetch succeeds but content extraction fails.
    Common causes include JavaScript-rendered content or bot-blocked HTML.

    Args:
        error: The ContentExtractionError that occurred.
        phase: Configured fallback phase (default: "phase1").

    Returns:
        True if error matches patterns for configured phase, False otherwise.

    Raises:
        ValueError: If phase is not one of the valid phase values.
    """
    # Validate phase parameter
    if phase not in VALID_PHASES:
        raise ValueError(f"Invalid phase: {phase!r}. Valid phases: {', '.join(VALID_PHASES)}")

    error_msg = str(error)

    # Collect all patterns up to configured phase
    patterns_to_check: list[str] = []

    # Add patterns for each phase up to the configured one
    # Use VALID_PHASES as single source of truth
    for p in VALID_PHASES:
        patterns_to_check.extend(PLAYWRIGHT_RETRYABLE_ERRORS[p])
        if p == phase:
            break

    # Check if error matches any pattern (case-insensitive)
    error_lower = error_msg.lower()
    matches = [pattern.lower() in error_lower for pattern in patterns_to_check]
    result = any(matches)

    # Log decision for debugging
    if result:
        logger.debug(
            f"Extraction error matches Playwright retry pattern (phase={phase}): {error_msg[:100]}"
        )
    else:
        logger.debug(
            f"Extraction error does NOT match Playwright retry pattern "
            f"(phase={phase}): {error_msg[:100]}"
        )

    return result
