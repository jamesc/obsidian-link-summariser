"""Tests for the frontmatter utilities module."""

import datetime

from summarize_links.utils.frontmatter import (
    extract_frontmatter_block,
    get_frontmatter_field,
    parse_frontmatter,
)


class TestExtractFrontmatterBlock:
    """Tests for extract_frontmatter_block()."""

    def test_extracts_simple_frontmatter(self) -> None:
        """Test extraction of basic frontmatter block."""
        content = """---
title: Test Note
date: 2025-01-23
---

Body content here."""

        block = extract_frontmatter_block(content)
        assert block == "title: Test Note\ndate: 2025-01-23"

    def test_extracts_multiline_frontmatter(self) -> None:
        """Test extraction of frontmatter with complex values."""
        content = """---
title: Multi-line
tags:
  - ai
  - obsidian
summary: |
  This is a long
  multi-line summary
---

Body."""

        block = extract_frontmatter_block(content)
        assert block is not None
        assert "tags:" in block
        assert "- ai" in block
        assert "multi-line summary" in block

    def test_returns_none_for_no_frontmatter(self) -> None:
        """Test returns None when no frontmatter present."""
        content = "Just plain markdown content."
        block = extract_frontmatter_block(content)
        assert block is None

    def test_returns_none_for_empty_frontmatter(self) -> None:
        """Test returns None for empty frontmatter (no content between delimiters)."""
        content = """---
---

Body content."""

        block = extract_frontmatter_block(content)
        # Regex won't match empty block, returns None
        assert block is None

    def test_handles_incomplete_frontmatter(self) -> None:
        """Test handles missing closing delimiter."""
        content = """---
title: Incomplete

Body without closing ---"""

        block = extract_frontmatter_block(content)
        assert block is None

    def test_requires_frontmatter_at_start(self) -> None:
        """Test frontmatter must be at document start."""
        content = """Some intro text

---
title: Not at start
---

More content."""

        block = extract_frontmatter_block(content)
        assert block is None


class TestParseFrontmatter:
    """Tests for parse_frontmatter()."""

    def test_parses_simple_fields(self) -> None:
        """Test parsing of simple string fields."""
        content = """---
title: Test Title
author: John Doe
url: https://example.com
---

Body."""

        fm = parse_frontmatter(content)
        assert fm["title"] == "Test Title"
        assert fm["author"] == "John Doe"
        assert fm["url"] == "https://example.com"

    def test_parses_list_values(self) -> None:
        """Test parsing of list fields."""
        content = """---
tags:
  - python
  - testing
  - obsidian
---

Body."""

        fm = parse_frontmatter(content)
        assert fm["tags"] == ["python", "testing", "obsidian"]

    def test_parses_dict_values(self) -> None:
        """Test parsing of nested dictionary fields."""
        content = """---
metadata:
  source: web
  confidence: high
  version: 1.0
---

Body."""

        fm = parse_frontmatter(content)
        assert fm["metadata"]["source"] == "web"
        assert fm["metadata"]["confidence"] == "high"
        assert fm["metadata"]["version"] == 1.0

    def test_parses_numeric_values(self) -> None:
        """Test parsing of numeric values."""
        content = """---
count: 42
rating: 4.5
scientific: 1.2e-3
---

Body."""

        fm = parse_frontmatter(content)
        assert fm["count"] == 42
        assert fm["rating"] == 4.5
        assert fm["scientific"] == 1.2e-3

    def test_parses_boolean_values(self) -> None:
        """Test parsing of boolean values."""
        content = """---
published: true
draft: false
---

Body."""

        fm = parse_frontmatter(content)
        assert fm["published"] is True
        assert fm["draft"] is False

    def test_returns_empty_dict_for_no_frontmatter(self) -> None:
        """Test returns empty dict when no frontmatter."""
        content = "Just plain markdown."
        fm = parse_frontmatter(content)
        assert fm == {}

    def test_returns_empty_dict_for_empty_frontmatter(self) -> None:
        """Test returns empty dict for empty frontmatter."""
        content = """---
---

Body."""

        fm = parse_frontmatter(content)
        assert fm == {}

    def test_handles_invalid_yaml(self) -> None:
        """Test gracefully handles invalid YAML syntax."""
        content = """---
invalid: [unclosed bracket
broken:: double colon
---

Body."""

        fm = parse_frontmatter(content)
        # Should return empty dict and log warning
        assert fm == {}

    def test_handles_multiline_strings(self) -> None:
        """Test parsing of multiline string values."""
        content = """---
description: |
  This is a long description
  that spans multiple lines
  and preserves formatting.
---

Body."""

        fm = parse_frontmatter(content)
        desc = fm["description"]
        assert "long description" in desc
        assert "multiple lines" in desc

    def test_handles_quoted_strings(self) -> None:
        """Test parsing of quoted string values."""
        content = """---
title: "Title with: colons and, commas"
url: 'https://example.com/?param=value'
---

Body."""

        fm = parse_frontmatter(content)
        assert fm["title"] == "Title with: colons and, commas"
        assert fm["url"] == "https://example.com/?param=value"

    def test_parses_date_as_datetime_by_default(self) -> None:
        """Test that ISO date strings are parsed as datetime.date objects."""
        content = """---
date: 2025-01-22
---

Body."""

        fm = parse_frontmatter(content)
        assert isinstance(fm["date"], datetime.date)
        assert fm["date"] == datetime.date(2025, 1, 22)

    def test_stringify_dates_converts_dates_to_strings(self) -> None:
        """Test stringify_dates=True converts datetime.date to ISO strings."""
        content = """---
date: 2025-01-22
created: 2024-12-01
---

Body."""

        fm = parse_frontmatter(content, stringify_dates=True)
        assert fm["date"] == "2025-01-22"
        assert fm["created"] == "2024-12-01"
        assert isinstance(fm["date"], str)
        assert isinstance(fm["created"], str)

    def test_stringify_dates_preserves_non_date_values(self) -> None:
        """Test stringify_dates=True doesn't affect other value types."""
        content = """---
title: Test
date: 2025-01-22
count: 42
tags:
  - ai
---

Body."""

        fm = parse_frontmatter(content, stringify_dates=True)
        assert fm["title"] == "Test"
        assert fm["date"] == "2025-01-22"
        assert fm["count"] == 42
        assert fm["tags"] == ["ai"]

    def test_parses_datetime_as_datetime_by_default(self) -> None:
        """Test that datetime strings are parsed as datetime objects."""
        content = """---
timestamp: 2025-01-22T14:30:00
---

Body."""

        fm = parse_frontmatter(content)
        assert isinstance(fm["timestamp"], datetime.datetime)

    def test_stringify_dates_converts_datetime_to_string(self) -> None:
        """Test stringify_dates=True converts datetime objects to ISO strings."""
        content = """---
timestamp: 2025-01-22T14:30:00
---

Body."""

        fm = parse_frontmatter(content, stringify_dates=True)
        assert fm["timestamp"] == "2025-01-22T14:30:00"
        assert isinstance(fm["timestamp"], str)


