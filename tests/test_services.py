"""Tests for summarization and summaries services."""

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from summarize_links.config import Config
from summarize_links.exceptions import ContentFetchError, RateLimitError
from summarize_links.models import PageMetadata, SummaryResult, UrlWithContext
from summarize_links.services import summarization
from summarize_links.services.summaries import find_summary_metadata


def test_find_summary_metadata_by_slug(tmp_path: Path) -> None:
    vault = tmp_path
    out_folder = "Summaries"
    summaries_path = vault / out_folder
    summaries_path.mkdir()
    content = """---
source: https://example.com
date: 2024-01-01
from: [[Daily/2024-01-01]]
---
Body
"""
    (summaries_path / "2024-01-01-example.md").write_text(content, encoding="utf-8")
    config = Config(vault_path=vault, out_folder=out_folder)

    meta = find_summary_metadata("example", config)

    assert meta is not None
    assert meta.source_url == "https://example.com"
    assert meta.original_date.date().isoformat() == "2024-01-01"
    assert meta.source_note is None or meta.source_note in {"Daily/2024-01-01.md", "2024-01-01.md"}


def test_resummarize_not_found(tmp_path: Path) -> None:
    config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="x")
    outcome = summarization.resummarize("nonexistent", config)
    assert outcome.success is False


def test_process_urls_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_create_llm_client(**kwargs: object) -> str:
        return "client"

    def fake_process_url(
        url_ctx: Any, config: Any, client: Any, **kwargs: Any
    ) -> summarization.ProcessOutcome:
        calls.append(url_ctx.url)
        return summarization.ProcessOutcome(True, f"ok:{url_ctx.url}", False)

    monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)
    monkeypatch.setattr(summarization, "process_url", fake_process_url)

    config = Config(vault_path=Path("."), out_folder="Summaries", gemini_api_key="x")
    url_ctxs = [UrlWithContext(url="https://a.com"), UrlWithContext(url="https://b.com")]

    code, outcomes = summarization.process_urls(url_ctxs, config)

    assert code == summarization.EXIT_SUCCESS
    assert calls == ["https://a.com", "https://b.com"]
    assert [o.message for o in outcomes] == ["ok:https://a.com", "ok:https://b.com"]


def test_process_urls_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_create_llm_client(**kwargs: object) -> str:
        return "client"

    def fake_process_url(
        url_ctx: Any, config: Any, client: Any, **kwargs: Any
    ) -> summarization.ProcessOutcome:
        return summarization.ProcessOutcome(False, f"fail:{url_ctx.url}", False)

    monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)
    monkeypatch.setattr(summarization, "process_url", fake_process_url)

    config = Config(vault_path=Path("."), out_folder="Summaries", gemini_api_key="x")
    url_ctxs = [UrlWithContext(url="https://a.com"), UrlWithContext(url="https://b.com")]

    code, outcomes = summarization.process_urls(url_ctxs, config)

    assert code == summarization.EXIT_ERROR
    assert len(outcomes) == 2


