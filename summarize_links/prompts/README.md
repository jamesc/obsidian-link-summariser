# Prompts for Obsidian Link Summarizer

This directory contains the fallback prompts used when Langfuse is unavailable or disabled.

## Files

- **`system.txt`** - System instructions for the LLM
  - Defines the assistant's role, output format (JSON), and guidelines
  - Used as the system message/instruction for both Gemini and Ollama
  
- **`user.txt`** - User prompt template
  - Template with variables: `{{title}}`, `{{url}}`, `{{content}}`
  - Variables are replaced with actual values at runtime
  - When using Langfuse, this template is fetched from Langfuse UI instead

## Langfuse Integration

When Langfuse is enabled (`langfuse_enabled=True`), the application:
1. First tries to fetch prompts from Langfuse UI:
   - `summarize-document/system` (maps to `system.txt`)
   - `summarize-document/user` (maps to `user.txt`)
2. If Langfuse is unavailable, falls back to these local files
3. Prompts are cached in-memory for the session duration

## Uploading to Langfuse

To upload these prompts to Langfuse, use the upload script:

```bash
# From project root
uv run python scripts/upload_prompts.py
```

This will:
- Read `system.txt` and `user.txt`
- Create/update prompts in Langfuse as `summarize-document/system` and `summarize-document/user`
- Automatically version prompts on each upload

## Editing Prompts

**For Development (using fallback prompts):**
1. Edit `system.txt` or `user.txt` directly
2. Test changes locally
3. Upload to Langfuse when ready

**For Production (using Langfuse):**
1. Edit prompts directly in Langfuse UI
2. Changes take effect immediately (hot-swapping)
3. Automatic versioning tracks all changes
4. Can rollback to any previous version
