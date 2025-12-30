"""
URL and hashtag extraction from Markdown content.

This module handles:
- Extracting URLs from Markdown links and bare URLs
- Extracting hashtags from text lines
- Cleaning tracking parameters from URLs
- Generating URL-safe slugs for filenames
"""

import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from summarize_links.exceptions import URLExtractionError
from summarize_links.models import UrlWithContext

__all__ = [
    "clean_url",
    "extract_hashtags_from_line",
    "extract_urls",
    "extract_urls_with_context",
]

# Configure module logger
logger = logging.getLogger(__name__)

# ----- URL Extraction Patterns -----
# Pattern to match Markdown links: [text](url)
MARKDOWN_LINK_PATTERN = r"\[([^\]]+)\]\((https?://[^)]+)\)"

# Pattern to match bare URLs (not inside Markdown link syntax)
# Matches http:// or https:// followed by non-whitespace, non-bracket characters
BARE_URL_PATTERN = r"(?<!\()(https?://[^\s\[\]()]+)(?!\))"

# Combined pattern for extraction
URL_PATTERN = re.compile(rf"{MARKDOWN_LINK_PATTERN}|{BARE_URL_PATTERN}", re.IGNORECASE)

# Pattern to match hashtags (Obsidian-style tags)
# Matches #tag but not ## headers or # in URLs
HASHTAG_PATTERN = re.compile(r"(?<!\S)#([a-zA-Z][a-zA-Z0-9_-]*)", re.UNICODE)

# ----- URL Cleaning -----
# Query parameters to strip (tracking, analytics, etc.)
TRACKING_PARAMS = {
    # UTM tracking (Google Analytics)
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    # Social/referrer tracking
    "ref",
    "ref_src",
    "ref_url",
    "source",
    "fbclid",  # Facebook
    "gclid",  # Google Ads
    "msclkid",  # Microsoft Ads
    "twclid",  # Twitter
    "igshid",  # Instagram
    # Mobile/app tracking
    "m",  # Blogspot mobile
    # Session/paywall tokens
    "st",
    "token",
    # Misc
    "share",
    "s",  # Some sharing params
}

# Fragments to strip (RSS noise, etc.)
NOISE_FRAGMENTS = {
    "atom-everything",
    "rss",
}

# Domains where certain params are meaningful and should be kept
MEANINGFUL_PARAMS = {
    "youtube.com": {"v", "t", "list", "index"},
    "youtu.be": {"t"},
    "github.com": {"tab", "q"},
    "twitter.com": {"s"},  # Tweet ID context
    "x.com": {"s"},
}


