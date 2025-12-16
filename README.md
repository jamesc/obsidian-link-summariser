# Obsidian Link Summarizer

A lightweight Python CLI tool that reads URLs from Obsidian daily notes, fetches web pages, generates AI summaries using Google's Gemini API, and creates formatted Markdown summary notes in your Obsidian vault.

## Features

- 📝 Extract URLs from Obsidian daily notes (Markdown links and bare URLs)
- 🤖 Generate AI summaries using Google Gemini Flash (free tier friendly)
- 📁 Create well-formatted summary notes with frontmatter
- ⌨️ Integrate with Obsidian via Shell Commands plugin
- 🧪 Mock mode for development/testing without API calls

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Google AI Studio API key ([get one here](https://aistudio.google.com/apikey))

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/obsidian-link-summariser.git
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
# Summarize URLs from a daily note
summarize-links from-note --vault ~/Notes --note "2025-12-16.md"

# Summarize explicit URLs
summarize-links urls --vault ~/Notes --url "https://example.com/article"

# Dry run (see what would happen without making changes)
summarize-links from-note --vault ~/Notes --note "2025-12-16.md" --dry-run

# Mock mode (for testing, no API calls)
summarize-links from-note --vault ~/Notes --note "2025-12-16.md" --mock
```

### Obsidian Integration

1. **Install Shell Commands plugin** in Obsidian → Enable it
2. **Create a new shell command**:
   - Working directory: `$SC_WORKSPACE_DIR`
   - Command: `summarize-links from-note --vault "$SC_WORKSPACE_DIR" --note "$SC_CURRENT_FILE_NAME"`
3. **Assign a hotkey** (e.g., `Ctrl+Alt+S`)
4. **Usage**: Open a daily note → Press your hotkey → Summaries appear in `Summaries/` folder

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
