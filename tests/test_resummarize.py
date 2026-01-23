"""
Tests for the resummarize command.

Tests the scan_summaries_for_resummarize function and cmd_resummarize CLI command.
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from summarize_links.commands import cmd_resummarize
from summarize_links.config import Config
from summarize_links.notes import scan_summaries_for_resummarize


class TestScanSummariesForResumarize:
    """Tests for scan_summaries_for_resummarize function."""

    def test_empty_folder(self, tmp_path: Path) -> None:
        """Test scanning when summaries folder doesn't exist."""
        vault = tmp_path / "vault"
        vault.mkdir()

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert results == []

    def test_success_summaries(self, tmp_path: Path) -> None:
        """Test finding successful summaries."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        # Create a successful summary
        summary1 = summaries / "2024-01-01-example.md"
        summary1.write_text(
            """---
source: https://example.com
date: 2024-01-01
summary_status: success
summary_date: 2024-01-01 10:30:00
---

Summary content here.
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 1
        url, orig_date, summ_date, _ = results[0]
        assert url == "https://example.com"
        assert orig_date == datetime(2024, 1, 1)
        assert summ_date == datetime(2024, 1, 1, 10, 30, 0)

    def test_skips_error_summaries(self, tmp_path: Path) -> None:
        """Test that error summaries are skipped."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        # Create an error summary
        (summaries / "2024-01-01-error.md").write_text(
            """---
source: https://example.com
date: 2024-01-01
summary_status: error
---

## Summary Unavailable
""",
            encoding="utf-8",
        )

        # Create a fetch_error summary
        (summaries / "2024-01-02-error2.md").write_text(
            """---
source: https://example2.com
date: 2024-01-02
summary_status: fetch_error
---

## Summary Unavailable
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 0

    def test_date_parsing_with_time(self, tmp_path: Path) -> None:
        """Test parsing summary_date with time component."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        (summaries / "2024-01-01-test.md").write_text(
            """---
source: https://example.com
date: 2024-01-01
summary_status: success
summary_date: 2024-01-15 14:25:33
---

Content.
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 1
        url, orig_date, summ_date, _ = results[0]
        assert orig_date == datetime(2024, 1, 1)
        assert summ_date == datetime(2024, 1, 15, 14, 25, 33)

    def test_date_parsing_date_only(self, tmp_path: Path) -> None:
        """Test parsing summary_date with date-only format."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        (summaries / "2024-01-01-test.md").write_text(
            """---
source: https://example.com
date: 2024-01-01
summary_status: success
summary_date: 2024-01-10
---

Content.
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 1
        url, orig_date, summ_date, _ = results[0]
        assert orig_date == datetime(2024, 1, 1)
        assert summ_date == datetime(2024, 1, 10)

    def test_missing_summary_date_uses_original_date(self, tmp_path: Path) -> None:
        """Test that missing summary_date falls back to original date."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        (summaries / "2024-01-01-test.md").write_text(
            """---
source: https://example.com
date: 2024-01-01
summary_status: success
---

Content.
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 1
        url, orig_date, summ_date, _ = results[0]
        assert orig_date == datetime(2024, 1, 1)
        assert summ_date == datetime(2024, 1, 1)  # Falls back to original date

    def test_invalid_date_format_skips_file(self, tmp_path: Path) -> None:
        """Test that files with invalid date formats are skipped."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        # Create file with invalid date format
        (summaries / "2024-01-01-invalid.md").write_text(
            """---
source: https://example.com
date: not-a-date
summary_status: success
---

Content.
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 0

    def test_invalid_summary_date_uses_original_date(self, tmp_path: Path) -> None:
        """Test that invalid summary_date falls back to original date."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        (summaries / "2024-01-01-test.md").write_text(
            """---
source: https://example.com
date: 2024-01-01
summary_status: success
summary_date: invalid-date-format
---

Content.
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 1
        url, orig_date, summ_date, _ = results[0]
        assert orig_date == datetime(2024, 1, 1)
        assert summ_date == datetime(2024, 1, 1)  # Falls back

    def test_sorted_by_original_date(self, tmp_path: Path) -> None:
        """Test that results are sorted by original date (oldest first)."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        # Create summaries in random order
        (summaries / "2024-03-15-third.md").write_text(
            """---
source: https://example3.com
date: 2024-03-15
summary_status: success
---
""",
            encoding="utf-8",
        )

        (summaries / "2024-01-01-first.md").write_text(
            """---
