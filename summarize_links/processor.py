"""
URL processing logic for the Obsidian Link Summarizer.

This module handles the core processing logic for URLs including:
- Single URL processing with metadata extraction
- Batch processing with progress tracking  - Error handling and retry logic
- Signal handling for graceful shutdown
"""

import contextlib
import logging
import signal
from datetime import datetime
from typing import Any

from rich.progress import Progress, SpinnerColumn, TaskID, TextColumn

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
from summarize_links.llm import SummarizerProtocol, create_llm_client
from summarize_links.models import UrlWithContext
from summarize_links.notes import (
    add_summary_link_to_daily_note,
    get_existing_summary_date,
    remove_url_line_from_note,
    slug_from_url,
    summary_exists,
    write_stub_note,
    write_summary_note_with_metadata,
)
from summarize_links.ui import console, print_message

# Module logger
logger = logging.getLogger(__name__)

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1

# Global shutdown flag for graceful interruption
_shutdown_requested = False


def _handle_shutdown(signum: int, frame: object) -> None:
    """
    Handle shutdown signal (Ctrl+C / SIGINT).

    Sets a flag that is checked between URL processing to allow
    graceful completion of current work and partial result reporting.

    Args:
        signum: Signal number.
        frame: Current stack frame (unused).
    """
    global _shutdown_requested
    _shutdown_requested = True
    print_message("\n[yellow]⚠ Shutdown requested, finishing current URL...[/]")


