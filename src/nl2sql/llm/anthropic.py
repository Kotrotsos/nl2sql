"""Anthropic adapter."""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional

from ..exceptions import LLMError
from ..types import LLMResponse, Message, TokenUsage, ToolCall, ToolDef
from .base import LLMClient


class AnthropicClient(LLMClient):
    def __init__(
        self,
        model: str = "claude-opus-4-7",
        *,
        api_key: Optional[str] = None,
        client: Any = None,
    ):
        self.model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = client

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as e:
            raise LLMError(
                "anthropic is required. Install with `pip install nl2sql[anthropic]`."
            ) from e
        if not self._api_key:
            raise LLMError(
                "Anthropic API key missing. Set ANTHROPIC_API_KEY or pass api_key=."
            )
        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        *,
        max_tokens: int = 4096,
        system: Optional[str] = None,
    ) -> LLMResponse:
        client = self._ensure_client()
        anth_messages = self._to_anthropic_messages(messages)
        anth_tools = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]
        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": anth_messages,
            }
            if system:
                kwargs["system"] = system
            if anth_tools:
                kwargs["tools"] = anth_tools
            resp = client.messages.create(**kwargs)
        except Exception as e:
            raise LLMError(f"Anthropic call failed: {e}") from e

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=getattr(block, "id", None) or f"call_{uuid.uuid4().hex[:8]}",
                        name=getattr(block, "name", "") or "",
                        arguments=dict(getattr(block, "input", {}) or {}),
                    )
                )
        stop_reason = getattr(resp, "stop_reason", "end_turn") or "end_turn"
        if stop_reason == "tool_use" and not tool_calls:
            stop_reason = "end_turn"

        usage = TokenUsage(
            input_tokens=getattr(resp.usage, "input_tokens", 0) if resp.usage else 0,
            output_tokens=getattr(resp.usage, "output_tokens", 0) if resp.usage else 0,
        )
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
            raw=resp,
        )

    @staticmethod
    def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
        """Translate normalised Message list to Anthropic format.

        Our normalised history uses:
        - role=user, content=str  → user text
        - role=assistant, content=LLMResponse-shaped dict (text + tool_calls)
        - role=tool, content=dict {tool_use_id, content}  → user message wrapping tool_result
        """
        out: list[dict] = []
        for m in messages:
            if m.role == "user":
                if isinstance(m.content, str):
                    out.append({"role": "user", "content": m.content})
                else:
                    out.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                # Re-emit assistant turn as Anthropic blocks.
                blocks: list[dict] = []
                c = m.content
                if isinstance(c, dict):
                    if c.get("text"):
                        blocks.append({"type": "text", "text": c["text"]})
                    for tc in c.get("tool_calls", []):
                        blocks.append(
                            {
                                "type": "tool_use",
                                "id": tc["id"],
                                "name": tc["name"],
                                "input": tc.get("arguments", {}),
                            }
                        )
                else:
                    blocks.append({"type": "text", "text": str(c)})
                out.append({"role": "assistant", "content": blocks})
            elif m.role == "tool":
                # Tool results go back as a user message with tool_result blocks.
                c = m.content if isinstance(m.content, list) else [m.content]
                blocks = []
                for entry in c:
                    blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": entry["tool_use_id"],
                            "content": entry["content"]
                            if isinstance(entry["content"], str)
                            else json.dumps(entry["content"], default=str),
                            **(
                                {"is_error": True}
                                if entry.get("is_error")
                                else {}
                            ),
                        }
                    )
                out.append({"role": "user", "content": blocks})
        return out
