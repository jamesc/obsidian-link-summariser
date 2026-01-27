"""
Rich output formatting for the chat CLI.

This module provides formatted output using the Rich library,
including markdown rendering, progress indicators, and tables.
"""

import logging
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

__all__ = [
    "ChatFormatter",
]

logger = logging.getLogger(__name__)


class ChatFormatter:
    """
    Handles formatted output for the chat CLI.

    Provides methods for rendering markdown, showing progress,
    displaying tables, and formatting assistant responses.
    """

    def __init__(self, console: Console | None = None) -> None:
        """
        Initialize the formatter.

        Args:
            console: Rich Console instance. Creates one if not provided.
        """
        self.console = console or Console()
        self._progress: Progress | None = None
        self._live: Live | None = None

    def print_welcome(self) -> None:
        """Print welcome message when starting chat."""
        welcome = Panel(
            Text.from_markup(
                "[bold blue]Obsidian Link Summarizer Chat[/]\n\n"
                "Chat with me to summarize web pages and manage your vault.\n"
                "Type [bold]/help[/] for commands, or [bold]/quit[/] to exit."
            ),
            border_style="blue",
        )
        self.console.print(welcome)
        self.console.print()

    def print_user_prompt(self) -> None:
        """Print the user input prompt."""
        self.console.print("[bold green]You:[/] ", end="")

    def print_assistant_label(self) -> None:
        """Print the assistant label before response."""
        self.console.print()
        self.console.print("[bold blue]Assistant:[/]")

    def print_assistant_response(self, response: str) -> None:
        """
        Print an assistant response with markdown formatting.

        Args:
            response: The response text to display.
        """
        self.print_assistant_label()
        # Render as markdown for nice formatting
        md = Markdown(response)
        self.console.print(md)
        self.console.print()

    def print_error(self, message: str) -> None:
        """
        Print an error message.

        Args:
            message: Error message to display.
        """
        self.console.print(f"[bold red]Error:[/] {message}")
        self.console.print()

    def print_warning(self, message: str) -> None:
        """
        Print a warning message.

        Args:
            message: Warning message to display.
        """
        self.console.print(f"[yellow]Warning:[/] {message}")

    def print_info(self, message: str) -> None:
        """
        Print an info message.

        Args:
            message: Info message to display.
        """
        self.console.print(f"[cyan]{message}[/]")

    def print_success(self, message: str) -> None:
        """
        Print a success message.

        Args:
            message: Success message to display.
        """
        self.console.print(f"[green]✓[/] {message}")

    def print_tool_start(self, tool_name: str, description: str) -> None:
        """
        Print that a tool is starting execution.

        Args:
            tool_name: Name of the tool.
            description: What the tool is doing.
        """
        self.console.print(f"[dim]→ {description}...[/]")

    def print_tool_result(self, tool_name: str, success: bool, message: str) -> None:
        """
        Print the result of a tool execution.

        Args:
            tool_name: Name of the tool.
            success: Whether the tool succeeded.
            message: Result message.
        """
        if success:
            self.console.print(f"[green]✓[/] {message}")
        else:
            self.console.print(f"[red]✗[/] {message}")

    def print_markdown(self, text: str) -> None:
        """
        Print text as formatted markdown.

        Args:
            text: Markdown text to render.
        """
        md = Markdown(text)
        self.console.print(md)

    def print_help(self) -> None:
        """Print help information about available commands."""
        help_text = """
## Available Commands

| Command | Description |
|---------|-------------|
| `/help` | Show this help message |
| `/clear` | Clear conversation history |
| `/quit` or `/exit` | Exit the chat |
| `/status` | Show rate limit status |

## Usage Examples

- **Summarize a URL**: Just paste a URL or say "summarize https://example.com"
- **Search summaries**: "What summaries do I have about Python?"
- **Find URLs**: "Show me links from today's note"

## Tips

- URLs are automatically detected in your messages
- Use tags like #python when summarizing to categorize
- The assistant remembers context from earlier in the conversation
"""
        self.print_markdown(help_text)

    def print_table(
        self,
        title: str,
        columns: list[str],
        rows: list[list[Any]],
    ) -> None:
        """
        Print a formatted table.

        Args:
            title: Table title.
            columns: Column headers.
            rows: Table data rows.
        """
        table = Table(title=title)
        for col in columns:
            table.add_column(col)
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        self.console.print(table)
        self.console.print()

    def start_progress(self, description: str) -> None:
        """
        Start a progress spinner.

        Args:
            description: What is in progress.
        """
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        )
        self._progress.start()
        self._progress.add_task(description=description, total=None)

    def update_progress(self, description: str) -> None:
        """
        Update the progress description.

        Args:
            description: New description.
        """
        if self._progress and self._progress.tasks:
            self._progress.update(self._progress.tasks[0].id, description=description)

    def stop_progress(self) -> None:
        """Stop and clear the progress spinner."""
        if self._progress:
            self._progress.stop()
            self._progress = None

    def print_goodbye(self) -> None:
        """Print goodbye message when exiting."""
        self.console.print()
        self.console.print("[dim]Goodbye![/]")
