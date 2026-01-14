"""
Factory for creating LLM clients based on provider selection.

Uses explicit MODEL_PROVIDER configuration to route to the
appropriate client implementation (Google, Ollama, or Azure).
"""

import logging
from pathlib import Path
from typing import Any

from summarize_links.config import (
    DEFAULT_AZURE_API_VERSION,
    DEFAULT_OLLAMA_ENDPOINT,
    PROVIDER_AZURE,
    PROVIDER_OLLAMA,
    VALID_PROVIDERS,
)
from summarize_links.llm.protocol import SummarizerProtocol

__all__ = [
    "validate_provider",
    "create_llm_client",
]

# Module logger
logger = logging.getLogger(__name__)


def validate_provider(provider: str) -> str:
    """
    Validate the provider setting.

    Args:
        provider: Provider from MODEL_PROVIDER env var or config.

    Returns:
        Validated provider string (lowercase): "google", "ollama", or "azure"

    Raises:
        ConfigError: If provider is missing or invalid.
    """
    from summarize_links.exceptions import ConfigError

    if not provider:
        raise ConfigError(
            f"MODEL_PROVIDER is required. Set to one of: {', '.join(sorted(VALID_PROVIDERS))}"
        )

    # Normalize to lowercase for case-insensitive matching
    normalized = provider.lower()

    if normalized not in VALID_PROVIDERS:
        raise ConfigError(
            f"Invalid provider: {provider}. Valid options: {', '.join(sorted(VALID_PROVIDERS))}"
        )

    logger.debug("Using provider: %s", normalized)
    return normalized


def create_llm_client(
    model: str,
    provider: str | None = None,
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
    """
    Create appropriate LLM client based on provider.

    Routes to the correct client implementation based on the
    explicit provider setting.

    Args:
        model: Model identifier.
        provider: LLM provider (google, ollama, azure) - REQUIRED.
        gemini_api_key: API key for Google Gemini.
        ollama_endpoint: Ollama server endpoint.
        azure_api_key: API key for Azure.
        azure_endpoint: Azure endpoint URL.
        azure_deployment_name: Azure deployment name (defaults to model).
        azure_api_version: Azure API version.
        mock_mode: Use mock client for testing.
        state_path: Path for rate limiter state.
        **kwargs: Additional provider-specific arguments.

    Returns:
        Configured client implementing SummarizerProtocol.

    Raises:
        ConfigError: If required configuration is missing.
    """
    from summarize_links.exceptions import ConfigError
    from summarize_links.llm.gemini import GeminiClient, MockGeminiClient

    if mock_mode:
        logger.info("Creating MockGeminiClient (mock mode enabled)")
        return MockGeminiClient(model=model)

    # Provider is required when not in mock mode
    if not provider:
        raise ConfigError(
            "MODEL_PROVIDER is required. "
            "Set MODEL_PROVIDER environment variable to: google, ollama, or azure"
        )

    validated_provider = validate_provider(provider)

    if validated_provider == PROVIDER_OLLAMA:
        from summarize_links.llm.ollama import OllamaClient

        logger.info("Creating OllamaClient for model: %s", model)
        endpoint = ollama_endpoint or DEFAULT_OLLAMA_ENDPOINT
        return OllamaClient(
            model=model,
            endpoint=endpoint,
        )

    elif validated_provider == PROVIDER_AZURE:
        from summarize_links.llm.azure import AzureClient

        if not azure_api_key:
            raise ConfigError("AZURE_API_KEY is required when MODEL_PROVIDER=azure.")
        if not azure_endpoint:
            raise ConfigError("AZURE_ENDPOINT is required when MODEL_PROVIDER=azure.")

        # deployment_name defaults to model if not provided
        deployment = azure_deployment_name if azure_deployment_name else model
        logger.info("Creating AzureClient for model: %s, deployment: %s", model, deployment)
        return AzureClient(
            api_key=azure_api_key,
            endpoint=azure_endpoint,
            model=model,
            deployment_name=deployment,
            api_version=azure_api_version or DEFAULT_AZURE_API_VERSION,
            state_path=state_path,
            **kwargs,
        )

    else:  # google
        if not gemini_api_key:
            raise ConfigError(
                "GEMINI_API_KEY is required when MODEL_PROVIDER=google. "
                "Get one at https://aistudio.google.com/apikey"
            )

        logger.info("Creating GeminiClient for model: %s", model)
        return GeminiClient(
            api_key=gemini_api_key,
            model=model,
            state_path=state_path,
            **kwargs,
        )
