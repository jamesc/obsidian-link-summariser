"""
Tests for the chat formatter module.
"""

from io import StringIO

import pytest
from rich.console import Console

from summarize_links.chat.formatter import ChatFormatter


class TestChatFormatterInit:
    """Tests for ChatFormatter initialization."""

    def test_creates_default_console(self) -> None:
        """Test that a default console is created."""
        formatter = ChatFormatter()
        assert formatter.console is not None
        assert isinstance(formatter.console, Console)

    def test_uses_provided_console(self) -> None:
        """Test that provided console is used."""
        custom_console = Console()
        formatter = ChatFormatter(console=custom_console)
        assert formatter.console is custom_console

    def test_initial_state(self) -> None:
        """Test initial state has no progress."""
        formatter = ChatFormatter()
        assert formatter._progress is None
        assert formatter._live is None


class TestChatFormatterMessages:
    """Tests for message formatting methods."""

    @pytest.fixture
    def formatter(self) -> ChatFormatter:
        """Create a formatter with captured output."""
        console = Console(file=StringIO(), force_terminal=True)
        return ChatFormatter(console=console)

    def test_print_welcome(self, formatter: ChatFormatter) -> None:
        """Test welcome message output."""
        formatter.print_welcome()
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "Obsidian Link Summarizer" in output
        assert "/help" in output
        assert "/quit" in output

    def test_print_user_prompt(self, formatter: ChatFormatter) -> None:
        """Test user prompt output."""
        formatter.print_user_prompt()
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "You:" in output

    def test_print_assistant_label(self, formatter: ChatFormatter) -> None:
        """Test assistant label output."""
        formatter.print_assistant_label()
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "Assistant:" in output

    def test_print_assistant_response(self, formatter: ChatFormatter) -> None:
        """Test assistant response with markdown."""
        formatter.print_assistant_response("**Bold** text")
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "Assistant:" in output
        assert "Bold" in output

    def test_print_error(self, formatter: ChatFormatter) -> None:
        """Test error message output."""
        formatter.print_error("Something went wrong")
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "Error:" in output
        assert "Something went wrong" in output

    def test_print_warning(self, formatter: ChatFormatter) -> None:
        """Test warning message output."""
        formatter.print_warning("Be careful")
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "Be careful" in output

    def test_print_info(self, formatter: ChatFormatter) -> None:
        """Test info message output."""
        formatter.print_info("FYI")
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "FYI" in output

    def test_print_success(self, formatter: ChatFormatter) -> None:
        """Test success message output."""
        formatter.print_success("It worked")
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "It worked" in output
        assert "✓" in output


class TestChatFormatterTools:
    """Tests for tool-related formatting methods."""

    @pytest.fixture
    def formatter(self) -> ChatFormatter:
        """Create a formatter with captured output."""
        console = Console(file=StringIO(), force_terminal=True)
        return ChatFormatter(console=console)

    def test_print_tool_start(self, formatter: ChatFormatter) -> None:
        """Test tool start message."""
        formatter.print_tool_start("summarize_url", "Summarizing URL")
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "Summarizing URL" in output
        assert "→" in output

    def test_print_tool_result_success(self, formatter: ChatFormatter) -> None:
        """Test successful tool result."""
        formatter.print_tool_result("summarize_url", True, "Summary saved")
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "Summary saved" in output
        assert "✓" in output

    def test_print_tool_result_failure(self, formatter: ChatFormatter) -> None:
        """Test failed tool result."""
        formatter.print_tool_result("summarize_url", False, "Failed to fetch")
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "Failed to fetch" in output
        assert "✗" in output


class TestChatFormatterMarkdown:
    """Tests for markdown rendering."""

    @pytest.fixture
    def formatter(self) -> ChatFormatter:
        """Create a formatter with captured output."""
        console = Console(file=StringIO(), force_terminal=True)
        return ChatFormatter(console=console)

    def test_print_markdown_simple(self, formatter: ChatFormatter) -> None:
        """Test simple markdown rendering."""
        formatter.print_markdown("# Heading\n\nParagraph text.")
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "Heading" in output
        assert "Paragraph" in output

    def test_print_help(self, formatter: ChatFormatter) -> None:
        """Test help output contains commands."""
        formatter.print_help()
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "/help" in output
        assert "/clear" in output
        assert "/quit" in output
        assert "/status" in output


class TestChatFormatterTable:
    """Tests for table formatting."""

    @pytest.fixture
    def formatter(self) -> ChatFormatter:
        """Create a formatter with captured output."""
        console = Console(file=StringIO(), force_terminal=True)
        return ChatFormatter(console=console)

    def test_print_table(self, formatter: ChatFormatter) -> None:
        """Test table output."""
        formatter.print_table(
            title="Test Table",
            columns=["Name", "Value"],
            rows=[["foo", "bar"], ["baz", "qux"]],
        )
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        assert "Test Table" in output
        assert "Name" in output
        assert "foo" in output
        assert "baz" in output

    def test_print_table_empty_rows(self, formatter: ChatFormatter) -> None:
        """Test table with no rows."""
        formatter.print_table(
            title="Empty Table",
            columns=["A", "B"],
            rows=[],
        )
        output = formatter.console.file.getvalue()  # type: ignore[attr-defined]
        # Title may be split across lines in narrow console, check for parts
        assert "Empty" in output or "Table" in output


class TestChatFormatterProgress:
    """Tests for progress indicator methods."""

    @pytest.fixture
    def formatter(self) -> ChatFormatter:
        """Create a formatter with captured output."""
        console = Console(file=StringIO(), force_terminal=True, width=80)
        return ChatFormatter(console=console)

    def test_start_progress(self, formatter: ChatFormatter) -> None:
        """Test starting progress spinner."""
        formatter.start_progress("Loading...")
        assert formatter._progress is not None
        formatter.stop_progress()

    def test_stop_progress_clears_state(self, formatter: ChatFormatter) -> None:
        """Test stopping progress clears state."""
        formatter.start_progress("Working...")
        formatter.stop_progress()
        assert formatter._progress is None

    def test_stop_progress_when_not_started(self, formatter: ChatFormatter) -> None:
        """Test stopping when no progress is active."""
        # Should not raise
        formatter.stop_progress()
        assert formatter._progress is None

    def test_update_progress(self, formatter: ChatFormatter) -> None:
        """Test updating progress description."""
        formatter.start_progress("Step 1")
        formatter.update_progress("Step 2")
        # Verify progress still active
        assert formatter._progress is not None
        formatter.stop_progress()

    def test_update_progress_when_not_started(self, formatter: ChatFormatter) -> None:
        """Test updating when no progress is active."""
        # Should not raise
        formatter.update_progress("Update without start")


class TestChatFormatterGoodbye:
    """Tests for goodbye message."""

    def test_print_goodbye(self) -> None:
        """Test goodbye message output."""
        console = Console(file=StringIO(), force_terminal=True)
        formatter = ChatFormatter(console=console)
        formatter.print_goodbye()
        output = console.file.getvalue()  # type: ignore[attr-defined]
        assert "Goodbye" in output
