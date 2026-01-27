"""
Rate limiting for the Gemini API.

This module provides rate limiting to stay within Gemini API quotas:
- Per-model rate limits (RPM, TPM, daily)
- 10% safety margin applied to all limits
- Sliding window for per-minute limits
- Per-model daily tracking with persistent storage

Uses a sliding window approach for per-minute limits and per-model counters
for daily limits with persistent storage.
"""

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from summarize_links.exceptions import RateLimitError

__all__ = [
    # Data classes
    "ModelRateLimits",
    # Main class
    "RateLimiter",
    # Singleton access
    "get_rate_limiter",
    "reset_rate_limiter",
]

# Module logger
logger = logging.getLogger(__name__)

# Approximate tokens per character (conservative estimate)
# Gemini uses roughly 1 token per 4 characters for English text
CHARS_PER_TOKEN = 4

# State file for daily request tracking
RATE_LIMIT_STATE_FILE = ".summarizer-rate-limit.json"

# Safety margin - work at 90% of actual limits to avoid hitting hard API limits
SAFETY_MARGIN = 0.9


@dataclass(frozen=True)
class ModelRateLimits:
    """
    Rate limit configuration for a specific model.

    Attributes:
        rpm_limit: Maximum requests per minute.
        tpm_limit: Maximum tokens per minute.
        daily_limit: Maximum requests per day.
    """

    rpm_limit: int
    tpm_limit: int
    daily_limit: int

    def with_safety_margin(self) -> "ModelRateLimits":
        """
        Return limits with safety margin applied (90% of actual limits).

        This provides a buffer to avoid hitting hard API limits.

        Returns:
            New ModelRateLimits with reduced limits.
        """
        return ModelRateLimits(
            rpm_limit=max(1, int(self.rpm_limit * SAFETY_MARGIN)),
            tpm_limit=max(1, int(self.tpm_limit * SAFETY_MARGIN)),
            daily_limit=max(1, int(self.daily_limit * SAFETY_MARGIN)),
        )


@dataclass
class RateLimitState:
    """
    Persistent state for rate limiting.

    Tracks daily requests both per-model and in total for backward
    compatibility with older state files.
    """

    date: str = ""
    daily_requests: int = 0  # Legacy total counter
    daily_requests_by_model: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "date": self.date,
            "daily_requests": self.daily_requests,
            "daily_requests_by_model": self.daily_requests_by_model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RateLimitState":
        """Create from dictionary."""
        return cls(
            date=data.get("date", ""),
            daily_requests=data.get("daily_requests", 0),
            daily_requests_by_model=data.get("daily_requests_by_model", {}),
        )

    def get_daily_requests(self, model: str) -> int:
        """
        Get daily request count for a specific model.

        Args:
            model: Model name to get count for.

        Returns:
            Number of requests made today for this model.
        """
        return self.daily_requests_by_model.get(model, 0)

    def increment_daily_requests(self, model: str) -> None:
        """
        Increment daily request count for a specific model.

        Also increments the legacy total counter for backward compatibility.

        Args:
            model: Model name to increment count for.
        """
        self.daily_requests_by_model[model] = self.daily_requests_by_model.get(model, 0) + 1
        self.daily_requests += 1


