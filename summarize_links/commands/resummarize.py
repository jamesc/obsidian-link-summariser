"""
Command handler for 'resummarize' subcommand.

Re-summarizes existing summaries from the Summaries folder.
"""

import logging
from datetime import datetime, timedelta

from summarize_links.config import Config
from summarize_links.models import UrlWithContext
from summarize_links.notes import scan_summaries_for_resummarize
from summarize_links.processor import process_resummarize_batch
from summarize_links.ui import print_error, print_message, print_results

# Module logger
logger = logging.getLogger(__name__)

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1


def cmd_resummarize(config: Config, age_days: int | None = None) -> int:
    """
    Re-summarize existing summaries from the Summaries folder.

    Scans all summaries, extracts their source URLs and dates,
    and reprocesses them using the current model and settings.
    Preserves the original summary date.

    Note: This command automatically enables force mode to overwrite
    existing summaries.

    Args:
        config: Application configuration.
        age_days: Only resummarize summaries older than this many days (optional).

    Returns:
        Exit code.
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    # Validate age_days parameter
    if age_days is not None and age_days <= 0:
        print_error("[red]--age must be a positive integer[/]")
        return EXIT_ERROR

    # Enable force mode for resummarize (we always want to overwrite)
    config.force = True

    print_message("[bold]Scanning summaries for re-summarization...[/]\n")

    # Find all summaries suitable for resummarization
    summaries = scan_summaries_for_resummarize(
        vault_path=config.vault_path,
        out_folder=config.out_folder,
    )

    # Filter by age if specified (based on summary_date)
    if age_days is not None:
        cutoff_date = datetime.now() - timedelta(days=age_days)
        original_count = len(summaries)
        # Filter based on summary_date (3rd element in tuple)
        summaries = [
            (url, orig_date, summ_date, source_note)
            for url, orig_date, summ_date, source_note in summaries
            if summ_date < cutoff_date
        ]
        filtered_count = original_count - len(summaries)
        if filtered_count > 0:
            print_message(
                f"[cyan]Filtered out {filtered_count} summaries newer than {age_days} days[/]"
            )

    if not summaries:
        print_message("[yellow]No summaries found to re-summarize.[/]")
        if age_days is not None:
            print_message(f"(No summaries older than {age_days} days)")
        print_message(f"Summaries folder: {config.vault_path / config.out_folder}")
        return EXIT_SUCCESS

    # Apply max_links limit
    if config.max_links and len(summaries) > config.max_links:
        print_message(
            f"[yellow]Found {len(summaries)} summaries, limiting to {config.max_links}[/]"
        )
        summaries = summaries[: config.max_links]
    else:
        print_message(f"[green]Found {len(summaries)} summaries to re-summarize[/]")

    # Convert to UrlWithContext (no user tags for resummarize)
    url_contexts = [UrlWithContext(url=url) for url, _, _, _ in summaries]

    # Extract original dates and source notes for each URL
    url_dates = {url: orig_date for url, orig_date, _, _ in summaries}
    url_source_notes = {url: source_note for url, _, _, source_note in summaries}

    # Process URLs with the preserved dates and source notes
    exit_code, results = process_resummarize_batch(
        url_contexts, url_dates, url_source_notes, config
    )

    # Print results
    if results:
        print_results(results)

    return exit_code
