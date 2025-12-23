"""Tests for the content extraction module."""

import pytest
from bs4 import BeautifulSoup
from pytest_mock import MockerFixture

from summarize_links.exceptions import ContentExtractionError, URLValidationError
from summarize_links.extract import (
    _clean_text,
    _extract_article_content,
    _extract_article_tags,
    _extract_author,
    _extract_description,
    _extract_published_date,
    _extract_site_name,
    _extract_title,
    _find_largest_text_block,
    _is_content_garbled,
    extract_page_metadata,
    extract_readable_content,
    truncate_content,
    validate_url,
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


class TestExtractTitle:
    """Tests for title extraction."""

    def test_extract_og_title(self) -> None:
        """Should prefer Open Graph title."""
        html = """
        <html>
            <head>
                <title>Page Title | Site Name</title>
                <meta property="og:title" content="Better OG Title">
            </head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        title = _extract_title(soup)
        assert title == "Better OG Title"

    def test_extract_twitter_title(self) -> None:
        """Should use Twitter title if no OG title."""
        html = """
        <html>
            <head>
                <title>Page Title</title>
                <meta name="twitter:title" content="Twitter Title">
            </head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        title = _extract_title(soup)
        assert title == "Twitter Title"

    def test_fallback_to_title_tag(self) -> None:
        """Should fall back to title tag."""
        html = """
        <html>
            <head><title>Simple Title</title></head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        title = _extract_title(soup)
        assert title == "Simple Title"

    def test_clean_title_with_pipe(self) -> None:
        """Should remove site name after pipe."""
        html = """
        <html>
            <head><title>Article Title | Site Name</title></head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        title = _extract_title(soup)
        assert title == "Article Title"

    def test_clean_title_with_dash(self) -> None:
        """Should remove site name after dash."""
        html = """
        <html>
            <head><title>Article Title - Site Name</title></head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        title = _extract_title(soup)
        assert title == "Article Title"

    def test_untitled_fallback(self) -> None:
        """Should return Untitled if no title found."""
        html = "<html><head></head><body><p>Content</p></body></html>"
        soup = BeautifulSoup(html, "lxml")
        title = _extract_title(soup)
        assert title == "Untitled"


class TestExtractAuthor:
    """Tests for author extraction."""

    def test_extract_author_meta(self) -> None:
        """Should extract from author meta tag."""
        html = """
        <html>
            <head><meta name="author" content="John Smith"></head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        author = _extract_author(soup)
        assert author == "John Smith"

    def test_extract_article_author(self) -> None:
        """Should extract from article:author meta tag."""
        html = """
        <html>
            <head><meta property="article:author" content="Jane Doe"></head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        author = _extract_author(soup)
        assert author == "Jane Doe"

    def test_extract_author_from_json_ld(self) -> None:
        """Should extract from JSON-LD schema."""
        html = """
        <html>
            <head>
                <script type="application/ld+json">
                {"@type": "Article", "author": {"name": "Schema Author"}}
                </script>
            </head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        author = _extract_author(soup)
        assert author == "Schema Author"

    def test_extract_author_from_json_ld_string(self) -> None:
        """Should handle JSON-LD author as string."""
        html = """
        <html>
            <head>
                <script type="application/ld+json">
                {"@type": "Article", "author": "Simple Author"}
                </script>
            </head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        author = _extract_author(soup)
        assert author == "Simple Author"

    def test_no_author_returns_none(self) -> None:
        """Should return None if no author found."""
        html = "<html><head></head><body><p>Content</p></body></html>"
        soup = BeautifulSoup(html, "lxml")
        author = _extract_author(soup)
        assert author is None


class TestExtractDescription:
    """Tests for description extraction."""

    def test_extract_og_description(self) -> None:
        """Should prefer OG description."""
        html = """
        <html>
            <head>
                <meta name="description" content="Regular description">
                <meta property="og:description" content="OG description">
            </head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        desc = _extract_description(soup)
        assert desc == "OG description"

    def test_fallback_to_meta_description(self) -> None:
        """Should fall back to regular description."""
        html = """
        <html>
            <head><meta name="description" content="Meta description"></head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        desc = _extract_description(soup)
        assert desc == "Meta description"


class TestExtractPublishedDate:
    """Tests for publication date extraction."""

    def test_extract_article_published_time(self) -> None:
        """Should extract from article:published_time."""
        html = """
        <html>
            <head>
                <meta property="article:published_time" content="2025-12-15T10:30:00Z">
            </head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        date = _extract_published_date(soup)
        assert date == "2025-12-15"

    def test_extract_date_without_time(self) -> None:
        """Should handle date without time component."""
        html = """
        <html>
            <head><meta name="date" content="2025-12-15"></head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        date = _extract_published_date(soup)
        assert date == "2025-12-15"


class TestExtractSiteName:
    """Tests for site name extraction."""

    def test_extract_site_name(self) -> None:
        """Should extract from og:site_name."""
        html = """
        <html>
            <head><meta property="og:site_name" content="Example Blog"></head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        site_name = _extract_site_name(soup)
        assert site_name == "Example Blog"


class TestExtractArticleTags:
    """Tests for article tag extraction."""

    def test_extract_from_keywords(self) -> None:
        """Should extract from keywords meta tag."""
        html = """
        <html>
            <head><meta name="keywords" content="python, testing, automation"></head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        tags = _extract_article_tags(soup, "")
        assert "python" in tags
        assert "testing" in tags
        assert "automation" in tags

    def test_extract_from_article_tag(self) -> None:
        """Should extract from article:tag meta tags."""
        html = """
        <html>
            <head>
                <meta property="article:tag" content="AI">
                <meta property="article:tag" content="Machine Learning">
            </head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        tags = _extract_article_tags(soup, "")
        assert "AI" in tags
        assert "Machine Learning" in tags

    def test_extract_hashtags_from_content(self) -> None:
        """Should extract hashtags from content."""
        html = "<html><head></head><body><p>Content</p></body></html>"
        soup = BeautifulSoup(html, "lxml")
        content = "This article discusses #AI and #machine-learning concepts."
        tags = _extract_article_tags(soup, content)
        assert "AI" in tags
        assert "machine-learning" in tags

    def test_deduplicates_tags(self) -> None:
        """Should deduplicate tags (case insensitive)."""
        html = """
        <html>
            <head><meta name="keywords" content="Python, python, PYTHON"></head>
            <body><p>Content</p></body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")
        tags = _extract_article_tags(soup, "")
        # Should only have one variation of "python"
        python_tags = [t for t in tags if t.lower() == "python"]
        assert len(python_tags) == 1


class TestExtractPageMetadata:
    """Tests for full page metadata extraction."""

    def test_extracts_all_metadata(self) -> None:
        """Should extract all available metadata."""
        html = """
        <html>
            <head>
                <title>Test Article | Example Site</title>
                <meta property="og:title" content="Test Article">
                <meta name="author" content="John Smith">
                <meta property="og:description" content="A test article">
                <meta property="article:published_time" content="2025-12-15T10:00:00Z">
                <meta property="og:site_name" content="Example Site">
                <meta name="keywords" content="testing, python">
            </head>
            <body>
                <article>
                    <p>This is the main content of the article. It contains enough
                    text to pass the minimum threshold for content extraction. The
                    article discusses various topics related to testing and Python
                    programming. We need to make sure this paragraph is long enough
                    to be considered valid content by the extraction algorithm.</p>
                </article>
            </body>
        </html>
        """
        metadata = extract_page_metadata(html, "https://example.com/article")

        assert metadata.title == "Test Article"
        assert metadata.author == "John Smith"
        assert metadata.description == "A test article"
        assert metadata.published_date == "2025-12-15"
        assert metadata.site_name == "Example Site"
        assert metadata.domain == "example.com"
        assert "testing" in metadata.article_tags
        assert "main content" in metadata.content.lower()

    def test_extracts_domain_from_url(self) -> None:
        """Should extract domain from URL."""
        html = """
        <html>
            <body>
                <article><p>Content that is long enough to pass the threshold.
                This needs to be at least 200 characters for the extraction to work
                properly. Adding more text to ensure we meet the requirement.</p></article>
            </body>
        </html>
        """
        metadata = extract_page_metadata(html, "https://www.example.com/path")
        assert metadata.domain == "example.com"

    def test_handles_missing_metadata(self) -> None:
        """Should handle pages with minimal metadata."""
        html = """
        <html>
            <body>
                <article><p>Just some content without any metadata at all.
                This paragraph needs to be long enough to be extracted properly
                by the content extraction algorithm. Adding more filler text.</p></article>
            </body>
        </html>
        """
        metadata = extract_page_metadata(html, "https://example.com")

        assert metadata.title == "Untitled"
        assert metadata.author is None
        assert metadata.description is None
        assert metadata.domain == "example.com"
        assert len(metadata.content) > 0


class TestFetchContentRetry:
    """Tests for fetch_content retry behavior."""

    def test_retry_on_connection_error(self, mocker: MockerFixture) -> None:
        """Should retry on connection errors."""
        import requests

        from summarize_links.extract import fetch_content

        mocker.patch("time.sleep")  # Skip actual waiting between retries

        # Mock session.get to fail twice then succeed
        mock_session = mocker.MagicMock()
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.text = "<html><body>Success</body></html>"

        # First two calls raise ConnectionError, third succeeds
        mock_session.get.side_effect = [
            requests.exceptions.ConnectionError("Network error"),
            requests.exceptions.ConnectionError("Network error"),
            mock_response,
        ]

        mocker.patch("summarize_links.extract._create_session", return_value=mock_session)

        content, content_type = fetch_content("https://example.com")
        assert content == "<html><body>Success</body></html>"
        assert mock_session.get.call_count == 3

    def test_no_retry_on_client_error(self, mocker: MockerFixture) -> None:
        """Should NOT retry on 4xx client errors."""
        import requests

        from summarize_links.exceptions import ContentFetchError
        from summarize_links.extract import fetch_content

        mocker.patch("time.sleep")  # Skip actual waiting between retries

        mock_session = mocker.MagicMock()
        mock_response = mocker.MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )

        mock_session.get.return_value = mock_response

        mocker.patch("summarize_links.extract._create_session", return_value=mock_session)

        with pytest.raises(ContentFetchError) as exc_info:
            fetch_content("https://example.com/missing")

        assert "404" in str(exc_info.value)
        # Should only try once - no retries for 4xx
        assert mock_session.get.call_count == 1

    def test_retry_on_server_error(self, mocker: MockerFixture) -> None:
        """Should retry on 5xx server errors."""
        from summarize_links.extract import fetch_content

        mocker.patch("time.sleep")  # Skip actual waiting between retries

        mock_session = mocker.MagicMock()
        mock_response_500 = mocker.MagicMock()
        mock_response_500.status_code = 500

        mock_response_ok = mocker.MagicMock()
        mock_response_ok.status_code = 200
        mock_response_ok.headers = {"Content-Type": "text/html"}
        mock_response_ok.text = "<html><body>Success</body></html>"

        # First call returns 500, second succeeds
        mock_session.get.side_effect = [mock_response_500, mock_response_ok]

        mocker.patch("summarize_links.extract._create_session", return_value=mock_session)

        content, content_type = fetch_content("https://example.com")
        assert content == "<html><body>Success</body></html>"
        assert mock_session.get.call_count == 2

    def test_exhausted_retries_raises_error(self, mocker: MockerFixture) -> None:
        """Should raise ContentFetchError after all retries exhausted."""
        import requests

        from summarize_links.exceptions import ContentFetchError
        from summarize_links.extract import HTTP_RETRY_ATTEMPTS, fetch_content

        mocker.patch("time.sleep")  # Skip actual waiting between retries

        mock_session = mocker.MagicMock()
        mock_session.get.side_effect = requests.exceptions.ConnectionError("Network down")

        mocker.patch("summarize_links.extract._create_session", return_value=mock_session)

        with pytest.raises(ContentFetchError) as exc_info:
            fetch_content("https://example.com")

        assert "Failed after" in str(exc_info.value)
        assert mock_session.get.call_count == HTTP_RETRY_ATTEMPTS


class TestValidateUrl:
    """Tests for URL validation."""

    def test_valid_http_url(self) -> None:
        """Should accept valid http URLs."""
        validate_url("http://example.com/page")  # Should not raise

    def test_valid_https_url(self) -> None:
        """Should accept valid https URLs."""
        validate_url("https://example.com/page?query=1#anchor")  # Should not raise

    def test_empty_url_rejected(self) -> None:
        """Should reject empty URLs."""
        with pytest.raises(URLValidationError, match="cannot be empty"):
            validate_url("")

    def test_none_url_rejected(self) -> None:
        """Should reject None (fails empty check)."""
        with pytest.raises(URLValidationError, match="cannot be empty"):
            validate_url(None)  # type: ignore

    def test_file_scheme_rejected(self) -> None:
        """Should reject file:// URLs (security risk)."""
        with pytest.raises(URLValidationError, match="Invalid URL scheme"):
            validate_url("file:///etc/passwd")

    def test_javascript_scheme_rejected(self) -> None:
        """Should reject javascript: URLs."""
        with pytest.raises(URLValidationError, match="Invalid URL scheme"):
            validate_url("javascript:alert(1)")

    def test_ftp_scheme_rejected(self) -> None:
        """Should reject ftp:// URLs."""
        with pytest.raises(URLValidationError, match="Invalid URL scheme"):
            validate_url("ftp://example.com/file.txt")

    def test_missing_scheme_rejected(self) -> None:
        """Should reject URLs without scheme."""
        with pytest.raises(URLValidationError, match="no scheme"):
            validate_url("example.com/page")

    def test_missing_domain_rejected(self) -> None:
        """Should reject URLs without domain."""
        with pytest.raises(URLValidationError, match="no domain"):
            validate_url("https:///path/to/page")

    def test_invalid_domain_rejected(self) -> None:
        """Should reject URLs with invalid domain format."""
        with pytest.raises(URLValidationError, match="invalid domain"):
            validate_url("https://nodots/page")

    def test_localhost_allowed(self) -> None:
        """Should accept localhost URLs."""
        validate_url("http://localhost:8080/page")  # Should not raise

    def test_very_long_url_rejected(self) -> None:
        """Should reject URLs exceeding max length."""
        long_url = "https://example.com/" + "a" * 3000
        with pytest.raises(URLValidationError, match="exceeds maximum length"):
            validate_url(long_url)

    def test_url_with_port_accepted(self) -> None:
        """Should accept URLs with port numbers."""
        validate_url("https://example.com:8443/page")  # Should not raise

    def test_unicode_domain_accepted(self) -> None:
        """Should accept URLs with unicode domains."""
        validate_url("https://例え.jp/page")  # Should not raise


class TestPaywallDetection:
    """Tests for paywall domain detection and HTTP error formatting."""

    def test_known_paywall_domain_exact_match(self) -> None:
        """Should detect exact match paywall domains."""
        from summarize_links.extract import _get_paywall_info

        result = _get_paywall_info("https://wsj.com/article")
        assert result is not None
        assert "Wall Street Journal" in result

    def test_paywall_subdomain_match(self) -> None:
        """Should detect paywall domains with www prefix."""
        from summarize_links.extract import _get_paywall_info

        result = _get_paywall_info("https://www.nytimes.com/article")
        assert result is not None
        assert "New York Times" in result

    def test_non_paywall_domain_returns_none(self) -> None:
        """Should return None for non-paywall domains."""
        from summarize_links.extract import _get_paywall_info

        result = _get_paywall_info("https://example.com/article")
        assert result is None

    def test_format_http_error_with_paywall(self) -> None:
        """Should include paywall info in error message for known sites."""
        from summarize_links.extract import _format_http_error

        result = _format_http_error(403, "https://wsj.com/article")
        assert "403" in result
        assert "Paywall" in result
        assert "Wall Street Journal" in result

    def test_format_http_error_without_paywall(self) -> None:
        """Should return standard error for non-paywall sites."""
        from summarize_links.extract import _format_http_error

        result = _format_http_error(404, "https://example.com/missing")
        assert "404" in result
        assert "Page not found" in result
        assert "Paywall" not in result

    def test_format_http_error_unknown_status(self) -> None:
        """Should handle unknown HTTP status codes."""
        from summarize_links.extract import _format_http_error

        result = _format_http_error(418, "https://example.com")
        assert "418" in result
        assert "Request failed" in result


class TestMarkdownExtraction:
    """Tests for markdown content extraction."""

    def test_extract_title_from_h1_heading(self) -> None:
        """Should extract title from first H1 heading."""
        from summarize_links.extract import _extract_markdown_metadata

        content = "# My Article Title\n\nSome content here."
        metadata = _extract_markdown_metadata(content, "https://example.com/article.md")

        assert metadata.title == "My Article Title"
        assert metadata.domain == "example.com"

    def test_extract_author_from_italic_line(self) -> None:
        """Should extract author from italic line with comma."""
        from summarize_links.extract import _extract_markdown_metadata

        content = "# Article Title\n\n_John Smith, December 2025_\n\nContent here."
        metadata = _extract_markdown_metadata(content, "https://example.com/article.md")

        assert metadata.author == "John Smith"

    def test_handles_markdown_without_title(self) -> None:
        """Should default to Untitled when no H1 found."""
        from summarize_links.extract import _extract_markdown_metadata

        content = "Just some content without a heading."
        metadata = _extract_markdown_metadata(content, "https://example.com/doc.md")

        assert metadata.title == "Untitled"

    def test_clean_markdown_removes_html_images(self) -> None:
        """Should remove HTML image tags from markdown."""
        from summarize_links.extract import _clean_markdown

        content = 'Text before <img src="image.jpg" alt="test"> text after.'
        result = _clean_markdown(content)

        assert "<img" not in result
        assert "Text before" in result
        assert "text after" in result

    def test_clean_markdown_removes_markdown_images(self) -> None:
        """Should remove markdown image syntax."""
        from summarize_links.extract import _clean_markdown

        content = "Text before ![alt text](image.png) text after."
        result = _clean_markdown(content)

        assert "![" not in result
        assert "Text before" in result
        assert "text after" in result

    def test_clean_markdown_collapses_blank_lines(self) -> None:
        """Should collapse multiple blank lines."""
        from summarize_links.extract import _clean_markdown

        content = "Line 1\n\n\n\n\nLine 2"
        result = _clean_markdown(content)

        assert result == "Line 1\n\nLine 2"


class TestNonContentFiltering:
    """Tests for non-content element detection."""

    def test_identifies_nav_class(self) -> None:
        """Should identify elements with nav class as non-content."""
        from bs4 import Tag

        from summarize_links.extract import _is_non_content_element

        html = '<div class="nav-menu">Navigation</div>'
        soup = BeautifulSoup(html, "lxml")
        element = soup.find("div")
        assert isinstance(element, Tag)

        assert _is_non_content_element(element) is True

    def test_identifies_sidebar_id(self) -> None:
        """Should identify elements with sidebar id as non-content."""
        from bs4 import Tag

        from summarize_links.extract import _is_non_content_element

        html = '<aside id="sidebar">Sidebar content</aside>'
        soup = BeautifulSoup(html, "lxml")
        element = soup.find("aside")
        assert isinstance(element, Tag)

        assert _is_non_content_element(element) is True

    def test_identifies_footer_class(self) -> None:
        """Should identify elements with footer class as non-content."""
        from bs4 import Tag

        from summarize_links.extract import _is_non_content_element

        html = '<div class="footer-links">Footer</div>'
        soup = BeautifulSoup(html, "lxml")
        element = soup.find("div")
        assert isinstance(element, Tag)

        assert _is_non_content_element(element) is True

    def test_allows_content_elements(self) -> None:
        """Should allow elements without non-content patterns."""
        from bs4 import Tag

        from summarize_links.extract import _is_non_content_element

        html = '<div class="article-body">Content</div>'
        soup = BeautifulSoup(html, "lxml")
        element = soup.find("div")
        assert isinstance(element, Tag)

        assert _is_non_content_element(element) is False

    def test_handles_list_class_attribute(self) -> None:
        """Should handle class as list (multiple classes)."""
        from bs4 import Tag

        from summarize_links.extract import _is_non_content_element

        html = '<div class="main-content sidebar-toggle">Content</div>'
        soup = BeautifulSoup(html, "lxml")
        element = soup.find("div")
        assert isinstance(element, Tag)

        # Should detect "sidebar" pattern
        assert _is_non_content_element(element) is True


class TestFetchAndExtract:
    """Tests for high-level fetch and extract functions."""

    def test_fetch_and_extract_returns_content_and_title(self, mocker: MockerFixture) -> None:
        """Should return extracted content and title."""
        from summarize_links.extract import fetch_and_extract

        mock_html = """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <article>
                    <p>This is the main content of the article. It contains enough
                    text to pass the minimum threshold for content extraction. The
                    article discusses various topics that are interesting to read.</p>
                </article>
            </body>
        </html>
        """
        mocker.patch("summarize_links.extract.fetch_html", return_value=mock_html)

        content, title = fetch_and_extract("https://example.com/article")

        assert "main content" in content
        assert title == "Test Page"

    def test_fetch_and_extract_metadata_for_html(self, mocker: MockerFixture) -> None:
        """Should extract full metadata from HTML pages."""
        from summarize_links.extract import fetch_and_extract_metadata

        mock_html = """
        <html>
            <head>
                <title>Article Title | Site Name</title>
                <meta name="author" content="Jane Doe">
                <meta property="og:description" content="Article description">
            </head>
            <body>
                <article>
                    <p>This is substantial article content that passes the minimum
                    threshold for extraction. It needs to be at least 200 characters
                    to be considered valid content by the extraction algorithm.</p>
                </article>
            </body>
        </html>
        """
        mocker.patch(
            "summarize_links.extract.fetch_content",
            return_value=(mock_html, "html"),
        )

        metadata = fetch_and_extract_metadata("https://example.com/article")

        assert metadata.title == "Article Title"
        assert metadata.author == "Jane Doe"
        assert metadata.description == "Article description"
        assert metadata.domain == "example.com"

    def test_fetch_and_extract_metadata_for_markdown(self, mocker: MockerFixture) -> None:
        """Should extract metadata from markdown files."""
        from summarize_links.extract import fetch_and_extract_metadata

        mock_markdown = """# Markdown Article

_Author Name, 2025_

This is the content of the markdown article. It contains enough text to be
meaningful and useful for summarization purposes.
"""
        mocker.patch(
            "summarize_links.extract.fetch_content",
            return_value=(mock_markdown, "markdown"),
        )

        metadata = fetch_and_extract_metadata("https://example.com/article.md")

        assert metadata.title == "Markdown Article"
        assert metadata.author == "Author Name"
        assert "content of the markdown" in metadata.content

    def test_fetch_and_extract_truncates_long_content(self, mocker: MockerFixture) -> None:
        """Should truncate content that exceeds max length."""
        from summarize_links.extract import fetch_and_extract

        # Create content that will exceed truncation limit
        long_paragraph = "This is a sentence. " * 5000  # ~100k chars
        mock_html = f"""
        <html>
            <head><title>Long Article</title></head>
            <body><article><p>{long_paragraph}</p></article></body>
        </html>
        """
        mocker.patch("summarize_links.extract.fetch_html", return_value=mock_html)

        content, _ = fetch_and_extract("https://example.com/long")

        # Should be truncated to max length + truncation message
        assert len(content) < 60000
        assert "[Content truncated...]" in content


class TestGarbledContentDetection:
    """Tests for detecting garbled/corrupted content during extraction."""

    def test_detects_high_ratio_non_ascii(self) -> None:
        """Should detect content with high ratio of non-ASCII characters."""
        # Create text with 50% non-ASCII characters
        garbled = "abc" + "".join(chr(i) for i in range(200, 300)) * 10
        assert _is_content_garbled(garbled) is True

    def test_detects_base64_like_content(self) -> None:
        """Should detect content that looks like base64 encoding."""
        # Create a long base64-like string (continuous alphanumeric)
        base64_like = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/" * 3
        assert _is_content_garbled(base64_like) is True

    def test_allows_normal_text(self) -> None:
        """Should not flag normal text content."""
        normal = (
            """This is a normal article with regular text content.
        It contains multiple sentences and paragraphs.
        The content is readable and makes sense.
        """
            * 5
        )
        assert _is_content_garbled(normal) is False

    def test_allows_moderate_unicode(self) -> None:
        """Should allow text with moderate amounts of Unicode."""
        text_with_unicode = (
            """This article discusses café culture in München.
        It mentions the naïve approach to résumé writing.
        The Zürich office has a unique approach to business.
        """
            * 10
        )
        assert _is_content_garbled(text_with_unicode) is False

    def test_short_text_not_checked(self) -> None:
        """Should not flag short text (< 100 chars) even if garbled."""
        short_garbled = "".join(chr(i) for i in range(200, 250))
        assert _is_content_garbled(short_garbled) is False

    def test_threshold_parameter(self) -> None:
        """Should respect custom threshold parameter."""
        # Content with 15% non-ASCII (using spaces to break up any base64-like pattern)
        mixed = ("This is normal text. " * 8) + "".join(chr(i) for i in range(200, 230))
        # Default threshold (0.3) should pass (15% unusual)
        assert _is_content_garbled(mixed, threshold=0.3) is False
        # Lower threshold (0.1) should fail (15% > 10%)
        assert _is_content_garbled(mixed, threshold=0.1) is True
