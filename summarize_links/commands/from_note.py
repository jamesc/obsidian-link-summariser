"""
Command handler for 'from-note' subcommand.

Processes URLs from daily notes (single date or all notes).
"""

import logging
from datetime import datetime

from summarize_links.config import Config
from summarize_links.exceptions import NoteReadError
from summarize_links.notes import (
    extract_urls_with_context,
    find_daily_notes_with_urls,
    read_daily_note,
)
from summarize_links.processor import process_urls_batch
from summarize_links.ui import print_error, print_message, print_results

# Module logger
logger = logging.getLogger(__name__)

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1


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
    exit_code, results = process_urls_batch(
        url_contexts, config, daily_note_filename=note_filename, source_date=source_datetime
    )

    # Print results
    if results:
        print_results(results)

    return exit_code


def cmd_from_note_all(config: Config) -> int:
    """
    Process URLs from all daily notes that contain URLs.

    Iterates through all daily notes with URLs (newest first) and processes
    each one in sequence, respecting the max_links limit across all notes.

    Args:
        config: Application configuration.

    Returns:
        Exit code.
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    print_message("[bold]Finding all daily notes with URLs...[/]")

    # Find all daily notes with URLs (returns newest first, we want oldest first)
    notes_with_urls = find_daily_notes_with_urls(
        vault_path=config.vault_path,
        daily_notes_folder=config.daily_notes_folder,
    )

    if not notes_with_urls:
        print_message("[yellow]No daily notes with URLs found.[/]")
        return EXIT_SUCCESS

    # Notes are returned newest first - process most recent first
    # (no reversal needed)

    total_urls = sum(count for _, count in notes_with_urls)
    print_message(
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
            print_message(
                f"[yellow]Reached max_links limit ({config.max_links}). "
                f"Skipping remaining {remaining_notes} notes.[/]"
            )
            break

        print_message(f"\n[bold cyan]Processing: {date_str} ({url_count} URLs)[/]")

        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
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
            overall_failures += url_count
            notes_processed += 1
            continue

        # Extract URLs with context
        url_contexts = extract_urls_with_context(note_content)
        if not url_contexts:
            print_message(f"[yellow]No URLs found in {date_str} (may have been processed)[/]")
            notes_processed += 1
            continue

        # Apply remaining max_links budget for this note
        if config.max_links:
            remaining_budget = config.max_links - processed_count
            if len(url_contexts) > remaining_budget:
                print_message(f"[yellow]Limiting to {remaining_budget} URLs (max_links budget)[/]")
                url_contexts = url_contexts[:remaining_budget]

        # Process this note's URLs
        source_datetime = datetime.combine(date, datetime.min.time())
        exit_code, results = process_urls_batch(
            url_contexts, config, daily_note_filename=note_filename, source_date=source_datetime
        )

        # Print results for this note
        if results:
            print_results(results)

        processed_count += len(url_contexts)
        notes_processed += 1

        if exit_code == EXIT_ERROR:
            overall_failures += len(url_contexts)

    # Final summary
    print_message("\n" + "=" * 50)
    print_message(f"[bold]Completed processing {notes_processed} daily notes[/]")
    print_message(f"[bold]Total URLs processed: {processed_count}[/]")

    if overall_failures > 0:
        return EXIT_ERROR
    return EXIT_SUCCESS
