# Microsoft Foundry Support Specification

**Author:** GitHub Copilot
**Date:** January 14, 2026
**Status:** Specification
**Priority:** Medium

---

## 1. Overview

This specification outlines the implementation plan for adding **Microsoft Foundry** support to the Obsidian Link Summarizer. The goal is to enable users to summarize web content using OpenAI models (GPT-4, GPT-4 Turbo, GPT-4 Vision) deployed through Microsoft Foundry, in addition to existing Gemini and Ollama providers.

### Key Benefits

- **Enterprise Integration**: Leverage Microsoft's enterprise security, compliance, and governance features
- **OpenAI Models via Microsoft**: Use OpenAI's latest models through Microsoft Foundry
- **Deployment Flexibility**: Support Microsoft Foundry deployments
- **Rate Limiting**: Built-in rate limit handling for Microsoft Foundry quotas and throttling
- **Cost Control**: Predictable pricing through Microsoft's subscription model

---

## 2. Requirements

### 2.1 Functional Requirements

| Requirement | Description |
|-------------|-------------|
| **FR1** | Route to correct client based on `MODEL_PROVIDER` setting |
| **FR2** | Create `AzureFoundryClient` implementing `SummarizerProtocol` |
| **FR3** | Support Microsoft Foundry endpoints |
| **FR4** | Handle Azure SDK authentication (API key, token-based) |
| **FR5** | Parse and handle Azure rate limiting headers |
| **FR6** | Support Azure's structured output formats |
| **FR7** | Implement per-model rate limiting for Azure models |
| **FR8** | Support custom deployment names (not just model names) |

### 2.2 Non-Functional Requirements

| Requirement | Description |
|-------------|-------------|
| **NFR1** | Azure client code must follow existing code patterns and conventions |
| **NFR2** | Type hints required on all functions and methods |
| **NFR3** | Comprehensive error handling with custom exceptions |
| **NFR4** | Logging at DEBUG, INFO, WARNING, ERROR levels |
| **NFR5** | Graceful degradation on API failures (consistent with other providers) |
| **NFR6** | Unit test coverage ≥ 85% for new code |
| **NFR7** | Integration tests for factory pattern |
| **NFR8** | Configuration management via env vars and YAML |

---

## 3. Architecture

### 3.1 Provider Selection Strategy

Instead of auto-detecting providers from model names, use an explicit `MODEL_PROVIDER` environment variable. This approach:

- **Eliminates ambiguity**: Model names like "gpt-4" or "llama3" could exist on multiple providers
- **Simplifies configuration**: Users explicitly declare their intent
- **Enables flexibility**: Any model name works with any provider
- **Reduces complexity**: No heuristics or prefix detection needed

**Provider Values:**
| Value | Description |
|-------|-------------|
| `google` | Google Gemini API |
| `ollama` | Local Ollama server |
| `azure` | Microsoft Foundry |

**Required Configuration:**
- `MODEL_PROVIDER` is **required** - no auto-detection
- Simplifies codebase by removing heuristic-based detection
- Clear error message if `MODEL_PROVIDER` is not set

### 3.2 Configuration Structure

#### Environment Variables

```bash
# Provider Selection (NEW)
MODEL_PROVIDER=azure              # Options: google, ollama, azure
MODEL=gpt-4                           # Model name (provider-specific)

# Azure Authentication (required when MODEL_PROVIDER=azure)
AZURE_API_KEY=<your-api-key>
AZURE_ENDPOINT=https://<resource-name>.openai.azure.com/
AZURE_API_VERSION=2024-02-15-preview

# Alternative: Token-based authentication
AZURE_USE_TOKEN_AUTH=true
AZURE_TOKEN=<your-token>

# Azure Model Configuration
AZURE_DEPLOYMENT_NAME=gpt4-deployment # Deployment name override (optional)

# Rate Limiting (optional, defaults provided)
AZURE_RPM_LIMIT=100
AZURE_TPM_LIMIT=90000
AZURE_DAILY_LIMIT=5000

# Existing Gemini Configuration (when MODEL_PROVIDER=google)
GEMINI_API_KEY=<your-api-key>

# Existing Ollama Configuration (when MODEL_PROVIDER=ollama)
OLLAMA_ENDPOINT=http://localhost:11434
```

#### YAML Configuration (`.summarizer-config.yaml`)

