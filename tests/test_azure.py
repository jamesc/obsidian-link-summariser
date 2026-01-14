"""
Tests for the Azure/Microsoft Foundry client module.

Tests cover client initialization, API calls, error handling,
retry logic, and response parsing.
"""

import json
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from openai import APIConnectionError, APIStatusError
from openai import RateLimitError as OpenAIRateLimitError

from summarize_links.config import DEFAULT_AZURE_API_VERSION
from summarize_links.exceptions import (
    AzureAPIError,
    AzureAuthenticationError,
    AzureDeploymentError,
    AzureRateLimitError,
)
from summarize_links.llm.azure import AzureClient
from summarize_links.models import SummaryResult
from summarize_links.rate_limiter import ModelRateLimits, RateLimiter


@pytest.fixture
def mock_rate_limiter() -> RateLimiter:
    """Create a rate limiter with high limits for testing."""
    limits = ModelRateLimits(rpm_limit=1000, tpm_limit=10000000, daily_limit=10000)
    return RateLimiter(model="gpt-4", limits=limits, _apply_safety_margin=False)


@pytest.fixture
def mock_time_functions() -> Generator[
    tuple[Callable[[], float], Callable[[float], None]], None, None
]:
    """
    Create mock time functions that advance time when sleep is called.

    This is essential for testing rate limiting and retry logic without
    real delays. The mock time advances whenever sleep() is called.

    Yields:
        Tuple of (mock_time, mock_sleep) functions.
    """
    current_time = [1000.0]  # Use list to allow mutation in nested function

    def mock_time() -> float:
        return current_time[0]

    def mock_sleep(seconds: float) -> None:
        current_time[0] += seconds

    with (
        patch("summarize_links.llm.azure.time.sleep", side_effect=mock_sleep),
        patch("summarize_links.llm.azure.time.time", side_effect=mock_time),
        patch("summarize_links.rate_limiter.time.sleep", side_effect=mock_sleep),
        patch("summarize_links.rate_limiter.time.time", side_effect=mock_time),
    ):
        yield mock_time, mock_sleep


class TestAzureClientInit:
    """Tests for AzureClient initialization."""

    def test_init_required_params(self, mock_rate_limiter: RateLimiter) -> None:
        """Should initialize with required parameters."""
        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=mock_rate_limiter,
        )

        assert client._api_key == "test-key"
        assert client._endpoint == "https://test.openai.azure.com"
        assert client._model_name == "gpt-4"
        assert client._deployment_name == "my-gpt4"
        assert client._api_version == DEFAULT_AZURE_API_VERSION

    def test_init_custom_api_version(self, mock_rate_limiter: RateLimiter) -> None:
        """Should accept custom API version."""
        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            api_version="2024-06-01",
            rate_limiter=mock_rate_limiter,
        )

        assert client._api_version == "2024-06-01"

    def test_init_lazy_client_creation(self, mock_rate_limiter: RateLimiter) -> None:
        """Should not create OpenAI client until first API call."""
        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=mock_rate_limiter,
        )

        # Client should be None until used
        assert client._client is None

    def test_init_rejects_http_endpoint(self, mock_rate_limiter: RateLimiter) -> None:
        """Should reject HTTP endpoints (require HTTPS)."""
        with pytest.raises(AzureAPIError, match="must use HTTPS"):
            AzureClient(
                api_key="test-key",
                endpoint="http://test.openai.azure.com",  # HTTP instead of HTTPS
                model="gpt-4",
                deployment_name="my-gpt4",
                rate_limiter=mock_rate_limiter,
            )

    def test_init_rejects_invalid_scheme(self, mock_rate_limiter: RateLimiter) -> None:
        """Should reject endpoints without proper scheme."""
        with pytest.raises(AzureAPIError, match="must use HTTPS"):
            AzureClient(
                api_key="test-key",
                endpoint="ftp://test.openai.azure.com",
                model="gpt-4",
                deployment_name="my-gpt4",
                rate_limiter=mock_rate_limiter,
            )


