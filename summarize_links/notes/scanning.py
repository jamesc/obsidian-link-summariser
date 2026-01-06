"""
Scan and analyze existing summary notes.

This module handles:
- Scanning all summary notes for statistics
- Finding summaries that need regeneration
- Extracting frontmatter fields
- Detecting error types from content
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TypedDict

__all__ = [
    "SummaryStats",
    "scan_summaries",
    "scan_summaries_for_resummarize",
]

# Configure module logger
logger = logging.getLogger(__name__)


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
            status = _extract_frontmatter_field(content, "summary_status")
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


def scan_summaries_for_resummarize(
    vault_path: Path,
    out_folder: str,
) -> list[tuple[str, datetime, datetime, str | None]]:
    """
    Scan all summary notes and return those suitable for resummarization.

    Returns summaries that exist (not errors or mocked stubs) and extracts
    their source URL, original date, summary date, and source note for reprocessing.

    Args:
        vault_path: Path to the Obsidian vault root.
        out_folder: Folder name for summaries (relative to vault).

    Returns:
        List of tuples (source_url, original_date, summary_date, source_note) for
        summaries to reprocess. For summaries without summary_date, the original date
        is used as summary_date. source_note is the 'from' field value (without
        brackets), or None if not present. Sorted by original date (newest first).
    """
    summaries_path = vault_path / out_folder

    if not summaries_path.exists():
        logger.warning(f"Summaries folder not found: {summaries_path}")
        return []

    results: list[tuple[str, datetime, datetime, str | None]] = []

    # Scan all markdown files
    for filepath in summaries_path.glob("*.md"):
        try:
            content = filepath.read_text(encoding="utf-8")

            # Extract source URL, dates, and source note from frontmatter
            source_url = _extract_frontmatter_field(content, "source")
            date_str = _extract_frontmatter_field(content, "date")
            summary_date_str = _extract_frontmatter_field(content, "summary_date")
            status = _extract_frontmatter_field(content, "summary_status")
            from_field = _extract_frontmatter_field(content, "from")

            if not source_url or not date_str:
                logger.debug(f"Skipping {filepath.name}: missing source or date")
                continue

            # Skip error/mocked summaries (they should be handled by from-note --force)
            if status and ("error" in status or status == "mocked"):
                logger.debug(f"Skipping {filepath.name}: status={status}")
                continue

            # Parse original date
            try:
                original_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                logger.warning(f"Invalid date format in {filepath.name}: {date_str}")
                continue

            # Parse summary_date if available, otherwise use original date
            summary_date = original_date
            if summary_date_str:
                try:
                    # summary_date format: "2025-12-29 22:31:49"
                    summary_date = datetime.strptime(summary_date_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    # Try date-only format as fallback
                    try:
                        summary_date = datetime.strptime(summary_date_str, "%Y-%m-%d")
                    except ValueError:
                        logger.warning(
                            f"Invalid summary_date format in {filepath.name}: {summary_date_str}"
                        )
                        # Keep using original_date as fallback

            # Extract note name from 'from' field (format: "[[2025-12-30]]")
            source_note = None
            if from_field:
                # Remove [[ and ]] brackets
                source_note = from_field.strip('"').strip("'")
                if source_note.startswith("[[") and source_note.endswith("]]"):
                    source_note = source_note[2:-2]
                # Add .md extension if not present
                if source_note and not source_note.endswith(".md"):
                    source_note = f"{source_note}.md"

            results.append((source_url, original_date, summary_date, source_note))
            logger.debug(
                f"Found summary for resummarize: {source_url} "
                f"(date={date_str}, summary_date={summary_date.strftime('%Y-%m-%d')}, "
                f"from={source_note})"
            )

        except OSError as e:
            logger.warning(f"Failed to read summary {filepath}: {e}")
            continue

    # Sort by original date (newest first) to prioritize recent content
    results.sort(key=lambda x: x[1], reverse=True)

    logger.info(f"Found {len(results)} summaries for resummarization")
    return results


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
