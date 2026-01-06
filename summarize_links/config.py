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
    # Constants - Ollama
    "DEFAULT_OLLAMA_ENDPOINT",
    "OLLAMA_TIMEOUT",
    # Functions
    "get_model_rate_limits",
]

# Configure module logger
logger = logging.getLogger(__name__)

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
}

# Fallback limits for unknown models (conservative)
FALLBACK_MODEL_LIMITS: dict[str, int] = {
    "rpm_limit": 2,
    "tpm_limit": 32000,
    "daily_limit": 20,
}


def get_model_rate_limits(
    model: str,
    yaml_model_limits: dict[str, dict[str, int]] | None = None,
) -> ModelRateLimits:
    """
    Get rate limits for a specific model.

    Looks up limits in this order:
    1. YAML config model_limits (if provided)
    2. DEFAULT_MODEL_LIMITS
    3. FALLBACK_MODEL_LIMITS (for unknown models)

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

    # Fallback for unknown models
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
        gemini_api_key: Google AI Studio API key (required for Gemini models)
        model: Model to use for summarization (auto-detects provider)
        vault_path: Path to the Obsidian vault
        out_folder: Folder name for summary notes (relative to vault)
        max_links: Maximum number of URLs to process in one run
        daily_notes_folder: Folder containing daily notes (relative to vault)
        mock_mode: If True, use mock summarizer instead of real API
        dry_run: If True, show what would happen without making changes
        verbose: If True, enable debug logging
        force: If True, overwrite existing summaries
        default_tags: Tags to add to all summary notes
        max_tags: Maximum number of tags to include in frontmatter
        ollama_endpoint: Ollama server endpoint URL
        rpm_limit: Gemini API requests per minute limit (legacy, per-model preferred)
        tpm_limit: Gemini API tokens per minute limit (legacy, per-model preferred)
        daily_limit: Gemini API requests per day limit (legacy, per-model preferred)
        model_limits: Per-model rate limit configuration from YAML
        langfuse_public_key: Langfuse public API key (required)
        langfuse_secret_key: Langfuse secret API key (required)
        langfuse_base_url: Langfuse server URL
    """

    gemini_api_key: str = ""
    model: str = DEFAULT_MODEL
    vault_path: Path | None = None
    out_folder: str = DEFAULT_OUT_FOLDER
    max_links: int = DEFAULT_MAX_LINKS
    daily_notes_folder: str = DEFAULT_DAILY_NOTES_FOLDER
    mock_mode: bool = False
    dry_run: bool = False
    verbose: bool = False
    force: bool = False
    default_tags: list[str] | None = None
    max_tags: int = DEFAULT_MAX_TAGS
    ollama_endpoint: str = DEFAULT_OLLAMA_ENDPOINT
    rpm_limit: int = GEMINI_RPM_LIMIT
    tpm_limit: int = GEMINI_TPM_LIMIT
    daily_limit: int = GEMINI_DAILY_LIMIT
    model_limits: dict[str, dict[str, int]] | None = None
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"

    def validate(self) -> None:
        """
        Validate the configuration.

        Raises:
            ConfigError: If required configuration is missing or invalid.
        """
        # Detect provider from model name
        from summarize_links.llm import detect_provider

        provider = detect_provider(self.model)

        # API key is required for Gemini models (unless in mock mode)
        if not self.mock_mode and provider == "gemini" and not self.gemini_api_key:
            raise ConfigError(
                "GEMINI_API_KEY environment variable is required for Gemini models. "
                "Get one at https://aistudio.google.com/apikey"
            )

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

        # Langfuse credentials are required (not in mock mode)
        if not self.mock_mode and (not self.langfuse_public_key or not self.langfuse_secret_key):
            raise ConfigError(
                "Langfuse credentials are required. Set LANGFUSE_PUBLIC_KEY and "
                "LANGFUSE_SECRET_KEY environment variables or configure in YAML."
            )

        logger.debug("Configuration validated successfully (provider: %s)", provider)


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
    out_folder: str | None = None,
    max_links: int | None = None,
    mock_mode: bool = False,
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
        model: Gemini model name (CLI override).
        out_folder: Output folder name (CLI override).
        max_links: Maximum links to process (CLI override).
        mock_mode: Use mock summarizer.
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
        mock_mode=mock_mode,
        dry_run=dry_run,
        verbose=verbose,
        force=force,
    )

    # Load API key from environment (required)
    config.gemini_api_key = os.getenv("GEMINI_API_KEY", "")

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

    # Merge: CLI args > env vars > YAML config > defaults
    # Model selection with backward compatibility
    # Priority: CLI arg > MODEL env > GEMINI_MODEL env > YAML > default
    if model:
        config.model = model
    elif os.getenv("MODEL"):
        config.model = os.getenv("MODEL", DEFAULT_MODEL)
    elif os.getenv("GEMINI_MODEL"):
        config.model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        logger.warning("GEMINI_MODEL is deprecated, use MODEL environment variable instead")
    elif "summary_model" in yaml_config:
        config.model = yaml_config["summary_model"]
    elif "model" in yaml_config:
        # Backward compatibility: support old "model" field
        config.model = yaml_config["model"]
        logger.warning("'model' in YAML config is deprecated, use 'summary_model' instead")

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

    logger.debug(f"Loaded config: model={config.model}, out_folder={config.out_folder}")

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

    logger.debug("Logging configured with level: %s", "DEBUG" if verbose else "INFO")
