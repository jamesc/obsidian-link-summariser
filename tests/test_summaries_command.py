"""
Tests for the summaries command.

Tests the scan_summaries function and cmd_summaries CLI command.
"""

from datetime import datetime
from pathlib import Path

from summarize_links.notes import scan_summaries, scan_summaries_for_resummarize


def test_scan_summaries_empty_folder(tmp_path: Path) -> None:
    """Test scanning when summaries folder doesn't exist."""
    vault = tmp_path / "vault"
    vault.mkdir()

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 0
    assert stats["success"] == 0
    assert stats["error"] == 0
    assert stats["unknown"] == 0
    assert stats["oldest_date"] is None
    assert stats["newest_date"] is None
    assert stats["error_summaries"] == []
    assert stats["unknown_summaries"] == []


def test_scan_summaries_with_success(tmp_path: Path) -> None:
    """Test scanning with successful summaries."""
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
---

Summary content here.
""",
        encoding="utf-8",
    )

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 1
    assert stats["success"] == 1
    assert stats["error"] == 0
    assert stats["oldest_date"] == "2024-01-01"
    assert stats["newest_date"] == "2024-01-01"


def test_scan_summaries_with_unknown_status(tmp_path: Path) -> None:
    """Test scanning with unknown status summaries."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a summary with unknown status
    summary1 = summaries / "2024-01-01-unknown.md"
    summary1.write_text(
        """---
source: https://example.com
date: 2024-01-01
summary_status: pending
---

This has an unknown status.
""",
        encoding="utf-8",
    )

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 1
    assert stats["success"] == 0
    assert stats["error"] == 0
    assert stats["unknown"] == 1
    assert len(stats["unknown_summaries"]) == 1
    assert stats["unknown_summaries"][0][0] == "2024-01-01-unknown.md"


def test_scan_summaries_with_errors(tmp_path: Path) -> None:
    """Test scanning with error summaries."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create an error summary
    summary1 = summaries / "2024-01-01-error.md"
    summary1.write_text(
        """---
source: https://example.com
date: 2024-01-01
summary_status: error
---

## Summary Unavailable

Failed to fetch: Connection timeout

**Original URL**: https://example.com
""",
        encoding="utf-8",
    )

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 1
    assert stats["success"] == 0
    assert stats["error"] == 1
    assert len(stats["error_summaries"]) == 1
    assert stats["error_summaries"][0][0] == "2024-01-01-error.md"
    assert "Fetch failed" in stats["error_summaries"][0][1]


def test_scan_summaries_mixed(tmp_path: Path) -> None:
    """Test scanning with mixed status summaries."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create successful summary
    (summaries / "2024-01-01-success.md").write_text(
        """---
source: https://example.com
date: 2024-01-01
summary_status: success
---
Summary.
""",
        encoding="utf-8",
    )

    # Create another success summary
    (summaries / "2024-01-02-success2.md").write_text(
        """---
source: https://example2.com
date: 2024-01-02
summary_status: success
---
Another.
""",
        encoding="utf-8",
    )

    # Create error summary
    (summaries / "2024-01-03-error.md").write_text(
        """---
source: https://example3.com
date: 2024-01-03
summary_status: error
---
Error.
""",
        encoding="utf-8",
    )

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 3
    assert stats["success"] == 2
    assert stats["error"] == 1
    assert stats["oldest_date"] == "2024-01-01"
    assert stats["newest_date"] == "2024-01-03"


def test_scan_summaries_date_range(tmp_path: Path) -> None:
    """Test that date range is correctly identified."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create summaries with different dates
    (summaries / "2024-01-01-old.md").write_text(
        """---
source: https://example.com
date: 2024-01-01
summary_status: success
---
""",
        encoding="utf-8",
    )

    (summaries / "2024-06-15-middle.md").write_text(
        """---
source: https://example.com
date: 2024-06-15
summary_status: success
---
""",
        encoding="utf-8",
    )

    (summaries / "2024-12-31-new.md").write_text(
        """---
source: https://example.com
date: 2024-12-31
summary_status: success
---
""",
        encoding="utf-8",
    )

    stats = scan_summaries(vault, "Summaries")

    assert stats["oldest_date"] == "2024-01-01"
    assert stats["newest_date"] == "2024-12-31"


def test_scan_summaries_ignores_non_markdown(tmp_path: Path) -> None:
    """Test that non-markdown files are ignored."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a markdown summary
    (summaries / "2024-01-01-summary.md").write_text(
        """---
source: https://example.com
date: 2024-01-01
summary_status: success
---
""",
        encoding="utf-8",
    )

    # Create non-markdown files
    (summaries / "notes.txt").write_text("Some notes")
    (summaries / ".DS_Store").write_text("")

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 1  # Only counts .md file


def test_scan_summaries_with_unknown_status_details(tmp_path: Path) -> None:
    """Test scanning with summaries that have unknown/missing status includes details."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a summary without status field
    (summaries / "2024-01-01-no-status.md").write_text(
        """---
source: https://example.com/no-status
date: 2024-01-01
---

