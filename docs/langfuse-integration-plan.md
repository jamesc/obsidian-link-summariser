# Langfuse Integration - Implementation Status

**Date**: 2026-01-06 (Updated)
**Status**: ✅ Phase 1 Complete | ✅ Phase 2 Complete (REQUIRED) | ✅ Phase 3 Complete
**Current**: Full Langfuse integration with evaluation framework
**Completed**: All phases implemented

---

## Implementation Phases

### ✅ Phase 1: Core Tracing & Raw Prompt Storage (COMPLETE)

**Core Tracing:**
- Full pipeline tracing: fetch → summarize (generation) → write
- OpenTelemetry-based automatic nesting (no manual trace_id passing)
- Slug-based trace naming for easy Langfuse UI filtering
- Session grouping via `propagate_attributes()`

**Data Capture:**
- Raw system prompt, user prompt, and LLM response stored in traces
- Token usage (input, output, total) from both Gemini and Ollama
- Comprehensive metadata at each stage (fetch, generation, write)
- Error tracking in generation observations

**Production Ready:**
- All operations require valid Langfuse credentials
- Safe update calls with `contextlib.suppress(Exception)`
- HTTP logging suppression for clean output
- Comprehensive test coverage

**Configuration:**
- Environment variables and YAML config support
- CLI initialization via `initialize_tracer(config)`

**What's Stored:** Prompts fetched from Langfuse and sent to traces for debugging.

---

### ✅ Phase 2: Langfuse Prompt Management (COMPLETE - REQUIRED)

**Goal:** Centralized Langfuse Prompt Management - REQUIRED for all operations

**Status**: ✅ **Implemented and REQUIRED** - All prompts MUST come from Langfuse

**Breaking Change (2025-01-06):** Langfuse is now REQUIRED as the sole prompt source. **No fallback prompts exist** - if Langfuse is not configured or prompts are unavailable, the application will raise an error and fail.

**What Was Implemented:**
- ✅ Mandatory prompt fetching from Langfuse UI using `langfuse.get_prompt()` API
- ✅ Two managed prompts:
  - `summarize-document/system` - System instructions
  - `summarize-document/user` - User prompt with variables
- ✅ Prompt caching to avoid repeated API calls within session
- ✅ Link prompt versions to generation observations via `prompt_metadata`
- ✅ Template variable compilation with `{{title}}` → ` titled 'X'` or empty string
- ✅ Upload script to sync prompts to Langfuse (`scripts/upload_prompts.py`)
- ✅ Implemented in both Gemini and Ollama clients
- ✅ Config validation requires Langfuse credentials (except mock mode)
- ✅ **No fallback** - errors raised if Langfuse prompts unavailable

**Filesystem Prompts (Development Reference Only):**
- Located in `summarize_links/prompts/` for version control
- **NOT used at runtime** - only for uploading to Langfuse and git tracking
- Can be uploaded to Langfuse using `scripts/upload_prompts.py`

```bash
# Upload filesystem prompts to Langfuse
uv run python scripts/upload_prompts.py
```

The script reads `system.txt` and `user.txt`, then creates/updates:
- `summarize-document/system` in Langfuse
- `summarize-document/user` in Langfuse

**Benefits Achieved:**
- ✅ Centralized prompt editing in Langfuse UI (no code changes needed)
- ✅ Automatic versioning on every prompt change
- ✅ Hot-swap prompts in production without redeploying
- ✅ Versioned prompts linked to generation traces
- ✅ Instant rollback to previous prompt versions
- ✅ Compare model responses using same prompt version
- ✅ Version control for filesystem prompts via git
- ✅ Clear error messages when Langfuse is misconfigured

**Prompt Metadata Tracking:**

The `SummaryResult` now includes `prompt_metadata`:

```python
@dataclass
class SummaryResult:
    content: str
    suggested_tags: list[str]
    content_type: ContentType
    # ... other fields ...
    prompt_metadata: dict[str, Any] | None = None  # NEW
```

When Langfuse prompts are used:

```python
prompt_metadata = {
    "system_prompt_name": "summarize-document/system",
    "system_prompt_version": 5,
    "user_prompt_name": "summarize-document/user",
    "user_prompt_version": 10,
    "source": "langfuse"
}
```

**Benefits Achieved:**
- ✅ Centralized prompt editing in Langfuse UI (no code changes needed)
- ✅ Automatic versioning on every prompt change
- ✅ Hot-swap prompts in production without redeploying
- ✅ Versioned prompts linked to generation traces
- ✅ Instant rollback to previous prompt versions
- ✅ Compare model responses using same prompt version

**Setup Instructions (REQUIRED):**

1. **Create prompts in Langfuse UI:**
   - Name: `summarize-document/system`
   - Content: Copy from `summarize_links/prompts/system.txt` or use `scripts/upload_prompts.py`

   - Name: `summarize-document/user`
   - Content: Copy from `summarize_links/prompts/user.txt` with variables:
     ```
     # Web Page Summary

     Title: {{title}}
     Source URL: {{url}}

     Content to summarize:
     {{content}}
     ```

2. **Configure Langfuse credentials (REQUIRED):**
   ```bash
   # .env
   LANGFUSE_PUBLIC_KEY=pk-lf-xxx
   LANGFUSE_SECRET_KEY=sk-lf-xxx
   LANGFUSE_BASE_URL=https://cloud.langfuse.com
   ```

3. **Application will fail to start without valid Langfuse credentials** (except in mock mode)

4. **Verify setup:**
   ```bash
   uv run summarize-links from-note --vault ~/Notes
   # Logs will show: "Fetched prompts from Langfuse: system vX, user vY"
   ```

---

### ✅ Phase 3: Evaluation Framework (COMPLETE)

**Goal:** Automated quality assessment and model comparison

**Status**: ✅ **Implemented**

**What Was Implemented:**
- ✅ YAML-based evaluation datasets (`summarize_links/eval_datasets.py`)
- ✅ Automated metrics: tag accuracy (precision, recall, F1), content type accuracy
- ✅ Eval CLI command: `summarize-links eval <dataset.yaml>`
- ✅ Results output to console with summary tables
- ✅ Optional YAML results export with `--output`
- ✅ Score syncing to Langfuse traces
- ✅ Sample evaluation dataset (`eval_datasets/sample.yaml`)

**Modules Created:**
- `summarize_links/eval_datasets.py` - Dataset loading/saving
- `summarize_links/eval_metrics.py` - Metric calculations
- `summarize_links/commands/eval.py` - CLI command handler

**Usage:**
```bash
# Run evaluation on a dataset
summarize-links eval eval_datasets/sample.yaml

# Save results to file
summarize-links eval eval_datasets/sample.yaml --output results.yaml

# Use a different model
summarize-links eval eval_datasets/sample.yaml --model llama3:latest

# Use mock mode for testing
summarize-links eval eval_datasets/sample.yaml --mock
```

**Dataset Format:**
```yaml
name: "My Dataset"
description: "Test dataset for evaluation"
examples:
  - url: "https://example.com/article"
    expected_tags: ["ai", "tutorial"]
    expected_content_type: "tutorial"
```

**Metrics Calculated:**
- **Tag Precision**: Fraction of suggested tags in expected tags
- **Tag Recall**: Fraction of expected tags that were suggested
- **Tag F1 Score**: Harmonic mean of precision and recall
- **Content Type Accuracy**: Binary match of content type classification

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

### Raw Prompt Storage (Phase 1 - Current Implementation)

**Status**: ✅ **Implemented** - Prompts stored inline and sent to traces

**What's Done:**
Both Gemini and Ollama clients store raw prompts and responses in `SummaryResult`:

```python
# In gemini_client.py and ollama_client.py
class GeminiClient:
    def summarize_with_metadata(self, content: str, url: str, title: str | None) -> SummaryResult:
        # Build prompts
        system_prompt = SUMMARY_SYSTEM_PROMPT  # Module-level constant
        user_prompt = _build_prompt(content, url, title)

        # Call API
        response = client.models.generate_content(
            model=self._model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
            ),
        )

        raw_response = response.text

        # Parse and return with prompts attached
        result = parse_llm_json_response(raw_response)
        result.usage_details = usage_details
        result.system_prompt = system_prompt      # Store for tracing
        result.raw_prompt = user_prompt            # Store for tracing
        result.raw_response = raw_response         # Store for tracing

        return result
```

**Integration with Langfuse:**
Prompts and raw responses are sent to Langfuse in processor.py:

```python
with tracer.trace_generation(name="summarize", model=config.model) as generation:
    summary_result = client.summarize_with_metadata(...)

    if generation and hasattr(generation, "update"):
        generation.update(
            input={
                "system": summary_result.system_prompt,  # Full system instructions
                "prompt": summary_result.raw_prompt,     # User prompt with content
            },
            output=summary_result.raw_response,  # Raw JSON response from LLM
            metadata={...},
            usage_details=summary_result.usage_details,
        )
```

**Limitations of Current Approach:**
- ❌ Prompts are hardcoded in `gemini.py` and `ollama.py`
- ❌ Changing prompts requires code changes and redeployment
- ❌ No centralized prompt management
- ❌ No automatic versioning (must manually track changes)
- ❌ Cannot A/B test prompts without code changes

**Benefits of Current Approach:**
- ✅ Simple implementation, no Langfuse prompt API dependency
- ✅ Complete data capture in traces for debugging
- ✅ Works offline/without Langfuse configuration

```python
# In gemini_client.py and ollama_client.py
class GeminiClient:
    def __init__(self, ...):
        # Initialize Langfuse client for prompt fetching
        self._langfuse_client = Langfuse() if langfuse_enabled else None
        self._system_prompt_cache = None
        self._user_prompt_template_cache = None

    def _get_prompts(self):
        """Fetch Langfuse prompt templates (with caching)."""
        if not self._langfuse_client:
            # Fallback to hardcoded prompts if Langfuse not configured
            return self._get_fallback_prompts()

        if not self._system_prompt_cache:
            self._system_prompt_cache = self._langfuse_client.get_prompt(
                "summarize-document/system"
            )
        if not self._user_prompt_template_cache:
            self._user_prompt_template_cache = self._langfuse_client.get_prompt(
                "summarize-document/user"
            )

        return self._system_prompt_cache, self._user_prompt_template_cache

    def summarize_with_metadata(self, content: str, url: str, title: str | None):
        # Get prompts from Langfuse
        system_prompt, user_prompt_template = self._get_prompts()

        # Compile user prompt with variables
        compiled_user = user_prompt_template.compile(
            title=title or "Unknown",
            url=url,
            content=content
        )

        # Use prompts in API call
        response = self._model.generate_content(
            [system_prompt.prompt, compiled_user]
        )

        # Return with prompt info for tracing
        return SummaryResult(
            ...,
            prompt_info={
                "system_prompt_name": "summarize-document/system",
                "user_prompt_name": "summarize-document/user",
                "system_version": system_prompt.version,
                "user_version": user_prompt_template.version,
            }
        )
```

**Benefits:**
- **Centralized Management**: Edit prompts in Langfuse UI without code changes
- **Automatic Versioning**: Every prompt change gets a new version
- **A/B Testing**: Deploy different prompt versions to different users
- **Instant Rollback**: Revert to previous prompt version with one click
- **Cross-Model Consistency**: Same prompts used by Gemini and Ollama
- **Hot-Swap**: Update prompts in production without redeploying code

**Implementation Tasks:**
1. Create prompts in Langfuse UI:
   - `summarize-document/system` with base instructions
   - `summarize-document/user` with `{{title}}`, `{{url}}`, `{{content}}` variables
2. Add Langfuse client initialization to LLM clients
3. Implement `_get_prompts()` method with caching
4. Add fallback to hardcoded prompts when Langfuse unavailable
5. Update API calls to use fetched prompts
6. Link prompt versions to generation observations
7. Test prompt fetching and compilation
8. Document prompt management workflow

