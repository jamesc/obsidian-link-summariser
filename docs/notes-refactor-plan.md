# Notes.py Refactoring Plan

## Current State

**File:** summarize_links/notes.py
**Size:** 1,484 lines
**Responsibilities:** 23 public functions handling URL extraction, daily notes, summary notes, and scanning operations

## Problem Analysis

The notes.py module has grown too large and handles multiple distinct responsibilities:

1. **URL Extraction & Cleaning** (5 functions, ~300 lines)
   - URL pattern matching and extraction
   - Hashtag extraction
   - URL cleaning (tracking param removal)
   - URL-to-slug conversion

2. **Daily Note Operations** (5 functions, ~400 lines)
   - Reading daily notes from vault
   - Finding notes with URLs
   - Adding summary links to daily notes
   - Removing URL lines from notes
   - Context preservation

3. **Summary Note Operations** (7 functions, ~600 lines)
   - Frontmatter building
   - Writing summary notes
   - Writing stub/error notes
   - Checking if summaries exist
   - Getting summary metadata

4. **Scanning Operations** (3 functions, ~180 lines)
   - Scanning all summaries for statistics
   - Scanning for resummarize candidates
   - Extracting frontmatter fields

## Proposed Structure

Split into 4 focused modules within a 
otes subpackage:

### 1. summarize_links/notes/extraction.py (~350 lines)
**Purpose:** URL and hashtag extraction from markdown content

**Functions:**
- xtract_urls(content) - Extract all URLs from markdown
- xtract_urls_with_context(content) - Extract URLs with user tags/context
- xtract_hashtags_from_line(line) - Extract Obsidian hashtags
- clean_url(url) - Remove tracking parameters
- Helper: _clean_url_fragment(url) - Remove noise fragments

**Constants:**
- MARKDOWN_LINK_PATTERN
- BARE_URL_PATTERN
- HASHTAG_PATTERN
- TRACKING_PARAMS
- MEANINGFUL_PARAMS
- NOISE_FRAGMENTS

**Dependencies:**
- models.UrlWithContext
- xceptions.URLExtractionError

### 2. summarize_links/notes/daily_notes.py (~400 lines)
**Purpose:** Daily note reading and modification operations

**Functions:**
- ead_daily_note(vault_path, note_path, daily_notes_folder) - Read note content
- ind_daily_notes_with_urls(vault_path, daily_notes_folder) - Scan for notes with URLs
- dd_summary_link_to_daily_note(vault_path, daily_note_filename, summary_filename, url, daily_notes_folder) - Add link to summaries section
- emove_url_line_from_note(vault_path, daily_note_filename, url, daily_notes_folder) - Remove processed URL lines
- Helper: _build_summary_line_with_context(content, url, obsidian_link) - Preserve context when adding links

**Dependencies:**
- .extraction for xtract_urls()
- xceptions.NoteReadError, NoteWriteError

### 3. summarize_links/notes/summaries.py (~550 lines)
**Purpose:** Summary note creation and management

**Functions:**
- write_summary_note_with_metadata(...) - Write full summary with rich frontmatter
- write_summary_note(...) - Legacy simple write (kept for compatibility)
- write_stub_note(...) - Write error stub
- summary_exists(...) - Check if summary already exists
- get_summary_filepath(...) - Calculate summary file path
- get_existing_summary_date(...) - Extract date from existing summary
- uild_frontmatter(...) - Build YAML frontmatter
- generate_slug(text) - Generate URL-safe slug
- slug_from_url(url) - Extract slug from URL
- Helper: _escape_yaml_string(value) - Escape YAML values

**Constants:**
- SLUG_REPLACEMENTS
- MAX_SLUG_LENGTH (imported from config)

**Dependencies:**
- models.PageMetadata, SummaryResult
- config.DEFAULT_MAX_TAGS
- xceptions.NoteWriteError

### 4. summarize_links/notes/scanning.py (~200 lines)
**Purpose:** Scan and analyze existing summary notes

**Functions:**
- scan_summaries(vault_path, out_folder) - Get statistics about all summaries
- scan_summaries_for_resummarize(vault_path, out_folder) - Find summaries to regenerate
- Helper: _extract_frontmatter_field(content, field) - Parse frontmatter
- Helper: _extract_error_reason(content) - Detect error type

**Types:**
- SummaryStats TypedDict

**Dependencies:**
- None (standalone)

### 5. summarize_links/notes/__init__.py (~50 lines)
**Purpose:** Package initialization and backward-compatible exports

**Exports all functions from submodules:**
`python
from .extraction import (
    clean_url,
    extract_hashtags_from_line,
    extract_urls,
    extract_urls_with_context,
)
from .daily_notes import (
    add_summary_link_to_daily_note,
    find_daily_notes_with_urls,
    read_daily_note,
    remove_url_line_from_note,
)
from .summaries import (
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
from .scanning import (
    SummaryStats,
    scan_summaries,
    scan_summaries_for_resummarize,
)

__all__ = [
    # ... all exports
]
`

## Implementation Strategy

### Phase 1: Create Module Structure
1. Create summarize_links/notes/ directory
2. Create __init__.py with re-exports
3. Create empty submodules (extraction.py, daily_notes.py, summaries.py, scanning.py)

### Phase 2: Move Code with Tests
For each submodule:
1. Copy relevant functions to new file
2. Update imports in new file
3. Run tests to verify
4. Move to next submodule

Order: extraction → summaries → daily_notes → scanning
(Respect dependency order)

### Phase 3: Update Main Package
1. Update 
otes/__init__.py to re-export everything
2. Old imports like rom summarize_links.notes import X still work
3. No changes needed in other modules

### Phase 4: Cleanup
1. Delete old 
otes.py file
2. Run full test suite
3. Run linting (ruff, mypy)

### Phase 5: Documentation
1. Update docstrings for each new module
2. Add entry to tasks.md
3. Consider updating README if module structure is mentioned

## Benefits

✓ **Clearer organization**: Each module has single, focused purpose
✓ **Easier navigation**: ~350 lines per file instead of 1,484
✓ **Better testing**: Can test submodules independently
✓ **Reduced cognitive load**: Don't need to understand entire notes system at once
✓ **Backward compatible**: All existing imports continue to work
✓ **Better separation**: Extraction logic separate from I/O operations
✓ **Future extensibility**: Easy to add new scanning operations or note types

## Migration Path

**Backward Compatibility:**
All existing code continues to work:
`python
# This still works (imports from __init__.py):
from summarize_links.notes import extract_urls, write_summary_note_with_metadata

# New explicit imports also available:
from summarize_links.notes.extraction import extract_urls
from summarize_links.notes.summaries import write_summary_note_with_metadata
`

**No Breaking Changes:**
- All function signatures remain the same
- All return types remain the same
- All exceptions remain the same
- Test suite should pass without modification (except import paths in test file if needed)

## Estimated Effort

- Phase 1 (Structure): 15 minutes
- Phase 2 (Move Code): 45-60 minutes
- Phase 3 (Integration): 15 minutes  
- Phase 4 (Cleanup): 15 minutes
- Phase 5 (Documentation): 15 minutes

**Total: ~2 hours**

## Success Criteria

✓ All 542 tests passing
✓ uff check . passes
✓ mypy . passes
✓ No import errors in application
✓ Each submodule < 600 lines
✓ Clear module responsibilities in docstrings
✓ Backward compatibility maintained

## Next Steps After notes.py

If we continue the refactoring pattern, xtract.py (1,123 lines) would be next:
- Could split into: etch.py, html_parsing.py, metadata.py
- But let's finish notes.py refactoring first and assess
