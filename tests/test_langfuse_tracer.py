"""Tests for Langfuse integration."""

from typing import Any
from unittest.mock import Mock, patch

import pytest

from summarize_links.langfuse_tracer import (
    LangfuseTracer,
    MockLangfuseTracer,
    get_tracer,
    initialize_tracer,
)


class TestLangfuseTracer:
    """Tests for LangfuseTracer class."""

    @patch("summarize_links.langfuse_tracer.Langfuse")
    def test_langfuse_tracer_initialization_success(
        self, mock_langfuse_class: Mock
    ) -> None:
        """Test that tracer initializes successfully with valid credentials."""
        mock_client = Mock()
        mock_client.auth_check.return_value = True
        mock_langfuse_class.return_value = mock_client

        LangfuseTracer(
            public_key="pk-test",
            secret_key="sk-test",
            base_url="https://cloud.langfuse.com",
        )

        mock_langfuse_class.assert_called_once_with(
            public_key="pk-test",
            secret_key="sk-test",
            host="https://cloud.langfuse.com",
        )
        mock_client.auth_check.assert_called_once()

    @patch("summarize_links.langfuse_tracer.Langfuse")
    def test_tracer_auth_failure(self, mock_langfuse_class: Mock) -> None:
        """Test that tracer fails when auth check fails."""
        mock_client = Mock()
        mock_client.auth_check.return_value = False
        mock_langfuse_class.return_value = mock_client

        with pytest.raises(RuntimeError, match="authentication failed"):
            LangfuseTracer(
                public_key="pk-invalid",
                secret_key="sk-invalid",
            )

    @patch("summarize_links.langfuse_tracer.Langfuse")
    def test_tracer_initialization_error(self, mock_langfuse_class: Mock) -> None:
        """Test that tracer handles initialization errors."""
        mock_langfuse_class.side_effect = Exception("Connection error")

        with pytest.raises(RuntimeError, match="Failed to initialize Langfuse"):
            LangfuseTracer(
                public_key="pk-test",
                secret_key="sk-test",
            )


class TestMockLangfuseTracer:
    """Tests for MockLangfuseTracer class."""

    def test_mock_tracer_no_op(self) -> None:
        """Test that mock tracer provides no-op implementations."""
        tracer = MockLangfuseTracer()

        # Should not raise errors
        with tracer.trace_url_processing("http://example.com") as trace:
            assert trace is None

        with tracer.trace_span("test_span") as span:
            assert span is None

        with tracer.trace_generation("test_gen") as gen:
            assert gen is None

        # Scoring should also be no-op
        tracer.score_trace("fake-id", "test_score", 0.5)

        # Flush should be safe
        tracer.flush()

    def test_mock_tracer_with_metadata(self) -> None:
        """Test that mock tracer accepts metadata."""
        tracer = MockLangfuseTracer()

        with tracer.trace_url_processing("http://example.com", metadata={"key": "value"}) as trace:
            assert trace is None

        with tracer.trace_span(
            name="test_span",
            input_data={"input": "data"},
            metadata={"key": "value"},
        ) as span:
            assert span is None

        with tracer.trace_generation(
            name="test_generation",
            input_data={"prompt": "test"},
            metadata={"key": "value"},
            model="test-model",
        ) as gen:
            assert gen is None

    def test_mock_tracer_score_with_comment(self) -> None:
        """Test that mock tracer accepts score with comment."""
        tracer = MockLangfuseTracer()

        # Should not raise
        tracer.score_trace(
            trace_id="fake-trace-id",
            name="test_score",
            value=0.75,
            comment="Test comment",
        )


class TestGlobalTracer:
    """Tests for global tracer functions."""

    def test_get_tracer_before_initialization(self) -> None:
        """get_tracer should return MockLangfuseTracer if not initialized."""
        # Reset global tracer
        import summarize_links.langfuse_tracer as tracer_module

        tracer_module._global_tracer = None

        tracer = get_tracer()

        assert isinstance(tracer, MockLangfuseTracer)

    @patch("summarize_links.langfuse_tracer.Langfuse")
    def test_initialize_tracer(self, mock_langfuse_class: Mock, mock_config) -> None:  # type: ignore[no-untyped-def]
        """Test initialize_tracer with config."""
        mock_client = Mock()
        mock_client.auth_check.return_value = True
        mock_langfuse_class.return_value = mock_client

        tracer = initialize_tracer(mock_config)

        assert isinstance(tracer, LangfuseTracer)
        assert tracer is get_tracer()  # Should set global tracer

    @patch("summarize_links.langfuse_tracer.Langfuse")
    def test_initialize_tracer_handles_auth_failure(
        self, mock_langfuse_class: Mock, mock_config: Any
    ) -> None:
        """Test initialize_tracer handles auth failures gracefully."""
        mock_client = Mock()
        mock_client.auth_check.return_value = False
        mock_langfuse_class.return_value = mock_client

        with pytest.raises(RuntimeError, match="authentication failed"):
            initialize_tracer(mock_config)


