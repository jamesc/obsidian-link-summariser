"""
Extended tests for the chat TUI module.

Focuses on edge cases, widget behavior, and slash command handling.
"""

from unittest.mock import MagicMock, patch

import pytest

from summarize_links.chat.tui import (
    CONFIG_COMMANDS,
    LOAD_COMMANDS,
    SAVE_COMMANDS,
    SLASH_COMMANDS,
    ChatInput,
    ChatMessages,
    ChatTUI,
    MessageBubble,
    MultiLineInput,
    StatusBar,
)
from summarize_links.config import Config


class TestSlashCommandConstants:
    """Tests for slash command constants."""

    def test_save_commands(self) -> None:
        """Test save commands are defined."""
        assert "/save" in SAVE_COMMANDS

    def test_load_commands(self) -> None:
        """Test load commands are defined."""
        assert "/load" in LOAD_COMMANDS

    def test_config_commands(self) -> None:
        """Test config commands are defined."""
        assert "/config" in CONFIG_COMMANDS

    def test_slash_commands_list(self) -> None:
        """Test that SLASH_COMMANDS list includes common commands."""
        assert "/help" in SLASH_COMMANDS
        assert "/clear" in SLASH_COMMANDS
        assert "/quit" in SLASH_COMMANDS
        assert "/status" in SLASH_COMMANDS


class TestChatInputHistory:
    """Extended tests for ChatInput history functionality."""

    def test_history_navigation_prev_empty(self) -> None:
        """Test navigating previous with no history."""
        input_widget = ChatInput()
        # Note: Cannot call action_history_prev without app context
        # Just verify initial state
        assert input_widget._history_index == -1
        assert input_widget._history == []

    def test_history_navigation_next_not_browsing(self) -> None:
        """Test navigating next when not browsing history."""
        input_widget = ChatInput()
        input_widget.add_to_history("test")
        # Not browsing history
        assert input_widget._history_index == -1
        # Note: Cannot call action_history_next without app context
        # Just verify state
        assert "test" in input_widget._history

    def test_history_stores_items(self) -> None:
        """Test that history stores items correctly."""
        input_widget = ChatInput()
        input_widget.add_to_history("first")
        input_widget.add_to_history("second")
        input_widget.add_to_history("third")

        assert input_widget._history == ["first", "second", "third"]
        assert input_widget._history_index == -1

    def test_history_resets_index_on_add(self) -> None:
        """Test that adding to history resets index."""
        input_widget = ChatInput()
        input_widget.add_to_history("first")
        input_widget._history_index = 0  # Simulate browsing

        input_widget.add_to_history("second")
        # Index should be reset
        assert input_widget._history_index == -1


class TestMessageBubbleCompose:
    """Tests for MessageBubble compose method."""

    def test_compose_user_message(self) -> None:
        """Test composing user message bubble."""
        bubble = MessageBubble("Hello", role="user")
        # compose() returns a generator, convert to list
        children = list(bubble.compose())
        assert len(children) == 2  # Label + content

    def test_compose_assistant_message_with_markdown(self) -> None:
        """Test composing assistant message with markdown."""
        bubble = MessageBubble("**Bold**", role="assistant", render_markdown=True)
        children = list(bubble.compose())
        assert len(children) == 2

    def test_compose_system_message(self) -> None:
        """Test composing system message."""
        bubble = MessageBubble("System notice", role="system")
        children = list(bubble.compose())
        assert len(children) == 2

    def test_compose_without_markdown(self) -> None:
        """Test composing without markdown rendering."""
        bubble = MessageBubble("Plain text", role="user", render_markdown=False)
        children = list(bubble.compose())
        # Should have Label and Static
        assert len(children) == 2


class TestStatusBarUpdate:
    """Tests for StatusBar update functionality."""

    def test_partial_update_session_id(self) -> None:
        """Test updating only session ID."""
        bar = StatusBar()
        # Can't fully test without app context, but ensure method exists
        assert hasattr(bar, "update_status")

    def test_init_state(self) -> None:
        """Test initial state of status bar."""
        bar = StatusBar()
        assert bar._session_id == ""
        assert bar._message_count == 0
        assert bar._model == ""


