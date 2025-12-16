"""
Command-line interface for the Obsidian Link Summarizer.

This module provides the main entry point for the CLI application,
handling argument parsing, command dispatch, and output formatting.
"""

import argparse
import logging
import sys
from datetime import datetime

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
    NoteReadError,
    RateLimitError,
    SummarizerError,
)
from summarize_links.extract import fetch_and_extract, fetch_and_extract_metadata, truncate_content
from summarize_links.gemini_client import SummarizerProtocol, create_client
from summarize_links.models import UrlWithContext
from summarize_links.notes import (
    add_summary_link_to_daily_note,
    extract_urls_with_context,
    find_daily_notes_with_urls,
    read_daily_note,
    remove_url_line_from_note,
    slug_from_url,
    summary_exists,
    write_stub_note,
    write_summary_note,
    write_summary_note_with_metadata,
)
from summarize_links.rate_limiter import get_rate_limiter

# Module logger
logger = logging.getLogger(__name__)

# Rich console for output
console = Console()

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

    return parser


def _process_url(
    url: str,
    config: Config,
    client: SummarizerProtocol,
    progress: Progress | None = None,
    task_id: TaskID | None = None,
    daily_note_filename: str | None = None,
    source_date: datetime | None = None,
) -> tuple[bool, str]:
    """
    Process a single URL: fetch, extract, summarize, write.

    Args:
        url: URL to process.
        config: Application configuration.
        client: Gemini client instance implementing SummarizerProtocol.
        progress: Optional progress instance for updates.
        task_id: Optional task ID for progress updates.
        daily_note_filename: Optional filename of source daily note for back-linking.
        source_date: Optional date from the source daily note (for filename).

    Returns:
        Tuple of (success, message).
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    slug = slug_from_url(url)

    # Check if summary already exists (skip check if force is enabled)
    if not config.force and summary_exists(config.vault_path, config.out_folder, url, source_date):
        return True, f"Skipped (exists): {slug}"

    if config.dry_run:
        return True, f"Would process: {url} -> {slug}.md"

    try:
        # Fetch and extract content
        if progress and task_id is not None:
            progress.update(task_id, description=f"[cyan]Fetching: {url[:50]}...")

        content, title = fetch_and_extract(url)
        content = truncate_content(content)

        # Generate summary
        if progress and task_id is not None:
            progress.update(task_id, description=f"[cyan]Summarizing: {slug}...")

        # Generate AI summary
        summary = client.summarize(content, url, title)

        # Write the summary note
        summary_path = write_summary_note(
            vault_path=config.vault_path,
            out_folder=config.out_folder,
            url=url,
            content=summary,
            date=source_date,
            overwrite=config.force,
        )

        # Add link to daily note if we have the source note filename
        if daily_note_filename:
            add_summary_link_to_daily_note(
                vault_path=config.vault_path,
                daily_notes_folder=config.daily_notes_folder,
                note_filename=daily_note_filename,
                summary_path=summary_path,
                url=url,
            )

        return True, f"Created: {slug}.md"

    except ContentFetchError as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        if not config.dry_run:
            write_stub_note(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                reason=f"Failed to fetch: {e}",
                date=source_date,
            )
        return False, f"Fetch error: {url}"

    except ContentExtractionError as e:
        logger.warning("Failed to extract content from %s: %s", url, e)
        if not config.dry_run:
            write_stub_note(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                reason=f"Failed to extract content: {e}",
                date=source_date,
            )
        return False, f"Extraction error: {url}"

    except RateLimitError as e:
        logger.error("Rate limited while processing %s: %s", url, e)
        if not config.dry_run:
            write_stub_note(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                reason="Rate limited - try again later",
                date=source_date,
            )
        return False, f"[Rate limited] {url}"

    except GeminiAPIError as e:
        logger.error("Gemini API error for %s: %s", url, e)
        if not config.dry_run:
            write_stub_note(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                reason=f"API error: {e}",
                date=source_date,
            )
        return False, f"API error: {url}"


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
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    url = url_context.url
    slug = slug_from_url(url)

    # Check if summary already exists (skip check if force is enabled)
    # summary_exists returns False for mocked/error stubs, so they get reprocessed
    existing_summary_complete = summary_exists(
        config.vault_path, config.out_folder, url, source_date
    )
    if not config.force and existing_summary_complete:
        return True, f"Skipped (exists): {slug}", False

    # If we're reprocessing (summary exists but incomplete), we need to overwrite
    needs_overwrite = config.force or not existing_summary_complete

    if config.dry_run:
        return True, f"Would process: {url} -> {slug}.md", False

    try:
        # Fetch and extract content with metadata
        if progress and task_id is not None:
            progress.update(task_id, description=f"[cyan]Fetching: {url[:50]}...")

        page_metadata = fetch_and_extract_metadata(url)

        # Generate summary with structured output
        if progress and task_id is not None:
            progress.update(task_id, description=f"[cyan]Summarizing: {slug}...")

        summary_result = client.summarize_with_metadata(
            content=page_metadata.content,
            url=url,
            title=page_metadata.title,
        )

        # Determine status based on mock mode
        status = "mocked" if config.mock_mode else "success"

        # Write the summary note with rich frontmatter
        # Use needs_overwrite to ensure mocked/error stubs get replaced
        summary_path = write_summary_note_with_metadata(
            vault_path=config.vault_path,
            out_folder=config.out_folder,
            url=url,
            summary_result=summary_result,
            page_metadata=page_metadata,
            user_tags=url_context.tags,
            date=source_date,
            source_note=daily_note_filename,
            default_tags=config.default_tags,
            overwrite=needs_overwrite,
            status=status,
        )

        # Add link to daily note if we have the source note filename
        if daily_note_filename:
            add_summary_link_to_daily_note(
                vault_path=config.vault_path,
                daily_notes_folder=config.daily_notes_folder,
                note_filename=daily_note_filename,
                summary_path=summary_path,
                url=url,
            )

        # Signal that this URL was successfully processed and should be deleted from source
        # Don't delete for mock mode - those summaries will be regenerated later
        should_delete = not config.mock_mode
        return True, f"Created: {slug}.md", should_delete

    except ContentFetchError as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        if not config.dry_run:
            write_stub_note(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                reason=f"Failed to fetch: {e}",
                date=source_date,
            )
        return False, f"Fetch error: {url}", False

    except ContentExtractionError as e:
        logger.warning("Failed to extract content from %s: %s", url, e)
        if not config.dry_run:
            write_stub_note(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                reason=f"Failed to extract content: {e}",
                date=source_date,
            )
        return False, f"Extraction error: {url}", False

    except RateLimitError as e:
        logger.error("Rate limited while processing %s: %s", url, e)
        if not config.dry_run:
            write_stub_note(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                reason="Rate limited - try again later",
                date=source_date,
            )
        return False, f"[Rate limited] {url}", False

    except GeminiAPIError as e:
        logger.error("Gemini API error for %s: %s", url, e)
        if not config.dry_run:
            write_stub_note(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                reason=f"API error: {e}",
                date=source_date,
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
            console.print(f"[red]Invalid date format: {date_str}[/]")
            console.print("Use YYYY-MM-DD format (e.g., 2024-01-15)")
            return EXIT_ERROR
    else:
        date = datetime.now().date()

    console.print(f"[bold]Processing daily note for: {date}[/]")

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
        console.print(f"[red]Error reading daily note: {e}[/]")
        return EXIT_ERROR

    # Extract URLs with context (user tags from daily note)
    url_contexts = extract_urls_with_context(note_content)
    if not url_contexts:
        console.print("[yellow]No URLs found in daily note.[/]")
        return EXIT_SUCCESS

    # Apply max_links limit
    if config.max_links and len(url_contexts) > config.max_links:
        console.print(f"[yellow]Found {len(url_contexts)} URLs, limiting to {config.max_links}[/]")
        url_contexts = url_contexts[: config.max_links]
    else:
        console.print(f"[green]Found {len(url_contexts)} URLs to process[/]")

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

    console.print("[bold]Finding all daily notes with URLs...[/]")

    # Find all daily notes with URLs (returns newest first, we want oldest first)
    notes_with_urls = find_daily_notes_with_urls(
        vault_path=config.vault_path,
        daily_notes_folder=config.daily_notes_folder,
    )

    if not notes_with_urls:
        console.print("[yellow]No daily notes with URLs found.[/]")
        return EXIT_SUCCESS

    # Reverse to process oldest first (chronological order)
    notes_with_urls = list(reversed(notes_with_urls))

    total_urls = sum(count for _, count in notes_with_urls)
    console.print(
        f"[green]Found {len(notes_with_urls)} daily notes with {total_urls} total URLs[/]"
    )

    # Track overall progress
    processed_count = 0
    overall_failures = 0
    notes_processed = 0

    for date_str, url_count in notes_with_urls:
        # Check if we've hit the max_links limit
        if config.max_links and processed_count >= config.max_links:
            remaining_notes = len(notes_with_urls) - notes_processed
            console.print(
                f"[yellow]Reached max_links limit ({config.max_links}). "
                f"Skipping remaining {remaining_notes} notes.[/]"
            )
            break

        console.print(f"\n[bold cyan]Processing: {date_str} ({url_count} URLs)[/]")

        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Invalid date format: {date_str}, skipping[/]")
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
            console.print(f"[red]Error reading daily note {date_str}: {e}[/]")
            overall_failures += url_count
            notes_processed += 1
            continue

        # Extract URLs with context
        url_contexts = extract_urls_with_context(note_content)
        if not url_contexts:
            console.print(f"[yellow]No URLs found in {date_str} (may have been processed)[/]")
            notes_processed += 1
            continue

        # Apply remaining max_links budget for this note
        if config.max_links:
            remaining_budget = config.max_links - processed_count
            if len(url_contexts) > remaining_budget:
                console.print(f"[yellow]Limiting to {remaining_budget} URLs (max_links budget)[/]")
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
    console.print("\n" + "=" * 50)
    console.print(f"[bold]Completed processing {notes_processed} daily notes[/]")
    console.print(f"[bold]Total URLs processed: {processed_count}[/]")

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

    console.print("[bold]Scanning daily notes for URLs...[/]")

    # Find all daily notes with URLs
    notes_with_urls = find_daily_notes_with_urls(
        vault_path=config.vault_path,
        daily_notes_folder=config.daily_notes_folder,
    )

    if not notes_with_urls:
        console.print("[yellow]No daily notes with URLs found.[/]")
        return EXIT_SUCCESS

    # Display results in a table
    table = Table(title="Daily Notes with URLs")
    table.add_column("Date", style="cyan")
    table.add_column("URLs", style="green", justify="right")

    total_urls = 0
    for date_str, url_count in notes_with_urls:
        table.add_row(date_str, str(url_count))
        total_urls += url_count

    console.print(table)
    console.print()
    console.print(f"[bold]Total:[/] {len(notes_with_urls)} notes with {total_urls} URLs")

    return EXIT_SUCCESS


def cmd_status(config: Config) -> int:
    """
    Show current rate limit status.

    Args:
        config: Application configuration.

    Returns:
        Exit code.
    """
    # Initialize rate limiter with vault path and configured limits
    rate_limiter = get_rate_limiter(
        state_path=config.vault_path,
        rpm_limit=config.rpm_limit,
        tpm_limit=config.tpm_limit,
        daily_limit=config.daily_limit,
    )
    status = rate_limiter.get_status()

    console.print("[bold]Gemini API Rate Limit Status[/]\n")

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

    console.print(table)
    console.print()

    # Warnings if approaching limits
    if status["daily"]["remaining"] < 50:
        console.print(
            f"[yellow]⚠ Warning: Only {status['daily']['remaining']} daily requests remaining![/]"
        )
    if status["daily"]["remaining"] == 0:
        console.print("[red]✗ Daily limit reached. Try again tomorrow.[/]")

    return EXIT_SUCCESS


def cmd_urls(config: Config, urls: list[str]) -> int:
    """
    Process specified URLs.

    Args:
        config: Application configuration.
        urls: List of URLs to process.

    Returns:
        Exit code.
    """
    console.print(f"[bold]Processing {len(urls)} URLs[/]")

    # Apply max_links limit
    if config.max_links and len(urls) > config.max_links:
        console.print(f"[yellow]Limiting to {config.max_links} URLs (from {len(urls)})[/]")
        urls = urls[: config.max_links]

    # Convert to UrlWithContext (no user tags for direct URL input)
    url_contexts = [UrlWithContext(url=url) for url in urls]

    return _process_urls_with_metadata(url_contexts, config)


def _process_urls(urls: list[str], config: Config, daily_note_filename: str | None = None) -> int:
    """
    Process a list of URLs.

    Args:
        urls: URLs to process.
        config: Application configuration.
        daily_note_filename: Optional filename of source daily note for back-linking.

    Returns:
        Exit code.
    """
    # Create the Gemini client
    client = create_client(
        api_key=config.gemini_api_key,
        model=config.model,
        mock_mode=config.mock_mode,
        state_path=config.vault_path,
        rpm_limit=config.rpm_limit,
        tpm_limit=config.tpm_limit,
        daily_limit=config.daily_limit,
    )

    if config.mock_mode:
        console.print("[yellow]Running in mock mode (no API calls)[/]")
    if config.dry_run:
        console.print("[yellow]Running in dry-run mode (no changes)[/]")

    # Process with progress bar
    results: list[tuple[bool, str]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("[cyan]Processing...", total=len(urls))

        for url in urls:
            success, message = _process_url(
                url, config, client, progress, task, daily_note_filename
            )
            results.append((success, message))
            progress.advance(task)

    # Print results table
    _print_results(results)

    # Return appropriate exit code
    failures = sum(1 for success, _ in results if not success)
    if failures == len(results):
        return EXIT_ERROR
    return EXIT_SUCCESS


def _process_urls_with_metadata(
    url_contexts: list[UrlWithContext],
    config: Config,
    daily_note_filename: str | None = None,
    source_date: datetime | None = None,
) -> int:
    """
    Process a list of URLs with full metadata extraction.

    Args:
        url_contexts: URLs with context (user tags, surrounding text).
        config: Application configuration.
        daily_note_filename: Optional filename of source daily note for back-linking.
        source_date: Optional date from the source daily note (for filename).

    Returns:
        Exit code.
    """
    # Create the Gemini client
    client = create_client(
        api_key=config.gemini_api_key,
        model=config.model,
        mock_mode=config.mock_mode,
        state_path=config.vault_path,
        rpm_limit=config.rpm_limit,
        tpm_limit=config.tpm_limit,
        daily_limit=config.daily_limit,
    )

    if config.mock_mode:
        console.print("[yellow]Running in mock mode (no API calls)[/]")
    if config.dry_run:
        console.print("[yellow]Running in dry-run mode (no changes)[/]")

    # Process with progress bar
    results: list[tuple[bool, str]] = []
    urls_to_delete: list[str] = []  # Track URLs that were successfully processed

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("[cyan]Processing...", total=len(url_contexts))

        for url_context in url_contexts:
            success, message, should_delete = _process_url_with_metadata(
                url_context, config, client, progress, task, daily_note_filename, source_date
            )
            results.append((success, message))

            # Track URLs that were newly processed (not skipped, not errors)
            if should_delete:
                urls_to_delete.append(url_context.url)

            progress.advance(task)

    # Delete processed URL lines from the daily note
    # Only if we have a source note and are not in dry-run mode
    if daily_note_filename and urls_to_delete and not config.dry_run:
        assert config.vault_path is not None
        console.print(
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

    # Print results table
    _print_results(results)

    # Return appropriate exit code
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

    console.print(table)

    # Print summary
    total = len(results)
    successes = sum(1 for success, _ in results if success)
    failures = total - successes

    console.print()
    console.print(f"[bold]Summary:[/] {successes} succeeded, {failures} failed out of {total}")


def main(argv: list[str] | None = None) -> int:
    """
    Main entry point for the CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code.
    """
    parser = create_parser()
    args = parser.parse_args(argv)

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
        else:
            console.print(f"[red]Unknown command: {args.command}[/]")
            return EXIT_ERROR

    except ConfigError as e:
        console.print(f"[red]Configuration error: {e}[/]")
        return EXIT_CONFIG_ERROR

    except SummarizerError as e:
        console.print(f"[red]Error: {e}[/]")
        return EXIT_ERROR

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/]")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
