"""
Integration tests for Azure OpenAI Responses API.

These tests run against the real Azure API and require valid credentials.
They are marked with @pytest.mark.integration and are skipped by default.

To run these tests:
    pytest tests/test_azure_responses_api_integration.py -v -m integration

Required environment variables:
    - CHAT_AZURE_API_KEY: Azure API key
    - CHAT_AZURE_ENDPOINT: Azure endpoint URL (e.g., https://your-resource.openai.azure.com)
    - CHAT_MODEL: Model name (optional, defaults to gpt-4.1-mini)
    - CHAT_AZURE_DEPLOYMENT: Deployment name (optional, defaults to CHAT_MODEL)
"""

import json
import logging
import os
from typing import Any

import pytest
from dotenv import load_dotenv

from summarize_links.chat.azure_client import (
    AzureChatClient,
    ChatResponse,
    FunctionCall,
    StreamingChatResponse,
)
from summarize_links.exceptions import AzureAPIError

logger = logging.getLogger(__name__)

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


def get_azure_credentials() -> dict[str, str]:
    """
    Get Azure credentials from environment variables.

    Loads from .env file if not already in environment.

    Returns:
        Dict with api_key, endpoint, model, and deployment.

    Raises:
        pytest.skip: If required credentials are missing.
    """
    # Load .env file for integration tests (only affects this test module)
    load_dotenv()

    api_key = os.environ.get("CHAT_AZURE_API_KEY") or os.environ.get("AZURE_API_KEY")
    endpoint = os.environ.get("CHAT_AZURE_ENDPOINT") or os.environ.get("AZURE_ENDPOINT")
    model = os.environ.get("CHAT_MODEL", "gpt-4.1-mini")
    deployment = os.environ.get("CHAT_AZURE_DEPLOYMENT", model)

    if not api_key:
        pytest.skip("CHAT_AZURE_API_KEY or AZURE_API_KEY environment variable not set")

    if not endpoint:
        pytest.skip("CHAT_AZURE_ENDPOINT or AZURE_ENDPOINT environment variable not set")

    return {
        "api_key": api_key,
        "endpoint": endpoint,
        "model": model,
        "deployment": deployment,
    }


@pytest.fixture
def azure_client() -> AzureChatClient:
    """Create an Azure client with real credentials."""
    creds = get_azure_credentials()
    return AzureChatClient(
        api_key=creds["api_key"],
        endpoint=creds["endpoint"],
        model=creds["model"],
        deployment_name=creds["deployment"],
    )


class TestAzureResponsesAPIBasic:
    """Basic tests for Azure OpenAI Responses API."""

    def test_simple_chat_response(self, azure_client: AzureChatClient) -> None:
        """Test that we can get a simple chat response."""
        response = azure_client.chat(
            user_input="What is 2 + 2? Reply with just the number.",
        )

        # Verify response structure
        assert isinstance(response, ChatResponse)
        assert response.response_id is not None
        assert response.status == "completed"
        assert response.content is not None
        assert len(response.content) > 0

        # The answer should contain "4"
        assert "4" in response.content

        logger.info("Response ID: %s", response.response_id)
        logger.info("Content: %s", response.content)
        logger.info("Usage: %s", response.usage)

    def test_chat_with_instructions(self, azure_client: AzureChatClient) -> None:
        """Test chat with system instructions."""
        instructions = (
            "You are a helpful assistant named TestBot. Always mention your name in responses."
        )
        response = azure_client.chat(
            user_input="What is your name?",
            instructions=instructions,
        )

        assert response.status == "completed"
        assert response.content is not None
        # Should mention the name from instructions
        assert "TestBot" in response.content or "testbot" in response.content.lower()

        logger.info("Content: %s", response.content)

    def test_chat_usage_tracking(self, azure_client: AzureChatClient) -> None:
        """Test that usage information is returned."""
        response = azure_client.chat(
            user_input="Say hello in exactly one word.",
        )

        assert response.status == "completed"
        assert response.usage is not None
        assert "input" in response.usage
        assert "output" in response.usage
        assert "total" in response.usage
        assert response.usage["input"] > 0
        assert response.usage["output"] > 0
        assert response.usage["total"] == response.usage["input"] + response.usage["output"]

        logger.info("Usage: %s", response.usage)


