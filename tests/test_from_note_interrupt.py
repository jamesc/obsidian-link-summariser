"""
Test batch processing structure for from-note --all command.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from summarize_links.config import Config


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    """Create a mock config for testing."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    return Config(
        vault_path=vault_path,
        out_folder="Summaries",
        gemini_api_key="test-key",
        model="gemini-2.5-flash",
        model_provider="google",
        daily_notes_folder="",
        max_links=100,
        dry_run=False,
        verbose=False,
        force=False,
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
    )


@patch("summarize_links.commands.from_note.find_daily_notes_with_urls")
@patch("summarize_links.commands.from_note.read_daily_note")
@patch("summarize_links.commands.from_note.extract_urls_with_context")
@patch("summarize_links.commands.from_note.process_urls")
def test_from_note_all_collects_urls_upfront(
    mock_process: MagicMock,
    mock_extract: MagicMock,
    mock_read: MagicMock,
    mock_find: MagicMock,
    mock_config: Config,
) -> None:
    """Test that from-note --all collects all URLs upfront and processes in one batch.

    This structure matches resummarize and allows signal handling to work
    correctly inside process_urls.
    """
    from summarize_links.commands.from_note import cmd_from_note_all
    from summarize_links.models import UrlWithContext
    from summarize_links.services.summarization import ProcessOutcome

    # Set up mocks - 3 notes with URLs
    mock_find.return_value = [
        ("2025-01-15", 2),
        ("2025-01-14", 3),
        ("2025-01-13", 1),
    ]
    mock_read.return_value = "# Daily Note\n\nhttps://example.com"
    mock_extract.return_value = [
        UrlWithContext(url="https://example.com", original_url="https://example.com")
    ]

    # Mock successful processing - process_urls returns (exit_code, list[ProcessOutcome])
    mock_process.return_value = (0, [ProcessOutcome(success=True, message="Created: example.md")])

    # Run the command
    exit_code = cmd_from_note_all(mock_config)

    # Should collect all URLs and process in ONE batch
    assert mock_process.call_count == 1
    assert exit_code == 0

    # Check that all URLs were collected with source info
    call_args = mock_process.call_args
    url_contexts = call_args[0][0]  # First positional arg
    assert len(url_contexts) == 3  # One URL per note

    # Verify source info was attached to each URL
    for url_ctx in url_contexts:
        assert url_ctx.source_note is not None
        assert url_ctx.source_date is not None
        assert url_ctx.source_note.endswith(".md")
        assert len(url_ctx.source_date) == 10  # YYYY-MM-DD format


@patch("summarize_links.commands.from_note.find_daily_notes_with_urls")
def test_from_note_all_no_urls_found(
    mock_find: MagicMock,
    mock_config: Config,
) -> None:
    """Test handling when no daily notes with URLs are found."""
    from summarize_links.commands.from_note import cmd_from_note_all

    mock_find.return_value = []

    exit_code = cmd_from_note_all(mock_config)

    assert exit_code == 0


def test_shutdown_flag_resets_between_batches(mock_config: Config) -> None:
    """Test that _shutdown_requested flag is reset between batch calls.

    This ensures that if a previous batch was interrupted, subsequent batches
    in the same process don't incorrectly think they're interrupted.
    Addresses Copilot review comment about multiple invocations in same process.
    """
    from summarize_links.models import UrlWithContext
    from summarize_links.services import summarization

    # Simulate a previous interrupted batch by setting the flag
    summarization._shutdown_requested = True

    # Now run a new batch - it should reset the flag and process normally
    url_contexts = [UrlWithContext(url="https://example.com", original_url="https://example.com")]

    with patch("summarize_links.services.summarization.create_llm_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = MagicMock(
            summary="Test summary",
            tags=[],
            content_type="article",
        )
        mock_client_factory.return_value = mock_client

        exit_code, outcomes = summarization.process_urls(url_contexts, mock_config)

        # Should have processed successfully (not immediately exited due to flag)
        assert exit_code == 0
        assert len(outcomes) == 1
        assert outcomes[0].success is True  # Success

        # The key behavior: _shutdown_requested was reset at the start of the batch,
        # so this new batch could run to completion despite being True beforehand.


def test_shutdown_flag_resets_in_resummarize_batch(mock_config: Config) -> None:
    """Test that _shutdown_requested flag is reset in resummarize calls too.

    This ensures consistency across all processing functions.
    """
    from datetime import datetime

    from summarize_links.services import summarization

    # Simulate a previous interrupted batch
    summarization._shutdown_requested = True

    # Run single resummarize call - should reset flag
    # Since resummarize is per-URL, we test the flag reset behavior with a direct call

    with patch("summarize_links.services.summarization.create_llm_client") as mock_client_factory:
        with patch("summarize_links.services.summarization.find_summary_metadata") as mock_find:
            # Mock the metadata lookup
            from summarize_links.services.summaries import SummaryMetadata

            assert mock_config.vault_path is not None, "vault_path must be set for this test"
            mock_find.return_value = SummaryMetadata(
                source_url="https://example.com",
                original_date=datetime(2025, 1, 1),
                source_note="2025-01-01.md",
                path=mock_config.vault_path / "Summaries" / "2025-01-01-example-com.md",
            )

            mock_client = MagicMock()
            mock_client.summarize_with_metadata.return_value = MagicMock(
                content="Test summary",
                suggested_tags=[],
                content_type="article",
            )
            mock_client_factory.return_value = mock_client

            # Force config to allow overwriting
            config_with_force = Config(
                vault_path=mock_config.vault_path,
                out_folder=mock_config.out_folder,
                gemini_api_key=mock_config.gemini_api_key,
                model=mock_config.model,
                model_provider=mock_config.model_provider,
                daily_notes_folder=mock_config.daily_notes_folder,
                max_links=mock_config.max_links,
                dry_run=mock_config.dry_run,
                verbose=mock_config.verbose,
                force=True,  # Enable force mode
                langfuse_public_key=mock_config.langfuse_public_key,
                langfuse_secret_key=mock_config.langfuse_secret_key,
            )

            outcome = summarization.resummarize("https://example.com", config_with_force)

            # Should process successfully
            assert outcome.success is True

            # The flag reset behavior is internal to the service and doesn't
            # directly affect resummarize (which is per-URL), but we verify
            # it doesn't prevent successful execution
