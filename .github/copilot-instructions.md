# Copilot Instructions for Obsidian Link Summarizer

This document provides guidance for GitHub Copilot coding agent when working on the Obsidian Link Summarizer project.

## Project Overview

**Obsidian Link Summarizer** is a lightweight Python CLI tool that reads URLs from Obsidian daily notes, fetches web pages, generates AI summaries using Google's Gemini API or local Ollama models, and creates formatted Markdown summary notes in an Obsidian vault.

### Key Features
- Extract URLs from Obsidian daily notes (Markdown links and bare URLs)
- Generate AI summaries using Google Gemini (cloud API) or Ollama (local models)
- Create well-formatted summary notes with rich frontmatter
- Automatic tag extraction and URL cleaning
- Built-in rate limiting for Gemini API
- Idempotent operations (safe to run multiple times)
- Graceful degradation (continues processing on failures)
- Mock mode for development/testing

### Architecture

**Main Modules:**
- `cli.py` - Command-line interface and main entry point
- `config.py` - Configuration management (env vars, YAML, defaults)
- `extract.py` - Web page fetching and content extraction
- `notes.py` - Obsidian note reading/writing operations
- `gemini_client.py` - Google Gemini API client
- `ollama_client.py` - Ollama API client for local models
- `llm_factory.py` - Factory pattern for creating LLM clients
- `rate_limiter.py` - Token bucket rate limiting for API calls
- `langfuse_tracer.py` - Optional LLM observability integration
- `models.py` - Pydantic data models
- `exceptions.py` - Custom exception classes

**Design Patterns:**
- Factory pattern for LLM client creation (supports multiple providers)
- Protocol-based interfaces for client abstraction
- Dependency injection for testability
- Configuration cascading: CLI args > env vars > YAML config > defaults

## Development Workflow

### Environment Setup

```bash
# Install dependencies
uv sync

# Install with dev dependencies
uv sync --all-extras

# Copy environment file and configure
cp .env.example .env
# Edit .env with your GEMINI_API_KEY and preferences
```

### Building and Testing

**Run tests:**
```bash
uv run pytest
```

**Run with coverage:**
```bash
uv run pytest --cov=summarize_links --cov-report=html
```

**Linting (MANDATORY before commits):**
```bash
# Run all three tools in order
uv run ruff check .
uv run ruff format .
uv run mypy .

# If ANY check fails, fix and re-run ALL THREE again
```

### Common Commands

**Run the CLI:**
```bash
# Process today's daily note
uv run summarize-links from-note --vault ~/Notes

# Process with specific date
uv run summarize-links from-note --vault ~/Notes --date 2025-12-16

# List daily notes with URLs
uv run summarize-links list --vault ~/Notes

# Specific URLs
uv run summarize-links urls https://example.com --vault ~/Notes

# Mock mode (no API calls)
uv run summarize-links from-note --vault ~/Notes --mock

# Verbose output
uv run summarize-links from-note --vault ~/Notes --verbose
```

## Code Style and Conventions

### General Principles
All code style guidelines are documented in `/AGENTS.md`. Key highlights:

1. **Never commit secrets** - Use environment variables and .env files
2. **Comment code** - Explain the "why" not just the "what"
   - Module-level docstrings for each file
   - Function/method docstrings with parameters and return values
   - Inline comments for complex logic
3. **Use standard logging** - Python's `logging` library throughout
   - Configure levels: DEBUG, INFO, WARNING, ERROR
   - Use `--verbose` flag to enable DEBUG output
4. **Write tests as you go** - Unit tests alongside each module
5. **Static analysis before commits** - Run ruff, format, mypy (see above)
6. **Type hints everywhere** - All function parameters and return values

### Python-Specific Conventions

**Type Annotations:**
```python
def summarize_url(url: str, client: SummarizerProtocol) -> SummaryResult:
    """All functions must have type hints."""
    pass
```

**Named Constants:**
```python
# Good: Use named constants
MAX_CONTENT_LENGTH = 50_000
content = page_text[:MAX_CONTENT_LENGTH]

# Bad: Magic values
content = page_text[:50000]
```

**Custom Exceptions:**
```python
# Use specific exception classes from exceptions.py
raise URLExtractionError(f"Failed to extract URLs: {err}")
# NOT: raise Exception("Failed to extract URLs")
```

**Dependency Injection:**
```python
# Good: Pass dependencies as parameters
def process_urls(urls: list[str], client: SummarizerProtocol) -> list[Result]:
    pass

# Bad: Instantiate inside function (harder to test)
def process_urls(urls: list[str]) -> list[Result]:
    client = GeminiClient()  # Avoid this
    pass
```

**Small, Focused Functions:**
- Each function should do one thing well
- If a function needs "and" in its description, split it

**Idempotency:**
- Running the same command twice should be safe
- Check if summary note already exists before processing
- Skip already-processed URLs

**Graceful Degradation:**
- If one URL fails, continue with the rest
- Log errors but don't abort entire batch
- Create stub notes for failures

### Git Commit Messages

Use conventional commits format:
- `feat:` new features
- `fix:` bug fixes
- `test:` adding/updating tests
- `docs:` documentation changes
- `refactor:` code changes that don't add features or fix bugs
- `chore:` maintenance tasks

Examples:
- `feat: add support for Ollama local models`
- `fix: handle rate limit errors gracefully`
- `test: add integration tests for URL extraction`
- `docs: update README with Ollama instructions`

## Testing

### Test Structure
- Tests are in `/tests/` directory
- Test files match source files: `test_*.py`
- Use pytest framework with pytest-mock for mocking

### Testing Practices

**Unit Tests:**
- Test individual functions in isolation
- Use mocks for external dependencies (API clients, file I/O)
- Test edge cases and error conditions

