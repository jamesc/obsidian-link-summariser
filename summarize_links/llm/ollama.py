"""
Ollama API client for content summarization.

This module provides a client for local Ollama models to generate
summaries of web page content in Obsidian-friendly Markdown format.
Supports structured output with suggested tags and content classification.
Uses the same interface as GeminiClient for seamless provider switching.
"""

import json
import logging

import requests

from summarize_links.exceptions import ModelNotInstalledError, OllamaAPIError, OllamaServerError
from summarize_links.llm.prompts import (
    build_user_prompt_from_template,
    load_system_prompt,
    load_user_prompt_template,
)
from summarize_links.models import SummaryResult

__all__ = [
    "OllamaClient",
]

# Module logger
logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
DEFAULT_TIMEOUT = 120  # Seconds (local models can be slower)


def _build_content_type_list() -> str:
    """
    Build the content type list for the system prompt.

    Returns:
        Formatted string listing all content types with descriptions.
    """
    from summarize_links.models import CONTENT_TYPE_DESCRIPTIONS

    lines = []
    for content_type, description in CONTENT_TYPE_DESCRIPTIONS.items():
        lines.append(f'- "{content_type}" ({description})')
    return "\n".join(lines)


# System prompt for summarization with structured output (same as Gemini)
# Cached prompts loaded from filesystem
_SYSTEM_PROMPT_CACHE: str | None = None
_USER_PROMPT_TEMPLATE_CACHE: str | None = None


def _get_system_prompt() -> str:
    """Get system prompt from cache or load from file."""
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is None:
        _SYSTEM_PROMPT_CACHE = load_system_prompt()
    return _SYSTEM_PROMPT_CACHE


def _get_user_prompt_template() -> str:
    """Get user prompt template from cache or load from file."""
    global _USER_PROMPT_TEMPLATE_CACHE
    if _USER_PROMPT_TEMPLATE_CACHE is None:
        _USER_PROMPT_TEMPLATE_CACHE = load_user_prompt_template()
    return _USER_PROMPT_TEMPLATE_CACHE


def _build_prompt(content: str, url: str, title: str | None = None) -> str:
    """
    Build the prompt for the Ollama API using template from filesystem.

    Args:
        content: Web page content to summarize.
        url: Source URL.
        title: Optional page title.

    Returns:
        Formatted prompt string with variables replaced.
    """
    template = _get_user_prompt_template()
    return build_user_prompt_from_template(template, content, url, title)


def _parse_ollama_response(response_text: str) -> SummaryResult:
    """
    Parse Ollama's JSON response into a SummaryResult.

    Handles various response formats including:
    - Clean JSON
    - JSON wrapped in markdown code blocks
    - Malformed responses (attempts extraction, falls back to plain text)

    Args:
        response_text: Raw response from Ollama API.

    Returns:
        Parsed SummaryResult object.
    """
    from summarize_links.llm.parsing import parse_llm_json_response

    # Reuse shared parsing logic
    return parse_llm_json_response(response_text)


