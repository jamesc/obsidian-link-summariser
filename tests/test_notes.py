"""
Tests for the notes module.
"""

from datetime import datetime
from pathlib import Path

import pytest

from summarize_links.exceptions import NoteReadError
from summarize_links.models import PageMetadata, SummaryResult
from summarize_links.notes import (
    _escape_yaml_string,
    add_summary_link_to_daily_note,
    build_frontmatter,
    clean_url,
    extract_hashtags_from_line,
    extract_urls,
    extract_urls_with_context,
    find_daily_notes_with_urls,
    generate_slug,
    get_summary_filepath,
    read_daily_note,
    remove_url_line_from_note,
    slug_from_url,
    summary_exists,
    write_stub_note,
    write_summary_note,
    write_summary_note_with_metadata,
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


class TestCleanUrl:
    """Tests for URL cleaning (stripping tracking params)."""

    def test_strip_utm_params(self) -> None:
        """Should strip UTM tracking parameters."""
        url = "https://example.com/article?utm_source=newsletter&utm_medium=email"
        assert clean_url(url) == "https://example.com/article"

    def test_strip_multiple_tracking_params(self) -> None:
        """Should strip multiple tracking parameters."""
        url = "https://example.com/page?utm_source=tldr&ref=twitter&m=1"
        assert clean_url(url) == "https://example.com/page"

    def test_preserve_meaningful_params(self) -> None:
        """Should preserve non-tracking query parameters."""
        url = "https://example.com/search?q=test&page=2"
        assert clean_url(url) == "https://example.com/search?q=test&page=2"

    def test_preserve_youtube_video_id(self) -> None:
        """Should preserve YouTube video ID parameter."""
        url = "https://www.youtube.com/watch?v=abc123&utm_source=share"
        assert clean_url(url) == "https://www.youtube.com/watch?v=abc123"

    def test_preserve_github_tab_param(self) -> None:
        """Should preserve GitHub tab parameter."""
        url = "https://github.com/user/repo?tab=readme-ov-file"
        assert clean_url(url) == "https://github.com/user/repo?tab=readme-ov-file"

    def test_preserve_github_issue_comment_fragment(self) -> None:
        """Should preserve GitHub issue comment fragments."""
        url = "https://github.com/org/repo/issues/123#issuecomment-456"
        assert clean_url(url) == "https://github.com/org/repo/issues/123#issuecomment-456"

    def test_strip_rss_fragment(self) -> None:
        """Should strip RSS feed noise fragments."""
        url = "https://example.com/post/#atom-everything"
        assert clean_url(url) == "https://example.com/post/"

    def test_strip_blogspot_mobile_param(self) -> None:
        """Should strip Blogspot mobile parameter."""
        url = "https://blog.blogspot.com/2025/01/post.html?m=1"
        assert clean_url(url) == "https://blog.blogspot.com/2025/01/post.html"

    def test_preserve_meaningful_fragment(self) -> None:
        """Should preserve meaningful fragments with numbers."""
        url = "https://docs.example.com/guide#section-3"
        assert clean_url(url) == "https://docs.example.com/guide#section-3"

    def test_handle_invalid_url_gracefully(self) -> None:
        """Should return original URL if parsing fails."""
        url = "not-a-valid-url"
        assert clean_url(url) == "not-a-valid-url"

    def test_extract_urls_cleans_tracking(self) -> None:
        """Integration: extract_urls should clean tracking params."""
        content = "Check https://example.com/page?utm_source=test"
        urls = extract_urls(content)
        assert urls[0] == "https://example.com/page"


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

    def test_error_stub_can_be_retried(self, tmp_path: Path) -> None:
        """Should return False for error stubs to allow retry."""
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        date = datetime(2025, 12, 16)
        filepath = get_summary_filepath(tmp_path, "Summaries", "https://example.com/error", date)
        filepath.write_text("---\nstatus: error\n---\nError stub")

        result = summary_exists(tmp_path, "Summaries", "https://example.com/error", date)
        assert result is False

    def test_mocked_summary_can_be_retried(self, tmp_path: Path) -> None:
        """Should return False for mocked summaries to allow regeneration."""
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        date = datetime(2025, 12, 16)
        filepath = get_summary_filepath(tmp_path, "Summaries", "https://example.com/mock", date)
        filepath.write_text("---\nstatus: mocked\n---\nMock summary")

        result = summary_exists(tmp_path, "Summaries", "https://example.com/mock", date)
        assert result is False

    def test_success_summary_not_retried(self, tmp_path: Path) -> None:
        """Should return True for successful summaries."""
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        date = datetime(2025, 12, 16)
        filepath = get_summary_filepath(tmp_path, "Summaries", "https://example.com/success", date)
        filepath.write_text("---\nstatus: success\n---\nReal summary")

        result = summary_exists(tmp_path, "Summaries", "https://example.com/success", date)
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

    def test_original_url_preserved_when_cleaning_normalizes(self) -> None:
        """Should preserve original URL when cleaning adds trailing = to query params.

        This is a regression test for URLs like ?2138 being normalized to ?2138=
        by urlencode, which breaks URL removal from notes.
        """
        content = "- https://www.lukew.com/ff/entry.asp?2138 #design"
        results = extract_urls_with_context(content)

        assert len(results) == 1
        # Cleaned URL has trailing = added by urlencode
        assert results[0].url == "https://www.lukew.com/ff/entry.asp?2138="
        # Original URL matches what's in the note (no trailing =)
        assert results[0].original_url == "https://www.lukew.com/ff/entry.asp?2138"
        # This is the key: original_url can be used to find/remove from note
        assert results[0].original_url in content
        assert results[0].url not in content  # Cleaned URL won't match!

    def test_original_url_same_when_no_normalization(self) -> None:
        """Original URL should match cleaned URL when no normalization needed."""
        content = "- https://example.com/page?key=value #tag"
        results = extract_urls_with_context(content)

        assert len(results) == 1
        # Both should be the same when URL doesn't need normalization
        assert results[0].url == "https://example.com/page?key=value"
        assert results[0].original_url == "https://example.com/page?key=value"


class TestEscapeYamlString:
    """Tests for YAML string escaping."""

    def test_simple_string(self) -> None:
        """Simple strings should not be quoted."""
        assert _escape_yaml_string("Hello World") == "Hello World"

    def test_string_with_colon(self) -> None:
        """Strings with colons should be quoted."""
        result = _escape_yaml_string("Title: Subtitle")
        assert result == '"Title: Subtitle"'

    def test_string_with_hash(self) -> None:
        """Strings with hash should be quoted."""
        result = _escape_yaml_string("C# Programming")
        assert result == '"C# Programming"'

    def test_string_with_quotes(self) -> None:
        """Internal quotes should be escaped."""
        result = _escape_yaml_string('He said "hello"')
        assert result == '"He said \\"hello\\""'

    def test_string_starting_with_dash(self) -> None:
        """Strings starting with dash should be quoted."""
        result = _escape_yaml_string("- bullet point")
        assert result == '"- bullet point"'


class TestBuildFrontmatter:
    """Tests for frontmatter building."""

    def test_minimal_frontmatter(self) -> None:
        """Should build frontmatter with just URL."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(url="https://example.com", date=date)

        assert "---" in result
        assert "source: https://example.com" in result
        assert "date: 2025-12-16" in result
        assert "summary_status: success" in result

    def test_summary_status_success(self) -> None:
        """Should include summary_status: success by default."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_status="success",
        )

        assert "summary_status: success" in result

    def test_summary_status_error(self) -> None:
        """Should include summary_status: error when specified."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_status="error",
        )

        assert "summary_status: error" in result

    def test_summary_status_mocked(self) -> None:
        """Should include summary_status: mocked when specified."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_status="mocked",
        )

        assert "summary_status: mocked" in result

    def test_summary_model_included(self) -> None:
        """Should include summary_model when provided."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_model="gemini-2.5-flash",
        )

        assert "summary_model: gemini-2.5-flash" in result

    def test_summary_model_not_included_when_none(self) -> None:
        """Should not include summary_model field when None."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_model=None,
        )

        assert "summary_model:" not in result

    def test_summary_model_with_different_models(self) -> None:
        """Should include any model name provided."""
        date = datetime(2025, 12, 16)

        # Test with Gemini model
        result1 = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_model="gemini-1.5-pro",
        )
        assert "summary_model: gemini-1.5-pro" in result1

        # Test with Ollama model
        result2 = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_model="qwen3:latest",
        )
        assert "summary_model: qwen3:latest" in result2

        # Test with another model
        result3 = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_model="llama3.1:8b",
        )
        assert "summary_model: llama3.1:8b" in result3

    def test_summary_provider_included(self) -> None:
        """Should include summary_provider when provided."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_provider="google",
        )

        assert "summary_provider: google" in result

    def test_summary_provider_not_included_when_none(self) -> None:
        """Should not include summary_provider field when None."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_provider=None,
        )

        assert "summary_provider:" not in result

    def test_summary_provider_with_different_providers(self) -> None:
        """Should include any provider name provided."""
        date = datetime(2025, 12, 16)

        # Test with Google provider
        result1 = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_provider="google",
        )
        assert "summary_provider: google" in result1

        # Test with Ollama provider
        result2 = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_provider="ollama",
        )
        assert "summary_provider: ollama" in result2

        # Test with Azure provider
        result3 = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_provider="azure",
        )
        assert "summary_provider: azure" in result3

    def test_summary_model_and_provider_together(self) -> None:
        """Should include both summary_model and summary_provider when provided."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_model="gpt-4",
            summary_provider="azure",
        )

        assert "summary_model: gpt-4" in result
        assert "summary_provider: azure" in result
        # Verify provider comes after model
        model_pos = result.index("summary_model")
        provider_pos = result.index("summary_provider")
        assert model_pos < provider_pos

    def test_summary_date_default_to_now(self) -> None:
        """Should include summary_date with current time when not provided."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_date=None,  # Should default to now
        )

        # Should have summary_date field
        assert "summary_date:" in result
        # Should be in YYYY-MM-DD HH:MM:SS format
        # Since it defaults to now, we can't test exact value, just format
        import re

        assert re.search(r"summary_date: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result)

    def test_summary_date_with_specific_datetime(self) -> None:
        """Should include summary_date with specific datetime when provided."""
        date = datetime(2025, 12, 16)
        summary_date = datetime(2025, 12, 16, 14, 30, 45)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_date=summary_date,
        )

        assert "summary_date: 2025-12-16 14:30:45" in result

    def test_summary_date_format(self) -> None:
        """Should format summary_date as YYYY-MM-DD HH:MM:SS."""
        date = datetime(2025, 12, 16)
        # Single-digit month, day, hour, minute, second
        summary_date = datetime(2025, 1, 5, 9, 5, 3)
        result = build_frontmatter(
            url="https://example.com",
            date=date,
            summary_date=summary_date,
        )

        # Should be zero-padded
        assert "summary_date: 2025-01-05 09:05:03" in result

    def test_summary_date_different_from_note_date(self) -> None:
        """summary_date can be different from note date field."""
        note_date = datetime(2025, 12, 15)
        summary_date = datetime(2025, 12, 16, 10, 30, 0)
        result = build_frontmatter(
            url="https://example.com",
            date=note_date,
            summary_date=summary_date,
        )

        # Should have both dates
        assert "date: 2025-12-15" in result  # Note date
        assert "summary_date: 2025-12-16 10:30:00" in result  # Summary generation time

    def test_with_page_metadata(self) -> None:
        """Should include page metadata fields."""
        date = datetime(2025, 12, 16)
        metadata = PageMetadata(
            title="Test Article",
            author="John Smith",
            domain="example.com",
            content="Content",
            published_date="2025-12-10",
            article_tags=["python", "testing"],
        )
        result = build_frontmatter(
            url="https://example.com",
            page_metadata=metadata,
            date=date,
        )

        assert "title: Test Article" in result
        assert "author: John Smith" in result
        assert "domain: example.com" in result
        assert "published: 2025-12-10" in result

    def test_with_summary_result(self) -> None:
        """Should include summary result fields."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(
            content="Summary text",
            suggested_tags=["ai", "ml"],
            content_type="tutorial",
        )
        result = build_frontmatter(
            url="https://example.com",
            summary_result=summary,
            date=date,
        )

        assert "type: tutorial" in result
        assert "- ai" in result
        assert "- ml" in result

    def test_with_user_tags(self) -> None:
        """Should include user tags first in priority."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            user_tags=["important", "reading"],
            date=date,
        )

        assert "tags:" in result
        assert "- important" in result
        assert "- reading" in result

    def test_tag_merging(self) -> None:
        """Should merge tags from all sources."""
        date = datetime(2025, 12, 16)
        metadata = PageMetadata(
            title="Title",
            domain="example.com",
            content="Content",
            article_tags=["article-tag"],
        )
        summary = SummaryResult(
            content="Summary",
            suggested_tags=["ai-tag"],
            content_type="article",
        )
        result = build_frontmatter(
            url="https://example.com",
            page_metadata=metadata,
            summary_result=summary,
            user_tags=["user-tag"],
            date=date,
        )

        assert "- user-tag" in result
        assert "- article-tag" in result
        assert "- ai-tag" in result

    def test_with_source_note(self) -> None:
        """Should include backlink to source note."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            source_note="2025-12-16.md",
            date=date,
        )

        assert 'from: "[[2025-12-16]]"' in result

    def test_with_default_tags(self) -> None:
        """Should include default tags first."""
        date = datetime(2025, 12, 16)
        result = build_frontmatter(
            url="https://example.com",
            user_tags=["user"],
            default_tags=["summarized"],
            date=date,
        )

        # Default tags should come before user tags
        lines = result.split("\n")
        tag_lines = [line for line in lines if line.strip().startswith("- ")]
        assert tag_lines[0].strip() == "- summarized"
        assert tag_lines[1].strip() == "- user"

    def test_escapes_special_characters_in_title(self) -> None:
        """Should escape special characters in title."""
        date = datetime(2025, 12, 16)
        metadata = PageMetadata(
            title='Title with "quotes" and: colons',
            domain="example.com",
            content="Content",
        )
        result = build_frontmatter(
            url="https://example.com",
            page_metadata=metadata,
            date=date,
        )

        assert 'title: "Title with \\"quotes\\" and: colons"' in result


class TestWriteSummaryNoteWithMetadata:
    """Tests for writing summary notes with rich frontmatter."""

    def test_writes_note_with_metadata(self, tmp_path: Path) -> None:
        """Should write note with all metadata fields."""
        date = datetime(2025, 12, 16)
        metadata = PageMetadata(
            title="Test Article",
            author="John Smith",
            domain="example.com",
            content="Content",
            article_tags=["python"],
        )
        summary = SummaryResult(
            content="## Summary\n\nThis is the summary.",
            suggested_tags=["testing"],
            content_type="article",
        )

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com/article",
            summary_result=summary,
            page_metadata=metadata,
            user_tags=["reading"],
            date=date,
            source_note="2025-12-16.md",
        )

        assert filepath.exists()
        content = filepath.read_text()

        # Check frontmatter
        assert "source: https://example.com/article" in content
        assert "title: Test Article" in content
        assert "author: John Smith" in content
        assert "type: article" in content
        assert "date: 2025-12-16" in content
        assert "summary_status: success" in content
        assert 'from: "[[2025-12-16]]"' in content
        assert "- reading" in content
        assert "- python" in content
        assert "- testing" in content
        assert "domain: example.com" in content

        # Check summary content
        assert "## Summary" in content
        assert "This is the summary." in content

    def test_skips_existing_file(self, tmp_path: Path) -> None:
        """Should skip if file exists and overwrite=False."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Summary 1")

        # Write first time
        write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
        )

        # Write second time with different content
        summary2 = SummaryResult(content="Summary 2")
        write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary2,
            date=date,
            overwrite=False,
        )

        # Should still have first content
        filepath = tmp_path / "Summaries" / "2025-12-16-example-com.md"
        content = filepath.read_text()
        assert "Summary 1" in content
        assert "Summary 2" not in content

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """Should overwrite if overwrite=True."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Summary 1")

        # Write first time
        write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
        )

        # Overwrite
        summary2 = SummaryResult(content="Summary 2")
        write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary2,
            date=date,
            overwrite=True,
        )

        filepath = tmp_path / "Summaries" / "2025-12-16-example-com.md"
        content = filepath.read_text()
        assert "Summary 2" in content

    def test_includes_summary_status_field(self, tmp_path: Path) -> None:
        """Should include summary_status field in written note."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Test summary")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_status="success",
        )

        content = filepath.read_text()
        assert "summary_status: success" in content

    def test_includes_summary_status_error(self, tmp_path: Path) -> None:
        """Should include summary_status: error when specified."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Error case")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_status="error",
        )

        content = filepath.read_text()
        assert "summary_status: error" in content

    def test_includes_summary_status_mocked(self, tmp_path: Path) -> None:
        """Should include summary_status: mocked when specified."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Mocked summary")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_status="mocked",
        )

        content = filepath.read_text()
        assert "summary_status: mocked" in content

    def test_includes_summary_model_when_provided(self, tmp_path: Path) -> None:
        """Should include summary_model field when provided."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Test summary")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_model="gemini-2.5-flash",
        )

        content = filepath.read_text()
        assert "summary_model: gemini-2.5-flash" in content

    def test_omits_summary_model_when_none(self, tmp_path: Path) -> None:
        """Should not include summary_model field when None."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Test summary")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_model=None,
        )

        content = filepath.read_text()
        assert "summary_model:" not in content

    def test_includes_summary_model_ollama(self, tmp_path: Path) -> None:
        """Should include Ollama model names."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Test summary")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_model="qwen3:latest",
        )

        content = filepath.read_text()
        assert "summary_model: qwen3:latest" in content

    def test_includes_summary_provider_when_provided(self, tmp_path: Path) -> None:
        """Should include summary_provider field when provided."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Test summary")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_provider="google",
        )

        content = filepath.read_text()
        assert "summary_provider: google" in content

    def test_omits_summary_provider_when_none(self, tmp_path: Path) -> None:
        """Should not include summary_provider field when None."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Test summary")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_provider=None,
        )

        content = filepath.read_text()
        assert "summary_provider:" not in content

    def test_includes_summary_provider_azure(self, tmp_path: Path) -> None:
        """Should include Azure provider name."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Test summary")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_provider="azure",
        )

        content = filepath.read_text()
        assert "summary_provider: azure" in content

    def test_includes_summary_date_field(self, tmp_path: Path) -> None:
        """Should include summary_date field with timestamp."""
        date = datetime(2025, 12, 16)
        summary_date = datetime(2025, 12, 16, 14, 30, 45)
        summary = SummaryResult(content="Test summary")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_date=summary_date,
        )

        content = filepath.read_text()
        assert "summary_date: 2025-12-16 14:30:45" in content

    def test_summary_date_defaults_to_current_time(self, tmp_path: Path) -> None:
        """Should include summary_date with current time when not provided."""
        date = datetime(2025, 12, 16)
        summary = SummaryResult(content="Test summary")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_date=None,  # Should default to now
        )

        content = filepath.read_text()
        # Should have summary_date field with proper format
        assert "summary_date:" in content
        import re

        assert re.search(r"summary_date: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", content)

    def test_all_summary_fields_together(self, tmp_path: Path) -> None:
        """Should include all summary_ fields when provided together."""
        date = datetime(2025, 12, 16)
        summary_date = datetime(2025, 12, 16, 10, 30, 0)
        summary = SummaryResult(content="Complete test")

        filepath = write_summary_note_with_metadata(
            vault_path=tmp_path,
            out_folder="Summaries",
            url="https://example.com",
            summary_result=summary,
            date=date,
            summary_status="success",
            summary_model="gpt-4",
            summary_provider="azure",
            summary_date=summary_date,
        )

        content = filepath.read_text()
        assert "summary_status: success" in content
        assert "summary_model: gpt-4" in content
        assert "summary_provider: azure" in content
        assert "summary_date: 2025-12-16 10:30:00" in content


