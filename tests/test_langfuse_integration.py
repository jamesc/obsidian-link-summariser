"""
Integration tests for Langfuse tracing and observability.

These tests run against the real Langfuse API and require valid credentials.
They are marked with @pytest.mark.integration and are skipped by default.

To run these tests:
    pytest tests/test_langfuse_integration.py -v -m integration

Required environment variables:
    - LANGFUSE_PUBLIC_KEY: Langfuse public API key
    - LANGFUSE_SECRET_KEY: Langfuse secret API key
    - LANGFUSE_BASE_URL: Langfuse host URL (optional, defaults to https://cloud.langfuse.com)
"""

import logging
import os
import uuid

import pytest
from dotenv import load_dotenv

from summarize_links.langfuse_tracer import LangfuseTracer, MockLangfuseTracer

logger = logging.getLogger(__name__)

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


def get_langfuse_credentials() -> dict[str, str]:
    """
    Get Langfuse credentials from environment variables.

    Loads from .env file if not already in environment.

    Returns:
        Dict with public_key, secret_key, and base_url.

    Raises:
        pytest.skip: If required credentials are missing.
    """
    # Load .env file for integration tests (only affects this test module)
    load_dotenv()

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    base_url = os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

    if not public_key:
        pytest.skip("LANGFUSE_PUBLIC_KEY environment variable not set")

    if not secret_key:
        pytest.skip("LANGFUSE_SECRET_KEY environment variable not set")

    return {
        "public_key": public_key,
        "secret_key": secret_key,
        "base_url": base_url,
    }


@pytest.fixture
def langfuse_tracer() -> LangfuseTracer:
    """Create a Langfuse tracer with real credentials."""
    creds = get_langfuse_credentials()
    tracer = LangfuseTracer(
        public_key=creds["public_key"],
        secret_key=creds["secret_key"],
        base_url=creds["base_url"],
    )
    return tracer


class TestLangfuseAuthentication:
    """Tests for Langfuse authentication."""

    def test_valid_credentials(self) -> None:
        """Test that tracer initializes with valid credentials."""
        creds = get_langfuse_credentials()

        tracer = LangfuseTracer(
            public_key=creds["public_key"],
            secret_key=creds["secret_key"],
            base_url=creds["base_url"],
        )

        # Should not raise any exceptions
        assert tracer is not None
        logger.info("Successfully authenticated with Langfuse")

    def test_invalid_public_key(self) -> None:
        """Test that invalid public key raises error."""
        creds = get_langfuse_credentials()

        with pytest.raises(RuntimeError, match="authentication failed"):
            LangfuseTracer(
                public_key="pk-lf-invalid-key",
                secret_key=creds["secret_key"],
                base_url=creds["base_url"],
            )

    def test_invalid_secret_key(self) -> None:
        """Test that invalid secret key raises error."""
        creds = get_langfuse_credentials()

        with pytest.raises(RuntimeError, match="authentication failed"):
            LangfuseTracer(
                public_key=creds["public_key"],
                secret_key="sk-lf-invalid-key",
                base_url=creds["base_url"],
            )