class TestProcessUrl:
    """Comprehensive tests for the process_url service function."""

    @pytest.fixture
    def mock_client(self) -> Mock:
        """Create a mock LLM client."""
        client = Mock()
        client.summarize_with_metadata.return_value = SummaryResult(
            content="## Summary\n\nThis is a test summary.",
            suggested_tags=["test", "article"],
            content_type="article",
        )
        return client

    @pytest.fixture
    def mock_page_metadata(self) -> PageMetadata:
        """Create mock page metadata."""
        return PageMetadata(
            title="Test Article",
            author="Test Author",
            domain="example.com",
            content="This is test content for the article.",
            published_date="2024-01-15",
            article_tags=["technology"],
        )

    def test_successful_summary_creation(
        self,
        tmp_path: Path,
        mock_client: Mock,
        mock_page_metadata: PageMetadata,
        mock_langfuse_client: Any,
    ) -> None:
        """Complete pipeline: fetch → summarize → write → link."""
        # Create a source note
        note_file = tmp_path / "2025-01-15.md"
        note_file.write_text("# Daily Note\n\n- https://example.com/article\n")

        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test-key")
        url_ctx = UrlWithContext(url="https://example.com/article", tags=["reading"])

        with patch(
            "summarize_links.services.summarization.fetch_and_extract_metadata"
        ) as mock_fetch:
            mock_fetch.return_value = mock_page_metadata

            outcome = summarization.process_url(
                url_ctx,
                config,
                mock_client,
                source_note="2025-01-15.md",
                source_date=datetime(2025, 1, 15),
            )

        # Verify summary file was created
        assert outcome.success is True
        assert outcome.summary_path is not None
        summary_path = Path(outcome.summary_path)
        assert summary_path.exists()

        # Verify frontmatter
        content = summary_path.read_text()
        assert "source: https://example.com/article" in content
        assert "date: 2025-01-15" in content
        assert "title: Test Article" in content
        assert "author: Test Author" in content
        assert "- test" in content
        assert "- article" in content
        assert "- reading" in content  # User tags merged

        # Verify summary content
        assert "## Summary" in content
        assert "This is a test summary." in content

        # Verify source note was linked
        note_content = note_file.read_text()
        assert "## Summaries" in note_content
        assert "[[" in note_content

    def test_skips_existing_summary_without_force(
        self, tmp_path: Path, mock_client: Mock, mock_langfuse_client: Any
    ) -> None:
        """Skips processing if summary exists and force=False."""
        # Create an existing summary
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        date = datetime(2025, 1, 15)
        summary_file = summaries / "2025-01-15-article.md"
        summary_file.write_text(
            """---
source: https://example.com/article
date: 2025-01-15
summary_status: success
---
Existing summary
"""
        )

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            force=False,
            gemini_api_key="test-key",
        )
        url_ctx = UrlWithContext(url="https://example.com/article")

        outcome = summarization.process_url(url_ctx, config, mock_client, source_date=date)

        # Should skip
        assert outcome.success is True
        assert "Skipped" in outcome.message
        assert mock_client.summarize_with_metadata.call_count == 0

    def test_overwrites_with_force_mode(
        self,
        tmp_path: Path,
        mock_client: Mock,
        mock_page_metadata: PageMetadata,
        mock_langfuse_client: Any,
    ) -> None:
        """Overwrites existing summary when force=True."""
        # Create an existing summary
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        date = datetime(2025, 1, 15)
        summary_file = summaries / "2025-01-15-article.md"
        summary_file.write_text(
            """---
source: https://example.com/article
date: 2025-01-15
summary_status: success
---
Old summary
"""
        )

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            force=True,
            gemini_api_key="test-key",
        )
        url_ctx = UrlWithContext(url="https://example.com/article")

        with patch(
            "summarize_links.services.summarization.fetch_and_extract_metadata"
        ) as mock_fetch:
            mock_fetch.return_value = mock_page_metadata

            outcome = summarization.process_url(url_ctx, config, mock_client, source_date=date)

        # Should overwrite
        assert outcome.success is True
        content = summary_file.read_text()
        assert "This is a test summary" in content
        assert "Old summary" not in content

    def test_handles_fetch_error_gracefully(
        self, tmp_path: Path, mock_client: Mock, mock_langfuse_client: Any
    ) -> None:
        """Creates error stub when fetch fails."""
        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test-key")
        url_ctx = UrlWithContext(url="https://example.com/article")

        with patch(
            "summarize_links.services.summarization.fetch_and_extract_metadata"
        ) as mock_fetch:
            mock_fetch.side_effect = ContentFetchError("Connection timeout")

            outcome = summarization.process_url(
                url_ctx,
                config,
                mock_client,
                source_date=datetime(2025, 1, 15),
            )

        # Should create error stub
        assert outcome.success is False
        assert outcome.error_type == "fetch"
        assert "Connection timeout" in outcome.message

        # Check stub was created
        summaries = tmp_path / "Summaries"
        stub_files = list(summaries.glob("*.md"))
        assert len(stub_files) == 1
        stub_content = stub_files[0].read_text()
        assert "Summary Unavailable" in stub_content
        assert "summary_status: fetch_error" in stub_content

    def test_handles_rate_limit_error(
        self,
        tmp_path: Path,
        mock_client: Mock,
        mock_page_metadata: PageMetadata,
        mock_langfuse_client: Any,
    ) -> None:
        """Handles rate limit error and creates stub for retry."""
        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test-key")
        url_ctx = UrlWithContext(url="https://example.com/article")

        with patch(
            "summarize_links.services.summarization.fetch_and_extract_metadata"
        ) as mock_fetch:
            mock_fetch.return_value = mock_page_metadata
            mock_client.summarize_with_metadata.side_effect = RateLimitError("Rate limit exceeded")

            outcome = summarization.process_url(
                url_ctx,
                config,
                mock_client,
                source_date=datetime(2025, 1, 15),
            )

        # Should return error outcome
        assert outcome.success is False
        assert outcome.error_type == "rate_limit"
        assert "Rate limited" in outcome.message

        # Should create stub for rate limit (to allow retry later)
        summaries = tmp_path / "Summaries"
        stub_files = list(summaries.glob("*.md"))
        assert len(stub_files) == 1
        stub_content = stub_files[0].read_text()
        assert "rate limit" in stub_content.lower()

    def test_preserves_existing_summary_date(
        self,
        tmp_path: Path,
        mock_client: Mock,
        mock_page_metadata: PageMetadata,
        mock_langfuse_client: Any,
    ) -> None:
        """Uses existing summary date when re-summarizing."""
        # Create existing summary with old date
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        summary_file = summaries / "2024-12-01-article.md"
        summary_file.write_text(
            """---
source: https://example.com/article
date: 2024-12-01
summary_status: success
---
Old summary
"""
        )

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            force=True,
            gemini_api_key="test-key",
        )
        url_ctx = UrlWithContext(url="https://example.com/article")
        new_date = datetime(2025, 1, 15)

        with patch(
            "summarize_links.services.summarization.fetch_and_extract_metadata"
        ) as mock_fetch:
            mock_fetch.return_value = mock_page_metadata

            outcome = summarization.process_url(url_ctx, config, mock_client, source_date=new_date)

        # Should preserve old date
        assert outcome.success is True
        content = summary_file.read_text()
        assert "date: 2024-12-01" in content
        assert "date: 2025-01-15" not in content

    def test_uses_source_date_for_new_summary(
        self,
        tmp_path: Path,
        mock_client: Mock,
        mock_page_metadata: PageMetadata,
        mock_langfuse_client: Any,
    ) -> None:
        """Uses provided source date for new summaries."""
        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test-key")
        url_ctx = UrlWithContext(url="https://example.com/article")
        source_date = datetime(2025, 1, 15)

        with patch(
            "summarize_links.services.summarization.fetch_and_extract_metadata"
        ) as mock_fetch:
            mock_fetch.return_value = mock_page_metadata

            outcome = summarization.process_url(
                url_ctx, config, mock_client, source_date=source_date
            )

        # Should use source date
        assert outcome.success is True
        assert outcome.summary_path is not None
        summary_path = Path(outcome.summary_path)
        assert "2025-01-15" in summary_path.name

        content = summary_path.read_text()
        assert "date: 2025-01-15" in content

    def test_dry_run_mode(
        self, tmp_path: Path, mock_client: Mock, mock_langfuse_client: Any
    ) -> None:
        """Dry run doesn't write files."""
        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            dry_run=True,
            gemini_api_key="test-key",
        )
        url_ctx = UrlWithContext(url="https://example.com/article")

        outcome = summarization.process_url(
            url_ctx,
            config,
            mock_client,
            source_date=datetime(2025, 1, 15),
        )

        # Should report what would happen
        assert outcome.success is True
        assert "Would process" in outcome.message

        # Should not create any files
        summaries = tmp_path / "Summaries"
        if summaries.exists():
            assert len(list(summaries.glob("*.md"))) == 0

        # Should not call LLM
        assert mock_client.summarize_with_metadata.call_count == 0

    def test_progress_callback_called(
        self,
        tmp_path: Path,
        mock_client: Mock,
        mock_page_metadata: PageMetadata,
        mock_langfuse_client: Any,
    ) -> None:
        """Progress callback called at each stage."""
        progress_calls = []

        def progress_cb(stage: str, detail: str) -> None:
            progress_calls.append((stage, detail))

        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test-key")
        url_ctx = UrlWithContext(url="https://example.com/article")

        with patch(
            "summarize_links.services.summarization.fetch_and_extract_metadata"
        ) as mock_fetch:
            mock_fetch.return_value = mock_page_metadata

            outcome = summarization.process_url(
                url_ctx,
                config,
                mock_client,
                source_date=datetime(2025, 1, 15),
                progress_cb=progress_cb,
            )

        # Should have called progress callback
        assert outcome.success is True
        assert len(progress_calls) >= 2
        assert any("Fetching" in stage for stage, _ in progress_calls)
        assert any("Summarizing" in stage for stage, _ in progress_calls)