def process_url_with_metadata(
    url_context: UrlWithContext,
    config: Config,
    client: SummarizerProtocol,
    progress: Progress | None = None,
    task_id: TaskID | None = None,
    daily_note_filename: str | None = None,
    source_date: datetime | None = None,
) -> tuple[bool, str, bool]:
    """
    Process a single URL with full metadata extraction and enriched frontmatter.

    This version uses the new metadata pipeline to generate rich frontmatter
    including author, tags from multiple sources, and content type.

    Args:
        url_context: URL with context (user tags, surrounding text).
        config: Application configuration.
        client: Gemini client instance implementing SummarizerProtocol.
        progress: Optional progress instance for updates.
        task_id: Optional task ID for progress updates.
        daily_note_filename: Optional filename of source daily note for back-linking.
        source_date: Optional date from the source daily note (for filename).

    Returns:
        Tuple of (success, message, should_delete_source).
        should_delete_source is True only when a new summary was created
        (not skipped, not dry-run, not error).
    """
    # Get tracer and propagate_attributes for Langfuse tracing
    from summarize_links.langfuse_tracer import get_tracer, propagate_attributes

    tracer = get_tracer()

    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    url = url_context.url
    slug = slug_from_url(url)

    # Check if summary already exists and get its date if it does
    # This allows us to preserve the original date when re-summarizing
    existing_date = get_existing_summary_date(config.vault_path, config.out_folder, url)

    # If an existing summary was found, use its date instead of source_date
    # This preserves the original date when re-summarizing
    if existing_date:
        summary_date = existing_date
        logger.debug(f"Using existing summary date: {existing_date.strftime('%Y-%m-%d')}")
    elif source_date:
        summary_date = source_date
    else:
        # No existing date and no source date - use current date
        summary_date = datetime.now()

    # Check if summary already exists (skip check if force is enabled)
    # summary_exists returns False for mocked/error stubs, so they get reprocessed
    existing_summary_complete = summary_exists(
        config.vault_path, config.out_folder, url, summary_date
    )
    if not config.force and existing_summary_complete:
        return True, f"Skipped (exists): {slug}", False

    # If we're reprocessing (summary exists but incomplete), we need to overwrite
    needs_overwrite = config.force or not existing_summary_complete

    # Store whether we had a successful summary before processing
    # Used to prevent overwriting successful summaries with error stubs
    had_successful_summary = existing_summary_complete

    if config.dry_run:
        return True, f"Would process: {url} -> {slug}.md", False

    # Create a trace for this URL processing with propagated attributes
    with tracer.trace_url_processing(
        url=url,
        name=slug,  # Include slug in trace name for easy filtering in Langfuse UI
        metadata={
            "slug": slug,
            "source_note": daily_note_filename,
            "user_tags": url_context.tags,
        },
    ) as trace:
        # Use propagate_attributes to set trace-level metadata for all observations
        with propagate_attributes(
            session_id=daily_note_filename or "direct-url",
            tags=[
                "production" if not config.mock_mode else "mock",
                config.model.split(":")[0] if ":" in config.model else config.model,
            ],
            metadata={
                "vault": str(config.vault_path),
                "provider": "gemini" if config.model.startswith("gemini") else "ollama",
            },
        ):
            try:
                # Fetch and extract content with metadata
                if progress and task_id is not None:
                    progress.update(task_id, description=f"[cyan]Fetching: {url[:50]}...")

                with tracer.trace_span(
                    name="fetch",
                    input_data={"url": url},
                ) as fetch_span:
                    page_metadata = fetch_and_extract_metadata(url)

                    # Update fetch span with extracted metadata
                    if fetch_span and hasattr(fetch_span, "update"):
                        with contextlib.suppress(Exception):
                            fetch_span.update(
                                output={
                                    "title": page_metadata.title,
                                    "domain": page_metadata.domain,
                                    "content_length": len(page_metadata.content),
                                    "has_author": page_metadata.author is not None,
                                    "has_published_date": page_metadata.published_date is not None,
                                    "article_tags_count": len(page_metadata.article_tags),
                                },
                                metadata={
                                    "author": page_metadata.author,
                                    "site_name": page_metadata.site_name,
                                    "published_date": page_metadata.published_date,
                                    "description": page_metadata.description[:200]
                                    if page_metadata.description
                                    else None,
                                    "article_tags": page_metadata.article_tags[:10],
                                },
                            )

                # Generate summary with structured output
                if progress and task_id is not None:
                    progress.update(task_id, description=f"[cyan]Summarizing: {slug}...")

                # Create generation observation (input/output will be set via update())
                with tracer.trace_generation(
                    name="summarize",
                    model=config.model,
                ) as generation:
                    try:
                        summary_result = client.summarize_with_metadata(
                            content=page_metadata.content,
                            url=url,
                            title=page_metadata.title,
                        )

                        # Update generation with raw LLM input/output and usage details
                        if generation and hasattr(generation, "update"):
                            with contextlib.suppress(Exception):
                                update_data: dict[str, Any] = {}

                                # Send both system and user prompts as input (full LLM context)
                                if summary_result.system_prompt and summary_result.raw_prompt:
                                    update_data["input"] = {
                                        "system": summary_result.system_prompt,
                                        "prompt": summary_result.raw_prompt,
                                    }
                                elif summary_result.raw_prompt:
                                    update_data["input"] = summary_result.raw_prompt

                                # Send raw response as output (actual LLM response)
                                if summary_result.raw_response:
                                    update_data["output"] = summary_result.raw_response

                                # Add metadata about the parsed result
                                update_data["metadata"] = {
                                    "url": url,
                                    "title": page_metadata.title,
                                    "content_length": len(page_metadata.content),
                                    "parsed_tags": summary_result.suggested_tags,
                                    "parsed_content_type": summary_result.content_type,
                                    "summary_length": len(summary_result.content),
                                }

                                # Add usage details if available
                                if summary_result.usage_details:
                                    update_data["usage_details"] = summary_result.usage_details

                                generation.update(**update_data)

                    except (GeminiAPIError, OllamaAPIError, RateLimitError) as e:
                        # Track errors in the generation observation
                        if generation and hasattr(generation, "update"):
                            with contextlib.suppress(Exception):
                                generation.update(
                                    level="ERROR",
                                    status_message=str(e),
                                    metadata={
                                        "error_type": type(e).__name__,
                                        "url": url,
                                    },
                                )
                        raise

                # Determine status based on mock mode
                summary_status = "mocked" if config.mock_mode else "success"

                # Calculate final merged tags (needed for both write span and trace output)
                from summarize_links.models import merge_tags

                final_tags = merge_tags(
                    user_tags=url_context.tags or [],
                    article_tags=page_metadata.article_tags,
                    ai_tags=summary_result.suggested_tags,
                    default_tags=config.default_tags,
                )

                # Write the summary note with rich frontmatter
                # Use needs_overwrite to ensure mocked/error stubs get replaced
                # Use summary_date to preserve original date when re-summarizing
                with tracer.trace_span(
                    name="write",
                    input_data={"slug": slug, "summary_status": summary_status},
                ) as write_span:
                    summary_path = write_summary_note_with_metadata(
                        vault_path=config.vault_path,
                        out_folder=config.out_folder,
                        url=url,
                        summary_result=summary_result,
                        page_metadata=page_metadata,
                        user_tags=url_context.tags,
                        date=summary_date,
                        source_note=daily_note_filename,
                        default_tags=config.default_tags,
                        overwrite=needs_overwrite,
                        summary_status=summary_status,
                        summary_model=config.model,
                        summary_date=datetime.now(),
                    )

                    # Capture write operation metadata
                    if write_span and hasattr(write_span, "update"):
                        with contextlib.suppress(Exception):
                            write_span.update(
                                output={
                                    "filepath": str(summary_path),
                                    "filename": summary_path.name,
                                    "overwritten": needs_overwrite,
                                    "final_tag_count": len(final_tags),
                                    "has_source_note_link": daily_note_filename is not None,
                                },
                                metadata={
                                    "user_tags": url_context.tags or [],
                                    "article_tags": page_metadata.article_tags[:5],
                                    "ai_tags": summary_result.suggested_tags,
                                    "final_tags": final_tags,
                                    "content_type": summary_result.content_type,
                                    "summary_model": config.model,
                                    "date": summary_date.strftime("%Y-%m-%d"),
                                },
                            )

                    # Add link to daily note if we have the source note filename
                    if daily_note_filename:
                        # Use original_url for finding the URL in the note
                        # (cleaned URL may differ due to normalization like ?key vs ?key=)
                        lookup_url = url_context.original_url or url
                        add_summary_link_to_daily_note(
                            vault_path=config.vault_path,
                            daily_notes_folder=config.daily_notes_folder,
                            note_filename=daily_note_filename,
                            summary_path=summary_path,
                            url=lookup_url,
                        )

                # Update trace with final input/output for visibility in Langfuse UI
                if trace and hasattr(trace, "update"):
                    with contextlib.suppress(Exception):
                        trace.update(
                            input=url,
                            output=summary_result.content,
                            metadata={
                                "success": True,
                                "slug": slug,
                                "user_tags": url_context.tags or [],
                                "source_note": daily_note_filename,
                                "summary_path": str(summary_path),
                                "summary_status": summary_status,
                                "filename": summary_path.name,
                                "title": page_metadata.title,
                                "content_type": summary_result.content_type,
                                "final_tags": final_tags,
                            },
                        )

                # Signal that this URL was successfully processed and should be deleted from source
                # Don't delete for mock mode - those summaries will be regenerated later
                should_delete = not config.mock_mode
                return True, f"Created: {slug}.md", should_delete

            except URLValidationError as e:
                logger.warning("Invalid URL %s: %s", url, e)
                # Don't create stub notes for invalid URLs - they can never succeed
                return False, f"Invalid URL: {url}", False

            except ContentFetchError as e:
                logger.warning("Failed to fetch %s: %s", url, e)
                # Only write error stub if we didn't have a successful summary before
                if not config.dry_run and not had_successful_summary:
                    write_stub_note(
                        vault_path=config.vault_path,
                        out_folder=config.out_folder,
                        url=url,
                        reason=f"Failed to fetch: {e}",
                        date=summary_date,
                        error_type="fetch_error",
                    )
                return False, f"Fetch error: {url}", False

            except ContentExtractionError as e:
                logger.warning("Failed to extract content from %s: %s", url, e)
                # Only write error stub if we didn't have a successful summary before
                if not config.dry_run and not had_successful_summary:
                    write_stub_note(
                        vault_path=config.vault_path,
                        out_folder=config.out_folder,
                        url=url,
                        reason=f"Failed to extract content: {e}",
                        date=summary_date,
                        error_type="extraction_error",
                    )
                return False, f"Extraction error: {url}", False

            except RateLimitError as e:
                logger.error("Rate limited while processing %s: %s", url, e)
                # Only write error stub if we didn't have a successful summary before
                if not config.dry_run and not had_successful_summary:
                    write_stub_note(
                        vault_path=config.vault_path,
                        out_folder=config.out_folder,
                        url=url,
                        reason="Rate limited - try again later",
                        date=summary_date,
                        error_type="rate_limit_error",
                    )
                return False, f"[Rate limited] {url}", False

            except OllamaServerError as e:
                logger.error("Ollama server error for %s: %s", url, e)
                # Only write error stub if we didn't have a successful summary before
                if not config.dry_run and not had_successful_summary:
                    write_stub_note(
                        vault_path=config.vault_path,
                        out_folder=config.out_folder,
                        url=url,
                        reason=f"Ollama server unavailable: {e}",
                        date=summary_date,
                        error_type="ollama_error",
                    )
                return False, f"Ollama server error: {url}", False

            except ModelNotInstalledError as e:
                logger.error("Model not installed for %s: %s", url, e)
                # Only write error stub if we didn't have a successful summary before
                if not config.dry_run and not had_successful_summary:
                    write_stub_note(
                        vault_path=config.vault_path,
                        out_folder=config.out_folder,
                        url=url,
                        reason=f"Model not installed: {e}",
                        date=summary_date,
                        error_type="model_error",
                    )
                return False, f"Model not installed: {url}", False

            except OllamaAPIError as e:
                logger.error("Ollama API error for %s: %s", url, e)
                # Only write error stub if we didn't have a successful summary before
                if not config.dry_run and not had_successful_summary:
                    write_stub_note(
                        vault_path=config.vault_path,
                        out_folder=config.out_folder,
                        url=url,
                        reason=f"Ollama API error: {e}",
                        date=summary_date,
                        error_type="ollama_error",
                    )
                return False, f"Ollama API error: {url}", False

            except GeminiAPIError as e:
                logger.error("Gemini API error for %s: %s", url, e)
                # Only write error stub if we didn't have a successful summary before
                if not config.dry_run and not had_successful_summary:
                    write_stub_note(
                        vault_path=config.vault_path,
                        out_folder=config.out_folder,
                        url=url,
                        reason=f"API error: {e}",
                        date=summary_date,
                        error_type="api_error",
                    )
                return False, f"API error: {url}", False


