"""
Azure OpenAI client for chat interactions using the Responses API.

This module provides a dedicated client for chat using Azure OpenAI's
Responses API with function calling support. The Responses API provides
a simpler interface with built-in conversation state management via
previous_response_id.

See: https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/responses
"""

import json
import logging
from collections.abc import Iterator
from typing import Any

from openai import APIConnectionError, APIError, OpenAI
from openai import RateLimitError as OpenAIRateLimitError

from summarize_links.exceptions import AzureAPIError
from summarize_links.llm.base import LazyClientMixin

__all__ = [
    "AzureChatClient",
    "FunctionCall",
    "ChatResponse",
    "StreamingChatResponse",
]

logger = logging.getLogger(__name__)

# Default chat model
DEFAULT_CHAT_MODEL = "gpt-4.1-mini"


class FunctionCall:
    """Represents a function call from the assistant in the Responses API."""

    def __init__(
        self,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> None:
        """
        Initialize a function call.

        Args:
            call_id: Unique identifier for this function call.
            name: Name of the function to call.
            arguments: Arguments to pass to the function.
        """
        self.call_id = call_id
        self.name = name
        self.arguments = arguments

    @classmethod
    def from_output_item(cls, item: Any) -> "FunctionCall":
        """
        Create from a Responses API output item.

        Args:
            item: Output item with type="function_call" from API response.

        Returns:
            FunctionCall instance.
        """
        # Parse arguments if they're a string
        args = item.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except json.JSONDecodeError:
                logger.warning("Failed to parse function arguments: %s", args)
                args = {}

        return cls(
            call_id=item.call_id,
            name=item.name,
            arguments=args,
        )


class ChatResponse:
    """Response from the Responses API."""

    def __init__(
        self,
        response_id: str,
        content: str | None,
        function_calls: list[FunctionCall] | None,
        status: str,
        usage: dict[str, int] | None = None,
    ) -> None:
        """
        Initialize chat response.

        Args:
            response_id: ID of this response (for chaining with previous_response_id).
            content: Text content of the response.
            function_calls: List of function calls requested by the model.
            status: Status of the response (completed, failed, etc).
            usage: Token usage information.
        """
        self.response_id = response_id
        self.content = content
        self.function_calls = function_calls
        self.status = status
        self.usage = usage

    @property
    def has_function_calls(self) -> bool:
        """Check if the response contains function calls."""
        return bool(self.function_calls)

    @classmethod
    def from_api_response(cls, response: Any) -> "ChatResponse":
        """
        Create from Responses API response.

        Args:
            response: Raw response from the API.

        Returns:
            ChatResponse instance.
        """
        # Extract text content using output_text property if available
        content = getattr(response, "output_text", None)

        # If no output_text, try to extract from output items
        if content is None and response.output:
            for item in response.output:
                if item.type == "message":
                    for content_item in getattr(item, "content", []):
                        if getattr(content_item, "type", None) == "output_text":
                            content = content_item.text
                            break

        # Extract function calls from output
        function_calls = None
        if response.output:
            calls = []
            for item in response.output:
                if item.type == "function_call":
                    calls.append(FunctionCall.from_output_item(item))
            if calls:
                function_calls = calls

        # Extract usage
        usage = None
        if response.usage:
            usage = {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
                "total": response.usage.total_tokens,
            }

        return cls(
            response_id=response.id,
            content=content,
            function_calls=function_calls,
            status=response.status,
            usage=usage,
        )


class StreamingChatResponse:
    """
    Streaming response from the Responses API.

    Yields content chunks as they arrive from the API.
    Aggregates function calls which cannot be streamed incrementally.
    """

    def __init__(self, stream: Any) -> None:
        """
        Initialize streaming response.

        Args:
            stream: The streaming response from OpenAI.
        """
        self._stream = stream
        self._content_chunks: list[str] = []
        self._function_calls: list[FunctionCall] = []
        self._function_call_buffer: dict[str, dict[str, Any]] = {}
        # Map item_id to call_id (from response.output_item.added events)
        self._item_to_call_id: dict[str, str] = {}
        self._response_id: str | None = None
        self._status: str = "in_progress"
        self._usage: dict[str, int] | None = None
        self._consumed = False

    def __iter__(self) -> Iterator[str]:
        """
        Iterate over content chunks.

        Yields:
            Content chunks as they arrive.
        """
        if self._consumed:
            # If already consumed, yield from cached chunks
            yield from self._content_chunks
            return

        for event in self._stream:
            # Handle different event types
            event_type = event.type

            # Capture response ID from response.created event
            if event_type == "response.created":
                self._response_id = event.response.id

            # Handle output item added - capture call_id and function name for function calls
            elif event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if item and getattr(item, "type", None) == "function_call":
                    # ResponseFunctionToolCall has both id (item_id), call_id, and name
                    item_id = getattr(item, "id", None)
                    call_id = getattr(item, "call_id", None)
                    name = getattr(item, "name", None)
                    if item_id and call_id:
                        self._item_to_call_id[item_id] = call_id
                    # Initialize buffer with function name from the added event
                    if item_id:
                        self._function_call_buffer[item_id] = {
                            "name": name or "",
                            "call_id": call_id or item_id,
                            "arguments": "",
                        }

            # Handle text content deltas
            elif event_type == "response.output_text.delta":
                chunk = event.delta
                self._content_chunks.append(chunk)
                yield chunk

            # Handle function call arguments delta - accumulate arguments
            elif event_type == "response.function_call_arguments.delta":
                item_id = getattr(event, "item_id", None)
                if item_id:
                    # Initialize buffer if not already done (fallback case)
                    if item_id not in self._function_call_buffer:
                        self._function_call_buffer[item_id] = {
                            "name": getattr(event, "name", "") or "",
                            "call_id": self._item_to_call_id.get(item_id, item_id),
                            "arguments": "",
                        }
                    self._function_call_buffer[item_id]["arguments"] += event.delta

            # Handle function call completion
            elif event_type == "response.function_call_arguments.done":
                # Get item_id from the event
                item_id = event.item_id
                # Look up the actual call_id from our mapping
                # (captured from response.output_item.added event)
                call_id = self._item_to_call_id.get(item_id, item_id)

                # Get function name from buffer (captured from output_item.added)
                # or fall back to event.name
                buffer = self._function_call_buffer.get(item_id, {})
                name = buffer.get("name") or getattr(event, "name", None) or ""

                try:
                    args = json.loads(event.arguments) if event.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                self._function_calls.append(
                    FunctionCall(
                        call_id=call_id,
                        name=name,
                        arguments=args,
                    )
                )

            # Handle response completion
            elif event_type == "response.completed":
                self._status = "completed"
                if hasattr(event, "response") and event.response:
                    self._response_id = event.response.id
                    if hasattr(event.response, "usage") and event.response.usage:
                        self._usage = {
                            "input": event.response.usage.input_tokens,
                            "output": event.response.usage.output_tokens,
                            "total": event.response.usage.total_tokens,
                        }

            # Handle response done event (final event)
            elif event_type == "response.done" and hasattr(event, "response") and event.response:
                self._response_id = event.response.id
                self._status = event.response.status or "completed"

        self._consumed = True

    @property
    def content(self) -> str:
        """Get the full content (after streaming completes)."""
        if not self._consumed:
            # Consume the stream to get content
            for _ in self:
                pass
        return "".join(self._content_chunks)

    @property
    def function_calls(self) -> list[FunctionCall] | None:
        """Get function calls (after streaming completes)."""
        if not self._consumed:
            # Consume the stream to get function calls
            for _ in self:
                pass
        return self._function_calls if self._function_calls else None

    @property
    def has_function_calls(self) -> bool:
        """Check if the response contains function calls."""
        if not self._consumed:
            # Consume the stream to check
            for _ in self:
                pass
        return bool(self._function_calls)

    @property
    def response_id(self) -> str | None:
        """Get the response ID for chaining."""
        if not self._consumed:
            for _ in self:
                pass
        return self._response_id

    @property
    def status(self) -> str:
        """Get the status."""
        if not self._consumed:
            for _ in self:
                pass
        return self._status

    @property
    def usage(self) -> dict[str, int] | None:
        """Get usage information."""
        if not self._consumed:
            for _ in self:
                pass
        return self._usage

    def to_response(self) -> ChatResponse:
        """
        Convert to a regular ChatResponse after consuming stream.

        Returns:
            ChatResponse with aggregated content and function calls.
        """
        return ChatResponse(
            response_id=self.response_id or "",
            content=self.content,
            function_calls=self.function_calls,
            status=self.status,
            usage=self.usage,
        )


class AzureChatClient(LazyClientMixin[OpenAI]):
    """
    Client for chat interactions using Azure OpenAI Responses API.

    Uses the Responses API which provides:
    - Simpler conversation state with previous_response_id
    - Built-in function calling support
    - Streaming with partial results

    Note: Uses base OpenAI client with Azure base_url, as the Responses API
    requires the v1 endpoint format.
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model: str = DEFAULT_CHAT_MODEL,
        deployment_name: str | None = None,
    ) -> None:
        """
        Initialize the Azure chat client.

        Args:
            api_key: Azure API key.
            endpoint: Azure endpoint URL (e.g., https://your-resource.openai.azure.com).
            model: Model name for the deployment.
            deployment_name: Azure deployment name. Defaults to model if not provided.
        """
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._deployment_name = deployment_name or model
        self._client: OpenAI | None = None

        # Avoid logging model/deployment names to prevent security scanning alerts
        logger.debug("Initialized AzureChatClient with Responses API")

    def _get_client(self) -> OpenAI:
        """Get or create the OpenAI client configured for Azure Responses API."""
        # Azure Responses API uses /openai/v1/ base URL
        base_url = f"{self._endpoint}/openai/v1/"
        return self._get_or_create_client(
            lambda: OpenAI(
                api_key=self._api_key,
                base_url=base_url,
            ),
            "AzureResponses",
        )

    def _convert_tools_for_responses_api(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Convert tools from Chat Completions format to Responses API format.

        Chat Completions format::

            {
                "type": "function",
                "function": {"name": "...", "description": "...", "parameters": {...}}
            }

        Responses API format::

            {"type": "function", "name": "...", "description": "...", "parameters": {...}}

        Args:
            tools: Tools in Chat Completions format.

        Returns:
            Tools in Responses API format.
        """
        converted = []
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                # Convert from Chat Completions nested format to flat format
                func = tool["function"]
                converted.append(
                    {
                        "type": "function",
                        "name": func.get("name"),
                        "description": func.get("description", ""),
                        "parameters": func.get("parameters", {}),
                    }
                )
            else:
                # Already in correct format or unknown format, pass through
                converted.append(tool)
        return converted

    def chat(
        self,
        user_input: str | list[dict[str, Any]],
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        previous_response_id: str | None = None,
    ) -> ChatResponse:
        """
        Send a chat request using the Responses API.

        Args:
            user_input: User message string or list of input items.
            instructions: System instructions for the model.
            tools: List of tool definitions (function schemas).
            previous_response_id: ID of previous response for multi-turn.

        Returns:
            ChatResponse with content and/or function calls.

        Raises:
            AzureAPIError: When the API returns an error.
        """
        client = self._get_client()

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": self._deployment_name,
            "input": user_input,
        }

        if instructions:
            kwargs["instructions"] = instructions

        if tools:
            # Convert tools from Chat Completions format to Responses API format
            kwargs["tools"] = self._convert_tools_for_responses_api(tools)

        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id

        try:
            logger.debug("Sending chat request to Azure Responses API")

            response = client.responses.create(**kwargs)
            return ChatResponse.from_api_response(response)

        except OpenAIRateLimitError as e:
            logger.error("Rate limited by Azure API: %s", type(e).__name__)
            raise AzureAPIError(f"Rate limited: {type(e).__name__}") from e

        except APIConnectionError as e:
            logger.error("Connection error to Azure API: %s", type(e).__name__)
            raise AzureAPIError(f"Connection error: {type(e).__name__}") from e

        except APIError as e:
            logger.error("Azure API error: %s", type(e).__name__)
            raise AzureAPIError(f"API error: {type(e).__name__}") from e

    def chat_stream(
        self,
        user_input: str | list[dict[str, Any]],
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        previous_response_id: str | None = None,
    ) -> StreamingChatResponse:
        """
        Send a streaming chat request using the Responses API.

        Args:
            user_input: User message string or list of input items.
            instructions: System instructions for the model.
            tools: List of tool definitions (function schemas).
            previous_response_id: ID of previous response for multi-turn.

        Returns:
            StreamingChatResponse that yields content chunks.

        Raises:
            AzureAPIError: When the API returns an error.
        """
        client = self._get_client()

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": self._deployment_name,
            "input": user_input,
            "stream": True,
        }

        if instructions:
            kwargs["instructions"] = instructions

        if tools:
            # Convert tools from Chat Completions format to Responses API format
            kwargs["tools"] = self._convert_tools_for_responses_api(tools)

        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id

        try:
            logger.debug("Sending streaming chat request to Azure Responses API")
            stream = client.responses.create(**kwargs)
            return StreamingChatResponse(stream)

        except OpenAIRateLimitError as e:
            logger.error("Rate limited by Azure API: %s", type(e).__name__)
            raise AzureAPIError(f"Rate limited: {type(e).__name__}") from e

        except APIConnectionError as e:
            logger.error("Connection error to Azure API: %s", type(e).__name__)
            raise AzureAPIError(f"Connection error: {type(e).__name__}") from e

        except APIError as e:
            logger.error("Azure API error: %s", type(e).__name__)
            raise AzureAPIError(f"API error: {type(e).__name__}") from e

    def submit_function_outputs(
        self,
        previous_response_id: str,
        function_outputs: list[dict[str, Any]],
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        """
        Submit function call outputs and get the next response.

        Args:
            previous_response_id: ID of the response that made the function calls.
            function_outputs: List of function call outputs in format:
                [{"type": "function_call_output", "call_id": "...", "output": "..."}]
            instructions: System instructions (optional, for context).
            tools: Tool definitions (optional, for follow-up calls).

        Returns:
            ChatResponse with the model's response to the function outputs.

        Raises:
            AzureAPIError: When the API returns an error.
        """
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model": self._deployment_name,
            "input": function_outputs,
            "previous_response_id": previous_response_id,
        }

        if instructions:
            kwargs["instructions"] = instructions

        if tools:
            # Convert tools from Chat Completions format to Responses API format
            kwargs["tools"] = self._convert_tools_for_responses_api(tools)

        try:
            logger.debug("Submitting function outputs to Azure Responses API")
            response = client.responses.create(**kwargs)
            return ChatResponse.from_api_response(response)

        except OpenAIRateLimitError as e:
            logger.error("Rate limited by Azure API: %s", type(e).__name__)
            raise AzureAPIError(f"Rate limited: {type(e).__name__}") from e

        except APIConnectionError as e:
            logger.error("Connection error to Azure API: %s", type(e).__name__)
            raise AzureAPIError(f"Connection error: {type(e).__name__}") from e

        except APIError as e:
            logger.error("Azure API error: %s", type(e).__name__)
            raise AzureAPIError(f"API error: {type(e).__name__}") from e

    @property
    def model(self) -> str:
        """Get the model name."""
        return self._model

    @property
    def deployment_name(self) -> str:
        """Get the deployment name."""
        return self._deployment_name
