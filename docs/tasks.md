# Task Log

This document tracks completed development tasks for the Obsidian Link Summarizer.

---

## 2025-12-30: Set up Copilot Instructions

**Goal:** Configure GitHub Copilot coding agent instructions following best practices documented at https://gh.io/copilot-coding-agent-tips.

**Changes:**

### Created `.github/copilot-instructions.md` (373 lines)
Comprehensive guidance document for GitHub Copilot coding agent including:

**Project Understanding:**
- Project overview and key features
- Architecture explanation (modules, design patterns, data flow)
- Technology stack (Python 3.11+, uv, pytest, ruff, mypy)

**Development Workflow:**
- Environment setup commands
- Building and testing procedures (pytest, coverage)
- Mandatory linting workflow (ruff check, ruff format, mypy)
- Common CLI commands for testing

**Code Conventions:**
- Reference to `/AGENTS.md` for detailed build guidelines
- Python-specific patterns (type hints, dependency injection, named constants)
- Custom exceptions for error handling
- Idempotency and graceful degradation principles
- Git commit message format (conventional commits)

**Testing Practices:**
- Test structure and organization
- Unit test patterns with mocks
- Integration test approaches
- Running test commands

**Configuration Management:**
- Priority order: CLI args > env vars > YAML > defaults
- Environment variables reference
- Vault YAML config file format

**Common Patterns:**
- Adding new LLM providers
- Adding CLI commands
- Modifying configuration
- Error handling patterns

**Development Tips:**
- Common pitfalls and solutions
- Security considerations
- When to use each tool/pattern

**Benefits:**
- Helps Copilot understand project structure and conventions
- Reduces need for repetitive explanations
- Ensures consistent coding patterns across tasks
- Improves quality of AI-generated code
- Provides quick reference for human developers too

**Verification:**
- Fixed spelling consistency (use American "Summarizer" to match codebase)
- Verified all referenced files and commands are accurate
- Confirmed alignment with existing documentation (AGENTS.md, README.md)

---

## 2025-12-29: Send Raw LLM Request/Response to Langfuse

**Issue:** Following user feedback and Langfuse best practices, generation traces should capture the **actual** LLM input/output (raw prompt and response), not metadata about them. This enables true LLM-as-a-Judge evaluation, prompt optimization, and debugging of actual model behavior.

**Changes:**

1. **Enhanced SummaryResult model** in [summarize_links/models.py](summarize_links/models.py):
   - Added `raw_prompt: str | None` field to store the complete prompt sent to LLM
   - Added `raw_response: str | None` field to store the unmodified model response
   - Updated docstring to document these tracing-specific fields

2. **Updated GeminiClient** in [summarize_links/gemini_client.py](summarize_links/gemini_client.py):
   - Modified `summarize_with_metadata()` to capture and store `raw_prompt`
   - Captures `raw_response` (the JSON string from Gemini)
   - These fields are populated before parsing/processing

3. **Updated OllamaClient** in [summarize_links/ollama_client.py](summarize_links/ollama_client.py):
   - Modified `summarize_with_metadata()` to capture and store `full_prompt`
   - Captures `raw_response` (the JSON string from Ollama)
   - Consistent with GeminiClient implementation

4. **Refactored CLI Langfuse integration** in [summarize_links/cli.py](summarize_links/cli.py):
   - Changed `input` to send `raw_prompt` (actual text sent to LLM)
   - Changed `output` to send `raw_response` (actual text from LLM)
   - Moved contextual information to `metadata`:
     - URL, title, content_length
     - Parsed results (tags, content_type, summary_length)
   - Usage details remain in `usage_details` field

5. **Updated documentation** in [summarize_links/langfuse_tracer.py](summarize_links/langfuse_tracer.py):
   - Clarified that Input = raw prompt text
   - Clarified that Output = raw response text (before parsing)
   - Documented that Metadata = contextual information and parsed results
   - Explained benefits of capturing actual LLM I/O

**Data Structure (Before vs After):**

Before (metadata only):
```python
# Input
{
    "url": "https://example.com",
    "title": "Article Title",
    "content_length": 5234,
    "content_preview": "First 500 chars..."
}

# Output
{
    "summary": "# Parsed Summary...",
    "suggested_tags": ["python", "testing"],
    "content_type": "article",
    "summary_length": 842
}
```

After (raw LLM I/O):
```python
# Input (actual prompt sent to LLM)
"Summarize the following web page content titled 'Article Title'.\n\nSource URL: https://example.com\n\nContent:\n[full content]\n\nRemember to respond with valid JSON..."

# Output (raw JSON string from LLM)
'{\n  "summary": "# Article Title\\n\\n...",\n  "suggested_tags": ["python", "testing"],\n  "content_type": "article"\n}'

# Metadata (context and parsed results)
{
    "url": "https://example.com",
    "title": "Article Title",
    "content_length": 5234,
    "parsed_tags": ["python", "testing"],
    "parsed_content_type": "article",
    "summary_length": 842
}
```

**Benefits:**
- **LLM-as-a-Judge**: Can evaluate actual model outputs, not parsed versions
- **Prompt Engineering**: See exactly what text the model receives
- **Debugging**: Identify parsing issues vs model issues
- **Reproducibility**: Have complete input/output for replay/testing
- **Evaluation**: Run quality assessments on real model behavior
- **Optimization**: A/B test actual prompts and see raw responses

**Verification:**
- All 499 tests pass
- Static analysis (ruff check, ruff format, mypy) passes
- No breaking changes to existing functionality
- Backward compatible (raw fields are optional)

---

## 2025-12-29: Enhanced Langfuse Data Capture for Comprehensive LLM Tracing

