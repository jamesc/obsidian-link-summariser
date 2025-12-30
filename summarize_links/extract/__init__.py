"""
Web content extraction package.

This package provides tools for fetching and extracting content from URLs:
- URL validation and security checks
- HTTP fetching with retry logic and browser headers
- HTML parsing and readable content extraction
- Metadata extraction (title, author, tags, etc.)

Main entry points:
- fetch_and_extract() - Fetch URL and extract content
- fetch_and_extract_metadata() - Fetch URL and extract full metadata
- fetch_content() - Just fetch the content
- extract_readable_content() - Just parse HTML
- extract_page_metadata() - Just extract metadata from HTML
- validate_url() - Validate a URL before use
"""

# Public API
# Re-export constants and private functions for tests
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
from summarize_links.extract.validation import validate_url
from summarize_links.models import PageMetadata

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


def fetch_and_extract_metadata(url: str) -> PageMetadata:
    """
    Fetch a URL and extract full metadata including content.

    This is the enhanced entry point that returns structured metadata.
    Content is automatically truncated to MAX_CONTENT_LENGTH.
    Supports both HTML pages and raw Markdown files.

    Args:
        url: URL to fetch and extract from.

    Returns:
        PageMetadata object with all extracted information.

    Raises:
        ContentFetchError: If fetching fails.
        ContentExtractionError: If extraction fails.
    """
    content, content_type = fetch_content(url)

    if content_type == "markdown":
        # For markdown files, extract metadata from the content itself
        from summarize_links.extract.metadata import _extract_markdown_metadata

        metadata = _extract_markdown_metadata(content, url)
    else:
        # For HTML, use the full extraction pipeline
        metadata = extract_page_metadata(content, url)

    # Truncate content
    metadata.content = truncate_content(metadata.content)

    return metadata
