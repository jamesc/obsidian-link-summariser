# Playwright Fallback Implementation Plan

## Overview

Add Playwright as a fallback mechanism for fetching pages that fail due to bot detection and access control. This enables browser-based rendering to bypass common blocking mechanisms including 401/403 errors, rate limiting, timeouts caused by bot detection, and more.

## Problem Statement

Many websites block automated HTTP requests with various error responses (401, 403, 429, timeouts, connection resets), even with browser-like headers. These failures prevent content extraction and summarization. Playwright can render pages in a real browser context, bypassing many of these bot detection mechanisms.

**Key Insight**: Not all HTTP errors indicate permanent failure. Many are bot detection mechanisms that can be bypassed with a real browser.

## Goals

1. **Preserve existing functionality**: Keep current HTTP-based fetching as primary method (fast, low overhead)
2. **Automatic fallback**: Seamlessly retry with Playwright when HTTP errors indicate bot detection
3. **Tiered rollout**: Start conservative (401/403), expand based on real-world data
4. **Minimal configuration**: Work out-of-box with sensible defaults, but allow fine-tuning
5. **Graceful degradation**: Continue to fail appropriately for truly blocked content (paywalls, auth-required)
6. **Testability**: Mock Playwright operations in tests
7. **Performance**: Use Playwright browser context efficiently (reuse between fetches)
8. **Observability**: Log which method succeeded for each URL (metrics)

## Architecture Changes

### Module Structure

```
summarize_links/extract/
├── __init__.py          # Exports fetch_and_extract_metadata
├── fetching.py          # HTTP fetching (EXISTING)
├── playwright_fetching.py  # NEW: Playwright-based fetching
├── html_parsing.py      # HTML parsing (EXISTING)
├── metadata.py          # Metadata extraction (EXISTING)
└── validation.py        # URL validation (EXISTING)
```

### Flow Diagram

```
process_url_with_metadata()
    ↓
fetch_and_extract_metadata(url)
    ↓
fetch_content(url)  [fetching.py]
    ├─ Success (200) → return (html, "html")
    ├─ 401/403/429 Error → raise ContentFetchError (with error details)
    ├─ Timeout/Connection Error (after retries) → raise ContentFetchError
    ├─ Unsupported Content-Type → raise ContentFetchError
    ├─ 404/5xx Error → raise ContentFetchError (NOT retryable)
    └─ Other Error → raise ContentFetchError
         ↓
    [CHECK if error is Playwright-retryable]
         ↓
    should_retry_with_playwright(error)  [NEW]
         ├─ True (401/403/429/timeout/connection/content-type)
         │    ↓
         │  fetch_content_with_playwright(url)  [NEW]
         │    ├─ Success → return (html, "html") + log success
         │    └─ Failure → re-raise ContentFetchError + log both failures
         └─ False (404/500/network unreachable/etc)
              ↓
           re-raise original ContentFetchError (no retry)
```

## Error Case Analysis

### Errors That Should Trigger Playwright Fallback

| Error | Benefit | Tiered Phase | Rationale |
|-------|---------|--------------|------------|
| **HTTP 401** (Unauthorized) | ✅ HIGH | **Phase 1** | Often bot detection masquerading as auth. Browser bypasses. |
| **HTTP 403** (Forbidden) | ✅ HIGH | **Phase 1** | Most common bot blocking (Cloudflare, etc.). Browser bypasses. |
| **HTTP 429** (Too Many Requests) | ✅ MEDIUM | **Phase 2** | Sometimes bot detection vs true rate limiting. Browser may work. |
| **Timeout** (after retries) | ✅ MEDIUM | **Phase 3** | Bot detection may delay responses indefinitely. Browser gets priority. |
| **Connection refused/reset** | ✅ LOW-MEDIUM | **Phase 3** | Aggressive bot blockers close connections. Browser may not trigger. |
| **Unsupported Content-Type** | ✅ MEDIUM | **Phase 4** | Servers return different content to bots (JSON error vs HTML). |

### Errors That Should NOT Trigger Playwright

