"""
Protocol defining the interface for LLM clients.

This module defines the consistent interface that all LLM client
implementations must follow, enabling seamless switching between
different providers (Gemini, Ollama, etc.).
"""

from typing import Protocol

from summarize_links.models import SummaryResult

__all__ = ["SummarizerProtocol"]


class SummarizerProtocol(Protocol):
    """Protocol defining the interface for content summarizers."""

    def summarize(self, content: str, url: str, title: str | None = None) -> str:
        """
        Summarize content from a web page (legacy interface).

        Args:
            content: The text content to summarize.
            url: The source URL for attribution.
            title: Optional page title.

        Returns:
            Markdown-formatted summary.
        """
        ...

    def summarize_with_metadata(
        self, content: str, url: str, title: str | None = None
    ) -> SummaryResult:
        """
        Summarize content and return structured result with tags.

        Args:
            content: The text content to summarize.
            url: The source URL for attribution.
            title: Optional page title.

        Returns:
            SummaryResult with content, suggested tags, and content type.
        """
        ...
