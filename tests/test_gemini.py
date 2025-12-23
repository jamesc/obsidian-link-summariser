"""Tests for the Gemini client module."""

from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors

from summarize_links.config import DEFAULT_MODEL
from summarize_links.exceptions import GeminiAPIError, RateLimitError
from summarize_links.gemini_client import (
    SUMMARY_SYSTEM_PROMPT,
    GeminiClient,
    MockGeminiClient,
    _build_content_type_list,
    _build_prompt,
    _extract_content_type_from_malformed_json,
    _extract_summary_from_malformed_json,
    _extract_tags_from_malformed_json,
    _is_garbled_summary,
    _parse_gemini_response,
    create_client,
)
from summarize_links.models import CONTENT_TYPE_DESCRIPTIONS, CONTENT_TYPES, SummaryResult
from summarize_links.rate_limiter import ModelRateLimits, RateLimiter


@pytest.fixture
def mock_rate_limiter() -> RateLimiter:
    """Create a rate limiter with high limits for testing."""
    limits = ModelRateLimits(rpm_limit=1000, tpm_limit=10000000, daily_limit=10000)
    return RateLimiter(model="test-model", limits=limits, _apply_safety_margin=False)


class TestContentTypeListGeneration:
    """Tests for dynamic content type list in system prompt."""

    def test_all_content_types_in_prompt(self) -> None:
        """System prompt should contain all content types from CONTENT_TYPES."""
        for content_type in CONTENT_TYPES:
            assert f'"{content_type}"' in SUMMARY_SYSTEM_PROMPT

    def test_all_descriptions_in_prompt(self) -> None:
        """System prompt should contain all descriptions from CONTENT_TYPE_DESCRIPTIONS."""
        for description in CONTENT_TYPE_DESCRIPTIONS.values():
            assert description in SUMMARY_SYSTEM_PROMPT

    def test_build_content_type_list_format(self) -> None:
        """_build_content_type_list should produce properly formatted list."""
        result = _build_content_type_list()
        # Check format: - "type" (description)
        for content_type, description in CONTENT_TYPE_DESCRIPTIONS.items():
            expected = f'- "{content_type}" ({description})'
            assert expected in result

    def test_content_types_synced_with_descriptions(self) -> None:
        """CONTENT_TYPES should be derived from CONTENT_TYPE_DESCRIPTIONS keys."""
        assert frozenset(CONTENT_TYPE_DESCRIPTIONS.keys()) == CONTENT_TYPES


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

    @patch("summarize_links.gemini_client.genai.Client")
    def test_successful_summarization(self, mock_client_class: MagicMock) -> None:
        """Should return summary on successful API call."""
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Generated summary"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = GeminiClient(
            api_key="test-key", model="gemini-2.0-flash", rate_limiter=self._rate_limiter
        )
        result = client.summarize("Test content", "https://example.com", "Title")

        assert result == "Generated summary"
        mock_client_class.assert_called_once_with(api_key="test-key")
        mock_client.models.generate_content.assert_called_once()

    @patch("summarize_links.gemini_client.genai.Client")
    def test_retry_on_rate_limit(self, mock_client_class: MagicMock) -> None:
        """Should retry on rate limit error."""
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Generated summary"

        # Fail twice, then succeed
        # Create a proper ClientError with required parameters
        rate_limit_error = errors.ClientError(429, {"error": {"message": "Rate limit exceeded"}})

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            rate_limit_error,
            rate_limit_error,
            mock_response,
        ]
        mock_client_class.return_value = mock_client

        # Create a mock time that advances when sleep is called
        current_time = [1000.0]  # Use list to allow mutation in nested function

        def mock_time() -> float:
            return current_time[0]

        def mock_sleep(seconds: float) -> None:
            current_time[0] += seconds

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with (
            patch("summarize_links.gemini_client.time.sleep", side_effect=mock_sleep),
            patch("summarize_links.gemini_client.time.time", side_effect=mock_time),
            patch("summarize_links.rate_limiter.time.sleep", side_effect=mock_sleep),
            patch("summarize_links.rate_limiter.time.time", side_effect=mock_time),
        ):
            result = client.summarize("Content", "https://example.com")

        assert result == "Generated summary"
        assert mock_client.models.generate_content.call_count == 3

    @patch("summarize_links.gemini_client.genai.Client")
    def test_rate_limit_error_after_retries(self, mock_client_class: MagicMock) -> None:
        """Should raise RateLimitError after all retries exhausted."""
        rate_limit_error = errors.ClientError(429, {"error": {"message": "Rate limit exceeded"}})

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = rate_limit_error
        mock_client_class.return_value = mock_client

        # Create a mock time that advances when sleep is called
        current_time = [1000.0]

        def mock_time() -> float:
            return current_time[0]

        def mock_sleep(seconds: float) -> None:
            current_time[0] += seconds

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with (
            patch("summarize_links.gemini_client.time.sleep", side_effect=mock_sleep),
            patch("summarize_links.gemini_client.time.time", side_effect=mock_time),
            patch("summarize_links.rate_limiter.time.sleep", side_effect=mock_sleep),
            patch("summarize_links.rate_limiter.time.time", side_effect=mock_time),
            pytest.raises(RateLimitError, match="Rate limit exceeded"),
        ):
            client.summarize("Content", "https://example.com")

    @patch("summarize_links.gemini_client.genai.Client")
    def test_invalid_argument_error(self, mock_client_class: MagicMock) -> None:
        """Should raise GeminiAPIError on invalid argument without retry."""
        invalid_error = errors.ClientError(400, {"error": {"message": "Invalid request"}})

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = invalid_error
        mock_client_class.return_value = mock_client

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with pytest.raises(GeminiAPIError, match="Invalid request"):
            client.summarize("Content", "https://example.com")

        # Should not retry
        assert mock_client.models.generate_content.call_count == 1

    @patch("summarize_links.gemini_client.genai.Client")
    def test_permission_denied_error(self, mock_client_class: MagicMock) -> None:
        """Should raise GeminiAPIError on permission denied without retry."""
        permission_error = errors.ClientError(403, {"error": {"message": "Access denied"}})

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = permission_error
        mock_client_class.return_value = mock_client

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with pytest.raises(GeminiAPIError, match="Permission denied"):
            client.summarize("Content", "https://example.com")

        # Should not retry
        assert mock_client.models.generate_content.call_count == 1

    @patch("summarize_links.gemini_client.genai.Client")
    def test_empty_response_error(self, mock_client_class: MagicMock) -> None:
        """Should raise error when response has no parts."""
        mock_response = MagicMock()
        mock_response.parts = []  # Empty - content blocked

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with pytest.raises(GeminiAPIError, match="blocked or empty"):
            client.summarize("Content", "https://example.com")

    @patch("summarize_links.gemini_client.genai.Client")
    def test_model_lazy_initialization(self, mock_client_class: MagicMock) -> None:
        """Should initialize client lazily on first call."""
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Summary"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        # No client created yet
        mock_client_class.assert_not_called()

        # First call creates client
        client.summarize("Content", "https://example.com")
        mock_client_class.assert_called_once()
        assert mock_client_class.call_count == 1

        # Second call reuses client
        client.summarize("More content", "https://other.com")
        assert mock_client_class.call_count == 1


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

    @patch("summarize_links.gemini_client.genai.Client")
    def test_parses_json_response(self, mock_client_class: MagicMock) -> None:
        """Should parse JSON response into SummaryResult."""
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = (
            '{"summary": "AI Summary", "suggested_tags": ["ai"], "content_type": "article"}'
        )

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)
        result = client.summarize_with_metadata("Content", "https://example.com", "Title")

        assert isinstance(result, SummaryResult)
        assert result.content == "AI Summary"
        assert result.suggested_tags == ["ai"]
        assert result.content_type == "article"

    @patch("summarize_links.gemini_client.genai.Client")
    def test_handles_non_json_response(self, mock_client_class: MagicMock) -> None:
        """Should handle non-JSON response gracefully."""
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Plain text summary without JSON"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)
        result = client.summarize_with_metadata("Content", "https://example.com")

        assert result.content == "Plain text summary without JSON"
        assert result.suggested_tags == []
        assert result.content_type == "article"


