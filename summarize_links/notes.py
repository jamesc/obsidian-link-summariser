"""
Obsidian note parsing and writing module.

This module handles:
- Reading daily notes from an Obsidian vault
- Extracting URLs from Markdown content (both links and bare URLs)
- Writing formatted summary notes with frontmatter
- Generating URL-safe slugs for filenames
- Building rich frontmatter with metadata and tags
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TypedDict
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from summarize_links.config import DEFAULT_MAX_TAGS, MAX_SLUG_LENGTH
from summarize_links.exceptions import NoteReadError, NoteWriteError, URLExtractionError
from summarize_links.models import PageMetadata, SummaryResult, UrlWithContext, merge_tags

__all__ = [
    # URL extraction
    "extract_urls",
    "extract_urls_with_context",
    "extract_hashtags_from_line",
    "clean_url",
    # Daily note operations
    "find_daily_notes_with_urls",
    "read_daily_note",
    "add_summary_link_to_daily_note",
    "remove_url_line_from_note",
    # Summary note operations
    "write_summary_note_with_metadata",
    "write_stub_note",
    "summary_exists",
    "get_summary_filepath",
    "scan_summaries",
    # Utilities
    "build_frontmatter",
    "generate_slug",
    "slug_from_url",
    # Lower-level (for internal use)
    "write_summary_note",
]

# Configure module logger
logger = logging.getLogger(__name__)

# ----- URL Extraction Patterns -----
# Pattern to match Markdown links: [text](url)
MARKDOWN_LINK_PATTERN = r"\[([^\]]+)\]\((https?://[^)]+)\)"


class SummaryStats(TypedDict):
    """Statistics from scanning summary notes."""

    total: int
    success: int
    mocked: int
    error: int
    unknown: int
    oldest_date: str | None
    newest_date: str | None
    error_summaries: list[tuple[str, str]]
    mocked_summaries: list[tuple[str, str]]


# Pattern to match bare URLs (not inside Markdown link syntax)
# Matches http:// or https:// followed by non-whitespace, non-bracket characters
BARE_URL_PATTERN = r"(?<!\()(https?://[^\s\[\]()]+)(?!\))"

# Combined pattern for extraction
URL_PATTERN = re.compile(rf"{MARKDOWN_LINK_PATTERN}|{BARE_URL_PATTERN}", re.IGNORECASE)

# Pattern to match hashtags (Obsidian-style tags)
# Matches #tag but not ## headers or # in URLs
HASHTAG_PATTERN = re.compile(r"(?<!\S)#([a-zA-Z][a-zA-Z0-9_-]*)", re.UNICODE)

# Characters to replace in slugs
SLUG_REPLACEMENTS = {
    "/": "-",
    "\\": "-",
    ":": "-",
    " ": "-",
    "_": "-",
    ".": "-",
    "?": "",
    "&": "",
    "=": "",
    "#": "",
    "%": "",
}

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


def find_daily_notes_with_urls(
    vault_path: Path,
    daily_notes_folder: str = "",
) -> list[tuple[str, int]]:
    """
    Find all daily notes that contain URLs.

    Scans the daily notes folder for files matching the YYYY-MM-DD.md pattern
    and returns those that contain at least one URL.

    Args:
        vault_path: Path to the Obsidian vault root.
        daily_notes_folder: Subfolder for daily notes (can be empty).

    Returns:
        List of tuples (date_string, url_count) sorted by date descending.
        Date string is in YYYY-MM-DD format.
    """
    # Construct path to daily notes folder
    notes_path = vault_path / daily_notes_folder if daily_notes_folder else vault_path

    if not notes_path.exists():
        logger.warning(f"Daily notes folder not found: {notes_path}")
        return []

    # Pattern for daily note filenames: YYYY-MM-DD.md
    date_pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

    results: list[tuple[str, int]] = []

    for filepath in notes_path.glob("*.md"):
        match = date_pattern.match(filepath.name)
        if not match:
            continue

        date_str = match.group(1)

        try:
            content = filepath.read_text(encoding="utf-8")
            urls = extract_urls(content)
            if urls:
                results.append((date_str, len(urls)))
                logger.debug(f"Found {len(urls)} URLs in {filepath.name}")
        except OSError as e:
            logger.warning(f"Failed to read {filepath}: {e}")
            continue

    # Sort by date descending (newest first)
    results.sort(key=lambda x: x[0], reverse=True)

    logger.info(f"Found {len(results)} daily notes with URLs")
    return results


def read_daily_note(vault_path: Path, note_path: str, daily_notes_folder: str = "") -> str:
    """
    Read content from a daily note file.

    Args:
        vault_path: Path to the Obsidian vault root.
        note_path: Relative path to the note file (e.g., "2025-12-11.md").
        daily_notes_folder: Optional subfolder for daily notes (e.g., "Journal").

    Returns:
        The note content as a string.

    Raises:
        NoteReadError: If the note file cannot be read.
    """
    # Construct full path to note
    if daily_notes_folder:
        full_path = vault_path / daily_notes_folder / note_path
    else:
        full_path = vault_path / note_path

    logger.debug(f"Reading note from: {full_path}")

    if not full_path.exists():
        raise NoteReadError(f"Note file not found: {full_path}")

    if not full_path.is_file():
        raise NoteReadError(f"Path is not a file: {full_path}")

    try:
        content = full_path.read_text(encoding="utf-8")
        logger.info(f"Read {len(content)} characters from {note_path}")
        return content
    except OSError as e:
        raise NoteReadError(f"Failed to read note {full_path}: {e}") from e


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


def generate_slug(text: str) -> str:
    """
    Generate a URL-safe slug from text.

    Converts text to lowercase, replaces special characters,
    removes consecutive dashes, and limits length.

    Args:
        text: Text to convert to slug (typically a title or URL).

    Returns:
        URL-safe slug string.
    """
    # Start with lowercase
    slug = text.lower()

    # Apply character replacements
    for char, replacement in SLUG_REPLACEMENTS.items():
        slug = slug.replace(char, replacement)

    # Remove any remaining non-alphanumeric characters (except dashes)
    slug = re.sub(r"[^a-z0-9-]", "", slug)

    # Collapse multiple dashes into single dash
    slug = re.sub(r"-+", "-", slug)

    # Remove leading/trailing dashes
    slug = slug.strip("-")

    # Limit length
    if len(slug) > MAX_SLUG_LENGTH:
        # Try to cut at a word boundary (dash)
        truncated = slug[:MAX_SLUG_LENGTH]
        last_dash = truncated.rfind("-")
        slug = truncated[:last_dash] if last_dash > MAX_SLUG_LENGTH // 2 else truncated.rstrip("-")

    return slug


def slug_from_url(url: str) -> str:
    """
    Generate a slug from a URL.

    Uses the URL path and domain to create a meaningful slug.

    Args:
        url: URL to generate slug from.

    Returns:
        URL-safe slug string.
    """
    parsed = urlparse(url)

    # Use path if available, otherwise use domain
    if parsed.path and parsed.path != "/":
        # Remove file extension if present
        path = parsed.path.rstrip("/")
        if "." in path.split("/")[-1]:
            path = path.rsplit(".", 1)[0]
        slug_source = path
    else:
        # Use domain name
        slug_source = parsed.netloc.replace("www.", "")

    return generate_slug(slug_source)


def get_summary_filepath(
    vault_path: Path,
    out_folder: str,
    url: str,
    date: datetime | None = None,
) -> Path:
    """
    Generate the filepath for a summary note.

    Format: {out_folder}/{YYYY-MM-DD}-{slug}.md

    Args:
        vault_path: Path to the Obsidian vault root.
        out_folder: Folder name for summaries (relative to vault).
        url: URL being summarized.
        date: Date for the summary (defaults to today).

    Returns:
        Full path to the summary file.
    """
    if date is None:
        date = datetime.now()

    date_str = date.strftime("%Y-%m-%d")
    slug = slug_from_url(url)
    filename = f"{date_str}-{slug}.md"

    return vault_path / out_folder / filename


def summary_exists(
    vault_path: Path,
    out_folder: str,
    url: str,
    date: datetime | None = None,
) -> bool:
    """
    Check if a successful summary note already exists for a URL.

    Returns False for error/stub notes (status: error) so they can be retried.

    Args:
        vault_path: Path to the Obsidian vault root.
        out_folder: Folder name for summaries.
        url: URL to check.
        date: Date for the summary.

    Returns:
        True if a successful summary file exists, False otherwise.
    """
    filepath = get_summary_filepath(vault_path, out_folder, url, date)

    if not filepath.exists():
        return False

    # Check if it's an error stub or mocked summary that should be retried
    try:
        content = filepath.read_text(encoding="utf-8")
        # Check for error/mocked status in frontmatter
        if content.startswith("---"):
            # Find end of frontmatter
            end_idx = content.find("---", 3)
            if end_idx != -1:
                frontmatter = content[3:end_idx]
                if "status: error" in frontmatter:
                    logger.debug(f"Found error stub, will retry: {filepath.name}")
                    return False
                if "status: mocked" in frontmatter:
                    logger.debug(f"Found mocked summary, will retry: {filepath.name}")
                    return False
    except OSError:
        pass  # If we can't read it, assume it exists

    return True


def _escape_yaml_string(value: str) -> str:
    """
    Escape a string value for YAML frontmatter.

    Quotes strings that contain special YAML characters.

    Args:
        value: String value to escape.

    Returns:
        Properly escaped/quoted string for YAML.
    """
    # Characters that require quoting
    special_chars = [
        ":",
        "#",
        "[",
        "]",
        "{",
        "}",
        ",",
        "&",
        "*",
        "!",
        "|",
        ">",
        "'",
        '"',
        "%",
        "@",
        "`",
    ]

    # Check if quoting is needed
    needs_quoting = (
        any(char in value for char in special_chars)
        or value.startswith("-")
        or value.startswith("?")
        or "\n" in value
    )

    if needs_quoting:
        # Use double quotes and escape internal double quotes
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    return value


def build_frontmatter(
    url: str,
    page_metadata: PageMetadata | None = None,
    summary_result: SummaryResult | None = None,
    user_tags: list[str] | None = None,
    date: datetime | None = None,
    source_note: str | None = None,
    status: str = "success",
    default_tags: list[str] | None = None,
    max_tags: int = DEFAULT_MAX_TAGS,
) -> str:
    """
    Build YAML frontmatter for a summary note.

    Combines metadata from multiple sources into rich frontmatter.

    Args:
        url: Source URL being summarized.
        page_metadata: Metadata extracted from the web page.
        summary_result: Result from Gemini summarization.
        user_tags: Tags from the user's daily note.
        date: Date for the summary (defaults to today).
        source_note: Name of the source daily note.
        status: Status of the summary ("success" or "error").
        default_tags: Tags to always include.
        max_tags: Maximum number of tags.

    Returns:
        YAML frontmatter string (including --- delimiters).
    """
    if date is None:
        date = datetime.now()

    lines = ["---"]

    # Source URL (always included)
    lines.append(f"source: {url}")

    # Title
    if page_metadata and page_metadata.title:
        lines.append(f"title: {_escape_yaml_string(page_metadata.title)}")

    # Author
    if page_metadata and page_metadata.author:
        lines.append(f"author: {_escape_yaml_string(page_metadata.author)}")

    # Content type
    if summary_result and summary_result.content_type:
        lines.append(f"type: {summary_result.content_type}")

    # Date
    date_str = date.strftime("%Y-%m-%d")
    lines.append(f"date: {date_str}")

    # Status
    lines.append(f"status: {status}")

    # Source daily note (backlink)
    if source_note:
        note_name = source_note.replace(".md", "")
        lines.append(f'from: "[[{note_name}]]"')

    # Tags - merge from all sources
    article_tags = page_metadata.article_tags if page_metadata else []
    ai_tags = summary_result.suggested_tags if summary_result else []
    merged_tags = merge_tags(
        user_tags=user_tags or [],
        article_tags=article_tags,
        ai_tags=ai_tags,
        default_tags=default_tags,
        max_tags=max_tags,
    )

    if merged_tags:
        lines.append("tags:")
        for tag in merged_tags:
            lines.append(f"  - {tag}")

    # Optional metadata fields
    if page_metadata:
        if page_metadata.published_date:
            lines.append(f"published: {page_metadata.published_date}")

        if page_metadata.domain:
            lines.append(f"domain: {page_metadata.domain}")

    lines.append("---")

    return "\n".join(lines)


def write_summary_note(
    vault_path: Path,
    out_folder: str,
    url: str,
    content: str,
    date: datetime | None = None,
    source_note: str | None = None,
    overwrite: bool = False,
    status: str = "success",
) -> Path:
    """
    Write a summary note with minimal frontmatter.

    This is the lower-level function used internally by write_stub_note()
    for creating error/stub notes. For production summaries with rich
    metadata (title, author, tags, etc.), use write_summary_note_with_metadata().

    Creates the output folder if it doesn't exist. The note includes
    basic frontmatter with source URL, date, and link to original daily note.

    Args:
        vault_path: Path to the Obsidian vault root.
        out_folder: Folder name for summaries (relative to vault).
        url: Source URL being summarized.
        content: Markdown content for the summary (without frontmatter).
        date: Date for the summary (defaults to today).
        source_note: Name of the source daily note (for backlink).
        overwrite: If True, overwrite existing file; if False, skip.
        status: Status of the summary ("success" or "error").

    Returns:
        Path to the written file.

    Raises:
        NoteWriteError: If writing the note fails.

    Note:
        For full-featured summaries with PageMetadata and SummaryResult,
        prefer write_summary_note_with_metadata() which builds comprehensive
        frontmatter automatically.
    """
    if date is None:
        date = datetime.now()

    filepath = get_summary_filepath(vault_path, out_folder, url, date)

    # Check if file exists
    if filepath.exists() and not overwrite:
        logger.info(f"Summary already exists, skipping: {filepath.name}")
        return filepath

    # Ensure output folder exists
    output_dir = vault_path / out_folder
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise NoteWriteError(f"Failed to create output folder {output_dir}: {e}") from e

    # Build frontmatter
    date_str = date.strftime("%Y-%m-%d")
    frontmatter_lines = [
        "---",
        f"source: {url}",
        f"date: {date_str}",
        f"status: {status}",
    ]

    if source_note:
        # Create Obsidian backlink to source note
        note_name = source_note.replace(".md", "")
        frontmatter_lines.append(f'from: "[[{note_name}]]"')

    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines)

    # Combine frontmatter and content
    full_content = f"{frontmatter}\n\n{content}"

    # Write file
    try:
        filepath.write_text(full_content, encoding="utf-8")
        logger.info(f"Wrote summary to: {filepath.name}")
        return filepath
    except OSError as e:
        raise NoteWriteError(f"Failed to write summary to {filepath}: {e}") from e


def write_summary_note_with_metadata(
    vault_path: Path,
    out_folder: str,
    url: str,
    summary_result: SummaryResult,
    page_metadata: PageMetadata | None = None,
    user_tags: list[str] | None = None,
    date: datetime | None = None,
    source_note: str | None = None,
    overwrite: bool = False,
    default_tags: list[str] | None = None,
    max_tags: int = DEFAULT_MAX_TAGS,
    status: str = "success",
) -> Path:
    """
    Write a summary note with rich frontmatter.

    This is the enhanced version that uses PageMetadata and SummaryResult
    to build comprehensive frontmatter with title, author, tags, etc.

    Args:
        vault_path: Path to the Obsidian vault root.
        out_folder: Folder name for summaries.
        url: Source URL being summarized.
        summary_result: Result from Gemini summarization.
        page_metadata: Metadata extracted from the web page.
        user_tags: Tags from the user's daily note.
        date: Date for the summary (defaults to today).
        source_note: Name of the source daily note.
        overwrite: If True, overwrite existing file.
        default_tags: Tags to always include.
        max_tags: Maximum number of tags.
        status: Status to write in frontmatter ('success', 'mocked', 'error').

    Returns:
        Path to the written file.

    Raises:
        NoteWriteError: If writing the note fails.
    """
    if date is None:
        date = datetime.now()

    filepath = get_summary_filepath(vault_path, out_folder, url, date)

    # Check if file exists
    if filepath.exists() and not overwrite:
        logger.info(f"Summary already exists, skipping: {filepath.name}")
        return filepath

    # Ensure output folder exists
    output_dir = vault_path / out_folder
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise NoteWriteError(f"Failed to create output folder {output_dir}: {e}") from e

    # Build rich frontmatter
    frontmatter = build_frontmatter(
        url=url,
        page_metadata=page_metadata,
        summary_result=summary_result,
        user_tags=user_tags,
        date=date,
        source_note=source_note,
        status=status,
        default_tags=default_tags,
        max_tags=max_tags,
    )

    # Combine frontmatter and content
    full_content = f"{frontmatter}\n\n{summary_result.content}"

    # Write file
    try:
        filepath.write_text(full_content, encoding="utf-8")
        logger.info(f"Wrote summary with metadata to: {filepath.name}")
        return filepath
    except OSError as e:
        raise NoteWriteError(f"Failed to write summary to {filepath}: {e}") from e


def write_stub_note(
    vault_path: Path,
    out_folder: str,
    url: str,
    reason: str,
    date: datetime | None = None,
    source_note: str | None = None,
) -> Path:
    """
    Write a stub note for a URL that couldn't be processed.

    Used when rate limiting or errors prevent full summarization.
    These notes are marked with status: error so they can be retried.

    Args:
        vault_path: Path to the Obsidian vault root.
        out_folder: Folder name for summaries.
        url: Source URL.
        reason: Reason the URL couldn't be processed.
        date: Date for the summary.
        source_note: Name of the source daily note.

    Returns:
        Path to the written stub file.

    Raises:
        NoteWriteError: If writing fails.
    """
    stub_content = f"""## Summary Unavailable

