"""Integration tests for prompt handling across the system."""

from unittest.mock import Mock, patch

import pytest

from summarize_links.exceptions import AzureAPIError, GeminiAPIError
from summarize_links.llm.azure import AzureClient
from summarize_links.llm.gemini import GeminiClient


def create_mock_chat_prompt(version: int = 1) -> Mock:
    """Create a mock Langfuse chat prompt."""
    mock_prompt = Mock()
    mock_prompt.prompt = [
        {
            "role": "system",
            "content": "You are a helpful assistant. You MUST respond with valid JSON.",
        },
        {"role": "user", "content": "Summarize{{title}}: {{url}}\n\n{{content}}"},
    ]
    mock_prompt.version = version
    mock_prompt.name = "summarize-document"

    def compile_fn(**kwargs: str) -> list[dict[str, str]]:
        title = kwargs.get("title", "")
        url = kwargs.get("url", "")
        content = kwargs.get("content", "")
        return [
            {
                "role": "system",
                "content": "You are a helpful assistant. You MUST respond with valid JSON.",
            },
            {"role": "user", "content": f"Summarize{title}: {url}\n\n{content}"},
        ]

    mock_prompt.compile = Mock(side_effect=compile_fn)
    return mock_prompt


class TestPromptPreFetching:
    """Test the pre-fetch pattern used in processor.py."""

    @patch("langfuse.Langfuse")
    def test_prefetch_before_get_cached_prompt(self, mock_langfuse: Mock) -> None:
        """Test that pre-fetching ensures prompt is available for linking."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance
        mock_lf_instance.get_prompt.return_value = create_mock_chat_prompt()

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Initially, get_cached_prompt returns None
        assert client.get_cached_prompt() is None

        # Pre-fetch the prompt (simulating processor.py behavior)
        client._get_langfuse_prompts()

        # Now get_cached_prompt should return the prompt object
        prompt = client.get_cached_prompt()
        assert prompt is not None
        assert prompt.name == "summarize-document"
        assert prompt.version == 1

    @patch("langfuse.Langfuse")
    def test_prefetch_failure_handled_gracefully(self, mock_langfuse: Mock) -> None:
        """Test that pre-fetch failures don't crash the system."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance
        mock_lf_instance.get_prompt.side_effect = Exception("Network error")

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Pre-fetch will fail
        with pytest.raises(GeminiAPIError, match="Failed to fetch prompt"):
            client._get_langfuse_prompts()

        # get_cached_prompt should still return None without crashing
        assert client.get_cached_prompt() is None

    @patch("langfuse.Langfuse")
    def test_cache_persists_across_calls(self, mock_langfuse: Mock) -> None:
        """Test that cached prompt persists for multiple summarizations."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance
        mock_lf_instance.get_prompt.return_value = create_mock_chat_prompt()

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # First call fetches
        prompt1 = client._get_langfuse_prompts()
        assert mock_lf_instance.get_prompt.call_count == 1

        # Subsequent calls use cache
        prompt2 = client._get_langfuse_prompts()
        prompt3 = client._get_langfuse_prompts()
        assert mock_lf_instance.get_prompt.call_count == 1  # No additional calls

        assert prompt1 == prompt2 == prompt3


class TestAzurePromptHandling:
    """Test Azure-specific prompt handling."""

    @patch("langfuse.Langfuse")
    @patch("openai.AzureOpenAI")
    def test_azure_fetches_prompts_correctly(
        self, mock_azure_openai: Mock, mock_langfuse: Mock
    ) -> None:
        """Test that Azure client correctly fetches Langfuse prompts."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance
        mock_chat_prompt = create_mock_chat_prompt()
        mock_lf_instance.get_prompt.return_value = mock_chat_prompt

        client = AzureClient(
            api_key="test-key",
            endpoint="https://test.openai.azure.com",
            deployment_name="gpt-4",
            model="gpt-4",
        )

        system, user = client._get_langfuse_prompts()

        assert "You MUST respond with valid JSON" in system
        assert "{{title}}" in user
        mock_lf_instance.get_prompt.assert_called_once_with("summarize-document", type="chat")


