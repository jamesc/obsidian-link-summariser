"""
Obsidian note parsing and writing module.

This package provides functionality for:
- Reading daily notes from an Obsidian vault
- Extracting URLs from Markdown content (both links and bare URLs)
- Writing formatted summary notes with frontmatter
- Generating URL-safe slugs for filenames
- Building rich frontmatter with metadata and tags
- Scanning and analyzing existing summaries

The module is organized into submodules for better maintainability:
- extraction: URL and hashtag extraction from markdown
- daily_notes: Reading and modifying daily notes
- summaries: Creating and managing summary notes
- scanning: Analyzing existing summary notes

All functions are re-exported at the package level for backward compatibility,
so existing code using `from summarize_links.notes import func` will continue to work.
"""

# Import all functions from submodules for backward compatibility
from summarize_links.notes.daily_notes import (
    add_summary_link_to_daily_note,
    find_daily_notes_with_urls,
    read_daily_note,
    remove_url_line_from_note,
)
from summarize_links.notes.extraction import (
    clean_url,
    extract_hashtags_from_line,
    extract_urls,
    extract_urls_with_context,
)
from summarize_links.notes.scanning import (
    SummaryStats,
    scan_summaries,
    scan_summaries_for_resummarize,
)
from summarize_links.notes.summaries import (
    _escape_yaml_string,  # Used by tests
    build_frontmatter,
    generate_slug,
    get_existing_summary_date,
    get_summary_filepath,
    slug_from_url,
    summary_exists,
    write_stub_note,
    write_summary_note,
    write_summary_note_with_metadata,
)

__all__ = [
    # URL extraction (from extraction.py)
    "extract_urls",
    "extract_urls_with_context",
    "extract_hashtags_from_line",
    "clean_url",
    # Daily note operations (from daily_notes.py)
    "find_daily_notes_with_urls",
    "read_daily_note",
    "add_summary_link_to_daily_note",
    "remove_url_line_from_note",
    # Summary note operations (from summaries.py)
    "write_summary_note_with_metadata",
    "write_stub_note",
    "summary_exists",
    "get_summary_filepath",
    "get_existing_summary_date",
    "build_frontmatter",
    "generate_slug",
    "slug_from_url",
    "write_summary_note",  # Lower-level, for internal use
    "_escape_yaml_string",  # Used by tests
    # Scanning operations (from scanning.py)
    "scan_summaries",
    "scan_summaries_for_resummarize",
    "SummaryStats",
]
