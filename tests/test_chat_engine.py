"""
Tests for the chat engine module.
"""

from unittest.mock import MagicMock, patch

import pytest

from summarize_links.chat.engine import ChatEngine
from summarize_links.chat.formatter import ChatFormatter
from summarize_links.chat.tools.base import ToolRegistry
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
    config.vault_path = "/test/vault"
    config.out_folder = "Summaries"
    config.force = False
    config.default_tags = None
    config.model_limits = None
    # Chat session config
    config.chat_max_history_messages = 50
    config.chat_max_context_tokens = 100000
    config.chat_auto_save = False
    config.chat_save_path = ".chat-history.json"
    config.chat_streaming = True
    config.chat_confirm_tools = False
    return config


class TestChatEngine:
    """Tests for the ChatEngine class."""

    def test_create_engine(self, mock_config: MagicMock) -> None:
        """Test creating a chat engine."""
        engine = ChatEngine(mock_config)
        assert engine.config is mock_config
        assert engine.formatter is not None
        assert engine.tools is not None

    def test_create_with_custom_formatter(self, mock_config: MagicMock) -> None:
        """Test creating with custom formatter."""
        formatter = ChatFormatter()
        engine = ChatEngine(mock_config, formatter=formatter)
        assert engine.formatter is formatter

    def test_create_with_custom_registry(self, mock_config: MagicMock) -> None:
        """Test creating with custom tool registry."""
        registry = ToolRegistry()
        engine = ChatEngine(mock_config, tool_registry=registry)
        assert engine.tools is registry

    def test_conversation_has_system_prompt(self, mock_config: MagicMock) -> None:
        """Test that conversation is initialized with system prompt."""
        engine = ChatEngine(mock_config)
        assert len(engine.conversation) > 0
        assert engine.conversation.messages[0].role == "system"
        assert "Obsidian" in engine.conversation.messages[0].content

    def test_clear_history(self, mock_config: MagicMock) -> None:
        """Test clearing conversation history."""
        engine = ChatEngine(mock_config)
        engine.conversation.add_user_message("Hello")
        engine.conversation.add_assistant_message("Hi!")

        engine.clear_history()

        # Should keep system message only
        assert len(engine.conversation) == 1
        assert engine.conversation.messages[0].role == "system"

    def test_get_status(self, mock_config: MagicMock) -> None:
        """Test getting engine status."""
        engine = ChatEngine(mock_config)
        status = engine.get_status()

        assert status["provider"] == "azure"
        assert status["model"] == "gpt-4o-mini"
        assert status["deployment"] == "gpt-4o-mini"
        assert "tools" in status
        assert "messages" in status
        assert "session_id" in status
        assert "message_count" in status
        assert status["message_count"] == 0

    def test_session_id_generated_on_init(self, mock_config: MagicMock) -> None:
        """Test that a unique session ID is generated on initialization."""
        engine1 = ChatEngine(mock_config)
        engine2 = ChatEngine(mock_config)

        # Each engine should have a unique session ID
        assert engine1.session_id != engine2.session_id
        # Session ID should be a UUID-like string
        assert len(engine1.session_id) == 36  # UUID format
        assert "-" in engine1.session_id

    def test_message_count_increments(self, mock_config: MagicMock) -> None:
        """Test that message count increments with each processed message."""
        engine = ChatEngine(mock_config)
        assert engine._message_count == 0

        # We can't easily test actual message processing without mocking,
        # but we can verify the initial state
        status = engine.get_status()
        assert status["message_count"] == 0

    def test_clear_history_with_reset_count(self, mock_config: MagicMock) -> None:
        """Test clearing history with message count reset."""
        engine = ChatEngine(mock_config)
        engine._message_count = 5  # Simulate 5 messages processed

        engine.clear_history(reset_message_count=True)

        assert engine._message_count == 0
        assert len(engine.conversation) == 1  # System message only

    def test_clear_history_keeps_count_by_default(self, mock_config: MagicMock) -> None:
        """Test that clear_history keeps message count by default."""
        engine = ChatEngine(mock_config)
        engine._message_count = 5  # Simulate 5 messages processed

        engine.clear_history()  # Don't reset count

        assert engine._message_count == 5
        assert len(engine.conversation) == 1  # System message only

    def test_clear_history_resets_previous_response_id(self, mock_config: MagicMock) -> None:
        """Test that clear_history resets the previous_response_id for Responses API."""
        engine = ChatEngine(mock_config)
        engine._previous_response_id = "resp_123"  # Simulate a previous response

        engine.clear_history()

        assert engine._previous_response_id is None
        assert len(engine.conversation) == 1  # System message only


