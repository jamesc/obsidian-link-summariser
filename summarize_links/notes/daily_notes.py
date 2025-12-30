"""
Daily note reading and modification operations.

This module handles:
- Reading daily notes from an Obsidian vault
- Finding daily notes that contain URLs
- Adding summary links to daily notes
- Removing processed URL lines from notes
- Preserving context when modifying notes
"""

import logging
import re
from pathlib import Path

from summarize_links.exceptions import NoteReadError, NoteWriteError
from summarize_links.notes.extraction import extract_urls

__all__ = [
    "add_summary_link_to_daily_note",
    "find_daily_notes_with_urls",
    "read_daily_note",
    "remove_url_line_from_note",
]

# Configure module logger
logger = logging.getLogger(__name__)


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
