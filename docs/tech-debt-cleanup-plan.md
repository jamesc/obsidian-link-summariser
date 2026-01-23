# Tech Debt Cleanup Plan

**Date:** 2026-01-23
**Goal:** Systematically address code duplication, obsolete functionality, and insufficient test coverage across the codebase.

## Executive Summary

This plan addresses technical debt identified through comprehensive codebase analysis:

- **Code Duplication:** 14 instances of duplicated logic across modules
- **Obsolete Code:** 3 unused/low-value components
- **Test Coverage Gaps:** 17% untested code (83% current, target 95%+)

**Estimated Impact:**
- Remove ~500 lines of duplicate/obsolete code
- Add ~1,200 lines of tests
- Improve maintainability score by 25%+

---

## Phase 1: Code Duplication Elimination (High Priority)

### 1.1 Client Lazy Initialization Pattern

**Problem:** All LLM and chat clients have identical `_get_client()` pattern:

**Affected Files:**
- `summarize_links/llm/gemini.py` (lines 106-115)
- `summarize_links/llm/azure.py` (lines 138-151)
- `summarize_links/chat/azure_client.py` (lines 401-412)
- `summarize_links/chat/engine.py` (lines 132-139)

**Duplicated Pattern:**
```python
def _get_client(self) -> ClientType:
    if self._client is None:
        self._client = create_client_instance()
        logger.debug("Created client")
    return self._client
```

**Solution:**
Create a base mixin class with generic lazy initialization:

```python
# summarize_links/llm/base.py or new utils/client_mixin.py
class LazyClientMixin(Generic[T]):
    """Mixin for lazy client initialization."""

    _client: T | None = None

    def _get_or_create_client(
        self,
        factory: Callable[[], T],
        name: str | None = None
    ) -> T:
        if self._client is None:
            self._client = factory()
            logger.debug(f"Created {name or 'client'}")
        return self._client
```

**Benefits:**
- Remove ~40 lines of duplicated code
- Consistent lazy loading pattern
- Easier to add caching/pooling later

### ✅ 1.2 Frontmatter Field Extraction [COMPLETED]

**Status:** COMPLETED 2025-01-23
**Commit:** 1aa11eb - "refactor: Consolidate frontmatter extraction to utils module"

**Problem:** Three different implementations of YAML frontmatter field extraction

**Solution Implemented:**
Created `summarize_links/utils/frontmatter.py` with unified utilities:
- `extract_frontmatter_block()` - Extract raw YAML block
- `parse_frontmatter()` - Full YAML parsing with proper type handling
- `get_frontmatter_field()` - Single field extraction

**Affected Files Refactored:**
- `summarize_links/notes/scanning.py` - Removed `_extract_frontmatter_field()` (33 lines)
- `summarize_links/chat/tools/summarize.py` - Removed `_extract_frontmatter_field()` (13 lines)
- `summarize_links/chat/tools/vault.py` - Removed `_extract_frontmatter()` (59 lines)

**Results:**
- Removed ~120 lines of duplicate code
- Added comprehensive test coverage (24 new tests in test_frontmatter.py)
- All 93 existing tests still passing
- Proper YAML parsing with PyYAML (handles all types correctly)
- Better error handling for malformed YAML

**Estimated Effort:** 6 hours (actual)
**Risk:** Low (isolated change) ✓

---

### ✅ 1.3 URL Extraction Pattern Duplication [COMPLETED]

**Problem:** URL regex pattern defined multiple times:

**Affected Files:**
- `summarize_links/notes/extraction.py` - `BARE_URL_PATTERN`, `MARKDOWN_LINK_PATTERN`
- `summarize_links/chat/tools/summarize.py` - `URL_PATTERN` (lines 45-53)

**Solution:**
Consolidate into single constants module:

