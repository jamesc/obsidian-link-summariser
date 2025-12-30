"""
Command-line interface for the Obsidian Link Summarizer.

This module provides the main entry point for the CLI application,
handling argument parsing, command dispatch, and output formatting.
"""

import argparse
import contextlib
import logging
import signal
import sys
from datetime import datetime, timedelta
from typing import Any

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Table

from summarize_links.config import Config, load_config, setup_logging
from summarize_links.exceptions import (
    ConfigError,
    ContentExtractionError,
    ContentFetchError,
    GeminiAPIError,
    ModelNotInstalledError,
    NoteReadError,
    OllamaAPIError,
    OllamaServerError,
    RateLimitError,
    SummarizerError,
    URLValidationError,
)
from summarize_links.extract import fetch_and_extract_metadata
from summarize_links.gemini_client import SummarizerProtocol
from summarize_links.llm_factory import create_llm_client, detect_provider
from summarize_links.models import UrlWithContext
from summarize_links.notes import (
    add_summary_link_to_daily_note,
    extract_urls_with_context,
    find_daily_notes_with_urls,
    get_existing_summary_date,
    read_daily_note,
    remove_url_line_from_note,
    scan_summaries,
    scan_summaries_for_resummarize,
    slug_from_url,
    summary_exists,
    write_stub_note,
    write_summary_note_with_metadata,
)
from summarize_links.rate_limiter import get_rate_limiter

# Module logger
logger = logging.getLogger(__name__)

# Rich console for output
console = Console()

# Global quiet mode flag (set by --quiet argument)
_quiet_mode = False

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
    _print("\n[yellow]⚠ Shutdown requested, finishing current URL...[/]")


def _print(message: Any = "", style: str | None = None, **kwargs: Any) -> None:
    """
    Print to console if not in quiet mode.

    Args:
        message: Message to print (Rich markup supported). Can be string or Rich object.
        style: Optional Rich style to apply.
        **kwargs: Additional arguments passed to console.print().
    """
    if not _quiet_mode:
        if style:
            console.print(message, style=style, **kwargs)
        else:
            console.print(message, **kwargs)


def _print_error(message: str) -> None:
    """
    Print error message (always shown, even in quiet mode).

    Args:
        message: Error message to print (Rich markup supported).
    """
    console.print(message)


# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_CONFIG_ERROR = 2


