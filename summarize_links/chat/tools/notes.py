"""
Daily notes tools for finding URLs and working with daily notes.

This module provides tools for:
- Finding URLs in daily notes that need summarization
- Listing daily notes with URLs
"""

import logging
from datetime import datetime
from typing import Any

from summarize_links.chat.tools.base import ProgressCallback, Tool, ToolResult
from summarize_links.config import Config
from summarize_links.notes import (
    extract_urls_with_context,
    find_daily_notes_with_urls,
    read_daily_note,
    summary_exists,
)

__all__ = [
    "FindUrlsInNotesTool",
]

logger = logging.getLogger(__name__)


class FindUrlsInNotesTool(Tool):
    """
    Tool to find URLs in daily notes that haven't been summarized.

    Scans daily notes for URLs and identifies which ones still need
    to be processed.
    """

    @property
    def name(self) -> str:
        return "find_urls_in_notes"

    @property
    def description(self) -> str:
        return (
            "Find URLs in daily notes that haven't been summarized yet. "
            "By default searches today's note, or specify a date or search all notes. "
            "Returns URLs along with their context (surrounding text and tags)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (default: today)",
                },
                "all_dates": {
                    "type": "boolean",
                    "description": "Search all daily notes instead of a specific date",
                    "default": False,
                },
                "include_summarized": {
                    "type": "boolean",
                    "description": "Include URLs that have already been summarized",
                    "default": False,
                },
            },
            "required": [],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Find URLs in daily notes.

        Args:
            config: Application configuration.
            **kwargs: Tool parameters including:
                - date: Specific date to search (YYYY-MM-DD).
                - all_dates: Search all daily notes.
                - include_summarized: Include already-summarized URLs.

        Returns:
            ToolResult with list of URLs found.
        """
        date_str = kwargs.get("date")
        all_dates = kwargs.get("all_dates", False)
        include_summarized = kwargs.get("include_summarized", False)

        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set.",
            )

        if all_dates:
            return self._search_all_notes(config, include_summarized)
        else:
            return self._search_single_note(config, date_str, include_summarized)

    def _search_single_note(
        self,
        config: Config,
        date_str: str | None,
        include_summarized: bool,
    ) -> ToolResult:
        """Search a single daily note for URLs."""
        # Default to today
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        note_filename = f"{date_str}.md"

        # Parse date for summary_exists check
        # If date doesn't parse, use None (don't assume today's date)
        try:
            note_date: datetime | None = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            # Allow reading notes with non-standard names, but don't check if summarized
            # (passing None to summary_exists will always return False)
            note_date = None

        # vault_path is validated in execute()
        assert config.vault_path is not None

        try:
            content = read_daily_note(
                config.vault_path,
                note_filename,
                config.daily_notes_folder,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Could not read daily note for {date_str}: {e}",
                error=str(e),
            )

        # Extract URLs with context
        urls_with_context = extract_urls_with_context(content)

        if not urls_with_context:
            return ToolResult(
                success=True,
                message=f"No URLs found in daily note for {date_str}.",
                data={"date": date_str, "urls": [], "total": 0},
            )

        # Check which URLs are already summarized
        results: list[dict[str, Any]] = []
        unsummarized_count = 0

        for url_ctx in urls_with_context:
            already_summarized = summary_exists(
                config.vault_path,
                config.out_folder,
                url_ctx.url,
                date=note_date,
            )

            if not include_summarized and already_summarized:
                continue

            results.append(
                {
                    "url": url_ctx.url,
                    "tags": url_ctx.tags,
                    "context": url_ctx.context_text,
                    "already_summarized": already_summarized,
                }
            )

            if not already_summarized:
                unsummarized_count += 1

        if not results:
            return ToolResult(
                success=True,
                message=(
                    f"All {len(urls_with_context)} URLs in {date_str} have already been summarized."
                ),
                data={"date": date_str, "urls": [], "total": 0, "all_summarized": True},
            )

        # Format output
        lines = [f"Found {len(results)} URLs in daily note for {date_str}:\n"]

        for i, r in enumerate(results, 1):
            status = "✓ (summarized)" if r["already_summarized"] else "○ (not summarized)"
            tags_str = f" [{', '.join(r['tags'])}]" if r["tags"] else ""
            lines.append(f"{i}. {r['url']} {status}{tags_str}")
            if r["context"]:
                lines.append(f"   Context: {r['context'][:100]}...")

        if unsummarized_count > 0:
            lines.append(f"\n{unsummarized_count} URL(s) need summarization.")

        return ToolResult(
            success=True,
            message="\n".join(lines),
            data={
                "date": date_str,
                "urls": results,
                "total": len(results),
                "unsummarized": unsummarized_count,
            },
        )

    def _search_all_notes(
        self,
        config: Config,
        include_summarized: bool,
    ) -> ToolResult:
        """Search all daily notes for URLs."""
        # vault_path is validated in execute()
        assert config.vault_path is not None

        # Find all daily notes with URLs
        notes_with_urls = find_daily_notes_with_urls(
            config.vault_path,
            config.daily_notes_folder,
        )

        if not notes_with_urls:
            return ToolResult(
                success=True,
                message="No daily notes with URLs found.",
                data={"notes": [], "total_urls": 0},
            )

        # Collect URLs from each note
        all_results: list[dict[str, Any]] = []
        total_unsummarized = 0

        for date_str, _url_count in notes_with_urls[:10]:  # Limit to 10 most recent
            note_filename = f"{date_str}.md"

            # Parse the date from date_str (YYYY-MM-DD format)
            try:
                note_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                note_date = None

            try:
                content = read_daily_note(
                    config.vault_path,
                    note_filename,
                    config.daily_notes_folder,
                )
                urls_with_context = extract_urls_with_context(content)

                note_urls: list[dict[str, Any]] = []
                for url_ctx in urls_with_context:
                    already_summarized = summary_exists(
                        config.vault_path,
                        config.out_folder,
                        url_ctx.url,
                        date=note_date,
                    )

                    if not include_summarized and already_summarized:
                        continue

                    note_urls.append(
                        {
                            "url": url_ctx.url,
                            "tags": url_ctx.tags,
                            "already_summarized": already_summarized,
                        }
                    )

                    if not already_summarized:
                        total_unsummarized += 1

                if note_urls:
                    all_results.append(
                        {
                            "date": date_str,
                            "urls": note_urls,
                        }
                    )

            except Exception as e:
                logger.warning("Failed to read note %s: %s", date_str, e)
                continue

        if not all_results:
            return ToolResult(
                success=True,
                message="All URLs in daily notes have been summarized.",
                data={"notes": [], "total_urls": 0, "all_summarized": True},
            )

        # Format output
        lines = [f"Found URLs in {len(all_results)} daily notes:\n"]

        total_urls = 0
        for note in all_results:
            unsummarized_in_note = sum(1 for u in note["urls"] if not u["already_summarized"])
            total_urls += len(note["urls"])
            url_count = len(note["urls"])
            lines.append(
                f"**{note['date']}**: {url_count} URLs ({unsummarized_in_note} not summarized)"
            )
            for u in note["urls"][:3]:  # Show first 3 URLs
                status = "✓" if u["already_summarized"] else "○"
                # Show full URL so LLM can use it for subsequent actions
                lines.append(f"  - {status} {u['url']}")
            if len(note["urls"]) > 3:
                lines.append(f"  - ... and {len(note['urls']) - 3} more")

        lines.append(f"\n**Total**: {total_urls} URLs, {total_unsummarized} need summarization.")

        return ToolResult(
            success=True,
            message="\n".join(lines),
            data={
                "notes": all_results,
                "total_urls": total_urls,
                "total_unsummarized": total_unsummarized,
            },
        )
