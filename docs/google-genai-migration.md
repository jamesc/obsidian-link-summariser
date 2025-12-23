# Migration to Google GenAI SDK

**Date**: December 23, 2025

## Overview

This project has been migrated from the deprecated `google-generativeai` package to the new `google-genai` SDK, following Google's migration guide at https://ai.google.dev/gemini-api/docs/migrate.

## What Changed

### Dependencies

- **Before**: `google-generativeai>=0.8.0`
- **After**: `google-genai>=0.1.0`, `pydantic>=2.0`

The new SDK includes `pydantic` as a dependency for type-safe models.

### API Changes

#### Client Initialization

**Before**:
```python
import google.generativeai as genai

genai.configure(api_key=api_key)
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction=SYSTEM_PROMPT
)
response = model.generate_content(prompt)
```

**After**:
```python
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)
response = client.models.generate_content(
    model="gemini-1.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT
    )
)
```

#### Key Differences

1. **Centralized Client**: The new SDK uses a centralized `Client` object that manages all API interactions, replacing the old implicit configuration approach.

2. **Explicit Configuration**: Configuration like `system_instruction` is now passed via `GenerateContentConfig` rather than during model initialization.

3. **Error Handling**: The new SDK uses `errors.ClientError` instead of Google API Core exceptions:
   - `google.api_core.exceptions.ResourceExhausted` → Detect via `errors.ClientError` with "429" or "quota" in error message
   - `google.api_core.exceptions.InvalidArgument` → Detect via `errors.ClientError` with "400" or "invalid" in error message
   - `google.api_core.exceptions.PermissionDenied` → Detect via `errors.ClientError` with "403" or "permission" in error message

## Files Modified

### Core Library
- **summarize_links/gemini_client.py**: Complete rewrite to use new SDK client architecture
- **pyproject.toml**: Updated dependencies

### Tests
- **tests/test_gemini.py**: Updated all tests to mock new SDK patterns and error types

## Testing

All 423 tests pass after migration:
```bash
uv run pytest
```

Static analysis also passes:
```bash
uv run ruff check .
uv run mypy .
```

## Backward Compatibility

The public API of `GeminiClient` and `MockGeminiClient` remains unchanged. Users of the library should not need to make any changes to their code.

## Environment Variables

The new SDK supports both `GEMINI_API_KEY` and `GOOGLE_API_KEY` environment variables. Our implementation continues to use `GEMINI_API_KEY` as before.

## Known Issues

None at this time. The migration was completed without any breaking changes to the public API.

## References

- [Google GenAI SDK Migration Guide](https://ai.google.dev/gemini-api/docs/migrate)
- [New Google GenAI SDK Repository](https://github.com/googleapis/python-genai)
- [Deprecated SDK Archive](https://github.com/google-gemini/deprecated-generative-ai-python)
