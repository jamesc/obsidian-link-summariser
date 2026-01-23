"""
Tests for chat vault tools (list_summaries, search_summaries, read_summary).
"""

from pathlib import Path

import pytest

from summarize_links.chat.tools.vault import (
    ListSummariesTool,
    ReadSummaryTool,
    SearchVaultTool,
    _extract_frontmatter,
    _get_body_content,
)
from summarize_links.config import Config


class TestExtractFrontmatter:
    """Tests for _extract_frontmatter helper function."""

    def test_extract_simple_fields(self) -> None:
        """Test extracting simple key-value pairs."""
        content = """---
title: Test Title
date: 2025-01-22
source: https://example.com
---

Body content here.
"""
        result = _extract_frontmatter(content)

        assert result["title"] == "Test Title"
        assert result["date"] == "2025-01-22"
        assert result["source"] == "https://example.com"

    def test_extract_quoted_values(self) -> None:
        """Test extracting quoted values."""
        content = """---
title: "Title with: colon"
from: "[[Daily Note]]"
---

Body.
"""
        result = _extract_frontmatter(content)

        assert result["title"] == "Title with: colon"
        assert result["from"] == "[[Daily Note]]"

    def test_extract_tags(self) -> None:
        """Test extracting tags as a list."""
        content = """---
title: Test
tags:
  - python
  - tutorial
  - ai
---

Body.
"""
        result = _extract_frontmatter(content)

        assert result["tags"] == ["python", "tutorial", "ai"]

    def test_no_frontmatter(self) -> None:
        """Test content without frontmatter."""
        content = "Just some content without frontmatter."
        result = _extract_frontmatter(content)

        assert result == {}

    def test_malformed_frontmatter(self) -> None:
        """Test malformed frontmatter (missing end delimiter)."""
        content = """---
title: Test
date: 2025-01-22

Body without closing delimiter.
"""
        result = _extract_frontmatter(content)

        assert result == {}


class TestGetBodyContent:
    """Tests for _get_body_content helper function."""

    def test_extract_body_after_frontmatter(self) -> None:
        """Test extracting content after frontmatter."""
        content = """---
title: Test
---

This is the body content.
With multiple lines.
"""
        result = _get_body_content(content)

        assert result == "This is the body content.\nWith multiple lines."

    def test_no_frontmatter_returns_all(self) -> None:
        """Test content without frontmatter returns everything."""
        content = "This is all body content."
        result = _get_body_content(content)

        assert result == content


class TestListSummariesTool:
    """Tests for ListSummariesTool."""

    @pytest.fixture
    def tool(self) -> ListSummariesTool:
        """Create a tool instance."""
        return ListSummariesTool()

    @pytest.fixture
    def vault_with_summaries(self, tmp_path: Path) -> Path:
        """Create a vault with test summaries."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        # Create test summaries
        (summaries_dir / "2025-01-22-test-article.md").write_text(
            """---
title: Test Article
date: 2025-01-22
summary_status: success
source: https://example.com/article
tags:
  - python
  - testing
---

Summary content here.
""",
            encoding="utf-8",
        )

        (summaries_dir / "2025-01-21-another-post.md").write_text(
            """---
title: Another Post
date: 2025-01-21
summary_status: mocked
source: https://example.com/post
---

Mocked summary.
""",
            encoding="utf-8",
        )

        (summaries_dir / "2025-01-20-error-page.md").write_text(
            """---
title: Error Page
date: 2025-01-20
summary_status: fetch_error
source: https://example.com/error
---

## Summary Unavailable

Failed to fetch.
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_name(self, tool: ListSummariesTool) -> None:
        """Test tool name."""
        assert tool.name == "list_summaries"

    def test_description_not_empty(self, tool: ListSummariesTool) -> None:
        """Test tool has a description."""
        assert len(tool.description) > 0

    def test_parameters_schema(self, tool: ListSummariesTool) -> None:
        """Test parameters schema is valid."""
        params = tool.parameters
        assert params["type"] == "object"
        assert "limit" in params["properties"]
        assert "status" in params["properties"]

    def test_no_vault_path(self, tool: ListSummariesTool) -> None:
        """Test error when vault path not set."""
        config = Config(vault_path=None)
        result = tool.execute(config)

        assert result.success is False
        assert "vault path" in result.message.lower()

    def test_no_summaries_folder(self, tool: ListSummariesTool, tmp_path: Path) -> None:
        """Test when summaries folder doesn't exist."""
        config = Config(vault_path=tmp_path, out_folder="Summaries")
        result = tool.execute(config)

        assert result.success is True
        assert "no summaries" in result.message.lower()

    def test_list_all_summaries(self, tool: ListSummariesTool, vault_with_summaries: Path) -> None:
        """Test listing all summaries."""
        config = Config(vault_path=vault_with_summaries, out_folder="Summaries")
        result = tool.execute(config, limit=10, status="all")

        assert result.success is True
        assert "3" in result.message  # 3 summaries
        assert result.data["total"] == 3

    def test_filter_by_success_status(
        self, tool: ListSummariesTool, vault_with_summaries: Path
    ) -> None:
        """Test filtering by success status."""
        config = Config(vault_path=vault_with_summaries, out_folder="Summaries")
        result = tool.execute(config, limit=10, status="success")

        assert result.success is True
        assert result.data["total"] == 1
        assert result.data["summaries"][0]["title"] == "Test Article"

    def test_filter_by_error_status(
        self, tool: ListSummariesTool, vault_with_summaries: Path
    ) -> None:
        """Test filtering by error status."""
        config = Config(vault_path=vault_with_summaries, out_folder="Summaries")
        result = tool.execute(config, limit=10, status="error")

        assert result.success is True
        assert result.data["total"] == 1
        assert "error" in result.data["summaries"][0]["status"]

    def test_limit_parameter(self, tool: ListSummariesTool, vault_with_summaries: Path) -> None:
        """Test limit parameter restricts results."""
        config = Config(vault_path=vault_with_summaries, out_folder="Summaries")
        result = tool.execute(config, limit=1, status="all")

        assert result.success is True
        assert result.data["total"] == 1


