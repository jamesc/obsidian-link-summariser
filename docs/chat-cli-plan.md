# Chat-Driven CLI Implementation Plan

## Overview

Implement an interactive, conversational CLI tool (similar to Gemini CLI or GitHub Copilot CLI) that allows users to chat with an AI assistant to fetch, summarize, and manage web pages in their Obsidian vault. The chat interface will understand natural language commands and provide a more intuitive way to interact with the summarization system.

## Goals

1. **Conversational Interface**: Natural language interaction for all operations
2. **Context-Aware**: Maintains conversation history and vault context
3. **Multi-Turn Dialogues**: Support follow-up questions and iterative refinement
4. **Rich Output**: Formatted markdown, tables, and progress indicators
5. **Extensible**: Easy to add new capabilities and tools
6. **Separate Models**: Use dedicated chat model distinct from summarization model

## Architecture

### Model Separation

The chat system uses a **separate model** from the summarization pipeline:

| Purpose | Model | Provider | Use Case |
|---------|-------|----------|----------|
| **Chat** | gpt-4o-mini (default) | Azure OpenAI | Conversational interaction, tool orchestration |
| **Summarization** | Configurable (existing) | Google/Azure/Ollama | Content summarization via existing pipeline |

**Rationale**:
- Chat needs fast, conversational responses → smaller, faster model
- Summarization needs quality content generation → can use different model
- Separation allows independent optimization of each use case
- Chat uses Azure OpenAI Responses API for native function calling

### High-Level Design

```
┌─────────────────────────────────────────────────────────────┐
│                    Chat CLI (chat.py)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐│
│  │ Input Loop  │──│ Message     │──│ Response Formatter   ││
│  │ (readline)  │  │ Handler     │  │ (Rich Markdown)      ││
│  └─────────────┘  └─────────────┘  └──────────────────────┘│
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                  Chat Engine (chat/engine.py)               │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐│
│  │ Conversation│  │ Tool        │  │ Azure OpenAI Client  ││
│  │ Manager     │  │ Dispatcher  │  │ (Responses API)      ││
│  └─────────────┘  └─────────────┘  └──────────────────────┘│
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                    Tools (chat/tools/)                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐│
│  │ summarize_url│ │ search_vault │ │ list_summaries       ││
│  └──────────────┘ └──────────────┘ └──────────────────────┘│
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐│
│  │ read_summary │ │ delete       │ │ find_daily_notes     ││
│  └──────────────┘ └──────────────┘ └──────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│               Existing Infrastructure                        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐│
│  │ LLM Clients  │ │ Notes Module │ │ Extract Module       ││
│  │ (factory.py) │ │ (notes/)     │ │ (extract/)           ││
│  └──────────────┘ └──────────────┘ └──────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### Azure OpenAI Responses API

Chat mode exclusively uses Azure OpenAI with the Responses API:

```python
from openai import AzureOpenAI

client = AzureOpenAI(
    api_key=config.azure_api_key,
    api_version="2024-12-01-preview",  # Responses API version
    azure_endpoint=config.azure_endpoint,
)

response = client.responses.create(
    model=config.chat_model,  # e.g., "gpt-4o-mini"
    input=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ],
    tools=tool_definitions,
)
```

**Benefits of Responses API**:
- Native function/tool calling with automatic execution loop
- Built-in streaming support
- Structured output handling
- Consistent with OpenAI best practices

### Langfuse Tracing Architecture

Full conversation tracing with hierarchical structure:

```
┌─────────────────────────────────────────────────────────────────┐
│ TRACE: chat_session                                             │
│   session_id: "abc123"                                          │
│   metadata: { model, vault_path, tools_available }              │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ SPAN: turn_1                                            │   │
│   │   input: "Summarize https://example.com"                │   │
│   │                                                         │   │
│   │   ┌─────────────────────────────────────────────────┐   │   │
│   │   │ GENERATION: chat_llm_call                       │   │   │
│   │   │   model: "gpt-4o-mini"                          │   │   │
│   │   │   input: [system, user messages]                │   │   │
│   │   │   output: function_call(summarize_url)          │   │   │
│   │   │   usage: { input: 150, output: 25 }             │   │   │
│   │   └─────────────────────────────────────────────────┘   │   │
│   │                                                         │   │
│   │   ┌─────────────────────────────────────────────────┐   │   │
│   │   │ SPAN: tool_summarize_url                        │   │   │
│   │   │   args: { url: "https://example.com" }          │   │   │
│   │   │   result: { success: true, file: "..." }        │   │   │
│   │   └─────────────────────────────────────────────────┘   │   │
│   │                                                         │   │
│   │   ┌─────────────────────────────────────────────────┐   │   │
│   │   │ GENERATION: chat_llm_followup                   │   │   │
│   │   │   input: [messages + tool_result]               │   │   │
│   │   │   output: "I've summarized the page..."         │   │   │
│   │   │   usage: { input: 200, output: 50 }             │   │   │
│   │   └─────────────────────────────────────────────────┘   │   │
│   │                                                         │   │
│   │   output: "I've summarized the page..."             │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ SPAN: turn_2                                            │   │
│   │   input: "What tags did it have?"                       │   │
│   │   ... (subsequent turns)                                │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Tracing Implementation**:

```python
# Session-level trace (created when chat starts)
with tracer.trace_chat_session(
    session_id=session_id,
    metadata={"model": config.chat_model, "vault": str(config.vault_path)}
) as session_trace:

    # Each user message creates a turn span
    with tracer.trace_span(
        name=f"turn_{turn_number}",
        input_data={"user_message": user_message},
    ) as turn_span:

        # LLM generation within turn
        with tracer.trace_generation(
            name="chat_llm_call",
            model=config.chat_model,
            input_data={"messages": messages},
        ) as generation:
            response = client.responses.create(...)
            generation.update(output=response, usage_details=usage)

        # Tool execution (if any)
        if tool_calls:
            with tracer.trace_span(
                name=f"tool_{tool_name}",
                input_data={"args": tool_args},
            ) as tool_span:
                result = execute_tool(tool_name, tool_args)
                tool_span.update(output=result)
```

**Benefits**:
- Full visibility into multi-turn conversations
- Track token usage across entire session
- Debug tool execution failures in context
- Analyze conversation patterns and user intent
- Cost tracking per session

### Key Components

#### 1. Chat Entry Point (`summarize_links/commands/chat.py`)

Entry point for the chat command, handles:
- Initializing the chat session
- Input/output loop with readline support
- Signal handling (Ctrl+C, Ctrl+D)
- Session persistence (optional)

#### 2. Chat Engine (`summarize_links/chat/engine.py`)

Core orchestration using Azure OpenAI Responses API:
- Manages conversation history
- Routes user messages to Azure OpenAI
- Handles tool calling via Responses API
- Manages streaming responses

#### 3. Azure Chat Client (`summarize_links/chat/azure_client.py`)

Dedicated Azure OpenAI client for chat:
- Uses OpenAI Responses API (`client.responses.create`)
- Separate configuration from summarization client
- Native function calling support
- Streaming response handling

#### 4. Tool System (`summarize_links/chat/tools/`)

Defines "tools" the LLM can call:
- **summarize_url**: Fetch and summarize a URL
- **summarize_urls**: Batch summarize multiple URLs
- **search_vault**: Search existing summaries
- **list_summaries**: Show recent summaries
- **read_summary**: Read a specific summary
- **find_urls_in_notes**: Find URLs in daily notes
- **get_status**: Show rate limit status
- **help**: Show available commands

#### 4. Conversation Manager (`summarize_links/chat/conversation.py`)

Handles:
- Message history storage (in-memory + optional persistence)
- Context window management
- System prompt construction

#### 5. Response Formatter (`summarize_links/chat/formatter.py`)

Rich output formatting:
- Markdown rendering
- Progress spinners
- Tables for lists
- Syntax highlighting for code

## Implementation Phases

### Phase 1: Foundation (MVP) - REVISION NEEDED
**Goal**: Basic chat loop with single-turn summarization

**Status**: Phase 1 was implemented with Gemini. Needs refactoring to Azure OpenAI.

1. **Create chat subcommand** (`commands/chat.py`) ✓
   - Add `chat` command to CLI parser
   - Basic REPL loop with readline
   - History support

2. **Implement chat engine** (`chat/engine.py`) - REFACTOR
   - ~~LLM client integration (reuse existing factory)~~ → Azure OpenAI Responses API
   - Single-turn message handling
   - Basic tool calling for `summarize_url`

3. **Create tool base class** (`chat/tools/base.py`) ✓
   - Tool protocol/interface
   - Tool registry
   - Execution wrapper with error handling