### Tracer Module (`summarize_links/langfuse_tracer.py`)

Implemented `LangfuseTracer` class using **OpenTelemetry API** (Langfuse SDK v3):

```python
# Key methods using OTel context managers
def trace_url_processing(url, name, metadata) -> ContextManager[Any]
    # Creates a trace (top-level observation) using start_as_current_observation
    # Uses slug as trace name for easy filtering in Langfuse UI

def trace_span(name, input_data, metadata) -> ContextManager[Any]
    # Creates a span observation within current context
    # Auto-nests via OpenTelemetry context propagation

def trace_generation(name, input_data, metadata, model) -> ContextManager[Any]
    # Creates a generation observation for LLM calls
    # Auto-nests via OpenTelemetry context propagation
    # Accepts usage_details for token tracking

def score_trace(trace_id, name, value, comment)
    # Adds evaluation scores to traces

def flush()
    # Flushes pending traces to Langfuse
```

**Features:**
- ✅ No-op when disabled (graceful degradation via enabled property)
- ✅ Context managers for automatic nesting (OpenTelemetry-based)
- ✅ Parent-child relationships via OpenTelemetry context propagation
- ✅ Exception handling with warning logs (re-raises for proper error handling)
- ✅ Automatic flushing in trace_url_processing finally block
- ✅ Global tracer management (initialize_tracer, get_tracer)
- ✅ Auth check on initialization
- ✅ Comprehensive docstrings with data capture best practices

**OpenTelemetry Context Propagation:**
The tracer uses `client.start_as_current_observation()` which automatically:
- Sets the observation as current in OpenTelemetry context
- Makes subsequent observations children of the current one
- Requires no manual parent tracking or trace_id passing

### Processor Integration (`summarize_links/processor.py`)

Added comprehensive tracing in `process_url_with_metadata()` function:

```python
# Import tracer and propagate_attributes
from summarize_links.langfuse_tracer import get_tracer, propagate_attributes

tracer = get_tracer()

# Create trace for entire URL processing (slug as trace name)
with tracer.trace_url_processing(
    url=url,
    name=slug,  # Easy filtering in Langfuse UI
    metadata={
        "slug": slug,
        "source_note": daily_note_filename,
        "user_tags": url_context.tags,
    },
) as trace:
    # Set trace-level attributes for all nested observations
    with propagate_attributes(
        session_id=daily_note_filename or "direct-url",
        tags=[
            "production" if not config.mock_mode else "mock",
            config.model.split(":")[0],
        ],
        metadata={
            "vault": str(config.vault_path),
            "provider": "gemini" if config.model.startswith("gemini") else "ollama",
        },
    ):
        # Fetch span
        with tracer.trace_span(name="fetch", input_data={"url": url}) as fetch_span:
            page_metadata = fetch_and_extract_metadata(url)

            # Update with extracted metadata
            if fetch_span and hasattr(fetch_span, "update"):
                fetch_span.update(
                    output={"title": ..., "content_length": ..., ...},
                    metadata={"author": ..., "published_date": ..., ...},
                )

        # Generate summary with generation observation
        with tracer.trace_generation(name="summarize", model=config.model) as generation:
            summary_result = client.summarize_with_metadata(...)

            # Update with raw LLM input/output and usage
            if generation and hasattr(generation, "update"):
                generation.update(
                    input={
                        "system": summary_result.system_prompt,  # Full system prompt
                        "prompt": summary_result.raw_prompt,     # User prompt
                    },
                    output=summary_result.raw_response,  # Raw LLM response (JSON)
                    metadata={
                        "url": url,
                        "parsed_tags": summary_result.suggested_tags,
                        "parsed_content_type": summary_result.content_type,
                        ...
                    },
                    usage_details=summary_result.usage_details,
                )

        # Write span
        with tracer.trace_span(name="write", input_data={...}) as write_span:
            summary_path = write_summary_note_with_metadata(...)

            # Update with write metadata
            if write_span and hasattr(write_span, "update"):
                write_span.update(
                    output={"filepath": ..., "overwritten": ..., ...},
                    metadata={"final_tags": ..., "content_type": ..., ...},
                )

        # Update trace with final summary
        if trace and hasattr(trace, "update"):
            trace.update(
                input=url,
                output=summary_result.content,
                metadata={"success": True, "slug": slug, ...},
            )
```

