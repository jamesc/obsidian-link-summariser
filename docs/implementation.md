# Obsidian Link Summarizer - Implementation Plan

## Build Guidelines

- **Comment code**: Add clear, meaningful comments explaining the "why" not just the "what"
  - Module-level docstrings for each file
  - Function/method docstrings with parameters and return values
  - Inline comments for complex logic

- **Use standard logging**: Implement Python's `logging` library from the start
  - Configure logging levels (DEBUG, INFO, WARNING, ERROR)
  - Use `--verbose` flag to enable DEBUG output
  - Log key operations: URL extraction, API calls, file writes

- **Write tests as you go**: Create unit tests alongside each module, not as an afterthought

- **Run tests regularly**: Execute `pytest` after each significant change to catch regressions early

- **Static analysis before commits**: Run these tools before each commit:
  - `ruff check .` - Fast linting
  - `ruff format .` - Code formatting
  - `mypy .` - Type checking

- **Type hints everywhere**: Enforce type annotations on all function parameters and return values

- **Custom exceptions**: Create specific exception classes for clearer error handling
  - `URLExtractionError`, `GeminiAPIError`, `NoteWriteError`, etc.
  - Catch and handle appropriately at CLI level

- **No magic values**: Use named constants instead of hardcoded strings/numbers
  - Define in `config.py` or module-level constants
  - e.g., `MAX_CONTENT_LENGTH = 50000` not `content[:50000]`

- **Small, focused functions**: Each function does one thing well
  - Easier to test, read, and maintain
  - If a function needs "and" in its description, split it

- **Dependency injection**: Pass clients/dependencies as parameters for testability
  - e.g., pass `GeminiClient` instance to functions rather than instantiating inside
  - Makes mocking straightforward in tests

- **Idempotency**: Running the same command twice should be safe
  - Skip already-processed URLs or overwrite gracefully
  - Check if summary note already exists before processing

- **Graceful degradation**: If one URL fails, continue with the rest
  - Log errors but don't abort entire batch
  - Report summary of successes/failures at end

- **Git hygiene**: Use conventional commit messages
  - `feat:` new features
  - `fix:` bug fixes
  - `test:` adding/updating tests
  - `docs:` documentation changes
  - `refactor:` code changes that don't add features or fix bugs

---

## Phase 1: Project Setup & Core Structure
**Goal**: Establish project foundation and tooling

1. Initialize `pyproject.toml` with uv configuration and dependencies
2. Set up package structure (`summarize_links/` with `__init__.py`)
3. Create `README.md` with basic setup instructions

---

## Phase 2: Configuration Module (`config.py`)
**Goal**: Handle environment variables and YAML config

1. Load `GEMINI_API_KEY`, `GEMINI_MODEL`, `DEFAULT_VAULT_PATH` from env
2. Parse optional `.summarizer-config.yaml` from vault root
3. Merge config sources with environment variables taking priority

---

## Phase 3: Notes Module (`notes.py`)
**Goal**: Parse daily notes and write summary files

1. **`read_daily_note(vault, note_path)`** - Read note content
2. **`extract_urls(content)`** - Regex extract URLs from Markdown links and bare URLs
3. **`write_summary_note(vault, out_folder, date, slug, content)`** - Atomic write with slug generation
4. **`generate_slug(title)`** - Lowercase, replace special chars, limit 50 chars

---

## Phase 4: End-to-End Test Suite
**Goal**: Establish testable foundation early

1. Create `tests/` directory with `conftest.py` for pytest fixtures
2. Add `tests/fixtures/` with sample daily notes and expected outputs
3. Write `test_notes.py` - URL extraction, slug generation, note writing
4. Write `test_integration.py` - Full flow with mock vault directory
5. Configure pytest in `pyproject.toml`

---

## Phase 5: GitHub Actions CI
**Goal**: Automated testing on every commit

1. Create `.github/workflows/test.yml`:
   - Trigger on push and pull request
   - Matrix test on Python 3.11, 3.12
   - Install dependencies, run `pytest`
   - Upload coverage report (optional)
2. Add status badge to `README.md`

---

## Phase 6: Content Extraction (`extract.py`)
**Goal**: Fetch and clean web page content

1. **`fetch_html(url)`** - HTTP GET with timeout, user-agent, error handling
2. **`extract_readable_content(html)`** - BeautifulSoup parsing
3. Add `test_extraction.py` to test suite

---

## Phase 7: Gemini Client (`gemini_client.py`)
**Goal**: AI summarization with mock support

1. **`summarize_page(content, url, model)`** - Real Gemini API call
2. **`MockGeminiClient`** - Deterministic responses for testing
3. Rate limit handling with stub note creation
4. Add `test_gemini_client.py` with mock tests

---

## Phase 8: CLI Entry Point (`cli.py`)
**Goal**: Argparse-based command interface

1. Global options and `from-note`/`urls` commands
2. Rich output with progress indicators
3. Add `test_cli.py` for argument parsing tests

---

## Phase 9: Documentation & Polish
**Goal**: Make it user-ready

1. Complete `README.md` with Obsidian setup guide
2. Add inline code documentation

---

## Implementation Order

| Order | Component | Estimated Time | Dependencies |
|-------|-----------|----------------|--------------|
| 1 | Project setup + `pyproject.toml` | 15 min | None |
| 2 | `config.py` | 30 min | Project setup |
| 3 | `notes.py` | 1 hr | Config |
| 4 | Test suite setup + notes tests | 45 min | Notes module |
| 5 | GitHub Actions CI | 20 min | Test suite |
| 6 | `extract.py` + tests | 1 hr | Test suite |
| 7 | `gemini_client.py` + tests | 1 hr | Config, Test suite |
| 8 | `cli.py` + tests | 1.5 hr | All modules |
| 9 | README + polish | 30 min | All |

**Total estimate**: ~8-9 hours
