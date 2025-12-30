"""
Console output and UI utilities for the CLI.

This module provides a centralized interface for all console output,
including progress bars, tables, and formatted messages using Rich.
"""

from typing import Any

from rich.console import Console
from rich.table import Table

# Rich console for output
console = Console()

# Global quiet mode flag (set by --quiet argument)
_quiet_mode = False


def set_quiet_mode(enabled: bool) -> None:
    """
    Enable or disable quiet mode.

    In quiet mode, informational messages are suppressed, but errors
    are still shown.

    Args:
        enabled: True to enable quiet mode, False to disable.
    """
    global _quiet_mode
    _quiet_mode = enabled


def print_message(message: Any = "", style: str | None = None, **kwargs: Any) -> None:
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


def print_error(message: str) -> None:
    """
    Print error message (always shown, even in quiet mode).

    Args:
        message: Error message to print (Rich markup supported).
    """
    console.print(message)


def print_results(results: list[tuple[bool, str]]) -> None:
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

    print_message(table)

    # Print summary
    total = len(results)
    successes = sum(1 for success, _ in results if success)
    failures = total - successes

    print_message()
    print_message(f"[bold]Summary:[/] {successes} succeeded, {failures} failed out of {total}")
