"""
Extended tests for the vault tools module.

Focuses on edge cases, error handling, and additional coverage.
"""

from pathlib import Path

import pytest

from summarize_links.chat.tools.vault import (
    ListSummariesTool,
    ReadSummaryTool,
    SearchVaultTool,
    _get_body_content,
)
from summarize_links.config import Config
from summarize_links.utils.frontmatter import parse_frontmatter


class TestExtractFrontmatterEdgeCases:
    """Additional tests for parse_frontmatter utility."""

    def test_extract_tags_inline_format(self) -> None:
        """Test tags in inline format are not extracted as list."""
        content = """---
title: Test
tags: python, testing
---

Body.
"""
        result = parse_frontmatter(content)
        # Inline tags are extracted as single string
        assert "tags" in result
        assert result["tags"] == "python, testing"

    def test_extract_empty_value(self) -> None:
        """Test field with empty value."""
        content = """---
title: Test
empty:
filled: value
---

Body.
"""
        result = parse_frontmatter(content)
        assert result["title"] == "Test"
        assert result["filled"] == "value"
        # YAML parsing treats "empty:" with no value as None
        assert result.get("empty") is None

    def test_extract_single_quoted_value(self) -> None:
        """Test single-quoted values."""
        content = """---
title: 'Single quoted'
---

Body.
"""
        result = parse_frontmatter(content)
        assert result["title"] == "Single quoted"

    def test_frontmatter_with_colons_in_value(self) -> None:
        """Test handling of colons in values."""
        content = """---
url: "https://example.com"
time: "10:30:00"
---

Body.
"""
        result = parse_frontmatter(content)
        assert result["url"] == "https://example.com"
        assert result["time"] == "10:30:00"

    def test_tags_with_mixed_content_after(self) -> None:
        """Test tags list followed by other content."""
        content = """---
tags:
  - tag1
  - tag2
other: value
---

Body.
"""
        result = parse_frontmatter(content)
        assert result["tags"] == ["tag1", "tag2"]
        assert result["other"] == "value"


class TestGetBodyContentEdgeCases:
    """Additional tests for _get_body_content helper."""

    def test_frontmatter_only(self) -> None:
        """Test content that is only frontmatter."""
        content = """---
title: Just frontmatter
---"""
        result = _get_body_content(content)
        assert result == ""

    def test_whitespace_after_frontmatter(self) -> None:
        """Test that leading whitespace is stripped from body."""
        content = """---
title: Test
---


   Body with leading whitespace.
"""
        result = _get_body_content(content)
        assert result.startswith("Body")


class TestListSummariesToolEdgeCases:
    """Additional tests for ListSummariesTool."""

    @pytest.fixture
    def tool(self) -> ListSummariesTool:
        """Create a tool instance."""
        return ListSummariesTool()

    def test_handles_unreadable_file(self, tool: ListSummariesTool, tmp_path: Path) -> None:
        """Test handling of files that can't be read."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        # Create a valid file
        (summaries_dir / "valid.md").write_text(
            """---
title: Valid
summary_status: success
---

Content.
""",
            encoding="utf-8",
        )

        # Create a directory with .md extension (edge case)
        # This will cause an error when trying to read_text
        (summaries_dir / "invalid.md").mkdir()

        config = Config(vault_path=tmp_path, out_folder="Summaries")
        result = tool.execute(config, limit=10, status="all")

        # Should succeed with the valid file
        assert result.success is True
        assert result.data["total"] == 1

    def test_filter_error_status(self, tool: ListSummariesTool, tmp_path: Path) -> None:
        """Test filtering by error status."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        (summaries_dir / "error.md").write_text(
            """---
title: Error Summary
summary_status: error
---

Content.
""",
            encoding="utf-8",
        )

        (summaries_dir / "success.md").write_text(
            """---
title: Success Summary
summary_status: success
---

Content.
""",
            encoding="utf-8",
        )

        config = Config(vault_path=tmp_path, out_folder="Summaries")
        result = tool.execute(config, limit=10, status="error")

        assert result.success is True
        assert result.data["total"] == 1
        assert result.data["summaries"][0]["status"] == "error"

    def test_to_schema(self, tool: ListSummariesTool) -> None:
        """Test tool schema generation."""
        schema = tool.to_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "list_summaries"
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]


class TestSearchVaultToolEdgeCases:
    """Additional tests for SearchVaultTool."""

    @pytest.fixture
    def tool(self) -> SearchVaultTool:
        """Create a tool instance."""
        return SearchVaultTool()

    def test_search_by_url(self, tool: SearchVaultTool, tmp_path: Path) -> None:
        """Test searching by URL in source field."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        (summaries_dir / "article.md").write_text(
            """---
