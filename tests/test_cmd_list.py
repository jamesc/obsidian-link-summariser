"""Tests for the list command."""

from pathlib import Path

from summarize_links.cli import EXIT_SUCCESS
from summarize_links.commands import cmd_list
from summarize_links.config import Config


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
