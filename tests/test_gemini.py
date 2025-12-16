"""Tests for the Gemini client module."""

from unittest.mock import MagicMock, patch

import pytest
from google.api_core import exceptions as google_exceptions

from summarize_links.config import DEFAULT_MODEL
from summarize_links.exceptions import GeminiAPIError, RateLimitError
from summarize_links.gemini_client import (
    GeminiClient,
    MockGeminiClient,
    _build_prompt,
    _parse_gemini_response,
    create_client,
)
from summarize_links.models import SummaryResult
from summarize_links.rate_limiter import RateLimiter


@pytest.fixture
def mock_rate_limiter() -> RateLimiter:
    """Create a rate limiter with high limits for testing."""
    return RateLimiter(rpm_limit=1000, tpm_limit=10000000, daily_limit=10000)


class TestBuildPrompt:
    """Tests for prompt building."""

    def test_basic_prompt(self) -> None:
        """Should build prompt with URL and content."""
        prompt = _build_prompt("Test content", "https://example.com")
        assert "Test content" in prompt
        assert "https://example.com" in prompt
        assert "JSON" in prompt  # Now requests JSON output

    def test_prompt_with_title(self) -> None:
        """Should include title when provided."""
        prompt = _build_prompt("Test content", "https://example.com", "Test Title")
        assert "titled 'Test Title'" in prompt

    def test_prompt_without_title(self) -> None:
        """Should not include title part when not provided."""
        prompt = _build_prompt("Test content", "https://example.com", None)
        assert "titled" not in prompt


class TestMockGeminiClient:
    """Tests for the mock client."""

    def test_returns_mock_summary(self) -> None:
        """Should return predictable mock summary."""
        client = MockGeminiClient()
        summary = client.summarize("Test content", "https://example.com", "Test Title")

        assert "Summary: Test Title" in summary
        assert "https://example.com" in summary
        assert "MockGeminiClient" in summary

    def test_uses_untitled_when_no_title(self) -> None:
        """Should use 'Untitled Page' when title not provided."""
        client = MockGeminiClient()
        summary = client.summarize("Test content", "https://example.com")

        assert "Untitled Page" in summary

    def test_custom_responses(self) -> None:
        """Should return custom response when URL matches."""
        responses = {"https://example.com": "Custom summary"}
        client = MockGeminiClient(responses=responses)

        summary = client.summarize("Content", "https://example.com")
        assert summary == "Custom summary"

    def test_custom_response_not_matched(self) -> None:
        """Should return default mock when URL doesn't match."""
        responses = {"https://example.com": "Custom summary"}
        client = MockGeminiClient(responses=responses)

        summary = client.summarize("Content", "https://other.com")
        assert "Custom summary" not in summary
        assert "MockGeminiClient" in summary

    def test_fail_urls(self) -> None:
        """Should raise error for URLs in fail_urls set."""
        client = MockGeminiClient(fail_urls={"https://fail.com"})

        with pytest.raises(GeminiAPIError, match="Simulated API error"):
            client.summarize("Content", "https://fail.com")

    def test_call_count(self) -> None:
        """Should track number of summarize calls."""
        client = MockGeminiClient()
        assert client.call_count == 0

        client.summarize("Content", "https://example.com")
        assert client.call_count == 1

        client.summarize("Content", "https://other.com")
        assert client.call_count == 2

    def test_content_preview_truncation(self) -> None:
        """Should truncate long content in preview."""
        long_content = "A" * 500
        client = MockGeminiClient()
        summary = client.summarize(long_content, "https://example.com")

        assert "..." in summary
        assert f"Content length: {len(long_content)}" in summary


