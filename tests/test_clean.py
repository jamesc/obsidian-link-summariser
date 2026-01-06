"""Tests for the clean command."""

from pathlib import Path

from summarize_links.commands.clean import clean_whitespace, cmd_clean
from summarize_links.config import Config


class TestCleanWhitespace:
    """Tests for the clean_whitespace function."""

    def test_collapses_consecutive_blank_lines(self) -> None:
        """Should collapse multiple blank lines into one."""
        content = "# Header\n\n\n\nContent\n"
        result = clean_whitespace(content)
        assert result == "# Header\n\nContent\n"

    def test_removes_leading_blank_lines(self) -> None:
        """Should remove blank lines at the start."""
        content = "\n\n# Header\nContent\n"
        result = clean_whitespace(content)
        assert result == "# Header\nContent\n"

    def test_removes_trailing_blank_lines(self) -> None:
        """Should remove blank lines at the end."""
        content = "# Header\nContent\n\n\n"
        result = clean_whitespace(content)
        assert result == "# Header\nContent\n"

    def test_preserves_single_blank_lines(self) -> None:
        """Should keep single blank lines between content."""
        content = "# Header\n\nContent\n\nMore content\n"
        result = clean_whitespace(content)
        assert result == "# Header\n\nContent\n\nMore content\n"

    def test_preserves_trailing_newline_if_present(self) -> None:
        """Should preserve trailing newline if original had one."""
        content = "# Header\nContent\n"
        result = clean_whitespace(content)
        assert result == "# Header\nContent\n"

    def test_no_trailing_newline_if_original_didnt_have_one(self) -> None:
        """Should not add trailing newline if original didn't have one."""
        content = "# Header\nContent"
        result = clean_whitespace(content)
        assert result == "# Header\nContent"

    def test_handles_empty_content(self) -> None:
        """Should handle empty content."""
        content = ""
        result = clean_whitespace(content)
        assert result == ""

    def test_handles_only_blank_lines(self) -> None:
        """Should handle content that is only blank lines."""
        content = "\n\n\n"
        result = clean_whitespace(content)
        assert result == ""

    def test_complex_cleanup(self) -> None:
        """Should handle complex cases with multiple issues."""
        content = "\n\n# Header\n\n\n- Item 1\n\n\n\n- Item 2\n\n\n"
        result = clean_whitespace(content)
        assert result == "# Header\n\n- Item 1\n\n- Item 2\n"


class TestCmdClean:
    """Tests for the cmd_clean command."""

    def test_cleans_daily_notes(self, tmp_path: Path) -> None:
        """Should clean whitespace in daily notes."""
        # Create a daily note with messy whitespace
        note = tmp_path / "2025-12-16.md"
        note.write_text("# 2025-12-16\n\n\n- Task\n\n\n", encoding="utf-8")

        config = Config(vault_path=tmp_path, gemini_api_key="test")
        result = cmd_clean(config)

        assert result == 0
        cleaned = note.read_text(encoding="utf-8")
        assert cleaned == "# 2025-12-16\n\n- Task\n"

    def test_skips_clean_notes(self, tmp_path: Path) -> None:
        """Should skip notes that don't need cleaning."""
        note = tmp_path / "2025-12-16.md"
        note.write_text("# 2025-12-16\n\n- Task\n", encoding="utf-8")

        config = Config(vault_path=tmp_path, gemini_api_key="test")
        result = cmd_clean(config)

        assert result == 0
        # Content should be unchanged
        cleaned = note.read_text(encoding="utf-8")
        assert cleaned == "# 2025-12-16\n\n- Task\n"

    def test_ignores_non_daily_notes(self, tmp_path: Path) -> None:
        """Should ignore files that don't match daily note pattern."""
        note = tmp_path / "random-note.md"
        original = "\n\n# Random\n\n\n"
        note.write_text(original, encoding="utf-8")

        config = Config(vault_path=tmp_path, gemini_api_key="test")
        result = cmd_clean(config)

        assert result == 0
        # Content should be unchanged (file was ignored)
        content = note.read_text(encoding="utf-8")
        assert content == original

    def test_dry_run_doesnt_modify(self, tmp_path: Path) -> None:
        """Should not modify files in dry run mode."""
        note = tmp_path / "2025-12-16.md"
        original = "# 2025-12-16\n\n\n- Task\n\n\n"
        note.write_text(original, encoding="utf-8")

        config = Config(vault_path=tmp_path, gemini_api_key="test", dry_run=True)
        result = cmd_clean(config)

        assert result == 0
        # Content should be unchanged
        content = note.read_text(encoding="utf-8")
        assert content == original

    def test_handles_daily_notes_folder(self, tmp_path: Path) -> None:
        """Should clean notes in daily notes subfolder."""
        journal = tmp_path / "Journal"
        journal.mkdir()
        note = journal / "2025-12-16.md"
        note.write_text("# 2025-12-16\n\n\n- Task\n\n\n", encoding="utf-8")

        config = Config(vault_path=tmp_path, gemini_api_key="test", daily_notes_folder="Journal")
        result = cmd_clean(config)

        assert result == 0
        cleaned = note.read_text(encoding="utf-8")
        assert cleaned == "# 2025-12-16\n\n- Task\n"

    def test_returns_success_for_missing_folder(self, tmp_path: Path) -> None:
        """Should return success if daily notes folder doesn't exist."""
        config = Config(vault_path=tmp_path, gemini_api_key="test", daily_notes_folder="Missing")
        result = cmd_clean(config)

        assert result == 0

    def test_cleans_multiple_notes(self, tmp_path: Path) -> None:
        """Should clean multiple daily notes."""
        (tmp_path / "2025-12-15.md").write_text("\n\n# Note 1\n\n\n", encoding="utf-8")
        (tmp_path / "2025-12-16.md").write_text("\n\n# Note 2\n\n\n", encoding="utf-8")
        (tmp_path / "2025-12-17.md").write_text("# Note 3\n", encoding="utf-8")  # Clean

        config = Config(vault_path=tmp_path, gemini_api_key="test")
        result = cmd_clean(config)

        assert result == 0
        assert (tmp_path / "2025-12-15.md").read_text() == "# Note 1\n"
        assert (tmp_path / "2025-12-16.md").read_text() == "# Note 2\n"
        assert (tmp_path / "2025-12-17.md").read_text() == "# Note 3\n"
