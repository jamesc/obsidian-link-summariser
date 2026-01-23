"""
Additional tests for the Azure chat client module.

Focuses on edge cases, error handling, and streaming functionality.
"""

from unittest.mock import MagicMock, patch

import pytest
from openai import APIConnectionError, APIError
from openai import RateLimitError as OpenAIRateLimitError

from summarize_links.chat.azure_client import (
    AzureChatClient,
    ChatResponse,
    FunctionCall,
    StreamingChatResponse,
)
from summarize_links.exceptions import AzureAPIError


class TestFunctionCallEdgeCases:
    """Additional tests for FunctionCall class."""

    def test_from_output_item_with_empty_arguments(self) -> None:
        """Test parsing function call with empty arguments."""
        item = MagicMock()
        item.call_id = "call_empty"
        item.name = "test_func"
        item.arguments = ""

        fc = FunctionCall.from_output_item(item)

        assert fc.call_id == "call_empty"
        assert fc.name == "test_func"
        assert fc.arguments == {}

    def test_from_output_item_with_none_arguments(self) -> None:
        """Test parsing function call with None arguments."""
        item = MagicMock()
        item.call_id = "call_none"
        item.name = "test_func"
        item.arguments = None

        # Should handle None gracefully
        fc = FunctionCall.from_output_item(item)
        assert fc.arguments == {} or fc.arguments is None

    def test_from_output_item_with_complex_arguments(self) -> None:
        """Test parsing function call with nested arguments."""
        item = MagicMock()
        item.call_id = "call_complex"
        item.name = "complex_func"
        item.arguments = '{"nested": {"key": "value"}, "list": [1, 2, 3]}'

        fc = FunctionCall.from_output_item(item)

        assert fc.arguments["nested"]["key"] == "value"
        assert fc.arguments["list"] == [1, 2, 3]


class TestChatResponseEdgeCases:
    """Additional tests for ChatResponse class."""

    def test_from_api_response_with_no_output(self) -> None:
        """Test parsing response with empty output."""
        response = MagicMock()
        response.id = "resp_empty"
        response.status = "completed"
        response.output = []
        response.output_text = None
        response.usage = None

        cr = ChatResponse.from_api_response(response)

        assert cr.response_id == "resp_empty"
        assert cr.content is None
        assert cr.function_calls is None
        assert cr.status == "completed"

    def test_from_api_response_with_multiple_function_calls(self) -> None:
        """Test parsing response with multiple function calls."""
        fc1 = MagicMock()
        fc1.type = "function_call"
        fc1.call_id = "call_1"
        fc1.name = "func1"
        fc1.arguments = '{"arg": "val1"}'

        fc2 = MagicMock()
        fc2.type = "function_call"
        fc2.call_id = "call_2"
        fc2.name = "func2"
        fc2.arguments = '{"arg": "val2"}'

        response = MagicMock()
        response.id = "resp_multi"
        response.status = "completed"
        response.output = [fc1, fc2]
        response.output_text = None
        response.usage = None

        cr = ChatResponse.from_api_response(response)

        assert cr.function_calls is not None
        assert len(cr.function_calls) == 2
        assert cr.function_calls[0].name == "func1"
        assert cr.function_calls[1].name == "func2"

    def test_response_with_both_content_and_function_calls(self) -> None:
        """Test response that has both text and function calls."""
        fc = MagicMock()
        fc.type = "function_call"
        fc.call_id = "call_mixed"
        fc.name = "my_func"
        fc.arguments = "{}"

        response = MagicMock()
        response.id = "resp_mixed"
        response.status = "completed"
        response.output = [fc]
        response.output_text = "Some text before function call"
        response.usage = MagicMock()
        response.usage.input_tokens = 10
        response.usage.output_tokens = 5
        response.usage.total_tokens = 15

        cr = ChatResponse.from_api_response(response)

        assert cr.content == "Some text before function call"
        assert cr.has_function_calls is True


