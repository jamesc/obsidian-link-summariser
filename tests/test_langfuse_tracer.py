"""Tests for Langfuse integration."""

import pytest

from summarize_links.config import Config
from summarize_links.langfuse_tracer import LangfuseTracer, get_tracer, initialize_tracer


class TestLangfuseTracer:
    """Tests for LangfuseTracer class."""

    def test_tracer_disabled_mode(self) -> None:
        """Test that tracer works as no-op when disabled."""
        tracer = LangfuseTracer(enabled=False)

        assert not tracer.enabled

        # Should not raise errors
        with tracer.trace_url_processing("http://example.com") as trace:
            assert trace is None

        with tracer.trace_span("test_span") as span:
            assert span is None

        with tracer.trace_generation("test_gen") as gen:
            assert gen is None

        # Scoring should also be no-op
        tracer.score_trace(None, "test_score", 0.5)

        # Flush should be safe
        tracer.flush()

    def test_tracer_missing_keys(self) -> None:
        """Test graceful degradation without API keys."""
        tracer = LangfuseTracer(
            public_key=None,
            secret_key=None,
            enabled=True,
        )

        assert not tracer.enabled

    def test_tracer_missing_public_key(self) -> None:
        """Test graceful degradation without public key."""
        tracer = LangfuseTracer(
            public_key=None,
            secret_key="sk-test",
            enabled=True,
        )

        assert not tracer.enabled

    def test_tracer_missing_secret_key(self) -> None:
        """Test graceful degradation without secret key."""
        tracer = LangfuseTracer(
            public_key="pk-test",
            secret_key=None,
            enabled=True,
        )

        assert not tracer.enabled

    def test_tracer_with_mock_config(self, mock_config: Config) -> None:
        """Test tracer initialization with mock config (should be disabled)."""
        tracer = LangfuseTracer(
            public_key=mock_config.langfuse_public_key,
            secret_key=mock_config.langfuse_secret_key,
            enabled=mock_config.langfuse_enabled,
        )

        # Mock config has Langfuse disabled by default
        assert not tracer.enabled

    def test_trace_url_processing_disabled(self) -> None:
        """Test trace_url_processing when disabled."""
        tracer = LangfuseTracer(enabled=False)

        with tracer.trace_url_processing("http://example.com", metadata={"key": "value"}) as trace:
            assert trace is None

    def test_trace_span_disabled(self) -> None:
        """Test trace_span when disabled."""
        tracer = LangfuseTracer(enabled=False)

        with tracer.trace_span(
            name="test_span",
            input_data={"input": "data"},
            metadata={"key": "value"},
        ) as span:
            assert span is None

    def test_trace_generation_disabled(self) -> None:
        """Test trace_generation when disabled."""
        tracer = LangfuseTracer(enabled=False)

        with tracer.trace_generation(
            name="test_generation",
            input_data={"prompt": "test"},
            metadata={"key": "value"},
            model="test-model",
        ) as gen:
            assert gen is None

    def test_score_trace_disabled(self) -> None:
        """Test score_trace when disabled."""
        tracer = LangfuseTracer(enabled=False)

        # Should not raise
        tracer.score_trace(
            trace_id="fake-trace-id",
            name="test_score",
            value=0.75,
            comment="Test comment",
        )

    def test_flush_disabled(self) -> None:
        """Test flush when disabled."""
        tracer = LangfuseTracer(enabled=False)

        # Should not raise
        tracer.flush()


class TestGlobalTracer:
    """Tests for global tracer functions."""

    def test_get_tracer_before_initialization(self) -> None:
        """get_tracer should return disabled tracer if not initialized."""
        # Reset global tracer
        import summarize_links.langfuse_tracer as tracer_module

        tracer_module._global_tracer = None

        tracer = get_tracer()

        assert not tracer.enabled

    def test_initialize_tracer(self, mock_config: Config) -> None:
        """Test initialize_tracer with config."""
        tracer = initialize_tracer(mock_config)

        assert not tracer.enabled  # Mock config has Langfuse disabled
        assert tracer is get_tracer()  # Should set global tracer

    def test_initialize_tracer_with_enabled_config(self, mock_config: Config) -> None:
        """Test initialize_tracer with Langfuse enabled."""
        # Modify config to enable Langfuse (but with fake keys)
        mock_config.langfuse_enabled = True
        mock_config.langfuse_public_key = "pk-test"
        mock_config.langfuse_secret_key = "sk-test"

        tracer = initialize_tracer(mock_config)

        # Note: Tracer will try to connect and may fail if langfuse not installed
        # That's expected - it should gracefully degrade
        assert isinstance(tracer, LangfuseTracer)


class TestTracerContextManagers:
    """Tests for tracer context manager behavior."""

    def test_trace_url_processing_with_metadata(self) -> None:
        """Test trace_url_processing accepts metadata."""
        tracer = LangfuseTracer(enabled=False)

        metadata = {
            "model": "gemini-2.5-flash",
            "provider": "gemini",
            "user_tags": ["test", "example"],
        }

        with tracer.trace_url_processing("http://example.com", metadata=metadata) as trace:
            assert trace is None  # Disabled, so returns None

    def test_trace_span_with_full_args(self) -> None:
        """Test trace_span accepts all arguments."""
        tracer = LangfuseTracer(enabled=False)

        with tracer.trace_span(
            name="fetch_content",
            input_data={"url": "http://example.com"},
            metadata={"timeout": 10},
        ) as span:
            assert span is None

    def test_trace_generation_with_model(self) -> None:
        """Test trace_generation includes model parameter."""
        tracer = LangfuseTracer(enabled=False)

        with tracer.trace_generation(
            name="summarize",
            input_data={"content_length": 1000},
            metadata={"provider": "gemini"},
            model="gemini-2.5-flash",
        ) as gen:
            assert gen is None

    def test_score_trace_with_comment(self) -> None:
        """Test score_trace with comment."""
        tracer = LangfuseTracer(enabled=False)

        tracer.score_trace(
            trace_id="trace-123",
            name="relevance",
            value=0.85,
            comment="High relevance to user query",
        )

        # Should not raise


class TestExceptionHandling:
    """Tests for exception handling in context managers."""

    def test_trace_url_processing_propagates_exceptions(self) -> None:
        """Test that exceptions inside trace_url_processing are properly propagated."""
        tracer = LangfuseTracer(enabled=False)

        class CustomError(Exception):
            pass

        # Exception should propagate through the context manager
        with pytest.raises(CustomError), tracer.trace_url_processing("http://example.com"):
            raise CustomError("Test error")

    def test_trace_span_propagates_exceptions(self) -> None:
        """Test that exceptions inside trace_span are properly propagated."""
        tracer = LangfuseTracer(enabled=False)

        class CustomError(Exception):
            pass

        # Exception should propagate through the context manager
        with pytest.raises(CustomError), tracer.trace_span("test_span"):
            raise CustomError("Test error")

    def test_trace_generation_propagates_exceptions(self) -> None:
        """Test that exceptions inside trace_generation are properly propagated."""
        tracer = LangfuseTracer(enabled=False)

        class CustomError(Exception):
            pass

        # Exception should propagate through the context manager
        with pytest.raises(CustomError), tracer.trace_generation("test_gen"):
            raise CustomError("Test error")
