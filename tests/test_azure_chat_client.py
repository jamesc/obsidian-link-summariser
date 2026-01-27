"""
Tests for the Azure chat client module using the Responses API.
"""

from unittest.mock import MagicMock, patch

import pytest

from summarize_links.chat.azure_client import (
    AzureChatClient,
    ChatResponse,
    FunctionCall,
)


class TestFunctionCall:
    """Tests for the FunctionCall class."""

    def test_create_function_call(self) -> None:
        """Test creating a function call."""
        fc = FunctionCall(call_id="call_123", name="test_function", arguments={"a": 1})
        assert fc.call_id == "call_123"
        assert fc.name == "test_function"
        assert fc.arguments == {"a": 1}

    def test_from_output_item(self) -> None:
        """Test creating from API output item."""
        mock_item = MagicMock()
        mock_item.call_id = "call_456"
        mock_item.name = "another_function"
        mock_item.arguments = '{"b": 2}'

        fc = FunctionCall.from_output_item(mock_item)

        assert fc.call_id == "call_456"
        assert fc.name == "another_function"
        assert fc.arguments == {"b": 2}

    def test_from_output_item_dict_arguments(self) -> None:
        """Test creating from API output item with dict arguments."""
        mock_item = MagicMock()
        mock_item.call_id = "call_789"
        mock_item.name = "dict_function"
        mock_item.arguments = {"c": 3}  # Already a dict

        fc = FunctionCall.from_output_item(mock_item)

        assert fc.call_id == "call_789"
        assert fc.name == "dict_function"
        assert fc.arguments == {"c": 3}

    def test_from_output_item_invalid_json(self) -> None:
        """Test handling invalid JSON in arguments."""
        mock_item = MagicMock()
        mock_item.call_id = "call_bad"
        mock_item.name = "broken_function"
        mock_item.arguments = "not valid json"

        fc = FunctionCall.from_output_item(mock_item)

        assert fc.call_id == "call_bad"
        assert fc.name == "broken_function"
        assert fc.arguments == {}


class TestChatResponse:
    """Tests for the ChatResponse class."""

    def test_response_with_content(self) -> None:
        """Test response with text content."""
        resp = ChatResponse(
            response_id="resp_123",
            content="Hello!",
            function_calls=None,
            status="completed",
        )
        assert resp.content == "Hello!"
        assert resp.has_function_calls is False
        assert resp.response_id == "resp_123"
        assert resp.status == "completed"

    def test_response_with_function_calls(self) -> None:
        """Test response with function calls."""
        function_calls = [FunctionCall(call_id="call_1", name="func", arguments={})]
        resp = ChatResponse(
            response_id="resp_456",
            content=None,
            function_calls=function_calls,
            status="completed",
        )
        assert resp.content is None
        assert resp.has_function_calls is True
        assert resp.function_calls is not None
        assert len(resp.function_calls) == 1

    def test_response_with_usage(self) -> None:
        """Test response with usage information."""
        resp = ChatResponse(
            response_id="resp_789",
            content="Hi",
            function_calls=None,
            status="completed",
            usage={"input": 10, "output": 5, "total": 15},
        )
        assert resp.usage == {"input": 10, "output": 5, "total": 15}

    def test_from_api_response(self) -> None:
        """Test creating from API response object."""
        mock_response = MagicMock()
        mock_response.id = "resp_api"
        mock_response.output_text = "Response text"
        mock_response.output = []
        mock_response.status = "completed"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 20
        mock_response.usage.output_tokens = 10
        mock_response.usage.total_tokens = 30

        resp = ChatResponse.from_api_response(mock_response)

        assert resp.response_id == "resp_api"
        assert resp.content == "Response text"
        assert resp.status == "completed"
        assert resp.usage == {"input": 20, "output": 10, "total": 30}

    def test_from_api_response_with_function_calls(self) -> None:
        """Test creating from API response with function calls."""
        mock_func_call = MagicMock()
        mock_func_call.type = "function_call"
        mock_func_call.call_id = "call_api"
        mock_func_call.name = "api_function"
        mock_func_call.arguments = '{"param": "value"}'

        mock_response = MagicMock()
        mock_response.id = "resp_func"
        mock_response.output_text = None
        mock_response.output = [mock_func_call]
        mock_response.status = "completed"
        mock_response.usage = None

        resp = ChatResponse.from_api_response(mock_response)

        assert resp.response_id == "resp_func"
        assert resp.has_function_calls is True
        assert resp.function_calls is not None
        assert len(resp.function_calls) == 1
        assert resp.function_calls[0].name == "api_function"