**Note:** This task was superseded by the "Send Raw LLM Request/Response" task above, which correctly implements Langfuse best practices.

---

## 2025-12-29: Change Error Frontmatter from `status: error` to `summary_status: <error_type>`

**Issue:** Error stub notes were using the legacy frontmatter key `status: error`, which was inconsistent with the modern `summary_status` key used for successful summaries. Additionally, there was no differentiation between different types of errors (fetch errors, extraction errors, API errors, etc.).

**Changes:**

1. **Updated `write_stub_note()` function** in [summarize_links/notes.py](summarize_links/notes.py):
   - Added new `error_type` parameter (default: "error")
   - Changed from `status="error"` to `summary_status=error_type`
   - Now allows specific error types like "fetch_error", "extraction_error", "api_error", etc.

2. **Updated `write_summary_note()` function** in [summarize_links/notes.py](summarize_links/notes.py):
   - Changed parameter name from `status` to `summary_status`
   - Changed frontmatter key from `status:` to `summary_status:`
   - Updated docstring to reflect new parameter name

3. **Updated `summary_exists()` function** in [summarize_links/notes.py](summarize_links/notes.py):
   - Added detection for new format: `summary_status: <value>` where value contains "error" or equals "mocked"
   - Maintained backward compatibility with legacy format (`status: error`, `status: mocked`)
   - More robust parsing that checks line-by-line for summary_status key

4. **Updated all `write_stub_note()` calls in CLI** ([summarize_links/cli.py](summarize_links/cli.py)):
   - `ContentFetchError` → `error_type="fetch_error"`
   - `ContentExtractionError` → `error_type="extraction_error"`
   - `RateLimitError` → `error_type="rate_limit_error"`
   - `OllamaServerError` → `error_type="ollama_error"`
   - `ModelNotInstalledError` → `error_type="model_error"`
   - `OllamaAPIError` → `error_type="ollama_error"`
   - `GeminiAPIError` → `error_type="api_error"`

**Benefits:**
- Consistent frontmatter structure across all summary notes
- Specific error types enable better error tracking and filtering
- Backward compatibility maintained for existing notes with legacy format
- Error notes can still be properly retried using `--all` or `--force` flags

**Verification:**
- All 499 tests pass
- Static analysis (ruff, mypy) passes
- Legacy format notes are still correctly identified as retriable

**Example frontmatter for fetch error:**
```yaml
---
source: https://example.com/article
date: 2025-12-29
summary_status: fetch_error
---
```

---

## 2025-12-29: Fix Langfuse Context Manager Exception Handling

**Issue:** When content extraction failed with `ContentExtractionError`, the Langfuse tracing context managers would raise `RuntimeError: generator didn't stop after throw()` instead of properly propagating the original exception.

**Root Cause:** The `@contextmanager` decorated functions in `langfuse_tracer.py` were catching exceptions and yielding None after the exception had already been thrown into the generator. This violated Python's generator protocol.

**Solution:**
- Modified `trace_url_processing()`, `trace_span()`, and `trace_generation()` context managers to properly propagate exceptions
- Changed exception handling to log warnings but re-raise the exception using `raise`
- Added `finally` block in `trace_url_processing()` to ensure Langfuse client flush happens even when exceptions occur
- Added test class `TestExceptionHandling` with 3 tests to verify exceptions propagate correctly through all context managers

**Changes:**
- `summarize_links/langfuse_tracer.py`: Fixed exception handling in all 3 context managers
- `tests/test_langfuse_tracer.py`: Added `TestExceptionHandling` class with 3 new tests

**Verification:**
- All 23 tests in `test_langfuse_tracer.py` pass
- Static analysis checks (ruff, mypy) pass
- Exception propagation now works correctly while still logging tracing failures

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

---

## 2025-12-18: Per-Model Rate Limits with Safety Margin

**Goal:** Implement per-model rate limiting with different limits for each Gemini model and a 10% safety margin to avoid hitting hard API limits.

**Implementation Plan:** See [per-model-rate-limits-plan.md](per-model-rate-limits-plan.md)

**Changes:**

### New Data Structures (`summarize_links/rate_limiter.py`)

- **`ModelRateLimits` dataclass** (frozen/immutable):
  - `rpm_limit`: Requests per minute
  - `tpm_limit`: Tokens per minute
  - `daily_limit`: Requests per day
  - `with_safety_margin()` method: Returns new limits at 90% of original

- **`SAFETY_MARGIN = 0.9`** constant for 10% buffer below actual API limits

- **Updated `RateLimitState`**:
  - Added `daily_requests_by_model: dict[str, int]` for per-model tracking
  - Added `get_daily_requests(model)` method
  - Added `increment_daily_requests(model)` method
  - Legacy `daily_requests` field maintained for backward compatibility

### Rate Limiter Updates (`summarize_links/rate_limiter.py`)

- **`RateLimiter` now uses `ModelRateLimits`**:
  - Constructor takes `model: str` and `limits: ModelRateLimits`
  - Safety margin automatically applied (controllable via `_apply_safety_margin`)
  - Properties `rpm_limit`, `tpm_limit`, `daily_limit` return effective limits

- **Per-model daily tracking**:
  - `record_request()` increments per-model counter
  - `check_limits()` uses per-model daily count
  - `get_remaining_daily()` returns remaining for current model
  - `get_status()` includes `model` and `daily_by_model` fields

- **`switch_model(model, limits)`** method:
  - Changes active model and applies new limits
  - RPM sliding window shared (per-minute is global)
  - Daily limits tracked separately per model

