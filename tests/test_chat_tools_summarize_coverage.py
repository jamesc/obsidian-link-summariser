"""
Comprehensive test coverage for summarize tool execute methods.

This module fills coverage gaps for the SummarizeUrlTool and ResummarizeTool
execute methods and error handling paths.
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from summarize_links.chat.tools.summarize import (
    ResummarizeTool,
    SummarizeUrlTool,
    extract_url_from_text,
)
from summarize_links.config import Config
from summarize_links.exceptions import (
    ContentExtractionError,
    ContentFetchError,
    OllamaAPIError,
    RateLimitError,
    URLValidationError,
)
from summarize_links.models import PageMetadata, SummaryResult
from summarize_links.utils.frontmatter import get_frontmatter_field


@pytest.fixture
def mock_config() -> Config:
    """Create a mock config for testing."""
    config = MagicMock(spec=Config)
    config.vault_path = Path("/vault")
    config.out_folder = "Summaries"
    config.daily_notes_folder = "Journal"
    config.force = False
    config.model = "test-model"
    config.model_provider = "test"
    config.default_tags = []
    config.gemini_api_key = "test-key"
    config.ollama_endpoint = "http://localhost:11434"
    config.azure_api_key = None
    config.azure_endpoint = None
    config.azure_deployment_name = None
    config.azure_api_version = None
    config.model_limits = {}
    config.playwright_enabled = False
    config.playwright_timeout = 30
    return config


@pytest.fixture
def mock_page_metadata() -> PageMetadata:
    """Create mock page metadata."""
    return PageMetadata(
        title="Test Page Title",
        domain="example.com",
        content="Test page content",
        description="Test description",
        author="Test Author",
        published_date="2025-01-01",
    )


@pytest.fixture
def mock_summary_result() -> SummaryResult:
    """Create mock summary result."""
    return SummaryResult(
        content="Test summary content",
        suggested_tags=["test", "ai"],
        content_type="article",
        raw_response="Raw LLM response",
        usage_details={"prompt_tokens": 100, "completion_tokens": 50},
    )


class TestSummarizeUrlToolExecute:
    """Comprehensive tests for SummarizeUrlTool.execute()."""

    def test_execute_missing_url(self, mock_config: Config) -> None:
        """Test execution fails with missing URL."""
        tool = SummarizeUrlTool()
        result = tool.execute(mock_config)

        assert result.success is False
        assert result.message and "required" in result.message.lower()
        assert result.error and "url" in result.error.lower()

    def test_execute_empty_url(self, mock_config: Config) -> None:
        """Test execution fails with empty URL."""
        tool = SummarizeUrlTool()
        result = tool.execute(mock_config, url="")

        assert result.success is False
        assert result.message and "required" in result.message.lower()

    def test_execute_normalizes_url_without_protocol(self, mock_config: Config) -> None:
        """Test that URLs without protocol are normalized."""
        tool = SummarizeUrlTool()

        with patch("summarize_links.chat.tools.summarize.summary_exists", return_value=True):
            result = tool.execute(mock_config, url="example.com")

            # Should succeed (skipped) after normalizing URL
            assert result.success is True
            assert result.data["url"] == "https://example.com"

    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    def test_execute_client_creation_error(
        self, mock_create_client: MagicMock, mock_config: Config
    ) -> None:
        """Test error handling when LLM client creation fails."""
        mock_create_client.side_effect = Exception("Client creation failed")

        tool = SummarizeUrlTool()

        with patch("summarize_links.chat.tools.summarize.summary_exists", return_value=False):
            result = tool.execute(mock_config, url="https://example.com")

        assert result.success is False
        assert "initialize AI model" in result.message
        assert result.error and "Client creation failed" in result.error

    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_url_validation_error(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_config: Config,
    ) -> None:
        """Test handling of URL validation errors."""
        mock_exists.return_value = False
        mock_create_client.return_value = MagicMock()
        mock_fetch.side_effect = URLValidationError("Invalid URL format")

        tool = SummarizeUrlTool()
        result = tool.execute(mock_config, url="https://invalid-url")

        assert result.success is False
        assert "Invalid URL" in result.message
        assert result.error and "Invalid URL format" in result.error

    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_content_fetch_error(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_config: Config,
    ) -> None:
        """Test handling of content fetch errors."""
        mock_exists.return_value = False
        mock_create_client.return_value = MagicMock()
        mock_fetch.side_effect = ContentFetchError("Network timeout")

        tool = SummarizeUrlTool()
        result = tool.execute(mock_config, url="https://example.com")

        assert result.success is False
        assert "Failed to fetch page" in result.message
        assert result.error and "Network timeout" in result.error

    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_content_extraction_error(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_config: Config,
    ) -> None:
        """Test handling of content extraction errors."""
        mock_exists.return_value = False
        mock_create_client.return_value = MagicMock()
        mock_fetch.side_effect = ContentExtractionError("No readable content")

        tool = SummarizeUrlTool()
        result = tool.execute(mock_config, url="https://example.com")

        assert result.success is False
        assert "Failed to extract content" in result.message
        assert result.error and "No readable content" in result.error

    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_rate_limit_error(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_config: Config,
        mock_page_metadata: PageMetadata,
    ) -> None:
        """Test handling of rate limit errors during summarization."""
        mock_exists.return_value = False
        mock_fetch.return_value = mock_page_metadata

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.side_effect = RateLimitError("Rate limit exceeded")
        mock_create_client.return_value = mock_client

        tool = SummarizeUrlTool()
        result = tool.execute(mock_config, url="https://example.com")

        assert result.success is False
        assert "Rate limited" in result.message
        assert result.error and "Rate limit exceeded" in result.error

    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_ollama_api_error(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_config: Config,
        mock_page_metadata: PageMetadata,
    ) -> None:
        """Test handling of Ollama API errors."""
        mock_exists.return_value = False
        mock_fetch.return_value = mock_page_metadata

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.side_effect = OllamaAPIError("Model not found")
        mock_create_client.return_value = mock_client

        tool = SummarizeUrlTool()
        result = tool.execute(mock_config, url="https://example.com")

        assert result.success is False
        assert "AI model error" in result.message
        assert result.error and "Model not found" in result.error

    @patch("summarize_links.chat.tools.summarize.write_summary_note_with_metadata")
    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_note_write_error(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_config: Config,
        mock_page_metadata: PageMetadata,
        mock_summary_result: SummaryResult,
    ) -> None:
        """Test handling of note write errors."""
        mock_exists.return_value = False
        mock_fetch.return_value = mock_page_metadata

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = mock_summary_result
        mock_create_client.return_value = mock_client

        mock_write.side_effect = OSError("Disk full")

        tool = SummarizeUrlTool()
        result = tool.execute(mock_config, url="https://example.com")

        assert result.success is False
        assert "Failed to save summary" in result.message
        assert result.error and "Disk full" in result.error

    @patch("summarize_links.chat.tools.summarize.remove_url_line_from_note")
    @patch("summarize_links.chat.tools.summarize.add_summary_link_to_daily_note")
    @patch("summarize_links.chat.tools.summarize.write_summary_note_with_metadata")
    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_success_with_tags(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_config: Config,
        mock_page_metadata: PageMetadata,
        mock_summary_result: SummaryResult,
    ) -> None:
        """Test successful execution with user-provided tags."""
        mock_exists.return_value = False
        mock_fetch.return_value = mock_page_metadata

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = mock_summary_result
        mock_create_client.return_value = mock_client

        mock_write.return_value = Path("/vault/Summaries/2025-01-23-test-page.md")

        tool = SummarizeUrlTool()
        result = tool.execute(
            mock_config,
            url="https://example.com",
            tags=["custom", "user-tag"],
        )

        assert result.success is True
        assert "Test Page Title" in result.message
        assert result.data["tags"] == ["test", "ai"]
        assert result.data["content_type"] == "article"

        # Verify tags were passed to write function
        call_kwargs = mock_write.call_args.kwargs
        assert call_kwargs["user_tags"] == ["custom", "user-tag"]

    @patch("summarize_links.chat.tools.summarize.remove_url_line_from_note")
    @patch("summarize_links.chat.tools.summarize.add_summary_link_to_daily_note")
    @patch("summarize_links.chat.tools.summarize.write_summary_note_with_metadata")
    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_success_daily_note_link_fails(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_config: Config,
        mock_page_metadata: PageMetadata,
        mock_summary_result: SummaryResult,
    ) -> None:
        """Test that execution succeeds even if daily note link addition fails."""
        mock_exists.return_value = False
        mock_fetch.return_value = mock_page_metadata

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = mock_summary_result
        mock_create_client.return_value = mock_client

        mock_write.return_value = Path("/vault/Summaries/test.md")
        mock_add_link.side_effect = OSError("Daily note not found")

        tool = SummarizeUrlTool()
        result = tool.execute(mock_config, url="https://example.com")

        # Should still succeed despite link addition failure
        assert result.success is True

    @patch("summarize_links.chat.tools.summarize.remove_url_line_from_note")
    @patch("summarize_links.chat.tools.summarize.add_summary_link_to_daily_note")
    @patch("summarize_links.chat.tools.summarize.write_summary_note_with_metadata")
    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_success_url_removal_fails(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_config: Config,
        mock_page_metadata: PageMetadata,
        mock_summary_result: SummaryResult,
    ) -> None:
        """Test that execution succeeds even if URL removal fails."""
        mock_exists.return_value = False
        mock_fetch.return_value = mock_page_metadata

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = mock_summary_result
        mock_create_client.return_value = mock_client

        mock_write.return_value = Path("/vault/Summaries/test.md")
        mock_remove_url.side_effect = OSError("Note is read-only")

        tool = SummarizeUrlTool()
        result = tool.execute(mock_config, url="https://example.com")

        # Should still succeed despite URL removal failure
        assert result.success is True

    @patch("summarize_links.chat.tools.summarize.remove_url_line_from_note")
    @patch("summarize_links.chat.tools.summarize.add_summary_link_to_daily_note")
    @patch("summarize_links.chat.tools.summarize.write_summary_note_with_metadata")
    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_with_progress_callback(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
        mock_config: Config,
        mock_page_metadata: PageMetadata,
        mock_summary_result: SummaryResult,
    ) -> None:
        """Test execution with progress callback."""
        mock_exists.return_value = False
        mock_fetch.return_value = mock_page_metadata

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = mock_summary_result
        mock_create_client.return_value = mock_client

        mock_write.return_value = Path("/vault/Summaries/test.md")

        progress_callback = Mock()

        tool = SummarizeUrlTool()
        result = tool.execute(
            mock_config,
            progress_callback=progress_callback,
            url="https://example.com",
        )

        assert result.success is True
        # Verify progress callback was called
        assert progress_callback.call_count >= 2
        progress_callback.assert_any_call("Fetching", "https://example.com")
        progress_callback.assert_any_call("Summarizing", "Test Page Title")


class TestResummarizeTool:
    """Comprehensive tests for ResummarizeTool."""

    def test_resummarize_missing_identifier(self, mock_config: Config) -> None:
        """Test execution fails with missing identifier."""
        tool = ResummarizeTool()
        result = tool.execute(mock_config)

        assert result.success is False
        assert result.message and "required" in result.message.lower()
        assert result.error and "identifier" in result.error.lower()

    def test_resummarize_no_vault(self) -> None:
        """Test execution fails without vault configured."""
        tool = ResummarizeTool()
        config = MagicMock(spec=Config)
        config.vault_path = None

        result = tool.execute(config, identifier="test-slug")

        assert result.success is False
        assert "vault" in result.message.lower()

    def test_resummarize_summary_not_found(self, mock_config: Config) -> None:
        """Test execution fails when summary is not found."""
        tool = ResummarizeTool()

        # Mock empty summaries folder
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "glob", return_value=[]):
                result = tool.execute(mock_config, identifier="nonexistent-slug")

        assert result.success is False
        assert "summary found" in result.message.lower()

    def test_find_summary_by_slug(self, mock_config: Config, tmp_path: Path) -> None:
        """Test finding summary by slug."""
        # Create a test summary file
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        summary_file = summaries_dir / "2025-01-23-test-article.md"
        summary_file.write_text("""---
