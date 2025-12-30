"""
Metadata extraction module.

This module handles extracting metadata from web pages:
- Title (Open Graph, Twitter cards, title tag)
- Author (meta tags, JSON-LD structured data)
- Description, publication date, site name
- Tags and keywords (meta tags, content hashtags)
- Markdown metadata extraction
"""

import json
import logging
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from summarize_links.exceptions import ContentExtractionError
from summarize_links.extract.html_parsing import extract_readable_content
from summarize_links.models import PageMetadata

__all__ = [
    "extract_page_metadata",
    # Private functions exported for tests
    "_extract_article_tags",
    "_extract_author",
    "_extract_description",
    "_extract_markdown_metadata",
    "_extract_published_date",
    "_extract_site_name",
    "_extract_title",
]

# Configure module logger
logger = logging.getLogger(__name__)


def _extract_meta_content(soup: BeautifulSoup, *selectors: str) -> str | None:
    """
    Extract content from the first matching meta tag.

    Args:
        soup: Parsed HTML document.
        selectors: CSS selectors to try in order.

    Returns:
        Meta tag content if found, None otherwise.
    """
    for selector in selectors:
        meta = soup.select_one(selector)
        if meta:
            content = meta.get("content")
            if content and isinstance(content, str) and content.strip():
                return content.strip()
    return None


def _extract_title(soup: BeautifulSoup) -> str:
    """
    Extract the best available title from the page.

    Priority: og:title > twitter:title > <title> tag

    Args:
        soup: Parsed HTML document.

    Returns:
        Page title, or "Untitled" if not found.
    """
    # Try Open Graph title first
    og_title = _extract_meta_content(
        soup,
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
    )
    if og_title:
        return og_title

    # Fall back to title tag
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)
        # Clean up title (remove site name suffix)
        for separator in [" | ", " - ", " — ", " · "]:
            if separator in title:
                title = title.split(separator)[0].strip()
                break
        if title:
            return title

    return "Untitled"


def _extract_author(soup: BeautifulSoup) -> str | None:
    """
    Extract author information from meta tags.

    Args:
        soup: Parsed HTML document.

    Returns:
        Author name if found, None otherwise.
    """
    # Try various author meta tags
    author = _extract_meta_content(
        soup,
        'meta[name="author"]',
        'meta[property="article:author"]',
        'meta[name="twitter:creator"]',
        'meta[property="og:article:author"]',
    )
    if author:
        return author

    # Try schema.org author in JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                author_data = data.get("author")
                if isinstance(author_data, str):
                    return author_data
                if isinstance(author_data, dict):
                    return author_data.get("name")
                if isinstance(author_data, list) and author_data:
                    first_author = author_data[0]
                    if isinstance(first_author, str):
                        return first_author
                    if isinstance(first_author, dict):
                        return first_author.get("name")
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue

    return None


def _extract_description(soup: BeautifulSoup) -> str | None:
    """
    Extract page description from meta tags.

    Args:
        soup: Parsed HTML document.

    Returns:
        Description if found, None otherwise.
    """
    return _extract_meta_content(
        soup,
        'meta[property="og:description"]',
        'meta[name="description"]',
        'meta[name="twitter:description"]',
    )


def _extract_published_date(soup: BeautifulSoup) -> str | None:
    """
    Extract publication date from meta tags.

    Args:
        soup: Parsed HTML document.

    Returns:
        Publication date string if found, None otherwise.
    """
    date = _extract_meta_content(
        soup,
        'meta[property="article:published_time"]',
        'meta[name="publication_date"]',
        'meta[name="date"]',
        'meta[property="og:published_time"]',
    )
    if date:
        # Normalize to YYYY-MM-DD if it's ISO format
        if "T" in date:
            date = date.split("T")[0]
        return date
    return None


def _extract_site_name(soup: BeautifulSoup) -> str | None:
    """
    Extract site name from meta tags.

    Args:
        soup: Parsed HTML document.

    Returns:
        Site name if found, None otherwise.
    """
    return _extract_meta_content(soup, 'meta[property="og:site_name"]')