class TestAzureResponsesAPIConversation:
    """Tests for multi-turn conversation chaining."""

    def test_conversation_chaining(self, azure_client: AzureChatClient) -> None:
        """Test that previous_response_id maintains conversation context."""
        # First message
        response1 = azure_client.chat(
            user_input="My favorite color is blue. Remember this.",
        )
        assert response1.status == "completed"
        assert response1.response_id is not None

        logger.info("First response ID: %s", response1.response_id)

        # Second message using previous_response_id
        response2 = azure_client.chat(
            user_input="What is my favorite color?",
            previous_response_id=response1.response_id,
        )

        assert response2.status == "completed"
        assert response2.content is not None
        # Should remember "blue" from the previous message
        assert "blue" in response2.content.lower()

        logger.info("Second response: %s", response2.content)

    def test_three_turn_conversation(self, azure_client: AzureChatClient) -> None:
        """Test a three-turn conversation."""
        # Turn 1: Set up context
        r1 = azure_client.chat(user_input="Let's count. I'll start: One.")
        assert r1.status == "completed"

        # Turn 2: Continue
        r2 = azure_client.chat(
            user_input="Continue counting.",
            previous_response_id=r1.response_id,
        )
        assert r2.status == "completed"

        # Turn 3: Verify context is maintained
        r3 = azure_client.chat(
            user_input="What number did I start with?",
            previous_response_id=r2.response_id,
        )
        assert r3.status == "completed"
        assert r3.content is not None
        assert "one" in r3.content.lower() or "1" in r3.content

        logger.info("Final response: %s", r3.content)


class TestAzureResponsesAPIFunctionCalling:
    """Tests for function calling with Responses API."""

    @staticmethod
    def get_weather_tool() -> list[dict[str, Any]]:
        """Get a sample weather tool definition."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City name, e.g., 'London'",
                            },
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

    def test_function_call_request(self, azure_client: AzureChatClient) -> None:
        """Test that the model requests function calls when appropriate."""
        tools = self.get_weather_tool()

        response = azure_client.chat(
            user_input="What's the weather like in London?",
            tools=tools,
        )

        assert response.status == "completed"
        assert response.has_function_calls is True
        assert response.function_calls is not None
        assert len(response.function_calls) >= 1

        # Verify the function call structure
        fc = response.function_calls[0]
        assert isinstance(fc, FunctionCall)
        assert fc.name == "get_weather"
        assert fc.call_id is not None
        assert "location" in fc.arguments
        assert "london" in fc.arguments["location"].lower()

        logger.info("Function call: %s(%s)", fc.name, fc.arguments)

    def test_submit_function_outputs(self, azure_client: AzureChatClient) -> None:
        """Test submitting function outputs and getting a response."""
        tools = self.get_weather_tool()

        # First, get a function call
        response1 = azure_client.chat(
            user_input="What's the weather in Paris?",
            tools=tools,
        )

        assert response1.has_function_calls is True
        assert response1.function_calls is not None
        fc = response1.function_calls[0]

        # Submit the function output
        function_outputs = [
            {
                "type": "function_call_output",
                "call_id": fc.call_id,
                "output": json.dumps({"temperature": 22, "conditions": "sunny", "humidity": 45}),
            }
        ]

        response2 = azure_client.submit_function_outputs(
            previous_response_id=response1.response_id,
            function_outputs=function_outputs,
        )

        assert response2.status == "completed"
        assert response2.content is not None
        # Response should mention the weather data we provided
        assert any(
            word in response2.content.lower() for word in ["22", "sunny", "warm", "nice", "good"]
        )

        logger.info("Final response: %s", response2.content)

    def test_multiple_function_calls(self, azure_client: AzureChatClient) -> None:
        """Test handling multiple function calls in one response."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Get current time in a city",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            },
        ]

        response = azure_client.chat(
            user_input="What's the weather AND time in New York?",
            instructions="Use both tools to get weather and time information.",
            tools=tools,
        )

        # Model should request at least one function call
        # Note: Some models may not always call multiple tools
        assert response.has_function_calls is True
        assert response.function_calls is not None

        logger.info("Function calls: %d", len(response.function_calls))
        for fc in response.function_calls:
            logger.info("  - %s(%s)", fc.name, fc.arguments)


