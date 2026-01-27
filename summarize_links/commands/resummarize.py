"""
Command handler for 'resummarize' subcommand.

Re-summarizes existing summaries from the Summaries folder.
"""

import logging
from datetime import datetime, timedelta

from summarize_links.commands.shared import outcomes_to_results, progress_callback
from summarize_links.config import Config
from summarize_links.notes import scan_summaries_for_resummarize
from summarize_links.services import summarization
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

    outcomes: list[summarization.ProcessOutcome] = []
    for url, _, _, _ in summaries:
        outcome = summarization.resummarize(url, config, progress_cb=progress_callback)
        outcomes.append(outcome)

    if not outcomes:
        return EXIT_ERROR

    exit_code = EXIT_ERROR if all(not o.success for o in outcomes) else EXIT_SUCCESS

    results = outcomes_to_results(outcomes)
    if results:
        print_results(results)

    return exit_code