```yaml
# Provider Selection (NEW)
model_provider: azure             # Options: google, ollama, azure
summary_model: gpt-4                  # Model name (provider-specific)

# Azure-specific configuration (when model_provider: azure)
azure:
  endpoint: https://<resource-name>.openai.azure.com/
  deployment_name: gpt4-deployment    # Optional: override model name
  api_version: 2024-02-15-preview

# Per-model rate limits (keyed by model name, not provider prefix)
model_limits:
  gpt-4:
    rpm_limit: 100
    tpm_limit: 90000
    daily_limit: 5000
  gpt-4-turbo:
    rpm_limit: 60
    tpm_limit: 80000
    daily_limit: 3000
  gpt-35-turbo:
    rpm_limit: 350
    tpm_limit: 90000
    daily_limit: 10000
  gemini-2.5-flash:
    rpm_limit: 5
    tpm_limit: 250000
    daily_limit: 20
```

### 3.3 Class Structure

#### `AzureFoundryClient`

```python
class AzureFoundryClient(BaseLLMClient):
    """
    Client for Microsoft Foundry.

    Supports Microsoft Foundry deployments.
    Handles authentication, request formatting, structured output,
    and rate limiting.
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model: str,
        deployment_name: str | None = None,
        api_version: str = DEFAULT_AZURE_API_VERSION,
        rate_limiter: RateLimiter | None = None,
        state_path: Path | None = None,
        model_limits: ModelRateLimits | None = None,
        yaml_model_limits: dict[str, dict[str, int]] | None = None,
        **kwargs: Any,
    ) -> None:
        ...

    def summarize(
        self,
        content: str,
        url: str,
        title: str | None = None,
    ) -> str:
        """Summarize content using Azure OpenAI API."""
        ...

    def summarize_with_metadata(
        self,
        content: str,
        url: str,
        title: str | None = None,
    ) -> SummaryResult:
        """Summarize with structured output and tags."""
        ...

    def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Make API call to Azure OpenAI endpoint."""
        ...

    def _handle_rate_limit(self, response_headers: dict) -> None:
        """Parse and handle Azure rate limit headers."""
        ...

    def _build_request_headers(self) -> dict[str, str]:
        """Build headers with API key authentication."""
        ...
```

#### Exception Classes

Add to [exceptions.py](exceptions.py):

```python
class AzureAPIError(SummarizerError):
    """Raised when Azure API call fails."""
    pass

class AzureAuthenticationError(AzureAPIError):
    """Raised when Azure authentication fails."""
    pass

class AzureRateLimitError(AzureAPIError):
    """Raised when Azure rate limit is hit (HTTP 429)."""
    pass

class AzureDeploymentError(AzureAPIError):
    """Raised when Azure deployment configuration is invalid."""
    pass
```

---

## 4. Implementation Plan

### 4.1 Phase 1: Core Implementation (Week 1)

#### 4.1.1 Configuration Updates

**File: [config.py](../summarize_links/config.py)**

- Add Azure-specific constants:
  ```python
  # Provider enum/constants
  PROVIDER_GOOGLE = "google"
  PROVIDER_OLLAMA = "ollama"
  PROVIDER_AZURE = "azure"
  VALID_PROVIDERS = {PROVIDER_GOOGLE, PROVIDER_OLLAMA, PROVIDER_AZURE}

  # Azure defaults
  DEFAULT_AZURE_API_VERSION = "2025-04-14"
  DEFAULT_AZURE_ENDPOINT = None  # Must be provided by user
  AZURE_RPM_LIMIT = 100
  AZURE_TPM_LIMIT = 90000
  AZURE_DAILY_LIMIT = 5000
  ```

- Update `DEFAULT_MODEL_LIMITS` (no provider prefix needed):
  ```python
  DEFAULT_MODEL_LIMITS: dict[str, dict[str, int]] = {
      ...
      # Azure/OpenAI models
      "gpt-4": {"rpm_limit": 100, "tpm_limit": 90000, "daily_limit": 5000},
      "gpt-4-turbo": {"rpm_limit": 60, "tpm_limit": 80000, "daily_limit": 3000},
      "gpt-35-turbo": {"rpm_limit": 350, "tpm_limit": 90000, "daily_limit": 10000},
  }
  ```

- Update `Config` dataclass to include:
  ```python
  # Provider selection (NEW)
  model_provider: str | None = None   # google, ollama, azure

  # Azure configuration
  azure_api_key: str | None = None
  azure_endpoint: str | None = None
  azure_api_version: str = DEFAULT_AZURE_API_VERSION
  azure_deployment_name: str | None = None
  azure_use_token_auth: bool = False
  azure_token: str | None = None
  ```

