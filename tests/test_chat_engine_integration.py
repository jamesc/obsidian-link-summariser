"""
Integration tests for the Chat Engine with Azure OpenAI Responses API.

These tests run against the real Azure API and require valid credentials.
They test the full ChatEngine workflow including tool calling.

To run these tests:
    pytest tests/test_chat_engine_integration.py -v -m integration

Required environment variables:
    - CHAT_AZURE_API_KEY: Azure API key
    - CHAT_AZURE_ENDPOINT: Azure endpoint URL
    - CHAT_MODEL: Model name (optional, defaults to gpt-4.1-mini)
    - CHAT_AZURE_DEPLOYMENT: Deployment name (optional)
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

from summarize_links.chat.engine import ChatEngine
from summarize_links.chat.tools.base import Tool, ToolRegistry, ToolResult
from summarize_links.config import Config

logger = logging.getLogger(__name__)

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


def has_azure_credentials() -> bool:
    """Check if Azure credentials are available. Loads from .env file if needed."""
    # Load .env file for integration tests
    load_dotenv()

    api_key = os.environ.get("CHAT_AZURE_API_KEY") or os.environ.get("AZURE_API_KEY")
    endpoint = os.environ.get("CHAT_AZURE_ENDPOINT") or os.environ.get("AZURE_ENDPOINT")
    return bool(api_key and endpoint)


@pytest.fixture
def integration_config(tmp_path: Path) -> Config:
    """Create a Config for integration testing."""
    if not has_azure_credentials():
        pytest.skip("Azure credentials not available")

    return Config(
        model_provider="azure",
        vault_path=tmp_path,
        out_folder="Summaries",
        # Azure settings from environment
        azure_api_key=os.environ.get("CHAT_AZURE_API_KEY") or os.environ.get("AZURE_API_KEY", ""),
        azure_endpoint=os.environ.get("CHAT_AZURE_ENDPOINT")
        or os.environ.get("AZURE_ENDPOINT", ""),
        chat_azure_api_key=os.environ.get("CHAT_AZURE_API_KEY")
        or os.environ.get("AZURE_API_KEY", ""),
        chat_azure_endpoint=os.environ.get("CHAT_AZURE_ENDPOINT")
        or os.environ.get("AZURE_ENDPOINT", ""),
        chat_model=os.environ.get("CHAT_MODEL", "gpt-4.1-mini"),
        chat_azure_deployment=os.environ.get(
            "CHAT_AZURE_DEPLOYMENT", os.environ.get("CHAT_MODEL", "gpt-4.1-mini")
        ),
        chat_streaming=False,  # Non-streaming for easier testing
        chat_confirm_tools=False,  # Auto-execute tools
        # Disable Langfuse for integration tests
        langfuse_public_key="",
        langfuse_secret_key="",
    )


class MockCalculatorTool(Tool):
    """A simple calculator tool for testing."""

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return "Perform basic arithmetic calculations. Supports +, -, *, / operations."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "A simple arithmetic expression like '2 + 2' or '10 * 5'",
                },
            },
            "required": ["expression"],
        }

    def execute(
        self,
        config: Config,
        progress_callback: Callable[[str, str], None] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        expression = kwargs.get("expression", "")
        try:
            # Very simple and safe eval for basic arithmetic
            # Only allow digits, operators, spaces, and parentheses
            allowed_chars = set("0123456789+-*/(). ")
            if not all(c in allowed_chars for c in expression):
                return ToolResult(
                    success=False,
                    message=f"Invalid characters in expression: {expression}",
                    error="Expression contains invalid characters",
                )

            result = eval(expression)  # Safe for our limited character set
            return ToolResult(
                success=True,
                message=f"The result of {expression} is {result}",
                data={"expression": expression, "result": result},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Could not calculate: {expression}",
                error=str(e),
            )


class MockMemoryTool(Tool):
    """A tool that stores and retrieves values for testing memory."""

    _memory: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return (
            "Store or retrieve values from memory. "
            "Use action='store' with key and value, or action='retrieve' with key."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["store", "retrieve"],
                    "description": "Whether to store or retrieve a value",
                },
                "key": {
                    "type": "string",
                    "description": "The key to store/retrieve",
                },
                "value": {
                    "type": "string",
                    "description": "The value to store (only for action='store')",
                },
            },
            "required": ["action", "key"],
        }

    def execute(
        self,
        config: Config,
        progress_callback: Callable[[str, str], None] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        action = kwargs.get("action")
        key = kwargs.get("key", "")

        if action == "store":
            value = kwargs.get("value", "")
            MockMemoryTool._memory[key] = value
            return ToolResult(
                success=True,
                message=f"Stored '{value}' under key '{key}'",
                data={"key": key, "value": value},
            )
        elif action == "retrieve":
            if key in MockMemoryTool._memory:
                value = MockMemoryTool._memory[key]
                return ToolResult(
                    success=True,
                    message=f"Value for '{key}' is '{value}'",
                    data={"key": key, "value": value},
                )
            else:
                return ToolResult(
                    success=False,
                    message=f"Key '{key}' not found in memory",
                    error="Key not found",
                )
        else:
            return ToolResult(
                success=False,
                message=f"Unknown action: {action}",
                error="Invalid action",
            )


@pytest.fixture
def test_tools() -> ToolRegistry:
    """Create a registry with test tools."""
    registry = ToolRegistry()
    registry.register(MockCalculatorTool())
    registry.register(MockMemoryTool())
    # Clear memory between tests
    MockMemoryTool._memory.clear()
    return registry


class TestChatEngineBasic:
    """Basic integration tests for ChatEngine."""

    def test_simple_message(self, integration_config: Config) -> None:
        """Test processing a simple message."""
        engine = ChatEngine(
            config=integration_config,
            tool_registry=ToolRegistry(),  # Empty registry
        )

        response = engine.process_message("What is 2 + 2? Just give me the number.")

        assert len(response) > 0
        assert "4" in response

        logger.info("Response: %s", response)

    def test_conversation_context(self, integration_config: Config) -> None:
        """Test that conversation context is maintained."""
        engine = ChatEngine(
            config=integration_config,
            tool_registry=ToolRegistry(),
        )

        # First message
        engine.process_message("My favorite programming language is Python.")

        # Second message should have context
        response = engine.process_message("What is my favorite programming language?")

        assert "python" in response.lower()

        logger.info("Response: %s", response)

    def test_session_tracking(self, integration_config: Config) -> None:
        """Test that session ID is generated and tracked."""
        engine = ChatEngine(
            config=integration_config,
            tool_registry=ToolRegistry(),
        )

        assert engine.session_id is not None
        assert len(engine.session_id) > 0

        initial_count = engine._message_count
        engine.process_message("Hello")
        assert engine._message_count == initial_count + 1

        logger.info("Session ID: %s", engine.session_id)


class TestChatEngineToolCalling:
    """Integration tests for ChatEngine tool calling."""

    def test_tool_execution(self, integration_config: Config, test_tools: ToolRegistry) -> None:
        """Test that tools are called and results are processed."""
        engine = ChatEngine(
            config=integration_config,
            tool_registry=test_tools,
        )

        response = engine.process_message(
            "Use the calculator to compute 15 * 7 and tell me the result."
        )

        # Should contain the result (105)
        assert "105" in response

        logger.info("Response: %s", response)

    def test_tool_with_followup(self, integration_config: Config, test_tools: ToolRegistry) -> None:
        """Test tool execution followed by a question about the result."""
        engine = ChatEngine(
            config=integration_config,
            tool_registry=test_tools,
        )

        # Use calculator
        response1 = engine.process_message("Calculate 100 / 4 using the calculator")
        assert "25" in response1

        # Ask about the result
        response2 = engine.process_message(
            "What was the result of my last calculation? Just the number."
        )
        assert "25" in response2

        logger.info("Response 1: %s", response1)
        logger.info("Response 2: %s", response2)

    def test_memory_tool_store_and_retrieve(
        self, integration_config: Config, test_tools: ToolRegistry
    ) -> None:
        """Test storing and retrieving with memory tool."""
        engine = ChatEngine(
            config=integration_config,
            tool_registry=test_tools,
        )

        # Store a value
        response1 = engine.process_message(
            "Use the memory tool to store the value 'hello world' under key 'greeting'"
        )

        # Retrieve the value
        response2 = engine.process_message(
            "Use the memory tool to retrieve the value stored under key 'greeting'"
        )

        assert "hello world" in response2.lower()

        logger.info("Store response: %s", response1)
        logger.info("Retrieve response: %s", response2)


class TestChatEngineStreaming:
    """Integration tests for streaming responses."""

    def test_streaming_basic(self, integration_config: Config) -> None:
        """Test basic streaming response."""
        # Enable streaming
        integration_config.chat_streaming = True

        engine = ChatEngine(
            config=integration_config,
            tool_registry=ToolRegistry(),
        )

        chunks = list(engine.process_message_streaming("Count from 1 to 3."))

        assert len(chunks) > 0
        full_response = "".join(chunks)
        assert len(full_response) > 0

        logger.info("Streaming chunks: %d", len(chunks))
        logger.info("Full response: %s", full_response)

    def test_streaming_with_tool(
        self, integration_config: Config, test_tools: ToolRegistry
    ) -> None:
        """Test streaming with tool execution."""
        integration_config.chat_streaming = True

        engine = ChatEngine(
            config=integration_config,
            tool_registry=test_tools,
        )

        chunks = list(engine.process_message_streaming("Calculate 8 * 8 using the calculator"))

        full_response = "".join(chunks)
        assert "64" in full_response

        logger.info("Streaming with tool response: %s", full_response)


class TestChatEngineHistoryManagement:
    """Integration tests for history management."""

    def test_clear_history(self, integration_config: Config) -> None:
        """Test clearing conversation history."""
        engine = ChatEngine(
            config=integration_config,
            tool_registry=ToolRegistry(),
        )

        # Establish context
        engine.process_message("Remember: The secret word is 'elephant'.")

        # Clear history
        engine.clear_history()

        # Should NOT remember the secret word
        response = engine.process_message("What was the secret word I mentioned?")

        # After clearing, it shouldn't know
        response_lower = response.lower()
        doesnt_remember = (
            "elephant" not in response_lower or "don't" in response_lower or "not" in response_lower
        )
        assert doesnt_remember

        logger.info("Response after clear: %s", response)

    def test_status(self, integration_config: Config, test_tools: ToolRegistry) -> None:
        """Test getting engine status."""
        engine = ChatEngine(
            config=integration_config,
            tool_registry=test_tools,
        )

        # Process a message to update state
        engine.process_message("Hello")

        status = engine.get_status()

        assert status["provider"] == "azure"
        assert status["model"] == integration_config.chat_model
        assert status["tools"] == 2  # calculator and memory
        assert status["messages"] >= 2  # at least user + assistant
        assert status["session_id"] is not None
        assert status["message_count"] >= 1

        logger.info("Status: %s", status)


class TestChatEngineErrorHandling:
    """Integration tests for error handling."""

    def test_graceful_api_error_handling(self, tmp_path: Path) -> None:
        """Test that API errors are handled gracefully."""
        if not has_azure_credentials():
            pytest.skip("Azure credentials not available")

        # Create config with invalid deployment
        config = Config(
            model_provider="azure",
            vault_path=tmp_path,
            chat_azure_api_key=os.environ.get("CHAT_AZURE_API_KEY")
            or os.environ.get("AZURE_API_KEY", ""),
            chat_azure_endpoint=os.environ.get("CHAT_AZURE_ENDPOINT")
            or os.environ.get("AZURE_ENDPOINT", ""),
            chat_model="invalid-model-name",
            chat_azure_deployment="invalid-deployment",
            langfuse_public_key="",
            langfuse_secret_key="",
        )

        engine = ChatEngine(
            config=config,
            tool_registry=ToolRegistry(),
        )

        # Should return error message, not raise exception
        response = engine.process_message("Hello")
        assert "error" in response.lower()

        logger.info("Error response: %s", response)
