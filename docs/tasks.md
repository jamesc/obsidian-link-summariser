# Task Log

This document tracks completed development tasks for the Obsidian Link Summarizer.

---

## 2025-12-16: Mark mock summaries for later regeneration

**Goal:** When generating summaries in mock mode, mark them with `status: mocked` so they can be automatically regenerated when running again without mock mode.

**Changes:**
- Added `status` parameter to `write_summary_note_with_metadata()` in `summarize_links/notes.py`
- Updated `_process_url_with_metadata()` in `summarize_links/cli.py` to pass `status="mocked"` when in mock mode
- Updated `summary_exists()` in `summarize_links/notes.py` to return `False` for mocked summaries (like error stubs)

**Behavior:**
- `--mock` mode creates summaries with `status: mocked` in frontmatter
- Running again without `--mock` detects mocked summaries and regenerates them with the real API
- No need for `--force` flag to replace mocked content

**Tests:** Added 3 tests for mocked/error/success status handling in `TestSummaryExists`

---

## 2025-12-16: Rich frontmatter with author, tags, and metadata

**Goal:** Generate Obsidian summary notes with comprehensive YAML frontmatter including author, tags from multiple sources, content type, and article metadata.

**Implementation Plan:** See [frontmatter-plan.md](frontmatter-plan.md)

**Changes by Phase:**

### Phase 1: Data Models (`summarize_links/models.py`)
- Created `UrlWithContext` dataclass: URL with user tags and context text
- Created `PageMetadata` dataclass: title, author, domain, description, published_date, site_name, article_tags, content
- Created `SummaryResult` dataclass: content, suggested_tags, content_type
- Added `CONTENT_TYPES` constant for valid content types
- Added `normalize_tag()` and `merge_tags()` utility functions

### Phase 2: URL Extraction with Context (`summarize_links/notes.py`)
- Added `HASHTAG_PATTERN` regex for extracting Obsidian hashtags
- Added `extract_hashtags_from_line()` to extract hashtags from a line
- Added `extract_urls_with_context()` returning `UrlWithContext` objects

### Phase 3: HTML Metadata Extraction (`summarize_links/extract.py`)
- Added `_extract_meta_content()` helper for meta tag extraction
- Added specialized extractors: `_extract_title()`, `_extract_author()`, `_extract_description()`, `_extract_published_date()`, `_extract_site_name()`, `_extract_article_tags()`
- Added `extract_page_metadata()` returning `PageMetadata`
- Added `fetch_and_extract_metadata()` combining fetch and metadata extraction
- Article tags extracted from: og:article:tag, keywords meta, JSON-LD

### Phase 4: Gemini Structured Output (`summarize_links/gemini_client.py`)
- Updated `SUMMARY_SYSTEM_PROMPT` to request JSON with content, suggested_tags, content_type
- Added `_parse_gemini_response()` to parse JSON from model response
- Added `summarize_with_metadata()` method returning `SummaryResult`
- Updated `MockGeminiClient` with matching method

### Phase 5: Frontmatter Builder (`summarize_links/notes.py`)
- Added `_escape_yaml_string()` for safe YAML value escaping
- Added `build_frontmatter()` to generate rich YAML frontmatter
- Added `write_summary_note_with_metadata()` for complete note generation
- Frontmatter fields: source, title, author, type, date, status, from, tags, domain, published, description

### Phase 6: CLI Integration (`summarize_links/cli.py`)
- Added `_process_url_with_metadata()` for new pipeline
- Added `_process_urls_with_metadata()` for batch processing
- Updated `cmd_from_note()` to use `extract_urls_with_context()`
- Updated `cmd_urls()` to wrap URLs in `UrlWithContext`

### Phase 7: Config Options (`summarize_links/config.py`)
- Added `default_tags` field (list of tags added to all summaries)
- Added `max_tags` field (maximum tags in frontmatter, default 10)
- Both loaded from YAML config

**Tag Priority Order:**
1. Default tags (from config)
2. User tags (from daily note hashtags)
3. Article tags (from page metadata)
4. Gemini suggested tags

**Example Frontmatter:**
```yaml
---
source: https://example.com/article
title: Example Article
author: John Smith
type: article
date: 2025-12-16
status: success
from: "[[2025-12-16]]"
tags:
  - summarized
  - ai
  - machine-learning
domain: example.com
published: 2025-12-10
description: An introduction to machine learning concepts
---
```

**Tests:** Added 39+ new tests across test_models.py, test_notes.py, test_extraction.py, test_gemini.py, test_cli.py

---

## 2025-12-16: Preserve context when adding summary links to daily notes

**Goal:** When adding summary links to the Summaries section, preserve the surrounding text (notes, tags) from the original line containing the URL.

**Changes:**
- Updated `add_summary_link_to_daily_note()` to accept a `url` parameter
- Added `_build_summary_line_with_context()` helper function that:
  - Finds the line containing the original URL
  - Replaces the URL or markdown link with the Obsidian internal link
  - Preserves surrounding text like notes and tags
  - Adds a bullet point if the original line didn't have one

**Example:**
If the daily note has:
```markdown
- [Great Article](https://example.com/article) - must read #ai #tech
```
The Summaries section will contain:
```markdown
- [[2025-12-16-article]] - must read #ai #tech
```

**Tests:** Added 3 new tests for context preservation in `tests/test_notes.py`

---

## 2025-12-16: Add --force option to overwrite existing summaries

