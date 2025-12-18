# Task Log

This document tracks completed development tasks for the Obsidian Link Summarizer.

---

## 2025-12-18: Test Coverage Improvement Initiative

**Goal:** Increase test coverage from 85% to 91%+ by adding comprehensive tests for identified gaps.

**Coverage Before:** 85% overall
**Coverage After:** 91% overall

**Module-by-Module Improvements:**

| Module | Before | After |
|--------|--------|-------|
| extract.py | 75% | 88% |
| cli.py | 81% | 87% |
| gemini_client.py | 89% | 93% |
| config.py | 88% | 98% |

**Changes:**

### `tests/test_extraction.py` (+21 tests, +278 lines)
- `TestPaywallDetection`: 6 tests for paywall domain detection and HTTP error formatting
- `TestMarkdownExtraction`: 6 tests for markdown metadata and content extraction
- `TestNonContentFiltering`: 5 tests for protected tags and element removal
- `TestFetchAndExtract`: 4 tests for full extraction pipeline edge cases

### `tests/test_cli.py` (+4 tests, +108 lines)
- `TestCmdStatus`: 2 tests for rate limit status display
- `TestQuietMode`: 1 test for quiet mode suppression
- `TestInvalidUrlHandling`: 1 test for graceful URL failure handling

### `tests/test_gemini.py` (+8 tests, +165 lines)
- `TestRateLimitWaitCalculation`: 3 tests for wait time calculations
- `TestTokenUsageExtraction`: 2 tests for token count extraction from responses
- `TestRetryOnGenericAPIError`: 3 tests for retry behavior on API errors

### `tests/test_config.py` (+10 tests, +168 lines)
- Rate limit configuration: 3 tests for YAML and environment variable loading
- `setup_logging`: 4 tests for verbose mode and log levels
- `daily_notes_folder`: 3 tests for path handling

**Performance Fix:**
- Patched `time.sleep` in retry tests to eliminate 3s wait times per test
- Test suite now runs in ~4.6s instead of ~12s

**Documentation:**
- Created [test-coverage-plan.md](test-coverage-plan.md) with detailed implementation plan

**Tests:** 371 total tests passing (up from 328)

---

## 2025-12-16: Add --all flag to from-note command

**Goal:** Process all daily notes with URLs in a single command.

**Changes:**
- Added `--all` flag to `from-note` subcommand in `cli.py`
- Created `cmd_from_note_all()` function to iterate through all daily notes
- Processes notes in chronological order (oldest first)
- Respects `--max-links` limit across all notes combined

**Usage:**
```bash
# Process all daily notes with URLs
summarize-links from-note --all

# Limit total links processed across all notes
summarize-links from-note --all --max-links 50

# Dry run to see what would be processed
summarize-links from-note --all --dry-run
```

**Tests:** Added `TestCmdFromNoteAll` class with 3 tests

---

## 2025-12-16: URL tracking parameter cleanup

**Goal:** Remove tracking parameters (UTM tags, analytics IDs) from URLs while preserving meaningful query strings.

**Changes:**
- Added `clean_url()` function in `summarize_links/notes.py`
- Defined `TRACKING_PARAMS` set: utm_*, ref, fbclid, gclid, m, st, etc.
- Defined `MEANINGFUL_PARAMS` dict for domain-specific params to preserve (YouTube v/t/list, GitHub tab/comments)
- Defined `NOISE_FRAGMENTS` set: #atom-everything, #rss
- Integrated URL cleaning into `extract_urls()` and `extract_urls_with_context()`

**Behavior:**
- Strips all tracking parameters from URLs automatically
- Preserves meaningful params (e.g., `?v=xxx` on youtube.com, `?tab=` on github.com)
- Removes noise URL fragments from RSS feeds
- Cleaned 10 existing summary files with tracking URLs

**Tests:** Added `TestCleanUrl` class with 11 tests covering various URL patterns

---

## 2025-12-16: Markdown file URL support

**Goal:** Support direct `.md` file URLs (e.g., GitHub raw markdown, personal sites with .md pages).

**Changes:**
- Added `fetch_content()` function in `summarize_links/extract.py` that returns (content, content_type)
- Added `_extract_markdown_metadata()` to parse title/author from markdown frontmatter or H1
- Added `_clean_markdown()` to remove image tags from markdown content
- Updated `extract_readable_content()` to handle markdown content directly

