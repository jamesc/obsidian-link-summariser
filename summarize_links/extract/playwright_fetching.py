"""
Playwright-based web content fetching module.

This module provides browser-based fetching using Playwright as a fallback
for URLs that fail with standard HTTP requests due to bot detection or
access controls (401, 403, etc.).

Key features:
- Self-contained fetches (no shared state)
- Headless browser automation with Chromium
- Timeout and error handling
- Asyncio-safe (runs in thread when needed)

Design Note:
    This module intentionally avoids shared browser contexts and complex cleanup
    logic. Each fetch is completely self-contained - creates browser, fetches,
    and cleans up in the same thread. This is slightly slower than context reuse
    but eliminates all threading/greenlet issues that arise with Langfuse and
    other async frameworks.
"""

import asyncio
import atexit
import concurrent.futures
import logging
from typing import Literal

from summarize_links.exceptions import ContentFetchError
from summarize_links.extract.validation import validate_url

__all__ = [
    "fetch_content_with_playwright",
    "close_browser_context",
    "PLAYWRIGHT_DEFAULT_TIMEOUT",
]

# Configure module logger
logger = logging.getLogger(__name__)

# ----- Constants -----

# Default timeout for Playwright operations (longer than HTTP)
PLAYWRIGHT_DEFAULT_TIMEOUT = 30  # seconds

# Browser types supported by Playwright
BrowserType = Literal["chromium", "firefox", "webkit"]

# Wait conditions for page load
WaitUntilType = Literal["load", "domcontentloaded", "networkidle"]

# Image file extensions to block for faster loading (performance optimization)
# These are blocked to reduce bandwidth and speed up page rendering
BLOCKED_IMAGE_EXTENSIONS = "png,jpg,jpeg,gif,svg,webp,ico"

# Thread pool for running Playwright in asyncio contexts
_thread_pool: concurrent.futures.ThreadPoolExecutor | None = None


def _get_thread_pool() -> concurrent.futures.ThreadPoolExecutor:
    """
    Get or create thread pool for running sync Playwright in async contexts.

    Returns:
        ThreadPoolExecutor instance.
    """
    global _thread_pool

    if _thread_pool is None:
        # Use a single worker to serialize Playwright sessions.
        # Each fetch is self-contained (spin up browser, fetch, teardown), so we
        # do not need multiple concurrent Playwright threads for correctness.
        # Async callers can still issue many fetches in parallel at the coroutine
        # level, but all Playwright work is funneled through this one thread.
        # This slightly reduces maximum throughput compared to multi-worker or
        # browser-context reuse approaches, but avoids the subtle threading and
        # greenlet issues seen when sharing Playwright resources across tasks.
        _thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="playwright"
        )

    return _thread_pool


def _cleanup_thread_pool() -> None:
    """Cleanup thread pool on exit."""
    global _thread_pool
    if _thread_pool is not None:
        _thread_pool.shutdown(wait=True)
        _thread_pool = None


# Register cleanup handler
atexit.register(_cleanup_thread_pool)


def _is_in_asyncio_loop() -> bool:
    """
    Check if we're currently inside an asyncio event loop.

    Returns:
        True if an event loop is running, False otherwise.
    """
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def close_browser_context() -> None:
    """
    No-op for API compatibility.

    This function exists for backward compatibility with code that calls
    close_browser_context() at the end of processing. Since we now use
    self-contained fetches with no shared state, there's nothing to clean up.
    """
    # No-op - each fetch cleans up its own resources
    logger.debug("close_browser_context called (no-op - using self-contained fetches)")


