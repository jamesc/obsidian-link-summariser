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
        Fetch consolidated chat prompt from Langfuse with caching.

        The "summarize-document" prompt is a chat-type prompt containing both
        system and user messages. This method extracts the text from each.

        Returns:
            Tuple of (system_prompt_text, user_prompt_template_text).

        Raises:
            Exception: Subclass-specific error if prompt cannot be fetched.
        """
        try:
            # Check cache first
            if "prompt" in self._prompt_cache:
                logger.debug("Using cached Langfuse prompt")
                prompt_obj = self._prompt_cache["prompt"]
                return self._extract_messages_from_chat_prompt(prompt_obj)

            # Fetch consolidated chat prompt from Langfuse
            logger.debug("Fetching prompt from Langfuse: summarize-document")
            prompt_obj = self._langfuse_client.get_prompt("summarize-document", type="chat")

            # Cache the prompt object (for metadata and trace linking)
            self._prompt_cache["prompt"] = prompt_obj

            logger.info(
                "Fetched prompt from Langfuse: summarize-document v%s",
                getattr(prompt_obj, "version", "unknown"),
            )

            return self._extract_messages_from_chat_prompt(prompt_obj)

        except Exception as e:
            raise self._error_class(f"Failed to fetch prompt from Langfuse (required): {e}") from e

    def _extract_messages_from_chat_prompt(self, prompt_obj: Any) -> tuple[str, str]:
        """
        Extract system and user message templates from a chat prompt object.

        Note: Langfuse automatically resolves prompt references (@@@langfusePrompt:...@@@)
        server-side, so we receive the fully resolved content in prompt_obj.prompt.

        Args:
            prompt_obj: Langfuse chat prompt object with messages array.

        Returns:
            Tuple of (system_prompt_text, user_prompt_template_text).

        Raises:
            Exception: If expected messages are not found.
        """
        # Get messages from prompt (already resolved by Langfuse)
        messages = prompt_obj.prompt
        if not isinstance(messages, list):
            raise self._error_class(
                f"Expected chat prompt to have list of messages, got {type(messages)}"
            )

        # Extract system and user content
        system_content = None
        user_content = None

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_content = content
            elif role == "user":
                user_content = content

        if system_content is None:
            raise self._error_class("Chat prompt missing system message")
        if user_content is None:
            raise self._error_class("Chat prompt missing user message")

        return system_content, user_content

    def _compile_user_prompt(self, template: str, content: str, url: str, title: str | None) -> str:
        """
        Compile user prompt template with variables.

        The {{title}} variable is special - it's replaced with " titled 'X'" when
        a title exists, or empty string when title is None.

        Args:
            template: Prompt template string (user message from chat prompt).
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

        # Format current date for temporal context (prevents LLM date hallucination)
        from datetime import date

        current_date = date.today().strftime("%B %d, %Y")  # e.g., "January 22, 2026"

        # Compile using Langfuse chat prompt object
        # compile() returns a list of messages with variables substituted
        prompt_obj = self._prompt_cache["prompt"]
        compiled_messages: list[dict[str, str]] = prompt_obj.compile(
            title=title_text,
            url=url,
            content=content,
            current_date=current_date,
        )

        # Extract the user message content from compiled messages
        for msg in compiled_messages:
            if msg.get("role") == "user":
                return msg.get("content", "")

        # Fallback: if no user message found, return the template as-is
        # This shouldn't happen with a well-formed prompt
        logger.warning("No user message found in compiled chat prompt, using raw template")
        return template

    def _build_prompt_metadata(self) -> dict[str, Any] | None:
        """
        Build prompt metadata dictionary from cached Langfuse prompt.

        Returns:
            Dictionary with prompt name, version, and source.
            None if prompt not cached.
        """
        if "prompt" not in self._prompt_cache:
            return None

        prompt_obj = self._prompt_cache["prompt"]

        return {
            "prompt_name": "summarize-document",
            "prompt_version": getattr(prompt_obj, "version", None),
            "prompt_type": "chat",
            "source": "langfuse",
        }

    def get_cached_prompt(self) -> Any | None:
        """
        Get cached Langfuse prompt object for trace linking.

        Returns the raw prompt object that can be passed to Langfuse's
        trace_generation to link prompts to generations. This enables
        per-prompt-version metrics in Langfuse UI.

        Returns:
            The cached prompt object, or None if not cached.
        """
        return self._prompt_cache.get("prompt")

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
            RuntimeError: If called without rate limiter initialized.
        """
        if self._rate_limiter is None:
            raise RuntimeError("_calculate_rate_limit_wait requires rate limiter")

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