class TestProcessUrls:
    """Tests for batch URL processing."""

    def test_processes_multiple_urls(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Processes batch of URLs, returns outcomes."""
        processed_urls = []

        def fake_create_llm_client(**kwargs: object) -> Mock:
            return Mock()

        def fake_process_url(
            url_ctx: UrlWithContext, config: Config, client: Any, **kwargs: Any
        ) -> summarization.ProcessOutcome:
            processed_urls.append(url_ctx.url)
            return summarization.ProcessOutcome(
                True, f"Success: {url_ctx.url}", True, f"/path/to/{url_ctx.url}.md"
            )

        monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)
        monkeypatch.setattr(summarization, "process_url", fake_process_url)

        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test")
        url_ctxs = [
            UrlWithContext(url="https://a.com"),
            UrlWithContext(url="https://b.com"),
            UrlWithContext(url="https://c.com"),
        ]

        exit_code, outcomes = summarization.process_urls(url_ctxs, config)

        assert exit_code == summarization.EXIT_SUCCESS
        assert len(outcomes) == 3
        assert processed_urls == ["https://a.com", "https://b.com", "https://c.com"]
        assert all(o.success for o in outcomes)

    def test_continues_on_individual_failures(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One URL failing doesn't stop others."""
        call_count = [0]

        def fake_create_llm_client(**kwargs: object) -> Mock:
            return Mock()

        def fake_process_url(
            url_ctx: UrlWithContext, config: Config, client: Any, **kwargs: Any
        ) -> summarization.ProcessOutcome:
            call_count[0] += 1
            # Second URL fails
            if call_count[0] == 2:
                return summarization.ProcessOutcome(False, "Failed", False)
            return summarization.ProcessOutcome(True, "Success", True)

        monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)
        monkeypatch.setattr(summarization, "process_url", fake_process_url)

        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test")
        url_ctxs = [
            UrlWithContext(url="https://a.com"),
            UrlWithContext(url="https://b.com"),
            UrlWithContext(url="https://c.com"),
        ]

        exit_code, outcomes = summarization.process_urls(url_ctxs, config)

        # Should still be success if at least one succeeded
        assert exit_code == summarization.EXIT_SUCCESS
        assert len(outcomes) == 3
        assert outcomes[0].success is True
        assert outcomes[1].success is False
        assert outcomes[2].success is True

    def test_exit_code_all_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns EXIT_SUCCESS when all succeed."""

        def fake_create_llm_client(**kwargs: object) -> Mock:
            return Mock()

        def fake_process_url(
            url_ctx: UrlWithContext, config: Config, client: Any, **kwargs: Any
        ) -> summarization.ProcessOutcome:
            return summarization.ProcessOutcome(True, "Success", True)

        monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)
        monkeypatch.setattr(summarization, "process_url", fake_process_url)

        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test")
        url_ctxs = [UrlWithContext(url=f"https://{i}.com") for i in range(3)]

        exit_code, outcomes = summarization.process_urls(url_ctxs, config)

        assert exit_code == summarization.EXIT_SUCCESS
        assert all(o.success for o in outcomes)

    def test_exit_code_partial_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns EXIT_SUCCESS when some succeed."""
        call_count = [0]

        def fake_create_llm_client(**kwargs: object) -> Mock:
            return Mock()

        def fake_process_url(
            url_ctx: UrlWithContext, config: Config, client: Any, **kwargs: Any
        ) -> summarization.ProcessOutcome:
            call_count[0] += 1
            success = call_count[0] % 2 == 1  # Alternate success/failure
            return summarization.ProcessOutcome(success, "Message", success)

        monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)
        monkeypatch.setattr(summarization, "process_url", fake_process_url)

        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test")
        url_ctxs = [UrlWithContext(url=f"https://{i}.com") for i in range(4)]

        exit_code, outcomes = summarization.process_urls(url_ctxs, config)

        # At least one succeeded
        assert exit_code == summarization.EXIT_SUCCESS
        assert sum(o.success for o in outcomes) == 2

    def test_exit_code_all_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns EXIT_ERROR when all fail."""

        def fake_create_llm_client(**kwargs: object) -> Mock:
            return Mock()

        def fake_process_url(
            url_ctx: UrlWithContext, config: Config, client: Any, **kwargs: Any
        ) -> summarization.ProcessOutcome:
            return summarization.ProcessOutcome(False, "Failed", False)

        monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)
        monkeypatch.setattr(summarization, "process_url", fake_process_url)

        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test")
        url_ctxs = [UrlWithContext(url=f"https://{i}.com") for i in range(3)]

        exit_code, outcomes = summarization.process_urls(url_ctxs, config)

        assert exit_code == summarization.EXIT_ERROR
        assert all(not o.success for o in outcomes)

    def test_processes_all_provided_urls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Processes all URLs provided (max_links is applied by caller)."""
        processed_count = [0]

        def fake_create_llm_client(**kwargs: object) -> Mock:
            return Mock()

        def fake_process_url(
            url_ctx: UrlWithContext, config: Config, client: Any, **kwargs: Any
        ) -> summarization.ProcessOutcome:
            processed_count[0] += 1
            return summarization.ProcessOutcome(True, "Success", True)

        monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)
        monkeypatch.setattr(summarization, "process_url", fake_process_url)

        config = Config(
            vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test", max_links=3
        )
        # Caller applies max_links and passes limited set
        url_ctxs = [UrlWithContext(url=f"https://{i}.com") for i in range(3)]

        exit_code, outcomes = summarization.process_urls(url_ctxs, config)

        # Should process all provided URLs
        assert processed_count[0] == 3
        assert len(outcomes) == 3