def _fetch_content_sync(
    url: str,
    timeout: int,
    browser_type: BrowserType,
    wait_until: WaitUntilType,
) -> tuple[str, str]:
    """
    Fetch content with Playwright (self-contained, no shared state).

    Creates a fresh Playwright instance, browser, context, and page for each
    fetch. Everything is cleaned up before returning. This approach is slower
    than context reuse but eliminates all threading/greenlet issues.

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds.
        browser_type: Browser to use ("chromium", "firefox", or "webkit";
            currently only chromium is used).
        wait_until: Wait condition for page load.

    Returns:
        Tuple of (content, content_type).

    Raises:
        ContentFetchError: If browser fetch fails.
    """
    playwright = None
    browser = None
    page = None

    try:
        from playwright.sync_api import sync_playwright

        from summarize_links.extract.fetching import USER_AGENT

        logger.debug(f"Starting Playwright for {url}")

        # Create fresh Playwright instance
        playwright = sync_playwright().start()

        # Launch browser with performance optimizations
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",  # Hide automation
                "--disable-dev-shm-usage",  # Avoid /dev/shm issues in containers
                # SECURITY NOTE: --no-sandbox disables Chromium's security sandbox.
                # This is required in Docker containers and some CI environments that
                # lack proper kernel privileges. It increases security risk if browsing
                # untrusted content, but is acceptable for content summarization use case.
                # Consider making this configurable via environment variable for production.
                "--no-sandbox",
            ],
        )

        # Create context with browser-like settings
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=USER_AGENT,
            ignore_https_errors=False,
            java_script_enabled=True,
        )

        # Create page
        page = context.new_page()

        # Block images for faster loading (configurable via BLOCKED_IMAGE_EXTENSIONS constant)
        page.route(f"**/*.{{{BLOCKED_IMAGE_EXTENSIONS}}}", lambda route: route.abort())

        # Navigate to URL
        logger.debug(f"Navigating to {url} (timeout={timeout}s, wait_until={wait_until})")
        response = page.goto(
            url,
            timeout=timeout * 1000,  # Playwright uses milliseconds
            wait_until=wait_until,
        )

        # Check if navigation succeeded
        if response is None:
            raise ContentFetchError(f"Navigation failed for {url} (no response)")

        # Check response status
        status = response.status
        if status >= 400:
            if status == 401:
                error_msg = "HTTP 401: Authentication required (via Playwright)"
            elif status == 403:
                error_msg = "HTTP 403: Access forbidden (via Playwright)"
            elif status == 404:
                error_msg = "HTTP 404: Page not found (via Playwright)"
            elif status == 429:
                error_msg = "HTTP 429: Too many requests (via Playwright)"
            elif 500 <= status < 600:
                error_msg = f"HTTP {status}: Server error (via Playwright)"
            else:
                error_msg = f"HTTP {status}: Request failed (via Playwright)"
            raise ContentFetchError(error_msg)

        # For SPAs/JavaScript-heavy pages, wait for network to be idle
        # This ensures JavaScript has time to render content
        try:
            logger.debug("Waiting for network idle after page load")
            page.wait_for_load_state("networkidle", timeout=min(timeout * 1000, 10000))
        except Exception as wait_error:
            # Log but don't fail - page might already be loaded
            logger.debug(f"Network idle wait timed out: {wait_error}")

        # Extract page content after JavaScript execution
        html_content = page.content()

        logger.info(f"✓ Fetched {len(html_content)} characters with Playwright from {url}")

        return html_content, "html"

    except ContentFetchError:
        raise
    except ImportError as e:
        raise ContentFetchError(
            "Playwright is not installed. Run: uv sync && playwright install chromium"
        ) from e
    except TimeoutError as e:
        raise ContentFetchError(f"Playwright timeout after {timeout}s: {url}") from e
    except Exception as e:
        error_msg = str(e).lower()
        if "timeout" in error_msg:
            raise ContentFetchError(f"Playwright timeout: {url} ({e})") from e
        elif "net::" in error_msg or "connection" in error_msg:
            raise ContentFetchError(f"Playwright connection error: {url} ({e})") from e
        else:
            raise ContentFetchError(f"Playwright error: {url} ({e})") from e

    finally:
        # Clean up in reverse order - all in the same thread
        import contextlib

        if page is not None:
            with contextlib.suppress(Exception):
                page.close()

        if browser is not None:
            with contextlib.suppress(Exception):
                browser.close()

        if playwright is not None:
            with contextlib.suppress(Exception):
                playwright.stop()

        logger.debug(f"Playwright cleanup complete for {url}")


def fetch_content_with_playwright(
    url: str,
    timeout: int = PLAYWRIGHT_DEFAULT_TIMEOUT,
    browser_type: BrowserType = "chromium",
    wait_until: WaitUntilType = "domcontentloaded",
) -> tuple[str, str]:
    """
    Fetch content using Playwright browser automation.

    Uses a headless browser to render JavaScript and bypass bot detection.
    Slower than HTTP requests but more robust against anti-bot measures.

    Each call is self-contained - creates browser, fetches, and cleans up.
    When running inside an asyncio event loop (e.g., with Langfuse), the
    fetch is automatically run in a separate thread to avoid conflicts
    with Playwright's sync API.

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds (default 30s).
        browser_type: Browser to use ("chromium", "firefox", or "webkit";
            "chromium" is recommended).
        wait_until: Wait condition - "load", "domcontentloaded", or "networkidle".

    Returns:
        Tuple of (content, content_type) where content_type is 'html'.

    Raises:
        ContentFetchError: If browser fetch fails.
        URLValidationError: If URL is invalid.
    """
    # Validate URL before attempting to fetch
    validate_url(url)

    logger.debug(f"Fetching URL with Playwright: {url}")

    # Check if we're inside an asyncio event loop
    if _is_in_asyncio_loop():
        logger.debug("Detected asyncio loop, running Playwright in thread")

        # Run in thread pool to avoid "Sync API in asyncio loop" error
        thread_pool = _get_thread_pool()
        future = thread_pool.submit(
            _fetch_content_sync,
            url,
            timeout,
            browser_type,
            wait_until,
        )

        # Wait for result with timeout
        try:
            return future.result(timeout=timeout + 10)  # Buffer for browser startup
        except concurrent.futures.TimeoutError as e:
            raise ContentFetchError(f"Playwright thread timeout: {url}") from e
        except Exception:
            # Re-raise any ContentFetchError from the thread
            raise
    else:
        # Direct execution (no asyncio loop)
        return _fetch_content_sync(url, timeout, browser_type, wait_until)