```python
# summarize_links/constants.py (new file)

import re

# URL patterns for extraction
MARKDOWN_LINK_PATTERN = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
BARE_URL_PATTERN = re.compile(r'https?://[^\s]+')

# Chat tool URL pattern (more lenient)
URL_PATTERN = re.compile(
    r"https?://[^\s<>\"')\]]+"
    r"|(?:www\.)[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s<>\"')\]]*)?"
    r"|[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}/[^\s<>\"')\]]*"
    rf"|[a-zA-Z0-9][-a-zA-Z0-9]*\.(?:com|org|net|io|dev|co|edu|gov|info|app|ai|me|xyz)",
    re.IGNORECASE,
)

# Tracking parameters to remove
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    # ... (move from notes/extraction.py)
}

# Common TLDs
COMMON_TLDS = r"com|org|net|io|dev|co|edu|gov|info|app|ai|me|xyz"
```

**Benefits:**
- Single import for URL patterns
- Avoid regex compilation duplication
- Consistent behavior across modules

**Estimated Effort:** 2 hours
**Risk:** Low

---

### 1.4 Error Handling Pattern Standardization

**Problem:** Similar try-except patterns repeated ~100+ times across codebase.

**Common Pattern:**
```python
try:
    # operation
except SomeError as e:
    logger.error("Failed to do X: %s", e)
    raise CustomError(f"Failed to do X: {e}") from e
```

**Solution:**
Create error handling decorators:

```python
# summarize_links/utils/errors.py

import functools
import logging
from typing import Callable, TypeVar, ParamSpec

P = ParamSpec('P')
R = TypeVar('R')

def handle_errors(
    error_type: type[Exception],
    message_template: str,
    log_level: int = logging.ERROR,
    reraise: bool = True
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator for consistent error handling."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger = logging.getLogger(func.__module__)
                message = message_template.format(error=e)
                logger.log(log_level, message)
                if reraise:
                    raise error_type(message) from e
                return None  # type: ignore
        return wrapper
    return decorator

# Usage:
@handle_errors(NoteWriteError, "Failed to write note: {error}")
def write_note(path: Path, content: str) -> None:
    path.write_text(content)
```

**Benefits:**
- Reduce ~300 lines of boilerplate
- Consistent error logging
- Easier to modify error handling strategy

**Estimated Effort:** 8 hours (many call sites)
**Risk:** Medium (need careful migration)

**Note:** Consider implementing selectively for high-value areas first.

---

## Phase 2: Obsolete Code Removal (Medium Priority)

### 2.1 Enhance `summaries` Command ✅ DECISION: ENHANCE

**Problem:** The `summaries` command has **12% test coverage** and lacks advanced features that would make it more valuable.

**Evidence:**
- `summarize_links/commands/summaries.py` - 166 lines, only 20 tested
- No tests exist in `tests/test_summaries_command.py` beyond basic parser check
- Command has potential but needs enhancement

**Current Functionality:**
```bash
summarize-links summaries --vault ~/Notes
```
Shows:
- Total/success/error/mocked counts
- Date range
- List of problematic summaries

**Decision: Enhance and Test (Option B)**

**Enhancements to Implement:**

1. **Filtering Options:**
   - `--status` filter: `--status=error` or `--status=mocked` or `--status=success`
   - `--after` date filter: `--after=2025-12-01` (only summaries after date)
   - `--before` date filter: `--before=2026-01-01` (only summaries before date)
   - `--tag` filter: `--tag=ai` (only summaries with specific tag)
   - `--limit` option: `--limit=50` (limit results shown)

2. **Machine-Readable Output:**
   - `--json` flag: output as JSON for scripting
   - `--csv` flag: output as CSV for spreadsheets
   - Include fields: date, title, status, tags, url, summary_date

3. **Enhanced Display:**
   - Sort options: `--sort=date` or `--sort=title` or `--sort=status`
   - Reverse order: `--reverse` flag
   - Show summary snippet: `--preview` flag (first 100 chars)
   - Color-coded status indicators

4. **Integration Features:**
   - Export to file: `--output=summaries.json`
   - Stats summary: show tag distribution, content type breakdown
   - Link to original note: show `from` field in output

**Example Enhanced Usage:**
```bash
# Find all error summaries from December
summarize-links summaries --status=error --after=2025-12-01

# Export all AI-tagged summaries as JSON
summarize-links summaries --tag=ai --json --output=ai-summaries.json

# Show recent successful summaries with previews
summarize-links summaries --status=success --limit=10 --preview --sort=date

# Get CSV of all summaries for analysis
summarize-links summaries --csv --output=vault-summaries.csv
```

