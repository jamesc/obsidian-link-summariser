"""
Unit tests for Playwright-based content fetching.

Tests cover:
- Content fetching with various outcomes
- Error handling
- Fallback logic (should_retry_with_playwright)
- Error categorization
"""

# mypy: disable-error-code="no-untyped-def"

from unittest.mock import Mock, patch

import pytest

from summarize_links.exceptions import ContentFetchError, URLValidationError
from summarize_links.extract.fallback import (
    get_error_category,
    should_retry_with_playwright,
)
from summarize_links.extract.playwright_fetching import (
    close_browser_context,
    fetch_content_with_playwright,
)


@pytest.fixture
def mock_playwright():
    """Create a mock Playwright setup for testing."""
    mock_page = Mock()
    mock_page.content.return_value = "<html><body>Test content</body></html>"
    mock_response = Mock()
    mock_response.status = 200
    mock_page.goto.return_value = mock_response
    mock_page.route = Mock()
    mock_page.close = Mock()

    mock_context = Mock()
    mock_context.new_page.return_value = mock_page

    mock_browser = Mock()
    mock_browser.new_context.return_value = mock_context
    mock_browser.close = Mock()

    mock_chromium = Mock()
    mock_chromium.launch.return_value = mock_browser

    mock_pw_instance = Mock()
    mock_pw_instance.chromium = mock_chromium
    mock_pw_instance.stop = Mock()

    mock_sync_playwright = Mock()
    mock_sync_playwright.return_value.start.return_value = mock_pw_instance

    return {
        "sync_playwright": mock_sync_playwright,
        "playwright": mock_pw_instance,
        "browser": mock_browser,
        "context": mock_context,
        "page": mock_page,
        "response": mock_response,
    }


class TestPlaywrightFetching:
    """Tests for Playwright content fetching."""

    def test_fetch_with_playwright_success(self, mock_playwright):
        """Should successfully fetch content with Playwright."""
        with patch(
            "playwright.sync_api.sync_playwright",
            mock_playwright["sync_playwright"],
        ):
            content, content_type = fetch_content_with_playwright("https://example.com")

            assert content == "<html><body>Test content</body></html>"
            assert content_type == "html"

            # Verify cleanup happened
            mock_playwright["page"].close.assert_called_once()
            mock_playwright["browser"].close.assert_called_once()
            mock_playwright["playwright"].stop.assert_called_once()

    def test_fetch_with_playwright_timeout(self, mock_playwright):
        """Should raise ContentFetchError on timeout."""
        mock_playwright["page"].goto.side_effect = TimeoutError("Navigation timeout")

        with patch(
            "playwright.sync_api.sync_playwright",
            mock_playwright["sync_playwright"],
        ):
            with pytest.raises(ContentFetchError) as exc_info:
                fetch_content_with_playwright("https://example.com", timeout=10)

            assert "timeout" in str(exc_info.value).lower()

    def test_fetch_with_playwright_http_403(self, mock_playwright):
        """Should raise ContentFetchError for 403 status."""
        mock_playwright["response"].status = 403

        with patch(
            "playwright.sync_api.sync_playwright",
            mock_playwright["sync_playwright"],
        ):
            with pytest.raises(ContentFetchError) as exc_info:
                fetch_content_with_playwright("https://example.com")

            assert "403" in str(exc_info.value)
            assert "forbidden" in str(exc_info.value).lower()

    def test_fetch_with_playwright_http_401(self, mock_playwright):
        """Should raise ContentFetchError for 401 status."""
        mock_playwright["response"].status = 401

        with patch(
            "playwright.sync_api.sync_playwright",
            mock_playwright["sync_playwright"],
        ):
            with pytest.raises(ContentFetchError) as exc_info:
                fetch_content_with_playwright("https://example.com")

            assert "401" in str(exc_info.value)
            assert "authentication" in str(exc_info.value).lower()

    def test_fetch_with_playwright_http_404(self, mock_playwright):
        """Should raise ContentFetchError for 404 status."""
        mock_playwright["response"].status = 404

        with patch(
            "playwright.sync_api.sync_playwright",
            mock_playwright["sync_playwright"],
        ):
            with pytest.raises(ContentFetchError) as exc_info:
                fetch_content_with_playwright("https://example.com")

            assert "404" in str(exc_info.value)

    def test_fetch_with_playwright_http_500(self, mock_playwright):
        """Should raise ContentFetchError for 500 status."""
        mock_playwright["response"].status = 500

        with patch(
            "playwright.sync_api.sync_playwright",
            mock_playwright["sync_playwright"],
        ):
            with pytest.raises(ContentFetchError) as exc_info:
                fetch_content_with_playwright("https://example.com")

            assert "500" in str(exc_info.value)
            assert "server error" in str(exc_info.value).lower()

    def test_fetch_with_playwright_navigation_error(self, mock_playwright):
        """Should raise ContentFetchError on navigation failure."""
        mock_playwright["page"].goto.return_value = None  # Navigation failed

        with patch(
            "playwright.sync_api.sync_playwright",
            mock_playwright["sync_playwright"],
        ):
            with pytest.raises(ContentFetchError) as exc_info:
                fetch_content_with_playwright("https://example.com")

            assert "navigation failed" in str(exc_info.value).lower()

    def test_fetch_with_playwright_connection_error(self, mock_playwright):
        """Should raise ContentFetchError on connection error."""
        mock_playwright["page"].goto.side_effect = Exception("net::ERR_CONNECTION_REFUSED")

        with patch(
            "playwright.sync_api.sync_playwright",
            mock_playwright["sync_playwright"],
        ):
            with pytest.raises(ContentFetchError) as exc_info:
                fetch_content_with_playwright("https://example.com")

            assert "connection" in str(exc_info.value).lower()

    def test_fetch_with_playwright_invalid_url(self):
        """Should raise URLValidationError for invalid URL."""
        with pytest.raises(URLValidationError):
            fetch_content_with_playwright("not-a-url")

    def test_fetch_with_playwright_custom_timeout(self, mock_playwright):
        """Should use custom timeout value."""
        with patch(
            "playwright.sync_api.sync_playwright",
            mock_playwright["sync_playwright"],
        ):
            fetch_content_with_playwright("https://example.com", timeout=60)

            # Verify timeout was converted to milliseconds
            mock_playwright["page"].goto.assert_called_once()
            call_kwargs = mock_playwright["page"].goto.call_args[1]
            assert call_kwargs["timeout"] == 60000  # 60s * 1000ms

    def test_close_browser_context_is_noop(self):
        """close_browser_context should be a no-op (for API compatibility)."""
        # Should not raise
        close_browser_context()

    def test_playwright_not_installed(self):
        """Should raise ContentFetchError if Playwright not installed."""
        # Simulate Playwright being unavailable by making sync_playwright raise ImportError
        with patch(
            "playwright.sync_api.sync_playwright",
            side_effect=ImportError("No module named 'playwright'"),
        ):
            with pytest.raises(ContentFetchError) as exc_info:
                fetch_content_with_playwright("https://example.com")

            assert "playwright" in str(exc_info.value).lower()

    def test_cleanup_on_error(self, mock_playwright):
        """Should cleanup resources even when errors occur."""
        mock_playwright["page"].goto.side_effect = Exception("Test error")

        with patch(
            "playwright.sync_api.sync_playwright",
            mock_playwright["sync_playwright"],
        ):
            with pytest.raises(ContentFetchError):
                fetch_content_with_playwright("https://example.com")

            # Verify cleanup still happened
            mock_playwright["page"].close.assert_called_once()
            mock_playwright["browser"].close.assert_called_once()
            mock_playwright["playwright"].stop.assert_called_once()