**Goal:** Add a `--force` CLI option that overwrites existing summaries instead of skipping them.

**Changes:**
- Added `force` field to `Config` dataclass in `summarize_links/config.py`
- Added `force` parameter to `load_config()` function
- Added `--force` CLI argument in `summarize_links/cli.py`
- Updated `_process_url()` to skip the exists check when `force=True`
- Updated `write_summary_note()` call to pass `overwrite=True` when force is enabled

**Usage:**
```bash
summarize-links --force from-note --date 2025-12-15
```

**Tests:** Added `test_force_overwrites_existing_summary` in `tests/test_cli.py`

---

## 2025-12-16: Add internal Obsidian links from daily note to summaries

**Goal:** When a summary is created successfully (not an error), add an internal Obsidian link from the daily note to the summary document.

**Changes:**
- Added `add_summary_link_to_daily_note()` function in `summarize_links/notes.py`
  - Creates a `## Summaries` section in the daily note if it doesn't exist
  - Appends `[[summary-note-name]]` links to the section
  - Skips duplicate links
- Updated `_process_url()` in `summarize_links/cli.py` to call link insertion after successful summary creation
- Updated `_process_urls()` and `cmd_from_note()` to pass through the daily note filename

**Behavior:**
- Links are only added for successful summaries (not error/stub notes)
- Link format: `[[2025-12-16-slug-name]]`
- Links appear at the end of the daily note under `## Summaries`
- No back-links when using the `urls` command (no daily note context)

**Tests:** Added 5 new tests in `tests/test_notes.py` for `TestAddSummaryLinkToDailyNote`

---

## 2025-12-16: Remove URL lines from daily note after successful summarization

**Goal:** After successfully generating a summary for a URL, automatically delete the original URL line from the daily note to avoid duplicate processing and keep the note clean.

**Changes:**

### `summarize_links/notes.py`
- Added `remove_url_line_from_note()` function that:
  - Finds lines containing the URL in the daily note
  - Removes those lines from the content
  - Preserves trailing newline if the original had one
  - Handles URLs in subfolders
  - Returns `True` if line(s) were removed, `False` otherwise

### `summarize_links/cli.py`
- Updated `_process_url_with_metadata()` to return a 3-tuple: `(success, message, should_delete_source)`
  - `should_delete_source` is `True` only when a new summary is created (not skipped, not dry-run, not error)
- Updated `_process_urls_with_metadata()` to:
  - Track URLs that were successfully processed
  - After all processing completes, delete the original URL lines from the daily note
  - Only perform deletion when not in dry-run mode and when there's a source daily note

**Behavior:**
- URL lines are deleted only after successful summary generation
- Skipped URLs (already exist) are NOT deleted
- Failed URLs (fetch error, API error, etc.) are NOT deleted
- Dry-run mode shows what would happen but doesn't delete anything
- The `urls` command (no daily note context) doesn't delete anything
- Cleanup message displayed: "Cleaning up N processed URLs from daily note..."

**Safety considerations:**
- Deletion happens AFTER all processing is complete
- Each URL is removed individually with error handling
- If removal fails for one URL, others still get processed
- Original note structure is preserved (only the specific lines are removed)

**Tests:** Added 8 new tests in `tests/test_notes.py` for `TestRemoveUrlLineFromNote`:
- `test_remove_bare_url_line` - Basic URL removal
- `test_remove_markdown_link_line` - Markdown link removal
- `test_remove_url_in_subfolder` - Works with daily notes in subfolders
- `test_return_false_if_url_not_found` - Handles missing URLs gracefully
- `test_return_false_if_note_not_found` - Handles missing notes gracefully
- `test_preserves_trailing_newline` - Maintains file formatting
- `test_removes_all_lines_with_same_url` - Handles duplicate URLs
- `test_handles_url_with_query_params` - Works with complex URLs

Added 5 tests in `tests/test_cli.py` for `TestUrlLineDeletion`:
- `test_mock_mode_does_not_delete_url_lines` - Mock mode preserves URLs
- `test_real_mode_deletes_url_lines` - Real mode deletes URLs
- `test_dry_run_does_not_delete_url_lines` - Dry run preserves URLs
- `test_skipped_urls_not_deleted` - Existing summaries don't trigger deletion
- `test_failed_urls_not_deleted` - Errors don't trigger deletion

---

## 2025-12-16: Fix reprocessing mocked summaries not overwriting

**Goal:** Fix bug where rerunning without `--mock` after a mock run would delete URLs but not update the mocked summaries.

**Problem:**
1. `summary_exists()` correctly returns `False` for mocked summaries (so they get reprocessed)
2. The URL gets fetched, content extracted, Gemini called
3. `write_summary_note_with_metadata()` was called with `overwrite=config.force` (which is `False`)
4. But the file exists on disk, so `write_summary_note_with_metadata()` silently skips writing
5. The function still returns success, so `should_delete=True` and URLs get deleted
6. Result: URLs deleted but mocked summaries never updated

**Fix:**
- Added `needs_overwrite` flag in `_process_url_with_metadata()` that is `True` when:
  - `config.force` is set, OR
  - `summary_exists()` returns `False` (meaning the existing file is mocked/error and needs replacement)
- Pass `needs_overwrite` to `write_summary_note_with_metadata()` instead of `config.force`

**Tests:** Added `test_reprocessing_mocked_summary_overwrites` in `tests/test_cli.py` (247 tests total)
