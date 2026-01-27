"""
Command handler for 'from-note' subcommand.

Processes URLs from daily notes (single date or all notes).
"""

import logging
from datetime import datetime

from summarize_links.config import Config
from summarize_links.exceptions import NoteReadError
from summarize_links.models import UrlWithContext
from summarize_links.notes import (
    extract_urls_with_context,
    find_daily_notes_with_urls,
    read_daily_note,
)
from summarize_links.services.summarization import ProcessOutcome, process_urls
from summarize_links.ui import print_error, print_message, print_results

# Module logger
logger = logging.getLogger(__name__)

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1


def _progress_cb(stage: str, detail: str) -> None:
    print_message(f"[dim]{stage}: {detail}[/]")


def _to_results(outcomes: list[ProcessOutcome]) -> list[tuple[bool, str]]:
    return [(o.success, o.message) for o in outcomes]


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
            print_error(f"[red]Invalid date format: {date_str}[/]")
            print_error("Use YYYY-MM-DD format (e.g., 2024-01-15)")
            return EXIT_ERROR
    else:
        date = datetime.now().date()

    print_message(f"[bold]Processing daily note for: {date}[/]")

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
        print_error(f"[red]Error reading daily note: {e}[/]")
        return EXIT_ERROR

    # Extract URLs with context (user tags from daily note)
    url_contexts = extract_urls_with_context(note_content)
    if not url_contexts:
        print_message("[yellow]No URLs found in daily note.[/]")
        return EXIT_SUCCESS

    # Apply max_links limit
    if config.max_links and len(url_contexts) > config.max_links:
        print_message(f"[yellow]Found {len(url_contexts)} URLs, limiting to {config.max_links}[/]")
        url_contexts = url_contexts[: config.max_links]
    else:
        print_message(f"[green]Found {len(url_contexts)} URLs to process[/]")

    # Process URLs with rich metadata pipeline
    # Convert date to datetime for the processing functions
    source_datetime = datetime.combine(date, datetime.min.time())
    exit_code, outcomes = process_urls(
        url_contexts,
        config,
        source_note=note_filename,
        source_date=source_datetime,
        progress_cb=_progress_cb,
    )

    results = _to_results(outcomes)
    if results:
        print_results(results)

    return exit_code


def cmd_from_note_all(config: Config) -> int:
    """
    Process URLs from all daily notes that contain URLs.

    Scans all notes upfront, collects URLs with their source info,
    and processes everything in a single batch (like resummarize).

    Args:
        config: Application configuration.

    Returns:
        Exit code.
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    print_message("[bold]Finding all daily notes with URLs...[/]")

    # Find all daily notes with URLs
    notes_with_urls = find_daily_notes_with_urls(
        vault_path=config.vault_path,
        daily_notes_folder=config.daily_notes_folder,
    )

    if not notes_with_urls:
        print_message("[yellow]No daily notes with URLs found.[/]")
        return EXIT_SUCCESS

    total_urls = sum(count for _, count in notes_with_urls)
    print_message(
        f"[green]Found {len(notes_with_urls)} daily notes with {total_urls} total URLs[/]"
    )

    # Collect all URLs from all notes with source info
    all_url_contexts: list[UrlWithContext] = []

    for date_str, _ in notes_with_urls:
        try:
            # Validate date format (YYYY-MM-DD); we discard the parsed date object,
            # but this ensures date_str is parseable before storing it as a string.
            datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            print_error(f"[red]Invalid date format: {date_str}, skipping[/]")
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
            print_error(f"[red]Error reading daily note {date_str}: {e}[/]")
            continue

        # Extract URLs with context
        url_contexts = extract_urls_with_context(note_content)
        if not url_contexts:
            continue

        # Attach source note and date to each URL context
        for url_ctx in url_contexts:
            url_ctx.source_note = note_filename
            url_ctx.source_date = date_str

        all_url_contexts.extend(url_contexts)

    if not all_url_contexts:
        print_message("[yellow]No URLs found in daily notes.[/]")
        return EXIT_SUCCESS

    # Apply max_links limit
    if config.max_links and len(all_url_contexts) > config.max_links:
        print_message(
            f"[yellow]Found {len(all_url_contexts)} URLs, limiting to {config.max_links}[/]"
        )
        all_url_contexts = all_url_contexts[: config.max_links]
    else:
        print_message(f"[green]Found {len(all_url_contexts)} URLs to process[/]")

    # Process all URLs in one batch (signal handling is in services.process_urls)
    exit_code, outcomes = process_urls(
        all_url_contexts,
        config,
        progress_cb=_progress_cb,
    )

    results = _to_results(outcomes)
    if results:
        print_results(results)

    return exit_code