class TestMalformedJsonExtraction:
    """Tests for extracting fields from malformed JSON responses."""

    def test_extract_summary_basic(self) -> None:
        """Should extract summary from malformed JSON with unescaped quotes."""
        malformed = (
            '{"summary": "This has "quotes" inside", '
            '"suggested_tags": ["tag1"], "content_type": "article"}'
        )
        result = _extract_summary_from_malformed_json(malformed)

        # Should extract the summary despite the unescaped quotes
        assert result is not None
        assert "This has" in result

    def test_extract_summary_with_code_blocks(self) -> None:
        """Should extract summary containing code blocks."""
        malformed = (
            '{"summary": "Here is code:\\n```python\\ndef foo():\\n    pass\\n```\\nEnd.", '
            '"suggested_tags": ["python"], "content_type": "tutorial"}'
        )
        result = _extract_summary_from_malformed_json(malformed)

        assert result is not None
        assert "code" in result.lower()

    def test_extract_summary_with_newlines(self) -> None:
        """Should handle escaped newlines in summary."""
        malformed = (
            '{"summary": "Line 1\\nLine 2\\n\\n## Header\\n\\nMore text", '
            '"suggested_tags": ["test"], "content_type": "article"}'
        )
        result = _extract_summary_from_malformed_json(malformed)

        assert result is not None
        assert "Line 1" in result
        # Newlines should be unescaped
        assert "\n" in result or "Line 2" in result

    def test_extract_summary_returns_none_for_no_summary(self) -> None:
        """Should return None when no summary field found."""
        malformed = '{"other_field": "value"}'
        result = _extract_summary_from_malformed_json(malformed)

        assert result is None

    def test_extract_tags_basic(self) -> None:
        """Should extract tags array from malformed JSON."""
        malformed = (
            '{"summary": "Test", "suggested_tags": ["ai", "coding", "tools"], '
            '"content_type": "article"}'
        )
        result = _extract_tags_from_malformed_json(malformed)

        assert result == ["ai", "coding", "tools"]

    def test_extract_tags_empty_array(self) -> None:
        """Should return empty list for empty tags array."""
        malformed = '{"summary": "Test", "suggested_tags": [], "content_type": "article"}'
        result = _extract_tags_from_malformed_json(malformed)

        assert result == []

    def test_extract_tags_no_field(self) -> None:
        """Should return empty list when no tags field."""
        malformed = '{"summary": "Test"}'
        result = _extract_tags_from_malformed_json(malformed)

        assert result == []

    def test_extract_content_type_basic(self) -> None:
        """Should extract content_type from malformed JSON."""
        malformed = '{"summary": "Test", "suggested_tags": [], "content_type": "tutorial"}'
        result = _extract_content_type_from_malformed_json(malformed)

        assert result == "tutorial"

    def test_extract_content_type_invalid(self) -> None:
        """Should return article for invalid content type."""
        malformed = '{"summary": "Test", "content_type": "invalid_type"}'
        result = _extract_content_type_from_malformed_json(malformed)

        assert result == "article"

    def test_extract_content_type_missing(self) -> None:
        """Should return article when no content_type field."""
        malformed = '{"summary": "Test"}'
        result = _extract_content_type_from_malformed_json(malformed)

        assert result == "article"

    def test_parse_gemini_response_uses_extraction_on_malformed_json(self) -> None:
        """Should use extraction functions when JSON parsing fails."""
        # This JSON has an unescaped quote in the summary that breaks parsing
        malformed = (
            '{"summary": "This article talks about "Claude Code" and how to optimize '
            'it with skills and plugins.", "suggested_tags": ["ai", "claude", '
            '"developer-tools"], "content_type": "tutorial"}'
        )
        result = _parse_gemini_response(malformed)

        # Should extract something useful rather than returning raw malformed JSON
        assert isinstance(result, SummaryResult)
        # Tags should be extracted even if summary parsing is partial
        assert (
            "ai" in result.suggested_tags
            or "claude" in result.suggested_tags
            or len(result.content) > 50
        )

    def test_parse_gemini_response_with_multiline_code_in_summary(self) -> None:
        """Should handle summary with embedded code that has curly braces."""
        # The curly braces in the code could confuse brace counting
        response = (
            '{"summary": "Example:\\n```json\\n{\\"key\\": \\"value\\"}\\n```\\nEnd.", '
            '"suggested_tags": ["json"], "content_type": "documentation"}'
        )
        result = _parse_gemini_response(response)

        assert isinstance(result, SummaryResult)
        # Should successfully parse or extract something meaningful
        assert len(result.content) > 10


