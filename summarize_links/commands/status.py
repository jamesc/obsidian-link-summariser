"""
Command handler for 'status' subcommand.

Shows current LLM provider and rate limit status.
"""

import logging

from rich.table import Table

from summarize_links.config import Config
from summarize_links.llm_factory import detect_provider
from summarize_links.rate_limiter import get_rate_limiter
from summarize_links.ui import print_message

# Module logger
logger = logging.getLogger(__name__)

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1


def cmd_status(config: Config) -> int:
    """
    Show current provider and rate limit status.

    Args:
        config: Application configuration.

    Returns:
        Exit code.
    """
    # Detect provider from model name
    provider = detect_provider(config.model)

    print_message("[bold]LLM Provider Status[/]\n")
    print_message(f"[bold]Provider:[/] {provider.upper()}")
    print_message(f"[bold]Model:[/] {config.model}\n")

    if provider == "ollama":
        print_message(f"[bold]Endpoint:[/] {config.ollama_endpoint}")
        print_message("[cyan]✓ No rate limiting for local models[/]")
        print_message()
        return EXIT_SUCCESS

    # For Gemini, show rate limit information
    # Initialize rate limiter with vault path and configured limits
    rate_limiter = get_rate_limiter(
        state_path=config.vault_path,
        rpm_limit=config.rpm_limit,
        tpm_limit=config.tpm_limit,
        daily_limit=config.daily_limit,
    )
    status = rate_limiter.get_status()

    print_message("[bold]Gemini API Rate Limit Status[/]\n")

    # Display rate limit information in a table
    table = Table(title="Current Usage")
    table.add_column("Limit Type", style="cyan")
    table.add_column("Used", style="yellow", justify="right")
    table.add_column("Limit", style="white", justify="right")
    table.add_column("Remaining", style="green", justify="right")

    table.add_row(
        "Requests/Minute (RPM)",
        str(status["rpm"]["current"]),
        str(status["rpm"]["limit"]),
        str(status["rpm"]["remaining"]),
    )
    table.add_row(
        "Tokens/Minute (TPM)",
        f"{status['tpm']['current']:,}",
        f"{status['tpm']['limit']:,}",
        f"{status['tpm']['remaining']:,}",
    )
    table.add_row(
        "Requests/Day",
        str(status["daily"]["current"]),
        str(status["daily"]["limit"]),
        str(status["daily"]["remaining"]),
    )

    print_message(table)
    print_message()

    # Warnings if approaching limits
    if status["daily"]["remaining"] < 50:
        print_message(
            f"[yellow]⚠ Warning: Only {status['daily']['remaining']} daily requests remaining![/]"
        )
    if status["daily"]["remaining"] == 0:
        print_message("[red]✗ Daily limit reached. Try again tomorrow.[/]")

    return EXIT_SUCCESS
