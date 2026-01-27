"""Shared summarization services used by CLI and chat tools.

These functions encapsulate the core fetch → summarize → write → link/remove
pipeline so that adapters (CLI commands and chat tools) can reuse them.
"""

from __future__ import annotations

import contextlib
import logging
import signal
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from summarize_links.config import Config
from summarize_links.exceptions import (
    ContentExtractionError,
    ContentFetchError,
    GeminiAPIError,
    ModelNotInstalledError,
    OllamaAPIError,
    OllamaServerError,
    RateLimitError,
    URLValidationError,
)
from summarize_links.extract import fetch_and_extract_metadata
from summarize_links.extract.playwright_fetching import close_browser_context
from summarize_links.langfuse_tracer import get_tracer, propagate_attributes
from summarize_links.llm import SummarizerProtocol, create_llm_client
from summarize_links.models import PageMetadata, SummaryResult, UrlWithContext, merge_tags
from summarize_links.notes import (
    add_summary_link_to_daily_note,
    get_existing_summary_date,
    remove_url_line_from_note,
    slug_from_url,
    summary_exists,
    write_stub_note,
    write_summary_note_with_metadata,
)
from summarize_links.services.summaries import SummaryMetadata, find_summary_metadata

logger = logging.getLogger(__name__)

# Simple progress callback signature: (stage, detail)
ProgressCallback = Callable[[str, str], None]

# Type-safe error type (ensures only valid error types are used)
ErrorType = Literal[
    "fetch",
    "extraction",
    "rate_limit",
    "api",
    "invalid_url",
    "model_not_installed",
    "ollama",
]

# Error type constants for structured error handling
ERROR_TYPE_FETCH: ErrorType = "fetch"
ERROR_TYPE_EXTRACTION: ErrorType = "extraction"
ERROR_TYPE_RATE_LIMIT: ErrorType = "rate_limit"
ERROR_TYPE_API: ErrorType = "api"
ERROR_TYPE_INVALID_URL: ErrorType = "invalid_url"
ERROR_TYPE_MODEL_NOT_INSTALLED: ErrorType = "model_not_installed"
ERROR_TYPE_OLLAMA: ErrorType = "ollama"


@dataclass
class ProcessOutcome:
    """Result of processing a single URL.

    Attributes:
        success: Whether the URL was processed successfully.
        message: Human-readable status message.
        should_delete_source: Whether the URL line should be deleted from source note.
        summary_path: Path to the created summary note (if successful).
        slug: URL slug used for the summary filename.
        summary_result: The SummaryResult from LLM summarization (if successful).
        page_metadata: The PageMetadata from content extraction (if successful).
        error_type: Structured error type for programmatic handling (None if success).
    """

    success: bool
    message: str
    should_delete_source: bool = False
    summary_path: str | None = None
    slug: str | None = None
    summary_result: SummaryResult | None = None
    page_metadata: PageMetadata | None = None
    error_type: ErrorType | None = None


# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1

_shutdown_requested = False


def _handle_shutdown(signum: int, frame: object) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown requested (signal %s)", signum)


