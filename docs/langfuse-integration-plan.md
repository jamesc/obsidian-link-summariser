# Langfuse Integration - Completed Implementation

**Date**: 2025-12-29  
**Status**: ✅ Phase 1 Complete (Core Integration + Token Tracking)  
**Next**: Phase 2 - Evaluation Framework (Optional)

---

## Overview

Langfuse integration has been successfully implemented with:
- ✅ Full tracing of URL processing pipeline (fetch → summarize → write)
- ✅ Token usage tracking for both Gemini and Ollama models
- ✅ Graceful degradation (optional, no-op when not configured)
- ✅ OpenTelemetry-based API (Langfuse SDK v3)
- ✅ Comprehensive test coverage (496 tests passing)

---

## What Was Implemented

### Configuration (`summarize_links/config.py`)

Added Langfuse configuration fields:
```python
langfuse_enabled: bool = False
langfuse_public_key: str = ""
langfuse_secret_key: str = ""
langfuse_base_url: str = "https://cloud.langfuse.com"
```

**Configuration priority:**
1. Environment variables: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`
2. YAML config: `.summarizer-config.yaml`
3. Auto-enable if keys provided (can be explicitly disabled)

**Example `.env`:**
```bash
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

**Example YAML:**
```yaml
langfuse:
  enabled: true
  base_url: "https://cloud.langfuse.com"
  # Keys should be in .env for security
```

### Tracer Module (`summarize_links/langfuse_tracer.py`)

Implemented `LangfuseTracer` class using **OpenTelemetry API**:

```python
# Key methods using OTel context managers
def trace_url_processing(url, metadata) -> ContextManager
def trace_span(trace_id, name, input_data, metadata) -> ContextManager
def trace_generation(trace_id, name, input_data, metadata, model) -> ContextManager
def score_trace(trace_id, name, value, comment)
def flush()
```

**Features:**
- ✅ No-op when disabled (graceful degradation)
- ✅ Context managers for automatic hierarchy
- ✅ Parent-child relationships via OpenTelemetry
- ✅ Exception handling and warning logs
- ✅ Global tracer management

**Migration from v2 to v3 API:**
```python
# Old (doesn't work):
trace_id = client.trace(name="process-url", input={...})

# New (OpenTelemetry-based):
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
        content, meta = fetch_and_extract_metadata(url)
    
    # Summarize span (generation observation)
    with tracer.trace_generation(trace_id, "summarize", model=config.model):
        summary = client.summarize_with_metadata(...)
        
        # Update generation with output and usage
        if generation and hasattr(generation, "update"):
            generation.update(
                output={
                    "summary_length": len(summary.content),
                    "tags": summary.suggested_tags,
                    "content_type": summary.content_type,
                },
                usage_details=summary.usage_details,
            )
    
    # Write span
    with tracer.trace_span(trace_id, "write", ...):
        write_summary_note_with_metadata(...)
```

**Trace hierarchy:**
```
trace: process_url
  ├─ span: fetch
  ├─ generation: summarize (with token usage)
  └─ span: write
```

### Token Usage Tracking

#### Data Model (`summarize_links/models.py`)
```python
@dataclass
class SummaryResult:
    content: str
    suggested_tags: list[str]
    content_type: str
    usage_details: dict[str, int] | None = None  # NEW
```

#### Gemini Client (`summarize_links/gemini_client.py`)
Extracts token usage from API response:
```python
# Extract from response.usage_metadata
usage_details = {
    "input": response.usage_metadata.prompt_token_count,
    "output": response.usage_metadata.candidates_token_count,
    "total": response.usage_metadata.total_token_count,
}
```

#### Ollama Client (`summarize_links/ollama_client.py`)
Extracts token usage from API response:
```python
# Extract from Ollama API response
usage_details = {
    "input": data.get("prompt_eval_count", 0),
    "output": data.get("eval_count", 0),
    "total": prompt_tokens + completion_tokens,
}
```

**Benefits:**
- ✅ Automatic cost calculation in Langfuse UI
- ✅ Token analytics per model
- ✅ Efficiency tracking over time
- ✅ Budget monitoring

### Testing (`tests/test_langfuse_tracer.py`)

Comprehensive test coverage (20 tests):
- ✅ Disabled mode (no-ops)
- ✅ Missing keys graceful degradation
- ✅ Context manager behavior
- ✅ Null trace_id handling
- ✅ Global tracer initialization
- ✅ Metadata and model info
- ✅ Span hierarchy

**Total tests:** 496 passing

### Configuration Improvements

Added HTTP logging suppressors (`config.py`):
```python
# Suppress verbose HTTP logs
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CLI Command Layer                        │
│  (from-note, urls)                                           │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│         Langfuse Tracer (OpenTelemetry Context Mgr)          │
│  • Initialize if configured, else no-op                      │
│  • Create trace per URL with trace_url_processing()          │
│  • Create nested observations with trace_span/generation()   │
│  • Update observations with outputs and token usage          │
└──────────────────────┬──────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
    ┌────────┐   ┌──────────┐   ┌──────────┐
    │ Fetch  │   │Summarize │   │  Write   │
    │  Span  │   │Generation│   │  Span    │
    └────────┘   └──────────┘   └──────────┘
                      │
                      │ Captures:
                      │ • Model name and provider
                      │ • Input (content_length, url, title)
                      │ • Output (summary, tags, content_type)
                      │ • Token usage (input, output, total)
                      │
                      ▼
              ┌────────────────┐
              │    Langfuse    │
              │   Dashboard    │
              └────────────────┘
```

---

## Trace Data Structure

**Trace metadata:**
```json
{
  "url": "https://example.com/article",
  "model": "gemini-2.5-flash",
  "provider": "gemini",
  "user_tags": ["ai", "tutorial"],
  "source_note": "2025-12-29.md"
}
```

