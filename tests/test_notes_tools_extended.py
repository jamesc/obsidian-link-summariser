"""
Extended tests for the notes tools module.

Focuses on edge cases, error handling, and additional coverage.
"""

from datetime import datetime
from pathlib import Path

import pytest

from summarize_links.chat.tools.notes import FindUrlsInNotesTool
from summarize_links.config import Config


class TestFindUrlsInNotesToolEdgeCases:
    """Additional tests for FindUrlsInNotesTool."""

    @pytest.fixture
    def tool(self) -> FindUrlsInNotesTool:
        """Create a tool instance."""
        return FindUrlsInNotesTool()

    def test_defaults_to_today(self, tool: FindUrlsInNotesTool, tmp_path: Path) -> None:
        """Test that default date is today."""
        # Create daily notes folder
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        # Create today's note
        today = datetime.now().strftime("%Y-%m-%d")
        (daily_notes / f"{today}.md").write_text(
            f"# {today}\n\nLink: https://example.com",
            encoding="utf-8",
        )

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        # Don't pass date - should default to today
        result = tool.execute(config)

        assert result.success is True
        assert result.data["date"] == today

    def test_invalid_date_format(self, tool: FindUrlsInNotesTool, tmp_path: Path) -> None:
        """Test handling of invalid date format."""
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        # Pass invalid date format
        result = tool.execute(config, date="01-22-2025")

        # Should fail because file doesn't exist
        assert result.success is False

    def test_url_with_tags_extraction(self, tool: FindUrlsInNotesTool, tmp_path: Path) -> None:
        """Test extraction of tags from URL context."""
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        (daily_notes / "2025-01-22.md").write_text(
            """# 2025-01-22

- Read this article https://example.com/article #reading #later
- Watch this video https://youtube.com/watch #video
""",
            encoding="utf-8",
        )

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, date="2025-01-22")

        assert result.success is True
        # Check that tags were extracted
        for url_info in result.data["urls"]:
            if "article" in url_info["url"]:
                assert "reading" in url_info["tags"] or "later" in url_info["tags"]

    def test_search_all_dates_limits_results(
        self, tool: FindUrlsInNotesTool, tmp_path: Path
    ) -> None:
        """Test that search all dates limits to recent notes."""
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        # Create many daily notes
        for i in range(15):
            date = f"2025-01-{i + 1:02d}"
            (daily_notes / f"{date}.md").write_text(
                f"# {date}\n\nLink: https://example.com/{i}",
                encoding="utf-8",
            )

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, all_dates=True)

        assert result.success is True
        # Should limit to 10 most recent
        assert len(result.data["notes"]) <= 10

    def test_search_all_dates_empty_vault(self, tool: FindUrlsInNotesTool, tmp_path: Path) -> None:
        """Test searching all dates in empty vault."""
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, all_dates=True)

        assert result.success is True
        assert "no daily notes" in result.message.lower()

    def test_markdown_link_format(self, tool: FindUrlsInNotesTool, tmp_path: Path) -> None:
        """Test extraction of markdown-formatted links."""
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        (daily_notes / "2025-01-22.md").write_text(
            """# 2025-01-22

[Article Title](https://example.com/article)
[Video](https://youtube.com/watch?v=abc123)
""",
            encoding="utf-8",
        )

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, date="2025-01-22")

        assert result.success is True
        urls = [u["url"] for u in result.data["urls"]]
        assert any("example.com/article" in u for u in urls)

    def test_parameters_schema(self, tool: FindUrlsInNotesTool) -> None:
        """Test that parameters schema is correctly defined."""
        params = tool.parameters

        assert params["type"] == "object"
        assert "date" in params["properties"]
        assert "all_dates" in params["properties"]
        assert "include_summarized" in params["properties"]
        # No required parameters
        assert params.get("required", []) == []

    def test_to_schema(self, tool: FindUrlsInNotesTool) -> None:
        """Test tool schema generation."""
        schema = tool.to_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "find_urls_in_notes"
        assert "description" in schema["function"]

    def test_search_single_note_handles_parse_error(
        self, tool: FindUrlsInNotesTool, tmp_path: Path
    ) -> None:
        """Test handling of date parsing errors."""
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        # Create a note with an unusual name
        (daily_notes / "not-a-date.md").write_text(
            "# Not a date\n\nhttps://example.com",
            encoding="utf-8",
        )

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        # Try to find note with invalid date
        result = tool.execute(config, date="not-a-date")

        # Should succeed in reading the note even with invalid date
        # (the date parsing is for summary_exists check)
        assert result.success is True or "could not read" in result.message.lower()

    def test_all_notes_handles_read_errors(self, tool: FindUrlsInNotesTool, tmp_path: Path) -> None:
        """Test that errors reading individual notes don't fail entire search."""
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        # Create a valid note
        (daily_notes / "2025-01-22.md").write_text(
            "# Valid\n\nhttps://example.com",
            encoding="utf-8",
        )

        # Create an unreadable "note" (directory)
        (daily_notes / "2025-01-21.md").mkdir()

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, all_dates=True)

        # Should still succeed with valid notes
        assert result.success is True
        assert result.data["total_urls"] >= 1
