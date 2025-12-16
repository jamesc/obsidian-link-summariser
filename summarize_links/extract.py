"""
Web content extraction module.

This module handles:
- Fetching HTML content from URLs
- Extracting readable content from HTML pages
- Extracting metadata (title, author, tags) from HTML
- Cleaning and truncating content for AI summarization
"""

import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

from summarize_links.config import MAX_CONTENT_LENGTH, REQUEST_TIMEOUT
from summarize_links.exceptions import ContentExtractionError, ContentFetchError
from summarize_links.models import PageMetadata

# Configure module logger
logger = logging.getLogger(__name__)

# ----- Constants -----

# User agent to identify as a legitimate browser (some sites block default requests)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Elements to remove from HTML (non-content elements)
ELEMENTS_TO_REMOVE = [
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "aside",
    "noscript",
    "iframe",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "svg",
    "canvas",
    "video",
    "audio",
    "ad",
    "advertisement",
]

# Class/ID patterns that typically contain non-content
# Use word boundaries or more specific patterns to avoid false positives
NON_CONTENT_PATTERNS = [
    r"\bnav\b",
    r"\bmenu\b",
    r"\bsidebar\b",
    r"\bfooter\b",
    r"\bheader\b",
    r"\bcomment",
    r"\badvert",
    r"\bad-",
    r"\bads\b",
    r"\bsocial\b",
    r"\bshare\b",
    r"\brelated\b",
    r"\brecommend",
    r"\bpopup\b",
    r"\bmodal\b",
    r"\bcookie",
    r"\bbanner\b",
]


def fetch_content(url: str, timeout: int = REQUEST_TIMEOUT) -> tuple[str, str]:
    """
    Fetch content from a URL and return content with its type.

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (content, content_type) where content_type is 'html', 'markdown', or 'text'.

    Raises:
        ContentFetchError: If the request fails.
    """
    logger.debug(f"Fetching URL: {url}")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "text/markdown,text/plain;q=0.8,*/*;q=0.7"
        ),
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        # Determine content type
        content_type_header = response.headers.get("Content-Type", "").lower()

        # Check for markdown (by content-type or URL extension)
        if "markdown" in content_type_header or url.lower().endswith(".md"):
            logger.info(f"Fetched {len(response.text)} chars of markdown from {url}")
            return response.text, "markdown"

        # Check for HTML or text
        if "html" in content_type_header or "text" in content_type_header:
            logger.info(f"Fetched {len(response.text)} characters from {url}")
            return response.text, "html"

        raise ContentFetchError(f"URL returned unsupported content type: {content_type_header}")

    except requests.exceptions.Timeout:
        raise ContentFetchError(f"Request timed out after {timeout}s: {url}") from None
    except requests.exceptions.ConnectionError as e:
        raise ContentFetchError(f"Connection error for {url}: {e}") from e
    except requests.exceptions.HTTPError as e:
        raise ContentFetchError(f"HTTP error {e.response.status_code} for {url}") from e
    except requests.exceptions.RequestException as e:
        raise ContentFetchError(f"Request failed for {url}: {e}") from e


def fetch_html(url: str, timeout: int = REQUEST_TIMEOUT) -> str:
    """
    Fetch HTML content from a URL.

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        HTML content as string.

    Raises:
        ContentFetchError: If the request fails.
    """
    content, _ = fetch_content(url, timeout)
    return content


def _is_non_content_element(element: Tag) -> bool:
    """
    Check if an element is likely to be non-content based on class/id.

    Args:
        element: BeautifulSoup Tag element.

    Returns:
        True if element is likely non-content.
    """
    # Get class and id attributes
    classes = element.get("class", [])
    if isinstance(classes, str):
        classes = [classes]
    element_id = element.get("id", "")

    # Combine for checking
    attrs_to_check = " ".join(classes) + " " + str(element_id)
    attrs_lower = attrs_to_check.lower()

    # Check against non-content patterns
    return any(re.search(pattern, attrs_lower) for pattern in NON_CONTENT_PATTERNS)


