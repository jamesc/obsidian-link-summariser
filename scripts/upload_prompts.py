#!/usr/bin/env python3
"""
Upload prompts to Langfuse.

This script reads the system and user prompts from the filesystem
and creates/updates them in Langfuse for centralized prompt management.

Usage:
    uv run python scripts/upload_prompts.py

Environment Variables (from .env file or environment):
    LANGFUSE_PUBLIC_KEY: Langfuse API public key
    LANGFUSE_SECRET_KEY: Langfuse API secret key
    LANGFUSE_BASE_URL: Langfuse API host (optional, defaults to cloud)
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Path to prompts directory (relative to scripts/ location)
PROMPTS_DIR = Path(__file__).parent.parent / "summarize_links" / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.txt"
USER_PROMPT_PATH = PROMPTS_DIR / "user.txt"
CHAT_SYSTEM_PROMPT_PATH = PROMPTS_DIR / "chat-system.txt"


def load_system_prompt() -> str:
    """Load system prompt from filesystem."""
    try:
        prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        logger.debug(f"Loaded system prompt from {SYSTEM_PROMPT_PATH}")
        return prompt
    except FileNotFoundError:
        logger.error(f"System prompt file not found: {SYSTEM_PROMPT_PATH}")
        raise


def load_user_prompt_template() -> str:
    """Load user prompt template from filesystem."""
    try:
        template = USER_PROMPT_PATH.read_text(encoding="utf-8")
        logger.debug(f"Loaded user prompt template from {USER_PROMPT_PATH}")
        return template
    except FileNotFoundError:
        logger.error(f"User prompt template file not found: {USER_PROMPT_PATH}")
        raise


def load_chat_system_prompt() -> str:
    """Load chat system prompt from filesystem."""
    try:
        prompt = CHAT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        logger.debug(f"Loaded chat system prompt from {CHAT_SYSTEM_PROMPT_PATH}")
        return prompt
    except FileNotFoundError:
        logger.error(f"Chat system prompt file not found: {CHAT_SYSTEM_PROMPT_PATH}")
        raise


def upload_prompts() -> None:
    """
    Upload prompts to Langfuse.

    Creates composable prompt structures:

    For summarization:
    1. "summarize-document/system" (text prompt) - system instructions
    2. "summarize-document/user" (text prompt) - user template with variables
    3. "summarize-document" (chat prompt) - references the above prompts

    For chat assistant:
    1. "chat-assistant/system" (text prompt) - chat system instructions with variables

    This allows independent versioning of prompts while maintaining
    composable structures.

    Raises:
        ValueError: If Langfuse credentials are not configured.
        Exception: If prompt upload fails.
    """
    # Load environment variables from .env file
    load_dotenv()

    # Check Langfuse credentials directly from environment
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    base_url = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        raise ValueError(
            "Langfuse is not configured. Please set LANGFUSE_PUBLIC_KEY and "
            "LANGFUSE_SECRET_KEY environment variables."
        )

    try:
        from langfuse import Langfuse
    except ImportError as e:
        raise ImportError(
            "langfuse package not installed. Install with: uv pip install langfuse"
        ) from e

    # Initialize Langfuse client
    langfuse = Langfuse(public_key=public_key, secret_key=secret_key, host=base_url)

    # Load prompts from filesystem
    logger.info("Loading prompts from filesystem...")
    system_prompt = load_system_prompt()
    user_prompt_template = load_user_prompt_template()
    chat_system_prompt = load_chat_system_prompt()

    # Upload individual component prompts
    logger.info("Uploading component prompts to Langfuse...")

    # Upload system prompt
    try:
        langfuse.create_prompt(
            name="summarize-document/system",
            prompt=system_prompt,
            type="text",
            labels=["production", "component"],
        )
        logger.info("✓ System prompt 'summarize-document/system' uploaded")
    except Exception as e:
        logger.error(f"Failed to upload system prompt: {e}")
        raise

    # Upload user prompt template
    try:
        langfuse.create_prompt(
            name="summarize-document/user",
            prompt=user_prompt_template,
            type="text",
            labels=["production", "component"],
        )
        logger.info("✓ User prompt 'summarize-document/user' uploaded")
    except Exception as e:
        logger.error(f"Failed to upload user prompt template: {e}")
        raise

    # Upload composed chat prompt that references the components
    logger.info("Uploading composed chat prompt to Langfuse...")
    try:
        langfuse.create_prompt(
            name="summarize-document",
            prompt=[
                {
                    "role": "system",
                    "content": (
                        "@@@langfusePrompt:name=summarize-document/system|label=production@@@"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "@@@langfusePrompt:name=summarize-document/user|label=production@@@"
                    ),
                },
            ],
            type="chat",
            labels=["production"],
        )
        logger.info("✓ Composed chat prompt 'summarize-document' uploaded")
    except Exception as e:
        logger.error(f"Failed to upload composed chat prompt: {e}")
        raise

    # Upload chat assistant system prompt
    logger.info("Uploading chat assistant prompt to Langfuse...")
    try:
        langfuse.create_prompt(
            name="chat-assistant/system",
            prompt=chat_system_prompt,
            type="text",
            labels=["production"],
        )
        logger.info("✓ Chat system prompt 'chat-assistant/system' uploaded")
    except Exception as e:
        logger.error(f"Failed to upload chat system prompt: {e}")
        raise

    # Flush any pending events
    langfuse.flush()

    logger.info("\n✓ All prompts uploaded successfully!")
    logger.info(
        "\nStructure:\n"
        "  - summarize-document/system (text, component)\n"
        "  - summarize-document/user (text, component)\n"
        "  - summarize-document (chat, references components)\n"
        "  - chat-assistant/system (text, standalone with variables)\n"
        "\nYou can now view and manage your prompts in the Langfuse UI."
    )


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    try:
        upload_prompts()
    except Exception as e:
        logger.error(f"\n✗ Failed to upload prompts: {e}")
        sys.exit(1)
