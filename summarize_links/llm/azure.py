"""
Azure / Microsoft Foundry API client for content summarization.

This module provides a client for the Azure OpenAI API (Microsoft Foundry)
to generate summaries of web page content in Obsidian-friendly Markdown format.
Supports structured output with suggested tags and content classification.
Includes rate limiting to stay within Azure API quotas.
"""

import logging
import time
from pathlib import Path

from openai import APIConnectionError, APIError, AzureOpenAI
from openai import RateLimitError as OpenAIRateLimitError

from summarize_links.config import (
    AZURE_DAILY_LIMIT,
    AZURE_RPM_LIMIT,
    AZURE_TPM_LIMIT,
    DEFAULT_AZURE_API_VERSION,
)
from summarize_links.exceptions import (
    AzureAPIError,
    AzureAuthenticationError,
    AzureDeploymentError,
    AzureRateLimitError,
)
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
    "AzureClient",
]

# Module logger
logger = logging.getLogger(__name__)


class AzureClient(BaseLLMClient):
    """
    Client for Azure OpenAI / Microsoft Foundry.

    Handles API authentication, request formatting, and response parsing
    with automatic retry logic for rate limits and transient errors.
    Includes per-model rate limiting to stay within Azure API quotas.
    """

    # Azure-specific default rate limits
    _default_rpm: int = AZURE_RPM_LIMIT
    _default_tpm: int = AZURE_TPM_LIMIT
    _default_daily: int = AZURE_DAILY_LIMIT

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model: str,
        deployment_name: str | None = None,
        api_version: str = DEFAULT_AZURE_API_VERSION,
        rate_limiter: RateLimiter | None = None,
        state_path: Path | None = None,
        model_limits: ModelRateLimits | None = None,
        yaml_model_limits: dict[str, dict[str, int]] | None = None,
        rpm_limit: int | None = None,
        tpm_limit: int | None = None,
        daily_limit: int | None = None,
    ) -> None:
        """
        Initialize the Azure client.

        Args:
            api_key: Azure API key.
            endpoint: Azure endpoint URL (e.g., https://myresource.openai.azure.com/).
                Must use HTTPS protocol.
            model: Model name for logging and rate limiting.
            deployment_name: Azure deployment name. Defaults to model name if not
                provided. Note: Azure deployment names are user-defined and often
                differ from model names (e.g., "my-gpt4-deployment" vs "gpt-4").
                Ensure this matches your actual Azure deployment.
            api_version: Azure API version.
            rate_limiter: Optional rate limiter instance. If None, creates a new one.
            state_path: Optional path for persisting rate limit state.
            model_limits: Explicit rate limits for the model.
            yaml_model_limits: Per-model limits from YAML config.
            rpm_limit: Legacy: Requests per minute limit.
            tpm_limit: Legacy: Tokens per minute limit.
            daily_limit: Legacy: Requests per day limit.
        """
        # Initialize base class with Langfuse prompt management and rate limiting
        super().__init__(
            error_class=AzureAPIError,
            model=model,
            rate_limiter=rate_limiter,
            state_path=state_path,
            model_limits=model_limits,
            yaml_model_limits=yaml_model_limits,
            rpm_limit=rpm_limit,
            tpm_limit=tpm_limit,
            daily_limit=daily_limit,
        )

        # AzureClient always has rate limiting enabled - narrow the type
        assert self._rate_limiter is not None
        # Re-declare with non-optional type for mypy
        self._rate_limiter: RateLimiter = self._rate_limiter

        self._api_key = api_key
        # Validate and normalize endpoint URL
        normalized_endpoint = endpoint.rstrip("/")
        if not normalized_endpoint.startswith("https://"):
            raise AzureAPIError(
                f"Azure endpoint must use HTTPS. Got: {endpoint}. "
                "Expected format: https://<resource-name>.openai.azure.com"
            )
        self._endpoint = normalized_endpoint
        self._deployment_name = deployment_name or model
        self._api_version = api_version
        self._client: AzureOpenAI | None = None

        logger.debug(
            "Initialized AzureClient with model: %s, deployment: %s (RPM=%d, TPM=%d, Daily=%d) "
            "[Langfuse prompts required]",
            model,
            self._deployment_name,
            self._rate_limiter.rpm_limit,
            self._rate_limiter.tpm_limit,
            self._rate_limiter.daily_limit,
        )

    def _get_client(self) -> AzureOpenAI:
        """
        Get or create the Azure OpenAI client instance.

        Returns:
            Configured AzureOpenAI client instance.
        """
        if self._client is None:
            self._client = AzureOpenAI(
                api_key=self._api_key,
                api_version=self._api_version,
                azure_endpoint=self._endpoint,
            )
            logger.debug("Created AzureOpenAI client instance")
        return self._client

    def summarize(self, content: str, url: str, title: str | None = None) -> str:
        """
        Summarize content using the Azure OpenAI API.

        Args:
            content: The text content to summarize.
            url: The source URL for attribution.
            title: Optional page title.

        Returns:
            Markdown-formatted summary.

        Raises:
            AzureRateLimitError: When rate limited after all retries exhausted.
            AzureAPIError: When API returns an error.
        """
        # Get prompts from Langfuse
        system_prompt, user_prompt_template = self._get_langfuse_prompts()
        prompt = self._compile_user_prompt(user_prompt_template, content, url, title)
        client = self._get_client()

        # Estimate tokens for rate limiting
        estimated_tokens = self._rate_limiter.estimate_tokens(content + prompt)

        # Wait if we're near rate limits
        self._rate_limiter.wait_if_needed(estimated_tokens)

        last_exception: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(
                    "Sending request to Azure OpenAI API (attempt %d/%d)",
                    attempt + 1,
                    MAX_RETRIES,
                )

                response = client.chat.completions.create(
                    model=self._deployment_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )

                # Extract the response content
                if not response.choices or not response.choices[0].message.content:
                    logger.warning("Azure response has no content")
                    raise AzureAPIError("Response empty or blocked")

                summary: str = response.choices[0].message.content

                # Record successful request for rate limiting
                tokens_used = estimated_tokens
                if response.usage:
                    tokens_used = response.usage.total_tokens
                self._rate_limiter.record_request(tokens_used)

                logger.info("Successfully generated summary (%d chars)", len(summary))
                return summary

            except OpenAIRateLimitError as e:
                # Rate limit from API
                last_exception = e
                wait_time = self._calculate_rate_limit_wait(attempt, e)

                logger.warning(
                    "API rate limited (attempt %d/%d). Waiting %.1fs before retry...",
                    attempt + 1,
                    MAX_RETRIES,
                    wait_time,
                )
                time.sleep(wait_time)
                self._rate_limiter.wait_if_needed(estimated_tokens)

            except APIConnectionError as e:
                # Connection error - retry with backoff
                last_exception = e
                wait_time = BASE_RETRY_DELAY * (2**attempt)
                wait_time = min(wait_time, MAX_RETRY_DELAY)

                logger.warning(
                    "Connection error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1,
                    MAX_RETRIES,
                    e,
                    wait_time,
                )
                time.sleep(wait_time)

            except APIError as e:
                error_str = str(e).lower()

                # Get status code from response if available
                status_code = getattr(getattr(e, "response", None), "status_code", None)

                # Check for authentication errors (401, 403)
                if status_code == 401 or "unauthorized" in error_str:
                    logger.error("Authentication failed for Azure API: %s", e)
                    raise AzureAuthenticationError(f"Authentication failed: {e}") from e

                if status_code == 403 or "forbidden" in error_str:
                    logger.error("Access forbidden for Azure API: %s", e)
                    raise AzureAuthenticationError(f"Access forbidden: {e}") from e

                # Check for deployment not found (404)
                if status_code == 404 or "deployment" in error_str:
                    logger.error("Deployment not found: %s", e)
                    raise AzureDeploymentError(
                        f"Deployment '{self._deployment_name}' not found: {e}"
                    ) from e

                # Other API errors - retry with backoff
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
        logger.error("All retries exhausted for Azure API call")
        if last_exception and isinstance(last_exception, OpenAIRateLimitError):
            raise AzureRateLimitError("Rate limit exceeded after retries") from last_exception
        raise AzureAPIError(f"API error after retries: {last_exception}") from last_exception

    def summarize_with_metadata(
        self, content: str, url: str, title: str | None = None
    ) -> SummaryResult:
        """
        Summarize content and return structured result with tags.

        This method requests JSON output from Azure OpenAI including:
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
            AzureRateLimitError: When rate limited after all retries exhausted.
            AzureAPIError: When API returns an error.
        """
        # Fetch prompts from Langfuse (required)
        system_prompt_text, user_prompt_template = self._get_langfuse_prompts()
        user_prompt_text = self._compile_user_prompt(user_prompt_template, content, url, title)

        # Debug: Check if system prompt contains "json" for Azure's requirement
        if "json" not in system_prompt_text.lower():
            logger.error(
                "System prompt does not contain 'json' - Azure will reject this. "
                "System prompt preview: %s",
                system_prompt_text[:200],
            )
            raise AzureAPIError(
                "System prompt must contain the word 'json' for Azure's "
                "json_object response format. Check your Langfuse prompts."
            )

        client = self._get_client()

        # Estimate tokens for rate limiting
        estimated_tokens = self._rate_limiter.estimate_tokens(content + user_prompt_text)

        # Wait if we're near rate limits
        self._rate_limiter.wait_if_needed(estimated_tokens)

        last_exception: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(
                    "Sending request to Azure OpenAI API with JSON mode (attempt %d/%d)",
                    attempt + 1,
                    MAX_RETRIES,
                )

                response = client.chat.completions.create(
                    model=self._deployment_name,
                    messages=[
                        {"role": "system", "content": system_prompt_text},
                        {"role": "user", "content": user_prompt_text},
                    ],
                    response_format={"type": "json_object"},
                )

                # Extract the response content
                if not response.choices or not response.choices[0].message.content:
                    logger.warning("Azure response has no content")
                    raise AzureAPIError("Response empty or blocked")

                raw_response = response.choices[0].message.content

                # Extract usage details (normalized to same format as other clients)
                usage_details: dict[str, int] | None = None
                if response.usage:
                    usage_details = {
                        "input": response.usage.prompt_tokens,
                        "output": response.usage.completion_tokens,
                        "total": response.usage.total_tokens,
                    }
                    tokens_used = response.usage.total_tokens
                else:
                    tokens_used = estimated_tokens

                # Record successful request
                self._rate_limiter.record_request(tokens_used)

                # Parse JSON response
                result = parse_llm_json_response(raw_response)

                # Populate metadata
                self._populate_result_metadata(
                    result,
                    system_prompt=system_prompt_text,
                    user_prompt=user_prompt_text,
                    raw_response=raw_response,
                    usage_details=usage_details,
                )

                logger.info(
                    "Successfully generated summary with %d tags, type: %s",
                    len(result.suggested_tags),
                    result.content_type,
                )
                return result

            except OpenAIRateLimitError as e:
                last_exception = e
                wait_time = self._calculate_rate_limit_wait(attempt, e)

                logger.warning(
                    "API rate limited (attempt %d/%d). Waiting %.1fs before retry...",
                    attempt + 1,
                    MAX_RETRIES,
                    wait_time,
                )
                time.sleep(wait_time)
                self._rate_limiter.wait_if_needed(estimated_tokens)

            except APIConnectionError as e:
                last_exception = e
                wait_time = BASE_RETRY_DELAY * (2**attempt)
                wait_time = min(wait_time, MAX_RETRY_DELAY)

                logger.warning(
                    "Connection error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1,
                    MAX_RETRIES,
                    e,
                    wait_time,
                )
                time.sleep(wait_time)

            except APIError as e:
                error_str = str(e).lower()

                # Get status code from response if available
                status_code = getattr(getattr(e, "response", None), "status_code", None)

                if status_code == 401 or "unauthorized" in error_str:
                    raise AzureAuthenticationError(f"Authentication failed: {e}") from e

                if status_code == 403 or "forbidden" in error_str:
                    raise AzureAuthenticationError(f"Access forbidden: {e}") from e

                if status_code == 404 or "deployment" in error_str:
                    raise AzureDeploymentError(
                        f"Deployment '{self._deployment_name}' not found: {e}"
                    ) from e

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

            except AzureAPIError:
                # Re-raise our own errors
                raise

        # All retries exhausted
        logger.error("All retries exhausted for Azure API call")
        if last_exception and isinstance(last_exception, OpenAIRateLimitError):
            raise AzureRateLimitError("Rate limit exceeded after retries") from last_exception
        raise AzureAPIError(f"API error after retries: {last_exception}") from last_exception
