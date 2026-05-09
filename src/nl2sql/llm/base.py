"""LLMClient ABC and a deterministic mock for testing."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from ..types import LLMResponse, Message, TokenUsage, ToolCall, ToolDef


class LLMClient(ABC):
    """Provider-agnostic chat interface used by the agent loop."""

    model: str

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        *,
        max_tokens: int = 4096,
        system: Optional[str] = None,
    ) -> LLMResponse: ...


class MockLLMClient(LLMClient):
    """Replay a scripted series of responses, in order.

    Each response in ``responses`` is either:
    - a callable taking ``(messages, tools)`` and returning an ``LLMResponse``, or
    - an ``LLMResponse``, or
    - a dict with ``text``, ``tool_calls`` (list of ``{name, arguments}``),
      ``stop_reason``.

    On exhaustion, raises ``IndexError``.
    """

    model = "mock"

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls: list[tuple[list[Message], list[ToolDef]]] = []

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        *,
        max_tokens: int = 4096,
        system: Optional[str] = None,
    ) -> LLMResponse:
        self.calls.append((list(messages), list(tools)))
        if not self._responses:
            raise IndexError("MockLLMClient exhausted: no more scripted responses.")
        nxt = self._responses.pop(0)
        if callable(nxt):
            resp = nxt(messages, tools)
        elif isinstance(nxt, LLMResponse):
            resp = nxt
        elif isinstance(nxt, dict):
            calls = []
            for c in nxt.get("tool_calls", []):
                calls.append(
                    ToolCall(
                        id=c.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                        name=c["name"],
                        arguments=c.get("arguments", {}),
                    )
                )
            stop_reason = nxt.get("stop_reason") or (
                "tool_use" if calls else "end_turn"
            )
            resp = LLMResponse(
                text=nxt.get("text", ""),
                tool_calls=calls,
                stop_reason=stop_reason,
                usage=TokenUsage(
                    input_tokens=nxt.get("input_tokens", 0),
                    output_tokens=nxt.get("output_tokens", 0),
                ),
            )
        else:  # pragma: no cover
            raise TypeError(f"Unrecognised mock response: {type(nxt)}")
        return resp


# Convenience factory used in tests
def scripted(*items: dict) -> MockLLMClient:
    return MockLLMClient(list(items))
