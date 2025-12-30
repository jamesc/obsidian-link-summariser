"""
LLM client integrations with a consistent interface.

This subpackage provides a unified interface for interacting with different
LLM providers (Google Gemini, Ollama, etc.) through the SummarizerProtocol.

Key components:
- protocol: SummarizerProtocol interface definition
- gemini: Google Gemini API client
- ollama: Ollama local model client
- factory: Automatic client creation based on model name

Usage:
    from summarize_links.llm import create_llm_client, SummarizerProtocol
    
    client = create_llm_client(model="gemini-2.5-flash", gemini_api_key="...")
    result = client.summarize_with_metadata(content, url, title)
"""

# Protocol interface
from summarize_links.llm.protocol import SummarizerProtocol

# Client implementations
from summarize_links.llm.gemini import GeminiClient, MockGeminiClient
from summarize_links.llm.ollama import OllamaClient

# Factory
from summarize_links.llm.factory import create_llm_client, detect_provider

__all__ = [
    # Protocol
    "SummarizerProtocol",
    # Clients
    "GeminiClient",
    "MockGeminiClient",
    "OllamaClient",
    # Factory
    "create_llm_client",
    "detect_provider",
]
