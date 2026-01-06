# Prompts for Obsidian Link Summarizer

This directory contains prompt templates for version control and upload to Langfuse.

**IMPORTANT:** These files are NOT used at runtime. Langfuse is REQUIRED for all operations.

## Files

- **`system.txt`** - System instructions for the LLM
  - Defines the assistant's role, output format (JSON), and guidelines
  - Used as the system message/instruction for both Gemini and Ollama
  
- **`user.txt`** - User prompt template
  - Template with variables: `{{title}}`, `{{url}}`, `{{content}}`
  - Variables are replaced with actual values at runtime

## Langfuse Integration (REQUIRED)

The application REQUIRES valid Langfuse credentials and will fetch prompts from:
- `summarize-document/system` (corresponds to `system.txt`)
- `summarize-document/user` (corresponds to `user.txt`)

**No Fallback:** If Langfuse prompts are not available, the application will raise an error.

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

**For Version Control:**
1. Edit `system.txt` or `user.txt` in this directory
2. Commit changes to git
3. Upload to Langfuse using `scripts/upload_prompts.py`

**For Production (Langfuse UI):**
1. Edit prompts directly in Langfuse UI at https://cloud.langfuse.com
2. Changes take effect immediately (hot-swapping)
3. Automatic versioning tracks all changes
4. Can rollback to any previous version
5. Sync changes back to filesystem files for version control

**Recommended Workflow:**
- Edit in filesystem → upload → test → commit to git
- For quick iterations: edit directly in Langfuse UI → sync back to filesystem when stable
