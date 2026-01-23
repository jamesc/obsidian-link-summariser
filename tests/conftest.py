"""
Pytest configuration and shared fixtures.

This module provides common fixtures used across all test modules,
including temporary vault directories and sample content.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, Mock

import pytest

from summarize_links.config import Config
from summarize_links.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from summarize_links.config import Config


@pytest.fixture(autouse=True)
def mock_load_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock load_dotenv globally to prevent .env file from interfering with tests."""
    monkeypatch.setattr("summarize_links.config.load_dotenv", Mock())


@pytest.fixture(autouse=True)
def mock_langfuse_globally(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Mock Langfuse class globally to prevent authentication attempts in tests."""
    # Don't set env vars for tests that specifically test Langfuse configuration
    test_name = request.node.name
    # Get the full node ID which includes class name
    node_id = request.node.nodeid

    # Set environment variables for all tests except those specifically testing langfuse config
    # Check both test name and node ID (which includes class name like
    # "test_config.py::TestLangfuseConfig::test_name")
    if "TestLangfuseConfig" not in node_id and test_name != "test_langfuse_requires_credentials":
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test-auto")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test-auto")

    # Create a comprehensive mock
    mock_lf = Mock()
    mock_lf.auth_check.return_value = True

    # Create a chat prompt mock with proper structure for summarization
    mock_chat_prompt = Mock()
    mock_chat_prompt.prompt = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant that summarizes web pages. "
                "You MUST respond with valid JSON."
            ),
        },
        {"role": "user", "content": "Summarize the web page{{title}}:\n{{url}}\n\n{{content}}"},
    ]
    mock_chat_prompt.version = 1
    mock_chat_prompt.name = "summarize-document"
    # compile() returns list of message dicts with variables substituted
    mock_chat_prompt.compile = Mock(
        return_value=[
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that summarizes web pages. "
                    "You MUST respond with valid JSON."
                ),
            },
            {"role": "user", "content": "compiled user prompt"},
        ]
    )

    # Create a text prompt mock for chat system prompt
    mock_text_prompt = Mock()
    mock_text_prompt.prompt = (
        "You are a helpful assistant for managing an Obsidian vault.\n"
        "Today is {{current_date}} ({{current_weekday}}).\n"
        "Vault: {{vault_path}}\n"
        "Model: {{model}}\n"
        "Provider: {{provider}}"
    )
    mock_text_prompt.version = 1
    mock_text_prompt.name = "chat-assistant/system"
    # compile() returns a simple string with variables substituted
    mock_text_prompt.compile = Mock(
        return_value=(
            "You are a helpful assistant for managing an Obsidian vault.\n"
            "Today is 2026-01-23 (Friday).\n"
            "Vault: /test/vault\n"
            "Model: gpt-4o-mini\n"
            "Provider: azure"
        )
    )

    # Mock get_prompt to return different mocks based on prompt name
    def get_prompt_mock(name: str, **kwargs: Any) -> Mock:
        if name == "chat-assistant/system":
            return mock_text_prompt
        return mock_chat_prompt

    mock_lf.get_prompt = Mock(side_effect=get_prompt_mock)

    mock_lf.start_as_current_observation.return_value.__enter__ = Mock(return_value=Mock())
    mock_lf.start_as_current_observation.return_value.__exit__ = Mock(return_value=False)
    mock_lf.flush.return_value = None
    mock_lf.score.return_value = None

    def mock_langfuse_class(*args: Any, **kwargs: Any) -> Mock:
        """Mock Langfuse class constructor."""
        return mock_lf

    # Mock at both the module level and the import location in langfuse_tracer
    monkeypatch.setattr("langfuse.Langfuse", mock_langfuse_class)
    monkeypatch.setattr("summarize_links.langfuse_tracer.Langfuse", mock_langfuse_class)


@pytest.fixture
def sample_daily_note_content() -> str:
    """Sample daily note content with various URL formats."""
    return """# 2025-12-16

## Articles to Read
- [Gemini API pricing](https://ai.google.dev/pricing)
- [Obsidian plugins](https://obsidian.md/plugins)
https://example.com/direct-link

## Tasks
- Follow up on [[2025-12-15]]
- Check [[Meeting Notes]]

## Notes
Found an interesting article at https://blog.example.com/post.html about testing.
"""


@pytest.fixture
def sample_urls() -> list[str]:
    """Expected URLs from sample_daily_note_content."""
    return [
        "https://ai.google.dev/pricing",
        "https://obsidian.md/plugins",
        "https://example.com/direct-link",
        "https://blog.example.com/post.html",
    ]


@pytest.fixture
def mock_vault(tmp_path: Path, sample_daily_note_content: str) -> Path:
    """
    Create a mock Obsidian vault structure.

    Structure:
        vault/
        ├── 2025-12-16.md (daily note with URLs)
        ├── Journal/
        │   └── 2025-12-15.md
        └── Summaries/ (empty, for output)
    """
    # Create daily note in root
    daily_note = tmp_path / "2025-12-16.md"
    daily_note.write_text(sample_daily_note_content)

    # Create Journal folder with a note
    journal = tmp_path / "Journal"
    journal.mkdir()
    (journal / "2025-12-15.md").write_text("# 2025-12-15\n\nYesterday's note.")

    # Create empty Summaries folder
    summaries = tmp_path / "Summaries"
    summaries.mkdir()

    return tmp_path


@pytest.fixture
def mock_vault_with_config(mock_vault: Path) -> Path:
    """Mock vault with a .summarizer-config.yaml file."""
    config_content = """
model_provider: "google"
out_folder: "MySummaries"
max_links: 5
daily_notes_folder: "Journal"
summary_model: "gemini-2.0-flash-exp"
"""
    (mock_vault / ".summarizer-config.yaml").write_text(config_content)
    return mock_vault


@pytest.fixture
def sample_html_content() -> str:
    """Sample HTML page content for extraction tests."""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Test Article - Example Site</title>
    <style>body { font-family: sans-serif; }</style>
    <script>console.log('tracking');</script>
</head>
<body>
    <nav>
        <a href="/">Home</a>
        <a href="/about">About</a>
    </nav>
    <article>
        <h1>Test Article Title</h1>
        <p>This is the main content of the article. It contains important information
        that should be extracted for summarization.</p>
        <p>Here is another paragraph with more details about the topic.</p>
        <ul>
            <li>Key point one</li>
            <li>Key point two</li>
            <li>Key point three</li>
        </ul>
    </article>
    <footer>
        <p>Copyright 2025 Example Site</p>
    </footer>
</body>
</html>
"""


@pytest.fixture
def sample_gemini_response() -> str:
    """Sample Gemini API response for mock testing."""
    return """---
source: https://example.com/article
title: Test Article Title
date: 2025-12-16
---

## Overview
This article discusses important information about the topic at hand.

## Key Points
- Key point one is significant
- Key point two provides context
- Key point three offers practical advice

## Actions
- Review the key points
- Apply learnings to current project
"""


@pytest.fixture
def fixed_date() -> datetime:
    """Fixed datetime for deterministic tests."""
    return datetime(2025, 12, 16, 10, 30, 0)


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    """
    Create a mock Config object with test values.

    Returns:
        Config object suitable for testing.
    """
    from summarize_links.config import Config

    return Config(
        model_provider="google",
        gemini_api_key="test-api-key",
        model="gemini-2.5-flash",
        vault_path=tmp_path,
        out_folder="Summaries",
        max_links=10,
        dry_run=False,
        verbose=False,
        force=False,
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
        langfuse_base_url="https://cloud.langfuse.com",
    )


class MockLangfuseTracer:
    """
    Mock Langfuse tracer for testing.

    Records all method calls for assertions while providing no-op implementations.
    """

    def __init__(self) -> None:
        """Initialize mock tracer with call tracking."""
        self.trace_calls: list[dict[str, Any]] = []
        self.span_calls: list[dict[str, Any]] = []
        self.generation_calls: list[dict[str, Any]] = []
        self.score_calls: list[dict[str, Any]] = []
        self.flush_calls: int = 0

    @contextmanager
    def trace_url_processing(
        self,
        url: str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[MagicMock, None, None]:
        """Mock trace - records call and yields a mock object."""
        self.trace_calls.append(
            {
                "url": url,
                "name": name,
                "metadata": metadata,
            }
        )
        mock_trace = MagicMock()
        mock_trace.update = MagicMock()
        yield mock_trace

    @contextmanager
    def trace_span(
        self,
        name: str,
        input_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[MagicMock, None, None]:
        """Mock span - records call and yields a mock object."""
        self.span_calls.append(
            {
                "name": name,
                "input_data": input_data,
                "metadata": metadata,
            }
        )
        mock_span = MagicMock()
        mock_span.update = MagicMock()
        yield mock_span

    @contextmanager
    def trace_generation(
        self,
        name: str,
        input_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        prompt: Any | None = None,
    ) -> Generator[MagicMock, None, None]:
        """Mock generation - records call and yields a mock object."""
        self.generation_calls.append(
            {
                "name": name,
                "input_data": input_data,
                "metadata": metadata,
                "model": model,
                "prompt": prompt,
            }
        )
        mock_generation = MagicMock()
        mock_generation.update = MagicMock()
        yield mock_generation

    def score_trace(
        self,
        trace_id: str,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        """Mock score - records call."""
        self.score_calls.append(
            {
                "trace_id": trace_id,
                "name": name,
                "value": value,
                "comment": comment,
            }
        )

    def flush(self) -> None:
        """Mock flush - records call."""
        self.flush_calls += 1


@pytest.fixture
def mock_tracer() -> MockLangfuseTracer:
    """Provide a mock Langfuse tracer for tests."""
    return MockLangfuseTracer()


@pytest.fixture
def mock_langfuse_client(
    monkeypatch: pytest.MonkeyPatch, mock_tracer: MockLangfuseTracer
) -> MockLangfuseTracer:
    """
    Mock the global Langfuse tracer for tests.

    This fixture patches the global tracer so tests can run without
    actual Langfuse credentials.
    """
    # Patch get_tracer to return our mock
    monkeypatch.setattr(
        "summarize_links.langfuse_tracer.get_tracer",
        lambda: mock_tracer,
    )

    # Also patch _global_tracer directly
    monkeypatch.setattr(
        "summarize_links.langfuse_tracer._global_tracer",
        mock_tracer,
    )

    return mock_tracer


@pytest.fixture
def mock_playwright_browser() -> Mock:
    """
    Mock Playwright browser context for testing.

    Provides a mock browser, context, and page that can be used
    to test Playwright functionality without launching a real browser.
    """
    # Create mock page
    mock_page = Mock()
    mock_page.goto.return_value = Mock(status=200)
    mock_page.content.return_value = "<html><body>Test content</body></html>"
    mock_page.close.return_value = None
    mock_page.route = Mock()

    # Create mock context
    mock_context = Mock()
    mock_context.new_page.return_value = mock_page
    mock_context.close.return_value = None

    # Create mock browser
    mock_browser = Mock()
    mock_browser.new_context.return_value = mock_context
    mock_browser.close.return_value = None

    return mock_browser


@pytest.fixture
def mock_rate_limiter() -> RateLimiter:
    """
    Create a rate limiter with high limits for testing.

    Returns a RateLimiter configured with generous limits that won't
    interfere with test execution, and safety margin disabled.
    """
    from summarize_links.rate_limiter import ModelRateLimits, RateLimiter

    limits = ModelRateLimits(rpm_limit=1000, tpm_limit=10000000, daily_limit=10000)
    return RateLimiter(model="test-model", limits=limits, _apply_safety_margin=False)


@pytest.fixture
def mock_time_functions(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[Any, Any], None, None]:
    """
    Create mock time functions that advance time when sleep is called.

    This is essential for testing rate limiting and retry logic without
    real delays. The mock time advances whenever sleep() is called.

    Yields:
        Tuple of (mock_time, mock_sleep) functions.
    """
    current_time = [1000.0]  # Use list to allow mutation in nested function

    def mock_time() -> float:
        return current_time[0]

    def mock_sleep(seconds: float) -> None:
        current_time[0] += seconds

    # Patch both llm modules and rate_limiter
    monkeypatch.setattr("summarize_links.llm.azure.time.sleep", mock_sleep)
    monkeypatch.setattr("summarize_links.llm.azure.time.time", mock_time)
    monkeypatch.setattr("summarize_links.llm.gemini.time.sleep", mock_sleep)
    monkeypatch.setattr("summarize_links.llm.gemini.time.time", mock_time)
    monkeypatch.setattr("summarize_links.rate_limiter.time.sleep", mock_sleep)
    monkeypatch.setattr("summarize_links.rate_limiter.time.time", mock_time)

    yield mock_time, mock_sleep


@pytest.fixture
def mock_chat_config(tmp_path: Path) -> MagicMock:
    """
    Create a mock Config object for chat testing.

    Provides a standard Azure chat configuration suitable for most
    chat-related tests. Override specific fields as needed in tests.
    """
    config = MagicMock(spec=Config)
    config.model_provider = "azure"
    config.model = "gpt-4o"
    config.chat_model = "gpt-4o-mini"
    config.chat_azure_endpoint = "https://test.openai.azure.com"
    config.chat_azure_api_key = "test-key"
    config.chat_azure_deployment = "gpt-4o-mini"
    config.vault_path = tmp_path / "vault"
    config.out_folder = "Summaries"
    config.force = False
    config.default_tags = None
    config.model_limits = None
    # Chat session config
    config.chat_max_history_messages = 50
    config.chat_max_context_tokens = 100000
    config.chat_auto_save = False
    config.chat_save_path = ".chat-history.json"
    config.chat_streaming = True
    config.chat_confirm_tools = False
    return config


def create_mock_azure_response(
    content: str,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    function_call: dict[str, Any] | None = None,
) -> MagicMock:
    """
    Create a mock Azure OpenAI API response.

    Args:
        content: The response text content
        prompt_tokens: Number of prompt tokens (default: 100)
        completion_tokens: Number of completion tokens (default: 50)
        function_call: Optional function call dict with 'name' and 'arguments'

    Returns:
        Mock response object matching Azure OpenAI response structure
    """
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_message = MagicMock()

    if function_call:
        mock_function_call = MagicMock()
        mock_function_call.name = function_call["name"]
        mock_function_call.arguments = function_call["arguments"]
        mock_message.function_call = mock_function_call
        mock_message.content = None
    else:
        mock_message.content = content
        mock_message.function_call = None

    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = prompt_tokens
    mock_usage.completion_tokens = completion_tokens
    mock_usage.total_tokens = prompt_tokens + completion_tokens
    mock_response.usage = mock_usage

    return mock_response


def create_mock_gemini_response(
    text: str,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> MagicMock:
    """
    Create a mock Gemini API response.

    Args:
        text: The response text content
        prompt_tokens: Number of prompt tokens (default: 100)
        completion_tokens: Number of completion tokens (default: 50)

    Returns:
        Mock response object matching Gemini response structure
    """
    mock_response = MagicMock()
    mock_response.parts = [MagicMock()]
    mock_response.text = text

    # Mock usage metadata
    mock_usage = MagicMock()
    mock_usage.prompt_token_count = prompt_tokens
    mock_usage.candidates_token_count = completion_tokens
    mock_usage.total_token_count = prompt_tokens + completion_tokens
    mock_response.usage_metadata = mock_usage

    return mock_response