- Update `load_config()` to read Azure env vars and YAML config
- Update YAML loading to parse `azure:` section

#### 4.1.2 Exceptions

**File: [exceptions.py](../summarize_links/exceptions.py)**

- Add four new Azure-specific exception classes
- Update `__all__` list

#### 4.1.3 Factory Pattern

**File: [llm/factory.py](../summarize_links/llm/factory.py)**

- Replace `detect_provider()` with simple `validate_provider()`:
  ```python
  def validate_provider(provider: str) -> str:
      """
      Validate the provider setting.

      Args:
          provider: Provider from MODEL_PROVIDER env var or config.

      Returns:
          Validated provider string: "google", "ollama", or "azure"

      Raises:
          ConfigError: If provider is missing or invalid.
      """
      from summarize_links.config import VALID_PROVIDERS
      from summarize_links.exceptions import ConfigError

      if not provider:
          raise ConfigError(
              "MODEL_PROVIDER is required. "
              f"Set to one of: {', '.join(sorted(VALID_PROVIDERS))}"
          )

      if provider not in VALID_PROVIDERS:
          raise ConfigError(
              f"Invalid MODEL_PROVIDER: {provider}. "
              f"Valid options: {', '.join(sorted(VALID_PROVIDERS))}"
          )

      logger.debug("Using provider: %s", provider)
      return provider
  ```

- Remove `detect_provider()` and all legacy detection logic (OLLAMA_MODEL_PREFIXES, etc.)

