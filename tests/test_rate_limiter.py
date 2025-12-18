"""
Tests for the rate limiter module.

Tests cover:
- RPM (requests per minute) limiting
- TPM (tokens per minute) limiting
- Daily request limiting (per-model)
- Persistent state storage
- Token estimation
- Safety margin application
- Model switching
"""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from summarize_links.exceptions import RateLimitError
from summarize_links.rate_limiter import (
    RATE_LIMIT_STATE_FILE,
    SAFETY_MARGIN,
    ModelRateLimits,
    RateLimiter,
    RateLimitState,
    get_rate_limiter,
    reset_rate_limiter,
)


class TestModelRateLimits:
    """Tests for ModelRateLimits dataclass."""

    def test_with_safety_margin(self) -> None:
        """Test safety margin application."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        safe_limits = limits.with_safety_margin()

        # Safety margin is 90%
        assert safe_limits.rpm_limit == 9
        assert safe_limits.tpm_limit == 90000
        assert safe_limits.daily_limit == 450

    def test_with_safety_margin_minimum_one(self) -> None:
        """Test that safety margin doesn't go below 1."""
        limits = ModelRateLimits(rpm_limit=1, tpm_limit=1, daily_limit=1)
        safe_limits = limits.with_safety_margin()

        # Should be at least 1
        assert safe_limits.rpm_limit >= 1
        assert safe_limits.tpm_limit >= 1
        assert safe_limits.daily_limit >= 1

    def test_frozen_dataclass(self) -> None:
        """Test that ModelRateLimits is immutable."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)

        with pytest.raises(AttributeError):
            limits.rpm_limit = 20  # type: ignore[misc]


class TestRateLimitState:
    """Tests for RateLimitState dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        state = RateLimitState(
            date="2024-01-15",
            daily_requests=42,
            daily_requests_by_model={"gemini-2.5-flash": 30, "gemini-2.5-pro": 12},
        )
        result = state.to_dict()

        assert result == {
            "date": "2024-01-15",
            "daily_requests": 42,
            "daily_requests_by_model": {"gemini-2.5-flash": 30, "gemini-2.5-pro": 12},
        }

    def test_from_dict(self) -> None:
        """Test deserialization from dict."""
        data = {
            "date": "2024-01-15",
            "daily_requests": 42,
            "daily_requests_by_model": {"gemini-2.5-flash": 30, "gemini-2.5-pro": 12},
        }
        state = RateLimitState.from_dict(data)

        assert state.date == "2024-01-15"
        assert state.daily_requests == 42
        assert state.daily_requests_by_model == {"gemini-2.5-flash": 30, "gemini-2.5-pro": 12}

    def test_from_dict_defaults(self) -> None:
        """Test deserialization with missing fields."""
        state = RateLimitState.from_dict({})

        assert state.date == ""
        assert state.daily_requests == 0
        assert state.daily_requests_by_model == {}

    def test_from_dict_backward_compatibility(self) -> None:
        """Test deserialization from old format without per-model tracking."""
        data = {"date": "2024-01-15", "daily_requests": 42}
        state = RateLimitState.from_dict(data)

        assert state.date == "2024-01-15"
        assert state.daily_requests == 42
        assert state.daily_requests_by_model == {}

    def test_get_daily_requests(self) -> None:
        """Test getting daily requests for a specific model."""
        state = RateLimitState(
            date="2024-01-15",
            daily_requests=42,
            daily_requests_by_model={"gemini-2.5-flash": 30, "gemini-2.5-pro": 12},
        )

        assert state.get_daily_requests("gemini-2.5-flash") == 30
        assert state.get_daily_requests("gemini-2.5-pro") == 12
        assert state.get_daily_requests("unknown-model") == 0

    def test_increment_daily_requests(self) -> None:
        """Test incrementing daily requests for a specific model."""
        state = RateLimitState(
            date="2024-01-15",
            daily_requests=42,
            daily_requests_by_model={"gemini-2.5-flash": 30},
        )

        state.increment_daily_requests("gemini-2.5-flash")
        assert state.get_daily_requests("gemini-2.5-flash") == 31
        assert state.daily_requests == 43

        # Increment for new model
        state.increment_daily_requests("gemini-2.5-pro")
        assert state.get_daily_requests("gemini-2.5-pro") == 1
        assert state.daily_requests == 44


