"""
Summary note creation and management.

This module handles:
- Writing formatted summary notes with rich frontmatter
- Writing stub/error notes for failed processing
- Checking if summaries exist
- Building YAML frontmatter from metadata
- Generating URL-safe slugs for filenames
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from summarize_links.config import DEFAULT_MAX_TAGS, MAX_SLUG_LENGTH
from summarize_links.exceptions import NoteWriteError
from summarize_links.models import PageMetadata, SummaryResult, merge_tags

__all__ = [
    "build_frontmatter",
    "generate_slug",
    "get_existing_summary_date",
    "get_summary_filepath",
    "slug_from_url",
    "summary_exists",
    "write_stub_note",
    "write_summary_note",
    "write_summary_note_with_metadata",
    "_escape_yaml_string",  # Used by tests
]

# Configure module logger
logger = logging.getLogger(__name__)

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

    Returns False for error/stub notes (summary_status: *_error or summary_status: error)
    and mocked summaries so they can be retried.

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
                # Check for new format: summary_status: <error_type>
                if "summary_status:" in frontmatter:
                    for line in frontmatter.split("\n"):
                        if line.strip().startswith("summary_status:"):
                            status_value = line.split(":", 1)[1].strip()
                            if "error" in status_value or status_value == "mocked":
                                logger.debug(
                                    f"Found {status_value} status, will retry: {filepath.name}"
                                )
                                return False
                # Check for legacy format: status: error / status: mocked
                elif "status: error" in frontmatter:
                    logger.debug(f"Found error stub (legacy format), will retry: {filepath.name}")
                    return False
                elif "status: mocked" in frontmatter:
                    logger.debug(
                        f"Found mocked summary (legacy format), will retry: {filepath.name}"
                    )
                    return False
    except OSError:
        pass  # If we can't read it, assume it exists

    return True


def get_existing_summary_date(
    vault_path: Path,
    out_folder: str,
    url: str,
) -> datetime | None:
    """
    Get the date from an existing summary file by searching for it.

    This searches for existing summary files for the given URL across all dates
    and returns the date of the first one found. This is used to preserve the
    original date when re-summarizing.

    Args:
        vault_path: Path to the Obsidian vault root.
        out_folder: Folder name for summaries.
        url: URL to search for.

    Returns:
        The date of the existing summary if found, None otherwise.
    """
    summaries_path = vault_path / out_folder

    if not summaries_path.exists():
        return None

    # Get the slug for this URL
    slug = slug_from_url(url)

    # Search for files matching the pattern {date}-{slug}.md
    pattern = f"*-{slug}.md"
    matching_files = list(summaries_path.glob(pattern))

    if not matching_files:
        return None

    # If multiple files found, use the first one (oldest)
    # Extract date from filename (format: YYYY-MM-DD-{slug}.md)
    filepath = matching_files[0]
    filename = filepath.stem  # Remove .md extension

    # Extract date part (first 10 characters: YYYY-MM-DD)
    date_str = filename[:10]

    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        logger.warning(f"Could not parse date from filename: {filepath.name}")
        return None


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
    summary_status: str = "success",
    default_tags: list[str] | None = None,
    max_tags: int = DEFAULT_MAX_TAGS,
    summary_model: str | None = None,
    summary_date: datetime | None = None,
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
        summary_status: Status of the summary ("success" or "error").
        default_tags: Tags to always include.
        max_tags: Maximum number of tags.
        summary_model: Model used to generate the summary.
        summary_date: Date when the summary was generated (defaults to now).

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
    lines.append(f"summary_status: {summary_status}")

    # Model used
    if summary_model:
        lines.append(f"summary_model: {summary_model}")

    # Summary generation date
    if summary_date is None:
        summary_date = datetime.now()
    summary_date_str = summary_date.strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"summary_date: {summary_date_str}")

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
    summary_status: str = "success",
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
        summary_status: Summary status (e.g., "success", "fetch_error", "extraction_error").

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
        f"summary_status: {summary_status}",
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
    summary_status: str = "success",
    summary_model: str | None = None,
    summary_date: datetime | None = None,
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
        summary_status: Status to write in frontmatter ('success', 'mocked', 'error').
        summary_model: Model used to generate the summary.
        summary_date: Date when the summary was generated (defaults to now).

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
        summary_status=summary_status,
        default_tags=default_tags,
        max_tags=max_tags,
        summary_model=summary_model,
        summary_date=summary_date,
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
    error_type: str = "error",
) -> Path:
    """
    Write a stub note for a URL that couldn't be processed.

    Used when rate limiting or errors prevent full summarization.
    These notes are marked with summary_status: <error_type> so they can be retried.

    Args:
        vault_path: Path to the Obsidian vault root.
        out_folder: Folder name for summaries.
        url: Source URL.
        reason: Reason the URL couldn't be processed.
        date: Date for the summary.
        source_note: Name of the source daily note.
        error_type: Type of error (e.g., "fetch_error", "extraction_error", "api_error").

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
        summary_status=error_type,  # Mark with error type so it can be retried
    )
