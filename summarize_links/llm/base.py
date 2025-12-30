"""
Base class for LLM clients with Langfuse prompt management.

This module provides shared functionality for fetching and compiling prompts
from Langfuse, used by both Gemini and Ollama clients.
"""

import logging
from typing import Any

__all__ = ["BaseLLMClient"]

logger = logging.getLogger(__name__)


class BaseLLMClient:
    """
    Base class for LLM clients with Langfuse prompt management.

    Provides shared functionality for:
    - Langfuse client initialization (required)
    - Fetching prompts from Langfuse with caching
    - Compiling user prompt templates with variables
    """

    def __init__(self, error_class: type[Exception]) -> None:
        """
        Initialize Langfuse prompt management.

        Args:
            error_class: Exception class to raise on Langfuse errors
                        (GeminiAPIError or OllamaAPIError).

        Raises:
            error_class: If Langfuse initialization fails.
        """
        self._prompt_cache: dict[str, Any] = {}
        self._error_class = error_class

        # Initialize Langfuse client (REQUIRED)
        try:
            from langfuse import Langfuse

            self._langfuse_client = Langfuse()
            logger.debug("Langfuse client initialized for prompt management")
        except Exception as e:
            raise error_class(f"Failed to initialize Langfuse (required): {e}") from e

    def _get_langfuse_prompts(self) -> tuple[str, str]:
        """
        Fetch prompts from Langfuse with caching.

        Returns:
            Tuple of (system_prompt_text, user_prompt_template_text).

        Raises:
            Exception: Subclass-specific error if prompts cannot be fetched.
        """
        try:
            # Check cache first
            if "system" in self._prompt_cache and "user" in self._prompt_cache:
                logger.debug("Using cached Langfuse prompts")
                system_obj = self._prompt_cache["system"]
                user_obj = self._prompt_cache["user"]
                return system_obj.prompt, user_obj.prompt

            # Fetch from Langfuse
            logger.debug("Fetching prompts from Langfuse")
            system_obj = self._langfuse_client.get_prompt("summarize-document/system")
            user_obj = self._langfuse_client.get_prompt("summarize-document/user")

            # Cache the objects (not just text, for metadata)
            self._prompt_cache["system"] = system_obj
            self._prompt_cache["user"] = user_obj

            logger.info(
                "Fetched prompts from Langfuse: system v%s, user v%s",
                getattr(system_obj, "version", "unknown"),
                getattr(user_obj, "version", "unknown"),
            )

            return system_obj.prompt, user_obj.prompt

        except Exception as e:
            raise self._error_class(f"Failed to fetch prompts from Langfuse (required): {e}") from e

    def _compile_user_prompt(self, template: str, content: str, url: str, title: str | None) -> str:
        """
        Compile user prompt template with variables.

        Supports both Langfuse templates (with {{var}}) and fallback templates.

        Args:
            template: Prompt template string.
            content: Web page content.
            url: Source URL.
            title: Page title.

        Returns:
            Compiled prompt string.
        """
        # Check if template uses Langfuse variable syntax {{var}}
        if "{{" in template and "}}" in template:
            # Langfuse template - compile with variables
            try:
                # Get the user prompt object from cache for compilation
                if "user" in self._prompt_cache:
                    user_obj = self._prompt_cache["user"]
                    compiled: str = user_obj.compile(
                        title=title or "Unknown",
                        url=url,
                        content=content,
                    )
                    return compiled
            except Exception as e:
                logger.warning(
                    f"Failed to compile Langfuse template, using simple replacement: {e}"
                )

            # Fallback: simple string replacement
            return (
                template.replace("{{title}}", title or "Unknown")
                .replace("{{url}}", url)
                .replace("{{content}}", content)
            )
        else:
            # Not a template, assume it's the old format
            return template