- Update `create_llm_client()` signature:
  ```python
  def create_llm_client(
      model: str,
      provider: str,                        # REQUIRED: explicit provider
      gemini_api_key: str | None = None,
      ollama_endpoint: str | None = None,
      azure_api_key: str | None = None,
      azure_endpoint: str | None = None,
      azure_deployment_name: str | None = None,
      azure_api_version: str | None = None,
      mock_mode: bool = False,
      state_path: Path | None = None,
      **kwargs: Any,
  ) -> SummarizerProtocol:
      ...
      validated_provider = validate_provider(provider)

      if validated_provider == "azure":
          if not azure_api_key or not azure_endpoint:
              raise ConfigError(
                  "AZURE_API_KEY and AZURE_ENDPOINT required when MODEL_PROVIDER=azure"
              )
          return AzureFoundryClient(
              api_key=azure_api_key,
              endpoint=azure_endpoint,
              model=model,
              deployment_name=azure_deployment_name,
              api_version=azure_api_version,
              state_path=state_path,
              **kwargs,
          )
      elif resolved_provider == "ollama":
          ...
      else:  # google
          ...
**File: [llm/azure.py](../summarize_links/llm/azure.py)** (New file)

- Implement `AzureFoundryClient(BaseLLMClient)`:
  - Constructor with authentication handling
  - `summarize()` method
  - `summarize_with_metadata()` method
  - `_call_api()` helper
  - Rate limit header parsing
  - Retry logic (exponential backoff)
  - Structured output parsing

- Key Implementation Details:
  - Use `openai` Python library (official Azure SDK)
  - Support API key authentication
  - Optional token-based auth
  - Map deployment names to model names
  - Handle Azure-specific error codes
  - Parse rate limit headers: `x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`

### 4.2 Phase 2: Testing (Week 2)

#### 4.2.1 Unit Tests

**File: [tests/test_azure.py](../tests/test_azure.py)** (New file)

Test coverage areas:
- Constructor initialization and validation
- Authentication (API key, token-based)
- Successful summarization requests
- Error handling (auth, deployment, rate limits)
- Retry logic and backoff
- Rate limit header parsing
- Structured output parsing
- Edge cases (empty content, long content, special characters)

Target: ≥ 85% code coverage

#### 4.2.2 Factory Integration Tests

**File: [tests/test_llm_factory.py](../tests/test_llm_factory.py)**

- Add tests for `validate_provider()`
- Test missing provider raises `ConfigError`
- Test invalid provider raises `ConfigError`
- Test `create_llm_client()` returns `AzureFoundryClient` for `provider="azure"`
- Test `create_llm_client()` returns `GeminiClient` for `provider="google"`
- Test `create_llm_client()` returns `OllamaClient` for `provider="ollama"`
- Test error handling for missing provider-specific configuration

#### 4.2.3 Configuration Tests

**File: [tests/test_config.py](../tests/test_config.py)**

- Test loading Azure env vars
- Test loading Azure YAML config
- Test config priority (CLI args > env vars > YAML > defaults)
- Test Azure validation

### 4.3 Phase 3: Integration & Documentation (Week 3)

#### 4.3.1 Configuration File Updates

- Update `.env.example`:
  ```bash
  # Provider Selection (REQUIRED)
  MODEL_PROVIDER=google             # Options: google, ollama, azure
  MODEL=gemini-2.5-flash            # Model name (provider-specific)

  # Azure Configuration (required when MODEL_PROVIDER=azure)
  # AZURE_API_KEY=your-key-here
  # AZURE_ENDPOINT=https://your-resource.openai.azure.com/
  # AZURE_API_VERSION=2024-02-15-preview
  # AZURE_DEPLOYMENT_NAME=gpt4-deployment
  ```

- Update `.summarizer-config.yaml` example in README

#### 4.3.2 CLI Updates

**File: [cli.py](../summarize_links/cli.py)**

- Add `--provider` flag (choices: google, ollama, azure)
- Add `--azure-api-key` flag
- Add `--azure-endpoint` flag
- Add `--azure-deployment-name` flag
- Update help text with provider examples

#### 4.3.3 Documentation

- Update [README.md](../README.md):
  - Add "Microsoft Foundry Setup" section
  - Include step-by-step setup instructions
  - Document model names and deployment names
  - Show example YAML config
  - Document rate limits for different tiers

- Update [docs/spec.md](spec.md):
  - List Azure as supported provider
  - Add provider comparison table

#### 4.3.4 Linting & Static Analysis

- Run `ruff check .` and fix issues
- Run `ruff format .`
- Run `mypy .` and resolve type errors

---

## 5. API Details

### 5.1 Azure Endpoint URL Format

```
https://<resource-name>.openai.azure.com/openai/deployments/<deployment-name>/chat/completions?api-version=<version>
```

### 5.2 Authentication Headers

```
Authorization: Bearer <api-key>
Content-Type: application/json
```

### 5.3 Request/Response Format

**Request:**
```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "model": "<model-name>",
  "temperature": 0.7,
  "max_tokens": 2000,
  "response_format": {"type": "json_object"}
}
```

**Response:**
```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "gpt-4",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "{...json...}"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 200,
    "total_tokens": 350
  }
}
```

### 5.4 Rate Limit Headers

Azure returns rate limit information in response headers:

```
x-ratelimit-remaining-requests: 99
x-ratelimit-remaining-tokens: 89850
x-ratelimit-reset-requests: 60s
x-ratelimit-reset-tokens: 60s
```

---

## 6. Error Handling

### 6.1 Azure-Specific Errors

| Error Code | HTTP | Meaning | Action |
|----------|------|---------|--------|
| 401 | 401 | Invalid API key or expired token | Log error, suggest checking credentials |
| 404 | 404 | Deployment not found | Suggest checking deployment name and region |
| 429 | 429 | Rate limit exceeded | Implement backoff and rate limiting |
| 500 | 500 | Server error | Retry with backoff |
| 503 | 503 | Service unavailable | Retry with longer backoff |

### 6.2 Retry Strategy

```
Retry Logic:
1. Exponential backoff: base_delay * (2 ** attempt)
2. Max retries: 5
3. Min delay: 2 seconds
4. Max delay: 120 seconds
5. Rate limit (429): Add 10s penalty + exponential backoff

Similar to existing Gemini retry logic in GeminiClient
```

---

## 7. Testing Strategy

### 7.1 Unit Test Categories

1. **Initialization Tests**
   - Valid configuration
   - Missing required fields
   - Token vs API key authentication

2. **API Call Tests**
   - Successful request/response
   - Structured output parsing
   - Error responses (401, 404, 429, 500, 503)

3. **Rate Limiting Tests**
   - Header parsing
   - Rate limiter integration
   - Backoff behavior

4. **Content Handling Tests**
   - Empty content
   - Very long content
   - Special characters
   - Non-ASCII content

5. **Edge Cases**
   - Malformed JSON responses
   - Network timeouts
   - Partial responses

### 7.2 Mock Strategy

Use `unittest.mock.patch` to mock:
- HTTP requests (via `openai` library)
- File I/O
- Rate limiter

Example fixtures needed:
```python
@pytest.fixture
def mock_azure_config():
    return {
        "api_key": "test-key-123",
        "endpoint": "https://test.openai.azure.com/",
        "deployment_name": "gpt4-test",
        "api_version": "2024-02-15-preview"
    }

