# Commands & Chat Unification Plan

**Date:** 2026-01-23
**Author:** GitHub Copilot
**Goal:** Maximize code reuse by unifying CLI commands and chat tools around a shared summarization service layer.

---

## Context
- CLI commands (`commands/*.py`) and chat tools (`chat/tools/*.py`) duplicate the same pipeline:
  - create LLM client → fetch & extract content → summarize → write note → link/remove URL.
- `processor.process_url_with_metadata` and `SummarizeUrlTool`/`ResummarizeTool` share ≥80% logic.
- Tracing, prompts, progress reporting, and error handling are repeated in both paths.

## Goals
1. Single source of truth for summarization/resummarization workflows.
2. Adapters for CLI and chat to reduce duplication.
3. Unified progress callbacks, tracing, and prompt prefetching.
4. Maintain backward compatibility (shims) while refactoring.

## Non-Goals
- Changing user-facing behavior or configuration.
- Replacing CLI/chat UIs.
- Adding new providers (reuse existing factory).

---

## Architecture Overview

### Service Layer (`summarize_links/services/`)
- `services/summarization.py`
  - `@dataclass ProcessOutcome`: `success`, `message`, `should_delete_source`, `summary_path`, `slug`, `summary_result`, `page_metadata`.
  - `process_url(url_ctx: UrlWithContext, config: Config, client: SummarizerProtocol, source_note: str | None = None, source_date: datetime | None = None, progress_cb: ProgressCallback | None = None) -> ProcessOutcome`
  - `process_urls(url_ctxs: list[UrlWithContext], config: Config, source_note: str | None = None, source_date: datetime | None = None, progress_cb: ProgressCallback | None = None) -> tuple[int, list[ProcessOutcome]]`
  - `resummarize(identifier: str, config: Config, progress_cb: ProgressCallback | None = None) -> ProcessOutcome`
- `services/summaries.py`
  - `find_summary_metadata(identifier: str, config: Config) -> SummaryMetadata` (shared slug/URL lookup)

**Responsibilities:** encapsulate fetch → summarize → write → link/remove → tracing; prefetch Langfuse prompts; standardize `ProgressCallback` `(stage: str, detail: str)`.

### Adapters
- **CLI commands** → call `services.summarization.*`; handle Rich output only.
- **Chat tools** → map tool inputs to `UrlWithContext`; call services; produce `ToolResult`.
- Keep `processor.py` as shim delegating to services to avoid breaking imports.

### Shared Utilities
- Refactor `_find_summary_by_url_or_slug` into `services/summaries.py` (used by `ResummarizeTool` and CLI).
- Keep `create_llm_client` as single factory.
- Tailored progress adapters for Rich (CLI) and `ChatFormatter` (chat).

---

## Deliverables
- `summarize_links/services/summarization.py`
- `summarize_links/services/summaries.py`
- Refactored `processor.py` delegating to services
- Refactored `chat/tools/summarize.py` & `ResummarizeTool`
- Refactored CLI commands (`from_note`, `urls`, `resummarize`) to services
- Tests for services, adapters
- Docs updated (this plan + tasks log)

---

## Checklist
- [x] Create `services/summarization.py` with `ProcessOutcome` and core functions
- [x] Create `services/summaries.py` with identifier lookup helper
- [x] Refactor `processor.py` to delegate to service layer (keep shim)
- [x] Refactor `chat/tools/summarize.py` & `ResummarizeTool` to call services
- [x] Refactor CLI commands to call services
- [x] Normalize `ProgressCallback` signature `(stage: str, detail: str)`
- [x] Add unit tests for services (process_url, process_urls, resummarize, lookup)
- [x] Add adapter tests for chat tools
- [ ] CLI adapter integration tests (deferred - lower priority)
- [x] Update docs/tasks.md with completion summary

---

## Risks & Mitigations
- **Risk:** Regression in CLI/chat behavior → **Mitigation:** keep shims, add adapter tests.
- **Risk:** Tracing gaps → **Mitigation:** keep tracing in services and verify Langfuse spans in tests.
- **Risk:** Progress UX differences → **Mitigation:** adapter-specific progress wrappers.

## Rollback
- Keep `processor.py` shim to re-point CLI quickly.
- Keep original chat tool logic for one release behind feature flag if needed.

---

## References
- Duplicated logic: `processor.process_url_with_metadata` ↔ `chat/tools/summarize.SummarizeUrlTool.execute`
- Duplicated logic: `process_resummarize_batch` ↔ `ResummarizeTool.execute`
- LLM factory: `summarize_links/llm/factory.py:create_llm_client`

