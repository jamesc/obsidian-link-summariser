"""
System prompts for the chat CLI.

This module loads prompt templates from Langfuse and formats them
with vault context.
"""

import logging
from datetime import datetime
from typing import Any

from summarize_links.config import Config

logger = logging.getLogger(__name__)

__all__ = [
    "build_system_prompt",
]


def build_system_prompt(config: Config) -> tuple[str, Any | None]:
    """
    Build the system prompt with vault context.

    Loads the chat assistant system prompt from Langfuse and formats it
    with current date and vault configuration.

    Args:
        config: Application configuration.

    Returns:
        Tuple of (formatted_prompt_string, prompt_object).
        The prompt_object can be linked to Langfuse generations for tracing.

    Raises:
        RuntimeError: If Langfuse prompt cannot be fetched.
    """
    try:
        # Initialize Langfuse client (required for prompt management)
        from langfuse import Langfuse

        langfuse_client = Langfuse()

        # Fetch chat assistant system prompt
        logger.debug("Fetching chat system prompt from Langfuse: chat-assistant/system")
        prompt_obj = langfuse_client.get_prompt("chat-assistant/system", type="text")

        logger.info(
            "Fetched chat system prompt from Langfuse v%s",
            getattr(prompt_obj, "version", "unknown"),
        )

        # Get the template and compile with variables
        now = datetime.now()

        # Compile the prompt with vault context
        formatted_prompt: str = prompt_obj.compile(
            current_date=now.strftime("%Y-%m-%d"),
            current_weekday=now.strftime("%A"),
            vault_path=str(config.vault_path) if config.vault_path else "Not set",
            out_folder=config.out_folder,
            model=config.chat_model,
            provider=config.model_provider,
        )

        return formatted_prompt, prompt_obj

    except Exception as e:
        raise RuntimeError(
            f"Failed to fetch chat system prompt from Langfuse (required): {e}"
        ) from e