source: https://example.com/article
date: 2025-01-23
from: "[[2025-01-23]]"
---

# Test Article
""")

        mock_config.vault_path = tmp_path

        tool = ResummarizeTool()
        metadata = tool._find_summary_by_url_or_slug(mock_config, "test-article")

        assert metadata is not None
        assert metadata[0] == "https://example.com/article"
        assert metadata[1] == datetime(2025, 1, 23)
        assert metadata[2] == "2025-01-23.md"

    def test_find_summary_by_url(self, mock_config: Config, tmp_path: Path) -> None:
        """Test finding summary by URL."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        summary_file = summaries_dir / "2025-01-23-example-com.md"
        summary_file.write_text("""---
source: https://example.com
date: 2025-01-23
---

# Example
""")

        mock_config.vault_path = tmp_path

        tool = ResummarizeTool()
        metadata = tool._find_summary_by_url_or_slug(mock_config, "https://example.com")

        assert metadata is not None
        assert metadata[0] == "https://example.com"

    def test_find_summary_normalized_url(self, mock_config: Config, tmp_path: Path) -> None:
        """Test finding summary with URL normalization."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        summary_file = summaries_dir / "2025-01-23-example.md"
        summary_file.write_text("""---
source: https://example.com/
date: 2025-01-23
---

