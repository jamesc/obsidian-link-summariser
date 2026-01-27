"""Shared utilities for CLI command handlers."""

from summarize_links.services import summarization
from summarize_links.ui import print_message


def progress_callback(stage: str, detail: str) -> None:
    """Standard progress callback for CLI commands."""
    print_message(f"[dim]{stage}: {detail}[/]")


def outcomes_to_results(outcomes: list[summarization.ProcessOutcome]) -> list[tuple[bool, str]]:
    """Convert ProcessOutcome list to legacy (success, message) tuples for print_results."""
    return [(o.success, o.message) for o in outcomes]
