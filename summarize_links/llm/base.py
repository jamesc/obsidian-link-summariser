"""
Base class for LLM clients with Langfuse prompt management and rate limiting.

This module provides shared functionality for:
- Fetching and compiling prompts from Langfuse
- Rate limiter initialization and management
- Common retry logic for rate-limited API calls

Used by GeminiClient, AzureClient, and OllamaClient.
"""

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from summarize_links.models import SummaryResult
    from summarize_links.rate_limiter import ModelRateLimits, RateLimiter

__all__ = [
    "BaseLLMClient",
    # Retry configuration constants (shared across rate-limited clients)
    "MAX_RETRIES",
    "BASE_RETRY_DELAY",
    "MIN_RATE_LIMIT_WAIT",
    "MAX_RETRY_DELAY",
]

# Retry configuration (shared across rate-limited clients)
MAX_RETRIES = 5
BASE_RETRY_DELAY = 2.0  # Base delay for exponential backoff (seconds)
MIN_RATE_LIMIT_WAIT = 10.0  # Minimum wait when rate limited (seconds)
MAX_RETRY_DELAY = 120.0  # Maximum delay cap (seconds)

logger = logging.getLogger(__name__)


class BaseLLMClient:
    """
    Base class for LLM clients with Langfuse prompt management and rate limiting.

    Provides shared functionality for:
    - Langfuse client initialization (required)
    - Fetching prompts from Langfuse with caching
    - Compiling user prompt templates with variables
    - Rate limiter initialization (optional, for cloud providers)
    """

    # Default rate limits (can be overridden by subclasses)
    _default_rpm: int = 5
    _default_tpm: int = 250000
    _default_daily: int = 20

    def __init__(
        self,
        error_class: type[Exception],
        model: str | None = None,
        rate_limiter: "RateLimiter | None" = None,
        state_path: Path | None = None,
        model_limits: "ModelRateLimits | None" = None,
        yaml_model_limits: dict[str, dict[str, int]] | None = None,
        rpm_limit: int | None = None,
        tpm_limit: int | None = None,
        daily_limit: int | None = None,
        enable_rate_limiting: bool = True,
    ) -> None:
        """
        Initialize Langfuse prompt management and optional rate limiting.

        Args:
            error_class: Exception class to raise on errors.
            model: Model name (required for rate limiting).
            rate_limiter: Optional rate limiter instance. If None and rate limiting
                         is enabled, creates a new one.
            state_path: Optional path for persisting rate limit state.
            model_limits: Explicit rate limits for the model.
            yaml_model_limits: Per-model limits from YAML config.
            rpm_limit: Legacy: Requests per minute limit.
            tpm_limit: Legacy: Tokens per minute limit.
            daily_limit: Legacy: Requests per day limit.
            enable_rate_limiting: If False, skip rate limiter initialization.

        Raises:
            error_class: If Langfuse initialization fails.
        """
        self._prompt_cache: dict[str, Any] = {}
        self._error_class = error_class
        self._model_name = model
        self._rate_limiter: RateLimiter | None = None

        # Initialize Langfuse client (REQUIRED)
        try:
            from langfuse import Langfuse

            self._langfuse_client = Langfuse()
            logger.debug("Langfuse client initialized for prompt management")
        except Exception as e:
            raise error_class(
                f"Failed to initialize Langfuse (required for prompt management): {e}. "
                "Please verify LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set correctly."
            ) from e

        # Initialize rate limiter if enabled
        if enable_rate_limiting and model is not None:
            self._rate_limiter = self._init_rate_limiter(
                model=model,
                rate_limiter=rate_limiter,
                state_path=state_path,
                model_limits=model_limits,
                yaml_model_limits=yaml_model_limits,
                rpm_limit=rpm_limit,
                tpm_limit=tpm_limit,
                daily_limit=daily_limit,
            )

    def _init_rate_limiter(
        self,
        model: str,
        rate_limiter: "RateLimiter | None" = None,
        state_path: Path | None = None,
        model_limits: "ModelRateLimits | None" = None,
        yaml_model_limits: dict[str, dict[str, int]] | None = None,
        rpm_limit: int | None = None,
        tpm_limit: int | None = None,
        daily_limit: int | None = None,
    ) -> "RateLimiter":
        """
        Initialize rate limiter with appropriate limits.

        Priority: rate_limiter > model_limits > legacy params > yaml config > defaults

        Args:
            model: Model name for rate limiting.
            rate_limiter: Optional pre-configured rate limiter.
            state_path: Optional path for persisting state.
            model_limits: Explicit rate limits.
            yaml_model_limits: Per-model limits from YAML config.
            rpm_limit: Legacy requests per minute limit.
            tpm_limit: Legacy tokens per minute limit.
            daily_limit: Legacy requests per day limit.

        Returns:
            Configured RateLimiter instance.
        """
        from summarize_links.config import get_model_rate_limits
        from summarize_links.rate_limiter import ModelRateLimits, RateLimiter

        # If rate limiter provided, use it directly
        if rate_limiter is not None:
            return rate_limiter

        # Determine rate limits
        if model_limits is not None:
            limits = model_limits
        elif rpm_limit is not None or tpm_limit is not None or daily_limit is not None:
            # Legacy: create limits from individual parameters
            limits = ModelRateLimits(
                rpm_limit=rpm_limit if rpm_limit is not None else self._default_rpm,
                tpm_limit=tpm_limit if tpm_limit is not None else self._default_tpm,
                daily_limit=daily_limit if daily_limit is not None else self._default_daily,
            )
        else:
            # Use model-specific defaults from config
            limits = get_model_rate_limits(model, yaml_model_limits)

        return RateLimiter(
            model=model,
            limits=limits,
            state_path=state_path,
        )

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

        The {{title}} variable is special - it's replaced with " titled 'X'" when
        a title exists, or empty string when title is None.

        Args:
            template: Prompt template string from Langfuse.
            content: Web page content.
            url: Source URL.
            title: Page title (None if unknown).

        Returns:
            Compiled prompt string.

        Raises:
            Exception: If template compilation fails (propagated as client error).
        """
        # Format title as " titled 'X'" or empty string (matches main branch behavior)
        title_text = f" titled '{title}'" if title else ""

        # Compile using Langfuse prompt object
        user_obj = self._prompt_cache["user"]
        compiled: str = user_obj.compile(
            title=title_text,
            url=url,
            content=content,
        )
        return compiled

    def _build_prompt_metadata(self) -> dict[str, Any] | None:
        """
        Build prompt metadata dictionary from cached Langfuse prompts.

        Returns:
            Dictionary with prompt names, versions, and source.
            None if prompts not cached.
        """
        if "system" not in self._prompt_cache or "user" not in self._prompt_cache:
            return None

        system_obj = self._prompt_cache["system"]
        user_obj = self._prompt_cache["user"]

        return {
            "system_prompt_name": "summarize-document/system",
            "user_prompt_name": "summarize-document/user",
            "system_prompt_version": getattr(system_obj, "version", None),
            "user_prompt_version": getattr(user_obj, "version", None),
            "source": "langfuse",
        }

    def _populate_result_metadata(
        self,
        result: "SummaryResult",
        system_prompt: str,
        user_prompt: str,
        raw_response: str,
        usage_details: dict[str, int] | None = None,
    ) -> None:
        """
        Populate SummaryResult with prompt and usage metadata.

        Args:
            result: SummaryResult object to populate.
            system_prompt: System prompt text used.
            user_prompt: User prompt text used.
            raw_response: Raw response from LLM.
            usage_details: Optional token usage details.
        """
        result.system_prompt = system_prompt
        result.raw_prompt = user_prompt
        result.raw_response = raw_response
        result.usage_details = usage_details
        result.prompt_metadata = self._build_prompt_metadata()

    def _calculate_rate_limit_wait(self, attempt: int, error: Exception) -> float:
        """
        Calculate wait time when rate limited, respecting actual rate limit windows.

        Uses a combination of:
        1. Retry-After header from the API response (if available)
        2. Rate limiter's calculated wait time based on sliding window
        3. Exponential backoff as a fallback

        This method requires rate limiting to be enabled (_rate_limiter not None).

        Args:
            attempt: Current retry attempt (0-indexed).
            error: The rate limit exception from the API.

        Returns:
            Number of seconds to wait before retrying.

        Raises:
            AssertionError: If called without rate limiter initialized.
        """
        assert self._rate_limiter is not None, "_calculate_rate_limit_wait requires rate limiter"

        # Mark that we hit a rate limit (syncs internal state)
        self._rate_limiter.mark_rate_limited()

        # Try to extract Retry-After from the error message or metadata
        retry_after: float | None = None
        error_str = str(error)

        # Parse retry delay from error message
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
