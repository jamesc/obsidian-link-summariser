"""
Base classes and registry for chat tools.

This module defines:
- Tool protocol/interface
- ToolResult for consistent return values
- ToolRegistry for tool discovery and execution
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from summarize_links.config import Config

__all__ = [
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "get_default_registry",
    "ProgressCallback",
]

logger = logging.getLogger(__name__)

# Type for progress callback (called during long operations)
# Arguments: (stage: str, detail: str) - e.g., ("Fetching", "https://example.com")
ProgressCallback = Callable[[str, str], None] | None


@dataclass
class ToolResult:
    """
    Result from executing a tool.

    Attributes:
        success: Whether the tool executed successfully.
        message: Human-readable result message.
        data: Optional structured data from the tool.
        error: Error message if success is False.
    """

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_content(self) -> str:
        """
        Convert result to content string for LLM.

        Returns:
            String representation for the LLM to process.
        """
        if self.success:
            return self.message
        else:
            return f"Error: {self.error or self.message}"


class Tool(ABC):
    """
    Abstract base class for chat tools.

    Tools are functions that the LLM can call to perform actions.
    Each tool has a name, description, and parameter schema.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for the tool."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does (for LLM)."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for the tool's parameters."""
        ...

    @abstractmethod
    def execute(
        self,
        config: Config,
        progress_callback: "ProgressCallback" = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Execute the tool with the given parameters.

        Args:
            config: Application configuration.
            progress_callback: Optional callback for reporting progress.
            **kwargs: Tool-specific parameters.

        Returns:
            ToolResult with success status and message.
        """
        ...

    def to_schema(self) -> dict[str, Any]:
        """
        Convert tool to JSON schema for LLM function calling.

        Returns:
            Dict with name, description, and parameters schema.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """
    Registry for chat tools.

    Manages tool registration, discovery, and execution.
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._tools: dict[str, Tool] = {}
        logger.debug("Initialized ToolRegistry")

    def register(self, tool: Tool) -> None:
        """
        Register a tool.

        Args:
            tool: Tool instance to register.

        Raises:
            ValueError: If a tool with the same name is already registered.
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        """
        Get a tool by name.

        Args:
            name: Tool name.

        Returns:
            Tool instance or None if not found.
        """
        return self._tools.get(name)

    def execute(
        self,
        name: str,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Execute a tool by name.

        Args:
            name: Tool name.
            config: Application configuration.
            progress_callback: Optional callback for reporting progress.
            **kwargs: Tool parameters.

        Returns:
            ToolResult from the tool execution.
        """
        tool = self.get(name)
        if not tool:
            logger.warning("Unknown tool requested: %s", name)
            return ToolResult(
                success=False,
                message=f"Unknown tool: {name}",
                error=f"Tool '{name}' is not registered",
            )

        try:
            logger.debug("Executing tool: %s with params: %s", name, kwargs)
            result = tool.execute(config, progress_callback=progress_callback, **kwargs)
            logger.debug("Tool %s completed: success=%s", name, result.success)
            return result
        except Exception as e:
            logger.exception("Tool %s failed with exception", name)
            return ToolResult(
                success=False,
                message=f"Tool execution failed: {e}",
                error=str(e),
            )

    def list_tools(self) -> list[Tool]:
        """
        Get all registered tools.

        Returns:
            List of registered Tool instances.
        """
        return list(self._tools.values())

    def get_schemas(self) -> list[dict[str, Any]]:
        """
        Get JSON schemas for all tools (OpenAI format).

        Returns:
            List of tool schemas for LLM function calling.
        """
        return [tool.to_schema() for tool in self._tools.values()]

    def __len__(self) -> int:
        """Return number of registered tools."""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools


# Global default registry instance
_default_registry: ToolRegistry | None = None


def get_default_registry() -> ToolRegistry:
    """
    Get the default tool registry with standard tools registered.

    Returns:
        ToolRegistry with default tools.
    """
    global _default_registry

    if _default_registry is None:
        _default_registry = ToolRegistry()

        # Import and register default tools
        from summarize_links.chat.tools.filesystem import (
            AddTextToNoteTool,
            CleanWhitespaceTool,
            ReadNoteTool,
            RemoveLineFromNoteTool,
            RemoveUrlFromNoteTool,
        )
        from summarize_links.chat.tools.notes import FindUrlsInNotesTool
        from summarize_links.chat.tools.summarize import ResummarizeTool, SummarizeUrlTool
        from summarize_links.chat.tools.system import (
            GetRateLimitStatusTool,
            GetVaultStatusTool,
        )
        from summarize_links.chat.tools.vault import (
            ListSummariesTool,
            ReadSummaryTool,
            SearchVaultTool,
        )

        # Register all tools
        _default_registry.register(SummarizeUrlTool())
        _default_registry.register(ResummarizeTool())
        _default_registry.register(ListSummariesTool())
        _default_registry.register(SearchVaultTool())
        _default_registry.register(ReadSummaryTool())
        _default_registry.register(FindUrlsInNotesTool())
        _default_registry.register(GetRateLimitStatusTool())
        _default_registry.register(GetVaultStatusTool())

        # File system tools
        _default_registry.register(CleanWhitespaceTool())
        _default_registry.register(RemoveUrlFromNoteTool())
        _default_registry.register(RemoveLineFromNoteTool())
        _default_registry.register(AddTextToNoteTool())
        _default_registry.register(ReadNoteTool())

        logger.debug("Initialized default registry with %d tools", len(_default_registry))

    return _default_registry
