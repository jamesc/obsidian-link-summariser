"""
Tests for preserving original summary dates when re-summarizing.

This ensures that when we re-summarize an existing URL (e.g., to fix a garbled
summary), we preserve the original date from the existing summary file instead
of creating a new file with today's date.
"""

from datetime import datetime
from pathlib import Path

from summarize_links.models import PageMetadata, SummaryResult
from summarize_links.notes import (
    get_existing_summary_date,
    get_summary_filepath,
    scan_summaries_for_resummarize,
    write_summary_note_with_metadata,
)


class TestGetExistingSummaryDate:
    """Tests for getting the date from an existing summary file."""

    def test_finds_existing_summary_date(self, tmp_path: Path) -> None:
        """Should extract date from existing summary filename."""
        vault_path = tmp_path / "vault"
        summaries_folder = "Summaries"
        summaries_path = vault_path / summaries_folder
        summaries_path.mkdir(parents=True)

        # Create an existing summary with a specific date
        url = "https://example.com/article"
        existing_file = summaries_path / "2024-01-15-article.md"
        existing_file.write_text(
            """---
source: https://example.com/article
date: 2024-01-15
status: success
---

# Article Summary

Some content here.
""",
            encoding="utf-8",
        )

        # Should find and return the existing date
        found_date = get_existing_summary_date(vault_path, summaries_folder, url)

        assert found_date is not None
        assert found_date.year == 2024
        assert found_date.month == 1
        assert found_date.day == 15

    def test_returns_none_when_no_summary_exists(self, tmp_path: Path) -> None:
        """Should return None when no matching summary file exists."""
        vault_path = tmp_path / "vault"
        summaries_folder = "Summaries"
        summaries_path = vault_path / summaries_folder
        summaries_path.mkdir(parents=True)

        url = "https://example.com/nonexistent"

        found_date = get_existing_summary_date(vault_path, summaries_folder, url)

        assert found_date is None

    def test_returns_none_when_summaries_folder_missing(self, tmp_path: Path) -> None:
        """Should return None when summaries folder doesn't exist."""
        vault_path = tmp_path / "vault"
        vault_path.mkdir()

        url = "https://example.com/article"

        found_date = get_existing_summary_date(vault_path, "Summaries", url)

        assert found_date is None

    def test_finds_oldest_when_multiple_summaries_exist(self, tmp_path: Path) -> None:
        """Should return date from first matching file if multiple exist."""
        vault_path = tmp_path / "vault"
        summaries_folder = "Summaries"
        summaries_path = vault_path / summaries_folder
        summaries_path.mkdir(parents=True)

        # Create multiple summaries for the same URL (unlikely but possible)
        url = "https://example.com/article"

        file1 = summaries_path / "2024-01-10-article.md"
        file1.write_text("---\nsource: url\n---\n\nOld summary", encoding="utf-8")

        file2 = summaries_path / "2024-01-20-article.md"
        file2.write_text("---\nsource: url\n---\n\nNewer summary", encoding="utf-8")

        # Should find one of them (glob order may vary, but we just need A date)
        found_date = get_existing_summary_date(vault_path, summaries_folder, url)

        assert found_date is not None
        assert found_date.year == 2024
        assert found_date.month == 1
        # Should be either the 10th or 20th
        assert found_date.day in (10, 20)

    def test_handles_invalid_date_in_filename(self, tmp_path: Path) -> None:
        """Should return None if filename date is malformed."""
        vault_path = tmp_path / "vault"
        summaries_folder = "Summaries"
        summaries_path = vault_path / summaries_folder
        summaries_path.mkdir(parents=True)

        # Create file with invalid date format
        url = "https://example.com/article"
        invalid_file = summaries_path / "invalid-date-article.md"
        invalid_file.write_text("---\nsource: url\n---\n\nContent", encoding="utf-8")

        found_date = get_existing_summary_date(vault_path, summaries_folder, url)

        assert found_date is None