# Example
""")

        mock_config.vault_path = tmp_path

        tool = ResummarizeTool()
        # Search without trailing slash
        metadata = tool._find_summary_by_url_or_slug(mock_config, "https://example.com")

        assert metadata is not None
        assert metadata[0] == "https://example.com/"

    def test_extract_summary_metadata_missing_fields(self, tmp_path: Path) -> None:
        """Test metadata extraction with missing required fields."""
        summary_file = tmp_path / "test.md"
        summary_file.write_text("""---
title: Test
---

Content
""")

        tool = ResummarizeTool()
        metadata = tool._extract_summary_metadata(summary_file)

        assert metadata is None

    def test_extract_summary_metadata_invalid_date(self, tmp_path: Path) -> None:
        """Test metadata extraction with invalid date format."""
        summary_file = tmp_path / "test.md"
        summary_file.write_text("""---
source: https://example.com
date: invalid-date
---

Content
""")

        tool = ResummarizeTool()
        metadata = tool._extract_summary_metadata(summary_file)

        assert metadata is None

    def test_extract_frontmatter_field_quoted(self, tmp_path: Path) -> None:
        """Test extracting quoted frontmatter field using centralized utility."""
        content = """---
source: "https://example.com"
date: '2025-01-23'
---
"""

        # Test uses centralized frontmatter utility (was moved from tool method)
        source = get_frontmatter_field(content, "source")
        date = get_frontmatter_field(content, "date")

        assert source == "https://example.com"
        assert date == "2025-01-23"

    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    def test_resummarize_client_creation_fails(
        self, mock_create_client: MagicMock, mock_config: Config, tmp_path: Path
    ) -> None:
        """Test resummarize fails gracefully when client creation fails."""
        # Create a test summary file
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        summary_file = summaries_dir / "2025-01-23-test.md"
        summary_file.write_text("""---
