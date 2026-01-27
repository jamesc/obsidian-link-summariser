"""
URL summarization tool for the chat CLI.

This tool fetches a web page and creates an AI-generated summary
in the Obsidian vault. LLM summarization calls are traced via Langfuse
for visibility in the session trace.
"""

import contextlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from summarize_links.chat.tools.base import ProgressCallback, Tool, ToolResult
from summarize_links.config import Config
from summarize_links.constants import CHAT_URL_PATTERN
from summarize_links.exceptions import (
    ContentExtractionError,
    ContentFetchError,
    OllamaAPIError,
    RateLimitError,
    URLValidationError,
)
from summarize_links.extract import fetch_and_extract_metadata
from summarize_links.langfuse_tracer import get_tracer
from summarize_links.llm import create_llm_client
from summarize_links.models import UrlWithContext
from summarize_links.notes import (
    add_summary_link_to_daily_note,
    remove_url_line_from_note,
    slug_from_url,
    summary_exists,
    write_summary_note_with_metadata,
)
from summarize_links.utils.frontmatter import get_frontmatter_field

__all__ = [
    "SummarizeUrlTool",
    "ResummarizeTool",
]

logger = logging.getLogger(__name__)


def extract_url_from_text(text: str) -> str | None:
    """
    Extract the first URL from text.

    Handles URLs with or without protocol, adding https:// if missing.

    Args:
        text: Text that may contain a URL.

    Returns:
        Extracted and normalized URL, or None if no URL found.
    """
    match = CHAT_URL_PATTERN.search(text)
    if not match:
        return None

    url = match.group(0)

    # Add protocol if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Clean up common trailing characters
    url = url.rstrip(".,;:!?")

    return url


