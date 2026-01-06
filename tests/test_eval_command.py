"""Tests for evaluation command."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from summarize_links.config import Config
from summarize_links.eval import cmd_eval
from summarize_links.models import SummaryResult


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    """Create a mock configuration for testing."""
    return Config(
        vault_path=tmp_path,
        model="gemini-2.5-flash",
        mock_mode=True,  # Use mock mode for tests
        gemini_api_key="test-key",
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
    )


@pytest.fixture
def sample_dataset(tmp_path: Path) -> Path:
    """Create a sample dataset file for testing."""
    dataset_content = """
name: "Test Dataset"
description: "A simple test dataset"
examples:
  - url: "https://example.com/article"
    title: "Example Article"
    expected_tags:
      - test
      - article
    expected_content_type: "article"
"""
    dataset_file = tmp_path / "test_dataset.yaml"
    dataset_file.write_text(dataset_content)
    return dataset_file


class TestCmdEval:
    """Tests for cmd_eval command handler."""

    def test_eval_loads_dataset(self, mock_config: Config, sample_dataset: Path) -> None:
        """Test that eval command loads the dataset."""
        with patch("summarize_links.eval.command.create_llm_client") as mock_create:
            mock_client = Mock()
            mock_create.return_value = mock_client

            # Mock the fetch and summarize methods
            with patch("summarize_links.eval.command.fetch_and_extract_metadata") as mock_fetch:
                mock_page = Mock()
                mock_page.content = "Test content"
                mock_page.title = "Test Title"
                mock_fetch.return_value = mock_page

                mock_client.summarize_with_metadata.return_value = SummaryResult(
                    content="Test summary",
                    suggested_tags=["test", "article"],
                    content_type="article",
                )

                result = cmd_eval(mock_config, str(sample_dataset))

                # Should complete successfully
                assert result == 0

    def test_eval_handles_missing_dataset(self, mock_config: Config, tmp_path: Path) -> None:
        """Test error handling when dataset file doesn't exist."""
        result = cmd_eval(mock_config, str(tmp_path / "nonexistent.yaml"))

        # Should return error
        assert result == 1

    def test_eval_handles_invalid_dataset(self, mock_config: Config, tmp_path: Path) -> None:
        """Test error handling for invalid dataset format."""
        invalid_file = tmp_path / "invalid.yaml"
        invalid_file.write_text("not: valid: yaml: content")

        result = cmd_eval(mock_config, str(invalid_file))

        assert result == 1

    def test_eval_handles_fetch_errors(self, mock_config: Config, sample_dataset: Path) -> None:
        """Test that eval handles fetch errors gracefully."""
        with patch("summarize_links.eval.command.create_llm_client") as mock_create:
            mock_client = Mock()
            mock_create.return_value = mock_client

            with patch("summarize_links.eval.command.fetch_and_extract_metadata") as mock_fetch:
                from summarize_links.exceptions import ContentFetchError

                mock_fetch.side_effect = ContentFetchError("Network error")

                result = cmd_eval(mock_config, str(sample_dataset))

                # Should return error when all examples fail
                assert result == 1

    def test_eval_saves_results(
        self, mock_config: Config, sample_dataset: Path, tmp_path: Path
    ) -> None:
        """Test that eval saves results when output path provided."""
        output_file = tmp_path / "results.yaml"

        with patch("summarize_links.eval.command.create_llm_client") as mock_create:
            mock_client = Mock()
            mock_create.return_value = mock_client

            with patch("summarize_links.eval.command.fetch_and_extract_metadata") as mock_fetch:
                mock_page = Mock()
                mock_page.content = "Test content"
                mock_page.title = "Test Title"
                mock_fetch.return_value = mock_page

                mock_client.summarize_with_metadata.return_value = SummaryResult(
                    content="Test summary",
                    suggested_tags=["test"],
                    content_type="article",
                )

                result = cmd_eval(mock_config, str(sample_dataset), str(output_file))

                assert result == 0
                assert output_file.exists()

    def test_eval_calculates_metrics(self, mock_config: Config, sample_dataset: Path) -> None:
        """Test that eval calculates metrics correctly."""
        with patch("summarize_links.eval.command.create_llm_client") as mock_create:
            mock_client = Mock()
            mock_create.return_value = mock_client

            with patch("summarize_links.eval.command.fetch_and_extract_metadata") as mock_fetch:
                mock_page = Mock()
                mock_page.content = "Test content"
                mock_page.title = "Test Title"
                mock_fetch.return_value = mock_page

                # Return tags that match expected
                mock_client.summarize_with_metadata.return_value = SummaryResult(
                    content="Test summary",
                    suggested_tags=["test", "article"],  # Matches expected
                    content_type="article",  # Matches expected
                )

                result = cmd_eval(mock_config, str(sample_dataset))

                assert result == 0

    def test_eval_with_mock_mode(self, mock_config: Config, sample_dataset: Path) -> None:
        """Test that eval works in mock mode."""
        mock_config.mock_mode = True

        with patch("summarize_links.eval.command.create_llm_client") as mock_create:
            mock_client = Mock()
            mock_create.return_value = mock_client

            with patch("summarize_links.eval.command.fetch_and_extract_metadata") as mock_fetch:
                mock_page = Mock()
                mock_page.content = "Test content"
                mock_page.title = "Test Title"
                mock_fetch.return_value = mock_page

                mock_client.summarize_with_metadata.return_value = SummaryResult(
                    content="Mock summary",
                    suggested_tags=["mock"],
                    content_type="article",
                )

                result = cmd_eval(mock_config, str(sample_dataset))

                assert result == 0
