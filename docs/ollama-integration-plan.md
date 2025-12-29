# Ollama Integration Implementation Plan

**Date:** 2025-12-29  
**Status:** Planning

## Overview

Add support for local LLM models via Ollama alongside existing Gemini API support. The system will automatically detect which provider to use based on the model name, maintaining feature parity between both providers.

## Requirements

1. ✅ Support multiple Ollama models (llama3, mistral, phi, etc.)
2. ✅ Automatic provider selection based on model name
3. ✅ Same structured JSON output (summary, tags, content_type)
4. ✅ No rate limiting for local models
5. ✅ Custom Ollama endpoint configuration
6. ✅ Maintain both providers long-term
7. ✅ Clear error messages when Ollama server unavailable

## Architecture Changes

### Provider Detection Logic

Models will be detected as Ollama if they match patterns like:
- `llama3:latest`, `llama3.1`, `llama3.2`
- `mistral:latest`, `mistral-large`
- `phi3:mini`, `phi3.5`
- `qwen2.5`, `gemma2`
- Any model name containing `:` (Ollama tag notation)
- Explicitly checking against known Ollama model prefixes

Otherwise, assume Gemini API.

### Module Structure

```
summarize_links/
├── gemini_client.py       # Existing Gemini implementation
├── ollama_client.py       # NEW: Ollama implementation
├── llm_factory.py         # NEW: Provider detection & client factory
├── config.py              # Add OLLAMA_ENDPOINT config
└── ...
```

### Configuration Updates

**Environment Variables (Backward Compatible):**

Add to `.env` and `.env.example`:
```bash
# API Keys (provider-specific)
GEMINI_API_KEY=your-key-here

# Model Selection (generic - works for both providers)
MODEL=llama3:latest              # Uses Ollama
# MODEL=gemini-2.5-flash         # Uses Gemini

# Legacy: GEMINI_MODEL still supported for backward compatibility
# GEMINI_MODEL=gemini-2.5-flash  # Deprecated, use MODEL instead

# Ollama Configuration
OLLAMA_ENDPOINT=http://localhost:11434  # Optional, defaults to localhost

# Rate Limits (Gemini only - no limits on local Ollama models)
# GEMINI_RPM_LIMIT=5
# GEMINI_TPM_LIMIT=250000
# GEMINI_DAILY_LIMIT=20
```

**Priority Order for Model Selection:**
1. CLI `--model` argument (highest priority)
2. `MODEL` environment variable
3. `GEMINI_MODEL` environment variable (deprecated but supported)
4. `model` in YAML config
5. `DEFAULT_MODEL` constant (lowest priority)

Add to `.summarizer-config.yaml`:
```yaml
# Ollama configuration
ollama_endpoint: "http://localhost:11434"  # Optional

# Model selection (auto-detects provider)
model: "llama3:latest"  # Uses Ollama
# model: "gemini-2.5-flash"  # Uses Gemini
```

## Implementation Tasks

### Phase 1: Core Infrastructure

#### Task 1.1: Create Ollama Client Module
**File:** `summarize_links/ollama_client.py`

**Implementation:**
```python
"""
Ollama API client for content summarization.

Provides local LLM support via Ollama, with the same interface
as GeminiClient for seamless provider switching.
"""

import json
import logging
from typing import Any, Protocol

import requests

from summarize_links.config import DEFAULT_OLLAMA_ENDPOINT
from summarize_links.exceptions import OllamaAPIError, OllamaServerError
from summarize_links.models import SummaryResult

class OllamaClient:
    """Client for Ollama API with structured output support."""
    
    def __init__(
        self,
        model: str,
        endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        timeout: int = 120,
    ) -> None:
        """Initialize Ollama client."""
        pass
    
    def summarize(self, content: str, url: str, title: str | None = None) -> str:
        """Generate summary using Ollama model."""
        pass
    
    def summarize_with_metadata(
        self, content: str, url: str, title: str | None = None
    ) -> SummaryResult:
        """Generate summary with structured metadata."""
        pass
    
    def _check_server(self) -> None:
        """Check if Ollama server is running."""
        pass
    
    def _check_model_installed(self) -> None:
        """Check if model is pulled/installed."""
        pass
```

