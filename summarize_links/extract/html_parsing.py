"""
HTML parsing and content extraction module.

This module handles extracting readable text content from HTML pages:
- Removing navigation, ads, and other non-content elements
- Detecting and extracting article content
- Finding the largest text blocks as fallback
- Cleaning and normalizing text
- Truncating content for AI processing
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

from summarize_links.config import MAX_CONTENT_LENGTH
from summarize_links.exceptions import ContentExtractionError

__all__ = [
    "extract_readable_content",
    "truncate_content",
    # Private functions exported for tests
    "_clean_text",
    "_clean_markdown",
    "_extract_article_content",
    "_find_largest_text_block",
    "_is_content_garbled",
    "_is_non_content_element",
]

# Configure module logger
logger = logging.getLogger(__name__)

# ----- Constants -----

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


def _is_content_garbled(text: str, threshold: float = 0.3) -> bool:
    """
    Check if text content appears to be garbled or corrupted.

    Detects base64, binary data, or high ratio of non-printable/unusual characters.

    Args:
        text: Text content to check.
        threshold: Maximum ratio of unusual characters allowed (default 0.3).

    Returns:
        True if content appears garbled.
    """
    if not text or len(text) < 100:
        return False

    # Take a sample (first 2000 chars should be representative)
    sample = text[:2000]

    # Check if content looks like base64 (long sequences of alphanumeric + / + =)
    # Base64 has very long unbroken sequences
    is_base64_like = bool(re.search(r"[A-Za-z0-9+/]{100,}={0,2}", sample))
    if is_base64_like:
        return True

    # Count unusual characters
    unusual_count = 0
    for char in sample:
        # Count non-ASCII, non-printable, or rare Unicode characters
        if ord(char) > 127 or (ord(char) < 32 and char not in "\n\r\t"):
            unusual_count += 1

    ratio = unusual_count / len(sample)

    # Consider it garbled if high ratio of unusual characters
    return ratio > threshold


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


def _clean_markdown(content: str) -> str:
    """
    Clean markdown content for summarization.

    Removes image tags and other non-text elements.

    Args:
        content: Raw markdown content.

    Returns:
        Cleaned markdown text.
    """
    # Remove HTML image tags
    content = re.sub(r"<img[^>]*>", "", content)

    # Remove markdown image syntax
    content = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", content)

    # Clean up multiple blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()


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
            # Check if content appears garbled/corrupted
            if _is_content_garbled(content):
                logger.warning(f"Content appears garbled with {parser} parser")
                return None, title
            logger.info(f"Extracted {len(content)} chars from article (parser={parser})")
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
            # Check if content appears garbled/corrupted
            if _is_content_garbled(content):
                logger.warning(f"Content appears garbled with {parser} parser")
                return None, title
            logger.info(f"Extracted {len(content)} chars from text block (parser={parser})")
            return content, title

        # No content found with this parser
        return None, title

    except Exception as e:
        if isinstance(e, ContentExtractionError):
            raise
        raise ContentExtractionError(f"Failed to extract content: {e}") from e


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