class TestGeminiClient:
    """Tests for the real Gemini client (mocked API calls)."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.gemini_client.genai")
    def test_successful_summarization(self, mock_genai: MagicMock) -> None:
        """Should return summary on successful API call."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Generated summary"
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(
            api_key="test-key", model="gemini-2.0-flash", rate_limiter=self._rate_limiter
        )
        result = client.summarize("Test content", "https://example.com", "Title")

        assert result == "Generated summary"
        mock_genai.configure.assert_called_once_with(api_key="test-key")
        mock_model.generate_content.assert_called_once()

    @patch("summarize_links.gemini_client.genai")
    def test_retry_on_rate_limit(self, mock_genai: MagicMock) -> None:
        """Should retry on rate limit error."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Generated summary"

        # Fail twice, then succeed
        mock_model.generate_content.side_effect = [
            google_exceptions.ResourceExhausted("Rate limit"),  # type: ignore[no-untyped-call]
            google_exceptions.ResourceExhausted("Rate limit"),  # type: ignore[no-untyped-call]
            mock_response,
        ]
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with patch("summarize_links.gemini_client.time.sleep"):
            result = client.summarize("Content", "https://example.com")

        assert result == "Generated summary"
        assert mock_model.generate_content.call_count == 3

    @patch("summarize_links.gemini_client.genai")
    def test_rate_limit_error_after_retries(self, mock_genai: MagicMock) -> None:
        """Should raise RateLimitError after all retries exhausted."""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = google_exceptions.ResourceExhausted(  # type: ignore[no-untyped-call]
            "Rate limit"
        )
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with (
            patch("summarize_links.gemini_client.time.sleep"),
            pytest.raises(RateLimitError, match="Rate limit exceeded"),
        ):
            client.summarize("Content", "https://example.com")

    @patch("summarize_links.gemini_client.genai")
    def test_invalid_argument_error(self, mock_genai: MagicMock) -> None:
        """Should raise GeminiAPIError on invalid argument without retry."""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = google_exceptions.InvalidArgument(  # type: ignore[no-untyped-call]
            "Bad request"
        )
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with pytest.raises(GeminiAPIError, match="Invalid request"):
            client.summarize("Content", "https://example.com")

        # Should not retry
        assert mock_model.generate_content.call_count == 1

    @patch("summarize_links.gemini_client.genai")
    def test_permission_denied_error(self, mock_genai: MagicMock) -> None:
        """Should raise GeminiAPIError on permission denied without retry."""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = google_exceptions.PermissionDenied(  # type: ignore[no-untyped-call]
            "Access denied"
        )
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with pytest.raises(GeminiAPIError, match="Permission denied"):
            client.summarize("Content", "https://example.com")

        # Should not retry
        assert mock_model.generate_content.call_count == 1

    @patch("summarize_links.gemini_client.genai")
    def test_empty_response_error(self, mock_genai: MagicMock) -> None:
        """Should raise error when response has no parts."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.parts = []  # Empty - content blocked
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with pytest.raises(GeminiAPIError, match="blocked or empty"):
            client.summarize("Content", "https://example.com")

    @patch("summarize_links.gemini_client.genai")
    def test_model_lazy_initialization(self, mock_genai: MagicMock) -> None:
        """Should initialize model lazily on first call."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Summary"
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        # No model created yet
        mock_genai.configure.assert_not_called()

        # First call creates model
        client.summarize("Content", "https://example.com")
        mock_genai.configure.assert_called_once()
        assert mock_genai.GenerativeModel.call_count == 1

        # Second call reuses model
        client.summarize("More content", "https://other.com")
        assert mock_genai.GenerativeModel.call_count == 1


class TestCreateClient:
    """Tests for the client factory function."""

    def test_creates_mock_client_in_mock_mode(self) -> None:
        """Should return MockGeminiClient when mock_mode=True."""
        client = create_client(api_key=None, mock_mode=True)
        assert isinstance(client, MockGeminiClient)

    def test_creates_mock_client_with_api_key_in_mock_mode(self) -> None:
        """Should return MockGeminiClient in mock mode even with api_key."""
        client = create_client(api_key="test-key", mock_mode=True)
        assert isinstance(client, MockGeminiClient)

    def test_creates_real_client_with_api_key(self) -> None:
        """Should return GeminiClient when api_key provided."""
        client = create_client(api_key="test-key", mock_mode=False)
        assert isinstance(client, GeminiClient)

    def test_raises_without_api_key_in_real_mode(self) -> None:
        """Should raise error when api_key missing in non-mock mode."""
        with pytest.raises(GeminiAPIError, match="API key required"):
            create_client(api_key=None, mock_mode=False)

    def test_passes_model_to_client(self) -> None:
        """Should pass model parameter to client."""
        client = create_client(api_key="test-key", model="custom-model", mock_mode=False)
        assert isinstance(client, GeminiClient)
        assert client._model_name == "custom-model"  # noqa: SLF001

    def test_default_model(self) -> None:
        """Should use DEFAULT_MODEL when not specified."""
        client = create_client(api_key="test-key", mock_mode=False)
        assert isinstance(client, GeminiClient)
        assert client._model_name == DEFAULT_MODEL  # noqa: SLF001


class TestParseGeminiResponse:
    """Tests for JSON response parsing."""

    def test_parse_valid_json(self) -> None:
        """Should parse valid JSON response."""
        response = (
            '{"summary": "Test summary", "suggested_tags": ["ai", "ml"], "content_type": "article"}'
        )
        result = _parse_gemini_response(response)

        assert result.content == "Test summary"
        assert result.suggested_tags == ["ai", "ml"]
        assert result.content_type == "article"

    def test_parse_json_in_code_block(self) -> None:
        """Should extract JSON from markdown code block."""
        response = """Here's the summary:
```json
{"summary": "Test summary", "suggested_tags": ["tag1"], "content_type": "tutorial"}
```"""
        result = _parse_gemini_response(response)

        assert result.content == "Test summary"
        assert result.suggested_tags == ["tag1"]
        assert result.content_type == "tutorial"

    def test_parse_json_without_code_block_marker(self) -> None:
        """Should extract JSON from code block without json marker."""
        response = """```
{"summary": "Summary text", "suggested_tags": [], "content_type": "blog"}
```"""
        result = _parse_gemini_response(response)

        assert result.content == "Summary text"
        assert result.content_type == "blog"

    def test_fallback_on_invalid_json(self) -> None:
        """Should use raw text as summary when JSON is invalid."""
        response = "This is not valid JSON, just plain text summary."
        result = _parse_gemini_response(response)

        assert result.content == response
        assert result.suggested_tags == []
        assert result.content_type == "article"

    def test_missing_summary_field(self) -> None:
        """Should use raw response if summary field is missing."""
        response = '{"suggested_tags": ["tag1"], "content_type": "article"}'
        result = _parse_gemini_response(response)

        # Should fall back to entire response since summary is empty
        assert result.suggested_tags == ["tag1"]

    def test_invalid_content_type(self) -> None:
        """Should default to article for unknown content types."""
        response = '{"summary": "Test", "suggested_tags": [], "content_type": "unknown_type"}'
        result = _parse_gemini_response(response)

        assert result.content_type == "article"

    def test_invalid_tags_type(self) -> None:
        """Should default to empty list for invalid tags."""
        response = '{"summary": "Test", "suggested_tags": "not-a-list", "content_type": "article"}'
        result = _parse_gemini_response(response)

        assert result.suggested_tags == []

    def test_parse_multiline_json_in_code_block(self) -> None:
        """Should parse multiline JSON inside markdown code blocks."""
        response = """```json
{
  "summary": "# Summary Title\\n\\nThis is a multiline summary.\\n\\n- Point 1",
  "suggested_tags": ["llm", "automation", "software-development"],
  "content_type": "blog"
}
```"""
        result = _parse_gemini_response(response)

        assert "Summary Title" in result.content
        assert result.suggested_tags == ["llm", "automation", "software-development"]
        assert result.content_type == "blog"

    def test_parse_json_with_nested_newlines_in_values(self) -> None:
        """Should handle JSON where values contain escaped newlines."""
        response = """```json
{
  "summary": "Line 1\\nLine 2\\n\\n> Quote here\\n\\nMore text",
  "suggested_tags": ["tag1", "tag2"],
  "content_type": "article"
}
```"""
        result = _parse_gemini_response(response)

        assert "Line 1" in result.content
        assert result.suggested_tags == ["tag1", "tag2"]


class TestMockGeminiClientWithMetadata:
    """Tests for MockGeminiClient.summarize_with_metadata."""

    def test_returns_summary_result(self) -> None:
        """Should return SummaryResult object."""
        client = MockGeminiClient()
        result = client.summarize_with_metadata("Content", "https://example.com", "Title")

        assert isinstance(result, SummaryResult)
        assert "Summary: Title" in result.content
        assert "mock-tag" in result.suggested_tags
        assert result.content_type == "article"

    def test_infers_tutorial_content_type(self) -> None:
        """Should infer tutorial content type from URL."""
        client = MockGeminiClient()
        result = client.summarize_with_metadata("Content", "https://example.com/tutorial/python")

        assert result.content_type == "tutorial"

    def test_infers_documentation_content_type(self) -> None:
        """Should infer documentation content type from URL."""
        client = MockGeminiClient()
        result = client.summarize_with_metadata("Content", "https://docs.example.com/api")

        assert result.content_type == "documentation"

    def test_infers_blog_content_type(self) -> None:
        """Should infer blog content type from URL."""
        client = MockGeminiClient()
        result = client.summarize_with_metadata("Content", "https://blog.example.com/post")

        assert result.content_type == "blog"

    def test_infers_video_content_type(self) -> None:
        """Should infer video content type from YouTube URL."""
        client = MockGeminiClient()
        result = client.summarize_with_metadata("Content", "https://youtube.com/watch?v=123")

        assert result.content_type == "video"

    def test_fail_urls_still_work(self) -> None:
        """Should raise error for fail_urls."""
        client = MockGeminiClient(fail_urls={"https://fail.com"})

        with pytest.raises(GeminiAPIError, match="Simulated API error"):
            client.summarize_with_metadata("Content", "https://fail.com")


class TestGeminiClientWithMetadata:
    """Tests for GeminiClient.summarize_with_metadata."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.gemini_client.genai")
    def test_parses_json_response(self, mock_genai: MagicMock) -> None:
        """Should parse JSON response into SummaryResult."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = (
            '{"summary": "AI Summary", "suggested_tags": ["ai"], "content_type": "article"}'
        )
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)
        result = client.summarize_with_metadata("Content", "https://example.com", "Title")

        assert isinstance(result, SummaryResult)
        assert result.content == "AI Summary"
        assert result.suggested_tags == ["ai"]
        assert result.content_type == "article"

    @patch("summarize_links.gemini_client.genai")
    def test_handles_non_json_response(self, mock_genai: MagicMock) -> None:
        """Should handle non-JSON response gracefully."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Plain text summary without JSON"
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)
        result = client.summarize_with_metadata("Content", "https://example.com")

        assert result.content == "Plain text summary without JSON"
        assert result.suggested_tags == []
        assert result.content_type == "article"