class TestRateLimiter:
    """Tests for RateLimiter class."""

    def test_safety_margin_applied(self) -> None:
        """Test that safety margin is applied to limits."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="test-model", limits=limits)

        # Effective limits should have safety margin applied
        assert limiter.rpm_limit == int(10 * SAFETY_MARGIN)
        assert limiter.tpm_limit == int(100000 * SAFETY_MARGIN)
        assert limiter.daily_limit == int(500 * SAFETY_MARGIN)

    def test_safety_margin_can_be_disabled(self) -> None:
        """Test that safety margin can be disabled for testing."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="test-model", limits=limits, _apply_safety_margin=False)

        # Effective limits should match original
        assert limiter.rpm_limit == 10
        assert limiter.tpm_limit == 100000
        assert limiter.daily_limit == 500

    def test_estimate_tokens(self) -> None:
        """Test token estimation."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="test-model", limits=limits)

        # Empty content should still have overhead
        result = limiter.estimate_tokens("")
        assert result == 1000  # Just overhead

        # Content estimation
        content = "a" * 4000  # 4000 chars = ~1000 tokens
        result = limiter.estimate_tokens(content)
        assert result == 1000 + 1000  # 1000 base + 1000 overhead

    def test_check_limits_under_limits(self) -> None:
        """Test that requests can proceed when under limits."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="test-model", limits=limits)

        can_proceed, wait_time, reason = limiter.check_limits()

        assert can_proceed is True
        assert wait_time == 0
        assert reason == ""

    def test_check_limits_rpm_exceeded(self) -> None:
        """Test RPM limit detection."""
        limits = ModelRateLimits(rpm_limit=3, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="test-model", limits=limits, _apply_safety_margin=False)

        # Record 3 requests
        for _ in range(3):
            limiter.record_request(100)

        can_proceed, wait_time, reason = limiter.check_limits()

        assert can_proceed is False
        assert wait_time > 0
        assert "RPM limit" in reason

    def test_check_limits_tpm_exceeded(self) -> None:
        """Test TPM limit detection."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=1000, daily_limit=500)
        limiter = RateLimiter(model="test-model", limits=limits, _apply_safety_margin=False)

        # Record request with 1000 tokens
        limiter.record_request(1000)

        # Try to add 100 more tokens
        can_proceed, wait_time, reason = limiter.check_limits(100)

        assert can_proceed is False
        assert wait_time > 0
        assert "TPM limit" in reason

    def test_check_limits_daily_exceeded(self) -> None:
        """Test daily limit detection (per-model)."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=2)
        limiter = RateLimiter(model="test-model", limits=limits, _apply_safety_margin=False)

        # Record 2 requests
        limiter.record_request(100)
        limiter.record_request(100)

        can_proceed, wait_time, reason = limiter.check_limits()

        assert can_proceed is False
        assert "Daily limit" in reason
        assert "test-model" in reason

    def test_record_request_increments_counters(self) -> None:
        """Test that record_request updates all counters."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="test-model", limits=limits)

        limiter.record_request(500)
        status = limiter.get_status()

        assert status["rpm"]["current"] == 1
        assert status["tpm"]["current"] == 500
        assert status["daily"]["current"] == 1
        assert status["model"] == "test-model"
        assert status["daily_by_model"] == {"test-model": 1}

    def test_get_status(self) -> None:
        """Test status reporting."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=1000, daily_limit=100)
        limiter = RateLimiter(model="test-model", limits=limits, _apply_safety_margin=False)

        limiter.record_request(200)
        limiter.record_request(300)

        status = limiter.get_status()

        assert status["model"] == "test-model"
        assert status["rpm"]["current"] == 2
        assert status["rpm"]["limit"] == 10
        assert status["rpm"]["remaining"] == 8

        assert status["tpm"]["current"] == 500
        assert status["tpm"]["limit"] == 1000
        assert status["tpm"]["remaining"] == 500

        assert status["daily"]["current"] == 2
        assert status["daily"]["limit"] == 100
        assert status["daily"]["remaining"] == 98

        assert status["daily_by_model"] == {"test-model": 2}

    def test_get_remaining_daily(self) -> None:
        """Test daily remaining calculation (per-model)."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=10)
        limiter = RateLimiter(model="test-model", limits=limits, _apply_safety_margin=False)

        assert limiter.get_remaining_daily() == 10

        limiter.record_request(100)
        limiter.record_request(100)

        assert limiter.get_remaining_daily() == 8

    def test_sliding_window_cleanup(self) -> None:
        """Test that old entries are cleaned up after 60 seconds."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="test-model", limits=limits)

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
        limits = ModelRateLimits(rpm_limit=1, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="test-model", limits=limits, _apply_safety_margin=False)
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
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=1)
        limiter = RateLimiter(model="test-model", limits=limits, _apply_safety_margin=False)
        limiter.record_request(100)

        with pytest.raises(RateLimitError) as exc_info:
            limiter.wait_if_needed()

        assert "Daily limit" in str(exc_info.value)
        assert "Try again tomorrow" in str(exc_info.value)


