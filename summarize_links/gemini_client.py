"""
Gemini API client for content summarization.

This module provides a client for the Google Gemini API to generate
summaries of web page content in Obsidian-friendly Markdown format.
Supports structured output with suggested tags and content classification.
"""

import json
import logging
import re
import time
from typing import Any, Protocol

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from summarize_links.config import DEFAULT_MODEL
from summarize_links.exceptions import GeminiAPIError, RateLimitError
from summarize_links.models import CONTENT_TYPES, SummaryResult

# Module logger
logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 30.0  # seconds

# System prompt for summarization with structured output
SUMMARY_SYSTEM_PROMPT = """You are a summarization assistant. Your task is to create
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
{
  "summary": "Your markdown-formatted summary here",
  "suggested_tags": ["tag1", "tag2", "tag3"],
  "content_type": "article"
}

For suggested_tags:
- Provide 3-5 relevant topic tags
- Use lowercase, hyphenated format (e.g., "machine-learning", "web-development")
- Focus on the main topics and technologies discussed
- Avoid generic tags like "article" or "blog"

For content_type, choose ONE of:
- "article" (news, opinion, analysis)
- "tutorial" (how-to, guide, walkthrough)
- "documentation" (API docs, reference material)
- "research" (academic papers, studies)
- "blog" (personal posts, informal writing)
- "news" (current events, announcements)
- "video" (video content transcripts)
- "tool" (software, service, product pages)
- "reference" (lists, comparisons, resources)
- "other" (if none of the above fit)"""


class SummarizerProtocol(Protocol):
    """Protocol defining the interface for content summarizers."""

    def summarize(self, content: str, url: str, title: str | None = None) -> str:
        """
        Summarize content from a web page (legacy interface).

        Args:
            content: The text content to summarize.
            url: The source URL for attribution.
            title: Optional page title.

        Returns:
            Markdown-formatted summary.
        """
        ...

    def summarize_with_metadata(
        self, content: str, url: str, title: str | None = None
    ) -> SummaryResult:
        """
        Summarize content and return structured result with tags.

        Args:
            content: The text content to summarize.
            url: The source URL for attribution.
            title: Optional page title.

        Returns:
            SummaryResult with content, suggested tags, and content type.
        """
        ...


def _build_prompt(content: str, url: str, title: str | None = None) -> str:
    """
    Build the prompt for the Gemini API.

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


def _parse_gemini_response(response_text: str) -> SummaryResult:
    """
    Parse Gemini's JSON response into a SummaryResult.

    Handles various response formats including:
    - Clean JSON
    - JSON wrapped in markdown code blocks
    - Malformed responses (falls back to plain text)

    Args:
        response_text: Raw response from Gemini API.

    Returns:
        Parsed SummaryResult object.
    """
    text = response_text.strip()

    # Try to extract JSON from markdown code block
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    # Try to find JSON object in the response
    json_object_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if json_object_match:
        text = json_object_match.group(0)

    try:
        data = json.loads(text)

        # Extract and validate fields
        summary = data.get("summary", "")
        if not summary:
            # If no summary field, use the whole response as summary
            logger.warning("No 'summary' field in response, using raw text")
            summary = response_text

        suggested_tags = data.get("suggested_tags", [])
        if not isinstance(suggested_tags, list):
            suggested_tags = []

        content_type = data.get("content_type", "article")
        if content_type not in CONTENT_TYPES:
            logger.debug(f"Unknown content_type '{content_type}', defaulting to 'article'")
            content_type = "article"

        return SummaryResult(
            content=summary,
            suggested_tags=suggested_tags,
            content_type=content_type,
        )

    except json.JSONDecodeError as e:
        # Fallback: treat the whole response as the summary
        logger.warning(f"Failed to parse JSON response: {e}. Using raw text as summary.")
        return SummaryResult(
            content=response_text,
            suggested_tags=[],
            content_type="article",
        )


class GeminiClient:
    """
    Client for the Google Gemini API.

    Handles API authentication, request formatting, and response parsing
    with automatic retry logic for rate limits and transient errors.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        """
        Initialize the Gemini client.

        Args:
            api_key: Google AI Studio API key.
            model: Gemini model name to use.
        """
        self._api_key = api_key
        self._model_name = model
        self._model: Any = None
        logger.debug("Initialized GeminiClient with model: %s", model)

    def _get_model(self) -> Any:
        """
        Get or create the generative model instance.

        Returns:
            Configured GenerativeModel instance.
        """
        if self._model is None:
            genai.configure(api_key=self._api_key)  # type: ignore[attr-defined]
            self._model = genai.GenerativeModel(  # type: ignore[attr-defined]
                model_name=self._model_name,
                system_instruction=SUMMARY_SYSTEM_PROMPT,
            )
            logger.debug("Created GenerativeModel instance")
        return self._model

    def summarize(self, content: str, url: str, title: str | None = None) -> str:
        """
        Summarize content using the Gemini API.

        Args:
            content: The text content to summarize.
            url: The source URL for attribution.
            title: Optional page title.

        Returns:
            Markdown-formatted summary.

        Raises:
            RateLimitError: When rate limited after all retries exhausted.
            GeminiAPIError: When API returns an error.
        """
        prompt = _build_prompt(content, url, title)
        model = self._get_model()

        retry_delay = INITIAL_RETRY_DELAY
        last_exception: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(
                    "Sending request to Gemini API (attempt %d/%d)",
                    attempt + 1,
                    MAX_RETRIES,
                )
                response = model.generate_content(prompt)

                # Check for blocked content
                if not response.parts:
                    logger.warning("Gemini response has no parts - content may be blocked")
                    raise GeminiAPIError("Response blocked or empty")

                summary: str = response.text
                logger.info("Successfully generated summary (%d chars)", len(summary))
                return summary

            except google_exceptions.ResourceExhausted as e:
                # Rate limit - retry with backoff
                last_exception = e
                logger.warning(
                    "Rate limited (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    retry_delay,
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)

            except google_exceptions.InvalidArgument as e:
                # Bad request - don't retry
                logger.error("Invalid request to Gemini API: %s", e)
                raise GeminiAPIError(f"Invalid request: {e}") from e

            except google_exceptions.PermissionDenied as e:
                # Auth error - don't retry
                logger.error("Permission denied for Gemini API: %s", e)
                raise GeminiAPIError(f"Permission denied: {e}") from e

            except google_exceptions.GoogleAPICallError as e:
                # Other API errors - retry for transient ones
                last_exception = e
                logger.warning(
                    "API error (attempt %d/%d): %s",
                    attempt + 1,
                    MAX_RETRIES,
                    e,
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)

        # All retries exhausted
        logger.error("All retries exhausted for Gemini API call")
        if isinstance(last_exception, google_exceptions.ResourceExhausted):
            raise RateLimitError("Rate limit exceeded after retries") from last_exception
        raise GeminiAPIError(f"API error after retries: {last_exception}") from last_exception

    def summarize_with_metadata(
        self, content: str, url: str, title: str | None = None
    ) -> SummaryResult:
        """
        Summarize content and return structured result with tags.

        This method requests JSON output from Gemini including:
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
            RateLimitError: When rate limited after all retries exhausted.
            GeminiAPIError: When API returns an error.
        """
        # Get the raw response (which should be JSON)
        raw_response = self.summarize(content, url, title)

        # Parse the JSON response into SummaryResult
        return _parse_gemini_response(raw_response)