**Implementation Plan:**

1. **Add Filtering Logic** (2 hours)
   - Refactor `scan_summaries()` to accept filter parameters
   - Add date range filtering
   - Add tag filtering
   - Add status filtering

2. **Add Output Formats** (3 hours)
   - Implement JSON serialization
   - Implement CSV output
   - Add `--output` file writing

3. **Enhanced Display** (2 hours)
   - Add sorting options
   - Add preview snippets
   - Improve color coding and formatting

4. **Comprehensive Testing** (5 hours)
   - Add ~20-25 new tests covering:
     - All filtering combinations
     - JSON/CSV output validation
     - Sorting and display options
     - Edge cases (empty results, invalid filters)

**Benefits:**
- Makes command valuable for vault analysis
- Enables scripting and automation
- Provides export capabilities for external tools
- Better than removing - fills real user need

**Estimated Effort:** 12 hours

**Priority:** Medium (Sprint 2)

**Test Coverage Target:** 90%+ (from current 12%)

---

### 2.2 Duplicate Summarization Logic

**Problem:** Both `processor.py` and `chat/tools/summarize.py` implement URL summarization with overlapping code.

**Affected Files:**
- `summarize_links/processor.py::process_url_with_metadata()` (lines 80-470, ~390 lines)
- `summarize_links/chat/tools/summarize.py` (entire file, ~760 lines)

**Overlap:**
- URL fetching and validation
- Content extraction
- LLM client creation
- Summary note writing
- Error handling

**Current Test Coverage:**
- `processor.py`: 81% (50 lines untested)
- `chat/tools/summarize.py`: 49% (128 lines untested)

**Solution:**
Extract common logic into reusable service:

```python
# summarize_links/services/summarization.py

@dataclass
class SummarizationRequest:
    """Request to summarize a URL."""
    url: str
    source_note: str | None = None
    source_date: datetime | None = None
    user_tags: list[str] = field(default_factory=list)
    force_overwrite: bool = False

@dataclass
class SummarizationResult:
    """Result of summarization attempt."""
    success: bool
    summary_path: Path | None
    error_message: str | None
    should_delete_source: bool

class SummarizationService:
    """Service for URL summarization operations."""

    def __init__(self, config: Config, client: SummarizerProtocol):
        self.config = config
        self.client = client

    def summarize_url(self, request: SummarizationRequest) -> SummarizationResult:
        """Summarize a URL and create/update summary note."""
        # Unified implementation used by both processor and chat tool
        ...
```

**Migration:**
1. Create new service module
2. Move shared logic from `processor.py`
3. Update `processor.py` to use service
4. Update `chat/tools/summarize.py` to use service
5. Remove duplicate code
6. Consolidate tests

**Benefits:**
- Remove ~300 lines of duplicate logic
- Single implementation to maintain
- Easier to add features (retry logic, caching, etc.)
- Better test coverage

**Estimated Effort:** 16 hours
**Risk:** High (core functionality)

**Recommendation:** Do this in Phase 3 after other cleanup

---

### ✅ 2.3 Remove Mock Mode Implementation [COMPLETED]

**Status:** COMPLETED 2026-01-23
**Commit:** To be added

**Problem:** Mock mode added unnecessary complexity with minimal benefit.

**Evidence:**
- `summarize_links/llm/gemini.py::MockGeminiClient` - 150 lines of code
- `--mock` CLI flag used in only a few tests
- `config.mock_mode` field used throughout codebase
- Mock mode bypassed API validation and rate limiting
- **Ollama provides superior local alternative** with real LLM behavior

**Decision:** **Removed Completely**

Mock mode was obsolete because:
- ✅ Ollama provides real local LLM (better quality than mocks)
- ✅ Ollama is free and unlimited (no API costs)
- ✅ Tests should use proper mocking/fixtures, not production mock mode
- ✅ Reduces complexity in config validation and client factory

