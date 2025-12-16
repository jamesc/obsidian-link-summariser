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
    read_daily_note,
    slug_from_url,
    summary_exists,
    write_stub_note,
    write_summary_note,
    write_summary_note_with_metadata,
)

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

    return parser


def _process_url(
    url: str,
    config: Config,
    client: SummarizerProtocol,
    progress: Progress | None = None,
    task_id: TaskID | None = None,
    daily_note_filename: str | None = None,
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

    Returns:
        Tuple of (success, message).
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    slug = slug_from_url(url)

    # Check if summary already exists (skip check if force is enabled)
    if not config.force and summary_exists(config.vault_path, config.out_folder, url):
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
            )
        return False, f"Rate limited: {url}"

    except GeminiAPIError as e:
        logger.error("Gemini API error for %s: %s", url, e)
        if not config.dry_run:
            write_stub_note(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                reason=f"API error: {e}",
            )
        return False, f"API error: {url}"


def _process_url_with_metadata(
    url_context: UrlWithContext,
    config: Config,
    client: SummarizerProtocol,
    progress: Progress | None = None,
    task_id: TaskID | None = None,
    daily_note_filename: str | None = None,
) -> tuple[bool, str]:
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

    Returns:
        Tuple of (success, message).
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    url = url_context.url
    slug = slug_from_url(url)

    # Check if summary already exists (skip check if force is enabled)
    if not config.force and summary_exists(config.vault_path, config.out_folder, url):
        return True, f"Skipped (exists): {slug}"

    if config.dry_run:
        return True, f"Would process: {url} -> {slug}.md"

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

        # Write the summary note with rich frontmatter
        summary_path = write_summary_note_with_metadata(
            vault_path=config.vault_path,
            out_folder=config.out_folder,
            url=url,
            summary_result=summary_result,
            page_metadata=page_metadata,
            user_tags=url_context.tags,
            source_note=daily_note_filename,
            default_tags=config.default_tags,
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
            )
        return False, f"Rate limited: {url}"

    except GeminiAPIError as e:
        logger.error("Gemini API error for %s: %s", url, e)
        if not config.dry_run:
            write_stub_note(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                reason=f"API error: {e}",
            )
        return False, f"API error: {url}"


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
    return _process_urls_with_metadata(url_contexts, config, daily_note_filename=note_filename)


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
) -> int:
    """
    Process a list of URLs with full metadata extraction.

    Args:
        url_contexts: URLs with context (user tags, surrounding text).
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
        task = progress.add_task("[cyan]Processing...", total=len(url_contexts))

        for url_context in url_contexts:
            success, message = _process_url_with_metadata(
                url_context, config, client, progress, task, daily_note_filename
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
            return cmd_from_note(config, getattr(args, "date", None))
        elif args.command == "urls":
            return cmd_urls(config, args.urls)
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