class TestFallbackLogic:
    """Tests for Playwright fallback logic."""

    def test_should_retry_with_playwright_phase1_401(self):
        """Should retry 401 errors in Phase 1."""
        error = ContentFetchError("HTTP 401: Unauthorized")
        assert should_retry_with_playwright(error, "phase1") is True

    def test_should_retry_with_playwright_phase1_403(self):
        """Should retry 403 errors in Phase 1."""
        error = ContentFetchError("HTTP 403: Forbidden")
        assert should_retry_with_playwright(error, "phase1") is True

    def test_invalid_phase_raises_value_error(self):
        """Should raise ValueError for invalid phase values."""
        error = ContentFetchError("HTTP 403: Forbidden")
        with pytest.raises(ValueError) as exc_info:
            should_retry_with_playwright(error, "phase5")  # type: ignore[arg-type]
        assert "Invalid phase" in str(exc_info.value)
        assert "phase5" in str(exc_info.value)

    def test_should_not_retry_404_phase1(self):
        """Should NOT retry 404 errors in Phase 1."""
        error = ContentFetchError("HTTP 404: Not Found")
        assert should_retry_with_playwright(error, "phase1") is False

    def test_should_not_retry_500_phase1(self):
        """Should NOT retry 500 errors in Phase 1."""
        error = ContentFetchError("HTTP 500: Server Error")
        assert should_retry_with_playwright(error, "phase1") is False

    def test_should_not_retry_429_phase1(self):
        """Should NOT retry 429 errors in Phase 1 (requires Phase 2)."""
        error = ContentFetchError("HTTP 429: Too Many Requests")
        assert should_retry_with_playwright(error, "phase1") is False

    def test_should_retry_429_phase2(self):
        """Should retry 429 errors in Phase 2."""
        error = ContentFetchError("HTTP 429: Too Many Requests")
        assert should_retry_with_playwright(error, "phase2") is True

    def test_should_retry_401_phase2(self):
        """Should still retry 401 errors in Phase 2 (includes Phase 1)."""
        error = ContentFetchError("HTTP 401: Unauthorized")
        assert should_retry_with_playwright(error, "phase2") is True

    def test_should_not_retry_timeout_phase2(self):
        """Should NOT retry timeout errors in Phase 2 (requires Phase 3)."""
        error = ContentFetchError("Timeout after 30s")
        assert should_retry_with_playwright(error, "phase2") is False

    def test_should_retry_timeout_phase3(self):
        """Should retry timeout errors in Phase 3."""
        error = ContentFetchError("Timeout after 30s")
        assert should_retry_with_playwright(error, "phase3") is True

    def test_should_retry_connection_phase3(self):
        """Should retry connection errors in Phase 3."""
        error = ContentFetchError("Connection refused")
        assert should_retry_with_playwright(error, "phase3") is True

    def test_should_retry_content_type_phase4(self):
        """Should retry content type errors in Phase 4."""
        error = ContentFetchError("URL returned unsupported content type: application/json")
        assert should_retry_with_playwright(error, "phase4") is True

    def test_should_retry_all_phases_in_phase4(self):
        """Phase 4 should include all previous phase errors."""
        errors = [
            ContentFetchError("HTTP 401: Unauthorized"),  # Phase 1
            ContentFetchError("HTTP 403: Forbidden"),  # Phase 1
            ContentFetchError("HTTP 429: Too Many Requests"),  # Phase 2
            ContentFetchError("Timeout after 30s"),  # Phase 3
            ContentFetchError("Connection error"),  # Phase 3
            ContentFetchError("unsupported content type"),  # Phase 4
        ]

        for error in errors:
            assert should_retry_with_playwright(error, "phase4") is True

    def test_should_not_retry_permanent_failures_any_phase(self):
        """Should never retry permanent failures in any phase."""
        permanent_errors = [
            ContentFetchError("HTTP 404: Not Found"),
            ContentFetchError("HTTP 500: Server Error"),
            ContentFetchError("HTTP 502: Bad Gateway"),
            ContentFetchError("Invalid URL"),
        ]

        from typing import cast

        from summarize_links.extract.fallback import PhaseType

        for phase_str in ["phase1", "phase2", "phase3", "phase4"]:
            phase = cast(PhaseType, phase_str)
            for error in permanent_errors:
                assert should_retry_with_playwright(error, phase) is False

    def test_error_matching_case_insensitive(self):
        """Should match errors case-insensitively."""
        error = ContentFetchError("http 403: forbidden")  # lowercase
        assert should_retry_with_playwright(error, "phase1") is True


