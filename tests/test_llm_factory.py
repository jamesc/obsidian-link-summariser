"""
Unit tests for the LLM factory.

Tests cover provider validation and client creation.
"""

from typing import Any

import pytest

from summarize_links.config import (
    PROVIDER_AZURE,
    PROVIDER_GOOGLE,
    PROVIDER_OLLAMA,
    VALID_PROVIDERS,
)
from summarize_links.exceptions import ConfigError
from summarize_links.llm import AzureClient, GeminiClient, MockGeminiClient, OllamaClient
from summarize_links.llm.factory import create_llm_client, validate_provider


class TestValidateProvider:
    """Tests for validate_provider function."""

    def test_validate_google_provider(self) -> None:
        """Test validation of Google provider."""
        assert validate_provider(PROVIDER_GOOGLE) == PROVIDER_GOOGLE
        assert validate_provider("google") == "google"

    def test_validate_ollama_provider(self) -> None:
        """Test validation of Ollama provider."""
        assert validate_provider(PROVIDER_OLLAMA) == PROVIDER_OLLAMA
        assert validate_provider("ollama") == "ollama"

    def test_validate_azure_provider(self) -> None:
        """Test validation of Azure provider."""
        assert validate_provider(PROVIDER_AZURE) == PROVIDER_AZURE
        assert validate_provider("azure") == "azure"

    def test_validate_case_insensitive(self) -> None:
        """Test that provider validation is case-insensitive."""
        assert validate_provider("GOOGLE") == "google"
        assert validate_provider("Ollama") == "ollama"
        assert validate_provider("AZURE") == "azure"
        assert validate_provider("Azure") == "azure"

    def test_validate_unknown_provider_raises_error(self) -> None:
        """Test that unknown providers raise ConfigError."""
        with pytest.raises(ConfigError, match="Invalid provider"):
            validate_provider("unknown")
        with pytest.raises(ConfigError, match="Invalid provider"):
            validate_provider("gemini")  # Not a valid provider value
        with pytest.raises(ConfigError, match="Invalid provider"):
            validate_provider("microsoft")  # Should be 'azure'

    def test_all_valid_providers_accepted(self) -> None:
        """Test that all valid providers are accepted."""
        for provider in VALID_PROVIDERS:
            assert validate_provider(provider) == provider


class TestCreateLLMClient:
    """Tests for create_llm_client factory function."""

    def test_create_mock_client(self) -> None:
        """Test creation of mock client."""
        client = create_llm_client(
            model="any-model",
            provider="google",
            mock_mode=True,
        )
        assert isinstance(client, MockGeminiClient)

    def test_create_ollama_client(self) -> None:
        """Test creation of Ollama client."""
        client = create_llm_client(
            model="llama3:latest",
            provider="ollama",
            ollama_endpoint="http://localhost:11434",
        )
        assert isinstance(client, OllamaClient)
        assert client._model == "llama3:latest"
        assert client._endpoint == "http://localhost:11434"

    def test_create_ollama_client_default_endpoint(self) -> None:
        """Test creation of Ollama client with default endpoint."""
        client = create_llm_client(model="mistral", provider="ollama")
        assert isinstance(client, OllamaClient)
        assert client._endpoint == "http://localhost:11434"

    def test_create_gemini_client(self) -> None:
        """Test creation of Gemini client."""
        client = create_llm_client(
            model="gemini-2.5-flash",
            provider="google",
            gemini_api_key="test-key",
        )
        assert isinstance(client, GeminiClient)
        assert client._model_name == "gemini-2.5-flash"

    def test_create_gemini_client_missing_api_key(self) -> None:
        """Test creation of Gemini client without API key raises error."""
        with pytest.raises(ConfigError, match="GEMINI_API_KEY required"):
            create_llm_client(model="gemini-2.5-flash", provider="google")

    def test_create_gemini_client_with_state_path(self, tmp_path: Any) -> None:
        """Test creation of Gemini client with state path."""
        client = create_llm_client(
            model="gemini-2.5-flash",
            provider="google",
            gemini_api_key="test-key",
            state_path=tmp_path,
        )
        assert isinstance(client, GeminiClient)

    def test_create_gemini_client_with_rate_limits(self) -> None:
        """Test creation of Gemini client with custom rate limits."""
        client = create_llm_client(
            model="gemini-2.5-flash",
            provider="google",
            gemini_api_key="test-key",
            rpm_limit=10,
            tpm_limit=500000,
            daily_limit=50,
        )
        assert isinstance(client, GeminiClient)

    def test_create_azure_client(self) -> None:
        """Test creation of Azure client."""
        client = create_llm_client(
            model="gpt-4",
            provider="azure",
            azure_api_key="test-key",
            azure_endpoint="https://test.openai.azure.com",
            azure_deployment_name="my-gpt4",
        )
        assert isinstance(client, AzureClient)
        assert client._model_name == "gpt-4"
        assert client._deployment_name == "my-gpt4"

    def test_create_azure_client_missing_api_key(self) -> None:
        """Test creation of Azure client without API key raises error."""
        with pytest.raises(ConfigError, match="AZURE_API_KEY required"):
            create_llm_client(
                model="gpt-4",
                provider="azure",
                azure_endpoint="https://test.openai.azure.com",
                azure_deployment_name="my-gpt4",
            )

    def test_create_azure_client_missing_endpoint(self) -> None:
        """Test creation of Azure client without endpoint raises error."""
        with pytest.raises(ConfigError, match="AZURE_ENDPOINT required"):
            create_llm_client(
                model="gpt-4",
                provider="azure",
                azure_api_key="test-key",
                azure_deployment_name="my-gpt4",
            )

    def test_create_azure_client_missing_deployment(self) -> None:
        """Test creation of Azure client without deployment name raises error."""
        with pytest.raises(ConfigError, match="AZURE_DEPLOYMENT_NAME required"):
            create_llm_client(
                model="gpt-4",
                provider="azure",
                azure_api_key="test-key",
                azure_endpoint="https://test.openai.azure.com",
            )

    def test_missing_provider_raises_error(self) -> None:
        """Test that missing provider parameter raises error."""
        with pytest.raises(ConfigError, match="MODEL_PROVIDER is required"):
            create_llm_client(model="gpt-4")

    def test_invalid_provider_raises_error(self) -> None:
        """Test that invalid provider raises error."""
        with pytest.raises(ConfigError, match="Invalid provider"):
            create_llm_client(model="gpt-4", provider="invalid")
