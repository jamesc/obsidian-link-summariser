"""Tests to verify Langfuse prompt composability behavior."""

from unittest.mock import Mock, patch

from summarize_links.llm.gemini import GeminiClient


def create_mock_resolved_chat_prompt() -> Mock:
    """
    Create a mock Langfuse chat prompt with resolved content.

    This simulates what Langfuse returns after automatically resolving
    the prompt references server-side.
    """
    mock_prompt = Mock()

    # Chat prompt with actual content (after Langfuse resolves references)
    mock_prompt.prompt = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant that summarizes web pages. "
                "You MUST respond with valid JSON."
            ),
        },
        {
            "role": "user",
            "content": "Please summarize this article: {{title}}\nURL: {{url}}\n\n{{content}}",
        },
    ]
    mock_prompt.version = 1
    mock_prompt.name = "summarize-document"

    # compile() method that substitutes variables
    def compile_fn(**kwargs: str) -> list[dict[str, str]]:
        title = kwargs.get("title", "")
        url = kwargs.get("url", "")
        content = kwargs.get("content", "")
        return [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that summarizes web pages. "
                    "You MUST respond with valid JSON."
                ),
            },
            {
                "role": "user",
                "content": f"Please summarize this article: {title}\nURL: {url}\n\n{content}",
            },
        ]

    mock_prompt.compile = Mock(side_effect=compile_fn)

    return mock_prompt


class TestPromptComposability:
    """Test Langfuse prompt composability reference resolution."""

    @patch("langfuse.Langfuse")
    def test_langfuse_resolves_references_automatically(self, mock_langfuse: Mock) -> None:
        """
        Test that Langfuse SDK automatically resolves prompt references.

        When we call get_prompt() on a chat prompt that contains
        @@@langfusePrompt:...@@@ references, Langfuse returns the prompt
        with references already resolved server-side.
        """
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        # Mock Langfuse to return a resolved prompt (references already resolved)
        mock_lf_instance.get_prompt.return_value = create_mock_resolved_chat_prompt()

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # This should work because Langfuse resolves references server-side
        system, user = client._get_langfuse_prompts()

        # Verify we get actual content, not references
        assert "You MUST respond with valid JSON" in system
        assert "{{title}}" in user
        assert "@@@langfusePrompt:" not in system
        assert "@@@langfusePrompt:" not in user

    @patch("langfuse.Langfuse")
    def test_compile_method_works_correctly(self, mock_langfuse: Mock) -> None:
        """
        Test that compile() method substitutes variables correctly.

        The compile() method should handle variable substitution while
        Langfuse handles prompt reference resolution separately.
        """
        mock_lf_instance = Mock()
        mock_langfuse.return_value = mock_lf_instance

        mock_lf_instance.get_prompt.return_value = create_mock_resolved_chat_prompt()

        client = GeminiClient(api_key="test-key", model="gemini-2.5-flash")

        # Get the prompts
        system, user_template = client._get_langfuse_prompts()

        # Compile the user prompt with variables
        compiled = client._compile_user_prompt(
            user_template,
            content="Test article content",
            url="https://example.com",
            title="Test Article",
        )

        # Verify compilation worked
        assert "Test Article" in compiled
        assert "https://example.com" in compiled
