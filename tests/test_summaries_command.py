"""
Tests for the summaries command.

Tests the scan_summaries function and cmd_summaries CLI command.
"""

from pathlib import Path

from summarize_links.notes import scan_summaries


def test_scan_summaries_empty_folder(tmp_path: Path) -> None:
    """Test scanning when summaries folder doesn't exist."""
    vault = tmp_path / "vault"
    vault.mkdir()

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 0
    assert stats["success"] == 0
    assert stats["mocked"] == 0
    assert stats["error"] == 0
    assert stats["unknown"] == 0
    assert stats["oldest_date"] is None
    assert stats["newest_date"] is None
    assert stats["error_summaries"] == []
    assert stats["mocked_summaries"] == []


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
status: success
---

Summary content here.
""",
        encoding="utf-8",
    )

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 1
    assert stats["success"] == 1
    assert stats["mocked"] == 0
    assert stats["error"] == 0
    assert stats["oldest_date"] == "2024-01-01"
    assert stats["newest_date"] == "2024-01-01"


def test_scan_summaries_with_mocked(tmp_path: Path) -> None:
    """Test scanning with mocked summaries."""
    vault = tmp_path / "vault"
    summaries = vault / "Summaries"
    summaries.mkdir(parents=True)

    # Create a mocked summary
    summary1 = summaries / "2024-01-01-mocked.md"
    summary1.write_text(
        """---
source: https://example.com
date: 2024-01-01
status: mocked
---

This is a mocked summary.
""",
        encoding="utf-8",
    )

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 1
    assert stats["success"] == 0
    assert stats["mocked"] == 1
    assert stats["error"] == 0
    assert len(stats["mocked_summaries"]) == 1
    assert stats["mocked_summaries"][0] == ("2024-01-01-mocked.md", "2024-01-01")


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
status: error
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
    assert stats["mocked"] == 0
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
status: success
---
Summary.
""",
        encoding="utf-8",
    )

    # Create mocked summary
    (summaries / "2024-01-02-mocked.md").write_text(
        """---
source: https://example2.com
date: 2024-01-02
status: mocked
---
Mocked.
""",
        encoding="utf-8",
    )

    # Create error summary
    (summaries / "2024-01-03-error.md").write_text(
        """---
source: https://example3.com
date: 2024-01-03
status: error
---
Error.
""",
        encoding="utf-8",
    )

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 3
    assert stats["success"] == 1
    assert stats["mocked"] == 1
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
status: success
---
""",
        encoding="utf-8",
    )

    (summaries / "2024-06-15-middle.md").write_text(
        """---
source: https://example.com
date: 2024-06-15
status: success
---
""",
        encoding="utf-8",
    )

    (summaries / "2024-12-31-new.md").write_text(
        """---
source: https://example.com
date: 2024-12-31
status: success
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
status: success
---
""",
        encoding="utf-8",
    )

    # Create non-markdown files
    (summaries / "notes.txt").write_text("Some notes")
    (summaries / ".DS_Store").write_text("")

    stats = scan_summaries(vault, "Summaries")

    assert stats["total"] == 1  # Only counts .md file