def create_parser() -> argparse.ArgumentParser:
    """
    Create the argument parser for the CLI.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="summarize-links",
        description="Summarize web links from Obsidian daily notes using AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Summarize links from today's daily note
  summarize-links from-note

  # Summarize links from a specific date
  summarize-links from-note --date 2024-01-15

  # List all daily notes that have URLs
  summarize-links list

  # Summarize specific URLs
  summarize-links urls https://example.com https://another.com

  # Re-summarize all existing summaries
  summarize-links resummarize

  # Re-summarize only summaries older than 30 days
  summarize-links resummarize --age 30

  # Dry run - show what would be done
  summarize-links from-note --dry-run

  # Use mock mode for testing
  summarize-links from-note --mock
""",
    )

    # Global options
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress informational output (errors still shown)",
    )
    parser.add_argument(
        "--vault",
        type=str,
        help="Path to Obsidian vault (overrides config)",
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Gemini model to use (overrides config)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock Gemini client (no API calls)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--max-links",
        type=int,
        help="Maximum number of links to process",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing summaries",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # from-note command
    from_note = subparsers.add_parser(
        "from-note",
        help="Summarize links from a daily note",
        description="Extract and summarize all URLs from a daily note.",
    )
    from_note.add_argument(
        "--date",
        type=str,
        help="Date of the daily note (YYYY-MM-DD format, defaults to today)",
    )
    from_note.add_argument(
        "--all",
        action="store_true",
        dest="process_all",
        help="Process all daily notes that contain URLs",
    )

    # urls command
    urls_cmd = subparsers.add_parser(
        "urls",
        help="Summarize specific URLs",
        description="Summarize one or more specified URLs.",
    )
    urls_cmd.add_argument(
        "urls",
        nargs="+",
        help="URLs to summarize",
    )

    # list command
    subparsers.add_parser(
        "list",
        help="List daily notes with URLs",
        description="List dates of all daily notes that contain URLs.",
    )

    # status command
    subparsers.add_parser(
        "status",
        help="Show rate limit status",
        description="Show current Gemini API rate limit usage and remaining quota.",
    )

    # summaries command
    subparsers.add_parser(
        "summaries",
        help="Report on summary status",
        description="Scan all summaries and report on their status (success, mocked, errors).",
    )

    # resummarize command
    resummarize_cmd = subparsers.add_parser(
        "resummarize",
        help="Re-summarize existing summaries",
        description="Re-summarize all existing summaries from the Summaries folder.",
    )
    resummarize_cmd.add_argument(
        "--age",
        type=int,
        metavar="DAYS",
        help="Only resummarize summaries older than DAYS days (based on generation date)",
    )

    return parser


def _process_url_with_metadata(
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


def cmd_from_note(config: Config, date_str: str | None = None) -> int:
    """
    Process URLs from a daily note.

    Args:
        config: Application configuration.
        date_str: Optional date string (YYYY-MM-DD).

    Returns:
        Exit code.
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    # Determine the date
    if date_str:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            _print_error(f"[red]Invalid date format: {date_str}[/]")
            _print_error("Use YYYY-MM-DD format (e.g., 2024-01-15)")
            return EXIT_ERROR
    else:
        date = datetime.now().date()

    _print(f"[bold]Processing daily note for: {date}[/]")

    # Read the daily note
    try:
        # Daily note filename is based on date format (YYYY-MM-DD.md)
        note_filename = f"{date.strftime('%Y-%m-%d')}.md"
        note_content = read_daily_note(
            vault_path=config.vault_path,
            note_path=note_filename,
            daily_notes_folder=config.daily_notes_folder,
        )
    except NoteReadError as e:
        _print_error(f"[red]Error reading daily note: {e}[/]")
        return EXIT_ERROR

    # Extract URLs with context (user tags from daily note)
    url_contexts = extract_urls_with_context(note_content)
    if not url_contexts:
        _print("[yellow]No URLs found in daily note.[/]")
        return EXIT_SUCCESS

    # Apply max_links limit
    if config.max_links and len(url_contexts) > config.max_links:
        _print(f"[yellow]Found {len(url_contexts)} URLs, limiting to {config.max_links}[/]")
        url_contexts = url_contexts[: config.max_links]
    else:
        _print(f"[green]Found {len(url_contexts)} URLs to process[/]")

    # Process URLs with rich metadata pipeline
    # Convert date to datetime for the processing functions
    source_datetime = datetime.combine(date, datetime.min.time())
    return _process_urls_with_metadata(
        url_contexts, config, daily_note_filename=note_filename, source_date=source_datetime
    )


def cmd_from_note_all(config: Config) -> int:
    """
    Process URLs from all daily notes that contain URLs.

    Iterates through all daily notes with URLs (oldest first) and processes
    each one in sequence, respecting the max_links limit across all notes.

    Args:
        config: Application configuration.

    Returns:
        Exit code.
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    _print("[bold]Finding all daily notes with URLs...[/]")

    # Find all daily notes with URLs (returns newest first, we want oldest first)
    notes_with_urls = find_daily_notes_with_urls(
        vault_path=config.vault_path,
        daily_notes_folder=config.daily_notes_folder,
    )

    if not notes_with_urls:
        _print("[yellow]No daily notes with URLs found.[/]")
        return EXIT_SUCCESS

    # Reverse to process oldest first (chronological order)
    notes_with_urls = list(reversed(notes_with_urls))

    total_urls = sum(count for _, count in notes_with_urls)
    _print(f"[green]Found {len(notes_with_urls)} daily notes with {total_urls} total URLs[/]")

    # Track overall progress
    processed_count = 0
    overall_failures = 0
    notes_processed = 0

    for date_str, url_count in notes_with_urls:
        # Check if we've hit the max_links limit
        if config.max_links and processed_count >= config.max_links:
            remaining_notes = len(notes_with_urls) - notes_processed
            _print(
                f"[yellow]Reached max_links limit ({config.max_links}). "
                f"Skipping remaining {remaining_notes} notes.[/]"
            )
            break

        _print(f"\n[bold cyan]Processing: {date_str} ({url_count} URLs)[/]")

        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            _print_error(f"[red]Invalid date format: {date_str}, skipping[/]")
            continue

        # Read the daily note
        note_filename = f"{date_str}.md"
        try:
            note_content = read_daily_note(
                vault_path=config.vault_path,
                note_path=note_filename,
                daily_notes_folder=config.daily_notes_folder,
            )
        except NoteReadError as e:
            _print_error(f"[red]Error reading daily note {date_str}: {e}[/]")
            overall_failures += url_count
            notes_processed += 1
            continue

        # Extract URLs with context
        url_contexts = extract_urls_with_context(note_content)
        if not url_contexts:
            _print(f"[yellow]No URLs found in {date_str} (may have been processed)[/]")
            notes_processed += 1
            continue

        # Apply remaining max_links budget for this note
        if config.max_links:
            remaining_budget = config.max_links - processed_count
            if len(url_contexts) > remaining_budget:
                _print(f"[yellow]Limiting to {remaining_budget} URLs (max_links budget)[/]")
                url_contexts = url_contexts[:remaining_budget]

        # Process this note's URLs
        source_datetime = datetime.combine(date, datetime.min.time())
        exit_code = _process_urls_with_metadata(
            url_contexts, config, daily_note_filename=note_filename, source_date=source_datetime
        )

        processed_count += len(url_contexts)
        notes_processed += 1

        if exit_code == EXIT_ERROR:
            overall_failures += len(url_contexts)

    # Final summary
    _print("\n" + "=" * 50)
    _print(f"[bold]Completed processing {notes_processed} daily notes[/]")
    _print(f"[bold]Total URLs processed: {processed_count}[/]")

    if overall_failures > 0:
        return EXIT_ERROR
    return EXIT_SUCCESS


def cmd_list(config: Config) -> int:
    """
    List all daily notes that contain URLs.

    Args:
        config: Application configuration.

    Returns:
        Exit code.
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    _print("[bold]Scanning daily notes for URLs...[/]")

    # Find all daily notes with URLs
    notes_with_urls = find_daily_notes_with_urls(
        vault_path=config.vault_path,
        daily_notes_folder=config.daily_notes_folder,
    )

    if not notes_with_urls:
        _print("[yellow]No daily notes with URLs found.[/]")
        return EXIT_SUCCESS

    # Display results in a table
    table = Table(title="Daily Notes with URLs")
    table.add_column("Date", style="cyan")
    table.add_column("URLs", style="green", justify="right")

    total_urls = 0
    for date_str, url_count in notes_with_urls:
        table.add_row(date_str, str(url_count))
        total_urls += url_count

    _print(table)
    _print()
    _print(f"[bold]Total:[/] {len(notes_with_urls)} notes with {total_urls} URLs")

    return EXIT_SUCCESS


def cmd_status(config: Config) -> int:
    """
    Show current provider and rate limit status.

    Args:
        config: Application configuration.

    Returns:
        Exit code.
    """
    # Detect provider from model name
    provider = detect_provider(config.model)

    _print("[bold]LLM Provider Status[/]\n")
    _print(f"[bold]Provider:[/] {provider.upper()}")
    _print(f"[bold]Model:[/] {config.model}\n")

    if provider == "ollama":
        _print(f"[bold]Endpoint:[/] {config.ollama_endpoint}")
        _print("[cyan]✓ No rate limiting for local models[/]")
        _print()
        return EXIT_SUCCESS

    # For Gemini, show rate limit information
    # Initialize rate limiter with vault path and configured limits
    rate_limiter = get_rate_limiter(
        state_path=config.vault_path,
        rpm_limit=config.rpm_limit,
        tpm_limit=config.tpm_limit,
        daily_limit=config.daily_limit,
    )
    status = rate_limiter.get_status()

    _print("[bold]Gemini API Rate Limit Status[/]\n")

    # Display rate limit information in a table
    table = Table(title="Current Usage")
    table.add_column("Limit Type", style="cyan")
    table.add_column("Used", style="yellow", justify="right")
    table.add_column("Limit", style="white", justify="right")
    table.add_column("Remaining", style="green", justify="right")

    table.add_row(
        "Requests/Minute (RPM)",
        str(status["rpm"]["current"]),
        str(status["rpm"]["limit"]),
        str(status["rpm"]["remaining"]),
    )
    table.add_row(
        "Tokens/Minute (TPM)",
        f"{status['tpm']['current']:,}",
        f"{status['tpm']['limit']:,}",
        f"{status['tpm']['remaining']:,}",
    )
    table.add_row(
        "Requests/Day",
        str(status["daily"]["current"]),
        str(status["daily"]["limit"]),
        str(status["daily"]["remaining"]),
    )

    _print(table)
    _print()

    # Warnings if approaching limits
    if status["daily"]["remaining"] < 50:
        _print(
            f"[yellow]⚠ Warning: Only {status['daily']['remaining']} daily requests remaining![/]"
        )
    if status["daily"]["remaining"] == 0:
        _print_error("[red]✗ Daily limit reached. Try again tomorrow.[/]")

    return EXIT_SUCCESS


def cmd_summaries(config: Config) -> int:
    """
    Report on summary status.

    Scans all summaries and displays statistics including
    successful, mocked, and error summaries.

    Args:
        config: Application configuration.

    Returns:
        Exit code.
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    _print("[bold]Scanning summaries...[/]\n")

    # Scan all summaries
    stats = scan_summaries(
        vault_path=config.vault_path,
        out_folder=config.out_folder,
    )

    if stats["total"] == 0:
        _print("[yellow]No summaries found.[/]")
        _print(f"Summaries folder: {config.vault_path / config.out_folder}")
        return EXIT_SUCCESS

    # Display overall statistics
    _print("[bold]Summary Statistics[/]\n")

    summary_table = Table(title="Overall Status")
    summary_table.add_column("Category", style="cyan")
    summary_table.add_column("Count", style="white", justify="right")
    summary_table.add_column("Percentage", style="green", justify="right")

    total = stats["total"]
    summary_table.add_row(
        "Total Summaries",
        str(total),
        "100%",
    )
    summary_table.add_row(
        "✓ Successful",
        str(stats["success"]),
        f"{stats['success'] * 100 // total}%" if total > 0 else "0%",
    )
    summary_table.add_row(
        "⚠ Mocked (needs real API)",
        str(stats["mocked"]),
        f"{stats['mocked'] * 100 // total}%" if total > 0 else "0%",
    )
    summary_table.add_row(
        "✗ Errors (failed)",
        str(stats["error"]),
        f"{stats['error'] * 100 // total}%" if total > 0 else "0%",
    )
    if stats["unknown"] > 0:
        summary_table.add_row(
            "? Unknown",
            str(stats["unknown"]),
            f"{stats['unknown'] * 100 // total}%" if total > 0 else "0%",
        )

    _print(summary_table)
    _print()

    # Display date range
    if stats["oldest_date"] and stats["newest_date"]:
        _print(f"[cyan]Date range:[/] {stats['oldest_date']} to {stats['newest_date']}")
        _print()

    # Display mocked summaries if any
    if stats["mocked"] > 0:
        _print("[yellow]⚠ Mocked Summaries (run without --mock to regenerate):[/]")
        mocked_table = Table(show_header=True)
        mocked_table.add_column("File", style="cyan")
        mocked_table.add_column("Date", style="white")

        for filename, date in stats["mocked_summaries"][:10]:  # Show first 10
            mocked_table.add_row(filename, date)

        if len(stats["mocked_summaries"]) > 10:
            mocked_table.add_row(
                f"... and {len(stats['mocked_summaries']) - 10} more",
                "",
            )

        _print(mocked_table)
        _print()

    # Display error summaries if any
    if stats["error"] > 0:
        _print("[red]✗ Error Summaries (run with --force to retry):[/]")
        error_table = Table(show_header=True)
        error_table.add_column("File", style="cyan")
        error_table.add_column("Reason", style="yellow")

        for filename, reason in stats["error_summaries"]:  # Show all errors
            error_table.add_row(filename, reason)

        _print(error_table)
        _print()

    # Helpful tips
    if stats["mocked"] > 0 or stats["error"] > 0:
        _print("[bold]Tips:[/]")
        if stats["mocked"] > 0:
            _print(
                "  • Run [cyan]summarize-links from-note --all --force[/] "
                "to regenerate mocked summaries"
            )
        if stats["error"] > 0:
            _print(
                "  • Run [cyan]summarize-links from-note --all --force[/] to retry failed summaries"
            )

    return EXIT_SUCCESS


def cmd_resummarize(config: Config, age_days: int | None = None) -> int:
    """
    Re-summarize existing summaries from the Summaries folder.

    Scans all summaries, extracts their source URLs and dates,
    and reprocesses them using the current model and settings.
    Preserves the original summary date.

    Note: This command automatically enables force mode to overwrite
    existing summaries.

    Args:
        config: Application configuration.
        age_days: Only resummarize summaries older than this many days (optional).

    Returns:
        Exit code.
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    # Enable force mode for resummarize (we always want to overwrite)
    config.force = True

    _print("[bold]Scanning summaries for re-summarization...[/]\n")

    # Find all summaries suitable for resummarization
    summaries = scan_summaries_for_resummarize(
        vault_path=config.vault_path,
        out_folder=config.out_folder,
    )

    # Filter by age if specified (based on summary_date)
    if age_days is not None:
        cutoff_date = datetime.now() - timedelta(days=age_days)
        original_count = len(summaries)
        # Filter based on summary_date (3rd element in tuple)
        summaries = [
            (url, orig_date, summ_date, source_note)
            for url, orig_date, summ_date, source_note in summaries
            if summ_date < cutoff_date
        ]
        filtered_count = original_count - len(summaries)
        if filtered_count > 0:
            _print(f"[cyan]Filtered out {filtered_count} summaries newer than {age_days} days[/]")

    if not summaries:
        _print("[yellow]No summaries found to re-summarize.[/]")
        if age_days is not None:
            _print(f"(No summaries older than {age_days} days)")
        _print(f"Summaries folder: {config.vault_path / config.out_folder}")
        return EXIT_SUCCESS

    # Apply max_links limit
    if config.max_links and len(summaries) > config.max_links:
        _print(f"[yellow]Found {len(summaries)} summaries, limiting to {config.max_links}[/]")
        summaries = summaries[: config.max_links]
    else:
        _print(f"[green]Found {len(summaries)} summaries to re-summarize[/]")

    # Convert to UrlWithContext (no user tags for resummarize)
    url_contexts = [UrlWithContext(url=url) for url, _, _, _ in summaries]

    # Extract original dates and source notes for each URL
    url_dates = {url: orig_date for url, orig_date, _, _ in summaries}
    url_source_notes = {url: source_note for url, _, _, source_note in summaries}

    # Process URLs with the preserved dates and source notes
    return _process_resummarize_batch(url_contexts, url_dates, url_source_notes, config)


def _process_resummarize_batch(
    url_contexts: list[UrlWithContext],
    url_dates: dict[str, datetime],
    url_source_notes: dict[str, str | None],
    config: Config,
) -> int:
    """
    Process a batch of URLs for resummarization.

    Similar to _process_urls_batch but preserves original dates
    and source notes, and doesn't attempt to remove URLs from daily notes.

    Args:
        url_contexts: URLs with context (no user tags for resummarize).
        url_dates: Mapping of URL to its original summary date.
        url_source_notes: Mapping of URL to its source note filename (from 'from' field).
        config: Application configuration.

    Returns:
        Exit code.
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
            rpm_limit=config.rpm_limit,
            tpm_limit=config.tpm_limit,
            daily_limit=config.daily_limit,
        )

        if config.mock_mode:
            _print("[yellow]Running in mock mode (no API calls)[/]")
        if config.dry_run:
            _print("[yellow]Running in dry-run mode (no changes)[/]")

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
                    _print(f"[yellow]Stopping early. {remaining} URLs not processed.[/]")
                    break

                # Get the original date and source note for this URL
                original_date = url_dates.get(url_context.url)
                source_note = url_source_notes.get(url_context.url)

                # Process URL with preserved date and source note (for 'from' field)
                success, message, _ = _process_url_with_metadata(
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

        # Print results table (even for partial results)
        if results:
            _print_results(results)

            # Print summary
            if interrupted:
                _print("[yellow]Processing was interrupted.[/]")

        # Return appropriate exit code
        if not results:
            return EXIT_ERROR
        failures = sum(1 for success, _ in results if not success)
        if failures == len(results):
            return EXIT_ERROR
        return EXIT_SUCCESS

    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)


def cmd_urls(config: Config, urls: list[str]) -> int:
    """
    Process specified URLs.

    Args:
        config: Application configuration.
        urls: List of URLs to process.

    Returns:
        Exit code.
    """
    _print(f"[bold]Processing {len(urls)} URLs[/]")

    # Apply max_links limit
    if config.max_links and len(urls) > config.max_links:
        _print(f"[yellow]Limiting to {config.max_links} URLs (from {len(urls)})[/]")
        urls = urls[: config.max_links]

    # Convert to UrlWithContext (no user tags for direct URL input)
    url_contexts = [UrlWithContext(url=url) for url in urls]

    return _process_urls_with_metadata(url_contexts, config)


def _process_urls_with_metadata(
    url_contexts: list[UrlWithContext],
    config: Config,
    daily_note_filename: str | None = None,
    source_date: datetime | None = None,
) -> int:
    """
    Process a list of URLs with full metadata extraction.

    Supports graceful shutdown - if Ctrl+C is pressed, finishes the current URL
    and reports partial results.

    Args:
        url_contexts: URLs with context (user tags, surrounding text).
        config: Application configuration.
        daily_note_filename: Optional filename of source daily note for back-linking.
        source_date: Optional date from the source daily note (for filename).

    Returns:
        Exit code.
    """
    global _shutdown_requested

    # Reset shutdown flag at start of batch
    _shutdown_requested = False

    # Install signal handler for graceful shutdown
    original_handler = signal.signal(signal.SIGINT, _handle_shutdown)

    try:
        return _process_urls_batch(url_contexts, config, daily_note_filename, source_date)
    finally:
        # Restore original signal handler
        signal.signal(signal.SIGINT, original_handler)


def _process_urls_batch(
    url_contexts: list[UrlWithContext],
    config: Config,
    daily_note_filename: str | None = None,
    source_date: datetime | None = None,
) -> int:
    """
    Internal batch processing implementation.

    Args:
        url_contexts: URLs with context (user tags, surrounding text).
        config: Application configuration.
        daily_note_filename: Optional filename of source daily note for back-linking.
        source_date: Optional date from the source daily note (for filename).

    Returns:
        Exit code.
    """
    # Create the LLM client (auto-detects provider from model name)
    client = create_llm_client(
        model=config.model,
        gemini_api_key=config.gemini_api_key,
        ollama_endpoint=config.ollama_endpoint,
        mock_mode=config.mock_mode,
        state_path=config.vault_path,
        rpm_limit=config.rpm_limit,
        tpm_limit=config.tpm_limit,
        daily_limit=config.daily_limit,
    )

    if config.mock_mode:
        _print("[yellow]Running in mock mode (no API calls)[/]")
    if config.dry_run:
        _print("[yellow]Running in dry-run mode (no changes)[/]")

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
                _print(f"[yellow]Stopping early. {remaining} URLs not processed.[/]")
                break

            success, message, should_delete = _process_url_with_metadata(
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
        _print(f"[cyan]Cleaning up {len(urls_to_delete)} processed URLs from daily note...[/]")
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

    # Print results table (even for partial results)
    if results:
        _print_results(results)

        # Print summary
        if interrupted:
            _print("[yellow]Processing was interrupted.[/]")

    # Return appropriate exit code
    if not results:
        return EXIT_ERROR
    failures = sum(1 for success, _ in results if not success)
    if failures == len(results):
        return EXIT_ERROR
    return EXIT_SUCCESS


def _print_results(results: list[tuple[bool, str]]) -> None:
    """
    Print a summary table of results.

    Args:
        results: List of (success, message) tuples.
    """
    table = Table(title="Processing Results")
    table.add_column("Status", style="bold")
    table.add_column("Details")

    for success, message in results:
        status = "[green]✓[/]" if success else "[red]✗[/]"
        table.add_row(status, message)

    _print(table)

    # Print summary
    total = len(results)
    successes = sum(1 for success, _ in results if success)
    failures = total - successes

    _print()
    _print(f"[bold]Summary:[/] {successes} succeeded, {failures} failed out of {total}")


def main(argv: list[str] | None = None) -> int:
    """
    Main entry point for the CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code.
    """
    global _quiet_mode

    parser = create_parser()
    args = parser.parse_args(argv)

    # Set quiet mode from args
    _quiet_mode = getattr(args, "quiet", False)

    # Show help if no command specified
    if not args.command:
        parser.print_help()
        return EXIT_SUCCESS

    # Setup logging (Rich handler for verbose mode)
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(message)s",
            handlers=[RichHandler(console=console, rich_tracebacks=True)],
        )
    else:
        logging.basicConfig(level=logging.WARNING)

    try:
        # Load configuration with CLI overrides
        config = load_config(
            vault_path=args.vault,
            model=args.model,
            max_links=args.max_links,
            mock_mode=args.mock,
            dry_run=args.dry_run,
            verbose=args.verbose,
            force=args.force,
        )
        setup_logging(config.verbose)

        # Initialize Langfuse tracer if configured
        from summarize_links.langfuse_tracer import initialize_tracer

        initialize_tracer(config)

        # Dispatch to command handler
        if args.command == "from-note":
            if getattr(args, "process_all", False):
                return cmd_from_note_all(config)
            return cmd_from_note(config, getattr(args, "date", None))
        elif args.command == "urls":
            return cmd_urls(config, args.urls)
        elif args.command == "list":
            return cmd_list(config)
        elif args.command == "status":
            return cmd_status(config)
        elif args.command == "summaries":
            return cmd_summaries(config)
        elif args.command == "resummarize":
            return cmd_resummarize(config, age_days=getattr(args, "age", None))
        else:
            _print_error(f"[red]Unknown command: {args.command}[/]")
            return EXIT_ERROR

    except ConfigError as e:
        _print_error(f"[red]Configuration error: {e}[/]")
        return EXIT_CONFIG_ERROR

    except OllamaServerError as e:
        _print_error("[red]Ollama server not available![/]")
        _print_error("[yellow]To start Ollama:[/]")
        _print_error("  • Start the Ollama app, or")
        _print_error("  • Run: ollama serve")
        _print_error(f"\n[red]Error:[/] {e}")
        return EXIT_ERROR

    except ModelNotInstalledError as e:
        _print_error("[red]Ollama model not installed![/]")
        _print_error(f"\n[red]Error:[/] {e}")
        return EXIT_ERROR

    except SummarizerError as e:
        _print_error(f"[red]Error: {e}[/]")
        return EXIT_ERROR

    except KeyboardInterrupt:
        _print_error("\n[yellow]Interrupted by user[/]")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
