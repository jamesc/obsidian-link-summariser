# Per-Model Rate Limits Implementation Plan

**Created**: 2025-12-18
**Branch**: `feature/per-model-rate-limits`
**Status**: ✅ Completed

## Overview

Update the rate limiter to support per-model rate limiting with configurable limits and a 10% safety margin.

## Requirements

1. **Per-model rate limits**: Each model gets its own rate limit state, so switching models during the day applies new rate limits
2. **Configurable limits per model**: Allow specifying different limits for different models via config
3. **10% safety margin**: Work at 90% of actual limits to avoid hitting API rate limits

## Current State

The current `RateLimiter` class:
- Uses global limits from `config.py` constants (`GEMINI_RPM_LIMIT`, `GEMINI_TPM_LIMIT`, `GEMINI_DAILY_LIMIT`)
- Stores a single daily request count
- Does not distinguish between models

## Proposed Changes

### 1. rate_limiter.py

#### New `ModelRateLimits` dataclass
```python
@dataclass
class ModelRateLimits:
    """Rate limit configuration for a specific model."""
    rpm_limit: int
    tpm_limit: int
    daily_limit: int

    def with_safety_margin(self) -> "ModelRateLimits":
        """Return limits with safety margin applied (90% of actual limits)."""
        return ModelRateLimits(
            rpm_limit=max(1, int(self.rpm_limit * SAFETY_MARGIN)),
            tpm_limit=max(1, int(self.tpm_limit * SAFETY_MARGIN)),
            daily_limit=max(1, int(self.daily_limit * SAFETY_MARGIN)),
        )
```

#### Updated `RateLimitState`
- Add `daily_requests_by_model: dict[str, int]` for per-model daily tracking
- Keep legacy `daily_requests` for backward compatibility
- Add methods: `get_daily_requests(model)`, `increment_daily_requests(model)`

#### Updated `RateLimiter`
- Add `model: str` attribute to track current model
- Add `model_limits: dict[str, ModelRateLimits]` for per-model configuration
- Apply safety margin automatically to all limits
- Per-minute limits (RPM/TPM) remain shared (sliding window) but daily limits are per-model
- Add `switch_model(model: str)` method to change active model and limits

### 2. config.py

#### New model limits configuration
```python
# Default rate limits per model (actual API limits)
DEFAULT_MODEL_LIMITS: dict[str, dict[str, int]] = {
    "gemini-2.5-flash": {
        "rpm_limit": 10,
        "tpm_limit": 250000,
        "daily_limit": 500,
    },
    "gemini-2.5-pro": {
        "rpm_limit": 5,
        "tpm_limit": 250000,
        "daily_limit": 25,
    },
    "gemini-1.5-flash": {
        "rpm_limit": 15,
        "tpm_limit": 1000000,
        "daily_limit": 1500,
    },
    "gemini-1.5-pro": {
        "rpm_limit": 2,
        "tpm_limit": 32000,
        "daily_limit": 50,
    },
}

def get_model_rate_limits(model: str) -> ModelRateLimits:
    """Get rate limits for a specific model."""
```

#### YAML config support
```yaml
# .summarizer-config.yaml
model_limits:
  gemini-2.5-flash:
    rpm_limit: 10
    tpm_limit: 250000
    daily_limit: 500
  gemini-2.5-pro:
    rpm_limit: 5
    tpm_limit: 250000
    daily_limit: 25
```

### 3. gemini_client.py

- Pass model name to rate limiter
- Update `GeminiClient.__init__` to use model-specific limits
- Update `create_client` factory function

### 4. Persistent State Format

Updated `.summarizer-rate-limit.json`:
```json
{
  "date": "2025-12-18",
  "daily_requests_by_model": {
    "gemini-2.5-flash": 15,
    "gemini-2.5-pro": 3
  },
  "daily_requests": 18
}
```

## Implementation Steps

1. [x] Update `rate_limiter.py`:
   - Add `ModelRateLimits` dataclass
   - Add `SAFETY_MARGIN = 0.9` constant
   - Update `RateLimitState` for per-model tracking
   - Update `RateLimiter` to accept model and apply safety margin
   - Add `switch_model()` method

2. [x] Update `config.py`:
   - Add `DEFAULT_MODEL_LIMITS` dictionary
   - Add `get_model_rate_limits()` function
   - Support model limits from YAML config

3. [x] Update `gemini_client.py`:
   - Pass model to rate limiter initialization
   - Update client to use model-specific limits

4. [x] Update tests:
   - Test per-model daily limit tracking
   - Test safety margin application
   - Test model switching
   - Test backward compatibility with old state files

5. [x] Run tests and validate

6. [x] Document changes in `tasks.md`

## Safety Margin Details

The 10% safety margin means:
- If API limit is 10 RPM, effective limit is 9 RPM
- If API limit is 500 daily, effective limit is 450 daily
- This provides buffer to avoid hitting hard API limits

## Backward Compatibility

- Old state files without `daily_requests_by_model` will work (uses `daily_requests` as fallback)
- Legacy `daily_requests` field maintained for total tracking
- Existing CLI flags continue to work

## Success Criteria

- [x] Per-model daily limits work correctly
- [x] Safety margin applied to all limits (90% of actual)
- [x] Model switching updates active limits
- [x] State persisted and loaded correctly per-model
- [x] All existing tests pass
- [x] New tests for per-model functionality pass