**Files Modified:**
1. ✅ `summarize_links/llm/gemini.py` - Removed `MockGeminiClient` class (~150 lines)
2. ✅ `summarize_links/llm/factory.py` - Removed mock_mode parameter
3. ✅ `summarize_links/config.py` - Removed mock_mode field and docstring reference
4. ✅ `summarize_links/cli.py` - Removed `--mock` argument
5. ✅ `summarize_links/processor.py` - Removed mock_mode checks
6. ✅ `tests/test_chat_tools.py` - Removed `config.mock_mode = False` (2 occurrences)
7. ✅ `tests/test_chat_engine.py` - Removed `config.mock_mode = False`
8. ✅ `tests/test_chat_engine_extended.py` - Removed `config.mock_mode = False`
9. ✅ `tests/test_config.py` - Updated comments removing mock mode references (2 locations)
10. ✅ `tests/test_cli.py` - Updated comment removing mock mode reference
11. ✅ `summarize_links/langfuse_tracer.py` - Updated comments (2 locations)

**Migration Implemented:**
- Development: Use `MODEL_PROVIDER=ollama` with local Ollama
- Testing: Use pytest-mock fixtures for unit tests
- CI/CD: Can use Ollama in Docker container for integration tests
- Documentation: README recommends Ollama for development

**Results:**
- Removed ~200 lines of code (class + usage + config)
- Simplified configuration and validation
- Better testing practices (proper fixtures)
- Reduced maintenance burden
- All 1012 tests passing ✅
- All linting/formatting/type checks passing ✅

**Actual Effort:** 6 hours
**Risk:** Low (clear migration path, tests ensure correctness) ✓

---

## Phase 3: Test Coverage Improvements (High Priority)

### Current Coverage: 83%

| Module | Coverage | Missing Lines | Priority |
|--------|----------|--------------|----------|
| `chat/tui.py` | 43% | 202 lines | HIGH |
| `chat/tools/summarize.py` | 49% | 128 lines | HIGH |
| `commands/summaries.py` | 12% | 65 lines | MEDIUM |
| `llm/azure.py` | 74% | 38 lines | MEDIUM |
| `extract/fetching.py` | 76% | 24 lines | LOW |
| `chat/azure_client.py` | 87% | 33 lines | LOW |

**Target: 95% coverage**

---

### 3.1 TUI Test Coverage (Priority: HIGH)

**Current:** 43% (202 untested lines)
**Target:** 85%+

**Missing Coverage:**
- User input handling loops (lines 188-212)
- Slash command parsing (lines 242-280)
- Message rendering (lines 457-615)
- Keybinding handlers (lines 621-684)
- Streaming display (lines 760-832)

**Testing Challenges:**
- Textual app requires special test harness
- Async event handling
- Terminal rendering

**Solution:**
Use Textual's testing utilities:

```python
# tests/test_chat_tui_coverage.py

from textual.testing import AppPilot
from summarize_links.chat.tui import ChatTUI

async def test_slash_command_save(mock_engine):
    """Test /save command execution."""
    async with AppPilot(ChatTUI(mock_engine)) as pilot:
        await pilot.press("slash")
        await pilot.press("s", "a", "v", "e")
        await pilot.press("enter")
        # Assert save was called

async def test_streaming_message_display(mock_engine):
    """Test streaming message rendering."""
    # Mock streaming response
    # Verify chunks appear incrementally
```

**New Tests Needed:** 15-20 tests

**Estimated Effort:** 12 hours

---

### 3.2 Summarize Tool Test Coverage (Priority: HIGH)

**Current:** 49% (128 untested lines)
**Target:** 90%+

**Missing Coverage:**
- `SummarizeUrlTool.execute()` integration (lines 145-220)
- `ResummarizeTool.execute()` full flow (lines 350-470)
- Error handling branches (lines 492-532)
- Helper methods `_extract_summary_metadata()` (lines 473-512)

**Solution:**
Add integration-style tests:

```python
# tests/test_chat_tools_summarize_coverage.py

def test_summarize_url_tool_full_pipeline(tmp_vault, mock_client):
    """Test complete summarization workflow."""
    tool = SummarizeUrlTool(config, mock_client)
    result = tool.execute({
        "url": "https://example.com",
        "force": False
    })
    assert result.success
    assert "Created summary" in result.output

def test_resummarize_tool_with_existing_summary(tmp_vault):
    """Test resummarization of existing file."""
    # Create existing summary
    # Run resummarize
    # Verify updated
```

