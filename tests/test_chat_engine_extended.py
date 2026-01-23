"""
Extended tests for the chat engine module.

Focuses on edge cases, error handling, streaming, and session management.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from summarize_links.chat.azure_client import FunctionCall
from summarize_links.chat.engine import ChatEngine
from summarize_links.chat.formatter import ChatFormatter
from summarize_links.chat.tools.base import ToolRegistry, ToolResult
from summarize_links.config import Config


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock config for testing."""
    config = MagicMock(spec=Config)
    config.model_provider = "azure"
    config.model = "gpt-4o"
    config.chat_model = "gpt-4o-mini"
    config.chat_azure_endpoint = "https://test.openai.azure.com"
    config.chat_azure_api_key = "test-key"
    config.chat_azure_deployment = "gpt-4o-mini"
    config.vault_path = Path("/test/vault")
    config.out_folder = "Summaries"
    config.mock_mode = False
    config.force = False
    config.default_tags = None
    config.model_limits = None
    config.chat_max_history_messages = 50
    config.chat_max_context_tokens = 100000
    config.chat_auto_save = False
    config.chat_save_path = ".chat-history.json"
    config.chat_streaming = False
    config.chat_confirm_tools = False
    return config


class TestChatEngineInit:
    """Tests for ChatEngine initialization."""

    def test_creates_formatter_if_not_provided(self, mock_config: MagicMock) -> None:
        """Test that formatter is created if not provided."""
        engine = ChatEngine(mock_config)
        assert engine.formatter is not None
        assert isinstance(engine.formatter, ChatFormatter)

    def test_creates_tool_registry_if_not_provided(self, mock_config: MagicMock) -> None:
        """Test that tool registry is created if not provided."""
        engine = ChatEngine(mock_config)
        assert engine.tools is not None
        assert isinstance(engine.tools, ToolRegistry)

    def test_accepts_tool_confirm_callback(self, mock_config: MagicMock) -> None:
        """Test that tool confirm callback is stored."""
        callback = MagicMock(return_value=True)
        engine = ChatEngine(mock_config, tool_confirm_callback=callback)
        assert engine._tool_confirm_callback is callback

    def test_accepts_progress_callback(self, mock_config: MagicMock) -> None:
        """Test that progress callback is stored."""
        callback = MagicMock()
        engine = ChatEngine(mock_config, progress_callback=callback)
        assert engine._progress_callback is callback