class TestSearchVaultTool:
    """Tests for SearchVaultTool."""

    @pytest.fixture
    def tool(self) -> SearchVaultTool:
        """Create a tool instance."""
        return SearchVaultTool()

    @pytest.fixture
    def vault_with_content(self, tmp_path: Path) -> Path:
        """Create a vault with searchable content."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        (summaries_dir / "2025-01-22-python-tutorial.md").write_text(
            """---
title: Python Tutorial
date: 2025-01-22
source: https://example.com/python
tags:
  - python
  - programming
---

This is a comprehensive Python tutorial covering the basics
of Python programming language and best practices.
""",
            encoding="utf-8",
        )

        (summaries_dir / "2025-01-21-rust-guide.md").write_text(
            """---
title: Rust Guide
date: 2025-01-21
source: https://example.com/rust
tags:
  - rust
  - systems
---

A guide to Rust programming for systems development.
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_name(self, tool: SearchVaultTool) -> None:
        """Test tool name."""
        assert tool.name == "search_summaries"

    def test_search_by_tag(self, tool: SearchVaultTool, vault_with_content: Path) -> None:
        """Test searching by tag."""
        config = Config(vault_path=vault_with_content, out_folder="Summaries")
        result = tool.execute(config, query="python", limit=10)

        assert result.success is True
        assert result.data["total"] >= 1
        assert any("Python" in r["title"] for r in result.data["results"])

    def test_search_by_content(self, tool: SearchVaultTool, vault_with_content: Path) -> None:
        """Test searching by content."""
        config = Config(vault_path=vault_with_content, out_folder="Summaries")
        result = tool.execute(config, query="systems", limit=10)

        assert result.success is True
        assert any("Rust" in r["title"] for r in result.data["results"])

    def test_search_no_results(self, tool: SearchVaultTool, vault_with_content: Path) -> None:
        """Test search with no matches."""
        config = Config(vault_path=vault_with_content, out_folder="Summaries")
        result = tool.execute(config, query="nonexistent-term-xyz", limit=10)

        assert result.success is True
        assert result.data["total"] == 0

    def test_search_missing_query(self, tool: SearchVaultTool, vault_with_content: Path) -> None:
        """Test error when query is missing."""
        config = Config(vault_path=vault_with_content, out_folder="Summaries")
        result = tool.execute(config, query="", limit=10)

        assert result.success is False
        assert "query" in result.message.lower()


class TestReadSummaryTool:
    """Tests for ReadSummaryTool."""

    @pytest.fixture
    def tool(self) -> ReadSummaryTool:
        """Create a tool instance."""
        return ReadSummaryTool()

    @pytest.fixture
    def vault_with_summary(self, tmp_path: Path) -> Path:
        """Create a vault with a test summary."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        (summaries_dir / "2025-01-22-test-article.md").write_text(
            """---
title: Test Article Title
date: 2025-01-22
source: https://example.com/article
tags:
  - test
  - article
---

This is the full summary content.
It has multiple paragraphs.

And some more text here.
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_name(self, tool: ReadSummaryTool) -> None:
        """Test tool name."""
        assert tool.name == "read_summary"

    def test_read_by_filename(self, tool: ReadSummaryTool, vault_with_summary: Path) -> None:
        """Test reading a summary by filename."""
        config = Config(vault_path=vault_with_summary, out_folder="Summaries")
        result = tool.execute(config, title="2025-01-22-test-article")

        assert result.success is True
        assert "Test Article Title" in result.message
        assert "full summary content" in result.data["content"]

    def test_read_by_title(self, tool: ReadSummaryTool, vault_with_summary: Path) -> None:
        """Test reading a summary by title."""
        config = Config(vault_path=vault_with_summary, out_folder="Summaries")
        result = tool.execute(config, title="Test Article")

        assert result.success is True
        assert result.data["title"] == "Test Article Title"

    def test_read_not_found(self, tool: ReadSummaryTool, vault_with_summary: Path) -> None:
        """Test error when summary not found."""
        config = Config(vault_path=vault_with_summary, out_folder="Summaries")
        result = tool.execute(config, title="nonexistent-summary")

        assert result.success is False
        assert "not found" in result.message.lower()

    def test_read_missing_title(self, tool: ReadSummaryTool, vault_with_summary: Path) -> None:
        """Test error when title is missing."""
        config = Config(vault_path=vault_with_summary, out_folder="Summaries")
        result = tool.execute(config, title="")

        assert result.success is False
        assert "title" in result.message.lower()
