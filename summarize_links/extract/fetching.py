"""
HTTP fetching module.

This module handles fetching content from URLs with:
- Browser-like headers to avoid bot detection
- Retry logic for transient errors
- Paywall detection
- Content type detection (HTML, markdown, text)
"""

import logging
from urllib.parse import urlparse

import requests
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from summarize_links.config import REQUEST_TIMEOUT
from summarize_links.exceptions import ContentFetchError
from summarize_links.extract.validation import validate_url

__all__ = [
    "fetch_content",
    "fetch_html",
    # Constants exported for tests
    "HTTP_RETRY_ATTEMPTS",
    # Private functions exported for tests
    "_create_session",
    "_format_http_error",
    "_get_paywall_info",
    "_is_javascript_required",
]

# Configure module logger
logger = logging.getLogger(__name__)

# ----- Constants -----

# Retry configuration for transient HTTP errors
HTTP_RETRY_ATTEMPTS = 3  # Total attempts (1 initial + 2 retries)
HTTP_RETRY_WAIT_MIN = 1  # Minimum wait between retries (seconds)
HTTP_RETRY_WAIT_MAX = 4  # Maximum wait between retries (seconds)

# User agent to identify as a legitimate browser (some sites block default requests)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Full set of browser headers to avoid bot detection
# These mimic a real Chrome browser request
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Cache-Control": "max-age=0",
}

# HTTP error messages with user-friendly explanations
HTTP_ERROR_MESSAGES = {
    401: "Authentication required - likely paywalled content",
    403: "Access forbidden (site may block automated requests)",
    404: "Page not found (URL may be incorrect or content removed)",
    429: "Too many requests (rate limited by server)",
    500: "Server error (site is having issues)",
    502: "Bad gateway (site is having issues)",
    503: "Service unavailable (site may be down)",
}

# Known paywall domains with specific messages
PAYWALL_DOMAINS = {
    "wsj.com": "Wall Street Journal (subscription required)",
    "nytimes.com": "New York Times (subscription required)",
    "ft.com": "Financial Times (subscription required)",
    "economist.com": "The Economist (subscription required)",
    "bloomberg.com": "Bloomberg (subscription required)",
    "washingtonpost.com": "Washington Post (subscription required)",
    "theathletic.com": "The Athletic (subscription required)",
    "thetimes.co.uk": "The Times UK (subscription required)",
    "telegraph.co.uk": "The Telegraph (subscription required)",
    "hbr.org": "Harvard Business Review (subscription required)",
    "medium.com": "Medium (may require membership for some articles)",
    "seekingalpha.com": "Seeking Alpha (premium content)",
    "barrons.com": "Barron's (subscription required)",
}


class _RetryableError(Exception):
    """Internal exception for errors that should trigger a retry."""

    pass


def _create_session() -> requests.Session:
    """
    Create a requests session with browser-like headers.

    Using a session persists cookies across redirects and
    makes the request appear more like a real browser.

    Returns:
        Configured requests Session.
    """
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    return session


def _is_javascript_required(html: str) -> bool:
    """
    Detect if a page requires JavaScript to display content.

    This checks for common patterns in JavaScript-only SPAs (Single Page Applications)
    that return an empty HTML shell requiring JavaScript to render.

    Args:
        html: The HTML content to check.

    Returns:
        True if the page appears to require JavaScript, False otherwise.

    Examples:
        >>> _is_javascript_required('<html><body>You need to enable JavaScript</body></html>')
        True
        >>> _is_javascript_required(
        ...     '<html><body><h1>Real Content</h1><p>More text</p></body></html>'
        ... )
        False
    """
    html_lower = html.lower()

    # Common messages in JavaScript-only pages
    js_required_phrases = [
        "you need to enable javascript",
        "please enable javascript",
        "javascript is required",
        "javascript must be enabled",
        "enable javascript to run",
        "this app requires javascript",
        "requires javascript to be enabled",
    ]

    # Check if any of these phrases appear
    has_js_message = any(phrase in html_lower for phrase in js_required_phrases)

    if not has_js_message:
        return False

    # If we found a JS message, check if the page is suspiciously small
    # Real pages with content are typically much larger
    # SPAs usually have just a shell with scripts
    if len(html) < 10000:  # Less than 10KB suggests empty shell
        return True

    # For larger pages, check body content to see if it's mostly empty
    # Extract text between <body> and </body> tags
    body_start = html_lower.find("<body")
    body_end = html_lower.find("</body>")

    if body_start == -1 or body_end == -1:
        return False

    # Find the actual start of body content (after the opening tag)
    body_content_start = html_lower.find(">", body_start) + 1
    body_content = html[body_content_start:body_end]

    # Remove script and style tags from body content
    import re

    body_no_scripts = re.sub(
        r"<script[^>]*>.*?</script>", "", body_content, flags=re.IGNORECASE | re.DOTALL
    )
    body_no_scripts = re.sub(
        r"<style[^>]*>.*?</style>", "", body_no_scripts, flags=re.IGNORECASE | re.DOTALL
    )

    # Remove HTML tags and check remaining text length
    text_only = re.sub(r"<[^>]+>", "", body_no_scripts)
    text_only = text_only.strip()

    # If body has very little actual text (< 200 chars), it's likely a JS-only page
    return len(text_only) < 200


