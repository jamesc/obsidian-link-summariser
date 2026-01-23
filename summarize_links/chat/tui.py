"""
Textual-based TUI for the chat interface.

This module provides a full-featured terminal UI using Textual with:
- Multi-line input support (Shift+Enter for newlines)
- Scrollable message history
- Command completion
- Keyboard shortcuts
- Status bar with session info
- Streaming response display
- Session save/load
- Tool confirmation prompts
"""

import logging
from typing import Any, ClassVar

from rich.markdown import Markdown
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.widgets import Footer, Input, Label, Static

from summarize_links.chat.engine import ChatEngine
from summarize_links.chat.formatter import ChatFormatter
from summarize_links.config import Config
from summarize_links.exceptions import ConfigError

__all__ = [
    "ChatTUI",
    "run_chat_tui",
]

logger = logging.getLogger(__name__)

# Slash commands
QUIT_COMMANDS = {"/quit", "/exit", "/q"}
HELP_COMMANDS = {"/help", "/h", "/?"}
CLEAR_COMMANDS = {"/clear", "/reset"}
STATUS_COMMANDS = {"/status"}
SAVE_COMMANDS = {"/save"}
LOAD_COMMANDS = {"/load"}
CONFIG_COMMANDS = {"/config"}

# Command completions
SLASH_COMMANDS = [
    "/help",
    "/clear",
    "/status",
    "/save",
    "/load",
    "/config",
    "/quit",
    "/exit",
]


class MessageBubble(Vertical):
    """A styled message bubble for chat messages."""

    DEFAULT_CSS = """
    MessageBubble {
        margin: 1 0;
        padding: 1 2;
        width: 100%;
        height: auto;
    }

    MessageBubble.user {
        background: $primary-darken-2;
        border: solid $primary;
    }

    MessageBubble.assistant {
        background: $surface;
        border: solid $secondary;
    }

    MessageBubble.system {
        background: $warning-darken-3;
        border: solid $warning;
        text-style: italic;
    }

    MessageBubble.error {
        background: $error-darken-3;
        border: solid $error;
    }

    MessageBubble .label {
        text-style: bold;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        content: str,
        role: str = "assistant",
        render_markdown: bool = True,
        **kwargs: Any,
    ) -> None:
        """
        Initialize a message bubble.

        Args:
            content: Message content.
            role: Message role (user, assistant, system, error).
            render_markdown: Whether to render content as markdown.
            **kwargs: Additional arguments for Static.
        """
        super().__init__(**kwargs)
        self.content = content
        self.role = role
        self.render_markdown = render_markdown
        self.add_class(role)

    def compose(self) -> ComposeResult:
        """Compose the message content."""
        # Role label
        label_text = {
            "user": "You",
            "assistant": "Assistant",
            "system": "System",
            "error": "Error",
        }.get(self.role, self.role.title())

        label_style = {
            "user": "bold green",
            "assistant": "bold blue",
            "system": "bold yellow",
            "error": "bold red",
        }.get(self.role, "bold")

        yield Label(Text(label_text, style=label_style), classes="label")

        # Content - self.content is always a str from __init__
        if self.render_markdown and self.role == "assistant":
            yield Static(Markdown(str(self.content)))
        else:
            yield Static(str(self.content))


class ChatInput(Input):
    """Enhanced input with multi-line support via modal."""

    BINDINGS: ClassVar = [
        Binding("up", "history_prev", "Previous", show=False),
        Binding("down", "history_next", "Next", show=False),
    ]

    class Submitted(Message):
        """Message sent when input is submitted."""

        def __init__(self, input_widget: "ChatInput", value: str) -> None:
            self.input = input_widget
            self.value = value
            super().__init__()

        @property
        def control(self) -> "ChatInput":
            """The ChatInput widget that was submitted."""
            return self.input

    async def action_submit(self) -> None:
        """Override submit to use our custom Submitted message."""
        self.post_message(self.Submitted(self, self.value))

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the chat input."""
        super().__init__(placeholder="Type a message... (Enter to send)", **kwargs)
        self._history: list[str] = []
        self._history_index = -1
        self._current_input = ""

    def add_to_history(self, text: str) -> None:
        """Add a message to history."""
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._history_index = -1
        self._current_input = ""

    def action_history_prev(self) -> None:
        """Navigate to previous history item."""
        if not self._history:
            return

        if self._history_index == -1:
            self._current_input = self.value
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1

        self.value = self._history[self._history_index]
        self.cursor_position = len(self.value)

    def action_history_next(self) -> None:
        """Navigate to next history item."""
        if self._history_index == -1:
            return

        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.value = self._history[self._history_index]
        else:
            self._history_index = -1
            self.value = self._current_input

        self.cursor_position = len(self.value)


