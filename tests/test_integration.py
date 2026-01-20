"""
Integration tests for the full workflow.

These tests verify that all components work together correctly,
using mock data and the mock vault fixture.
"""

from datetime import datetime
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from summarize_links.config import load_config
from summarize_links.exceptions import ContentFetchError
from summarize_links.notes import (
    extract_urls,
    read_daily_note,
    write_summary_note,
)


class TestFullWorkflow:
    """Integration tests for the complete summarization workflow."""

    def test_extract_urls_from_daily_note(self, mock_vault: Path, sample_urls: list[str]) -> None:
        """Should extract URLs from a daily note file."""
        # Read the daily note
        content = read_daily_note(mock_vault, "2025-12-16.md")

        # Extract URLs
        urls = extract_urls(content)

        # Verify all expected URLs were found
        assert len(urls) == len(sample_urls)
        for expected_url in sample_urls:
            assert expected_url in urls

    def test_write_summaries_for_extracted_urls(
        self, mock_vault: Path, fixed_date: datetime
    ) -> None:
        """Should write summary notes for each extracted URL."""
        # Read and extract URLs
        content = read_daily_note(mock_vault, "2025-12-16.md")
        urls = extract_urls(content)

        # Write summaries for each URL
        written_files: list[Path] = []
        for url in urls:
            filepath = write_summary_note(
                vault_path=mock_vault,
                out_folder="Summaries",
                url=url,
                content=f"## Summary\n\nMock summary for {url}",
                date=fixed_date,
                source_note="2025-12-16.md",
            )
            written_files.append(filepath)

        # Verify all files were created
        assert len(written_files) == len(urls)
        for filepath in written_files:
            assert filepath.exists()
            assert filepath.suffix == ".md"

        # Verify content structure
        first_summary = written_files[0].read_text()
        assert "---" in first_summary  # Has frontmatter
        assert "source:" in first_summary
        assert "date: 2025-12-16" in first_summary
        assert "## Summary" in first_summary

    def test_idempotency_skip_existing(self, mock_vault: Path, fixed_date: datetime) -> None:
        """Running twice should skip already-processed URLs."""
        url = "https://example.com/test"

        # First write
        filepath1 = write_summary_note(
            vault_path=mock_vault,
            out_folder="Summaries",
            url=url,
            content="First summary",
            date=fixed_date,
            overwrite=False,
        )

        # Second write (should skip)
        filepath2 = write_summary_note(
            vault_path=mock_vault,
            out_folder="Summaries",
            url=url,
            content="Second summary",
            date=fixed_date,
            overwrite=False,
        )

        # Same filepath returned
        assert filepath1 == filepath2

        # Original content preserved
        assert "First summary" in filepath1.read_text()
        assert "Second summary" not in filepath1.read_text()

    def test_config_loading_with_mock_vault(
        self, mock_vault_with_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should load config from vault YAML file."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config = load_config(vault_path=mock_vault_with_config)

        assert config.out_folder == "MySummaries"
        assert config.max_links == 5
        assert config.daily_notes_folder == "Journal"

    def test_daily_note_in_subfolder(self, mock_vault: Path) -> None:
        """Should read daily notes from configured subfolder."""
        # Note in Journal folder was created by mock_vault fixture
        content = read_daily_note(mock_vault, "2025-12-15.md", daily_notes_folder="Journal")

        assert "Yesterday's note" in content

    def test_max_links_limit(
        self, mock_vault: Path, sample_urls: list[str], fixed_date: datetime
    ) -> None:
        """Should respect max_links configuration."""
        max_links = 2

        # Read and extract URLs
        content = read_daily_note(mock_vault, "2025-12-16.md")
        urls = extract_urls(content)

        # Limit URLs
        limited_urls = urls[:max_links]

        # Process only limited URLs
        written_files = []
        for url in limited_urls:
            filepath = write_summary_note(
                vault_path=mock_vault,
                out_folder="Summaries",
                url=url,
                content=f"Summary for {url}",
                date=fixed_date,
            )
            written_files.append(filepath)

        # Verify only max_links files created
        assert len(written_files) == max_links


class TestConfigIntegration:
    """Integration tests for configuration loading."""

    def test_cli_overrides_yaml_config(
        self, mock_vault_with_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI arguments should override YAML config."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config = load_config(
            vault_path=mock_vault_with_config,
            out_folder="CLIOverride",
            max_links=20,
        )

        # CLI values should win
        assert config.out_folder == "CLIOverride"
        assert config.max_links == 20
        # YAML values for non-overridden settings should persist
        assert config.daily_notes_folder == "Journal"

    def test_config_validation_integration(
        self, mock_vault: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Full config should pass validation."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")

        config = load_config(vault_path=mock_vault)
        config.validate()  # Should not raise

        assert config.vault_path == mock_vault
        assert config.gemini_api_key == "test-key"


class TestPlaywrightFallbackIntegration:
    """Integration tests for Playwright fallback behavior."""

    def test_fallback_on_429_phase2(self, mocker: MockerFixture) -> None:
        """Should fallback to Playwright on HTTP 429 in Phase 2."""
        from summarize_links.extract import fetch_and_extract_metadata

        # Mock HTTP fetch to return 429 error
        mock_fetch_content = mocker.patch("summarize_links.extract.fetch_content")
        mock_fetch_content.side_effect = ContentFetchError("HTTP 429: Too Many Requests")

        # Mock Playwright to succeed
        mock_playwright = mocker.patch("summarize_links.extract.fetch_content_with_playwright")
        mock_playwright.return_value = (
            """
            <html>
                <head><title>Test Article</title></head>
                <body><article>
                    <p>Content fetched via Playwright after 429 error.</p>
                </article></body>
            </html>
            """,
            "html",
        )

        # Call with phase2 enabled
        metadata = fetch_and_extract_metadata(
            "https://example.com/rate-limited",
            playwright_enabled=True,
            playwright_phase="phase2",
        )

        # Verify HTTP was tried first
        mock_fetch_content.assert_called_once_with("https://example.com/rate-limited")

        # Verify Playwright was called as fallback
        mock_playwright.assert_called_once_with("https://example.com/rate-limited", timeout=30)

        # Verify content was extracted successfully
        assert metadata.title == "Test Article"
        assert "Playwright" in metadata.content
        assert metadata.fetch_method == "playwright"
        assert metadata.http_error_category == "rate_limit"

    def test_no_fallback_on_429_phase1(self, mocker: MockerFixture) -> None:
        """Should NOT fallback to Playwright on HTTP 429 in Phase 1."""
        from summarize_links.extract import fetch_and_extract_metadata

        # Mock HTTP fetch to return 429 error
        mock_fetch_content = mocker.patch("summarize_links.extract.fetch_content")
        mock_fetch_content.side_effect = ContentFetchError("HTTP 429: Too Many Requests")

        # Mock Playwright (should not be called)
        mock_playwright = mocker.patch("summarize_links.extract.fetch_content_with_playwright")

        # Call with phase1 (should raise without trying Playwright)
        with pytest.raises(ContentFetchError) as exc_info:
            fetch_and_extract_metadata(
                "https://example.com/rate-limited",
                playwright_enabled=True,
                playwright_phase="phase1",
            )

        # Verify error message
        assert "429" in str(exc_info.value)

        # Verify HTTP was tried
        mock_fetch_content.assert_called_once()

        # Verify Playwright was NOT called (429 not in phase1)
        mock_playwright.assert_not_called()

    def test_fallback_on_403_phase1(self, mocker: MockerFixture) -> None:
        """Should fallback to Playwright on HTTP 403 in Phase 1."""
        from summarize_links.extract import fetch_and_extract_metadata

        # Mock HTTP fetch to return 403 error
        mock_fetch_content = mocker.patch("summarize_links.extract.fetch_content")
        mock_fetch_content.side_effect = ContentFetchError("HTTP 403: Forbidden")

        # Mock Playwright to succeed
        mock_playwright = mocker.patch("summarize_links.extract.fetch_content_with_playwright")
        mock_playwright.return_value = (
            """
            <html>
                <head><title>Protected Article</title></head>
                <body><article>
                    <p>Content fetched via Playwright after 403 error.</p>
                </article></body>
            </html>
            """,
            "html",
        )

        # Call with phase1 enabled (403 is in phase1)
        metadata = fetch_and_extract_metadata(
            "https://example.com/protected",
            playwright_enabled=True,
            playwright_phase="phase1",
        )

        # Verify HTTP was tried first
        mock_fetch_content.assert_called_once_with("https://example.com/protected")

        # Verify Playwright was called as fallback
        mock_playwright.assert_called_once_with("https://example.com/protected", timeout=30)

        # Verify content was extracted successfully
        assert metadata.title == "Protected Article"
        assert "Playwright" in metadata.content
        assert metadata.fetch_method == "playwright"
        assert metadata.http_error_category == "bot_detection"

    def test_fallback_on_401_phase2(self, mocker: MockerFixture) -> None:
        """Should fallback to Playwright on HTTP 401 in Phase 2 (includes Phase 1)."""
        from summarize_links.extract import fetch_and_extract_metadata

        # Mock HTTP fetch to return 401 error
        mock_fetch_content = mocker.patch("summarize_links.extract.fetch_content")
        mock_fetch_content.side_effect = ContentFetchError("HTTP 401: Unauthorized")

        # Mock Playwright to succeed
        mock_playwright = mocker.patch("summarize_links.extract.fetch_content_with_playwright")
        mock_playwright.return_value = (
            """
            <html>
                <head><title>Auth Protected</title></head>
                <body><article>
                    <p>Content fetched via Playwright after 401 error.</p>
                </article></body>
            </html>
            """,
            "html",
        )

        # Call with phase2 (should include phase1 errors)
        metadata = fetch_and_extract_metadata(
            "https://example.com/auth-required",
            playwright_enabled=True,
            playwright_phase="phase2",
        )

        # Verify Playwright was called
        mock_playwright.assert_called_once()

        # Verify content was extracted successfully
        assert metadata.title == "Auth Protected"
        assert metadata.fetch_method == "playwright"
        assert metadata.http_error_category == "bot_detection"

    def test_both_methods_fail(self, mocker: MockerFixture) -> None:
        """Should raise enhanced error when both HTTP and Playwright fail."""
        from summarize_links.extract import fetch_and_extract_metadata

        # Mock HTTP fetch to return 403 error
        mock_fetch_content = mocker.patch("summarize_links.extract.fetch_content")
        mock_fetch_content.side_effect = ContentFetchError("HTTP 403: Forbidden")

        # Mock Playwright to also fail
        mock_playwright = mocker.patch("summarize_links.extract.fetch_content_with_playwright")
        mock_playwright.side_effect = ContentFetchError("Playwright timeout")

        # Should raise with both errors mentioned
        with pytest.raises(ContentFetchError) as exc_info:
            fetch_and_extract_metadata(
                "https://example.com/blocked",
                playwright_enabled=True,
                playwright_phase="phase1",
            )

        # Verify error message mentions both failures
        error_msg = str(exc_info.value)
        assert "403" in error_msg
        assert "Playwright fallback also failed" in error_msg
        assert "timeout" in error_msg.lower()

    def test_playwright_disabled(self, mocker: MockerFixture) -> None:
        """Should not fallback when Playwright is disabled."""
        from summarize_links.extract import fetch_and_extract_metadata

        # Mock HTTP fetch to return 403 error
        mock_fetch_content = mocker.patch("summarize_links.extract.fetch_content")
        mock_fetch_content.side_effect = ContentFetchError("HTTP 403: Forbidden")

        # Mock Playwright (should not be called)
        mock_playwright = mocker.patch("summarize_links.extract.fetch_content_with_playwright")

        # Call with Playwright disabled
        with pytest.raises(ContentFetchError) as exc_info:
            fetch_and_extract_metadata(
                "https://example.com/blocked",
                playwright_enabled=False,
                playwright_phase="phase1",
            )

        # Verify error is original HTTP error
        assert "403" in str(exc_info.value)

        # Verify Playwright was not called
        mock_playwright.assert_not_called()

    def test_no_fallback_on_404(self, mocker: MockerFixture) -> None:
        """Should NOT fallback to Playwright on HTTP 404 (not retryable)."""
        from summarize_links.extract import fetch_and_extract_metadata

        # Mock HTTP fetch to return 404 error
        mock_fetch_content = mocker.patch("summarize_links.extract.fetch_content")
        mock_fetch_content.side_effect = ContentFetchError("HTTP 404: Not Found")

        # Mock Playwright (should not be called)
        mock_playwright = mocker.patch("summarize_links.extract.fetch_content_with_playwright")

        # Should raise without trying Playwright (404 is never retryable)
        with pytest.raises(ContentFetchError) as exc_info:
            fetch_and_extract_metadata(
                "https://example.com/not-found",
                playwright_enabled=True,
                playwright_phase="phase2",
            )

        # Verify error message
        assert "404" in str(exc_info.value)

        # Verify Playwright was NOT called (404 is not retryable)
        mock_playwright.assert_not_called()