def _get_paywall_info(url: str) -> str | None:
    """
    Check if URL is from a known paywall site.

    Args:
        url: The URL to check.

    Returns:
        Paywall description if known, None otherwise.
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "")

    # Check exact match first
    if domain in PAYWALL_DOMAINS:
        return PAYWALL_DOMAINS[domain]

    # Check if domain ends with any known paywall domain
    for paywall_domain, description in PAYWALL_DOMAINS.items():
        if domain.endswith(paywall_domain):
            return description

    return None


def _format_http_error(status_code: int, url: str) -> str:
    """
    Format an HTTP error with a user-friendly message.

    For 401/403 errors, checks if the URL is from a known paywall
    site and provides specific information.

    Args:
        status_code: HTTP status code.
        url: The URL that failed.

    Returns:
        Formatted error message.
    """
    # For auth errors, check for known paywall sites
    if status_code in (401, 403):
        paywall_info = _get_paywall_info(url)
        if paywall_info:
            return f"HTTP {status_code}: Paywall - {paywall_info}"

    explanation = HTTP_ERROR_MESSAGES.get(status_code, "Request failed")
    return f"HTTP {status_code}: {explanation}"


def _log_retry(retry_state: RetryCallState) -> None:
    """Log retry attempts for debugging."""
    logger.warning(
        "Retrying fetch (attempt %d/%d) after error: %s",
        retry_state.attempt_number,
        HTTP_RETRY_ATTEMPTS,
        retry_state.outcome.exception() if retry_state.outcome else "unknown",
    )


@retry(
    retry=retry_if_exception_type(_RetryableError),
    stop=stop_after_attempt(HTTP_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=HTTP_RETRY_WAIT_MIN, max=HTTP_RETRY_WAIT_MAX),
    before_sleep=_log_retry,
    reraise=True,
)
def _fetch_with_retry(url: str, timeout: int) -> tuple[str, str]:
    """
    Internal fetch function with retry logic for transient errors.

    Only retries on:
    - Connection errors (network issues)
    - Timeouts
    - Server errors (5xx)

    Does NOT retry on:
    - Client errors (4xx) - these are permanent failures
    - Invalid content types
    """
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    try:
        session = _create_session()
        session.headers["Referer"] = referer

        response = session.get(url, timeout=timeout, allow_redirects=True)

        # Check for server errors (5xx) - these are retryable
        if 500 <= response.status_code < 600:
            raise _RetryableError(f"Server error {response.status_code}")

        response.raise_for_status()

        # Determine content type
        content_type_header = response.headers.get("Content-Type", "").lower()

        # Check for markdown (by content-type or URL extension)
        if "markdown" in content_type_header or url.lower().endswith(".md"):
            logger.info(f"Fetched {len(response.text)} chars of markdown from {url}")
            return response.text, "markdown"

        # Check for HTML or text
        if "html" in content_type_header or "text" in content_type_header:
            # Check if this is a JavaScript-only page (SPA with no server-side rendering)
            if _is_javascript_required(response.text):
                raise ContentFetchError(
                    "Page requires JavaScript to render content (detected empty SPA shell)"
                )

            logger.info(f"Fetched {len(response.text)} characters from {url}")
            return response.text, "html"

        raise ContentFetchError(f"URL returned unsupported content type: {content_type_header}")

    except requests.exceptions.Timeout as e:
        # Timeouts are retryable
        raise _RetryableError(f"Timeout after {timeout}s") from e
    except requests.exceptions.ConnectionError as e:
        # Connection errors are retryable
        raise _RetryableError(f"Connection error: {e}") from e
    except requests.exceptions.HTTPError as e:
        # Client errors (4xx) are NOT retryable - raise directly
        raise ContentFetchError(_format_http_error(e.response.status_code, url)) from e
    except _RetryableError:
        # Let retryable errors propagate for tenacity
        raise
    except requests.exceptions.RequestException as e:
        raise ContentFetchError(f"Request failed for {url}: {e}") from e


def fetch_content(url: str, timeout: int = REQUEST_TIMEOUT) -> tuple[str, str]:
    """
    Fetch content from a URL and return content with its type.

    Uses browser-like headers and a session to avoid bot detection.
    Automatically follows redirects and persists cookies.
    Retries on transient errors (timeouts, connection errors, server errors).

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (content, content_type) where content_type is 'html', 'markdown', or 'text'.

    Raises:
        URLValidationError: If the URL is invalid or unsafe.
        ContentFetchError: If the request fails after all retries.
    """
    # Validate URL before attempting to fetch
    validate_url(url)

    logger.debug(f"Fetching URL: {url}")

    try:
        return _fetch_with_retry(url, timeout)
    except _RetryableError as e:
        # All retries exhausted - convert to ContentFetchError
        raise ContentFetchError(f"Failed after {HTTP_RETRY_ATTEMPTS} attempts: {url} ({e})") from e


def fetch_html(url: str, timeout: int = REQUEST_TIMEOUT) -> str:
    """
    Fetch HTML content from a URL.

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        HTML content as string.

    Raises:
        ContentFetchError: If the request fails.
    """
    content, _ = fetch_content(url, timeout)
    return content
