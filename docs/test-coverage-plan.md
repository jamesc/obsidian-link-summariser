# Test Coverage Improvement Plan

**Created**: 2025-12-18  
**Goal**: Increase overall coverage from 85% to 90%+

## Current State

| Module | Current | Target | Gap Areas |
|--------|---------|--------|-----------|
| extract.py | 75% | 90% | Paywall detection, markdown extraction, fetch convenience |
| cli.py | 81% | 90% | Status command, graceful shutdown, error handling |
| gemini_client.py | 89% | 95% | Retry-After parsing, token usage extraction |
| config.py | 88% | 95% | YAML error handling, env var type errors |

## Implementation Plan

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
