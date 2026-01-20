"""
Data models for the summarization pipeline.

This module defines dataclasses for passing structured data between
components: URL extraction, web scraping, AI summarization, and note writing.
"""

from dataclasses import dataclass, field
from typing import Any

from summarize_links.config import DEFAULT_MAX_TAGS

__all__ = [
    # Data classes
    "UrlWithContext",
    "PageMetadata",
    "SummaryResult",
    # Constants
    "CONTENT_TYPES",
    "CONTENT_TYPE_DESCRIPTIONS",
    # Tag utilities
    "normalize_tag",
    "merge_tags",
]


@dataclass
class UrlWithContext:
    """
    A URL extracted from a daily note with its surrounding context.

    Captures hashtags and text from the same line as the URL,
    preserving user intent and categorization.

    Attributes:
        url: The cleaned URL (tracking params removed, normalized).
        original_url: The URL exactly as it appears in the note (for removal).
        tags: Hashtags found on the same line (without # prefix).
        context_text: The full line text for reference.
        source_note: Optional filename of the daily note this URL came from.
        source_date: Optional date from the source daily note (for summary filename).
    """

    url: str
    original_url: str = ""  # Populated by extract_urls_with_context
    tags: list[str] = field(default_factory=list)
    context_text: str = ""
    source_note: str | None = None  # For batch processing from multiple notes
    source_date: str | None = None  # ISO format: YYYY-MM-DD


@dataclass
class PageMetadata:
    """
    Metadata extracted from a web page's HTML.

    Contains structured information from meta tags, Open Graph,
    and schema.org markup for building rich frontmatter.

    Attributes:
        title: Page title from <title> or og:title.
        author: Author name if available.
        description: Page description from meta or og:description.
        published_date: Publication date if available (ISO format string).
        domain: Domain name extracted from URL.
        site_name: Site name from og:site_name.
        article_tags: Tags/keywords from meta tags or content.
        content: The main readable text content.
        fetch_method: Method used to fetch content ("http" or "playwright").
        http_error_category: Category of HTTP error if fallback occurred.
    """

    title: str
    domain: str
    content: str
    author: str | None = None
    description: str | None = None
    published_date: str | None = None
    site_name: str | None = None
    article_tags: list[str] = field(default_factory=list)
    # Fetch metadata for observability
    fetch_method: str = "http"
    http_error_category: str | None = None


@dataclass
class SummaryResult:
    """
    Result from Gemini summarization.

    Contains the AI-generated summary along with suggested
    categorization for the content.

    Attributes:
        content: Markdown-formatted summary text.
        suggested_tags: AI-suggested topic tags (3-5 typically).
        content_type: Classification of content type.
        usage_details: Token usage details (input, output, total).
        system_prompt: The system instructions/prompt (for tracing).
        raw_prompt: The raw user prompt sent to the LLM (for tracing).
        raw_response: The raw response from the LLM (for tracing).
        prompt_metadata: Langfuse prompt info (names, versions) if using managed prompts.
    """

    content: str
    suggested_tags: list[str] = field(default_factory=list)
    content_type: str = "article"
    usage_details: dict[str, int] | None = None
    system_prompt: str | None = None
    raw_prompt: str | None = None
    raw_response: str | None = None
    prompt_metadata: dict[str, Any] | None = None


# Valid content types for classification with descriptions
# The descriptions are used in the Gemini prompt to explain each type
CONTENT_TYPE_DESCRIPTIONS: dict[str, str] = {
    "article": "news, opinion, analysis",
    "tutorial": "how-to, guide, walkthrough",
    "documentation": "API docs, reference material",
    "news": "current events, announcements",
    "video": "video content transcripts",
    "tool": "software, service, product pages",
    "reference": "lists, comparisons, resources",
    "blog": "personal posts, informal writing",
    "research": "academic papers, studies",
    "other": "if none of the above fit",
}

# Frozenset of valid content type keys for validation
CONTENT_TYPES = frozenset(CONTENT_TYPE_DESCRIPTIONS.keys())


def normalize_tag(tag: str) -> str:
    """
    Normalize a tag to a consistent format.

    Converts to lowercase, replaces spaces with hyphens,
    removes special characters, and strips # prefix.

    Args:
        tag: Raw tag string.

    Returns:
        Normalized tag string.
    """
    # Remove # prefix if present
    tag = tag.lstrip("#")

    # Lowercase
    tag = tag.lower()

    # Replace spaces and underscores with hyphens
    tag = tag.replace(" ", "-").replace("_", "-")

    # Remove non-alphanumeric characters except hyphens
    tag = "".join(c for c in tag if c.isalnum() or c == "-")

    # Collapse multiple hyphens
    while "--" in tag:
        tag = tag.replace("--", "-")

    # Strip leading/trailing hyphens
    tag = tag.strip("-")

    return tag


def merge_tags(
    user_tags: list[str],
    article_tags: list[str],
    ai_tags: list[str],
    default_tags: list[str] | None = None,
    max_tags: int = DEFAULT_MAX_TAGS,
) -> list[str]:
    """
    Merge tags from multiple sources with deduplication.

    Priority order (earlier sources win for deduplication):
    1. User tags (from daily note)
    2. Article tags (from HTML)
    3. AI-suggested tags (from Gemini)

    Default tags are always included first.

    Args:
        user_tags: Tags from the user's daily note.
        article_tags: Tags from HTML meta/content.
        ai_tags: Tags suggested by Gemini.
        default_tags: Tags to always include (e.g., ["summarized"]).
        max_tags: Maximum number of tags to return.

    Returns:
        Merged, deduplicated, normalized list of tags.
    """
    seen: set[str] = set()
    result: list[str] = []

    # Process in priority order
    all_sources = [
        default_tags or [],
        user_tags,
        article_tags,
        ai_tags,
    ]

    for source in all_sources:
        for tag in source:
            normalized = normalize_tag(tag)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)

                if len(result) >= max_tags:
                    return result

    return result