def process_urls_batch(
    url_contexts: list[UrlWithContext],
    config: Config,
    daily_note_filename: str | None = None,
    source_date: datetime | None = None,
) -> tuple[int, list[tuple[bool, str]]]:
    """
    Process a batch of URLs with full metadata extraction.

    Supports graceful shutdown - if Ctrl+C is pressed, finishes the current URL
    and reports partial results.

    Args:
        url_contexts: URLs with context (user tags, surrounding text).
        config: Application configuration.
        daily_note_filename: Optional filename of source daily note for back-linking.
        source_date: Optional date from the source daily note (for filename).

    Returns:
        Tuple of (exit_code, results).
    """
    global _shutdown_requested

    # Reset shutdown flag at start of batch
    _shutdown_requested = False

    # Install signal handler for graceful shutdown
    original_handler = signal.signal(signal.SIGINT, _handle_shutdown)

    try:
        # Create the LLM client (auto-detects provider from model name)
        client = create_llm_client(
            model=config.model,
            gemini_api_key=config.gemini_api_key,
            ollama_endpoint=config.ollama_endpoint,
            mock_mode=config.mock_mode,
            state_path=config.vault_path,
            langfuse_enabled=config.langfuse_enabled,
            rpm_limit=config.rpm_limit,
            tpm_limit=config.tpm_limit,
            daily_limit=config.daily_limit,
        )

        if config.mock_mode:
            print_message("[yellow]Running in mock mode (no API calls)[/]")
        if config.dry_run:
            print_message("[yellow]Running in dry-run mode (no changes)[/]")

        # Process with progress bar
        results: list[tuple[bool, str]] = []
        urls_to_delete: list[str] = []  # Track URLs that were successfully processed
        interrupted = False

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Processing...", total=len(url_contexts))

            for url_context in url_contexts:
                # Check for shutdown request before processing each URL
                if _shutdown_requested:
                    interrupted = True
                    remaining = len(url_contexts) - len(results)
                    print_message(f"[yellow]Stopping early. {remaining} URLs not processed.[/]")
                    break

                success, message, should_delete = process_url_with_metadata(
                    url_context, config, client, progress, task, daily_note_filename, source_date
                )
                results.append((success, message))

                # Track URLs that were newly processed (not skipped, not errors)
                if should_delete:
                    # Store original_url for removal (cleaned URL may not match note)
                    urls_to_delete.append(url_context.original_url or url_context.url)

                progress.advance(task)

        # Delete processed URL lines from the daily note
        # Only if we have a source note and are not in dry-run mode
        if daily_note_filename and urls_to_delete and not config.dry_run:
            assert config.vault_path is not None
            print_message(
                f"[cyan]Cleaning up {len(urls_to_delete)} processed URLs from daily note...[/]"
            )
            for url in urls_to_delete:
                try:
                    removed = remove_url_line_from_note(
                        vault_path=config.vault_path,
                        daily_notes_folder=config.daily_notes_folder,
                        note_filename=daily_note_filename,
                        url=url,
                    )
                    if removed:
                        logger.debug(f"Removed URL line from daily note: {url}")
                except Exception as e:
                    logger.warning(f"Failed to remove URL line from daily note: {e}")

        # Print summary if interrupted
        if interrupted and results:
            print_message("[yellow]Processing was interrupted.[/]")

        # Determine exit code
        if not results:
            return EXIT_ERROR, results
        failures = sum(1 for success, _ in results if not success)
        if failures == len(results):
            return EXIT_ERROR, results
        return EXIT_SUCCESS, results

    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)


