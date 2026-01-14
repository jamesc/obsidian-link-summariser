"""
Unit tests for the Ollama client.

Tests cover client initialization, server connectivity, model validation,
and summarization functionality with various response formats.
"""

import json
from typing import Any
from unittest.mock import patch

import pytest
import requests

from summarize_links.exceptions import ModelNotInstalledError, OllamaAPIError, OllamaServerError
from summarize_links.llm.ollama import OllamaClient, _parse_ollama_response
from summarize_links.models import SummaryResult


class TestOllamaClient:
    """Tests for OllamaClient."""

    def test_init(self) -> None:
        """Test client initialization."""
        client = OllamaClient(model="llama3:latest")
        assert client._model_name == "llama3:latest"
        assert client._endpoint == "http://localhost:11434"
        assert client._timeout == 120

    def test_init_custom_endpoint(self) -> None:
        """Test client initialization with custom endpoint."""
        client = OllamaClient(
            model="mistral",
            endpoint="http://custom-server:8080",
            timeout=60,
        )
        assert client._model_name == "mistral"
        assert client._endpoint == "http://custom-server:8080"
        assert client._timeout == 60

    @patch("summarize_links.llm.ollama.requests.get")
    def test_check_server_success(self, mock_get: Any) -> None:
        """Test successful server connectivity check."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"models": []}

        client = OllamaClient(model="llama3")
        client._check_server()  # Should not raise

        assert client._server_checked is True
        mock_get.assert_called_once()

    @patch("summarize_links.llm.ollama.requests.get")
    def test_check_server_connection_error(self, mock_get: Any) -> None:
        """Test server check with connection error."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        client = OllamaClient(model="llama3")
        with pytest.raises(OllamaServerError, match="Cannot connect to Ollama server"):
            client._check_server()

    @patch("summarize_links.llm.ollama.requests.get")
    def test_check_server_timeout(self, mock_get: Any) -> None:
        """Test server check with timeout."""
        mock_get.side_effect = requests.exceptions.Timeout("Timeout")

        client = OllamaClient(model="llama3")
        with pytest.raises(OllamaServerError, match="timed out"):
            client._check_server()

    @patch("summarize_links.llm.ollama.requests.get")
    def test_check_model_installed_success(self, mock_get: Any) -> None:
        """Test successful model installation check."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "models": [
                {"name": "llama3:latest"},
                {"name": "mistral"},
            ]
        }

        client = OllamaClient(model="llama3:latest")
        client._check_model_installed()  # Should not raise

        assert client._model_checked is True

    @patch("summarize_links.llm.ollama.requests.get")
    def test_check_model_not_installed(self, mock_get: Any) -> None:
        """Test model check when model is not installed."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "models": [
                {"name": "mistral"},
            ]
        }

        client = OllamaClient(model="llama3:latest")
        with pytest.raises(ModelNotInstalledError, match="not installed"):
            client._check_model_installed()

    @patch("summarize_links.llm.ollama.requests.post")
    @patch("summarize_links.llm.ollama.requests.get")
    def test_summarize_success(self, mock_get: Any, mock_post: Any) -> None:
        """Test successful summarization."""
        # Mock server and model checks
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"models": [{"name": "llama3"}]}

        # Mock API response
        mock_post.return_value.status_code = 200
        response_json = {
            "summary": "Test summary",
            "suggested_tags": ["test"],
            "content_type": "article",
        }
        mock_post.return_value.json.return_value = {
            "model": "llama3",
            "response": json.dumps(response_json),
            "done": True,
        }

        client = OllamaClient(model="llama3")
        result = client.summarize("Test content", "https://example.com", "Test Title")

        assert '"summary": "Test summary"' in result
        assert client._server_checked is True
        assert client._model_checked is True

    @patch("summarize_links.llm.ollama.requests.post")
    @patch("summarize_links.llm.ollama.requests.get")
    def test_summarize_timeout(self, mock_get: Any, mock_post: Any) -> None:
        """Test summarization with timeout."""
        # Mock server and model checks
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"models": [{"name": "llama3"}]}

        # Mock timeout
        mock_post.side_effect = requests.exceptions.Timeout("Timeout")

        client = OllamaClient(model="llama3")
        with pytest.raises(OllamaAPIError, match="timed out"):
            client.summarize("Test content", "https://example.com")

    @patch("summarize_links.llm.ollama.requests.post")
    @patch("summarize_links.llm.ollama.requests.get")
    def test_summarize_empty_response(self, mock_get: Any, mock_post: Any) -> None:
        """Test summarization with empty response."""
        # Mock server and model checks
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"models": [{"name": "llama3"}]}

        # Mock empty response
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "model": "llama3",
            "response": "",
            "done": True,
        }

        client = OllamaClient(model="llama3")
        with pytest.raises(OllamaAPIError, match="Empty response"):
            client.summarize("Test content", "https://example.com")

    @patch("summarize_links.llm.ollama.requests.post")
    @patch("summarize_links.llm.ollama.requests.get")
    def test_summarize_with_metadata(self, mock_get: Any, mock_post: Any) -> None:
        """Test summarization with structured metadata."""
        # Mock server and model checks
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"models": [{"name": "llama3"}]}

        # Mock API response with structured JSON and token usage
        response_json = {
            "summary": "# Test Summary\n\nThis is a test.",
            "suggested_tags": ["test", "example"],
            "content_type": "tutorial",
        }
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "model": "llama3",
            "response": json.dumps(response_json),
            "done": True,
            "prompt_eval_count": 150,
            "eval_count": 75,
        }

        client = OllamaClient(model="llama3")
        result = client.summarize_with_metadata("Test content", "https://example.com", "Test Title")

        assert isinstance(result, SummaryResult)
        assert result.content == "# Test Summary\n\nThis is a test."
        assert result.suggested_tags == ["test", "example"]
        assert result.content_type == "tutorial"
        assert result.usage_details == {"input": 150, "output": 75, "total": 225}


class TestParseOllamaResponse:
    """Tests for _parse_ollama_response function."""

    def test_parse_clean_json(self) -> None:
        """Test parsing clean JSON response."""
        response = '{"summary": "Test", "suggested_tags": ["tag1"], "content_type": "article"}'
        result = _parse_ollama_response(response)

        assert result.content == "Test"
        assert result.suggested_tags == ["tag1"]
        assert result.content_type == "article"

    def test_parse_json_in_markdown(self) -> None:
        """Test parsing JSON wrapped in markdown code block."""
        response = """```json
{
  "summary": "Test summary",
  "suggested_tags": ["test"],
  "content_type": "blog"
}
```"""
        result = _parse_ollama_response(response)

        assert result.content == "Test summary"
        assert result.suggested_tags == ["test"]
        assert result.content_type == "blog"

    def test_parse_malformed_json(self) -> None:
        """Test parsing malformed JSON (fallback to raw text)."""
        response = "This is not valid JSON but should still work"
        result = _parse_ollama_response(response)

        # Should fall back to using raw text as summary
        assert result.content == response
        assert result.suggested_tags == []
        assert result.content_type == "article"