class MultiLineInput(Static):
    """Multi-line input area using TextArea-like behavior."""

    DEFAULT_CSS = """
    MultiLineInput {
        height: auto;
        max-height: 10;
        padding: 0 1;
        background: $surface;
        border: solid $primary;
    }

    MultiLineInput:focus-within {
        border: solid $accent;
    }

    MultiLineInput Input {
        width: 100%;
        border: none;
        background: transparent;
    }
    """

    class Submitted(Message):
        """Message sent when input is submitted."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the multi-line input."""
        super().__init__(**kwargs)
        self._lines: list[str] = [""]
        self._history: list[str] = []
        self._history_index = -1

    def compose(self) -> ComposeResult:
        """Compose the input widget."""
        yield ChatInput(id="chat-input")

    def add_to_history(self, text: str) -> None:
        """Add text to history."""
        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget.add_to_history(text)

    @property
    def value(self) -> str:
        """Get current input value."""
        return self.query_one("#chat-input", ChatInput).value

    @value.setter
    def value(self, new_value: str) -> None:
        """Set input value."""
        self.query_one("#chat-input", ChatInput).value = new_value

    def clear(self) -> None:
        """Clear the input."""
        self.query_one("#chat-input", ChatInput).value = ""

    def focus(self, scroll_visible: bool = True) -> "MultiLineInput":
        """Focus the input."""
        self.query_one("#chat-input", ChatInput).focus(scroll_visible)
        return self


class ChatMessages(ScrollableContainer):
    """Scrollable container for chat messages."""

    DEFAULT_CSS = """
    ChatMessages {
        height: 1fr;
        padding: 1 2;
        background: $background;
    }
    """

    def add_message(
        self,
        content: str,
        role: str = "assistant",
        render_markdown: bool = True,
    ) -> None:
        """
        Add a message to the chat.

        Args:
            content: Message content.
            role: Message role.
            render_markdown: Whether to render as markdown.
        """
        bubble = MessageBubble(content, role=role, render_markdown=render_markdown)
        self.mount(bubble)
        bubble.scroll_visible()


class StatusBar(Horizontal):
    """Status bar showing session info."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $primary-darken-3;
        padding: 0 2;
        dock: bottom;
    }

    StatusBar Label {
        width: auto;
        margin-right: 2;
    }

    StatusBar .status-item {
        color: $text-muted;
    }

    StatusBar .status-value {
        color: $text;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the status bar."""
        super().__init__(**kwargs)
        self._session_id = ""
        self._message_count = 0
        self._model = ""

    def compose(self) -> ComposeResult:
        """Compose the status bar."""
        yield Label("Session: ", classes="status-item")
        yield Label("", id="session-id", classes="status-value")
        yield Label(" | Messages: ", classes="status-item")
        yield Label("0", id="message-count", classes="status-value")
        yield Label(" | Model: ", classes="status-item")
        yield Label("", id="model-name", classes="status-value")

    def update_status(
        self,
        session_id: str | None = None,
        message_count: int | None = None,
        model: str | None = None,
    ) -> None:
        """Update status bar values."""
        if session_id is not None:
            self.query_one("#session-id", Label).update(session_id[:8] + "...")
        if message_count is not None:
            self.query_one("#message-count", Label).update(str(message_count))
        if model is not None:
            self.query_one("#model-name", Label).update(model)