class TestPreserveExistingDate:
    """Integration tests for preserving dates when re-summarizing."""

    def test_overwrites_summary_with_same_date(self, tmp_path: Path) -> None:
        """Should overwrite existing summary while preserving its date."""
        vault_path = tmp_path / "vault"
        summaries_folder = "Summaries"
        summaries_path = vault_path / summaries_folder
        summaries_path.mkdir(parents=True)

        url = "https://example.com/article"
        original_date = datetime(2024, 1, 15)

        # Create original summary
        summary_result = SummaryResult(
            content="# Original Summary\n\nOriginal content.",
            suggested_tags=["tag1"],
            content_type="article",
        )
        page_metadata = PageMetadata(
            title="Original Title",
            domain="example.com",
            content="Original content",
        )

        original_path = write_summary_note_with_metadata(
            vault_path=vault_path,
            out_folder=summaries_folder,
            url=url,
            summary_result=summary_result,
            page_metadata=page_metadata,
            date=original_date,
            summary_status="error",  # Simulate an error summary that needs re-summarizing
        )

        assert original_path.exists()
        assert "2024-01-15" in original_path.name

        # Now re-summarize with new content but same date
        new_summary_result = SummaryResult(
            content="# Updated Summary\n\nNew and improved content!",
            suggested_tags=["tag1", "tag2"],
            content_type="article",
        )
        new_page_metadata = PageMetadata(
            title="Updated Title",
            domain="example.com",
            content="New content",
        )

        # When we use the same date, it should overwrite the same file
        new_path = write_summary_note_with_metadata(
            vault_path=vault_path,
            out_folder=summaries_folder,
            url=url,
            summary_result=new_summary_result,
            page_metadata=new_page_metadata,
            date=original_date,  # Same date!
            summary_status="success",
            overwrite=True,
        )

        # Should be the same file path
        assert new_path == original_path
        assert new_path.exists()

        # Content should be updated
        content = new_path.read_text(encoding="utf-8")
        assert "Updated Summary" in content
        assert "Updated Title" in content
        assert "summary_status: success" in content

        # Date should be preserved
        assert "date: 2024-01-15" in content
        assert "2024-01-15" in new_path.name

    def test_does_not_create_duplicate_with_new_date(self, tmp_path: Path) -> None:
        """Verifies that using the original date prevents duplicate files."""
        vault_path = tmp_path / "vault"
        summaries_folder = "Summaries"
        summaries_path = vault_path / summaries_folder
        summaries_path.mkdir(parents=True)

        url = "https://example.com/article"
        original_date = datetime(2024, 1, 15)
        new_date = datetime(2024, 12, 23)  # Today's date

        # Create original summary
        summary_result = SummaryResult(
            content="# Original",
            suggested_tags=[],
            content_type="article",
        )
        page_metadata = PageMetadata(title="Title", domain="example.com", content="Content")

        original_path = write_summary_note_with_metadata(
            vault_path=vault_path,
            out_folder=summaries_folder,
            url=url,
            summary_result=summary_result,
            page_metadata=page_metadata,
            date=original_date,
        )

        # What we DON'T want: creating a new file with today's date
        # This would happen if we used new_date instead of original_date
        wrong_path = get_summary_filepath(vault_path, summaries_folder, url, new_date)

        # These should be different files
        assert original_path != wrong_path

        # Re-summarize using ORIGINAL date (correct behavior)
        new_summary_result = SummaryResult(
            content="# Updated",
            suggested_tags=[],
            content_type="article",
        )

        updated_path = write_summary_note_with_metadata(
            vault_path=vault_path,
            out_folder=summaries_folder,
            url=url,
            summary_result=new_summary_result,
            page_metadata=page_metadata,
            date=original_date,  # Use original date!
            overwrite=True,
        )

        # Should update the original file
        assert updated_path == original_path

        # The "wrong" path should not exist
        assert not wrong_path.exists()

        # Only one file should exist
        summary_files = list(summaries_path.glob("*.md"))
        assert len(summary_files) == 1
        assert summary_files[0] == original_path