**Integration Tests:**
- Test end-to-end workflows
- Use temporary directories for file operations
- Clean up after tests

**Example Test Pattern:**
```python
import pytest
from unittest.mock import Mock

def test_summarize_url_success(mock_client):
    """Test successful URL summarization."""
    mock_client.summarize.return_value = "Summary content"
    
    result = summarize_url("https://example.com", mock_client)
    
    assert result.success is True
    assert "Summary content" in result.content
    mock_client.summarize.assert_called_once()
```

### Running Tests

```bash
# All tests
uv run pytest

# Specific test file
uv run pytest tests/test_notes.py

# Specific test
uv run pytest tests/test_notes.py::test_extract_urls

# With coverage
uv run pytest --cov=summarize_links

# Verbose output
uv run pytest -v
```

## Configuration

### Configuration Priority
1. CLI arguments (highest)
2. Environment variables
3. Vault YAML config file (`.summarizer-config.yaml`)
4. Default values (lowest)

### Environment Variables
- `GEMINI_API_KEY` - Required for Gemini models
- `MODEL` - Model to use (auto-detects provider)
- `DEFAULT_VAULT_PATH` - Default Obsidian vault path
- `OLLAMA_ENDPOINT` - Ollama server endpoint (default: http://localhost:11434)
- `LANGFUSE_*` - Optional Langfuse tracing configuration

### Vault Configuration File
Create `.summarizer-config.yaml` in vault root:
```yaml
out_folder: "Summaries"
max_links: 10
daily_notes_folder: "Journal"
summary_model: "gemini-2.5-flash"

# Per-model rate limits (optional)
model_limits:
  gemini-2.5-flash:
    rpm_limit: 5
    tpm_limit: 250000
    daily_limit: 20
```

## Common Patterns and Tasks

### Adding a New LLM Provider

1. Create a new client in `summarize_links/` (e.g., `anthropic_client.py`)
2. Implement the `SummarizerProtocol` interface
3. Update `llm_factory.py` to detect and create the new client
4. Add provider-specific configuration to `config.py`
5. Add tests in `tests/test_anthropic_client.py`
6. Update documentation

### Adding a New CLI Command

1. Add command handler function to `cli.py`
2. Update argument parser with new subcommand
3. Add business logic in appropriate module
4. Write unit tests for the command
5. Update README with command usage

### Modifying Configuration

1. Update `Config` dataclass in `config.py`
2. Add loading logic in `load_config()` function
3. Update validation in `Config.validate()`
4. Update `.env.example` with new variable
5. Add tests in `tests/test_config.py`
6. Document in README

### Handling Errors

1. Use custom exceptions from `exceptions.py`
2. Catch specific exceptions at appropriate levels
3. Log errors with context using `logging`
4. For user-facing errors, use `console.print()` with rich formatting
5. In CLI, convert exceptions to user-friendly messages

## Common Pitfalls and How to Avoid Them

### Issue: Untyped Functions
**Problem:** Missing type hints make code harder to maintain and prevent mypy from catching bugs.
**Solution:** Always add type hints to all function parameters and return values.

### Issue: Magic Values
**Problem:** Hardcoded numbers/strings scattered throughout code.
**Solution:** Define constants in `config.py` or at module level.

### Issue: Tight Coupling
**Problem:** Functions instantiate their own dependencies, making testing difficult.
**Solution:** Use dependency injection - pass dependencies as parameters.

### Issue: Test Failures After Changes
**Problem:** Making changes breaks unrelated tests.
**Solution:** Run tests frequently during development: `uv run pytest`

### Issue: Rate Limit Errors
**Problem:** Hitting Gemini API rate limits during development.
**Solution:** Use `--mock` flag for testing or switch to Ollama for local testing.

### Issue: File Path Issues
**Problem:** Hardcoded paths fail on different systems.
**Solution:** Use `Path` objects and resolve paths with `.expanduser().resolve()`

## Resources

- **Project README:** `/README.md` - User-facing documentation
- **Build Guidelines:** `/AGENTS.md` - Detailed development guidelines
- **Dependencies:** `pyproject.toml` - Project metadata and dependencies
- **Environment Example:** `.env.example` - Configuration template
- **Test Suite:** `/tests/` - Comprehensive test coverage

## Additional Notes

- **Python Version:** Requires Python 3.11+
- **Package Manager:** Always use `uv` for dependency management
- **Rich Output:** Use `rich` library for CLI formatting and progress indicators
- **Logging:** Use module-level loggers: `logger = logging.getLogger(__name__)`
- **Path Handling:** Always use `pathlib.Path` objects, never string concatenation

## When Working on Issues

1. **Understand Requirements:** Read the issue description and comments carefully
2. **Explore First:** Review relevant code files before making changes
3. **Make Minimal Changes:** Only modify what's necessary to fix the issue
4. **Write Tests:** Add tests for new functionality or bug fixes
5. **Run Quality Checks:** Execute linting, formatting, and type checking
6. **Test Thoroughly:** Run relevant tests to ensure changes work
7. **Document Changes:** Update docs if user-facing behavior changes
8. **Follow Conventions:** Match existing code style and patterns

## Security Considerations

- **Never commit API keys** - Use environment variables only
- **Validate User Input** - Sanitize URLs and file paths
- **Rate Limiting** - Respect API limits to avoid service abuse
- **Error Messages** - Don't expose sensitive information in errors
- **File Operations** - Validate paths to prevent directory traversal

## Getting Help

- Review existing code for patterns and examples
- Check test files for usage examples
- Consult `/AGENTS.md` for detailed build guidelines
- Read module docstrings for API documentation
