"""
Command handler for 'urls' subcommand.

Processes specific URLs provided as command-line arguments.
"""

import logging

from summarize_links.config import Config
from summarize_links.models import UrlWithContext
from summarize_links.services import summarization
from summarize_links.ui import print_message, print_results


def _progress_cb(stage: str, detail: str) -> None:
    print_message(f"[dim]{stage}: {detail}[/]")


def _to_results(outcomes: list[summarization.ProcessOutcome]) -> list[tuple[bool, str]]:
    return [(o.success, o.message) for o in outcomes]


# Module logger
logger = logging.getLogger(__name__)

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1


def cmd_urls(config: Config, urls: list[str]) -> int:
    """
    Process specified URLs.

    Args:
        config: Application configuration.
        urls: List of URLs to process.

    Returns:
        Exit code.
    """
    print_message(f"[bold]Processing {len(urls)} URLs[/]")

    # Apply max_links limit
    if config.max_links and len(urls) > config.max_links:
        print_message(f"[yellow]Limiting to {config.max_links} URLs (from {len(urls)})[/]")
        urls = urls[: config.max_links]

    # Convert to UrlWithContext (no user tags for direct URL input)
    url_contexts = [UrlWithContext(url=url) for url in urls]

    exit_code, outcomes = summarization.process_urls(
        url_contexts,
        config,
        progress_cb=_progress_cb,
    )

    results = _to_results(outcomes)
    if results:
        print_results(results)

    return exit_code
