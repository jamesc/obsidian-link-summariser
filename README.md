# Obsidian Link Summarizer

[![Tests](https://github.com/jamesc/obsidian-link-summariser/actions/workflows/test.yml/badge.svg)](https://github.com/jamesc/obsidian-link-summariser/actions/workflows/test.yml)

A lightweight Python CLI tool that reads URLs from Obsidian daily notes, fetches web pages, generates AI summaries using Google's Gemini API or local Ollama models, and creates formatted Markdown summary notes in your Obsidian vault.

## Features

- 📝 Extract URLs from Obsidian daily notes (Markdown links and bare URLs)
- 🤖 Generate AI summaries using:
  - **Google Gemini** (cloud API, free tier friendly)
  - **Ollama** (local models, unlimited usage, private)
- 📁 Create well-formatted summary notes with rich frontmatter (author, tags, content type)
- 🏷️ Automatic tag extraction from page metadata and user hashtags
- 🔗 Automatic URL cleaning (strips UTM tracking parameters)
- 🔄 Idempotent - safe to run multiple times (skips existing summaries)
- ⚠️ Graceful degradation - creates stub notes for failures, continues processing
- 🧹 Auto-cleanup - removes processed URLs from daily notes
- ⏱️ Built-in rate limiting for Gemini API (no limits for local Ollama)
- ⌨️ Integrate with Obsidian via Shell Commands plugin
- 🧪 Mock mode for development/testing without API calls

## Installation

### Option 1: Dev Container (Recommended for Contributors)

The fastest way to get started with development is using VS Code Dev Containers:

1. **Prerequisites**: [Docker Desktop](https://www.docker.com/products/docker-desktop), [VS Code](https://code.visualstudio.com/), and [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

2. **Setup**:
   ```bash
   git clone https://github.com/jamesc/obsidian-link-summariser.git
   cd obsidian-link-summariser
   cp .env.example .env
   # Edit .env with your configuration
   code .
   # Then: Command Palette → "Dev Containers: Reopen in Container"
   ```

See [.devcontainer/README.md](.devcontainer/README.md) for detailed setup instructions and troubleshooting.

**GitHub Copilot Users:** This repository includes [`.github/copilot-agent.yml`](.github/copilot-agent.yml) to optimize the Copilot Coding Agent's context. It ensures the agent focuses on relevant source code and documentation while excluding cache files and build artifacts.

### Option 2: Local Setup

#### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- **For Gemini**: Google AI Studio API key ([get one free](https://aistudio.google.com/apikey))
- **For Ollama** (optional): [Ollama](https://ollama.ai) installed and running

#### Setup

```bash
# Clone the repository
git clone https://github.com/jamesc/obsidian-link-summariser.git
cd obsidian-link-summariser

# Install dependencies with uv (includes Langfuse for tracing/evaluation)
uv sync

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your configuration (see below)
```

### Configuration Options

#### Using Gemini (Cloud API)

```bash
# .env
GEMINI_API_KEY=your_api_key_here
MODEL=gemini-2.5-flash
```

#### Using Ollama (Local Models)

```bash
# 1. Install Ollama from https://ollama.ai
# 2. Pull a model (e.g., llama3)
ollama pull llama3

# 3. Start Ollama (or use the app)
ollama serve

# 4. Configure .env
MODEL=llama3:latest
# OLLAMA_ENDPOINT=http://localhost:11434  # Optional, this is the default
```

The tool automatically detects which provider to use based on the model name:
- Models with `:` (e.g., `llama3:latest`) → Ollama
- Known Ollama models (llama, mistral, phi, qwen, etc.) → Ollama  
- Others (e.g., `gemini-2.5-flash`) → Gemini API

## Usage

### Basic Commands

```bash
# Summarize URLs from today's daily note
summarize-links from-note --vault ~/Notes

# Summarize URLs from a specific date's daily note
summarize-links from-note --vault ~/Notes --date 2025-12-16

# Process ALL daily notes with URLs (oldest first)
summarize-links from-note --vault ~/Notes --all

# Re-summarize existing summaries (useful when changing models)
summarize-links resummarize --vault ~/Notes

# Re-summarize only summaries older than 30 days
summarize-links resummarize --vault ~/Notes --age 30

# List all daily notes that have URLs
summarize-links list --vault ~/Notes

# Summarize explicit URLs
summarize-links urls https://example.com/article https://another.com/post --vault ~/Notes

# Limit number of links to process
summarize-links from-note --vault ~/Notes --max-links 5

# Force regenerate existing summaries
summarize-links from-note --vault ~/Notes --force

# Dry run (see what would happen without making changes)
summarize-links from-note --vault ~/Notes --dry-run

# Mock mode (for testing, no API calls)
summarize-links from-note --vault ~/Notes --mock

# Verbose output for debugging
summarize-links from-note --vault ~/Notes --verbose

# Check rate limit status
summarize-links status --vault ~/Notes

# Check summary statistics
summarize-links summaries --vault ~/Notes
```

### Using Different LLM Providers

The tool automatically detects which provider to use based on the model name:

**Using Gemini API (cloud):**
```bash
# Use Gemini Flash
MODEL=gemini-2.0-flash-exp summarize-links from-note --vault ~/Notes

# Rate limits are tracked and displayed
summarize-links status --vault ~/Notes
```

**Using Ollama (local):**
```bash
# Use Llama3 (automatically detected as Ollama)
MODEL=llama3:latest summarize-links from-note --vault ~/Notes

# Use Mistral
MODEL=mistral:7b-instruct summarize-links from-note --vault ~/Notes

# Rate limits are not applicable for local models
summarize-links status --vault ~/Notes  # Shows "Provider: ollama (no rate limits)"
```

**Override model per command:**
```bash
# Use different model just for this command
summarize-links from-note --vault ~/Notes --model llama3:latest
```

**Common Ollama models supported:**
- `llama3:latest`, `llama3:8b`, `llama3:70b`
- `mistral:latest`, `mistral:7b-instruct`
- `phi:latest`, `phi3:latest`
- `qwen:latest`, `gemma:latest`

### Command Reference

```
summarize-links [-h] [-v] [--vault PATH] [--model MODEL] [--mock] [--dry-run]
                [--max-links N] [--force] {from-note,urls,list} ...

Global Options:
  -v, --verbose     Enable verbose output
  --vault PATH      Path to Obsidian vault (overrides config)
  --model MODEL     Gemini model to use (overrides config)
  --mock            Use mock Gemini client (no API calls)
  --dry-run         Show what would be done without making changes
  --max-links N     Maximum number of links to process
  --force           Overwrite existing summaries

Commands:
  from-note         Summarize links from a daily note
    --date DATE     Date of the daily note (YYYY-MM-DD, defaults to today)
    --all           Process all daily notes that contain URLs

  urls              Summarize specific URLs
    URLS...         One or more URLs to summarize

  resummarize       Re-summarize existing summaries from Summaries folder
                    Preserves original dates, useful when changing models
    --age DAYS      Only resummarize summaries older than DAYS days

  list              List all daily notes that have URLs

  summaries         Report on summary status
                    Shows statistics and identifies mocked/error summaries

  status            Show current Gemini API rate limit usage
```

### Output Format

Summary notes are created in the configured output folder (default: `Summaries/`) with:

- **Filename**: `YYYY-MM-DD-slug.md` (date + URL-derived slug)
- **Frontmatter**: Rich metadata including source URL, title, author, tags, content type, and backlink
- **Content**: AI-generated Markdown summary

Example output (`2025-12-16-api-pricing.md`):

```markdown
---
source: https://ai.google.dev/pricing
title: "Gemini API Pricing"
date: 2025-12-16
author: Google
content_type: documentation
domain: ai.google.dev
tags:
  - ai
  - gemini
  - pricing
from: "[[2025-12-16]]"
summary_status: success
---

## Overview

Google AI provides generous free tier pricing for Gemini models...

## Key Points

- Gemini Flash: 1500 requests/day free
- ...
```

### URL Cleaning

The tool automatically strips tracking parameters from URLs:
- UTM tags (`utm_source`, `utm_medium`, etc.)
- Social tracking (`fbclid`, `gclid`, etc.)
- RSS noise fragments (`#atom-everything`, `#rss`)

Meaningful parameters are preserved (e.g., YouTube `?v=`, GitHub `?tab=`).

### Obsidian Integration

1. **Install Shell Commands plugin** in Obsidian → Enable it
2. **Create a new shell command**:
   - Command: `summarize-links from-note --vault "{{vault_path}}"`
   - Or with current date: `summarize-links from-note --vault "{{vault_path}}" --date "{{date:YYYY-MM-DD}}"`
3. **Assign a hotkey** (e.g., `Ctrl+Alt+S`)
4. **Usage**: Press your hotkey → Summaries appear in `Summaries/` folder

### Error Handling

When a URL fails to process (fetch error, rate limit, etc.), the tool creates a **stub note** with:
- The original URL
- The reason for failure
- A `summary_status: error` marker

This ensures you don't lose track of links that couldn't be summarized. Running the command again will skip successfully processed URLs and retry failed ones (stubs are automatically regenerated).

### Mock Mode

When developing or testing, use `--mock` to:
- Skip real API calls
- Create summaries with `status: mocked` marker
- Running again without `--mock` will regenerate mocked summaries with real content

### Rate Limiting

The tool automatically manages Gemini API rate limits to keep you within free tier quotas:

| Limit | Quota | Behavior |
|-------|-------|----------|
| RPM (Requests/Minute) | 5 | Automatically waits if limit approached |
| TPM (Tokens/Minute) | 250,000 | Automatically waits if limit approached |
| Daily Requests | 20 | Raises error when exceeded |

**Check current usage:**
```bash
summarize-links status --vault ~/Notes
```

**Output:**
```
Gemini API Rate Limit Status

       Current Usage
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ Limit Type            ┃ Used ┃ Limit   ┃ Remaining ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━┩
│ Requests/Minute (RPM) │    2 │       5 │         3 │
│ Tokens/Minute (TPM)   │ 5000 │ 250,000 │   245,000 │
│ Requests/Day          │   15 │      20 │         5 │
└───────────────────────┴──────┴─────────┴───────────┘
```

Daily usage is tracked persistently in `.summarizer-rate-limit.json` in your vault and resets automatically each day.

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MODEL` | No | `gemini-2.0-flash-exp` | Model to use (auto-detects provider) |
| `GEMINI_API_KEY` | Conditional* | - | Google AI Studio API key |
| `GEMINI_MODEL` | No | - | **Deprecated:** Use `MODEL` instead |
| `OLLAMA_ENDPOINT` | No | `http://localhost:11434` | Ollama server endpoint |
| `DEFAULT_VAULT_PATH` | No | - | Default Obsidian vault path |
| `GEMINI_RPM_LIMIT` | No | `5` | Requests per minute limit (Gemini only) |
| `GEMINI_TPM_LIMIT` | No | `250000` | Tokens per minute limit (Gemini only) |
| `GEMINI_DAILY_LIMIT` | No | `20` | Requests per day limit (Gemini only) |

*\*Required only when using Gemini models*

### Vault Config File (Optional)

Create `.summarizer-config.yaml` in your vault root:

```yaml
out_folder: "Summaries"
max_links: 10
daily_notes_folder: "Journal"
model: "gemini-2.5-flash"

# Rate limits (override defaults for paid tiers)
rpm_limit: 60         # Requests per minute
tpm_limit: 1000000    # Tokens per minute (1M)
daily_limit: 10000    # Requests per day
```

**Note:** Rate limit settings can be customized for paid Gemini API tiers. Free tier defaults are conservative to avoid hitting quotas.

## Troubleshooting

### Ollama Errors

**"Ollama server not available"**
```bash
# Check if Ollama is running
ollama serve

# Or on macOS/Linux (background):
ollama serve &
```

**"Model not installed"**
```bash
# List available models
ollama list

# Pull the model you want
ollama pull llama3:latest

# Or pull a specific size
ollama pull mistral:7b-instruct
```

**"Connection refused" or wrong endpoint**
```bash
# Check your endpoint configuration
echo $OLLAMA_ENDPOINT  # Should be http://localhost:11434

# If using a remote Ollama server
export OLLAMA_ENDPOINT=http://remote-host:11434
```

### Gemini API Errors

**"GEMINI_API_KEY not set"**
- Set the environment variable or add to `.env` file
- Get your API key from https://makersuite.google.com/app/apikey

**"Daily rate limit exceeded"**
- Rate limit resets at midnight UTC
- Check usage with: `summarize-links status --vault ~/Notes`
- Consider upgrading to a paid Gemini tier for higher limits

### General Issues

**"No URLs found in note"**
- Ensure URLs are in standard markdown format: `[text](url)` or `<url>`
- Check that the daily note path is correct
- Use `--verbose` to see extraction details

**"Summary note already exists"**
- Use `--force` to regenerate existing summaries
- Check the configured `out_folder` in your vault

## Development

```bash
# Install dev dependencies
uv sync --all-extras

# Run tests
pytest

# Run linting
ruff check .

# Run formatting
ruff format .

# Run type checking
mypy .
```

## License

MIT