def _handle_processing_error(
    error: Exception,
    error_type: ErrorType,
    url: str,
    slug: str,
    config: Config,
    had_successful_summary: bool,
    summary_date: datetime,
    log_level: str = "warning",
    message_prefix: str | None = None,
) -> ProcessOutcome:
    """Handle errors during URL processing.

    Creates stub notes for failures (unless dry-run or summary already exists)
    and returns a ProcessOutcome with structured error information.

    Args:
        error: The exception that was raised.
        error_type: Structured error type for programmatic handling.
        url: The URL being processed.
        slug: The URL slug for the summary filename.
        config: Application configuration.
        had_successful_summary: Whether a complete summary already existed.
        summary_date: Date for the summary note.
        log_level: Logging level ("warning" or "error").
        message_prefix: Optional prefix for the outcome message.

    Returns:
        ProcessOutcome indicating failure with error details.
    """
    # Log the error at appropriate level
    log_func = logger.warning if log_level == "warning" else logger.error
    log_func("%s for %s: %s", error_type.replace("_", " ").title(), url, error)

    # Write stub note for first-time failures (not for retries/re-summarizations)
    assert config.vault_path is not None, "vault_path must be set"
    if not config.dry_run and not had_successful_summary:
        write_stub_note(
            vault_path=config.vault_path,
            out_folder=config.out_folder,
            url=url,
            reason=str(error),
            date=summary_date,
            error_type=f"{error_type}_error",
        )

    # Construct message
    prefix = message_prefix or error_type.replace("_", " ").title()
    message = f"{prefix}: {url} ({error})"

    return ProcessOutcome(
        success=False,
        message=message,
        should_delete_source=False,
        slug=slug,
        error_type=error_type,
    )


def _should_skip_processing(
    existing_summary_complete: bool, force: bool, slug: str
) -> ProcessOutcome | None:
    """Check if processing should be skipped for an existing summary.

    Returns:
        ProcessOutcome if processing should be skipped, None otherwise.
    """
    if not force and existing_summary_complete:
        return ProcessOutcome(True, f"Skipped (exists): {slug}", True, None, slug)
    return None


def _fetch_page_content(
    url: str,
    config: Config,
    tracer: Any,
    progress_cb: ProgressCallback | None,
) -> PageMetadata:
    """Fetch and extract page content with tracing.

    Args:
        url: URL to fetch.
        config: Application configuration.
        tracer: Langfuse tracer instance.
        progress_cb: Optional progress callback.

    Returns:
        PageMetadata with extracted content.

    Raises:
        ContentFetchError: If fetching fails.
        ContentExtractionError: If extraction fails.
        URLValidationError: If URL is invalid.
    """
    if progress_cb:
        progress_cb("Fetching", url)

    with tracer.trace_span(name="fetch", input_data={"url": url}) as fetch_span:
        try:
            page_metadata = fetch_and_extract_metadata(
                url,
                playwright_enabled=config.playwright_enabled,
                playwright_timeout=config.playwright_timeout,
            )
            # Update trace with fetch metadata
            if fetch_span and hasattr(fetch_span, "update"):
                with contextlib.suppress(Exception):
                    fetch_span.update(
                        output={
                            "title": page_metadata.title,
                            "domain": page_metadata.domain,
                            "content_length": len(page_metadata.content),
                        },
                        metadata={
                            "author": page_metadata.author,
                            "site_name": page_metadata.site_name,
                            "published_date": page_metadata.published_date,
                            "article_tags": page_metadata.article_tags[:10],
                            "fetch_method": page_metadata.fetch_method,
                            "fallback_triggered": (page_metadata.fetch_method == "playwright"),
                            "http_error_category": page_metadata.http_error_category,
                        },
                    )
            return page_metadata
        except (ContentFetchError, ContentExtractionError, URLValidationError) as e:
            if fetch_span and hasattr(fetch_span, "update"):
                with contextlib.suppress(Exception):
                    fetch_span.update(
                        level="ERROR",
                        status_message=str(e),
                        output={"error": str(e)},
                        metadata={"error_type": type(e).__name__, "url": url},
                    )
            raise