class TestAzureResponsesAPIStreaming:
    """Tests for streaming responses."""

    def test_streaming_basic(self, azure_client: AzureChatClient) -> None:
        """Test basic streaming response."""
        stream = azure_client.chat_stream(
            user_input="Count from 1 to 5, one number per line.",
        )

        assert isinstance(stream, StreamingChatResponse)

        # Collect chunks
        chunks: list[str] = []
        for chunk in stream:
            chunks.append(chunk)
            logger.debug("Chunk: %r", chunk)

        # Verify we got multiple chunks
        assert len(chunks) > 0

        # Full content should be available after streaming
        full_content = stream.content
        assert len(full_content) > 0

        # Should have response_id after streaming
        assert stream.response_id is not None

        # Status should be completed
        assert stream.status == "completed"

        logger.info("Total chunks: %d", len(chunks))
        logger.info("Full content: %s", full_content)

    def test_streaming_to_response(self, azure_client: AzureChatClient) -> None:
        """Test converting streaming response to ChatResponse."""
        stream = azure_client.chat_stream(
            user_input="Say 'Hello, world!'",
        )

        # Consume the stream
        for _ in stream:
            pass

        # Convert to regular response
        response = stream.to_response()

        assert isinstance(response, ChatResponse)
        assert response.response_id is not None
        assert response.content is not None
        assert response.status == "completed"

        logger.info("Converted response: %s", response.content)

    def test_streaming_with_function_call(self, azure_client: AzureChatClient) -> None:
        """Test streaming response that includes function calls."""
        tools = [
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

        stream = azure_client.chat_stream(
            user_input="What's the weather in Tokyo?",
            tools=tools,
        )

        # Consume the stream
        for _ in stream:
            pass

        # After streaming, should have function calls
        assert stream.has_function_calls is True
        assert stream.function_calls is not None

        fc = stream.function_calls[0]
        assert fc.name == "get_weather"
        assert fc.call_id is not None

        logger.info("Streaming function call: %s(%s)", fc.name, fc.arguments)

    def test_streaming_chained_conversation(self, azure_client: AzureChatClient) -> None:
        """Test that streaming maintains conversation context."""
        # First message (non-streaming for simplicity)
        r1 = azure_client.chat(user_input="My name is Alice.")
        assert r1.response_id is not None

        # Second message (streaming)
        stream = azure_client.chat_stream(
            user_input="What's my name?",
            previous_response_id=r1.response_id,
        )

        # Consume stream
        for _ in stream:
            pass

        # Should remember the name
        assert "alice" in stream.content.lower()

        logger.info("Streaming response with context: %s", stream.content)


class TestAzureResponsesAPIErrorHandling:
    """Tests for error handling."""

    def test_invalid_model(self) -> None:
        """Test error handling for invalid model/deployment."""
        creds = get_azure_credentials()

        client = AzureChatClient(
            api_key=creds["api_key"],
            endpoint=creds["endpoint"],
            model="invalid-model-that-does-not-exist",
            deployment_name="invalid-deployment",
        )

        with pytest.raises(AzureAPIError):
            client.chat(user_input="Hello")

    def test_invalid_api_key(self) -> None:
        """Test error handling for invalid API key."""
        creds = get_azure_credentials()

        client = AzureChatClient(
            api_key="invalid-api-key",
            endpoint=creds["endpoint"],
            model=creds["model"],
            deployment_name=creds["deployment"],
        )

        with pytest.raises(AzureAPIError):
            client.chat(user_input="Hello")

    def test_invalid_endpoint(self) -> None:
        """Test error handling for invalid endpoint."""
        creds = get_azure_credentials()

        client = AzureChatClient(
            api_key=creds["api_key"],
            endpoint="https://invalid-endpoint-that-does-not-exist.openai.azure.com",
            model=creds["model"],
        )

        with pytest.raises(AzureAPIError):
            client.chat(user_input="Hello")


class TestAzureResponsesAPIToolConversion:
    """Tests for tool format conversion (Chat Completions -> Responses API)."""

    def test_tools_converted_correctly(self, azure_client: AzureChatClient) -> None:
        """Test that tools in Chat Completions format work correctly."""
        # Tools in Chat Completions format (nested under "function")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "Perform a calculation",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string", "description": "Math expression"},
                        },
                        "required": ["expression"],
                    },
                },
            }
        ]

        # Should work without error and call the function
        response = azure_client.chat(
            user_input="Calculate 5 times 7 using the calculate function",
            tools=tools,
        )

        # Should request function call
        assert response.has_function_calls is True
        assert response.function_calls is not None
        assert response.function_calls[0].name == "calculate"

        logger.info("Tool conversion worked correctly")


class TestAzureResponsesAPILongConversation:
    """Tests for longer conversations."""

    def test_five_turn_conversation(self, azure_client: AzureChatClient) -> None:
        """Test a 5-turn conversation maintains context throughout."""
        # Build up context over multiple turns
        facts = [
            ("My favorite food is pizza.", "pizza"),
            ("My pet is a cat named Whiskers.", "whiskers"),
            ("I live in Seattle.", "seattle"),
            ("My hobby is photography.", "photography"),
        ]

        prev_id = None
        for fact, _ in facts:
            response = azure_client.chat(
                user_input=f"Remember this: {fact}",
                previous_response_id=prev_id,
            )
            assert response.status == "completed"
            prev_id = response.response_id

        # Now ask about all the facts
        final_response = azure_client.chat(
            user_input="What are all the facts you know about me? List them.",
            previous_response_id=prev_id,
        )

        assert final_response.status == "completed"
        assert final_response.content is not None
        content_lower = final_response.content.lower()

        # Should remember most facts
        remembered = sum(1 for _, keyword in facts if keyword in content_lower)
        logger.info("Remembered %d/%d facts", remembered, len(facts))
        logger.info("Response: %s", final_response.content)

        # Should remember at least some facts (context window may truncate)
        assert remembered >= 2, f"Expected at least 2 facts, got {remembered}"
