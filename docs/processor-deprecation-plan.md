# Processor.py Deprecation Plan

## Status: Ready for Deprecation ✅

The `summarize_links/processor.py` module has been successfully replaced by the new services layer (`summarize_links/services/summarization.py`). All command handlers now use the new service functions.

## Migration Summary

### Old Functions → New Services

| Old Function (processor.py) | New Function (services/summarization.py) | Status |
|------------------------------|------------------------------------------|--------|
| `process_url_with_metadata()` | `process_url()` | ✅ Replaced |
| `process_urls_batch()` | `process_urls()` | ✅ Replaced |
| `process_resummarize_batch()` | `process_resummarize()` | ✅ Replaced |

### Command Migration Status

All command handlers have been migrated to use the services layer:

- ✅ [from_note.py](../summarize_links/commands/from_note.py) - Uses `services.summarization.process_urls()`
- ✅ [urls.py](../summarize_links/commands/urls.py) - Uses `services.summarization.process_urls()`
- ✅ [resummarize.py](../summarize_links/commands/resummarize.py) - Uses `services.summarization.process_resummarize()`

### Remaining Direct Usage

Only 2 files still import from `processor.py`:

1. **tests/test_cli.py** - Line 38: `from summarize_links.processor import process_url_with_metadata`
   - Used in ~16 test functions
   - **Action Required**: Refactor tests to use `services.summarization.process_url()`

2. **tests/test_from_note_interrupt.py** - Lines 109, 145: `from summarize_links import processor`
   - Tests the shutdown signal handling in batch processing
   - Uses `processor.process_urls_batch()` and `processor.process_resummarize_batch()`
   - **Action Required**: Update to use `services.summarization` functions

## Deprecation Steps

### Phase 1: Update Tests (Required)

1. **Refactor test_cli.py**
   - Replace `process_url_with_metadata()` calls with `process_url()`
   - Update return value handling (new service returns `ProcessOutcome` object)
   - Update test expectations for new structured return values

2. **Refactor test_from_note_interrupt.py**
   - Update imports to use `services.summarization`
   - Replace `processor.process_urls_batch()` with `summarization.process_urls()`
   - Replace `processor.process_resummarize_batch()` with `summarization.process_resummarize()`
   - Update shutdown flag access (`_shutdown_requested` is now in `services.summarization`)

### Phase 2: Add Deprecation Warning

Add deprecation warnings to processor.py functions:

```python
import warnings

def process_url_with_metadata(*args, **kwargs):
    warnings.warn(
        "process_url_with_metadata is deprecated. "
        "Use summarize_links.services.summarization.process_url() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Existing implementation...
```

### Phase 3: Remove After Test Migration

Once all tests are updated:

1. Remove `summarize_links/processor.py`
2. Remove legacy shim in `commands/from_note.py`:
   ```python
   # Legacy shim for tests
   process_urls_batch = process_urls
   ```
3. Update documentation to reference new services layer

## Benefits of Migration

### Improved Architecture
- ✅ Clear separation of concerns (services vs command handlers)
- ✅ Reusable business logic across CLI and chat tools
- ✅ Better testability with dependency injection

### Enhanced Return Values
Old: `tuple[bool, str, bool]` - Unclear what each boolean means
New: `ProcessOutcome` dataclass with explicit fields:
- `success: bool`
- `message: str`
- `should_delete_source: bool`
- `summary_path: str | None`
- `slug: str | None`
- `summary_result: SummaryResult | None`
- `page_metadata: PageMetadata | None`
- `error_type: ErrorType | None`

### Progress Callbacks
New services support optional progress callbacks for better UI integration in chat tools.

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Test failures after refactoring | Medium | Run full test suite after each change |
| Behavioral differences in new services | Low | Services were designed as drop-in replacements |
| Breaking external code using processor.py | Low | No known external users; this is a CLI tool |

## Timeline

- **Week 1**: Refactor test_cli.py tests
- **Week 1**: Refactor test_from_note_interrupt.py tests
- **Week 1**: Verify all tests pass
- **Week 2**: Add deprecation warnings
- **Week 3**: Remove processor.py completely

## Checklist

- [ ] Update test_cli.py to use services.summarization.process_url()
- [ ] Update test_from_note_interrupt.py to use services.summarization functions
- [ ] Run full test suite: `uv run pytest`
- [ ] Run linting: `uv run ruff check .`
- [ ] Run type checking: `uv run mypy .`
- [ ] Add deprecation warnings to processor.py
- [ ] Update docs to reference services layer
- [ ] Remove processor.py
- [ ] Remove legacy shim in commands/from_note.py
- [ ] Final test suite verification

## References

- New services implementation: [services/summarization.py](../summarize_links/services/summarization.py)
- Service layer plan: [commands-chat-unification-plan.md](commands-chat-unification-plan.md)
- Original refactor discussion: PR #37