4. **Implement summarize_url tool** (`chat/tools/summarize.py`) ✓
   - Reuse `process_url_with_metadata` from processor.py
   - Return structured results

5. **Basic formatter** (`chat/formatter.py`) ✓
   - Markdown output with Rich
   - Simple progress indicators

### Phase 1a: Langfuse Tracing ✓
**Goal**: Full observability for chat interactions

1. **Trace chat sessions** ✓
   - Create trace per conversation session
   - Track session metadata (provider, model, tools)

2. **Trace LLM generations** ✓
   - Wrap API calls with `trace_generation()`
   - Capture input messages, output response, token usage
   - Link to system prompts

3. **Trace tool executions** ✓
   - Wrap tool calls with `trace_span()`
   - Capture tool name, arguments, results
   - Track success/failure

4. **Integration with existing tracer** ✓
   - Use `get_tracer()` for mock mode support
   - Respect Langfuse configuration from config

### Phase 1b: Azure OpenAI Migration
**Goal**: Migrate chat engine from Gemini to Azure OpenAI Responses API

1. **Create Azure chat client** (`chat/azure_client.py`)
   - Use `openai.AzureOpenAI` with Responses API
   - Configure separate endpoint/model for chat
   - Implement function calling with OpenAI tool format

2. **Refactor chat engine**
   - Remove Gemini-specific code
   - Use Azure chat client exclusively
   - Update tool declarations to OpenAI format

3. **Configuration updates**
   - Add `CHAT_MODEL` environment variable
   - Add `CHAT_AZURE_DEPLOYMENT` configuration
   - Keep existing summarization config separate

4. **Full conversation Langfuse tracing**
   - Create **session-level trace** for entire chat session
   - Each user message creates a **turn span** within the session
   - LLM generations are **nested within turn spans**
   - Tool executions are **nested within generation spans**
   - Track conversation context across turns

   ```
   Trace: chat_session (session_id, start_time, user)
   └── Span: turn_1 (user_message)
   │   └── Generation: chat_response (input, output, usage)
   │       └── Span: tool_summarize_url (args, result)
   │       └── Generation: followup_response (input, output, usage)
   └── Span: turn_2 (user_message)
   │   └── Generation: chat_response (input, output, usage)
   └── ... (subsequent turns)
   ```

5. **Update tests**

### Phase 2: Multi-Turn & Tools ✓
**Goal**: Full conversational experience with multiple tools

1. **Conversation history management** ✓
   - Token counting for context window ✓
   - Message pruning/summarization ✓
   - Session persistence (JSON) ✓

2. **Expand tool set**: ✓
   - `list_summaries` - Show existing summaries ✓
   - `search_vault` - Search by keyword/tag ✓
   - `read_summary` - Read content of a summary ✓
   - `find_urls_in_notes` - Find URLs in daily notes ✓
   - `get_rate_limit_status` - Rate limit status ✓
   - `get_vault_status` - Vault statistics ✓

3. **Enhanced tool calling**: ✓
   - Multi-tool chains ✓
   - Tool confirmation prompts ✓
   - Dry-run mode for tools (via confirm_tools config)

4. **Streaming responses** ✓
   - Word-by-word output ✓
   - Interrupt handling ✓

### Phase 3: Advanced Features
**Goal**: Power user features and polish

1. **Smart context**:
   - Auto-detect URLs in user input
   - Suggest related summaries
   - Remember user preferences

2. **Slash commands**:
   - `/help` - Show help
   - `/clear` - Clear history
   - `/save` - Save conversation
   - `/load` - Load conversation
   - `/config` - Show/set config

3. **Batch operations**:
   - "Summarize all links from today's note"
   - "Re-summarize old summaries"

4. **Integration**:
   - Obsidian URI handling
   - Clipboard support

## File Structure

```
summarize_links/
├── chat/
│   ├── __init__.py
│   ├── azure_client.py    # Azure OpenAI Responses API client
│   ├── engine.py          # Chat orchestration
│   ├── conversation.py    # History management
│   ├── formatter.py       # Rich output formatting
│   ├── prompts.py         # System prompts
│   └── tools/
│       ├── __init__.py
│       ├── base.py        # Tool protocol & registry
│       ├── summarize.py   # URL summarization tools
│       ├── search.py      # Vault search tools
│       ├── notes.py       # Daily note tools
│       └── system.py      # Status, help tools
├── commands/
│   └── chat.py            # Chat command entry point
```

