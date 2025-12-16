"""
Tests for the notes module.
"""

from datetime import datetime
from pathlib import Path

import pytest

from summarize_links.exceptions import NoteReadError
from summarize_links.notes import (
    add_summary_link_to_daily_note,
    extract_hashtags_from_line,
    extract_urls,
    extract_urls_with_context,
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
        filepath = get_summary_filepath(tmp_path, "Summaries", "https://example.com/article", date)

        assert filepath.parent == tmp_path / "Summaries"
        assert filepath.name.startswith("2025-12-16-")
        assert filepath.suffix == ".md"

    def test_uses_current_date_by_default(self, tmp_path: Path) -> None:
        """Should use current date when not specified."""
        filepath = get_summary_filepath(tmp_path, "Summaries", "https://example.com/test")

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


class TestAddSummaryLinkToDailyNote:
    """Tests for adding summary links to daily notes."""

    def test_add_link_creates_summaries_section(self, tmp_path: Path) -> None:
        """Should create Summaries section and add link."""
        # Create a daily note with the URL
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\n- https://example.com/article\n")

        # Create a mock summary path
        summary_path = tmp_path / "Summaries" / "2025-12-16-example-article.md"
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text("Summary content")

        result = add_summary_link_to_daily_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            summary_path=summary_path,
            url="https://example.com/article",
        )

        assert result is True
        content = note_file.read_text()
        assert "## Summaries" in content
        assert "[[2025-12-16-example-article]]" in content

    def test_add_link_to_existing_summaries_section(self, tmp_path: Path) -> None:
        """Should append link to existing Summaries section."""
        # Create a daily note with existing Summaries section
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text(
            "# 2025-12-16\n\nhttps://example.com/new\n\n## Summaries\n- [[existing-summary]]\n"
        )

        summary_path = tmp_path / "Summaries" / "2025-12-16-new-article.md"
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text("Summary content")

        result = add_summary_link_to_daily_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            summary_path=summary_path,
            url="https://example.com/new",
        )

        assert result is True
        content = note_file.read_text()
        assert "[[existing-summary]]" in content
        assert "[[2025-12-16-new-article]]" in content

    def test_skip_if_link_already_exists(self, tmp_path: Path) -> None:
        """Should not add duplicate links."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\n## Summaries\n- [[2025-12-16-article]]\n")

        summary_path = tmp_path / "Summaries" / "2025-12-16-article.md"
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text("Summary content")

        result = add_summary_link_to_daily_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            summary_path=summary_path,
            url="https://example.com/article",
        )

        assert result is False
        # Should only have one occurrence
        content = note_file.read_text()
        assert content.count("[[2025-12-16-article]]") == 1

    def test_add_link_in_daily_notes_subfolder(self, tmp_path: Path) -> None:
        """Should work with daily notes in subfolder."""
        # Create daily note in Journal subfolder
        journal = tmp_path / "Journal"
        journal.mkdir()
        note_file = journal / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\n- https://example.com/article\n")

        summary_path = tmp_path / "Summaries" / "2025-12-16-article.md"
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text("Summary content")

        result = add_summary_link_to_daily_note(
            vault_path=tmp_path,
            daily_notes_folder="Journal",
            note_filename="2025-12-16.md",
            summary_path=summary_path,
            url="https://example.com/article",
        )

        assert result is True
        content = note_file.read_text()
        assert "[[2025-12-16-article]]" in content

    def test_return_false_if_daily_note_not_found(self, tmp_path: Path) -> None:
        """Should return False if daily note doesn't exist."""
        summary_path = tmp_path / "Summaries" / "2025-12-16-article.md"

        result = add_summary_link_to_daily_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="nonexistent.md",
            summary_path=summary_path,
            url="https://example.com/article",
        )

        assert result is False

    def test_preserves_context_from_markdown_link(self, tmp_path: Path) -> None:
        """Should preserve surrounding text when URL is in a markdown link."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text(
            "# 2025-12-16\n\n- [Great Article](https://example.com/article) - must read #ai #tech\n"
        )

        summary_path = tmp_path / "Summaries" / "2025-12-16-article.md"
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text("Summary content")

        result = add_summary_link_to_daily_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            summary_path=summary_path,
            url="https://example.com/article",
        )

        assert result is True
        content = note_file.read_text()
        # Should have the link with surrounding context
        assert "[[2025-12-16-article]]" in content
        assert "must read" in content
        assert "#ai" in content
        assert "#tech" in content

    def test_preserves_context_from_bare_url(self, tmp_path: Path) -> None:
        """Should preserve surrounding text when URL is bare."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text(
            "# 2025-12-16\n\n- https://example.com/article interesting thoughts on AI #reading\n"
        )

        summary_path = tmp_path / "Summaries" / "2025-12-16-article.md"
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text("Summary content")

        result = add_summary_link_to_daily_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            summary_path=summary_path,
            url="https://example.com/article",
        )

        assert result is True
        content = note_file.read_text()
        # Should have the link with surrounding context
        assert "[[2025-12-16-article]]" in content
        assert "interesting thoughts on AI" in content
        assert "#reading" in content

    def test_adds_bullet_if_original_line_has_none(self, tmp_path: Path) -> None:
        """Should add bullet point if original line doesn't have one."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\nhttps://example.com/article some notes\n")

        summary_path = tmp_path / "Summaries" / "2025-12-16-article.md"
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text("Summary content")

        result = add_summary_link_to_daily_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            summary_path=summary_path,
            url="https://example.com/article",
        )

        assert result is True
        content = note_file.read_text()
        # Check the Summaries section has a bullet
        summaries_section = content.split("## Summaries")[1]
        assert "- [[2025-12-16-article]]" in summaries_section


class TestExtractHashtagsFromLine:
    """Tests for hashtag extraction from lines."""

    def test_extract_single_hashtag(self) -> None:
        """Should extract a single hashtag."""
        tags = extract_hashtags_from_line("Check this out #ai")
        assert tags == ["ai"]

    def test_extract_multiple_hashtags(self) -> None:
        """Should extract multiple hashtags."""
        tags = extract_hashtags_from_line("Article about #ai #machine-learning #python")
        assert tags == ["ai", "machine-learning", "python"]

    def test_no_hashtags(self) -> None:
        """Should return empty list when no hashtags."""
        tags = extract_hashtags_from_line("No tags here")
        assert tags == []

    def test_ignore_header_hashes(self) -> None:
        """Should not extract markdown headers as tags."""
        tags = extract_hashtags_from_line("## Header")
        assert tags == []

    def test_ignore_hash_in_url(self) -> None:
        """Should not extract hashes from URLs (anchors)."""
        # The hashtag pattern requires whitespace before #
        tags = extract_hashtags_from_line("https://example.com#section")
        assert tags == []

    def test_hashtag_with_numbers(self) -> None:
        """Should extract tags with numbers."""
        tags = extract_hashtags_from_line("Read about #gpt4 and #llm2024")
        assert "gpt4" in tags
        assert "llm2024" in tags

    def test_hashtag_with_hyphens(self) -> None:
        """Should extract tags with hyphens."""
        tags = extract_hashtags_from_line("Learning #deep-learning today")
        assert tags == ["deep-learning"]

    def test_hashtag_with_underscores(self) -> None:
        """Should extract tags with underscores."""
        tags = extract_hashtags_from_line("Working on #my_project")
        assert tags == ["my_project"]

    def test_hashtag_at_start_of_line(self) -> None:
        """Should extract hashtag at start of line."""
        tags = extract_hashtags_from_line("#important this is key")
        assert tags == ["important"]

    def test_hashtag_must_start_with_letter(self) -> None:
        """Hashtags must start with a letter."""
        tags = extract_hashtags_from_line("Price is #123")
        assert tags == []


class TestExtractUrlsWithContext:
    """Tests for URL extraction with context."""

    def test_extract_url_with_hashtags(self) -> None:
        """Should extract URL along with hashtags from same line."""
        content = "- [Article](https://example.com/article) #ai #reading"
        results = extract_urls_with_context(content)

        assert len(results) == 1
        assert results[0].url == "https://example.com/article"
        assert "ai" in results[0].tags
        assert "reading" in results[0].tags

    def test_extract_bare_url_with_hashtags(self) -> None:
        """Should work with bare URLs too."""
        content = "- https://example.com/article interesting #tech #must-read"
        results = extract_urls_with_context(content)

        assert len(results) == 1
        assert results[0].url == "https://example.com/article"
        assert "tech" in results[0].tags
        assert "must-read" in results[0].tags

    def test_extract_context_text(self) -> None:
        """Should capture the full line as context."""
        content = "- [Great Article](https://example.com) by John #ai"
        results = extract_urls_with_context(content)

        assert len(results) == 1
        assert "Great Article" in results[0].context_text
        assert "by John" in results[0].context_text

    def test_no_hashtags_returns_empty_list(self) -> None:
        """Should return empty tags list when no hashtags on line."""
        content = "- https://example.com/article"
        results = extract_urls_with_context(content)

        assert len(results) == 1
        assert results[0].tags == []

    def test_multiple_urls_different_lines(self) -> None:
        """Should handle multiple URLs on different lines."""
        content = """
        - https://first.com #tag1
        - https://second.com #tag2 #tag3
        """
        results = extract_urls_with_context(content)

        assert len(results) == 2
        assert results[0].url == "https://first.com"
        assert results[0].tags == ["tag1"]
        assert results[1].url == "https://second.com"
        assert "tag2" in results[1].tags
        assert "tag3" in results[1].tags

    def test_deduplicate_urls(self) -> None:
        """Should deduplicate URLs, keeping first occurrence."""
        content = """
        - https://example.com #first
        - https://example.com #second
        """
        results = extract_urls_with_context(content)

        assert len(results) == 1
        assert results[0].tags == ["first"]

    def test_url_with_no_context(self) -> None:
        """Should handle URL-only lines."""
        content = "https://example.com"
        results = extract_urls_with_context(content)

        assert len(results) == 1
        assert results[0].url == "https://example.com"
        assert results[0].tags == []

    def test_mixed_urls_and_text(self) -> None:
        """Should extract from realistic daily note content."""
        content = """# 2025-12-16

## Articles to Read
- [Attention Is All You Need](https://arxiv.org/abs/1706.03762) #ai #papers #transformers
- https://openai.com/blog/gpt-4 exciting stuff #gpt #ai

## Tasks
- Follow up on [[meeting-notes]]
"""
        results = extract_urls_with_context(content)

        assert len(results) == 2
        assert results[0].url == "https://arxiv.org/abs/1706.03762"
        assert "papers" in results[0].tags
        assert "transformers" in results[0].tags
        assert results[1].url == "https://openai.com/blog/gpt-4"
        assert "gpt" in results[1].tags
