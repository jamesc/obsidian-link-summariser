"""
Vault tools for searching and listing summaries.

This module provides tools for:
- Listing existing summaries in the vault
- Searching summaries by keyword or tag
- Reading summary content
"""

import logging
from pathlib import Path
from typing import Any

from summarize_links.chat.tools.base import ProgressCallback, Tool, ToolResult
from summarize_links.config import Config
from summarize_links.notes import slug_from_url

__all__ = [
    "ListSummariesTool",
    "SearchVaultTool",
    "ReadSummaryTool",
]

logger = logging.getLogger(__name__)


def _extract_frontmatter(content: str) -> dict[str, Any]:
    """
    Extract frontmatter fields from a markdown file.

    Args:
        content: Full file content with YAML frontmatter.

    Returns:
        Dictionary of frontmatter fields.
    """
    if not content.startswith("---"):
        return {}

    # Find closing delimiter on its own line to avoid matching --- in values
    # Look for \n---\n or \n--- at EOF
    end_idx = content.find("\n---\n", 3)
    if end_idx == -1:
        # Try end of file case (no trailing newline after ---)
        end_idx = content.find("\n---", 3)
        if end_idx == -1 or end_idx + 4 < len(content) and content[end_idx + 4] not in ("\n", ""):
            # Not a standalone line delimiter
            end_idx = -1
    if end_idx == -1:
        return {}
    # Adjust to skip the leading newline we matched
    end_idx += 1

    frontmatter = content[3:end_idx]
    result: dict[str, Any] = {}

    # Parse simple key-value pairs
    for line in frontmatter.split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            result[key] = value

    # Parse tags as a list
    if "tags:" in frontmatter:
        tags = []
        in_tags = False
        for line in frontmatter.split("\n"):
            if line.strip() == "tags:":
                in_tags = True
                continue
            if in_tags:
                if line.strip().startswith("-"):
                    tag = line.strip().lstrip("-").strip()
                    tags.append(tag)
                elif line.strip() and not line.startswith(" "):
                    break
        if tags:
            result["tags"] = tags

    return result


def _get_body_content(content: str) -> str:
    """
    Extract body content after frontmatter.

    Args:
        content: Full file content with YAML frontmatter.

    Returns:
        Content after the frontmatter block.
    """
    if not content.startswith("---"):
        return content

    end_idx = content.find("---", 3)
    if end_idx == -1:
        return content

    return content[end_idx + 3 :].strip()