**Behavior:**
- Detects .md URLs and text/markdown content-type
- Extracts title from YAML frontmatter or first H1 heading
- Passes cleaned markdown directly to Gemini (no HTML parsing needed)

---

## 2025-12-16: Improved content extraction with parser fallback

**Goal:** Handle malformed HTML (especially Blogspot) that causes lxml parser to fail.

**Changes:**
- Added html5lib as fallback parser in `extract.py`
- Created `_extract_with_parser()` helper for parser-specific extraction
- Try lxml first (fast), fall back to html5lib if no content extracted
- Added `protected_tags` set to never remove critical elements (body, html, article, main)
- Extract article/main content BEFORE removing nav/header/footer elements

**Behavior:**
- lxml handles well-formed HTML quickly
- html5lib handles malformed Blogspot/legacy pages
- Protected tags prevent accidental removal of body element
- Pre-extraction of article content preserves content nested in nav/header

**Tests:** All 270 tests passing

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

---

## 2025-12-16: Add 'list' command to show daily notes with URLs

**Goal:** Add a new CLI command `list` that scans all daily notes and displays which dates have URLs in them.

**Changes:**

### `summarize_links/notes.py`
- Added `find_daily_notes_with_urls()` function that:
  - Scans the daily notes folder for files matching `YYYY-MM-DD.md` pattern
  - Extracts URLs from each note using `extract_urls()`
  - Returns list of tuples `(date_string, url_count)` sorted by date descending
  - Respects `daily_notes_folder` configuration setting
  - Handles missing folders gracefully

### `summarize_links/cli.py`
- Added `list` subcommand to argument parser
- Added `cmd_list()` function that:
  - Calls `find_daily_notes_with_urls()` with current config
  - Displays results in a Rich table with Date and URL count columns
  - Shows total count of notes and URLs at the bottom
- Updated command dispatcher in `main()` to handle `list` command
- Updated help examples to include the `list` command

**Usage:**
```bash
summarize-links --vault /path/to/vault list
```

**Output Example:**
```
Scanning daily notes for URLs...
       Daily Notes with URLs
┏━━━━━━━━━━━━┳━━━━━━┓
┃ Date       ┃ URLs ┃
┡━━━━━━━━━━━━╇━━━━━━┩
│ 2025-12-16 │    3 │
│ 2025-12-15 │    5 │
│ 2025-12-14 │    2 │
└────────────┴──────┘

Total: 3 notes with 10 URLs
```

**Tests:** Added 9 new tests:
- `tests/test_notes.py::TestFindDailyNotesWithUrls`:
  - `test_find_notes_with_urls` - Basic functionality
  - `test_sorted_by_date_descending` - Correct sort order
  - `test_ignores_non_daily_note_files` - Only YYYY-MM-DD.md files
  - `test_handles_daily_notes_subfolder` - Works with configured subfolder
  - `test_returns_empty_for_no_urls` - Empty result when no URLs
  - `test_returns_empty_for_missing_folder` - Handles missing folder
- `tests/test_cli.py`:
  - `TestCreateParser::test_list_command` - Parser test
  - `TestCmdList::test_list_notes_with_urls` - Command handler test
  - `TestCmdList::test_list_no_notes_with_urls` - Empty result test
  - `TestCmdList::test_list_with_daily_notes_folder` - Subfolder test

Total tests: 257

---

## 2025-12-16: Use daily note date for summary filenames

**Goal:** When generating summaries from a daily note, use the date from the daily note in the summary filename instead of the current date.

**Problem:**
Previously, running `summarize-links from-note --date 2025-12-12` would create files named `2025-12-16-slug.md` (today's date) instead of `2025-12-12-slug.md` (the daily note's date).

**Changes:**

### `summarize_links/cli.py`
- Added `source_date` parameter to `_process_url()`:
  - Passes date to `summary_exists()` for correct duplicate detection
  - Passes date to `write_summary_note()` for correct filename
  - Passes date to `write_stub_note()` for error stubs

