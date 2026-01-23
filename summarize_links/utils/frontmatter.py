"""
Utilities for parsing YAML frontmatter from Markdown files.

This module provides a unified approach to extracting frontmatter from
Obsidian markdown notes. It handles both field-by-field extraction and
full dictionary parsing.
"""

import logging
import re
from typing import Any

import yaml

__all__ = [
    "extract_frontmatter_block",
    "parse_frontmatter",
    "get_frontmatter_field",
]

logger = logging.getLogger(__name__)

# Pattern to match YAML frontmatter block (--- at start and end)
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*$", re.MULTILINE | re.DOTALL)


def extract_frontmatter_block(content: str) -> str | None:
    """
    Extract the raw YAML frontmatter block from markdown content.

    Args:
        content: Markdown content that may contain frontmatter.

    Returns:
        The YAML block text (without the --- delimiters), or None if no frontmatter found.

    Example:
        >>> content = "---\\ntitle: Test\\n---\\nBody text"
        >>> extract_frontmatter_block(content)
        'title: Test'
    """
    match = FRONTMATTER_PATTERN.match(content)
    return match.group(1) if match else None


def parse_frontmatter(content: str) -> dict[str, Any]:
    """
    Parse complete frontmatter as a dictionary.

    Handles various YAML value types including strings, lists, dicts, etc.
    Returns empty dict if no frontmatter or parsing fails.

    Args:
        content: Markdown content that may contain frontmatter.

    Returns:
        Dictionary of frontmatter fields, or empty dict if none found.

    Example:
        >>> content = "---\\ntitle: Test\\ntags:\\n  - ai\\n---\\nBody"
        >>> fm = parse_frontmatter(content)
        >>> fm['title']
        'Test'
        >>> fm['tags']
        ['ai']
    """
    block = extract_frontmatter_block(content)
    if not block:
        return {}

    try:
        parsed = yaml.safe_load(block)
        # yaml.safe_load can return None for empty documents
        return parsed if isinstance(parsed, dict) else {}
    except yaml.YAMLError as e:
        logger.warning("Failed to parse YAML frontmatter: %s", e)
        return {}


def get_frontmatter_field(content: str, field: str) -> str | None:
    """
    Extract a single field value from frontmatter.

    This is more efficient than parsing the entire frontmatter when you only
    need one field. Returns string representation of the value.

    Args:
        content: Markdown content that may contain frontmatter.
        field: Name of the frontmatter field to extract.

    Returns:
        String value of the field, or None if not found or value is complex type.

    Example:
        >>> content = "---\\ntitle: Test\\ndate: 2025-01-23\\n---\\nBody"
        >>> get_frontmatter_field(content, 'title')
        'Test'
        >>> get_frontmatter_field(content, 'missing')
        None

    Note:
        - Returns None for list or dict values (use parse_frontmatter for those)
        - Converts non-string scalar values to strings
        - Returns None if field doesn't exist
    """
    data = parse_frontmatter(content)
    value = data.get(field)

    # Handle various YAML value types
    if value is None:
        return None

    # Don't try to stringify complex types
    if isinstance(value, (list, dict)):
        return None

    # Convert to string
    return str(value)
