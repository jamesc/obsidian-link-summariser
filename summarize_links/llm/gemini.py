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

from summarize_links.config import DEFAULT_MODEL, get_model_rate_limits
from summarize_links.exceptions import GeminiAPIError, RateLimitError
from summarize_links.llm.parsing import parse_llm_json_response
from summarize_links.llm.prompts import (
    build_user_prompt_from_template,
    load_system_prompt,
    load_user_prompt_template,
)
from summarize_links.models import CONTENT_TYPE_DESCRIPTIONS, SummaryResult
from summarize_links.rate_limiter import ModelRateLimits, RateLimiter

__all__ = [
    # Client implementations
    "GeminiClient",
    "MockGeminiClient",
]

# Module logger
logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 5
BASE_RETRY_DELAY = 2.0  # Base delay for exponential backoff (seconds)
MIN_RATE_LIMIT_WAIT = 10.0  # Minimum wait when rate limited (seconds)
MAX_RETRY_DELAY = 120.0  # Maximum delay cap (seconds)


def _build_content_type_list() -> str:
    """
    Build the content type list for the system prompt from CONTENT_TYPE_DESCRIPTIONS.

    Returns:
        Formatted string listing all content types with descriptions.
    """
    lines = []
    for content_type, description in CONTENT_TYPE_DESCRIPTIONS.items():
        lines.append(f'- "{content_type}" ({description})')
    return "\n".join(lines)


# System prompt for summarization with structured output
# Content types are generated dynamically from CONTENT_TYPE_DESCRIPTIONS
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
    Build the prompt for the Gemini API using template from filesystem.

    Args:
        content: Web page content to summarize.
        url: Source URL.
        title: Optional page title.

    Returns:
        Formatted prompt string with variables replaced.
    """
    template = _get_user_prompt_template()
    return build_user_prompt_from_template(template, content, url, title)


class GeminiClient:
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
        self._api_key = api_key
        self._model_name = model
        self._client: Any = None
        self._prompt_cache: dict[str, Any] = {}

        # Initialize Langfuse client (REQUIRED)
        try:
            from langfuse import Langfuse

            self._langfuse_client = Langfuse()
            logger.debug("Langfuse client initialized for prompt management")
        except Exception as e:
            raise GeminiAPIError(f"Failed to initialize Langfuse (required): {e}") from e

        # Get model-specific rate limits
        if model_limits is not None:
            limits = model_limits
        elif rpm_limit is not None or tpm_limit is not None or daily_limit is not None:
            # Legacy: create limits from individual parameters
            limits = ModelRateLimits(
                rpm_limit=rpm_limit if rpm_limit is not None else 5,
                tpm_limit=tpm_limit if tpm_limit is not None else 250000,
                daily_limit=daily_limit if daily_limit is not None else 20,
            )
        else:
            # Use model-specific defaults
            limits = get_model_rate_limits(model, yaml_model_limits)

        # Use provided rate limiter or create one with model-specific limits
        if rate_limiter is not None:
            self._rate_limiter = rate_limiter
        else:
            self._rate_limiter = RateLimiter(
                model=model,
                limits=limits,
                state_path=state_path,
            )

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

    def _get_langfuse_prompts(self) -> tuple[str, str]:
        """
        Fetch prompts from Langfuse with caching.

        Returns:
            Tuple of (system_prompt_text, user_prompt_template_text).

        Raises:
            GeminiAPIError: If prompts cannot be fetched from Langfuse.
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
            raise GeminiAPIError(f"Failed to fetch prompts from Langfuse (required): {e}") from e

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
            # Not a template, assume it's the old _build_prompt format
            return template

    def _calculate_rate_limit_wait(self, attempt: int, error: Exception) -> float:
        """
        Calculate wait time when rate limited, respecting actual rate limit windows.

        Uses a combination of:
        1. Retry-After header from the API response (if available)
        2. Rate limiter's calculated wait time based on sliding window
        3. Exponential backoff as a fallback

        Args:
            attempt: Current retry attempt (0-indexed).
            error: The rate limit exception from the API.

        Returns:
            Number of seconds to wait before retrying.
        """
        # Mark that we hit a rate limit (syncs internal state)
        self._rate_limiter.mark_rate_limited()

        # Try to extract Retry-After from the error message or metadata
        retry_after: float | None = None
        error_str = str(error)

        # Parse retry delay from error message (Gemini often includes this)
        # Example: "Resource has been exhausted... Retry after 60 seconds"
        retry_match = re.search(r"[Rr]etry after (\d+(?:\.\d+)?)", error_str)
        if retry_match:
            retry_after = float(retry_match.group(1))
            logger.debug("Extracted Retry-After from error: %.1fs", retry_after)

        # Get the rate limiter's suggestion based on sliding window
        rpm_wait = self._rate_limiter.get_time_until_rpm_slot()
        can_proceed, limiter_wait, reason = self._rate_limiter.check_limits()

        if not can_proceed:
            logger.debug("Rate limiter suggests waiting %.1fs: %s", limiter_wait, reason)

        # Calculate exponential backoff: BASE * 2^attempt
        exponential_wait = BASE_RETRY_DELAY * (2**attempt)

        # Choose the appropriate wait time
        if retry_after is not None:
            # API told us exactly how long to wait - use that with a small buffer
            wait_time = retry_after + 1.0
        elif rpm_wait > 0:
            # Use the calculated time until an RPM slot opens
            wait_time = rpm_wait
        elif limiter_wait > 0:
            # Use rate limiter's general calculation
            wait_time = limiter_wait
        else:
            # Fallback to exponential backoff with minimum for rate limits
            wait_time = max(MIN_RATE_LIMIT_WAIT, exponential_wait)

        # Cap at maximum and ensure minimum wait for rate limits
        wait_time = min(wait_time, MAX_RETRY_DELAY)
        wait_time = max(wait_time, MIN_RATE_LIMIT_WAIT)

        return wait_time

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
        prompt = _build_prompt(content, url, title)
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
                        system_instruction=_get_system_prompt(),
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

        # Store prompt metadata from Langfuse
        system_obj = self._prompt_cache["system"]
        user_obj = self._prompt_cache["user"]
        prompt_metadata = {
            "system_prompt_name": "summarize-document/system",
            "user_prompt_name": "summarize-document/user",
            "system_version": getattr(system_obj, "version", None),
            "user_version": getattr(user_obj, "version", None),
            "source": "langfuse",
        }
        logger.debug("Using Langfuse-managed prompts")

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
        result.usage_details = usage_details

        # Store system prompt, user prompt, and response for tracing
        result.system_prompt = system_prompt_text
        result.raw_prompt = user_prompt_text
        result.raw_response = raw_response
        result.prompt_metadata = prompt_metadata

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

        # Build prompt for tracing consistency
        prompt = _build_prompt(content, url, title)

        return SummaryResult(
            content=summary_text,
            suggested_tags=mock_tags,
            content_type=content_type,
            system_prompt=_get_system_prompt(),
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