@pytest.fixture
def azure_client(mock_azure_config):
    return AzureFoundryClient(**mock_azure_config)
```

---

## 8. Dependencies

### 8.1 New Package Dependencies

```toml
# Add to pyproject.toml
openai = "^1.3.0"  # Official Azure OpenAI SDK
```

**Note**: Check if `openai` package is already installed for Gemini compatibility.

### 8.2 Version Compatibility

- Python: 3.11+ (existing requirement)
- `openai`: 1.3.0+ (latest stable)
- `requests`: Already a dependency (used by openai)

---

## 9. Migration

### 9.1 Breaking Changes

This update introduces a **breaking change**: `MODEL_PROVIDER` is now required.

### 9.2 Migration Steps

**All users must:**
1. Add `MODEL_PROVIDER` to their configuration:
   - Environment variable: `MODEL_PROVIDER=google` (or `ollama`, `azure`)
   - OR YAML config: `model_provider: google`

**Existing Gemini users:**
```bash
# Before (auto-detected)
MODEL=gemini-2.5-flash

# After (explicit)
MODEL_PROVIDER=google
MODEL=gemini-2.5-flash
```

**Existing Ollama users:**
```bash
# Before (auto-detected)
MODEL=llama3:latest

# After (explicit)
MODEL_PROVIDER=ollama
MODEL=llama3:latest
```

**New Azure users:**
```bash
MODEL_PROVIDER=azure
MODEL=gpt-4
AZURE_API_KEY=...
AZURE_ENDPOINT=...
```

---

## 10. Performance Considerations

### 10.1 Rate Limiting

Azure has different rate limits per subscription tier:

**Default/Free Tier** (estimated):
- 10 requests/minute
- 10,000 tokens/minute

**Standard/Paid Tier** (examples):
- 100 requests/minute (gpt-4)
- 90,000 tokens/minute (gpt-4)
- Varies by model and tier

**Implementation**: Use existing `RateLimiter` class with Azure-specific limits.

### 10.2 Latency

- Azure OpenAI typically responds in 0.5-3 seconds
- Network latency to Azure region: 10-100ms
- Total request time: Expected 1-5 seconds
- Similar to Gemini; faster than local Ollama

---

## 11. Security Considerations

### 11.1 API Key Management

- ✅ Keys stored in environment variables only
- ✅ Never logged or exposed in errors
- ✅ Support for token-based auth as alternative
- ✅ `.env.example` doesn't include real keys

### 11.2 Endpoint Validation

- Validate endpoint URL format
- Ensure HTTPS (not HTTP)
- Prevent directory traversal in deployment names

### 11.3 Error Messages

- Don't expose full API keys in error messages
- Mask sensitive headers
- Log safely for debugging

---

## 12. Documentation & Examples

### 12.1 README Section: "Microsoft Foundry Setup"

```markdown
## Microsoft Foundry Setup

### Prerequisites
- Microsoft Foundry subscription with model deployed
- Resource name (e.g., `my-resource`)
- Deployment name (e.g., `gpt4-deployment`)
- API key from Microsoft Foundry portal

### Configuration

1. **Environment Variables**
   ```bash
   export MODEL_PROVIDER="azure"
   export MODEL="gpt-4"
   export AZURE_API_KEY="your-key-here"
   export AZURE_ENDPOINT="https://my-resource.openai.azure.com/"
   ```

2. **Or, via YAML Config**
   ```yaml
   model_provider: azure
   summary_model: gpt-4

   azure:
     endpoint: https://my-resource.openai.azure.com/
     deployment_name: gpt4-deployment

   model_limits:
     gpt-4:
       rpm_limit: 100
       tpm_limit: 90000
   ```

3. **Run**
   ```bash
   uv run summarize-links from-note --vault ~/Notes
   ```

4. **Or, via CLI flags**
   ```bash
   uv run summarize-links from-note --vault ~/Notes \
     --provider azure \
     --model gpt-4 \
     --azure-endpoint https://my-resource.openai.azure.com/
   ```
