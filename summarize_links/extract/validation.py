"""
URL validation module.

This module handles URL validation and security checks to ensure
URLs are safe and well-formed before attempting to fetch them.
"""

from urllib.parse import urlparse

from summarize_links.exceptions import URLValidationError

__all__ = [
    "validate_url",
]

# ----- URL Validation Constants -----

# Allowed URL schemes (security: prevent file://, javascript:, etc.)
ALLOWED_SCHEMES = {"http", "https"}

# Maximum URL length to accept (prevent memory issues with very long URLs)
MAX_URL_LENGTH = 2048


def validate_url(url: str) -> None:
    """
    Validate a URL for safety and correctness.

    Checks:
    - URL is not empty
    - URL length is reasonable (max 2048 characters)
    - URL has valid scheme (http or https only)
    - URL has a valid domain/netloc

    Args:
        url: The URL to validate.

    Raises:
        URLValidationError: If the URL is invalid or unsafe.
    """
    if not url:
        raise URLValidationError("URL cannot be empty")

    if not isinstance(url, str):
        raise URLValidationError(f"URL must be a string, got {type(url).__name__}")

    # Check length
    if len(url) > MAX_URL_LENGTH:
        raise URLValidationError(
            f"URL exceeds maximum length ({len(url)} > {MAX_URL_LENGTH} characters)"
        )

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise URLValidationError(f"Failed to parse URL: {e}") from e

    # Check scheme
    scheme = parsed.scheme.lower()
    if not scheme:
        raise URLValidationError(f"URL has no scheme (expected http or https): {url[:100]}")
    if scheme not in ALLOWED_SCHEMES:
        raise URLValidationError(
            f"Invalid URL scheme '{scheme}' (only http and https allowed): {url[:100]}"
        )

    # Check domain/netloc
    if not parsed.netloc:
        raise URLValidationError(f"URL has no domain: {url[:100]}")

    # Basic domain format check (must have at least one dot or be localhost)
    domain = parsed.netloc.lower()
    # Strip port if present
    if ":" in domain:
        domain = domain.split(":")[0]

    if domain != "localhost" and "." not in domain:
        raise URLValidationError(f"URL has invalid domain format: {domain}")
