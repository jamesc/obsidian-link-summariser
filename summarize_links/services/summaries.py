"""Summary lookup helpers shared between CLI and chat tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from summarize_links.config import Config
from summarize_links.utils.frontmatter import get_frontmatter_field


@dataclass
class SummaryMetadata:
    """Metadata about a summary note."""

    source_url: str
    original_date: datetime
    source_note: str | None
    path: Path


def _extract_summary_metadata(filepath: Path) -> SummaryMetadata | None:
    try:
        content = filepath.read_text(encoding="utf-8")
        source_url = get_frontmatter_field(content, "source")
        date_str = get_frontmatter_field(content, "date")
        from_field = get_frontmatter_field(content, "from")
        if not source_url or not date_str:
            return None
        try:
            original_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            # try datetime with time
            try:
                original_date = datetime.fromisoformat(date_str)
            except ValueError:
                return None
        source_note = None
        if from_field:
            source_note = from_field.strip('"').strip("'")
            if source_note.startswith("[[") and source_note.endswith("]]"):
                source_note = source_note[2:-2]
            if source_note and not source_note.endswith(".md"):
                source_note = f"{source_note}.md"
        return SummaryMetadata(
            source_url=source_url,
            original_date=original_date,
            source_note=source_note,
            path=filepath,
        )
    except OSError:
        return None


def find_summary_metadata(identifier: str, config: Config) -> SummaryMetadata | None:
    """Find an existing summary by slug or URL.

    Searches first by slug/filename matching, then by normalized URL.
    Uses a single iteration over files with early return for efficiency.

    Returns SummaryMetadata or None if not found.
    """
    if not config.vault_path:
        return None
    summaries_path = config.vault_path / config.out_folder
    if not summaries_path.exists():
        return None

    # Only strip .md if it's an actual suffix (not character-by-character strip)
    slug_or_url = identifier[:-3] if identifier.endswith(".md") else identifier

    def _normalize_url(u: str) -> str:
        norm = u.rstrip("/").replace("http://", "https://")
        if not norm.startswith("https://"):
            norm = "https://" + norm
        return norm

    normalized_input = _normalize_url(slug_or_url)

    # Single pass: check both slug matching and URL matching together
    url_match: SummaryMetadata | None = None

    for filepath in summaries_path.glob("*.md"):
        stem = filepath.stem  # may be YYYY-MM-DD-slug or slug

        # Try slug/filename matching first (preferred, returns immediately)
        if stem == slug_or_url or stem.endswith(f"-{slug_or_url}"):
            metadata = _extract_summary_metadata(filepath)
            if metadata:
                return metadata  # Early return on slug match

        # If no slug match yet, check URL match (cache first found for fallback)
        if url_match is None:
            metadata = _extract_summary_metadata(filepath)
            if metadata:
                normalized_source = _normalize_url(metadata.source_url)
                if normalized_source == normalized_input:
                    url_match = metadata
                    # Don't return yet - slug match takes priority

    # Return URL match if found (no slug match was found)
    return url_match