**Key Features:**
- Same `SummarizerProtocol` interface as `GeminiClient`
- No rate limiting (local models)
- Check server availability on first request
- Validate model is installed
- Use same system prompt as Gemini for consistency
- Parse JSON responses (same format as Gemini)
- Proper timeout handling (local models may be slower)

#### Task 1.2: Create LLM Factory Module
**File:** `summarize_links/llm_factory.py`

**Implementation:**
```python
"""
Factory for creating LLM clients based on model name.

Automatically detects provider (Ollama vs Gemini) and returns
the appropriate client implementation.
"""

import logging
from pathlib import Path

from summarize_links.gemini_client import GeminiClient, MockGeminiClient
from summarize_links.ollama_client import OllamaClient
from summarize_links.exceptions import ConfigError

# Known Ollama model prefixes
OLLAMA_MODEL_PREFIXES = [
    "llama", "mistral", "phi", "qwen", "gemma", "codellama",
    "mixtral", "neural-chat", "starling", "orca", "vicuna",
    "wizardlm", "yi", "solar", "deepseek", "openchat",
]

def detect_provider(model: str) -> str:
    """
    Detect which provider to use based on model name.
    
    Args:
        model: Model name/identifier
        
    Returns:
        "ollama" or "gemini"
    """
    # Ollama models typically use : for tags (e.g., llama3:latest)
    if ":" in model:
        return "ollama"
    
    # Check against known Ollama model prefixes
    model_lower = model.lower()
    for prefix in OLLAMA_MODEL_PREFIXES:
        if model_lower.startswith(prefix):
            return "ollama"
    
    # Default to Gemini
    return "gemini"

def create_llm_client(
    model: str,
    gemini_api_key: str | None = None,
    ollama_endpoint: str | None = None,
    mock_mode: bool = False,
    state_path: Path | None = None,
    **kwargs,
) -> SummarizerProtocol:
    """
    Create appropriate LLM client based on model name.
    
    Args:
        model: Model identifier
        gemini_api_key: API key for Gemini (required for Gemini models)
        ollama_endpoint: Ollama server endpoint (defaults to localhost)
        mock_mode: Use mock client for testing
        state_path: Path for rate limiter state (Gemini only)
        **kwargs: Additional provider-specific arguments
        
    Returns:
        Configured client implementing SummarizerProtocol
        
    Raises:
        ConfigError: If required configuration is missing
    """
    if mock_mode:
        return MockGeminiClient(model=model)
    
    provider = detect_provider(model)
    
    if provider == "ollama":
        return OllamaClient(
            model=model,
            endpoint=ollama_endpoint,
        )
    else:  # gemini
        if not gemini_api_key:
            raise ConfigError("GEMINI_API_KEY required for Gemini models")
        return GeminiClient(
            api_key=gemini_api_key,
            model=model,
            state_path=state_path,
            **kwargs,
        )
```

#### Task 1.3: Update Configuration
**Files:** `summarize_links/config.py`

**Changes:**
1. Add constants:
   ```python
   DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
   OLLAMA_TIMEOUT = 120  # Seconds
   ```

2. Add to `Config` dataclass:
   ```python
   ollama_endpoint: str = DEFAULT_OLLAMA_ENDPOINT
   ```

3. Update `load_config()` to implement priority order:
   ```python
   # Model selection with backward compatibility
   # Priority: CLI arg > MODEL env > GEMINI_MODEL env > YAML > default
   if model:  # CLI argument
       config.model = model
   elif os.getenv("MODEL"):  # New generic env var
       config.model = os.getenv("MODEL", DEFAULT_MODEL)
   elif os.getenv("GEMINI_MODEL"):  # Deprecated but supported
       config.model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
       logger.warning("GEMINI_MODEL is deprecated, use MODEL instead")
   elif "model" in yaml_config:
       config.model = yaml_config["model"]
   
   # Ollama endpoint
   if os.getenv("OLLAMA_ENDPOINT"):
       config.ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", DEFAULT_OLLAMA_ENDPOINT)
   elif "ollama_endpoint" in yaml_config:
       config.ollama_endpoint = yaml_config["ollama_endpoint"]
   ```

4. Update `Config.validate()`:
   - Detect provider using `detect_provider()` function
   - Don't require `gemini_api_key` if using Ollama model:
     ```python
     from summarize_links.llm_factory import detect_provider
     
     provider = detect_provider(self.model)
     
     # API key only required for Gemini (unless mock mode)
     if not self.mock_mode and provider == "gemini" and not self.gemini_api_key:
         raise ConfigError("GEMINI_API_KEY required for Gemini models")
     ```

