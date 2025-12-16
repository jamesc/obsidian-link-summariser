"""
Obsidian note parsing and writing module.

This module handles:
- Reading daily notes from an Obsidian vault
- Extracting URLs from Markdown content (both links and bare URLs)
- Writing formatted summary notes with frontmatter
- Generating URL-safe slugs for filenames
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from summarize_links.config import MAX_SLUG_LENGTH
from summarize_links.exceptions import NoteReadError, NoteWriteError, URLExtractionError

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

    Args:
        content: Markdown content to parse.

    Returns:
        List of unique URLs in order of first appearance.

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

            if url and url not in seen:
                # Clean up URL (remove trailing punctuation that might have been captured)
                url = url.rstrip(".,;:")
                urls.append(url)
                seen.add(url)
                logger.debug(f"Extracted URL: {url}")

        logger.info(f"Extracted {len(urls)} unique URLs from content")
        return urls

    except Exception as e:
        raise URLExtractionError(f"Failed to extract URLs: {e}") from e


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

    # Check if it's an error stub that should be retried
    try:
        content = filepath.read_text(encoding="utf-8")
        # Check for error status in frontmatter
        if content.startswith("---"):
            # Find end of frontmatter
            end_idx = content.find("---", 3)
            if end_idx != -1:
                frontmatter = content[3:end_idx]
                if "status: error" in frontmatter:
                    logger.debug(f"Found error stub, will retry: {filepath.name}")
                    return False
    except OSError:
        pass  # If we can't read it, assume it exists

    return True


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
    Write a summary note to the vault.

    Creates the output folder if it doesn't exist. The note includes
    frontmatter with source URL, date, and link to original daily note.

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
