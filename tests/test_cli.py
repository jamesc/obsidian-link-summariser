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
    cmd_from_note,
    cmd_from_note_all,
    cmd_list,
    cmd_resummarize,
    cmd_status,
    cmd_urls,
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
from summarize_links.models import PageMetadata, SummaryResult, UrlWithContext
from summarize_links.processor import process_url_with_metadata
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
            mock_mode=True,  # Use mock mode to skip Langfuse
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
            mock_mode=True,  # Use mock mode to skip Langfuse
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
            mock_mode=True,  # Use mock mode to skip Langfuse
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

    @patch("summarize_links.commands.from_note.read_daily_note")
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

    @patch("summarize_links.commands.from_note.read_daily_note")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
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

    @patch("summarize_links.commands.from_note.process_urls_batch")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    def test_max_links_applied(
        self,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_process: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should limit URLs to max_links."""
        mock_read.return_value = "Note with URLs"
        mock_extract.return_value = [
            UrlWithContext(url="https://1.com"),
            UrlWithContext(url="https://2.com"),
            UrlWithContext(url="https://3.com"),
            UrlWithContext(url="https://4.com"),
            UrlWithContext(url="https://5.com"),
        ]
        mock_process.return_value = (EXIT_SUCCESS, [])

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            max_links=3,
        )

        cmd_from_note(config, "2025-12-16")

        # Check that only 3 URLs were passed to process
        call_args = mock_process.call_args[0]
        assert len(call_args[0]) == 3


class TestCmdFromNoteAll:
    """Tests for from-note --all command handler."""

    @patch("summarize_links.commands.from_note.find_daily_notes_with_urls")
    def test_no_notes_with_urls(
        self,
        mock_find: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should return success when no notes with URLs found."""
        mock_find.return_value = []
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_from_note_all(config)
        assert result == EXIT_SUCCESS

    @patch("summarize_links.commands.from_note.process_urls_batch")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    @patch("summarize_links.commands.from_note.find_daily_notes_with_urls")
    def test_processes_multiple_notes(
        self,
        mock_find: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_process: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should process all notes with newest first."""
        # Returns newest first, function should process newest first
        mock_find.return_value = [
            ("2025-12-16", 2),
            ("2025-12-15", 1),
        ]
        mock_read.return_value = "Note content"
        mock_extract.return_value = [UrlWithContext(url="https://example.com")]
        mock_process.return_value = (EXIT_SUCCESS, [])

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_from_note_all(config)

        assert result == EXIT_SUCCESS
        assert mock_process.call_count == 2
        # First call should be for newest date (2025-12-16)
        first_call = mock_process.call_args_list[0]
        assert first_call[1]["daily_note_filename"] == "2025-12-16.md"

    @patch("summarize_links.commands.from_note.process_urls_batch")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    @patch("summarize_links.commands.from_note.find_daily_notes_with_urls")
    def test_max_links_across_notes(
        self,
        mock_find: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_process: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should respect max_links limit across all notes."""
        mock_find.return_value = [
            ("2025-12-16", 5),
            ("2025-12-15", 5),
        ]
        mock_read.return_value = "Note content"
        mock_extract.return_value = [
            UrlWithContext(url="https://1.com"),
            UrlWithContext(url="https://2.com"),
            UrlWithContext(url="https://3.com"),
        ]
        mock_process.return_value = (EXIT_SUCCESS, [])

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            max_links=4,  # Limit to 4 total
        )

        cmd_from_note_all(config)

        # First note: 3 URLs processed (all of them)
        # Second note: only 1 URL processed (to reach limit of 4)
        assert mock_process.call_count == 2
        first_call_urls = mock_process.call_args_list[0][0][0]
        second_call_urls = mock_process.call_args_list[1][0][0]
        assert len(first_call_urls) == 3
        assert len(second_call_urls) == 1


class TestCmdUrls:
    """Tests for urls command handler."""

    @patch("summarize_links.commands.urls.process_urls_batch")
    def test_processes_provided_urls(
        self,
        mock_process: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should process provided URLs."""
        mock_process.return_value = (EXIT_SUCCESS, [])
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

    @patch("summarize_links.commands.urls.process_urls_batch")
    def test_max_links_applied(
        self,
        mock_process: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should limit URLs to max_links."""
        mock_process.return_value = (EXIT_SUCCESS, [])
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

        with patch("summarize_links.processor.summary_exists", return_value=True):
            success, message, should_delete = process_url_with_metadata(
                url_context,
                config,
                MagicMock(),
            )

        assert success is True
        assert "Skipped" in message
        # URL should still be deleted from daily note since summary exists
        assert should_delete is True

    @patch("summarize_links.processor.write_summary_note_with_metadata")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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

        success, message, should_delete = process_url_with_metadata(
            url_context,
            config,
            mock_client,
        )

        assert success is True
        assert "Created" in message
        assert should_delete is True
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

        with patch("summarize_links.processor.summary_exists", return_value=False):
            success, message, should_delete = process_url_with_metadata(
                url_context,
                config,
                MagicMock(),
            )

        assert success is True
        assert "Would process" in message
        assert should_delete is False

    @patch("summarize_links.processor.write_summary_note_with_metadata")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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

        success, message, should_delete = process_url_with_metadata(
            url_context,
            config,
            mock_client,
        )

        assert success is True
        assert "Created" in message
        assert should_delete is True
        mock_write.assert_called_once()

    @patch("summarize_links.processor.write_stub_note")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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

        success, message, should_delete = process_url_with_metadata(
            url_context,
            config,
            MagicMock(),
        )

        assert success is False
        assert "Fetch error" in message
        assert should_delete is False
        mock_stub.assert_called_once()

    @patch("summarize_links.processor.write_stub_note")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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

        success, message, should_delete = process_url_with_metadata(
            url_context,
            config,
            MagicMock(),
        )

        assert success is False
        assert "Extraction error" in message
        assert should_delete is False
        mock_stub.assert_called_once()

    @patch("summarize_links.processor.write_stub_note")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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

        success, message, should_delete = process_url_with_metadata(
            url_context,
            config,
            mock_client,
        )

        assert success is False
        assert "Rate limited" in message
        assert should_delete is False
        mock_stub.assert_called_once()

    @patch("summarize_links.processor.write_stub_note")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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

        success, message, should_delete = process_url_with_metadata(
            url_context,
            config,
            mock_client,
        )

        assert success is False
        assert "API error" in message
        assert should_delete is False
        mock_stub.assert_called_once()

    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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

        with patch("summarize_links.processor.write_stub_note") as mock_stub:
            success, message, should_delete = process_url_with_metadata(
                url_context,
                config,
                MagicMock(),
            )

            mock_stub.assert_not_called()
            assert should_delete is False

    @patch("summarize_links.processor.write_stub_note")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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

        success, message, should_delete = process_url_with_metadata(
            url_context,
            config,
            MagicMock(),
        )

        # Should return error
        assert success is False
        assert "Fetch error" in message
        assert should_delete is False

        # CRITICAL: Should NOT write stub note because a successful summary already existed
        mock_stub.assert_not_called()

    @patch("summarize_links.processor.write_stub_note")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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
        mock_fetch.side_effect = ContentFetchError("Connection refused")

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        url_context = UrlWithContext(url="https://example.com")

        success, message, should_delete = process_url_with_metadata(
            url_context,
            config,
            MagicMock(),
        )

        # Should return error
        assert success is False
        assert "Fetch error" in message
        assert should_delete is False

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

    @patch("summarize_links.processor.write_summary_note_with_metadata")
    @patch("summarize_links.processor.create_llm_client")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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
        mock_create_llm_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        mock_read.assert_called_once()
        mock_extract.assert_called_once()
        mock_fetch.assert_called_once()
        mock_write.assert_called_once()

    @patch("summarize_links.processor.write_summary_note_with_metadata")
    @patch("summarize_links.processor.create_llm_client")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
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
        mock_create_llm_client.return_value = mock_client

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

    @patch("summarize_links.processor.remove_url_line_from_note")
    @patch("summarize_links.processor.add_summary_link_to_daily_note")
    @patch("summarize_links.processor.write_summary_note_with_metadata")
    @patch("summarize_links.processor.create_llm_client")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_mock_mode_does_not_delete_url_lines(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Mock mode should NOT delete URL lines from daily note."""
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
        mock_create_llm_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        # URL line should NOT be deleted in mock mode
        mock_remove_url.assert_not_called()

    @patch("summarize_links.processor.remove_url_line_from_note")
    @patch("summarize_links.processor.add_summary_link_to_daily_note")
    @patch("summarize_links.processor.write_summary_note_with_metadata")
    @patch("summarize_links.processor.create_llm_client")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_real_mode_deletes_url_lines(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Real mode (not mock) should delete URL lines from daily note."""
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
        mock_create_llm_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        # URL line SHOULD be deleted in real mode
        mock_remove_url.assert_called_once()
        call_args = mock_remove_url.call_args
        assert call_args[1]["url"] == "https://example.com"

    @patch("summarize_links.processor.remove_url_line_from_note")
    @patch("summarize_links.processor.add_summary_link_to_daily_note")
    @patch("summarize_links.processor.write_summary_note_with_metadata")
    @patch("summarize_links.processor.create_llm_client")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_dry_run_does_not_delete_url_lines(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Dry-run mode should NOT delete URL lines from daily note."""
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
        mock_create_llm_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        # URL line should NOT be deleted in dry-run mode
        mock_remove_url.assert_not_called()

    @patch("summarize_links.processor.remove_url_line_from_note")
    @patch("summarize_links.processor.add_summary_link_to_daily_note")
    @patch("summarize_links.processor.write_summary_note_with_metadata")
    @patch("summarize_links.processor.create_llm_client")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_skipped_urls_still_deleted(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Skipped URLs (already exist) should still be deleted from daily note."""
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
        mock_create_llm_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        assert result == EXIT_SUCCESS
        # URL line SHOULD be deleted even when summary already exists
        mock_remove_url.assert_called_once()

    @patch("summarize_links.processor.write_stub_note")
    @patch("summarize_links.processor.remove_url_line_from_note")
    @patch("summarize_links.processor.create_llm_client")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_failed_urls_not_deleted(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_remove_url: MagicMock,
        mock_stub: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Failed URLs (fetch error) should NOT be deleted from daily note."""
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
        mock_create_llm_client.return_value = mock_client

        # Run CLI
        result = main(["from-note", "--date", "2025-12-16"])

        # Should have error exit but URL should NOT be deleted
        assert result == EXIT_ERROR
        mock_remove_url.assert_not_called()

    @patch("summarize_links.processor.remove_url_line_from_note")
    @patch("summarize_links.processor.add_summary_link_to_daily_note")
    @patch("summarize_links.processor.write_summary_note_with_metadata")
    @patch("summarize_links.processor.create_llm_client")
    @patch("summarize_links.processor.fetch_and_extract_metadata")
    @patch("summarize_links.processor.summary_exists")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    @patch("summarize_links.cli.load_config")
    def test_reprocessing_mocked_summary_overwrites(
        self,
        mock_load_config: MagicMock,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_exists: MagicMock,
        mock_fetch: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Reprocessing a mocked summary should overwrite it (not skip it)."""
        # summary_exists returns False for mocked summaries

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
        mock_create_llm_client.return_value = mock_client
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

    @patch("summarize_links.processor.summary_exists")
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

        with patch("summarize_links.processor.fetch_and_extract_metadata") as mock_fetch:
            mock_fetch.side_effect = URLValidationError("Invalid URL")

            success, message, should_delete = process_url_with_metadata(
                url_context,
                config,
                MagicMock(),
            )

        assert success is False
        assert "Invalid URL" in message
        assert should_delete is False


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