## Tool Definitions

### Tool Schema (OpenAI Format for Responses API)

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "summarize_url",
            "description": "Fetch a web page and create an AI-generated summary in the vault",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to summarize"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags to add to the summary"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_summaries",
            "description": "Search existing summaries in the vault by keyword or tag",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (keywords or tags)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_summaries",
            "description": "List recent summaries in the vault",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum summaries to list",
                        "default": 10
                    },
                    "status": {
                        "type": "string",
                        "enum": ["all", "success", "error", "mocked"],
                        "description": "Filter by summary status"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_summary",
            "description": "Read the content of an existing summary",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title or filename of the summary"
                    }
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_urls_in_notes",
            "description": "Find URLs in daily notes that haven't been summarized yet",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format (default: today)"
                    },
                    "all_dates": {
                        "type": "boolean",
                        "description": "Search all daily notes"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_rate_limit_status",
            "description": "Show current API rate limit usage and remaining quota",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]
```

## System Prompt Design

```markdown
You are a helpful assistant for managing an Obsidian vault of web page summaries.

## Your Capabilities
You can help users:
- Summarize web pages and save them to the vault
- Search and find existing summaries
- Find URLs in daily notes that need summarization
- Check API rate limit status

## Guidelines
1. When the user shares a URL, offer to summarize it
2. Extract URLs from natural language (e.g., "summarize example.com")
3. Provide concise, helpful responses
4. Show progress for long operations
5. Suggest related actions after completing tasks

## Vault Context
- Vault path: {vault_path}
- Output folder: {out_folder}
- Model: {model}
- Provider: {provider}

## Available Tools
{tool_descriptions}
```

## User Experience Examples

### Example 1: Basic Summarization
```
You: Summarize https://example.com/article
Assistant: I'll summarize that article for you...

[Fetching page...]
[Generating summary...]

✓ Created summary: article-title.md

**Summary**: This article discusses...

Would you like me to add any specific tags?
```

### Example 2: Multi-URL
```
You: Can you summarize these?
- https://example1.com
- https://example2.com
Assistant: I found 2 URLs. Let me summarize them...

[1/2] Summarizing example1.com...
✓ Created: example1-title.md

[2/2] Summarizing example2.com...
✓ Created: example2-title.md

Done! Created 2 summaries.
```

### Example 3: Search & Discovery
```
You: What summaries do I have about Python?
Assistant: [Searching vault...]

Found 5 summaries mentioning Python:

| Title | Date | Tags |
|-------|------|------|
| Python 3.12 Features | 2024-01-10 | python, programming |
| FastAPI Tutorial | 2024-01-08 | python, api, tutorial |
| ...

Would you like me to read any of these?
```

### Example 4: Daily Note Integration
```
You: Show me links from today's note
Assistant: [Reading daily note for 2024-01-15...]

Found 3 URLs in today's note:
1. https://news.site.com/article (not summarized)
2. https://blog.dev/post (already summarized)
3. https://docs.python.org/page (not summarized)

Would you like me to summarize the 2 new links?
```

### Example 5: Conversational Follow-up
```
You: Summarize this article about Rust programming
Assistant: I'd be happy to help! Could you share the URL?

You: Oh sorry, here: https://rust-lang.org/article
Assistant: [Summarizing...]

✓ Created: rust-article.md

This article covers Rust's memory safety features...

You: Can you add the tags "systems" and "programming"?
Assistant: Updated! Added tags: systems, programming
```

## Technical Considerations

### LLM Provider Integration

**Chat Mode: Azure OpenAI Only**

Chat mode uses Azure OpenAI exclusively via the Responses API:

```python
from openai import AzureOpenAI

client = AzureOpenAI(
    api_key=config.chat_azure_api_key,
    api_version="2024-12-01-preview",
    azure_endpoint=config.chat_azure_endpoint,
)

# Using Responses API for function calling
response = client.responses.create(
    model=config.chat_model,  # e.g., "gpt-4o-mini"
    input=messages,
    tools=tools,
    tool_choice="auto",
)

# Handle tool calls
if response.output:
    for item in response.output:
        if item.type == "function_call":
            # Execute tool and continue conversation
            result = execute_tool(item.name, item.arguments)
