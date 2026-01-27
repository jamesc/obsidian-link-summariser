"""
File system tools for modifying daily notes.

This module provides tools for:
- Cleaning whitespace in daily notes
- Removing URLs or lines from daily notes
- Adding text/URLs to daily notes
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from summarize_links.chat.tools.base import ProgressCallback, Tool, ToolResult
from summarize_links.commands.clean import clean_whitespace
from summarize_links.config import Config
from summarize_links.exceptions import NoteWriteError
from summarize_links.notes import remove_url_line_from_note

__all__ = [
    "CleanWhitespaceTool",
    "RemoveUrlFromNoteTool",
    "AddTextToNoteTool",
    "ReadNoteTool",
]

logger = logging.getLogger(__name__)


class CleanWhitespaceTool(Tool):
    """
    Tool to clean up whitespace in daily notes.

    Removes consecutive blank lines, leading/trailing blank lines
    from daily notes to keep them tidy.
    """

    @property
    def name(self) -> str:
        return "clean_whitespace"

    @property
    def description(self) -> str:
        return (
            "Clean up whitespace in daily notes. Removes consecutive blank lines, "
            "leading blank lines, and trailing blank lines. Can clean a specific "
            "note by date or all daily notes."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": (
                        "Date in YYYY-MM-DD format to clean a specific note. "
                        "If not provided, cleans all daily notes."
                    ),
                },
                "all_notes": {
                    "type": "boolean",
                    "description": "Clean all daily notes instead of a specific date",
                    "default": False,
                },
            },
            "required": [],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Clean whitespace in daily notes.

        Args:
            config: Application configuration.
            progress_callback: Optional progress callback.
            **kwargs: Tool parameters including:
                - date: Specific date to clean (YYYY-MM-DD).
                - all_notes: Clean all daily notes.

        Returns:
            ToolResult with cleaning summary.
        """
        date_str = kwargs.get("date")
        all_notes = kwargs.get("all_notes", False)

        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set.",
            )

        if date_str and not all_notes:
            return self._clean_single_note(config, date_str, progress_callback)
        else:
            return self._clean_all_notes(config, progress_callback)

    def _clean_single_note(
        self,
        config: Config,
        date_str: str,
        progress_callback: ProgressCallback = None,
    ) -> ToolResult:
        """Clean whitespace in a single daily note."""
        assert config.vault_path is not None

        # Construct path to the daily note
        if config.daily_notes_folder:
            daily_note_path = config.vault_path / config.daily_notes_folder / f"{date_str}.md"
        else:
            daily_note_path = config.vault_path / f"{date_str}.md"

        if not daily_note_path.exists():
            return ToolResult(
                success=False,
                message=f"Daily note not found for {date_str}",
                error=f"File does not exist: {daily_note_path}",
            )

        if progress_callback:
            progress_callback("Cleaning", str(daily_note_path.name))

        try:
            original_content = daily_note_path.read_text(encoding="utf-8")
            cleaned_content = clean_whitespace(original_content)

            if original_content == cleaned_content:
                return ToolResult(
                    success=True,
                    message=f"No whitespace changes needed for {date_str}.",
                    data={"date": date_str, "changed": False},
                )

            daily_note_path.write_text(cleaned_content, encoding="utf-8")
            logger.info(f"Cleaned whitespace in {daily_note_path.name}")

            return ToolResult(
                success=True,
                message=f"Cleaned whitespace in daily note for {date_str}.",
                data={"date": date_str, "changed": True},
            )

        except OSError as e:
            logger.error(f"Failed to clean {daily_note_path}: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to clean note for {date_str}: {e}",
                error=str(e),
            )

    def _clean_all_notes(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
    ) -> ToolResult:
        """Clean whitespace in all daily notes."""
        assert config.vault_path is not None

        # Determine daily notes path
        if config.daily_notes_folder:
            daily_notes_path = config.vault_path / config.daily_notes_folder
        else:
            daily_notes_path = config.vault_path

        if not daily_notes_path.exists():
            return ToolResult(
                success=False,
                message=f"Daily notes folder not found: {daily_notes_path}",
                error="Folder does not exist.",
            )

        # Pattern for daily note files (YYYY-MM-DD.md)
        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")

        cleaned_count = 0
        skipped_count = 0
        error_count = 0
        errors: list[str] = []

        # Find and clean all daily note files
        for filepath in sorted(daily_notes_path.glob("*.md"), reverse=True):
            if not date_pattern.match(filepath.name):
                continue

            if progress_callback:
                progress_callback("Cleaning", filepath.name)

            try:
                original_content = filepath.read_text(encoding="utf-8")
                cleaned_content = clean_whitespace(original_content)

                if original_content != cleaned_content:
                    filepath.write_text(cleaned_content, encoding="utf-8")
                    cleaned_count += 1
                    logger.debug(f"Cleaned: {filepath.name}")
                else:
                    skipped_count += 1
                    logger.debug(f"No changes needed: {filepath.name}")

            except OSError as e:
                error_count += 1
                errors.append(f"{filepath.name}: {e}")
                logger.error(f"Error cleaning {filepath.name}: {e}")

        # Build summary message
        lines = [f"Cleaned {cleaned_count} daily notes."]
        if skipped_count > 0:
            lines.append(f"Skipped {skipped_count} notes (no changes needed).")
        if error_count > 0:
            lines.append(f"Errors: {error_count}")
            for err in errors[:3]:  # Show first 3 errors
                lines.append(f"  - {err}")

        return ToolResult(
            success=error_count == 0,
            message="\n".join(lines),
            data={
                "cleaned": cleaned_count,
                "skipped": skipped_count,
                "errors": error_count,
            },
            error="\n".join(errors) if errors else None,
        )