**Generation observation (summarize):**
```json
{
  "input": {
    "content_length": 15000,
    "url": "https://example.com/article",
    "title": "Example Article"
  },
  "output": {
    "summary_length": 250,
    "tags": ["ai", "machine-learning"],
    "content_type": "tutorial"
  },
  "usage_details": {
    "input": 1234,
    "output": 567,
    "total": 1801
  },
  "model": "gemini-2.5-flash",
  "metadata": {
    "provider": "gemini"
  }
}
```

---

## Usage

### Basic Usage (Tracing Enabled)

1. **Configure Langfuse** (in `.env`):
```bash
LANGFUSE_PUBLIC_KEY=pk-lf-your-key
LANGFUSE_SECRET_KEY=sk-lf-your-secret
```

2. **Run normally**:
```bash
# Traces are automatically created and sent to Langfuse
summarize-links from-note --date 2025-12-29
```

3. **View in Langfuse dashboard**:
   - Open https://cloud.langfuse.com
   - See traces for each URL processed
   - View token usage, timing, and outputs
   - Drill down into spans and generations

### Graceful Degradation (No Config)

If Langfuse is not configured:
- ✅ Application works normally
- ✅ No errors or warnings
- ✅ Minimal performance overhead (quick checks)
- ✅ All tracing operations are no-ops

### Debugging

Enable verbose logging to see tracing activity:
```bash
summarize-links from-note --date 2025-12-29 -v
```

Output shows:
```
DEBUG: Langfuse tracing enabled
DEBUG: Created trace for URL: https://example.com
DEBUG: Token usage: input=1234, output=567, total=1801
INFO: Trace flushed to Langfuse
```

---

## Implementation Commits

1. `feat: Add Phase 1 Langfuse integration (Core Integration)` (9733a6c)
   - Initial configuration and tracer module
   - Decorator-based approach (later replaced)

2. `fix: migrate Langfuse tracer to OpenTelemetry API` (a9a5556)
   - Complete rewrite to use `start_as_current_observation()`
   - Implemented actual trace/span creation in CLI
   - Removed deprecated decorator approach

3. `feat: Add token usage tracking to Langfuse integration` (0a260cd)
   - Added usage_details to SummaryResult
   - Modified GeminiClient to extract tokens
   - Updated CLI to send usage to Langfuse

4. `feat: Add token usage tracking for Ollama models` (e5e70ae)
   - Modified OllamaClient to extract tokens
   - Consistent format across providers

5. `docs: Document Phase 1.5 Langfuse integration` (f4f57bd)
   - Updated tasks.md with implementation details

6. `docs: Add Ollama token usage tracking to tasks.md` (41514a8)
   - Documented Ollama-specific token tracking

---

## Phase 2: Evaluation Framework (Future)

**Status:** Not yet implemented (optional enhancement)

### Proposed Features

1. **Evaluation Datasets** (`eval_datasets.py`):
   - Load/save datasets from YAML
   - Store expected outputs (tags, content_type, reference summary)
   - Support for notes and annotations

2. **Evaluation Metrics** (`eval_metrics.py`):
   - Tag accuracy (precision, recall, F1)
   - Content type classification accuracy
   - Summary quality (LLM-as-judge)

3. **Evaluation CLI Command**:
```bash
summarize-links eval --dataset eval_dataset.yaml
```

4. **Dataset Format**:
```yaml
name: "My Evaluation Dataset"
description: "Test cases for summary quality"
examples:
  - url: "https://example.com/article"
    title: "Example Article"
    expected_tags: ["example", "test"]
    expected_content_type: "article"
    notes: "Should identify main concept"
```

### Implementation Plan (If Needed)

**Step 1:** Create dataset management module
- `EvalDataset` and `EvalExample` dataclasses
- YAML loading/saving
- Sample dataset creator

**Step 2:** Implement metrics
- Tag accuracy calculator
- Content type matcher
- LLM-as-judge for summary quality

**Step 3:** Add eval command to CLI
- Load dataset
- Run summaries with tracing
- Calculate metrics
- Score traces in Langfuse
- Display results table

**Step 4:** Testing and documentation
- Unit tests for metrics
- Integration tests for eval command
- README section on evaluation
- Example datasets

**Estimated effort:** 6-8 hours

---

## Dependencies

Already installed:
```toml
[project.dependencies]
langfuse = ">=2.0.0"
```

For HTTP logging suppression (already in use):
```toml
httpcore = "*"
httpx = "*"
```

---

## Success Metrics

✅ **Core Integration:**
- Langfuse tracing works with both Gemini and Ollama ✓
- Graceful degradation when not configured ✓
- No breaking changes to existing functionality ✓
- Traces appear in Langfuse dashboard ✓
- Token usage tracked and visible ✓

✅ **Code Quality:**
- All 496 tests passing ✓
- Static analysis clean (ruff, mypy) ✓
- Type hints complete ✓
- Comprehensive documentation ✓

✅ **Production Ready:**
- HTTP logs suppressed ✓
- Error handling robust ✓
- Performance impact minimal ✓
- Configuration flexible ✓

---

## Future Enhancements

1. **Evaluation Framework (Phase 2):**
   - Dataset management
   - Automated metrics
   - Eval command
   - LLM-as-judge

2. **Advanced Features:**
   - Prompt versioning
   - A/B testing (Gemini vs Ollama)
   - Cost tracking and budgets
   - Continuous evaluation
   - Custom metrics

3. **Integrations:**
   - Dataset builder UI
   - Webhook notifications
   - Export to other platforms

---

## Troubleshooting

### Traces not appearing in Langfuse

1. Check configuration:
```bash
# Verify keys are set
echo $LANGFUSE_PUBLIC_KEY
echo $LANGFUSE_SECRET_KEY
```

2. Enable verbose logging:
```bash
summarize-links from-note --date 2025-12-29 -v
```

3. Check Langfuse dashboard:
   - Verify project is selected
   - Check date filters
   - Look in "Traces" tab

### Token usage not showing

1. For Gemini:
   - Ensure API response includes `usage_metadata`
   - Check debug logs for "Token usage: ..."

