
## Build Guidelines

- **Never commit secrets**: Always use environment variables and .env files, and only commit an .env.example

- **Comment code**: Add clear, meaningful comments explaining the "why" not just the "what"
  - Module-level docstrings for each file
  - Function/method docstrings with parameters and return values
  - Inline comments for complex logic

- **Use standard logging**: Implement Python's `logging` library from the start
  - Configure logging levels (DEBUG, INFO, WARNING, ERROR)
  - Use `--verbose` flag to enable DEBUG output
  - Log key operations: URL extraction, API calls, file writes

- **Write tests as you go**: Create unit tests alongside each module, not as an afterthought

- **Run tests regularly**: Execute `uv run pytest` after each significant change to catch regressions early

- **Always use uv for python environment management**

- **Static analysis before commits - MANDATORY**: Run ALL these tools before EVERY commit:
  1. `uv run ruff check .` - Fast linting
  2. `uv run ruff format .` - Code formatting
  3. `uv run mypy .` - Type checking

  **CRITICAL**: If ANY check fails:
  1. Fix the issue
  2. Re-run ALL THREE checks again (not just the one that failed)
  3. Only commit when all three pass

  This prevents cascading failures where fixing one issue introduces another.

- **Type hints everywhere**: Enforce type annotations on all function parameters and return values

- **Document your actions**: On completing a task, write a summary to docs/tasks.md

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
