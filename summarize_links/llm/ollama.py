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
from summarize_links.llm.base import BaseLLMClient
from summarize_links.models import SummaryResult

__all__ = [
    "OllamaClient",
]

# Module logger
logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
DEFAULT_TIMEOUT = 120  # Seconds (local models can be slower)


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


class OllamaClient(BaseLLMClient):
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
    ) -> None:
        """
        Initialize the Ollama client.

        Args:
            model: Ollama model name (e.g., "llama3:latest", "mistral").
            endpoint: Ollama server endpoint URL.
            timeout: Request timeout in seconds.
        """
        # Initialize base class with Langfuse support
        super().__init__(error_class=OllamaAPIError)

        self._model = model
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._server_checked = False
        self._model_checked = False

        logger.debug(
            "Initialized OllamaClient with model: %s, endpoint: %s [Langfuse prompts required]",
            model,
            endpoint,
        )

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

        # Get prompts from Langfuse
        system_prompt, user_prompt_template = self._get_langfuse_prompts()
        prompt = self._compile_user_prompt(user_prompt_template, content, url, title)

        # Combine system prompt and user prompt
        full_prompt = f"{system_prompt}\n\n{prompt}"

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

        # Fetch prompts from Langfuse (REQUIRED)
        system_prompt, user_prompt_template = self._get_langfuse_prompts()

        # Build prompt_metadata from cached prompt objects
        prompt_metadata = None
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

        # Build the user prompt using Langfuse template
        prompt = self._compile_user_prompt(user_prompt_template, content, url, title)
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
