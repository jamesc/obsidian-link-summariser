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
    _print_results,
    _process_url,
    cmd_from_note,
    cmd_list,
    cmd_urls,
    create_parser,
    main,
)
from summarize_links.config import Config
from summarize_links.exceptions import (
    ConfigError,
    ContentExtractionError,
    ContentFetchError,
    GeminiAPIError,
    NoteReadError,
    RateLimitError,
)


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

        # Test --vault
        args = parser.parse_args(["--vault", "/path/to/vault", "from-note"])
        assert args.vault == "/path/to/vault"

        # Test --model
        args = parser.parse_args(["--model", "gemini-pro", "from-note"])
        assert args.model == "gemini-pro"

        # Test --mock
        args = parser.parse_args(["--mock", "from-note"])
        assert args.mock is True

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
        )
        mock_load_config.return_value = mock_config
        mock_cmd.return_value = EXIT_SUCCESS

        result = main(["urls", "https://example.com"])

        mock_cmd.assert_called_once()
        assert result == EXIT_SUCCESS

    def test_keyboard_interrupt_handled(self) -> None:
        """Should handle keyboard interrupt gracefully."""
        with patch("summarize_links.cli.load_config") as mock_load:
            mock_load.side_effect = KeyboardInterrupt()
            result = main(["from-note"])
            assert result == EXIT_ERROR


