"""Tests for Langfuse prompt management integration."""

from unittest.mock import Mock, patch

from summarize_links.llm.gemini import GeminiClient
from summarize_links.llm.ollama import OllamaClient
from summarize_links.models import SummaryResult


class TestGeminiLangfusePrompts:
    """Test Langfuse prompt management in Gemini client."""

    def test_client_initializes_without_langfuse(self) -> None:
        """Test that client initializes normally when langfuse_enabled=False."""
        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash", langfuse_enabled=False)

        assert client._langfuse_enabled is False
        assert client._langfuse_client is None
        assert client._prompt_cache == {}

    @patch("langfuse.Langfuse")
    def test_client_initializes_with_langfuse(self, mock_langfuse: Mock) -> None:
        """Test that client initializes Langfuse client when enabled."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash", langfuse_enabled=True)

        assert client._langfuse_enabled is True
        assert client._langfuse_client == mock_lf_instance
        mock_langfuse.assert_called_once()

    def test_get_langfuse_prompts_returns_none_when_disabled(self) -> None:
        """Test that _get_langfuse_prompts returns None when Langfuse is disabled."""
        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash", langfuse_enabled=False)

        result = client._get_langfuse_prompts()

        assert result is None

    @patch("langfuse.Langfuse")
    def test_get_langfuse_prompts_fetches_and_caches(self, mock_langfuse: Mock) -> None:
        """Test that prompts are fetched from Langfuse and cached."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        # Mock prompt objects
        mock_system_prompt = Mock()
        mock_system_prompt.prompt = "System prompt text"
        mock_system_prompt.version = 1

        mock_user_prompt = Mock()
        mock_user_prompt.prompt = "User prompt with {{title}}, {{url}}, {{content}}"
        mock_user_prompt.version = 2

        mock_lf_instance.get_prompt.side_effect = [mock_system_prompt, mock_user_prompt]

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash", langfuse_enabled=True)

        # First call should fetch
        result = client._get_langfuse_prompts()

        assert result == ("System prompt text", "User prompt with {{title}}, {{url}}, {{content}}")
        assert mock_lf_instance.get_prompt.call_count == 2
        assert client._prompt_cache["system"] == mock_system_prompt
        assert client._prompt_cache["user"] == mock_user_prompt

        # Second call should use cache
        result2 = client._get_langfuse_prompts()

        assert result2 == result
        assert mock_lf_instance.get_prompt.call_count == 2  # No additional calls

    @patch("langfuse.Langfuse")
    def test_get_langfuse_prompts_handles_errors(self, mock_langfuse: Mock) -> None:
        """Test that errors during prompt fetching are handled gracefully."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        # Simulate error during fetch
        mock_lf_instance.get_prompt.side_effect = Exception("Network error")

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash", langfuse_enabled=True)

        result = client._get_langfuse_prompts()

        # Should return None to trigger fallback
        assert result is None

    def test_compile_user_prompt_with_langfuse_template(self) -> None:
        """Test that user prompt template is compiled with variables."""
        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash", langfuse_enabled=False)

        # Mock the cached user prompt
        mock_user_obj = Mock()
        mock_user_obj.compile.return_value = (
            "Compiled prompt with title: Test, url: https://example.com"
        )
        client._prompt_cache["user"] = mock_user_obj

        template = "User prompt with {{title}}, {{url}}, {{content}}"
        result = client._compile_user_prompt(
            template, "content here", "https://example.com", "Test"
        )

        assert "Compiled prompt" in result
        mock_user_obj.compile.assert_called_once_with(
            title="Test", url="https://example.com", content="content here"
        )

    def test_compile_user_prompt_fallback_on_error(self) -> None:
        """Test that template compilation falls back to string replacement on error."""
        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash", langfuse_enabled=False)

        # Mock the cached user prompt with failing compile
        mock_user_obj = Mock()
        mock_user_obj.compile.side_effect = Exception("Compilation error")
        client._prompt_cache["user"] = mock_user_obj

        template = "Title: {{title}}, URL: {{url}}, Content: {{content}}"
        result = client._compile_user_prompt(
            template, "test content", "https://example.com", "Test Title"
        )

        # Should use simple string replacement
        assert "Title: Test Title" in result
        assert "URL: https://example.com" in result
        assert "Content: test content" in result

    def test_compile_user_prompt_non_template(self) -> None:
        """Test that non-template strings are returned as-is."""
        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash", langfuse_enabled=False)

        non_template = "This is a regular string without variables"
        result = client._compile_user_prompt(non_template, "content", "url", "title")

        # Should return the string as-is since it's not a template
        assert result == non_template


class TestOllamaLangfusePrompts:
    """Test Langfuse prompt management in Ollama client."""

    def test_client_initializes_without_langfuse(self) -> None:
        """Test that client initializes normally when langfuse_enabled=False."""
        client = OllamaClient(model="llama3:latest", langfuse_enabled=False)

        assert client._langfuse_enabled is False
        assert client._langfuse_client is None
        assert client._prompt_cache == {}

    @patch("langfuse.Langfuse")
    def test_client_initializes_with_langfuse(self, mock_langfuse: Mock) -> None:
        """Test that client initializes Langfuse client when enabled."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = OllamaClient(model="llama3:latest", langfuse_enabled=True)

        assert client._langfuse_enabled is True
        assert client._langfuse_client == mock_lf_instance
        mock_langfuse.assert_called_once()

    def test_get_langfuse_prompts_returns_none_when_disabled(self) -> None:
        """Test that _get_langfuse_prompts returns None when Langfuse is disabled."""
        client = OllamaClient(model="llama3:latest", langfuse_enabled=False)

        result = client._get_langfuse_prompts()

        assert result is None

    @patch("langfuse.Langfuse")
    def test_get_langfuse_prompts_fetches_and_caches(self, mock_langfuse: Mock) -> None:
        """Test that prompts are fetched from Langfuse and cached."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        # Mock prompt objects
        mock_system_prompt = Mock()
        mock_system_prompt.prompt = "System instructions"
        mock_system_prompt.version = 1

        mock_user_prompt = Mock()
        mock_user_prompt.prompt = "{{title}} from {{url}}: {{content}}"
        mock_user_prompt.version = 3

        mock_lf_instance.get_prompt.side_effect = [mock_system_prompt, mock_user_prompt]

        client = OllamaClient(model="llama3:latest", langfuse_enabled=True)

        # First call should fetch
        result = client._get_langfuse_prompts()

        assert result == ("System instructions", "{{title}} from {{url}}: {{content}}")
        assert mock_lf_instance.get_prompt.call_count == 2
        assert client._prompt_cache["system"] == mock_system_prompt
        assert client._prompt_cache["user"] == mock_user_prompt

    def test_compile_user_prompt_with_template(self) -> None:
        """Test that user prompt template is compiled with variables."""
        client = OllamaClient(model="llama3:latest", langfuse_enabled=False)

        # Mock the cached user prompt
        mock_user_obj = Mock()
        mock_user_obj.compile.return_value = "My Title from https://test.com: content here"
        client._prompt_cache["user"] = mock_user_obj

        template = "{{title}} from {{url}}: {{content}}"
        result = client._compile_user_prompt(
            template, "content here", "https://test.com", "My Title"
        )

        assert "My Title" in result
        mock_user_obj.compile.assert_called_once_with(
            title="My Title", url="https://test.com", content="content here"
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