Summary without status.
""",
        encoding="utf-8",
    )

    # Create a summary with unrecognized status
    (summaries / "2024-01-02-weird-status.md").write_text(
        """---
source: https://example.com/weird
date: 2024-01-02
summary_status: weird_status_value
---

Summary with unrecognized status.
""",
        encoding="utf-8",
    )

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 2
    assert stats["success"] == 0
    assert stats["error"] == 0
    assert stats["unknown"] == 2
    assert len(stats["unknown_summaries"]) == 2

    # Check that unknown summaries contain expected details
    filenames = [s[0] for s in stats["unknown_summaries"]]
    assert "2024-01-01-no-status.md" in filenames
    assert "2024-01-02-weird-status.md" in filenames

    # Find the specific entries and check details
    for filename, status, source in stats["unknown_summaries"]:
        if filename == "2024-01-01-no-status.md":
            assert status is None
            assert source == "https://example.com/no-status"
        elif filename == "2024-01-02-weird-status.md":
            assert status == "weird_status_value"
            assert source == "https://example.com/weird"


# Tests for scan_summaries_for_resummarize


def test_scan_summaries_for_resummarize_empty_folder(tmp_path: Path) -> None:
    """Test scanning when summaries folder doesn't exist."""
    vault = tmp_path / "vault"
    vault.mkdir()

    results = scan_summaries_for_resummarize(vault, "Summaries")

    assert results == []


def test_scan_summaries_for_resummarize_extracts_source_url_and_dates(tmp_path: Path) -> None:
    """Test correct extraction of source URLs and dates from frontmatter."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a summary with all fields
    summary = summaries / "2024-01-15-example.md"
    summary.write_text(
        """---
source: https://example.com/article
date: 2024-01-15
summary_date: 2024-12-29 22:31:49
summary_status: success
---

Summary content here.
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    assert len(results) == 1
    url, original_date, summary_date, _ = results[0]
    assert url == "https://example.com/article"
    assert original_date == datetime(2024, 1, 15)
    assert summary_date == datetime(2024, 12, 29, 22, 31, 49)


def test_scan_summaries_for_resummarize_filters_error_summaries(tmp_path: Path) -> None:
    """Test proper filtering of error summaries."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create an error summary
    error_summary = summaries / "2024-01-01-error.md"
    error_summary.write_text(
        """---
source: https://example.com
date: 2024-01-01
summary_status: error
---

## Summary Unavailable

Failed to fetch: Connection timeout
""",
        encoding="utf-8",
    )

    # Create a success summary
    success_summary = summaries / "2024-01-02-success.md"
    success_summary.write_text(
        """---
source: https://example.com/success
date: 2024-01-02
summary_status: success
---

Summary content.
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    # Only the success summary should be included
    assert len(results) == 1
    assert results[0][0] == "https://example.com/success"


def test_scan_summaries_for_resummarize_handles_summary_date_datetime_format(
    tmp_path: Path,
) -> None:
    """Test handling of summary_date in datetime format (YYYY-MM-DD HH:MM:SS)."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    summary = summaries / "2024-01-15-example.md"
    summary.write_text(
        """---
source: https://example.com
date: 2024-01-15
summary_date: 2024-12-29 14:30:45
summary_status: success
---

Summary.
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    assert len(results) == 1
    _, original_date, summary_date, _ = results[0]
    assert original_date == datetime(2024, 1, 15)
    assert summary_date == datetime(2024, 12, 29, 14, 30, 45)


def test_scan_summaries_for_resummarize_handles_summary_date_date_only_format(
    tmp_path: Path,
) -> None:
    """Test handling of summary_date in date-only format (YYYY-MM-DD)."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    summary = summaries / "2024-01-15-example.md"
    summary.write_text(
        """---
source: https://example.com
date: 2024-01-15
summary_date: 2024-12-29
summary_status: success
---

Summary.
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    assert len(results) == 1
    _, original_date, summary_date, _ = results[0]
    assert original_date == datetime(2024, 1, 15)
    assert summary_date == datetime(2024, 12, 29)


def test_scan_summaries_for_resummarize_fallback_to_original_date_when_summary_date_missing(
    tmp_path: Path,
) -> None:
    """Test fallback to original date when summary_date is missing."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    summary = summaries / "2024-01-15-example.md"
    summary.write_text(
        """---
source: https://example.com
date: 2024-01-15
summary_status: success
---

Summary without summary_date.
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    assert len(results) == 1
    _, original_date, summary_date, _ = results[0]
    assert original_date == datetime(2024, 1, 15)
    assert summary_date == datetime(2024, 1, 15)  # Fallback to original date


def test_scan_summaries_for_resummarize_fallback_to_original_date_when_summary_date_invalid(
    tmp_path: Path,
) -> None:
    """Test fallback to original date when summary_date has invalid format."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    summary = summaries / "2024-01-15-example.md"
    summary.write_text(
        """---
source: https://example.com
date: 2024-01-15
summary_date: invalid-date-format
summary_status: success
---