source: https://example.com
date: 2025-01-23
---

Content
""")

        mock_config.vault_path = tmp_path
        mock_create_client.side_effect = Exception("Client init failed")

        tool = ResummarizeTool()
        result = tool.execute(mock_config, identifier="test")

        assert result.success is False
        assert "initialize AI model" in result.message

    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    def test_resummarize_fetch_fails(
        self,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_config: Config,
        tmp_path: Path,
    ) -> None:
        """Test resummarize handles fetch failures."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        summary_file = summaries_dir / "2025-01-23-test.md"
        summary_file.write_text("""---
source: https://example.com
date: 2025-01-23
---

Content
""")

        mock_config.vault_path = tmp_path
        mock_create_client.return_value = MagicMock()
        mock_fetch.side_effect = ContentFetchError("404 Not Found")

        tool = ResummarizeTool()
        result = tool.execute(mock_config, identifier="test")

        assert result.success is False
        assert "Failed to fetch page" in result.message

    @patch("summarize_links.chat.tools.summarize.write_summary_note_with_metadata")
    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    def test_resummarize_success(
        self,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_config: Config,
        mock_page_metadata: PageMetadata,
        mock_summary_result: SummaryResult,
        tmp_path: Path,
    ) -> None:
        """Test successful resummarization."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        summary_file = summaries_dir / "2025-01-20-test-article.md"
        summary_file.write_text("""---
