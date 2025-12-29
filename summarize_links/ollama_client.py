"""
Ollama API client for content summarization.

This module provides a client for local Ollama models to generate
summaries of web page content in Obsidian-friendly Markdown format.
Supports structured output with suggested tags and content classification.
Uses the same interface as GeminiClient for seamless provider switching.
"""

import json
import logging
from typing import Any

import requests

from summarize_links.exceptions import ModelNotInstalledError, OllamaAPIError, OllamaServerError
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
SUMMARY_SYSTEM_PROMPT = f"""You are a summarization assistant. Your task is to create
concise, informative summaries of web page content for a personal knowledge base.

Guidelines for the summary:
- Write in clear, direct prose
- Use Markdown formatting (headers, bullet points, bold/italic as appropriate)
- Focus on the main ideas and key takeaways
- Omit advertisements, navigation, and boilerplate content
- Keep summaries focused and scannable
- Include relevant quotes if they capture key insights
- Use a neutral, informative tone

You MUST respond with valid JSON in this exact format:
{{
  "summary": "Your markdown-formatted summary here",
  "suggested_tags": ["tag1", "tag2", "tag3"],
  "content_type": "article"
}}

For suggested_tags:
- Provide 3-5 relevant topic tags
- Use lowercase, hyphenated format (e.g., "machine-learning", "web-development")
- Focus on the main topics and technologies discussed
- Avoid generic tags like "article" or "blog"

For content_type, choose ONE of:
{_build_content_type_list()}"""


def _build_prompt(content: str, url: str, title: str | None = None) -> str:
    """
    Build the prompt for the Ollama API.

    Args:
        content: Web page content to summarize.
        url: Source URL.
        title: Optional page title.

    Returns:
        Formatted prompt string.
    """
    title_part = f" titled '{title}'" if title else ""
    return f"""Summarize the following web page content{title_part}.

Source URL: {url}

Content:
{content}

Remember to respond with valid JSON containing "summary", "suggested_tags", and "content_type"."""


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
    from summarize_links.gemini_client import _parse_gemini_response

    # Reuse Gemini's robust parsing logic
    return _parse_gemini_response(response_text)


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
    ) -> None:
        """
        Initialize the Ollama client.

        Args:
            model: Ollama model name (e.g., "llama3:latest", "mistral").
            endpoint: Ollama server endpoint URL.
            timeout: Request timeout in seconds.
        """
        self._model = model
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout
        self._server_checked = False
        self._model_checked = False

        logger.debug(
            "Initialized OllamaClient with model: %s, endpoint: %s",
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
                f"Failed to connect to Ollama server at {self._endpoint}.\n"
                f"Details: {e}"
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
                raise ModelNotInstalledError(
                    f"Model '{self._model}' is not installed.\n"
                    f"To install: ollama pull {self._model}\n\n"
                    f"Available models: {', '.join(installed_models) if installed_models else 'none'}"
                )

            self._model_checked = True
            logger.debug("Model '%s' is installed", self._model)

        except requests.exceptions.RequestException as e:
            if not isinstance(e, requests.exceptions.HTTPError):
                raise OllamaServerError(f"Failed to check installed models: {e}") from e
            raise

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
        full_prompt = f"{SUMMARY_SYSTEM_PROMPT}\n\n{prompt}"

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
            summary = data.get("response", "")

            if not summary:
                raise OllamaAPIError("Empty response from Ollama API")

            logger.info("Successfully generated summary (%d chars)", len(summary))
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

        Args:
            content: The text content to summarize.
            url: The source URL for attribution.
            title: Optional page title.

        Returns:
            SummaryResult with content, suggested tags, and content type.

        Raises:
            OllamaServerError: When Ollama server is not available.
            ModelNotInstalledError: When model is not installed.
            OllamaAPIError: When API returns an error.
        """
        # Get the raw response (which should be JSON)
        raw_response = self.summarize(content, url, title)

        # Parse the JSON response into SummaryResult
        return _parse_ollama_response(raw_response)