class TestAzureClientSummarize:
    """Tests for AzureClient.summarize method."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_successful_summarization(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should return summary on successful API call."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Generated summary"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        result = client.summarize("Test content", "https://example.com", "Title")

        assert result == "Generated summary"
        mock_azure_class.assert_called_once_with(
            api_key="test-key",
            azure_endpoint="https://test.openai.azure.com",
            api_version=DEFAULT_AZURE_API_VERSION,
        )

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_client_reused_across_calls(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should reuse client across multiple calls."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Summary"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        # Make two calls
        client.summarize("Content 1", "https://example.com")
        client.summarize("Content 2", "https://example.com")

        # Client should only be created once
        assert mock_azure_class.call_count == 1

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_empty_response_raises_error(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should raise error when response has no content."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        with pytest.raises(AzureAPIError, match="empty"):
            client.summarize("Content", "https://example.com")


class TestAzureClientAuthentication:
    """Tests for authentication error handling."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_auth_error_401(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should raise AzureAuthenticationError on 401."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.headers = {}

        auth_error = APIStatusError(
            message="Invalid API key",
            response=mock_response,
            body={"error": {"message": "Invalid API key"}},
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = auth_error
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="bad-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        with pytest.raises(AzureAuthenticationError, match="Authentication failed"):
            client.summarize("Content", "https://example.com")

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_auth_error_403(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should raise AzureAuthenticationError on 403."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.headers = {}

        forbidden_error = APIStatusError(
            message="Access denied",
            response=mock_response,
            body={"error": {"message": "Access denied"}},
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = forbidden_error
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        with pytest.raises(AzureAuthenticationError, match="Access denied"):
            client.summarize("Content", "https://example.com")


class TestAzureClientDeployment:
    """Tests for deployment error handling."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_deployment_not_found(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should raise AzureDeploymentError on 404."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {}

        not_found_error = APIStatusError(
            message="Deployment not found",
            response=mock_response,
            body={"error": {"message": "Deployment 'bad-name' not found"}},
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = not_found_error
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="bad-name",
            rate_limiter=self._rate_limiter,
        )

        with pytest.raises(AzureDeploymentError, match="not found"):
            client.summarize("Content", "https://example.com")


class TestAzureClientRateLimiting:
    """Tests for rate limit handling."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_rate_limit_retry_succeeds(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should retry on rate limit and succeed."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "1"}

        rate_limit_error = OpenAIRateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body={"error": {"message": "Rate limit exceeded"}},
        )

        success_response = MagicMock()
        success_response.choices = [MagicMock()]
        success_response.choices[0].message.content = "Summary after retry"
        success_response.usage.prompt_tokens = 100
        success_response.usage.completion_tokens = 50
        success_response.usage.total_tokens = 150

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            rate_limit_error,
            success_response,
        ]
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        result = client.summarize("Content", "https://example.com")

        assert result == "Summary after retry"
        assert mock_client.chat.completions.create.call_count == 2

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_rate_limit_exhausted_raises(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should raise AzureRateLimitError after all retries exhausted."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}

        rate_limit_error = OpenAIRateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body={"error": {"message": "Rate limit exceeded"}},
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = rate_limit_error
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        with pytest.raises(AzureRateLimitError, match="Rate limit exceeded"):
            client.summarize("Content", "https://example.com")


class TestAzureClientRetry:
    """Tests for retry logic on transient errors."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_retry_on_500_error(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should retry on server errors."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {}

        server_error = APIStatusError(
            message="Internal server error",
            response=mock_response,
            body={"error": {"message": "Internal server error"}},
        )

        success_response = MagicMock()
        success_response.choices = [MagicMock()]
        success_response.choices[0].message.content = "Success"
        success_response.usage.prompt_tokens = 100
        success_response.usage.completion_tokens = 50
        success_response.usage.total_tokens = 150

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            server_error,
            success_response,
        ]
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        result = client.summarize("Content", "https://example.com")

        assert result == "Success"
        assert mock_client.chat.completions.create.call_count == 2

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_retry_on_connection_error(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should retry on connection errors."""
        connection_error = APIConnectionError(request=MagicMock())

        success_response = MagicMock()
        success_response.choices = [MagicMock()]
        success_response.choices[0].message.content = "Success"
        success_response.usage.prompt_tokens = 100
        success_response.usage.completion_tokens = 50
        success_response.usage.total_tokens = 150

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            connection_error,
            success_response,
        ]
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        result = client.summarize("Content", "https://example.com")

        assert result == "Success"


class TestAzureClientSummarizeWithMetadata:
    """Tests for AzureClient.summarize_with_metadata method."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_parses_json_response(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should parse JSON response into SummaryResult."""
        response_json = {
            "summary": "Test summary content",
            "suggested_tags": ["ai", "azure"],
            "content_type": "article",
        }

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(response_json)
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        result = client.summarize_with_metadata("Content", "https://example.com", "Title")

        assert isinstance(result, SummaryResult)
        assert result.content == "Test summary content"
        assert result.suggested_tags == ["ai", "azure"]
        assert result.content_type == "article"
        assert result.usage_details == {"input": 100, "output": 50, "total": 150}

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_handles_json_in_code_block(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should handle JSON wrapped in markdown code block."""
        response_text = """```json
{
  "summary": "Summary text",
  "suggested_tags": ["test"],
  "content_type": "tutorial"
}
```"""

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = response_text
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        result = client.summarize_with_metadata("Content", "https://example.com")

        assert result.content == "Summary text"
        assert result.suggested_tags == ["test"]
        assert result.content_type == "tutorial"

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_handles_non_json_response(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should handle plain text response as fallback."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Plain text summary"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        result = client.summarize_with_metadata("Content", "https://example.com")

        assert result.content == "Plain text summary"
        assert result.suggested_tags == []
        assert result.content_type == "article"


class TestAzureClientTokenTracking:
    """Tests for token usage tracking."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.llm.azure.AzureOpenAI")
    def test_tracks_token_usage(
        self,
        mock_azure_class: MagicMock,
        mock_time_functions: tuple[Any, Any],
    ) -> None:
        """Should track token usage in rate limiter."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Summary"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_azure_class.return_value = mock_client

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            model="gpt-4",
            deployment_name="my-gpt4",
            rate_limiter=self._rate_limiter,
        )

        client.summarize("Content", "https://example.com")

        # Check that rate limiter recorded the tokens
        status = self._rate_limiter.get_status()
        assert status["tpm"]["current"] >= 150