```

### 12.2 Troubleshooting Guide

Document common issues:
- Invalid API key error
- Deployment not found
- Rate limit exceeded
- Token limits exceeded
- Wrong region/resource name

---

## 13. Success Criteria

### 13.1 Functional Criteria

- ✅ Factory routes to correct client based on `MODEL_PROVIDER`
- ✅ AzureFoundryClient successfully summarizes content
- ✅ Structured output parsing works correctly
- ✅ Rate limiting enforced per Azure quotas
- ✅ Error handling for all Azure-specific errors
- ✅ Authentication works (API key and token-based)

### 13.2 Quality Criteria

- ✅ Unit test coverage ≥ 85%
- ✅ All linting checks pass (ruff, mypy)
- ✅ Integration tests pass
- ✅ Code follows project conventions
- ✅ Documentation complete and accurate

### 13.3 Performance Criteria

- ✅ Request latency: < 10 seconds (including network)
- ✅ Rate limiting prevents API quota errors
- ✅ Graceful degradation on failures
- ✅ Exponential backoff prevents thundering herd

---

## 14. Timeline

| Phase | Tasks | Estimated Duration |
|-------|-------|-------------------|
| **Phase 1** | Config, exceptions, factory, Azure client | 5-7 days |
| **Phase 2** | Unit tests, integration tests | 3-4 days |
| **Phase 3** | Documentation, CLI updates, polish | 2-3 days |
| **Total** | | ~2 weeks |

---

## 15. Future Enhancements (Out of Scope)

1. **Azure Cognitive Search Integration**: Use Azure Search for document retrieval
2. **Azure Key Vault**: Store secrets in Azure Key Vault instead of env vars
3. **Managed Identity**: Use Azure Entra ID for authentication
4. **Azure Monitor Integration**: Track usage and costs
5. **Azure Cosmos DB**: Persist summaries in Azure database
6. **Vision Models**: Support GPT-4 Vision for image-based summaries
7. **Function Calling**: Leverage Azure Functions for processing

---

## Appendix A: API Version Timeline

| Version | Release Date | Status | Notes |
|---------|-------------|--------|-------|
| `2024-02-15-preview` | Feb 2024 | Current | Recommended for new deployments |
| `2024-02-01` | Feb 2024 | Current | Stable version |
| `2023-12-01-preview` | Dec 2023 | Legacy | Still supported |
| `2023-05-15` | May 2023 | Legacy | Older but stable |

**Recommendation**: Default to `2024-02-15-preview` for latest features.

---

## Appendix B: Model Availability by Region

Azure OpenAI model availability varies by region. Key models:

| Model | Status | Regions |
|-------|--------|---------|
| gpt-4 | Generally Available | Most regions |
| gpt-4-turbo | Generally Available | Most regions |
| gpt-35-turbo | Generally Available | All regions |
| gpt-4-vision | Preview | Limited regions |

---

## Appendix C: Reference Implementation Checklist

- [ ] Add provider constants to `config.py` (`PROVIDER_GOOGLE`, `PROVIDER_OLLAMA`, `PROVIDER_AZURE`)
- [ ] Add `VALID_PROVIDERS` set to `config.py`
- [ ] Add Azure constants to `config.py`
- [ ] Add Azure exception classes to `exceptions.py`
- [ ] Update `DEFAULT_MODEL_LIMITS` in `config.py` (no provider prefix)
- [ ] Update `Config` dataclass with `model_provider` field
- [ ] Update `load_config()` to read `MODEL_PROVIDER` env var
- [ ] Update YAML loading to parse `model_provider` field
- [ ] Create `llm/azure.py` with `AzureFoundryClient`
- [ ] Remove `detect_provider()` and `OLLAMA_MODEL_PREFIXES` from `llm/factory.py`
- [ ] Add `validate_provider()` to `llm/factory.py`
- [ ] Update `create_llm_client()` with required `provider` parameter
- [ ] Add `openai` to `pyproject.toml` dependencies
- [ ] Create `tests/test_azure.py` with comprehensive tests
- [ ] Update `tests/test_config.py` with provider config tests
- [ ] Update `tests/test_llm_factory.py` with explicit provider tests
- [ ] Update `.env.example` with `MODEL_PROVIDER` and Azure variables
- [ ] Update `cli.py` with `--provider` flag
- [ ] Update `README.md` with Azure setup section
- [ ] Update troubleshooting documentation
- [ ] Run `ruff check .` and fix issues
- [ ] Run `ruff format .`
- [ ] Run `mypy .` and resolve type errors
- [ ] Run full test suite with `pytest --cov`
- [ ] Create PR with Azure support