- Added `source_date` parameter to `_process_url_with_metadata()`:
  - Passes date to `summary_exists()` for correct duplicate detection
  - Passes date to `write_summary_note_with_metadata()` for correct filename
  - Passes date to `write_stub_note()` for error stubs

- Added `source_date` parameter to `_process_urls_with_metadata()`:
  - Accepts the date and passes it through to `_process_url_with_metadata()`

- Updated `cmd_from_note()`:
  - Converts the parsed date to a `datetime` object
  - Passes `source_date` to `_process_urls_with_metadata()`

**Behavior:**
- `from-note --date 2025-12-12` creates files like `2025-12-12-slug.md`
- `from-note` (no date) uses today's date for both note lookup and filename
- `urls` command still uses today's date (no daily note context)
- Duplicate detection now correctly checks for files with the matching date

**Tests:** All 259 existing tests pass

---

## 2025-12-16: Fix content extraction errors for multiple sites

**Goal:** Fix "No readable content found in page" errors occurring on various websites including rivercottage.net, blogspot.com, infoworld.com, and others.

**Root Causes Identified:**

1. **Body element being removed** - Sites with CSS framework classes like `understrap-no-sidebar` were matching the `\bsidebar\b` pattern, causing the entire `<body>` element to be removed.

2. **Content inside nav/header elements** - Some sites (like infoworld.com) wrap their `<article>` content inside `<header>` or `<nav>` elements. Removing these parent elements first destroyed the content.

3. **Malformed HTML** - Blogspot/Blogger pages have HTML that the `lxml` parser can't handle correctly, resulting in 0 characters of body text.

**Changes in `summarize_links/extract.py`:**

### Fix 1: Protected Critical Elements
- Added `protected_tags = {"html", "body", "article", "main"}` set
- These elements are never removed even if they match non-content patterns
- Prevents false positives from CSS framework class names

### Fix 2: Extract Article Content Before Cleanup
- Moved `_extract_article_content()` call to happen BEFORE removing nav/header/footer elements
- If article content is found, return it immediately without aggressive cleanup
- Only perform cleanup when falling back to largest text block extraction

### Fix 3: Parser Fallback
- Refactored `extract_readable_content()` to try multiple parsers
- New `_extract_with_parser()` helper function handles extraction with a specific parser
- Tries `lxml` first (faster), falls back to `html5lib` if no content found
- Added `html5lib` as a project dependency