class RemoveUrlFromNoteTool(Tool):
    """
    Tool to remove a URL line from a daily note.

    Removes the entire line containing the specified URL.
    Useful for cleaning up bad links or processed URLs.
    """

    @property
    def name(self) -> str:
        return "remove_url_from_note"

    @property
    def description(self) -> str:
        return (
            "Remove a URL from a daily note. Removes the entire line containing "
            "the specified URL. Use this to clean up bad links, broken links, "
            "or URLs that should no longer be processed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to remove from the note",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (default: today)",
                },
            },
            "required": ["url"],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Remove a URL line from a daily note.

        Args:
            config: Application configuration.
            progress_callback: Optional progress callback.
            **kwargs: Tool parameters including:
                - url: The URL to remove.
                - date: Date of the note (YYYY-MM-DD).

        Returns:
            ToolResult indicating success or failure.
        """
        url = kwargs.get("url")
        date_str = kwargs.get("date")

        if not url:
            return ToolResult(
                success=False,
                message="URL parameter is required",
                error="Missing required parameter: url",
            )

        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set.",
            )

        # Default to today
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        note_filename = f"{date_str}.md"

        if progress_callback:
            progress_callback("Removing URL", url)

        try:
            removed = remove_url_line_from_note(
                config.vault_path,
                config.daily_notes_folder,
                note_filename,
                url,
            )

            if removed:
                return ToolResult(
                    success=True,
                    message=f"Removed URL from {date_str}: {url}",
                    data={"date": date_str, "url": url, "removed": True},
                )
            else:
                return ToolResult(
                    success=True,
                    message=f"URL not found in {date_str}: {url}",
                    data={"date": date_str, "url": url, "removed": False},
                )

        except NoteWriteError as e:
            logger.error(f"Failed to remove URL from {date_str}: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to remove URL from {date_str}: {e}",
                error=str(e),
            )


class AddTextToNoteTool(Tool):
    """
    Tool to add text or URLs to a daily note.

    Appends content to the end of a daily note, optionally
    under a specific section heading.
    """

    @property
    def name(self) -> str:
        return "add_to_note"

    @property
    def description(self) -> str:
        return (
            "Add text, URLs, or other content to a daily note. The content is "
            "appended to the note, optionally under a specific section heading. "
            "Use this to save URLs for later summarization, add notes, or "
            "create new sections in daily notes."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": ("The text content to add (can include URLs, markdown, etc.)"),
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (default: today)",
                },
                "section": {
                    "type": "string",
                    "description": (
                        "Optional section heading to add content under. "
                        "If the section doesn't exist, it will be created."
                    ),
                },
                "as_bullet": {
                    "type": "boolean",
                    "description": "Format the content as a bullet point",
                    "default": False,
                },
                "create_if_missing": {
                    "type": "boolean",
                    "description": "Create the daily note if it doesn't exist",
                    "default": True,
                },
            },
            "required": ["content"],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Add text to a daily note.

        Args:
            config: Application configuration.
            progress_callback: Optional progress callback.
            **kwargs: Tool parameters including:
                - content: The text to add.
                - date: Date of the note (YYYY-MM-DD).
                - section: Optional section heading.
                - as_bullet: Format as bullet point.
                - create_if_missing: Create note if needed.

        Returns:
            ToolResult indicating success or failure.
        """
        content = kwargs.get("content")
        date_str = kwargs.get("date")
        section = kwargs.get("section")
        as_bullet = kwargs.get("as_bullet", False)
        create_if_missing = kwargs.get("create_if_missing", True)

        if not content:
            return ToolResult(
                success=False,
                message="Content parameter is required",
                error="Missing required parameter: content",
            )

        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set.",
            )

        # Default to today
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        # Construct path to the daily note
        if config.daily_notes_folder:
            daily_note_path = config.vault_path / config.daily_notes_folder / f"{date_str}.md"
        else:
            daily_note_path = config.vault_path / f"{date_str}.md"

        if progress_callback:
            progress_callback("Adding to note", date_str)

        try:
            return self._add_content_to_note(
                daily_note_path,
                date_str,
                content,
                section,
                as_bullet,
                create_if_missing,
            )
        except (OSError, NoteWriteError) as e:
            logger.error(f"Failed to add content to {date_str}: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to add content to {date_str}: {e}",
                error=str(e),
            )

    def _add_content_to_note(
        self,
        filepath: Path,
        date_str: str,
        content: str,
        section: str | None,
        as_bullet: bool,
        create_if_missing: bool,
    ) -> ToolResult:
        """Add content to a daily note file."""
        # Format the content as bullet if requested
        stripped = content.strip()
        if as_bullet and not stripped.startswith("-") and not stripped.startswith("*"):
            content = f"- {content}"

        # Check if file exists
        if filepath.exists():
            existing_content = filepath.read_text(encoding="utf-8")
        elif create_if_missing:
            # Create new note with header
            filepath.parent.mkdir(parents=True, exist_ok=True)
            existing_content = f"# {date_str}\n\n"
            logger.info(f"Creating new daily note: {filepath.name}")
        else:
            return ToolResult(
                success=False,
                message=f"Daily note for {date_str} does not exist",
                error="Note not found and create_if_missing is False",
            )

        # Add content to the note
        if section:
            new_content = self._add_to_section(existing_content, section, content)
        else:
            # Append to end of file
            new_content = existing_content.rstrip() + "\n\n" + content + "\n"

        # Write the updated content
        filepath.write_text(new_content, encoding="utf-8")
        logger.info(f"Added content to {filepath.name}")

        return ToolResult(
            success=True,
            message=f"Added content to daily note for {date_str}.",
            data={
                "date": date_str,
                "section": section,
                "content_length": len(content),
            },
        )

    def _add_to_section(
        self,
        file_content: str,
        section: str,
        content: str,
    ) -> str:
        """
        Add content under a specific section heading.

        If the section doesn't exist, it will be created at the end of the file.
        """
        # Normalize section heading (ensure it starts with ##)
        section_heading = f"## {section}" if not section.startswith("#") else section

        lines = file_content.split("\n")

        # Find the section
        section_index = -1
        next_section_index = len(lines)

        for i, line in enumerate(lines):
            # Check if this is our section
            if line.strip().lower() == section_heading.lower():
                section_index = i
            # If we've found our section, look for the next section
            elif section_index >= 0 and line.strip().startswith("#"):
                next_section_index = i
                break

        if section_index >= 0:
            # Section exists - insert content before next section
            # Find the last non-empty line in the section
            insert_index = section_index + 1
            for i in range(section_index + 1, next_section_index):
                if lines[i].strip():
                    insert_index = i + 1

            # Insert the content
            lines.insert(insert_index, content)
        else:
            # Section doesn't exist - create it at the end
            while lines and not lines[-1].strip():
                lines.pop()  # Remove trailing empty lines
            lines.append("")
            lines.append(section_heading)
            lines.append(content)

        return "\n".join(lines) + "\n"


