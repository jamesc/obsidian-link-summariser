"""
Tests for the chat tokens module.
"""

from summarize_links.chat.tokens import (
    DEFAULT_ENCODING,
    MODEL_ENCODINGS,
    TOKENS_PER_MESSAGE,
    TOKENS_REPLY_OVERHEAD,
    count_message_tokens,
    count_messages_tokens,
    count_tokens,
    estimate_tool_tokens,
    get_encoding_for_model,
)


class TestGetEncodingForModel:
    """Tests for get_encoding_for_model function."""

    def test_known_model_gpt4(self) -> None:
        """Test encoding for GPT-4."""
        encoding = get_encoding_for_model("gpt-4")
        assert encoding is not None
        assert encoding.name == "cl100k_base"

    def test_known_model_gpt4o(self) -> None:
        """Test encoding for GPT-4o."""
        encoding = get_encoding_for_model("gpt-4o")
        assert encoding is not None
        assert encoding.name == "o200k_base"

    def test_known_model_gpt4_1_mini(self) -> None:
        """Test encoding for GPT-4.1-mini."""
        encoding = get_encoding_for_model("gpt-4.1-mini")
        assert encoding is not None
        assert encoding.name == "o200k_base"

    def test_unknown_model_uses_default(self) -> None:
        """Test that unknown models use default encoding."""
        encoding = get_encoding_for_model("unknown-model-xyz")
        assert encoding is not None
        assert encoding.name == DEFAULT_ENCODING

    def test_normalized_model_name(self) -> None:
        """Test that model names are normalized (dashes/dots removed)."""
        # These should all map to the same encoding
        enc1 = get_encoding_for_model("gpt-4o")
        enc2 = get_encoding_for_model("gpt4o")
        assert enc1.name == enc2.name

    def test_encoding_is_cached(self) -> None:
        """Test that encodings are cached."""
        enc1 = get_encoding_for_model("gpt-4")
        enc2 = get_encoding_for_model("gpt-4")
        assert enc1 is enc2  # Same object due to caching


class TestCountTokens:
    """Tests for count_tokens function."""

    def test_empty_string(self) -> None:
        """Test counting empty string returns 0."""
        assert count_tokens("") == 0

    def test_simple_text(self) -> None:
        """Test counting simple text."""
        count = count_tokens("Hello, world!")
        assert count > 0
        assert count < 10  # Should be small for simple text

    def test_longer_text(self) -> None:
        """Test counting longer text."""
        text = "This is a longer piece of text with multiple words and sentences."
        count = count_tokens(text)
        assert count > 5
        assert count < 50

    def test_different_models(self) -> None:
        """Test that different models may have different counts."""
        text = "Hello, world!"
        count_gpt4 = count_tokens(text, model="gpt-4")
        count_gpt4o = count_tokens(text, model="gpt-4o")
        # Both should be positive (actual values may differ)
        assert count_gpt4 > 0
        assert count_gpt4o > 0

    def test_special_characters(self) -> None:
        """Test counting text with special characters."""
        count = count_tokens("Hello! 🎉 World 🌍")
        assert count > 0

    def test_code_content(self) -> None:
        """Test counting code content."""
        code = "def hello():\n    print('Hello, World!')"
        count = count_tokens(code)
        assert count > 0


class TestCountMessageTokens:
    """Tests for count_message_tokens function."""

    def test_simple_message(self) -> None:
        """Test counting a simple message."""
        from summarize_links.chat.conversation import Message

        msg = Message(role="user", content="Hello!")
        count = count_message_tokens(msg)
        # Should include overhead + content + role
        assert count >= TOKENS_PER_MESSAGE + 1

    def test_empty_content(self) -> None:
        """Test message with empty content."""
        from summarize_links.chat.conversation import Message

        msg = Message(role="assistant", content="")
        count = count_message_tokens(msg)
        # Should still have overhead
        assert count >= TOKENS_PER_MESSAGE

    def test_message_with_name(self) -> None:
        """Test message with name field."""
        from summarize_links.chat.conversation import Message

        msg = Message(role="tool", content="result", name="summarize_url")
        count = count_message_tokens(msg)
        assert count > TOKENS_PER_MESSAGE

    def test_message_with_tool_calls(self) -> None:
        """Test message with tool calls."""
        from summarize_links.chat.conversation import Message

        msg = Message(
            role="assistant",
            content="",  # Use empty string instead of None
            tool_calls=[{"name": "summarize_url", "arguments": {"url": "https://example.com"}}],
        )
        count = count_message_tokens(msg)
        # Should include overhead + tool call tokens
        assert count >= TOKENS_PER_MESSAGE


class TestCountMessagesTokens:
    """Tests for count_messages_tokens function."""

    def test_empty_list(self) -> None:
        """Test counting empty message list."""
        count = count_messages_tokens([])
        # Should still have reply overhead
        assert count == TOKENS_REPLY_OVERHEAD

    def test_single_message(self) -> None:
        """Test counting single message."""
        from summarize_links.chat.conversation import Message

        messages = [Message(role="user", content="Hello!")]
        count = count_messages_tokens(messages)
        assert count > TOKENS_REPLY_OVERHEAD

    def test_multiple_messages(self) -> None:
        """Test counting multiple messages."""
        from summarize_links.chat.conversation import Message

        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello!"),
            Message(role="assistant", content="Hi there!"),
        ]
        count = count_messages_tokens(messages)
        # Should be sum of all messages plus reply overhead
        assert count > 3 * TOKENS_PER_MESSAGE + TOKENS_REPLY_OVERHEAD


class TestEstimateToolTokens:
    """Tests for estimate_tool_tokens function."""

    def test_empty_tools(self) -> None:
        """Test estimating empty tool list."""
        assert estimate_tool_tokens([]) == 0

    def test_single_tool(self) -> None:
        """Test estimating single tool."""
        tools = [
            {
                "type": "function",
                "name": "summarize_url",
                "description": "Summarize a URL",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The URL to summarize"}
                    },
                    "required": ["url"],
                },
            }
        ]
        count = estimate_tool_tokens(tools)
        assert count > 0

    def test_multiple_tools(self) -> None:
        """Test estimating multiple tools."""
        tools = [
            {"type": "function", "name": "tool1", "description": "First tool", "parameters": {}},
            {"type": "function", "name": "tool2", "description": "Second tool", "parameters": {}},
        ]
        count = estimate_tool_tokens(tools)
        # Should be more than a single tool
        single_count = estimate_tool_tokens([tools[0]])
        assert count > single_count


class TestModelEncodings:
    """Tests for MODEL_ENCODINGS constant."""

    def test_has_common_models(self) -> None:
        """Test that common models are defined."""
        assert "gpt-4" in MODEL_ENCODINGS
        assert "gpt-4o" in MODEL_ENCODINGS
        assert "gpt-4.1-mini" in MODEL_ENCODINGS

    def test_all_encodings_valid(self) -> None:
        """Test that all encoding names are valid."""
        import tiktoken

        for model, encoding_name in MODEL_ENCODINGS.items():
            # Should not raise
            encoding = tiktoken.get_encoding(encoding_name)
            assert encoding is not None, f"Invalid encoding {encoding_name} for {model}"