#### Task 1.4: Add New Exceptions
**File:** `summarize_links/exceptions.py`

**Add:**
```python
class OllamaServerError(SummarizerError):
    """Raised when Ollama server is not available."""
    pass

class OllamaAPIError(SummarizerError):
    """Raised when Ollama API returns an error."""
    pass

class ModelNotInstalledError(SummarizerError):
    """Raised when required Ollama model is not installed."""
    pass
```

### Phase 2: CLI Integration

#### Task 2.1: Update CLI to Use Factory
**File:** `summarize_links/cli.py`

**Changes:**
1. Import `create_llm_client` from `llm_factory`
2. Replace `create_client()` calls with `create_llm_client()`
3. Pass `ollama_endpoint` from config
4. Update error handling for new exception types:
   ```python
   except OllamaServerError as e:
       _print_error(
           "[red]Ollama server not available![/]\n"
           "[yellow]To start Ollama:[/]\n"
           "  • Start Ollama app, or\n"
           "  • Run: ollama serve\n\n"
           f"Error: {e}"
       )
   ```

#### Task 2.2: Add Provider Info to Status Command
**File:** `summarize_links/cli.py` - `cmd_status()`

**Enhancement:**
Show which provider is active:
```python
_print(f"[bold]Provider:[/] {provider.upper()}")
_print(f"[bold]Model:[/] {config.model}\n")

if provider == "ollama":
    _print(f"[bold]Endpoint:[/] {config.ollama_endpoint}")
    _print("[cyan]No rate limiting for local models[/]\n")
else:
    # Show existing rate limit table
    ...
```

### Phase 3: Testing

#### Task 3.1: Unit Tests for Ollama Client
**File:** `tests/test_ollama_client.py`

**Test Cases:**
- Connection to Ollama server
- Model availability checking
- Successful summarization
- JSON parsing and structured output
- Error handling (server down, model missing)
- Timeout behavior

#### Task 3.2: Unit Tests for Provider Detection
**File:** `tests/test_llm_factory.py`

**Test Cases:**
- Detect Ollama models (with `:`, known prefixes)
- Detect Gemini models (default)
- Factory creates correct client type
- Configuration validation

#### Task 3.3: Integration Tests
**File:** `tests/test_ollama_integration.py`

**Test Cases:**
- End-to-end with Ollama model (if available)
- Graceful degradation when server unavailable
- Switching between providers via model name

#### Task 3.4: Update Existing Tests
**Files:** Various test files

**Changes:**
- Mock `detect_provider()` where needed
- Update fixtures to handle both providers
- Ensure mock mode works with both

### Phase 4: Documentation

#### Task 4.1: Update README
**File:** `README.md`

**Sections to Add:**
```markdown
## Using Local Models with Ollama

This tool supports local LLMs via [Ollama](https://ollama.ai) 
as an alternative to the Gemini API.

### Setup

1. Install Ollama: https://ollama.ai/download
2. Pull a model: `ollama pull llama3`
3. Start Ollama server: `ollama serve` (or use the app)

### Configuration

Use any Ollama model by specifying it in your config:

```yaml
# .summarizer-config.yaml
model: "llama3:latest"  # Or mistral, phi3, etc.
ollama_endpoint: "http://localhost:11434"  # Optional
```

Or via CLI:
```bash
summarize-links from-note --model llama3:latest
```

### Supported Models

Any model available in Ollama can be used:
- llama3, llama3.1, llama3.2
- mistral, mixtral
- phi3, phi3.5
- qwen2.5
- gemma2
- And more...

See: https://ollama.ai/library

### Provider Selection

The tool automatically detects which provider to use:
- Models with `:` → Ollama (e.g., `llama3:latest`)
- Known Ollama models → Ollama (e.g., `mistral`)
- Others → Gemini API (e.g., `gemini-2.5-flash`)
```

#### Task 4.2: Update Configuration Guide
**File:** `docs/spec.md` or create `docs/ollama-setup.md`

**Include:**
- Detailed configuration options
- Performance considerations
- Model recommendations
- Troubleshooting guide