### Default Model Limits (`summarize_links/config.py`)

Added `DEFAULT_MODEL_LIMITS` with actual API limits (free tier):
| Model | RPM | TPM | Daily |
|-------|-----|-----|-------|
| gemini-3-flash | 5 | 250,000 | 20 |
| gemini-2.5-flash | 5 | 250,000 | 20 |
| gemini-2.5-flash-lite | 10 | 250,000 | 20 |

Added `FALLBACK_MODEL_LIMITS` for unknown models (conservative):
- RPM: 2, TPM: 32,000, Daily: 20

Added `get_model_rate_limits(model, yaml_model_limits)` function:
- Checks YAML config first (for custom overrides)
- Falls back to `DEFAULT_MODEL_LIMITS`
- Falls back to `FALLBACK_MODEL_LIMITS` for unknown models
- Returns `ModelRateLimits` instance

### YAML Configuration Support (`summarize_links/config.py`)

Added `model_limits` field to `Config` dataclass for custom per-model limits:

```yaml
# .summarizer-config.yaml
model_limits:
  gemini-2.5-flash:
    rpm_limit: 20
    tpm_limit: 500000
    daily_limit: 1000
  my-custom-model:
    rpm_limit: 5
    tpm_limit: 100000
    daily_limit: 50
```

### Client Integration (`summarize_links/gemini_client.py`)

- **`GeminiClient`** updated:
  - Accepts `model_limits: ModelRateLimits` parameter
  - Accepts `yaml_model_limits: dict` parameter for config override
  - Creates model-specific `RateLimiter` instance
  - Falls back to `get_model_rate_limits()` if no explicit limits

- **`create_client()`** factory updated:
  - Accepts and passes through `model_limits` and `yaml_model_limits`

### Persistent State Format

Updated `.summarizer-rate-limit.json`:
```json
{
  "date": "2025-12-18",
  "daily_requests": 18,
  "daily_requests_by_model": {
    "gemini-2.5-flash": 15,
    "gemini-2.5-pro": 3
  }
}
```

### Backward Compatibility

- Old state files without `daily_requests_by_model` work correctly
- Legacy `daily_requests` field maintained for total count
- Individual `rpm_limit/tpm_limit/daily_limit` parameters still work

### Tests Added

**`tests/test_rate_limiter.py`**:
- `TestModelRateLimits` (3 tests): Safety margin, minimum values, immutability
- `TestRateLimitState` expanded (6 tests): Per-model tracking, backward compat
- `TestRateLimiter` updated (12 tests): Safety margin, per-model daily
- `TestModelSwitching` (4 tests): Model switching, RPM preservation, daily tracking
- `TestPersistentState` expanded (6 tests): Per-model persistence, old format compat
- `TestGlobalRateLimiter` expanded (4 tests): Model and limit parameters

**`tests/test_config.py`**:
- `TestGetModelRateLimits` (5 tests): Known models, unknown, YAML override
- `TestModelLimitsConfig` (3 tests): YAML loading, integration

**`tests/test_gemini.py`**:
- Updated `mock_rate_limiter` fixture to use `ModelRateLimits`

**Tests:** All 395 tests pass

**Safety Margin Benefits:**
- 10 RPM limit → 9 effective RPM
- 500 daily → 450 effective daily
- Provides buffer to avoid hitting hard API limits
- Reduces 429 rate limit errors

**Example Usage:**
```bash
# Using gemini-2.5-flash (effective: 9 RPM, 450 daily)
summarize-links --model gemini-2.5-flash from-note

# Using gemini-2.5-pro (effective: 4 RPM, 22 daily)
summarize-links --model gemini-2.5-pro from-note

# Check status (shows per-model usage)
summarize-links status
```

---

## 2025-12-23: Fix garbled content detection and error handling

**Goal:** Fix issue where summaries indicating "corrupted or encrypted, consisting of garbled characters" were being marked as `status: success` when they should be `status: error`.

**Problem:**
When processing URLs, every summary showed "The provided web page content appears to be corrupted or encrypted, consisting of garbled characters", but these were marked as successful summaries. This prevented proper error handling and retry logic.

**Root Causes:**
1. No detection of garbled content responses from Gemini
2. No validation of extracted content quality before sending to API
3. Incorrect status marking for these failures

**Solution:** Implemented three-layer defense system

### 1. Gemini Response Detection (`summarize_links/gemini_client.py`)

Added `_is_garbled_summary()` function that detects common indicators in AI responses:
- "corrupted or encrypted"
- "garbled characters"
- "appears to be encrypted/corrupted"
- "not possible to extract"
- "meaningless/random characters"
- "base64 encoded"
- "binary data"
- "unreadable content"

Updated `_parse_gemini_response()` to check summary content:
- Raises `GeminiAPIError` if garbled content detected
- Applied to both successful JSON parsing and fallback paths
- Prevents marking corrupted summaries as successful

### 2. Early Content Validation (`summarize_links/extract.py`)

Added `_is_content_garbled()` function that detects:
- **High ratio of non-ASCII characters** (>30% threshold)
  - Counts characters outside ASCII range (>127)
  - Counts non-printable characters (<32, except newlines/tabs)
- **Base64-like patterns**
  - Long sequences (100+) of alphanumeric + `/` + `+` characters
  - Indicates encoded data rather than readable text

Integrated into `_extract_with_parser()`:
- Checks content after `_clean_text()` and before returning
- Rejects garbled content early, saving API calls
- Provides clearer error messages about content quality

### 3. Proper Error Handling

Updated CLI error handling in `summarize_links/cli.py`:
- Garbled content raises `GeminiAPIError`
- Creates stub note with `status: error`
- Error stubs can be retried later
- Clear error messages about extraction issues

