"""
Tests for chat filesystem tools (clean_whitespace, remove_url, add_to_note, read_note).
"""

from pathlib import Path

import pytest

from summarize_links.chat.tools.filesystem import (
    AddTextToNoteTool,
    CleanWhitespaceTool,
    ReadNoteTool,
    RemoveLineFromNoteTool,
    RemoveUrlFromNoteTool,
)
from summarize_links.config import Config


class TestCleanWhitespaceTool:
    """Tests for CleanWhitespaceTool."""

    @pytest.fixture
    def tool(self) -> CleanWhitespaceTool:
        """Create a tool instance."""
        return CleanWhitespaceTool()

    @pytest.fixture
    def vault_with_notes(self, tmp_path: Path) -> Path:
        """Create a vault with daily notes containing whitespace issues."""
        # Create daily notes folder
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        # Note with whitespace issues
        (daily_notes / "2025-01-22.md").write_text(
            """# Daily Note


Some notes.


- Item 1

- Item 2



More content.

""",
            encoding="utf-8",
        )

        # Clean note (no changes needed)
        (daily_notes / "2025-01-21.md").write_text(
            """# Yesterday

Notes from yesterday.
- Item 1
- Item 2
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_name(self, tool: CleanWhitespaceTool) -> None:
        """Test tool name."""
        assert tool.name == "clean_whitespace"

    def test_description_not_empty(self, tool: CleanWhitespaceTool) -> None:
        """Test tool has a description."""
        assert len(tool.description) > 0

    def test_parameters_schema(self, tool: CleanWhitespaceTool) -> None:
        """Test parameters schema is valid."""
        params = tool.parameters
        assert params["type"] == "object"
        assert "date" in params["properties"]
        assert "all_notes" in params["properties"]

    def test_no_vault_path(self, tool: CleanWhitespaceTool) -> None:
        """Test error when vault path not set."""
        config = Config(vault_path=None)
        result = tool.execute(config)

        assert result.success is False
        assert "vault path" in result.message.lower()

    def test_clean_single_note(self, tool: CleanWhitespaceTool, vault_with_notes: Path) -> None:
        """Test cleaning a single note with whitespace issues."""
        config = Config(
            vault_path=vault_with_notes,
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, date="2025-01-22")

        assert result.success is True
        assert result.data["changed"] is True

        # Verify the file was cleaned
        note_path = vault_with_notes / "Journal" / "2025-01-22.md"
        content = note_path.read_text(encoding="utf-8")
        # Should not have consecutive blank lines
        assert "\n\n\n" not in content

    def test_clean_note_no_changes(self, tool: CleanWhitespaceTool, vault_with_notes: Path) -> None:
        """Test cleaning a note that doesn't need changes."""
        config = Config(
            vault_path=vault_with_notes,
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, date="2025-01-21")

        assert result.success is True
        assert result.data["changed"] is False
        assert "no whitespace changes" in result.message.lower()

    def test_clean_note_not_found(self, tool: CleanWhitespaceTool, vault_with_notes: Path) -> None:
        """Test error when note doesn't exist."""
        config = Config(
            vault_path=vault_with_notes,
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, date="1999-01-01")

        assert result.success is False
        assert "not found" in result.message.lower()

    def test_clean_all_notes(self, tool: CleanWhitespaceTool, vault_with_notes: Path) -> None:
        """Test cleaning all daily notes."""
        config = Config(
            vault_path=vault_with_notes,
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, all_notes=True)

        assert result.success is True
        assert result.data["cleaned"] >= 1  # At least one note cleaned
        assert result.data["skipped"] >= 1  # At least one note skipped


class TestRemoveUrlFromNoteTool:
    """Tests for RemoveUrlFromNoteTool."""

    @pytest.fixture
    def tool(self) -> RemoveUrlFromNoteTool:
        """Create a tool instance."""
        return RemoveUrlFromNoteTool()

    @pytest.fixture
    def vault_with_urls(self, tmp_path: Path) -> Path:
        """Create a vault with daily notes containing URLs."""
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        (daily_notes / "2025-01-22.md").write_text(
            """# Daily Note

- Bad link: https://example.com/broken
- Good link: https://example.com/article
- Another: https://example.com/other
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_name(self, tool: RemoveUrlFromNoteTool) -> None:
        """Test tool name."""
        assert tool.name == "remove_url_from_note"

    def test_description_not_empty(self, tool: RemoveUrlFromNoteTool) -> None:
        """Test tool has a description."""
        assert len(tool.description) > 0

    def test_parameters_schema(self, tool: RemoveUrlFromNoteTool) -> None:
        """Test parameters schema is valid."""
        params = tool.parameters
        assert params["type"] == "object"
        assert "url" in params["properties"]
        assert "date" in params["properties"]
        assert "url" in params["required"]

    def test_no_vault_path(self, tool: RemoveUrlFromNoteTool) -> None:
        """Test error when vault path not set."""
        config = Config(vault_path=None)
        result = tool.execute(config, url="https://example.com")

        assert result.success is False
        assert "vault path" in result.message.lower()

    def test_missing_url_parameter(self, tool: RemoveUrlFromNoteTool, tmp_path: Path) -> None:
        """Test error when URL not provided."""
        config = Config(vault_path=tmp_path)
        result = tool.execute(config)

        assert result.success is False
        assert "required" in result.message.lower()

    def test_remove_url_success(self, tool: RemoveUrlFromNoteTool, vault_with_urls: Path) -> None:
        """Test successfully removing a URL."""
        config = Config(
            vault_path=vault_with_urls,
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, url="https://example.com/broken", date="2025-01-22")

        assert result.success is True
        assert result.data["removed"] is True

        # Verify URL was removed
        note_path = vault_with_urls / "Journal" / "2025-01-22.md"
        content = note_path.read_text(encoding="utf-8")
        assert "broken" not in content
        assert "article" in content  # Other URLs still there

    def test_remove_url_not_found(self, tool: RemoveUrlFromNoteTool, vault_with_urls: Path) -> None:
        """Test removing a URL that doesn't exist in the note."""
        config = Config(
            vault_path=vault_with_urls,
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, url="https://nonexistent.com", date="2025-01-22")

        assert result.success is True
        assert result.data["removed"] is False
        assert "not found" in result.message.lower()


class TestAddTextToNoteTool:
    """Tests for AddTextToNoteTool."""

    @pytest.fixture
    def tool(self) -> AddTextToNoteTool:
        """Create a tool instance."""
        return AddTextToNoteTool()

    @pytest.fixture
    def vault_with_notes(self, tmp_path: Path) -> Path:
        """Create a vault with daily notes."""
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        (daily_notes / "2025-01-22.md").write_text(
            """# Daily Note

Some existing content.

## Links

- Existing link
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_name(self, tool: AddTextToNoteTool) -> None:
        """Test tool name."""
        assert tool.name == "add_to_note"

    def test_description_not_empty(self, tool: AddTextToNoteTool) -> None:
        """Test tool has a description."""
        assert len(tool.description) > 0

    def test_parameters_schema(self, tool: AddTextToNoteTool) -> None:
        """Test parameters schema is valid."""
        params = tool.parameters
        assert params["type"] == "object"
        assert "content" in params["properties"]
        assert "date" in params["properties"]
        assert "section" in params["properties"]
        assert "as_bullet" in params["properties"]
        assert "content" in params["required"]

    def test_no_vault_path(self, tool: AddTextToNoteTool) -> None:
        """Test error when vault path not set."""
        config = Config(vault_path=None)
        result = tool.execute(config, content="Test content")

        assert result.success is False
        assert "vault path" in result.message.lower()

    def test_missing_content_parameter(self, tool: AddTextToNoteTool, tmp_path: Path) -> None:
        """Test error when content not provided."""
        config = Config(vault_path=tmp_path)
        result = tool.execute(config)

        assert result.success is False
        assert "required" in result.message.lower()

    def test_add_content_success(self, tool: AddTextToNoteTool, vault_with_notes: Path) -> None:
        """Test successfully adding content to a note."""
        config = Config(
            vault_path=vault_with_notes,
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, content="New content here", date="2025-01-22")

        assert result.success is True

        # Verify content was added
        note_path = vault_with_notes / "Journal" / "2025-01-22.md"
        content = note_path.read_text(encoding="utf-8")
        assert "New content here" in content

    def test_add_content_as_bullet(self, tool: AddTextToNoteTool, vault_with_notes: Path) -> None:
        """Test adding content as a bullet point."""
        config = Config(
            vault_path=vault_with_notes,
            daily_notes_folder="Journal",
        )
        result = tool.execute(
            config,
            content="Check this URL: https://example.com",
            date="2025-01-22",
            as_bullet=True,
        )

        assert result.success is True

        # Verify bullet was added
        note_path = vault_with_notes / "Journal" / "2025-01-22.md"
        content = note_path.read_text(encoding="utf-8")
        assert "- Check this URL: https://example.com" in content

    def test_add_content_to_section(self, tool: AddTextToNoteTool, vault_with_notes: Path) -> None:
        """Test adding content to a specific section."""
        config = Config(
            vault_path=vault_with_notes,
            daily_notes_folder="Journal",
        )
        result = tool.execute(
            config,
            content="- New link",
            date="2025-01-22",
            section="Links",
        )

        assert result.success is True

        # Verify content was added to section
        note_path = vault_with_notes / "Journal" / "2025-01-22.md"
        content = note_path.read_text(encoding="utf-8")
        assert "- New link" in content

    def test_add_content_new_section(self, tool: AddTextToNoteTool, vault_with_notes: Path) -> None:
        """Test adding content creates a new section if it doesn't exist."""
        config = Config(
            vault_path=vault_with_notes,
            daily_notes_folder="Journal",
        )
        result = tool.execute(
            config,
            content="- Task 1",
            date="2025-01-22",
            section="Tasks",
        )

        assert result.success is True

        # Verify section was created
        note_path = vault_with_notes / "Journal" / "2025-01-22.md"
        content = note_path.read_text(encoding="utf-8")
        assert "## Tasks" in content
        assert "- Task 1" in content

    def test_create_note_if_missing(self, tool: AddTextToNoteTool, vault_with_notes: Path) -> None:
        """Test creating a new note when it doesn't exist."""
        config = Config(
            vault_path=vault_with_notes,
            daily_notes_folder="Journal",
        )
        result = tool.execute(
            config,
            content="First entry",
            date="2025-01-23",
            create_if_missing=True,
        )

        assert result.success is True

        # Verify note was created
        note_path = vault_with_notes / "Journal" / "2025-01-23.md"
        assert note_path.exists()
        content = note_path.read_text(encoding="utf-8")
        assert "First entry" in content

    def test_no_create_if_missing_false(
        self, tool: AddTextToNoteTool, vault_with_notes: Path
    ) -> None:
        """Test not creating note when create_if_missing is False."""
        config = Config(
            vault_path=vault_with_notes,
            daily_notes_folder="Journal",
        )
        result = tool.execute(
            config,
            content="Entry",
            date="2025-01-23",
            create_if_missing=False,
        )

        assert result.success is False
        assert "does not exist" in result.message.lower()


class TestRemoveLineFromNoteTool:
    """Tests for RemoveLineFromNoteTool."""

    @pytest.fixture
    def tool(self) -> RemoveLineFromNoteTool:
        """Create a tool instance."""
        return RemoveLineFromNoteTool()

    @pytest.fixture
    def vault_with_content(self, tmp_path: Path) -> Path:
        """Create a vault with daily notes containing various content."""
        daily_notes = tmp_path / "Journal"
        daily_notes.mkdir()

        (daily_notes / "2025-01-22.md").write_text(
            """# Daily Note

- TODO: Complete task
- TODO: Another task
- Meeting notes
- Important item
""",
            encoding="utf-8",
        )

        return tmp_path

    def test_name(self, tool: RemoveLineFromNoteTool) -> None:
        """Test tool name."""
        assert tool.name == "remove_line_from_note"

    def test_description_not_empty(self, tool: RemoveLineFromNoteTool) -> None:
        """Test tool has a description."""
        assert len(tool.description) > 0

    def test_parameters_schema(self, tool: RemoveLineFromNoteTool) -> None:
        """Test parameters schema is valid."""
        params = tool.parameters
        assert params["type"] == "object"
        assert "text" in params["properties"]
        assert "date" in params["properties"]
        assert "exact_match" in params["properties"]
        assert "text" in params["required"]

    def test_no_vault_path(self, tool: RemoveLineFromNoteTool) -> None:
        """Test error when vault path not set."""
        config = Config(vault_path=None)
        result = tool.execute(config, text="some text")

        assert result.success is False
        assert "vault path" in result.message.lower()

    def test_remove_lines_containing_text(
        self, tool: RemoveLineFromNoteTool, vault_with_content: Path
    ) -> None:
        """Test removing all lines containing specific text."""
        config = Config(
            vault_path=vault_with_content,
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, text="TODO", date="2025-01-22")

        assert result.success is True
        assert result.data["removed"] == 2

        # Verify lines were removed
        note_path = vault_with_content / "Journal" / "2025-01-22.md"
        content = note_path.read_text(encoding="utf-8")
        assert "TODO" not in content
        assert "Meeting notes" in content

    def test_remove_exact_match(
        self, tool: RemoveLineFromNoteTool, vault_with_content: Path
    ) -> None:
        """Test removing only exact matching lines."""
        config = Config(
            vault_path=vault_with_content,
            daily_notes_folder="Journal",
        )
        result = tool.execute(
            config,
            text="- TODO: Complete task",
            date="2025-01-22",
            exact_match=True,
        )

        assert result.success is True
        assert result.data["removed"] == 1

        # Verify only exact match was removed
        note_path = vault_with_content / "Journal" / "2025-01-22.md"
        content = note_path.read_text(encoding="utf-8")
        assert "Complete task" not in content
        assert "Another task" in content  # Other TODO still there

    def test_no_matching_lines(
        self, tool: RemoveLineFromNoteTool, vault_with_content: Path
    ) -> None:
        """Test when no lines match the text."""
        config = Config(
            vault_path=vault_with_content,
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, text="NONEXISTENT", date="2025-01-22")

        assert result.success is True
        assert result.data["removed"] == 0
        assert "no matching lines" in result.message.lower()

    def test_note_not_found(self, tool: RemoveLineFromNoteTool, vault_with_content: Path) -> None:
        """Test error when note doesn't exist."""
        config = Config(
            vault_path=vault_with_content,
            daily_notes_folder="Journal",
        )
        result = tool.execute(config, text="anything", date="1999-01-01")

        assert result.success is False
        assert "not found" in result.message.lower()


class TestReadNoteTool:
    """Tests for ReadNoteTool."""

    @pytest.fixture
    def tool(self) -> ReadNoteTool:
        """Create a tool instance."""
        return ReadNoteTool()

    @pytest.fixture
    def vault_with_notes(self, tmp_path: Path) -> Path:
        """Create a vault with various notes."""
        # Create folder structure
        (tmp_path / "Projects").mkdir()
        (tmp_path / "Journal").mkdir()
        (tmp_path / "Notes").mkdir()

        # Create some notes
        (tmp_path / "Projects" / "myproject.md").write_text(
            """# My Project

This is a project note with details about my project.

## Tasks
- Task 1
- Task 2
""",
            encoding="utf-8",
        )

        (tmp_path / "Journal" / "2025-01-22.md").write_text(
            """# 2025-01-22

Daily note content.
""",
            encoding="utf-8",
        )

        (tmp_path / "Notes" / "ideas.md").write_text(
            "# Ideas\n\nSome ideas here.",
            encoding="utf-8",
        )

        # Create a duplicate named note in different folder
        (tmp_path / "Projects" / "ideas.md").write_text(
            "# Project Ideas\n\nProject-specific ideas.",
            encoding="utf-8",
        )

        # Create a large note
        large_content = "# Large Note\n\n" + ("Content line.\n" * 2000)
        (tmp_path / "large.md").write_text(large_content, encoding="utf-8")

        return tmp_path

    def test_name(self, tool: ReadNoteTool) -> None:
        """Test tool name."""
        assert tool.name == "read_note"

    def test_description_not_empty(self, tool: ReadNoteTool) -> None:
        """Test tool has a description."""
        assert len(tool.description) > 0

    def test_parameters_schema(self, tool: ReadNoteTool) -> None:
        """Test parameters schema is valid."""
        params = tool.parameters
        assert params["type"] == "object"
        assert "path" in params["properties"]
        assert "note_name" in params["properties"]
        assert "max_length" in params["properties"]

    def test_no_vault_path(self, tool: ReadNoteTool) -> None:
        """Test error when vault path not set."""
        config = Config(vault_path=None)
        result = tool.execute(config, path="test.md")

        assert result.success is False
        assert "vault path" in result.message.lower()

    def test_no_path_or_name(self, tool: ReadNoteTool, vault_with_notes: Path) -> None:
        """Test error when neither path nor name provided."""
        config = Config(vault_path=vault_with_notes)
        result = tool.execute(config)

        assert result.success is False
        assert "required" in result.message.lower()

    def test_read_by_path(self, tool: ReadNoteTool, vault_with_notes: Path) -> None:
        """Test reading a note by path."""
        config = Config(vault_path=vault_with_notes)
        result = tool.execute(config, path="Projects/myproject.md")

        assert result.success is True
        assert "My Project" in result.data["content"]
        assert result.data["path"] == "Projects/myproject.md"

    def test_read_by_path_without_extension(
        self, tool: ReadNoteTool, vault_with_notes: Path
    ) -> None:
        """Test reading a note by path without .md extension."""
        config = Config(vault_path=vault_with_notes)
        result = tool.execute(config, path="Projects/myproject")

        assert result.success is True
        assert "My Project" in result.data["content"]

    def test_read_by_name(self, tool: ReadNoteTool, vault_with_notes: Path) -> None:
        """Test reading a note by name (search)."""
        config = Config(vault_path=vault_with_notes)
        result = tool.execute(config, note_name="myproject")

        assert result.success is True
        assert "My Project" in result.data["content"]

    def test_read_by_name_multiple_matches(
        self, tool: ReadNoteTool, vault_with_notes: Path
    ) -> None:
        """Test reading when multiple notes have the same name."""
        config = Config(vault_path=vault_with_notes)
        result = tool.execute(config, note_name="ideas")

        assert result.success is True
        # Should read one of them and mention multiple matches
        assert result.data["matches"] == 2
        assert "Ideas" in result.data["content"]

    def test_read_not_found_by_path(self, tool: ReadNoteTool, vault_with_notes: Path) -> None:
        """Test error when note not found by path."""
        config = Config(vault_path=vault_with_notes)
        result = tool.execute(config, path="nonexistent.md")

        assert result.success is False
        assert "not found" in result.message.lower()

    def test_read_not_found_by_name(self, tool: ReadNoteTool, vault_with_notes: Path) -> None:
        """Test error when note not found by name."""
        config = Config(vault_path=vault_with_notes)
        result = tool.execute(config, note_name="nonexistent")

        assert result.success is False
        assert "no note found" in result.message.lower()

    def test_truncation(self, tool: ReadNoteTool, vault_with_notes: Path) -> None:
        """Test that large notes are truncated."""
        config = Config(vault_path=vault_with_notes)
        result = tool.execute(config, path="large.md", max_length=100)

        assert result.success is True
        assert result.data["truncated"] is True
        assert "truncated" in result.data["content"]

    def test_no_truncation_for_small_notes(
        self, tool: ReadNoteTool, vault_with_notes: Path
    ) -> None:
        """Test that small notes are not truncated."""
        config = Config(vault_path=vault_with_notes)
        result = tool.execute(config, path="Notes/ideas.md")

        assert result.success is True
        assert result.data["truncated"] is False
