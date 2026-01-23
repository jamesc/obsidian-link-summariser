"""
Chat-driven CLI module for conversational interaction with the summarizer.

This package provides an interactive chat interface for:
- Natural language URL summarization
- Vault search and discovery
- Multi-turn conversations with context
- Token-based context management
- Streaming responses
- Session persistence

Main components:
- engine: Chat orchestration and LLM integration
- conversation: Message history management
- formatter: Rich output formatting
- tools: Function calling tools for vault operations
- tokens: Token counting utilities
"""

from summarize_links.chat.conversation import Conversation, Message
from summarize_links.chat.engine import ChatEngine
from summarize_links.chat.tokens import (
    count_message_tokens,
    count_messages_tokens,
    count_tokens,
)

__all__ = [
    "ChatEngine",
    "Conversation",
    "Message",
    "count_tokens",
    "count_message_tokens",
    "count_messages_tokens",
]
