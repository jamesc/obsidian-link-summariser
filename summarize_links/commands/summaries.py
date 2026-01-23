"""
Command handler for 'summaries' subcommand.

Reports on the status of existing summary notes.
"""

import logging

from rich.table import Table

from summarize_links.config import Config
from summarize_links.notes import scan_summaries
from summarize_links.ui import print_message

# Module logger
logger = logging.getLogger(__name__)

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1


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

    print_message("[bold]Scanning summaries...[/]\n")

    # Scan all summaries
    stats = scan_summaries(
        vault_path=config.vault_path,
        out_folder=config.out_folder,
    )

    if stats["total"] == 0:
        print_message("[yellow]No summaries found.[/]")
        print_message(f"Summaries folder: {config.vault_path / config.out_folder}")
        return EXIT_SUCCESS

    # Display overall statistics
    print_message("[bold]Summary Statistics[/]\n")

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

    print_message(summary_table)
    print_message()

    # Display date range
    if stats["oldest_date"] and stats["newest_date"]:
        print_message(f"[cyan]Date range:[/] {stats['oldest_date']} to {stats['newest_date']}")
        print_message()

    # Display error summaries if any
    if stats["error"] > 0:
        print_message("[red]✗ Error Summaries (run with --force to retry):[/]")
        error_table = Table(show_header=True)
        error_table.add_column("File", style="cyan")
        error_table.add_column("Reason", style="yellow")

        for filename, reason in stats["error_summaries"]:  # Show all errors
            error_table.add_row(filename, reason)

        print_message(error_table)
        print_message()

    # Display unknown summaries if any
    if stats["unknown"] > 0:
        print_message("[dim]? Unknown Summaries (missing or unrecognized status):[/]")
        unknown_table = Table(show_header=True)
        unknown_table.add_column("File", style="cyan")
        unknown_table.add_column("Status", style="dim")
        unknown_table.add_column("Source", style="blue")

        for filename, status, source in stats["unknown_summaries"][:10]:  # Show first 10
            status_display = status if status else "(missing)"
            source_display = (
                source[:50] + "..." if source and len(source) > 50 else (source or "(unknown)")
            )
            unknown_table.add_row(filename, status_display, source_display)

        if len(stats["unknown_summaries"]) > 10:
            unknown_table.add_row(
                f"... and {len(stats['unknown_summaries']) - 10} more",
                "",
                "",
            )

        print_message(unknown_table)
        print_message()

    # Helpful tips
    if stats["mocked"] > 0 or stats["error"] > 0:
        print_message("[bold]Tips:[/]")
        if stats["mocked"] > 0:
            print_message(
                "  • Run [cyan]summarize-links from-note --all --force[/] "
                "to regenerate mocked summaries"
            )
        if stats["error"] > 0:
            print_message(
                "  • Run [cyan]summarize-links from-note --all --force[/] to retry failed summaries"
            )

    return EXIT_SUCCESS