class TestPreserveFromField:
    """Tests for preserving the 'from' frontmatter field during resummarization."""

    def test_scan_extracts_from_field(self, tmp_path: Path) -> None:
        """Should extract the 'from' field when scanning summaries."""
        vault_path = tmp_path / "vault"
        summaries_folder = "Summaries"
        summaries_path = vault_path / summaries_folder
        summaries_path.mkdir(parents=True)

        # Create a summary with a 'from' field
        url = "https://example.com/article"
        summary_file = summaries_path / "2024-01-15-article.md"
        summary_file.write_text(
            """---
source: https://example.com/article
date: 2024-01-15
summary_status: success
summary_date: 2024-01-15 10:30:00
from: "[[2024-01-15]]"
---

# Article Summary

Some content here.
""",
            encoding="utf-8",
        )

        # Scan for summaries
        summaries = scan_summaries_for_resummarize(vault_path, summaries_folder)

        assert len(summaries) == 1
        source_url, original_date, summary_date, source_note = summaries[0]

        assert source_url == url
        assert original_date.strftime("%Y-%m-%d") == "2024-01-15"
        assert source_note == "2024-01-15.md"

    def test_scan_handles_missing_from_field(self, tmp_path: Path) -> None:
        """Should handle summaries without a 'from' field."""
        vault_path = tmp_path / "vault"
        summaries_folder = "Summaries"
        summaries_path = vault_path / summaries_folder
        summaries_path.mkdir(parents=True)

        # Create a summary without a 'from' field
        url = "https://example.com/article"
        summary_file = summaries_path / "2024-01-15-article.md"
        summary_file.write_text(
            """---
source: https://example.com/article
date: 2024-01-15
summary_status: success
---

# Article Summary

Some content here.
""",
            encoding="utf-8",
        )

        # Scan for summaries
        summaries = scan_summaries_for_resummarize(vault_path, summaries_folder)

        assert len(summaries) == 1
        source_url, original_date, summary_date, source_note = summaries[0]

        assert source_url == url
        assert source_note is None

    def test_preserves_from_field_during_resummarize(self, tmp_path: Path) -> None:
        """Should preserve the 'from' field when re-summarizing."""
        vault_path = tmp_path / "vault"
        summaries_folder = "Summaries"
        summaries_path = vault_path / summaries_folder
        summaries_path.mkdir(parents=True)

        url = "https://example.com/article"
        original_date = datetime(2024, 1, 15)
        source_note = "2024-01-15.md"

        # Create original summary with 'from' field
        summary_result = SummaryResult(
            content="# Original Summary\n\nOriginal content.",
            suggested_tags=["tag1"],
            content_type="article",
        )
        page_metadata = PageMetadata(
            title="Original Title",
            domain="example.com",
            content="Original content",
        )

        write_summary_note_with_metadata(
            vault_path=vault_path,
            out_folder=summaries_folder,
            url=url,
            summary_result=summary_result,
            page_metadata=page_metadata,
            date=original_date,
            source_note=source_note,  # Original source note
            summary_status="success",
        )

        # Re-summarize with new content but preserve source_note
        new_summary_result = SummaryResult(
            content="# Updated Summary\n\nNew content!",
            suggested_tags=["tag2"],
            content_type="article",
        )

        updated_path = write_summary_note_with_metadata(
            vault_path=vault_path,
            out_folder=summaries_folder,
            url=url,
            summary_result=new_summary_result,
            page_metadata=page_metadata,
            date=original_date,
            source_note=source_note,  # Preserve the source note
            summary_status="success",
            overwrite=True,
        )

        # Verify the 'from' field is still present
        content = updated_path.read_text(encoding="utf-8")
        assert "Updated Summary" in content
        assert 'from: "[[2024-01-15]]"' in content
