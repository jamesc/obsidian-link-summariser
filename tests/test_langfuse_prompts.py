"""Tests for Langfuse prompt management integration."""

from unittest.mock import ANY, Mock, patch

import pytest

from summarize_links.exceptions import GeminiAPIError, OllamaAPIError
from summarize_links.llm.gemini import GeminiClient
from summarize_links.llm.ollama import OllamaClient
from summarize_links.models import SummaryResult


def create_mock_chat_prompt(
    system_content: str = "System prompt text",
    user_content: str = "User prompt with {{title}}, {{url}}, {{content}}",
    version: int = 1,
) -> Mock:
    """Create a mock Langfuse chat prompt with messages array.

    The chat prompt has:
    - prompt: list of message dictionaries with role and content
    - version: prompt version number
    - name: prompt name
    - compile(): method that substitutes variables and returns list of message dicts
    """
    mock_prompt = Mock()

    # Chat prompt structure has messages array as list of dicts
    mock_prompt.prompt = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
    mock_prompt.version = version
    mock_prompt.name = "summarize-document"

    # compile() returns list of message dicts with variables substituted
    def compile_fn(**kwargs: str) -> list[dict[str, str]]:
        title = kwargs.get("title", "")
        url = kwargs.get("url", "")
        # content is passed but not used in mock response
        _ = kwargs.get("content", "")
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"Compiled prompt with title:{title}, url: {url}"},
        ]

    mock_prompt.compile = Mock(side_effect=compile_fn)

    return mock_prompt