class TestResumarize:
    """Tests for resummarizing existing summaries."""

    def test_finds_and_updates_existing_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Finds summary by slug and updates it."""
        # Create an existing summary
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        summary_file = summaries / "2024-01-15-test-article.md"
        summary_file.write_text(
            """---
source: https://example.com/test-article
date: 2024-01-15
from: "[[2024-01-15]]"
summary_status: success
---

Old summary content.
"""
        )

        # Mock the process_url to return success
        def fake_process_url(
            url_ctx: UrlWithContext, config: Config, client: Any, **kwargs: Any
        ) -> summarization.ProcessOutcome:
            return summarization.ProcessOutcome(
                True, "Updated", True, str(summary_file), "test-article"
            )

        def fake_create_llm_client(**kwargs: object) -> Mock:
            return Mock()

        monkeypatch.setattr(summarization, "process_url", fake_process_url)
        monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            gemini_api_key="test",
            force=True,
        )

        outcome = summarization.resummarize("test-article", config)

        assert outcome.success is True
        assert "Updated" in outcome.message

    def test_returns_error_for_missing_summary(self, tmp_path: Path) -> None:
        """Returns failure outcome when summary not found."""
        config = Config(vault_path=tmp_path, out_folder="Summaries", gemini_api_key="test")

        outcome = summarization.resummarize("nonexistent-slug", config)

        assert outcome.success is False
        assert "no existing summary found" in outcome.message.lower()

    def test_preserves_original_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Keeps original date and source note."""
        # Create existing summary with specific metadata
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        summary_file = summaries / "2024-01-15-article.md"
        summary_file.write_text(
            """---
source: https://example.com/article
date: 2024-01-15
from: "[[Daily/2024-01-15]]"
summary_status: success
---

Original content.
"""
        )

        captured_kwargs = {}

        def fake_process_url(
            url_ctx: UrlWithContext, config: Config, client: Any, **kwargs: Any
        ) -> summarization.ProcessOutcome:
            captured_kwargs.update(kwargs)
            return summarization.ProcessOutcome(True, "Updated", True, str(summary_file), "article")

        def fake_create_llm_client(**kwargs: object) -> Mock:
            return Mock()

        monkeypatch.setattr(summarization, "process_url", fake_process_url)
        monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            gemini_api_key="test",
            force=True,
        )

        outcome = summarization.resummarize("article", config)

        assert outcome.success is True
        # Should preserve original date
        assert captured_kwargs.get("source_date") == datetime(2024, 1, 15)
        # Should preserve source note
        assert "source_note" in captured_kwargs

    def test_force_mode_used_for_resummarize(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resummarize uses force override to allow updating existing summaries."""
        # Create existing summary
        summaries = tmp_path / "Summaries"
        summaries.mkdir()
        summary_file = summaries / "2024-01-15-article.md"
        summary_file.write_text(
            """---
source: https://example.com/article
date: 2024-01-15
from: "[[2024-01-15]]"
summary_status: success
---

Content.
"""
        )

        # Mock to verify force_override is used
        captured_kwargs = {}

        def fake_process_url(
            url_ctx: UrlWithContext, config: Config, client: Any, **kwargs: Any
        ) -> summarization.ProcessOutcome:
            captured_kwargs.update(kwargs)
            return summarization.ProcessOutcome(True, "Updated", True, str(summary_file), "article")

        def fake_create_llm_client(**kwargs: object) -> Mock:
            return Mock()

        monkeypatch.setattr(summarization, "process_url", fake_process_url)
        monkeypatch.setattr(summarization, "create_llm_client", fake_create_llm_client)

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
            gemini_api_key="test",
            force=False,
        )

        outcome = summarization.resummarize("article", config)

        # Should succeed with force_override
        assert outcome.success is True
        # Verify force_override was passed
        assert captured_kwargs.get("force_override") is True
