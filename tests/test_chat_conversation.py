"""
Tests for the chat conversation module.
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from summarize_links.chat.conversation import Conversation, Message


class TestMessage:
    """Tests for the Message dataclass."""

    def test_create_message(self) -> None:
        """Test creating a basic message."""
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert isinstance(msg.timestamp, datetime)

    def test_message_with_tool_calls(self) -> None:
        """Test creating a message with tool calls."""
        tool_calls = [{"name": "test_tool", "args": {"url": "https://example.com"}}]
        msg = Message(role="assistant", content="", tool_calls=tool_calls)
        assert msg.tool_calls == tool_calls

    def test_message_to_dict(self) -> None:
        """Test serializing message to dict."""
        msg = Message(role="user", content="Test message")
        data = msg.to_dict()
        assert data["role"] == "user"
        assert data["content"] == "Test message"
        assert "timestamp" in data

    def test_message_from_dict(self) -> None:
        """Test deserializing message from dict."""
        data = {
            "role": "assistant",
            "content": "Response",
            "timestamp": "2024-01-15T10:30:00",
        }
        msg = Message.from_dict(data)
        assert msg.role == "assistant"
        assert msg.content == "Response"

    def test_message_to_llm_format(self) -> None:
        """Test converting message to LLM format."""
        msg = Message(role="user", content="Hello")
        llm_format = msg.to_llm_format()
        assert llm_format == {"role": "user", "content": "Hello"}

    def test_tool_message_to_llm_format(self) -> None:
        """Test converting tool message to LLM format."""
        msg = Message(
            role="tool",
            content="Result",
            tool_call_id="call_123",
            name="summarize_url",
        )
        llm_format = msg.to_llm_format()
        assert llm_format["role"] == "tool"
        assert llm_format["tool_call_id"] == "call_123"
        assert llm_format["name"] == "summarize_url"


class TestConversation:
    """Tests for the Conversation class."""

    def test_create_conversation(self) -> None:
        """Test creating a new conversation."""
        conv = Conversation()
        assert len(conv) == 0

    def test_create_with_system_prompt(self) -> None:
        """Test creating conversation with system prompt."""
        conv = Conversation(system_prompt="You are a helpful assistant.")
        assert len(conv) == 1
        assert conv.messages[0].role == "system"
        assert conv.system_prompt == "You are a helpful assistant."

    def test_add_user_message(self) -> None:
        """Test adding a user message."""
        conv = Conversation()
        msg = conv.add_user_message("Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert len(conv) == 1

    def test_add_assistant_message(self) -> None:
        """Test adding an assistant message."""
        conv = Conversation()
        msg = conv.add_assistant_message("Hi there!")
        assert msg.role == "assistant"
        assert msg.content == "Hi there!"

    def test_add_tool_result(self) -> None:
        """Test adding a tool result message."""
        conv = Conversation()
        msg = conv.add_tool_result(
            tool_call_id="call_123",
            name="summarize_url",
            content="Summary created",
        )
        assert msg.role == "tool"
        assert msg.tool_call_id == "call_123"
        assert msg.name == "summarize_url"

    def test_get_messages_for_llm(self) -> None:
        """Test getting messages in LLM format."""
        conv = Conversation(system_prompt="System")
        conv.add_user_message("Hello")
        conv.add_assistant_message("Hi!")

        messages = conv.get_messages_for_llm()
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"

    def test_get_last_user_message(self) -> None:
        """Test getting the last user message."""
        conv = Conversation()
        conv.add_user_message("First")
        conv.add_assistant_message("Response")
        conv.add_user_message("Second")

        last = conv.get_last_user_message()
        assert last is not None
        assert last.content == "Second"

    def test_get_last_assistant_message(self) -> None:
        """Test getting the last assistant message."""
        conv = Conversation()
        conv.add_user_message("Hello")
        conv.add_assistant_message("Hi!")
        conv.add_user_message("Bye")

        last = conv.get_last_assistant_message()
        assert last is not None
        assert last.content == "Hi!"

    def test_clear_conversation(self) -> None:
        """Test clearing conversation history."""
        conv = Conversation(system_prompt="System")
        conv.add_user_message("Hello")
        conv.add_assistant_message("Hi!")

        conv.clear(keep_system=True)
        assert len(conv) == 1
        assert conv.messages[0].role == "system"

    def test_clear_conversation_all(self) -> None:
        """Test clearing all messages including system."""
        conv = Conversation(system_prompt="System")
        conv.add_user_message("Hello")

        conv.clear(keep_system=False)
        assert len(conv) == 0

    def test_trim_history(self) -> None:
        """Test automatic history trimming."""
        conv = Conversation(max_messages=5)

        for i in range(10):
            conv.add_user_message(f"Message {i}")

        # Should have trimmed to max_messages
        assert len(conv) == 5

    def test_trim_preserves_system_message(self) -> None:
        """Test that trimming preserves system message."""
        conv = Conversation(system_prompt="System", max_messages=3)

        for i in range(10):
            conv.add_user_message(f"Message {i}")

        # System message should still be there
        assert conv.messages[0].role == "system"
        assert len(conv) == 3

    def test_save_and_load(self) -> None:
        """Test saving and loading conversation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "conversation.json"

            # Create and save
            conv = Conversation(system_prompt="System")
            conv.add_user_message("Hello")
            conv.add_assistant_message("Hi!")
            conv.save(save_path)

            # Load
            loaded = Conversation.load(save_path)
            assert len(loaded) == 3
            assert loaded.messages[0].content == "System"
            assert loaded.messages[1].content == "Hello"
            assert loaded.messages[2].content == "Hi!"

    def test_save_requires_path(self) -> None:
        """Test that save raises error without path."""
        conv = Conversation()
        with pytest.raises(ValueError, match="No save path"):
            conv.save()

    def test_repr(self) -> None:
        """Test string representation."""
        conv = Conversation(max_messages=50)
        conv.add_user_message("Hello")
        assert repr(conv) == "Conversation(messages=1, max=50)"