**New Tests Needed:** 12-15 tests

**Estimated Effort:** 10 hours

---

### 3.3 Azure Client Error Handling (Priority: MEDIUM)

**Current:** 74% (38 untested lines)
**Target:** 95%+

**Missing Coverage:**
- Authentication error branches (lines 252-257, 428-431)
- Deployment error handling (lines 260-264, 434-437)
- Retry after exhaustion (lines 283-284, 458-459)
- Connection timeout scenarios (lines 316-321)

**Solution:**
Add error simulation tests:

```python
# tests/test_azure_client_error_coverage.py

def test_authentication_error_401(mock_openai_client):
    """Test 401 auth error raises AzureAuthenticationError."""
    mock_client = Mock()
    mock_client.chat.completions.create.side_effect = APIError(
        "Unauthorized", response=Mock(status_code=401)
    )

    client = AzureClient(...)
    with pytest.raises(AzureAuthenticationError, match="Authentication failed"):
        client.summarize("content", "url")

def test_deployment_not_found_404(mock_openai_client):
    """Test 404 deployment error."""
    # Similar structure
```

**New Tests Needed:** 8-10 tests

**Estimated Effort:** 6 hours

---

### 3.4 Summaries Command Testing (Priority: MEDIUM) ✅ INCLUDED IN 2.1

**Status:** Testing included as part of enhancement in Phase 2.1

**Test Coverage Plan:**
- Empty vault (0 summaries)
- Mixed status summaries
- Date range calculation and filtering
- Tag filtering
- Status filtering
- Mocked summary display
- Error summary display
- Tips section logic
- JSON output validation
- CSV output validation
- Sorting and reverse order
- Preview snippets
- Output to file

**New Tests Needed:** 20-25 tests

