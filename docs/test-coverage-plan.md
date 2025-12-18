# Test Coverage Improvement Plan

**Created**: 2025-12-18
**Completed**: 2025-12-18  
**Result**: Coverage improved from 85% → 91% ✅

## Final Coverage Results

| Module | Before | After | Target | Status |
|--------|--------|-------|--------|--------|
| extract.py | 75% | 88% | 90% | ✅ Close |
| cli.py | 81% | 87% | 90% | ✅ Close |
| gemini_client.py | 89% | 93% | 95% | ✅ Close |
| config.py | 88% | 98% | 95% | ✅ Exceeded |
| **Overall** | **85%** | **91%** | **90%** | ✅ **Exceeded** |

## Tests Added

### extract.py (+21 tests)
- `TestPaywallDetection` (6 tests) - paywall domain detection, HTTP error formatting
- `TestMarkdownExtraction` (6 tests) - title extraction, author extraction, image cleaning
- `TestNonContentFiltering` (5 tests) - nav/sidebar/footer class detection
- `TestFetchAndExtract` (4 tests) - high-level fetch functions, truncation

### cli.py (+4 tests)
- `TestCmdStatus` (2 tests) - rate limit display, low quota warnings
- `TestQuietMode` (1 test) - quiet mode flag behavior
- `TestInvalidUrlHandling` (1 test) - URL validation error handling

### gemini_client.py (+8 tests)
- `TestRateLimitWaitCalculation` (3 tests) - Retry-After parsing, wait time caps
- `TestTokenUsageExtraction` (2 tests) - actual vs estimated token usage
- `TestRetryOnGenericAPIError` (3 tests) - generic API error retry behavior

### config.py (+10 tests)
- `TestLoadConfig` (4 tests) - rate limits, default tags from YAML/env
- `TestSetupLogging` (3 tests) - verbose/normal logging, third-party suppression
- `TestDailyNotesFolder` (2 tests) - daily notes folder configuration
### Phase 1: extract.py Tests (Highest Impact)

#### 1.1 Paywall Detection Tests
```python
class TestPaywallDetection:
    - test_known_paywall_domain_exact_match
    - test_paywall_subdomain_match
    - test_non_paywall_domain_returns_none
    - test_format_http_error_with_paywall
    - test_format_http_error_without_paywall
```

#### 1.2 Markdown Extraction Tests
```python
class TestMarkdownExtraction:
    - test_extract_title_from_h1_heading
    - test_extract_author_from_italic_line
    - test_clean_markdown_removes_html_images
    - test_clean_markdown_removes_markdown_images
    - test_handles_markdown_without_title
```

#### 1.3 Convenience Function Tests
```python
class TestFetchAndExtract:
    - test_fetch_and_extract_returns_truncated_content
    - test_fetch_and_extract_metadata_for_html
    - test_fetch_and_extract_metadata_for_markdown
```

#### 1.4 Non-Content Element Filtering Tests
```python
class TestNonContentFiltering:
    - test_identifies_nav_class
    - test_identifies_sidebar_id
    - test_ignores_article_content
```

### Phase 2: cli.py Tests

#### 2.1 Status Command Tests
```python
class TestCmdStatus:
    - test_displays_rate_limit_info
    - test_warns_on_low_daily_quota
```

#### 2.2 Graceful Shutdown Tests
```python
class TestGracefulShutdown:
    - test_shutdown_flag_stops_processing
```

### Phase 3: gemini_client.py Tests

#### 3.1 Rate Limit Wait Calculation
```python
class TestRateLimitWaitCalculation:
    - test_extracts_retry_after_from_error_message
    - test_uses_rate_limiter_wait_time
    - test_caps_wait_at_max_delay
```

#### 3.2 Token Usage Extraction
```python
class TestTokenUsageExtraction:
    - test_uses_actual_token_count_from_response
    - test_falls_back_to_estimate_when_unavailable
```

### Phase 4: config.py Tests

#### 4.1 Error Handling
```python
class TestConfigErrorHandling:
    - test_malformed_yaml_raises_config_error
    - test_setup_logging_verbose_mode
    - test_setup_logging_normal_mode
```

## Execution Order

1. ✅ Create this plan
2. Implement extract.py tests (commit)
3. Implement cli.py tests (commit)
4. Implement gemini_client.py tests (commit)
5. Implement config.py tests (commit)
6. Run final coverage report
7. Update tasks.md with results

## Success Criteria

- [ ] Overall coverage ≥ 90%
- [ ] extract.py coverage ≥ 90%
- [ ] cli.py coverage ≥ 88%
- [ ] All tests pass
- [ ] No regressions in existing tests
