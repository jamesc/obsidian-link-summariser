"""
Configuration management for the Obsidian Link Summarizer.

This module handles loading configuration from multiple sources:
1. Environment variables (highest priority)
2. Vault-specific YAML config file
3. Default values (lowest priority)

Environment variables take precedence over YAML config to allow
easy overrides and secure API key management.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from dotenv import load_dotenv

from summarize_links.exceptions import ConfigError

if TYPE_CHECKING:
    from summarize_links.rate_limiter import ModelRateLimits

__all__ = [
    # Configuration class
    "Config",
    # Configuration loaders
    "load_config",
    "load_yaml_config",
    "setup_logging",
    # Constants - providers
    "PROVIDER_GOOGLE",
    "PROVIDER_OLLAMA",
    "PROVIDER_AZURE",
    "VALID_PROVIDERS",
    # Constants - defaults
    "DEFAULT_MODEL",
    "DEFAULT_OUT_FOLDER",
    "DEFAULT_MAX_LINKS",
    "DEFAULT_DAILY_NOTES_FOLDER",
    "DEFAULT_MAX_TAGS",
    "CONFIG_FILENAME",
    # Constants - limits
    "MAX_CONTENT_LENGTH",
    "MAX_SLUG_LENGTH",
    "REQUEST_TIMEOUT",
    # Constants - Gemini rate limits
    "GEMINI_RPM_LIMIT",
    "GEMINI_TPM_LIMIT",
    "GEMINI_DAILY_LIMIT",
    "DEFAULT_MODEL_LIMITS",
    "FALLBACK_MODEL_LIMITS",
    "FALLBACK_AZURE_MODEL_LIMITS",
    # Constants - Ollama
    "DEFAULT_OLLAMA_ENDPOINT",
    "OLLAMA_TIMEOUT",
    # Constants - Azure
    "DEFAULT_AZURE_API_VERSION",
    "AZURE_RPM_LIMIT",
    "AZURE_TPM_LIMIT",
    "AZURE_DAILY_LIMIT",
    # Functions
    "get_model_rate_limits",
]

# Configure module logger
logger = logging.getLogger(__name__)

# ----- Provider Constants -----
# These define the valid LLM providers that can be used
PROVIDER_GOOGLE = "google"
PROVIDER_OLLAMA = "ollama"
PROVIDER_AZURE = "azure"
VALID_PROVIDERS = {PROVIDER_GOOGLE, PROVIDER_OLLAMA, PROVIDER_AZURE}

# ----- Constants -----
# These define default values and filenames used throughout the application

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_OUT_FOLDER = "Summaries"
DEFAULT_MAX_LINKS = 10
DEFAULT_DAILY_NOTES_FOLDER = ""  # Root of vault by default
CONFIG_FILENAME = ".summarizer-config.yaml"

# Content processing limits
MAX_CONTENT_LENGTH = 50_000  # Maximum characters to send to Gemini
MAX_SLUG_LENGTH = 50  # Maximum length for filename slugs
REQUEST_TIMEOUT = 10  # HTTP request timeout in seconds
DEFAULT_MAX_TAGS = 10  # Maximum tags in frontmatter

# Gemini API rate limits (free tier) - legacy constants for backward compatibility
GEMINI_RPM_LIMIT = 5  # Requests per minute
GEMINI_TPM_LIMIT = 250000  # Tokens per minute (peak)
GEMINI_DAILY_LIMIT = 20  # Requests per day

# Ollama configuration
DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
OLLAMA_TIMEOUT = 120  # Seconds (local models can be slower)

# Azure / Microsoft Foundry configuration
DEFAULT_AZURE_API_VERSION = "2024-02-15-preview"
AZURE_RPM_LIMIT = 100  # Requests per minute (varies by tier)
AZURE_TPM_LIMIT = 90000  # Tokens per minute (varies by tier)
# Note: Azure OpenAI has NO daily request limits - only RPM/TPM limits.
# The daily_limit values below are set high (1M) to effectively disable
# daily limiting for Azure models while preserving RPM/TPM enforcement.
AZURE_DAILY_LIMIT = 1_000_000  # Effectively unlimited (Azure has no daily limits)

# Default rate limits per model (actual API limits before safety margin)
# These are the raw API limits - the rate limiter applies a 10% safety margin
# Note: Actual limits vary by usage tier (Free/Tier 1-3) and can be checked
# in Google AI Studio. These are defaults for the free tier.
# See: https://ai.google.dev/gemini-api/docs/rate-limits
DEFAULT_MODEL_LIMITS: dict[str, dict[str, int]] = {
    # Gemini 3 models (free tier limits from AI Studio)
    "gemini-3-flash": {
        "rpm_limit": 5,
        "tpm_limit": 250000,
        "daily_limit": 20,
    },
    # Gemini 2.5 models (free tier limits from AI Studio)
    "gemini-2.5-flash": {
        "rpm_limit": 5,
        "tpm_limit": 250000,
        "daily_limit": 20,
    },
    "gemini-2.5-flash-lite": {
        "rpm_limit": 10,
        "tpm_limit": 250000,
        "daily_limit": 20,
    },
    # Azure / OpenAI models (standard tier limits)
    # Note: Azure has NO daily limits - only RPM/TPM. daily_limit=1M effectively disables it.
    # RPM/TPM values are for Default tier. Enterprise tiers have much higher limits.
    # See: https://learn.microsoft.com/en-us/azure/ai-services/openai/quotas-limits
    "gpt-4": {
        "rpm_limit": 100,
        "tpm_limit": 90000,
        "daily_limit": 1_000_000,  # Azure has no daily limit
    },
    "gpt-4-turbo": {
        "rpm_limit": 60,
        "tpm_limit": 80000,
        "daily_limit": 1_000_000,  # Azure has no daily limit
    },
    "gpt-4o": {
        "rpm_limit": 2700,  # Default tier: 450K TPM / 6 RPM per 1K TPM
        "tpm_limit": 450000,
        "daily_limit": 1_000_000,  # Azure has no daily limit
    },
    "gpt-4o-mini": {
        "rpm_limit": 12000,  # Default tier: 2M TPM
        "tpm_limit": 2_000_000,
        "daily_limit": 1_000_000,  # Azure has no daily limit
    },
    "gpt-35-turbo": {
        "rpm_limit": 350,
        "tpm_limit": 90000,
        "daily_limit": 1_000_000,  # Azure has no daily limit
    },
    # GPT-4.1 series (Azure deployment - various naming conventions)
    # Default tier: 5M TPM, 5K RPM for gpt-4.1-mini Global Standard
    "gpt-4.1": {
        "rpm_limit": 1000,  # Default tier
        "tpm_limit": 1_000_000,
        "daily_limit": 1_000_000,  # Azure has no daily limit
    },
    "gpt-4.1-mini": {
        "rpm_limit": 5000,  # Default tier: 5M TPM, 5K RPM
        "tpm_limit": 5_000_000,
        "daily_limit": 1_000_000,  # Azure has no daily limit
    },
    "gpt-41-mini": {
        "rpm_limit": 5000,
        "tpm_limit": 5_000_000,
        "daily_limit": 1_000_000,  # Azure has no daily limit
    },
    "gpt4.1-mini": {
        "rpm_limit": 5000,
        "tpm_limit": 5_000_000,
        "daily_limit": 1_000_000,  # Azure has no daily limit
    },
    "gpt-4.1-nano": {
        "rpm_limit": 5000,  # Default tier: 5M TPM, 5K RPM
        "tpm_limit": 5_000_000,
        "daily_limit": 1_000_000,  # Azure has no daily limit
    },
}

# Fallback limits for unknown models (conservative)
# Note: Used for Gemini/other models. For Azure/OpenAI models, see _is_azure_model().
FALLBACK_MODEL_LIMITS: dict[str, int] = {
    "rpm_limit": 2,
    "tpm_limit": 32000,
    "daily_limit": 20,
}

# Fallback limits for unknown Azure/OpenAI models
# Azure has no daily limits, so we set a high value to effectively disable it.
FALLBACK_AZURE_MODEL_LIMITS: dict[str, int] = {
    "rpm_limit": 100,
    "tpm_limit": 100000,
    "daily_limit": 1_000_000,  # Azure has no daily limit
}


def _is_azure_model(model: str) -> bool:
    """
    Check if a model name appears to be an Azure/OpenAI model.

    Args:
        model: Model name to check.

    Returns:
        True if the model name suggests it's an Azure/OpenAI model.
    """
    model_lower = model.lower()
    azure_prefixes = ("gpt-", "gpt4", "o1", "o3", "o4", "text-embedding", "dall-e")
    return any(model_lower.startswith(prefix) for prefix in azure_prefixes)


def get_model_rate_limits(
    model: str,
    yaml_model_limits: dict[str, dict[str, int]] | None = None,
) -> ModelRateLimits:
    """
    Get rate limits for a specific model.

    Looks up limits in this order:
    1. YAML config model_limits (if provided)
    2. DEFAULT_MODEL_LIMITS
    3. Azure-specific fallback (for gpt-* and o-series models)
    4. FALLBACK_MODEL_LIMITS (for other unknown models)

    Args:
        model: Model name (e.g., "gemini-2.5-flash").
        yaml_model_limits: Optional model limits from YAML config.

    Returns:
        ModelRateLimits instance with the appropriate limits.
    """
    # Import here to avoid circular import
    from summarize_links.rate_limiter import ModelRateLimits

    # Check YAML config first
    if yaml_model_limits and model in yaml_model_limits:
        limits_dict = yaml_model_limits[model]
        logger.debug("Using YAML config limits for model '%s'", model)
        return ModelRateLimits(
            rpm_limit=limits_dict.get("rpm_limit", FALLBACK_MODEL_LIMITS["rpm_limit"]),
            tpm_limit=limits_dict.get("tpm_limit", FALLBACK_MODEL_LIMITS["tpm_limit"]),
            daily_limit=limits_dict.get("daily_limit", FALLBACK_MODEL_LIMITS["daily_limit"]),
        )

    # Check default model limits
    if model in DEFAULT_MODEL_LIMITS:
        limits_dict = DEFAULT_MODEL_LIMITS[model]
        logger.debug("Using default limits for model '%s'", model)
        return ModelRateLimits(
            rpm_limit=limits_dict["rpm_limit"],
            tpm_limit=limits_dict["tpm_limit"],
            daily_limit=limits_dict["daily_limit"],
        )

    # For Azure/OpenAI models not in defaults, use Azure-specific fallback
    # (Azure has no daily limits, so we use a high value)
    if _is_azure_model(model):
        logger.info(
            "Unknown Azure/OpenAI model '%s', using Azure fallback limits: "
            "RPM=%d, TPM=%d, Daily=unlimited",
            model,
            FALLBACK_AZURE_MODEL_LIMITS["rpm_limit"],
            FALLBACK_AZURE_MODEL_LIMITS["tpm_limit"],
        )
        return ModelRateLimits(
            rpm_limit=FALLBACK_AZURE_MODEL_LIMITS["rpm_limit"],
            tpm_limit=FALLBACK_AZURE_MODEL_LIMITS["tpm_limit"],
            daily_limit=FALLBACK_AZURE_MODEL_LIMITS["daily_limit"],
        )

    # Fallback for other unknown models (e.g., Gemini variants)
    logger.warning(
        "Unknown model '%s', using conservative fallback limits: RPM=%d, TPM=%d, Daily=%d",
        model,
        FALLBACK_MODEL_LIMITS["rpm_limit"],
        FALLBACK_MODEL_LIMITS["tpm_limit"],
        FALLBACK_MODEL_LIMITS["daily_limit"],
    )
    return ModelRateLimits(
        rpm_limit=FALLBACK_MODEL_LIMITS["rpm_limit"],
        tpm_limit=FALLBACK_MODEL_LIMITS["tpm_limit"],
        daily_limit=FALLBACK_MODEL_LIMITS["daily_limit"],
    )


@dataclass
class Config:
    """
    Application configuration container.

    Holds all configuration values needed by the application, loaded from
    environment variables and/or YAML config file.

    Attributes:
        model_provider: LLM provider to use (google, ollama, azure) - REQUIRED
        gemini_api_key: Google AI Studio API key (required for google provider)
        model: Model to use for summarization
        vault_path: Path to the Obsidian vault
        out_folder: Folder name for summary notes (relative to vault)
        max_links: Maximum number of URLs to process in one run
        daily_notes_folder: Folder containing daily notes (relative to vault)
        dry_run: If True, show what would happen without making changes
        verbose: If True, enable debug logging
        force: If True, overwrite existing summaries
        default_tags: Tags to add to all summary notes
        max_tags: Maximum number of tags to include in frontmatter
        ollama_endpoint: Ollama server endpoint URL
        azure_api_key: Azure API key (required for azure provider)
        azure_endpoint: Azure endpoint URL (required for azure provider)
        azure_api_version: Azure API version
        azure_deployment_name: Azure deployment name (optional, defaults to model)
        rpm_limit: API requests per minute limit (legacy, per-model preferred)
        tpm_limit: API tokens per minute limit (legacy, per-model preferred)
        daily_limit: API requests per day limit (legacy, per-model preferred)
        model_limits: Per-model rate limit configuration from YAML
        langfuse_public_key: Langfuse public API key (required)
        langfuse_secret_key: Langfuse secret API key (required)
        langfuse_base_url: Langfuse server URL
        playwright_enabled: Enable Playwright fallback for bot-blocked requests
        playwright_timeout: Timeout in seconds for Playwright operations
        playwright_browser: Browser to use (chromium, firefox, webkit)
    """

    model_provider: str = ""  # Required: google, ollama, azure
    gemini_api_key: str = ""
    model: str = DEFAULT_MODEL
    vault_path: Path | None = None
    out_folder: str = DEFAULT_OUT_FOLDER
    max_links: int = DEFAULT_MAX_LINKS
    daily_notes_folder: str = DEFAULT_DAILY_NOTES_FOLDER
    dry_run: bool = False
    verbose: bool = False
    force: bool = False
    default_tags: list[str] | None = None
    max_tags: int = DEFAULT_MAX_TAGS
    ollama_endpoint: str = DEFAULT_OLLAMA_ENDPOINT
    # Azure fields - required when model_provider="azure", validated in validate()
    azure_api_key: str = ""
    azure_endpoint: str = ""
    azure_api_version: str = DEFAULT_AZURE_API_VERSION
    azure_deployment_name: str = ""
    rpm_limit: int = GEMINI_RPM_LIMIT
    tpm_limit: int = GEMINI_TPM_LIMIT
    daily_limit: int = GEMINI_DAILY_LIMIT
    model_limits: dict[str, dict[str, int]] | None = None
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    # Playwright fallback configuration
    playwright_enabled: bool = True
    playwright_timeout: int = 30
    playwright_browser: str = "chromium"
    # Chat mode configuration (uses Azure OpenAI Responses API exclusively)
    # Note: Responses API uses /openai/v1/ endpoint without api-version parameter
    chat_model: str = "gpt-4.1-mini"
    chat_azure_endpoint: str = ""
    chat_azure_api_key: str = ""
    chat_azure_deployment: str = ""
    # Chat session configuration
    chat_max_history_messages: int = 50
    chat_max_context_tokens: int = 100000  # Leave room for response
    chat_auto_save: bool = False
    chat_save_path: str = ".chat-history.json"
    chat_streaming: bool = True
    chat_confirm_tools: bool = False

    def validate(self) -> None:
        """
        Validate the configuration.

        Raises:
            ConfigError: If required configuration is missing or invalid.
        """
        # Provider is required
        if not self.model_provider:
            raise ConfigError(
                f"MODEL_PROVIDER is required. Set to one of: {', '.join(sorted(VALID_PROVIDERS))}"
            )

        if self.model_provider not in VALID_PROVIDERS:
            raise ConfigError(
                f"Invalid MODEL_PROVIDER: {self.model_provider}. "
                f"Valid options: {', '.join(sorted(VALID_PROVIDERS))}"
            )

        # Provider-specific validation
        if self.model_provider == PROVIDER_GOOGLE and not self.gemini_api_key:
            raise ConfigError(
                "GEMINI_API_KEY is required when MODEL_PROVIDER=google. "
                "Get one at https://aistudio.google.com/apikey"
            )

        if self.model_provider == PROVIDER_AZURE:
            if not self.azure_api_key:
                raise ConfigError("AZURE_API_KEY is required when MODEL_PROVIDER=azure.")
            if not self.azure_endpoint:
                raise ConfigError("AZURE_ENDPOINT is required when MODEL_PROVIDER=azure.")

        # Vault path must be set and exist
        if self.vault_path is None:
            raise ConfigError("Vault path is required. Use --vault or set DEFAULT_VAULT_PATH.")

        if not self.vault_path.exists():
            raise ConfigError(f"Vault path does not exist: {self.vault_path}")

        if not self.vault_path.is_dir():
            raise ConfigError(f"Vault path is not a directory: {self.vault_path}")

        # Max links must be positive
        if self.max_links < 1:
            raise ConfigError(f"max_links must be at least 1, got {self.max_links}")

        # Langfuse credentials are required
        if not self.langfuse_public_key or not self.langfuse_secret_key:
            raise ConfigError(
                "Langfuse credentials are required. Set LANGFUSE_PUBLIC_KEY and "
                "LANGFUSE_SECRET_KEY environment variables or configure in YAML."
            )

        logger.debug(
            "Configuration validated successfully (provider: %s, model: %s)",
            self.model_provider,
            self.model,
        )


def load_yaml_config(vault_path: Path) -> dict[str, Any]:
    """
    Load configuration from vault-specific YAML file.

    Args:
        vault_path: Path to the Obsidian vault root.

    Returns:
        Dictionary of configuration values, or empty dict if file doesn't exist.

    Raises:
        ConfigError: If the YAML file exists but cannot be parsed.
    """
    config_file = vault_path / CONFIG_FILENAME

    if not config_file.exists():
        logger.debug(f"No config file found at {config_file}")
        return {}

    logger.debug(f"Loading config from {config_file}")

    try:
        with open(config_file, encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
            # Handle empty file case
            return config_data if config_data else {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse {config_file}: {e}") from e


def load_config(
    vault_path: Path | str | None = None,
    model: str | None = None,
    provider: str | None = None,
    out_folder: str | None = None,
    max_links: int | None = None,
    dry_run: bool = False,
    verbose: bool = False,
    force: bool = False,
) -> Config:
    """
    Load configuration from all sources and merge them.

    Priority order (highest to lowest):
    1. Function arguments (CLI flags)
    2. Environment variables
    3. Vault YAML config file
    4. Default values

    Args:
        vault_path: Path to Obsidian vault (CLI override).
        model: Model name (CLI override).
        provider: LLM provider (CLI override): google, ollama, azure.
        out_folder: Output folder name (CLI override).
        max_links: Maximum links to process (CLI override).
        dry_run: Show what would happen without changes.
        verbose: Enable debug logging.
        force: Overwrite existing summaries.

    Returns:
        Populated Config object.

    Raises:
        ConfigError: If configuration is invalid.
    """
    # Load environment variables from .env file
    load_dotenv()

    # Start with defaults
    config = Config(
        dry_run=dry_run,
        verbose=verbose,
        force=force,
    )

    # Provider selection: CLI arg > env var > YAML > error
    if provider:
        config.model_provider = provider
    elif os.getenv("MODEL_PROVIDER"):
        config.model_provider = os.getenv("MODEL_PROVIDER", "")

    # Load API keys from environment
    config.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    config.azure_api_key = os.getenv("AZURE_API_KEY", "")
    config.azure_endpoint = os.getenv("AZURE_ENDPOINT", "")
    config.azure_api_version = os.getenv("AZURE_API_VERSION", DEFAULT_AZURE_API_VERSION)
    config.azure_deployment_name = os.getenv("AZURE_DEPLOYMENT_NAME", "")

    # Resolve vault path: CLI arg > env var > None
    resolved_vault_path: Path | None = None
    if vault_path:
        resolved_vault_path = Path(vault_path).expanduser().resolve()
    elif os.getenv("DEFAULT_VAULT_PATH"):
        resolved_vault_path = Path(os.getenv("DEFAULT_VAULT_PATH", "")).expanduser().resolve()

    config.vault_path = resolved_vault_path

    # Load YAML config if vault path is available
    yaml_config: dict[str, Any] = {}
    if resolved_vault_path and resolved_vault_path.exists():
        yaml_config = load_yaml_config(resolved_vault_path)

    # Provider from YAML (if not already set)
    if not config.model_provider and "model_provider" in yaml_config:
        config.model_provider = yaml_config["model_provider"]

    # Merge: CLI args > env vars > YAML config > defaults
    # Model selection
    # Priority: CLI arg > MODEL env > YAML > default
    if model:
        config.model = model
    elif os.getenv("MODEL"):
        config.model = os.getenv("MODEL", DEFAULT_MODEL)
    elif "summary_model" in yaml_config:
        config.model = yaml_config["summary_model"]

    # Output folder
    if out_folder:
        config.out_folder = out_folder
    elif "out_folder" in yaml_config:
        config.out_folder = yaml_config["out_folder"]

    # Max links
    if max_links is not None:
        config.max_links = max_links
    elif "max_links" in yaml_config:
        config.max_links = int(yaml_config["max_links"])

    # Daily notes folder (YAML only, no CLI/env override)
    if "daily_notes_folder" in yaml_config:
        config.daily_notes_folder = yaml_config["daily_notes_folder"]

    # Default tags (YAML only)
    if "default_tags" in yaml_config:
        tags = yaml_config["default_tags"]
        if isinstance(tags, list):
            config.default_tags = [str(t) for t in tags]
        elif isinstance(tags, str):
            config.default_tags = [tags]

    # Max tags (YAML only)
    if "max_tags" in yaml_config:
        config.max_tags = int(yaml_config["max_tags"])

    # Ollama endpoint (env var > YAML > default)
    if os.getenv("OLLAMA_ENDPOINT"):
        config.ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", DEFAULT_OLLAMA_ENDPOINT)
    elif "ollama_endpoint" in yaml_config:
        config.ollama_endpoint = yaml_config["ollama_endpoint"]

    # Azure configuration from YAML (env vars already loaded above)
    azure_yaml = yaml_config.get("azure", {})
    if not config.azure_endpoint and azure_yaml.get("endpoint"):
        config.azure_endpoint = azure_yaml["endpoint"]
    if not config.azure_deployment_name and azure_yaml.get("deployment_name"):
        config.azure_deployment_name = azure_yaml["deployment_name"]
    if azure_yaml.get("api_version"):
        config.azure_api_version = azure_yaml["api_version"]

    # Per-model rate limits (YAML only)
    if "model_limits" in yaml_config:
        model_limits = yaml_config["model_limits"]
        if isinstance(model_limits, dict):
            config.model_limits = model_limits
            logger.debug("Loaded per-model rate limits from YAML config")

    # Rate limits (YAML and env vars) - legacy global limits
    if os.getenv("GEMINI_RPM_LIMIT"):
        config.rpm_limit = int(os.getenv("GEMINI_RPM_LIMIT", str(GEMINI_RPM_LIMIT)))
    elif "rpm_limit" in yaml_config:
        config.rpm_limit = int(yaml_config["rpm_limit"])

    if os.getenv("GEMINI_TPM_LIMIT"):
        config.tpm_limit = int(os.getenv("GEMINI_TPM_LIMIT", str(GEMINI_TPM_LIMIT)))
    elif "tpm_limit" in yaml_config:
        config.tpm_limit = int(yaml_config["tpm_limit"])

    if os.getenv("GEMINI_DAILY_LIMIT"):
        config.daily_limit = int(os.getenv("GEMINI_DAILY_LIMIT", str(GEMINI_DAILY_LIMIT)))
    elif "daily_limit" in yaml_config:
        config.daily_limit = int(yaml_config["daily_limit"])

    # Langfuse configuration (env vars > YAML > defaults) - REQUIRED
    if os.getenv("LANGFUSE_PUBLIC_KEY"):
        config.langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    elif yaml_config.get("langfuse", {}).get("public_key"):
        config.langfuse_public_key = yaml_config["langfuse"]["public_key"]

    if os.getenv("LANGFUSE_SECRET_KEY"):
        config.langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    elif yaml_config.get("langfuse", {}).get("secret_key"):
        config.langfuse_secret_key = yaml_config["langfuse"]["secret_key"]

    if os.getenv("LANGFUSE_BASE_URL"):
        config.langfuse_base_url = os.getenv("LANGFUSE_BASE_URL", config.langfuse_base_url)
    elif yaml_config.get("langfuse", {}).get("base_url"):
        config.langfuse_base_url = yaml_config["langfuse"]["base_url"]

    # Playwright configuration (env vars > YAML > defaults)
    if os.getenv("PLAYWRIGHT_ENABLED"):
        config.playwright_enabled = os.getenv("PLAYWRIGHT_ENABLED", "").lower() in (
            "true",
            "1",
            "yes",
        )
    elif "playwright_enabled" in yaml_config:
        config.playwright_enabled = bool(yaml_config["playwright_enabled"])

    if os.getenv("PLAYWRIGHT_TIMEOUT"):
        config.playwright_timeout = int(os.getenv("PLAYWRIGHT_TIMEOUT", "30"))
    elif "playwright_timeout" in yaml_config:
        config.playwright_timeout = int(yaml_config["playwright_timeout"])

    if os.getenv("PLAYWRIGHT_BROWSER"):
        config.playwright_browser = os.getenv("PLAYWRIGHT_BROWSER", "chromium")
    elif "playwright_browser" in yaml_config:
        config.playwright_browser = yaml_config["playwright_browser"]

    # Chat mode configuration (env vars > YAML > defaults)
    # Chat uses Azure OpenAI exclusively with a separate model/deployment
    if os.getenv("CHAT_MODEL"):
        config.chat_model = os.getenv("CHAT_MODEL", "gpt-4.1-mini")
    elif yaml_config.get("chat", {}).get("model"):
        config.chat_model = yaml_config["chat"]["model"]

    if os.getenv("CHAT_AZURE_ENDPOINT"):
        config.chat_azure_endpoint = os.getenv("CHAT_AZURE_ENDPOINT", "")
    elif yaml_config.get("chat", {}).get("azure_endpoint"):
        config.chat_azure_endpoint = yaml_config["chat"]["azure_endpoint"]
    # Fall back to main Azure endpoint if chat-specific not set
    if not config.chat_azure_endpoint:
        config.chat_azure_endpoint = config.azure_endpoint

    if os.getenv("CHAT_AZURE_API_KEY"):
        config.chat_azure_api_key = os.getenv("CHAT_AZURE_API_KEY", "")
    elif yaml_config.get("chat", {}).get("azure_api_key"):
        config.chat_azure_api_key = yaml_config["chat"]["azure_api_key"]
    # Fall back to main Azure API key if chat-specific not set
    if not config.chat_azure_api_key:
        config.chat_azure_api_key = config.azure_api_key

    if os.getenv("CHAT_AZURE_DEPLOYMENT"):
        config.chat_azure_deployment = os.getenv("CHAT_AZURE_DEPLOYMENT", "")
    elif yaml_config.get("chat", {}).get("azure_deployment"):
        config.chat_azure_deployment = yaml_config["chat"]["azure_deployment"]
    # Fall back to chat_model if deployment not set
    if not config.chat_azure_deployment:
        config.chat_azure_deployment = config.chat_model

    # Chat session configuration (env vars > YAML > defaults)
    chat_yaml = yaml_config.get("chat", {})

    if os.getenv("CHAT_MAX_HISTORY_MESSAGES"):
        config.chat_max_history_messages = int(os.getenv("CHAT_MAX_HISTORY_MESSAGES", "50"))
    elif "max_history_messages" in chat_yaml:
        config.chat_max_history_messages = int(chat_yaml["max_history_messages"])

    if os.getenv("CHAT_MAX_CONTEXT_TOKENS"):
        config.chat_max_context_tokens = int(os.getenv("CHAT_MAX_CONTEXT_TOKENS", "100000"))
    elif "max_context_tokens" in chat_yaml:
        config.chat_max_context_tokens = int(chat_yaml["max_context_tokens"])

    if os.getenv("CHAT_AUTO_SAVE"):
        config.chat_auto_save = os.getenv("CHAT_AUTO_SAVE", "").lower() in ("true", "1", "yes")
    elif "auto_save" in chat_yaml:
        config.chat_auto_save = bool(chat_yaml["auto_save"])

    if os.getenv("CHAT_SAVE_PATH"):
        config.chat_save_path = os.getenv("CHAT_SAVE_PATH", ".chat-history.json")
    elif "save_path" in chat_yaml:
        config.chat_save_path = chat_yaml["save_path"]

    if os.getenv("CHAT_STREAMING"):
        config.chat_streaming = os.getenv("CHAT_STREAMING", "").lower() in ("true", "1", "yes")
    elif "streaming" in chat_yaml:
        config.chat_streaming = bool(chat_yaml["streaming"])

    if os.getenv("CHAT_CONFIRM_TOOLS"):
        config.chat_confirm_tools = os.getenv("CHAT_CONFIRM_TOOLS", "").lower() in (
            "true",
            "1",
            "yes",
        )
    elif "confirm_tools" in chat_yaml:
        config.chat_confirm_tools = bool(chat_yaml["confirm_tools"])

    logger.debug(
        "Loaded config: provider=%s, model=%s, out_folder=%s",
        config.model_provider,
        config.model,
        config.out_folder,
    )

    # Validate the configuration before returning
    config.validate()

    return config


def setup_logging(verbose: bool = False) -> None:
    """
    Configure application-wide logging.

    Args:
        verbose: If True, set level to DEBUG; otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO

    # Configure root logger for the package
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Set third-party loggers to WARNING to reduce noise
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("azure").setLevel(logging.WARNING)

    logger.debug("Logging configured with level: %s", "DEBUG" if verbose else "INFO")
