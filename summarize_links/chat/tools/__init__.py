"""
Chat tools module for function calling.

This package provides tools that the LLM can invoke to perform
actions like summarizing URLs, searching the vault, etc.

Tools follow a common protocol and are registered in a central registry.
"""

from summarize_links.chat.tools.base import (
    Tool,
    ToolRegistry,
    ToolResult,
    get_default_registry,
)
from summarize_links.chat.tools.filesystem import (
    AddTextToNoteTool,
    CleanWhitespaceTool,
    ReadNoteTool,
    RemoveLineFromNoteTool,
    RemoveUrlFromNoteTool,
)
from summarize_links.chat.tools.notes import FindUrlsInNotesTool
from summarize_links.chat.tools.summarize import ResummarizeTool, SummarizeUrlTool
from summarize_links.chat.tools.system import GetRateLimitStatusTool, GetVaultStatusTool
from summarize_links.chat.tools.vault import (
    ListSummariesTool,
    ReadSummaryTool,
    SearchVaultTool,
)

__all__ = [
    # Base classes
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "get_default_registry",
    # Summarization tools
    "SummarizeUrlTool",
    "ResummarizeTool",
    # Vault tools
    "ListSummariesTool",
    "SearchVaultTool",
    "ReadSummaryTool",
    # Daily notes tools
    "FindUrlsInNotesTool",
    # File system tools
    "CleanWhitespaceTool",
    "RemoveUrlFromNoteTool",
    "RemoveLineFromNoteTool",
    "AddTextToNoteTool",
    "ReadNoteTool",
    # System tools
    "GetRateLimitStatusTool",
    "GetVaultStatusTool",
]
