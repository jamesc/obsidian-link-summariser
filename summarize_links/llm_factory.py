"""
Factory for creating LLM clients based on model name.

Automatically detects provider (Ollama vs Gemini) and returns
the appropriate client implementation.
"""

import logging
from pathlib import Path

from summarize_links.gemini_client import GeminiClient, MockGeminiClient, SummarizerProtocol
from summarize_links.ollama_client import DEFAULT_OLLAMA_ENDPOINT, OllamaClient

__all__ = [
    "detect_provider",
    "create_llm_client",
    "OLLAMA_MODEL_PREFIXES",
]

# Module logger
logger = logging.getLogger(__name__)

# Known Ollama model prefixes
OLLAMA_MODEL_PREFIXES = [
    "llama",
    "mistral",
    "phi",
    "qwen",
    "gemma",
    "codellama",
    "mixtral",
    "neural-chat",
    "starling",
    "orca",
    "vicuna",
    "wizardlm",
    "yi",
    "solar",
    "deepseek",
    "openchat",
    "nous",
    "zephyr",
    "orca2",
    "dolphin",
]


def detect_provider(model: str) -> str:
    """
    Detect which provider to use based on model name.

    Ollama models are detected by:
    1. Presence of ":" character (Ollama tag notation, e.g., "llama3:latest")
    2. Known Ollama model name prefixes

    Otherwise, defaults to Gemini.

    Args:
        model: Model name/identifier.

    Returns:
        "ollama" or "gemini"
    """
    # Ollama models typically use : for tags (e.g., llama3:latest)
    if ":" in model:
        logger.debug("Detected Ollama model by ':' character: %s", model)
        return "ollama"

    # Check against known Ollama model prefixes
    model_lower = model.lower()
    for prefix in OLLAMA_MODEL_PREFIXES:
        if model_lower.startswith(prefix):
            logger.debug("Detected Ollama model by prefix '%s': %s", prefix, model)
            return "ollama"

    # Default to Gemini
    logger.debug("Detected Gemini model (default): %s", model)
    return "gemini"


def create_llm_client(
    model: str,
    gemini_api_key: str | None = None,
    ollama_endpoint: str | None = None,
    mock_mode: bool = False,
    state_path: Path | None = None,
    **kwargs,
) -> SummarizerProtocol:
    """
    Create appropriate LLM client based on model name.

    Automatically detects the provider from the model name and
    instantiates the correct client implementation.

    Args:
        model: Model identifier (auto-detects provider).
        gemini_api_key: API key for Gemini (required for Gemini models).
        ollama_endpoint: Ollama server endpoint (defaults to localhost).
        mock_mode: Use mock client for testing.
        state_path: Path for rate limiter state (Gemini only).
        **kwargs: Additional provider-specific arguments.

    Returns:
        Configured client implementing SummarizerProtocol.

    Raises:
        ConfigError: If required configuration is missing.
    """
    from summarize_links.exceptions import ConfigError

    if mock_mode:
        logger.info("Creating MockGeminiClient (mock mode enabled)")
        return MockGeminiClient(model=model)

    provider = detect_provider(model)

    if provider == "ollama":
        logger.info("Creating OllamaClient for model: %s", model)
        endpoint = ollama_endpoint or DEFAULT_OLLAMA_ENDPOINT
        return OllamaClient(
            model=model,
            endpoint=endpoint,
        )
    else:  # gemini
        if not gemini_api_key:
            raise ConfigError(
                "GEMINI_API_KEY required for Gemini models. "
                "Get one at https://aistudio.google.com/apikey"
            )

        logger.info("Creating GeminiClient for model: %s", model)
        return GeminiClient(
            api_key=gemini_api_key,
            model=model,
            state_path=state_path,
            **kwargs,
        )
