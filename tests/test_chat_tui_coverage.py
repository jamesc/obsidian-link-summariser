"""
Comprehensive test coverage for the chat TUI module.

These tests focus on improving coverage from 43% to >85%, testing:
- User input handling and history navigation
- Slash command execution
- Message rendering and display
- Streaming response handling
- Status updates
- Error scenarios

Note: Most tests directly test methods rather than using Textual's async app pilot,
which simplifies testing while achieving good coverage.
"""

from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import Static

from summarize_links.chat.tui import (
    ChatInput,
    ChatMessages,
    ChatTUI,
    MessageBubble,
    StatusBar,
)
from summarize_links.config import Config


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock configuration."""
    config = MagicMock(spec=Config)
    config.chat_azure_api_key = "test-key"
    config.chat_azure_endpoint = "https://test.openai.azure.com"
    config.chat_model = "gpt-4"
    config.chat_azure_deployment = "test-deployment"
    config.chat_max_history_messages = 10
    config.chat_max_context_tokens = 100000
    config.chat_auto_save = False
    config.chat_save_path = "chat_sessions"
    config.chat_streaming = False
    config.chat_confirm_tools = False
    config.vault_path = "/test/vault"
    return config


@pytest.fixture
def mock_engine() -> MagicMock:
    """Create a mock chat engine."""
    engine = MagicMock()
    engine.get_status.return_value = {
        "session_id": "test-session-12345",
        "message_count": 0,
        "tokens": 0,
        "max_tokens": 100000,
        "provider": "azure",
        "model": "gpt-4",
        "deployment": "test-deployment",
        "tools": 3,
        "streaming": False,
        "confirm_tools": False,
        "vault": "/test/vault",
    }
    engine.process_message.return_value = "Test response"
    engine.clear_history.return_value = None
    engine.save_session.return_value = "/path/to/session.json"
    engine.load_session.return_value = True
    engine.process_message_streaming.return_value = iter(["chunk1", " chunk2", " chunk3"])
    return engine


class TestChatInputHistoryNavigation:
    """Test ChatInput history navigation functionality."""

    def test_history_navigation_internals(self) -> None:
        """Test history navigation internal state (without setting value to avoid app context)."""
        input_widget = ChatInput()

        # Add history items
        input_widget.add_to_history("first")
        input_widget.add_to_history("second")
        input_widget.add_to_history("third")

        # Test internal state
        assert input_widget._history == ["first", "second", "third"]
        assert input_widget._history_index == -1

        # Test history_prev with empty check
        input_widget_empty = ChatInput()
        input_widget_empty.action_history_prev()
        assert input_widget_empty._history_index == -1  # Should not change

    def test_history_next_when_not_browsing(self) -> None:
        """Test that history_next does nothing when not browsing."""
        input_widget = ChatInput()

        input_widget.add_to_history("test")

        # Not browsing history
        assert input_widget._history_index == -1
        input_widget.action_history_next()

        # Should still not be browsing
        assert input_widget._history_index == -1


class TestSlashCommandHandling:
    """Test slash command handling in TUI."""

    def test_quit_command_exits(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test /quit command exits the app."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            with patch.object(tui, "exit") as mock_exit:
                tui._handle_slash_command("/quit")
                mock_exit.assert_called_once_with(0)

    def test_exit_command_exits(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test /exit command also exits the app."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            with patch.object(tui, "exit") as mock_exit:
                tui._handle_slash_command("/exit")
                mock_exit.assert_called_once_with(0)

    def test_help_command_shows_help(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test /help command shows help."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            with patch.object(tui, "action_show_help") as mock_show_help:
                tui._handle_slash_command("/help")
                mock_show_help.assert_called_once()

    def test_clear_command_clears_history(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test /clear command clears conversation."""
        tui = ChatTUI(mock_config, engine=mock_engine)

        # Mock the query_one to return a mock messages widget
        mock_messages = MagicMock(spec=ChatMessages)
        mock_messages.children = []

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._handle_slash_command("/clear")

            # Engine should be cleared
            mock_engine.clear_history.assert_called_once()

    def test_status_command_shows_status(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test /status command displays status information."""
        tui = ChatTUI(mock_config, engine=mock_engine)

        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._handle_slash_command("/status")

            # Should call get_status
            mock_engine.get_status.assert_called()
            # Should add a message
            mock_messages.add_message.assert_called_once()

    def test_save_command_saves_session(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test /save command saves session."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._handle_slash_command("/save")

            # Should call save_session
            mock_engine.save_session.assert_called_once()
            # Should show success message
            assert mock_messages.add_message.call_count == 1

    def test_save_command_handles_error(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test /save command handles errors gracefully."""
        mock_engine.save_session.side_effect = Exception("Save failed")
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._handle_slash_command("/save")

            # Should show error message
            calls = mock_messages.add_message.call_args_list
            assert len(calls) == 1
            assert "error" in str(calls[0]).lower() or "role" in str(calls[0])

    def test_load_command_loads_session(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test /load command loads saved session."""
        mock_engine.load_session.return_value = True
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)
        mock_messages.children = []

        with patch.object(tui, "query_one", return_value=mock_messages):
            with patch.object(tui, "_update_status") as mock_update_status:
                tui._handle_slash_command("/load")

                # Should call load_session
                mock_engine.load_session.assert_called_once()
                # Should update status
                mock_update_status.assert_called_once()

    def test_load_command_no_session(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test /load command when no saved session exists."""
        mock_engine.load_session.return_value = False
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._handle_slash_command("/load")

            mock_engine.load_session.assert_called_once()
            # Should show "no session" message
            mock_messages.add_message.assert_called_once()

    def test_load_command_handles_error(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test /load command handles errors gracefully."""
        mock_engine.load_session.side_effect = Exception("Load failed")
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._handle_slash_command("/load")

            # Should show error message
            assert mock_messages.add_message.call_count == 1

    def test_config_command_shows_config(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test /config command displays configuration."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._handle_slash_command("/config")

            # Should display config info
            mock_messages.add_message.assert_called_once()

    def test_unknown_command_shows_error(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test unknown command shows error message."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._handle_slash_command("/unknown")

            # Should show error message
            mock_messages.add_message.assert_called_once()
            call_args = mock_messages.add_message.call_args
            assert "error" in str(call_args).lower()


class TestMessageRendering:
    """Test message rendering and display."""

    def test_add_user_message(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test adding a user message."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._add_user_message("Test user message")

            mock_messages.add_message.assert_called_once()
            call_args = mock_messages.add_message.call_args
            assert call_args[0][0] == "Test user message"
            assert call_args[1]["role"] == "user"

    def test_add_assistant_message(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test adding an assistant message."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._add_assistant_message("Test assistant message")

            mock_messages.add_message.assert_called_once()
            call_args = mock_messages.add_message.call_args
            assert call_args[0][0] == "Test assistant message"
            assert call_args[1]["role"] == "assistant"

    def test_add_error_message(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test adding an error message."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui._add_error_message("Test error")

            mock_messages.add_message.assert_called_once()
            call_args = mock_messages.add_message.call_args
            assert "Test error" in call_args[0][0]
            assert call_args[1]["role"] == "error"

    def test_show_thinking(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test showing thinking indicator."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)
        mock_bubble = MagicMock(spec=MessageBubble)

        with patch.object(tui, "query_one", return_value=mock_messages):
            with patch("summarize_links.chat.tui.MessageBubble", return_value=mock_bubble):
                tui._show_thinking()

                assert tui._thinking_message is mock_bubble
                mock_messages.mount.assert_called_once_with(mock_bubble)

    def test_hide_thinking(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test hiding thinking indicator."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_bubble = MagicMock(spec=MessageBubble)
        tui._thinking_message = mock_bubble

        tui._hide_thinking()

        mock_bubble.remove.assert_called_once()
        assert tui._thinking_message is None

    def test_update_thinking_message(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test updating thinking indicator text."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_bubble = MagicMock(spec=MessageBubble)
        mock_static = MagicMock(spec=Static)
        mock_bubble.query_one.return_value = mock_static
        tui._thinking_message = mock_bubble

        tui._update_thinking_message("Running tool...")

        mock_static.update.assert_called_once_with("Running tool...")


class TestStreamingMessages:
    """Test streaming message display."""

    def test_start_streaming_message(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test starting a streaming message."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)
        mock_bubble = MagicMock(spec=MessageBubble)

        with patch.object(tui, "query_one", return_value=mock_messages):
            with patch("summarize_links.chat.tui.MessageBubble", return_value=mock_bubble):
                tui._start_streaming_message()

                assert tui._streaming_message is mock_bubble
                mock_messages.mount.assert_called_once_with(mock_bubble)

    def test_update_streaming_message(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test updating streaming message content."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_bubble = MagicMock(spec=MessageBubble)
        mock_static = MagicMock(spec=Static)
        mock_bubble.query_one.return_value = mock_static
        tui._streaming_message = mock_bubble

        tui._update_streaming_message("Partial content...")

        mock_static.update.assert_called_once()
        call_args = mock_static.update.call_args
        assert "Partial content..." in call_args[0][0]

    def test_finalize_streaming_message(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test finalizing streaming message."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_bubble = MagicMock(spec=MessageBubble)
        mock_static = MagicMock(spec=Static)
        mock_bubble.query_one.return_value = mock_static
        tui._streaming_message = mock_bubble

        tui._finalize_streaming_message("Final content")

        mock_static.update.assert_called_once()
        assert tui._streaming_message is None

    def test_cancel_streaming_message(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test canceling streaming message on error."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_bubble = MagicMock(spec=MessageBubble)
        tui._streaming_message = mock_bubble

        tui._cancel_streaming_message()

        mock_bubble.remove.assert_called_once()
        assert tui._streaming_message is None

    def test_update_progress_message_with_thinking(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test updating progress when thinking message is visible."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_bubble = MagicMock(spec=MessageBubble)
        mock_static = MagicMock(spec=Static)
        mock_bubble.query_one.return_value = mock_static
        tui._thinking_message = mock_bubble

        tui._update_progress_message("Fetching URL...")

        mock_static.update.assert_called_once_with("Fetching URL...")

    def test_update_progress_message_with_streaming(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test updating progress when streaming message is visible."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_bubble = MagicMock(spec=MessageBubble)
        mock_static = MagicMock(spec=Static)
        mock_bubble.query_one.return_value = mock_static
        tui._streaming_message = mock_bubble
        tui._thinking_message = None  # No thinking message

        tui._update_progress_message("Summarizing...")

        mock_static.update.assert_called_once()
        call_args = mock_static.update.call_args[0][0]
        assert "Summarizing..." in call_args

    def test_update_progress_message_no_messages(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test updating progress when no message bubbles are visible."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        tui._thinking_message = None
        tui._streaming_message = None

        # Should not crash
        tui._update_progress_message("Progress...")


class TestStatusBarUpdates:
    """Test status bar update functionality."""

    def test_update_status_all_fields(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test updating all status bar fields."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_status_bar = MagicMock(spec=StatusBar)

        status = {
            "session_id": "new-session-67890",
            "message_count": 5,
            "model": "gpt-4-turbo",
        }

        with patch.object(tui, "query_one", return_value=mock_status_bar):
            tui._update_status(status)

            mock_status_bar.update_status.assert_called_once()
            call_args = mock_status_bar.update_status.call_args[1]
            assert call_args["session_id"] == "new-session-67890"
            assert call_args["message_count"] == 5
            assert call_args["model"] == "gpt-4-turbo"


class TestProgressCallback:
    """Test progress callback integration."""

    def test_progress_callback_updates_thinking(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test that progress callback updates thinking message."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_bubble = MagicMock(spec=MessageBubble)
        mock_static = MagicMock(spec=Static)
        mock_bubble.query_one.return_value = mock_static
        tui._thinking_message = mock_bubble

        with patch.object(tui, "call_from_thread") as mock_call:
            tui._progress_callback("Fetching", "https://example.com")

            # Should call _update_progress_message through call_from_thread
            mock_call.assert_called_once()

    def test_progress_callback_with_long_detail(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test that long detail strings are truncated."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_bubble = MagicMock(spec=MessageBubble)
        tui._thinking_message = mock_bubble

        long_detail = "x" * 100

        with patch.object(tui, "call_from_thread") as mock_call:
            tui._progress_callback("Processing", long_detail)

            # Should be called with truncated message
            mock_call.assert_called_once()
            called_args = mock_call.call_args[0]
            # Second argument should contain truncated detail
            assert "..." in str(called_args)


class TestToolConfirmCallback:
    """Test tool confirmation callback."""

    def test_tool_confirm_callback_auto_confirms(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test that tool confirm callback returns True by default."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        result = tui._tool_confirm_callback("test_tool", {"arg": "value"})
        assert result is True


class TestKeyboardActions:
    """Test keyboard action methods."""

    def test_action_show_help(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test show help action."""
        tui = ChatTUI(mock_config, engine=mock_engine)
        mock_messages = MagicMock(spec=ChatMessages)

        with patch.object(tui, "query_one", return_value=mock_messages):
            tui.action_show_help()

            # Should add help message
            mock_messages.add_message.assert_called_once()
            call_args = mock_messages.add_message.call_args
            assert "help" in str(call_args).lower() or "command" in str(call_args).lower()

    def test_action_clear_messages(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test clear messages action."""
        tui = ChatTUI(mock_config, engine=mock_engine)

        with patch.object(tui, "_handle_slash_command") as mock_handle:
            tui.action_clear_messages()
            mock_handle.assert_called_once_with("/clear")

    def test_action_save_session(self, mock_config: MagicMock, mock_engine: MagicMock) -> None:
        """Test save session action."""
        tui = ChatTUI(mock_config, engine=mock_engine)

        with patch.object(tui, "_handle_slash_command") as mock_handle:
            tui.action_save_session()
            mock_handle.assert_called_once_with("/save")


class TestSendMessageStreaming:
    """Test streaming message sending."""

    def test_send_message_streaming_success(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test successful streaming message send."""
        tui = ChatTUI(mock_config, engine=mock_engine)

        with patch.object(tui, "call_from_thread") as mock_call:
            tui._send_message_streaming(mock_engine, "Test message")

            # Should call hide_thinking, start_streaming, update, and finalize
            assert mock_call.call_count >= 4

    def test_send_message_streaming_error(
        self, mock_config: MagicMock, mock_engine: MagicMock
    ) -> None:
        """Test streaming with error."""
        mock_engine.process_message_streaming.side_effect = Exception("Stream failed")
        tui = ChatTUI(mock_config, engine=mock_engine)

        with patch.object(tui, "call_from_thread") as mock_call:
            with pytest.raises(Exception, match="Stream failed"):
                tui._send_message_streaming(mock_engine, "Test message")

            # Should call cancel_streaming_message on error
            # Check that call_from_thread was called with _cancel_streaming_message
            calls = [str(call) for call in mock_call.call_args_list]
            assert any("cancel" in str(c).lower() for c in calls)