class TestLangfuseTraceCreation:
    """Tests for creating traces in Langfuse."""

    def test_simple_trace(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test creating a simple trace."""
        test_url = f"https://example.com/test-{uuid.uuid4().hex[:8]}"

        with langfuse_tracer.trace_url_processing(test_url) as trace:
            assert trace is not None

        # Flush to ensure trace is sent
        langfuse_tracer.flush()

        logger.info(f"Created trace for URL: {test_url}")

    def test_trace_with_name(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test creating a trace with custom name."""
        test_url = "https://example.com/named-trace"
        trace_name = f"test-trace-{uuid.uuid4().hex[:8]}"

        with langfuse_tracer.trace_url_processing(test_url, name=trace_name) as trace:
            assert trace is not None

        langfuse_tracer.flush()

        logger.info(f"Created named trace: {trace_name}")

    def test_trace_with_metadata(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test creating a trace with metadata."""
        test_url = "https://example.com/metadata-trace"
        metadata = {
            "test_run": True,
            "test_id": uuid.uuid4().hex,
            "model": "test-model",
            "tags": ["integration-test", "langfuse"],
        }

        with langfuse_tracer.trace_url_processing(test_url, metadata=metadata) as trace:
            assert trace is not None

        langfuse_tracer.flush()

        logger.info(f"Created trace with metadata: {metadata}")


class TestLangfuseSpans:
    """Tests for span creation within traces."""

    def test_span_within_trace(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test creating a span within a trace context."""
        test_url = f"https://example.com/span-test-{uuid.uuid4().hex[:8]}"

        with langfuse_tracer.trace_url_processing(test_url):
            with langfuse_tracer.trace_span(
                name="fetch_content",
                input_data={"url": test_url},
                metadata={"timeout": 10},
            ) as span:
                assert span is not None

        langfuse_tracer.flush()

        logger.info("Created span within trace")

    def test_nested_spans(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test creating nested spans."""
        test_url = f"https://example.com/nested-spans-{uuid.uuid4().hex[:8]}"

        with langfuse_tracer.trace_url_processing(test_url):
            with langfuse_tracer.trace_span(name="outer_operation") as outer_span:
                assert outer_span is not None

                with langfuse_tracer.trace_span(name="inner_operation_1") as inner_span1:
                    assert inner_span1 is not None

                with langfuse_tracer.trace_span(name="inner_operation_2") as inner_span2:
                    assert inner_span2 is not None

        langfuse_tracer.flush()

        logger.info("Created nested spans")

    def test_multiple_sequential_spans(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test creating multiple sequential spans in a trace."""
        test_url = f"https://example.com/sequential-{uuid.uuid4().hex[:8]}"

        with langfuse_tracer.trace_url_processing(test_url):
            # Span 1: Fetch
            with langfuse_tracer.trace_span(
                name="fetch",
                input_data={"url": test_url},
            ) as span1:
                assert span1 is not None

            # Span 2: Extract
            with langfuse_tracer.trace_span(
                name="extract",
                input_data={"content_length": 1000},
            ) as span2:
                assert span2 is not None

            # Span 3: Write
            with langfuse_tracer.trace_span(
                name="write",
                input_data={"filename": "test.md"},
            ) as span3:
                assert span3 is not None

        langfuse_tracer.flush()

        logger.info("Created multiple sequential spans")


class TestLangfuseGeneration:
    """Tests for generation tracking (LLM calls)."""

    def test_generation_basic(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test creating a generation observation."""
        test_url = f"https://example.com/generation-{uuid.uuid4().hex[:8]}"

        with langfuse_tracer.trace_url_processing(test_url):
            with langfuse_tracer.trace_generation(
                name="summarize",
                model="test-model",
                input_data={"prompt": "Summarize this content"},
            ) as generation:
                assert generation is not None

                # Update with output and usage
                generation.update(
                    output="This is a test summary",
                    usage_details={
                        "input": 50,
                        "output": 20,
                        "total": 70,
                        "unit": "TOKENS",
                    },
                )

        langfuse_tracer.flush()

        logger.info("Created generation with usage tracking")

    def test_generation_with_metadata(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test generation with comprehensive metadata."""
        test_url = f"https://example.com/gen-metadata-{uuid.uuid4().hex[:8]}"

        with langfuse_tracer.trace_url_processing(test_url):
            with langfuse_tracer.trace_generation(
                name="summarize",
                model="gemini-2.5-flash",
                input_data={
                    "prompt": "Summarize the following...",
                    "content_length": 5000,
                },
                metadata={
                    "provider": "google",
                    "temperature": 0.7,
                    "max_tokens": 500,
                },
            ) as generation:
                assert generation is not None

                generation.update(
                    output="Generated summary text",
                    usage_details={
                        "input": 1000,
                        "output": 150,
                        "total": 1150,
                        "unit": "TOKENS",
                    },
                )

        langfuse_tracer.flush()

        logger.info("Created generation with metadata")

    def test_multiple_generations_in_trace(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test multiple LLM calls within one trace."""
        test_url = f"https://example.com/multi-gen-{uuid.uuid4().hex[:8]}"

        with langfuse_tracer.trace_url_processing(test_url):
            # First generation: Extract title
            with langfuse_tracer.trace_generation(
                name="extract_title",
                model="test-model",
            ) as gen1:
                assert gen1 is not None
                gen1.update(
                    output="Extracted Title",
                    usage_details={"input": 100, "output": 10, "total": 110, "unit": "TOKENS"},
                )

            # Second generation: Summarize content
            with langfuse_tracer.trace_generation(
                name="summarize_content",
                model="test-model",
            ) as gen2:
                assert gen2 is not None
                gen2.update(
                    output="Summary text",
                    usage_details={"input": 500, "output": 100, "total": 600, "unit": "TOKENS"},
                )

        langfuse_tracer.flush()

        logger.info("Created multiple generations in one trace")


class TestLangfuseSessionTracking:
    """Tests for session-based conversation tracking."""

    def test_session_trace_creation(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test creating a trace with session context."""
        session_id = f"test-session-{uuid.uuid4().hex}"
        user_input = "Hello, this is a test message"

        with langfuse_tracer.trace_message(
            session_id=session_id,
            message_number=1,
            user_input=user_input,
        ) as trace:
            assert trace is not None

        langfuse_tracer.flush()

        logger.info(f"Created trace with session_id: {session_id}")

    def test_multi_turn_conversation(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test tracking a multi-turn conversation with session linking."""
        session_id = f"test-conversation-{uuid.uuid4().hex}"

        # Turn 1
        with langfuse_tracer.trace_message(
            session_id=session_id,
            message_number=1,
            user_input="What is Python?",
            metadata={"model": "test-model"},
        ) as trace1:
            assert trace1 is not None
            # Simulate assistant response
            langfuse_tracer.update_trace_output(
                output={"assistant_response": "Python is a programming language"},
            )

        # Turn 2
        with langfuse_tracer.trace_message(
            session_id=session_id,
            message_number=2,
            user_input="What are its main features?",
        ) as trace2:
            assert trace2 is not None
            langfuse_tracer.update_trace_output(
                output={"assistant_response": "Python has dynamic typing, readability..."},
            )

        # Turn 3
        with langfuse_tracer.trace_message(
            session_id=session_id,
            message_number=3,
            user_input="Thank you!",
        ) as trace3:
            assert trace3 is not None
            langfuse_tracer.update_trace_output(
                output={"assistant_response": "You're welcome!"},
            )

        langfuse_tracer.flush()

        logger.info(f"Created 3-turn conversation with session_id: {session_id}")

    def test_session_with_generation(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test session trace with nested generation."""
        session_id = f"test-gen-session-{uuid.uuid4().hex}"

        with langfuse_tracer.trace_message(
            session_id=session_id,
            message_number=1,
            user_input="Summarize this article for me",
        ) as trace:
            assert trace is not None

            # Nested generation for LLM call
            with langfuse_tracer.trace_generation(
                name="chat_response",
                model="gpt-4o-mini",
                input_data={"messages": [{"role": "user", "content": "Summarize..."}]},
            ) as generation:
                assert generation is not None
                generation.update(
                    output="Here's a summary...",
                    usage_details={
                        "input": 100,
                        "output": 50,
                        "total": 150,
                        "unit": "TOKENS",
                    },
                )

            # Update trace output
            langfuse_tracer.update_trace_output(
                output={"assistant_response": "Here's a summary..."},
            )

        langfuse_tracer.flush()

        logger.info("Created session trace with nested generation")


class TestLangfusePromptManagement:
    """Tests for Langfuse prompt fetching."""

    def test_fetch_prompt(self, langfuse_tracer: LangfuseTracer) -> None:
        """
        Test fetching a prompt from Langfuse.

        Note: This test requires a prompt named 'summarize-document' to exist
        in your Langfuse project. Skip if not available.
        """
        try:
            # Access the internal Langfuse client
            prompt = langfuse_tracer._client.get_prompt("summarize-document", type="chat")

            # Basic validation
            assert prompt is not None
            assert hasattr(prompt, "prompt")
            assert hasattr(prompt, "version")
            assert hasattr(prompt, "name")

            logger.info(f"Fetched prompt: {prompt.name} (version {prompt.version})")
            logger.info(f"Prompt has {len(prompt.prompt)} messages")

        except Exception as e:
            # Skip if prompt doesn't exist
            pytest.skip(f"Prompt 'summarize-document' not found: {e}")

    def test_generation_with_prompt_linking(self, langfuse_tracer: LangfuseTracer) -> None:
        """
        Test linking a generation to a Langfuse prompt.

        Note: Requires 'summarize-document' prompt to exist.
        """
        try:
            # Fetch the prompt
            prompt = langfuse_tracer._client.get_prompt("summarize-document", type="chat")
            test_url = f"https://example.com/prompt-link-{uuid.uuid4().hex[:8]}"

            with langfuse_tracer.trace_url_processing(test_url):
                with langfuse_tracer.trace_generation(
                    name="summarize",
                    model="gemini-2.5-flash",
                    input_data={"content": "Test content"},
                    prompt=prompt,  # Link to prompt
                ) as generation:
                    assert generation is not None
                    generation.update(
                        output="Summary with prompt linking",
                        usage_details={
                            "input": 100,
                            "output": 50,
                            "total": 150,
                            "unit": "TOKENS",
                        },
                    )

            langfuse_tracer.flush()

            logger.info(f"Created generation linked to prompt: {prompt.name} v{prompt.version}")

        except Exception as e:
            pytest.skip(f"Prompt 'summarize-document' not found: {e}")


class TestLangfuseErrorHandling:
    """Tests for error handling and resilience."""

    def test_trace_with_exception(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test that exceptions within traces are properly handled."""
        test_url = f"https://example.com/error-test-{uuid.uuid4().hex[:8]}"

        with pytest.raises(ValueError, match="Test error"):
            with langfuse_tracer.trace_url_processing(test_url):
                with langfuse_tracer.trace_span(name="failing_operation"):
                    raise ValueError("Test error")

        # Trace should still be sent despite the error
        langfuse_tracer.flush()

        logger.info("Handled exception within trace")

    def test_generation_failure(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test tracking a failed generation."""
        test_url = f"https://example.com/gen-fail-{uuid.uuid4().hex[:8]}"

        with langfuse_tracer.trace_url_processing(test_url):
            with langfuse_tracer.trace_generation(
                name="failing_generation",
                model="test-model",
            ) as generation:
                assert generation is not None

                # Record failure
                generation.update(
                    output=None,
                    metadata={
                        "error": "API rate limit exceeded",
                        "status": "failed",
                    },
                )

        langfuse_tracer.flush()

        logger.info("Recorded failed generation")


class TestLangfuseFlushAndTiming:
    """Tests for flush behavior and timing."""

    def test_explicit_flush(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test explicit flushing of traces."""
        test_url = f"https://example.com/flush-test-{uuid.uuid4().hex[:8]}"

        with langfuse_tracer.trace_url_processing(test_url):
            pass

        # Explicit flush
        langfuse_tracer.flush()

        logger.info("Explicitly flushed traces")

    def test_multiple_traces_batch(self, langfuse_tracer: LangfuseTracer) -> None:
        """Test creating multiple traces in quick succession."""
        base_url = f"https://example.com/batch-{uuid.uuid4().hex[:8]}"

        for i in range(5):
            test_url = f"{base_url}/{i}"
            with langfuse_tracer.trace_url_processing(test_url):
                with langfuse_tracer.trace_span(name=f"operation_{i}"):
                    pass

        # Flush all at once
        langfuse_tracer.flush()

        logger.info("Created and flushed batch of 5 traces")


class TestMockLangfuseTracer:
    """Tests to ensure MockLangfuseTracer provides compatible interface."""

    def test_mock_tracer_compatibility(self) -> None:
        """Test that mock tracer has same interface as real tracer."""
        mock_tracer = MockLangfuseTracer()

        # Should not raise any exceptions
        with mock_tracer.trace_url_processing("http://example.com"):
            with mock_tracer.trace_span("test_span"):
                with mock_tracer.trace_generation("test_gen", model="test-model"):
                    pass

        mock_tracer.score_trace("fake-id", "test_score", 0.5)
        mock_tracer.flush()

        logger.info("Mock tracer provides compatible interface")

    def test_mock_tracer_session(self) -> None:
        """Test that mock tracer supports session tracing."""
        mock_tracer = MockLangfuseTracer()

        with mock_tracer.trace_message(
            session_id="test-session",
            message_number=1,
            user_input="Test message",
        ):
            pass

        mock_tracer.update_trace_output(output={"response": "test"})

        logger.info("Mock tracer supports session tracing")