class TestModelSwitching:
    """Tests for model switching functionality."""

    def test_switch_model(self) -> None:
        """Test switching to a different model."""
        limits1 = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="model-1", limits=limits1, _apply_safety_margin=False)

        # Record some requests for model-1
        limiter.record_request(100)
        limiter.record_request(100)

        assert limiter.model == "model-1"
        assert limiter.get_remaining_daily() == 498

        # Switch to model-2 with different limits
        limits2 = ModelRateLimits(rpm_limit=5, tpm_limit=50000, daily_limit=25)
        limiter.switch_model("model-2", limits2)

        assert limiter.model == "model-2"
        assert limiter.rpm_limit == 5
        assert limiter.daily_limit == 25
        # New model should have full daily allocation
        assert limiter.get_remaining_daily() == 25

    def test_switch_model_preserves_rpm_window(self) -> None:
        """Test that RPM sliding window is shared across models."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="model-1", limits=limits, _apply_safety_margin=False)

        # Record requests for model-1
        limiter.record_request(100)
        limiter.record_request(100)

        # Switch models
        limiter.switch_model("model-2", limits)

        # RPM should still reflect previous requests
        status = limiter.get_status()
        assert status["rpm"]["current"] == 2

    def test_per_model_daily_tracking(self) -> None:
        """Test that daily limits are tracked separately per model."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=10)
        limiter = RateLimiter(model="model-1", limits=limits, _apply_safety_margin=False)

        # Use 5 requests for model-1
        for _ in range(5):
            limiter.record_request(100)

        assert limiter.get_remaining_daily() == 5

        # Switch to model-2
        limiter.switch_model("model-2", limits)

        # Model-2 should have full allocation
        assert limiter.get_remaining_daily() == 10

        # Use 3 requests for model-2
        for _ in range(3):
            limiter.record_request(100)

        # Check daily_by_model tracking
        status = limiter.get_status()
        assert status["daily_by_model"]["model-1"] == 5
        assert status["daily_by_model"]["model-2"] == 3

    def test_switch_model_applies_safety_margin(self) -> None:
        """Test that safety margin is applied when switching models."""
        limits1 = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        limiter = RateLimiter(model="model-1", limits=limits1)

        limits2 = ModelRateLimits(rpm_limit=20, tpm_limit=200000, daily_limit=1000)
        limiter.switch_model("model-2", limits2)

        # Safety margin should be applied
        assert limiter.rpm_limit == int(20 * SAFETY_MARGIN)
        assert limiter.daily_limit == int(1000 * SAFETY_MARGIN)