{reason}

**Original URL**: {url}

---
*Run summarize-links again to retry this URL.*
"""

    return write_summary_note(
        vault_path=vault_path,
        out_folder=out_folder,
        url=url,
        content=stub_content,
        date=date,
        source_note=source_note,
        overwrite=True,  # Always overwrite stubs
        status="error",  # Mark as error so it can be retried
    )


def add_summary_link_to_daily_note(
    vault_path: Path,
    daily_notes_folder: str,
    note_filename: str,
    summary_path: Path,
    url: str,
) -> bool:
    """
    Add an internal Obsidian link to the summary note in the daily note.

    Preserves surrounding context (notes, tags) from the original line containing the URL.
    If the link already exists, it won't be added again.

    Args:
        vault_path: Path to the Obsidian vault root.
        daily_notes_folder: Subfolder for daily notes (can be empty).
        note_filename: Filename of the daily note (e.g., "2025-12-15.md").
        summary_path: Path to the created summary note.
        url: The original URL that was summarized.

    Returns:
        True if the link was added, False if it already existed or couldn't be added.

    Raises:
        NoteWriteError: If writing the updated note fails.
    """
    # Construct full path to daily note
    if daily_notes_folder:
        daily_note_path = vault_path / daily_notes_folder / note_filename
    else:
        daily_note_path = vault_path / note_filename

    if not daily_note_path.exists():
        logger.warning(f"Daily note not found for linking: {daily_note_path}")
        return False

    # Get the summary note name (without .md extension) for the Obsidian link
    summary_name = summary_path.stem

    # Create the Obsidian internal link
    obsidian_link = f"[[{summary_name}]]"

    try:
        content = daily_note_path.read_text(encoding="utf-8")

        # Check if link already exists
        if obsidian_link in content:
            logger.debug(f"Link already exists in daily note: {obsidian_link}")
            return False

        # Find the line containing the URL and extract context
        summary_line = _build_summary_line_with_context(content, url, obsidian_link)

        # Append the link at the end of the note
        # Add a section header if this is the first summary link
        if "## Summaries" not in content:
            updated_content = content.rstrip() + f"\n\n## Summaries\n{summary_line}\n"
        else:
            # Find the Summaries section and append to it
            # Simple approach: append at end of file under existing section
            updated_content = content.rstrip() + f"\n{summary_line}\n"

        daily_note_path.write_text(updated_content, encoding="utf-8")
        logger.info(f"Added summary link to daily note: {obsidian_link}")
        return True

    except OSError as e:
        raise NoteWriteError(f"Failed to update daily note {daily_note_path}: {e}") from e


def _build_summary_line_with_context(content: str, url: str, obsidian_link: str) -> str:
    """
    Build a summary line by extracting context from the original URL line.

    Finds the line containing the URL, replaces the URL (or markdown link) with
    the Obsidian internal link, and preserves surrounding text like notes and tags.

    Args:
        content: Full content of the daily note.
        url: The original URL to find.
        obsidian_link: The Obsidian internal link to use (e.g., "[[summary-name]]").

    Returns:
        A formatted summary line with context, or a simple bullet point if no context found.
    """
    # Find the line containing the URL
    for line in content.split("\n"):
        if url not in line:
            continue

        # Found the line - now replace the URL with the obsidian link
        # First try to match a markdown link containing this URL: [text](url)
        markdown_link_pattern = rf"\[[^\]]*\]\({re.escape(url)}\)"
        if re.search(markdown_link_pattern, line):
            # Replace the markdown link with the obsidian link
            new_line = re.sub(markdown_link_pattern, obsidian_link, line)
        else:
            # It's a bare URL - replace it directly
            new_line = line.replace(url, obsidian_link)

        # Clean up the line - ensure it starts with a bullet if it doesn't already
        new_line = new_line.strip()
        if not new_line.startswith("-") and not new_line.startswith("*"):
            new_line = f"- {new_line}"

        logger.debug(f"Built summary line with context: {new_line}")
        return new_line

    # URL not found in content - return simple link
    logger.debug(f"URL not found in content, using simple link: {url}")
    return f"- {obsidian_link}"


def remove_url_line_from_note(
    vault_path: Path,
    daily_notes_folder: str,
    note_filename: str,
    url: str,
) -> bool:
    """
    Remove the line containing a URL from a daily note.

    Called after a URL has been successfully summarized to clean up
    the original daily note. Only removes the line if the URL is found.

    Args:
        vault_path: Path to the Obsidian vault root.
        daily_notes_folder: Subfolder for daily notes (can be empty).
        note_filename: Filename of the daily note (e.g., "2025-12-15.md").
        url: The URL to find and remove its containing line.

    Returns:
        True if a line was removed, False if URL not found.

    Raises:
        NoteWriteError: If writing the updated note fails.
    """
    # Construct full path to daily note
    if daily_notes_folder:
        daily_note_path = vault_path / daily_notes_folder / note_filename
    else:
        daily_note_path = vault_path / note_filename

    if not daily_note_path.exists():
        logger.warning(f"Daily note not found for URL removal: {daily_note_path}")
        return False

    try:
        content = daily_note_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        # Find the line(s) containing the URL
        new_lines: list[str] = []
        removed = False

        for line in lines:
            if url in line:
                logger.info(f"Removing line containing URL: {url}")
                logger.debug(f"Removed line: {line}")
                removed = True
                # Skip this line (don't add to new_lines)
            else:
                new_lines.append(line)

        if not removed:
            logger.debug(f"URL not found in note, nothing to remove: {url}")
            return False

        # Write the updated content
        # Preserve trailing newline if original had one
        new_content = "\n".join(new_lines)
        if content.endswith("\n") and not new_content.endswith("\n"):
            new_content += "\n"

        daily_note_path.write_text(new_content, encoding="utf-8")
        logger.info(f"Successfully removed URL line from daily note: {note_filename}")
        return True

    except OSError as e:
        raise NoteWriteError(f"Failed to update daily note {daily_note_path}: {e}") from e


def scan_summaries(
    vault_path: Path,
    out_folder: str,
) -> SummaryStats:
    """
    Scan all summary notes and collect status information.

    Examines all .md files in the summaries folder and extracts their
    status from frontmatter. Returns statistics and lists of problematic
    summaries that may need attention.

    Args:
        vault_path: Path to the Obsidian vault root.
        out_folder: Folder name for summaries (relative to vault).

    Returns:
        Dictionary containing:
        - total: Total number of summaries
        - success: Number of successful summaries
        - mocked: Number of mocked summaries (need real summarization)
        - error: Number of error/stub summaries (failed processing)
        - unknown: Number without clear status
        - oldest_date: Oldest summary date (YYYY-MM-DD)
        - newest_date: Newest summary date (YYYY-MM-DD)
        - error_summaries: List of (filename, reason) for error summaries
        - mocked_summaries: List of (filename, date) for mocked summaries
    """
    summaries_path = vault_path / out_folder

    if not summaries_path.exists():
        logger.warning(f"Summaries folder not found: {summaries_path}")
        return {
            "total": 0,
            "success": 0,
            "mocked": 0,
            "error": 0,
            "unknown": 0,
            "oldest_date": None,
            "newest_date": None,
            "error_summaries": [],
            "mocked_summaries": [],
        }

    total = 0
    success_count = 0
    mocked_count = 0
    error_count = 0
    unknown_count = 0
    error_summaries: list[tuple[str, str]] = []
    mocked_summaries: list[tuple[str, str]] = []
    dates: list[str] = []

    # Scan all markdown files
    for filepath in summaries_path.glob("*.md"):
        total += 1

        try:
            content = filepath.read_text(encoding="utf-8")

            # Extract status from frontmatter
            status = _extract_frontmatter_field(content, "status")
            date = _extract_frontmatter_field(content, "date")

            if date:
                dates.append(date)

            # Categorize by status
            if status == "success":
                success_count += 1
            elif status == "mocked":
                mocked_count += 1
                mocked_summaries.append((filepath.name, date or "unknown"))
            elif status == "error":
                error_count += 1
                # Extract error reason if available
                reason = _extract_error_reason(content)
                error_summaries.append((filepath.name, reason))
            else:
                unknown_count += 1
                logger.debug(f"Unknown status for {filepath.name}: {status}")

        except OSError as e:
            logger.warning(f"Failed to read summary {filepath}: {e}")
            unknown_count += 1

    # Determine date range
    oldest_date = min(dates) if dates else None
    newest_date = max(dates) if dates else None

    logger.info(
        f"Scanned {total} summaries: "
        f"{success_count} success, {mocked_count} mocked, "
        f"{error_count} error, {unknown_count} unknown"
    )

    return {
        "total": total,
        "success": success_count,
        "mocked": mocked_count,
        "error": error_count,
        "unknown": unknown_count,
        "oldest_date": oldest_date,
        "newest_date": newest_date,
        "error_summaries": error_summaries,
        "mocked_summaries": mocked_summaries,
    }


def _extract_frontmatter_field(content: str, field: str) -> str | None:
    """
    Extract a field value from YAML frontmatter.

    Args:
        content: Note content with frontmatter.
        field: Field name to extract.

    Returns:
        Field value as string, or None if not found.
    """
    if not content.startswith("---"):
        return None

    # Find end of frontmatter
    end_idx = content.find("---", 3)
    if end_idx == -1:
        return None

    frontmatter = content[3:end_idx]

    # Simple field extraction (works for single-line values)
    # Format: "field: value" or "field: 'value'" or 'field: "value"'
    pattern = rf"^{re.escape(field)}:\s*(.+)$"
    match = re.search(pattern, frontmatter, re.MULTILINE)

    if match:
        value = match.group(1).strip()
        # Remove quotes if present
        value = value.strip('"').strip("'")
        return value

    return None


def _extract_error_reason(content: str) -> str:
    """
    Extract error reason from a stub note.

    Looks for the error description in the note content.

    Args:
        content: Note content.

    Returns:
        Error reason string, or "Unknown error" if not found.
    """
    # Look for common error patterns
    if "Failed to fetch" in content:
        return "Fetch failed"
    elif "Failed to extract content" in content:
        return "Extraction failed"
    elif "Rate limited" in content:
        return "Rate limited"
    elif "API error" in content:
        return "API error"
    else:
        return "Unknown error"
