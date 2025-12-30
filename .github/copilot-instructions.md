# GitHub Copilot Instructions for Obsidian Link Summariser

This document provides context and guidelines for GitHub Copilot when working on this project.

## Project Overview

Obsidian Link Summariser is a Python CLI tool that:
- Extracts URLs from Obsidian daily notes (Markdown files)
- Fetches web page content
- Generates AI summaries using Google Gemini API or local Ollama models
- Creates formatted Markdown summary notes with rich frontmatter

## Technology Stack

- **Language**: Python 3.11+
- **Package Manager**: uv (not pip or poetry)
- **Key Dependencies**: google-genai, pydantic, requests, beautifulsoup4, rich, pyyaml, langfuse
- **Testing**: pytest with pytest-cov and pytest-mock
- **Linting/Formatting**: ruff
- **Type Checking**: mypy (strict mode)

## Code Style and Standards

### Python Standards
- **Type hints required**: All function parameters and return values must have type annotations
- **Docstrings**: Module-level and function/method docstrings required
- **Line length**: 100 characters (configured in pyproject.toml)
- **String quotes**: Double quotes preferred (ruff configured)
- **Imports**: Organized with ruff (E, F, I rules)

### Architecture Patterns
- **Dependency injection**: Pass clients/services as parameters for testability
- **Custom exceptions**: Use specific exception classes (e.g., `URLExtractionError`, `GeminiAPIError`)
- **No magic values**: Define constants instead of hardcoded strings/numbers
- **Small, focused functions**: Each function should do one thing well
- **Idempotency**: Commands should be safe to run multiple times

### Error Handling
- **Graceful degradation**: If one URL fails, continue with others
- **Stub notes**: Create error notes for failed URLs with `summary_status: error`
- **Logging**: Use Python's logging library with appropriate levels (DEBUG, INFO, WARNING, ERROR)

## Development Workflow

### Before Committing (MANDATORY)
Run these commands in order and ensure all pass:
```bash
uv run ruff check .      # Linting
uv run ruff format .     # Formatting
uv run mypy .           # Type checking
uv run pytest           # Tests
```

**CRITICAL**: If ANY check fails, fix it and re-run ALL checks (not just the failing one).

### Package Management
- **Always use `uv`** for Python environment management
- Install dependencies: `uv sync` or `uv sync --all-extras`
- Add dependencies: `uv add <package>`
- Add dev dependencies: `uv add --dev <package>`

### Testing
- Write tests alongside new modules
- Run tests frequently: `uv run pytest`
- Check coverage: `uv run pytest --cov=summarize_links`
- Use pytest-mock for mocking external dependencies

### Environment Variables
- Never commit secrets to source code
- Use `.env` file for local development (see `.env.example`)
- Required for Gemini: `GEMINI_API_KEY`
- Model selection: `MODEL` (e.g., `gemini-2.5-flash` or `llama3:latest`)

## Project Structure

```
summarize_links/        # Main package
  ├── cli.py           # CLI entry point (argparse)
  ├── config.py        # Configuration management
  ├── url_extraction.py # URL extraction from notes
  ├── content_fetcher.py # Web content fetching
  ├── gemini_client.py  # Gemini API client
  ├── ollama_client.py  # Ollama API client
  ├── note_writer.py    # Summary note creation
  └── rate_limiter.py   # Rate limiting for Gemini API

tests/                  # Test suite
  ├── test_*.py        # Unit tests for each module

docs/                   # Documentation
  ├── spec.md          # Project specification
  ├── implementation.md # Implementation details
  └── tasks.md         # Task tracking
```

## Key Features to Understand

### Multi-Provider Support
- Automatically detects provider based on model name
- Models with `:` (e.g., `llama3:latest`) → Ollama
- Known Ollama models → Ollama
- Others → Gemini API

### Rate Limiting
- Only applies to Gemini API (not Ollama)
- Tracks RPM (requests/minute), TPM (tokens/minute), and daily requests
- Persists state in `.summarizer-rate-limit.json` in vault

### URL Cleaning
- Strips tracking parameters (UTM tags, fbclid, etc.)
- Preserves meaningful parameters (YouTube `?v=`, GitHub `?tab=`)
- Removes RSS noise fragments

### Frontmatter Structure
Summary notes include rich frontmatter:
- `source`: Original URL
- `title`: Page title
- `date`: Processing date
- `author`: Page author (if available)
- `content_type`: e.g., article, documentation
- `domain`: Source domain
- `tags`: Extracted from metadata and hashtags
- `from`: Backlink to daily note
- `summary_status`: success/error/mocked

## Common Commands

```bash
# Summarize URLs from today's daily note
summarize-links from-note --vault ~/Notes

# Summarize specific URLs
summarize-links urls https://example.com --vault ~/Notes

# List all daily notes with URLs
summarize-links list --vault ~/Notes

# Check rate limit status
summarize-links status --vault ~/Notes

# Mock mode (no API calls)
summarize-links from-note --vault ~/Notes --mock

# Verbose output
summarize-links from-note --vault ~/Notes --verbose
```

## Git Commit Conventions

Use conventional commit messages:
- `feat:` - New features
- `fix:` - Bug fixes
- `test:` - Adding/updating tests
- `docs:` - Documentation changes
- `refactor:` - Code changes that don't add features or fix bugs
- `chore:` - Build/tooling changes

## When Suggesting Code

1. **Maintain strict type hints** - mypy runs in strict mode
2. **Follow existing patterns** - Check similar code in the codebase
3. **Test your suggestions** - Ensure code can be tested with pytest
4. **Handle errors gracefully** - Use custom exceptions and logging
5. **Consider idempotency** - Make operations safe to retry
6. **Document complex logic** - Add docstrings and comments
7. **Use dependency injection** - Pass dependencies as parameters

## Important Notes

- This project uses `uv`, not `pip` or `poetry`
- Always run linting/formatting/type checking before committing
- Tests must pass before changes are merged
- Environment variables are used for configuration
- Both Gemini and Ollama are supported providers
- Rate limiting only applies to Gemini API
- Mock mode is available for testing without API calls