class TestGeminiLangfusePrompts:
    """Test Langfuse prompt management in Gemini client."""

    @patch("langfuse.Langfuse")
    def test_client_initializes_with_langfuse(self, mock_langfuse: Mock) -> None:
        """Test that client initializes Langfuse client (required)."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        assert client._langfuse_client == mock_lf_instance
        mock_langfuse.assert_called_once()

    @patch("langfuse.Langfuse")
    def test_client_initialization_fails_without_langfuse(self, mock_langfuse: Mock) -> None:
        """Test that client fails to initialize if Langfuse is not available."""
        mock_langfuse.side_effect = Exception("Langfuse not available")

        with pytest.raises(GeminiAPIError, match="Failed to initialize Langfuse"):
            GeminiClient(api_key="test-key", model="gemini-2.5-flash")

    @patch("langfuse.Langfuse")
    def test_get_langfuse_prompts_fetches_and_caches(self, mock_langfuse: Mock) -> None:
        """Test that prompts are fetched from Langfuse and cached."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        # Mock chat prompt with system and user messages
        mock_chat_prompt = create_mock_chat_prompt()
        mock_lf_instance.get_prompt.return_value = mock_chat_prompt

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # First call should fetch
        result = client._get_langfuse_prompts()

        assert result == (
            "System prompt text",
            "User prompt with {{title}}, {{url}}, {{content}}",
        )
        mock_lf_instance.get_prompt.assert_called_once_with("summarize-document", type="chat")
        assert client._prompt_cache["prompt"] == mock_chat_prompt

        # Second call should use cache
        result2 = client._get_langfuse_prompts()

        assert result2 == result
        assert mock_lf_instance.get_prompt.call_count == 1  # No additional calls

    @patch("langfuse.Langfuse")
    def test_get_langfuse_prompts_handles_errors(self, mock_langfuse: Mock) -> None:
        """Test that errors during prompt fetching are raised as GeminiAPIError."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        # Simulate error during fetch
        mock_lf_instance.get_prompt.side_effect = Exception("Network error")

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Should raise GeminiAPIError (new error message format)
        with pytest.raises(GeminiAPIError, match="Failed to fetch prompt from Langfuse"):
            client._get_langfuse_prompts()

    @patch("langfuse.Langfuse")
    def test_compile_user_prompt_with_langfuse_template(self, mock_langfuse: Mock) -> None:
        """Test that user prompt template is compiled with variables."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Mock the cached prompt - compile() returns list of message dicts
        mock_prompt = Mock()
        mock_prompt.compile.return_value = [
            {"role": "system", "content": "System prompt"},
            {
                "role": "user",
                "content": "Compiled prompt with title: Test, url: https://example.com",
            },
        ]
        client._prompt_cache["prompt"] = mock_prompt

        template = "User prompt with {{title}}, {{url}}, {{content}}"
        result = client._compile_user_prompt(
            template, "content here", "https://example.com", "Test"
        )

        assert "Compiled prompt" in result
        # Title is formatted as " titled 'X'" to match main branch behavior
        # current_date is dynamically set to today's date
        mock_prompt.compile.assert_called_once_with(
            title=" titled 'Test'",
            url="https://example.com",
            content="content here",
            current_date=ANY,
        )

    @patch("langfuse.Langfuse")
    def test_compile_user_prompt_raises_on_error(self, mock_langfuse: Mock) -> None:
        """Test that template compilation errors are raised, not swallowed."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Mock the cached prompt with failing compile
        mock_prompt = Mock()
        mock_prompt.compile.side_effect = Exception("Variable mismatch")
        client._prompt_cache["prompt"] = mock_prompt

        template = "Page{{title}}, URL: {{url}}, Content: {{content}}"

        # Should raise the exception, not fall back
        with pytest.raises(Exception, match="Variable mismatch"):
            client._compile_user_prompt(
                template, "test content", "https://example.com", "Test Title"
            )

    @patch("langfuse.Langfuse")
    def test_compile_user_prompt_with_none_title(self, mock_langfuse: Mock) -> None:
        """Test that None title produces empty string, not 'Unknown'."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Mock the cached prompt - compile() returns list of message dicts
        mock_prompt = Mock()
        mock_prompt.compile.return_value = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Summarize the web page:\nhttps://example.com\ncontent"},
        ]
        client._prompt_cache["prompt"] = mock_prompt

        template = "Summarize the web page{{title}}:\n{{url}}\n{{content}}"
        result = client._compile_user_prompt(template, "test content", "https://example.com", None)

        # Should pass empty string for title, not 'Unknown'
        # current_date is dynamically set to today's date
        mock_prompt.compile.assert_called_once_with(
            title="",
            url="https://example.com",
            content="test content",
            current_date=ANY,
        )
        assert "Summarize the web page" in result

    @patch("langfuse.Langfuse")
    def test_get_cached_prompt_returns_prompt_object(self, mock_langfuse: Mock) -> None:
        """Test that get_cached_prompt returns cached prompt object."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Mock cached prompt object
        mock_prompt = create_mock_chat_prompt()

        # No prompt cached yet
        assert client.get_cached_prompt() is None

        # Add to cache
        client._prompt_cache["prompt"] = mock_prompt

        # Now should return the cached prompt
        result = client.get_cached_prompt()
        assert result is not None
        assert result == mock_prompt
        assert result.name == "summarize-document"

    @patch("langfuse.Langfuse")
    def test_extract_messages_from_chat_prompt(self, mock_langfuse: Mock) -> None:
        """Test extraction of system and user messages from chat prompt."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Create chat prompt with messages as list of dicts
        mock_prompt = Mock()
        mock_prompt.prompt = [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Summarize: {{content}}"},
        ]

        system, user = client._extract_messages_from_chat_prompt(mock_prompt)

        assert system == "Be helpful"
        assert user == "Summarize: {{content}}"

    @patch("langfuse.Langfuse")
    def test_extract_messages_raises_on_missing_system(self, mock_langfuse: Mock) -> None:
        """Test that missing system message raises an error."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Create prompt with only user message
        mock_prompt = Mock()
        mock_prompt.prompt = [
            {"role": "user", "content": "User only"},
        ]

        with pytest.raises(GeminiAPIError, match="missing system message"):
            client._extract_messages_from_chat_prompt(mock_prompt)

    @patch("langfuse.Langfuse")
    def test_extract_messages_raises_on_missing_user(self, mock_langfuse: Mock) -> None:
        """Test that missing user message raises an error."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Create prompt with only system message
        mock_prompt = Mock()
        mock_prompt.prompt = [
            {"role": "system", "content": "System only"},
        ]

        with pytest.raises(GeminiAPIError, match="missing user message"):
            client._extract_messages_from_chat_prompt(mock_prompt)