def _extract_article_content(soup: BeautifulSoup) -> str | None:
    """
    Try to extract content from article-like elements.

    Args:
        soup: Parsed HTML document.

    Returns:
        Article text if found, None otherwise.
    """
    # Try standard article tags first
    article_selectors = [
        "article",
        '[role="main"]',
        '[role="article"]',
        ".post-content",
        ".article-content",
        ".entry-content",
        ".content-body",
        "#content",
        ".content",
        "main",
    ]

    for selector in article_selectors:
        elements = soup.select(selector)
        for element in elements:
            if not _is_non_content_element(element):
                text = element.get_text(separator="\n", strip=True)
                if len(text) > 200:  # Minimum content threshold
                    logger.debug(f"Found article content via selector: {selector}")
                    return text

    return None


def _find_largest_text_block(soup: BeautifulSoup) -> str:
    """
    Find the largest text block in the document as fallback.

    Args:
        soup: Parsed HTML document.

    Returns:
        Text from the largest content block.
    """
    # Find all paragraph and div elements
    candidates: list[tuple[int, str]] = []

    for tag in soup.find_all(["p", "div", "section"]):
        if _is_non_content_element(tag):
            continue

        text = tag.get_text(separator="\n", strip=True)
        if len(text) > 100:  # Minimum threshold
            candidates.append((len(text), text))

    if candidates:
        # Sort by length, return longest
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    # Ultimate fallback: body text
    body = soup.find("body")
    if body:
        return body.get_text(separator="\n", strip=True)

    return ""


def extract_readable_content(html: str) -> tuple[str, str | None]:
    """
    Extract readable text content from HTML.

    Removes navigation, ads, and other non-content elements,
    then extracts the main article or largest text block.

    Args:
        html: Raw HTML string.

    Returns:
        Tuple of (extracted_text, page_title).

    Raises:
        ContentExtractionError: If extraction fails.
    """
    # Try lxml parser first (faster), fall back to html5lib for malformed HTML
    for parser in ["lxml", "html5lib"]:
        try:
            content, title = _extract_with_parser(html, parser)
            if content:
                return content, title
        except ContentExtractionError:
            if parser == "html5lib":
                raise
            logger.debug(f"Parser '{parser}' failed, trying fallback")
            continue

    raise ContentExtractionError("No readable content found in page")


def _extract_with_parser(html: str, parser: str) -> tuple[str | None, str | None]:
    """
    Extract content using a specific parser.

    Args:
        html: Raw HTML string.
        parser: BeautifulSoup parser to use ('lxml' or 'html5lib').

    Returns:
        Tuple of (extracted_text, page_title). Text may be None if not found.

    Raises:
        ContentExtractionError: If extraction fails critically.
    """
    try:
        soup = BeautifulSoup(html, parser)

        # Extract title before removing elements
        title = None
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
            # Clean up title (remove site name suffix if present)
            if " | " in title:
                title = title.split(" | ")[0]
            elif " - " in title:
                title = title.split(" - ")[0]

        # Try to extract article content FIRST, before any removal.
        # This prevents losing content nested in unusual structures
        # (e.g., article inside nav/header).
        content = _extract_article_content(soup)

        if content:
            # Found article content - clean and return it
            content = _clean_text(content)
            logger.info(
                f"Extracted {len(content)} chars from article (parser={parser})"
            )
            return content, title

        # No article found - do aggressive cleanup and try largest text block
        logger.debug(f"No article found with {parser}, performing aggressive cleanup")

        # Remove non-content elements
        for tag_name in ELEMENTS_TO_REMOVE:
            for element in soup.find_all(tag_name):
                element.decompose()

        # Remove elements with non-content class/id patterns
        # Use list() to take a snapshot - decompose() modifies the tree during iteration
        # Critical elements that should never be removed even if they match patterns
        protected_tags = {"html", "body", "article", "main"}
        for element in list(soup.find_all(True)):
            # Skip elements already removed (orphaned when parent was decomposed)
            if element.parent is None:
                continue
            # Never remove critical structural elements
            if element.name in protected_tags:
                continue
            if _is_non_content_element(element):
                element.decompose()

        # Fall back to largest text block
        content = _find_largest_text_block(soup)

        if content:
            content = _clean_text(content)
            logger.info(
                f"Extracted {len(content)} chars from text block (parser={parser})"
            )
            return content, title

        # No content found with this parser
        return None, title

    except Exception as e:
        if isinstance(e, ContentExtractionError):
            raise
        raise ContentExtractionError(f"Failed to extract content: {e}") from e