class TestStreamingChatResponse:
    """Tests for StreamingChatResponse class."""

    def test_content_property_consumes_stream(self) -> None:
        """Test that content property consumes stream if not consumed."""
        # Create mock events
        events = [
            MagicMock(type="response.created", response=MagicMock(id="resp_stream")),
            MagicMock(type="response.output_text.delta", delta="Hello"),
            MagicMock(type="response.output_text.delta", delta=" World"),
            MagicMock(
                type="response.completed",
                response=MagicMock(id="resp_stream", usage=None),
            ),
        ]

        stream = iter(events)
        scr = StreamingChatResponse(stream)

        # Access content property without iterating
        content = scr.content
        assert content == "Hello World"
        assert scr._consumed is True

    def test_function_calls_property_consumes_stream(self) -> None:
        """Test that function_calls property consumes stream if not consumed."""
        # Create mock item with explicit string name (not MagicMock)
        mock_item = MagicMock()
        mock_item.type = "function_call"
        mock_item.id = "item_1"
        mock_item.call_id = "call_1"
        mock_item.name = "test_func"  # Set as string explicitly

        events = [
            MagicMock(type="response.created", response=MagicMock(id="resp_fc")),
            MagicMock(
                type="response.output_item.added",
                item=mock_item,
            ),
            MagicMock(
                type="response.function_call_arguments.delta",
                item_id="item_1",
                delta='{"key": ',
            ),
            MagicMock(
                type="response.function_call_arguments.delta",
                item_id="item_1",
                delta='"value"}',
            ),
            MagicMock(
                type="response.function_call_arguments.done",
                item_id="item_1",
                arguments='{"key": "value"}',
            ),
            MagicMock(
                type="response.completed",
                response=MagicMock(id="resp_fc", usage=None),
            ),
        ]

        stream = iter(events)
        scr = StreamingChatResponse(stream)

        # Access function_calls property
        fcs = scr.function_calls
        assert fcs is not None  # Narrow type for mypy
        assert len(fcs) == 1  # Now safe since we asserted not None
        assert fcs[0].name == "test_func"

    def test_iterate_twice_returns_cached(self) -> None:
        """Test that iterating twice returns cached chunks."""
        events = [
            MagicMock(type="response.output_text.delta", delta="Test"),
            MagicMock(
                type="response.completed",
                response=MagicMock(id="resp_cache", usage=None),
            ),
        ]

        stream = iter(events)
        scr = StreamingChatResponse(stream)

        # First iteration
        chunks1 = list(scr)
        # Second iteration
        chunks2 = list(scr)

        assert chunks1 == chunks2 == ["Test"]

    def test_to_response_conversion(self) -> None:
        """Test converting streaming response to regular response."""
        events = [
            MagicMock(type="response.created", response=MagicMock(id="resp_conv")),
            MagicMock(type="response.output_text.delta", delta="Content"),
            MagicMock(
                type="response.completed",
                response=MagicMock(
                    id="resp_conv",
                    status="completed",
                    usage=MagicMock(input_tokens=5, output_tokens=3, total_tokens=8),
                ),
            ),
        ]

        stream = iter(events)
        scr = StreamingChatResponse(stream)

        response = scr.to_response()

        assert isinstance(response, ChatResponse)
        assert response.content == "Content"
        assert response.response_id == "resp_conv"
        assert response.usage is not None

    def test_response_done_event(self) -> None:
        """Test handling of response.done event."""
        events = [
            MagicMock(type="response.output_text.delta", delta="Done"),
            MagicMock(
                type="response.done",
                response=MagicMock(id="resp_done", status="completed"),
            ),
        ]

        stream = iter(events)
        scr = StreamingChatResponse(stream)

        # Consume stream
        list(scr)

        assert scr.response_id == "resp_done"
        assert scr.status == "completed"


class TestAzureChatClientInit:
    """Tests for AzureChatClient initialization."""

    def test_init_with_defaults(self) -> None:
        """Test initialization with default values."""
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
        )

        assert client._api_key == "test-key"
        assert client._endpoint == "https://test.openai.azure.com"
        assert client._deployment_name == client._model

    def test_init_strips_trailing_slash(self) -> None:
        """Test that trailing slash is stripped from endpoint."""
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com/",
        )

        assert client._endpoint == "https://test.openai.azure.com"

    def test_model_and_deployment_properties(self) -> None:
        """Test model and deployment_name properties."""
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4o",
            deployment_name="my-deployment",
        )

        assert client.model == "gpt-4o"
        assert client.deployment_name == "my-deployment"