class TestRemoveUrlLineFromNote:
    """Tests for removing URL lines from daily notes."""

    def test_remove_bare_url_line(self, tmp_path: Path) -> None:
        """Should remove a line containing a bare URL."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\n- Task 1\n- https://example.com/article\n- Task 2\n")

        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            url="https://example.com/article",
        )

        assert result is True
        content = note_file.read_text()
        assert "https://example.com/article" not in content
        assert "Task 1" in content
        assert "Task 2" in content

    def test_remove_markdown_link_line(self, tmp_path: Path) -> None:
        """Should remove a line containing a markdown link with the URL."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text(
            "# 2025-12-16\n\n"
            "- Task 1\n"
            "- [Great Article](https://example.com/article) #ai\n"
            "- Task 2\n"
        )

        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            url="https://example.com/article",
        )

        assert result is True
        content = note_file.read_text()
        assert "https://example.com/article" not in content
        assert "Great Article" not in content
        assert "#ai" not in content
        assert "Task 1" in content
        assert "Task 2" in content

    def test_remove_url_in_subfolder(self, tmp_path: Path) -> None:
        """Should work with daily notes in subfolder."""
        journal = tmp_path / "Journal"
        journal.mkdir()
        note_file = journal / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\n- https://example.com/article\n- Other task\n")

        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="Journal",
            note_filename="2025-12-16.md",
            url="https://example.com/article",
        )

        assert result is True
        content = note_file.read_text()
        assert "https://example.com/article" not in content
        assert "Other task" in content

    def test_return_false_if_url_not_found(self, tmp_path: Path) -> None:
        """Should return False if URL is not in the note."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\n- https://other-url.com\n")

        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            url="https://example.com/not-here",
        )

        assert result is False
        # Content should be unchanged
        content = note_file.read_text()
        assert "https://other-url.com" in content

    def test_return_false_if_note_not_found(self, tmp_path: Path) -> None:
        """Should return False if daily note doesn't exist."""
        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="nonexistent.md",
            url="https://example.com/article",
        )

        assert result is False

    def test_preserves_trailing_newline(self, tmp_path: Path) -> None:
        """Should preserve trailing newline if original had one."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\n- https://example.com/article\n- Task 2\n")

        remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            url="https://example.com/article",
        )

        content = note_file.read_text()
        assert content.endswith("\n")

    def test_removes_all_lines_with_same_url(self, tmp_path: Path) -> None:
        """Should remove all lines containing the URL (in case of duplicates)."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text(
            "# 2025-12-16\n\n"
            "- https://example.com/article\n"
            "- Task 2\n"
            "- https://example.com/article again\n"
        )

        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            url="https://example.com/article",
        )

        assert result is True
        content = note_file.read_text()
        assert "https://example.com/article" not in content
        assert "Task 2" in content

    def test_handles_url_with_query_params(self, tmp_path: Path) -> None:
        """Should handle URLs with query parameters."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text(
            "# 2025-12-16\n\n- https://example.com/article?utm=test&ref=link\n- Task 2\n"
        )

        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            url="https://example.com/article?utm=test&ref=link",
        )

        assert result is True
        content = note_file.read_text()
        assert "https://example.com/article" not in content
        assert "Task 2" in content

    def test_removes_consecutive_blank_lines(self, tmp_path: Path) -> None:
        """Should collapse consecutive blank lines after URL removal."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\n- https://example.com\n\n\n- Task 2\n")

        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            url="https://example.com",
        )

        assert result is True
        content = note_file.read_text()
        # Should have at most one blank line between heading and Task 2
        assert "\n\n\n" not in content
        assert "# 2025-12-16" in content
        assert "Task 2" in content

    def test_removes_leading_blank_lines(self, tmp_path: Path) -> None:
        """Should remove leading blank lines after URL removal."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text("- https://example.com\n\n- Task 2\n")

        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            url="https://example.com",
        )

        assert result is True
        content = note_file.read_text()
        # Should not start with blank line
        assert not content.startswith("\n")
        assert "Task 2" in content

    def test_removes_trailing_blank_lines(self, tmp_path: Path) -> None:
        """Should remove trailing blank lines after URL removal."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\n- Task 1\n\n- https://example.com\n\n\n")

        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            url="https://example.com",
        )

        assert result is True
        content = note_file.read_text()
        # Should end with single newline, not multiple blank lines
        assert content.endswith("- Task 1\n")
        assert not content.endswith("\n\n")

    def test_cleans_whitespace_when_all_urls_removed(self, tmp_path: Path) -> None:
        """Should handle whitespace cleanup when removing the only URL."""
        note_file = tmp_path / "2025-12-16.md"
        note_file.write_text("# 2025-12-16\n\n- https://example.com\n")

        result = remove_url_line_from_note(
            vault_path=tmp_path,
            daily_notes_folder="",
            note_filename="2025-12-16.md",
            url="https://example.com",
        )

        assert result is True
        content = note_file.read_text()
        # Should just have the heading with newline
        assert content == "# 2025-12-16\n"