| Error | Why Not | Rationale |
|-------|---------|------------|
| **HTTP 404** (Not Found) | ❌ No benefit | Page doesn't exist. Browser won't help. |
| **HTTP 5xx** (Server Errors) | ❌ No benefit | Server-side problem. Browser won't fix. |
| **SSL/Certificate Errors** | ❌ No benefit | Certificate issue. Browser has same problem. |
| **Invalid URL** | ❌ No benefit | Validation failure. Nothing to fetch. |
| **Network unreachable** | ❌ No benefit | Genuine network issue. Browser won't help. |

### Tiered Rollout Strategy

**Phase 1 (Initial Release)**: Conservative - High confidence cases only
- ✅ HTTP 401, 403
- Expected impact: ~60-80% of bot-blocked pages
- Risk: Low (clear bot detection signals)

**Phase 2 (After monitoring)**: Expand to rate limiting
- ✅ HTTP 429
- Expected impact: Additional ~10-15% of blocked pages
- Risk: Low-Medium (could waste time on true rate limits)
- Metric to watch: Playwright success rate for 429s

**Phase 3 (If Phase 2 successful)**: Network-level issues
- ✅ Timeouts after retries
- ✅ Connection errors after retries
- Expected impact: Additional ~5-10% of blocked pages
- Risk: Medium (could waste time on genuine network issues)
- Metric to watch: Network error -> Playwright success rate

**Phase 4 (Future enhancement)**: Content negotiation
- ✅ Unsupported content-type errors
- Expected impact: ~2-5% edge cases
- Risk: Low (rare case, clear signal)

## Implementation Details

### 1. New Module: `playwright_fetching.py`

**Purpose**: Browser-based fetching using Playwright

**Key Functions**:

```python
def fetch_content_with_playwright(
    url: str,
    timeout: int = REQUEST_TIMEOUT,
    browser_type: str = "chromium",
) -> tuple[str, str]:
    """
    Fetch content using Playwright browser automation.

    Uses a headless browser to render JavaScript and bypass bot detection.
    Slower than HTTP requests but more robust against anti-bot measures.

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds (default from config).
        browser_type: Browser to use ("chromium", "firefox", "webkit").

    Returns:
        Tuple of (content, content_type) where content_type is 'html'.

    Raises:
        ContentFetchError: If browser fetch fails.
        URLValidationError: If URL is invalid.
    """
    pass


def _get_or_create_browser_context() -> BrowserContext:
    """
    Get existing browser context or create new one.

    Maintains a single browser instance across multiple fetches
    for better performance. Uses a thread-local or module-level
    singleton pattern.

    Returns:
        Playwright BrowserContext instance.
    """
    pass


def close_browser_context() -> None:
    """
    Close the browser context and cleanup resources.

    Should be called at the end of batch processing or when
    the application exits.
    """
    pass
```

**Implementation Notes**:
- Use `playwright.sync_api` for synchronous operation (matches existing code style)
- Browser context should persist across multiple fetches (performance optimization)
- Set browser options: headless, disable images (faster), viewport size
- Wait for network idle or DOM content loaded (configurable)
- Extract final page HTML after JavaScript execution

**Browser Context Management**:
- Store browser context in module-level variable with lock (thread-safe)
- Lazy initialization on first use
- Automatic cleanup via `atexit` handler
- Option to explicitly close via CLI flag or config

### 2. Update `extract/__init__.py`

Modify the main entry point to add intelligent Playwright fallback logic:

```python
import logging
from summarize_links.config import Config
from summarize_links.extract.fetching import fetch_content
from summarize_links.extract.playwright_fetching import (
    fetch_content_with_playwright,
    close_browser_context,
)

logger = logging.getLogger(__name__)

# Tiered error patterns that trigger Playwright fallback
# Configure via Config.playwright_fallback_on_errors
PLAYWRIGHT_RETRYABLE_ERRORS = {
    "phase1": ["HTTP 401", "HTTP 403"],  # High confidence
    "phase2": ["HTTP 429"],  # Rate limiting
    "phase3": ["Timeout", "Connection"],  # Network issues
    "phase4": ["unsupported content type"],  # Content negotiation
}

def should_retry_with_playwright(error: ContentFetchError, config: Config) -> bool:
    """
    Check if error should trigger Playwright fallback based on config phase.

    Args:
        error: The ContentFetchError that occurred.
        config: Application configuration (contains playwright_fallback_phase).

    Returns:
        True if error matches patterns for configured phase, False otherwise.
    """
    error_msg = str(error).lower()

    # Collect all patterns up to configured phase
    patterns_to_check = []
    for phase in ["phase1", "phase2", "phase3", "phase4"]:
        patterns_to_check.extend(PLAYWRIGHT_RETRYABLE_ERRORS[phase])
        if phase == config.playwright_fallback_phase:
            break

    # Check if error matches any pattern
    return any(pattern.lower() in error_msg for pattern in patterns_to_check)

def fetch_and_extract_metadata(url: str, config: Config | None = None) -> PageMetadata:
    """
    Fetch page and extract metadata with intelligent Playwright fallback.

    Strategy:
    1. Try HTTP fetch (fast, low overhead)
    2. If error indicates bot detection, retry with Playwright (based on config phase)
    3. Extract metadata from HTML (same path for both)

    Args:
        url: URL to fetch.
        config: Optional config (for playwright settings). Uses defaults if None.

    Returns:
        PageMetadata with extracted content and metadata.
    """
    if config is None:
        from summarize_links.config import Config
        config = Config()  # Use defaults

    fetch_method = "http"  # Track which method succeeded

    try:
        # Try HTTP first
        html, content_type = fetch_content(url)
        logger.debug(f"✓ Fetched via HTTP: {url}")
        fetch_method = "http"

    except ContentFetchError as e:
        # Check if Playwright is enabled and error is retryable
        if config.playwright_enabled and should_retry_with_playwright(e, config):
            logger.info(f"HTTP fetch failed ({e}), retrying with Playwright: {url}")
            try:
                html, content_type = fetch_content_with_playwright(
                    url,
                    timeout=config.playwright_timeout,
                    browser_type=config.playwright_browser,
                )
                logger.info(f"✓ Successfully fetched via Playwright: {url}")
                fetch_method = "playwright"
            except ContentFetchError as playwright_error:
                # Playwright also failed - give up
                logger.error(f"✗ Playwright fallback also failed: {playwright_error}")
                # Enhance error message to show both attempts failed
                raise ContentFetchError(
                    f"{e} (Playwright fallback also failed: {playwright_error})"
                ) from playwright_error
        else:
            # Not retryable or Playwright disabled - fail immediately
            reason = "disabled" if not config.playwright_enabled else "not retryable"
            logger.debug(f"Playwright fallback {reason} for error: {e}")
            raise

    # Continue with existing extraction logic...
    # Add fetch_method to metadata for observability
    metadata = extract_metadata_from_html(html, url, title)
    metadata.fetch_method = fetch_method  # Track for metrics
    return metadata
### 3. Update Dependencies

**Add to `pyproject.toml`**:
```toml
[project]
dependencies = [
    # ... existing deps
    "playwright>=1.40.0",
]

[project.optional-dependencies]
dev = [
    # ... existing dev deps
]
```

**Installation Script**:
Create `scripts/install_playwright.py`:
```python
"""
One-time setup script to install Playwright browsers.

Run after: uv sync
"""
import subprocess
import sys