source: https://example1.com
date: 2024-01-01
summary_status: success
---
""",
            encoding="utf-8",
        )

        (summaries / "2024-02-10-second.md").write_text(
            """---
source: https://example2.com
date: 2024-02-10
summary_status: success
---
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 3
        # Check order (newest first)
        assert results[0][1] == datetime(2024, 3, 15)
        assert results[1][1] == datetime(2024, 2, 10)
        assert results[2][1] == datetime(2024, 1, 1)

    def test_mixed_statuses(self, tmp_path: Path) -> None:
        """Test filtering with mixed summary statuses."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        # Success - should be included
        (summaries / "2024-01-01-success.md").write_text(
            """---
source: https://example1.com
date: 2024-01-01
summary_status: success
---
""",
            encoding="utf-8",
        )

        # Error - should be skipped
        (summaries / "2024-01-03-error.md").write_text(
            """---
source: https://example3.com
date: 2024-01-03
summary_status: error
---
""",
            encoding="utf-8",
        )

        # Success - should be included
        (summaries / "2024-01-04-success2.md").write_text(
            """---
source: https://example4.com
date: 2024-01-04
summary_status: success
---
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 2
        assert results[0][0] == "https://example4.com"  # 2024-01-04 (newest)
        assert results[1][0] == "https://example1.com"  # 2024-01-01 (oldest)

    def test_missing_source_url_skips_file(self, tmp_path: Path) -> None:
        """Test that files without source URL are skipped."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        (summaries / "2024-01-01-no-source.md").write_text(
            """---
date: 2024-01-01
summary_status: success
---

Content without source.
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 0

    def test_no_status_field_includes_summary(self, tmp_path: Path) -> None:
        """Test that summaries without status field are included."""
        vault = tmp_path / "vault"
        summaries = vault / "Summaries"
        summaries.mkdir(parents=True)

        (summaries / "2024-01-01-no-status.md").write_text(
            """---
source: https://example.com
date: 2024-01-01
---

Content without explicit status.
""",
            encoding="utf-8",
        )

        results = scan_summaries_for_resummarize(vault, "Summaries")

        assert len(results) == 1
        assert results[0][0] == "https://example.com"


