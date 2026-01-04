#!/usr/bin/env python3
"""
Upload fallback prompts to Langfuse.

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

# Add parent directory to path to import project modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from summarize_links.llm.prompts import load_system_prompt, load_user_prompt_template

logger = logging.getLogger(__name__)


def upload_prompts() -> None:
    """
    Upload fallback prompts to Langfuse.

    Reads system.txt and user.txt from the prompts directory and creates/updates
    them in Langfuse as "summarize-document/system" and "summarize-document/user".

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

    # Upload system prompt
    logger.info("Uploading system prompt to Langfuse...")
    try:
        langfuse.create_prompt(
            name="summarize-document/system",
            prompt=system_prompt,
            type="text",
            labels=["system", "production"],
        )
        logger.info("✓ System prompt uploaded successfully")
    except Exception as e:
        logger.error(f"Failed to upload system prompt: {e}")
        raise

    # Upload user prompt template
    logger.info("Uploading user prompt template to Langfuse...")
    try:
        langfuse.create_prompt(
            name="summarize-document/user",
            prompt=user_prompt_template,
            type="text",
            labels=["user", "template", "production"],
        )
        logger.info("✓ User prompt template uploaded successfully")
    except Exception as e:
        logger.error(f"Failed to upload user prompt template: {e}")
        raise

    # Flush any pending events
    langfuse.flush()

    logger.info("\n✓ All prompts uploaded successfully!")
    logger.info(
        "\nYou can now view and manage your prompts in the Langfuse UI "
        "(using your configured Langfuse project)."
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
