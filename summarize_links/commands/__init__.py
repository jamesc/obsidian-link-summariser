"""
Command handlers for the Obsidian Link Summarizer CLI.

Each command is implemented in its own module for better maintainability
and testability. Command handlers receive a Config object and return an
exit code (0 for success, non-zero for errors).
"""

from summarize_links.commands.chat import run_chat_tui
from summarize_links.commands.clean import cmd_clean
from summarize_links.commands.eval import cmd_eval
from summarize_links.commands.from_note import cmd_from_note, cmd_from_note_all
from summarize_links.commands.list import cmd_list
from summarize_links.commands.resummarize import cmd_resummarize
from summarize_links.commands.status import cmd_status
from summarize_links.commands.summaries import cmd_summaries
from summarize_links.commands.urls import cmd_urls

__all__ = [
    "cmd_clean",
    "cmd_eval",
    "cmd_from_note",
    "cmd_from_note_all",
    "cmd_urls",
    "cmd_list",
    "cmd_status",
    "cmd_summaries",
    "cmd_resummarize",
    "run_chat_tui",
]
