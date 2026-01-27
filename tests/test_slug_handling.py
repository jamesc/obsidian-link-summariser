"""
Tests for slug handling in chat tools.

Tests the new slug-based lookup behavior added to handle:
- Slugs without .md extension
- Date-prefixed filenames (YYYY-MM-DD-slug.md format)
"""

from pathlib import Path

import pytest

from summarize_links.chat.tools.summarize import ResummarizeTool
from summarize_links.chat.tools.vault import ReadSummaryTool
from summarize_links.config import Config


class TestReadSummarySlugHandling:
    """Tests for ReadSummaryTool slug handling."""

    @pytest.fixture
    def tool(self) -> ReadSummaryTool:
        """Create a tool instance."""
        return ReadSummaryTool()

    @pytest.fixture
    def vault_with_dated_summary(self, tmp_path: Path) -> Path:
        """Create a vault with a date-prefixed summary file."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        # Create a file with date prefix: YYYY-MM-DD-slug.md
        (
            summaries_dir / "2026-01-23-microsoft-is-using-claude-code-internally-while.md"
        ).write_text(
            """---
title: Microsoft is using Claude code internally while selling you Copilot
date: 2026-01-23
source: https://example.com/microsoft-article
tags:
  - microsoft
  - ai
---

Microsoft has been spotted using Claude internally...
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_read_by_slug_without_md_extension(
        self, tool: ReadSummaryTool, vault_with_dated_summary: Path
    ) -> None:
        """Test reading a summary using just the slug (no .md extension)."""
        config = Config(vault_path=vault_with_dated_summary, out_folder="Summaries")

        # Should find the file even without .md
        result = tool.execute(config, title="microsoft-is-using-claude-code-internally-while")

        assert result.success is True
        assert (
            result.data["title"]
            == "Microsoft is using Claude code internally while selling you Copilot"
        )
        assert "Claude internally" in result.data["content"]

    def test_read_by_slug_with_md_extension(
        self, tool: ReadSummaryTool, vault_with_dated_summary: Path
    ) -> None:
        """Test reading a summary using slug with .md extension."""
        config = Config(vault_path=vault_with_dated_summary, out_folder="Summaries")

        # Should work with .md extension too
        result = tool.execute(config, title="microsoft-is-using-claude-code-internally-while.md")

        assert result.success is True
        assert (
            result.data["title"]
            == "Microsoft is using Claude code internally while selling you Copilot"
        )

    def test_read_by_full_filename_with_date(
        self, tool: ReadSummaryTool, vault_with_dated_summary: Path
    ) -> None:
        """Test reading using the full date-prefixed filename."""
        config = Config(vault_path=vault_with_dated_summary, out_folder="Summaries")

        # Should work with full filename
        result = tool.execute(
            config,
            title="2026-01-23-microsoft-is-using-claude-code-internally-while",
        )

        assert result.success is True
        assert (
            result.data["title"]
            == "Microsoft is using Claude code internally while selling you Copilot"
        )

    def test_read_by_full_filename_with_date_and_md(
        self, tool: ReadSummaryTool, vault_with_dated_summary: Path
    ) -> None:
        """Test reading using the full filename with .md extension."""
        config = Config(vault_path=vault_with_dated_summary, out_folder="Summaries")

        result = tool.execute(
            config,
            title="2026-01-23-microsoft-is-using-claude-code-internally-while.md",
        )

        assert result.success is True
        assert (
            result.data["title"]
            == "Microsoft is using Claude code internally while selling you Copilot"
        )


class TestResummarizeSlugHandling:
    """Tests for ResummarizeTool slug handling."""

    @pytest.fixture
    def tool(self) -> ResummarizeTool:
        """Create a tool instance."""
        return ResummarizeTool()

    @pytest.fixture
    def vault_with_dated_summary(self, tmp_path: Path) -> Path:
        """Create a vault with a date-prefixed summary file."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        # Create a file with date prefix: YYYY-MM-DD-slug.md
        (summaries_dir / "2026-01-15-example-article.md").write_text(
            """---
title: Example Article
date: 2026-01-15
source: https://example.com/article
summary_status: success
---

