"""
Tests for the CLI module.

This module tests argument parsing, command dispatch, and output formatting.
"""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from summarize_links.cli import (
    EXIT_CONFIG_ERROR,
    EXIT_ERROR,
    EXIT_SUCCESS,
    create_parser,
    main,
)
from summarize_links.commands import (
    cmd_list,
    cmd_resummarize,
    cmd_status,
)
from summarize_links.config import Config
from summarize_links.exceptions import (
    ConfigError,
    ContentExtractionError,
    ContentFetchError,
    GeminiAPIError,
    RateLimitError,
)
from summarize_links.models import PageMetadata, SummaryResult, UrlWithContext
from summarize_links.services.summarization import process_url
from summarize_links.ui import print_results


class TestCreateParser:
    """Tests for argument parser creation."""

    def test_parser_created(self) -> None:
        """Should create an ArgumentParser instance."""
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_global_options(self) -> None:
        """Should support global options."""
        parser = create_parser()

        # Test --verbose
        args = parser.parse_args(["--verbose", "from-note"])
        assert args.verbose is True

        # Test --quiet
        args = parser.parse_args(["--quiet", "from-note"])
        assert args.quiet is True

        # Test -q shorthand
        args = parser.parse_args(["-q", "from-note"])
        assert args.quiet is True

        # Test --vault
        args = parser.parse_args(["--vault", "/path/to/vault", "from-note"])
        assert args.vault == "/path/to/vault"

        # Test --model
        args = parser.parse_args(["--model", "gemini-pro", "from-note"])
        assert args.model == "gemini-pro"

        # Test --dry-run
        args = parser.parse_args(["--dry-run", "from-note"])
        assert args.dry_run is True

        # Test --max-links
        args = parser.parse_args(["--max-links", "5", "from-note"])
        assert args.max_links == 5

    def test_from_note_command(self) -> None:
        """Should parse from-note command."""
        parser = create_parser()

        # Basic from-note
        args = parser.parse_args(["from-note"])
        assert args.command == "from-note"

        # With date option
        args = parser.parse_args(["from-note", "--date", "2025-12-16"])
        assert args.command == "from-note"
        assert args.date == "2025-12-16"

        # With --all option
        args = parser.parse_args(["from-note", "--all"])
        assert args.command == "from-note"
        assert args.process_all is True

        # --all and --date are mutually exclusive in practice (--all takes precedence)
        args = parser.parse_args(["from-note", "--all", "--date", "2025-12-16"])
        assert args.process_all is True
        assert args.date == "2025-12-16"

    def test_urls_command(self) -> None:
        """Should parse urls command."""
        parser = create_parser()

        # Single URL
        args = parser.parse_args(["urls", "https://example.com"])
        assert args.command == "urls"
        assert args.urls == ["https://example.com"]

        # Multiple URLs
        args = parser.parse_args(["urls", "https://one.com", "https://two.com"])
        assert args.command == "urls"
        assert args.urls == ["https://one.com", "https://two.com"]

    def test_list_command(self) -> None:
        """Should parse list command."""
        parser = create_parser()
        args = parser.parse_args(["list"])
        assert args.command == "list"

    def test_resummarize_command(self) -> None:
        """Should parse resummarize command."""
        parser = create_parser()

        # Basic resummarize
        args = parser.parse_args(["resummarize"])
        assert args.command == "resummarize"
        assert args.age is None

        # With --age option
        args = parser.parse_args(["resummarize", "--age", "30"])
        assert args.command == "resummarize"
        assert args.age == 30

    def test_clean_command(self) -> None:
        """Should parse clean command."""
        parser = create_parser()
        args = parser.parse_args(["clean"])
        assert args.command == "clean"

    def test_short_options(self) -> None:
        """Should support short option forms."""
        parser = create_parser()

        args = parser.parse_args(["-v", "from-note"])
        assert args.verbose is True

    def test_no_command_returns_none(self) -> None:
        """Should return None command when no subcommand given."""
        parser = create_parser()
        args = parser.parse_args([])
        assert args.command is None