def _clean_text(text: str) -> str:
    """
    Clean extracted text by normalizing whitespace.

    Args:
        text: Raw extracted text.

    Returns:
        Cleaned text.
    """
    # Replace multiple newlines with double newline (paragraph break)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Replace multiple spaces with single space
    text = re.sub(r" {2,}", " ", text)

    # Remove leading/trailing whitespace from lines
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()


def truncate_content(content: str, max_length: int = MAX_CONTENT_LENGTH) -> str:
    """
    Truncate content to maximum length, preferring to break at paragraph.

    Args:
        content: Text content to truncate.
        max_length: Maximum length in characters.

    Returns:
        Truncated content.
    """
    if len(content) <= max_length:
        return content

    # Try to break at a paragraph boundary
    truncated = content[:max_length]
    last_para = truncated.rfind("\n\n")

    if last_para > max_length // 2:
        truncated = truncated[:last_para]
    else:
        # Break at sentence boundary
        last_sentence = max(
            truncated.rfind(". "),
            truncated.rfind("! "),
            truncated.rfind("? "),
        )
        if last_sentence > max_length // 2:
            truncated = truncated[: last_sentence + 1]

    logger.debug(f"Truncated content from {len(content)} to {len(truncated)} chars")
    return truncated + "\n\n[Content truncated...]"


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
            import json

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


def fetch_and_extract(url: str) -> tuple[str, str | None]:
    """
    Fetch a URL and extract readable content.

    This is the main entry point combining fetch and extraction.

    Args:
        url: URL to fetch and extract content from.

    Returns:
        Tuple of (extracted_content, page_title).

    Raises:
        ContentFetchError: If fetching fails.
        ContentExtractionError: If extraction fails.
    """
    html = fetch_html(url)
    content, title = extract_readable_content(html)
    content = truncate_content(content)
    return content, title


def fetch_and_extract_metadata(url: str) -> PageMetadata:
    """
    Fetch a URL and extract full metadata including content.

    This is the enhanced entry point that returns structured metadata.
    Content is automatically truncated to MAX_CONTENT_LENGTH.
    Supports both HTML pages and raw Markdown files.

    Args:
        url: URL to fetch and extract from.

    Returns:
        PageMetadata object with all extracted information.

    Raises:
        ContentFetchError: If fetching fails.
        ContentExtractionError: If extraction fails.
    """
    content, content_type = fetch_content(url)

    if content_type == "markdown":
        # For markdown files, extract metadata from the content itself
        metadata = _extract_markdown_metadata(content, url)
    else:
        # For HTML, use the full extraction pipeline
        metadata = extract_page_metadata(content, url)

    # Truncate content
    metadata.content = truncate_content(metadata.content)

    return metadata


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
    import re

    # Extract domain from URL
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.replace("www.", "")

    # Try to extract title from first H1 heading
    title = "Untitled"
    h1_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if h1_match:
        title = h1_match.group(1).strip()

    # Try to extract author from italic line near the top (common pattern)
    # Look for short italic lines that look like author attribution
    author = None
    # Find all italic lines in first 2000 chars
    italic_matches = re.findall(r'^_([^_]+)_$', content[:2000], re.MULTILINE)
    for italic_text in italic_matches:
        # Skip long lines (likely descriptions)
        if len(italic_text) > 100:
            continue
        # If it contains a comma and looks like "Name, Date"
        if ',' in italic_text:
            parts = italic_text.split(',')
            # First part should be short (name) and second part looks like a date
            if len(parts[0].strip()) < 50:
                author = parts[0].strip()
                break

    # Clean up the content (remove image tags, etc.)
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


def _clean_markdown(content: str) -> str:
    """
    Clean markdown content for summarization.

    Removes image tags and other non-text elements.

    Args:
        content: Raw markdown content.

    Returns:
        Cleaned markdown text.
    """
    import re

    # Remove HTML image tags
    content = re.sub(r'<img[^>]*>', '', content)

    # Remove markdown image syntax
    content = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', content)

    # Clean up multiple blank lines
    content = re.sub(r'\n{3,}', '\n\n', content)

    return content.strip()
