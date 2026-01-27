"""Tests for the status command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from summarize_links.cli import EXIT_SUCCESS
from summarize_links.commands import cmd_status
from summarize_links.config import Config


class TestCmdStatus:
    """Tests for the status command."""

    @patch("summarize_links.commands.status.get_rate_limiter")
    def test_displays_rate_limit_info(
        self,
        mock_get_limiter: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should display rate limit information."""
        mock_limiter = MagicMock()
        mock_limiter.get_status.return_value = {
            "rpm": {"current": 2, "limit": 5, "remaining": 3},
            "tpm": {"current": 1000, "limit": 250000, "remaining": 249000},
            "daily": {"current": 10, "limit": 100, "remaining": 90},
        }
        mock_get_limiter.return_value = mock_limiter

        # cmd_status is now imported at module level

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_status(config)

        assert result == EXIT_SUCCESS
        mock_limiter.get_status.assert_called_once()

    @patch("summarize_links.commands.status.get_rate_limiter")
    def test_warns_on_low_daily_quota(
        self,
        mock_get_limiter: MagicMock,
        mock_vault: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Should warn when daily quota is low."""
        mock_limiter = MagicMock()
        mock_limiter.get_status.return_value = {
            "rpm": {"current": 0, "limit": 5, "remaining": 5},
            "tpm": {"current": 0, "limit": 250000, "remaining": 250000},
            "daily": {"current": 95, "limit": 100, "remaining": 5},  # Low!
        }
        mock_get_limiter.return_value = mock_limiter

        # cmd_status is now imported at module level

        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )

        result = cmd_status(config)

        assert result == EXIT_SUCCESS
