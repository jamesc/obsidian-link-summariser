"""
Gemini API client for content summarization.

This module provides a client for the Google Gemini API to generate
summaries of web page content in Obsidian-friendly Markdown format.
Supports structured output with suggested tags and content classification.
Includes rate limiting to stay within Gemini API quotas.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Protocol

from google import genai
from google.genai import errors, types

from summarize_links.config import DEFAULT_MODEL, get_model_rate_limits
from summarize_links.exceptions import GeminiAPIError, RateLimitError
from summarize_links.models import CONTENT_TYPE_DESCRIPTIONS, CONTENT_TYPES, SummaryResult
from summarize_links.rate_limiter import ModelRateLimits, RateLimiter

__all__ = [
    # Protocol for dependency injection
    "SummarizerProtocol",
    # Client implementations
    "GeminiClient",
    "MockGeminiClient",
    # Factory function
    "create_client",
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


def _extract_summary_from_malformed_json(text: str) -> str | None:
    """
    Try to extract summary content from malformed JSON response.

    When Gemini returns JSON with unescaped characters in the summary field,
    standard JSON parsing fails. This function attempts to extract the summary
    content using regex patterns.

    Args:
        text: The malformed JSON text.

    Returns:
        Extracted summary content, or None if extraction fails.
    """
    # Try to find the summary field value
    # Pattern: "summary": "content..." or "summary": 'content...'
    # The summary typically ends before "suggested_tags" or "content_type"

    # First try to find content between "summary": " and the next field
    patterns = [
        # Match "summary": "..." ending at suggested_tags or content_type
        r'"summary"\s*:\s*"(.*?)"\s*,\s*"(?:suggested_tags|content_type)"',
        # Match with single quotes
        r'"summary"\s*:\s*\'(.*?)\'\s*,\s*"(?:suggested_tags|content_type)"',
        # Match until we hit the array or closing structure
        r'"summary"\s*:\s*"(.*?)"\s*,\s*"suggested_tags"\s*:\s*\[',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            summary = match.group(1)
            # Unescape common JSON escape sequences
            summary = summary.replace('\\"', '"')
            summary = summary.replace("\\n", "\n")
            summary = summary.replace("\\t", "\t")
            summary = summary.replace("\\\\", "\\")
            return summary

    # Fallback: try to extract everything after "summary": " until a reasonable end
    match = re.search(r'"summary"\s*:\s*"(.{100,})', text, re.DOTALL)
    if match:
        content = match.group(1)
        # Find a reasonable end point - look for the pattern that ends the summary
        # Usually it's: ", "suggested_tags" or similar
        end_patterns = [
            r'",\s*"suggested_tags"',
            r'",\s*"content_type"',
            r'"\s*,\s*"[a-z_]+"\s*:',  # Any next field
            r'"\s*}',  # End of object
        ]
        for end_pattern in end_patterns:
            end_match = re.search(end_pattern, content)
            if end_match:
                summary = content[: end_match.start()]
                summary = summary.replace('\\"', '"')
                summary = summary.replace("\\n", "\n")
                summary = summary.replace("\\t", "\t")
                summary = summary.replace("\\\\", "\\")
                return summary

    return None


def _extract_tags_from_malformed_json(text: str) -> list[str]:
    """
    Try to extract suggested_tags from malformed JSON response.

    Args:
        text: The malformed JSON text.

    Returns:
        List of extracted tags, or empty list if extraction fails.
    """
    # Try to find the suggested_tags array
    match = re.search(r'"suggested_tags"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if match:
        tags_content = match.group(1)
        # Extract quoted strings from the array
        tags = re.findall(r'"([^"]+)"', tags_content)
        return tags
    return []


def _extract_content_type_from_malformed_json(text: str) -> str:
    """
    Try to extract content_type from malformed JSON response.

    Args:
        text: The malformed JSON text.

    Returns:
        Extracted content type, or "article" as default.
    """
    match = re.search(r'"content_type"\s*:\s*"([^"]+)"', text)
    if match:
        content_type = match.group(1)
        if content_type in CONTENT_TYPES:
            return content_type
    return "article"


def _is_garbled_summary(summary_text: str) -> bool:
    """
    Detect if a summary indicates the content was garbled or corrupted.

    Checks for common patterns in AI responses that indicate the source
    content was unreadable (base64, encrypted, corrupted, etc.).

    Args:
        summary_text: The summary content to check.

    Returns:
        True if the summary indicates garbled/corrupted content.
    """
    indicators = [
        "corrupted or encrypted",
        "garbled characters",
        "appears to be encrypted",
        "appears to be corrupted",
        "consists of garbled",
        "not possible to extract",
        "meaningless characters",
        "random characters",
        "base64 encoded",
        "binary data",
        "unreadable content",
    ]

    summary_lower = summary_text.lower()
    return any(indicator in summary_lower for indicator in indicators)


def _parse_gemini_response(response_text: str) -> SummaryResult:
    """
    Parse Gemini's JSON response into a SummaryResult.

    Handles various response formats including:
    - Clean JSON
    - JSON wrapped in markdown code blocks
    - Malformed responses (attempts field extraction, falls back to plain text)
    - Detects garbled/corrupted content responses and raises an error

    Args:
        response_text: Raw response from Gemini API.

    Returns:
        Parsed SummaryResult object.

    Raises:
        GeminiAPIError: If the response indicates garbled/corrupted content.
    """
    text = response_text.strip()
    original_text = text  # Keep original for fallback extraction

    # Try to extract JSON from markdown code block (handles multiline)
    json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    # If no code block found, try to find JSON object by finding matching braces
    if not json_match:
        # Find the first { and try to extract the full JSON object
        start_idx = text.find("{")
        if start_idx != -1:
            # Count braces to find the matching closing brace
            brace_count = 0
            end_idx = start_idx
            for i, char in enumerate(text[start_idx:], start=start_idx):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break
            if brace_count == 0:
                text = text[start_idx:end_idx]

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

        result = SummaryResult(
            content=summary,
            suggested_tags=suggested_tags,
            content_type=content_type,
        )

        # Check if the summary indicates garbled/corrupted content
        if _is_garbled_summary(result.content):
            raise GeminiAPIError(
                "Summary indicates the content appears corrupted or garbled. "
                "This may indicate an extraction issue."
            )

        return result

    except json.JSONDecodeError as e:
        # JSON parsing failed - try to extract fields from malformed JSON
        logger.warning(f"Failed to parse JSON response: {e}. Attempting field extraction.")

        # Try to extract the summary from the malformed JSON
        extracted_summary = _extract_summary_from_malformed_json(original_text)

        if extracted_summary:
            # Successfully extracted summary, try to get other fields too
            logger.info("Successfully extracted summary from malformed JSON response.")
            extracted_tags = _extract_tags_from_malformed_json(original_text)
            extracted_type = _extract_content_type_from_malformed_json(original_text)

            return SummaryResult(
                content=extracted_summary,
                suggested_tags=extracted_tags,
                content_type=extracted_type,
            )

        # Complete fallback: use raw text as summary
        logger.warning("Could not extract fields from malformed JSON. Using raw text.")
        result = SummaryResult(
            content=response_text,
            suggested_tags=[],
            content_type="article",
        )

    # Check if the summary indicates garbled/corrupted content
    if _is_garbled_summary(result.content):
        raise GeminiAPIError(
            "Summary indicates the content appears corrupted or garbled. "
            "This may indicate an extraction issue."
        )

    return result


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
            "Initialized GeminiClient with model: %s (RPM=%d, TPM=%d, Daily=%d)",
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
        import re

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
                        system_instruction=SUMMARY_SYSTEM_PROMPT,
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
                        term in error_str
                        for term in ("request", "argument", "arguments", "input")
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
