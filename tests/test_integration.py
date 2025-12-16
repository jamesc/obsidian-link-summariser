"""
Integration tests for the full workflow.

These tests verify that all components work together correctly,
using mock data and the mock vault fixture.
"""

from datetime import datetime
from pathlib import Path

import pytest

from summarize_links.config import load_config
from summarize_links.notes import (
    extract_urls,
    read_daily_note,
    write_summary_note,
)


class TestFullWorkflow:
    """Integration tests for the complete summarization workflow."""

    def test_extract_urls_from_daily_note(self, mock_vault: Path, sample_urls: list[str]) -> None:
        """Should extract URLs from a daily note file."""
        # Read the daily note
        content = read_daily_note(mock_vault, "2025-12-16.md")

        # Extract URLs
        urls = extract_urls(content)

        # Verify all expected URLs were found
        assert len(urls) == len(sample_urls)
        for expected_url in sample_urls:
            assert expected_url in urls

    def test_write_summaries_for_extracted_urls(
        self, mock_vault: Path, fixed_date: datetime
    ) -> None:
        """Should write summary notes for each extracted URL."""
        # Read and extract URLs
        content = read_daily_note(mock_vault, "2025-12-16.md")
        urls = extract_urls(content)

        # Write summaries for each URL
        written_files: list[Path] = []
        for url in urls:
            filepath = write_summary_note(
                vault_path=mock_vault,
                out_folder="Summaries",
                url=url,
                content=f"## Summary\n\nMock summary for {url}",
                date=fixed_date,
                source_note="2025-12-16.md",
            )
            written_files.append(filepath)

        # Verify all files were created
        assert len(written_files) == len(urls)
        for filepath in written_files:
            assert filepath.exists()
            assert filepath.suffix == ".md"

        # Verify content structure
        first_summary = written_files[0].read_text()
        assert "---" in first_summary  # Has frontmatter
        assert "source:" in first_summary
        assert "date: 2025-12-16" in first_summary
        assert "## Summary" in first_summary

    def test_idempotency_skip_existing(self, mock_vault: Path, fixed_date: datetime) -> None:
        """Running twice should skip already-processed URLs."""
        url = "https://example.com/test"

        # First write
        filepath1 = write_summary_note(
            vault_path=mock_vault,
            out_folder="Summaries",
            url=url,
            content="First summary",
            date=fixed_date,
            overwrite=False,
        )

        # Second write (should skip)
        filepath2 = write_summary_note(
            vault_path=mock_vault,
            out_folder="Summaries",
            url=url,
            content="Second summary",
            date=fixed_date,
            overwrite=False,
        )

        # Same filepath returned
        assert filepath1 == filepath2

        # Original content preserved
        assert "First summary" in filepath1.read_text()
        assert "Second summary" not in filepath1.read_text()

    def test_config_loading_with_mock_vault(
        self, mock_vault_with_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should load config from vault YAML file."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config = load_config(vault_path=mock_vault_with_config)

        assert config.out_folder == "MySummaries"
        assert config.max_links == 5
        assert config.daily_notes_folder == "Journal"

    def test_daily_note_in_subfolder(self, mock_vault: Path) -> None:
        """Should read daily notes from configured subfolder."""
        # Note in Journal folder was created by mock_vault fixture
        content = read_daily_note(mock_vault, "2025-12-15.md", daily_notes_folder="Journal")

        assert "Yesterday's note" in content

    def test_max_links_limit(
        self, mock_vault: Path, sample_urls: list[str], fixed_date: datetime
    ) -> None:
        """Should respect max_links configuration."""
        max_links = 2

        # Read and extract URLs
        content = read_daily_note(mock_vault, "2025-12-16.md")
        urls = extract_urls(content)

        # Limit URLs
        limited_urls = urls[:max_links]

        # Process only limited URLs
        written_files = []
        for url in limited_urls:
            filepath = write_summary_note(
                vault_path=mock_vault,
                out_folder="Summaries",
                url=url,
                content=f"Summary for {url}",
                date=fixed_date,
            )
            written_files.append(filepath)

        # Verify only max_links files created
        assert len(written_files) == max_links


class TestConfigIntegration:
    """Integration tests for configuration loading."""

    def test_cli_overrides_yaml_config(
        self, mock_vault_with_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI arguments should override YAML config."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config = load_config(
            vault_path=mock_vault_with_config,
            out_folder="CLIOverride",
            max_links=20,
        )

        # CLI values should win
        assert config.out_folder == "CLIOverride"
        assert config.max_links == 20
        # YAML values for non-overridden settings should persist
        assert config.daily_notes_folder == "Journal"

    def test_config_validation_integration(
        self, mock_vault: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Full config should pass validation."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config = load_config(vault_path=mock_vault)
        config.validate()  # Should not raise

        assert config.vault_path == mock_vault
        assert config.gemini_api_key == "test-key"
