"""
Tests for the notes module.
"""

from datetime import datetime
from pathlib import Path

import pytest

from summarize_links.exceptions import NoteReadError
from summarize_links.notes import (
    extract_urls,
    generate_slug,
    get_summary_filepath,
    read_daily_note,
    slug_from_url,
    summary_exists,
    write_stub_note,
    write_summary_note,
)


class TestReadDailyNote:
    """Tests for reading daily notes."""

    def test_read_existing_note(self, tmp_path: Path) -> None:
        """Should read content from an existing note."""
        note_content = "# My Note\n\nSome content here."
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text(note_content)

        result = read_daily_note(tmp_path, "2025-12-16.md")
        assert result == note_content

    def test_read_note_in_subfolder(self, tmp_path: Path) -> None:
        """Should read note from daily notes subfolder."""
        journal_folder = tmp_path / "Journal"
        journal_folder.mkdir()
        note_file = journal_folder / "2025-12-16.md"
        note_file.write_text("Daily note content")

        result = read_daily_note(tmp_path, "2025-12-16.md", daily_notes_folder="Journal")
        assert result == "Daily note content"

    def test_read_nonexistent_note(self, tmp_path: Path) -> None:
        """Should raise NoteReadError for missing note."""
        with pytest.raises(NoteReadError, match="not found"):
            read_daily_note(tmp_path, "nonexistent.md")

    def test_read_directory_not_file(self, tmp_path: Path) -> None:
        """Should raise NoteReadError if path is a directory."""
        dir_path = tmp_path / "not_a_file"
        dir_path.mkdir()

        with pytest.raises(NoteReadError, match="not a file"):
            read_daily_note(tmp_path, "not_a_file")


class TestExtractUrls:
    """Tests for URL extraction from Markdown."""

    def test_extract_markdown_links(self) -> None:
        """Should extract URLs from Markdown link syntax."""
        content = """
        # Links
        - [Google](https://google.com)
        - [Example](https://example.com/path)
        """
        urls = extract_urls(content)
        assert "https://google.com" in urls
        assert "https://example.com/path" in urls

    def test_extract_bare_urls(self) -> None:
        """Should extract bare URLs."""
        content = """
        Check out https://example.com/article
        Also see http://test.com
        """
        urls = extract_urls(content)
        assert "https://example.com/article" in urls
        assert "http://test.com" in urls

    def test_extract_mixed_urls(self) -> None:
        """Should extract both Markdown links and bare URLs."""
        content = """
        # Daily Note
        - [Gemini API](https://ai.google.dev/pricing)
        - https://obsidian.md/plugins
        """
        urls = extract_urls(content)
        assert len(urls) == 2
        assert "https://ai.google.dev/pricing" in urls
        assert "https://obsidian.md/plugins" in urls

    def test_deduplicate_urls(self) -> None:
        """Should return unique URLs only."""
        content = """
        [Link 1](https://example.com)
        https://example.com
        [Link 2](https://example.com)
        """
        urls = extract_urls(content)
        assert len(urls) == 1
        assert urls[0] == "https://example.com"

    def test_preserve_order(self) -> None:
        """Should preserve order of first occurrence."""
        content = """
        https://first.com
        https://second.com
        https://third.com
        """
        urls = extract_urls(content)
        assert urls == ["https://first.com", "https://second.com", "https://third.com"]

    def test_ignore_obsidian_internal_links(self) -> None:
        """Should not extract Obsidian internal links."""
        content = """
        See [[2025-12-15]] for more.
        Also check https://external.com
        """
        urls = extract_urls(content)
        assert len(urls) == 1
        assert "https://external.com" in urls

    def test_strip_trailing_punctuation(self) -> None:
        """Should strip trailing punctuation from URLs."""
        content = "Check out https://example.com/page."
        urls = extract_urls(content)
        assert urls[0] == "https://example.com/page"

    def test_empty_content(self) -> None:
        """Should return empty list for content without URLs."""
        urls = extract_urls("No URLs here, just text.")
        assert urls == []


class TestGenerateSlug:
    """Tests for slug generation."""

    def test_basic_slug(self) -> None:
        """Should convert text to lowercase slug."""
        assert generate_slug("Hello World") == "hello-world"

    def test_special_characters(self) -> None:
        """Should replace special characters."""
        assert generate_slug("foo/bar") == "foo-bar"
        assert generate_slug("a:b:c") == "a-b-c"
        assert generate_slug("test?query=value") == "testqueryvalue"

    def test_collapse_dashes(self) -> None:
        """Should collapse multiple dashes."""
        assert generate_slug("foo---bar") == "foo-bar"
        assert generate_slug("a / b / c") == "a-b-c"

    def test_strip_leading_trailing(self) -> None:
        """Should strip leading/trailing dashes."""
        assert generate_slug("-hello-") == "hello"
        assert generate_slug("---test---") == "test"

    def test_max_length(self) -> None:
        """Should limit slug length."""
        long_text = "a" * 100
        slug = generate_slug(long_text)
        assert len(slug) <= 50