def _extract_article_tags(soup: BeautifulSoup, content: str) -> list[str]:
    """
    Extract tags/keywords from meta tags and content.

    Args:
        soup: Parsed HTML document.
        content: Extracted text content.

    Returns:
        List of tags found.
    """
    tags: list[str] = []
    seen: set[str] = set()

    def add_tag(tag: str) -> None:
        """Add a tag if not seen before."""
        tag_lower = tag.lower().strip()
        if tag_lower and tag_lower not in seen and len(tag_lower) < 50:
            seen.add(tag_lower)
            tags.append(tag.strip())

    # Extract from keywords meta tag
    keywords = _extract_meta_content(soup, 'meta[name="keywords"]')
    if keywords:
        for keyword in keywords.split(","):
            add_tag(keyword)

    # Extract from article:tag meta tags (can have multiple)
    for meta in soup.select('meta[property="article:tag"]'):
        content_val = meta.get("content")
        if content_val and isinstance(content_val, str):
            add_tag(content_val)

    # Extract hashtags from article content
    # Pattern matches #tag but not URLs or headers
    hashtag_pattern = re.compile(r"(?<!\S)#([a-zA-Z][a-zA-Z0-9_-]{1,30})(?!\S)")
    for match in hashtag_pattern.finditer(content):
        add_tag(match.group(1))

    logger.debug(f"Extracted {len(tags)} article tags")
    return tags


def extract_page_metadata(html: str, url: str) -> PageMetadata:
    """
    Extract metadata from an HTML page.

    Extracts title, author, description, publication date, tags,
    and readable content from the page.

    Args:
        html: Raw HTML string.
        url: Source URL (used for domain extraction).

    Returns:
        PageMetadata object with extracted information.

    Raises:
        ContentExtractionError: If extraction fails.
    """
    try:
        soup = BeautifulSoup(html, "lxml")

        # Extract metadata before removing elements
        title = _extract_title(soup)
        author = _extract_author(soup)
        description = _extract_description(soup)
        published_date = _extract_published_date(soup)
        site_name = _extract_site_name(soup)

        # Extract domain from URL
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.replace("www.", "")

        # Now extract content (this modifies the soup)
        content, _ = extract_readable_content(html)

        # Extract tags from original soup (before content extraction modified it)
        soup_fresh = BeautifulSoup(html, "lxml")
        article_tags = _extract_article_tags(soup_fresh, content)

        logger.info(
            f"Extracted metadata: title='{title}', author={author}, tags={len(article_tags)}"
        )

        return PageMetadata(
            title=title,
            domain=domain,
            content=content,
            author=author,
            description=description,
            published_date=published_date,
            site_name=site_name,
            article_tags=article_tags,
        )

    except ContentExtractionError:
        raise
    except Exception as e:
        raise ContentExtractionError(f"Failed to extract metadata: {e}") from e


def _extract_markdown_metadata(content: str, url: str) -> PageMetadata:
    """
    Extract metadata from a raw Markdown file.

    Attempts to extract title from first H1 heading.
    Returns the markdown content as-is (already readable).

    Args:
        content: Raw markdown content.
        url: Source URL for domain extraction.

    Returns:
        PageMetadata object.
    """
    # Extract domain from URL
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.replace("www.", "")

    # Try to extract title from first H1 heading
    title = "Untitled"
    h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if h1_match:
        title = h1_match.group(1).strip()

    # Try to extract author from italic line near the top (common pattern)
    # Look for short italic lines that look like author attribution
    author = None
    # Find all italic lines in first 2000 chars
    italic_matches = re.findall(r"^_([^_]+)_$", content[:2000], re.MULTILINE)
    for italic_text in italic_matches:
        # Skip long lines (likely descriptions)
        if len(italic_text) > 100:
            continue
        # If it contains a comma and looks like "Name, Date"
        if "," in italic_text:
            parts = italic_text.split(",")
            # First part should be short (name) and second part looks like a date
            if len(parts[0].strip()) < 50:
                author = parts[0].strip()
                break

    # Clean up the content (remove image tags, etc.)
    from summarize_links.extract.html_parsing import _clean_markdown

    cleaned_content = _clean_markdown(content)

    logger.info(f"Extracted metadata from markdown: title='{title}', author={author}")

    return PageMetadata(
        title=title,
        domain=domain,
        content=cleaned_content,
        author=author,
        description=None,
        published_date=None,
        site_name=None,
        article_tags=[],
    )
