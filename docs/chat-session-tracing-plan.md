# Chat Session Tracing Plan

## Overview

Implement Langfuse session-level tracing for the chat CLI to group all interactions within a conversation under a single session. This enables:

- Viewing full conversation replay in Langfuse UI
- Aggregating metrics (cost, latency, tokens) per conversation
- Sharing sessions via public links
- Session-level scoring and evaluation

## Current State

Currently, each `process_message()` call in `ChatEngine` creates independent, disconnected traces:

- `chat_generate` - for initial LLM calls
- `chat_generate_followup` - for responses after tool execution
- `tool_{name}` spans - for individual tool executions

These traces are not grouped, making it impossible to view a conversation holistically in Langfuse.

## Langfuse Best Practice

According to [Langfuse documentation](https://langfuse.com/docs/observability/features/sessions):

- **Sessions** (`session_id`) group multiple traces across a conversation
- **Traces** represent individual request/response turns
- **Generations/Spans** are nested within traces for individual operations

```
Session (conversation)
├── Trace (message 1)
│   ├── Generation (chat_generate)
│   └── Span (tool_execution)
├── Trace (message 2)
│   └── Generation (chat_generate)
└── Trace (message 3)
    ├── Generation (chat_generate)
    ├── Span (tool_summarize)
    └── Generation (chat_generate_followup)
```

## Implementation Plan

### 1. Generate Session ID in ChatEngine

Add a unique `session_id` when `ChatEngine` is initialized:

```python
import uuid

class ChatEngine:
    def __init__(self, config: Config, ...):
        self.session_id = str(uuid.uuid4())
```

### 2. Update LangfuseTracer with Session Support

Add `propagate_attributes()` support to set `session_id` on all observations:

```python
from langfuse import propagate_attributes

# In trace methods, propagate session_id
with propagate_attributes(session_id=session_id):
    with tracer.trace_generation(...) as gen:
        # All nested observations inherit session_id
        pass
```

### 3. Add trace_message() Method for Per-Turn Traces

Create a context manager that wraps each message turn with a proper trace:

```python
@contextmanager
def trace_message(
    self,
    session_id: str,
    message_number: int,
    user_input: str,
) -> Generator[Any, None, None]:
    """Create a trace for a single conversation turn."""
    with propagate_attributes(session_id=session_id):
        with self._client.start_as_current_observation(
            as_type="span",
            name=f"message_{message_number}",
            input={"user_message": user_input},
            metadata={"message_number": message_number},
        ) as trace:
            yield trace
```

### 4. Modify ChatEngine.process_message()

Wrap the entire message processing in a session-aware trace:

```python
def process_message(self, user_message: str) -> str:
    self._message_count += 1

    with tracer.trace_message(
        session_id=self.session_id,
        message_number=self._message_count,
        user_input=user_message,
    ):
        # Existing processing logic
        # All nested trace_generation/trace_span calls
        # automatically become children of this trace
        return self._process_with_azure(user_message)
```

### 5. Include Session Info in Status Command

Update `get_status()` to return session information:

```python
def get_status(self) -> dict[str, Any]:
    return {
        "session_id": self.session_id,
        "message_count": self._message_count,
        # ... existing fields
    }
```

## Files to Modify

1. **`summarize_links/langfuse_tracer.py`**
   - Add `trace_message()` context manager for per-turn traces with session propagation
   - Update `MockLangfuseTracer` with no-op implementation

2. **`summarize_links/chat/engine.py`**
   - Add `session_id` and `_message_count` attributes
   - Wrap `process_message()` with session-aware tracing
   - Update `get_status()` to include session info
   - Update `clear_history()` to optionally reset message count

3. **`summarize_links/chat/formatter.py`** (optional)
   - Display session ID in welcome message

4. **`tests/test_chat_engine.py`**
   - Add tests for session ID generation
   - Test session propagation in traces

## Testing

1. **Unit Tests**
   - Verify session ID is generated on engine init
   - Verify message count increments correctly
   - Verify session_id is passed to tracer methods

2. **Integration Tests**
   - Start chat, send multiple messages, verify all appear in same Langfuse session
   - Verify session metrics aggregate correctly

## Rollback Plan

If issues arise, session tracing can be disabled by:
1. Removing `propagate_attributes()` calls
2. Session ID will still be generated but not propagated

## Success Criteria

- [ ] All messages in a chat session grouped under single session_id in Langfuse
- [ ] Session replay shows chronological conversation flow
- [ ] Per-session metrics (cost, latency) available in Langfuse
- [ ] No performance regression in chat responsiveness
- [ ] Tests pass with session tracing enabled