**Behavior After Fix:**

1. **During extraction**: 
   - If web page content appears garbled (base64, high non-ASCII ratio)
   - Extraction fails with `ContentExtractionError`
   - Clear error message about garbled content

2. **During summarization**:
   - If Gemini's response indicates garbled content
   - Summarization fails with `GeminiAPIError`
   - Error note created with proper status

3. **Error handling**:
   - Failed summaries marked as `status: error`
   - Stub notes created for retry
   - URLs not deleted from daily notes (can retry later)

**Tests Added:**

**`tests/test_gemini.py`** - `TestGarbledContentDetection` (8 tests):
- `test_detects_corrupted_or_encrypted` - Main error message pattern
- `test_detects_garbled_characters` - Alternate phrasing
- `test_detects_not_possible_to_extract` - Extraction failure message
- `test_detects_base64_encoded` - Encoding detection
- `test_case_insensitive` - Case variations
- `test_normal_summary_not_detected` - No false positives
- `test_parse_response_raises_on_garbled_content` - Integration test
- `test_parse_response_passes_normal_content` - Normal path works

**`tests/test_extraction.py`** - `TestGarbledContentDetection` (6 tests):
- `test_detects_high_ratio_non_ascii` - Character ratio detection
- `test_detects_base64_like_content` - Base64 pattern detection
- `test_allows_normal_text` - Normal content passes
- `test_allows_moderate_unicode` - Unicode support
- `test_short_text_not_checked` - Skip short samples
- `test_threshold_parameter` - Configurable threshold

**Tests:** All 409 tests pass

**Static Analysis:** All checks pass
- `ruff check .` ✓
- `ruff format .` ✓
- `mypy .` ✓

**Next Steps:**
The underlying cause of *why* content is garbled (bot detection, encoding issues, JavaScript rendering) requires separate investigation. However, these issues are now properly detected and reported rather than silently marked as successful.

**Utility Script:**
Created `fix_garbled_summaries.py` script to:
- Scan existing summaries marked as `status: success`
- Detect garbled content using `_is_garbled_summary()`
- Update status to `status: error` for retry
- Provides clear summary of fixed files
- Can be run after updates to catch historical issues

---

## 2025-12-23: Add 'summaries' command to report on summary status

**Goal:** Add a CLI command to scan all summary notes and provide statistics about their status (successful, mocked, errors).

**Changes:**

### New Function: `scan_summaries()` in `summarize_links/notes.py`
- Scans all `.md` files in the summaries folder
- Extracts status from frontmatter (`success`, `mocked`, `error`)
- Collects statistics:
  - Total summaries count
  - Count by status (success/mocked/error/unknown)
  - Date range (oldest to newest)
  - Lists of problematic summaries (errors and mocked)
- Helper functions added:
  - `_extract_frontmatter_field()` - Extract YAML field values
  - `_extract_error_reason()` - Detect error type from stub notes

### New TypedDict: `SummaryStats` in `summarize_links/notes.py`
- Strongly typed return value for `scan_summaries()`
- Fields: total, success, mocked, error, unknown, oldest_date, newest_date, error_summaries, mocked_summaries

### New CLI Command: `summarize-links summaries`
- Added `summaries` subcommand to argument parser
- Created `cmd_summaries()` function that:
  - Calls `scan_summaries()` with current config
  - Displays overall statistics in a Rich table
  - Shows date range
  - Lists mocked summaries (needing real API calls)
  - Lists error summaries (failed processing)
  - Provides helpful tips for regenerating/retrying
- Updated command dispatcher in `main()` to handle `summaries` command

**Usage:**
```bash
summarize-links summaries
```

**Output Example:**
```
Scanning summaries...

Summary Statistics
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┓
┃ Category                  ┃ Count ┃ Percentage ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━┩
│ Total Summaries           │   150 │       100% │
│ ✓ Successful              │   130 │        86% │
│ ⚠ Mocked (needs real API) │    15 │        10% │
│ ✗ Errors (failed)         │     5 │         3% │
└───────────────────────────┴───────┴────────────┘

Date range: 2025-01-01 to 2025-12-23

⚠ Mocked Summaries (run without --mock to regenerate):
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ File                        ┃ Date       ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ 2025-12-15-example.md       │ 2025-12-15 │
│ 2025-12-16-tutorial.md      │ 2025-12-16 │
└─────────────────────────────┴────────────┘

✗ Error Summaries (run with --force to retry):
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ File                       ┃ Reason         ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ 2025-12-10-broken.md       │ Fetch failed   │
│ 2025-12-12-rate.md         │ Rate limited   │
└────────────────────────────┴────────────────┘

Tips:
  • Run summarize-links from-note --all --force to regenerate mocked summaries
  • Run summarize-links from-note --all --force to retry failed summaries
```

**Behavior:**
- Shows statistics for all summaries in the configured out_folder
- Displays first 10 mocked/error summaries (shows "... and N more" if more exist)
- Provides actionable tips for fixing problematic summaries
- Empty folder handling (shows "No summaries found" message)
- Works with any configured summaries folder

**Tests:** Added 7 new tests in `tests/test_summaries_command.py`:
- `test_scan_summaries_empty_folder` - Handles missing folder
- `test_scan_summaries_with_success` - Counts successful summaries
- `test_scan_summaries_with_mocked` - Identifies mocked summaries
- `test_scan_summaries_with_errors` - Identifies error summaries
- `test_scan_summaries_mixed` - Mixed status summaries
- `test_scan_summaries_date_range` - Date range detection
- `test_scan_summaries_ignores_non_markdown` - Only counts .md files