class TestMain:
    """Tests for main entry point."""

    def test_no_command_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should show help and return success when no command given."""
        result = main([])
        assert result == EXIT_SUCCESS

    @patch("summarize_links.cli.load_config")
    def test_config_error_returns_config_exit_code(self, mock_load_config: MagicMock) -> None:
        """Should return CONFIG_ERROR exit code on configuration errors."""
        mock_load_config.side_effect = ConfigError("Missing API key")

        result = main(["from-note"])
        assert result == EXIT_CONFIG_ERROR

    @patch("summarize_links.cli.load_config")
    @patch("summarize_links.cli.cmd_from_note")
    def test_from_note_command_dispatched(
        self,
        mock_cmd: MagicMock,
        mock_load_config: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should dispatch to cmd_from_note for from-note command."""
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            model_provider="google",
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        mock_load_config.return_value = mock_config
        mock_cmd.return_value = EXIT_SUCCESS

        result = main(["from-note"])

        mock_cmd.assert_called_once()
        assert result == EXIT_SUCCESS

    @patch("summarize_links.cli.load_config")
    @patch("summarize_links.cli.cmd_urls")
    def test_urls_command_dispatched(
        self,
        mock_cmd: MagicMock,
        mock_load_config: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should dispatch to cmd_urls for urls command."""
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            model_provider="google",
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        mock_load_config.return_value = mock_config
        mock_cmd.return_value = EXIT_SUCCESS

        result = main(["urls", "https://example.com"])

        mock_cmd.assert_called_once()
        assert result == EXIT_SUCCESS

    @patch("summarize_links.cli.load_config")
    @patch("summarize_links.cli.cmd_clean")
    def test_clean_command_dispatched(
        self,
        mock_cmd: MagicMock,
        mock_load_config: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should dispatch to cmd_clean for clean command."""
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            model_provider="google",
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        mock_load_config.return_value = mock_config
        mock_cmd.return_value = EXIT_SUCCESS

        result = main(["clean"])

        mock_cmd.assert_called_once()
        assert result == EXIT_SUCCESS

    def test_keyboard_interrupt_handled(self) -> None:
        """Should handle keyboard interrupt gracefully."""
        with patch("summarize_links.cli.load_config") as mock_load:
            mock_load.side_effect = KeyboardInterrupt()
            result = main(["from-note"])
            assert result == EXIT_ERROR


# Note: Tests for TestCmdFromNote, TestCmdFromNoteAll, and TestCmdUrls have been
# moved to separate test files (test_cmd_from_note.py and test_cmd_urls.py) for
# better organization and to use the new services layer API.


class TestCmdList:
    """Tests for list command handler."""

    def test_list_notes_with_urls(self, mock_vault: Path) -> None:
        """Should list daily notes that contain URLs."""
        # Create daily notes with URLs
        (mock_vault / "2025-12-15.md").write_text("Check https://example.com")
        (mock_vault / "2025-12-14.md").write_text("No links here")
        (mock_vault / "2025-12-13.md").write_text("https://one.com and https://two.com")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_list(config)

        assert result == EXIT_SUCCESS

    def test_list_no_notes_with_urls(self, mock_vault: Path) -> None:
        """Should return success when no notes have URLs."""
        (mock_vault / "2025-12-15.md").write_text("Just plain text")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_list(config)

        assert result == EXIT_SUCCESS

    def test_list_with_daily_notes_folder(self, mock_vault: Path) -> None:
        """Should respect daily_notes_folder setting."""
        journal = mock_vault / "Journal"
        journal.mkdir(exist_ok=True)
        (journal / "2025-12-15.md").write_text("https://example.com")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            daily_notes_folder="Journal",
        )

        result = cmd_list(config)

        assert result == EXIT_SUCCESS


