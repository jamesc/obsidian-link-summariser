"""
Command handler for 'clean' subcommand.

Cleans up whitespace in daily notes.
"""

import logging
import re

from summarize_links.config import Config
from summarize_links.ui import print_message

# Module logger
logger = logging.getLogger(__name__)

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1


def clean_whitespace(content: str) -> str:
    """
    Clean up whitespace in note content.

    - Collapses consecutive blank lines into single blank lines
    - Removes leading blank lines
    - Removes trailing blank lines (keeps one newline at end if original had one)

    Args:
        content: The note content to clean.

    Returns:
        Cleaned content.
    """
    had_trailing_newline = content.endswith("\n")
    lines = content.split("\n")

    # Collapse consecutive blank lines
    cleaned_lines: list[str] = []
    prev_blank = False

    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            # Skip consecutive blank lines
            continue
        cleaned_lines.append(line)
        prev_blank = is_blank

    # Remove leading blank lines (efficiently, without repeated pop(0))
    start_index = 0
    for line in cleaned_lines:
        if line.strip() == "":
            start_index += 1
        else:
            break
    if start_index:
        cleaned_lines = cleaned_lines[start_index:]

    # Remove trailing blank lines
    while cleaned_lines and cleaned_lines[-1].strip() == "":
        cleaned_lines.pop()

    # Reconstruct content
    new_content = "\n".join(cleaned_lines)
    if had_trailing_newline and new_content:
        new_content += "\n"

    return new_content


def cmd_clean(config: Config) -> int:
    """
    Clean up whitespace in all daily notes.

    Removes consecutive blank lines, leading blank lines, and
    trailing blank lines from all daily notes in the vault.

    Args:
        config: Application configuration.

    Returns:
        Exit code.
    """
    # Vault path must be set (validated in load_config)
    assert config.vault_path is not None

    # Determine daily notes path
    if config.daily_notes_folder:
        daily_notes_path = config.vault_path / config.daily_notes_folder
    else:
        daily_notes_path = config.vault_path

    if not daily_notes_path.exists():
        print_message(f"[yellow]Daily notes folder not found: {daily_notes_path}[/]")
        return EXIT_SUCCESS

    print_message("[bold]Cleaning whitespace in daily notes...[/]\n")

    # Pattern for daily note files (YYYY-MM-DD.md)
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")

    cleaned_count = 0
    skipped_count = 0
    error_count = 0

    # Find all daily note files
    for filepath in sorted(daily_notes_path.glob("*.md"), reverse=True):
        if not date_pattern.match(filepath.name):
            continue

        try:
            original_content = filepath.read_text(encoding="utf-8")
            cleaned_content = clean_whitespace(original_content)

            if original_content != cleaned_content:
                if config.dry_run:
                    print_message(f"[cyan]Would clean: {filepath.name}[/]")
                else:
                    filepath.write_text(cleaned_content, encoding="utf-8")
                    print_message(f"[green]Cleaned: {filepath.name}[/]")
                cleaned_count += 1
            else:
                skipped_count += 1
                logger.debug(f"No changes needed: {filepath.name}")

        except OSError as e:
            print_message(f"[red]Error processing {filepath.name}: {e}[/]")
            error_count += 1

    # Summary
    print_message("")
    if config.dry_run:
        print_message(f"[bold]Would clean {cleaned_count} files[/]")
    else:
        print_message(f"[bold]Cleaned {cleaned_count} files[/]")
    print_message(f"[dim]Skipped {skipped_count} files (no changes needed)[/]")

    if error_count > 0:
        print_message(f"[red]Errors: {error_count}[/]")
        return EXIT_ERROR

    return EXIT_SUCCESS