**Results:**
| URL | Before | After |
|-----|--------|-------|
| rivercottage.net/recipes/* | ❌ Error | ✅ Works |
| infoworld.com | ❌ Error | ✅ Works |
| klaraslife.com | ❌ Error | ✅ Works |
| dev.to | ✅ Works | ✅ Works |
| redmonk.com | ✅ Works | ✅ Works |
| blogspot.com | ❌ Error | ✅ Works |
| danfu.org | ❌ Error | ❌ JS-rendered* |

*danfu.org uses client-side JavaScript to fetch and render Markdown content. This requires a headless browser to extract and is not fixable with the current approach.

**Tests:** All 259 tests pass

---

## 2025-12-16: Gemini API Rate Limiting

**Goal:** Implement rate limiting to stay within Gemini API free tier quotas:
- 5 requests per minute (RPM)
- 250,000 tokens per minute (TPM)
- 20 requests per day

**Changes:**

### New Module: `summarize_links/rate_limiter.py`
- Created `RateLimiter` class with sliding window rate limiting for RPM/TPM
- `RateLimitState` dataclass for persistent daily counter storage
- Token estimation using ~4 chars per token plus overhead
- Automatic waiting when approaching limits (`wait_if_needed()`)
- Persistent daily request counter stored in `.summarizer-rate-limit.json`
- Daily counter automatically resets when date changes
- Thread-safe implementation with locking

### Config Constants: `summarize_links/config.py`
- Added `GEMINI_RPM_LIMIT = 5` (requests per minute)
- Added `GEMINI_TPM_LIMIT = 250000` (tokens per minute)
- Added `GEMINI_DAILY_LIMIT = 20` (requests per day)

### Client Integration: `summarize_links/gemini_client.py`
- `GeminiClient` now accepts optional `rate_limiter` and `state_path` parameters
- Before each API call, estimates tokens and waits if needed
- After each successful call, records the request for rate tracking
- Tries to use actual token count from API response when available
- Falls back to estimate if response metadata unavailable

### New CLI Command: `summarize-links status`
- Shows current rate limit usage in a Rich table
- Displays RPM, TPM, and daily usage with remaining quota
- Warns when daily limit is low (<50 remaining)
- Errors when daily limit is exhausted

### CLI Integration: `summarize_links/cli.py`
- Updated `create_client()` calls to pass `state_path=config.vault_path`
- Rate limit state persisted in vault directory
- Added `cmd_status()` handler and dispatch

**Behavior:**
- Automatically waits when RPM or TPM limits approached
- Raises `RateLimitError` if daily limit exceeded (cannot wait for day change)
- Logs rate limit status and wait times at INFO level
- State persists across runs to track daily usage accurately

**Usage:**
```bash
# Check current rate limit status
summarize-links --vault /path/to/vault status

# Output:
# Gemini API Rate Limit Status
#
#        Current Usage
# ┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
# ┃ Limit Type            ┃ Used ┃ Limit   ┃ Remaining ┃
# ┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━┩
# │ Requests/Minute (RPM) │    2 │       5 │         3 │
# │ Tokens/Minute (TPM)   │ 5000 │ 250,000 │   245,000 │
# │ Requests/Day          │   15 │      20 │         5 │
# └───────────────────────┴──────┴─────────┴───────────┘
```

**Tests:** Added 20 tests in `tests/test_rate_limiter.py`:
- `TestRateLimitState`: serialization/deserialization (3 tests)
- `TestRateLimiter`: limit checking, recording, status (10 tests)
- `TestPersistentState`: file I/O, day reset, error handling (4 tests)
- `TestGlobalRateLimiter`: singleton behavior (2 tests)

Total tests: 293

---

## 2025-12-16: Configurable Rate Limits

**Goal:** Make rate limits configurable via environment variables and YAML config, allowing users to adjust for paid API tiers.

**Changes:**

### Config Updates: `summarize_links/config.py`
- Added `rpm_limit`, `tpm_limit`, `daily_limit` fields to `Config` dataclass
- Fields default to constants: `GEMINI_RPM_LIMIT`, `GEMINI_TPM_LIMIT`, `GEMINI_DAILY_LIMIT`
- Load from environment variables: `GEMINI_RPM_LIMIT`, `GEMINI_TPM_LIMIT`, `GEMINI_DAILY_LIMIT`
- Load from YAML config: `rpm_limit`, `tpm_limit`, `daily_limit`
- YAML takes precedence over environment variables

### Rate Limiter Updates: `summarize_links/rate_limiter.py`
- Updated `get_rate_limiter()` to accept optional `rpm_limit`, `tpm_limit`, `daily_limit` parameters
- Parameters passed through to `RateLimiter` constructor when provided
- Added debug logging showing configured limits on initialization

### Client Updates: `summarize_links/gemini_client.py`
- Updated `GeminiClient.__init__()` to accept `rpm_limit`, `tpm_limit`, `daily_limit` parameters
- Updated `create_client()` factory to accept and pass through limit parameters
- Limits passed to `get_rate_limiter()` call

### CLI Updates: `summarize_links/cli.py`
- Updated `cmd_status()` to pass config limits when getting rate limiter
- Updated both `create_client()` calls to pass config limits

### Documentation: `README.md`
- Added `GEMINI_RPM_LIMIT`, `GEMINI_TPM_LIMIT`, `GEMINI_DAILY_LIMIT` to environment variables table
- Added rate limit config example in YAML section
- Added note about customizing for paid tiers

**Usage:**

Via environment variables:
```bash
export GEMINI_RPM_LIMIT=60
export GEMINI_TPM_LIMIT=1000000
export GEMINI_DAILY_LIMIT=10000
summarize-links from-note
```

Via YAML config (`.summarizer-config.yaml`):
```yaml
rpm_limit: 60
tpm_limit: 1000000
daily_limit: 10000
```

**Tests:** All 293 existing tests pass
---

## 2025-12-16: Improved HTTP headers and error messages for content fetching

**Goal:** Improve success rate for fetching URLs by using more browser-like headers, and provide clearer error messages for failures.

**Changes in `summarize_links/extract.py`:**

### Browser-like Headers
- Updated Chrome version from 120 to 131 in User-Agent
- Added full `BROWSER_HEADERS` dictionary with modern browser fingerprint:
  - `Sec-Fetch-*` headers (Dest, Mode, Site, User)
  - `Sec-Ch-Ua` client hints for Chrome 131
  - `Accept-Encoding: gzip, deflate, br`
  - `Cache-Control` and `Upgrade-Insecure-Requests`
- Created `_create_session()` helper using `requests.Session()` for cookie persistence
- Added dynamic `Referer` header based on target domain

### Descriptive HTTP Error Messages
- Added `HTTP_ERROR_MESSAGES` dictionary with user-friendly explanations:
  - 401: "Authentication required - likely paywalled content"
  - 403: "Access forbidden (site may block automated requests)"
  - 404: "Page not found (URL may be incorrect or content removed)"
  - 429: "Too many requests (rate limited by server)"
  - 5xx: Server error messages

### Paywall Site Detection
- Added `PAYWALL_DOMAINS` dictionary with 13 known paywall sites:
  - WSJ, NYT, FT, Economist, Bloomberg, Washington Post
  - The Athletic, The Times UK, Telegraph, HBR
  - Medium, Seeking Alpha, Barron's
- Created `_get_paywall_info()` to detect known paywall domains
- Updated `_format_http_error()` to show specific paywall messages for 401/403 errors

**Example Error Messages:**
| URL | Old Message | New Message |
|-----|-------------|-------------|
| wsj.com | `HTTP error 401 for URL` | `HTTP 401: Paywall - Wall Street Journal (subscription required)` |
| medium.com | `HTTP error 403 for URL` | `HTTP 403: Paywall - Medium (may require membership for some articles)` |
| simonwillison.net (404) | `HTTP error 404 for URL` | `HTTP 404: Page not found (URL may be incorrect or content removed)` |

**Tests:** All 293 existing tests pass

---

## 2025-12-17: Fix URL removal when query params get normalized

**Goal:** Fix bug where URLs with empty query parameter values (like `?2138`) were not being removed from daily notes after summarization.

**Problem:**
When a URL like `https://www.lukew.com/ff/entry.asp?2138` is processed:
1. The regex extracts it correctly from the note
2. `clean_url()` passes it through `parse_qs()` and `urlencode()`, which normalizes `?2138` to `?2138=` (adding trailing `=`)
3. The cleaned URL `?2138=` is stored and used for all subsequent operations
4. When trying to find/remove the URL from the note, `?2138=` doesn't match the original `?2138`
5. Log shows: "URL not found in note, nothing to remove"

**Solution:**
Store the original URL (before cleaning) alongside the cleaned URL, and use the original for note operations.

**Changes:**

### `summarize_links/models.py`
- Added `original_url` field to `UrlWithContext` dataclass
- Default value is empty string for backward compatibility
- Docstring updated to explain the two URL fields

### `summarize_links/notes.py`
- Updated `extract_urls_with_context()` to:
  - Store the URL before cleaning as `original_url`
  - Store the cleaned URL as `url`
  - Both are populated in the `UrlWithContext` object

### `summarize_links/cli.py`
- Updated `_process_url_with_metadata()` to use `original_url` (falling back to `url`) when calling `add_summary_link_to_daily_note()`
- Updated `_process_batch_with_metadata()` to store `original_url` (falling back to `url`) in `urls_to_delete` list

**Behavior:**
- `url` field: Cleaned URL used for fetching, slug generation, duplicate detection
- `original_url` field: Original URL as it appears in the note, used for finding/removing lines

**Tests:** Added 3 new tests:
- `test_models.py::TestUrlWithContext::test_original_url_differs_from_cleaned` - Model field test
- `test_notes.py::TestExtractUrlsWithContext::test_original_url_preserved_when_cleaning_normalizes` - Regression test for `?key` → `?key=` normalization
- `test_notes.py::TestExtractUrlsWithContext::test_original_url_same_when_no_normalization` - Normal case test

Total tests: 296

---

## 2025-12-18: Improved handling of malformed JSON responses from Gemini

**Goal:** Fix issue where Gemini returns JSON with unescaped quotes or other invalid characters in the summary field, causing JSON parsing to fail and fall back to raw text (which includes JSON structure).

**Problem:**
When summarizing content with lots of quoted text or code examples (like https://mays.co/optimizing-claude-code), Gemini sometimes returns JSON with unescaped characters:
```json
{"summary": "This article talks about "Claude Code" and how...", ...}
```
The error: `Expecting ',' delimiter: line 2 column 1766 (char 1767)`

The previous fallback just used the entire raw response as the summary, which wasn't useful.

**Solution:**
Added regex-based extraction functions that can recover the summary, tags, and content type even when JSON parsing fails.

**Changes in `summarize_links/gemini_client.py`:**

### New Functions
- `_extract_summary_from_malformed_json()`: Uses multiple regex patterns to extract the summary field value:
  - Tries to match summary ending at next field (`suggested_tags` or `content_type`)
  - Falls back to finding end patterns like `", "suggested_tags"`
  - Unescapes common JSON escape sequences (`\\n`, `\\"`, etc.)
  - Returns `None` if extraction fails

- `_extract_tags_from_malformed_json()`: Extracts the `suggested_tags` array using regex:
  - Finds content inside `"suggested_tags": [...]`
  - Extracts all quoted strings from the array
  - Returns empty list if not found

- `_extract_content_type_from_malformed_json()`: Extracts the `content_type` field:
  - Simple pattern match for `"content_type": "value"`
  - Validates against `CONTENT_TYPES` constant
  - Returns `"article"` as default

### Updated `_parse_gemini_response()`
- Now attempts field extraction when `json.loads()` fails
- Uses the new extraction functions to recover what it can
- Logs success/failure of extraction attempts
- Only falls back to raw text if extraction completely fails

**Behavior:**
- JSON parsing still tried first (most responses are valid)
- On JSON error, extraction functions attempt field-by-field recovery
- Tags and content type often recoverable even when summary has issues
- Graceful degradation: partial success better than complete failure

**Tests:** Added `TestMalformedJsonExtraction` class with 12 tests:
- `test_extract_summary_basic` - Unescaped quotes in summary
- `test_extract_summary_with_code_blocks` - Code blocks in summary
- `test_extract_summary_with_newlines` - Escaped newlines
- `test_extract_summary_returns_none_for_no_summary` - Missing field
- `test_extract_tags_basic` - Tag array extraction
- `test_extract_tags_empty_array` - Empty tags
- `test_extract_tags_no_field` - Missing tags field
- `test_extract_content_type_basic` - Content type extraction
- `test_extract_content_type_invalid` - Invalid content type
- `test_extract_content_type_missing` - Missing content type
- `test_parse_gemini_response_uses_extraction_on_malformed_json` - Integration test
- `test_parse_gemini_response_with_multiline_code_in_summary` - Curly braces in code

Total tests: 308

---

## 2025-12-18: Technical Debt Cleanup - Phase 1

**Goal:** Remove legacy code duplication and improve code quality as identified in technical-debt-plan.md.

**Changes:**

### Removed Legacy Functions (`summarize_links/cli.py`)
- Removed `_process_url()` (legacy function without metadata support)
- Removed `_process_urls()` (legacy batch processor without metadata)
- These were 90%+ duplicated with `_process_url_with_metadata()` and `_process_urls_with_metadata()`
- All code paths now use the metadata versions
- Removed ~150 lines of duplicated code

### Cleaned Up Imports
- Removed unused imports: `fetch_and_extract`, `truncate_content`, `write_summary_note`
- These were only used by the removed legacy functions

### Updated Tests (`tests/test_cli.py`)
- Renamed `TestProcessUrl` to `TestProcessUrlWithMetadata`
- Updated all tests to use `_process_url_with_metadata()` with `UrlWithContext`
- Tests now verify 3-tuple return value `(success, message, should_delete)`
- Added imports for `PageMetadata`, `SummaryResult`, `UrlWithContext` at module level
- Removed redundant local imports in test functions

### Removed Duplicate Test Fixture
- Removed local `mock_vault` fixture from `TestUrlLineDeletion` class
- Now uses the global fixture from `conftest.py`

### Code Quality Improvements
- Added `py.typed` marker file for PEP 561 compliance
- Added `DEFAULT_MAX_TAGS` constant (was hardcoded as 10 in multiple places)
- Updated `MAX_CONTENT_LENGTH` to use underscore separator for readability (50_000)
- Updated `models.py`, `notes.py`, `config.py` to use `DEFAULT_MAX_TAGS` constant

### Config Validation
- `load_config()` now automatically calls `config.validate()` before returning
- Previously validation could be skipped, leading to late failures
- Errors now surface immediately with clear messages

### Rate Limiter Cleanup
- Removed redundant mutable default reinitializations in `RateLimiter.__post_init__`
- `default_factory` already handles this correctly in dataclasses

**Technical Debt Issues Addressed:**
- Issue #1: Duplicate `_process_url` and `_process_url_with_metadata` ✓
- Issue #2: Duplicate `_process_urls` and `_process_urls_with_metadata` ✓
- Issue #3: Duplicate `mock_vault` fixture ✓
- Issue #6: Unused `_process_urls` function ✓
- Issue #7: Duplicate import patterns ✓
- Issue #12: Magic numbers (max_tags) ✓
- Issue #15: Missing py.typed marker ✓
- Issue #18: Mutable default reinit ✓
- Issue #26: Config validation too late ✓

**Tests:** All 308 tests pass

---

## 2025-12-18: Technical Debt Cleanup - Medium Priority Issues

**Goal:** Address medium priority issues #5, #10, #11 from technical-debt-plan.md.

**Changes:**

### Issue #5: Inconsistent Function Signatures
- Already addressed in Phase 2 when `write_summary_note()` docstring was updated
- Marked as completed in tech debt plan

### Issue #10: HTTP Retry Strategy (`summarize_links/extract.py`)
Added retry logic for transient HTTP errors using `tenacity` library:

- Created `_RetryableError` internal exception for retry-eligible errors
- Added `_log_retry()` callback for logging retry attempts
- Created `_fetch_with_retry()` function with tenacity decorator:
  - Retries on connection errors (`requests.RequestException`)
  - Retries on timeouts
  - Retries on 5xx server errors (wrapped in `_RetryableError`)
  - Does NOT retry 4xx client errors (these are not transient)
  - Max 3 attempts with exponential backoff (1-4 second wait)
- Updated `fetch_content()` to use the retry wrapper

**New Constants:**
- `HTTP_RETRY_ATTEMPTS = 3`
- `HTTP_RETRY_WAIT_MIN = 1` (seconds)
- `HTTP_RETRY_WAIT_MAX = 4` (seconds)

### Issue #11: Logging Patterns - Quiet Flag (`summarize_links/cli.py`)
Added `--quiet` / `-q` flag to suppress non-error console output:

- Added `_quiet_mode` global flag
- Created `_print(message, **kwargs)` helper that respects quiet mode
- Created `_print_error(message, **kwargs)` helper that always prints (for errors)
- Replaced all `console.print()` calls with appropriate helpers:
  - Normal status output → `_print()`
  - Error messages → `_print_error()`
  - Progress bars and tables → `_print()`
- Added `-q/--quiet` CLI argument

**Behavior:**
- `--quiet` suppresses informational output (dry-run warnings, progress, tables)
- Errors always shown regardless of quiet mode
- Useful for scripting and automation

### Dependencies Added (`pyproject.toml`)
- `tenacity>=9.1.2` - Retry logic with decorators
- `pytest-mock>=3.15.1` - Testing retry behavior (dev dependency)

### Tests Added
**`tests/test_extraction.py`** - `TestFetchContentRetry` class:
- `test_retry_on_connection_error` - Verifies 3 attempts on network error
- `test_no_retry_on_client_error` - Verifies single attempt on 404
- `test_retry_on_server_error` - Verifies retry on 500
- `test_exhausted_retries_raises_error` - Verifies `ContentFetchError` after all retries

**`tests/test_cli.py`** - Updated `TestCreateParser`:
- Added tests for `--quiet` and `-q` flag parsing

**Total tests:** 312 passing

**Technical Debt Plan Updates:**
Marked Issues #5, #10, #11 as ✅ Done in `docs/technical-debt-plan.md`