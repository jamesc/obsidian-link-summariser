"""
Configuration management for the Obsidian Link Summarizer.

This module handles loading configuration from multiple sources:
1. Environment variables (highest priority)
2. Vault-specific YAML config file
3. Default values (lowest priority)

Environment variables take precedence over YAML config to allow
easy overrides and secure API key management.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from summarize_links.exceptions import ConfigError

# Configure module logger
logger = logging.getLogger(__name__)

# ----- Constants -----
# These define default values and filenames used throughout the application

DEFAULT_MODEL = "gemini-2.0-flash-exp"
DEFAULT_OUT_FOLDER = "Summaries"
DEFAULT_MAX_LINKS = 10
DEFAULT_DAILY_NOTES_FOLDER = ""  # Root of vault by default
CONFIG_FILENAME = ".summarizer-config.yaml"

# Content processing limits
MAX_CONTENT_LENGTH = 50000  # Maximum characters to send to Gemini
MAX_SLUG_LENGTH = 50  # Maximum length for filename slugs
REQUEST_TIMEOUT = 10  # HTTP request timeout in seconds

# Gemini API rate limits (free tier)
GEMINI_RPM_LIMIT = 10  # Requests per minute
GEMINI_TPM_LIMIT = 250000  # Tokens per minute (peak)
GEMINI_DAILY_LIMIT = 500  # Requests per day


@dataclass
class Config:
    """
    Application configuration container.

    Holds all configuration values needed by the application, loaded from
    environment variables and/or YAML config file.

    Attributes:
        gemini_api_key: Google AI Studio API key (required for non-mock mode)
        model: Gemini model to use for summarization
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
    max_tags: int = 10

    def validate(self) -> None:
        """
        Validate the configuration.

        Raises:
            ConfigError: If required configuration is missing or invalid.
        """
        # API key is required unless in mock mode
        if not self.mock_mode and not self.gemini_api_key:
            raise ConfigError(
                "GEMINI_API_KEY environment variable is required. "
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

        logger.debug("Configuration validated successfully")


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
    # Model
    if model:
        config.model = model
    elif os.getenv("GEMINI_MODEL"):
        config.model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    elif "model" in yaml_config:
        config.model = yaml_config["model"]

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

    logger.debug(f"Loaded config: model={config.model}, out_folder={config.out_folder}")

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

    logger.debug("Logging configured with level: %s", "DEBUG" if verbose else "INFO")