#### Task 4.3: Add Examples
**File:** `docs/examples.md` (new)

**Include:**
- Switching between providers
- Model comparison workflows
- Custom endpoint configuration

### Phase 5: Code Quality

#### Task 5.1: Type Hints
- Ensure all new code has complete type annotations
- Run `mypy .` to verify

#### Task 5.2: Code Formatting
- Run `ruff format .`
- Run `ruff check .`
- Fix any issues

#### Task 5.3: Logging
- Add appropriate DEBUG/INFO logs
- Follow existing patterns
- Log provider selection

#### Task 5.4: Error Messages
- User-friendly messages
- Include helpful instructions
- Link to documentation

## Technical Considerations

### Ollama API

**Endpoint:** `POST /api/generate`
```json
{
  "model": "llama3",
  "prompt": "...",
  "stream": false,
  "format": "json"
}
```

**Response:**
```json
{
  "model": "llama3",
  "response": "{\"summary\": \"...\", \"suggested_tags\": [...], \"content_type\": \"...\"}",
  "done": true
}
```

**Health Check:** `GET /api/tags`
- Returns list of installed models
- Use to verify server and model availability

### Prompt Engineering

- Use **same system prompt** as Gemini for consistency
- Ollama's `format: "json"` helps constrain output
- May need model-specific tweaks if output quality varies

### Performance

- Local models typically **slower** than API
- Increase timeout to 120s (vs 10s for HTTP)
- Consider progress updates for long-running summaries
- No rate limiting needed (unlimited local usage)

### Model Installation

When model not found:
```python
raise ModelNotInstalledError(
    f"Model '{model}' not installed.\n"
    f"To install: ollama pull {model}"
)
```

## Migration Path

### For Existing Users

No changes required! Existing Gemini configurations continue to work.

### For New Users

1. Can start with Ollama (free, no API key)
2. Can switch to Gemini for better quality/speed
3. Can use both for different use cases

## Dependencies

### New Python Packages

Add to `pyproject.toml`:
```toml
[project]
dependencies = [
    # ... existing ...
    # Ollama uses standard HTTP, no special package needed
    # Already have: requests (or httpx)
]
```

Actually, we already have `requests` via `trafilatura`, or we could use standard `urllib`. Check existing dependencies.

## Testing Strategy

### Local Testing
```bash
# Start Ollama
ollama serve

# Pull test model
ollama pull llama3

# Run with Ollama
summarize-links from-note --model llama3:latest --verbose

# Compare with Gemini
summarize-links from-note --model gemini-2.5-flash --verbose
```

### CI/CD
- Mock Ollama responses in CI (server won't be available)
- Add optional integration tests if Ollama available
- Don't block on Ollama tests

## Open Questions

1. **Default Model:** After evaluation, which should be default?
   - Gemini: Better quality, faster, but requires API key
   - Ollama: Free, private, but slower and needs setup

2. **Model Recommendations:** Which Ollama models work best?
   - Need to test: llama3, mistral, phi3 for summary quality
   - Document findings in README

3. **Fallback Behavior:** Should we support automatic fallback?
   - If Ollama unavailable, try Gemini?
   - Probably NO - explicit choice is clearer

4. **Model Aliases:** Should we support friendly names?
   - `--model local` → uses configured Ollama model
   - `--model cloud` → uses configured Gemini model
   - Could be a future enhancement

## Success Criteria

- ✅ Can summarize URLs using Ollama models
- ✅ Same quality frontmatter as Gemini
- ✅ Clear error messages when Ollama unavailable
- ✅ All tests passing
- ✅ Documentation complete
- ✅ Zero breaking changes for existing users
- ✅ Code follows existing patterns (comments, types, tests)

## Timeline Estimate

- **Phase 1 (Core):** 4-6 hours
- **Phase 2 (CLI):** 2-3 hours
- **Phase 3 (Testing):** 3-4 hours
- **Phase 4 (Docs):** 2-3 hours
- **Phase 5 (Polish):** 1-2 hours

**Total:** ~12-18 hours

## Next Steps

1. Review and approve this plan
2. Create feature branch: `feature/ollama-integration`
3. Implement Phase 1 (core infrastructure)
4. Test with real Ollama instance
5. Iterate on prompt if output quality differs
6. Complete remaining phases
7. Update tasks.md with completion summary