class TestChatTUIInit:
    """Tests for ChatTUI initialization."""

    def test_init_stores_config(self) -> None:
        """Test that config is stored."""
        config = MagicMock(spec=Config)
        config.chat_confirm_tools = False

        tui = ChatTUI(config)
        assert tui.config is config

    def test_init_accepts_engine(self) -> None:
        """Test that engine can be provided."""
        config = MagicMock(spec=Config)
        config.chat_confirm_tools = False
        engine = MagicMock()

        tui = ChatTUI(config, engine=engine)
        assert tui._engine is engine

    def test_init_creates_formatter(self) -> None:
        """Test that formatter is created."""
        config = MagicMock(spec=Config)
        config.chat_confirm_tools = False

        tui = ChatTUI(config)
        assert tui._formatter is not None


class TestChatTUICallbacks:
    """Tests for ChatTUI callback methods."""

    def test_tool_confirm_callback_auto_confirms(self) -> None:
        """Test that default tool confirm callback returns True."""
        config = MagicMock(spec=Config)
        config.chat_confirm_tools = True

        tui = ChatTUI(config)
        result = tui._tool_confirm_callback("test_tool", {"arg": "value"})
        assert result is True

    def test_progress_callback_stores(self) -> None:
        """Test that progress callback method exists."""
        config = MagicMock(spec=Config)
        config.chat_confirm_tools = False

        tui = ChatTUI(config)
        # Method should exist
        assert hasattr(tui, "_progress_callback")


class TestChatTUIGetEngine:
    """Tests for ChatTUI engine getter."""

    @patch("summarize_links.chat.tui.ChatEngine")
    def test_creates_engine_on_first_call(self, mock_engine_class: MagicMock) -> None:
        """Test that engine is created on first call."""
        config = MagicMock(spec=Config)
        config.chat_confirm_tools = False

        tui = ChatTUI(config)
        assert tui._engine is None

        tui._get_engine()
        mock_engine_class.assert_called_once()

    @patch("summarize_links.chat.tui.ChatEngine")
    def test_returns_same_engine_on_subsequent_calls(self, mock_engine_class: MagicMock) -> None:
        """Test that same engine is returned on subsequent calls."""
        config = MagicMock(spec=Config)
        config.chat_confirm_tools = False

        tui = ChatTUI(config)

        engine1 = tui._get_engine()
        engine2 = tui._get_engine()

        assert engine1 is engine2
        # Should only be created once
        mock_engine_class.assert_called_once()

    @patch("summarize_links.chat.tui.ChatEngine")
    def test_creates_with_confirm_callback_when_enabled(self, mock_engine_class: MagicMock) -> None:
        """Test that confirm callback is passed when enabled."""
        config = MagicMock(spec=Config)
        config.chat_confirm_tools = True

        tui = ChatTUI(config)
        tui._get_engine()

        call_kwargs = mock_engine_class.call_args[1]
        assert call_kwargs["tool_confirm_callback"] is not None


class TestMultiLineInput:
    """Tests for MultiLineInput widget."""

    def test_init(self) -> None:
        """Test MultiLineInput initialization."""
        widget = MultiLineInput()
        assert widget._lines == [""]
        assert widget._history == []
        assert widget._history_index == -1


class TestChatMessagesAddMessage:
    """Tests for ChatMessages widget."""

    def test_init(self) -> None:
        """Test ChatMessages initialization."""
        widget = ChatMessages()
        # Widget should be created without error
        assert widget is not None


class TestValidateEmptyStrings:
    """Tests for validation with empty strings."""

    def test_empty_api_key_string_fails(self) -> None:
        """Test that empty string API key fails validation."""
        from summarize_links.chat.tui import _validate_chat_config
        from summarize_links.exceptions import ConfigError

        config = MagicMock(spec=Config)
        config.chat_azure_api_key = ""
        config.chat_azure_endpoint = "https://example.openai.azure.com"

        # Empty string should be falsy and trigger error
        with pytest.raises(ConfigError):
            _validate_chat_config(config)

    def test_empty_endpoint_string_fails(self) -> None:
        """Test that empty string endpoint fails validation."""
        from summarize_links.chat.tui import _validate_chat_config
        from summarize_links.exceptions import ConfigError

        config = MagicMock(spec=Config)
        config.chat_azure_api_key = "test-key"
        config.chat_azure_endpoint = ""

        with pytest.raises(ConfigError):
            _validate_chat_config(config)
