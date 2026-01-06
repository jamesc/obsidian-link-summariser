"""Prompt loading utilities for management scripts.

NOTE: This module is used by scripts/upload_prompts.py to load prompts
from the filesystem for uploading to Langfuse. It is NOT used during
normal CLI operation - LLM clients fetch prompts directly from Langfuse.

Reads prompt files from summarize_links/prompts/ directory.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to prompts directory (relative to scripts/ location)
PROMPTS_DIR = Path(__file__).parent.parent / "summarize_links" / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.txt"
USER_PROMPT_PATH = PROMPTS_DIR / "user.txt"


def load_system_prompt() -> str:
    """
    Load system prompt from filesystem.

    Returns:
        System prompt text.

    Raises:
        FileNotFoundError: If prompt file is missing.
    """
    try:
        prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        logger.debug(f"Loaded system prompt from {SYSTEM_PROMPT_PATH}")
        return prompt
    except FileNotFoundError:
        logger.error(f"System prompt file not found: {SYSTEM_PROMPT_PATH}")
        raise


def load_user_prompt_template() -> str:
    """
    Load user prompt template from filesystem.

    Template contains variables: {{title}}, {{url}}, {{content}}

    Returns:
        User prompt template text.

    Raises:
        FileNotFoundError: If prompt file is missing.
    """
    try:
        template = USER_PROMPT_PATH.read_text(encoding="utf-8")
        logger.debug(f"Loaded user prompt template from {USER_PROMPT_PATH}")
        return template
    except FileNotFoundError:
        logger.error(f"User prompt template file not found: {USER_PROMPT_PATH}")
        raise


def build_user_prompt_from_template(
    template: str, content: str, url: str, title: str | None = None
) -> str:
    """
    Build user prompt from template by replacing variables.

    Args:
        template: Prompt template with {{variables}}.
        content: Web page content.
        url: Source URL.
        title: Optional page title.

    Returns:
        Compiled prompt with variables replaced.
    """
    # Handle inline title format: "{{title}}" becomes " titled 'X'" or empty
    title_text = f" titled '{title}'" if title else ""

    return (
        template.replace("{{title}}", title_text)
        .replace("{{url}}", url)
        .replace("{{content}}", content)
    )
