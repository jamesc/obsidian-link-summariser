"""
Rate limiting for the Gemini API.

This module provides rate limiting to stay within Gemini API quotas:
- 10 requests per minute (RPM)
- 250,000 tokens per minute (TPM)
- 500 requests per day

Uses a sliding window approach for per-minute limits and a simple counter
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

from summarize_links.config import (
    GEMINI_DAILY_LIMIT,
    GEMINI_RPM_LIMIT,
    GEMINI_TPM_LIMIT,
)
from summarize_links.exceptions import RateLimitError

# Module logger
logger = logging.getLogger(__name__)

# Approximate tokens per character (conservative estimate)
# Gemini uses roughly 1 token per 4 characters for English text
CHARS_PER_TOKEN = 4

# State file for daily request tracking
RATE_LIMIT_STATE_FILE = ".summarizer-rate-limit.json"


@dataclass
class RateLimitState:
    """Persistent state for rate limiting."""

    date: str = ""
    daily_requests: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "date": self.date,
            "daily_requests": self.daily_requests,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RateLimitState":
        """Create from dictionary."""
        return cls(
            date=data.get("date", ""),
            daily_requests=data.get("daily_requests", 0),
        )


@dataclass
class RateLimiter:
    """
    Rate limiter for Gemini API requests.

    Implements sliding window rate limiting for per-minute quotas
    and daily request counting with persistent storage.

    Attributes:
        rpm_limit: Maximum requests per minute.
        tpm_limit: Maximum tokens per minute.
        daily_limit: Maximum requests per day.
        state_path: Optional path for persisting daily state.
    """

    rpm_limit: int = GEMINI_RPM_LIMIT
    tpm_limit: int = GEMINI_TPM_LIMIT
    daily_limit: int = GEMINI_DAILY_LIMIT
    state_path: Path | None = None

    # Sliding window for request timestamps (for RPM)
    _request_times: deque[float] = field(default_factory=deque)

    # Sliding window for token usage (timestamp, tokens)
    _token_usage: deque[tuple[float, int]] = field(default_factory=deque)

    # Daily counter
    _state: RateLimitState = field(default_factory=RateLimitState)

    # Thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        """Initialize rate limiter and load persistent state."""
        # Reinitialize mutable defaults (dataclass quirk)
        self._request_times = deque()
        self._token_usage = deque()
        self._state = RateLimitState()
        self._lock = threading.Lock()

        # Load persistent state if path provided
        if self.state_path:
            self._load_state()

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
                "New day detected, resetting daily counter (was %d on %s)",
                self._state.daily_requests,
                self._state.date or "unknown",
            )
            self._state.date = today
            self._state.daily_requests = 0
            self._save_state()

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

            return {
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
                    "current": self._state.daily_requests,
                    "limit": self.daily_limit,
                    "remaining": max(0, self.daily_limit - self._state.daily_requests),
                },
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

            # Check daily limit
            if self._state.daily_requests >= self.daily_limit:
                return False, 0, f"Daily limit reached ({self.daily_limit} requests)"

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

            # Increment daily counter
            self._reset_daily_if_needed()
            self._state.daily_requests += 1
            self._save_state()

            logger.debug(
                "Recorded request: RPM=%d, TPM=%d, Daily=%d",
                len(self._request_times),
                self._current_tpm(),
                self._state.daily_requests,
            )

    def get_remaining_daily(self) -> int:
        """
        Get remaining daily requests.

        Returns:
            Number of requests remaining today.
        """
        with self._lock:
            self._reset_daily_if_needed()
            return max(0, self.daily_limit - self._state.daily_requests)

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
    state_path: Path | None = None,
    rpm_limit: int | None = None,
    tpm_limit: int | None = None,
    daily_limit: int | None = None,
) -> RateLimiter:
    """
    Get the global rate limiter instance.

    Args:
        state_path: Optional path for persisting daily state.
                   Only used on first call to initialize the limiter.
        rpm_limit: Requests per minute limit (uses default if None).
        tpm_limit: Tokens per minute limit (uses default if None).
        daily_limit: Requests per day limit (uses default if None).

    Returns:
        Configured RateLimiter instance.
    """
    global _rate_limiter

    if _rate_limiter is None:
        kwargs: dict[str, Any] = {"state_path": state_path}
        if rpm_limit is not None:
            kwargs["rpm_limit"] = rpm_limit
        if tpm_limit is not None:
            kwargs["tpm_limit"] = tpm_limit
        if daily_limit is not None:
            kwargs["daily_limit"] = daily_limit

        _rate_limiter = RateLimiter(**kwargs)
        logger.debug(
            "Initialized global rate limiter: RPM=%d, TPM=%d, Daily=%d",
            _rate_limiter.rpm_limit,
            _rate_limiter.tpm_limit,
            _rate_limiter.daily_limit,
        )

    return _rate_limiter


def reset_rate_limiter() -> None:
    """Reset the global rate limiter (mainly for testing)."""
    global _rate_limiter
    _rate_limiter = None