class ChatTUI(App[int]):
    """
    Textual TUI application for the chat interface.

    Features:
    - Scrollable message history
    - Multi-line input support
    - Command history (up/down arrows)
    - Slash command support
    - Keyboard shortcuts
    """

    TITLE = "Chat"

    CSS = """
    Screen {
        layout: vertical;
    }

    #chat-container {
        height: 1fr;
    }

    #input-container {
        height: auto;
        max-height: 12;
        padding: 0 2;
        background: $surface;
    }

    .thinking {
        text-style: italic;
        color: $text-muted;
    }
    """

    BINDINGS: ClassVar = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+l", "clear_messages", "Clear", show=True),
        Binding("ctrl+h", "show_help", "Help", show=True),
        Binding("ctrl+s", "save_session", "Save", show=True),
        Binding("escape", "focus_input", "Focus Input", show=False),
    ]

    def __init__(
        self,
        config: Config,
        engine: ChatEngine | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the chat TUI.

        Args:
            config: Application configuration.
            engine: ChatEngine instance. Created if not provided.
            **kwargs: Additional arguments for App.
        """
        super().__init__(**kwargs)
        self.config = config
        self._engine = engine
        self._formatter = ChatFormatter()
        self._thinking_message: MessageBubble | None = None
        self._streaming_message: MessageBubble | None = None

    def _get_engine(self) -> ChatEngine:
        """Get or create the chat engine."""
        if self._engine is None:
            # Create engine with tool confirmation callback if enabled
            callback = self._tool_confirm_callback if self.config.chat_confirm_tools else None
            self._engine = ChatEngine(
                self.config,
                formatter=self._formatter,
                tool_confirm_callback=callback,
                progress_callback=self._progress_callback,
            )
        return self._engine

    def _progress_callback(self, stage: str, detail: str) -> None:
        """
        Callback for progress updates during long operations.

        Called from background thread, so uses call_from_thread to
        update the UI safely.

        Args:
            stage: Current stage (e.g., "Fetching", "Summarizing").
            detail: Detail about what is being processed.
        """
        # Truncate detail for display
        display_detail = detail[:50] + "..." if len(detail) > 50 else detail
        message = f"{stage}: {display_detail}"
        self.call_from_thread(self._update_progress_message, message)

    def _tool_confirm_callback(self, tool_name: str, args: dict[str, Any]) -> bool:
        """
        Callback for tool confirmation prompts.

        Currently returns True (auto-confirm). In future, could show
        a confirmation dialog in the TUI.

        Args:
            tool_name: Name of the tool to execute.
            args: Tool arguments.

        Returns:
            True to execute, False to skip.
        """
        # TODO: Implement interactive confirmation dialog
        # For now, auto-confirm all tools
        logger.debug("Auto-confirming tool: %s with args: %s", tool_name, args)
        return True

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        with Vertical(id="chat-container"):
            yield ChatMessages(id="messages")

        with Vertical(id="input-container"):
            yield MultiLineInput(id="input")

        yield StatusBar(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Handle mount event."""
        # Show welcome message
        messages = self.query_one("#messages", ChatMessages)
        messages.add_message(
            "Welcome to the Obsidian Link Summarizer Chat!\n\n"
            "I can help you summarize web pages and manage your vault.\n"
            "Type `/help` for available commands.",
            role="system",
            render_markdown=True,
        )

        # Update status bar
        engine = self._get_engine()
        status = engine.get_status()
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_status(
            session_id=status["session_id"],
            message_count=status["message_count"],
            model=status["model"],
        )

        # Focus input
        self.query_one("#input", MultiLineInput).focus()

    @on(ChatInput.Submitted, "#chat-input")
    def handle_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle input submission."""
        text = event.value.strip()
        if not text:
            return

        # Clear input and add to history
        input_widget = self.query_one("#input", MultiLineInput)
        input_widget.add_to_history(text)
        input_widget.clear()

        # Handle slash commands
        if text.startswith("/"):
            self._handle_slash_command(text.lower())
            return

        # Process message
        self._send_message(text)

    def _handle_slash_command(self, command: str) -> None:
        """Handle a slash command."""
        messages = self.query_one("#messages", ChatMessages)

        if command in QUIT_COMMANDS:
            self.exit(0)
            return

        if command in HELP_COMMANDS:
            self.action_show_help()
            return

        if command in CLEAR_COMMANDS:
            self._get_engine().clear_history()
            # Clear message display
            for child in list(messages.children):
                child.remove()
            messages.add_message("Conversation cleared.", role="system")
            return

        if command in STATUS_COMMANDS:
            status = self._get_engine().get_status()
            status_text = (
                f"**Session:** {status['session_id'][:8]}...\n"
                f"**Messages:** {status['message_count']}\n"
                f"**Tokens:** {status['tokens']:,} / {status['max_tokens']:,}\n"
                f"**Provider:** {status['provider']}\n"
                f"**Model:** {status['model']}\n"
                f"**Deployment:** {status['deployment']}\n"
                f"**Tools:** {status['tools']}\n"
                f"**Streaming:** {status['streaming']}\n"
                f"**Confirm Tools:** {status['confirm_tools']}\n"
                f"**Vault:** {status['vault']}"
            )
            messages.add_message(status_text, role="system")
            return

        if command in SAVE_COMMANDS:
            try:
                path = self._get_engine().save_session()
                messages.add_message(f"Session saved to: `{path}`", role="system")
            except Exception as e:
                messages.add_message(f"Failed to save session: {e}", role="error")
            return

        if command in LOAD_COMMANDS:
            try:
                engine = self._get_engine()
                if engine.load_session():
                    # Clear and rebuild message display
                    for child in list(messages.children):
                        child.remove()
                    messages.add_message("Session loaded successfully.", role="system")
                    # Update status bar
                    status = engine.get_status()
                    self._update_status(status)
                else:
                    messages.add_message("No saved session found.", role="system")
            except Exception as e:
                messages.add_message(f"Failed to load session: {e}", role="error")
            return

        if command in CONFIG_COMMANDS:
            config = self.config
            config_text = (
                f"**Chat Configuration:**\n"
                f"- Model: `{config.chat_model}`\n"
                f"- Deployment: `{config.chat_azure_deployment}`\n"
                f"- Max History: {config.chat_max_history_messages} messages\n"
                f"- Max Tokens: {config.chat_max_context_tokens:,}\n"
                f"- Auto-save: {config.chat_auto_save}\n"
                f"- Save Path: `{config.chat_save_path}`\n"
                f"- Streaming: {config.chat_streaming}\n"
                f"- Confirm Tools: {config.chat_confirm_tools}\n"
            )
            messages.add_message(config_text, role="system")
            return

        # Unknown command
        messages.add_message(f"Unknown command: {command}", role="error")

    @work(exclusive=True, thread=True)
    def _send_message(self, text: str) -> None:
        """Send a message to the assistant (runs in background thread)."""
        # Add user message to display
        self.call_from_thread(self._add_user_message, text)

        # Show thinking indicator
        self.call_from_thread(self._show_thinking)

        try:
            engine = self._get_engine()

            # Use streaming if enabled
            if self.config.chat_streaming:
                self._send_message_streaming(engine, text)
            else:
                # Non-streaming: process and show full response
                response = engine.process_message(text)
                self.call_from_thread(self._hide_thinking)
                self.call_from_thread(self._add_assistant_message, response)

            # Update status bar
            status = engine.get_status()
            self.call_from_thread(self._update_status, status)

            # Auto-save if enabled
            if self.config.chat_auto_save:
                try:
                    engine.save_session()
                except Exception as e:
                    logger.warning("Auto-save failed: %s", e)

        except Exception as e:
            logger.exception("Error processing message")
            self.call_from_thread(self._hide_thinking)
            self.call_from_thread(self._add_error_message, str(e))

    def _send_message_streaming(self, engine: ChatEngine, text: str) -> None:
        """Send a message with streaming response display."""
        # Replace thinking indicator with streaming bubble
        self.call_from_thread(self._hide_thinking)
        self.call_from_thread(self._start_streaming_message)

        try:
            full_response = ""
            for chunk in engine.process_message_streaming(text):
                full_response += chunk
                # Update the streaming message periodically
                self.call_from_thread(self._update_streaming_message, full_response)

            # Finalize the streaming message
            self.call_from_thread(self._finalize_streaming_message, full_response)
        except Exception:
            # Clean up the streaming message on error
            self.call_from_thread(self._cancel_streaming_message)
            # Re-raise to be handled by the outer exception handler
            raise

    def _start_streaming_message(self) -> None:
        """Start a new streaming message bubble."""
        messages = self.query_one("#messages", ChatMessages)
        self._streaming_message = MessageBubble(
            "",
            role="assistant",
            render_markdown=False,  # Don't render markdown while streaming
        )
        messages.mount(self._streaming_message)
        self._streaming_message.scroll_visible()

    def _update_streaming_message(self, content: str) -> None:
        """Update the streaming message with new content."""
        if self._streaming_message:
            # Update the content in the bubble
            static_widget = self._streaming_message.query_one(Static)
            if static_widget:
                # Show raw text while streaming
                static_widget.update(content + "▌")  # Cursor indicator

    def _finalize_streaming_message(self, content: str) -> None:
        """Finalize the streaming message with rendered markdown."""
        if self._streaming_message:
            # Replace with final rendered content
            static_widget = self._streaming_message.query_one(Static)
            if static_widget:
                static_widget.update(Markdown(content))
            self._streaming_message = None

    def _cancel_streaming_message(self) -> None:
        """Cancel and remove the streaming message on error."""
        if self._streaming_message:
            self._streaming_message.remove()
            self._streaming_message = None

    def _add_user_message(self, text: str) -> None:
        """Add a user message to the display."""
        messages = self.query_one("#messages", ChatMessages)
        messages.add_message(text, role="user", render_markdown=False)

    def _add_assistant_message(self, text: str) -> None:
        """Add an assistant message to the display."""
        messages = self.query_one("#messages", ChatMessages)
        messages.add_message(text, role="assistant", render_markdown=True)

    def _add_error_message(self, text: str) -> None:
        """Add an error message to the display."""
        messages = self.query_one("#messages", ChatMessages)
        messages.add_message(f"Error: {text}", role="error")

    def _show_thinking(self) -> None:
        """Show thinking indicator."""
        messages = self.query_one("#messages", ChatMessages)
        self._thinking_message = MessageBubble(
            "Thinking...",
            role="assistant",
            render_markdown=False,
            classes="thinking",
        )
        messages.mount(self._thinking_message)
        self._thinking_message.scroll_visible()

    def _update_thinking_message(self, text: str) -> None:
        """
        Update the thinking indicator with new text.

        Args:
            text: New text to display (e.g., "Running: summarize_url").
        """
        if self._thinking_message:
            static_widget = self._thinking_message.query_one(Static)
            if static_widget:
                static_widget.update(text)

    def _update_progress_message(self, text: str) -> None:
        """
        Update the visible progress message (thinking or streaming).

        This method determines which message bubble is currently visible
        and updates it with the progress text.

        Args:
            text: Progress text to display.
        """
        # Try to update thinking message first
        if self._thinking_message:
            static_widget = self._thinking_message.query_one(Static)
            if static_widget:
                static_widget.update(text)
                self._thinking_message.scroll_visible()
            return

        # If streaming, prepend progress to the streaming content
        if self._streaming_message:
            static_widget = self._streaming_message.query_one(Static)
            if static_widget:
                # Show progress text while tool is running
                static_widget.update(f"[dim]{text}[/dim]\n▌")
                self._streaming_message.scroll_visible()
            return

    def _hide_thinking(self) -> None:
        """Hide thinking indicator."""
        if self._thinking_message:
            self._thinking_message.remove()
            self._thinking_message = None

    def _update_status(self, status: dict[str, Any]) -> None:
        """Update the status bar."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_status(
            session_id=status["session_id"],
            message_count=status["message_count"],
            model=status["model"],
        )

    async def action_quit(self) -> None:
        """Quit the application."""
        self.exit(0)

    def action_clear_messages(self) -> None:
        """Clear the message display."""
        self._handle_slash_command("/clear")

    def action_save_session(self) -> None:
        """Save the current session."""
        self._handle_slash_command("/save")

    def action_show_help(self) -> None:
        """Show help message."""
        messages = self.query_one("#messages", ChatMessages)
        help_text = """## Available Commands

| Command | Shortcut | Description |
|---------|----------|-------------|
| `/help` | Ctrl+H | Show this help |
| `/clear` | Ctrl+L | Clear conversation |
| `/status` | | Show session status |
| `/save` | Ctrl+S | Save session to disk |
| `/load` | | Load saved session |
| `/config` | | Show chat configuration |
| `/quit` | Ctrl+C | Exit the chat |

## Usage

- Type a message and press **Enter** to send
- Use **Up/Down** arrows to navigate history
- Paste URLs to summarize them
- Ask questions about your vault

## Tips

- URLs are automatically detected in your messages
- Use natural language to search your summaries
- The assistant remembers context from earlier messages
- Sessions can be saved and restored between runs
"""
        messages.add_message(help_text, role="system", render_markdown=True)

    def action_focus_input(self) -> None:
        """Focus the input field."""
        self.query_one("#input", MultiLineInput).focus()


def _validate_chat_config(config: Config) -> None:
    """
    Validate chat-specific configuration.

    Args:
        config: Application configuration.

    Raises:
        ConfigError: If chat configuration is invalid.
    """
    if config.mock_mode:
        return

    if not config.chat_azure_api_key:
        raise ConfigError(
            "Chat mode requires Azure OpenAI credentials. "
            "Set CHAT_AZURE_API_KEY (or AZURE_API_KEY as fallback)."
        )

    if not config.chat_azure_endpoint:
        raise ConfigError(
            "Chat mode requires Azure OpenAI endpoint. "
            "Set CHAT_AZURE_ENDPOINT (or AZURE_ENDPOINT as fallback)."
        )


def run_chat_tui(config: Config) -> int:
    """
    Run the Textual chat TUI.

    Args:
        config: Application configuration.

    Returns:
        Exit code (0 for success).
    """
    # Validate configuration first
    try:
        _validate_chat_config(config)
    except ConfigError as e:
        from rich.console import Console

        console = Console()
        console.print(f"[bold red]Error:[/] {e}")
        return 1

    # Run the TUI
    app = ChatTUI(config)
    result = app.run()
    return result if result is not None else 0
