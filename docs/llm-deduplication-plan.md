# LLM Module Deduplication Plan

## Overview

This plan addresses code duplication in the `summarize_links/llm/` module, particularly in the Gemini and Ollama client implementations. The goal is to consolidate shared logic into the base class while maintaining clean, maintainable provider-specific implementations.

## Current Issues

### 1. Duplicated Metadata Building
Both `GeminiClient` and `OllamaClient` build the same `prompt_metadata` dictionary structure with slight naming inconsistencies:
- **GeminiClient**: Uses `system_version`, `user_version`
- **OllamaClient**: Uses `system_prompt_version`, `user_prompt_version`

Both include the same fields: system/user prompt names, versions, and source.

### 2. Duplicated Result Population
Both clients populate `SummaryResult` with identical fields in `summarize_with_metadata()`:
```python
result.usage_details = usage_details
result.system_prompt = system_prompt
result.raw_prompt = prompt
result.raw_response = raw_response
result.prompt_metadata = prompt_metadata
```

### 3. Dead Code in prompts.py
The `prompts.py` module provides fallback prompt loading from the filesystem but is unused since Langfuse became required. Functions include:
- `load_system_prompt()`
- `load_user_prompt_template()`
- `build_user_prompt_from_template()`

### 4. Inconsistent Naming
Prompt metadata field names differ between implementations, making the codebase harder to maintain.

### 5. Repeated Prompt Version Logging
Both clients have similar debug logging for prompt versions.

## Proposed Solution

### Phase 1: Standardize Metadata Structure

**Goal**: Use consistent field names across all clients.

**Decision**: Follow Ollama's naming convention (more explicit with `_prompt_version`).

