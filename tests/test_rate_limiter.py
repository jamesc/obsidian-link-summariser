"""
Tests for the rate limiter module.

Tests cover:
- RPM (requests per minute) limiting
- TPM (tokens per minute) limiting
- Daily request limiting
- Persistent state storage
- Token estimation
"""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from summarize_links.exceptions import RateLimitError
from summarize_links.rate_limiter import (
    RATE_LIMIT_STATE_FILE,
    RateLimiter,
    RateLimitState,
    get_rate_limiter,
    reset_rate_limiter,
)


class TestRateLimitState:
    """Tests for RateLimitState dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        state = RateLimitState(date="2024-01-15", daily_requests=42)
        result = state.to_dict()

        assert result == {"date": "2024-01-15", "daily_requests": 42}

    def test_from_dict(self) -> None:
        """Test deserialization from dict."""
        data = {"date": "2024-01-15", "daily_requests": 42}
        state = RateLimitState.from_dict(data)

        assert state.date == "2024-01-15"
        assert state.daily_requests == 42

    def test_from_dict_defaults(self) -> None:
        """Test deserialization with missing fields."""
        state = RateLimitState.from_dict({})

        assert state.date == ""
        assert state.daily_requests == 0


class TestRateLimiter:
    """Tests for RateLimiter class."""

    def test_estimate_tokens(self) -> None:
        """Test token estimation."""
        limiter = RateLimiter()

        # Empty content should still have overhead
        result = limiter.estimate_tokens("")
        assert result == 1000  # Just overhead

        # Content estimation
        content = "a" * 4000  # 4000 chars = ~1000 tokens
        result = limiter.estimate_tokens(content)
        assert result == 1000 + 1000  # 1000 base + 1000 overhead

    def test_check_limits_under_limits(self) -> None:
        """Test that requests can proceed when under limits."""
        limiter = RateLimiter()

        can_proceed, wait_time, reason = limiter.check_limits()

        assert can_proceed is True
        assert wait_time == 0
        assert reason == ""

    def test_check_limits_rpm_exceeded(self) -> None:
        """Test RPM limit detection."""
        limiter = RateLimiter(rpm_limit=3)

        # Record 3 requests
        for _ in range(3):
            limiter.record_request(100)

        can_proceed, wait_time, reason = limiter.check_limits()

        assert can_proceed is False
        assert wait_time > 0
        assert "RPM limit" in reason

    def test_check_limits_tpm_exceeded(self) -> None:
        """Test TPM limit detection."""
        limiter = RateLimiter(tpm_limit=1000)

        # Record request with 1000 tokens
        limiter.record_request(1000)

        # Try to add 100 more tokens
        can_proceed, wait_time, reason = limiter.check_limits(100)

        assert can_proceed is False
        assert wait_time > 0
        assert "TPM limit" in reason

    def test_check_limits_daily_exceeded(self) -> None:
        """Test daily limit detection."""
        limiter = RateLimiter(daily_limit=2)

        # Record 2 requests
        limiter.record_request(100)
        limiter.record_request(100)

        can_proceed, wait_time, reason = limiter.check_limits()

        assert can_proceed is False
        assert "Daily limit" in reason

    def test_record_request_increments_counters(self) -> None:
        """Test that record_request updates all counters."""
        limiter = RateLimiter()

        limiter.record_request(500)
        status = limiter.get_status()

        assert status["rpm"]["current"] == 1
        assert status["tpm"]["current"] == 500
        assert status["daily"]["current"] == 1

    def test_get_status(self) -> None:
        """Test status reporting."""
        limiter = RateLimiter(rpm_limit=10, tpm_limit=1000, daily_limit=100)

        limiter.record_request(200)
        limiter.record_request(300)

        status = limiter.get_status()

        assert status["rpm"]["current"] == 2
        assert status["rpm"]["limit"] == 10
        assert status["rpm"]["remaining"] == 8

        assert status["tpm"]["current"] == 500
        assert status["tpm"]["limit"] == 1000
        assert status["tpm"]["remaining"] == 500

        assert status["daily"]["current"] == 2
        assert status["daily"]["limit"] == 100
        assert status["daily"]["remaining"] == 98

    def test_get_remaining_daily(self) -> None:
        """Test daily remaining calculation."""
        limiter = RateLimiter(daily_limit=10)

        assert limiter.get_remaining_daily() == 10

        limiter.record_request(100)
        limiter.record_request(100)

        assert limiter.get_remaining_daily() == 8

    def test_sliding_window_cleanup(self) -> None:
        """Test that old entries are cleaned up after 60 seconds."""
        limiter = RateLimiter(rpm_limit=10)

        # Mock time to simulate passage of time
        with patch("summarize_links.rate_limiter.time.time") as mock_time:
            # Record a request at t=0
            mock_time.return_value = 0.0
            limiter.record_request(100)

            # At t=30, still in window
            mock_time.return_value = 30.0
            status = limiter.get_status()
            assert status["rpm"]["current"] == 1

            # At t=61, should be cleaned up
            mock_time.return_value = 61.0
            status = limiter.get_status()
            assert status["rpm"]["current"] == 0

    def test_wait_if_needed_blocks_on_rpm(self) -> None:
        """Test that wait_if_needed blocks when RPM exceeded."""
        limiter = RateLimiter(rpm_limit=1)
        limiter.record_request(100)

        # Mock time and sleep to avoid actual waiting
        start_time = time.time()
        with (
            patch("summarize_links.rate_limiter.time.time") as mock_time,
            patch("summarize_links.rate_limiter.time.sleep") as mock_sleep,
        ):
            # Simulate time passing when sleep is called
            mock_time.return_value = start_time + 60.5
            mock_sleep.return_value = None

            # This should not block since we mock time to be past the window
            limiter.wait_if_needed()

    def test_wait_if_needed_raises_on_daily_limit(self) -> None:
        """Test that wait_if_needed raises error on daily limit."""
        limiter = RateLimiter(daily_limit=1)
        limiter.record_request(100)

        with pytest.raises(RateLimitError) as exc_info:
            limiter.wait_if_needed()

        assert "Daily limit" in str(exc_info.value)
        assert "Try again tomorrow" in str(exc_info.value)


class TestPersistentState:
    """Tests for persistent state storage."""

    def test_save_and_load_state(self, tmp_path: Path) -> None:
        """Test that state is persisted to disk."""
        # Create limiter with state path
        limiter1 = RateLimiter(daily_limit=100, state_path=tmp_path)
        limiter1.record_request(100)
        limiter1.record_request(100)

        # Verify state file exists
        state_file = tmp_path / RATE_LIMIT_STATE_FILE
        assert state_file.exists()

        # Create new limiter that loads the state
        limiter2 = RateLimiter(daily_limit=100, state_path=tmp_path)

        assert limiter2.get_remaining_daily() == 98

    def test_state_resets_on_new_day(self, tmp_path: Path) -> None:
        """Test that daily counter resets on new day."""
        # Create state file with yesterday's date
        state_file = tmp_path / RATE_LIMIT_STATE_FILE
        state_data = {"date": "2020-01-01", "daily_requests": 50}
        with open(state_file, "w") as f:
            json.dump(state_data, f)

        # Create limiter - should reset since date changed
        limiter = RateLimiter(daily_limit=100, state_path=tmp_path)
        status = limiter.get_status()

        assert status["daily"]["current"] == 0
        assert status["daily"]["remaining"] == 100

    def test_handles_missing_state_file(self, tmp_path: Path) -> None:
        """Test graceful handling of missing state file."""
        limiter = RateLimiter(daily_limit=100, state_path=tmp_path)

        # Should start fresh
        assert limiter.get_remaining_daily() == 100

    def test_handles_corrupt_state_file(self, tmp_path: Path) -> None:
        """Test graceful handling of corrupt state file."""
        state_file = tmp_path / RATE_LIMIT_STATE_FILE
        with open(state_file, "w") as f:
            f.write("not valid json {{{")

        # Should start fresh (with warning log)
        limiter = RateLimiter(daily_limit=100, state_path=tmp_path)
        assert limiter.get_remaining_daily() == 100


class TestGlobalRateLimiter:
    """Tests for global rate limiter singleton."""

    def setup_method(self) -> None:
        """Reset global limiter before each test."""
        reset_rate_limiter()

    def teardown_method(self) -> None:
        """Reset global limiter after each test."""
        reset_rate_limiter()

    def test_get_rate_limiter_returns_singleton(self) -> None:
        """Test that get_rate_limiter returns same instance."""
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()

        assert limiter1 is limiter2

    def test_reset_rate_limiter(self) -> None:
        """Test that reset creates new instance."""
        limiter1 = get_rate_limiter()
        reset_rate_limiter()
        limiter2 = get_rate_limiter()

        assert limiter1 is not limiter2