class TestChatEngineProgressCallback:
    """Tests for progress callback functionality."""

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_progress_callback_called_during_tool_execution(
        self,
        mock_get_tracer: MagicMock,
        mock_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that progress callback is called during tool execution."""
        # Setup mock tracer
        mock_tracer = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_ctx
        mock_tracer.trace_generation.return_value = mock_ctx
        mock_tracer.trace_span.return_value = mock_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock client with function call response
        mock_client = MagicMock()
        mock_fc = FunctionCall("call_1", "summarize_url", {"url": "https://test.com"})
        mock_response1 = MagicMock()
        mock_response1.content = None
        mock_response1.function_calls = [mock_fc]
        mock_response1.has_function_calls = True
        mock_response1.response_id = "resp_1"
        mock_response1.usage = None

        mock_response2 = MagicMock()
        mock_response2.content = "Done"
        mock_response2.function_calls = None
        mock_response2.has_function_calls = False
        mock_response2.response_id = "resp_2"
        mock_response2.usage = None

        mock_client.chat.return_value = mock_response1
        mock_client.submit_function_outputs.return_value = mock_response2
        mock_client_class.return_value = mock_client

        # Track progress calls
        progress_calls = []

        def progress_callback(stage: str, detail: str) -> None:
            progress_calls.append((stage, detail))

        engine = ChatEngine(mock_config, progress_callback=progress_callback)

        # Mock tool execution
        mock_result = ToolResult(success=True, message="OK")
        with patch.object(engine.tools, "execute", return_value=mock_result):
            engine.process_message("Test")

        # Verify progress was reported
        assert len(progress_calls) > 0
        assert ("Running", "summarize_url") in progress_calls

    def test_report_progress_handles_callback_exception(self, mock_config: MagicMock) -> None:
        """Test that exceptions in progress callback are handled."""

        def bad_callback(stage: str, detail: str) -> None:
            raise ValueError("Callback error")

        engine = ChatEngine(mock_config, progress_callback=bad_callback)

        # Should not raise
        engine._report_progress("Test", "detail")


class TestChatEngineSessionManagement:
    """Tests for session save/load functionality."""

    def test_save_session_uses_vault_path(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Test that save uses vault path by default."""
        mock_config.vault_path = tmp_path
        mock_config.chat_save_path = ".chat-history.json"

        engine = ChatEngine(mock_config)
        path = engine.save_session()

        assert path == tmp_path / ".chat-history.json"
        assert path.exists()

    def test_save_session_custom_path(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Test saving to custom path."""
        engine = ChatEngine(mock_config)
        custom_path = tmp_path / "custom-session.json"
        path = engine.save_session(custom_path)

        assert path == custom_path
        assert path.exists()

    def test_load_session_not_found(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Test loading when file doesn't exist."""
        mock_config.vault_path = tmp_path
        mock_config.chat_save_path = "nonexistent.json"

        engine = ChatEngine(mock_config)
        result = engine.load_session()

        assert result is False

    def test_load_session_success(self, mock_config: MagicMock, tmp_path: Path) -> None:
        """Test successful session load."""
        mock_config.vault_path = tmp_path
        mock_config.chat_save_path = ".chat-history.json"

        # Save a session first
        engine1 = ChatEngine(mock_config)
        engine1.conversation.add_user_message("Hello")
        engine1.save_session()

        # Load in new engine
        engine2 = ChatEngine(mock_config)
        result = engine2.load_session()

        assert result is True
        # Should have system message + user message
        assert len(engine2.conversation) >= 2


class TestChatEngineToolConfirmation:
    """Tests for tool confirmation functionality."""

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_tool_rejected_by_callback(
        self,
        mock_get_tracer: MagicMock,
        mock_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that rejected tools are not executed."""
        mock_config.chat_confirm_tools = True

        # Setup mock tracer
        mock_tracer = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_ctx
        mock_tracer.trace_generation.return_value = mock_ctx
        mock_tracer.trace_span.return_value = mock_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock client
        mock_client = MagicMock()
        mock_fc = FunctionCall("call_1", "dangerous_tool", {})
        mock_response1 = MagicMock()
        mock_response1.content = None
        mock_response1.function_calls = [mock_fc]
        mock_response1.has_function_calls = True
        mock_response1.response_id = "resp_1"
        mock_response1.usage = None

        mock_response2 = MagicMock()
        mock_response2.content = "Tool was skipped"
        mock_response2.function_calls = None
        mock_response2.has_function_calls = False
        mock_response2.response_id = "resp_2"
        mock_response2.usage = None

        mock_client.chat.return_value = mock_response1
        mock_client.submit_function_outputs.return_value = mock_response2
        mock_client_class.return_value = mock_client

        # Callback rejects all tools
        reject_callback = MagicMock(return_value=False)

        engine = ChatEngine(
            mock_config,
            tool_confirm_callback=reject_callback,
        )

        with patch.object(engine.tools, "execute") as mock_execute:
            engine.process_message("Run dangerous tool")
            # Tool should not have been executed
            mock_execute.assert_not_called()


class TestChatEngineErrorHandling:
    """Tests for error handling in ChatEngine."""

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_api_error_returns_error_message(
        self,
        mock_get_tracer: MagicMock,
        mock_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that API errors return user-friendly message."""
        # Setup mock tracer
        mock_tracer = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_ctx
        mock_tracer.trace_generation.return_value = mock_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock client to raise error
        mock_client = MagicMock()
        mock_client.chat.side_effect = Exception("API connection failed")
        mock_client_class.return_value = mock_client

        engine = ChatEngine(mock_config)
        response = engine.process_message("Hello")

        assert "Error communicating with AI" in response

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_function_execution_error_continues(
        self,
        mock_get_tracer: MagicMock,
        mock_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that function execution errors are handled gracefully."""
        # Setup mock tracer
        mock_tracer = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_ctx
        mock_tracer.trace_generation.return_value = mock_ctx
        mock_tracer.trace_span.return_value = mock_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock client
        mock_client = MagicMock()
        mock_fc = FunctionCall("call_1", "failing_tool", {})
        mock_response1 = MagicMock()
        mock_response1.content = None
        mock_response1.function_calls = [mock_fc]
        mock_response1.has_function_calls = True
        mock_response1.response_id = "resp_1"
        mock_response1.usage = None

        # Submit function outputs fails
        mock_client.chat.return_value = mock_response1
        mock_client.submit_function_outputs.side_effect = Exception("API error")
        mock_client_class.return_value = mock_client

        engine = ChatEngine(mock_config)

        # Mock tool to return error result
        error_result = ToolResult(success=False, message="Tool failed", error="Error")
        with patch.object(engine.tools, "execute", return_value=error_result):
            response = engine.process_message("Run failing tool")

        assert "error" in response.lower()


class TestChatEngineStreaming:
    """Tests for streaming functionality."""

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_streaming_yields_chunks(
        self,
        mock_get_tracer: MagicMock,
        mock_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that streaming yields content chunks."""
        # Setup mock tracer
        mock_tracer = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_ctx
        mock_tracer.trace_generation.return_value = mock_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock streaming response
        mock_stream = MagicMock()
        mock_stream.__iter__ = MagicMock(return_value=iter(["Hello", " ", "World"]))
        mock_stream.response_id = "resp_stream"
        mock_stream.has_function_calls = False
        mock_stream.function_calls = None
        mock_stream.content = "Hello World"
        mock_stream.usage = None

        mock_client = MagicMock()
        mock_client.chat_stream.return_value = mock_stream
        mock_client_class.return_value = mock_client

        engine = ChatEngine(mock_config)
        chunks = list(engine.process_message_streaming("Test"))

        assert chunks == ["Hello", " ", "World"]

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_streaming_updates_response_id(
        self,
        mock_get_tracer: MagicMock,
        mock_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that streaming updates previous_response_id."""
        # Setup mock tracer
        mock_tracer = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_ctx
        mock_tracer.trace_generation.return_value = mock_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock streaming response
        mock_stream = MagicMock()
        mock_stream.__iter__ = MagicMock(return_value=iter(["OK"]))
        mock_stream.response_id = "resp_new_stream"
        mock_stream.has_function_calls = False
        mock_stream.function_calls = None
        mock_stream.content = "OK"
        mock_stream.usage = None

        mock_client = MagicMock()
        mock_client.chat_stream.return_value = mock_stream
        mock_client_class.return_value = mock_client

        engine = ChatEngine(mock_config)
        assert engine._previous_response_id is None

        list(engine.process_message_streaming("Test"))

        assert engine._previous_response_id == "resp_new_stream"