class RemoveLineFromNoteTool(Tool):
    """
    Tool to remove a specific line from a daily note.

    Removes lines matching the given text pattern.
    More flexible than RemoveUrlFromNoteTool for non-URL content.
    """

    @property
    def name(self) -> str:
        return "remove_line_from_note"

    @property
    def description(self) -> str:
        return (
            "Remove a line from a daily note by matching text content. "
            "Removes all lines containing the specified text. Use this "
            "to clean up unwanted entries, duplicates, or incorrect content."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to match for line removal (case-sensitive)",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (default: today)",
                },
                "exact_match": {
                    "type": "boolean",
                    "description": (
                        "If true, the line must match exactly (after stripping whitespace). "
                        "If false, removes lines containing the text."
                    ),
                    "default": False,
                },
            },
            "required": ["text"],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Remove lines from a daily note.

        Args:
            config: Application configuration.
            progress_callback: Optional progress callback.
            **kwargs: Tool parameters including:
                - text: The text to match.
                - date: Date of the note (YYYY-MM-DD).
                - exact_match: Whether to require exact match.

        Returns:
            ToolResult indicating how many lines were removed.
        """
        text = kwargs.get("text")
        date_str = kwargs.get("date")
        exact_match = kwargs.get("exact_match", False)

        if not text:
            return ToolResult(
                success=False,
                message="Text parameter is required",
                error="Missing required parameter: text",
            )

        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set.",
            )

        # Default to today
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")

        # Construct path to the daily note
        if config.daily_notes_folder:
            daily_note_path = config.vault_path / config.daily_notes_folder / f"{date_str}.md"
        else:
            daily_note_path = config.vault_path / f"{date_str}.md"

        if not daily_note_path.exists():
            return ToolResult(
                success=False,
                message=f"Daily note not found for {date_str}",
                error="Note does not exist.",
            )

        if progress_callback:
            progress_callback("Removing lines", text[:30])

        try:
            original_content = daily_note_path.read_text(encoding="utf-8")
            lines = original_content.split("\n")

            # Find and remove matching lines
            new_lines: list[str] = []
            removed_count = 0

            for line in lines:
                should_remove = line.strip() == text.strip() if exact_match else text in line

                if should_remove:
                    removed_count += 1
                    logger.debug(f"Removing line: {line[:50]}...")
                else:
                    new_lines.append(line)

            if removed_count == 0:
                return ToolResult(
                    success=True,
                    message=f"No matching lines found in {date_str}",
                    data={"date": date_str, "removed": 0},
                )

            # Clean up consecutive blank lines
            cleaned_lines = self._clean_blank_lines(new_lines)

            # Write the updated content
            new_content = "\n".join(cleaned_lines)
            if original_content.endswith("\n") and new_content:
                new_content += "\n"

            daily_note_path.write_text(new_content, encoding="utf-8")
            logger.info(f"Removed {removed_count} lines from {daily_note_path.name}")

            return ToolResult(
                success=True,
                message=f"Removed {removed_count} line(s) from {date_str}.",
                data={"date": date_str, "removed": removed_count},
            )

        except OSError as e:
            logger.error(f"Failed to modify {daily_note_path}: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to modify note for {date_str}: {e}",
                error=str(e),
            )

    def _clean_blank_lines(self, lines: list[str]) -> list[str]:
        """Collapse consecutive blank lines into single blank lines."""
        cleaned: list[str] = []
        prev_blank = False

        for line in lines:
            is_blank = line.strip() == ""
            if is_blank and prev_blank:
                continue
            cleaned.append(line)
            prev_blank = is_blank

        # Remove leading/trailing blank lines
        while cleaned and cleaned[0].strip() == "":
            cleaned.pop(0)
        while cleaned and cleaned[-1].strip() == "":
            cleaned.pop()

        return cleaned


class ReadNoteTool(Tool):
    """
    Tool to read any note in the vault.

    Can read notes by path, name, or search for notes matching a pattern.
    """

    @property
    def name(self) -> str:
        return "read_note"

    @property
    def description(self) -> str:
        return (
            "Read the content of any note in the Obsidian vault. "
            "Provide the note path (relative to vault root) or note name. "
            "Use this to read daily notes, project notes, or any markdown file in the vault."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to the note relative to vault root (e.g., 'Projects/myproject.md' "
                        "or 'Journal/2025-01-23.md'). The .md extension is optional."
                    ),
                },
                "note_name": {
                    "type": "string",
                    "description": (
                        "Note name to search for (without path). Will search the entire vault "
                        "and return the first matching note. The .md extension is optional."
                    ),
                },
                "max_length": {
                    "type": "integer",
                    "description": (
                        "Maximum characters to return (default: 10000). "
                        "Use to limit output for very large notes."
                    ),
                    "default": 10000,
                },
            },
            "required": [],
        }

    def execute(
        self,
        config: Config,
        progress_callback: ProgressCallback = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Read a note from the vault.

        Args:
            config: Application configuration.
            progress_callback: Optional progress callback.
            **kwargs: Tool parameters including:
                - path: Path to the note relative to vault.
                - note_name: Note name to search for.
                - max_length: Maximum content length to return.

        Returns:
            ToolResult with note content.
        """
        path = kwargs.get("path")
        note_name = kwargs.get("note_name")
        max_length = kwargs.get("max_length", 10000)

        if not config.vault_path:
            return ToolResult(
                success=False,
                message="Vault path not configured",
                error="No vault path set.",
            )

        if not path and not note_name:
            return ToolResult(
                success=False,
                message="Either 'path' or 'note_name' parameter is required",
                error="Missing required parameter: path or note_name",
            )

        if path:
            return self._read_by_path(config.vault_path, path, max_length, progress_callback)
        else:
            # note_name must be set if we reach here (checked above)
            assert note_name is not None
            return self._read_by_name(config.vault_path, note_name, max_length, progress_callback)

    def _read_by_path(
        self,
        vault_path: Path,
        note_path: str,
        max_length: int,
        progress_callback: ProgressCallback = None,
    ) -> ToolResult:
        """Read a note by its path relative to vault."""
        # Normalize path - add .md if missing
        if not note_path.endswith(".md"):
            note_path = f"{note_path}.md"

        # Construct full path
        full_path = vault_path / note_path

        if progress_callback:
            progress_callback("Reading", note_path)

        if not full_path.exists():
            return ToolResult(
                success=False,
                message=f"Note not found: {note_path}",
                error=f"File does not exist: {full_path}",
            )

        if not full_path.is_file():
            return ToolResult(
                success=False,
                message=f"Path is not a file: {note_path}",
                error="Expected a file, got a directory or other type",
            )

        # Security check - ensure path is within vault
        try:
            full_path.resolve().relative_to(vault_path.resolve())
        except ValueError:
            return ToolResult(
                success=False,
                message="Invalid path: cannot access files outside vault",
                error="Path traversal attempt detected",
            )

        try:
            content = full_path.read_text(encoding="utf-8")
            truncated = len(content) > max_length
            if truncated:
                content = content[:max_length] + f"\n\n... (truncated, {len(content)} total chars)"

            return ToolResult(
                success=True,
                message=f"Read note: {note_path}",
                data={
                    "path": note_path,
                    "content": content,
                    "length": len(content),
                    "truncated": truncated,
                },
            )

        except OSError as e:
            logger.error(f"Failed to read {full_path}: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to read note: {e}",
                error=str(e),
            )

    def _read_by_name(
        self,
        vault_path: Path,
        note_name: str,
        max_length: int,
        progress_callback: ProgressCallback = None,
    ) -> ToolResult:
        """Search for and read a note by name."""
        # Normalize name - add .md if missing
        if not note_name.endswith(".md"):
            note_name = f"{note_name}.md"

        if progress_callback:
            progress_callback("Searching", note_name)

        # Search for the note in the vault
        matches: list[Path] = []
        for md_file in vault_path.rglob("*.md"):
            if md_file.name.lower() == note_name.lower():
                matches.append(md_file)

        if not matches:
            return ToolResult(
                success=False,
                message=f"No note found with name: {note_name}",
                error="Note not found in vault",
            )

        if len(matches) > 1:
            # Multiple matches - list them and read the first
            match_paths = [str(m.relative_to(vault_path)) for m in matches[:5]]
            note_path = matches[0]
            message_prefix = (
                f"Found {len(matches)} notes named '{note_name}'. "
                f"Reading first match: {match_paths[0]}\n"
                f"Other matches: {', '.join(match_paths[1:])}\n\n"
            )
        else:
            note_path = matches[0]
            message_prefix = ""

        # Read the note
        relative_path = str(note_path.relative_to(vault_path))

        if progress_callback:
            progress_callback("Reading", relative_path)

        try:
            content = note_path.read_text(encoding="utf-8")
            truncated = len(content) > max_length
            if truncated:
                content = content[:max_length] + f"\n\n... (truncated, {len(content)} total chars)"

            return ToolResult(
                success=True,
                message=f"{message_prefix}Read note: {relative_path}",
                data={
                    "path": relative_path,
                    "content": content,
                    "length": len(content),
                    "truncated": truncated,
                    "matches": len(matches),
                },
            )

        except OSError as e:
            logger.error(f"Failed to read {note_path}: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to read note: {e}",
                error=str(e),
            )