**Key Features:**
- ✅ Uses slug as trace name for easy Langfuse UI filtering
- ✅ **propagate_attributes()** sets session_id, tags, and metadata for all nested observations
- ✅ **System and user prompts** stored in generation input
- ✅ **Raw LLM response** stored in generation output (for LLM-as-judge evaluation)
- ✅ **Parsed results** (tags, content_type) stored in generation metadata
- ✅ **Token usage** tracked via usage_details
- ✅ **Error tracking** in generation observations with level="ERROR"
- ✅ **contextlib.suppress(Exception)** for safe update calls
- ✅ **Comprehensive metadata** at each stage (fetch, generation, write)

**Trace hierarchy:**
```
trace: {slug} (e.g., "google-gemini-api-docs")
  ├─ span: fetch
  │  └─ output: {title, content_length, has_author, ...}
  ├─ generation: summarize
  │  ├─ input: {system: "...", prompt: "..."}
  │  ├─ output: "{\"summary\": ..., \"tags\": ..., ...}"
  │  ├─ metadata: {parsed_tags, parsed_content_type, ...}
  │  └─ usage_details: {input, output, total}
  └─ span: write
     └─ output: {filepath, overwritten, final_tag_count, ...}
```

### Prompt Storage and Versioning

**Current Implementation (Phase 1):** ✅ Raw prompts stored in SummaryResult

Both Gemini and Ollama clients store system prompt, user prompt, and raw response in `SummaryResult`, which are then sent to Langfuse generation observations. See "Prompt Storage Implementation" section above for details.

**Future Enhancement (Optional):** Langfuse Prompt Management API
For centralized prompt management, we could migrate to use `langfuse.get_prompt()` to fetch prompts from the Langfuse UI with automatic versioning. This would enable hot-swapping prompts without code changes and A/B testing. However, the current approach of storing raw prompts in traces is sufficient for debugging and evaluation.

### Token Usage Tracking