class TestProcessUrlWithMetadata:
    """Tests for single URL processing with metadata."""

    def test_skip_existing_summary(self, mock_vault: Path) -> None:
        """Should skip URLs with existing summaries but still mark for deletion."""
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            out_folder="Summaries",
        )

        url_context = UrlWithContext(url="https://example.com")

        with patch("summarize_links.services.summarization.summary_exists", return_value=True):
            outcome = process_url(
                url_context,
                config,
                MagicMock(),
            )

        assert outcome.success is True
        assert "Skipped" in outcome.message
        # URL should still be deleted from daily note since summary exists
        assert outcome.should_delete_source is True

    @patch("summarize_links.services.summarization.write_summary_note_with_metadata")
    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    def test_force_overwrites_existing_summary(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should overwrite existing summaries when force=True."""
        mock_exists.return_value = True  # Summary exists (complete)
        mock_fetch.return_value = PageMetadata(
            title="Article Title",
            domain="example.com",
            content="Article content",
        )

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = SummaryResult(
            content="## Summary\n\nNew summary."
        )

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            force=True,
        )

        url_context = UrlWithContext(url="https://example.com")

        outcome = process_url(
            url_context,
            config,
            mock_client,
        )

        assert outcome.success is True
        assert "Created" in outcome.message
        assert outcome.should_delete_source is True
        # Verify overwrite=True was passed to write_summary_note_with_metadata
        mock_write.assert_called_once()
        call_kwargs = mock_write.call_args[1]
        assert call_kwargs.get("overwrite") is True

    def test_dry_run_mode(self, mock_vault: Path) -> None:
        """Should not make changes in dry-run mode."""
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            dry_run=True,
        )

        url_context = UrlWithContext(url="https://example.com")

        with patch("summarize_links.services.summarization.summary_exists", return_value=False):
            outcome = process_url(
                url_context,
                config,
                MagicMock(),
            )

        assert outcome.success is True
        assert "Would process" in outcome.message
        assert outcome.should_delete_source is False

    @patch("summarize_links.services.summarization.write_summary_note_with_metadata")
    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    def test_successful_processing(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should process URL and write summary."""
        mock_exists.return_value = False
        mock_fetch.return_value = PageMetadata(
            title="Article Title",
            domain="example.com",
            content="Article content",
        )

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = SummaryResult(
            content="## Summary\n\nThis is a summary."
        )

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        url_context = UrlWithContext(url="https://example.com")

        outcome = process_url(
            url_context,
            config,
            mock_client,
        )

        assert outcome.success is True
        assert "Created" in outcome.message
        assert outcome.should_delete_source is True
        mock_write.assert_called_once()

    @patch("summarize_links.services.summarization.write_stub_note")
    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    def test_fetch_error_creates_stub(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_stub: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should create stub note on fetch error."""
        mock_exists.return_value = False
        mock_fetch.side_effect = ContentFetchError("Connection refused")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        url_context = UrlWithContext(url="https://example.com")

        outcome = process_url(
            url_context,
            config,
            MagicMock(),
        )

        assert outcome.success is False
        assert "Fetch" in outcome.message or "fetch" in outcome.message
        assert outcome.should_delete_source is False
        mock_stub.assert_called_once()

    @patch("summarize_links.services.summarization.write_stub_note")
    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    def test_extraction_error_creates_stub(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_stub: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should create stub note on extraction error."""
        mock_exists.return_value = False
        mock_fetch.side_effect = ContentExtractionError("No content found")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        url_context = UrlWithContext(url="https://example.com")

        outcome = process_url(
            url_context,
            config,
            MagicMock(),
        )

        assert outcome.success is False
        assert "extraction" in outcome.message.lower()
        assert outcome.should_delete_source is False
        mock_stub.assert_called_once()

    @patch("summarize_links.services.summarization.write_stub_note")
    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    def test_rate_limit_creates_stub(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_stub: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should create stub note on rate limit."""
        mock_exists.return_value = False
        mock_fetch.return_value = PageMetadata(
            title="Title",
            domain="example.com",
            content="Content",
        )

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.side_effect = RateLimitError("Rate limited")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        url_context = UrlWithContext(url="https://example.com")

        outcome = process_url(
            url_context,
            config,
            mock_client,
        )

        assert outcome.success is False
        assert "rate" in outcome.message.lower() or "Rate limited" in outcome.message
        assert outcome.should_delete_source is False
        mock_stub.assert_called_once()

    @patch("summarize_links.services.summarization.write_stub_note")
    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    def test_api_error_creates_stub(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_stub: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should create stub note on API error."""
        mock_exists.return_value = False
        mock_fetch.return_value = PageMetadata(
            title="Title",
            domain="example.com",
            content="Content",
        )

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.side_effect = GeminiAPIError("API unavailable")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        url_context = UrlWithContext(url="https://example.com")

        outcome = process_url(
            url_context,
            config,
            mock_client,
        )

        assert outcome.success is False
        assert "api" in outcome.message.lower()
        assert outcome.should_delete_source is False
        mock_stub.assert_called_once()

    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    def test_dry_run_no_stub_on_error(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should not create stub in dry-run mode."""
        mock_exists.return_value = False
        mock_fetch.side_effect = ContentFetchError("Connection refused")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            dry_run=True,
        )

        url_context = UrlWithContext(url="https://example.com")

        with patch("summarize_links.services.summarization.write_stub_note") as mock_stub:
            outcome = process_url(
                url_context,
                config,
                MagicMock(),
            )

            mock_stub.assert_not_called()
            assert outcome.should_delete_source is False

    @patch("summarize_links.services.summarization.write_stub_note")
    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    def test_error_during_resummarize_preserves_successful_summary(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_stub: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should NOT overwrite successful summary with error stub during resummarization."""
        # Simulate that a successful summary already exists
        mock_exists.return_value = True
        # Force mode is enabled (as in resummarize)
        mock_fetch.side_effect = ContentFetchError("Connection refused")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            force=True,  # Force mode is enabled during resummarization
        )

        url_context = UrlWithContext(url="https://example.com")

        outcome = process_url(
            url_context,
            config,
            MagicMock(),
        )

        # Should return error
        assert outcome.success is False
        assert "fetch" in outcome.message.lower()
        assert outcome.should_delete_source is False

        # CRITICAL: Should NOT write stub note because a successful summary already existed
        mock_stub.assert_not_called()

    @patch("summarize_links.services.summarization.write_stub_note")
    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    def test_error_on_first_try_creates_stub(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_stub: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should create stub on error for URLs that never had a successful summary."""
        # No existing summary
        mock_exists.return_value = False
        # Force fetch to fail with ContentFetchError
        mock_fetch.side_effect = ContentFetchError("Connection refused")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        url_context = UrlWithContext(url="https://example.com")

        outcome = process_url(
            url_context,
            config,
            MagicMock(),
        )

        # Should return error
        assert outcome.success is False
        assert "fetch" in outcome.message.lower() or "Fetch error" in outcome.message
        assert outcome.should_delete_source is False

        # Should write stub note because this is the first attempt
        mock_stub.assert_called_once()


class TestPrintResults:
    """Tests for results table printing."""

    def test_prints_success_and_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print both successful and failed results."""
        results = [
            (True, "Created: example.md"),
            (False, "Fetch error: test.com"),
        ]

        print_results(results)

        # The output goes to Rich console, which uses stderr by default
        # We can verify the function runs without error


class TestCliIntegration:
    """Integration tests for CLI functionality."""

    @patch("summarize_links.services.summarization.write_summary_note_with_metadata")
    @patch("summarize_links.services.summarization.create_llm_client")
    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_full_from_note_flow(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_write: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should complete full from-note workflow."""
        # Setup mocks
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            model_provider="google",
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        mock_load_config.return_value = mock_config
        mock_read.return_value = "Note with URLs"
        mock_extract.return_value = [UrlWithContext(url="https://example.com")]
        mock_exists.return_value = False
        mock_fetch.return_value = PageMetadata(
            title="Article Title",
            domain="example.com",
            content="Article content",
        )

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = SummaryResult(content="## Summary")
        mock_create_llm_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        mock_read.assert_called_once()
        mock_extract.assert_called_once()
        mock_fetch.assert_called_once()
        mock_write.assert_called_once()

    @patch("summarize_links.services.summarization.write_summary_note_with_metadata")
    @patch("summarize_links.services.summarization.create_llm_client")
    @patch("summarize_links.services.summarization.fetch_and_extract_metadata")
    @patch("summarize_links.services.summarization.summary_exists")
    @patch("summarize_links.cli.load_config")
    def test_full_urls_flow(
        self,
        mock_load_config: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_write: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should complete full urls workflow."""
        # Setup mocks
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            model_provider="google",
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        mock_load_config.return_value = mock_config
        mock_exists.return_value = False
        mock_fetch.return_value = PageMetadata(
            title="Article Title",
            domain="example.com",
            content="Article content",
        )

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = SummaryResult(content="## Summary")
        mock_create_llm_client.return_value = mock_client

        # Run CLI
        result = main(["urls", "https://example.com", "https://test.com"])

        assert result == EXIT_SUCCESS
        assert mock_fetch.call_count == 2
        assert mock_write.call_count == 2


# Note: Tests for TestUrlLineDeletion have been removed as they test deprecated
# processor.py functionality. URL line deletion behavior is now tested through
# the services layer in separate test files.


class TestCmdStatus:
    """Tests for the status command."""

    @patch("summarize_links.commands.status.get_rate_limiter")
    def test_displays_rate_limit_info(
        self,
        mock_get_limiter: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should display rate limit information."""
        mock_limiter = MagicMock()
        mock_limiter.get_status.return_value = {
            "rpm": {"current": 2, "limit": 5, "remaining": 3},
            "tpm": {"current": 1000, "limit": 250000, "remaining": 249000},
            "daily": {"current": 10, "limit": 100, "remaining": 90},
        }
        mock_get_limiter.return_value = mock_limiter

        # cmd_status is now imported at module level

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_status(config)

        assert result == EXIT_SUCCESS
        mock_limiter.get_status.assert_called_once()

    @patch("summarize_links.commands.status.get_rate_limiter")
    def test_warns_on_low_daily_quota(
        self,
        mock_get_limiter: MagicMock,
        mock_vault: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should warn when daily quota is low."""
        mock_limiter = MagicMock()
        mock_limiter.get_status.return_value = {
            "rpm": {"current": 0, "limit": 5, "remaining": 5},
            "tpm": {"current": 0, "limit": 250000, "remaining": 250000},
            "daily": {"current": 95, "limit": 100, "remaining": 5},  # Low!
        }
        mock_get_limiter.return_value = mock_limiter

        # cmd_status is now imported at module level

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_status(config)

        assert result == EXIT_SUCCESS


class TestQuietMode:
    """Tests for quiet mode behavior."""

    def test_quiet_mode_suppresses_output(self) -> None:
        """Quiet mode flag should be set from args."""
        from summarize_links.cli import main

        # Running with --quiet should set the flag
        with patch("summarize_links.cli.load_config") as mock_config:
            mock_config.side_effect = ConfigError("test")
            main(["--quiet", "from-note"])
            # The function runs but we just verify no crash


class TestInvalidUrlHandling:
    """Tests for invalid URL handling in processing."""

    @patch("summarize_links.services.summarization.summary_exists")
    def test_invalid_url_not_retried(
        self,
        mock_exists: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Invalid URLs should fail without creating stubs."""
        from summarize_links.exceptions import URLValidationError

        mock_exists.return_value = False

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        # URL without proper domain
        url_context = UrlWithContext(url="not-a-valid-url")

        with patch(
            "summarize_links.services.summarization.fetch_and_extract_metadata"
        ) as mock_fetch:
            mock_fetch.side_effect = URLValidationError("Invalid URL")

            outcome = process_url(
                url_context,
                config,
                MagicMock(),
            )

        assert outcome.success is False
        assert "Invalid" in outcome.message or "invalid" in outcome.message
        assert outcome.should_delete_source is False


class TestCmdResummarize:
    """Tests for resummarize command handler."""

    def test_negative_age_rejected(self, mock_vault: Path) -> None:
        """Should reject negative age values."""
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_resummarize(config, age_days=-5)
        assert result == EXIT_ERROR

    def test_zero_age_rejected(self, mock_vault: Path) -> None:
        """Should reject zero age value."""
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_resummarize(config, age_days=0)
        assert result == EXIT_ERROR

    def test_negative_one_age_rejected(self, mock_vault: Path) -> None:
        """Should reject -1 age value."""
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_resummarize(config, age_days=-1)
        assert result == EXIT_ERROR

    @patch("summarize_links.commands.resummarize.scan_summaries_for_resummarize")
    def test_positive_age_accepted(
        self,
        mock_scan: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should accept positive age values."""
        mock_scan.return_value = []  # No summaries to process
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_resummarize(config, age_days=30)
        assert result == EXIT_SUCCESS

    @patch("summarize_links.commands.resummarize.scan_summaries_for_resummarize")
    def test_no_age_filter_accepted(
        self,
        mock_scan: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should accept None (no age filter)."""
        mock_scan.return_value = []  # No summaries to process
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_resummarize(config, age_days=None)
        assert result == EXIT_SUCCESS
