
# Obsidian Link Summarizer CLI - Complete Specification

## Project Overview

**Purpose**: A lightweight Python CLI tool that reads URLs from Obsidian daily notes, fetches web pages, generates AI summaries using Google's Gemini API, and creates formatted Markdown summary notes in your Obsidian vault.

**Target usage**: 5-10 links per day for personal knowledge management, triggered via Obsidian hotkey.

**Key principles**:
- Zero dependencies beyond standard libraries + minimal external packages
- Works entirely offline except for Gemini API calls
- Free tier friendly (uses Gemini Flash model)
- Deterministic mocking for development/testing
- Simple Obsidian integration via "Shell commands" plugin

## Architecture

```
summarize_links/
├── pyproject.toml          # Packaging/installation
├── README.md              # Setup + Obsidian instructions
├── summarize_links/
│   ├── __init__.py
│   ├── cli.py             # Main argparse entrypoint
│   ├── config.py          # Env var + YAML config loader
│   ├── gemini_client.py   # Gemini API wrapper + mock
│   ├── extract.py         # HTML fetch + readability extraction
│   └── notes.py           # Obsidian note parsing + writing
└── tests/                 # Unit tests with mock fixtures
    ├── test_cli.py
    └── test_summarizer.py
```

### Core Components

```
User (Obsidian hotkey)
    ↓
Shell Commands Plugin ──→ CLI (`from-note --vault /path --note "2025-12-11.md"`)
    ↓
1. notes.read_daily_note() ──→ List of URLs
2. extract.fetch_and_clean(url) ──→ Readable text
3. gemini_client.summarize(text, url) ──→ Markdown summary
4. notes.write_summary_note(summary, url) ──→ Summaries/YYYY-MM-DD-slug.md
```

## CLI Interface

```
Usage: summarize-links [OPTIONS] COMMAND [ARGS]...

Commands:
  from-note  Process URLs from an Obsidian daily note
  urls       Summarize explicit URLs

Global options:
  --vault PATH          Obsidian vault root [required]
  --out-folder TEXT     Summary notes folder (default: "Summaries")
  --model TEXT          Gemini model (default: "gemini-2.0-flash-exp")
  --max-links INTEGER   Max URLs to process (default: 10)
  --dry-run            Show what would be done
  --mock               Use local mock summarizer
  --verbose            Debug logging
```

**Primary workflow**:
```
# From Obsidian hotkey (Shell Commands plugin)
summarize-links from-note \
  --vault "$SC_WORKSPACE_DIR" \
  --note "$SC_CURRENT_FILE_NAME" \
  --out-folder "Summaries"
```

## Detailed Scenarios

### Scenario 1: Daily Note Processing (Primary)

**Input daily note** (`2025-12-11.md`):
```
# 2025-12-11

## Articles
- [Gemini API pricing](https://ai.google.dev/pricing)
- [Obsidian plugins](https://obsidian.md/plugins)
https://example.com/direct-link

## Tasks
- Follow up on [[2025-12-10]]
```

**Processing steps**:
1. Regex extract: `https://ai.google.dev/pricing`, `https://obsidian.md/plugins`, `https://example.com/direct-link`
2. For each URL:
   - Fetch HTML → Extract main content → Truncate if >50k chars
   - Gemini prompt → Generate Markdown summary
   - Write `Summaries/2025-12-11-gemini-api-pricing.md`

**Output note** (`Summaries/2025-12-11-gemini-api-pricing.md`):
```
***
source: https://ai.google.dev/pricing
title: Gemini Developer API pricing
date: 2025-12-11
from: [[2025-12-11]]
***

## Overview
Gemini API offers generous free tier for development with rate limits suitable for personal projects. Paid tier required for production scale.

## Key Points
- Free tier: ~25 req/day for Pro models, higher for Flash
- Flash models: <$1/million tokens
- AI Studio: No billing setup needed for prototyping

## Actions
- Monitor rate limits during development
- Consider Vertex AI for higher quotas if needed
```

### Scenario 2: Rate Limit Handling