**Changes**:
1. Define standard metadata structure (following Ollama's naming):
   ```python
   {
       "system_prompt_name": "summarize-document/system",
       "system_prompt_version": int | None,
       "user_prompt_name": "summarize-document/user", 
       "user_prompt_version": int | None,
       "source": "langfuse"
   }
   ```

2. Update GeminiClient to use this structure (change `system_version` → `system_prompt_version` and `user_version` → `user_prompt_version`)
 (update field names)

**Testing**:
- Update tests that check Gemini metadata field names
- Add test to verify both clients produce identical metadata structure
- Verify serialization/deserialization still works

**Risk Level**: LOW
- Simple naming change in one file
- OllamaClient already follows standards to verify metadata field names
- Add test to verify metadata structure consistency

**Risk Level**: LOW
- Simple naming change
- Easy to verify in tests
- No functional changes

---

### Phase 2: Move Metadata Building to Base Class

**Goal**: Centralize prompt metadata construction in `BaseLLMClient`.

**Changes**:

1. Add new method to `BaseLLMClient`:
   ```python
   def _build_prompt_metadata(self) -> dict[str, Any] | None:
       """
       Build prompt metadata dictionary from cached Langfuse prompts.
       
       Returns:
           Dictionary with prompt names, versions, and source.
           None if prompts not cached.
       """
       if "system" not in self._prompt_cache or "user" not in self._prompt_cache:
           return None
           
       system_obj = self._prompt_cache["system"]
       user_obj = self._prompt_cache["user"]
       
       return {
           "system_prompt_name": "summarize-document/system",
           "system_prompt_version": getattr(system_obj, "version", None),
           "user_prompt_name": "summarize-document/user",
           "user_prompt_version": getattr(user_obj, "version", None),
           "source": "langfuse",
       }
   ```

2. Replace duplicated metadata building in both clients with:
   ```python
   prompt_metadata = self._build_prompt_metadata()
   ```

**Files Affected**:
- `summarize_links/llm/base.py` (add method)
- `summarize_links/llm/gemini.py` (remove duplication)
- `summarize_links/llm/ollama.py` (remove duplication)

**Testing**:
- Unit test for `_build_prompt_metadata()` method
- Verify existing integration tests still pass
- Test behavior when prompts not cached

**Risk Level**: LOW
- Pure refactoring, no logic changes
- Well-isolated change
- Easy to verify correctness

---

### Phase 3: Create Result Population Helper

**Goal**: Consolidate the pattern of populating SummaryResult fields.

**Changes**:

1. Add new method to `BaseLLMClient`:
   ```python
   def _populate_result_metadata(
       self,
       result: SummaryResult,
       system_prompt: str,
       user_prompt: str,
       raw_response: str,
       usage_details: dict[str, int] | None = None,
   ) -> None:
       """
       Populate SummaryResult with prompt and usage metadata.
       
       Args:
           result: SummaryResult object to populate.
           system_prompt: System prompt text used.
           user_prompt: User prompt text used.
           raw_response: Raw response from LLM.
           usage_details: Optional token usage details.
       """
       result.system_prompt = system_prompt
       result.raw_prompt = user_prompt
       result.raw_response = raw_response
       result.usage_details = usage_details
       result.prompt_metadata = self._build_prompt_metadata()
   ```

2. Replace duplicated population code in both clients:
   ```python
   # Before (duplicated in both clients):
   result.usage_details = usage_details
   result.system_prompt = system_prompt
   result.raw_prompt = prompt
   result.raw_response = raw_response
   result.prompt_metadata = prompt_metadata
   
   # After (single call):
   self._populate_result_metadata(
       result, system_prompt, prompt, raw_response, usage_details
   )
   ```

**Files Affected**:
- `summarize_links/llm/base.py` (add method)
- `summarize_links/llm/gemini.py` (simplify)
- `summarize_links/llm/ollama.py` (simplify)

**Testing**:
- Unit test for `_populate_result_metadata()`
- Verify all fields are set correctly
- Test with and without usage_details
- Verify existing integration tests pass

**Risk Level**: LOW-MEDIUM
- More complex than Phase 2
- Touches result object directly
- But still isolated and testable

---

### Phase 4: Relocate prompts.py Module

**Goal**: Move prompts.py to a more appropriate location since it's used by utility scripts, not at runtime.

**Analysis**:
The `prompts.py` module is NOT dead code - it's actively used by `scripts/upload_prompts.py` to load prompts from the filesystem and upload them to Langfuse. However, it's never used during normal CLI operation (LLM clients fetch prompts directly from Langfuse).

**Current Usage**:
- `scripts/upload_prompts.py` imports `load_system_prompt()` and `load_user_prompt_template()`
- Reads `system.txt` and `user.txt` from `summarize_links/prompts/`
- Uploads to Langfuse as `summarize-document/system` and `summarize-document/user`

#### Recommended Approach: Move to scripts/ directory

**Changes**:
1. Move `summarize_links/llm/prompts.py` → `scripts/prompt_loader.py`
2. Update import in `scripts/upload_prompts.py`:
   ```python
   # Before:
   from summarize_links.llm.prompts import load_system_prompt, load_user_prompt_template
   
   # After:
   from prompt_loader import load_system_prompt, load_user_prompt_template
   ```
3. Update `PROMPTS_DIR` path in the moved file to point to correct location:
   ```python
   # Before (in summarize_links/llm/prompts.py):
   PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
   
   # After (in scripts/prompt_loader.py):
   PROMPTS_DIR = Path(__file__).parent.parent / "summarize_links" / "prompts"
   ```
4. Keep `summarize_links/prompts/` directory (contains actual prompt files)

**Pros**:
- Clarifies that this is a utility module for scripts, not runtime code
- Removes it from the LLM module where it doesn't belong
- Makes it obvious what it's for (loading prompts for upload)
- Collocates with its only consumer (upload script)

**Cons**:
- Slightly longer import path in the script
- Minor refactoring needed

**Alternative**: Keep with better documentation
If moving seems like overkill, at least update the module docstring:
```python
"""
Prompt loading utilities for management scripts.

NOTE: This module is used by scripts/upload_prompts.py to load prompts
from the filesystem for uploading to Langfuse. It is NOT used during
normal CLI operation - LLM clients fetch prompts directly from Langfuse.
"""
```

**Recommendation**: Move to scripts/ directory
- Clearer separation of concerns
- Makes codebase easier to understand
- Small effort with high clarity benefit

**Files Affected**:
- `summarize_links/llm/prompts.py` → `scripts/prompt_loader.py` (move)
- `scripts/upload_prompts.py` (update import)
- `summarize_links/prompts/` directory (keep as-is)

**Testing**:
- Run `uv run python scripts/upload_prompts.py` to verify it still works
- Verify no other imports of the old module location
- Run full test suite

**Risk Level**: LOW
- Only affects utility script, not main CLI
- Easy to test and verify
- No impact on users

---

### Phase 5: Consolidate Prompt Version Logging

**Goal**: Standardize how prompt versions are logged.

**Changes**:

1. Add logging to `_get_langfuse_prompts()` in base class (already exists):
   ```python
   logger.info(
       "Fetched prompts from Langfuse: system v%s, user v%s",
       getattr(system_obj, "version", "unknown"),
       getattr(user_obj, "version", "unknown"),
   )
   ```

2. Remove duplicate version logging from subclasses since base class handles it.

3. Remove redundant debug logs like:
   ```python
   logger.debug(
       "Using Langfuse prompts: system v%s, user v%s",
       prompt_metadata["system_prompt_version"],
       prompt_metadata["user_prompt_version"],
   )
   ```

**Files Affected**:
- `summarize_links/llm/gemini.py`
- `summarize_links/llm/ollama.py`

**Testing**:
- Verify appropriate log messages appear once
- Check log output in integration tests

**Risk Level**: MINIMAL
- Logging changes only
- No functional impact

---

## Implementation Order

Execute phases in sequence:

1. **Phase 1**: Standardize metadata structure (1-2 hours)
   - Quick win, establishes foundation

2. **Phase 2**: Move metadata building to base class (1-2 hours)
   - Builds on Phase 1, reduces duplication significantly

3. **Phase 3**: Create result population helper (2-3 hours)
   - More complex, but high value

4. **Phase 4**: Handle prompts.py module (30 minutes)
   - Quick cleanup after main refactoring

5. **Phase 5**: Consolidate logging (30 minutes)
   - Final polish

**Total Estimated Time**: 6-8 hours

---

## Testing Strategy

### Unit Tests
- Test `_build_prompt_metadata()` in isolation
- Test `_populate_result_metadata()` with various inputs
- Mock Langfuse prompt objects
- Test with and without cached prompts

### Integration Tests
- Verify existing tests still pass after each phase
- No changes to external behavior
- Both Gemini and Ollama clients produce same metadata structure

### Manual Testing
- Run CLI with `--verbose` to verify logging
- Check summary notes contain correct metadata
- Test with both Gemini and Ollama models

---

## Success Criteria

- [ ] No duplicated metadata building code
- [ ] No duplicated result population code
- [ ] Consistent field naming across clients
- [ ] Unused `prompts.py` handled appropriately
- [ ] All existing tests pass
- [ ] No new mypy/ruff errors
- [ ] Code coverage maintained or improved
- [ ] Clear, concise base class with reusable methods
- [ ] Both clients simplified and more maintainable

---Breaking Upload Script
**Likelihood**: VERY LOW  
**Impact**: LOW  
**Mitigation**:
- Test upload script after moving prompts.py
- Import path is simple to update
- Can easily revert if issues arise
**Mitigation**: 
- Comprehensive test coverage
- Incremental changes with testing after each phase
- Easy to revert individual commits

### Risk: Metadata Structure Changes
**Likelihood**: LOW  
**Impact**: LOW  
**Mitigation**:
- Only internal structure changes
- Users don't directly consume this metadata
- Backward compatible field names

### Risk: Removing Useful Code (prompts.py)
**Likelihood**: VERY LOW  
**Impact**: LOW  
**Mitigation**:
- Code preserved in git history
- Langfuse requirement is well-established
- Can restore quickly if needed

---

## Follow-up Opportunities

After completing this plan, consider:

1. **Extract Usage Details Parsing**: Both clients parse token counts differently - could be unified
2. **Retry Logic**: Gemini has sophisticated retry logic - could be abstracted for reuse
3. **Server Health Checks**: Ollama's server checking could be a base class pattern
4. **Error Handling**: More shared exception handling patterns
5. **Response Parsing**: Some overlap in how responses are validated

These are lower priority and can be addressed in future refactorings.

---

## Rollback Plan

If issues arise:

1. **Per-Phase Rollback**: Each phase is a separate commit/PR - revert individually
2. **Full Rollback**: Revert the entire feature branch
3. **Partial Fix**: If only one client has issues, fix that client specifically
4. **Git Bisect**: Use git bisect to find problematic commit if tests fail mysteriously

---

## Documentation Updates

After implementation:

- [ ] Update `AGENTS.md` if refactoring patterns should be followed elsewhere
- [ ] Update `docs/tasks.md` with completion summary
- [ ] Add comments in base class explaining the abstraction pattern
- [ ] Update PR description with summary of changes

---

## Conclusion

This plan systematically eliminates duplication in the LLM module while maintaining code quality and test coverage. The phased approach allows for incremental progress with low risk. Each phase can be completed independently, tested thoroughly, and committed separately.

The end result will be a cleaner, more maintainable codebase with shared functionality properly abstracted in the base class, making it easier to add new LLM providers in the future.