def clean_url(url: str) -> str:
    """
    Clean tracking parameters and noise from a URL.

    Removes:
    - UTM and other tracking parameters
    - Mobile/app parameters
    - Session tokens
    - RSS feed fragment noise

    Preserves:
    - Essential parameters (YouTube video ID, GitHub tab, etc.)
    - Meaningful fragments (GitHub issue comments, etc.)

    Args:
        url: URL to clean.

    Returns:
        Cleaned URL with tracking removed.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")

        # Get meaningful params for this domain
        keep_params = MEANINGFUL_PARAMS.get(domain, set())

        # Parse and filter query parameters
        if parsed.query:
            params = parse_qs(parsed.query, keep_blank_values=True)
            filtered_params = {}

            for key, values in params.items():
                key_lower = key.lower()
                # Keep if it's meaningful for this domain OR not a tracking param
                if key_lower in keep_params or key_lower not in TRACKING_PARAMS:
                    filtered_params[key] = values

            # Rebuild query string
            new_query = urlencode(filtered_params, doseq=True) if filtered_params else ""
        else:
            new_query = ""

        # Filter fragment
        new_fragment = parsed.fragment
        if new_fragment:
            fragment_lower = new_fragment.lower()
            # Strip noise fragments, but keep meaningful ones (like GitHub comments)
            if fragment_lower in NOISE_FRAGMENTS:
                new_fragment = ""
            # Keep fragments that look like anchors/comments (contain numbers or specific patterns)
            elif not any(c.isdigit() for c in new_fragment) and "comment" not in fragment_lower:
                # Generic fragment without numbers - might be noise
                # Keep it for now (could be a section anchor)
                pass

        # Rebuild URL
        cleaned = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                new_fragment,
            )
        )

        if cleaned != url:
            logger.debug(f"Cleaned URL: {url} -> {cleaned}")

        return cleaned

    except Exception as e:
        logger.warning(f"Failed to clean URL {url}: {e}")
        return url  # Return original on error


def extract_urls(content: str) -> list[str]:
    """
    Extract URLs from Markdown content.

    Extracts both:
    - URLs from Markdown links: [text](https://example.com)
    - Bare URLs: https://example.com

    Deduplicates URLs while preserving order of first occurrence.
    Cleans tracking parameters from URLs.

    Args:
        content: Markdown content to parse.

    Returns:
        List of unique cleaned URLs in order of first appearance.

    Raises:
        URLExtractionError: If URL extraction fails unexpectedly.
    """
    try:
        urls: list[str] = []
        seen: set[str] = set()

        # Find all matches
        for match in URL_PATTERN.finditer(content):
            # Group 2 is URL from Markdown link, Group 3 is bare URL
            url = match.group(2) or match.group(3)

            if not url:
                continue

            # Clean up URL (remove trailing punctuation that might have been captured)
            url = url.rstrip(".,;:")

            # Clean tracking parameters
            url = clean_url(url)

            if url not in seen:
                urls.append(url)
                seen.add(url)
                logger.debug(f"Extracted URL: {url}")

        logger.info(f"Extracted {len(urls)} unique URLs from content")
        return urls

    except Exception as e:
        raise URLExtractionError(f"Failed to extract URLs: {e}") from e


def extract_hashtags_from_line(line: str) -> list[str]:
    """
    Extract hashtags from a single line of text.

    Finds Obsidian-style tags like #ai, #machine-learning, etc.
    Does not include the # prefix in the returned tags.

    Args:
        line: Single line of text to parse.

    Returns:
        List of tag names (without # prefix).
    """
    tags = HASHTAG_PATTERN.findall(line)
    logger.debug(f"Found {len(tags)} hashtags in line: {tags}")
    return tags


def extract_urls_with_context(content: str) -> list[UrlWithContext]:
    """
    Extract URLs from Markdown content with surrounding context.

    For each URL found, captures:
    - The URL itself (cleaned of tracking params)
    - Any hashtags on the same line (user's categorization)
    - The full line text for reference

    Deduplicates URLs while preserving order of first occurrence.
    Cleans tracking parameters from URLs.

    Args:
        content: Markdown content to parse.

    Returns:
        List of UrlWithContext objects in order of first appearance.

    Raises:
        URLExtractionError: If URL extraction fails unexpectedly.
    """
    try:
        results: list[UrlWithContext] = []
        seen: set[str] = set()

        # Process line by line to capture context
        for line in content.split("\n"):
            # Find all URLs in this line
            for match in URL_PATTERN.finditer(line):
                # Group 2 is URL from Markdown link, Group 3 is bare URL
                url = match.group(2) or match.group(3)

                if not url:
                    continue

                # Clean up URL (remove trailing punctuation)
                url = url.rstrip(".,;:")

                # Store original URL before cleaning (for note removal)
                original_url = url

                # Clean tracking parameters
                url = clean_url(url)

                if url in seen:
                    continue

                seen.add(url)

                # Extract hashtags from the same line
                tags = extract_hashtags_from_line(line)

                result = UrlWithContext(
                    url=url,
                    original_url=original_url,
                    tags=tags,
                    context_text=line.strip(),
                )
                results.append(result)
                logger.debug(f"Extracted URL with context: {url} (tags: {tags})")

        logger.info(f"Extracted {len(results)} unique URLs with context")
        return results

    except Exception as e:
        raise URLExtractionError(f"Failed to extract URLs with context: {e}") from e
