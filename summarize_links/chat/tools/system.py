"""
System tools for status, help, and utility functions.

This module provides tools for:
- Checking rate limit status
- Getting help on available tools
- System information
"""

import logging
from typing import Any

from summarize_links.chat.tools.base import ProgressCallback, Tool, ToolResult
from summarize_links.config import Config
from summarize_links.notes import scan_summaries
from summarize_links.rate_limiter import get_rate_limiter

__all__ = [
    "GetRateLimitStatusTool",
    "GetVaultStatusTool",
]

logger = logging.getLogger(__name__)


class GetRateLimitStatusTool(Tool):
    """
    Tool to check current API rate limit status.

    Shows usage and remaining quota for the summarization model.
    """

    @property
    def name(self) -> str:
        return "get_rate_limit_status"

    @property
    def description(self) -> str:
        return (
            "Check current API rate limit usage and remaining quota. "
            "Shows requests per minute, tokens per minute, and daily limits. "
            "Use this to see if you can make more summarization requests."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Get rate limit status.

        Args:
            config: Application configuration.
            progress_callback: Optional callback for reporting progress.
            **kwargs: No parameters needed.

        Returns:
            ToolResult with rate limit information.
        """
        try:
            # Get the rate limiter (if initialized)
            limiter = get_rate_limiter(
                model=config.model,
                state_path=config.vault_path,
            )
            status = limiter.get_status()

            # Format output
            lines = ["**Rate Limit Status**\n"]

            model = status.get("model", config.model)
            lines.append(f"**Model**: {model}")
            lines.append(f"**Provider**: {config.model_provider}\n")

            # RPM
            rpm = status.get("rpm", {})
            rpm_current = rpm.get("current", 0)
            rpm_limit = rpm.get("limit", 0)
            rpm_remaining = rpm.get("remaining", 0)
            lines.append(
                f"**Requests/minute**: {rpm_current}/{rpm_limit} (remaining: {rpm_remaining})"
            )

            # TPM
            tpm = status.get("tpm", {})
            tpm_current = tpm.get("current", 0)
            tpm_limit = tpm.get("limit", 0)
            tpm_remaining = tpm.get("remaining", 0)
            lines.append(
                f"**Tokens/minute**: {tpm_current:,}/{tpm_limit:,} (remaining: {tpm_remaining:,})"
            )

            # Daily
            daily = status.get("daily", {})
            daily_current = daily.get("current", 0)
            daily_limit = daily.get("limit", 0)
            daily_remaining = daily.get("remaining", 0)
            lines.append(
                f"**Daily requests**: {daily_current}/{daily_limit} (remaining: {daily_remaining})"
            )

            # Summary
            if daily_remaining > 0:
                lines.append(
                    f"\n✓ You can make {daily_remaining} more summarization requests today."
                )
            else:
                lines.append("\n⚠ Daily limit reached. Try again tomorrow.")

            return ToolResult(
                success=True,
                message="\n".join(lines),
                data=status,
            )

        except Exception as e:
            logger.warning("Could not get rate limit status: %s", e)
            return ToolResult(
                success=True,
                message=(
                    "Rate limit status not available. "
                    "The rate limiter initializes when you first summarize a URL."
                ),
                data={"available": False, "reason": str(e)},
            )


class GetVaultStatusTool(Tool):
    """
    Tool to get overall vault status and summary statistics.

    Shows counts of summaries by status, date ranges, etc.
    """

    @property
    def name(self) -> str:
        return "get_vault_status"

    @property
    def description(self) -> str:
        return (
            "Get overall status of the Obsidian vault and summary statistics. "
            "Shows total summaries, success/error counts, date range, etc. "
            "Use this to understand the state of your summarization vault."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Get vault status.

        Args:
            config: Application configuration.
            progress_callback: Optional callback for reporting progress.
            **kwargs: No parameters needed.

        Returns:
            ToolResult with vault status information.
        """
        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set.",
            )

        # Scan summaries
        stats = scan_summaries(config.vault_path, config.out_folder)

        # Format output
        lines = ["**Vault Status**\n"]
        lines.append(f"**Vault path**: {config.vault_path}")
        lines.append(f"**Summaries folder**: {config.out_folder}")
        lines.append(f"**Daily notes folder**: {config.daily_notes_folder or '(root)'}\n")

        lines.append(f"**Total summaries**: {stats['total']}")
        lines.append(f"  - ✓ Success: {stats['success']}")
        lines.append(f"  - ⚠ Error: {stats['error']}")
        if stats["unknown"] > 0:
            lines.append(f"  - ? Unknown: {stats['unknown']}")

        if stats["oldest_date"] and stats["newest_date"]:
            lines.append(f"\n**Date range**: {stats['oldest_date']} to {stats['newest_date']}")

        # Show problematic summaries if any
        if stats["error_summaries"]:
            lines.append(f"\n**Error summaries** ({len(stats['error_summaries'])}):")
            for filename, reason in stats["error_summaries"][:5]:
                lines.append(f"  - {filename}: {reason}")
            if len(stats["error_summaries"]) > 5:
                lines.append(f"  - ... and {len(stats['error_summaries']) - 5} more")

        # Current configuration
        lines.append("\n**Current configuration**:")
        lines.append(f"  - Model: {config.model}")
        lines.append(f"  - Provider: {config.model_provider}")

        return ToolResult(
            success=True,
            message="\n".join(lines),
            data={
                "vault_path": str(config.vault_path),
                "out_folder": config.out_folder,
                "stats": stats,
                "model": config.model,
                "provider": config.model_provider,
            },
        )