class TestTracerContextManagers:
    """Tests for tracer context manager behavior."""

    @patch("summarize_links.langfuse_tracer.Langfuse")
    def test_trace_url_processing_with_metadata(self, mock_langfuse_class: Mock) -> None:
        """Test trace_url_processing accepts metadata."""
        mock_client = Mock()
        mock_client.auth_check.return_value = True
        mock_trace = Mock()
        mock_client.start_as_current_observation.return_value.__enter__ = Mock(
            return_value=mock_trace
        )
        mock_client.start_as_current_observation.return_value.__exit__ = Mock(return_value=False)
        mock_langfuse_class.return_value = mock_client

        tracer = LangfuseTracer(
            public_key="pk-test",
            secret_key="sk-test",
        )

        metadata = {
            "model": "gemini-2.5-flash",
            "provider": "gemini",
            "user_tags": ["test", "example"],
        }

        with tracer.trace_url_processing("http://example.com", metadata=metadata) as trace:
            assert trace is not None

    @patch("summarize_links.langfuse_tracer.Langfuse")
    def test_trace_span_with_full_args(self, mock_langfuse_class: Mock) -> None:
        """Test trace_span accepts all arguments."""
        mock_client = Mock()
        mock_client.auth_check.return_value = True
        mock_span = Mock()
        mock_client.start_as_current_observation.return_value.__enter__ = Mock(
            return_value=mock_span
        )
        mock_client.start_as_current_observation.return_value.__exit__ = Mock(return_value=False)
        mock_langfuse_class.return_value = mock_client

        tracer = LangfuseTracer(
            public_key="pk-test",
            secret_key="sk-test",
        )

        with tracer.trace_span(
            name="fetch_content",
            input_data={"url": "http://example.com"},
            metadata={"timeout": 10},
        ) as span:
            assert span is not None

    @patch("summarize_links.langfuse_tracer.Langfuse")
    def test_trace_generation_with_model(self, mock_langfuse_class: Mock) -> None:
        """Test trace_generation includes model parameter."""
        mock_client = Mock()
        mock_client.auth_check.return_value = True
        mock_gen = Mock()
        mock_client.start_as_current_observation.return_value.__enter__ = Mock(
            return_value=mock_gen
        )
        mock_client.start_as_current_observation.return_value.__exit__ = Mock(return_value=False)
        mock_langfuse_class.return_value = mock_client

        tracer = LangfuseTracer(
            public_key="pk-test",
            secret_key="sk-test",
        )

        with tracer.trace_generation(
            name="summarize",
            input_data={"content_length": 1000},
            metadata={"provider": "gemini"},
            model="gemini-2.5-flash",
        ) as gen:
            assert gen is not None

    @patch("summarize_links.langfuse_tracer.Langfuse")
    def test_score_trace_with_comment(self, mock_langfuse_class: Mock) -> None:
        """Test score_trace with comment."""
        mock_client = Mock()
        mock_client.auth_check.return_value = True
        mock_langfuse_class.return_value = mock_client

        tracer = LangfuseTracer(
            public_key="pk-test",
            secret_key="sk-test",
        )

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
        tracer = MockLangfuseTracer()

        class CustomError(Exception):
            pass

        # Exception should propagate through the context manager
        with pytest.raises(CustomError), tracer.trace_url_processing("http://example.com"):
            raise CustomError("Test error")

    def test_trace_span_propagates_exceptions(self) -> None:
        """Test that exceptions inside trace_span are properly propagated."""
        tracer = MockLangfuseTracer()

        class CustomError(Exception):
            pass

        # Exception should propagate through the context manager
        with pytest.raises(CustomError), tracer.trace_span("test_span"):
            raise CustomError("Test error")

    def test_trace_generation_propagates_exceptions(self) -> None:
        """Test that exceptions inside trace_generation are properly propagated."""
        tracer = MockLangfuseTracer()

        class CustomError(Exception):
            pass

        # Exception should propagate through the context manager
        with pytest.raises(CustomError), tracer.trace_generation("test_gen"):
            raise CustomError("Test error")