class ListSummariesTool(Tool):
    """
    Tool to list recent summaries in the vault.

    Lists summaries with their metadata (title, date, tags, status).
    """

    @property
    def name(self) -> str:
        return "list_summaries"

    @property
    def description(self) -> str:
        return (
            "List recent summaries in the Obsidian vault. "
            "Returns summary titles, dates, tags, and status. "
            "Use this to see what has already been summarized."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of summaries to return (default: 10)",
                    "default": 10,
                },
                "status": {
                    "type": "string",
                    "enum": ["all", "success", "error", "mocked"],
                    "description": "Filter by summary status (default: all)",
                    "default": "all",
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
        List summaries in the vault.

        Args:
            config: Application configuration.
            progress_callback: Optional callback for reporting progress.
            **kwargs: Tool parameters including:
                - limit: Maximum summaries to return (default 10).
                - status: Filter by status (all, success, error, mocked).

        Returns:
            ToolResult with list of summaries.
        """
        limit = kwargs.get("limit", 10)
        status_filter = kwargs.get("status", "all")

        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set.",
            )

        summaries_path = config.vault_path / config.out_folder
        if not summaries_path.exists():
            return ToolResult(
                success=True,
                message="No summaries folder found. No summaries have been created yet.",
                data={"summaries": [], "total": 0},
            )

        # Collect summary files
        summaries: list[dict[str, Any]] = []

        for filepath in sorted(summaries_path.glob("*.md"), reverse=True):
            if len(summaries) >= limit * 3:  # Get extra for filtering
                break

            try:
                content = filepath.read_text(encoding="utf-8")
                frontmatter = _extract_frontmatter(content)

                status = frontmatter.get("summary_status", "unknown")

                # Apply status filter
                if status_filter != "all":
                    is_error_filter = status_filter == "error"
                    if (is_error_filter and "error" not in status) or (
                        not is_error_filter and status != status_filter
                    ):
                        continue

                # Extract slug from source URL
                source_url = frontmatter.get("source", "")
                slug = slug_from_url(source_url) if source_url else filepath.stem

                summaries.append(
                    {
                        "filename": filepath.name,
                        "slug": slug,
                        "title": frontmatter.get("title", filepath.stem),
                        "date": frontmatter.get("date", ""),
                        "status": status,
                        "tags": frontmatter.get("tags", []),
                        "source": frontmatter.get("source", ""),
                        "type": frontmatter.get("type", ""),
                    }
                )

            except OSError as e:
                logger.warning("Failed to read %s: %s", filepath, e)
                continue

        # Limit results
        summaries = summaries[:limit]

        if not summaries:
            return ToolResult(
                success=True,
                message=f"No summaries found with status '{status_filter}'.",
                data={"summaries": [], "total": 0},
            )

        # Format output
        lines = [f"Found {len(summaries)} summaries:\n"]
        for s in summaries:
            tags_value = s.get("tags")
            if isinstance(tags_value, str):
                # Support inline tags like "tag1, tag2"
                tags_str = tags_value
            elif isinstance(tags_value, list):
                tags_str = ", ".join(str(t) for t in tags_value) if tags_value else "no tags"
            else:
                tags_str = "no tags"
            if s["status"] == "success":
                status_icon = "✓"
            elif "error" in s["status"]:
                status_icon = "⚠"
            else:
                status_icon = "○"
            lines.append(
                f"- {status_icon} **{s['title']}** ({s['date']}) `{s['slug']}` [{tags_str}]"
            )

        return ToolResult(
            success=True,
            message="\n".join(lines),
            data={"summaries": summaries, "total": len(summaries)},
        )


class SearchVaultTool(Tool):
    """
    Tool to search existing summaries by keyword or tag.

    Searches both frontmatter and content of summary notes.
    """

    @property
    def name(self) -> str:
        return "search_summaries"

    @property
    def description(self) -> str:
        return (
            "Search existing summaries in the vault by keyword or tag. "
            "Searches titles, content, tags, and URLs. "
            "Use this to find summaries on a specific topic."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (keywords or tags to find)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Search summaries by keyword or tag.

        Args:
            config: Application configuration.
            progress_callback: Optional callback for reporting progress.
            **kwargs: Tool parameters including:
                - query: Search query (required).
                - limit: Maximum results (default 10).

        Returns:
            ToolResult with matching summaries.
        """
        query = kwargs.get("query", "")
        limit = kwargs.get("limit", 10)

        if not query or not query.strip():
            return ToolResult(
                success=False,
                message="Search query is required",
                error="Missing 'query' parameter",
            )

        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set.",
            )

        summaries_path = config.vault_path / config.out_folder
        if not summaries_path.exists():
            return ToolResult(
                success=True,
                message="No summaries folder found.",
                data={"results": [], "total": 0},
            )

        # Search for matches
        query_lower = query.lower()
        query_terms = query_lower.split()
        results: list[dict[str, Any]] = []

        for filepath in summaries_path.glob("*.md"):
            try:
                content = filepath.read_text(encoding="utf-8")
                frontmatter = _extract_frontmatter(content)

                # Calculate match score
                score = 0
                matched_terms: list[str] = []

                # Check tags (high score)
                tags = frontmatter.get("tags", [])
                if isinstance(tags, list):
                    for term in query_terms:
                        if any(term in tag.lower() for tag in tags):
                            score += 3
                            matched_terms.append(f"tag:{term}")

                # Check title (high score)
                title = frontmatter.get("title", filepath.stem)
                if query_lower in title.lower():
                    score += 3
                    matched_terms.append("title")

                # Check content (lower score)
                body = _get_body_content(content)
                for term in query_terms:
                    count = body.lower().count(term)
                    if count > 0:
                        score += min(count, 2)
                        matched_terms.append(f"content:{term}({count})")

                # Check URL
                source = frontmatter.get("source", "")
                if query_lower in source.lower():
                    score += 2
                    matched_terms.append("url")

                if score > 0:
                    # Extract slug from source URL
                    slug = slug_from_url(source) if source else filepath.stem

                    results.append(
                        {
                            "filename": filepath.name,
                            "slug": slug,
                            "title": title,
                            "date": frontmatter.get("date", ""),
                            "tags": tags,
                            "source": source,
                            "score": score,
                            "matched": matched_terms,
                            "preview": body[:150] + "..." if len(body) > 150 else body,
                        }
                    )

            except OSError as e:
                logger.warning("Failed to read %s: %s", filepath, e)
                continue

        # Sort by score and limit
        results.sort(key=lambda x: x["score"], reverse=True)
        results = results[:limit]

        if not results:
            return ToolResult(
                success=True,
                message=f"No summaries found matching '{query}'.",
                data={"results": [], "total": 0},
            )

        # Format output
        lines = [f"Found {len(results)} summaries matching '{query}':\n"]
        for r in results:
            tags = r.get("tags") or []
            if isinstance(tags, str):
                tags_str = tags
            elif isinstance(tags, (list, tuple)):
                tags_str = ", ".join(str(t) for t in tags)
            else:
                tags_str = str(tags) if tags else ""
            tags_display = f" [{tags_str}]" if tags_str else ""
            lines.append(f"- **{r['title']}** ({r['date']}) `{r['slug']}`{tags_display}")
            lines.append(f"  {r['preview']}")

        return ToolResult(
            success=True,
            message="\n".join(lines),
            data={"results": results, "total": len(results)},
        )