def _generate_summary(
    page_metadata: PageMetadata,
    url: str,
    client: SummarizerProtocol,
    config: Config,
    tracer: Any,
    progress_cb: ProgressCallback | None,
) -> SummaryResult:
    """Generate AI summary with tracing.

    Args:
        page_metadata: Extracted page content.
        url: Source URL.
        client: LLM client for summarization.
        config: Application configuration.
        tracer: Langfuse tracer instance.
        progress_cb: Optional progress callback.

    Returns:
        SummaryResult with generated content.

    Raises:
        GeminiAPIError: If Gemini API call fails.
        OllamaAPIError: If Ollama API call fails.
        RateLimitError: If rate limit exceeded.
    """
    if progress_cb:
        progress_cb("Summarizing", page_metadata.title or url)

    # Pre-fetch Langfuse prompt if available (for caching/tracing)
    if hasattr(client, "_get_langfuse_prompts"):
        try:
            client._get_langfuse_prompts()
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to pre-fetch Langfuse prompt: %s", e)

    langfuse_prompt = None
    if hasattr(client, "get_cached_prompt"):
        langfuse_prompt = client.get_cached_prompt()

    with tracer.trace_generation(
        name="summarize",
        model=config.model,
        prompt=langfuse_prompt,
    ) as generation:
        try:
            summary_result = client.summarize_with_metadata(
                content=page_metadata.content,
                url=url,
                title=page_metadata.title,
            )
            # Update trace with generation metadata
            if generation and hasattr(generation, "update"):
                with contextlib.suppress(Exception):
                    update_data: dict[str, Any] = {}
                    if summary_result.system_prompt and summary_result.raw_prompt:
                        update_data["input"] = {
                            "system": summary_result.system_prompt,
                            "prompt": summary_result.raw_prompt,
                        }
                    elif summary_result.raw_prompt:
                        update_data["input"] = summary_result.raw_prompt
                    if summary_result.raw_response:
                        update_data["output"] = summary_result.raw_response
                    update_data["metadata"] = {
                        "url": url,
                        "title": page_metadata.title,
                        "content_length": len(page_metadata.content),
                        "parsed_tags": summary_result.suggested_tags,
                        "parsed_content_type": summary_result.content_type,
                        "summary_length": len(summary_result.content),
                        "provider": config.model_provider,
                        "model": config.model,
                    }
                    if summary_result.usage_details:
                        update_data["usage_details"] = summary_result.usage_details
                    generation.update(**update_data)
            return summary_result
        except (GeminiAPIError, OllamaAPIError, RateLimitError) as e:
            if generation and hasattr(generation, "update"):
                with contextlib.suppress(Exception):
                    generation.update(
                        level="ERROR",
                        status_message=str(e),
                        metadata={"error_type": type(e).__name__, "url": url},
                    )
            raise


def _write_summary_and_link(
    url: str,
    url_ctx: UrlWithContext,
    summary_result: SummaryResult,
    page_metadata: PageMetadata,
    summary_date: datetime,
    needs_overwrite: bool,
    source_note: str | None,
    link_source_note: bool,
    config: Config,
) -> tuple[Path, list[str]]:
    """Write summary note and optionally link back to source.

    Args:
        url: Source URL.
        url_ctx: URL with context (tags, source info).
        summary_result: Generated summary.
        page_metadata: Extracted page metadata.
        summary_date: Date for summary note.
        needs_overwrite: Whether to overwrite existing note.
        source_note: Source daily note filename.
        link_source_note: Whether to add link to source note.
        config: Application configuration.

    Returns:
        Tuple of (summary_path, final_tags).
    """
    assert config.vault_path is not None, "vault_path must be set"

    summary_status = "success"
    final_tags = merge_tags(
        user_tags=url_ctx.tags or [],
        article_tags=page_metadata.article_tags,
        ai_tags=summary_result.suggested_tags,
        default_tags=config.default_tags,
    )

    summary_path = write_summary_note_with_metadata(
        vault_path=config.vault_path,
        out_folder=config.out_folder,
        url=url,
        summary_result=summary_result,
        page_metadata=page_metadata,
        user_tags=url_ctx.tags,
        date=summary_date,
        source_note=source_note,
        default_tags=config.default_tags,
        overwrite=needs_overwrite,
        summary_status=summary_status,
        summary_model=config.model,
        summary_provider=config.model_provider,
        summary_date=datetime.now(),
    )

    # Link back to source daily note (optional)
    if source_note and link_source_note:
        lookup_url = url_ctx.original_url or url
        try:
            add_summary_link_to_daily_note(
                vault_path=config.vault_path,
                daily_notes_folder=config.daily_notes_folder,
                note_filename=source_note,
                summary_path=summary_path,
                url=lookup_url,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Failed to add summary link to daily note %s: %s",
                source_note,
                e,
            )

    return summary_path, final_tags


