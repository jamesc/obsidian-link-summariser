"""
Tests for chat system tools (get_rate_limit_status, get_vault_status).
"""

from pathlib import Path

import pytest

from summarize_links.chat.tools.system import GetRateLimitStatusTool, GetVaultStatusTool
from summarize_links.config import Config
from summarize_links.rate_limiter import reset_rate_limiter


class TestGetRateLimitStatusTool:
    """Tests for GetRateLimitStatusTool."""

    @pytest.fixture
    def tool(self) -> GetRateLimitStatusTool:
        """Create a tool instance."""
        return GetRateLimitStatusTool()

    @pytest.fixture(autouse=True)
    def reset_limiter(self) -> None:
        """Reset rate limiter before each test."""
        reset_rate_limiter()

    def test_name(self, tool: GetRateLimitStatusTool) -> None:
        """Test tool name."""
        assert tool.name == "get_rate_limit_status"

    def test_description_not_empty(self, tool: GetRateLimitStatusTool) -> None:
        """Test tool has a description."""
        assert len(tool.description) > 0

    def test_no_parameters_required(self, tool: GetRateLimitStatusTool) -> None:
        """Test no parameters are required."""
        params = tool.parameters
        assert params["required"] == []

    def test_returns_status(self, tool: GetRateLimitStatusTool, tmp_path: Path) -> None:
        """Test that status is returned."""
        config = Config(
            vault_path=tmp_path,
            model="test-model",
            model_provider="google",
        )
        result = tool.execute(config)

        assert result.success is True
        # Should contain rate limit info
        assert "rpm" in result.data or "available" in result.data


class TestGetVaultStatusTool:
    """Tests for GetVaultStatusTool."""

    @pytest.fixture
    def tool(self) -> GetVaultStatusTool:
        """Create a tool instance."""
        return GetVaultStatusTool()

    @pytest.fixture
    def vault_with_mixed_summaries(self, tmp_path: Path) -> Path:
        """Create a vault with various summary types."""
        summaries = tmp_path / "Summaries"
        summaries.mkdir()

        # Success summary
        (summaries / "2025-01-22-success.md").write_text(
            """---
title: Success Article
date: 2025-01-22
summary_status: success
---

Good summary.
""",
            encoding="utf-8",
        )

        # Another success summary
        (summaries / "2025-01-21-another.md").write_text(
            """---
title: Another Article
date: 2025-01-21
summary_status: success
---

Another summary.
""",
            encoding="utf-8",
        )

        # Error summary (must be exactly "error" for scanner)
        (summaries / "2025-01-20-error.md").write_text(
            """---
title: Error Article
date: 2025-01-20
summary_status: error
---

## Summary Unavailable
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_name(self, tool: GetVaultStatusTool) -> None:
        """Test tool name."""
        assert tool.name == "get_vault_status"

    def test_description_not_empty(self, tool: GetVaultStatusTool) -> None:
        """Test tool has a description."""
        assert len(tool.description) > 0

    def test_no_vault_path(self, tool: GetVaultStatusTool) -> None:
        """Test error when vault path not set."""
        config = Config(vault_path=None)
        result = tool.execute(config)

        assert result.success is False
        assert "vault path" in result.message.lower()

    def test_returns_statistics(
        self, tool: GetVaultStatusTool, vault_with_mixed_summaries: Path
    ) -> None:
        """Test that correct statistics are returned."""
        config = Config(
            vault_path=vault_with_mixed_summaries,
            out_folder="Summaries",
            model="test-model",
            model_provider="google",
        )
        result = tool.execute(config)

        assert result.success is True
        assert "3" in result.message  # Total summaries

        stats = result.data["stats"]
        assert stats["total"] == 3
        assert stats["success"] == 2
        assert stats["error"] == 1

    def test_shows_date_range(
        self, tool: GetVaultStatusTool, vault_with_mixed_summaries: Path
    ) -> None:
        """Test that date range is shown."""
        config = Config(
            vault_path=vault_with_mixed_summaries,
            out_folder="Summaries",
        )
        result = tool.execute(config)

        assert result.success is True
        stats = result.data["stats"]
        assert stats["oldest_date"] == "2025-01-20"
        assert stats["newest_date"] == "2025-01-22"

    def test_empty_vault(self, tool: GetVaultStatusTool, tmp_path: Path) -> None:
        """Test vault with no summaries."""
        # Create empty summaries folder
        (tmp_path / "Summaries").mkdir()

        config = Config(
            vault_path=tmp_path,
            out_folder="Summaries",
        )
        result = tool.execute(config)

        assert result.success is True
        assert result.data["stats"]["total"] == 0

    def test_includes_config_info(
        self, tool: GetVaultStatusTool, vault_with_mixed_summaries: Path
    ) -> None:
        """Test that configuration info is included."""
        config = Config(
            vault_path=vault_with_mixed_summaries,
            out_folder="Summaries",
            model="gemini-2.5-flash",
            model_provider="google",
        )
        result = tool.execute(config)

        assert result.success is True
        assert result.data["model"] == "gemini-2.5-flash"
        assert result.data["provider"] == "google"