class TestAzureChatClientToolConversion:
    """Tests for tool schema conversion."""

    @pytest.fixture
    def client(self) -> AzureChatClient:
        """Create a client instance."""
        return AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
        )

    def test_convert_nested_format(self, client: AzureChatClient) -> None:
        """Test converting from nested Chat Completions format."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "my_func",
                    "description": "Does something",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        converted = client._convert_tools_for_responses_api(tools)

        assert len(converted) == 1
        assert converted[0]["type"] == "function"
        assert converted[0]["name"] == "my_func"
        assert converted[0]["description"] == "Does something"
        assert "function" not in converted[0]

    def test_convert_already_flat_format(self, client: AzureChatClient) -> None:
        """Test that already-flat format is passed through."""
        tools = [
            {
                "type": "function",
                "name": "my_func",
                "description": "Already flat",
                "parameters": {},
            }
        ]

        converted = client._convert_tools_for_responses_api(tools)

        assert converted == tools

    def test_convert_mixed_formats(self, client: AzureChatClient) -> None:
        """Test converting mixed formats."""
        tools = [
            {
                "type": "function",
                "function": {"name": "nested", "description": "Nested format", "parameters": {}},
            },
            {
                "type": "function",
                "name": "flat",
                "description": "Flat format",
                "parameters": {},
            },
        ]

        converted = client._convert_tools_for_responses_api(tools)

        assert len(converted) == 2
        assert converted[0]["name"] == "nested"
        assert converted[1]["name"] == "flat"


class TestAzureChatClientErrors:
    """Tests for error handling in AzureChatClient."""

    @pytest.fixture
    def client(self) -> AzureChatClient:
        """Create a client instance."""
        return AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
        )

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_chat_connection_error(
        self, mock_openai_class: MagicMock, client: AzureChatClient
    ) -> None:
        """Test handling of connection errors."""
        mock_client = MagicMock()
        mock_client.responses.create.side_effect = APIConnectionError(request=MagicMock())
        mock_openai_class.return_value = mock_client

        with pytest.raises(AzureAPIError, match="Connection error"):
            client.chat("Hello")

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_chat_api_error(self, mock_openai_class: MagicMock, client: AzureChatClient) -> None:
        """Test handling of general API errors."""
        mock_client = MagicMock()
        mock_error = APIError(
            message="Internal server error",
            request=MagicMock(),
            body=None,
        )
        mock_client.responses.create.side_effect = mock_error
        mock_openai_class.return_value = mock_client

        with pytest.raises(AzureAPIError, match="API error"):
            client.chat("Hello")

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_submit_function_outputs_rate_limit(
        self, mock_openai_class: MagicMock, client: AzureChatClient
    ) -> None:
        """Test handling of rate limit errors in submit_function_outputs."""
        mock_client = MagicMock()
        mock_error = OpenAIRateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429),
            body={"error": {"message": "Rate limit exceeded"}},
        )
        mock_client.responses.create.side_effect = mock_error
        mock_openai_class.return_value = mock_client

        with pytest.raises(AzureAPIError, match="Rate limited"):
            client.submit_function_outputs(
                previous_response_id="resp_123",
                function_outputs=[],
            )

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_chat_stream_connection_error(
        self, mock_openai_class: MagicMock, client: AzureChatClient
    ) -> None:
        """Test handling of connection errors in streaming."""
        mock_client = MagicMock()
        mock_client.responses.create.side_effect = APIConnectionError(request=MagicMock())
        mock_openai_class.return_value = mock_client

        with pytest.raises(AzureAPIError, match="Connection error"):
            client.chat_stream("Hello")


class TestAzureChatClientChatMethod:
    """Tests for the chat method."""

    @pytest.fixture
    def client(self) -> AzureChatClient:
        """Create a client instance."""
        return AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4o",
            deployment_name="my-gpt4o",
        )

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_chat_with_list_input(
        self, mock_openai_class: MagicMock, client: AzureChatClient
    ) -> None:
        """Test chat with list input (multi-modal)."""
        mock_api_client = MagicMock()
        mock_response = MagicMock()
        mock_response.id = "resp_list"
        mock_response.status = "completed"
        mock_response.output = []
        mock_response.output_text = "Response to list input"
        mock_response.usage = None
        mock_api_client.responses.create.return_value = mock_response
        mock_openai_class.return_value = mock_api_client

        input_items = [{"type": "text", "text": "Hello"}]
        response = client.chat(input_items)

        assert response.content == "Response to list input"
        # Verify input was passed correctly
        call_kwargs = mock_api_client.responses.create.call_args[1]
        assert call_kwargs["input"] == input_items

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_chat_passes_all_parameters(
        self, mock_openai_class: MagicMock, client: AzureChatClient
    ) -> None:
        """Test that all parameters are passed to API."""
        mock_api_client = MagicMock()
        mock_response = MagicMock()
        mock_response.id = "resp_params"
        mock_response.status = "completed"
        mock_response.output = []
        mock_response.output_text = "OK"
        mock_response.usage = None
        mock_api_client.responses.create.return_value = mock_response
        mock_openai_class.return_value = mock_api_client

        tools = [{"type": "function", "name": "test", "parameters": {}}]

        client.chat(
            user_input="Test",
            instructions="Be helpful",
            tools=tools,
            previous_response_id="resp_prev",
        )

        call_kwargs = mock_api_client.responses.create.call_args[1]
        assert call_kwargs["model"] == "my-gpt4o"
        assert call_kwargs["input"] == "Test"
        assert call_kwargs["instructions"] == "Be helpful"
        assert call_kwargs["tools"] is not None
        assert call_kwargs["previous_response_id"] == "resp_prev"
