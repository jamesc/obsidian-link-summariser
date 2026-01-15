#!/usr/bin/env python3
"""
Test script to verify whether Langfuse automatically resolves prompt references.

This script checks if the Langfuse SDK resolves @@@langfusePrompt:...@@@ references
automatically when calling get_prompt(), or if we need to resolve them manually.

Run this after uploading the composed prompts to Langfuse with upload_prompts.py
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env file
load_dotenv(project_root / ".env")

from langfuse import Langfuse  # noqa: E402


def main() -> None:
    """Test Langfuse prompt composability behavior."""

    # Initialize Langfuse client
    print("Initializing Langfuse client...")
    langfuse = Langfuse()

    print("\n" + "=" * 80)
    print("TESTING PROMPT COMPOSABILITY")
    print("=" * 80)

    # Fetch the composed chat prompt
    print("\n1. Fetching 'summarize-document' chat prompt...")
    try:
        prompt = langfuse.get_prompt("summarize-document", type="chat")
        print(f"   ✓ Fetched prompt: {prompt.name} v{prompt.version}")
    except Exception as e:
        print(f"   ✗ Failed to fetch prompt: {e}")
        print("\n   Make sure you've uploaded the prompts first:")
        print("   uv run python scripts/upload_prompts.py")
        return

    # Check the raw prompt structure
    print("\n2. Inspecting raw prompt.prompt attribute...")
    print(f"   Type: {type(prompt.prompt)}")
    print(f"   Length: {len(prompt.prompt) if isinstance(prompt.prompt, list) else 'N/A'}")

    if isinstance(prompt.prompt, list):
        print("\n   Messages:")
        for i, msg in enumerate(prompt.prompt):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            content_preview = content[:100] + "..." if len(content) > 100 else content
            print(f"   [{i}] {role}: {content_preview}")

            # Check if content contains references
            if "@@@langfusePrompt:" in content:
                print("       → CONTAINS REFERENCE (not resolved)")
            else:
                print("       → Direct content (resolved or never had reference)")

    # Test the compile() method
    print("\n3. Testing compile() method...")
    try:
        compiled = prompt.compile(
            title="Test Article",
            url="https://example.com/test",
            content="This is test content for the article.",
        )
        print("   ✓ Compiled successfully")
        print(f"   Type: {type(compiled)}")
        print(f"   Length: {len(compiled) if isinstance(compiled, list) else 'N/A'}")

        if isinstance(compiled, list):
            print("\n   Compiled messages:")
            for i, msg in enumerate(compiled):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                content_preview = content[:100] + "..." if len(content) > 100 else content
                print(f"   [{i}] {role}: {content_preview}")

                # Check if references were resolved during compilation
                if "@@@langfusePrompt:" in content:
                    print("       → STILL CONTAINS REFERENCE (compile didn't resolve)")
                else:
                    print("       → Content resolved")
    except Exception as e:
        print(f"   ✗ Compilation failed: {e}")

    # Summary
    print("\n" + "=" * 80)
    print("CONCLUSION")
    print("=" * 80)

    if isinstance(prompt.prompt, list):
        has_refs_in_raw = any(
            "@@@langfusePrompt:" in msg.get("content", "") for msg in prompt.prompt
        )

        if has_refs_in_raw:
            print("\n✗ Langfuse does NOT automatically resolve references in get_prompt()")
            print(
                "  → The prompt.prompt attribute still contains @@@langfusePrompt:...@@@ references"
            )
            print("  → We NEED manual resolution in _extract_messages_from_chat_prompt()")
        else:
            print("\n✓ Langfuse DOES automatically resolve references in get_prompt()")
            print("  → The prompt.prompt attribute contains actual content")
            print("  → Manual resolution in _extract_messages_from_chat_prompt() is REDUNDANT")
            print("  → We can simplify the code by removing manual resolution")

    if isinstance(compiled, list):
        has_refs_in_compiled = any(
            "@@@langfusePrompt:" in msg.get("content", "") for msg in compiled
        )

        if has_refs_in_compiled:
            print("\n✗ compile() does NOT resolve references")
            print("  → We cannot rely on compile() to resolve references")
        else:
            print("\n✓ compile() successfully resolves references")
            print("  → References are resolved during variable substitution")

    print()
    langfuse.flush()


if __name__ == "__main__":
    main()