class TestErrorCategorization:
    """Tests for error categorization."""

    def test_categorize_404_error(self):
        """Should categorize 404 as not_found."""
        error = ContentFetchError("HTTP 404: Not Found")
        assert get_error_category(error) == "not_found"

    def test_categorize_401_error(self):
        """Should categorize 401 as bot_detection."""
        error = ContentFetchError("HTTP 401: Unauthorized")
        assert get_error_category(error) == "bot_detection"

    def test_categorize_403_error(self):
        """Should categorize 403 as bot_detection."""
        error = ContentFetchError("HTTP 403: Forbidden")
        assert get_error_category(error) == "bot_detection"

    def test_categorize_429_error(self):
        """Should categorize 429 as rate_limit."""
        error = ContentFetchError("HTTP 429: Too Many Requests")
        assert get_error_category(error) == "rate_limit"

    def test_categorize_timeout_error(self):
        """Should categorize timeout as timeout."""
        error = ContentFetchError("Timeout after 30s")
        assert get_error_category(error) == "timeout"

    def test_categorize_connection_error(self):
        """Should categorize connection errors as connection_error."""
        error = ContentFetchError("Connection refused")
        assert get_error_category(error) == "connection_error"

    def test_categorize_500_error(self):
        """Should categorize 500 as server_error."""
        error = ContentFetchError("HTTP 500: Server Error")
        assert get_error_category(error) == "server_error"

    def test_categorize_502_error(self):
        """Should categorize 502 as server_error."""
        error = ContentFetchError("HTTP 502: Bad Gateway")
        assert get_error_category(error) == "server_error"

    def test_categorize_content_type_error(self):
        """Should categorize content-type errors as content_type_mismatch."""
        error = ContentFetchError("URL returned unsupported content type: application/json")
        assert get_error_category(error) == "content_type_mismatch"

    def test_categorize_unknown_error(self):
        """Should categorize unknown errors as unknown."""
        error = ContentFetchError("Something went wrong")
        assert get_error_category(error) == "unknown"