**Estimated Effort:** 5 hours (included in 2.1's 12 hour estimate)

---

### 3.5 HTTP Fetching Edge Cases (Priority: LOW)

**Current:** 76% (24 untested lines)
**Target:** 90%+

**Missing Coverage:**
- Retry logic with various delays (lines 171-201)
- Paywall detection corner cases (lines 224, 303-304)
- Content-type header variations (lines 310, 317)
- Timeout and connection error recovery (lines 321, 331-332)

**Solution:**
Mock network errors:

```python
def test_retry_with_exponential_backoff(mock_requests):
    """Test retry attempts with proper delays."""
    mock_requests.get.side_effect = [
        requests.ConnectionError(),
        requests.Timeout(),
        Mock(status_code=200, text="content")
    ]

    result = fetch_html("https://example.com")
    assert mock_requests.get.call_count == 3
```

**New Tests Needed:** 6-8 tests

**Estimated Effort:** 5 hours

---

## Phase 4: Code Quality Improvements (Low Priority)

### 4.1 Type Annotation Completeness

**Current State:** Good (mypy strict mode enabled)

**Gaps:**
- Some `Any` types could be more specific
- Missing type stubs for third-party libraries

**Action:**
- Add `py.typed` marker (already done)
- Create type stubs for missing libraries if needed

**Estimated Effort:** 3 hours

---

### 4.2 Documentation Completeness

**Gaps:**
- Some functions lack docstrings
- Missing examples in complex functions
- No architecture diagrams

**Action:**
1. Add docstrings to undocumented functions
2. Create `docs/architecture.md` with diagrams
3. Add code examples to complex modules

**Estimated Effort:** 8 hours

---

### 4.3 Logging Consistency

**Current State:** Generally good, but inconsistent levels

**Issues:**
- Some DEBUG messages should be INFO
- Some INFO messages should be WARNING
- Missing context in some error logs

**Action:**
Audit and standardize:
- DEBUG: Implementation details
- INFO: High-level operations
- WARNING: Recoverable issues
- ERROR: Failures requiring attention

**Estimated Effort:** 4 hours

---

## Implementation Schedule

### Sprint 1 (Week 1): Quick Wins
**Goal:** Low-risk, high-impact changes

- [ ] 1.3 URL Pattern Consolidation (2h)
- [ ] 2.3 Simplify Mock Client (3h)
- [ ] 3.5 HTTP Fetching Tests (5h)
- [ ] 4.1 Type Annotation Review (3h)

**Total:** 13 hours
**Risk:** Low
**Impact:** Remove ~150 lines, add ~15 tests

---

### Sprint 2 (Week 2): Duplication Cleanup + Summaries Enhancement
**Goal:** Reduce code duplication and enhance summaries command

- [ ] 1.1 Client Lazy Init Pattern (4h)
- [ ] 1.2 Frontmatter Extraction (6h)
- [ ] 2.1 Enhance Summaries Command (12h)
  - Add filtering options (2h)
  - Add JSON/CSV output (3h)
  - Enhanced display (2h)
  - Comprehensive tests (5h)
- [ ] 4.3 Logging Consistency (4h)

**Total:** 26 hours
**Risk:** Medium
**Impact:** Remove ~200 lines, add valuable features to summaries command

---

### Sprint 3 (Week 3): Test Coverage Push
**Goal:** Increase coverage to 90%+

- [ ] 3.1 TUI Test Coverage (12h)
- [ ] 3.2 Summarize Tool Coverage (10h)
- [ ] 3.3 Azure Error Coverage (6h)

**Total:** 28 hours
**Risk:** Low
**Impact:** Add ~40 tests, reach 90% coverage

---

### Sprint 4 (Week 4): Major Refactoring
**Goal:** Eliminate largest duplication

- [ ] 2.2 Summarization Service (16h)
- [ ] 1.4 Error Handling (start, 8h)
- [ ] 4.2 Documentation (8h)

**Total:** 32 hours
**Risk:** High (major refactoring)
**Impact:** Remove ~400 lines, single source of truth

---

## Success Metrics

**Code Quality:**
- [ ] Test coverage ≥ 95%
- [ ] Reduce duplicate code by 60%+
- [ ] Remove ≥ 500 lines of obsolete code
- [ ] All modules < 500 lines

**Maintainability:**
- [ ] Reduced complexity in processor.py
- [ ] Unified frontmatter parsing
- [ ] Consistent error handling patterns
- [ ] Complete docstring coverage

**Testing:**
- [ ] All commands have integration tests
- [ ] Error paths tested
- [ ] TUI functionality covered
- [ ] Chat tools fully tested

---

## Risk Mitigation

### High-Risk Changes
1. **Summarization Service Refactoring** (Phase 2.2)
   - **Risk:** Breaking core functionality
   - **Mitigation:**
     - Create service alongside existing code
     - Migrate one caller at a time
     - Keep old code until fully tested
     - Feature flag for rollback

2. **Error Handling Standardization** (Phase 1.4)
   - **Risk:** Changed error semantics
   - **Mitigation:**
     - Start with low-risk modules
     - Keep exception types unchanged
     - Add tests before migration

### Medium-Risk Changes
1. **Frontmatter Consolidation** (Phase 1.2)
   - **Risk:** Behavior changes in edge cases
   - **Mitigation:**
     - Comprehensive test suite first
     - Compare outputs before/after
     - Gradual rollout

---

## Rollback Plan

**For each phase:**
1. Work in feature branch
2. Commit after each logical change
3. Run full test suite before merge
4. Tag releases for easy rollback

**If issues found:**
1. Revert specific commits
2. Fix forward if simple
3. Feature flag to disable new code path

---

## Maintenance After Cleanup

**Ongoing practices:**
1. **No Duplication Rule:** DRY violations in PR review
2. **Coverage Checks:** Require 90%+ for new code
3. **Complexity Limits:** Max 300 lines per function/class
4. **Monthly Audit:** Review for new tech debt

---

## Notes

**One TODO Found:**
- `summarize_links/chat/tui.py:475` - "TODO: Implement interactive confirmation dialog"
- Low priority - confirmation works via simple prompt currently

**Obsolete Features to Consider:**
- `--mock` flag - Could simplify given Ollama availability
- Legacy `status:` frontmatter key - Already supports new format
- Multiple HTML parsers - Could consolidate to html5lib only

**Future Considerations:**
- Plugin architecture for new providers
- Async/await for parallel processing
- Database for summary metadata (instead of file scanning)
- REST API for programmatic access

---

**End of Plan**
