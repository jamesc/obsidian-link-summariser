"""
Unit tests for the LLM factory.

Tests cover provider detection logic and client creation.
"""

from typing import Any

import pytest

from summarize_links.exceptions import ConfigError
from summarize_links.gemini_client import GeminiClient, MockGeminiClient
from summarize_links.llm_factory import OLLAMA_MODEL_PREFIXES, create_llm_client, detect_provider
from summarize_links.ollama_client import OllamaClient


class TestDetectProvider:
    """Tests for detect_provider function."""

    def test_detect_ollama_with_colon(self) -> None:
        """Test detection of Ollama models by ':' character."""
        assert detect_provider("llama3:latest") == "ollama"
        assert detect_provider("mistral:7b") == "ollama"
        assert detect_provider("phi3:mini") == "ollama"

    def test_detect_ollama_by_prefix(self) -> None:
        """Test detection of Ollama models by known prefixes."""
        for prefix in ["llama", "mistral", "phi", "qwen", "gemma"]:
            assert detect_provider(prefix) == "ollama"
            assert detect_provider(f"{prefix}3") == "ollama"
            assert detect_provider(f"{prefix.upper()}") == "ollama"

    def test_detect_gemini_by_prefix(self) -> None:
        """Test detection of Gemini models by 'gemini-' prefix."""
        assert detect_provider("gemini-2.5-flash") == "gemini"
        assert detect_provider("gemini-3-flash") == "gemini"
        assert detect_provider("gemini-1.5-pro") == "gemini"

    def test_detect_gemini_prefix_overrides_colon(self) -> None:
        """Test that gemini- prefix takes priority over : character."""
        # Even if someone weirdly adds a colon, gemini- prefix wins
        assert detect_provider("gemini-1.5:custom") == "gemini"

    def test_detect_unknown_model_raises_error(self) -> None:
        """Test that unknown models raise ConfigError."""
        with pytest.raises(ConfigError, match="Unable to determine provider"):
            detect_provider("unknown-model")
        with pytest.raises(ConfigError, match="Unable to determine provider"):
            detect_provider("some-other-model")

    def test_all_ollama_prefixes_detected(self) -> None:
        """Test that all known Ollama prefixes are detected."""
        for prefix in OLLAMA_MODEL_PREFIXES:
            assert detect_provider(prefix) == "ollama"
            assert detect_provider(f"{prefix}2") == "ollama"


class TestCreateLLMClient:
    """Tests for create_llm_client factory function."""

    def test_create_mock_client(self) -> None:
        """Test creation of mock client."""
        client = create_llm_client(
            model="any-model",
            mock_mode=True,
        )
        assert isinstance(client, MockGeminiClient)

    def test_create_ollama_client(self) -> None:
        """Test creation of Ollama client."""
        client = create_llm_client(
            model="llama3:latest",
            ollama_endpoint="http://localhost:11434",
        )
        assert isinstance(client, OllamaClient)
        assert client._model == "llama3:latest"
        assert client._endpoint == "http://localhost:11434"

    def test_create_ollama_client_default_endpoint(self) -> None:
        """Test creation of Ollama client with default endpoint."""
        client = create_llm_client(model="mistral")
        assert isinstance(client, OllamaClient)
        assert client._endpoint == "http://localhost:11434"

    def test_create_gemini_client(self) -> None:
        """Test creation of Gemini client."""
        client = create_llm_client(
            model="gemini-2.5-flash",
            gemini_api_key="test-key",
        )
        assert isinstance(client, GeminiClient)
        assert client._model_name == "gemini-2.5-flash"

    def test_create_gemini_client_missing_api_key(self) -> None:
        """Test creation of Gemini client without API key raises error."""
        with pytest.raises(ConfigError, match="GEMINI_API_KEY required"):
            create_llm_client(model="gemini-2.5-flash")

    def test_create_gemini_client_with_state_path(self, tmp_path: Any) -> None:
        """Test creation of Gemini client with state path."""
        client = create_llm_client(
            model="gemini-2.5-flash",
            gemini_api_key="test-key",
            state_path=tmp_path,
        )
        assert isinstance(client, GeminiClient)

    def test_create_gemini_client_with_rate_limits(self) -> None:
        """Test creation of Gemini client with custom rate limits."""
        client = create_llm_client(
            model="gemini-2.5-flash",
            gemini_api_key="test-key",
            rpm_limit=10,
            tpm_limit=500000,
            daily_limit=50,
        )
        assert isinstance(client, GeminiClient)