class SummarizeUrlTool(Tool):
    """
    Tool to summarize a URL and save it to the vault.

    Fetches web page content, generates an AI summary, and writes
    a formatted markdown note to the Obsidian vault.
    """

    @property
    def name(self) -> str:
        return "summarize_url"

    @property
    def description(self) -> str:
        return (
            "Fetch a web page and create an AI-generated summary in the Obsidian vault. "
            "Use this when the user wants to summarize a URL or web page."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to summarize (must be a valid web address)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags to add to the summary note",
                },
            },
            "required": ["url"],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Summarize a URL and save it to the vault.

        Args:
            config: Application configuration.
            progress_callback: Optional callback for reporting progress.
            **kwargs: Tool parameters including:
                - url: URL to summarize (required).
                - tags: Optional tags to add to the summary.

        Returns:
            ToolResult with success status and summary info.
        """
        # Extract parameters
        url: str = kwargs.get("url", "")
        tags: list[str] | None = kwargs.get("tags")

        if not url:
            return ToolResult(
                success=False,
                message="URL is required",
                error="Missing 'url' parameter",
            )

        # Normalize URL
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        logger.info("Summarizing URL: %s", url)

        # Check if vault is configured
        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set. Use --vault or set DEFAULT_VAULT_PATH.",
            )

        slug = slug_from_url(url)

        # Check if summary already exists
        if not config.force and summary_exists(config.vault_path, config.out_folder, url):
            return ToolResult(
                success=True,
                message=f"Summary already exists: {slug}.md",
                data={"slug": slug, "skipped": True, "url": url},
            )

        # Create LLM client
        try:
            client = create_llm_client(
                model=config.model,
                provider=config.model_provider,
                gemini_api_key=config.gemini_api_key,
                ollama_endpoint=config.ollama_endpoint,
                azure_api_key=config.azure_api_key,
                azure_endpoint=config.azure_endpoint,
                azure_deployment_name=config.azure_deployment_name,
                azure_api_version=config.azure_api_version,
                state_path=config.vault_path,
                yaml_model_limits=config.model_limits,
            )
        except Exception as e:
            logger.error("Failed to create LLM client: %s", e)
            return ToolResult(
                success=False,
                message=f"Failed to initialize AI model: {e}",
                error=str(e),
            )

        # Fetch and extract content
        if progress_callback:
            progress_callback("Fetching", url)
        try:
            page_metadata = fetch_and_extract_metadata(
                url,
                playwright_enabled=config.playwright_enabled,
                playwright_timeout=config.playwright_timeout,
            )
        except URLValidationError as e:
            return ToolResult(
                success=False,
                message=f"Invalid URL: {e}",
                error=str(e),
            )
        except ContentFetchError as e:
            return ToolResult(
                success=False,
                message=f"Failed to fetch page: {e}",
                error=str(e),
            )
        except ContentExtractionError as e:
            return ToolResult(
                success=False,
                message=f"Failed to extract content: {e}",
                error=str(e),
            )

        # Generate summary with LLM tracing
        if progress_callback:
            progress_callback("Summarizing", page_metadata.title or url)
        tracer = get_tracer()

        # Pre-fetch the Langfuse prompt to ensure it's cached
        # This allows us to link the prompt to the generation trace
        if hasattr(client, "_get_langfuse_prompts"):
            try:
                client._get_langfuse_prompts()
            except Exception as e:
                logger.warning(f"Failed to pre-fetch Langfuse prompt: {e}")

        # Get cached prompt object for linking to trace
        langfuse_prompt = None
        if hasattr(client, "get_cached_prompt"):
            langfuse_prompt = client.get_cached_prompt()

        # Trace the LLM generation (nested under the tool span in chat engine)
        with tracer.trace_generation(
            name="summarize_content",
            input_data={
                "url": url,
                "title": page_metadata.title,
                "content_length": len(page_metadata.content),
                "content_preview": page_metadata.content[:500] + "..."
                if len(page_metadata.content) > 500
                else page_metadata.content,
            },
            metadata={
                "provider": config.model_provider,
                "model": config.model,
            },
            model=config.model,
            prompt=langfuse_prompt,
        ) as generation:
            try:
                summary_result = client.summarize_with_metadata(
                    content=page_metadata.content,
                    url=url,
                    title=page_metadata.title,
                )

                # Update generation with output and usage
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        update_data: dict[str, Any] = {
                            "output": summary_result.raw_response or summary_result.content,
                        }
                        if summary_result.usage_details:
                            update_data["usage_details"] = summary_result.usage_details
                        generation.update(**update_data)

            except RateLimitError as e:
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        generation.update(
                            output={"error": str(e)},
                            metadata={"error": True, "error_type": "rate_limit"},
                        )
                return ToolResult(
                    success=False,
                    message="Rate limited - try again later",
                    error=str(e),
                )
            except OllamaAPIError as e:
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        generation.update(
                            output={"error": str(e)},
                            metadata={"error": True, "error_type": "api_error"},
                        )
                return ToolResult(
                    success=False,
                    message=f"AI model error: {e}",
                    error=str(e),
                )

        # Create URL context with user-provided tags
        url_context = UrlWithContext(
            url=url,
            original_url=url,
            tags=tags or [],
        )

        # Summary succeeded
        summary_status = "success"

        # Write the summary note
        try:
            summary_path = write_summary_note_with_metadata(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=url,
                summary_result=summary_result,
                page_metadata=page_metadata,
                user_tags=url_context.tags,
                date=datetime.now(),
                source_note=None,  # No source note for chat-initiated summaries
                default_tags=config.default_tags,
                overwrite=config.force,
                summary_status=summary_status,
                summary_model=config.model,
                summary_provider=config.model_provider,
                summary_date=datetime.now(),
            )
        except Exception as e:
            logger.error("Failed to write summary note: %s", e)
            return ToolResult(
                success=False,
                message=f"Failed to save summary: {e}",
                error=str(e),
            )

        # Add link to today's daily note
        today_filename = f"{datetime.now().strftime('%Y-%m-%d')}.md"
        try:
            add_summary_link_to_daily_note(
                vault_path=config.vault_path,
                daily_notes_folder=config.daily_notes_folder,
                note_filename=today_filename,
                summary_path=summary_path,
                url=url,
            )
        except Exception as e:
            # Log but don't fail - the summary was created successfully
            logger.warning("Failed to add link to daily note: %s", e)

        # Remove the original URL line from the daily note
        try:
            remove_url_line_from_note(
                vault_path=config.vault_path,
                daily_notes_folder=config.daily_notes_folder,
                note_filename=today_filename,
                url=url,
            )
        except Exception as e:
            # Log but don't fail - the summary was created successfully
            logger.warning("Failed to remove URL from daily note: %s", e)

        # Build success message
        title = page_metadata.title or slug
        content_preview = summary_result.content[:200]
        if len(summary_result.content) > 200:
            content_preview += "..."

        return ToolResult(
            success=True,
            message=f"Created summary: {summary_path.name}\n\n**{title}**\n\n{content_preview}",
            data={
                "slug": slug,
                "path": str(summary_path),
                "title": title,
                "url": url,
                "content_type": summary_result.content_type,
                "tags": summary_result.suggested_tags,
            },
        )


class ResummarizeTool(Tool):
    """
    Tool to re-summarize an existing summary note.

    Finds an existing summary by URL or slug, re-fetches the content,
    and regenerates the summary while preserving the original date.
    """

    @property
    def name(self) -> str:
        return "resummarize"

    @property
    def description(self) -> str:
        return (
            "Re-summarize an existing summary note by URL or slug. "
            "This will re-fetch the web page and generate a new summary, "
            "replacing the existing one while preserving the original date. "
            "Use this when the user wants to update or refresh an existing summary."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": (
                        "The slug or URL of the summary to re-generate. "
                        "Slugs are preferred (e.g., 'example-com-article'). "
                        "Can also be the full source URL."
                    ),
                },
            },
            "required": ["identifier"],
        }

    def _find_summary_by_url_or_slug(
        self, config: Config, url_or_slug: str
    ) -> tuple[str, datetime, str | None] | None:
        """
        Find an existing summary by URL or slug.

        Args:
            config: Application configuration.
            url_or_slug: URL or slug to search for.

        Returns:
            Tuple of (source_url, original_date, source_note) or None if not found.
        """
        if not config.vault_path:
            return None

        summaries_path = config.vault_path / config.out_folder
        if not summaries_path.exists():
            return None

        # Normalize the input: remove .md if present
        slug_or_url = url_or_slug.rstrip(".md")

        # Try to find by slug (files are named YYYY-MM-DD-slug.md)
        # Search for files ending with the slug
        for filepath in summaries_path.glob("*.md"):
            # Check if filename ends with -{slug}.md or is exactly {slug}.md
            if filepath.stem.endswith(f"-{slug_or_url}") or filepath.stem == slug_or_url:
                return self._extract_summary_metadata(filepath)

        # Otherwise search by source URL
        for filepath in summaries_path.glob("*.md"):
            metadata = self._extract_summary_metadata(filepath)
            if metadata and metadata[0] == url_or_slug:
                return metadata

            # Also check normalized URL
            if metadata:
                source_url = metadata[0]
                # Compare without trailing slashes and protocol normalization
                normalized_source = source_url.rstrip("/").replace("http://", "https://")
                normalized_input = url_or_slug.rstrip("/").replace("http://", "https://")
                if not normalized_input.startswith("https://"):
                    normalized_input = "https://" + normalized_input
                if normalized_source == normalized_input:
                    return metadata

        return None

    def _extract_summary_metadata(self, filepath: Path) -> tuple[str, datetime, str | None] | None:
        """
        Extract source URL, original date, and source note from a summary file.

        Args:
            filepath: Path to the summary file.

        Returns:
            Tuple of (source_url, original_date, source_note) or None.
        """
        try:
            content = filepath.read_text(encoding="utf-8")

            # Extract frontmatter fields using centralized utility
            source_url = get_frontmatter_field(content, "source")
            date_str = get_frontmatter_field(content, "date")
            from_field = get_frontmatter_field(content, "from")

            if not source_url or not date_str:
                return None

            # Parse date
            try:
                original_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                return None

            # Extract source note from 'from' field
            source_note = None
            if from_field:
                source_note = from_field.strip('"').strip("'")
                if source_note.startswith("[[") and source_note.endswith("]]"):
                    source_note = source_note[2:-2]
                if source_note and not source_note.endswith(".md"):
                    source_note = f"{source_note}.md"

            return (source_url, original_date, source_note)

        except OSError:
            return None

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Re-summarize an existing summary.

        Args:
            config: Application configuration.
            progress_callback: Optional callback for reporting progress.
            **kwargs: Tool parameters including:
                - identifier: Slug or URL to re-summarize (required).

        Returns:
            ToolResult with success status and summary info.
        """
        # Accept both 'identifier' (new) and 'url' (backward compatibility)
        identifier: str = kwargs.get("identifier", kwargs.get("url", ""))

        if not identifier:
            return ToolResult(
                success=False,
                message="Identifier (slug or URL) is required",
                error="Missing 'identifier' parameter",
            )

        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set. Use --vault or set DEFAULT_VAULT_PATH.",
            )

        logger.info("Searching for summary: %s", identifier)

        # Find the existing summary (by slug or URL)
        metadata = self._find_summary_by_url_or_slug(config, identifier)
        if not metadata:
            return ToolResult(
                success=False,
                message=f"No existing summary found for: {identifier}",
                error="Summary not found. Check the slug or URL is correct.",
            )

        # Extract the actual source URL from the summary metadata
        source_url, original_date, source_note = metadata
        slug = slug_from_url(source_url)

        logger.info(
            "Found summary for %s (date: %s, source: %s)",
            source_url,
            original_date.strftime("%Y-%m-%d"),
            source_note,
        )

        # Create LLM client
        try:
            client = create_llm_client(
                model=config.model,
                provider=config.model_provider,
                gemini_api_key=config.gemini_api_key,
                ollama_endpoint=config.ollama_endpoint,
                azure_api_key=config.azure_api_key,
                azure_endpoint=config.azure_endpoint,
                azure_deployment_name=config.azure_deployment_name,
                azure_api_version=config.azure_api_version,
                state_path=config.vault_path,
                yaml_model_limits=config.model_limits,
            )
        except Exception as e:
            logger.error("Failed to create LLM client: %s", e)
            return ToolResult(
                success=False,
                message=f"Failed to initialize AI model: {e}",
                error=str(e),
            )

        # Fetch and extract content
        if progress_callback:
            progress_callback("Fetching", source_url)
        try:
            page_metadata = fetch_and_extract_metadata(
                source_url,
                playwright_enabled=config.playwright_enabled,
                playwright_timeout=config.playwright_timeout,
            )
        except URLValidationError as e:
            return ToolResult(
                success=False,
                message=f"Invalid URL: {e}",
                error=str(e),
            )
        except ContentFetchError as e:
            return ToolResult(
                success=False,
                message=f"Failed to fetch page: {e}",
                error=str(e),
            )
        except ContentExtractionError as e:
            return ToolResult(
                success=False,
                message=f"Failed to extract content: {e}",
                error=str(e),
            )

        # Generate summary with LLM tracing
        if progress_callback:
            progress_callback("Summarizing", page_metadata.title or source_url)
        tracer = get_tracer()

        # Pre-fetch the Langfuse prompt to ensure it's cached
        # This allows us to link the prompt to the generation trace
        if hasattr(client, "_get_langfuse_prompts"):
            try:
                client._get_langfuse_prompts()
            except Exception as e:
                logger.warning(f"Failed to pre-fetch Langfuse prompt: {e}")

        # Get cached prompt object for linking to trace
        langfuse_prompt = None
        if hasattr(client, "get_cached_prompt"):
            langfuse_prompt = client.get_cached_prompt()

        with tracer.trace_generation(
            name="resummarize_content",
            input_data={
                "url": source_url,
                "title": page_metadata.title,
                "content_length": len(page_metadata.content),
                "original_date": original_date.strftime("%Y-%m-%d"),
            },
            metadata={
                "provider": config.model_provider,
                "model": config.model,
                "is_resummarize": True,
            },
            model=config.model,
            prompt=langfuse_prompt,
        ) as generation:
            try:
                summary_result = client.summarize_with_metadata(
                    content=page_metadata.content,
                    url=source_url,
                    title=page_metadata.title,
                )

                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        update_data: dict[str, Any] = {
                            "output": summary_result.raw_response or summary_result.content,
                        }
                        if summary_result.usage_details:
                            update_data["usage_details"] = summary_result.usage_details
                        generation.update(**update_data)

            except RateLimitError as e:
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        generation.update(
                            output={"error": str(e)},
                            metadata={"error": True, "error_type": "rate_limit"},
                        )
                return ToolResult(
                    success=False,
                    message="Rate limited - try again later",
                    error=str(e),
                )
            except OllamaAPIError as e:
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        generation.update(
                            output={"error": str(e)},
                            metadata={"error": True, "error_type": "api_error"},
                        )
                return ToolResult(
                    success=False,
                    message=f"AI model error: {e}",
                    error=str(e),
                )

        # Summary succeeded
        summary_status = "success"

        # Write the summary note (overwrite existing)
        try:
            summary_path = write_summary_note_with_metadata(
                vault_path=config.vault_path,
                out_folder=config.out_folder,
                url=source_url,
                summary_result=summary_result,
                page_metadata=page_metadata,
                user_tags=[],  # No user tags for resummarize
                date=original_date,  # Preserve original date
                source_note=source_note,  # Preserve source note
                default_tags=config.default_tags,
                overwrite=True,  # Always overwrite for resummarize
                summary_status=summary_status,
                summary_model=config.model,
                summary_provider=config.model_provider,
                summary_date=datetime.now(),  # Update summary date to now
            )
        except Exception as e:
            logger.error("Failed to write summary note: %s", e)
            return ToolResult(
                success=False,
                message=f"Failed to save summary: {e}",
                error=str(e),
            )

        # Build success message
        title = page_metadata.title or slug
        content_preview = summary_result.content[:200]
        if len(summary_result.content) > 200:
            content_preview += "..."

        return ToolResult(
            success=True,
            message=(f"Re-summarized: {summary_path.name}\n\n**{title}**\n\n{content_preview}"),
            data={
                "slug": slug,
                "path": str(summary_path),
                "title": title,
                "url": source_url,
                "original_date": original_date.strftime("%Y-%m-%d"),
                "content_type": summary_result.content_type,
                "tags": summary_result.suggested_tags,
            },
        )