#### Data Model (`summarize_links/models.py`)
```python
@dataclass
class SummaryResult:
    content: str
    suggested_tags: list[str]
    content_type: str
    usage_details: dict[str, int] | None = None  # Token usage
    system_prompt: str | None = None              # System instruction
    raw_prompt: str | None = None                 # User prompt
    raw_response: str | None = None               # Raw LLM response
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

## Implementation Summary

**Phase 1: Core Integration** - ✅ **COMPLETE**
Phase 1 Implementation Summary

**Status:** ✅ **COMPLETE** (Core Tracing + Raw Prompt Storage)
1. **Tracer Module** (`langfuse_tracer.py`)
   - OpenTelemetry-based API using `start_as_current_observation()`
   - Context managers: `trace_url_processing`, `trace_span`, `trace_generation`
   - Graceful degradation when not configured
   - Global tracer management: `initialize_tracer()`, `get_tracer()`
   - `propagate_attributes()` for setting trace-level metadata

2. **Processor Integration** (`processor.py`)
   - Full pipeline tracing in `process_url_with_metadata()`
   - Trace hierarchy: trace → fetch span → generation → write span
   - Slug-based trace naming for easy filtering
   - Error tracking in generation observations
   - Safe update calls with `contextlib.suppress(Exception)`

3. **LLM Client Integration** (`gemini.py`, `ollama.py`)
   - System prompt, user prompt, and raw response storage in `SummaryResult`
   - Token usage extraction from API responses
   - Consistent interface across providers

4. **Data Models** (`models.py`)
   - Added `usage_details: dict[str, int] | None` to `SummaryResult`
   - Added `system_prompt: str | None` to `SummaryResult`
   - Added `raw_prompt: str | None` to `SummaryResult`
   - Added `raw_response: str | None` to `SummaryResult`

5. **Configuration** (`config.py`)
   - `langfuse_enabled`, `langfuse_public_key`, `langfuse_secret_key`, `langfuse_base_url`
   - HTTP logging suppression for cleaner output
   - CLI initialization in `cli.py`: `initialize_tracer(config)`

6. **Testing** (`test_langfuse_tracer.py`)
   - 20 tests covering disabled mode, context managers, metadata
   - Integration tested with 496 total tests passing

### Implementation Approach:

**commit history available in git log** - Key commits include:
- Initial Langfuse integration with configuration
- Migration to OpenTelemetry API
- Token usage tracking for both Gemini and Ollama
- Prompt and response storage in SummaryResult
- Processor integration with comprehensive metadata
- Error tracking and safe update patterns

---

## Phase 1.5: Prompt Storage (Next Step)
---

## Phase 2: Evaluation Framework (Future)

**Status:** Not yet implemented (optional enhancement)
Langfuse Prompt Management (Next Step)

**Status:** 📋 Not yet implemented (optional enhancement after Phase 2t
**Estimated Time:** 2-3 hours
**Priority:** High (enables prompt iteration without code changes)

### Goals

Migrate from hardcoded prompts to **Langfuse Prompt Management** for centralized prompt control.

### Implementation Tasks

#### 1. Create Prompts in Langfuse UI
- [ ] Navigate to Langfuse dashboard → "Prompts" section
- [ ] Create `summarize-document/system` prompt
  - Type: Text prompt
  - Content: Current `SUMMARY_SYSTEM_PROMPT` from `gemini.py`
  - Publish as v1
- [ ] Create `summarize-document/user` prompt
  - Type: Text prompt with variables
  - Variables: `{{title}}`, `{{url}}`, `{{content}}`
  - Content: Current `_build_prompt()` template
  - Publish as v1

#### 2. Update LLM Clients (Gemini & Ollama)
- [ ] Add Langfuse client initialization to `__init__`
  ```python
  self._langfuse_client = Langfuse() if langfuse_enabled else None
  self._prompt_cache = {}
  ```
- [ ] Implement `_get_langfuse_prompts()` method with caching
  - Fetch `summarize-document/system` and `summarize-document/user`
  - Cache to avoid repeated API calls
  - Fall back to hardcoded prompts on error
- [ ] Update `summarize_with_metadata()` to use fetched prompts
  - Fetch prompts via `_get_langfuse_prompts()`
  - Compile user prompt with variables: `.compile(title=..., url=..., content=...)`
  - Use compiled prompts in API calls
  - Store prompt names and versions in result

#### 3. Update Data Models
- [ ] Add `prompt_metadata` field to `SummaryResult`:
  ```python
  prompt_metadata: dict[str, Any] | None = None  # Langfuse prompt info
  ```
  - Store: `system_prompt_name`, `user_prompt_name`, versions

#### 4. Update Processor Integration
- [ ] Modify `processor.py` generation observation update
- [ ] Add prompt metadata to generation observation
- [ ] Link prompt objects to observations (if supported by SDK)

#### 5. Testing
- [ ] Test prompt fetching from Langfuse
- [ ] Test prompt compilation with variables
- [ ] Test fallback when Langfuse unavailable or prompts don't exist
- [ ] Test caching (verify no repeated API calls)
- [ ] Verify prompt versions appear in Langfuse traces

#### 6. Documentation
- [ ] Update README with prompt management instructions
- [ ] Document how to create/edit prompts in Langfuse UI
- [ ] Document prompt versioning workflow
- [ ] Add troubleshooting section for prompt fetching

### Implementation Example

See detailed code examples in the "Future Enhancement: Langfuse Prompt Management" section below.

### Verification Checklist

After implementation:
- [ ] Prompts exist in Langfuse UI with v1 published
- [ ] Processing a URL creates trace with linked prompt versions
- [ ] Editing prompt in Langfuse UI changes behavior (after cache clear)
- [ ] Fallback works when Langfuse unavailable
- [ ] All 496+ tests still passing

---

## Phase 3:
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
