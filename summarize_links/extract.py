"""
Web content extraction module.

This module handles:
- Fetching HTML content from URLs
- Extracting readable content from HTML pages
- Cleaning and truncating content for AI summarization
"""

import logging
import re

import requests
from bs4 import BeautifulSoup, Tag

from summarize_links.config import MAX_CONTENT_LENGTH, REQUEST_TIMEOUT
from summarize_links.exceptions import ContentExtractionError, ContentFetchError

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
NON_CONTENT_PATTERNS = [
    r"nav",
    r"menu",
    r"sidebar",
    r"footer",
    r"header",
    r"comment",
    r"ad(vert)?",
    r"social",
    r"share",
    r"related",
    r"recommend",
    r"popup",
    r"modal",
    r"cookie",
    r"banner",
]


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
    logger.debug(f"Fetching URL: {url}")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()

        # Check content type is HTML
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower() and "text" not in content_type.lower():
            raise ContentFetchError(f"URL returned non-HTML content type: {content_type}")

        logger.info(f"Fetched {len(response.text)} characters from {url}")
        return response.text

    except requests.exceptions.Timeout:
        raise ContentFetchError(f"Request timed out after {timeout}s: {url}") from None
    except requests.exceptions.ConnectionError as e:
        raise ContentFetchError(f"Connection error for {url}: {e}") from e
    except requests.exceptions.HTTPError as e:
        raise ContentFetchError(f"HTTP error {e.response.status_code} for {url}") from e
    except requests.exceptions.RequestException as e:
        raise ContentFetchError(f"Request failed for {url}: {e}") from e


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
    try:
        # Parse HTML with lxml for speed
        soup = BeautifulSoup(html, "lxml")

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

        # Remove non-content elements
        for tag_name in ELEMENTS_TO_REMOVE:
            for element in soup.find_all(tag_name):
                element.decompose()

        # Remove elements with non-content class/id patterns
        for element in soup.find_all(True):
            if _is_non_content_element(element):
                element.decompose()

        # Try to extract article content
        content = _extract_article_content(soup)

        # Fallback to largest text block
        if not content:
            logger.debug("No article found, falling back to largest text block")
            content = _find_largest_text_block(soup)

        if not content:
            raise ContentExtractionError("No readable content found in page")

        # Clean up whitespace
        content = _clean_text(content)

        logger.info(f"Extracted {len(content)} characters of content")
        return content, title

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
