# Obsidian Link Summarizer

[![Tests](https://github.com/jamesc/obsidian-link-summariser/actions/workflows/test.yml/badge.svg)](https://github.com/jamesc/obsidian-link-summariser/actions/workflows/test.yml)

A lightweight Python CLI tool that reads URLs from Obsidian daily notes, fetches web pages, generates AI summaries using Google's Gemini API, and creates formatted Markdown summary notes in your Obsidian vault.

## Features

- 📝 Extract URLs from Obsidian daily notes (Markdown links and bare URLs)
- 🤖 Generate AI summaries using Google Gemini Flash (free tier friendly)
- 📁 Create well-formatted summary notes with rich frontmatter (author, tags, content type)
- 🏷️ Automatic tag extraction from page metadata and user hashtags
- 🔗 Automatic URL cleaning (strips UTM tracking parameters)
- 🔄 Idempotent - safe to run multiple times (skips existing summaries)
- ⚠️ Graceful degradation - creates stub notes for failures, continues processing
- 🧹 Auto-cleanup - removes processed URLs from daily notes
- ⌨️ Integrate with Obsidian via Shell Commands plugin
- 🧪 Mock mode for development/testing without API calls

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Google AI Studio API key ([get one free](https://aistudio.google.com/apikey))

### Setup

```bash
# Clone the repository
git clone https://github.com/jamesc/obsidian-link-summariser.git
cd obsidian-link-summariser

# Install dependencies with uv
uv sync

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your GEMINI_API_KEY
```

## Usage

### Basic Commands

```bash
# Summarize URLs from today's daily note
summarize-links from-note --vault ~/Notes

# Summarize URLs from a specific date's daily note
summarize-links from-note --vault ~/Notes --date 2025-12-16

# Process ALL daily notes with URLs (oldest first)
summarize-links from-note --vault ~/Notes --all

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
```

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

  list              List all daily notes that have URLs
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
status: success
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
- A `status: error` marker

This ensures you don't lose track of links that couldn't be summarized. Running the command again will skip successfully processed URLs and retry failed ones (stubs are automatically regenerated).

### Mock Mode

When developing or testing, use `--mock` to:
- Skip real API calls
- Create summaries with `status: mocked` marker
- Running again without `--mock` will regenerate mocked summaries with real content

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | - | Google AI Studio API key |
| `GEMINI_MODEL` | No | `gemini-2.0-flash-exp` | Gemini model to use |
| `DEFAULT_VAULT_PATH` | No | - | Default Obsidian vault path |

### Vault Config File (Optional)

Create `.summarizer-config.yaml` in your vault root:

```yaml
out_folder: "Summaries"
max_links: 10
daily_notes_folder: "Journal"
model: "gemini-2.0-flash-exp"
```

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
