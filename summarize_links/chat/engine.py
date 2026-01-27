"""
Chat engine for orchestrating conversations with tool calling.

This module provides the core ChatEngine class that:
- Manages LLM interactions using Azure OpenAI Responses API
- Handles function calling with automatic conversation chaining
- Maintains conversation context via previous_response_id
- Supports streaming responses
- Optional tool confirmation prompts
- Traces all operations via Langfuse with session-level grouping

The Responses API simplifies conversation management by using previous_response_id
to automatically include conversation history, rather than requiring manual
message array construction.
"""

import contextlib
import logging
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from summarize_links.chat.azure_client import (
    AzureChatClient,
    ChatResponse,
)
from summarize_links.chat.conversation import Conversation
from summarize_links.chat.formatter import ChatFormatter
from summarize_links.chat.prompts import build_system_prompt
from summarize_links.chat.tools.base import ToolRegistry, ToolResult, get_default_registry
from summarize_links.config import Config
from summarize_links.langfuse_tracer import get_tracer
from summarize_links.llm.base import LazyClientMixin

__all__ = [
    "ChatEngine",
]

logger = logging.getLogger(__name__)

# Type for tool confirmation callback
ToolConfirmCallback = Callable[[str, dict[str, Any]], bool]

# Type for progress callback (called during long operations)
# Arguments: (stage: str, detail: str) - e.g., ("Fetching", "https://example.com")
ProgressCallback = Callable[[str, str], None]