class TestOllamaLangfusePrompts:
    """Test Langfuse prompt management in Ollama client."""

    @patch("langfuse.Langfuse")
    def test_client_initializes_with_langfuse(self, mock_langfuse: Mock) -> None:
        """Test that client initializes Langfuse client (required)."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = OllamaClient(model="llama3:latest")

        assert client._langfuse_client == mock_lf_instance
        mock_langfuse.assert_called_once()

    @patch("langfuse.Langfuse")
    def test_client_initialization_fails_without_langfuse(self, mock_langfuse: Mock) -> None:
        """Test that client fails to initialize if Langfuse is not available."""
        mock_langfuse.side_effect = Exception("Langfuse not available")

        with pytest.raises(OllamaAPIError, match="Failed to initialize Langfuse"):
            OllamaClient(model="llama3:latest")

    @patch("langfuse.Langfuse")
    def test_get_langfuse_prompts_fetches_and_caches(self, mock_langfuse: Mock) -> None:
        """Test that prompts are fetched from Langfuse and cached."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        # Mock chat prompt with system and user messages
        mock_chat_prompt = create_mock_chat_prompt(
            system_content="System instructions",
            user_content="{{title}} from {{url}}: {{content}}",
            version=3,
        )
        mock_lf_instance.get_prompt.return_value = mock_chat_prompt

        client = OllamaClient(model="llama3:latest")

        # First call should fetch
        result = client._get_langfuse_prompts()

        assert result == ("System instructions", "{{title}} from {{url}}: {{content}}")
        mock_lf_instance.get_prompt.assert_called_once_with("summarize-document", type="chat")
        assert client._prompt_cache["prompt"] == mock_chat_prompt

    @patch("langfuse.Langfuse")
    def test_compile_user_prompt_with_template(self, mock_langfuse: Mock) -> None:
        """Test that user prompt template is compiled with variables."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = OllamaClient(model="llama3:latest")

        # Mock the cached prompt - compile() returns list of message dicts
        mock_prompt = Mock()
        mock_prompt.compile.return_value = [
            {"role": "system", "content": "System prompt"},
            {
                "role": "user",
                "content": "Page titled 'My Title' from https://test.com: content here",
            },
        ]
        client._prompt_cache["prompt"] = mock_prompt

        template = "Page{{title}} from {{url}}: {{content}}"
        result = client._compile_user_prompt(
            template, "content here", "https://test.com", "My Title"
        )

        assert "titled 'My Title'" in result
        # Title is formatted as " titled 'X'" to match main branch behavior
        # current_date is dynamically set to today's date
        mock_prompt.compile.assert_called_once_with(
            title=" titled 'My Title'",
            url="https://test.com",
            content="content here",
            current_date=ANY,
        )


class TestPromptMetadata:
    """Test that prompt metadata is included in SummaryResult."""

    def test_summary_result_accepts_prompt_metadata(self) -> None:
        """Test that SummaryResult accepts and stores prompt_metadata."""
        metadata = {"system_prompt_version": 5, "user_prompt_version": 10, "source": "langfuse"}

        result = SummaryResult(
            content="Test summary",
            suggested_tags=["test"],
            content_type="article",
            prompt_metadata=metadata,
        )

        assert result.prompt_metadata == metadata
        assert result.prompt_metadata["system_prompt_version"] == 5
        assert result.prompt_metadata["source"] == "langfuse"

    def test_summary_result_prompt_metadata_defaults_to_none(self) -> None:
        """Test that prompt_metadata defaults to None when not provided."""
        result = SummaryResult(content="Test summary", suggested_tags=[], content_type="article")

        assert result.prompt_metadata is None