2. For Ollama:
   - Ensure Ollama API returns `prompt_eval_count` and `eval_count`
   - Update Ollama if using old version

### Performance concerns

- Tracing adds ~10-50ms per URL
- Flush operations are batched
- HTTP logs suppressed to reduce noise
- Disable tracing if not needed

---

## Conclusion

Phase 1 of Langfuse integration is **complete and production-ready**:
- ✅ Full tracing pipeline implemented
- ✅ Token usage tracking for cost analysis
- ✅ Graceful degradation for optional use
- ✅ Comprehensive testing (496 tests)
- ✅ Clean static analysis
- ✅ Well-documented

**Phase 2 (Evaluation)** is optional and can be implemented later if needed for systematic quality assessment and model comparison.

## Requirements Summary

Based on discussion:
- ✅ **Scope**: Trace entire pipeline (fetch → extract → summarize → write)
- ✅ **Optional**: Graceful degradation if not configured
- ✅ **Evaluation Focus**: 
  - Summary quality (relevance, coherence, completeness)
  - Tag accuracy (are suggested tags relevant?)
  - Content type classification (article, tutorial, etc.)

**Reasonable Defaults** (based on existing patterns):
- **Configuration**: Both env vars (`.env`) and YAML config (consistent with existing)
- **Dataset**: Curated URLs in YAML file
- **Metadata**: Comprehensive (model, provider, URL, tokens, timing, status)
- **Trace Granularity**: One trace per URL with observations (spans) for each stage
- **Error Handling**: Log warning and continue (don't break summarization)
- **Mock Mode**: Skip tracing (keeps mock truly isolated)
- **Project Organization**: Configurable via tags and session ID

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     CLI Command Layer                        │
│  (from-note, urls, eval)                                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Langfuse Tracer (Context Manager)               │
│  • Initialize if configured, else no-op                      │
│  • Create trace per URL                                      │
│  • Capture observations: fetch → extract → summarize → write │
└──────────────────────┬──────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
    ┌────────┐   ┌──────────┐   ┌──────────┐
    │ Fetch  │   │Summarize │   │  Write   │
    │  Obs   │   │Generation│   │  Obs     │
    └────────┘   └──────────┘   └──────────┘
                      │
                      │ Captures:
                      │ • Inputs (prompt, content)
                      │ • Outputs (summary, tags, type)
                      │ • Metadata (model, tokens, timing)
                      │
                      ▼
              ┌────────────────┐
              │    Langfuse    │
              │   Dashboard    │
              └────────────────┘

Evaluation Flow:
┌────────────────┐      ┌──────────────┐      ┌────────────────┐
│ eval_dataset   │─────▶│ Run summaries│─────▶│ Langfuse Eval  │
│ (URLs + refs)  │      │ w/ tracing   │      │ w/ scores      │
└────────────────┘      └──────────────┘      └────────────────┘
```

---

## Implementation Phases

### Phase 1: Core Langfuse Integration (3-4 hours)

**1.1 Configuration Support**

Add Langfuse config to `config.py`:

```python
# New configuration fields in Config dataclass:
langfuse_enabled: bool = False
langfuse_public_key: str = ""
langfuse_secret_key: str = ""
langfuse_base_url: str = "https://cloud.langfuse.com"
```

Config loading priority:
1. Environment variables: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`
2. YAML config: `.summarizer-config.yaml`
3. Defaults

Example `.env` additions:
```bash
# Langfuse Configuration (optional)
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com  # Or self-hosted URL
```

Example YAML additions:
```yaml
# .summarizer-config.yaml
langfuse:
  enabled: true
  base_url: "https://cloud.langfuse.com"
  # Keys should be in .env for security
```

**1.2 Langfuse Tracer Module**

Create `summarize_links/langfuse_tracer.py`:

```python
"""
Langfuse integration for tracing and evaluation.

Provides a context manager for tracing LLM operations and pipeline stages.
Gracefully degrades if Langfuse is not configured.
"""

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator

logger = logging.getLogger(__name__)


class LangfuseTracer:
    """
    Wrapper for LangSmith tracing with graceful degradation.
    
    If LangSmith is not configured or unavailable, all operations
    become no-ops, allowing the application to function normally.
    """
    
    def __init__(
        self,
        api_key: str | None = None,
        project: str | None = None,
        endpoint: str | None = None,
        enabled: bool = True,
    ) -> None:
        """
        Initialize LangSmith tracer.
        
        Args:
            api_key: LangSmith API key (required if enabled).
            project: Project name for organizing traces.
            endpoint: LangSmith API endpoint.
            enabled: Whether tracing is enabled.
        """
        self._enabled = enabled and api_key is not None
        self._client = None
        self._available = False
        
        if not self._enabled:
            logger.debug("LangSmith tracing disabled")
            return
        
        try:
            # Import langsmith and set environment
            from langsmith import Client
            import os
            
            # Set environment variables for LangChain integration
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = api_key
            if project:
                os.environ["LANGCHAIN_PROJECT"] = project
            if endpoint:
                os.environ["LANGCHAIN_ENDPOINT"] = endpoint
            
            self._client = Client(api_key=api_key, api_url=endpoint)
            self._project = project or "obsidian-link-summariser"
            self._available = True
            
            logger.info(f"LangSmith tracing enabled (project: {self._project})")
            
        except ImportError:
            logger.warning(
                "LangSmith package not installed. "
                "Install with: uv add langsmith langchain"
            )
            self._enabled = False
        except Exception as e:
            logger.warning(f"Failed to initialize LangSmith: {e}")
            self._enabled = False
    
    @property
    def enabled(self) -> bool:
        """Whether tracing is enabled and available."""
        return self._enabled and self._available
    
    @contextmanager
    def trace_url_processing(
        self,
        url: str,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[Any, None, None]:
        """
        Create a trace for processing a single URL.
        
        Args:
            url: The URL being processed.
            metadata: Additional metadata to attach to trace.
            
        Yields:
            Trace context (or None if tracing disabled).
        """
        if not self.enabled or not self._client:
            yield None
            return
        
        try:
            trace_metadata = {
                "source_url": url,
                "timestamp": datetime.now().isoformat(),
                **(metadata or {}),
            }
            
            trace = self._client.trace(
                name="process_url",
                input={"url": url},
                metadata=trace_metadata,
            )
            
            yield trace
            
        except Exception as e:
            logger.warning(f"Langfuse trace_url_processing failed: {e}")
            yield None
    
    @contextmanager
    def trace_span(
        self,observation(
        self,
        trace_id: str,
        name: str,
        input_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        observation_type: str = "span",
    ) -> Generator[Any, None, None]:
        """
        Create an observation (span) within a trace.
        
        Args:
            trace_id: Parent trace ID.
            name: Observation name (e.g., "fetch", "extract", "summarize", "write").
            input_data: Input data for the observation.
            metadata: Additional metadata.
            observation_type: Type of observation ("span" or "generation" for LLM calls).
            
        Yields:
            Observation context (or None if tracing disabled).
        """
        if not self.enabled or not self._client:
            yield None
            return
        
        try:
            class ObservationContext:
                def __init__(self, client: Any, trace_id: str, name: str, obs_type: str):
                    self.client = client
                    self.trace_id = trace_id
                    self.name = name
                    self.obs_type = obs_type
                    self.observation = None
                
                def __enter__(self):
                    if self.obs_type == "generation":
                        self.observation = self.client.generation(
                            trace_id=self.trace_id,
                            name=self.name,
                            input=input_data or {},
                            metadata=metadata or {},
                        )
                    else:
        score_trace(
        self,
        trace_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        """
        Add a score to a trace (used in evaluation).
        
        Args:
            trace_id: The trace ID to score.
            name: Score name (e.g., "relevance", "tag_accuracy").
            value: Numeric score (typically 0.0-1.0).
            comment: Optional text comment.
        """
        if not self.enabled or not self._client:
            return
        
        try:
            self._client.score(
                trace_id=trace_id,
                name=name,
                value=value,
                comment=comment,
            )
        except Exception as e:
            logger.warning(f"Failed to score trace: {e}")


# Global tracer instance (initialized in CLI)
_global_tracer: LangfuseTracer | None = None


def initialize_tracer(config: Any) -> LangfuseTracer:
    """
    Initialize the global Langfuse tracer from config.
    
    Args:
        config: Application Config object.
        
    Returns:
        Initialized tracer instance.
    """
    global _global_tracer
    
    _global_tracer = LangfuseTracer(
        public_key=config.langfuse_public_key,
        secret_key=config.langfuse_secret_key,
        base_url=config.langfuse_base_url,
        enabled=config.langfuse_enabled,
    )
    
    return _global_tracer


def get_tracer() -> LangfuseTracer:
    """
    Get the global tracer instance.
    
    Returns:
        Global tracer (or a disabled tracer if not initialized).
    """
    if _global_tracer is None:
        # Return a disabled tracer as fallback
        return Langfuser
    
    _global_tracer = LangSmithTracer(
        api_key=config.langsmith_api_key,
        project=config.langsmith_project,
        endpoint=config.langsmith_endpoint,
        enabled=config.langsmith_enabled,
    )
    
- ✅ Support for both spans and generation observations

**1.3 Instrument Pipeline Components**

Modify `cli.py` to initialize tracer and add tracing context to `_process_url_with_metadata`:

```python
def _process_url_with_metadata(
    url_context: UrlWithContext,
    config: Config,
    client: SummarizerProtocol,
    progress: Progress | None = None,
    task_id: TaskID | None = None,
    daily_note_filename: str | None = None,
    source_date: datetime | None = None,
) -> tuple[bool, str, bool]:
    """Process a single URL with full tracing."""
    from summarize_links.langfuse_tracer import get_tracer
    
    tracer = get_tracer()
    url = url_context.url
    
    # Create trace for this URL
    with tracer.trace_url_processing(
        url=url,
        metadata={
            "model": config.model,
            "provider": detect_provider(config.model),
            "user_tags": url_context.tags,
            "source_note": daily_note_filename,
        },
    ) as trace:
        if trace:
            trace_id = trace.id
            
            # Fetch and extract with observation
            with tracer.trace_observation(
                trace_id=trace_id,
                name="fetch_and_extract",
                input_data={"url": url},
            ):
                page_metadata = fetch_and_extract_metadata(url)
            
            # Summarize with generation observation (LLM call)
            with tracer.trace_observation(
                trace_id=trace_id,
                name="summarize",
                input_data={
                    "content_length": len(page_metadata.content),
                    "title": page_metadata.title,
                },
                metadata={
                    "model": config.model,
                    "provider": detect_provider(config.model),
                },
                observation_type="generation",
            ):
                summary_result = client.summarize_with_metadata(
                    content=page_metadata.content,
                    url=url,
                    title=page_metadata.title,
                )
            
            # Write with observation
            with tracer.trace_observation(
                trace_id=trace_id,fuse-compatible wrappers for automatic LLM tracing.

We'll use Langfuse's decorators for automatic instrumentation:

```python
# In gemini_client.py
from langfuse.decorators import observe, langfuse_context

class GeminiClient:
    # ... existing code ...
    
    @observe(as_type="generation")
    def summarize_with_metadata(
        self, content: str, url: str, title: str | None = None
    ) -> SummaryResult:
        """Summarize with Langfuse tracing."""
        # Update trace with model info
        langfuse_context.update_current_observation(
            model=self._model_name,
            input={"content_length": len(content), "url": url, "title": title},
            metadata={"provider": "gemini"},
        )
        
        # Existing summarization logic
        raw_response = self.summarize(content, url, title)
        result = _parse_gemini_response(raw_response)
        
        # Update with outputs
        langfuse_context.update_current_observation(
            output={
                "summary_length": len(result.content),
                "tags": result.suggested_tags,
                "content_type": result.content_type,
            },
        )
        
        return result

# Similar for ollama_client.py with provider="ollama"
        with tracer.trace_span(
            "write_note",
            inputs={"slug": slug_from_url(url)},
        ):
            summary_path = write_summary_note_with_metadata(...)
    
    # Rest of existing logic...
```

**1.4 Instrument LLM Clients**

Both `gemini_client.py` and `ollama_client.py` need LangChain-compatible wrappers for automatic LLM tracing.

Since you're using the Google GenAI SDK (not LangChain), we'll need to manually log LLM calls:

```python
# In gemini_client.py and ollama_client.py
def summarize_with_metadata(
    self, content: str, url: str, title: str | None = None
) -> SummaryResult:
    """Summarize with LangSmith tracing."""
    from langsmith import traceable
    
    @traceable(
```

---

### Phase 2: Evaluation Framework (3-4 hours)

**2.1 Evaluation Dataset Management**

Create `summarize_links/eval_datasets.py`:

```python
"""
Evaluation dataset management.

Supports loading/saving datasets of URLs with reference outputs
for evaluation purposes.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from summarize_links.exceptions import ConfigError

logger = logging.getLogger(__name__)


@dataclass
class EvalExample:
    """A single evaluation example."""
    
    url: str
    title: str | None = None
    expected_tags: list[str] | None = None
    expected_content_type: str | None = None
    reference_summary: str | None = None
    notes: str | None = None


@dataclass
class EvalDataset:
    """Collection of evaluation examples."""
    
    name: str
    description: str
    examples: list[EvalExample]
    
    @classmethod
    def from_yaml(cls, path: Path) -> "EvalDataset":
        """Load dataset from YAML file."""
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            
            if not data or "examples" not in data:
                raise ConfigError(f"Invalid eval dataset format: {path}")
            
            examples = [
                EvalExample(
                    url=ex["url"],
                    title=ex.get("title"),
                    expected_tags=ex.get("expected_tags"),
                    expected_content_type=ex.get("expected_content_type"),
                    reference_summary=ex.get("reference_summary"),
                    notes=ex.get("notes"),
                )
                for ex in data["examples"]
            ]
            
            return cls(
                name=data.get("name", "Untitled Dataset"),
                description=data.get("description", ""),
                examples=examples,
            )
            
        except Exception as e:
            raise ConfigError(f"Failed to load eval dataset from {path}: {e}") from e
    
    def to_yaml(self, path: Path) -> None:
        """Save dataset to YAML file."""
        data = {
            "name": self.name,
            "description": self.description,
            "examples": [
                {
                    "url": ex.url,
                    "title": ex.title,
                    "expected_tags": ex.expected_tags,
                    "expected_content_type": ex.expected_content_type,
                    "reference_summary": ex.reference_summary,
                    "notes": ex.notes,
                }
                for ex in self.examples
            ],
        }
        
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        
        logger.info(f"Saved eval dataset to {path}")


def create_sample_dataset() -> EvalDataset:
    """Create a sample evaluation dataset for documentation."""
    return EvalDataset(
        name="Sample Evaluation Dataset",
        description="Example dataset showing expected format",
        examples=[
            EvalExample(
                url="https://ai.google.dev/gemini-api/docs/models/gemini",
                title="Gemini models documentation",
                expected_tags=["ai", "gemini", "documentation", "llm"],
                expected_content_type="documentation",
                reference_summary="Overview of Google's Gemini model family...",
                notes="Should identify as documentation and extract relevant AI tags",
            ),
            EvalExample(
                url="https://www.anthropic.com/news/claude-3-family",
                title="Introducing Claude 3",
                expected_tags=["ai", "anthropic", "claude", "announcement"],
                expected_content_type="news",
                notes="Should be classified as news/announcement",
            ),
        ],
    )
```

**2.2 Evaluation Metrics**

Create `summarize_links/eval_metrics.py`:

```python
"""
Custom evaluation metrics for summary quality assessment.

Implements metrics for:
- Summary quality (relevance, coherence, completeness)
- Tag accuracy
- Content type classification
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SummaryQualityMetric:
    """
    Evaluate summary quality using LLM-as-judge.
    
    Assesses relevance, coherence, and completeness.
    """
    
    def __init__(self, judge_model: str = "gemini-2.0-flash-exp"):
        """
        Initialize metric.
        
        Args:
            judge_model: Model to use as judge.
        """
        self.judge_model = judge_model
    
    async def evaluate(
        self,
        original_content: str,
        summary: str,
        url: str,
    ) -> dict[str, float]:
        """
        Evaluate summary quality.
        
        Returns scores for:
        - relevance: How well summary captures key points (0-1)
        - coherence: How well-structured and readable (0-1)
        - completeness: Coverage of important information (0-1)
        - overall: Average of above metrics (0-1)
        """
        # TODO: Implement LLM-as-judge evaluation
        # For now, return placeholder scores
        
        prompt = f"""You are evaluating a summary of a web page.

Original URL: {url}
Original Content Length: {len(original_content)} characters
Summary Length: {len(summary)} characters

Summary to evaluate:
{summary}

Please rate the summary on these dimensions (0.0 to 1.0):
1. Relevance: Does it capture the main points?
2. Coherence: Is it well-structured and readable?
3. Completeness: Does it cover important information?

Respond with JSON: {{"relevance": 0.0, "coherence": 0.0, "completeness": 0.0}}
"""
        
        # Placeholder implementation
        logger.warning("SummaryQualityMetric.evaluate not fully implemented")
        return {
            "relevance": 0.8,
            "coherence": 0.9,
            "completeness": 0.7,
            "overall": 0.8,
        }


class TagAccuracyMetric:
    """Evaluate accuracy and relevance of suggested tags."""
    
    def evaluate(
        self,
        suggested_tags: list[str],
        expected_tags: list[str] | None,
        content: str,
        url: str,
    ) -> dict[str, float]:
        """
        Evaluate tag accuracy.
        
        Returns:
        - precision: What % of suggested tags are relevant (0-1)
        - recall: What % of expected tags were suggested (0-1)
        - f1_score: Harmonic mean of precision and recall (0-1)
        """
        if not expected_tags:
            logger.warning("No expected tags provided, skipping recall calculation")
            return {
                "precision": 1.0,  # Assume all tags are valid
                "recall": 0.0,
                "f1_score": 0.0,
            }
        
        # Calculate overlap
        suggested_set = set(tag.lower() for tag in suggested_tags)
        expected_set = set(tag.lower() for tag in expected_tags)
        
        true_positives = len(suggested_set & expected_set)
        
        precision = true_positives / len(suggested_set) if suggested_set else 0.0
        recall = true_positives / len(expected_set) if expected_set else 0.0
        
        if precision + recall > 0:
            f1_score = 2 * (precision * recall) / (precision + recall)
        else:
            f1_score = 0.0
        
        return {
            "precision": precision,
            "recall": recall,
            "f1_score": f1_score,
        }


class ContentTypeAccuracyMetric:
    """Evaluate content type classification accuracy."""
    
    def evaluate(
        self,
        predicted_type: str,
        expected_type: str | None,
    ) -> dict[str, float]:
        """
        Evaluate content type classification.
        
        Returns:
        - accuracy: 1.0 if correct, 0.0 if incorrect
        """
        if not expected_type:
            return {"accuracy": 1.0}  # Assume correct if no expectation
        
        accuracy = 1.0 if predicted_type.lower() == expected_type.lower() else 0.0
        
        return {"accuracy": accuracy}


def evaluate_summary_result(
    summary_result: Any,  # SummaryResult
    eval_example: Any,  # EvalExample
    original_content: str,
    url: str,
) -> dict[str, Any]:
    """
    Run all evaluation metrics on a summary result.
    
    Args:
        summary_result: The generated SummaryResult.
        eval_example: The evaluation example with expected outputs.
        original_content: Original page content.
        url: Source URL.
        
    Returns:
        Dictionary of metric scores.
    """
    metrics = {}
    
    # Tag accuracy
    tag_metric = TagAccuracyMetric()
    metrics["tag_accuracy"] = tag_metric.evaluate(
        suggested_tags=summary_result.suggested_tags,
        expected_tags=eval_example.expected_tags,
        content=original_content,
        url=url,
    )
    
    # Content type accuracy
    type_metric = ContentTypeAccuracyMetric()
    metrics["content_type_accuracy"] = type_metric.evaluate(
        predicted_type=summary_result.content_type,
        expected_type=eval_example.expected_content_type,
    )
    
    # Summary quality (placeholder - requires async implementation)
    metrics["summary_quality"] = {
        "relevance": 0.8,
        "coherence": 0.9,
        "completeness": 0.7,
        "overall": 0.8,
    }
    
    return metrics
```

**2.3 Evaluation CLI Command**

Add `cmd_eval` to `cli.py`:

```python
def cmd_eval(config: Config, dataset_path: str) -> int:
    """
    Run evaluation on a dataset.
    
    Args:
        config: Application configuration.
        dataset_path: Path to evaluation dataset YAML file.
        
    Returns:
        Exit code.
    """
    from summarize_links.eval_datasets import EvalDataset
    from summarize_links.eval_metrics import evaluate_summary_result
    from summarize_links.langsmith_tracer import get_tracer
    
    _print(f"[bold]Running evaluation on: {dataset_path}[/]")
    
    # Load dataset
    try:
        dataset = EvalDataset.from_yaml(Path(dataset_path))
    except ConfigError as e:
        _print_error(f"[red]Failed to load dataset: {e}[/]")
        return EXIT_ERROR
    
    _print(f"[green]Loaded {len(dataset.examples)} examples from '{dataset.name}'[/]")
    _print(f"[dim]{dataset.description}[/]\n")
    
    # Create LLM client
    client = create_llm_client(
        model=config.model,
        gemini_api_key=config.gemini_api_key,
        ollama_endpoint=config.ollama_endpoint,
        mock_mode=config.mock_mode,
        state_path=config.vault_path,
    )
    
    tracer = get_tracer()
    
    # Run evaluation
    results = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("[cyan]Evaluating...", total=len(dataset.examples))
        
        for example in dataset.examples:
            try:
                # Fetch content
                page_metadata = fetch_and_extract_metadata(example.url)
                
                # Generate summary
                summary_result = client.summarize_with_metadata(
                    content=page_metadata.content,
                    url=example.url,
                    title=example.title or page_metadata.title,
                )
                
                # Evaluate
                metrics = evaluate_summary_result(
                    summary_result=summary_result,
                    eval_example=example,
                    original_content=page_metadata.content,
                    url=example.url,
                )
                
                results.append({
                    "url": example.url,
                    "metrics": metrics,
                    "success": True,
                })
                
            except Exception as e:
                logger.error(f"Evaluation failed for {example.url}: {e}")
                results.append({
                    "url": example.url,
                    "error": str(e),
                    "success": False,
                })
            
            progress.advance(task)
    
    # Display results
    _display_eval_results(results, dataset.name)
    
    return EXIT_SUCCESS if any(r["success"] for r in results) else EXIT_ERROR


def _display_eval_results(results: list[dict], dataset_name: str) -> None:
    """Display evaluation results in a table."""
    # Aggregate metrics
    tag_precision = []
    tag_recall = []
    tag_f1 = []
    content_type_acc = []
    
    for result in results:
        if not result["success"]:
            continue
        
        metrics = result["metrics"]
        
        tag_precision.append(metrics["tag_accuracy"]["precision"])
        tag_recall.append(metrics["tag_accuracy"]["recall"])
        tag_f1.append(metrics["tag_accuracy"]["f1_score"])
        content_type_acc.append(metrics["content_type_accuracy"]["accuracy"])
    
    # Display summary table
    table = Table(title=f"Evaluation Results: {dataset_name}")
    table.add_column("Metric", style="cyan")
    table.add_column("Average Score", style="green", justify="right")
    table.add_column("Min", style="white", justify="right")
    table.add_column("Max", style="white", justify="right")
    
    if tag_precision:
        table.add_row(
            "Tag Precision",
            f"{sum(tag_precision) / len(tag_precision):.2f}",
            f"{min(tag_precision):.2f}",
            f"{max(tag_precision):.2f}",
        )
        table.add_row(
            "Tag Recall",
            f"{sum(tag_recall) / len(tag_recall):.2f}",
            f"{min(tag_recall):.2f}",
            f"{max(tag_recall):.2f}",
        )
        table.add_row(
            "Tag F1 Score",
            f"{sum(tag_f1) / len(tag_f1):.2f}",
            f"{min(tag_f1):.2f}",
            f"{max(tag_f1):.2f}",
        )
        table.add_row(
            "Content Type Accuracy",
            f"{sum(content_type_acc) / len(content_type_acc):.2f}",
            f"{min(content_type_acc):.2f}",
            f"{max(content_type_acc):.2f}",
        )
    
    _print(table)
    _print()
    _print(f"[bold]Total examples:[/] {len(results)}")
    _print(f"[green]Successful:[/] {sum(1 for r in results if r['success'])}")
    _print(f"[red]Failed:[/] {sum(1 for r in results if not r['success'])}")
```

---

### Phase 3: Testing & Documentation (2-3 hours)

**3.1 Unit Tests**

Create `tests/test_langsmith_tracer.py`:

```python
"""Tests for LangSmith integration."""

import pytest
from summarize_links.langsmith_tracer import LangSmithTracer


def test_tracer_disabled_mode():
    """Test that tracer works as no-op when disabled."""
    tracer = LangSmithTracer(enabled=False)
    
    assert not tracer.enabled
    
    # Should not raise errors
    with tracer.trace_url_processing("http://example.com"):
        pass
    
    with tracer.trace_span("test_span"):
        pass


def test_tracer_missing_api_key():
    """Test graceful degradation without API key."""
    tracer = LangSmithTracer(api_key=None, enabled=True)
    
    assert not tracer.enabled


def test_tracer_with_mock_config(mock_config):
    """Test tracer initfuse_integration.py`:

```python
"""Integration tests for Langfuse tracing."""

import pytest
from summarize_links.langfuse_tracer import LangfuseTracer


@pytest.mark.integration
def test_full_pipeline_with_tracing(mock_config, tmp_path):
    """Test that tracing doesn't break the pipeline."""
    # This test requires Langfuse to be installed but not configured
    # It should gracefully degrade
    
    from summarize_links.cli import cmd_urls
    
    mock_config.vault_path = tmp_path
    mock_config.mock_mode = True
    mock_config.langfuse_enabled = True
    mock_config.langfuse_public_key = None  # Not configured
    mock_config.langfuse_secret_key = None
from summarize_links.eval_datasets import EvalDataset, EvalExample, create_sample_dataset


def test_create_sample_dataset():
    """Test sample dataset creation."""
    dataset = create_sample_dataset()
    
    assert dataset.name == "Sample Evaluation Dataset"
    assert len(dataset.exampfuse section:

```markdown
## Langfuse Integration

The tool supports optional integration with [Langfuse](https://langfuse.com) for tracing and evaluation.

### Configuration

Add to your `.env` file:

```bash
# Optional: Langfuse tracing
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com  # Or self-hosted URL
```

Or in `.summarizer-config.yaml`:

```yaml
langfuse:
  enabled: true
  base_url: "https://cloud.langfuse.com"
  # Keys should be in .env for security
```

### Features

**Automatic Tracing**: When configured, all LLM operations are automatically traced:
- URL processing pipeline (fetch → extract → summarize → write)
- Individual LLM calls with inputs/outputs (as "generation" observations)
- Timing and token usage
- Errors and exceptions

**Evaluation**: Run evaluations on curated datasets:

```bash
# Run evaluation
summarize-links eval --vault ~/Notes --dataset eval_dataset.yaml

# With specific model
summarize-links eval --vault ~/Notes --dataset eval_dataset.yaml --model llama3:latest
```

### Creating Evaluation Datasets

Create a YAML file with URLs and expected outputs:

```yaml
name: "My Evaluation Dataset"
description: "Test cases for summary quality"
examples:
  - url: "https://example.com/article"
    title: "Example Article"
    expected_tags: ["example", "article", "test"]
    expected_content_type: "article"
    notes: "Should extract main concept clearly"
    
  - url: "https://github.com/user/repo"
    expected_tags: ["github", "repository"]
    expected_content_type: "documentation"
```

Then run:

```bash
summarize-links eval --vault ~/Notes --dataset my_dataset.yaml
```

### Metrics

The evaluation framework assesses:
- **Tag Accuracy**: Precision, recall, and F1 score for suggested tags
- **Content Type Accuracy**: Correct classification (article, tutorial, etc.)
- **Summary Quality**: Relevance, coherence, completeness (LLM-as-judge)

### Graceful Degradation

Langfuse integration is completely optional:
- If not configured, tracing is silently skipped
- Application functions normally without Langfuserize → write)
- Individual LLM calls with inputs/outputs
- Timing and token usage
- Errors and exceptions

**Evaluation**: Run evaluations on curated datasets:

```basfuse_tracer.py        # NEW: Langfuse integration wrapper
  eval_datasets.py          # NEW: Dataset management
  eval_metrics.py           # NEW: Evaluation metrics
  config.py                 # MODIFIED: Add Langfuse config
  cli.py                    # MODIFIED: Add eval command, initialize tracer
  gemini_client.py          # MODIFIED: Add tracing to summarize_with_metadata
  ollama_client.py          # MODIFIED: Add tracing to summarize_with_metadata

tests/
  test_langfuse_tracer.py   # NEW: Tracer tests
  test_eval_datasets.py     # NEW: Dataset tests
  test_eval_metrics.py      # NEW: Metrics tests
  test_langfuse_integration.py  # NEW: Integration tests

docs/
  langfuse-integration-plan.md  # THIS FILE

# Example evaluation dataset
eval_examples/
  sample_dataset.yaml       # NEW: Sample eval dataset
```

---

## Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
langfuse = [
    "langfuse>=2.0.0",
]
```

Install with:
```bash
uv add --optional langfuse langfusempleteness (LLM-as-judge)

### Graceful Degradation

LangSmith integration is completely optional:
- If not configured, tracing is silently skipped
- Application functions normally without LangSmith
- No dependencies required unless you want tracing
```
fuse config to `config.py`
- [ ] Create `langfuse_tracer.py` module
- [ ] Initialize tracer in `cli.py`
- [ ] Add tracing to `_process_url_with_metadata`
- [ ] Add tracing to `gemini_client.py`
- [ ] Add tracing to `ollama_client.py`
- [ ] Test graceful degradation (no config)
- [ ] Test with real Langfuse API keysgSmith integration wrapper
  eval_datasets.py          # NEW: Dataset management
  eval_metrics.py           # NEW: Evaluation metrics
  config.py                 # MODIFIED: Add LangSmith config
  cli.py                    # MODIFIED: Add eval command, initialize tracer
  gemini_client.py          # MODIFIED: Add tracing to summarize_with_metadata
  ollama_client.py          # MODIFIED: Add tracing to summarize_with_metadata

tests/
  test_langsmith_tracer.py  # NEW: Tracer tests
  test_eval_datasets.py     # NEW: Dataset tests
  test_eval_metrics.py      # NEW: Metrics tests
  test_langsmith_integration.py  # NEW: Integration tests

docs/
  langsmith-integration-plan.md  # THIS FILE

# Example evaluation dataset
eval_examples/
  sample_dataset.yaml       # NEW: Sample eval dataset
```

---

## Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
langsmith = [
    "langsmith>=0.1.0",
    "langchain>=0.1.0",
]
```
fuse tracing works with both Gemini and Ollama
- Graceful degradation when not configured
- No breaking changes to existing functionality
- Traces appear in Langfuse dashboard
- Generation observations properly track LLM calls

✅ **Evaluation Framework**:
- Can load evaluation datasets from YAML
- Metrics calculate correctly
- Evaluation command produces readable output
- Results sync to Langfuse as scores

✅ **Testing**:
- All tests pass
- Test coverage > 80% for new modules
- Integration tests verify end-to-end flow

✅ **Documentation**:
- README explains Langfusetion (no config)
- [ ] Test with real LangSmith API key

### Phase 2: Evaluation (3-4 hours)
- [ ] Create `eval_datasets.py` module
- [ ] Create `eval_metrics.py` module
- [ ] Add `cmd_eval` to `cli.py`
- [ ] Create sample evaluation dataset
- [ ] Implement tag accuracy metric
- [ ] Implement content type metric
- [ ] Implement summary quality metric (LLM-as-judge)
- [ ] Test evaluation command

### Phase 3: Testing & Docs (2-3 hours)
- [ ] Write unit tests for tracer
- [ ] Write unit tests for datasets
- [ ] Write unit tests for metrics
- [ ] Write integration tests
- [ ] Update README.md
- [ ] Create example evaluation dataset
- [ ] Document configuration options
- [ ] Add troubleshooting section

### Phase 4: Polish (1-2 hours)
- [ ] Run static analysis (ruff, mypy)
- [ ] Fix type hints
- [ ] Update AGENTS.md build guidelines
- [ ] Create task summary in docs/tasks.md
- [ ] Test with both Gemini and Ollama
- [ ] Test in production vault

---

## Success Criteria

✅ **Core Integration**:
- LangSmith tracing works with both Gemini and Ollama
- Graceful degradation when not configured
- No breaking changes to existing functionality
- Traces appear in LangSmith dashboard

✅ **Evaluation Framework**:
- Can load evaluation datasets from YAML
- Metrics calculate correctly
- Evaluation command produces readable output
- Results sync to LangSmith

✅ **Testing**:
- All tests pass
- Test coverage > 80% for new modules
- Integration tests verify end-to-end flow

✅ **Documentation**:
- README explains LangSmith setup
- Example dataset provided
- Configuration options documented
- Troubleshooting guide included

---

## Future Enhancements (Post-MVP)

1. **LLM-as-Judge Implementation**: Complete async evaluation using LLM judges
2. **Comparative Evaluations**: Compare Gemini vs Ollama on same dataset
3. **Custom Metrics**: User-defined evaluation criteria
4. **Dataset Builder**: CLI tool to help create evaluation datasets
5. **Continuous Evaluation**: Automated eval runs on dataset changes
6. **Cost Tracking**: Track API costs in traces
7. **Prompt Versioning**: Track prompt changes and their impact

---

## Questions / Decisions Needed

Before starting implementation, confirm:

1. ✅ Are the proposed metrics (tag accuracy, content type, summary quality) sufficient?
2. ✅ Should we implement LLM-as-judge now or as a placeholder?
3. ✅ Do you want a CLI tool to help create evaluation datasets?
4. ✅ Should evaluation results be saved to files or just displayed?
5. ✅ Do you want to track costs (API usage) in traces?

---

## Estimated Timeline

- **Phase 1 (Core)**: 3-4 hours
- **Phase 2 (Eval)**: 3-4 hours
- **Phase 3 (Testing)**: 2-3 hours
- **Phase 4 (Polish)**: 1-2 hours

**Total**: ~10-13 hours

Can be broken into:
- Day 1: Core integration (Phase 1)
- Day 2: Evaluation framework (Phase 2)
- Day 3: Testing & documentation (Phases 3-4)
