"""
Tests for the chat tools module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from summarize_links.chat.tools.base import ToolRegistry, ToolResult, get_default_registry
from summarize_links.chat.tools.summarize import SummarizeUrlTool, extract_url_from_text
from summarize_links.config import Config


class TestToolResult:
    """Tests for the ToolResult dataclass."""

    def test_success_result(self) -> None:
        """Test creating a success result."""
        result = ToolResult(success=True, message="Done!")
        assert result.success is True
        assert result.message == "Done!"
        assert result.error is None

    def test_failure_result(self) -> None:
        """Test creating a failure result."""
        result = ToolResult(success=False, message="Failed", error="Some error")
        assert result.success is False
        assert result.error == "Some error"

    def test_to_content_success(self) -> None:
        """Test converting success result to content."""
        result = ToolResult(success=True, message="Summary created")
        assert result.to_content() == "Summary created"

    def test_to_content_failure(self) -> None:
        """Test converting failure result to content."""
        result = ToolResult(success=False, message="Failed", error="Network error")
        assert result.to_content() == "Error: Network error"


class TestToolRegistry:
    """Tests for the ToolRegistry class."""

    def test_create_registry(self) -> None:
        """Test creating an empty registry."""
        registry = ToolRegistry()
        assert len(registry) == 0

    def test_register_tool(self) -> None:
        """Test registering a tool."""
        registry = ToolRegistry()
        tool = SummarizeUrlTool()
        registry.register(tool)
        assert len(registry) == 1
        assert "summarize_url" in registry

    def test_register_duplicate_raises(self) -> None:
        """Test that registering duplicate tool raises error."""
        registry = ToolRegistry()
        tool = SummarizeUrlTool()
        registry.register(tool)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(tool)

    def test_get_tool(self) -> None:
        """Test getting a tool by name."""
        registry = ToolRegistry()
        tool = SummarizeUrlTool()
        registry.register(tool)

        retrieved = registry.get("summarize_url")
        assert retrieved is tool

    def test_get_unknown_tool(self) -> None:
        """Test getting an unknown tool returns None."""
        registry = ToolRegistry()
        assert registry.get("unknown") is None

    def test_list_tools(self) -> None:
        """Test listing all tools."""
        registry = ToolRegistry()
        tool = SummarizeUrlTool()
        registry.register(tool)

        tools = registry.list_tools()
        assert len(tools) == 1
        assert tools[0] is tool

    def test_get_schemas(self) -> None:
        """Test getting OpenAI-style schemas."""
        registry = ToolRegistry()
        registry.register(SummarizeUrlTool())

        schemas = registry.get_schemas()
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "summarize_url"

    def test_execute_unknown_tool(self) -> None:
        """Test executing unknown tool returns error."""
        registry = ToolRegistry()
        config = MagicMock(spec=Config)

        result = registry.execute("unknown_tool", config)
        assert result.success is False
        assert "Unknown tool" in result.message


class TestSummarizeUrlTool:
    """Tests for the SummarizeUrlTool."""

    def test_tool_properties(self) -> None:
        """Test tool properties."""
        tool = SummarizeUrlTool()
        assert tool.name == "summarize_url"
        assert "summarize" in tool.description.lower()
        assert "url" in tool.parameters["properties"]
        assert "url" in tool.parameters["required"]

    def test_to_schema(self) -> None:
        """Test converting to OpenAI schema."""
        tool = SummarizeUrlTool()
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "summarize_url"

    def test_execute_no_vault(self) -> None:
        """Test execution fails without vault."""
        tool = SummarizeUrlTool()
        config = MagicMock(spec=Config)
        config.vault_path = None

        result = tool.execute(config, url="https://example.com")
        assert result.success is False
        assert "vault" in result.message.lower()

    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_skip_existing(self, mock_exists: MagicMock) -> None:
        """Test skipping existing summaries."""
        mock_exists.return_value = True

        tool = SummarizeUrlTool()
        config = MagicMock(spec=Config)
        config.vault_path = Path("/vault")
        config.out_folder = "Summaries"
        config.force = False

        result = tool.execute(config, url="https://example.com")
        assert result.success is True
        assert result.data.get("skipped") is True

    @patch("summarize_links.chat.tools.summarize.add_summary_link_to_daily_note")
    @patch("summarize_links.chat.tools.summarize.write_summary_note_with_metadata")
    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_adds_link_to_daily_note(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
    ) -> None:
        """Test that summarization adds link to daily note."""
        mock_exists.return_value = False

        # Setup mock client
        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = MagicMock(
            content="Test summary content",
            suggested_tags=["test"],
            content_type="article",
        )
        mock_create_client.return_value = mock_client

        # Setup mock fetch
        mock_fetch.return_value = MagicMock(
            content="Test page content",
            title="Test Page",
        )

        # Setup mock write
        mock_write.return_value = Path("/vault/Summaries/example-com.md")

        tool = SummarizeUrlTool()
        config = MagicMock(spec=Config)
        config.vault_path = Path("/vault")
        config.out_folder = "Summaries"
        config.daily_notes_folder = "Journal"
        config.force = False
        config.mock_mode = False
        config.model = "test-model"
        config.model_provider = "test"
        config.default_tags = []
        config.gemini_api_key = None
        config.ollama_endpoint = None
        config.azure_api_key = None
        config.azure_endpoint = None
        config.azure_deployment_name = None
        config.azure_api_version = None
        config.model_limits = {}
        config.playwright_enabled = False
        config.playwright_timeout = 30

        result = tool.execute(config, url="https://example.com")

        assert result.success is True
        mock_add_link.assert_called_once()
        # Verify the call was made with the right arguments
        call_kwargs = mock_add_link.call_args.kwargs
        assert call_kwargs["vault_path"] == Path("/vault")
        assert call_kwargs["daily_notes_folder"] == "Journal"
        assert call_kwargs["note_filename"].endswith(".md")
        assert call_kwargs["summary_path"] == Path("/vault/Summaries/example-com.md")
        assert call_kwargs["url"] == "https://example.com"

    @patch("summarize_links.chat.tools.summarize.remove_url_line_from_note")
    @patch("summarize_links.chat.tools.summarize.add_summary_link_to_daily_note")
    @patch("summarize_links.chat.tools.summarize.write_summary_note_with_metadata")
    @patch("summarize_links.chat.tools.summarize.fetch_and_extract_metadata")
    @patch("summarize_links.chat.tools.summarize.create_llm_client")
    @patch("summarize_links.chat.tools.summarize.summary_exists")
    def test_execute_removes_url_from_daily_note(
        self,
        mock_exists: MagicMock,
        mock_create_client: MagicMock,
        mock_fetch: MagicMock,
        mock_write: MagicMock,
        mock_add_link: MagicMock,
        mock_remove_url: MagicMock,
    ) -> None:
        """Test that summarization removes original URL from daily note."""
        mock_exists.return_value = False

        # Setup mock client
        mock_client = MagicMock()
        mock_client.summarize_with_metadata.return_value = MagicMock(
            content="Test summary content",
            suggested_tags=["test"],
            content_type="article",
        )
        mock_create_client.return_value = mock_client

        # Setup mock fetch
        mock_fetch.return_value = MagicMock(
            content="Test page content",
            title="Test Page",
        )

        # Setup mock write
        mock_write.return_value = Path("/vault/Summaries/example-com.md")

        tool = SummarizeUrlTool()
        config = MagicMock(spec=Config)
        config.vault_path = Path("/vault")
        config.out_folder = "Summaries"
        config.daily_notes_folder = "Journal"
        config.force = False
        config.mock_mode = False
        config.model = "test-model"
        config.model_provider = "test"
        config.default_tags = []
        config.gemini_api_key = None
        config.ollama_endpoint = None
        config.azure_api_key = None
        config.azure_endpoint = None
        config.azure_deployment_name = None
        config.azure_api_version = None
        config.model_limits = {}
        config.playwright_enabled = False
        config.playwright_timeout = 30

        result = tool.execute(config, url="https://example.com")

        assert result.success is True
        # Verify URL removal was called
        mock_remove_url.assert_called_once()
        call_kwargs = mock_remove_url.call_args.kwargs
        assert call_kwargs["vault_path"] == Path("/vault")
        assert call_kwargs["daily_notes_folder"] == "Journal"
        assert call_kwargs["note_filename"].endswith(".md")
        assert call_kwargs["url"] == "https://example.com"


class TestExtractUrlFromText:
    """Tests for URL extraction from text."""

    def test_extract_full_url(self) -> None:
        """Test extracting full URL with protocol."""
        url = extract_url_from_text("Check out https://example.com/page")
        assert url == "https://example.com/page"

    def test_extract_http_url(self) -> None:
        """Test extracting HTTP URL."""
        url = extract_url_from_text("Visit http://example.com")
        assert url == "http://example.com"

    def test_extract_www_url(self) -> None:
        """Test extracting www URL (adds https)."""
        url = extract_url_from_text("Go to www.example.com")
        assert url == "https://www.example.com"

    def test_extract_url_with_path(self) -> None:
        """Test extracting URL with path."""
        url = extract_url_from_text("Read https://blog.example.com/posts/article")
        assert url == "https://blog.example.com/posts/article"

    def test_no_url_found(self) -> None:
        """Test when no URL is present."""
        url = extract_url_from_text("Just some regular text")
        assert url is None

    def test_strip_trailing_punctuation(self) -> None:
        """Test stripping trailing punctuation."""
        url = extract_url_from_text("Check https://example.com.")
        assert url == "https://example.com"


class TestDefaultRegistry:
    """Tests for the default registry."""

    def test_get_default_registry(self) -> None:
        """Test getting the default registry."""
        registry = get_default_registry()
        assert isinstance(registry, ToolRegistry)
        assert "summarize_url" in registry

    def test_default_registry_singleton(self) -> None:
        """Test that default registry is a singleton."""
        registry1 = get_default_registry()
        registry2 = get_default_registry()
        assert registry1 is registry2
