"""
Command-line interface for the Obsidian Link Summarizer.

This module provides the main entry point for the CLI application,
handling argument parsing, command dispatch, and setup.

Command handlers are implemented in separate modules under the
`commands` subpackage for better maintainability.
"""

import argparse
import logging
import sys

from rich.logging import RichHandler

from summarize_links.commands import (
    cmd_from_note,
    cmd_from_note_all,
    cmd_list,
    cmd_resummarize,
    cmd_status,
    cmd_summaries,
    cmd_urls,
)
from summarize_links.config import load_config, setup_logging
from summarize_links.exceptions import (
    ConfigError,
    ModelNotInstalledError,
    OllamaServerError,
    SummarizerError,
    URLValidationError,
)
from summarize_links.extract import fetch_and_extract_metadata
from summarize_links.llm import SummarizerProtocol, create_llm_client, detect_provider
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
from summarize_links.ui import console, print_error, set_quiet_mode

# Module logger
logger = logging.getLogger(__name__)

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

    # Set quiet mode from args
    set_quiet_mode(getattr(args, "quiet", False))

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
            print_error(f"[red]Unknown command: {args.command}[/]")
            return EXIT_ERROR

    except ConfigError as e:
        print_error(f"[red]Configuration error: {e}[/]")
        return EXIT_CONFIG_ERROR

    except OllamaServerError as e:
        print_error("[red]Ollama server not available![/]")
        print_error("[yellow]To start Ollama:[/]")
        print_error("  • Start the Ollama app, or")
        print_error("  • Run: ollama serve")
        print_error(f"\n[red]Error:[/] {e}")
        return EXIT_ERROR

    except ModelNotInstalledError as e:
        print_error("[red]Ollama model not installed![/]")
        print_error(f"\n[red]Error:[/] {e}")
        return EXIT_ERROR

    except SummarizerError as e:
        print_error(f"[red]Error: {e}[/]")
        return EXIT_ERROR

    except KeyboardInterrupt:
        print_error("\n[yellow]Interrupted by user[/]")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