class TestChatEngineAzureIntegration:
    """Tests for Azure OpenAI integration using Responses API."""

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_process_message_no_tool_calls(
        self,
        mock_get_tracer: MagicMock,
        mock_azure_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test processing a message that doesn't trigger function calls."""
        # Setup mock tracer with trace_message context manager
        mock_tracer = MagicMock()
        mock_message_ctx = MagicMock()
        mock_message_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_message_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_message_ctx

        mock_generation_ctx = MagicMock()
        mock_generation_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_generation_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_generation.return_value = mock_generation_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock Azure client using Responses API structure
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Hello! I can help you with that."
        mock_response.function_calls = None
        mock_response.has_function_calls = False
        mock_response.status = "completed"
        mock_response.response_id = "resp_123"
        mock_response.usage = {"input": 10, "output": 20, "total": 30}
        mock_client.chat.return_value = mock_response
        mock_azure_client_class.return_value = mock_client

        engine = ChatEngine(mock_config)
        response = engine.process_message("Hello!")

        assert response == "Hello! I can help you with that."
        mock_client.chat.assert_called_once()

        # Verify trace_message was called with session_id
        mock_tracer.trace_message.assert_called_once()
        call_kwargs = mock_tracer.trace_message.call_args[1]
        assert call_kwargs["session_id"] == engine.session_id
        assert call_kwargs["message_number"] == 1
        assert call_kwargs["user_input"] == "Hello!"

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_process_message_increments_count(
        self,
        mock_get_tracer: MagicMock,
        mock_azure_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that processing messages increments the message count."""
        # Setup mock tracer
        mock_tracer = MagicMock()
        mock_message_ctx = MagicMock()
        mock_message_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_message_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_message_ctx

        mock_generation_ctx = MagicMock()
        mock_generation_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_generation_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_generation.return_value = mock_generation_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock Azure client using Responses API structure
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Response"
        mock_response.function_calls = None
        mock_response.has_function_calls = False
        mock_response.status = "completed"
        mock_response.response_id = "resp_456"
        mock_response.usage = None
        mock_client.chat.return_value = mock_response
        mock_azure_client_class.return_value = mock_client

        engine = ChatEngine(mock_config)
        assert engine._message_count == 0

        engine.process_message("First message")
        assert engine._message_count == 1

        engine.process_message("Second message")
        assert engine._message_count == 2

        # Verify message numbers in trace calls
        calls = mock_tracer.trace_message.call_args_list
        assert calls[0][1]["message_number"] == 1
        assert calls[1][1]["message_number"] == 2

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_process_message_with_function_calls(
        self,
        mock_get_tracer: MagicMock,
        mock_azure_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test processing a message that triggers function calls."""
        # Setup mock tracer with trace_message context manager
        mock_tracer = MagicMock()
        mock_message_ctx = MagicMock()
        mock_message_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_message_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_message_ctx

        mock_generation_ctx = MagicMock()
        mock_generation_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_generation_ctx.__exit__ = MagicMock(return_value=None)
        mock_span_ctx = MagicMock()
        mock_span_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_span_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_generation.return_value = mock_generation_ctx
        mock_tracer.trace_span.return_value = mock_span_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock Azure client using Responses API structure
        mock_client = MagicMock()

        # First response with function call
        from summarize_links.chat.azure_client import FunctionCall

        mock_function_call = FunctionCall(
            call_id="call_123",
            name="summarize_url",
            arguments={"url": "https://example.com"},
        )
        mock_response1 = MagicMock()
        mock_response1.content = None
        mock_response1.function_calls = [mock_function_call]
        mock_response1.has_function_calls = True
        mock_response1.status = "completed"
        mock_response1.response_id = "resp_func_1"
        mock_response1.usage = {"input": 10, "output": 5, "total": 15}

        # Second response after function execution (via submit_function_outputs)
        mock_response2 = MagicMock()
        mock_response2.content = "I've summarized the article for you."
        mock_response2.function_calls = None
        mock_response2.has_function_calls = False
        mock_response2.status = "completed"
        mock_response2.response_id = "resp_func_2"
        mock_response2.usage = {"input": 50, "output": 20, "total": 70}

        # First call returns function call, submit_function_outputs returns final response
        mock_client.chat.return_value = mock_response1
        mock_client.submit_function_outputs.return_value = mock_response2
        mock_azure_client_class.return_value = mock_client

        # Mock tool execution using patch
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "Summary saved"
        mock_result.data = None
        mock_result.to_content.return_value = "Summary saved"

        engine = ChatEngine(mock_config)

        with patch.object(engine.tools, "execute", return_value=mock_result) as mock_execute:
            response = engine.process_message("Summarize https://example.com")

            assert response == "I've summarized the article for you."
            mock_client.chat.assert_called_once()
            mock_client.submit_function_outputs.assert_called_once()
            mock_execute.assert_called_once_with(
                "summarize_url",
                mock_config,
                progress_callback=None,
                url="https://example.com",
            )

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_process_message_tracks_response_id(
        self,
        mock_get_tracer: MagicMock,
        mock_azure_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that processing messages tracks response_id for conversation chaining."""
        # Setup mock tracer
        mock_tracer = MagicMock()
        mock_message_ctx = MagicMock()
        mock_message_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_message_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_message_ctx

        mock_generation_ctx = MagicMock()
        mock_generation_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_generation_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_generation.return_value = mock_generation_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock Azure client
        mock_client = MagicMock()
        mock_response1 = MagicMock()
        mock_response1.content = "First response"
        mock_response1.function_calls = None
        mock_response1.has_function_calls = False
        mock_response1.status = "completed"
        mock_response1.response_id = "resp_first"
        mock_response1.usage = None

        mock_response2 = MagicMock()
        mock_response2.content = "Second response"
        mock_response2.function_calls = None
        mock_response2.has_function_calls = False
        mock_response2.status = "completed"
        mock_response2.response_id = "resp_second"
        mock_response2.usage = None

        mock_client.chat.side_effect = [mock_response1, mock_response2]
        mock_azure_client_class.return_value = mock_client

        engine = ChatEngine(mock_config)
        assert engine._previous_response_id is None

        engine.process_message("First message")
        assert engine._previous_response_id == "resp_first"

        engine.process_message("Second message")
        assert engine._previous_response_id == "resp_second"

        # Verify the second call used the first response_id
        calls = mock_client.chat.call_args_list
        assert calls[1][1]["previous_response_id"] == "resp_first"

    @patch("summarize_links.chat.engine.AzureChatClient")
    @patch("summarize_links.chat.engine.get_tracer")
    def test_process_message_updates_trace_output(
        self,
        mock_get_tracer: MagicMock,
        mock_azure_client_class: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test that update_trace_output is called with the response."""
        # Setup mock tracer
        mock_tracer = MagicMock()
        mock_trace_obj = MagicMock()
        mock_message_ctx = MagicMock()
        mock_message_ctx.__enter__ = MagicMock(return_value=mock_trace_obj)
        mock_message_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_message.return_value = mock_message_ctx

        mock_generation_ctx = MagicMock()
        mock_generation_ctx.__enter__ = MagicMock(return_value=MagicMock())
        mock_generation_ctx.__exit__ = MagicMock(return_value=None)
        mock_tracer.trace_generation.return_value = mock_generation_ctx
        mock_get_tracer.return_value = mock_tracer

        # Setup mock Azure client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Test response"
        mock_response.function_calls = None
        mock_response.has_function_calls = False
        mock_response.status = "completed"
        mock_response.response_id = "resp_test"
        mock_response.usage = None
        mock_client.chat.return_value = mock_response
        mock_azure_client_class.return_value = mock_client

        engine = ChatEngine(mock_config)
        engine.process_message("Test message")

        # Verify update_trace_output was called with the response
        mock_tracer.update_trace_output.assert_called_once()
        call_kwargs = mock_tracer.update_trace_output.call_args[1]
        assert call_kwargs["output"] == {"assistant_response": "Test response"}
        assert "response_length" in call_kwargs["metadata"]
        assert call_kwargs["metadata"]["response_length"] == len("Test response")
        assert call_kwargs["metadata"]["message_count"] == 1
