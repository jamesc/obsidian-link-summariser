# LLM Provider Refactoring Plan

## Overview

This plan consolidates shared functionality across `GeminiClient`, `AzureClient`, and `OllamaClient` into the `BaseLLMClient` base class, reducing code duplication and improving maintainability.

**Scope**: Items 1-4 and 6 from the refactoring analysis.

---

## Phase 1: Shared Constants (Item 6)

**Goal**: Move retry configuration constants to `base.py`.

### Changes

1. **Add constants to `base.py`**:
   ```python
   # Retry configuration (shared across rate-limited clients)
   MAX_RETRIES = 5
   BASE_RETRY_DELAY = 2.0  # Base delay for exponential backoff (seconds)
   MIN_RATE_LIMIT_WAIT = 10.0  # Minimum wait when rate limited (seconds)
   MAX_RETRY_DELAY = 120.0  # Maximum delay cap (seconds)
   ```

2. **Update `gemini.py`**: Remove local constants, import from `base`

3. **Update `azure.py`**: Remove local constants, import from `base`

### Testing
- Run existing tests to verify no regressions

---

## Phase 2: Rate Limiter Initialization (Item 2)

**Goal**: Move rate limiter setup logic to `BaseLLMClient`.

### Current State (duplicated in GeminiClient and AzureClient)
```python
# ~25 lines of identical logic:
# - Check model_limits parameter
# - Check legacy rpm/tpm/daily params
# - Call get_model_rate_limits()
# - Create or use provided RateLimiter
```

### Changes

1. **Add to `BaseLLMClient.__init__()`**:
   ```python
   def __init__(
       self,
       error_class: type[Exception],
       model: str | None = None,
       rate_limiter: RateLimiter | None = None,
       state_path: Path | None = None,
       model_limits: ModelRateLimits | None = None,
       yaml_model_limits: dict[str, dict[str, int]] | None = None,
       rpm_limit: int | None = None,
       tpm_limit: int | None = None,
       daily_limit: int | None = None,
       default_rpm: int = 5,
       default_tpm: int = 250000,
       default_daily: int = 20,
   ) -> None:
   ```

2. **Add `_init_rate_limiter()` helper method** to `BaseLLMClient`:
   - Handles the model_limits vs legacy params vs defaults logic
   - Creates `RateLimiter` if not provided
   - Sets `self._rate_limiter` attribute

3. **Simplify `GeminiClient.__init__()`**: Call `super().__init__()` with rate limit params

4. **Simplify `AzureClient.__init__()`**: Call `super().__init__()` with rate limit params

5. **Update `OllamaClient`**: Optionally pass `model` but no rate limiter (see Phase 4)

### Testing
- `test_gemini.py`: Verify rate limiter initialization still works
- `test_azure.py`: Verify rate limiter initialization still works
- Add new test in `test_llm_factory.py` for base class rate limiter logic

---

## Phase 3: Retry Logic Consolidation (Item 1)

**Goal**: Extract common retry-with-rate-limiting pattern into base class.

### Current Duplication
Both `GeminiClient` and `AzureClient` have:
- `_calculate_rate_limit_wait()` - **identical** implementation
- Retry loop pattern in `summarize()` and `summarize_with_metadata()`

### Changes

1. **Move `_calculate_rate_limit_wait()` to `BaseLLMClient`**:
   ```python
   def _calculate_rate_limit_wait(self, attempt: int, error: Exception) -> float:
       """Calculate wait time when rate limited."""
       # Existing implementation (identical in both clients)
   ```

2. **Add generic retry helper to `BaseLLMClient`**:
   ```python
   def _call_with_retry(
       self,
       operation: Callable[[], T],
       estimated_tokens: int,
       rate_limit_error_class: type[Exception],
       is_rate_limit_error: Callable[[Exception], bool],
       is_retryable_error: Callable[[Exception], bool],
       handle_non_retryable: Callable[[Exception], None] | None = None,
   ) -> T:
       """
       Execute an operation with retry logic and rate limiting.

       Args:
           operation: Callable that performs the API call
           estimated_tokens: Estimated token count for rate limiting
           rate_limit_error_class: Exception class for rate limit errors
           is_rate_limit_error: Predicate to detect rate limit errors
           is_retryable_error: Predicate to detect retryable errors
           handle_non_retryable: Optional handler for non-retryable errors

       Returns:
           Result from the operation

       Raises:
           rate_limit_error_class: When rate limited after retries exhausted
           error_class: When API returns non-retryable error
       """
   ```