class TestFindDailyNotesWithUrls:
    """Tests for finding daily notes containing URLs."""

    def test_find_notes_with_urls(self, tmp_path: Path) -> None:
        """Should find daily notes that contain URLs."""
        # Create notes with URLs
        (tmp_path / "2025-12-15.md").write_text("Check out https://example.com")
        (tmp_path / "2025-12-14.md").write_text("No links here")
        (tmp_path / "2025-12-13.md").write_text("[Link](https://test.com) and https://other.com")

        result = find_daily_notes_with_urls(tmp_path)

        assert len(result) == 2
        assert ("2025-12-15", 1) in result
        assert ("2025-12-13", 2) in result

    def test_sorted_by_date_descending(self, tmp_path: Path) -> None:
        """Should return results sorted by date, newest first."""
        (tmp_path / "2025-12-01.md").write_text("https://old.com")
        (tmp_path / "2025-12-15.md").write_text("https://new.com")
        (tmp_path / "2025-12-10.md").write_text("https://middle.com")

        result = find_daily_notes_with_urls(tmp_path)

        dates = [date for date, _ in result]
        assert dates == ["2025-12-15", "2025-12-10", "2025-12-01"]

    def test_ignores_non_daily_note_files(self, tmp_path: Path) -> None:
        """Should only match files with YYYY-MM-DD.md pattern."""
        (tmp_path / "2025-12-15.md").write_text("https://example.com")
        (tmp_path / "notes.md").write_text("https://ignored.com")
        (tmp_path / "random-file.md").write_text("https://ignored.com")
        (tmp_path / "12-15-2025.md").write_text("https://wrong-format.com")

        result = find_daily_notes_with_urls(tmp_path)

        assert len(result) == 1
        assert result[0] == ("2025-12-15", 1)

    def test_handles_daily_notes_subfolder(self, tmp_path: Path) -> None:
        """Should find notes in a daily notes subfolder."""
        journal = tmp_path / "Journal"
        journal.mkdir()
        (journal / "2025-12-15.md").write_text("https://example.com")

        result = find_daily_notes_with_urls(tmp_path, daily_notes_folder="Journal")

        assert len(result) == 1
        assert result[0] == ("2025-12-15", 1)

    def test_returns_empty_for_no_urls(self, tmp_path: Path) -> None:
        """Should return empty list if no notes have URLs."""
        (tmp_path / "2025-12-15.md").write_text("Just some text")
        (tmp_path / "2025-12-14.md").write_text("More text without links")

        result = find_daily_notes_with_urls(tmp_path)

        assert result == []

    def test_returns_empty_for_missing_folder(self, tmp_path: Path) -> None:
        """Should return empty list if folder doesn't exist."""
        result = find_daily_notes_with_urls(tmp_path, daily_notes_folder="NonExistent")

        assert result == []