Original content.
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_find_by_slug_without_md(
        self, tool: ResummarizeTool, vault_with_dated_summary: Path
    ) -> None:
        """Test that _find_summary_by_url_or_slug finds file by bare slug."""
        config = Config(vault_path=vault_with_dated_summary, out_folder="Summaries")

        # Internal method test - verifies the lookup works
        metadata = tool._find_summary_by_url_or_slug(config, "example-article")

        assert metadata is not None
        source_url, original_date, source_note = metadata
        assert source_url == "https://example.com/article"
        assert original_date.strftime("%Y-%m-%d") == "2026-01-15"

    def test_find_by_slug_with_md(
        self, tool: ResummarizeTool, vault_with_dated_summary: Path
    ) -> None:
        """Test that _find_summary_by_url_or_slug handles .md extension."""
        config = Config(vault_path=vault_with_dated_summary, out_folder="Summaries")

        # Should strip .md and still find the file
        metadata = tool._find_summary_by_url_or_slug(config, "example-article.md")

        assert metadata is not None
        source_url, _, _ = metadata
        assert source_url == "https://example.com/article"

    def test_find_by_full_filename(
        self, tool: ResummarizeTool, vault_with_dated_summary: Path
    ) -> None:
        """Test finding by full date-prefixed filename."""
        config = Config(vault_path=vault_with_dated_summary, out_folder="Summaries")

        metadata = tool._find_summary_by_url_or_slug(config, "2026-01-15-example-article")

        assert metadata is not None
        source_url, _, _ = metadata
        assert source_url == "https://example.com/article"

    def test_find_by_url_still_works(
        self, tool: ResummarizeTool, vault_with_dated_summary: Path
    ) -> None:
        """Test that finding by URL still works (backward compatibility)."""
        config = Config(vault_path=vault_with_dated_summary, out_folder="Summaries")

        metadata = tool._find_summary_by_url_or_slug(config, "https://example.com/article")

        assert metadata is not None
        source_url, _, _ = metadata
        assert source_url == "https://example.com/article"

    def test_parameter_name_changed_to_identifier(self, tool: ResummarizeTool) -> None:
        """Test that the parameter schema uses 'identifier' not 'url'."""
        params = tool.parameters

        assert "identifier" in params["properties"]
        assert "identifier" in params["required"]
        # Verify description mentions both slug and URL
        desc = params["properties"]["identifier"]["description"]
        assert "slug" in desc.lower()
        assert "url" in desc.lower()


class TestSlugHandlingMultipleFiles:
    """Test slug handling with multiple summary files."""

    @pytest.fixture
    def vault_with_multiple_summaries(self, tmp_path: Path) -> Path:
        """Create a vault with multiple summaries."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        # Create multiple files with similar slugs
        (summaries_dir / "2026-01-20-python-tutorial.md").write_text(
            """---
title: Python Tutorial
date: 2026-01-20
source: https://example.com/python-tutorial
---
Content.
""",
            encoding="utf-8",
        )

        (summaries_dir / "2026-01-21-python-tutorial-advanced.md").write_text(
            """---
title: Python Tutorial Advanced
date: 2026-01-21
source: https://example.com/python-tutorial-advanced
---
Advanced content.
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_exact_slug_match_preferred(self, vault_with_multiple_summaries: Path) -> None:
        """Test that exact slug match is preferred over partial matches."""
        from datetime import date

        tool = ReadSummaryTool()
        config = Config(vault_path=vault_with_multiple_summaries, out_folder="Summaries")

        # Should match the exact slug, not the partial one
        result = tool.execute(config, title="python-tutorial")

        assert result.success is True
        # Should get the first one, not the advanced one
        assert result.data["title"] == "Python Tutorial"
        assert result.data["date"] == date(2026, 1, 20)

    def test_slug_with_suffix_matches_correctly(self, vault_with_multiple_summaries: Path) -> None:
        """Test that slugs with suffixes match the right file."""
        from datetime import date

        tool = ReadSummaryTool()
        config = Config(vault_path=vault_with_multiple_summaries, out_folder="Summaries")

        result = tool.execute(config, title="python-tutorial-advanced")

        assert result.success is True
        assert result.data["title"] == "Python Tutorial Advanced"
        assert result.data["date"] == date(2026, 1, 21)