source: https://example.com/article
date: 2025-01-20
from: "[[2025-01-20]]"
---

Old summary
""")

        mock_config.vault_path = tmp_path
        mock_fetch.return_value = mock_page_metadata

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = mock_summary_result
        mock_create_client.return_value = mock_client

        mock_write.return_value = Path("/vault/Summaries/2025-01-20-test-article.md")

        tool = ResummarizeTool()
        result = tool.execute(mock_config, identifier="test-article")

        assert result.success is True
        assert "Re-summarized" in result.message
        assert result.data["url"] == "https://example.com/article"
        assert result.data["original_date"] == "2025-01-20"

        # Verify write was called with overwrite=True
        call_kwargs = mock_write.call_args.kwargs
        assert call_kwargs["overwrite"] is True
        assert call_kwargs["date"] == datetime(2025, 1, 20)
        assert call_kwargs["source_note"] == "2025-01-20.md"

    @patch("summarize_links.chat.tools.summarize.write_summary_note_with_metadata")
    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    def test_resummarize_with_progress_callback(
        self,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_config: Config,
        mock_page_metadata: PageMetadata,
        mock_summary_result: SummaryResult,
        tmp_path: Path,
    ) -> None:
        """Test resummarization with progress callback."""
        summaries_dir = tmp_path / "Summaries"
        summaries_dir.mkdir()

        summary_file = summaries_dir / "2025-01-23-test.md"
        summary_file.write_text("""---
source: https://example.com
date: 2025-01-23
---

Content
""")

        mock_config.vault_path = tmp_path
        mock_fetch.return_value = mock_page_metadata

        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = mock_summary_result
        mock_create_client.return_value = mock_client

        mock_write.return_value = Path("/vault/Summaries/test.md")

        progress_callback = Mock()

        tool = ResummarizeTool()
        result = tool.execute(
            mock_config,
            progress_callback=progress_callback,
            identifier="test",
        )

        assert result.success is True
        assert progress_callback.call_count >= 2
        progress_callback.assert_any_call("Fetching", "https://example.com")
        progress_callback.assert_any_call("Summarizing", "Test Page Title")


class TestExtractUrlFromTextEdgeCases:
    """Additional tests for URL extraction edge cases."""

    def test_extract_bare_domain_com(self) -> None:
        """Test extracting bare .com domain."""
        url = extract_url_from_text("Visit example.com for more")
        assert url == "https://example.com"

    def test_extract_bare_domain_org(self) -> None:
        """Test extracting bare .org domain."""
        url = extract_url_from_text("Check wikipedia.org")
        assert url == "https://wikipedia.org"

    def test_extract_domain_with_path_no_protocol(self) -> None:
        """Test extracting domain with path but no protocol."""
        url = extract_url_from_text("See example.com/docs/page")
        assert url == "https://example.com/docs/page"

    def test_extract_url_with_query_params(self) -> None:
        """Test extracting URL with query parameters."""
        url = extract_url_from_text("Link: https://example.com/page?foo=bar&baz=qux")
        assert url == "https://example.com/page?foo=bar&baz=qux"

    def test_extract_url_strips_trailing_comma(self) -> None:
        """Test stripping trailing comma."""
        url = extract_url_from_text("Check https://example.com, it's great")
        assert url == "https://example.com"

    def test_extract_url_strips_trailing_semicolon(self) -> None:
        """Test stripping trailing semicolon."""
        url = extract_url_from_text("Visit https://example.com; then return")
        assert url == "https://example.com"

    def test_extract_first_url_from_multiple(self) -> None:
        """Test extracting first URL when multiple are present."""
        url = extract_url_from_text("See https://first.com and https://second.com for info")
        assert url == "https://first.com"

    def test_extract_url_with_fragment(self) -> None:
        """Test extracting URL with fragment identifier."""
        url = extract_url_from_text("Jump to https://example.com/page#section")
        assert url == "https://example.com/page#section"

    def test_no_url_in_code_snippet(self) -> None:
        """Test that malformed URLs in code don't match."""
        text = "localhost:8080 is not a valid URL"
        url = extract_url_from_text(text)
        # Should not match localhost without proper format
        assert url is None or not url.startswith("https://localhost:8080")
