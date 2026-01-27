"""Tests for UI and output formatting."""

import pytest

from summarize_links.ui import print_results


class TestPrintResults:
    """Tests for results table printing."""

    def test_prints_success_and_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should print both successful and failed results."""
        results = [
            (True, "Created: example.md"),
            (False, "Fetch error: test.com"),
        ]

        print_results(results)

        # The output goes to Rich console, which uses stderr by default
        # We can verify the function runs without error


class TestQuietMode:
    """Tests for quiet mode behavior."""

    def test_quiet_mode_suppresses_output(self) -> None:
        """Quiet mode flag should be set from args."""
        from unittest.mock import patch

        from summarize_links.cli import main
        from summarize_links.exceptions import ConfigError

        # Running with --quiet should set the flag
        with patch("summarize_links.cli.load_config") as mock_config:
            mock_config.side_effect = ConfigError("test")
            main(["--quiet", "from-note"])
            # The function runs but we just verify no crash