class TestSlugFromUrl:
    """Tests for URL to slug conversion."""

    def test_path_based_slug(self) -> None:
        """Should use URL path for slug."""
        slug = slug_from_url("https://example.com/my-article")
        assert slug == "my-article"

    def test_nested_path(self) -> None:
        """Should handle nested paths."""
        slug = slug_from_url("https://example.com/blog/2025/post")
        assert "blog" in slug or "post" in slug

    def test_domain_only(self) -> None:
        """Should use domain when no path."""
        slug = slug_from_url("https://example.com/")
        assert slug == "example-com"

    def test_strip_file_extension(self) -> None:
        """Should strip common file extensions."""
        slug = slug_from_url("https://example.com/page.html")
        assert "html" not in slug
        assert "page" in slug


class TestGetSummaryFilepath:
    """Tests for summary filepath generation."""

    def test_basic_filepath(self, tmp_path: Path) -> None:
        """Should generate correct filepath."""
        date = datetime(2025, 12, 16)
        filepath = get_summary_filepath(
            tmp_path, "Summaries", "https://example.com/article", date
        )

        assert filepath.parent == tmp_path / "Summaries"
        assert filepath.name.startswith("2025-12-16-")
        assert filepath.suffix == ".md"

    def test_uses_current_date_by_default(self, tmp_path: Path) -> None:
        """Should use current date when not specified."""
        filepath = get_summary_filepath(
            tmp_path, "Summaries", "https://example.com/test"
        )

        today = datetime.now().strftime("%Y-%m-%d")
        assert today in filepath.name


class TestSummaryExists:
    """Tests for checking if summary exists."""

    def test_summary_does_not_exist(self, tmp_path: Path) -> None:
        """Should return False when summary doesn't exist."""
        result = summary_exists(tmp_path, "Summaries", "https://example.com/new")
        assert result is False

    def test_summary_exists(self, tmp_path: Path) -> None:
        """Should return True when summary exists."""
        # Create the summary folder and file
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        date = datetime(2025, 12, 16)
        filepath = get_summary_filepath(tmp_path, "Summaries", "https://example.com/test", date)
        filepath.write_text("Existing summary")

        result = summary_exists(tmp_path, "Summaries", "https://example.com/test", date)
        assert result is True


class TestWriteSummaryNote:
    """Tests for writing summary notes."""

    def test_write_new_summary(self, tmp_path: Path) -> None:
        """Should write summary with frontmatter."""
        date = datetime(2025, 12, 16)
        filepath = write_summary_note(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com/article",
            content="## Summary\n\nThis is the summary.",
            date=date,
            source_note="2025-12-16.md",
        )

        assert filepath.exists()
        content = filepath.read_text()
        assert "source: https://example.com/article" in content
        assert "date: 2025-12-16" in content
        assert 'from: "[[2025-12-16]]"' in content
        assert "## Summary" in content

    def test_creates_output_folder(self, tmp_path: Path) -> None:
        """Should create output folder if it doesn't exist."""
        write_summary_note(
            vault_path=tmp_path,
            out_folder="NewFolder/Nested",
            url="https://example.com",
            content="Test content",
        )

        assert (tmp_path / "NewFolder" / "Nested").exists()

    def test_skip_existing_without_overwrite(self, tmp_path: Path) -> None:
        """Should skip existing file when overwrite=False."""
        date = datetime(2025, 12, 16)

        # Write first time
        write_summary_note(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            content="Original content",
            date=date,
        )

        # Write second time (should skip)
        write_summary_note(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            content="New content",
            date=date,
            overwrite=False,
        )

        # Content should still be original
        filepath = get_summary_filepath(tmp_path, "Summaries", "https://example.com", date)
        assert "Original content" in filepath.read_text()

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        """Should overwrite existing file when overwrite=True."""
        date = datetime(2025, 12, 16)

        # Write first time
        write_summary_note(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            content="Original content",
            date=date,
        )

        # Overwrite
        write_summary_note(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            content="New content",
            date=date,
            overwrite=True,
        )

        filepath = get_summary_filepath(tmp_path, "Summaries", "https://example.com", date)
        assert "New content" in filepath.read_text()


class TestWriteStubNote:
    """Tests for writing stub notes."""

    def test_write_stub(self, tmp_path: Path) -> None:
        """Should write stub note with reason."""
        date = datetime(2025, 12, 16)
        filepath = write_stub_note(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com/failed",
            reason="Rate limit exceeded",
            date=date,
        )

        content = filepath.read_text()
        assert "Summary Unavailable" in content
        assert "Rate limit exceeded" in content
        assert "https://example.com/failed" in content