title: Test Article
source: https://github.com/test/repo
---

Some content.
""",
            encoding="utf-8",
        )

        config = Config(vault_path=tmp_path, out_folder="Summaries")
        result = tool.execute(config, query="github", limit=10)

        assert result.success is True
        assert result.data["total"] == 1
        assert "url" in result.data["results"][0]["matched"]

    def test_search_score_ranking(self, tool: SearchVaultTool, tmp_path: Path) -> None:
        """Test that results are ranked by score."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        # Article with term in tags (high score)
        (summaries_dir / "high.md").write_text(
            """---
title: Something Else
tags:
  - python
  - tutorial
---

Content without the search term.
""",
            encoding="utf-8",
        )

        # Article with term only in content (lower score)
        (summaries_dir / "low.md").write_text(
            """---
title: Something
---

This article mentions python once.
""",
            encoding="utf-8",
        )

        config = Config(vault_path=tmp_path, out_folder="Summaries")
        result = tool.execute(config, query="python", limit=10)

        assert result.success is True
        assert result.data["total"] == 2
        # Higher scored result should be first
        assert result.data["results"][0]["title"] == "Something Else"

    def test_search_multiple_terms(self, tool: SearchVaultTool, tmp_path: Path) -> None:
        """Test searching with multiple terms."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        (summaries_dir / "both.md").write_text(
            """---
title: Both Terms
tags:
  - python
  - web
---

Content about python web development.
""",
            encoding="utf-8",
        )

        (summaries_dir / "one.md").write_text(
            """---
title: One Term
tags:
  - rust
---

Just rust content.
""",
            encoding="utf-8",
        )

        config = Config(vault_path=tmp_path, out_folder="Summaries")
        result = tool.execute(config, query="python web", limit=10)

        assert result.success is True
        # Both terms article should be higher scored
        if result.data["total"] > 1:
            assert result.data["results"][0]["title"] == "Both Terms"

    def test_no_vault_path(self, tool: SearchVaultTool) -> None:
        """Test error when vault path not set."""
        config = Config(vault_path=None)
        result = tool.execute(config, query="test")

        assert result.success is False
        assert "vault path" in result.message.lower()


class TestReadSummaryToolEdgeCases:
    """Additional tests for ReadSummaryTool."""

    @pytest.fixture
    def tool(self) -> ReadSummaryTool:
        """Create a tool instance."""
        return ReadSummaryTool()

    def test_read_by_partial_filename(self, tool: ReadSummaryTool, tmp_path: Path) -> None:
        """Test reading by partial filename match."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        (summaries_dir / "2025-01-22-my-article.md").write_text(
            """---
title: My Article
---

Content.
""",
            encoding="utf-8",
        )

        config = Config(vault_path=tmp_path, out_folder="Summaries")
        result = tool.execute(config, title="my-article")

        assert result.success is True
        assert result.data["title"] == "My Article"

    def test_read_case_insensitive(self, tool: ReadSummaryTool, tmp_path: Path) -> None:
        """Test case-insensitive title matching."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        (summaries_dir / "article.md").write_text(
            """---
title: UPPERCASE Title
---

Content.
""",
            encoding="utf-8",
        )

        config = Config(vault_path=tmp_path, out_folder="Summaries")
        result = tool.execute(config, title="uppercase")

        assert result.success is True

    def test_read_returns_metadata(self, tool: ReadSummaryTool, tmp_path: Path) -> None:
        """Test that all metadata is returned."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        (summaries_dir / "full.md").write_text(
            """---
title: Full Metadata
date: 2025-01-22
source: https://example.com
tags:
  - test
  - metadata
---

Content here.
""",
            encoding="utf-8",
        )

        config = Config(vault_path=tmp_path, out_folder="Summaries")
        result = tool.execute(config, title="Full Metadata")

        assert result.success is True
        assert result.data["title"] == "Full Metadata"
        # YAML parsing converts ISO date strings to datetime.date objects
        from datetime import date

        assert result.data["date"] == date(2025, 1, 22)
        assert result.data["source"] == "https://example.com"
        assert result.data["tags"] == ["test", "metadata"]
        assert "Content here" in result.data["content"]

    def test_no_vault_path(self, tool: ReadSummaryTool) -> None:
        """Test error when vault path not set."""
        config = Config(vault_path=None)
        result = tool.execute(config, title="test")

        assert result.success is False
        assert "vault path" in result.message.lower()

    def test_no_summaries_folder(self, tool: ReadSummaryTool, tmp_path: Path) -> None:
        """Test error when summaries folder doesn't exist."""
        config = Config(vault_path=tmp_path, out_folder="NonExistent")
        result = tool.execute(config, title="test")

        assert result.success is False
        assert "not found" in result.message.lower()
