"""
Conversation history management for the chat CLI.

This module handles:
- Message storage and retrieval
- Context window management (token-based)
- Session persistence (optional)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "Message",
    "Conversation",
]

logger = logging.getLogger(__name__)

# Role type for messages
Role = Literal["system", "user", "assistant", "tool"]

# Default token limits
DEFAULT_MAX_CONTEXT_TOKENS = 100000  # Leave room for response
DEFAULT_MAX_MESSAGES = 50  # Fallback message limit


@dataclass
class Message:
    """
    A single message in the conversation.

    Attributes:
        role: The role of the message sender (system, user, assistant, tool).
        content: The text content of the message.
        timestamp: When the message was created.
        tool_calls: Optional list of tool calls made by the assistant.
        tool_call_id: Optional ID if this is a tool response.
        name: Optional name for tool messages.
        metadata: Optional additional metadata.
    """

    role: Role
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert message to dictionary for serialization."""
        data: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.tool_calls:
            data["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        if self.name:
            data["name"] = self.name
        if self.metadata:
            data["metadata"] = self.metadata
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Create a Message from a dictionary."""
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat())),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
            metadata=data.get("metadata", {}),
        )

    def to_llm_format(self) -> dict[str, Any]:
        """
        Convert to format expected by LLM APIs.

        Returns a dict with role and content, plus tool-related fields if present.
        """
        msg: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        return msg


class Conversation:
    """
    Manages conversation history and context.

    Handles message storage, context window management (token-based),
    and optional persistence to disk.

    Attributes:
        messages: List of messages in the conversation.
        max_messages: Maximum messages to retain (fallback limit).
        max_context_tokens: Maximum tokens for context window.
        model: Model name for token counting.
        save_path: Optional path for session persistence.
    """

    def __init__(
        self,
        system_prompt: str | None = None,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        model: str = "gpt-4.1-mini",
        save_path: Path | None = None,
    ) -> None:
        """
        Initialize a new conversation.

        Args:
            system_prompt: Optional system prompt to set context.
            max_messages: Maximum messages to retain (fallback).
            max_context_tokens: Maximum tokens for context window.
            model: Model name for token counting.
            save_path: Optional path to save conversation history.
        """
        self.messages: list[Message] = []
        self.max_messages = max_messages
        self.max_context_tokens = max_context_tokens
        self.model = model
        self.save_path = save_path
        self._system_prompt = system_prompt
        self._token_cache: dict[int, int] = {}  # message id -> token count

        if system_prompt:
            self.add_message("system", system_prompt)

        logger.debug(
            "Initialized conversation (max_messages=%d, max_tokens=%d, model=%s)",
            max_messages,
            max_context_tokens,
            model,
        )

    @property
    def system_prompt(self) -> str | None:
        """Get the system prompt for this conversation."""
        return self._system_prompt

    def add_message(
        self,
        role: Role,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        """
        Add a message to the conversation.

        Args:
            role: Message role (system, user, assistant, tool).
            content: Message content.
            tool_calls: Optional tool calls for assistant messages.
            tool_call_id: Optional tool call ID for tool responses.
            name: Optional name for tool messages.
            metadata: Optional additional metadata.

        Returns:
            The created Message object.
        """
        message = Message(
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            name=name,
            metadata=metadata or {},
        )
        self.messages.append(message)

        # Trim history if needed (but keep system message)
        self._trim_history()

        logger.debug("Added %s message (%d chars)", role, len(content))
        return message

    def add_user_message(self, content: str) -> Message:
        """Add a user message."""
        return self.add_message("user", content)

    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Add an assistant message."""
        return self.add_message("assistant", content, tool_calls=tool_calls)

    def add_assistant_tool_call(
        self,
        content: str | None,
        tool_calls: list[dict[str, Any]],
    ) -> Message:
        """
        Add an assistant message with tool calls.

        Args:
            content: Optional text content.
            tool_calls: List of tool call dicts with id, name, arguments.

        Returns:
            The created Message.
        """
        return self.add_message(
            "assistant",
            content or "",
            tool_calls=tool_calls,
        )

    def add_tool_result(
        self,
        tool_call_id: str,
        name: str,
        content: str,
    ) -> Message:
        """Add a tool result message."""
        return self.add_message(
            "tool",
            content,
            tool_call_id=tool_call_id,
            name=name,
        )

    def get_messages_for_llm(self) -> list[dict[str, Any]]:
        """
        Get messages formatted for LLM API.

        Returns:
            List of message dicts with role/content structure.
        """
        return [msg.to_llm_format() for msg in self.messages]

    def get_last_user_message(self) -> Message | None:
        """Get the most recent user message."""
        for msg in reversed(self.messages):
            if msg.role == "user":
                return msg
        return None

    def get_last_assistant_message(self) -> Message | None:
        """Get the most recent assistant message."""
        for msg in reversed(self.messages):
            if msg.role == "assistant":
                return msg
        return None

    def _get_message_tokens(self, message: Message) -> int:
        """
        Get token count for a message (with caching).

        Args:
            message: Message to count tokens for.

        Returns:
            Number of tokens.
        """
        msg_id = id(message)
        if msg_id not in self._token_cache:
            from summarize_links.chat.tokens import count_message_tokens

            self._token_cache[msg_id] = count_message_tokens(message, self.model)
        return self._token_cache[msg_id]

    def get_total_tokens(self) -> int:
        """
        Get total token count for all messages.

        Returns:
            Total tokens in conversation.
        """
        return sum(self._get_message_tokens(msg) for msg in self.messages)

    def _trim_history(self) -> None:
        """
        Trim conversation history to stay within limits.

        Uses token-based trimming first, then falls back to message count.
        Preserves the system message (if present) and removes oldest
        non-system messages first.
        """
        # Separate system message from others
        system_msgs = [m for m in self.messages if m.role == "system"]
        other_msgs = [m for m in self.messages if m.role != "system"]

        # Calculate system message tokens (always kept)
        system_tokens = sum(self._get_message_tokens(m) for m in system_msgs)

        # Token-based trimming
        available_tokens = self.max_context_tokens - system_tokens
        kept_messages: list[Message] = []
        current_tokens = 0

        # Keep messages from most recent, working backwards
        for msg in reversed(other_msgs):
            msg_tokens = self._get_message_tokens(msg)
            if current_tokens + msg_tokens <= available_tokens:
                kept_messages.insert(0, msg)
                current_tokens += msg_tokens
            else:
                # Stop adding messages once we exceed token limit
                break

        # Also enforce message count limit
        max_other = self.max_messages - len(system_msgs)
        if len(kept_messages) > max_other:
            kept_messages = kept_messages[-max_other:]

        # Only update if we actually trimmed
        if len(kept_messages) < len(other_msgs):
            self.messages = system_msgs + kept_messages
            # Clear token cache for removed messages
            kept_ids = {id(m) for m in self.messages}
            self._token_cache = {k: v for k, v in self._token_cache.items() if k in kept_ids}
            logger.debug(
                "Trimmed conversation: %d -> %d messages, ~%d tokens",
                len(system_msgs) + len(other_msgs),
                len(self.messages),
                system_tokens + current_tokens,
            )

    def clear(self, keep_system: bool = True) -> None:
        """
        Clear conversation history.

        Args:
            keep_system: If True, preserve the system message.
        """
        if keep_system and self._system_prompt:
            self.messages = [m for m in self.messages if m.role == "system"]
            # Keep only system message tokens in cache
            kept_ids = {id(m) for m in self.messages}
            self._token_cache = {k: v for k, v in self._token_cache.items() if k in kept_ids}
        else:
            self.messages = []
            self._token_cache = {}
        logger.debug("Cleared conversation history (keep_system=%s)", keep_system)

    def save(self, path: Path | None = None) -> None:
        """
        Save conversation to disk.

        Args:
            path: Path to save to. Uses save_path if not provided.

        Raises:
            ValueError: If no path is available.
        """
        save_to = path or self.save_path
        if not save_to:
            raise ValueError("No save path specified")

        data = {
            "messages": [m.to_dict() for m in self.messages],
            "max_messages": self.max_messages,
            "max_context_tokens": self.max_context_tokens,
            "model": self.model,
            "system_prompt": self._system_prompt,
            "saved_at": datetime.now().isoformat(),
        }

        save_to.parent.mkdir(parents=True, exist_ok=True)
        with open(save_to, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info("Saved conversation to %s", save_to)

    @classmethod
    def load(cls, path: Path) -> "Conversation":
        """
        Load a conversation from disk.

        Args:
            path: Path to load from.

        Returns:
            Loaded Conversation instance.

        Raises:
            FileNotFoundError: If the file doesn't exist.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        conv = cls(
            system_prompt=data.get("system_prompt"),
            max_messages=data.get("max_messages", DEFAULT_MAX_MESSAGES),
            max_context_tokens=data.get("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS),
            model=data.get("model", "gpt-4.1-mini"),
            save_path=path,
        )

        # Replace messages (don't duplicate system prompt)
        conv.messages = [Message.from_dict(m) for m in data.get("messages", [])]

        # Clear token cache since we replaced all messages
        conv._token_cache = {}

        logger.info("Loaded conversation from %s (%d messages)", path, len(conv.messages))
        return conv

    def __len__(self) -> int:
        """Return number of messages in conversation."""
        return len(self.messages)

    def __repr__(self) -> str:
        """String representation of conversation."""
        return f"Conversation(messages={len(self.messages)}, max={self.max_messages})"