Summary with invalid summary_date.
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    assert len(results) == 1
    _, original_date, summary_date, _ = results[0]
    assert original_date == datetime(2024, 1, 15)
    assert summary_date == datetime(2024, 1, 15)  # Fallback to original date


def test_scan_summaries_for_resummarize_sorting_by_original_date(tmp_path: Path) -> None:
    """Test proper sorting by original date (newest first)."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create summaries in non-chronological order
    (summaries / "2024-06-15-middle.md").write_text(
        """---
source: https://example.com/middle
date: 2024-06-15
summary_status: success
---
""",
        encoding="utf-8",
    )

    (summaries / "2024-01-01-oldest.md").write_text(
        """---
source: https://example.com/oldest
date: 2024-01-01
summary_status: success
---
""",
        encoding="utf-8",
    )

    (summaries / "2024-12-31-newest.md").write_text(
        """---
source: https://example.com/newest
date: 2024-12-31
summary_status: success
---
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    # Should be sorted by original date (newest first)
    assert len(results) == 3
    assert results[0][0] == "https://example.com/newest"
    assert results[0][1] == datetime(2024, 12, 31)
    assert results[1][0] == "https://example.com/middle"
    assert results[1][1] == datetime(2024, 6, 15)
    assert results[2][0] == "https://example.com/oldest"
    assert results[2][1] == datetime(2024, 1, 1)


def test_scan_summaries_for_resummarize_skips_summaries_without_source(tmp_path: Path) -> None:
    """Test that summaries without source URL are skipped."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a summary without source
    (summaries / "2024-01-01-no-source.md").write_text(
        """---
date: 2024-01-01
summary_status: success
---

Summary without source.
""",
        encoding="utf-8",
    )

    # Create a summary with source
    (summaries / "2024-01-02-with-source.md").write_text(
        """---
source: https://example.com
date: 2024-01-02
summary_status: success
---

Summary with source.
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    # Only the summary with source should be included
    assert len(results) == 1
    assert results[0][0] == "https://example.com"


def test_scan_summaries_for_resummarize_skips_summaries_without_date(tmp_path: Path) -> None:
    """Test that summaries without date are skipped."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a summary without date
    (summaries / "no-date.md").write_text(
        """---
source: https://example.com/no-date
summary_status: success
---

Summary without date.
""",
        encoding="utf-8",
    )

    # Create a summary with date
    (summaries / "2024-01-02-with-date.md").write_text(
        """---
source: https://example.com/with-date
date: 2024-01-02
summary_status: success
---

Summary with date.
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    # Only the summary with date should be included
    assert len(results) == 1
    assert results[0][0] == "https://example.com/with-date"


def test_scan_summaries_for_resummarize_skips_summaries_with_invalid_date(
    tmp_path: Path,
) -> None:
    """Test that summaries with invalid date format are skipped."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a summary with invalid date
    (summaries / "invalid-date.md").write_text(
        """---
source: https://example.com/invalid
date: not-a-date
summary_status: success
---

Summary with invalid date.
""",
        encoding="utf-8",
    )

    # Create a summary with valid date
    (summaries / "2024-01-02-valid.md").write_text(
        """---
source: https://example.com/valid
date: 2024-01-02
summary_status: success
---

Summary with valid date.
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    # Only the summary with valid date should be included
    assert len(results) == 1
    assert results[0][0] == "https://example.com/valid"


def test_scan_summaries_for_resummarize_includes_summaries_without_status(
    tmp_path: Path,
) -> None:
    """Test that summaries without status field are included (not filtered out)."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a summary without status field
    (summaries / "2024-01-01-no-status.md").write_text(
        """---
source: https://example.com
date: 2024-01-01
---

Summary without status.
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    # Summary should be included (not filtered)
    assert len(results) == 1
    assert results[0][0] == "https://example.com"


def test_scan_summaries_for_resummarize_ignores_non_markdown_files(tmp_path: Path) -> None:
    """Test that non-markdown files are ignored."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a markdown summary
    (summaries / "2024-01-01-summary.md").write_text(
        """---
source: https://example.com
date: 2024-01-01
summary_status: success
---
""",
        encoding="utf-8",
    )

    # Create non-markdown files
    (summaries / "notes.txt").write_text("Some notes")
    (summaries / ".DS_Store").write_text("")

    results = scan_summaries_for_resummarize(vault, "Summaries")

    # Only the .md file should be processed
    assert len(results) == 1


def test_scan_summaries_for_resummarize_handles_read_errors_gracefully(tmp_path: Path) -> None:
    """Test that read errors are handled gracefully and don't stop processing."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a valid summary
    (summaries / "2024-01-01-valid.md").write_text(
        """---
source: https://example.com/valid
date: 2024-01-01
summary_status: success
---
""",
        encoding="utf-8",
    )

    # Create another valid summary
    (summaries / "2024-01-02-valid.md").write_text(
        """---
source: https://example.com/valid2
date: 2024-01-02
summary_status: success
---
""",
        encoding="utf-8",
    )

    results = scan_summaries_for_resummarize(vault, "Summaries")

    # Both valid summaries should be processed
    assert len(results) == 2
