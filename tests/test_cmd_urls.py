"""Tests for the urls command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from summarize_links.cli import EXIT_SUCCESS
from summarize_links.commands import cmd_urls
from summarize_links.config import Config


class TestCmdUrls:
    """Tests for urls command handler."""

    @patch("summarize_links.services.summarization.process_urls")
    def test_processes_provided_urls(
        self,
        mock_process: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should process provided URLs."""
        mock_process.return_value = (EXIT_SUCCESS, [])
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
        )
        urls = ["https://example.com", "https://test.com"]

        result = cmd_urls(config, urls)

        mock_process.assert_called_once()
        call_args = mock_process.call_args[0]
        # Now receives UrlWithContext objects, check URLs match
        assert [ctx.url for ctx in call_args[0]] == urls
        assert result == EXIT_SUCCESS

    @patch("summarize_links.services.summarization.process_urls")
    def test_max_links_applied(
        self,
        mock_process: MagicMock,
        mock_vault: Path,
    ) -> None:
        """Should limit URLs to max_links."""
        mock_process.return_value = (EXIT_SUCCESS, [])
        config = Config(
            vault_path=mock_vault,
            gemini_api_key="test-key",
            max_links=2,
        )
        urls = ["https://1.com", "https://2.com", "https://3.com"]

        cmd_urls(config, urls)

        call_args = mock_process.call_args[0]
        # Now receives UrlWithContext objects
        assert len(call_args[0]) == 2