def process_url(
    url_ctx: UrlWithContext,
    config: Config,
    client: SummarizerProtocol,
    source_note: str | None = None,
    source_date: datetime | None = None,
    progress_cb: ProgressCallback | None = None,
    link_source_note: bool = True,
    force_override: bool | None = None,
) -> ProcessOutcome:
    """Process a single URL with full metadata extraction and note writing.

    This is the core orchestrator that delegates to specialized helper functions:
    - _should_skip_processing: Check if URL already processed
    - _fetch_page_content: Fetch and extract web page content
    - _generate_summary: Generate AI summary with LLM
    - _write_summary_and_link: Write note and link to source

    All operations are traced via Langfuse for observability.

    Args:
        url_ctx: URL with context (tags, source info).
        config: Application configuration.
        client: LLM client for summarization.
        source_note: Source daily note filename for back-linking.
        source_date: Date from source note (for filename).
        progress_cb: Optional progress callback.
        link_source_note: Whether to add link to source note.
        force_override: Override config.force if set (avoids config mutation).

    Returns:
        ProcessOutcome with success status and details. If should_delete_source is True,
        the caller must remove the URL line from the source note using
        remove_url_line_from_note().
    """
    assert config.vault_path is not None, "vault_path must be set"

    # Use force_override if provided, otherwise fall back to config.force
    force = force_override if force_override is not None else config.force

    # Resolve summary date: existing summary date > source_date > now
    url = url_ctx.url
    slug = slug_from_url(url)
    existing_date = get_existing_summary_date(config.vault_path, config.out_folder, url)
    summary_date = existing_date or source_date or datetime.now()

    # Check if we should skip processing
    existing_summary_complete = summary_exists(
        config.vault_path, config.out_folder, url, summary_date
    )
    skip_outcome = _should_skip_processing(existing_summary_complete, force, slug)
    if skip_outcome:
        return skip_outcome

    needs_overwrite = force or not existing_summary_complete
    had_successful_summary = existing_summary_complete

    if config.dry_run:
        return ProcessOutcome(True, f"Would process: {url} -> {slug}.md", False, None, slug)

    # Main processing with tracing
    tracer = get_tracer()
    with tracer.trace_url_processing(
        url=url,
        name=slug,
        metadata={"slug": slug, "source_note": source_note, "user_tags": url_ctx.tags},
    ) as trace:
        with propagate_attributes(
            session_id=source_note or "direct-url",
            tags=[
                "production",
                config.model.split(":")[0] if ":" in config.model else config.model,
            ],
            metadata={"vault": str(config.vault_path), "provider": config.model_provider},
        ):
            try:
                # Fetch page content
                page_metadata = _fetch_page_content(url, config, tracer, progress_cb)

                # Generate AI summary
                summary_result = _generate_summary(
                    page_metadata, url, client, config, tracer, progress_cb
                )

                # Write summary note and link to source
                summary_path, final_tags = _write_summary_and_link(
                    url,
                    url_ctx,
                    summary_result,
                    page_metadata,
                    summary_date,
                    needs_overwrite,
                    source_note,
                    link_source_note,
                    config,
                )

                # Update trace with success metadata
                if trace and hasattr(trace, "update"):
                    with contextlib.suppress(Exception):
                        trace.update(
                            input=url,
                            output=summary_result.content,
                            metadata={
                                "success": True,
                                "slug": slug,
                                "user_tags": url_ctx.tags or [],
                                "source_note": source_note,
                                "summary_path": str(summary_path),
                                "summary_status": "success",
                                "summary_provider": config.model_provider,
                                "filename": summary_path.name,
                                "title": page_metadata.title,
                                "content_type": summary_result.content_type,
                                "final_tags": final_tags,
                            },
                        )

                return ProcessOutcome(
                    True,
                    f"Created: {slug}.md",
                    True,
                    str(summary_path),
                    slug,
                    summary_result,
                    page_metadata,
                )

            # === STEP 6: Error handling with stub note creation ===
            # Each error type is handled with appropriate logging and stub note creation
            except URLValidationError as e:
                return _handle_processing_error(
                    e,
                    ERROR_TYPE_INVALID_URL,
                    url,
                    slug,
                    config,
                    had_successful_summary,
                    summary_date,
                    log_level="warning",
                    message_prefix="Invalid URL",
                )
            except ContentFetchError as e:
                return _handle_processing_error(
                    e,
                    ERROR_TYPE_FETCH,
                    url,
                    slug,
                    config,
                    had_successful_summary,
                    summary_date,
                    log_level="warning",
                    message_prefix="Fetch error",
                )
            except ContentExtractionError as e:
                return _handle_processing_error(
                    e,
                    ERROR_TYPE_EXTRACTION,
                    url,
                    slug,
                    config,
                    had_successful_summary,
                    summary_date,
                    log_level="warning",
                    message_prefix="Extraction error",
                )
            except RateLimitError as e:
                return _handle_processing_error(
                    e,
                    ERROR_TYPE_RATE_LIMIT,
                    url,
                    slug,
                    config,
                    had_successful_summary,
                    summary_date,
                    log_level="error",
                    message_prefix="[Rate limited]",
                )
            except OllamaServerError as e:
                return _handle_processing_error(
                    e,
                    ERROR_TYPE_OLLAMA,
                    url,
                    slug,
                    config,
                    had_successful_summary,
                    summary_date,
                    log_level="error",
                    message_prefix="Ollama server error",
                )
            except ModelNotInstalledError as e:
                return _handle_processing_error(
                    e,
                    ERROR_TYPE_MODEL_NOT_INSTALLED,
                    url,
                    slug,
                    config,
                    had_successful_summary,
                    summary_date,
                    log_level="error",
                    message_prefix="Model not installed",
                )
            except OllamaAPIError as e:
                return _handle_processing_error(
                    e,
                    ERROR_TYPE_OLLAMA,
                    url,
                    slug,
                    config,
                    had_successful_summary,
                    summary_date,
                    log_level="error",
                    message_prefix="Ollama API error",
                )
            except GeminiAPIError as e:
                return _handle_processing_error(
                    e,
                    ERROR_TYPE_API,
                    url,
                    slug,
                    config,
                    had_successful_summary,
                    summary_date,
                    log_level="error",
                    message_prefix="API error",
                )