class MockGeminiClient:
    """
    Mock client for testing without making real API calls.

    Returns predictable summaries for testing the full pipeline.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        responses: dict[str, str] | None = None,
        fail_urls: set[str] | None = None,
    ) -> None:
        """
        Initialize the mock client.

        Args:
            api_key: Ignored, for interface compatibility.
            model: Ignored, for interface compatibility.
            responses: Optional mapping of URLs to custom responses.
            fail_urls: Optional set of URLs that should raise errors.
        """
        self._responses = responses or {}
        self._fail_urls = fail_urls or set()
        self._call_count = 0
        logger.debug("Initialized MockGeminiClient")

    @property
    def call_count(self) -> int:
        """Number of times summarize was called."""
        return self._call_count

    def summarize(self, content: str, url: str, title: str | None = None) -> str:
        """
        Return a mock summary.

        Args:
            content: Content (used for generating mock response).
            url: URL (used for custom responses or errors).
            title: Optional title.

        Returns:
            Mock summary text.

        Raises:
            GeminiAPIError: If URL is in fail_urls set.
        """
        self._call_count += 1

        if url in self._fail_urls:
            logger.debug("MockGeminiClient: Simulating failure for %s", url)
            raise GeminiAPIError(f"Simulated API error for {url}")

        if url in self._responses:
            logger.debug("MockGeminiClient: Using custom response for %s", url)
            return self._responses[url]

        # Generate a predictable mock summary
        title_text = title or "Untitled Page"
        content_preview = content[:200].replace("\n", " ")
        if len(content) > 200:
            content_preview += "..."

        mock_summary = f"""# Summary: {title_text}

## Overview

This is a mock summary generated for testing purposes.

## Key Points

- Source: {url}
- Content length: {len(content)} characters
- Content preview: {content_preview}

## Conclusion

This summary was generated by MockGeminiClient for testing the summarization pipeline.
"""
        logger.debug("MockGeminiClient: Generated mock summary for %s", url)
        return mock_summary

    def summarize_with_metadata(
        self, content: str, url: str, title: str | None = None
    ) -> SummaryResult:
        """
        Return a mock summary with metadata.

        Args:
            content: Content (used for generating mock response).
            url: URL (used for custom responses or errors).
            title: Optional title.

        Returns:
            Mock SummaryResult with summary, tags, and content type.

        Raises:
            GeminiAPIError: If URL is in fail_urls set.
        """
        # Get the summary content (handles fail_urls and custom responses)
        summary_text = self.summarize(content, url, title)

        # Generate predictable mock tags based on URL
        mock_tags = ["mock-tag", "testing"]

        # Infer content type from URL patterns
        content_type = "article"
        url_lower = url.lower()
        if "tutorial" in url_lower or "how-to" in url_lower:
            content_type = "tutorial"
        elif "docs" in url_lower or "documentation" in url_lower:
            content_type = "documentation"
        elif "blog" in url_lower:
            content_type = "blog"
        elif "news" in url_lower:
            content_type = "news"
        elif "video" in url_lower or "youtube" in url_lower:
            content_type = "video"

        return SummaryResult(
            content=summary_text,
            suggested_tags=mock_tags,
            content_type=content_type,
        )


def create_client(
    api_key: str | None,
    model: str = DEFAULT_MODEL,
    mock_mode: bool = False,
) -> GeminiClient | MockGeminiClient:
    """
    Factory function to create appropriate client based on mode.

    Args:
        api_key: API key for real client, can be None in mock mode.
        model: Model name to use.
        mock_mode: If True, return MockGeminiClient.

    Returns:
        Configured client instance.

    Raises:
        GeminiAPIError: If api_key is missing in non-mock mode.
    """
    if mock_mode:
        logger.info("Creating MockGeminiClient (mock mode enabled)")
        return MockGeminiClient(api_key=api_key, model=model)

    if not api_key:
        raise GeminiAPIError("API key required for non-mock mode")

    logger.info("Creating GeminiClient with model: %s", model)
    return GeminiClient(api_key=api_key, model=model)
