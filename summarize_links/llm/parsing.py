"""
Shared parsing utilities for LLM responses.

This module provides common parsing logic for handling JSON responses
from different LLM providers, including fallback strategies for malformed
responses and content validation.
"""

import json
import logging
import re

from summarize_links.exceptions import GeminiAPIError
from summarize_links.models import CONTENT_TYPE_DESCRIPTIONS, CONTENT_TYPES, SummaryResult

__all__ = [
    "parse_llm_json_response",
]

# Module logger
logger = logging.getLogger(__name__)


def _build_content_type_list() -> str:
    """
    Build the content type list for the system prompt from CONTENT_TYPE_DESCRIPTIONS.

    Returns:
        Formatted string listing all content types with descriptions.
    """
    lines = []
    for content_type, description in CONTENT_TYPE_DESCRIPTIONS.items():
        lines.append(f'- "{content_type}" ({description})')
    return "\n".join(lines)


def _extract_summary_from_malformed_json(text: str) -> str | None:
    """
    Try to extract summary content from malformed JSON response.

    When LLMs return JSON with unescaped characters in the summary field,
    standard JSON parsing fails. This function attempts to extract the summary
    content using regex patterns.

    Args:
        text: The malformed JSON text.

    Returns:
        Extracted summary content, or None if extraction fails.
    """
    # Try to find the summary field value
    # Pattern: "summary": "content..." or "summary": 'content...'
    # The summary typically ends before "suggested_tags" or "content_type"

    # First try to find content between "summary": " and the next field
    patterns = [
        # Match "summary": "..." ending at suggested_tags or content_type
        r'"summary"\s*:\s*"(.*?)"\s*,\s*"(?:suggested_tags|content_type)"',
        # Match with single quotes
        r'"summary"\s*:\s*\'(.*?)\'\s*,\s*"(?:suggested_tags|content_type)"',
        # Match until we hit the array or closing structure
        r'"summary"\s*:\s*"(.*?)"\s*,\s*"suggested_tags"\s*:\s*\[',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            summary = match.group(1)
            # Unescape common JSON escape sequences
            summary = summary.replace('\\"', '"')
            summary = summary.replace("\\n", "\n")
            summary = summary.replace("\\t", "\t")
            summary = summary.replace("\\\\", "\\")
            return summary

    # Fallback: try to extract everything after "summary": " until a reasonable end
    match = re.search(r'"summary"\s*:\s*"(.{100,})', text, re.DOTALL)
    if match:
        content = match.group(1)
        # Find a reasonable end point - look for the pattern that ends the summary
        # Usually it's: ", "suggested_tags" or similar
        end_patterns = [
            r'",\s*"suggested_tags"',
            r'",\s*"content_type"',
            r'"\s*,\s*"[a-z_]+"\s*:',  # Any next field
            r'"\s*}',  # End of object
        ]
        for end_pattern in end_patterns:
            end_match = re.search(end_pattern, content)
            if end_match:
                summary = content[: end_match.start()]
                summary = summary.replace('\\"', '"')
                summary = summary.replace("\\n", "\n")
                summary = summary.replace("\\t", "\t")
                summary = summary.replace("\\\\", "\\")
                return summary

    return None


def _extract_tags_from_malformed_json(text: str) -> list[str]:
    """
    Try to extract suggested_tags from malformed JSON response.

    Args:
        text: The malformed JSON text.

    Returns:
        List of extracted tags, or empty list if extraction fails.
    """
    # Try to find the suggested_tags array
    match = re.search(r'"suggested_tags"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if match:
        tags_content = match.group(1)
        # Extract quoted strings from the array
        tags = re.findall(r'"([^"]+)"', tags_content)
        return tags
    return []


def _extract_content_type_from_malformed_json(text: str) -> str:
    """
    Try to extract content_type from malformed JSON response.

    Args:
        text: The malformed JSON text.

    Returns:
        Extracted content type, or "article" as default.
    """
    match = re.search(r'"content_type"\s*:\s*"([^"]+)"', text)
    if match:
        content_type = match.group(1)
        if content_type in CONTENT_TYPES:
            return content_type
    return "article"


def _is_garbled_summary(summary_text: str) -> bool:
    """
    Detect if a summary indicates the content was garbled or corrupted.

    Checks for common patterns in AI responses that indicate the source
    content was unreadable (base64, encrypted, corrupted, etc.).

    Args:
        summary_text: The summary content to check.

    Returns:
        True if the summary indicates garbled/corrupted content.
    """
    indicators = [
        "corrupted or encrypted",
        "garbled characters",
        "appears to be encrypted",
        "appears to be corrupted",
        "consists of garbled",
        "not possible to extract",
        "meaningless characters",
        "random characters",
        "base64 encoded",
        "binary data",
        "unreadable content",
    ]

    summary_lower = summary_text.lower()
    return any(indicator in summary_lower for indicator in indicators)


def parse_llm_json_response(response_text: str) -> SummaryResult:
    """
    Parse LLM's JSON response into a SummaryResult.

    Handles various response formats including:
    - Clean JSON
    - JSON wrapped in markdown code blocks
    - Malformed responses (attempts field extraction, falls back to plain text)
    - Detects garbled/corrupted content responses and raises an error

    This function is provider-agnostic and can be used by any LLM client
    that returns JSON responses with summary, suggested_tags, and content_type.

    Args:
        response_text: Raw response from LLM API.

    Returns:
        Parsed SummaryResult object.

    Raises:
        GeminiAPIError: If the response indicates garbled/corrupted content.
    """
    text = response_text.strip()
    original_text = text  # Keep original for fallback extraction

    # Try to extract JSON from markdown code block (handles multiline)
    json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    # If no code block found, try to find JSON object by finding matching braces
    if not json_match:
        # Find the first { and try to extract the full JSON object
        start_idx = text.find("{")
        if start_idx != -1:
            # Count braces to find the matching closing brace
            brace_count = 0
            end_idx = start_idx
            for i, char in enumerate(text[start_idx:], start=start_idx):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break
            if brace_count == 0:
                text = text[start_idx:end_idx]

    try:
        data = json.loads(text)

        # Extract and validate fields
        summary = data.get("summary", "")
        if not summary:
            # If no summary field, use the whole response as summary
            logger.warning("No 'summary' field in response, using raw text")
            summary = response_text

        suggested_tags = data.get("suggested_tags", [])
        if not isinstance(suggested_tags, list):
            suggested_tags = []

        content_type = data.get("content_type", "article")
        if content_type not in CONTENT_TYPES:
            logger.debug(f"Unknown content_type '{content_type}', defaulting to 'article'")
            content_type = "article"

        result = SummaryResult(
            content=summary,
            suggested_tags=suggested_tags,
            content_type=content_type,
        )

        # Check if the summary indicates garbled/corrupted content
        if _is_garbled_summary(result.content):
            raise GeminiAPIError(
                "Summary indicates the content appears corrupted or garbled. "
                "This may indicate an extraction issue."
            )

        return result

    except json.JSONDecodeError as e:
        # JSON parsing failed - try to extract fields from malformed JSON
        logger.warning(f"Failed to parse JSON response: {e}. Attempting field extraction.")

        # Try to extract the summary from the malformed JSON
        extracted_summary = _extract_summary_from_malformed_json(original_text)

        if extracted_summary:
            # Successfully extracted summary, try to get other fields too
            logger.info("Successfully extracted summary from malformed JSON response.")
            extracted_tags = _extract_tags_from_malformed_json(original_text)
            extracted_type = _extract_content_type_from_malformed_json(original_text)

            return SummaryResult(
                content=extracted_summary,
                suggested_tags=extracted_tags,
                content_type=extracted_type,
            )

        # Complete fallback: use raw text as summary
        logger.warning("Could not extract fields from malformed JSON. Using raw text.")
        result = SummaryResult(
            content=response_text,
            suggested_tags=[],
            content_type="article",
        )

    # Check if the summary indicates garbled/corrupted content
    if _is_garbled_summary(result.content):
        raise GeminiAPIError(
            "Summary indicates the content appears corrupted or garbled. "
            "This may indicate an extraction issue."
        )

    return result