**When Gemini returns 429**:
```
$ summarize-links from-note --vault ~/Notes --note "2025-12-11.md"
Processing 3 URLs...
✅ https://example.com/a → Summaries/2025-12-11-example-a.md
⚠️  https://example.com/b → Rate limited. Retrying in 60s...
✅ https://example.com/c → Summaries/2025-12-11-example-c.md
```

**Stub note created**:
```
***
source: https://example.com/b
title: Rate limited - retry later
date: 2025-12-11
status: retry
***
Gemini API rate limit hit. Run again later or reduce --max-links.
```

### Scenario 3: Mock Mode (Development)

```
$ summarize-links from-note --vault ~/Notes --note "2025-12-11.md" --mock
[Mock] Would fetch: https://ai.google.dev/pricing
[Mock] Generated summary (42 chars)
[Mock] Would write: Summaries/2025-12-11-gemini-api-pricing.md
```

### Scenario 4: Explicit URLs

```
$ summarize-links urls --vault ~/Notes \
  --url "https://example.com/a" \
  --url "https://example.com/b"
```

## Technical Implementation Details

### 1. URL Extraction (`notes.py`)
```python
# Matches Markdown links [text](url) and bare http:// URLs
URL_PATTERN = r'(?:$.+?$$(https?://[^$]+)$|https?://[^\s$$$$]+)'
```

### 2. Content Extraction (`extract.py`)
```
1. requests.get(url, timeout=10)
2. BeautifulSoup(html, 'html.parser')
3. Remove: <script>, <style>, <nav>, <footer>
4. Extract: <article> or longest text block
5. Clean: strip extra whitespace, limit ~50k chars
```

**Packages**: `requests`, `beautifulsoup4`, `lxml` (fast parser)

### 3. Gemini Client (`gemini_client.py`)
```python
def summarize_page(content: str, url: str, model: str = "gemini-2.0-flash-exp") -> str:
    prompt = f"""
    Summarize this webpage for my Obsidian notes.

    URL: {url}
    Content: {content[:40000]}

    Return ONLY valid Markdown:
    1. Frontmatter with source/url/title/date
    2. ## Overview (1 paragraph)
    3. ## Key Points (3-6 bullets)
    4. ## Actions (if relevant)
    """

    response = genai.generate_content(model=model, contents=prompt)
    return response.text
```

**Mock implementation**:
```python
MOCK_RESPONSES = {
    "https://ai.google.dev": "# Mock Gemini pricing summary\n...",
}
```

### 4. Note Writing (`notes.py`)
```
Filename: Summaries/{date}-{title-slug}.md
Slug: lowercase, replace / -> -, limit 50 chars
Atomic writes: read → modify → write
```

## Configuration

**Environment variables** (priority):
```
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.0-flash-exp
DEFAULT_VAULT_PATH=~/Notes
```

**Optional vault config** (`.summarizer-config.yaml`):
```yaml
out_folder: "Summaries"
max_links: 10
daily_notes_folder: "Journal"
model: "gemini-2.0-flash-exp"
```

## Dependencies

```toml
[tool.poetry.dependencies]
python = "^3.11"
google-generativeai = "^0.8.0"
requests = "^2.32"
beautifulsoup4 = "^4.12"
lxml = "^5.3"
python-dotenv = "^1.0"
rich = "^13.9"  # Pretty CLI output
```

## Obsidian Setup Instructions

1. **Install Shell Commands plugin** → Enable
2. **Create shell command**:
   ```
   Working dir: $SC_WORKSPACE_DIR
   Command: summarize-links from-note --vault "$SC_WORKSPACE_DIR" --note "$SC_CURRENT_FILE_NAME"
   ```
3. **Hotkey**: `Ctrl+Alt+S` → Select your shell command
4. **Usage**: Open daily note → `Ctrl+Alt+S` → Watch magic happen

## Testing Strategy

```
tests/
├── fixtures/           # Mock HTML pages + expected summaries
├── test_cli.py         # pytest + mock subprocess
├── test_extraction.py  # HTML parsing edge cases
└── test_end_to_end.py  # --mock flag full workflow
```

**Run tests**: `pytest` (uses mock summarizer, no API calls)

---

*This spec is production-ready for a 1-2 day implementation. Start with `cli.py` + `notes.py` for MVP.*