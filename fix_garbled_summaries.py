#!/usr/bin/env python
"""
Script to find summaries marked as 'success' but containing garbled content,
and update their status to 'error'.
"""

from summarize_links.config import load_config
from summarize_links.gemini_client import _is_garbled_summary


def find_and_fix_garbled_summaries() -> None:
    """Find and fix summaries with garbled content marked as success."""
    # Load config to get vault path and output folder
    config = load_config()

    if config.vault_path is None:
        print("Error: Vault path not configured")
        return

    vault_path = config.vault_path
    out_folder = config.out_folder

    summaries_path = vault_path / out_folder

    if not summaries_path.exists():
        print(f"Summaries folder not found: {summaries_path}")
        return

    print(f"Scanning summaries in: {summaries_path}")
    print()

    # Find all markdown files
    summary_files = list(summaries_path.glob("*.md"))
    print(f"Found {len(summary_files)} summary files")
    print()

    fixed_count = 0

    for filepath in summary_files:
        try:
            content = filepath.read_text(encoding="utf-8")

            # Check if it has status: success
            if "status: success" not in content:
                continue

            # Extract the summary content (after frontmatter)
            # Frontmatter is between --- markers
            parts = content.split("---", 2)
            if len(parts) < 3:
                continue

            summary_content = parts[2].strip()

            # Check if the content is garbled
            if _is_garbled_summary(summary_content):
                print(f"🔧 Fixing: {filepath.name}")
                print(f"   Content preview: {summary_content[:100]}...")

                # Replace status: success with status: error in frontmatter
                new_content = content.replace("status: success", "status: error", 1)

                # Write the updated content
                filepath.write_text(new_content, encoding="utf-8")
                fixed_count += 1
                print("   ✓ Updated status to 'error'")
                print()

        except Exception as e:
            print(f"Error processing {filepath.name}: {e}")
            continue

    print(f"\n{'=' * 60}")
    print(f"Summary: Fixed {fixed_count} file(s)")
    if fixed_count > 0:
        print("\nThese summaries can now be retried with:")
        print("  summarize-links from-note --force")


if __name__ == "__main__":
    find_and_fix_garbled_summaries()
