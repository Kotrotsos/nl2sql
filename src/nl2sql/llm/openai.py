"""OpenAI adapter (Chat Completions tool calling)."""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Optional

from ..exceptions import LLMError
from ..types import LLMResponse, Message, TokenUsage, ToolCall, ToolDef
from .base import LLMClient


class OpenAIClient(LLMClient):
    def __init__(
        self,
        model: str = "gpt-5",
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        client: Any = None,
    ):
        self.model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self._client = client

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            import openai
        except ImportError as e:
            raise LLMError(
                "openai is required. Install with `pip install nl2sql[openai]`."
            ) from e
        if not self._api_key:
            raise LLMError(
                "OpenAI API key missing. Set OPENAI_API_KEY or pass api_key=."
            )
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = openai.OpenAI(**kwargs)
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
        oai_messages = self._to_openai_messages(messages, system=system)
        oai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": oai_messages,
            }
            if oai_tools:
                kwargs["tools"] = oai_tools
            # Some models don't accept max_tokens; tolerate either field.
            kwargs["max_completion_tokens"] = max_tokens
            resp = client.chat.completions.create(**kwargs)
        except TypeError:
            kwargs.pop("max_completion_tokens", None)
            kwargs["max_tokens"] = max_tokens
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as e:
                raise LLMError(f"OpenAI call failed: {e}") from e
        except Exception as e:
            raise LLMError(f"OpenAI call failed: {e}") from e

        choice = resp.choices[0]
        msg = choice.message
        text = msg.content or ""
        tool_calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(
                ToolCall(
                    id=tc.id or f"call_{uuid.uuid4().hex[:8]}",
                    name=tc.function.name,
                    arguments=args,
                )
            )
        finish = choice.finish_reason or "stop"
        stop_reason = "tool_use" if tool_calls else (
            "end_turn" if finish in ("stop", "end_turn") else
            ("max_tokens" if finish == "length" else "end_turn")
        )
        usage = TokenUsage(
            input_tokens=getattr(resp.usage, "prompt_tokens", 0) if resp.usage else 0,
            output_tokens=getattr(resp.usage, "completion_tokens", 0)
            if resp.usage
            else 0,
        )
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage,
            raw=resp,
        )

    @staticmethod
    def _to_openai_messages(
        messages: list[Message], *, system: Optional[str] = None
    ) -> list[dict]:
        out: list[dict] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            if m.role == "user":
                if isinstance(m.content, str):
                    out.append({"role": "user", "content": m.content})
                else:
                    out.append({"role": "user", "content": json.dumps(m.content, default=str)})
            elif m.role == "assistant":
                c = m.content
                if isinstance(c, dict):
                    msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": c.get("text") or None,
                    }
                    tcs = []
                    for tc in c.get("tool_calls", []):
                        tcs.append(
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(
                                        tc.get("arguments", {}), default=str
                                    ),
                                },
                            }
                        )
                    if tcs:
                        msg["tool_calls"] = tcs
                    out.append(msg)
                else:
                    out.append({"role": "assistant", "content": str(c)})
            elif m.role == "tool":
                c = m.content if isinstance(m.content, list) else [m.content]
                for entry in c:
                    payload = entry["content"]
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": entry["tool_use_id"],
                            "content": payload
                            if isinstance(payload, str)
                            else json.dumps(payload, default=str),
                        }
                    )
        return out