class TestRateLimitWaitCalculation:
    """Tests for rate limit wait time calculation."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    def test_extracts_retry_after_from_error_message(self) -> None:
        """Should extract Retry-After value from error message."""
        from summarize_links.gemini_client import GeminiClient

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        # Simulate an error message containing retry delay
        error = errors.ClientError(
            429, {"error": {"message": "Resource exhausted. Retry after 30 seconds."}}
        )

        wait_time = client._calculate_rate_limit_wait(0, error)  # noqa: SLF001

        # Should respect the retry-after with a small buffer
        assert wait_time >= 30
        assert wait_time <= 35  # 30 + 1s buffer + some tolerance

    def test_respects_minimum_rate_limit_wait(self) -> None:
        """Should enforce minimum wait time for rate limits."""
        from summarize_links.gemini_client import MIN_RATE_LIMIT_WAIT, GeminiClient

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        # Error without explicit retry-after
        error = errors.ClientError(429, {"error": {"message": "Rate limit exceeded"}})

        wait_time = client._calculate_rate_limit_wait(0, error)  # noqa: SLF001

        # Should be at least the minimum
        assert wait_time >= MIN_RATE_LIMIT_WAIT

    def test_caps_wait_at_max_delay(self) -> None:
        """Should cap wait time at maximum delay."""
        from summarize_links.gemini_client import MAX_RETRY_DELAY, GeminiClient

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        # Simulate very long retry-after
        error = errors.ClientError(429, {"error": {"message": "Retry after 999999 seconds"}})

        wait_time = client._calculate_rate_limit_wait(0, error)  # noqa: SLF001

        # Should be capped at max
        assert wait_time <= MAX_RETRY_DELAY


class TestTokenUsageExtraction:
    """Tests for token usage extraction from API responses."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.gemini_client.genai")
    def test_uses_actual_token_count_from_response(self, mock_genai: MagicMock) -> None:
        """Should use actual token count when available in response."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Summary text"

        # Add usage metadata
        mock_usage = MagicMock()
        mock_usage.total_token_count = 500
        mock_response.usage_metadata = mock_usage

        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)
        client.summarize("Content", "https://example.com")

        # Rate limiter should have recorded 500 tokens
        status = self._rate_limiter.get_status()
        # The token count should reflect the actual usage
        assert status["tpm"]["current"] >= 500

    @patch("summarize_links.gemini_client.genai.Client")
    def test_falls_back_to_estimate_when_metadata_unavailable(
        self, mock_client_class: MagicMock
    ) -> None:
        """Should fall back to estimate when usage_metadata is None."""
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Summary text"
        mock_response.usage_metadata = None  # No metadata

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        # Should not raise
        result = client.summarize("Short content", "https://example.com")

        assert result == "Summary text"


class TestRetryOnGenericAPIError:
    """Tests for retry behavior on generic API errors."""

    @pytest.fixture(autouse=True)
    def setup_rate_limiter(self, mock_rate_limiter: RateLimiter) -> None:
        """Inject mock rate limiter for all tests in this class."""
        self._rate_limiter = mock_rate_limiter

    @patch("summarize_links.gemini_client.genai.Client")
    def test_retry_on_generic_api_error(self, mock_client_class: MagicMock) -> None:
        """Should retry on generic ClientError."""
        mock_response = MagicMock()
        mock_response.parts = [MagicMock()]
        mock_response.text = "Success after retry"

        # First call fails with generic error, second succeeds
        generic_error = errors.ClientError(500, {"error": {"message": "Transient error"}})

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            generic_error,
            mock_response,
        ]
        mock_client_class.return_value = mock_client

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with patch("summarize_links.gemini_client.time.sleep"):
            result = client.summarize("Content", "https://example.com")

        assert result == "Success after retry"
        assert mock_client.models.generate_content.call_count == 2

    @patch("summarize_links.gemini_client.genai.Client")
    def test_raises_after_all_retries_exhausted_generic_error(
        self, mock_client_class: MagicMock
    ) -> None:
        """Should raise GeminiAPIError after retries exhausted for generic errors."""
        from summarize_links.gemini_client import MAX_RETRIES

        generic_error = errors.ClientError(500, {"error": {"message": "Persistent error"}})

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = generic_error
        mock_client_class.return_value = mock_client

        client = GeminiClient(api_key="test-key", rate_limiter=self._rate_limiter)

        with (
            patch("summarize_links.gemini_client.time.sleep"),
            pytest.raises(GeminiAPIError, match="API error after retries"),
        ):
            client.summarize("Content", "https://example.com")

        assert mock_client.models.generate_content.call_count == MAX_RETRIES


class TestGarbledContentDetection:
    """Tests for detecting garbled/corrupted content in summaries."""

    def test_detects_corrupted_or_encrypted(self) -> None:
        """Should detect 'corrupted or encrypted' in summary."""
        text = "The provided web page content appears to be corrupted or encrypted."
        assert _is_garbled_summary(text) is True

    def test_detects_garbled_characters(self) -> None:
        """Should detect 'garbled characters' in summary."""
        text = "This text consists of garbled characters that cannot be read."
        assert _is_garbled_summary(text) is True

    def test_detects_not_possible_to_extract(self) -> None:
        """Should detect 'not possible to extract' in summary."""
        text = "It is not possible to extract any meaningful information from this content."
        assert _is_garbled_summary(text) is True

    def test_detects_base64_encoded(self) -> None:
        """Should detect 'base64 encoded' in summary."""
        text = "The content appears to be base64 encoded data."
        assert _is_garbled_summary(text) is True

    def test_case_insensitive(self) -> None:
        """Should detect indicators in any case."""
        text = "THE CONTENT APPEARS TO BE CORRUPTED OR ENCRYPTED"
        assert _is_garbled_summary(text) is True

    def test_normal_summary_not_detected(self) -> None:
        """Should not flag normal summaries."""
        text = """# Summary of Article

        This is a normal article about encryption technologies in modern computing.
        The article discusses how encryption protects data."""
        assert _is_garbled_summary(text) is False

    def test_parse_response_raises_on_garbled_content(self) -> None:
        """Should raise GeminiAPIError when summary indicates garbled content."""
        summary = (
            "The provided web page content appears to be corrupted or encrypted, "
            "consisting of garbled characters."
        )
        json_response = f"""{{
            "summary": "{summary}",
            "suggested_tags": ["error"],
            "content_type": "article"
        }}"""

        with pytest.raises(GeminiAPIError, match="corrupted or garbled"):
            _parse_gemini_response(json_response)

    def test_parse_response_passes_normal_content(self) -> None:
        """Should successfully parse normal content."""
        json_response = """{
            "summary": "This is a normal summary about encryption technologies.",
            "suggested_tags": ["security", "encryption"],
            "content_type": "article"
        }"""

        result = _parse_gemini_response(json_response)
        assert "normal summary" in result.content
        assert result.suggested_tags == ["security", "encryption"]
