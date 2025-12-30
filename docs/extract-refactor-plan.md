# Extract Module Refactoring Plan

## Current State

The `summarize_links/extract.py` module is currently **1,123 lines long** and handles multiple distinct responsibilities:

1. **URL Validation** (~100 lines)
   - URL scheme checking, domain validation
   - Security checks (prevent file://, javascript:, etc.)
   - Length limits and format validation

2. **HTTP Fetching** (~250 lines)
   - Session management with browser headers
   - Retry logic with exponential backoff
   - Paywall detection and error formatting
   - Content type detection (HTML, markdown, etc.)

3. **HTML Parsing & Content Extraction** (~450 lines)
   - BeautifulSoup parsing with fallback parsers
   - Article content detection
   - Non-content element removal (nav, ads, etc.)
   - Text block identification
   - Content cleaning and normalization
   - Garbled content detection

4. **Metadata Extraction** (~300 lines)
   - Title extraction (Open Graph, Twitter cards, title tags)
   - Author detection (meta tags, JSON-LD)
   - Description, published date, site name
   - Tag/keyword extraction (meta tags, hashtags)
   - Markdown metadata handling

## Problem Statement

The current single-file structure has several issues:

1. **Difficult to navigate**: Finding specific functionality requires scrolling through 1,100+ lines
2. **Mixed concerns**: URL validation, HTTP fetching, HTML parsing, and metadata extraction are intertwined
3. **Testing complexity**: Testing individual components requires understanding the entire module
4. **Hard to extend**: Adding new parsers or extraction strategies is difficult
5. **Code reuse**: Some functions could be independently useful but are buried in the large file

## Proposed Structure

Split `extract.py` into a focused subpackage with clear separation of concerns:

```
summarize_links/
  extract/
    __init__.py         # Re-exports for backward compatibility
    validation.py       # URL validation and security checks
    fetching.py         # HTTP session, retry logic, content fetching
    html_parsing.py     # BeautifulSoup parsing and content extraction
    metadata.py         # Metadata extraction from HTML and markdown
```

### Module Responsibilities

#### `validation.py` (~150 lines)
- URL validation (scheme, domain, length checks)
- Constants: ALLOWED_SCHEMES, MAX_URL_LENGTH
- Functions:
  - `validate_url()` - Main validation entry point

#### `fetching.py` (~300 lines)
- HTTP session management with browser headers
- Retry logic with tenacity
- Paywall detection and error formatting
- Constants: HTTP_RETRY_*, BROWSER_HEADERS, HTTP_ERROR_MESSAGES, PAYWALL_DOMAINS
- Functions:
  - `fetch_content()` - Main fetch with retry
  - `fetch_html()` - HTML-specific fetch
  - `_create_session()` - Session setup
  - `_get_paywall_info()` - Paywall detection
  - `_format_http_error()` - Error formatting
  - `_fetch_with_retry()` - Retry logic
  - `_log_retry()` - Retry logging
- Classes:
  - `_RetryableError` - Internal exception for retries

#### `html_parsing.py` (~450 lines)
- HTML parsing with BeautifulSoup
- Content extraction and cleaning
- Article detection and text block identification
- Constants: ELEMENTS_TO_REMOVE, NON_CONTENT_PATTERNS
- Functions:
  - `extract_readable_content()` - Main extraction entry point
  - `truncate_content()` - Content truncation
  - `_extract_with_parser()` - Parser-specific extraction
  - `_extract_article_content()` - Article detection
  - `_find_largest_text_block()` - Fallback extraction
  - `_is_non_content_element()` - Element filtering
  - `_is_content_garbled()` - Garbled content detection
  - `_clean_text()` - Text normalization
  - `_clean_markdown()` - Markdown cleaning

#### `metadata.py` (~350 lines)
- Metadata extraction from HTML (Open Graph, Twitter cards, meta tags)
- JSON-LD parsing for structured data
- Tag and keyword extraction
- Markdown metadata handling
- Functions:
  - `extract_page_metadata()` - Main metadata extraction
  - `_extract_markdown_metadata()` - Markdown-specific extraction
  - `_extract_title()` - Title extraction
  - `_extract_author()` - Author detection
  - `_extract_description()` - Description extraction
  - `_extract_published_date()` - Date extraction
  - `_extract_site_name()` - Site name extraction
  - `_extract_article_tags()` - Tag/keyword extraction
  - `_extract_meta_content()` - Generic meta tag helper

#### `__init__.py` (~100 lines)
- Re-export all public functions for backward compatibility
- Provide high-level convenience functions that combine modules:
  - `fetch_and_extract()` - Combines fetching and parsing
  - `fetch_and_extract_metadata()` - Combines fetching and metadata extraction
- Ensures existing code continues to work: `from summarize_links.extract import function`

## Implementation Strategy

1. **Create directory structure**
   ```bash
   mkdir summarize_links/extract
   ```

2. **Create validation.py**
   - Move URL validation logic
   - Move constants: ALLOWED_SCHEMES, MAX_URL_LENGTH
   - Move `validate_url()` function

3. **Create fetching.py**
   - Move HTTP constants and headers
   - Move session creation and retry logic
   - Move `fetch_content()`, `fetch_html()` and helpers
   - Import `validate_url` from validation.py

4. **Create html_parsing.py**
   - Move HTML parsing constants
   - Move content extraction functions
   - Move `extract_readable_content()`, `truncate_content()` and helpers

5. **Create metadata.py**
   - Move metadata extraction functions
   - Move `extract_page_metadata()` and helpers
   - Import `extract_readable_content` from html_parsing.py
   - Import `truncate_content` from html_parsing.py

6. **Create __init__.py**
   - Import all public functions from submodules
   - Define `__all__` with exported names
   - Implement `fetch_and_extract()` - combines fetching + parsing
   - Implement `fetch_and_extract_metadata()` - combines fetching + metadata

7. **Delete old extract.py**
   - Only after tests pass

8. **Run tests**
   ```bash
   uv run pytest
   ```

9. **Fix imports if needed**
   - Existing code should work: `from summarize_links.extract import function`

10. **Run linting**
    ```bash
    uv run ruff check .
    uv run ruff format .
    uv run mypy .
    ```

## Benefits

1. **Improved organization**: Clear separation of validation, fetching, parsing, and metadata
2. **Easier navigation**: Each module is 150-450 lines, focused on one concern
3. **Better testing**: Test individual components in isolation
4. **Easier to extend**: Add new parsers or extraction strategies without affecting other parts
5. **Code reuse**: Functions like `fetch_content()` or `extract_readable_content()` can be used independently
6. **Backward compatibility**: All existing imports continue to work

## Success Criteria

- ✅ All 542 tests pass
- ✅ No changes required to code that imports from `summarize_links.extract`
- ✅ All linting checks pass (ruff, mypy)
- ✅ Each module is under 500 lines
- ✅ Each module has a clear, single responsibility
- ✅ Module docstrings clearly explain purpose
- ✅ Public API remains identical (`__all__` exports match original)

## Dependencies Between Modules

```
validation.py (no dependencies)
    ↓
fetching.py (imports: validation)
    ↓
html_parsing.py (no extract dependencies)
    ↓
metadata.py (imports: html_parsing)
    ↓
__init__.py (imports: all above, provides convenience functions)
```

This dependency order ensures clean imports without circular dependencies.
