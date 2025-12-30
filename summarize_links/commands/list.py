"""
Command handler for 'list' subcommand.

Lists all daily notes that contain URLs.
"""

import logging

from rich.table import Table

from summarize_links.config import Config
from summarize_links.notes import find_daily_notes_with_urls
from summarize_links.ui import print_message

# Module logger
logger = logging.getLogger(__name__)

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1


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

    print_message("[bold]Scanning daily notes for URLs...[/]")

    # Find all daily notes with URLs
    notes_with_urls = find_daily_notes_with_urls(
        vault_path=config.vault_path,
        daily_notes_folder=config.daily_notes_folder,
    )

    if not notes_with_urls:
        print_message("[yellow]No daily notes with URLs found.[/]")
        return EXIT_SUCCESS

    # Display results in a table
    table = Table(title="Daily Notes with URLs")
    table.add_column("Date", style="cyan")
    table.add_column("URLs", style="green", justify="right")

    total_urls = 0
    for date_str, url_count in notes_with_urls:
        table.add_row(date_str, str(url_count))
        total_urls += url_count

    print_message(table)
    print_message()
    print_message(f"[bold]Total:[/] {len(notes_with_urls)} notes with {total_urls} URLs")

    return EXIT_SUCCESS
