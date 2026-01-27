"""
Tests for chat notes tools (find_urls_in_notes).
"""

from pathlib import Path

import pytest

from summarize_links.chat.tools.notes import FindUrlsInNotesTool
from summarize_links.config import Config


class TestFindUrlsInNotesTool:
    """Tests for FindUrlsInNotesTool."""

    @pytest.fixture
    def tool(self) -> FindUrlsInNotesTool:
        """Create a tool instance."""
        return FindUrlsInNotesTool()

    @pytest.fixture
    def vault_with_notes(self, tmp_path: Path) -> Path:
        """Create a vault with daily notes and summaries."""
        # Create daily notes folder
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        # Create a daily note with URLs
        (daily_notes / "2025-01-22.md").write_text(
            """# Daily Note

Some notes for today.

- Check out this article https://example.com/article1 #reading
- Interesting tutorial: [Python Guide](https://example.com/tutorial) #python
- Already summarized: https://example.com/old-article
""",
            encoding="utf-8",
        )

        # Create another daily note
        (daily_notes / "2025-01-21.md").write_text(
            """# Yesterday

- Link to video: https://youtube.com/watch?v=abc123 #video
""",
            encoding="utf-8",
        )

        # Create summaries folder with existing summary
        summaries = tmp_path / "Summaries"
        summaries.mkdir()

        # Summary with same date as the note
        (summaries / "2025-01-22-old-article.md").write_text(
            """---
title: Old Article
date: 2025-01-22
source: https://example.com/old-article
summary_status: success
---

Summary content.
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_name(self, tool: FindUrlsInNotesTool) -> None:
        """Test tool name."""
        assert tool.name == "find_urls_in_notes"

    def test_description_not_empty(self, tool: FindUrlsInNotesTool) -> None:
        """Test tool has a description."""
        assert len(tool.description) > 0

    def test_parameters_schema(self, tool: FindUrlsInNotesTool) -> None:
        """Test parameters schema is valid."""
        params = tool.parameters
        assert params["type"] == "object"
        assert "date" in params["properties"]
        assert "all_dates" in params["properties"]
        assert "include_summarized" in params["properties"]

    def test_no_vault_path(self, tool: FindUrlsInNotesTool) -> None:
        """Test error when vault path not set."""
        config = Config(vault_path=None)
        result = tool.execute(config)

        assert result.success is False
        assert "vault path" in result.message.lower()

    def test_find_urls_in_specific_date(
        self, tool: FindUrlsInNotesTool, vault_with_notes: Path
    ) -> None:
        """Test finding URLs in a specific date's note."""
        config = Config(
            vault_path=vault_with_notes,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, date="2025-01-22")

        assert result.success is True
        # Should find 2 unsummarized URLs (article1 and tutorial)
        # old-article should be excluded as it's already summarized
        assert result.data["unsummarized"] == 2
        assert any("example.com/article1" in u["url"] for u in result.data["urls"])

    def test_include_summarized_urls(
        self, tool: FindUrlsInNotesTool, vault_with_notes: Path
    ) -> None:
        """Test including already-summarized URLs."""
        config = Config(
            vault_path=vault_with_notes,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, date="2025-01-22", include_summarized=True)

        assert result.success is True
        # Should find all 3 URLs including the already summarized one
        assert result.data["total"] == 3

    def test_find_urls_all_dates(self, tool: FindUrlsInNotesTool, vault_with_notes: Path) -> None:
        """Test searching all daily notes."""
        config = Config(
            vault_path=vault_with_notes,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, all_dates=True)

        assert result.success is True
        # Should find notes from multiple dates
        assert len(result.data["notes"]) >= 2
        assert result.data["total_unsummarized"] >= 3

    def test_note_not_found(self, tool: FindUrlsInNotesTool, vault_with_notes: Path) -> None:
        """Test error when daily note doesn't exist."""
        config = Config(
            vault_path=vault_with_notes,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, date="1999-01-01")

        assert result.success is False
        assert "could not read" in result.message.lower()

    def test_no_urls_in_note(self, tool: FindUrlsInNotesTool, tmp_path: Path) -> None:
        """Test note with no URLs."""
        # Create daily note without URLs
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()
        (daily_notes / "2025-01-22.md").write_text(
            "# Today\n\nJust some notes, no links.",
            encoding="utf-8",
        )

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, date="2025-01-22")

        assert result.success is True
        assert "no urls found" in result.message.lower()

    def test_extracts_tags_from_context(
        self, tool: FindUrlsInNotesTool, vault_with_notes: Path
    ) -> None:
        """Test that hashtags are extracted from URL context."""
        config = Config(
            vault_path=vault_with_notes,
            out_folder="Summaries",
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, date="2025-01-22")

        assert result.success is True
        # Find the URL with the #reading tag
        for url_info in result.data["urls"]:
            if "article1" in url_info["url"]:
                assert "reading" in url_info["tags"]
                break

    def test_all_urls_summarized_message(self, tool: FindUrlsInNotesTool, tmp_path: Path) -> None:
        """Test message when all URLs are already summarized."""
        # Create daily note with one URL
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()
        (daily_notes / "2025-01-22.md").write_text(
            "# Today\n\nCheck this: https://example.com/done",
            encoding="utf-8",
        )

        # Create existing summary for that URL
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        (summaries / "2025-01-22-done.md").write_text(
            """---
source: https://example.com/done
summary_status: success
---

Done.
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
        assert "already been summarized" in result.message.lower()