def process_resummarize_batch(
    url_contexts: list[UrlWithContext],
    url_dates: dict[str, datetime],
    url_source_notes: dict[str, str | None],
    config: Config,
) -> tuple[int, list[tuple[bool, str]]]:
    """
    Process a batch of URLs for resummarization.

    Similar to process_urls_batch but preserves original dates
    and source notes, and doesn't attempt to remove URLs from daily notes.

    Args:
        url_contexts: URLs with context (no user tags for resummarize).
        url_dates: Mapping of URL to its original summary date.
        url_source_notes: Mapping of URL to its source note filename (from 'from' field).
        config: Application configuration.

    Returns:
        Tuple of (exit_code, results).
    """
    global _shutdown_requested

    # Reset shutdown flag at start of batch
    _shutdown_requested = False

    # Install signal handler for graceful shutdown
    original_handler = signal.signal(signal.SIGINT, _handle_shutdown)

    try:
        # Create the LLM client
        client = create_llm_client(
            model=config.model,
            gemini_api_key=config.gemini_api_key,
            ollama_endpoint=config.ollama_endpoint,
            mock_mode=config.mock_mode,
            state_path=config.vault_path,
            langfuse_enabled=config.langfuse_enabled,
            rpm_limit=config.rpm_limit,
            tpm_limit=config.tpm_limit,
            daily_limit=config.daily_limit,
        )

        if config.mock_mode:
            print_message("[yellow]Running in mock mode (no API calls)[/]")
        if config.dry_run:
            print_message("[yellow]Running in dry-run mode (no changes)[/]")

        # Process with progress bar
        results: list[tuple[bool, str]] = []
        interrupted = False

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Re-summarizing...", total=len(url_contexts))

            for url_context in url_contexts:
                # Check for shutdown request before processing each URL
                if _shutdown_requested:
                    interrupted = True
                    remaining = len(url_contexts) - len(results)
                    print_message(f"[yellow]Stopping early. {remaining} URLs not processed.[/]")
                    break

                # Get the original date and source note for this URL
                original_date = url_dates.get(url_context.url)
                source_note = url_source_notes.get(url_context.url)

                # Process URL with preserved date and source note (for 'from' field)
                success, message, _ = process_url_with_metadata(
                    url_context,
                    config,
                    client,
                    progress,
                    task,
                    daily_note_filename=source_note,  # Preserve 'from' field
                    source_date=original_date,
                )
                results.append((success, message))
                progress.advance(task)

        # Print summary if interrupted
        if interrupted and results:
            print_message("[yellow]Processing was interrupted.[/]")

        # Determine exit code
        if not results:
            return EXIT_ERROR, results
        failures = sum(1 for success, _ in results if not success)
        if failures == len(results):
            return EXIT_ERROR, results
        return EXIT_SUCCESS, results

    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)