class TestPromptMetadataBuilding:
    """Test _build_prompt_metadata functionality."""

    @patch("langfuse.Langfuse")
    def test_build_prompt_metadata_with_cached_prompt(self, mock_langfuse: Mock) -> None:
        """Test metadata building when prompt is cached."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance
        mock_lf_instance.get_prompt.return_value = create_mock_chat_prompt(version=5)

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Fetch to populate cache
        client._get_langfuse_prompts()

        # Build metadata
        metadata = client._build_prompt_metadata()

        assert metadata is not None
        assert metadata["prompt_name"] == "summarize-document"
        assert metadata["prompt_version"] == 5
        assert metadata["prompt_type"] == "chat"
        assert metadata["source"] == "langfuse"

    @patch("langfuse.Langfuse")
    def test_build_prompt_metadata_without_cached_prompt(self, mock_langfuse: Mock) -> None:
        """Test metadata building when prompt is not cached."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Don't fetch prompt
        metadata = client._build_prompt_metadata()

        assert metadata is None


class TestPromptVersionTracking:
    """Test that prompt versions are correctly tracked."""

    @patch("langfuse.Langfuse")
    def test_different_prompt_versions_tracked(self, mock_langfuse: Mock) -> None:
        """Test that different prompt versions are correctly identified."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        # Create prompts with different versions
        v1_prompt = create_mock_chat_prompt(version=1)
        v2_prompt = create_mock_chat_prompt(version=2)

        # First client uses v1
        mock_lf_instance.get_prompt.return_value = v1_prompt
        client1 = GeminiClient(api_key="test-key", model="gemini-2.5-flash")
        client1._get_langfuse_prompts()
        metadata1 = client1._build_prompt_metadata()

        # Second client uses v2
        mock_lf_instance.get_prompt.return_value = v2_prompt
        client2 = GeminiClient(api_key="test-key", model="gemini-2.5-flash")
        client2._get_langfuse_prompts()
        metadata2 = client2._build_prompt_metadata()

        assert metadata1["prompt_version"] == 1
        assert metadata2["prompt_version"] == 2

    @patch("langfuse.Langfuse")
    def test_cached_prompt_object_linkable(self, mock_langfuse: Mock) -> None:
        """Test that cached prompt can be passed to Langfuse trace."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance
        mock_prompt = create_mock_chat_prompt(version=3)
        mock_lf_instance.get_prompt.return_value = mock_prompt

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")
        client._get_langfuse_prompts()

        # Get the cached prompt for linking
        cached_prompt = client.get_cached_prompt()

        # Should be the exact same object that can be passed to trace_generation
        assert cached_prompt is mock_prompt
        assert cached_prompt.name == "summarize-document"
        assert cached_prompt.version == 3
        # Verify it has the required attributes for Langfuse linking
        assert hasattr(cached_prompt, "name")
        assert hasattr(cached_prompt, "version")
        assert hasattr(cached_prompt, "prompt")


class TestPromptErrorRecovery:
    """Test error recovery in prompt handling."""

    @patch("langfuse.Langfuse")
    def test_cache_cleared_after_error(self, mock_langfuse: Mock) -> None:
        """Test that cache state is correct even after errors."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # First call fails
        mock_lf_instance.get_prompt.side_effect = Exception("Network error")
        with pytest.raises(GeminiAPIError):
            client._get_langfuse_prompts()

        # Cache should still be empty
        assert client.get_cached_prompt() is None

        # Second call succeeds
        mock_lf_instance.get_prompt.side_effect = None
        mock_lf_instance.get_prompt.return_value = create_mock_chat_prompt()
        client._get_langfuse_prompts()

        # Now cache should have the prompt
        assert client.get_cached_prompt() is not None

    @patch("langfuse.Langfuse")
    def test_compilation_error_preserves_cache(self, mock_langfuse: Mock) -> None:
        """Test that compilation errors don't corrupt the prompt cache."""
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance
        mock_prompt = create_mock_chat_prompt()
        mock_lf_instance.get_prompt.return_value = mock_prompt

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")
        client._get_langfuse_prompts()

        # Break the compile function
        mock_prompt.compile.side_effect = Exception("Compilation failed")

        # Compilation should fail
        with pytest.raises(Exception, match="Compilation failed"):
            client._compile_user_prompt(
                "template {{url}}", "content", "https://test.com", "Title"
            )

        # But cached prompt should still be available
        assert client.get_cached_prompt() is not None
        assert client.get_cached_prompt().name == "summarize-document"