**Tests:** All 416 tests pass

**Static Analysis:** All checks pass
- `ruff check .` ✓
- `ruff format .` ✓
- `mypy .` ✓
---

## 2025-12-24: Ollama Integration

**Goal:** Add support for local LLM models via Ollama as an alternative to Gemini API, enabling offline summarization without rate limits.

**Requirements:**
- Support multiple Ollama models (Llama3, Mistral, Phi, Qwen, Gemma, etc.)
- Automatic provider detection based on model name
- Same output format from both providers (JSON with summary, tags, content_type)
- No rate limiting for local models  
- Support custom Ollama endpoint configuration
- Clear error messages when Ollama is unavailable or model not installed
- Both providers supported long-term (not replacing Gemini)

**Implementation Plan:** See [ollama-integration-plan.md](docs/ollama-integration-plan.md)

**Changes by Phase:**

### Phase 1: Core Infrastructure

**New Module: `summarize_links/ollama_client.py`** (332 lines)
- `OllamaClient` class implementing `SummarizerProtocol` interface
- Uses `requests` library for Ollama API communication
- 120s timeout (10x longer than Gemini for slower local models)
- Server availability check with helpful error messages
- Model installation check with installation instructions
- `summarize()` and `summarize_with_metadata()` methods matching Gemini client
- Reuses `_parse_gemini_response()` for consistent JSON parsing
- No rate limiting (local models don't have quotas)

**New Module: `summarize_links/llm_factory.py`** (126 lines)
- `detect_provider()` function for automatic provider detection:
  - Models containing `:` → Ollama (e.g., `llama3:latest`)
  - Known Ollama model prefixes → Ollama (llama, mistral, phi, qwen, gemma, etc.)
  - Default → Gemini
- `create_llm_client()` factory function:
  - Returns `GeminiClient` or `OllamaClient` based on detection
  - Passes appropriate configuration to each client
  - Validates API key only for Gemini models
  - Handles custom Ollama endpoint

**Updated: `summarize_links/exceptions.py`**
- Added `OllamaServerError` - Raised when Ollama server not reachable
  - Message includes: "Run 'ollama serve' to start the server"
- Added `OllamaAPIError` - Raised when Ollama API call fails
- Added `ModelNotInstalledError` - Raised when model not pulled
  - Message includes: "Pull it with 'ollama pull <model>'"

**Updated: `summarize_links/config.py`**
- Added `MODEL` environment variable (replaces GEMINI_MODEL)
- `GEMINI_MODEL` deprecated but still supported for backward compatibility
- Priority order: CLI → MODEL env → GEMINI_MODEL env → YAML → default
- Added `ollama_endpoint` field with default `http://localhost:11434`
- `OLLAMA_ENDPOINT` environment variable support
- Updated `validate()` to only require API key for Gemini models
- Config validation now provider-aware via `detect_provider()`

### Phase 2: CLI Integration

**Updated: `summarize_links/cli.py`**
- Replaced imports to use `llm_factory` instead of `gemini_client`
- Updated all `create_client()` calls to `create_llm_client()`
- Added Ollama exception handlers with helpful error messages
- Updated `cmd_status()` to show provider info and skip rate limits for Ollama

### Phase 3: Testing

**New Module: `tests/test_ollama_client.py`** (14 tests)
**New Module: `tests/test_llm_factory.py`** (11 tests)
**Updated: `tests/test_cli.py`** - Fixed create_client references

**Test Results:** All 448 tests passing (440 existing + 8 new)

### Phase 4: Documentation

**Updated: `README.md`**
- Added Ollama to features, prerequisites, and configuration sections
- Added usage examples for both Gemini and Ollama providers  
- Updated environment variables table with MODEL, OLLAMA_ENDPOINT
- Added troubleshooting section for Ollama-specific errors

### Phase 5: Code Quality

**Linting & Formatting:**
- Ran `ruff check .` and fixed unused imports
- Fixed line length violations manually
- Ran `ruff format .` to format all files

**Static Analysis:** All checks pass ✓

### Commits Made

1. **feat: add core Ollama integration infrastructure**
2. **feat: integrate LLM factory into CLI with Ollama error handling**
3. **test: add comprehensive tests for Ollama integration**
4. **style: fix linting issues and format code**
5. **docs: complete README with Ollama usage examples and troubleshooting**

**Provider Detection Rules:**
- **Ollama detected if:** Model contains `:` OR starts with known prefix (llama, mistral, phi, qwen, gemma, etc.)
- **Gemini otherwise:** Known gemini-* models or default for unknown

**Key Benefits:**
✓ Offline summarization capability
✓ No API costs for local models
✓ No rate limits
✓ Privacy (content never leaves your machine)
✓ Backward compatible (existing Gemini setups work unchanged)
✓ Clear error messages guide users to fix issues
✓ Consistent interface between providers

**Tests:** All 448 tests passing
**Branch:** `jc/ollama` (pushed to remote with 5 commits)

---

## 2025-12-29: Langfuse Integration - Phase 1 (Core Integration)

**Goal:** Add core Langfuse tracing infrastructure with graceful degradation for monitoring LLM operations.

**Implementation Plan:** See [langfuse-integration-plan.md](docs/langfuse-integration-plan.md)

**Changes:**

### Configuration (`summarize_links/config.py`)
Added Langfuse configuration fields to `Config` dataclass:
- `langfuse_enabled`: Boolean flag (default: False)
- `langfuse_public_key`: Public API key (from env or YAML)
- `langfuse_secret_key`: Secret API key (from env or YAML)
- `langfuse_base_url`: Server URL (default: "https://cloud.langfuse.com")

Configuration priority: Environment variables → YAML config → Defaults
- Env vars: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`
- Auto-enable if keys provided (can be explicitly disabled in YAML)

Example YAML:
```yaml
langfuse:
  enabled: true
  base_url: "https://cloud.langfuse.com"
  # Keys should be in .env for security
```

### Tracer Module (`summarize_links/langfuse_tracer.py`)
Created `LangfuseTracer` class with graceful degradation:
- No-op when Langfuse not configured or library not installed
- Context managers for different observation types:
  - `trace_url_processing()`: Creates trace for entire URL processing
  - `trace_span()`: Creates span observations (fetch, extract, write)
  - `trace_generation()`: Creates generation observations for LLM calls
- `score_trace()`: Adds scores to traces (for future evaluation)
- `flush()`: Ensures traces are sent to server
- Global tracer management: `initialize_tracer()`, `get_tracer()`

**Graceful Degradation:**
- All operations return None when disabled
- Exceptions caught and logged as warnings
- Application functions normally without Langfuse

### CLI Integration (`summarize_links/cli.py`)
- Initialize tracer after config loading in `main()`
- Tracer auto-detects configuration
- No-op if not configured

### LLM Client Tracing
**`summarize_links/gemini_client.py`:**
- Added tracing to `summarize_with_metadata()` method
- Updates current observation with model, input metadata (content_length, url, title)
- Updates observation with output metadata (summary_length, tags, content_type)
- Provider metadata: `provider: "gemini"`

**`summarize_links/ollama_client.py`:**
- Added identical tracing to `summarize_with_metadata()` method
- Provider metadata: `provider: "ollama"`, includes endpoint
- Uses `self._model` attribute (not `_model_name`)

**Implementation:**
- Uses Langfuse decorators for automatic instrumentation
- Graceful handling of missing `langfuse.decorators` import
- Type ignore comments for optional dependencies

### Tests
**`tests/test_config.py`** - Added `TestLangfuseConfig` class (7 tests):
- Default disabled state
- Environment variable loading
- YAML configuration loading
- Priority (env overrides YAML)
- Auto-enable when keys provided
- Explicit disable in YAML respected
- Default base URL

**`tests/test_langfuse_tracer.py`** - Comprehensive tracer tests (20 tests):
- Disabled mode (all operations are no-ops)
- Missing keys graceful degradation
- Context manager behavior
- Null trace_id handling
- Global tracer initialization

**`tests/conftest.py`:**
- Added `mock_config` fixture with Langfuse fields
- Type-safe Config import using TYPE_CHECKING

### Code Quality
**Static Analysis:** All checks pass ✓
- `ruff check .` - All issues fixed
- `ruff format .` - Code formatted
- `mypy .` - Type checking passes with appropriate type: ignore comments

**Tests:** All 494 tests passing (474 existing + 20 new)

### Key Features
✓ Optional integration (gracefully degrades if not configured)
✓ No performance impact when disabled (minimal overhead when checking)
✓ Configuration from environment variables or YAML
✓ Comprehensive test coverage
✓ Both Gemini and Ollama tracing supported
✓ Type-safe with proper error handling
✓ Ready for Phase 2 (Evaluation Framework)

**Commit:** `feat: Add Phase 1 Langfuse integration (Core Integration)` (9733a6c)
**Branch:** `feat/langfuse-integration` (pushed to remote)

---

## 2025-12-29: Langfuse Integration - Phase 1.5 (Fixed Tracing Issues)

**Goal:** Fix non-working Langfuse tracing by migrating to OpenTelemetry-based API and implementing proper trace/span creation with token usage tracking.

**Problem:** 
Initial integration used decorator-based `langfuse_context` API which was deprecated in Langfuse v2.x. The new v3.x SDK uses OpenTelemetry context managers via `start_as_current_observation()`.

**Root Causes:**
1. Used `@observe()` decorators and `langfuse_context` which don't exist in new SDK
2. Tracer was initialized but never actually created traces
3. `'Langfuse' object has no attribute 'trace'` warnings
4. No traces appeared in Langfuse dashboard
5. Verbose HTTP debug logs from httpcore/httpx flooding output
6. Token usage not captured from API responses

**Migration Changes:**

### Tracer Module (`summarize_links/langfuse_tracer.py`)
Complete rewrite of trace creation methods:
- Replaced direct method calls with `start_as_current_observation()` context managers
- `trace_url_processing()`: Creates trace using `as_type="span"` with URL metadata
- `trace_span()`: Creates nested spans for operations (fetch, summarize, write)
- `trace_generation()`: Creates generation observations for LLM calls
- All methods return context managers that yield the observation object
- Parent-child relationships handled automatically by OpenTelemetry context

**API Migration:**
```python
# Old (doesn't exist):
trace_id = client.trace(name="process-url", input={...})

# New:
with client.start_as_current_observation(as_type="span", name="process-url", input={...}) as trace:
    trace_id = trace.trace_id
```

### CLI Integration (`summarize_links/cli.py`)
Added comprehensive tracing in `_process_url_with_metadata()`:

```python
# Create trace for entire URL processing
with tracer.trace_url_processing(url, metadata={...}) as trace:
    trace_id = trace.trace_id if trace else None
    
    # Fetch span
    with tracer.trace_span(trace_id, "fetch", ...):
        content, meta = fetch_and_extract_metadata(...)
    
    # Summarize span (generation)
    with tracer.trace_generation(trace_id, "summarize", model=...):
        summary = client.summarize_with_metadata(...)
        
        # Update generation with output and usage
        if generation and hasattr(generation, "update"):
            generation.update(output={...}, usage_details={...})
    
    # Write span
    with tracer.trace_span(trace_id, "write", ...):
        write_summary_note_with_metadata(...)
```

### Token Usage Tracking

**Models (`summarize_links/models.py`):**
- Added `usage_details: dict[str, int] | None = None` field to `SummaryResult`
- Stores token counts: `{"input": 100, "output": 50, "total": 150}`

**Gemini Client (`summarize_links/gemini_client.py`):**
- Modified `summarize_with_metadata()` to extract tokens from `response.usage_metadata`
- Maps Gemini response fields to standard names:
  - `prompt_token_count` → `"input"`
  - `candidates_token_count` → `"output"`
  - `total_token_count` → `"total"`
- Returns usage in SummaryResult
- Removed decorator-based `langfuse_context` usage

**CLI (`summarize_links/cli.py`):**
- Updated generation span to include `usage_details` in Langfuse update
- Format: `generation.update(output={...}, usage_details={...})`
- Enables cost calculation in Langfuse UI when matched with model definitions

### Configuration Changes (`summarize_links/config.py`)
Added HTTP logging suppressors:
- httpcore and httpx loggers set to WARNING level
- Prevents verbose connection debug logs flooding output
- Uses proper name-based suppression without regex

### LLM Client Cleanup
**`summarize_links/ollama_client.py`:**
- Removed decorator-based `langfuse_context` usage
- Consistent with Gemini client approach
- Tracing now handled at CLI layer

### Tests

**Updated `tests/test_langfuse_tracer.py`:**
- All tracer tests updated to use new API
- Mock `get_client()` and `start_as_current_observation()`
- Tests verify context manager behavior
- Proper handling of disabled/null trace scenarios
- Tests for metadata, model info, and span hierarchy

**Updated `tests/test_gemini.py`:**
- Fixed mock responses to include `usage_metadata` with token counts:
  ```python
  mock_response.usage_metadata.prompt_token_count = 100
  mock_response.usage_metadata.candidates_token_count = 50
  mock_response.usage_metadata.total_token_count = 150
  ```
- Prevents MagicMock comparison errors in rate limiter

**Tests:** All 496 tests passing

### Static Analysis
**All checks pass** ✓
- `ruff check .` - Linting clean
- `ruff format .` - Code formatted
- `mypy .` - Type checking passes (added type annotation for `update_data`)

### Results
✓ Traces successfully created and sent to Langfuse
✓ Proper hierarchy: trace → fetch span → generation → write span
✓ Token usage tracked and visible in Langfuse UI
✓ All metadata captured (URL, content length, model, tags, content_type)
✓ HTTP debug logs suppressed
✓ Graceful degradation when Langfuse not configured
✓ All tests passing

### Token Tracking Format
Langfuse receives:
```json
{
  "usage_details": {
    "input": 1234,
    "output": 567,
    "total": 1801
  }
}
```

This enables:
- Automatic cost calculation in Langfuse dashboard
- Token usage analytics per model
- Tracking efficiency over time
- Budget monitoring

**Commits:**
1. `fix: migrate Langfuse tracer to OpenTelemetry API` (a9a5556)
2. `feat: Add token usage tracking to Langfuse integration` (0a260cd)
3. `feat: Add token usage tracking for Ollama models` (e5e70ae)

**Branch:** `feat/langfuse-integration` (pushed to remote)

### Ollama Token Usage Support

**Problem:** Token usage not appearing in Langfuse for Ollama models (qwen3:latest, etc.)

**Solution:** Added token usage extraction from Ollama API responses

**Changes:**

**`summarize_links/ollama_client.py`:**
- Updated `summarize()` to extract and log token counts from Ollama response
- Modified `summarize_with_metadata()` to capture token usage:
  - Extracts `prompt_eval_count` (input tokens)
  - Extracts `eval_count` (output/completion tokens)
  - Calculates total tokens
  - Maps to standard format: `{"input": X, "output": Y, "total": Z}`
  - Returns usage in `SummaryResult.usage_details`
- Added debug logging for token counts

**`tests/test_ollama_client.py`:**
- Updated `test_summarize_with_metadata` to include token counts in mock response
- Verifies `usage_details` in returned `SummaryResult`

**Ollama API Response Format:**
```json
{
  "response": "...",
  "prompt_eval_count": 150,
  "eval_count": 75
}
```

**Behavior:**
- Token usage now tracked for both Gemini and Ollama models
- Consistent format across all LLM providers
- Appears in Langfuse dashboard for analytics and cost tracking
- Debug logs show: "Token usage: input=X, output=Y, total=Z"

**Tests:** All 496 tests passing



---

## 2025-12-30: Setup Devcontainer and Copilot Environment

**Goal:** Configure VS Code Dev Container and GitHub Copilot instructions to streamline onboarding and provide consistent development environment.

**Changes:**

1. **Created `.devcontainer/devcontainer.json`**:
   - Base image: Python 3.11 from Microsoft
   - Auto-installed features: uv package manager (latest)
   - VS Code extensions:
     - Python language support (ms-python.python)
     - Pylance language server (ms-python.vscode-pylance)
     - Ruff linter/formatter (charliermarsh.ruff)
     - MyPy type checker (ms-python.mypy-type-checker)
     - GitHub Copilot and Copilot Chat
     - TOML and YAML language support
   - Editor configuration:
     - Format on save with Ruff
     - Auto-organize imports
     - Strict type checking mode
     - Pytest integration
   - Post-create command: `uv sync --all-extras`
   - .env file mounted as read-only from host
   - Python virtual environment configured in container

2. **Created `.devcontainer/README.md`**:
   - Comprehensive setup guide for dev containers
   - Prerequisites (Docker Desktop, VS Code, Dev Containers extension)
   - Step-by-step instructions for opening project in container
   - Troubleshooting section for common issues
   - Benefits of using dev containers
   - Alternative local setup instructions

3. **Created `.github/copilot-instructions.md`**:
   - Project overview and technology stack
   - Code style standards and architecture patterns
   - Development workflow (linting, building, testing)
   - Package management with uv
   - Environment variable configuration
   - Project structure overview
   - Key features explanation (multi-provider support, rate limiting, URL cleaning)
   - Common commands reference
   - Git commit conventions
   - Guidelines for Copilot when suggesting code

4. **Created `.github/copilot-agent.yml`**:
   - Configures Copilot Coding Agent environment per GitHub's documentation
   - Specifies files and directories to include in agent's context
   - Excludes cache files, build artifacts, and IDE-specific files
   - Prioritizes core architecture files (models, config, exceptions)
   - Prioritizes LLM client implementations and key functionality
   - Ensures agent focuses on relevant code and documentation

5. **Updated main `README.md`**:
   - Added "Option 1: Dev Container (Recommended for Contributors)" section
   - Reorganized installation instructions
   - Links to devcontainer README for detailed setup
   - Preserves existing "Option 2: Local Setup" instructions
   - Added note about Copilot agent configuration

**Benefits:**

- **Fast Onboarding**: New contributors can start coding in minutes with pre-configured environment
- **Consistency**: Everyone uses same Python version, tools, and dependencies
- **Isolated Development**: Container environment doesn't affect host system
- **Pre-configured Tools**: All linters, formatters, and type checkers ready to use
- **Cross-platform**: Works identically on Windows, Mac, and Linux
- **Copilot Context**: GitHub Copilot has project-specific guidelines and conventions
- **Better Suggestions**: Copilot understands project architecture and standards

**Files Created:**
- `.devcontainer/devcontainer.json` (77 lines)
- `.devcontainer/README.md` (170 lines)
- `.github/copilot-instructions.md` (206 lines)
- `.github/copilot-agent.yml` (101 lines)

**Files Modified:**
- `README.md` (added devcontainer setup option and Copilot agent note)

**Testing:**
- JSON syntax validated
- All configuration paths checked
- Documentation reviewed for accuracy
- Ready for manual testing in VS Code

**Next Steps:**
- Users can test by opening project in VS Code and selecting "Reopen in Container"
- Container will build and install dependencies automatically
- Copilot will use instructions for context-aware suggestions

---

## 2025-12-29: Implement Langfuse Best Practices for Tracing

**Issue:** Following Langfuse documentation and best practices, implemented three high-priority improvements to enhance tracing capabilities:
1. Include system prompt in generation input
2. Use propagate_attributes() for trace-level metadata
3. Add error tracking to generation observations

**Changes:**

1. **Enhanced SummaryResult model** in [summarize_links/models.py](summarize_links/models.py):
   - Added `system_prompt: str | None` field to capture system instructions
   - Now stores three components: system prompt, user prompt, and model response

2. **Updated both LLM clients** ([gemini_client.py](summarize_links/gemini_client.py), [ollama_client.py](summarize_links/ollama_client.py)):
   - Modified `summarize_with_metadata()` to capture SUMMARY_SYSTEM_PROMPT
   - Set `result.system_prompt = SUMMARY_SYSTEM_PROMPT` before returning
   - Enables complete reconstruction of model input

3. **Enhanced Langfuse tracer module** in [summarize_links/langfuse_tracer.py](summarize_links/langfuse_tracer.py):
   - Added `propagate_attributes` to imports and __all__ exports
   - Re-exported for convenient use in CLI code
   - Added documentation about its purpose

4. **Refactored CLI tracing** in [summarize_links/cli.py](summarize_links/cli.py):
   - **System Prompt in Input**: Generation input now includes both system and user prompts:
     `python
     update_data["input"] = {
         "system": system_prompt,
         "prompt": raw_prompt,
     }
     `
   
   - **Propagate Attributes**: Wrapped processing in propagate_attributes context:
     `python
     with propagate_attributes(
         session_id=daily_note_filename or "direct-url",
         tags=["production"/"mock", model_name],
         metadata={"vault": vault_path, "provider": "gemini"/"ollama"},
     ):
     `
     This ensures session_id, tags, and metadata propagate to ALL child observations (fetch, generation, write spans)
   
   - **Error Tracking**: Added error handling in generation observation:
     `python
     except Exception as e:
         if generation:
             generation.update(level="ERROR", status_message=str(e))
         raise
     `
     Failed generations now marked with ERROR level and status message

5. **Configuration update** in [pyproject.toml](pyproject.toml):
   - Added SIM117 to ruff ignore list to allow nested with statements
   - Nested contexts (trace + propagate_attributes) are intentional for clarity

**Benefits:**

- **Complete Context**: Evaluators see both system instructions and user prompts
- **Consistent Metadata**: All observations within a trace share session_id, tags, and metadata
- **Better Debugging**: Failed generations are clearly marked with error details
- **Improved Evaluation**: LLM-as-a-Judge can assess responses with full prompt context
- **Session Tracking**: Easy to analyze all URLs from a daily note or processing session
- **Provider Analytics**: Can filter/analyze by provider (Gemini vs Ollama)

**Testing:**

- All 499 tests pass with new implementation
- Static analysis (ruff, mypy) validates type safety and code quality
- Error tracking tested with exception scenarios
- Metadata propagation verified in traces