3. **Refactor `GeminiClient.summarize()`**: Use `_call_with_retry()`

4. **Refactor `GeminiClient.summarize_with_metadata()`**: Use `_call_with_retry()`

5. **Refactor `AzureClient.summarize()`**: Use `_call_with_retry()`

6. **Refactor `AzureClient.summarize_with_metadata()`**: Use `_call_with_retry()`

### Alternative Approach (Simpler)
If the generic retry helper proves too complex, just move `_calculate_rate_limit_wait()` to base and keep the retry loops in each client. This still eliminates ~30 lines of duplication.

### Testing
- All existing tests should pass
- Add test for `_calculate_rate_limit_wait()` in base class
- Add test for `_call_with_retry()` if implemented

---

## Phase 4: Optional Rate Limiting for OllamaClient (Item 4)

**Goal**: Give `OllamaClient` the same rate limiter infrastructure for consistency.

### Rationale
- Local models typically don't need rate limiting
- But having the infrastructure allows:
  - Consistent interface across all clients
  - Future support for remote Ollama deployments
  - Optional self-imposed limits for resource management

### Changes

1. **Update `OllamaClient.__init__()`**:
   ```python
   def __init__(
       self,
       model: str,
       endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
       timeout: int = DEFAULT_TIMEOUT,
       rate_limiter: RateLimiter | None = None,  # Optional
       # ... other rate limit params with high defaults
   ) -> None:
   ```

2. **Make rate limiting optional**:
   - If no rate limiter provided and no limits specified, skip rate limiting
   - If rate limiter provided, use it
   - Add `self._rate_limiter: RateLimiter | None` attribute

3. **Update `summarize()` and `summarize_with_metadata()`**:
   ```python
   if self._rate_limiter:
       self._rate_limiter.wait_if_needed(estimated_tokens)
   ```

### Testing
- Existing Ollama tests should pass (no rate limiter by default)
- Add test for Ollama with optional rate limiter

---

## Phase 5: Token Usage Helper (Item 3)

**Goal**: Standardize usage details extraction.

### Changes

1. **Add helper to `BaseLLMClient`**:
   ```python
   @staticmethod
   def _build_usage_details(
       input_tokens: int,
       output_tokens: int,
       total_tokens: int | None = None,
   ) -> dict[str, int]:
       """Build standardized usage details dictionary."""
       return {
           "input": input_tokens,
           "output": output_tokens,
           "total": total_tokens if total_tokens is not None else input_tokens + output_tokens,
       }
   ```

2. **Update all clients** to use `_build_usage_details()`

### Testing
- Existing tests should pass

---

## Implementation Order

1. **Phase 1** (Constants) - No functional changes, pure consolidation
2. **Phase 5** (Usage helper) - Simple addition, low risk
3. **Phase 2** (Rate limiter init) - Moderate complexity
4. **Phase 3** (Retry logic) - Higher complexity, biggest impact
5. **Phase 4** (Ollama rate limiting) - Optional enhancement

---

## File Changes Summary

| File | Changes |
|------|---------|
| `llm/base.py` | Add constants, rate limiter init, retry helper, usage helper |
| `llm/gemini.py` | Simplify init, use base class methods |
| `llm/azure.py` | Simplify init, use base class methods |
| `llm/ollama.py` | Optional rate limiter support |
| `tests/test_gemini.py` | Verify existing tests pass |
| `tests/test_azure.py` | Verify existing tests pass |
| `tests/test_ollama_client.py` | Add optional rate limiter test |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing behavior | Run full test suite after each phase |
| Over-abstraction making code harder to understand | Keep retry loops if generic helper is too complex |
| Rate limiter coupling issues | Make rate limiter optional with `None` default |

---

## Success Criteria

- [ ] All existing tests pass
- [ ] No duplicate retry constants across files
- [ ] `_calculate_rate_limit_wait()` exists only in `BaseLLMClient`
- [ ] Rate limiter initialization logic exists only in `BaseLLMClient`
- [ ] `OllamaClient` supports optional rate limiting
- [ ] Code coverage maintained or improved

---

## Estimated Effort

| Phase | Effort | Risk |
|-------|--------|------|
| Phase 1 | 15 min | Low |
| Phase 5 | 15 min | Low |
| Phase 2 | 45 min | Medium |
| Phase 3 | 1-2 hrs | Medium-High |
| Phase 4 | 30 min | Low |

**Total**: ~3-4 hours including testing