class OllamaClient:
    """
    Client for the Ollama API.

    Handles API communication, request formatting, and response parsing.
    Implements the same interface as GeminiClient for seamless switching.
    No rate limiting needed for local models.
    """

    def __init__(
        self,
        model: str,
        endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        timeout: int = DEFAULT_TIMEOUT,
        langfuse_enabled: bool = False,
    ) -> None:
        """
        Initialize the Ollama client.

        Args:
            model: Ollama model name (e.g., "llama3:latest", "mistral").
            endpoint: Ollama server endpoint URL.
            timeout: Request timeout in seconds.
            langfuse_enabled: Whether to fetch prompts from Langfuse (requires Langfuse configured).
        """
        self._model = model
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._server_checked = False
        self._model_checked = False
        self._langfuse_enabled = langfuse_enabled
        self._langfuse_client = None
        self._prompt_cache: dict[str, object] = {}

        # Initialize Langfuse client if enabled
        if self._langfuse_enabled:
            try:
                from langfuse import Langfuse

                self._langfuse_client = Langfuse()
                logger.debug("Langfuse client initialized for prompt management")
            except Exception as e:
                logger.warning(f"Failed to initialize Langfuse for prompt management: {e}")
                self._langfuse_enabled = False

        logger.debug(
            "Initialized OllamaClient with model: %s, endpoint: %s%s",
            model,
            endpoint,
            " [Langfuse prompts enabled]" if self._langfuse_enabled else "",
        )

    def _get_langfuse_prompts(self) -> tuple[str, str] | None:
        """
        Fetch prompts from Langfuse with caching.

        Returns:
            Tuple of (system_prompt_text, user_prompt_template_text) if successful, None otherwise.
            Returns None to signal fallback to hardcoded prompts.
        """
        if not self._langfuse_enabled or not self._langfuse_client:
            return None

        try:
            # Check cache first
            if "system" in self._prompt_cache and "user" in self._prompt_cache:
                logger.debug("Using cached Langfuse prompts")
                system_obj = self._prompt_cache["system"]
                user_obj = self._prompt_cache["user"]
                return system_obj.prompt, user_obj.prompt  # type: ignore[attr-defined]

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
            logger.warning(f"Failed to fetch Langfuse prompts, using fallback: {e}")
            return None

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
                    compiled: str = user_obj.compile(  # type: ignore[attr-defined]
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
            # Not a template, assume it's the old _build_prompt format
            return template

    def _check_server(self) -> None:
        """
        Check if Ollama server is running and accessible.

        Raises:
            OllamaServerError: If server is not reachable.
        """
        if self._server_checked:
            return

        try:
            logger.debug("Checking Ollama server at %s", self._endpoint)
            response = requests.get(
                f"{self._endpoint}/api/tags",
                timeout=5,
            )
            response.raise_for_status()
            self._server_checked = True
            logger.debug("Ollama server is running")

        except requests.exceptions.ConnectionError as e:
            raise OllamaServerError(
                f"Cannot connect to Ollama server at {self._endpoint}.\n"
                "To start Ollama:\n"
                "  • Start the Ollama app, or\n"
                "  • Run: ollama serve\n\n"
                f"Details: {e}"
            ) from e

        except requests.exceptions.Timeout as e:
            raise OllamaServerError(
                f"Ollama server at {self._endpoint} timed out.\n"
                "The server may be starting up or overloaded.\n"
                f"Details: {e}"
            ) from e

        except requests.exceptions.RequestException as e:
            raise OllamaServerError(
                f"Failed to connect to Ollama server at {self._endpoint}.\nDetails: {e}"
            ) from e

    def _check_model_installed(self) -> None:
        """
        Check if the specified model is installed.

        Raises:
            ModelNotInstalledError: If model is not installed.
            OllamaServerError: If server check fails.
        """
        if self._model_checked:
            return

        # Ensure server is running first
        self._check_server()

        try:
            logger.debug("Checking if model '%s' is installed", self._model)
            response = requests.get(
                f"{self._endpoint}/api/tags",
                timeout=5,
            )
            response.raise_for_status()
            data = response.json()

            # Extract installed model names
            installed_models = []
            if "models" in data:
                installed_models = [m.get("name", "") for m in data["models"]]

            # Check if our model is in the list
            if self._model not in installed_models:
                available = ", ".join(installed_models) if installed_models else "none"
                raise ModelNotInstalledError(
                    f"Model '{self._model}' is not installed.\n"
                    f"To install: ollama pull {self._model}\n\n"
                    f"Available models: {available}"
                )

            self._model_checked = True
            logger.debug("Model '%s' is installed", self._model)

        except requests.exceptions.RequestException as e:
            raise OllamaServerError(f"Failed to check installed models: {e}") from e

    def summarize(self, content: str, url: str, title: str | None = None) -> str:
        """
        Summarize content using the Ollama API.

        Args:
            content: The text content to summarize.
            url: The source URL for attribution.
            title: Optional page title.

        Returns:
            Markdown-formatted summary.

        Raises:
            OllamaServerError: When Ollama server is not available.
            ModelNotInstalledError: When model is not installed.
            OllamaAPIError: When API returns an error.
        """
        # Check server and model availability
        self._check_server()
        self._check_model_installed()

        # Build the prompt
        prompt = _build_prompt(content, url, title)

        # Combine system prompt and user prompt
        full_prompt = f"{_get_system_prompt()}\n\n{prompt}"

        logger.debug("Sending request to Ollama API")

        try:
            response = requests.post(
                f"{self._endpoint}/api/generate",
                json={
                    "model": self._model,
                    "prompt": full_prompt,
                    "stream": False,
                    "format": "json",  # Request JSON output
                },
                timeout=self._timeout,
            )
            response.raise_for_status()

            data = response.json()
            summary: str = data.get("response", "")

            if not summary:
                raise OllamaAPIError("Empty response from Ollama API")

            # Extract token usage if available
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)
            total_tokens = prompt_tokens + completion_tokens

            logger.info(
                "Successfully generated summary (%d chars, tokens: input=%d output=%d total=%d)",
                len(summary),
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
            return summary

        except requests.exceptions.Timeout as e:
            raise OllamaAPIError(
                f"Request timed out after {self._timeout}s. "
                "Local models can be slow; consider increasing timeout."
            ) from e

        except requests.exceptions.RequestException as e:
            raise OllamaAPIError(f"Ollama API error: {e}") from e

        except (KeyError, json.JSONDecodeError) as e:
            raise OllamaAPIError(f"Failed to parse Ollama response: {e}") from e

    def summarize_with_metadata(
        self, content: str, url: str, title: str | None = None
    ) -> SummaryResult:
        """
        Summarize content and return structured result with tags.

        This method requests JSON output from Ollama including:
        - A markdown-formatted summary
        - Suggested topic tags
        - Content type classification
        - Token usage statistics

        Args:
            content: The text content to summarize.
            url: The source URL for attribution.
            title: Optional page title.

        Returns:
            SummaryResult with content, suggested tags, content type, and usage details.

        Raises:
            OllamaServerError: When Ollama server is not available.
            ModelNotInstalledError: When model is not installed.
            OllamaAPIError: When API returns an error.
        """
        # Check server and model availability
        self._check_server()
        self._check_model_installed()

        # Try to fetch prompts from Langfuse first, fallback to filesystem
        system_prompt = _get_system_prompt()
        user_prompt_template = None
        prompt_metadata = None
        using_langfuse = False

        langfuse_prompts = self._get_langfuse_prompts()
        if langfuse_prompts:
            langfuse_system, langfuse_user = langfuse_prompts
            system_prompt = langfuse_system
            user_prompt_template = langfuse_user
            using_langfuse = True

            # Build prompt_metadata from cached prompt objects
            if "system" in self._prompt_cache and "user" in self._prompt_cache:
                sys_obj = self._prompt_cache["system"]
                user_obj = self._prompt_cache["user"]
                prompt_metadata = {
                    "system_prompt_name": "summarize-document/system",
                    "system_prompt_version": getattr(sys_obj, "version", None),
                    "user_prompt_name": "summarize-document/user",
                    "user_prompt_version": getattr(user_obj, "version", None),
                    "source": "langfuse",
                }
                logger.debug(
                    "Using Langfuse prompts: system v%s, user v%s",
                    prompt_metadata["system_prompt_version"],
                    prompt_metadata["user_prompt_version"],
                )
        else:
            logger.debug("Using hardcoded fallback prompts")

        # Build the user prompt (with or without Langfuse template)
        if using_langfuse and user_prompt_template:
            prompt = self._compile_user_prompt(user_prompt_template, content, url, title)
        else:
            prompt = _build_prompt(content, url, title)

        full_prompt = f"{system_prompt}\n\n{prompt}"

        logger.debug("Sending request to Ollama API for metadata")

        try:
            response = requests.post(
                f"{self._endpoint}/api/generate",
                json={
                    "model": self._model,
                    "prompt": full_prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()

            data = response.json()
            raw_response: str = data.get("response", "")

            if not raw_response:
                raise OllamaAPIError("Empty response from Ollama API")

            # Extract token usage
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)
            total_tokens = prompt_tokens + completion_tokens

            usage_details = None
            if prompt_tokens > 0 or completion_tokens > 0:
                usage_details = {
                    "input": prompt_tokens,
                    "output": completion_tokens,
                    "total": total_tokens,
                }
                logger.debug(
                    "Token usage: input=%d, output=%d, total=%d",
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                )

            # Parse the JSON response into SummaryResult
            result = _parse_ollama_response(raw_response)
            # Add usage details to result
            result.usage_details = usage_details

            # Store system prompt, user prompt (combined), and response for tracing
            result.system_prompt = system_prompt  # Use Langfuse or fallback
            result.raw_prompt = prompt  # Store user prompt separately
            result.raw_response = raw_response
            result.prompt_metadata = prompt_metadata  # Store Langfuse prompt metadata

            logger.info(
                "Successfully generated summary with metadata (%d chars, %d tags)",
                len(result.content),
                len(result.suggested_tags),
            )

        except requests.exceptions.Timeout as e:
            raise OllamaAPIError(
                f"Request timed out after {self._timeout}s. "
                "Local models can be slow; consider increasing timeout."
            ) from e

        except requests.exceptions.RequestException as e:
            raise OllamaAPIError(f"Ollama API error: {e}") from e

        except (KeyError, json.JSONDecodeError) as e:
            raise OllamaAPIError(f"Failed to parse Ollama response: {e}") from e

        return result