class ChatEngine(LazyClientMixin[AzureChatClient]):
    """
    Orchestrates chat interactions with tool calling support.

    Uses Azure OpenAI Responses API for chat interactions. The Responses API
    provides automatic conversation state management via previous_response_id,
    simplifying multi-turn conversations.

    Handles:
    - Sending messages to the LLM with automatic context chaining
    - Processing function calls (with optional confirmation)
    - Maintaining local conversation history for display/save
    - Streaming responses
    - Coordinating with the formatter for output
    - Session-level tracing via Langfuse (all messages grouped by session_id)
    """

    def __init__(
        self,
        config: Config,
        formatter: ChatFormatter | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_confirm_callback: ToolConfirmCallback | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """
        Initialize the chat engine.

        Args:
            config: Application configuration.
            formatter: ChatFormatter for output. Creates one if not provided.
            tool_registry: Tool registry. Uses default if not provided.
            tool_confirm_callback: Optional callback for tool confirmation.
                                   If provided, called with (tool_name, args).
                                   Return True to execute, False to skip.
            progress_callback: Optional callback for progress updates during
                             long-running operations (e.g., tool execution).
                             Called with (stage, detail) strings.
        """
        self.config = config
        self.formatter = formatter or ChatFormatter()
        self.tools = tool_registry if tool_registry is not None else get_default_registry()
        self._tool_confirm_callback = tool_confirm_callback
        self._progress_callback = progress_callback

        # Session tracking for Langfuse
        # All messages in this conversation will be grouped under the same session_id
        self.session_id = str(uuid.uuid4())
        self._message_count = 0

        # Build system prompt with vault context (used as instructions)
        # Also get the Langfuse prompt object for linking generations
        self._instructions, self._langfuse_prompt = build_system_prompt(config)

        # Track the last response ID for conversation chaining
        # The Responses API uses this to maintain conversation context
        self._previous_response_id: str | None = None

        # Initialize conversation for local history (display/save purposes)
        # Note: The Responses API manages its own context via previous_response_id
        self.conversation = Conversation(
            system_prompt=self._instructions,
            max_messages=config.chat_max_history_messages,
            max_context_tokens=config.chat_max_context_tokens,
            model=config.chat_model,
        )

        # Initialize Azure client for chat
        self._client: AzureChatClient | None = None

        logger.debug(
            "Initialized ChatEngine with Responses API (session_id=%s, chat_model=%s, "
            "chat_deployment=%s, tools=%d, streaming=%s, confirm_tools=%s, has_progress_cb=%s)",
            self.session_id,
            config.chat_model,
            config.chat_azure_deployment,
            len(self.tools),
            config.chat_streaming,
            config.chat_confirm_tools,
            progress_callback is not None,
        )

    def _get_client(self) -> AzureChatClient:
        """Get or create the Azure chat client."""
        return self._get_or_create_client(
            lambda: AzureChatClient(
                api_key=self.config.chat_azure_api_key,
                endpoint=self.config.chat_azure_endpoint,
                model=self.config.chat_model,
                deployment_name=self.config.chat_azure_deployment,
            ),
            "AzureChatClient",
        )

    def _report_progress(self, stage: str, detail: str) -> None:
        """
        Report progress to the callback if registered.

        Args:
            stage: Current stage (e.g., "Fetching", "Summarizing", "Running").
            detail: Detail about what is being processed (e.g., URL, tool name).
        """
        if self._progress_callback:
            try:
                self._progress_callback(stage, detail)
            except Exception as e:
                logger.warning("Progress callback failed: %s", e)

    def process_message(self, user_message: str) -> str:
        """
        Process a user message and return the assistant's response.

        This method:
        1. Increments message counter for session tracking
        2. Creates a Langfuse trace for this message turn (linked to session)
        3. Adds the user message to local conversation history
        4. Sends to LLM with previous_response_id for context
        5. Handles any function calls
        6. Returns the final response

        Args:
            user_message: The user's input message.

        Returns:
            The assistant's response text.
        """
        # Increment message counter for session tracking
        self._message_count += 1

        # Add user message to local history (for display/save)
        self.conversation.add_user_message(user_message)

        # Get tracer for session-level tracing
        tracer = get_tracer()

        # Wrap the entire message processing in a session-aware trace
        # All nested trace_generation/trace_span calls become children
        with tracer.trace_message(
            session_id=self.session_id,
            message_number=self._message_count,
            user_input=user_message,
            metadata={
                "model": self.config.chat_model,
                "deployment": self.config.chat_azure_deployment,
            },
        ) as trace:
            response = self._process_with_azure(user_message)

            # Update both the span and trace-level output for visibility in Langfuse UI
            if trace and hasattr(trace, "update"):
                with contextlib.suppress(Exception):
                    trace.update(
                        output={"assistant_response": response},
                        metadata={
                            "response_length": len(response),
                            "message_count": self._message_count,
                        },
                    )

            # Also update trace-level output for session view visibility
            tracer.update_trace_output(
                output={"assistant_response": response},
                metadata={
                    "response_length": len(response),
                    "message_count": self._message_count,
                },
            )

            return response

    def _process_with_azure(self, user_message: str) -> str:
        """
        Process message using Azure OpenAI Responses API.

        Uses previous_response_id for automatic conversation context management.
        Called within a trace_message context, so all LLM calls are
        automatically nested under the session-aware message trace.

        Args:
            user_message: The user's message.

        Returns:
            Assistant's response.
        """
        client = self._get_client()

        # Get tool schemas in OpenAI format
        tools = self.tools.get_schemas() if self.tools else None

        tracer = get_tracer()

        # Trace the LLM generation (nested under the message trace)
        # Link to Langfuse prompt for tracking prompt versions
        # Truncate instructions for logging to avoid excessive output
        instructions_preview = (
            self._instructions[:200] + "..."
            if len(self._instructions) > 200
            else self._instructions
        )
        with tracer.trace_generation(
            name="chat_generate",
            input_data={
                "user_message": user_message,
                "previous_response_id": self._previous_response_id,
                "instructions": instructions_preview,
            },
            metadata={
                "provider": "azure_responses_api",
                "has_tools": bool(tools),
                "tool_count": len(tools) if tools else 0,
            },
            model=self.config.chat_model,
            prompt=self._langfuse_prompt,  # Link to Langfuse prompt
        ) as generation:
            try:
                response = client.chat(
                    user_input=user_message,
                    instructions=self._instructions,
                    tools=tools,
                    previous_response_id=self._previous_response_id,
                )

                # Update previous_response_id for conversation chaining
                self._previous_response_id = response.response_id

                # Update generation with response data
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        update_data: dict[str, Any] = {}

                        # Capture response content
                        update_data["output"] = {
                            "text": response.content,
                            "function_calls": (
                                [
                                    {"name": fc.name, "args": fc.arguments}
                                    for fc in response.function_calls
                                ]
                                if response.function_calls
                                else None
                            ),
                            "status": response.status,
                            "response_id": response.response_id,
                        }

                        # Capture usage if available
                        if response.usage:
                            update_data["usage_details"] = response.usage

                        generation.update(**update_data)

            except Exception as e:
                logger.error("Azure API error: %s", e)
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        generation.update(
                            output={"error": str(e)},
                            metadata={"error": True},
                        )
                return f"Error communicating with AI: {e}"

        # Check for function calls
        if response.has_function_calls:
            return self._handle_function_calls(response)

        # No function calls - return text response
        response_text = response.content or ""

        # Add to local conversation history
        self.conversation.add_assistant_message(response_text)
        return response_text

    def _handle_function_calls(
        self,
        response: ChatResponse,
    ) -> str:
        """
        Handle function calls from the LLM.

        Executes each function (with optional confirmation) and submits results
        back using the Responses API's submit_function_outputs method.
        All function executions and the follow-up LLM call are traced via
        Langfuse, nested under the current message trace for session grouping.

        Args:
            response: The ChatResponse containing function calls.

        Returns:
            Final assistant response after function execution.
        """
        tracer = get_tracer()
        client = self._get_client()
        tools = self.tools.get_schemas() if self.tools else None

        # Process function calls
        function_calls = response.function_calls or []

        # Add assistant's message with function calls to local conversation history
        assistant_function_calls = [
            {"id": fc.call_id, "name": fc.name, "arguments": fc.arguments} for fc in function_calls
        ]
        self.conversation.add_assistant_tool_call(response.content, assistant_function_calls)

        # Build function outputs for Responses API
        function_outputs: list[dict[str, Any]] = []

        # Execute each function and collect results
        for fc in function_calls:
            tool_name = fc.name
            tool_args = fc.arguments

            logger.info("Executing function: %s with args: %s", tool_name, tool_args)

            # Check for tool confirmation if enabled
            if self.config.chat_confirm_tools and self._tool_confirm_callback:
                confirmed = self._tool_confirm_callback(tool_name, tool_args)
                if not confirmed:
                    logger.info("Function %s was rejected by user", tool_name)
                    result = ToolResult(
                        success=False,
                        message=f"Function {tool_name} was skipped by user",
                        error="User declined to execute function",
                    )
                    # Add skipped result to local conversation
                    self.conversation.add_tool_result(
                        tool_call_id=fc.call_id,
                        name=tool_name,
                        content=result.to_content(),
                    )
                    function_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": fc.call_id,
                            "output": result.to_content(),
                        }
                    )
                    continue

            # Show progress
            self.formatter.print_tool_start(tool_name, f"Running {tool_name}")
            self._report_progress("Running", tool_name)

            # Trace function execution as a span
            with tracer.trace_span(
                name=f"function_{tool_name}",
                input_data={"function": tool_name, "args": tool_args},
                metadata={"function_name": tool_name},
            ) as span:
                # Execute the function with progress callback
                result = self.tools.execute(
                    tool_name,
                    self.config,
                    progress_callback=self._progress_callback,
                    **tool_args,
                )

                # Update span with result
                if span and hasattr(span, "update"):
                    with contextlib.suppress(Exception):
                        span.update(
                            output={
                                "success": result.success,
                                "message": result.message,
                            },
                            metadata={
                                "success": result.success,
                                "has_data": result.data is not None,
                            },
                        )

            # Show result (truncate for display but LLM gets full result)
            display_message = (
                result.message[:100] + "..." if len(result.message) > 100 else result.message
            )
            self.formatter.print_tool_result(tool_name, result.success, display_message)

            # Add function result to local conversation
            self.conversation.add_tool_result(
                tool_call_id=fc.call_id,
                name=tool_name,
                content=result.to_content(),
            )

            # Add to function outputs for Responses API
            function_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": fc.call_id,
                    "output": result.to_content(),
                }
            )

        # Trace the follow-up generation
        with tracer.trace_generation(
            name="chat_generate_followup",
            input_data={
                "function_results_count": len(function_calls),
                "functions_executed": [fc.name for fc in function_calls],
                "previous_response_id": response.response_id,
            },
            metadata={
                "provider": "azure_responses_api",
                "is_followup": True,
            },
            model=self.config.chat_model,
            prompt=self._langfuse_prompt,  # Link to Langfuse prompt
        ) as generation:
            # Submit function outputs and get final response
            try:
                final_response = client.submit_function_outputs(
                    previous_response_id=response.response_id,
                    function_outputs=function_outputs,
                    instructions=self._instructions,
                    tools=tools,
                )

                # Update previous_response_id for conversation chaining
                self._previous_response_id = final_response.response_id

                response_text = final_response.content or "Function executed successfully."

                # Update generation with response
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        update_data: dict[str, Any] = {
                            "output": {
                                "text": response_text,
                                "response_id": final_response.response_id,
                            },
                        }

                        # Capture usage if available
                        if final_response.usage:
                            update_data["usage_details"] = final_response.usage

                        generation.update(**update_data)

                # Check for more function calls (recursive)
                if final_response.has_function_calls:
                    return self._handle_function_calls(final_response)

                self.conversation.add_assistant_message(response_text)
                return response_text

            except Exception as e:
                logger.error("Error getting final response: %s", e)
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        generation.update(
                            output={"error": str(e)},
                            metadata={"error": True},
                        )
                return f"Function executed but error getting response: {e}"

    def process_message_streaming(
        self,
        user_message: str,
    ) -> Iterator[str]:
        """
        Process a user message with streaming response.

        Yields content chunks as they arrive from the LLM.
        Note: Function calls are handled non-streaming, only the final
        response text is streamed.

        Args:
            user_message: The user's input message.

        Yields:
            Content chunks as they arrive.
        """
        # Increment message counter for session tracking
        self._message_count += 1

        # Add user message to local history
        self.conversation.add_user_message(user_message)

        # Get tracer for session-level tracing
        tracer = get_tracer()

        # Use proper with block for trace context manager
        with tracer.trace_message(
            session_id=self.session_id,
            message_number=self._message_count,
            user_input=user_message,
            metadata={
                "model": self.config.chat_model,
                "deployment": self.config.chat_azure_deployment,
                "streaming": True,
            },
        ) as trace:
            # Stream the response
            full_response = ""
            for chunk in self._process_with_azure_streaming(user_message):
                full_response += chunk
                yield chunk

            # Update both span and trace-level output for visibility in Langfuse UI
            if trace and hasattr(trace, "update"):
                with contextlib.suppress(Exception):
                    trace.update(
                        output={"assistant_response": full_response},
                        metadata={
                            "response_length": len(full_response),
                            "message_count": self._message_count,
                        },
                    )

            # Also update trace-level output for session view visibility
            tracer.update_trace_output(
                output={"assistant_response": full_response},
                metadata={
                    "response_length": len(full_response),
                    "message_count": self._message_count,
                },
            )

    def _process_with_azure_streaming(
        self,
        user_message: str,
    ) -> Iterator[str]:
        """
        Process message using Azure OpenAI Responses API with streaming.

        Args:
            user_message: The user's message.

        Yields:
            Content chunks as they arrive.
        """
        client = self._get_client()

        # Get tool schemas in OpenAI format
        tools = self.tools.get_schemas() if self.tools else None

        tracer = get_tracer()

        # Start generation trace
        gen_ctx = tracer.trace_generation(
            name="chat_generate_stream",
            input_data={
                "user_message": user_message,
                "previous_response_id": self._previous_response_id,
            },
            metadata={
                "provider": "azure_responses_api",
                "has_tools": bool(tools),
                "streaming": True,
            },
            model=self.config.chat_model,
            prompt=self._langfuse_prompt,  # Link to Langfuse prompt
        )
        generation = gen_ctx.__enter__()

        # Track exception info for proper context manager exit
        exc_info: tuple[type[BaseException], BaseException, Any] | tuple[None, None, None] = (
            None,
            None,
            None,
        )

        try:
            stream_response = client.chat_stream(
                user_input=user_message,
                instructions=self._instructions,
                tools=tools,
                previous_response_id=self._previous_response_id,
            )

            # Yield content chunks
            yield from stream_response

            # Update previous_response_id for conversation chaining
            if stream_response.response_id:
                self._previous_response_id = stream_response.response_id

            # After streaming, check for function calls
            if stream_response.has_function_calls:
                # Update generation with function call info
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        generation.update(
                            output={
                                "text": stream_response.content,
                                "function_calls": (
                                    [
                                        {"name": fc.name, "args": fc.arguments}
                                        for fc in (stream_response.function_calls or [])
                                    ]
                                ),
                            },
                            usage_details=stream_response.usage,
                        )

                # Handle function calls (non-streaming)
                response = stream_response.to_response()
                result = self._handle_function_calls(response)
                yield result
            else:
                # No function calls - update generation and add to local conversation
                response_text = stream_response.content or ""
                if generation and hasattr(generation, "update"):
                    with contextlib.suppress(Exception):
                        generation.update(
                            output=response_text,
                            usage_details=stream_response.usage,
                        )
                self.conversation.add_assistant_message(response_text)

        except Exception as e:
            # Capture exception info for proper context manager exit
            exc_info = sys.exc_info()
            logger.error("Azure API streaming error: %s", e)
            if generation and hasattr(generation, "update"):
                with contextlib.suppress(Exception):
                    generation.update(
                        output={"error": str(e)},
                        metadata={"error": True},
                    )
            yield f"Error communicating with AI: {e}"
        finally:
            gen_ctx.__exit__(*exc_info)

    def save_session(self, path: Path | None = None) -> Path:
        """
        Save the current conversation session to disk.

        Args:
            path: Optional path to save to. Uses config default if not provided.

        Returns:
            Path where session was saved.
        """
        if path is None:
            if self.config.vault_path:
                path = self.config.vault_path / self.config.chat_save_path
            else:
                path = Path(self.config.chat_save_path)

        self.conversation.save(path)
        logger.info("Saved session to %s", path)
        return path

    def load_session(self, path: Path | None = None) -> bool:
        """
        Load a conversation session from disk.

        Args:
            path: Optional path to load from. Uses config default if not provided.

        Returns:
            True if session was loaded, False if file not found.
        """
        if path is None:
            if self.config.vault_path:
                path = self.config.vault_path / self.config.chat_save_path
            else:
                path = Path(self.config.chat_save_path)

        if not path.exists():
            logger.warning("Session file not found: %s", path)
            return False

        try:
            self.conversation = Conversation.load(path)
            logger.info("Loaded session from %s (%d messages)", path, len(self.conversation))
            return True
        except Exception as e:
            logger.error("Failed to load session: %s", e)
            return False

    def clear_history(self, reset_message_count: bool = False) -> None:
        """
        Clear conversation history, keeping system prompt.

        This resets both the local conversation history and the
        previous_response_id for the Responses API, effectively
        starting a fresh conversation.

        Args:
            reset_message_count: If True, also reset the message counter.
                               Note: This does NOT start a new session.
                               Use a new ChatEngine instance for a new session.
        """
        self.conversation.clear(keep_system=True)
        # Reset the previous_response_id to start fresh with Responses API
        self._previous_response_id = None
        if reset_message_count:
            self._message_count = 0
        logger.info("Cleared conversation history (reset_count=%s)", reset_message_count)

    def get_status(self) -> dict[str, Any]:
        """
        Get status information about the chat engine.

        Returns:
            Dict with status information including session tracking.
        """
        return {
            "provider": "azure",
            "model": self.config.chat_model,
            "deployment": self.config.chat_azure_deployment,
            "tools": len(self.tools),
            "messages": len(self.conversation),
            "tokens": self.conversation.get_total_tokens(),
            "max_tokens": self.config.chat_max_context_tokens,
            "vault": str(self.config.vault_path),
            "session_id": self.session_id,
            "message_count": self._message_count,
            "streaming": self.config.chat_streaming,
            "confirm_tools": self.config.chat_confirm_tools,
        }
