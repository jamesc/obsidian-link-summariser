"""
Langfuse integration for tracing and evaluation.

Provides a context manager for tracing LLM operations and pipeline stages.
Langfuse is REQUIRED - the application will not run without valid credentials.

## Data Capture Best Practices

To enable effective evaluation and debugging in Langfuse, we capture:

1. **Generation Input**: Raw prompt sent to the LLM
   - Complete user prompt text
   - System instructions are part of the API call context
   - This is the actual text the model receives

2. **Generation Output**: Raw text response from the LLM
   - Unmodified model output (JSON string for structured responses)
   - Before any parsing or post-processing
   - Exactly what the model returned

3. **Generation Metadata**: Context and parsed results
   - Source URL, page title, content length
   - Parsed summary metadata (tags, content type)
   - Any relevant processing information

4. **Usage Details**: Token consumption for cost tracking
   - Input tokens (prompt + system instruction)
   - Output tokens (model response)
   - Total tokens

This comprehensive data capture enables:
- LLM-as-a-Judge evaluations on actual model outputs
- Prompt engineering and optimization
- Cost analysis and token optimization
- Quality monitoring and regression detection
- Debugging failed or low-quality responses
- A/B testing of prompts, models, and parameters

## Session-Level Tracing for Conversations

For multi-turn conversations (e.g., chat CLI), we use Langfuse Sessions:
- Each conversation gets a unique `session_id`
- Each user message creates a separate trace within the session
- All traces in a session are grouped in the Langfuse UI
- Enables conversation replay and per-session metrics

See: https://langfuse.com/docs/observability/features/sessions
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from langfuse import Langfuse, propagate_attributes

__all__ = [
    "LangfuseTracer",
    "get_tracer",
    "initialize_tracer",
    "propagate_attributes",
]

logger = logging.getLogger(__name__)


class MockLangfuseTracer:
    """No-op tracer for mock mode."""

    @contextmanager
    def trace_url_processing(
        self,
        url: str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[None, None, None]:
        """No-op trace - yields None."""
        yield None

    @contextmanager
    def trace_span(
        self,
        name: str,
        input_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[None, None, None]:
        """No-op span - yields None."""
        yield None

    @contextmanager
    def trace_generation(
        self,
        name: str,
        input_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        prompt: Any | None = None,
    ) -> Generator[None, None, None]:
        """No-op generation - yields None."""
        yield None

    @contextmanager
    def trace_message(
        self,
        session_id: str,
        message_number: int,
        user_input: str,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[None, None, None]:
        """No-op message trace - yields None."""
        yield None

    def update_trace_output(
        self,
        output: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """No-op update trace output."""
        pass

    def score_trace(
        self,
        trace_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        """No-op score."""
        pass

    def flush(self) -> None:
        """No-op flush."""
        pass


class LangfuseTracer:
    """
    Wrapper for Langfuse tracing (REQUIRED).

    All operations require valid Langfuse credentials.
    The application will fail to start if Langfuse is not properly configured.
    """

    def __init__(
        self,
        public_key: str,
        secret_key: str,
        base_url: str | None = None,
    ) -> None:
        """
        Initialize Langfuse tracer.

        Args:
            public_key: Langfuse public API key (required).
            secret_key: Langfuse secret API key (required).
            base_url: Langfuse server URL.

        Raises:
            RuntimeError: If Langfuse initialization or authentication fails.
        """
        try:
            # Initialize Langfuse client directly with parameters
            # This avoids modifying global environment variables
            self._client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=base_url,
            )

            # Verify authentication
            if not self._client.auth_check():
                raise RuntimeError("Langfuse authentication failed - check your credentials")

            logger.info(f"Langfuse tracing enabled (host: {base_url})")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Langfuse (required): {e}") from e

    @contextmanager
    def trace_url_processing(
        self,
        url: str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[Any, None, None]:
        """
        Create a trace for processing a single URL.

        Args:
            url: The URL being processed.
            name: Optional name for the trace (e.g., slug). Defaults to "process_url".
            metadata: Additional metadata to attach to trace.

        Yields:
            Trace object.
        """
        trace_metadata = {
            "source_url": url,
            "timestamp": datetime.now().isoformat(),
            **(metadata or {}),
        }

        try:
            # Use the new OpenTelemetry-based API
            trace_name = name or "process_url"
            with self._client.start_as_current_observation(
                as_type="generation",
                name=trace_name,
                input={"url": url},
                metadata=trace_metadata,
            ) as trace:
                yield trace
        except Exception as e:
            # Log the error but re-raise to allow proper exception handling
            logger.warning(f"Langfuse trace_url_processing encountered error: {e}")
            raise
        finally:
            # Flush to ensure trace is sent (even if exception occurred)
            try:
                self._client.flush()
            except Exception as flush_error:
                logger.debug(f"Failed to flush Langfuse client: {flush_error}")

    @contextmanager
    def trace_span(
        self,
        name: str,
        input_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[Any, None, None]:
        """
        Create a span within the current trace context.

        Uses OpenTelemetry context propagation - automatically becomes a child
        of the current observation. Must be called within a trace_url_processing context.

        Args:
            name: Span name (e.g., "fetch", "extract", "write").
            input_data: Input data for the span.
            metadata: Additional metadata.

        Yields:
            Span object.
        """
        try:
            # Use the new OpenTelemetry-based API
            with self._client.start_as_current_observation(
                as_type="span",
                name=name,
                input=input_data or {},
                metadata=metadata or {},
            ) as span:
                yield span
        except Exception as e:
            # Log the error but re-raise to allow proper exception handling
            logger.warning(f"Langfuse trace_span encountered error: {e}")
            raise

    @contextmanager
    def trace_generation(
        self,
        name: str,
        input_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        prompt: Any | None = None,
    ) -> Generator[Any, None, None]:
        """
        Create a generation observation for an LLM call within the current trace context.

        Uses OpenTelemetry context propagation - automatically becomes a child
        of the current observation. Must be called within a trace_url_processing context.

        Best practices for capturing LLM data:
        - Include full prompt/messages in input_data
        - Capture raw model response in output via generation.update()
        - Include usage_details for token tracking
        - Add relevant metadata (temperature, max_tokens, etc.)
        - Pass prompt object to link to Langfuse prompt management

        Args:
            name: Generation name (e.g., "summarize").
            input_data: Full input data for the generation including:
                       - prompt/messages sent to model
                       - any context or retrieved data
                       - preprocessing results
            metadata: Additional metadata (model config, parameters, etc.).
            model: Model name used for generation.
            prompt: Optional Langfuse prompt object to link to this generation.
                   This enables per-prompt-version metrics in the Langfuse UI.

        Yields:
            Generation object.
            Call generation.update(output=..., usage_details=...) to capture results.
        """
        try:
            # Use the new OpenTelemetry-based API
            generation_metadata = {**(metadata or {})}
            if model:
                generation_metadata["model"] = model

            with self._client.start_as_current_observation(
                as_type="generation",
                name=name,
                input=input_data or {},
                metadata=generation_metadata,
                model=model,
                prompt=prompt,
            ) as generation:
                yield generation
        except Exception as e:
            # Log the error but re-raise to allow proper exception handling
            logger.warning(f"Langfuse trace_generation encountered error: {e}")
            raise

    @contextmanager
    def trace_message(
        self,
        session_id: str,
        message_number: int,
        user_input: str,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[Any, None, None]:
        """
        Create a trace for a single conversation turn with session context.

        This method creates a root-level trace for a single message in a conversation,
        with session_id, name, and input/output properly set at the trace level for
        visibility in the Langfuse session view.

        The session_id links multiple traces (message turns) together, enabling:
        - Session replay in Langfuse UI showing full conversation
        - Per-session metrics aggregation (cost, latency, tokens)
        - Session-level scoring and evaluation

        Args:
            session_id: Unique identifier for the conversation session.
            message_number: The sequence number of this message in the conversation.
            user_input: The user's message text.
            metadata: Additional metadata to attach to the trace.

        Yields:
            The root span object for this message turn.
            All nested trace_generation/trace_span calls become children.
        """
        trace_metadata = {
            "message_number": message_number,
            "timestamp": datetime.now().isoformat(),
            **(metadata or {}),
        }

        try:
            # Create trace name with session prefix for visual linking in Langfuse UI
            # Format: "chat-{session_prefix}#{msg_num}" e.g., "chat-a1b2c3d4#3"
            session_prefix = session_id[:8] if len(session_id) >= 8 else session_id
            trace_name = f"chat-{session_prefix}#{message_number}"

            # Create a root-level span that will become the trace
            with self._client.start_as_current_observation(
                as_type="span",
                name=trace_name,
                input={"user_message": user_input},
                metadata=trace_metadata,
            ) as trace:
                # Update the trace with session_id, name, and input at the trace level
                # This ensures the session view shows proper names and input/output
                self._client.update_current_trace(
                    session_id=session_id,
                    name=trace_name,
                    input={"user_message": user_input},
                    metadata=trace_metadata,
                )
                yield trace
        except Exception as e:
            logger.warning(f"Langfuse trace_message encountered error: {e}")
            raise
        finally:
            # Flush to ensure trace is sent
            try:
                self._client.flush()
            except Exception as flush_error:
                logger.debug(f"Failed to flush Langfuse client: {flush_error}")

    def update_trace_output(
        self,
        output: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Update the current trace with output data.

        This should be called at the end of a trace_message context to ensure
        the trace-level output is visible in the Langfuse session view.

        Args:
            output: Output data for the trace (typically the assistant response).
            metadata: Additional metadata to attach to the trace.
        """
        try:
            update_kwargs: dict[str, Any] = {"output": output}
            if metadata:
                update_kwargs["metadata"] = metadata
            self._client.update_current_trace(**update_kwargs)
        except Exception as e:
            logger.debug(f"Failed to update trace output: {e}")

    def score_trace(
        self,
        trace_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        """
        Add a score to a trace (used in evaluation).

        Args:
            trace_id: The trace ID to score.
            name: Score name (e.g., "relevance", "tag_accuracy").
            value: Numeric score (typically 0.0-1.0).
            comment: Optional text comment.
        """
        try:
            # Use the scoring API (this remains the same in the new SDK)
            self._client.score(  # type: ignore[attr-defined]
                trace_id=trace_id,
                name=name,
                value=value,
                comment=comment,
            )
        except Exception as e:
            logger.warning(f"Failed to score trace: {e}")

    def flush(self) -> None:
        """Flush any pending traces to Langfuse."""
        try:
            self._client.flush()
        except Exception as e:
            logger.warning(f"Failed to flush Langfuse client: {e}")


# Global tracer instance (initialized in CLI)
_global_tracer: LangfuseTracer | MockLangfuseTracer | None = None


def initialize_tracer(config: Any) -> LangfuseTracer:
    """
    Initialize the global Langfuse tracer from config.

    Args:
        config: Application Config object.

    Returns:
        Initialized tracer instance.

    Raises:
        RuntimeError: If tracer initialization fails.
    """
    global _global_tracer

    _global_tracer = LangfuseTracer(
        public_key=config.langfuse_public_key,
        secret_key=config.langfuse_secret_key,
        base_url=config.langfuse_base_url,
    )

    return _global_tracer


def get_tracer() -> LangfuseTracer | MockLangfuseTracer:
    """
    Get the global tracer instance.

    Returns:
        Global tracer (real or mock).
    """
    if _global_tracer is None:
        # Return a mock tracer as fallback (for tests or mock mode)
        return MockLangfuseTracer()

    return _global_tracer