class TestAzureChatClient:
    """Tests for the AzureChatClient class."""

    def test_init(self) -> None:
        """Test client initialization."""
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4.1-mini",
        )
        assert client.model == "gpt-4.1-mini"
        assert client.deployment_name == "gpt-4.1-mini"

    def test_init_custom_deployment(self) -> None:
        """Test client with custom deployment name."""
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4.1-mini",
            deployment_name="my-deployment",
        )
        assert client.model == "gpt-4.1-mini"
        assert client.deployment_name == "my-deployment"

    def test_convert_tools_for_responses_api(self) -> None:
        """Test that tools are converted from Chat Completions to Responses API format."""
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4.1-mini",
        )

        # Chat Completions format (nested under "function")
        chat_completions_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                        "required": ["location"],
                    },
                },
            }
        ]

        # Convert
        converted = client._convert_tools_for_responses_api(chat_completions_tools)

        # Responses API format (flat structure)
        assert len(converted) == 1
        assert converted[0]["type"] == "function"
        assert converted[0]["name"] == "get_weather"
        assert converted[0]["description"] == "Get weather for a location"
        assert converted[0]["parameters"]["type"] == "object"
        assert "function" not in converted[0]

    def test_convert_tools_already_in_responses_format(self) -> None:
        """Test that tools already in Responses API format pass through unchanged."""
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4.1-mini",
        )

        # Already in Responses API format
        responses_tools = [
            {
                "type": "function",
                "name": "get_weather",
                "description": "Get weather for a location",
                "parameters": {"type": "object"},
            }
        ]

        converted = client._convert_tools_for_responses_api(responses_tools)

        assert converted == responses_tools

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_chat_simple(self, mock_openai_class: MagicMock) -> None:
        """Test simple chat request."""
        # Setup mock
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.id = "resp_simple"
        mock_response.output_text = "Hello!"
        mock_response.output = []
        mock_response.status = "completed"
        mock_response.usage = MagicMock()
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.usage.total_tokens = 15

        mock_client.responses.create.return_value = mock_response

        # Test
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4.1-mini",
        )
        response = client.chat(user_input="Hi")

        assert response.content == "Hello!"
        assert response.has_function_calls is False
        assert response.usage == {"input": 10, "output": 5, "total": 15}
        assert response.response_id == "resp_simple"

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_chat_with_tools(self, mock_openai_class: MagicMock) -> None:
        """Test chat request with tool definitions."""
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        # Mock function call response
        mock_func_call = MagicMock()
        mock_func_call.type = "function_call"
        mock_func_call.call_id = "call_123"
        mock_func_call.name = "test_tool"
        mock_func_call.arguments = '{"arg": "value"}'

        mock_response = MagicMock()
        mock_response.id = "resp_tools"
        mock_response.output_text = None
        mock_response.output = [mock_func_call]
        mock_response.status = "completed"
        mock_response.usage = None

        mock_client.responses.create.return_value = mock_response

        # Test with Chat Completions format tools (nested under "function")
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4.1-mini",
        )
        tools = [
            {
                "type": "function",
                "function": {"name": "test_tool", "description": "A test tool"},
            }
        ]
        response = client.chat(user_input="Call a tool", tools=tools)

        assert response.has_function_calls is True
        assert response.function_calls is not None
        assert len(response.function_calls) == 1
        assert response.function_calls[0].name == "test_tool"
        assert response.function_calls[0].arguments == {"arg": "value"}

        # Verify tools were converted to Responses API format
        call_kwargs = mock_client.responses.create.call_args[1]
        assert call_kwargs["tools"][0]["name"] == "test_tool"
        assert call_kwargs["tools"][0]["description"] == "A test tool"
        assert "function" not in call_kwargs["tools"][0]

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_chat_with_previous_response_id(self, mock_openai_class: MagicMock) -> None:
        """Test chat with conversation chaining."""
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.id = "resp_chained"
        mock_response.output_text = "Chained response"
        mock_response.output = []
        mock_response.status = "completed"
        mock_response.usage = None

        mock_client.responses.create.return_value = mock_response

        # Test
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4.1-mini",
        )
        response = client.chat(
            user_input="Follow up",
            previous_response_id="resp_previous",
        )

        # Verify previous_response_id was passed
        mock_client.responses.create.assert_called_once()
        call_kwargs = mock_client.responses.create.call_args[1]
        assert call_kwargs["previous_response_id"] == "resp_previous"
        assert response.response_id == "resp_chained"

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_submit_function_outputs(self, mock_openai_class: MagicMock) -> None:
        """Test submitting function outputs."""
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.id = "resp_after_func"
        mock_response.output_text = "Function completed"
        mock_response.output = []
        mock_response.status = "completed"
        mock_response.usage = None

        mock_client.responses.create.return_value = mock_response

        # Test
        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4.1-mini",
        )
        function_outputs = [
            {
                "type": "function_call_output",
                "call_id": "call_123",
                "output": '{"result": "success"}',
            }
        ]
        response = client.submit_function_outputs(
            previous_response_id="resp_func",
            function_outputs=function_outputs,
        )

        assert response.content == "Function completed"
        # Verify the call was made correctly
        mock_client.responses.create.assert_called_once()
        call_kwargs = mock_client.responses.create.call_args[1]
        assert call_kwargs["previous_response_id"] == "resp_func"
        assert call_kwargs["input"] == function_outputs

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_chat_rate_limit_error(self, mock_openai_class: MagicMock) -> None:
        """Test handling rate limit error."""
        from openai import RateLimitError

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_client.responses.create.side_effect = RateLimitError(
            "Rate limited",
            response=MagicMock(status_code=429),
            body={"error": {"message": "Rate limited"}},
        )

        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4.1-mini",
        )

        from summarize_links.exceptions import AzureAPIError

        with pytest.raises(AzureAPIError, match="Rate limited"):
            client.chat(user_input="Hi")

    @patch("summarize_links.chat.azure_client.OpenAI")
    def test_chat_api_error(self, mock_openai_class: MagicMock) -> None:
        """Test handling API error."""
        from openai import APIError

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_client.responses.create.side_effect = APIError(
            "Something went wrong",
            request=MagicMock(),
            body={"error": {"message": "Something went wrong"}},
        )

        client = AzureChatClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4.1-mini",
        )

        from summarize_links.exceptions import AzureAPIError

        with pytest.raises(AzureAPIError, match="API error"):
            client.chat(user_input="Hi")
