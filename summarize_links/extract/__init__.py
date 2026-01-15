"""
Web content extraction package.

This package provides tools for fetching and extracting content from URLs:
- URL validation and security checks
- HTTP fetching with retry logic and browser headers
- HTML parsing and readable content extraction
- Metadata extraction (title, author, tags, etc.)
- Playwright fallback for bot-blocked URLs

Main entry points:
- fetch_and_extract() - Fetch URL and extract content
- fetch_and_extract_metadata() - Fetch URL and extract full metadata (with Playwright fallback)
- fetch_content() - Just fetch the content
- extract_readable_content() - Just parse HTML
- extract_page_metadata() - Just extract metadata from HTML
- validate_url() - Validate a URL before use
"""

import logging

from summarize_links.exceptions import ContentFetchError

# Public API
# Re-export constants and private functions for tests
from summarize_links.extract.fallback import (
    PhaseType,
    get_error_category,
    should_retry_with_playwright,
)
from summarize_links.extract.fetching import (
    HTTP_RETRY_ATTEMPTS,
    _create_session,
    _format_http_error,
    _get_paywall_info,
    fetch_content,
    fetch_html,
)
from summarize_links.extract.html_parsing import (
    _clean_markdown,
    _clean_text,
    _extract_article_content,
    _find_largest_text_block,
    _is_content_garbled,
    _is_non_content_element,
    extract_readable_content,
    truncate_content,
)
from summarize_links.extract.metadata import (
    _extract_article_tags,
    _extract_author,
    _extract_description,
    _extract_markdown_metadata,
    _extract_published_date,
    _extract_site_name,
    _extract_title,
    extract_page_metadata,
)
from summarize_links.extract.playwright_fetching import (
    fetch_content_with_playwright,
)
from summarize_links.extract.validation import validate_url
from summarize_links.models import PageMetadata

logger = logging.getLogger(__name__)

__all__ = [
    # High-level fetch functions
    "fetch_and_extract",
    "fetch_and_extract_metadata",
    # Individual operations
    "fetch_content",
    "fetch_html",
    "extract_readable_content",
    "extract_page_metadata",
    "truncate_content",
    # URL validation
    "validate_url",
    # Constants
    "HTTP_RETRY_ATTEMPTS",
    # Private functions (for tests)
    "_clean_text",
    "_clean_markdown",
    "_create_session",
    "_extract_article_content",
    "_extract_article_tags",
    "_extract_author",
    "_extract_description",
    "_extract_markdown_metadata",
    "_extract_published_date",
    "_extract_site_name",
    "_extract_title",
    "_find_largest_text_block",
    "_format_http_error",
    "_get_paywall_info",
    "_is_content_garbled",
    "_is_non_content_element",
]


def fetch_and_extract(url: str) -> tuple[str, str | None]:
    """
    Fetch a URL and extract readable content.

    This is the main entry point combining fetch and extraction.

    Args:
        url: URL to fetch and extract content from.

    Returns:
        Tuple of (extracted_content, page_title).

    Raises:
        ContentFetchError: If fetching fails.
        ContentExtractionError: If extraction fails.
    """
    html = fetch_html(url)
    content, title = extract_readable_content(html)
    content = truncate_content(content)
    return content, title


def fetch_and_extract_metadata(
    url: str,
    playwright_enabled: bool = True,
    playwright_phase: PhaseType = "phase1",
    playwright_timeout: int = 30,
) -> PageMetadata:
    """
    Fetch a URL and extract full metadata including content.

    This is the enhanced entry point that returns structured metadata.
    Content is automatically truncated to MAX_CONTENT_LENGTH.
    Supports both HTML pages and raw Markdown files.

    Automatically falls back to Playwright for URLs blocked by bot detection
    (401/403 errors by default, configurable via playwright_phase).

    Args:
        url: URL to fetch and extract from.
        playwright_enabled: Enable Playwright fallback (default: True).
        playwright_phase: Phase level for fallback (phase1-phase4, default: phase1).
        playwright_timeout: Timeout in seconds for Playwright operations (default: 30).

    Returns:
        PageMetadata object with all extracted information.

    Raises:
        ContentFetchError: If fetching fails (both HTTP and Playwright if applicable).
        ContentExtractionError: If extraction fails.
    """
    http_error_category: str | None = None  # Track error category if fallback used

    try:
        # Try HTTP first (fast path)
        content, content_type = fetch_content(url)
        logger.debug(f"✓ HTTP fetch succeeded: {url}")
        fetch_method = "http"

    except ContentFetchError as http_error:
        # Check if Playwright fallback should be attempted
        if playwright_enabled and should_retry_with_playwright(http_error, playwright_phase):
            error_category = get_error_category(http_error)
            http_error_category = error_category  # Store for observability
            logger.info(f"HTTP fetch failed ({error_category}), retrying with Playwright: {url}")

            try:
                # Fallback to Playwright
                content, content_type = fetch_content_with_playwright(
                    url, timeout=playwright_timeout
                )
                logger.info(f"✓ Playwright fetch succeeded: {url}")
                fetch_method = "playwright"

            except ContentFetchError as playwright_error:
                # Both methods failed - enhance error message
                logger.error(
                    f"✗ Both HTTP and Playwright failed for {url}. "
                    f"HTTP: {http_error}, Playwright: {playwright_error}"
                )
                raise ContentFetchError(
                    f"{http_error} (Playwright fallback also failed: {playwright_error})"
                ) from playwright_error
        else:
            # Playwright disabled or error not retryable
            reason = "disabled" if not playwright_enabled else f"not in {playwright_phase}"
            logger.debug(f"Playwright fallback {reason} for error: {http_error}")
            raise

    # Extract metadata based on content type
    if content_type == "markdown":
        # For markdown files, extract metadata from the content itself
        from summarize_links.extract.metadata import _extract_markdown_metadata

        metadata = _extract_markdown_metadata(content, url)
    else:
        # For HTML, use the full extraction pipeline
        metadata = extract_page_metadata(content, url)

    # Truncate content
    metadata.content = truncate_content(metadata.content)

    # Store fetch metadata for observability
    metadata.fetch_method = fetch_method
    metadata.http_error_category = http_error_category
    logger.debug(
        f"Content fetched via {fetch_method}: {len(metadata.content)} chars"
        + (f" (after HTTP {http_error_category} error)" if http_error_category else "")
    )

    return metadata