def process_urls(
    url_ctxs: Iterable[UrlWithContext],
    config: Config,
    source_note: str | None = None,
    source_date: datetime | None = None,
    progress_cb: ProgressCallback | None = None,
) -> tuple[int, list[ProcessOutcome]]:
    """Process a batch of URLs with graceful interruption handling."""
    global _shutdown_requested
    _shutdown_requested = False

    original_handler = signal.signal(signal.SIGINT, _handle_shutdown)
    try:
        client = create_llm_client(
            model=config.model,
            provider=config.model_provider,
            gemini_api_key=config.gemini_api_key,
            ollama_endpoint=config.ollama_endpoint,
            azure_api_key=config.azure_api_key,
            azure_endpoint=config.azure_endpoint,
            azure_deployment_name=config.azure_deployment_name,
            azure_api_version=config.azure_api_version,
            state_path=config.vault_path,
            yaml_model_limits=config.model_limits,
        )

        results: list[ProcessOutcome] = []
        urls_to_delete: dict[str, list[str]] = {}
        interrupted = False

        for url_ctx in url_ctxs:
            if _shutdown_requested:
                interrupted = True
                logger.info("Stopping early due to shutdown request")
                break

            ctx_note_filename = url_ctx.source_note or source_note
            ctx_source_date = None
            if url_ctx.source_date:
                try:
                    parsed_date = datetime.strptime(url_ctx.source_date, "%Y-%m-%d").date()
                    ctx_source_date = datetime.combine(parsed_date, datetime.min.time())
                except ValueError:
                    logger.debug(
                        "Ignoring source_date '%s' (expected YYYY-MM-DD)", url_ctx.source_date
                    )
            if ctx_source_date is None:
                ctx_source_date = source_date

            outcome = process_url(
                url_ctx,
                config,
                client,
                source_note=ctx_note_filename,
                source_date=ctx_source_date,
                progress_cb=progress_cb,
                link_source_note=True,
            )
            results.append(outcome)

            if outcome.should_delete_source and ctx_note_filename:
                if ctx_note_filename not in urls_to_delete:
                    urls_to_delete[ctx_note_filename] = []
                urls_to_delete[ctx_note_filename].append(url_ctx.original_url or url_ctx.url)

        if urls_to_delete and not config.dry_run:
            assert config.vault_path is not None
            for note_filename, urls in urls_to_delete.items():
                for url in urls:
                    try:
                        removed = remove_url_line_from_note(
                            vault_path=config.vault_path,
                            daily_notes_folder=config.daily_notes_folder,
                            note_filename=note_filename,
                            url=url,
                        )
                        if removed:
                            logger.debug("Removed URL line from %s: %s", note_filename, url)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Failed to remove URL line from %s: %s", note_filename, e)

        if interrupted and results:
            logger.info("Processing was interrupted; partial results returned")

        if not results:
            return EXIT_ERROR, results
        failures = sum(1 for r in results if not r.success)
        if failures == len(results):
            return EXIT_ERROR, results
        return EXIT_SUCCESS, results
    finally:
        try:
            close_browser_context()
        except Exception as e:  # noqa: BLE001
            logger.debug("Failed to cleanup browser context: %s", e)
        signal.signal(signal.SIGINT, original_handler)


