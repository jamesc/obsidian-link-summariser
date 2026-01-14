"""
Gemini API client for content summarization.

This module provides a client for the Google Gemini API to generate
summaries of web page content in Obsidian-friendly Markdown format.
Supports structured output with suggested tags and content classification.
Includes rate limiting to stay within Gemini API quotas.
"""

import logging
import re
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import errors, types

from summarize_links.config import DEFAULT_MODEL
from summarize_links.exceptions import GeminiAPIError, RateLimitError
from summarize_links.llm.base import (
    BASE_RETRY_DELAY,
    MAX_RETRIES,
    MAX_RETRY_DELAY,
    BaseLLMClient,
)
from summarize_links.llm.parsing import parse_llm_json_response
from summarize_links.models import SummaryResult
from summarize_links.rate_limiter import ModelRateLimits, RateLimiter

__all__ = [
    # Client implementations
    "GeminiClient",
    "MockGeminiClient",
]

# Module logger
logger = logging.getLogger(__name__)


class GeminiClient(BaseLLMClient):
    """
    Client for the Google Gemini API.

    Handles API authentication, request formatting, and response parsing
    with automatic retry logic for rate limits and transient errors.
    Includes per-model rate limiting to stay within Gemini API quotas.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        rate_limiter: RateLimiter | None = None,
        state_path: Path | None = None,
        model_limits: ModelRateLimits | None = None,
        yaml_model_limits: dict[str, dict[str, int]] | None = None,
        rpm_limit: int | None = None,
        tpm_limit: int | None = None,
        daily_limit: int | None = None,
    ) -> None:
        """
        Initialize the Gemini client.

        Args:
            api_key: Google AI Studio API key.
            model: Gemini model name to use.
            rate_limiter: Optional rate limiter instance. If None, creates a new one.
            state_path: Optional path for persisting rate limit state.
            model_limits: Explicit rate limits for the model. If None, uses get_model_rate_limits.
            yaml_model_limits: Per-model limits from YAML config (passed to get_model_rate_limits).
            rpm_limit: Legacy: Requests per minute limit (ignored if model_limits provided).
            tpm_limit: Legacy: Tokens per minute limit (ignored if model_limits provided).
            daily_limit: Legacy: Requests per day limit (ignored if model_limits provided).
        """
        # Initialize base class with Langfuse prompt management and rate limiting
        super().__init__(
            error_class=GeminiAPIError,
            model=model,
            rate_limiter=rate_limiter,
            state_path=state_path,
            model_limits=model_limits,
            yaml_model_limits=yaml_model_limits,
            rpm_limit=rpm_limit,
            tpm_limit=tpm_limit,
            daily_limit=daily_limit,
        )

        # GeminiClient always has rate limiting enabled - narrow the type
        assert self._rate_limiter is not None
        # Re-declare with non-optional type for mypy
        self._rate_limiter: RateLimiter = self._rate_limiter

        self._api_key = api_key
        self._client: Any = None

        logger.debug(
            "Initialized GeminiClient with model: %s (RPM=%d, TPM=%d, Daily=%d) "
            "[Langfuse prompts required]",
            model,
            self._rate_limiter.rpm_limit,
            self._rate_limiter.tpm_limit,
            self._rate_limiter.daily_limit,
        )

    def _get_client(self) -> Any:
        """
        Get or create the client instance.

        Returns:
            Configured Client instance.
        """
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
            logger.debug("Created Client instance")
        return self._client

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
            RateLimitError: When rate limited after all retries exhausted,
                           or daily limit exceeded.
            GeminiAPIError: When API returns an error.
        """
        # Get prompts from Langfuse
        system_prompt, user_prompt_template = self._get_langfuse_prompts()
        prompt = self._compile_user_prompt(user_prompt_template, content, url, title)
        client = self._get_client()

        # Estimate tokens for rate limiting
        estimated_tokens = self._rate_limiter.estimate_tokens(content + prompt)

        # Wait if we're near rate limits (blocks until safe to proceed)
        self._rate_limiter.wait_if_needed(estimated_tokens)

        last_exception: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(
                    "Sending request to Gemini API (attempt %d/%d)",
                    attempt + 1,
                    MAX_RETRIES,
                )
                response = client.models.generate_content(
                    model=self._model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                    ),
                )

                # Check for blocked content
                if not response.parts:
                    logger.warning("Gemini response has no parts - content may be blocked")
                    raise GeminiAPIError("Response blocked or empty")

                summary: str = response.text

                # Record successful request for rate limiting
                # Try to get actual token count from response metadata
                tokens_used = estimated_tokens
                try:
                    if hasattr(response, "usage_metadata") and response.usage_metadata:
                        usage = response.usage_metadata
                        if hasattr(usage, "total_token_count") and isinstance(
                            usage.total_token_count, int
                        ):
                            tokens_used = usage.total_token_count
                except (AttributeError, TypeError):
                    # Fall back to estimate if metadata unavailable
                    pass
                self._rate_limiter.record_request(tokens_used)

                logger.info("Successfully generated summary (%d chars)", len(summary))
                return summary

            except errors.ClientError as e:
                # Check for specific error types based on error message/status
                error_str = str(e).lower()

                # Check if it's a rate limit error (429, quota, rate limit)
                if (
                    "429" in str(e)
                    or "quota" in error_str
                    or re.search(r"\brate[-_\s]*limit\b", error_str)
                ):
                    # Rate limit from API - calculate smart wait time
                    last_exception = e
                    wait_time = self._calculate_rate_limit_wait(attempt, e)

                    logger.warning(
                        "API rate limited (attempt %d/%d). Waiting %.1fs before retry...",
                        attempt + 1,
                        MAX_RETRIES,
                        wait_time,
                    )

                    # Show rate limit status for debugging
                    status = self._rate_limiter.get_status()
                    logger.debug(
                        "Rate limit status: RPM=%d/%d, TPM=%d/%d, Daily=%d/%d",
                        status["rpm"]["current"],
                        status["rpm"]["limit"],
                        status["tpm"]["current"],
                        status["tpm"]["limit"],
                        status["daily"]["current"],
                        status["daily"]["limit"],
                    )

                    time.sleep(wait_time)

                    # After waiting, also check via rate limiter to be safe
                    self._rate_limiter.wait_if_needed(estimated_tokens)

                elif "400" in str(e) or (
                    "invalid" in error_str
                    and any(
                        term in error_str for term in ("request", "argument", "arguments", "input")
                    )
                ):
                    # Bad request - don't retry
                    logger.error("Invalid request to Gemini API: %s", e)
                    raise GeminiAPIError(f"Invalid request: {e}") from e

                elif (
                    "permission denied" in error_str
                    or "access denied" in error_str
                    or "unauthorized" in error_str
                    or "forbidden" in error_str
                    or "403" in str(e)
                    or "401" in str(e)
                ):
                    # Auth error - don't retry
                    logger.error("Permission denied for Gemini API: %s", e)
                    raise GeminiAPIError(f"Permission denied: {e}") from e

                else:
                    # Other API errors - retry with exponential backoff
                    last_exception = e
                    wait_time = BASE_RETRY_DELAY * (2**attempt)
                    wait_time = min(wait_time, MAX_RETRY_DELAY)

                    logger.warning(
                        "API error (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1,
                        MAX_RETRIES,
                        e,
                        wait_time,
                    )
                    time.sleep(wait_time)

        # All retries exhausted
        logger.error("All retries exhausted for Gemini API call")
        # Check if last exception was rate limit related
        if last_exception:
            message = str(last_exception)
            message_lower = message.lower()
            if (
                "429" in message
                or "quota" in message_lower
                or "rate limit" in message_lower
                or "rate_limit" in message_lower
            ):
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
        - Token usage details

        Args:
            content: The text content to summarize.
            url: The source URL for attribution.
            title: Optional page title.

        Returns:
            SummaryResult with content, suggested tags, content type, and usage.

        Raises:
            RateLimitError: When rate limited after all retries exhausted.
            GeminiAPIError: When API returns an error.
        """
        # Fetch prompts from Langfuse (required)
        system_prompt_text, user_prompt_template = self._get_langfuse_prompts()
        user_prompt_text = self._compile_user_prompt(user_prompt_template, content, url, title)

        client = self._get_client()

        # Estimate tokens for rate limiting
        estimated_tokens = self._rate_limiter.estimate_tokens(content + user_prompt_text)

        # Wait if we're near rate limits
        self._rate_limiter.wait_if_needed(estimated_tokens)

        # Make the API call
        response = client.models.generate_content(
            model=self._model_name,
            contents=user_prompt_text,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt_text,
            ),
        )

        # Check for blocked content
        if not response.parts:
            logger.warning("Gemini response has no parts - content may be blocked")
            raise GeminiAPIError("Response blocked or empty")

        raw_response = response.text

        # Extract usage details from response
        usage_details = None
        try:
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage = response.usage_metadata
                usage_details = {
                    "input": getattr(usage, "prompt_token_count", 0),
                    "output": getattr(usage, "candidates_token_count", 0),
                    "total": getattr(usage, "total_token_count", 0),
                }
                logger.debug(
                    "Token usage: input=%d, output=%d, total=%d",
                    usage_details["input"],
                    usage_details["output"],
                    usage_details["total"],
                )
        except (AttributeError, TypeError) as e:
            logger.debug("Could not extract usage metadata: %s", e)

        # Record successful request for rate limiting
        tokens_used = usage_details["total"] if usage_details else estimated_tokens
        self._rate_limiter.record_request(tokens_used)

        # Parse the JSON response into SummaryResult
        result = parse_llm_json_response(raw_response)

        # Populate result with prompt and usage metadata using base class helper
        self._populate_result_metadata(
            result, system_prompt_text, user_prompt_text, raw_response, usage_details
        )

        return result


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

        # Build mock prompts for tracing consistency
        system_prompt = "Mock system prompt"
        prompt = f"Mock prompt for URL: {url}"

        return SummaryResult(
            content=summary_text,
            suggested_tags=mock_tags,
            content_type=content_type,
            system_prompt=system_prompt,
            raw_prompt=prompt,
            raw_response=summary_text,  # Mock: response is the summary itself
        )


def create_client(
    api_key: str | None,
    model: str = DEFAULT_MODEL,
    mock_mode: bool = False,
    state_path: Path | None = None,
    model_limits: ModelRateLimits | None = None,
    yaml_model_limits: dict[str, dict[str, int]] | None = None,
    rpm_limit: int | None = None,
    tpm_limit: int | None = None,
    daily_limit: int | None = None,
) -> GeminiClient | MockGeminiClient:
    """
    Factory function to create appropriate client based on mode.

    Args:
        api_key: API key for real client, can be None in mock mode.
        model: Model name to use.
        mock_mode: If True, return MockGeminiClient.
        state_path: Optional path for persisting rate limit state.
        model_limits: Explicit rate limits for the model.
        yaml_model_limits: Per-model limits from YAML config.
        rpm_limit: Legacy: Requests per minute limit (uses default if None).
        tpm_limit: Legacy: Tokens per minute limit (uses default if None).
        daily_limit: Legacy: Requests per day limit (uses default if None).

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
    return GeminiClient(
        api_key=api_key,
        model=model,
        state_path=state_path,
        model_limits=model_limits,
        yaml_model_limits=yaml_model_limits,
        rpm_limit=rpm_limit,
        tpm_limit=tpm_limit,
        daily_limit=daily_limit,
    )
