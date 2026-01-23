"""
Chat command handler for the CLI.

This module provides the interactive chat interface for conversational
interaction with the summarizer using a full-featured Textual TUI.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from summarize_links.config import Config

__all__ = [
    "run_chat_tui",
]


def run_chat_tui(config: "Config") -> int:
    """
    Run the full Textual TUI chat interface.

    This is the default chat mode, providing:
    - Scrollable message history
    - Multi-line input support (via input field)
    - Command history (up/down arrows)
    - Keyboard shortcuts
    - Status bar

    Args:
        config: Application configuration.

    Returns:
        Exit code (0 for success).
    """
    from summarize_links.chat.tui import run_chat_tui as _run_tui

    return _run_tui(config)