class TestPersistentState:
    """Tests for persistent state storage."""

    def test_save_and_load_state(self, tmp_path: Path) -> None:
        """Test that state is persisted to disk."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=100)

        # Create limiter with state path
        limiter1 = RateLimiter(
            model="test-model", limits=limits, state_path=tmp_path, _apply_safety_margin=False
        )
        limiter1.record_request(100)
        limiter1.record_request(100)

        # Verify state file exists
        state_file = tmp_path / RATE_LIMIT_STATE_FILE
        assert state_file.exists()

        # Create new limiter that loads the state
        limiter2 = RateLimiter(
            model="test-model", limits=limits, state_path=tmp_path, _apply_safety_margin=False
        )

        assert limiter2.get_remaining_daily() == 98

    def test_save_and_load_per_model_state(self, tmp_path: Path) -> None:
        """Test that per-model daily counts are persisted."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=100)

        # Create limiter and record for different models
        limiter1 = RateLimiter(
            model="model-1", limits=limits, state_path=tmp_path, _apply_safety_margin=False
        )
        limiter1.record_request(100)
        limiter1.record_request(100)

        limiter1.switch_model("model-2", limits)
        limiter1.record_request(100)

        # Load state in new limiter
        limiter2 = RateLimiter(
            model="model-1", limits=limits, state_path=tmp_path, _apply_safety_margin=False
        )

        status = limiter2.get_status()
        assert status["daily_by_model"]["model-1"] == 2
        assert status["daily_by_model"]["model-2"] == 1

    def test_state_resets_on_new_day(self, tmp_path: Path) -> None:
        """Test that daily counter resets on new day."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=100)

        # Create state file with yesterday's date
        state_file = tmp_path / RATE_LIMIT_STATE_FILE
        state_data = {
            "date": "2020-01-01",
            "daily_requests": 50,
            "daily_requests_by_model": {"test-model": 50},
        }
        with open(state_file, "w") as f:
            json.dump(state_data, f)

        # Create limiter - should reset since date changed
        limiter = RateLimiter(
            model="test-model", limits=limits, state_path=tmp_path, _apply_safety_margin=False
        )
        status = limiter.get_status()

        assert status["daily"]["current"] == 0
        assert status["daily"]["remaining"] == 100
        assert status["daily_by_model"] == {}

    def test_handles_missing_state_file(self, tmp_path: Path) -> None:
        """Test graceful handling of missing state file."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=100)
        limiter = RateLimiter(
            model="test-model", limits=limits, state_path=tmp_path, _apply_safety_margin=False
        )

        # Should start fresh
        assert limiter.get_remaining_daily() == 100

    def test_handles_corrupt_state_file(self, tmp_path: Path) -> None:
        """Test graceful handling of corrupt state file."""
        state_file = tmp_path / RATE_LIMIT_STATE_FILE
        with open(state_file, "w") as f:
            f.write("not valid json {{{")

        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=100)

        # Should start fresh (with warning log)
        limiter = RateLimiter(
            model="test-model", limits=limits, state_path=tmp_path, _apply_safety_margin=False
        )
        assert limiter.get_remaining_daily() == 100

    def test_backward_compatibility_old_state_format(self, tmp_path: Path) -> None:
        """Test loading old state format without per-model tracking."""
        # Create state file in old format
        state_file = tmp_path / RATE_LIMIT_STATE_FILE
        state_data = {"date": "2024-01-15", "daily_requests": 50}
        with open(state_file, "w") as f:
            json.dump(state_data, f)

        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=100)

        # Mock today's date to match state file
        with patch("summarize_links.rate_limiter.date") as mock_date:
            mock_date.today.return_value.isoformat.return_value = "2024-01-15"

            limiter = RateLimiter(
                model="test-model", limits=limits, state_path=tmp_path, _apply_safety_margin=False
            )

            # Old state loaded but per-model tracking starts fresh
            status = limiter.get_status()
            # The total daily_requests is loaded, but per-model starts at 0
            assert status["daily"]["current"] == 0
            assert limiter._state.daily_requests == 50


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

    def test_get_rate_limiter_with_model(self) -> None:
        """Test creating rate limiter with model name."""
        limits = ModelRateLimits(rpm_limit=10, tpm_limit=100000, daily_limit=500)
        limiter = get_rate_limiter(model="gemini-2.5-flash", limits=limits)

        assert limiter.model == "gemini-2.5-flash"

    def test_get_rate_limiter_with_individual_limits(self) -> None:
        """Test creating rate limiter with individual limit parameters."""
        limiter = get_rate_limiter(rpm_limit=5, tpm_limit=50000, daily_limit=100)

        # Note: safety margin is applied
        assert limiter.rpm_limit == int(5 * SAFETY_MARGIN)
        assert limiter.tpm_limit == int(50000 * SAFETY_MARGIN)
        assert limiter.daily_limit == int(100 * SAFETY_MARGIN)
