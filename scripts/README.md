# Scripts

Utility scripts for managing the Obsidian Link Summarizer project.

## upload_prompts.py

Uploads prompts from the filesystem to Langfuse for centralized prompt management.

**Note:** Langfuse is REQUIRED for all operations. There are no fallback prompts - the application will fail if Langfuse credentials are not configured or prompts are not available.

### Usage

The script automatically loads environment variables from the `.env` file in the project root.

```bash
# Configure .env file with Langfuse credentials
# LANGFUSE_PUBLIC_KEY=pk-lf-...
# LANGFUSE_SECRET_KEY=sk-lf-...
# LANGFUSE_BASE_URL=https://cloud.langfuse.com  # Optional

# Run the script
uv run python scripts/upload_prompts.py
```

Alternatively, you can set environment variables directly:

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
uv run python scripts/upload_prompts.py
```

### What it does

1. Loads `system.txt` and `user.txt` from `summarize_links/prompts/`
2. Creates/updates two prompts in Langfuse:
   - `summarize-document/system` (system prompt)
   - `summarize-document/user` (user prompt template)

### Requirements

- Langfuse credentials must be configured in environment variables
- The `langfuse` package must be installed (included in `[tracing]` extras)

### Error Handling

- Checks for Langfuse credentials before attempting upload
- Provides clear error messages if credentials are missing
- Exits with code 1 on failure