@dataclass
class RateLimiter:
    """
    Rate limiter for Gemini API requests.

    Implements sliding window rate limiting for per-minute quotas
    and per-model daily request counting with persistent storage.
    Automatically applies a 10% safety margin to all limits.

    Attributes:
        model: Current model name for per-model tracking.
        limits: Rate limits for the current model (with safety margin applied).
        state_path: Optional path for persisting daily state.
    """

    model: str = ""
    limits: ModelRateLimits = field(
        default_factory=lambda: ModelRateLimits(rpm_limit=5, tpm_limit=250000, daily_limit=20)
    )
    state_path: Path | None = None
    _apply_safety_margin: bool = True  # Internal flag to control safety margin

    # Sliding window for request timestamps (for RPM)
    _request_times: deque[float] = field(default_factory=deque)

    # Sliding window for token usage (timestamp, tokens)
    _token_usage: deque[tuple[float, int]] = field(default_factory=deque)

    # Daily counter
    _state: RateLimitState = field(default_factory=RateLimitState)

    # Thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Effective limits (after safety margin)
    _effective_limits: ModelRateLimits | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Initialize rate limiter and load persistent state."""
        # Apply safety margin to limits
        if self._apply_safety_margin:
            self._effective_limits = self.limits.with_safety_margin()
        else:
            self._effective_limits = self.limits

        # Load persistent state if path provided
        if self.state_path:
            self._load_state()

        logger.debug(
            "Initialized RateLimiter for model '%s': RPM=%d, TPM=%d, Daily=%d (with safety margin)",
            self.model,
            self._effective_limits.rpm_limit,
            self._effective_limits.tpm_limit,
            self._effective_limits.daily_limit,
        )

    @property
    def rpm_limit(self) -> int:
        """Get effective RPM limit (with safety margin applied)."""
        return self._effective_limits.rpm_limit if self._effective_limits else self.limits.rpm_limit

    @property
    def tpm_limit(self) -> int:
        """Get effective TPM limit (with safety margin applied)."""
        return self._effective_limits.tpm_limit if self._effective_limits else self.limits.tpm_limit

    @property
    def daily_limit(self) -> int:
        """Get effective daily limit (with safety margin applied)."""
        if self._effective_limits:
            return self._effective_limits.daily_limit
        return self.limits.daily_limit

    def switch_model(self, model: str, limits: ModelRateLimits) -> None:
        """
        Switch to a different model with new rate limits.

        Per-minute sliding windows are preserved (shared across models),
        but daily limits are tracked per-model.

        Args:
            model: New model name.
            limits: Rate limits for the new model.
        """
        with self._lock:
            self.model = model
            self.limits = limits
            if self._apply_safety_margin:
                self._effective_limits = limits.with_safety_margin()
            else:
                self._effective_limits = limits

            logger.info(
                "Switched to model '%s': RPM=%d, TPM=%d, Daily=%d (with safety margin)",
                model,
                self._effective_limits.rpm_limit,
                self._effective_limits.tpm_limit,
                self._effective_limits.daily_limit,
            )

    def _load_state(self) -> None:
        """Load daily request count from persistent storage."""
        if not self.state_path:
            return

        state_file = self.state_path / RATE_LIMIT_STATE_FILE
        if not state_file.exists():
            logger.debug("No rate limit state file found, starting fresh")
            return

        try:
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
            self._state = RateLimitState.from_dict(data)
            logger.debug(
                "Loaded rate limit state: %d requests on %s",
                self._state.daily_requests,
                self._state.date,
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load rate limit state: %s", e)

    def _save_state(self) -> None:
        """Save daily request count to persistent storage."""
        if not self.state_path:
            return

        state_file = self.state_path / RATE_LIMIT_STATE_FILE
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f)
            logger.debug("Saved rate limit state")
        except OSError as e:
            logger.warning("Failed to save rate limit state: %s", e)

    def _clean_old_entries(self) -> None:
        """Remove entries older than 60 seconds from sliding windows."""
        now = time.time()
        cutoff = now - 60.0

        # Clean request times
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

        # Clean token usage
        while self._token_usage and self._token_usage[0][0] < cutoff:
            self._token_usage.popleft()

    def _reset_daily_if_needed(self) -> None:
        """Reset daily counter if date has changed."""
        today = date.today().isoformat()
        if self._state.date != today:
            logger.info(
                "New day detected, resetting daily counters (was %d total on %s)",
                self._state.daily_requests,
                self._state.date or "unknown",
            )
            self._state.date = today
            self._state.daily_requests = 0
            self._state.daily_requests_by_model = {}
            self._save_state()

    def _get_current_daily_requests(self) -> int:
        """Get current daily requests for the active model."""
        return self._state.get_daily_requests(self.model)

    def _current_rpm(self) -> int:
        """Get current requests per minute count."""
        self._clean_old_entries()
        return len(self._request_times)

    def _current_tpm(self) -> int:
        """Get current tokens per minute count."""
        self._clean_old_entries()
        return sum(tokens for _, tokens in self._token_usage)

    def estimate_tokens(self, content: str) -> int:
        """
        Estimate token count for content.

        Uses a conservative estimate of ~4 characters per token.

        Args:
            content: Text content to estimate.

        Returns:
            Estimated token count.
        """
        # Add overhead for system prompt and response
        base_tokens = len(content) // CHARS_PER_TOKEN
        overhead = 1000  # System prompt, formatting, etc.
        return base_tokens + overhead

    def get_status(self) -> dict[str, Any]:
        """
        Get current rate limit status.

        Returns:
            Dictionary with current usage and limits.
        """
        with self._lock:
            self._reset_daily_if_needed()
            self._clean_old_entries()

            current_daily = self._get_current_daily_requests()

            return {
                "model": self.model,
                "rpm": {
                    "current": len(self._request_times),
                    "limit": self.rpm_limit,
                    "remaining": max(0, self.rpm_limit - len(self._request_times)),
                },
                "tpm": {
                    "current": self._current_tpm(),
                    "limit": self.tpm_limit,
                    "remaining": max(0, self.tpm_limit - self._current_tpm()),
                },
                "daily": {
                    "current": current_daily,
                    "limit": self.daily_limit,
                    "remaining": max(0, self.daily_limit - current_daily),
                },
                "daily_by_model": dict(self._state.daily_requests_by_model),
            }

    def check_limits(self, estimated_tokens: int = 0) -> tuple[bool, float, str]:
        """
        Check if a request can proceed within rate limits.

        Args:
            estimated_tokens: Estimated tokens for the request.

        Returns:
            Tuple of (can_proceed, wait_time_seconds, reason).
            If can_proceed is True, wait_time is 0 and reason is empty.
        """
        with self._lock:
            self._reset_daily_if_needed()
            self._clean_old_entries()

            now = time.time()

            # Check daily limit (per-model)
            current_daily = self._get_current_daily_requests()
            if current_daily >= self.daily_limit:
                return (
                    False,
                    0,
                    f"Daily limit reached for {self.model} ({self.daily_limit} requests)",
                )

            # Check RPM limit
            if len(self._request_times) >= self.rpm_limit:
                oldest = self._request_times[0]
                wait_time = 60.0 - (now - oldest) + 0.1  # Add small buffer
                return False, max(0, wait_time), f"RPM limit ({self.rpm_limit}/min)"

            # Check TPM limit
            current_tpm = self._current_tpm()
            if current_tpm + estimated_tokens > self.tpm_limit:
                if self._token_usage:
                    oldest_time = self._token_usage[0][0]
                    wait_time = 60.0 - (now - oldest_time) + 0.1
                else:
                    wait_time = 60.0
                return (
                    False,
                    max(0, wait_time),
                    f"TPM limit ({self.tpm_limit}/min), current: {current_tpm}",
                )

            return True, 0, ""

    def wait_if_needed(self, estimated_tokens: int = 0) -> None:
        """
        Wait if necessary to respect rate limits.

        Blocks until the request can proceed within limits.

        Args:
            estimated_tokens: Estimated tokens for the request.

        Raises:
            RateLimitError: If daily limit is exceeded.
        """
        while True:
            can_proceed, wait_time, reason = self.check_limits(estimated_tokens)

            if can_proceed:
                return

            if "Daily limit" in reason:
                raise RateLimitError(f"{reason}. Try again tomorrow.")

            logger.info("Rate limit: %s. Waiting %.1fs...", reason, wait_time)
            time.sleep(wait_time)

    def record_request(self, tokens_used: int = 0) -> None:
        """
        Record a completed request for rate limiting.

        Call this after a successful API call.

        Args:
            tokens_used: Actual tokens used (for TPM tracking).
        """
        with self._lock:
            now = time.time()

            # Record request time (for RPM)
            self._request_times.append(now)

            # Record token usage (for TPM)
            if tokens_used > 0:
                self._token_usage.append((now, tokens_used))

            # Increment daily counter for this model
            self._reset_daily_if_needed()
            self._state.increment_daily_requests(self.model)
            self._save_state()

            logger.debug(
                "Recorded request for %s: RPM=%d, TPM=%d, Daily=%d",
                self.model,
                len(self._request_times),
                self._current_tpm(),
                self._state.get_daily_requests(self.model),
            )

    def get_remaining_daily(self) -> int:
        """
        Get remaining daily requests for the current model.

        Returns:
            Number of requests remaining today for this model.
        """
        with self._lock:
            self._reset_daily_if_needed()
            current_daily = self._get_current_daily_requests()
            return max(0, self.daily_limit - current_daily)

    def get_time_until_rpm_slot(self) -> float:
        """
        Get seconds until an RPM slot opens up.

        Useful for calculating backoff when rate limited by the API.

        Returns:
            Seconds until a request slot opens, or 0 if slots available.
        """
        with self._lock:
            self._clean_old_entries()

            if len(self._request_times) < self.rpm_limit:
                return 0.0

            # Calculate when the oldest request will expire from the window
            now = time.time()
            oldest = self._request_times[0]
            wait_time = 60.0 - (now - oldest) + 0.5  # Add small buffer
            return max(0.0, wait_time)

    def mark_rate_limited(self) -> None:
        """
        Mark that we received a rate limit response from the API.

        This can help sync our internal state when the API rate limits us
        unexpectedly (e.g., due to other clients sharing the quota).
        Adds artificial entries to ensure we wait appropriately.
        """
        with self._lock:
            now = time.time()

            # If we're rate limited but don't have enough recent requests recorded,
            # it means other factors (other clients, burst limits) are in play.
            # Add entries to force waiting behavior.
            while len(self._request_times) < self.rpm_limit:
                self._request_times.append(now)

            logger.debug(
                "Marked as rate limited, RPM window now has %d entries",
                len(self._request_times),
            )


# Global rate limiter instance (initialized when first used)
_rate_limiter: RateLimiter | None = None


def get_rate_limiter(
    model: str = "",
    limits: ModelRateLimits | None = None,
    state_path: Path | None = None,
    rpm_limit: int | None = None,
    tpm_limit: int | None = None,
    daily_limit: int | None = None,
    yaml_model_limits: dict[str, dict[str, int]] | None = None,
) -> RateLimiter:
    """
    Get the global rate limiter instance.

    Args:
        model: Model name for per-model tracking.
        limits: ModelRateLimits for the model. If provided, overrides individual limits.
        state_path: Optional path for persisting daily state.
                   Only used on first call to initialize the limiter.
        rpm_limit: Requests per minute limit (auto-detected from model if None).
        tpm_limit: Tokens per minute limit (auto-detected from model if None).
        daily_limit: Requests per day limit (auto-detected from model if None).
        yaml_model_limits: Optional YAML config model limits for lookup.

    Returns:
        Configured RateLimiter instance.
    """
    global _rate_limiter

    if _rate_limiter is None:
        # Build ModelRateLimits from individual parameters if not provided
        if limits is None:
            # If individual limits are provided, use them
            if rpm_limit is not None or tpm_limit is not None or daily_limit is not None:
                # Import here to avoid circular import
                from summarize_links.config import FALLBACK_MODEL_LIMITS

                limits = ModelRateLimits(
                    rpm_limit=rpm_limit
                    if rpm_limit is not None
                    else FALLBACK_MODEL_LIMITS["rpm_limit"],
                    tpm_limit=tpm_limit
                    if tpm_limit is not None
                    else FALLBACK_MODEL_LIMITS["tpm_limit"],
                    daily_limit=daily_limit
                    if daily_limit is not None
                    else FALLBACK_MODEL_LIMITS["daily_limit"],
                )
            elif model:
                # Auto-detect limits based on model name
                from summarize_links.config import get_model_rate_limits

                limits = get_model_rate_limits(model, yaml_model_limits=yaml_model_limits)
                logger.debug(
                    "Auto-detected rate limits for model '%s': RPM=%d, TPM=%d, Daily=%d",
                    model,
                    limits.rpm_limit,
                    limits.tpm_limit,
                    limits.daily_limit,
                )
            else:
                # No model specified, use conservative defaults
                from summarize_links.config import FALLBACK_MODEL_LIMITS

                limits = ModelRateLimits(
                    rpm_limit=FALLBACK_MODEL_LIMITS["rpm_limit"],
                    tpm_limit=FALLBACK_MODEL_LIMITS["tpm_limit"],
                    daily_limit=FALLBACK_MODEL_LIMITS["daily_limit"],
                )

        _rate_limiter = RateLimiter(
            model=model,
            limits=limits,
            state_path=state_path,
        )
        logger.debug(
            "Initialized global rate limiter for model '%s': RPM=%d, TPM=%d, Daily=%d",
            _rate_limiter.model,
            _rate_limiter.rpm_limit,
            _rate_limiter.tpm_limit,
            _rate_limiter.daily_limit,
        )

    return _rate_limiter


def reset_rate_limiter() -> None:
    """Reset the global rate limiter (mainly for testing)."""
    global _rate_limiter
    _rate_limiter = None