def main():
    print("Installing Playwright browsers...")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        print("✓ Playwright browsers installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to install Playwright browsers: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

**Update README.md**:
```markdown
### Setup
```bash
# Install dependencies
uv sync

# Install Playwright browsers (one-time setup)
uv run python scripts/install_playwright.py
```
```

### 4. Configuration Options

**New config fields in `config.py`**:

```python
@dataclass
class Config:
    # ... existing fields

    # Playwright settings
    playwright_enabled: bool = True  # Enable/disable Playwright fallback
    playwright_fallback_phase: str = "phase1"  # Which errors trigger fallback: phase1, phase2, phase3, phase4
    playwright_timeout: int = 30  # Timeout for Playwright operations (seconds)
    playwright_browser: str = "chromium"  # Browser type: chromium, firefox, webkit
    playwright_wait_until: str = "domcontentloaded"  # Wait condition: load, domcontentloaded, networkidle
```

**Environment variables**:
```bash
PLAYWRIGHT_ENABLED=true
PLAYWRIGHT_FALLBACK_PHASE=phase1  # phase1 (401/403), phase2 (+429), phase3 (+timeout/connection), phase4 (+content-type)
PLAYWRIGHT_TIMEOUT=30
PLAYWRIGHT_BROWSER=chromium
PLAYWRIGHT_WAIT_UNTIL=domcontentloaded
```

**CLI flags**:
```bash
--no-playwright  # Disable Playwright fallback
--playwright-phase phase2  # Set fallback phase (phase1, phase2, phase3, phase4)
--playwright-timeout 30
--playwright-browser firefox
```

**Phase descriptions for docs**:
- `phase1` (default): 401, 403 only - High confidence bot detection
- `phase2`: phase1 + 429 - Add rate limiting
- `phase3`: phase2 + timeout/connection errors - Network-level blocking
- `phase4`: phase3 + content-type mismatches - All retryable cases
**Error messages**:
```python
# In ContentFetchError message, indicate which method was used
"HTTP 403: Access forbidden (Playwright fallback also failed)"
"HTTP 401: Authentication required (tried Playwright, still blocked - likely paywall)"
```

### 6. Logging and Observability

**Log events** (with structured data for analysis):
```python
# Successful HTTP fetch
logger.info(f"✓ HTTP fetch succeeded", extra={
    "url": url,
    "method": "http",
    "duration_ms": 1234,
})

# Fallback triggered
logger.info(f"HTTP fetch failed, trying Playwright", extra={
    "url": url,
    "http_error": str(e),
    "error_category": get_error_category(e),
    "playwright_phase": config.playwright_fallback_phase,
})

# Playwright success
logger.info(f"✓ Playwright fetch succeeded", extra={
    "url": url,
    "method": "playwright",
    "duration_ms": 5678,
    "original_error": str(original_error),
})

# Both failed
logger.error(f"✗ Both HTTP and Playwright failed", extra={
    "url": url,
    "http_error": str(http_error),
    "playwright_error": str(playwright_error),
    "error_category": get_error_category(http_error),
})
```

**Langfuse trace updates** (for metrics and analysis):
```python
# In fetch span metadata
{
    "fetch_method": "playwright",  # or "http"
    "fallback_triggered": true,
    "fallback_succeeded": true,  # false if Playwright also failed
    "http_error": "HTTP 403: Forbidden",
    "http_error_category": "bot_detection",
    "playwright_phase": "phase1",
    "http_duration_ms": 1234,  # Time before error
    "playwright_duration_ms": 5678,  # Time for successful fallback
    "total_duration_ms": 6912,
}
```

**Metrics to track** (for phase rollout decisions):
1. **Fallback success rate by phase**:
   - Phase 1: 401/403 → Playwright success %
   - Phase 2: 429 → Playwright success %
   - Phase 3: Timeout/connection → Playwright success %
   - Phase 4: Content-type → Playwright success %

2. **Performance impact**:
   - Average HTTP duration (success cases)
   - Average Playwright duration (fallback cases)
   - Percentage of URLs requiring fallback

3. **Error distribution**:
   - Count by error category (bot_detection, rate_limit, timeout, etc.)
   - Playwright not attempted (outside phase) count
   - Both methods failed count

**Query Langfuse for metrics**:
```python
# Example: Find all Playwright fallback attempts in last 7 days
# Filter by: metadata.fallback_triggered = true
# Group by: metadata.error_category, metadata.fallback_succeeded
# Metric: Success rate per error category
```

### 7. Testing Strategy

**Unit Tests** (`tests/test_playwright_fetching.py`):
- Mock Playwright browser/page objects
- Test successful fetch
- Test timeout handling
- Test error conditions
- Test browser context reuse

**Integration Tests** (`tests/test_integration.py`):
- Mock HTTP fetch to return 401/403
- Verify Playwright is invoked
- Verify final result is correct
- Test with real Playwright (optional, slow)

**Test Helpers**:
```python
# In conftest.py
@pytest.fixture
def mock_playwright_browser():
    """Mock Playwright browser context for testing."""
    mock_page = Mock()
    mock_page.goto.return_value = None
    mock_page.content.return_value = "<html>Test content</html>"

    mock_context = Mock()
    mock_context.new_page.return_value = mock_page

    mock_browser = Mock()
    mock_browser.new_context.return_value = mock_context

    return mock_browser
```

**Mock Mode**:
- When `--mock` is enabled, skip Playwright entirely (too slow for mocking)
- Fall back to generating fake content

### 8. Performance Considerations

**Browser Context Reuse**:
- Create browser context once, reuse for all URLs in batch
- Significantly faster than launching browser per URL
- Close context after batch completes

**Optimization Settings**:
```python
context = browser.new_context(
    viewport={"width": 1280, "height": 720},
    user_agent=USER_AGENT,  # Same as HTTP requests
    ignore_https_errors=False,  # Strict HTTPS
    java_script_enabled=True,  # Need JS for dynamic content
)

# Per-page optimizations
page.route("**/*.{png,jpg,jpeg,gif,svg,webp}", lambda route: route.abort())  # Block images
```

**Timeout Strategy**:
- Default 30s timeout (longer than HTTP's 10s)
- Configurable via CLI/config
- Wait for `domcontentloaded` by default (faster than `networkidle`)

### 9. Cleanup and Resource Management

**Browser Context Lifecycle**:

```python
# In processor.py, after batch completion
def process_urls_batch(...):
    try:
        # ... process URLs
    finally:
        # Cleanup browser context
        from summarize_links.extract import close_browser_context
        close_browser_context()
```

**atexit Handler**:
```python
# In playwright_fetching.py
import atexit

_browser_context: BrowserContext | None = None

def _cleanup_browser():
    """Cleanup browser on exit."""
    global _browser_context
    if _browser_context:
        try:
            _browser_context.close()
        except Exception:
            pass

atexit.register(_cleanup_browser)
```

### 10. Documentation Updates

**README.md**:
- Add Playwright installation instructions
- Document new CLI flags
- Explain fallback behavior
- Performance implications

**AGENTS.md**:
- Note that Playwright is a fallback mechanism
- Explain when it's triggered
- Testing considerations

**docs/spec.md**:
- Update fetch flow diagram
- Document error handling strategy

## Implementation Phases

### Phase 1: Core Playwright Module (1-2 hours)
- [ ] Create `playwright_fetching.py` with basic fetch function
- [ ] Implement browser context management
- [ ] Add error handling and logging
- [ ] Write unit tests with mocked Playwright
- [ ] Add `should_retry_with_playwright()` function with phase logic
- [ ] Add `get_error_category()` helper function

### Phase 2: Integration (1-1.5 hours)
- [ ] Update `extract/__init__.py` with intelligent fallback logic
- [ ] Add phase-based error checking
- [ ] Update `processor.py` to cleanup browser context
- [ ] Add Langfuse trace metadata (fetch_method, error_category, phase)
- [ ] Add structured logging with extra fields
- [ ] Write integration tests for each phase

### Phase 3: Configuration (30-45 min)
- [ ] Add config fields to `config.py` (playwright_fallback_phase, etc.)
- [ ] Add CLI flags (--playwright-phase, --no-playwright)
- [ ] Update `.env.example` with phase descriptions
- [ ] Add config validation (phase must be phase1-4)
- [ ] Test configuration loading and phase behavior

### Phase 4: Dependencies & Setup (30 min)
- [ ] Update `pyproject.toml` with playwright dependency
- [ ] Create installation script (`scripts/install_playwright.py`)
- [ ] Test installation process on clean environment
- [ ] Update CI/CD if needed (install Playwright browsers)

### Phase 5: Documentation (45 min)
- [ ] Update README.md with phase descriptions
- [ ] Update AGENTS.md with Playwright testing notes
- [ ] Add inline code comments explaining phase logic
- [ ] Create usage examples for each phase
- [ ] Document metrics and monitoring approach

### Phase 6: Testing & Refinement (1.5-2 hours)
- [ ] Run full test suite (all phases)
- [ ] Test with real websites for each error type:
  - [ ] 401/403 sites (Cloudflare protected)
  - [ ] 429 sites (if possible)
  - [ ] Slow sites (timeout testing)
- [ ] Performance benchmarking (HTTP vs Playwright by phase)
- [ ] Verify Langfuse metrics are captured correctly
- [ ] Fix any issues found
- [ ] Run linting (ruff, mypy)

### Phase 7: Monitoring Setup (30 min)
- [ ] Document Langfuse queries for key metrics
- [ ] Set baseline metrics (Phase 1 only)
- [ ] Create dashboard queries for:
  - [ ] Fallback success rate by error category
  - [ ] Phase effectiveness comparison
  - [ ] Performance impact metrics

## Testing Plan

### Test Cases

**Unit Tests** (`test_playwright_fetching.py`):
1. `test_fetch_with_playwright_success` - Mock successful page load
2. `test_fetch_with_playwright_timeout` - Mock timeout error
3. `test_fetch_with_playwright_navigation_error` - Mock navigation failure
4. `test_browser_context_reuse` - Verify context is reused
5. `test_browser_context_cleanup` - Verify cleanup works
6. `test_disabled_via_config` - Verify can disable Playwright
7. `test_should_retry_with_playwright_phase1` - Verify 401/403 triggers fallback
8. `test_should_retry_with_playwright_phase2` - Verify phase2 includes 429
9. `test_should_retry_with_playwright_phase3` - Verify phase3 includes timeout/connection
10. `test_should_retry_with_playwright_phase4` - Verify phase4 includes content-type
11. `test_should_not_retry_404` - Verify 404 never triggers fallback
12. `test_should_not_retry_500` - Verify 5xx never triggers fallback

**Integration Tests** (`test_integration.py`):
1. `test_fallback_on_403_phase1` - HTTP 403 → Playwright succeeds (Phase 1)
2. `test_fallback_on_401_phase1` - HTTP 401 → Playwright succeeds (Phase 1)
3. `test_fallback_on_429_phase2` - HTTP 429 → Playwright succeeds (Phase 2)
4. `test_fallback_on_timeout_phase3` - Timeout → Playwright succeeds (Phase 3)
5. `test_fallback_on_connection_phase3` - Connection error → Playwright succeeds (Phase 3)
6. `test_fallback_on_content_type_phase4` - Content-type error → Playwright succeeds (Phase 4)
7. `test_no_fallback_on_404` - HTTP 404 → No Playwright retry (any phase)
8. `test_no_fallback_on_500` - HTTP 500 → No Playwright retry (any phase)
9. `test_no_fallback_429_in_phase1` - HTTP 429 in Phase 1 → No retry (not in phase)
10. `test_playwright_also_fails` - Both HTTP and Playwright fail → Error mentions both
11. `test_browser_cleanup_after_batch` - Context closed after processing
12. `test_phase_config_controls_fallback` - Phase config determines which errors retry

**Manual Testing**:
1. Test with known 403 site (e.g., sites with Cloudflare protection)
2. Test with paywall site (both should fail, but gracefully)
3. Test batch processing (verify context reuse)
4. Test performance (HTTP vs Playwright time)
5. Test with `--no-playwright` flag

## Performance Impact

**Expected Performance**:
- HTTP fetch: ~1-3 seconds per URL
- Playwright fetch: ~5-15 seconds per URL (first page slower, subsequent faster)
- Browser startup overhead: ~2-3 seconds (one-time per batch)

**Mitigation**:
- Playwright only used for failed HTTP requests (minority of cases)
- Browser context reused across URLs in batch
- Optional: disable Playwright via config if not needed

## Risks and Mitigation

### Risk 1: Playwright Installation Complexity
**Risk**: Users might not install Playwright browsers correctly.
**Mitigation**:
- Clear installation instructions in README
- Installation script with error handling
- Graceful fallback if Playwright not available

### Risk 2: Performance Degradation
**Risk**: Playwright adds significant overhead.
**Mitigation**:
- Only used as fallback (not primary method)
- Browser context reuse
- Option to disable via config

### Risk 3: New Dependencies
**Risk**: Playwright adds ~200MB of browsers.
**Mitigation**:
- Document storage requirements
- Make Playwright optional (graceful degradation)
- Consider making it an optional dependency

### Risk 4: Test Complexity
**Risk**: Mocking Playwright is complex.
**Mitigation**:
- Use pytest-playwright for better test support
- Comprehensive mocking fixtures in conftest.py
- Skip Playwright tests in mock mode

### Risk 5: Cloudflare/Bot Detection Still Blocks
**Risk**: Some sites may still detect and block Playwright.
**Mitigation**:
- Document limitations
- Add stealth mode options (user agent, viewport, etc.)
- Future enhancement: playwright-stealth plugin

## Future Enhancements

1. **Stealth Mode**: Add `playwright-stealth` for better bot detection evasion
2. **Screenshot Capture**: Save screenshots of failed pages for debugging
3. **Cookie Persistence**: Maintain cookies across sessions for authenticated sites
4. **Proxy Support**: Allow proxy configuration for regional content
5. **Browser Selection**: Let users choose browser type (Chromium, Firefox, WebKit)
6. **Wait Strategies**: Configurable wait conditions (load, networkidle, selector)
7. **JavaScript Execution**: Allow custom JS to run before content extraction
8. **Cache**: Cache Playwright results to avoid re-fetching unchanged content

## Success Criteria

### Phase 1 (Initial Release)
1. ✅ HTTP 401/403 errors trigger Playwright fallback automatically
2. ✅ Playwright successfully fetches pages that HTTP cannot
3. ✅ 404/5xx errors do NOT trigger fallback (fail fast)
4. ✅ Browser context is reused across batch processing
5. ✅ All tests pass (unit, integration) for Phase 1
6. ✅ Linting passes (ruff, mypy)
7. ✅ Documentation includes phase descriptions
8. ✅ Performance impact is acceptable (<2x slowdown for fallback cases)
9. ✅ Graceful degradation when Playwright is unavailable
10. ✅ Metrics captured in Langfuse (fetch_method, error_category, phase)

### Phase 2+ (Future Rollout)
1. ✅ Baseline metrics from Phase 1 collected (1-2 weeks)
2. ✅ Playwright success rate for 401/403 is >60%
3. ✅ Phase 2 config enables 429 fallback correctly
4. ✅ Tests pass for Phase 2 error cases
5. ✅ Monitoring shows Phase 2 effectiveness

### Overall Quality
1. ✅ Error messages clearly indicate which method(s) tried and failed
2. ✅ Logging is structured and query-able
3. ✅ Configuration is well-documented with examples
4. ✅ Code follows project conventions (AGENTS.md)
5. ✅ No performance regression for HTTP-only paths

## Rollback Plan

If issues arise:
1. Disable Playwright via config: `PLAYWRIGHT_ENABLED=false`
2. Revert to previous branch: `git checkout main`
3. Remove Playwright dependency: `uv remove playwright`
4. Remove new files: `rm summarize_links/extract/playwright_fetching.py`

## Conclusion

This implementation adds robust fallback for blocked HTTP requests while maintaining backward compatibility and performance. The design prioritizes:
- **Simplicity**: Minimal config, works out-of-box
- **Performance**: Fast HTTP as primary, Playwright only when needed
- **Reliability**: Graceful fallback chain, clear error messages
- **Testability**: Comprehensive mocking and test coverage
