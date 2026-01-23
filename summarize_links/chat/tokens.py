"""
Token counting utilities for chat context management.

This module provides token counting for OpenAI/Azure OpenAI models
using tiktoken to accurately manage context window limits.
"""

import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import tiktoken

if TYPE_CHECKING:
    from summarize_links.chat.conversation import Message

__all__ = [
    "count_tokens",
    "count_message_tokens",
    "count_messages_tokens",
    "get_encoding_for_model",
    "estimate_tool_tokens",
]

logger = logging.getLogger(__name__)

# Model to encoding mapping for Azure OpenAI models
# Most GPT-4 variants use cl100k_base encoding
MODEL_ENCODINGS: dict[str, str] = {
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4.1": "o200k_base",
    "gpt-4.1-mini": "o200k_base",
    "gpt-41-mini": "o200k_base",
    "gpt4.1-mini": "o200k_base",
    "gpt-35-turbo": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
}

# Default encoding for unknown models
DEFAULT_ENCODING = "cl100k_base"

# Token overhead per message (role, separators, etc.)
# See: https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb
TOKENS_PER_MESSAGE = 4  # every message follows <|im_start|>{role}\n{content}<|im_end|>\n
TOKENS_PER_NAME = -1  # if there's a name, the role is omitted
TOKENS_REPLY_OVERHEAD = 3  # every reply is primed with <|im_start|>assistant


@lru_cache(maxsize=8)
def get_encoding_for_model(model: str) -> tiktoken.Encoding:
    """
    Get the tiktoken encoding for a specific model.

    Uses caching to avoid repeated encoding lookups.

    Args:
        model: Model name (e.g., "gpt-4.1-mini").

    Returns:
        tiktoken Encoding instance.
    """
    # Normalize model name (remove common prefixes/suffixes)
    model_lower = model.lower().replace("-", "").replace(".", "")

    # Try direct model lookup first
    encoding_name = MODEL_ENCODINGS.get(model)

    # Try normalized lookup
    if not encoding_name:
        for known_model, enc in MODEL_ENCODINGS.items():
            if known_model.lower().replace("-", "").replace(".", "") == model_lower:
                encoding_name = enc
                break

    # Fall back to default encoding
    if not encoding_name:
        logger.debug("Unknown model '%s', using default encoding %s", model, DEFAULT_ENCODING)
        encoding_name = DEFAULT_ENCODING

    try:
        return tiktoken.get_encoding(encoding_name)
    except Exception:
        logger.warning("Failed to get encoding %s, using cl100k_base", encoding_name)
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, model: str = "gpt-4.1-mini") -> int:
    """
    Count the number of tokens in a text string.

    Args:
        text: Text to count tokens for.
        model: Model name for encoding selection.

    Returns:
        Number of tokens.
    """
    if not text:
        return 0

    encoding = get_encoding_for_model(model)
    return len(encoding.encode(text))


def count_message_tokens(message: "Message", model: str = "gpt-4.1-mini") -> int:
    """
    Count tokens for a single conversation message.

    Accounts for the message structure overhead (role, separators).

    Args:
        message: Conversation Message object.
        model: Model name for encoding selection.

    Returns:
        Total tokens including overhead.
    """
    encoding = get_encoding_for_model(model)
    tokens = TOKENS_PER_MESSAGE  # Already includes role/separator overhead

    # Content
    if message.content:
        tokens += len(encoding.encode(message.content))

    # Name (if present) - replaces role in token count
    if message.name:
        tokens += len(encoding.encode(message.name))
        tokens += TOKENS_PER_NAME

    # Tool calls (estimate)
    if message.tool_calls:
        for tc in message.tool_calls:
            # Function name
            if "name" in tc:
                tokens += len(encoding.encode(tc["name"]))
            # Arguments (as JSON string)
            if "arguments" in tc:
                import json

                args_str = (
                    json.dumps(tc["arguments"])
                    if isinstance(tc["arguments"], dict)
                    else str(tc["arguments"])
                )
                tokens += len(encoding.encode(args_str))

    return tokens


def count_messages_tokens(
    messages: list["Message"],
    model: str = "gpt-4.1-mini",
) -> int:
    """
    Count total tokens for a list of messages.

    Includes overhead for the reply priming.

    Args:
        messages: List of Message objects.
        model: Model name for encoding selection.

    Returns:
        Total token count including all overhead.
    """
    total = 0
    for msg in messages:
        total += count_message_tokens(msg, model)

    # Add reply overhead
    total += TOKENS_REPLY_OVERHEAD

    return total


def estimate_tool_tokens(tools: list[dict[str, Any]]) -> int:
    """
    Estimate tokens used by tool definitions.

    This is a rough estimate as the exact tokenization depends
    on how the API formats the tools.

    Args:
        tools: List of tool schema dictionaries.

    Returns:
        Estimated token count.
    """
    if not tools:
        return 0

    import json

    # Serialize tools to JSON for token counting
    tools_json = json.dumps(tools, separators=(",", ":"))
    encoding = tiktoken.get_encoding("cl100k_base")

    # Add some overhead for formatting
    return len(encoding.encode(tools_json)) + (len(tools) * 10)
