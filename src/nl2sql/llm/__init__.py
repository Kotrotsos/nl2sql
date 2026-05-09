"""LLM provider adapters."""
from .base import LLMClient, MockLLMClient

__all__ = ["LLMClient", "MockLLMClient", "AnthropicClient", "OpenAIClient"]


def __getattr__(name: str):
    if name == "AnthropicClient":
        from .anthropic import AnthropicClient
        return AnthropicClient
    if name == "OpenAIClient":
        from .openai import OpenAIClient
        return OpenAIClient
    raise AttributeError(name)