class TestCmdFromNote:
    """Tests for from-note command handler."""

    def test_invalid_date_format(self, mock_vault: Path) -> None:
        """Should return error for invalid date format."""
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_from_note(config, "not-a-date")
        assert result == EXIT_ERROR

    @patch("summarize_links.cli.read_daily_note")
    def test_note_read_error(
        self,
        mock_read: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should return error when note cannot be read."""
        mock_read.side_effect = NoteReadError("Note not found")
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_from_note(config, "2025-12-16")
        assert result == EXIT_ERROR

    @patch("summarize_links.cli.read_daily_note")
    @patch("summarize_links.cli.extract_urls_with_context")
    def test_no_urls_found(
        self,
        mock_extract: MagicMock,
        mock_read: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should return success when no URLs found."""
        mock_read.return_value = "No URLs here"
        mock_extract.return_value = []
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_from_note(config, "2025-12-16")
        assert result == EXIT_SUCCESS

    @patch("summarize_links.cli._process_urls_with_metadata")
    @patch("summarize_links.cli.extract_urls_with_context")
    @patch("summarize_links.cli.read_daily_note")
    def test_max_links_applied(
        self,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_process: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should limit URLs to max_links."""
        from summarize_links.models import UrlWithContext

        mock_read.return_value = "Note with URLs"
        mock_extract.return_value = [
            UrlWithContext(url="https://1.com"),
            UrlWithContext(url="https://2.com"),
            UrlWithContext(url="https://3.com"),
            UrlWithContext(url="https://4.com"),
            UrlWithContext(url="https://5.com"),
        ]
        mock_process.return_value = EXIT_SUCCESS

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            max_links=3,
        )

        cmd_from_note(config, "2025-12-16")

        # Check that only 3 URLs were passed to process
        call_args = mock_process.call_args[0]
        assert len(call_args[0]) == 3


class TestCmdUrls:
    """Tests for urls command handler."""

    @patch("summarize_links.cli._process_urls_with_metadata")
    def test_processes_provided_urls(
        self,
        mock_process: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should process provided URLs."""
        mock_process.return_value = EXIT_SUCCESS
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )
        urls = ["https://example.com", "https://test.com"]

        result = cmd_urls(config, urls)

        mock_process.assert_called_once()
        call_args = mock_process.call_args[0]
        # Now receives UrlWithContext objects, check URLs match
        assert [ctx.url for ctx in call_args[0]] == urls
        assert result == EXIT_SUCCESS

    @patch("summarize_links.cli._process_urls_with_metadata")
    def test_max_links_applied(
        self,
        mock_process: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should limit URLs to max_links."""
        mock_process.return_value = EXIT_SUCCESS
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            max_links=2,
        )
        urls = ["https://1.com", "https://2.com", "https://3.com"]

        cmd_urls(config, urls)

        call_args = mock_process.call_args[0]
        # Now receives UrlWithContext objects
        assert len(call_args[0]) == 2


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


class TestProcessUrl:
    """Tests for single URL processing."""

    def test_skip_existing_summary(self, mock_vault: Path) -> None:
        """Should skip URLs with existing summaries."""
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            out_folder="Summaries",
        )

        with patch("summarize_links.cli.summary_exists", return_value=True):
            success, message = _process_url(
                "https://example.com",
                config,
                MagicMock(),
            )

        assert success is True
        assert "Skipped" in message

    @patch("summarize_links.cli.write_summary_note")
    @patch("summarize_links.cli.fetch_and_extract")
    @patch("summarize_links.cli.summary_exists")
    def test_force_overwrites_existing_summary(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should overwrite existing summaries when force=True."""
        mock_exists.return_value = True  # Summary exists
        mock_fetch.return_value = ("Article content", "Article Title")

        mock_client = MagicMock()
        mock_client.summarize.return_value = "## Summary\n\nNew summary."

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            force=True,
        )

        success, message = _process_url(
            "https://example.com",
            config,
            mock_client,
        )

        assert success is True
        assert "Created" in message
        # Verify overwrite=True was passed to write_summary_note
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

        with patch("summarize_links.cli.summary_exists", return_value=False):
            success, message = _process_url(
                "https://example.com",
                config,
                MagicMock(),
            )

        assert success is True
        assert "Would process" in message

    @patch("summarize_links.cli.write_summary_note")
    @patch("summarize_links.cli.fetch_and_extract")
    @patch("summarize_links.cli.summary_exists")
    def test_successful_processing(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should process URL and write summary."""
        mock_exists.return_value = False
        mock_fetch.return_value = ("Article content", "Article Title")

        mock_client = MagicMock()
        mock_client.summarize.return_value = "## Summary\n\nThis is a summary."

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        success, message = _process_url(
            "https://example.com",
            config,
            mock_client,
        )

        assert success is True
        assert "Created" in message
        mock_write.assert_called_once()

    @patch("summarize_links.cli.write_stub_note")
    @patch("summarize_links.cli.fetch_and_extract")
    @patch("summarize_links.cli.summary_exists")
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

        success, message = _process_url(
            "https://example.com",
            config,
            MagicMock(),
        )

        assert success is False
        assert "Fetch error" in message
        mock_stub.assert_called_once()

    @patch("summarize_links.cli.write_stub_note")
    @patch("summarize_links.cli.fetch_and_extract")
    @patch("summarize_links.cli.summary_exists")
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

        success, message = _process_url(
            "https://example.com",
            config,
            MagicMock(),
        )

        assert success is False
        assert "Extraction error" in message
        mock_stub.assert_called_once()

    @patch("summarize_links.cli.write_stub_note")
    @patch("summarize_links.cli.fetch_and_extract")
    @patch("summarize_links.cli.summary_exists")
    def test_rate_limit_creates_stub(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_stub: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should create stub note on rate limit."""
        mock_exists.return_value = False
        mock_fetch.return_value = ("Content", "Title")

        mock_client = MagicMock()
        mock_client.summarize.side_effect = RateLimitError("Rate limited")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        success, message = _process_url(
            "https://example.com",
            config,
            mock_client,
        )

        assert success is False
        assert "Rate limited" in message
        mock_stub.assert_called_once()

    @patch("summarize_links.cli.write_stub_note")
    @patch("summarize_links.cli.fetch_and_extract")
    @patch("summarize_links.cli.summary_exists")
    def test_api_error_creates_stub(
        self,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_stub: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should create stub note on API error."""
        mock_exists.return_value = False
        mock_fetch.return_value = ("Content", "Title")

        mock_client = MagicMock()
        mock_client.summarize.side_effect = GeminiAPIError("API unavailable")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        success, message = _process_url(
            "https://example.com",
            config,
            mock_client,
        )

        assert success is False
        assert "API error" in message
        mock_stub.assert_called_once()

    @patch("summarize_links.cli.fetch_and_extract")
    @patch("summarize_links.cli.summary_exists")
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

        with patch("summarize_links.cli.write_stub_note") as mock_stub:
            success, message = _process_url(
                "https://example.com",
                config,
                MagicMock(),
            )

            mock_stub.assert_not_called()


class TestPrintResults:
    """Tests for results table printing."""

    def test_prints_success_and_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print both successful and failed results."""
        results = [
            (True, "Created: example.md"),
            (False, "Fetch error: test.com"),
        ]

        _print_results(results)

        # The output goes to Rich console, which uses stderr by default
        # We can verify the function runs without error


class TestCliIntegration:
    """Integration tests for CLI functionality."""

    @patch("summarize_links.cli.write_summary_note_with_metadata")
    @patch("summarize_links.cli.create_client")
    @patch("summarize_links.cli.fetch_and_extract_metadata")
    @patch("summarize_links.cli.summary_exists")
    @patch("summarize_links.cli.extract_urls_with_context")
    @patch("summarize_links.cli.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_full_from_note_flow(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_client: MagicMock,
        mock_write: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should complete full from-note workflow."""
        from summarize_links.models import PageMetadata, SummaryResult, UrlWithContext

        # Setup mocks
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            mock_mode=True,
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
        mock_create_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        mock_read.assert_called_once()
        mock_extract.assert_called_once()
        mock_fetch.assert_called_once()
        mock_write.assert_called_once()

    @patch("summarize_links.cli.write_summary_note_with_metadata")
    @patch("summarize_links.cli.create_client")
    @patch("summarize_links.cli.fetch_and_extract_metadata")
    @patch("summarize_links.cli.summary_exists")
    @patch("summarize_links.cli.load_config")
    def test_full_urls_flow(
        self,
        mock_load_config: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_client: MagicMock,
        mock_write: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should complete full urls workflow."""
        from summarize_links.models import PageMetadata, SummaryResult

        # Setup mocks
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            mock_mode=True,
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
        mock_create_client.return_value = mock_client

        # Run CLI
        result = main(["urls", "https://example.com", "https://test.com"])

        assert result == EXIT_SUCCESS
        assert mock_fetch.call_count == 2
        assert mock_write.call_count == 2

    @patch("summarize_links.cli.load_config")
    def test_mock_mode_flag(
        self,
        mock_load_config: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should pass mock mode to config."""
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            mock_mode=True,
        )
        mock_load_config.return_value = mock_config

        with patch("summarize_links.cli.cmd_from_note", return_value=EXIT_SUCCESS):
            main(["--mock", "from-note"])

        # Verify mock_mode was passed
        call_kwargs = mock_load_config.call_args[1]
        assert call_kwargs["mock_mode"] is True


class TestUrlLineDeletion:
    """Tests for URL line deletion behavior after successful processing."""

    @pytest.fixture
    def mock_vault(self, tmp_path: Path) -> Path:
        """Create a mock vault directory."""
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "Summaries").mkdir()
        return vault

    @patch("summarize_links.cli.remove_url_line_from_note")
    @patch("summarize_links.cli.add_summary_link_to_daily_note")
    @patch("summarize_links.cli.write_summary_note_with_metadata")
    @patch("summarize_links.cli.create_client")
    @patch("summarize_links.cli.fetch_and_extract_metadata")
    @patch("summarize_links.cli.summary_exists")
    @patch("summarize_links.cli.extract_urls_with_context")
    @patch("summarize_links.cli.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_mock_mode_does_not_delete_url_lines(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_client: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Mock mode should NOT delete URL lines from daily note."""
        from summarize_links.models import PageMetadata, SummaryResult, UrlWithContext

        # Setup mocks - mock mode enabled
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            mock_mode=True,  # Mock mode!
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
        mock_write.return_value = mock_vault / "Summaries" / "2025-12-16-example.md"

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = SummaryResult(content="## Summary")
        mock_create_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        # URL line should NOT be deleted in mock mode
        mock_remove_url.assert_not_called()

    @patch("summarize_links.cli.remove_url_line_from_note")
    @patch("summarize_links.cli.add_summary_link_to_daily_note")
    @patch("summarize_links.cli.write_summary_note_with_metadata")
    @patch("summarize_links.cli.create_client")
    @patch("summarize_links.cli.fetch_and_extract_metadata")
    @patch("summarize_links.cli.summary_exists")
    @patch("summarize_links.cli.extract_urls_with_context")
    @patch("summarize_links.cli.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_real_mode_deletes_url_lines(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_client: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Real mode (not mock) should delete URL lines from daily note."""
        from summarize_links.models import PageMetadata, SummaryResult, UrlWithContext

        # Setup mocks - NOT mock mode
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            mock_mode=False,  # Real mode!
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
        mock_write.return_value = mock_vault / "Summaries" / "2025-12-16-example.md"

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = SummaryResult(content="## Summary")
        mock_create_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        # URL line SHOULD be deleted in real mode
        mock_remove_url.assert_called_once()
        call_args = mock_remove_url.call_args
        assert call_args[1]["url"] == "https://example.com"

    @patch("summarize_links.cli.remove_url_line_from_note")
    @patch("summarize_links.cli.add_summary_link_to_daily_note")
    @patch("summarize_links.cli.write_summary_note_with_metadata")
    @patch("summarize_links.cli.create_client")
    @patch("summarize_links.cli.fetch_and_extract_metadata")
    @patch("summarize_links.cli.summary_exists")
    @patch("summarize_links.cli.extract_urls_with_context")
    @patch("summarize_links.cli.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_dry_run_does_not_delete_url_lines(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_client: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Dry-run mode should NOT delete URL lines from daily note."""
        from summarize_links.models import UrlWithContext

        # Setup mocks - dry-run enabled
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            mock_mode=False,
            dry_run=True,  # Dry-run mode!
        )
        mock_load_config.return_value = mock_config
        mock_read.return_value = "Note with URLs"
        mock_extract.return_value = [UrlWithContext(url="https://example.com")]

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        # URL line should NOT be deleted in dry-run mode
        mock_remove_url.assert_not_called()

    @patch("summarize_links.cli.remove_url_line_from_note")
    @patch("summarize_links.cli.add_summary_link_to_daily_note")
    @patch("summarize_links.cli.write_summary_note_with_metadata")
    @patch("summarize_links.cli.create_client")
    @patch("summarize_links.cli.fetch_and_extract_metadata")
    @patch("summarize_links.cli.summary_exists")
    @patch("summarize_links.cli.extract_urls_with_context")
    @patch("summarize_links.cli.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_skipped_urls_not_deleted(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_client: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Skipped URLs (already exist) should NOT be deleted from daily note."""
        from summarize_links.models import UrlWithContext

        # Setup mocks - summary already exists
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            mock_mode=False,
        )
        mock_load_config.return_value = mock_config
        mock_read.return_value = "Note with URLs"
        mock_extract.return_value = [UrlWithContext(url="https://example.com")]
        mock_exists.return_value = True  # Summary already exists!

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        # URL line should NOT be deleted when summary already exists
        mock_remove_url.assert_not_called()

    @patch("summarize_links.cli.write_stub_note")
    @patch("summarize_links.cli.remove_url_line_from_note")
    @patch("summarize_links.cli.create_client")
    @patch("summarize_links.cli.fetch_and_extract_metadata")
    @patch("summarize_links.cli.summary_exists")
    @patch("summarize_links.cli.extract_urls_with_context")
    @patch("summarize_links.cli.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_failed_urls_not_deleted(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_client: MagicMock,
        mock_remove_url: MagicMock,
        mock_stub: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Failed URLs (fetch error) should NOT be deleted from daily note."""
        from summarize_links.models import UrlWithContext

        # Setup mocks - fetch will fail
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            mock_mode=False,
        )
        mock_load_config.return_value = mock_config
        mock_read.return_value = "Note with URLs"
        mock_extract.return_value = [UrlWithContext(url="https://example.com")]
        mock_exists.return_value = False
        mock_fetch.side_effect = ContentFetchError("Connection failed")

        mock_client = MagicMock()
        mock_create_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        # Should have error exit but URL should NOT be deleted
        assert result == EXIT_ERROR
        mock_remove_url.assert_not_called()

    @patch("summarize_links.cli.remove_url_line_from_note")
    @patch("summarize_links.cli.add_summary_link_to_daily_note")
    @patch("summarize_links.cli.write_summary_note_with_metadata")
    @patch("summarize_links.cli.create_client")
    @patch("summarize_links.cli.fetch_and_extract_metadata")
    @patch("summarize_links.cli.summary_exists")
    @patch("summarize_links.cli.extract_urls_with_context")
    @patch("summarize_links.cli.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_reprocessing_mocked_summary_overwrites(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_client: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Reprocessing a mocked summary should overwrite it (not skip it)."""
        from summarize_links.models import PageMetadata, SummaryResult, UrlWithContext

        # Setup mocks - summary_exists returns False for mocked summaries
        mock_config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            mock_mode=False,  # Real mode this time
        )
        mock_load_config.return_value = mock_config
        mock_read.return_value = "Note with URLs"
        mock_extract.return_value = [UrlWithContext(url="https://example.com")]
        mock_exists.return_value = False  # Mocked summary returns False!
        mock_fetch.return_value = PageMetadata(
            title="Article Title",
            domain="example.com",
            content="Article content",
        )

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = SummaryResult(content="## Summary")
        mock_create_client.return_value = mock_client
        mock_write.return_value = mock_vault / "summaries" / "example.md"

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        # write_summary_note_with_metadata should be called with overwrite=True
        # because summary_exists returned False (meaning it needs reprocessing)
        mock_write.assert_called_once()
        call_kwargs = mock_write.call_args[1]
        assert call_kwargs["overwrite"] is True, "Should overwrite mocked summary"
        # URL should be deleted since we're in real mode
        mock_remove_url.assert_called_once()