class TestCmdResumarize:
    """Tests for cmd_resummarize command."""

    @patch("summarize_links.commands.resummarize.process_resummarize_batch")
    @patch("summarize_links.commands.resummarize.scan_summaries_for_resummarize")
    def test_no_summaries_found(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_config: Config,
    ) -> None:
        """Should return success when no summaries to resummarize."""
        mock_scan.return_value = []

        result = cmd_resummarize(mock_config)

        assert result == 0  # EXIT_SUCCESS
        mock_process.assert_not_called()

    @patch("summarize_links.commands.resummarize.process_resummarize_batch")
    @patch("summarize_links.commands.resummarize.scan_summaries_for_resummarize")
    def test_basic_resummarize(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_config: Config,
    ) -> None:
        """Test basic resummarize without age filter."""
        mock_scan.return_value = [
            ("https://example1.com", datetime(2024, 1, 1), datetime(2024, 1, 1, 10, 0), None),
            ("https://example2.com", datetime(2024, 1, 2), datetime(2024, 1, 2, 11, 0), None),
        ]
        mock_process.return_value = (0, [])

        result = cmd_resummarize(mock_config)

        assert result == 0
        # Verify force mode is enabled
        assert mock_config.force is True
        # Verify process was called with correct URLs
        mock_process.assert_called_once()
        call_args = mock_process.call_args[0]
        url_contexts = call_args[0]
        assert len(url_contexts) == 2
        assert url_contexts[0].url == "https://example1.com"
        assert url_contexts[1].url == "https://example2.com"

    @patch("summarize_links.commands.resummarize.datetime")
    @patch("summarize_links.commands.resummarize.process_resummarize_batch")
    @patch("summarize_links.commands.resummarize.scan_summaries_for_resummarize")
    def test_age_filtering(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_datetime: MagicMock,
        mock_config: Config,
    ) -> None:
        """Test age filtering with --age flag."""
        # Mock datetime.now() to return a fixed date
        fixed_now = datetime(2024, 1, 20, 12, 0, 0)
        mock_datetime.now.return_value = fixed_now

        old_date = datetime(2024, 1, 5)  # 15 days ago
        recent_date = datetime(2024, 1, 18)  # 2 days ago

        mock_scan.return_value = [
            ("https://old.com", datetime(2024, 1, 1), old_date, None),
            ("https://recent.com", datetime(2024, 1, 2), recent_date, None),
        ]
        mock_process.return_value = (0, [])

        result = cmd_resummarize(mock_config, age_days=5)

        assert result == 0
        # Verify only old summary was processed
        mock_process.assert_called_once()
        call_args = mock_process.call_args[0]
        url_contexts = call_args[0]
        assert len(url_contexts) == 1
        assert url_contexts[0].url == "https://old.com"

    @patch("summarize_links.commands.resummarize.datetime")
    @patch("summarize_links.commands.resummarize.process_resummarize_batch")
    @patch("summarize_links.commands.resummarize.scan_summaries_for_resummarize")
    def test_no_summaries_within_age_filter(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_datetime: MagicMock,
        mock_config: Config,
    ) -> None:
        """Test when all summaries are filtered out by age."""
        # Mock datetime.now() to return a fixed date
        fixed_now = datetime(2024, 1, 20, 12, 0, 0)
        mock_datetime.now.return_value = fixed_now

        recent_date = datetime(2024, 1, 18)  # 2 days ago

        mock_scan.return_value = [
            ("https://recent1.com", datetime(2024, 1, 1), recent_date, None),
            ("https://recent2.com", datetime(2024, 1, 2), recent_date, None),
        ]

        result = cmd_resummarize(mock_config, age_days=5)

        assert result == 0
        mock_process.assert_not_called()

    @patch("summarize_links.commands.resummarize.process_resummarize_batch")
    @patch("summarize_links.commands.resummarize.scan_summaries_for_resummarize")
    def test_max_links_limiting(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_config: Config,
    ) -> None:
        """Test max_links limits number of summaries processed."""
        mock_scan.return_value = [
            ("https://example1.com", datetime(2024, 1, 1), datetime(2024, 1, 1), None),
            ("https://example2.com", datetime(2024, 1, 2), datetime(2024, 1, 2), None),
            ("https://example3.com", datetime(2024, 1, 3), datetime(2024, 1, 3), None),
            ("https://example4.com", datetime(2024, 1, 4), datetime(2024, 1, 4), None),
            ("https://example5.com", datetime(2024, 1, 5), datetime(2024, 1, 5), None),
        ]
        mock_process.return_value = (0, [])
        mock_config.max_links = 3

        result = cmd_resummarize(mock_config)

        assert result == 0
        mock_process.assert_called_once()
        call_args = mock_process.call_args[0]
        url_contexts = call_args[0]
        assert len(url_contexts) == 3

    @patch("summarize_links.commands.resummarize.process_resummarize_batch")
    @patch("summarize_links.commands.resummarize.scan_summaries_for_resummarize")
    def test_force_mode_enabled(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_config: Config,
    ) -> None:
        """Test that force mode is automatically enabled."""
        mock_scan.return_value = [
            ("https://example.com", datetime(2024, 1, 1), datetime(2024, 1, 1), None),
        ]
        mock_process.return_value = (0, [])
        mock_config.force = False

        cmd_resummarize(mock_config)

        assert mock_config.force is True

    @patch("summarize_links.commands.resummarize.process_resummarize_batch")
    @patch("summarize_links.commands.resummarize.scan_summaries_for_resummarize")
    def test_preserves_original_dates(
        self,
        mock_scan: MagicMock,
        mock_process: MagicMock,
        mock_config: Config,
    ) -> None:
        """Test that original dates are passed to batch processor."""
        orig_date1 = datetime(2024, 1, 1)
        orig_date2 = datetime(2024, 1, 2)
        summ_date1 = datetime(2024, 1, 10)
        summ_date2 = datetime(2024, 1, 11)

        mock_scan.return_value = [
            ("https://example1.com", orig_date1, summ_date1, None),
            ("https://example2.com", orig_date2, summ_date2, None),
        ]
        mock_process.return_value = (0, [])

        cmd_resummarize(mock_config)

        mock_process.assert_called_once()
        call_args = mock_process.call_args[0]
        url_dates = call_args[1]
        # Check that original dates (not summary dates) are preserved
        assert url_dates["https://example1.com"] == orig_date1
        assert url_dates["https://example2.com"] == orig_date2
