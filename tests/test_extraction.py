"""Tests for the content extraction module."""

import pytest
from bs4 import BeautifulSoup

from summarize_links.exceptions import ContentExtractionError
from summarize_links.extract import (
    _clean_text,
    _extract_article_content,
    _find_largest_text_block,
    extract_readable_content,
    truncate_content,
)


class TestCleanText:
    """Tests for text cleaning."""

    def test_collapse_multiple_newlines(self) -> None:
        """Should collapse 3+ newlines to 2."""
        text = "Hello\n\n\n\nWorld"
        result = _clean_text(text)
        assert result == "Hello\n\nWorld"

    def test_collapse_multiple_spaces(self) -> None:
        """Should collapse multiple spaces to single."""
        text = "Hello    World"
        result = _clean_text(text)
        assert result == "Hello World"

    def test_strip_line_whitespace(self) -> None:
        """Should strip leading/trailing whitespace from lines."""
        text = "  Hello  \n  World  "
        result = _clean_text(text)
        assert result == "Hello\nWorld"


class TestTruncateContent:
    """Tests for content truncation."""

    def test_no_truncation_needed(self) -> None:
        """Should return content unchanged if under limit."""
        content = "Short content"
        result = truncate_content(content, max_length=100)
        assert result == content

    def test_truncate_at_paragraph(self) -> None:
        """Should prefer truncating at paragraph boundary."""
        content = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = truncate_content(content, max_length=40)
        assert "First paragraph" in result
        assert "[Content truncated...]" in result

    def test_truncate_at_sentence(self) -> None:
        """Should fall back to sentence boundary."""
        content = "First sentence. Second sentence. Third sentence."
        result = truncate_content(content, max_length=35)
        assert "First sentence." in result
        assert "[Content truncated...]" in result


class TestExtractReadableContent:
    """Tests for HTML content extraction."""

    def test_extract_from_article_tag(self, sample_html_content: str) -> None:
        """Should extract content from article tag."""
        content, title = extract_readable_content(sample_html_content)
        assert "main content" in content
        assert "Key point" in content
        assert title == "Test Article"

    def test_removes_script_tags(self) -> None:
        """Should remove script elements."""
        html = """
        <html>
            <body>
                <script>alert('bad');</script>
                <p>Good content here.</p>
            </body>
        </html>
        """
        content, _ = extract_readable_content(html)
        assert "alert" not in content
        assert "Good content" in content

    def test_removes_nav_elements(self) -> None:
        """Should remove navigation elements."""
        html = """
        <html>
            <body>
                <nav><a href="/">Home</a><a href="/about">About</a></nav>
                <article><p>Main article content here.</p></article>
            </body>
        </html>
        """
        content, _ = extract_readable_content(html)
        assert "Home" not in content
        assert "Main article" in content

    def test_removes_footer(self) -> None:
        """Should remove footer elements."""
        html = """
        <html>
            <body>
                <article><p>Main content.</p></article>
                <footer>Copyright 2025</footer>
            </body>
        </html>
        """
        content, _ = extract_readable_content(html)
        assert "Copyright" not in content
        assert "Main content" in content

    def test_extracts_title(self) -> None:
        """Should extract page title."""
        html = """
        <html>
            <head><title>My Page Title</title></head>
            <body><article><p>Content here.</p></article></body>
        </html>
        """
        _, title = extract_readable_content(html)
        assert title == "My Page Title"

    def test_cleans_title_with_separator(self) -> None:
        """Should clean title with site name."""
        html = """
        <html>
            <head><title>Article Title | Site Name</title></head>
            <body><article><p>Content here.</p></article></body>
        </html>
        """
        _, title = extract_readable_content(html)
        assert title == "Article Title"

    def test_fallback_to_largest_block(self) -> None:
        """Should fall back to largest text block when no article."""
        html = """
        <html>
            <body>
                <div>Short text</div>
                <div>This is a much longer piece of content that should be
                selected as the main content because it has more text than
                any other element in the document. It contains enough words
                to pass the minimum threshold for content detection.</div>
            </body>
        </html>
        """
        content, _ = extract_readable_content(html)
        assert "much longer piece" in content

    def test_raises_on_empty_content(self) -> None:
        """Should raise error when no content found."""
        html = "<html><body></body></html>"
        with pytest.raises(ContentExtractionError, match="No readable content"):
            extract_readable_content(html)


class TestExtractArticleContent:
    """Tests for article-specific extraction."""

    def test_extracts_article_element(self) -> None:
        """Should extract from article element."""
        html = (
            "<article><p>Article content here with enough text to pass threshold. "
            "This paragraph needs to be at least 200 characters long to be "
            "considered valid content. Let's add more text to ensure we meet "
            "the minimum threshold requirements for extraction.</p></article>"
        )
        soup = BeautifulSoup(html, "lxml")
        content = _extract_article_content(soup)
        assert content is not None
        assert "Article content" in content

    def test_extracts_main_role(self) -> None:
        """Should extract from main role element."""
        html = (
            '<div role="main"><p>Main content here with enough text to pass '
            "the threshold. This needs to be a longer paragraph with more than "
            "200 characters to be detected properly. Adding additional sentences "
            "to ensure we meet the minimum content length requirements.</p></div>"
        )
        soup = BeautifulSoup(html, "lxml")
        content = _extract_article_content(soup)
        assert content is not None
        assert "Main content" in content

    def test_skips_small_content(self) -> None:
        """Should skip elements with too little content."""
        html = "<article><p>Too short.</p></article>"
        soup = BeautifulSoup(html, "lxml")
        content = _extract_article_content(soup)
        assert content is None


class TestFindLargestTextBlock:
    """Tests for fallback text block finding."""

    def test_finds_largest_paragraph(self) -> None:
        """Should find the largest text block."""
        html = """
        <div><p>Short</p></div>
        <div><p>This is a much longer paragraph that contains many more words
        and should be selected as the largest text block in the document because
        it has significantly more content than any other element.</p></div>
        """
        soup = BeautifulSoup(html, "lxml")
        content = _find_largest_text_block(soup)
        assert "much longer paragraph" in content

    def test_skips_nav_elements(self) -> None:
        """Should skip elements with nav-like class."""
        html = """
        <div class="nav-menu"><p>Navigation text should be skipped.</p></div>
        <div><p>Actual content that should be found because this paragraph contains
        more than 100 characters which is the minimum threshold for content detection
        and it will be selected as the main content block.</p></div>
        """
        soup = BeautifulSoup(html, "lxml")
        content = _find_largest_text_block(soup)
        assert "Actual content" in content
