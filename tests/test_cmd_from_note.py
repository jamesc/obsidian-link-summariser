"""Tests for the from-note command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from summarize_links.cli import EXIT_ERROR, EXIT_SUCCESS
from summarize_links.commands import cmd_from_note, cmd_from_note_all
from summarize_links.config import Config
from summarize_links.exceptions import NoteReadError
from summarize_links.models import UrlWithContext


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

    @patch("summarize_links.commands.from_note.process_urls")
    @patch("summarize_links.commands.from_note.extract_urls_with_context")
    @patch("summarize_links.commands.from_note.read_daily_note")
    def test_max_links_applied(
        self,
        mock_read: MagicMock,
        mock_extract: MagicMock,
        mock_process: MagicMock,
        mock_vault: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should limit URLs to max_links."""
        monkeypatch.setenv("MODEL_PROVIDER", "google")
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
            model_provider="google",
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

    @patch("summarize_links.commands.from_note.process_urls")
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
        # Should collect all URLs and process in ONE batch
        assert mock_process.call_count == 1
        # Check that all URLs were collected
        call_args = mock_process.call_args
        url_contexts = call_args[0][0]
        assert len(url_contexts) == 2  # URLs from both notes

    @patch("summarize_links.commands.from_note.process_urls")
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
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should respect max_links limit across all notes."""
        monkeypatch.setenv("MODEL_PROVIDER", "google")
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
            model_provider="google",
            gemini_api_key="test-key",
            max_links=4,  # Limit to 4 total
        )

        cmd_from_note_all(config)

        # Should collect all 6 URLs but limit to 4 and process in ONE batch
        assert mock_process.call_count == 1
        call_urls = mock_process.call_args[0][0]
        assert len(call_urls) == 4  # Limited to max_links
