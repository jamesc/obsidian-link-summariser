"""
Tests for the Textual-based chat TUI.

These tests verify the TUI components without running the full app,
since Textual provides good test utilities.
"""

from unittest.mock import MagicMock, patch

import pytest

from summarize_links.chat.tui import (
    CLEAR_COMMANDS,
    HELP_COMMANDS,
    QUIT_COMMANDS,
    STATUS_COMMANDS,
    ChatInput,
    MessageBubble,
    _validate_chat_config,
    run_chat_tui,
)
from summarize_links.config import Config
from summarize_links.exceptions import ConfigError


class TestSlashCommands:
    """Test slash command constants."""

    def test_quit_commands(self) -> None:
        """Test quit commands are defined."""
        assert "/quit" in QUIT_COMMANDS
        assert "/exit" in QUIT_COMMANDS
        assert "/q" in QUIT_COMMANDS

    def test_help_commands(self) -> None:
        """Test help commands are defined."""
        assert "/help" in HELP_COMMANDS
        assert "/h" in HELP_COMMANDS
        assert "/?" in HELP_COMMANDS

    def test_clear_commands(self) -> None:
        """Test clear commands are defined."""
        assert "/clear" in CLEAR_COMMANDS
        assert "/reset" in CLEAR_COMMANDS

    def test_status_commands(self) -> None:
        """Test status commands are defined."""
        assert "/status" in STATUS_COMMANDS


class TestValidateChatConfig:
    """Test chat configuration validation."""

    def test_missing_api_key_raises_error(self) -> None:
        """Missing API key raises ConfigError."""
        config = MagicMock(spec=Config)
        config.chat_azure_api_key = None
        config.chat_azure_endpoint = "https://example.openai.azure.com"

        with pytest.raises(ConfigError, match="CHAT_AZURE_API_KEY"):
            _validate_chat_config(config)

    def test_missing_endpoint_raises_error(self) -> None:
        """Missing endpoint raises ConfigError."""
        config = MagicMock(spec=Config)
        config.chat_azure_api_key = "test-key"
        config.chat_azure_endpoint = None

        with pytest.raises(ConfigError, match="CHAT_AZURE_ENDPOINT"):
            _validate_chat_config(config)

    def test_valid_config_passes(self) -> None:
        """Valid config passes validation."""
        config = MagicMock(spec=Config)
        config.chat_azure_api_key = "test-key"
        config.chat_azure_endpoint = "https://example.openai.azure.com"

        # Should not raise
        _validate_chat_config(config)


class TestChatInput:
    """Test ChatInput history functionality."""

    def test_add_to_history(self) -> None:
        """Test adding to history."""
        input_widget = ChatInput()
        input_widget.add_to_history("test message")

        assert "test message" in input_widget._history
        assert input_widget._history_index == -1

    def test_history_deduplicates(self) -> None:
        """Test that duplicate messages are not added."""
        input_widget = ChatInput()
        input_widget.add_to_history("test message")
        input_widget.add_to_history("test message")

        assert len(input_widget._history) == 1

    def test_empty_not_added_to_history(self) -> None:
        """Test that empty strings are not added."""
        input_widget = ChatInput()
        input_widget.add_to_history("")

        assert len(input_widget._history) == 0


class TestMessageBubble:
    """Test MessageBubble widget."""

    def test_user_role_class(self) -> None:
        """Test user role adds correct class."""
        bubble = MessageBubble("test", role="user")
        assert "user" in bubble.classes

    def test_assistant_role_class(self) -> None:
        """Test assistant role adds correct class."""
        bubble = MessageBubble("test", role="assistant")
        assert "assistant" in bubble.classes

    def test_system_role_class(self) -> None:
        """Test system role adds correct class."""
        bubble = MessageBubble("test", role="system")
        assert "system" in bubble.classes

    def test_error_role_class(self) -> None:
        """Test error role adds correct class."""
        bubble = MessageBubble("test", role="error")
        assert "error" in bubble.classes


class TestRunChatTui:
    """Test the run_chat_tui function."""

    def test_invalid_config_returns_error(self) -> None:
        """Test that invalid config returns error code."""
        config = MagicMock(spec=Config)
        config.chat_azure_api_key = None
        config.chat_azure_endpoint = None

        result = run_chat_tui(config)
        assert result == 1

    @patch("summarize_links.chat.tui.ChatTUI")
    def test_valid_config_runs_app(self, mock_app_class: MagicMock) -> None:
        """Test that valid config runs the app."""
        config = MagicMock(spec=Config)
        config.chat_azure_api_key = "test-key"
        config.chat_azure_endpoint = "https://example.openai.azure.com"

        mock_app = MagicMock()
        mock_app.run.return_value = 0
        mock_app_class.return_value = mock_app

        result = run_chat_tui(config)

        mock_app_class.assert_called_once_with(config)
        mock_app.run.assert_called_once()
        assert result == 0

    @patch("summarize_links.chat.tui.ChatTUI")
    def test_handles_none_return(self, mock_app_class: MagicMock) -> None:
        """Test that None return from app.run() is handled."""
        config = MagicMock(spec=Config)
        config.chat_azure_api_key = "test-key"
        config.chat_azure_endpoint = "https://example.openai.azure.com"

        mock_app = MagicMock()
        mock_app.run.return_value = None
        mock_app_class.return_value = mock_app

        result = run_chat_tui(config)
        assert result == 0
