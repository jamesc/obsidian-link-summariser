"""
LLM client integrations with a consistent interface.

This subpackage provides a unified interface for interacting with different
LLM providers (Google Gemini, Ollama, Azure/Microsoft Foundry) through the
SummarizerProtocol.

Key components:
- protocol: SummarizerProtocol interface definition
- gemini: Google Gemini API client
- ollama: Ollama local model client
- azure: Azure / Microsoft Foundry client
- factory: Client creation based on explicit provider selection

Usage:
    from summarize_links.llm import create_llm_client, SummarizerProtocol

    client = create_llm_client(
        model="gemini-2.5-flash",
        provider="google",
        gemini_api_key="...",
    )
    result = client.summarize_with_metadata(content, url, title)
"""

# Protocol interface
# Factory
# Client implementations
from summarize_links.llm.azure import AzureClient
from summarize_links.llm.factory import create_llm_client, validate_provider
from summarize_links.llm.gemini import GeminiClient
from summarize_links.llm.ollama import OllamaClient
from summarize_links.llm.protocol import SummarizerProtocol

__all__ = [
    # Protocol
    "SummarizerProtocol",
    # Clients
    "AzureClient",
    "GeminiClient",
    "OllamaClient",
    # Factory
    "create_llm_client",
    "validate_provider",
]