class TestGetFrontmatterField:
    """Tests for get_frontmatter_field()."""

    def test_gets_simple_string_field(self) -> None:
        """Test getting a simple string field."""
        content = """---
title: Test Title
author: John Doe
---

Body."""

        title = get_frontmatter_field(content, "title")
        assert title == "Test Title"

        author = get_frontmatter_field(content, "author")
        assert author == "John Doe"

    def test_converts_numeric_to_string(self) -> None:
        """Test numeric values are converted to strings."""
        content = """---
count: 42
rating: 4.5
---

Body."""

        count = get_frontmatter_field(content, "count")
        assert count == "42"
        assert isinstance(count, str)

        rating = get_frontmatter_field(content, "rating")
        assert rating == "4.5"

    def test_converts_boolean_to_string(self) -> None:
        """Test boolean values are converted to strings."""
        content = """---
published: true
draft: false
---

Body."""

        published = get_frontmatter_field(content, "published")
        assert published == "True"

        draft = get_frontmatter_field(content, "draft")
        assert draft == "False"

    def test_returns_none_for_list_values(self) -> None:
        """Test returns None for list values (complex type)."""
        content = """---
tags:
  - python
  - testing
---

Body."""

        tags = get_frontmatter_field(content, "tags")
        assert tags is None

    def test_returns_none_for_dict_values(self) -> None:
        """Test returns None for dict values (complex type)."""
        content = """---
metadata:
  source: web
  confidence: high
---

Body."""

        metadata = get_frontmatter_field(content, "metadata")
        assert metadata is None

    def test_returns_none_for_missing_field(self) -> None:
        """Test returns None when field doesn't exist."""
        content = """---
title: Test
---

Body."""

        missing = get_frontmatter_field(content, "nonexistent")
        assert missing is None

    def test_returns_none_for_no_frontmatter(self) -> None:
        """Test returns None when no frontmatter present."""
        content = "Just plain markdown."
        result = get_frontmatter_field(content, "title")
        assert result is None

    def test_handles_empty_string_value(self) -> None:
        """Test handles empty string values."""
        content = """---
title: ""
author:
---

Body."""

        # Empty string should still return empty string (not None)
        title = get_frontmatter_field(content, "title")
        assert title == ""

        # Null value should return None
        author = get_frontmatter_field(content, "author")
        assert author is None