```

**Summarization: Existing Multi-Provider Support**

Summarization continues to use the existing provider system (Google/Azure/Ollama) configured separately.

| Aspect | Chat | Summarization |
|--------|------|---------------|
| Provider | Azure OpenAI only | Google, Azure, or Ollama |
| API | Responses API | Provider-specific |
| Model | `CHAT_MODEL` | `MODEL` |
| Use Case | Conversation orchestration | Content generation |

### Token Management

For multi-turn conversations:
1. Track token usage per message
2. Implement sliding window (keep recent messages)
3. Summarize old context when approaching limit
4. Context window for chat model:
   - GPT-4o-mini: 128K tokens
   - GPT-4o: 128K tokens

### Error Handling

```python
class ChatError(SummarizerError):
    """Base exception for chat operations."""
    pass

class ToolExecutionError(ChatError):
    """Error executing a tool."""
    pass

class ConversationError(ChatError):
    """Error managing conversation state."""
    pass
```

### Testing Strategy

1. **Unit tests** for each tool
2. **Integration tests** for tool chains
3. **Mock LLM responses** for conversation tests
4. **E2E tests** with real API (optional, flagged)

## Dependencies

New dependencies to add to `pyproject.toml`:

```toml
dependencies = [
    # Existing...
    "prompt-toolkit>=3.0",  # Better input handling than readline
]
```

## Configuration

New config options in `.summarizer-config.yaml`:

```yaml
# Chat configuration
chat:
  # Azure OpenAI settings for chat (separate from summarization)
  azure_endpoint: "https://your-resource.openai.azure.com"
  azure_deployment: "gpt-4o-mini"  # Chat model deployment

  # Maximum conversation history to retain
  max_history_messages: 50

  # Auto-save conversation to file
  auto_save: true
  save_path: ".chat-history.json"

  # Streaming output (word-by-word)
  streaming: true

  # Require confirmation before executing tools
  confirm_tools: false

  # Custom system prompt additions
  system_prompt_extra: |
    Additional context for my vault...
```

Environment variables:
```bash
# Chat-specific Azure settings (can differ from summarization)
CHAT_AZURE_API_KEY=your-chat-api-key
CHAT_AZURE_ENDPOINT=https://your-resource.openai.azure.com
CHAT_MODEL=gpt-4o-mini
CHAT_AZURE_DEPLOYMENT=gpt-4o-mini

# Falls back to existing Azure settings if not specified
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
```

## Milestones & Timeline

### Milestone 1: MVP (Phase 1)
- [x] Chat command with basic REPL
- [x] Single URL summarization via chat
- [x] Basic tool framework
- [x] Rich output formatting

### Milestone 2: Full Chat (Phase 2) ✓
- [x] Multi-turn conversation
- [x] All core tools implemented
- [x] Session persistence
- [x] Streaming responses

### Milestone 3: Polish (Phase 3)
- [ ] Slash commands
- [ ] Smart URL detection
- [ ] Batch operations
- [ ] Full test coverage

## Open Questions

1. **Session persistence format**: JSON vs SQLite?
2. ~~**Multi-model chat**: Allow different models for chat vs summarization?~~ → **Decided: Yes, separate models**
3. **Offline mode**: Cache for when API is unavailable?
4. **Voice input**: Future consideration for voice commands?
5. **Shared Azure credentials**: Should chat reuse summarization Azure config or require separate?

## Related Work

- [Gemini CLI](https://github.com/google-gemini/gemini-cli) - Google's chat CLI
- [GitHub Copilot CLI](https://githubnext.com/projects/copilot-cli/) - Natural language shell
- [llm CLI](https://github.com/simonw/llm) - Simon Willison's LLM CLI tool
- [aider](https://github.com/paul-gauthier/aider) - AI pair programming in terminal

## Next Steps

1. ~~Review and approve this plan~~ ✓
2. ~~Create Phase 1 implementation issues~~ ✓
3. ~~Begin with `commands/chat.py` scaffold~~ ✓
4. ~~Implement basic tool framework~~ ✓
5. ~~Add first tool: `summarize_url`~~ ✓
6. **Phase 1b: Migrate to Azure OpenAI Responses API**
   - Create `chat/azure_client.py`
   - Refactor `chat/engine.py` to use Azure client
   - Add chat-specific configuration
   - Update tests