class ReadSummaryTool(Tool):
    """
    Tool to read the content of an existing summary.

    Returns the full content of a summary note given its title or filename.
    """

    @property
    def name(self) -> str:
        return "read_summary"

    @property
    def description(self) -> str:
        return (
            "Read the full content of an existing summary note. "
            "Provide the title or filename to retrieve its content. "
            "Use this when the user wants to see details of a specific summary."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title or filename of the summary to read",
                },
            },
            "required": ["title"],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Read the content of a summary.

        Args:
            config: Application configuration.
            progress_callback: Optional callback for reporting progress.
            **kwargs: Tool parameters including:
                - title: Title or filename of the summary (required).

        Returns:
            ToolResult with summary content.
        """
        title = kwargs.get("title", "")

        if not title:
            return ToolResult(
                success=False,
                message="Summary title is required",
                error="Missing 'title' parameter",
            )

        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set.",
            )

        summaries_path = config.vault_path / config.out_folder
        if not summaries_path.exists():
            return ToolResult(
                success=False,
                message="Summaries folder not found",
                error="No summaries have been created yet.",
            )

        # Normalize the input: remove .md if present
        title_normalized = title.rstrip(".md").lower()

        # Try to find the summary
        found_path: Path | None = None

        for filepath in summaries_path.glob("*.md"):
            # Check exact filename match (with or without .md)
            if (
                filepath.name.lower() == title_normalized
                or filepath.name.lower() == f"{title_normalized}.md"
            ):
                found_path = filepath
                break
            # Check stem match
            if filepath.stem.lower() == title_normalized:
                found_path = filepath
                break
            # Check if stem ends with -{slug} (handles YYYY-MM-DD-slug.md format)
            if filepath.stem.lower().endswith(f"-{title_normalized}"):
                found_path = filepath
                break

            # Check title in frontmatter
            try:
                content = filepath.read_text(encoding="utf-8")
                frontmatter = _extract_frontmatter(content)
                file_title = frontmatter.get("title", "").lower()
                if file_title and title_normalized in file_title:
                    found_path = filepath
                    break
            except OSError:
                continue

        if not found_path:
            # Try partial match on filename
            for filepath in summaries_path.glob("*.md"):
                if title_normalized in filepath.stem.lower():
                    found_path = filepath
                    break

        if not found_path:
            return ToolResult(
                success=False,
                message=f"Summary not found: {title}",
                error="No summary matches the given title.",
            )

        # Read and return content
        try:
            content = found_path.read_text(encoding="utf-8")
            frontmatter = _extract_frontmatter(content)
            body = _get_body_content(content)

            # Build response
            file_title = frontmatter.get("title", found_path.stem)
            source = frontmatter.get("source", "")
            date = frontmatter.get("date", "")
            tags = frontmatter.get("tags", [])

            header = f"# {file_title}\n\n"
            if source:
                header += f"**Source**: {source}\n"
            if date:
                header += f"**Date**: {date}\n"
            if tags:
                tags_display = tags if isinstance(tags, str) else ", ".join(str(t) for t in tags)
                header += f"**Tags**: {tags_display}\n"
            header += "\n---\n\n"

            return ToolResult(
                success=True,
                message=header + body,
                data={
                    "filename": found_path.name,
                    "title": file_title,
                    "source": source,
                    "date": date,
                    "tags": tags,
                    "content": body,
                },
            )

        except OSError as e:
            return ToolResult(
                success=False,
                message=f"Failed to read summary: {e}",
                error=str(e),
            )