def resummarize(
    identifier: str,
    config: Config,
    progress_cb: ProgressCallback | None = None,
    metadata: SummaryMetadata | None = None,
) -> ProcessOutcome:
    """Re-summarize an existing summary by slug or URL.

    Args:
        identifier: Slug or URL to re-summarize.
        config: Application configuration.
        progress_cb: Optional progress callback.
        metadata: Pre-fetched SummaryMetadata (avoids duplicate lookup if caller already has it).

    Returns:
        ProcessOutcome with success status and details.
    """
    if metadata is None:
        metadata = find_summary_metadata(identifier, config)
    if not metadata:
        return ProcessOutcome(False, f"No existing summary found for: {identifier}", False)

    source_url = metadata.source_url
    original_date = metadata.original_date
    source_note = metadata.source_note

    try:
        client = create_llm_client(
            model=config.model,
            provider=config.model_provider,
            gemini_api_key=config.gemini_api_key,
            ollama_endpoint=config.ollama_endpoint,
            azure_api_key=config.azure_api_key,
            azure_endpoint=config.azure_endpoint,
            azure_deployment_name=config.azure_deployment_name,
            azure_api_version=config.azure_api_version,
            state_path=config.vault_path,
            yaml_model_limits=config.model_limits,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to create LLM client: %s", e)
        return ProcessOutcome(False, f"Failed to initialize AI model: {e}", False)

    # Reuse process_url logic but avoid linking to daily notes
    url_ctx = UrlWithContext(
        url=source_url,
        original_url=source_url,
        tags=[],
    )

    # Use force_override=True instead of mutating config.force
    return process_url(
        url_ctx,
        config,
        client,
        source_note=source_note,
        source_date=original_date,
        progress_cb=progress_cb,
        link_source_note=False,
        force_override=True,
    )
