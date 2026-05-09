"""LLM adapter translation tests using fake provider clients."""
from __future__ import annotations

from typing import Any

import pytest

from nl2sql.llm.anthropic import AnthropicClient
from nl2sql.llm.openai import OpenAIClient
from nl2sql.types import Message, ToolDef


class FakeAnthropicBlock:
    def __init__(self, *, type, text=None, id=None, name=None, input=None):
        self.type = type
        self.text = text
        self.id = id
        self.name = name
        self.input = input


class FakeAnthropicResponse:
    def __init__(self, content, stop_reason="end_turn", usage=None):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage


class FakeAnthropicUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeAnthropicClient:
    def __init__(self, response):
        self.messages = self
        self._response = response
        self.last_kwargs: dict[str, Any] = {}

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class TestAnthropicAdapter:
    def test_text_only_response(self):
        fake = FakeAnthropicClient(
            FakeAnthropicResponse(
                content=[FakeAnthropicBlock(type="text", text="Hi.")],
                stop_reason="end_turn",
                usage=FakeAnthropicUsage(10, 5),
            )
        )
        client = AnthropicClient(client=fake, api_key="k")
        resp = client.chat(
            [Message(role="user", content="Hello")],
            tools=[],
            system="You are helpful.",
        )
        assert resp.text == "Hi."
        assert resp.tool_calls == []
        assert resp.stop_reason == "end_turn"
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5
        assert fake.last_kwargs["system"] == "You are helpful."

    def test_tool_use_response(self):
        fake = FakeAnthropicClient(
            FakeAnthropicResponse(
                content=[
                    FakeAnthropicBlock(type="text", text="thinking..."),
                    FakeAnthropicBlock(
                        type="tool_use",
                        id="tu_1",
                        name="get_db_table_list",
                        input={},
                    ),
                ],
                stop_reason="tool_use",
                usage=FakeAnthropicUsage(20, 8),
            )
        )
        client = AnthropicClient(client=fake, api_key="k")
        resp = client.chat(
            [Message(role="user", content="Q")],
            tools=[
                ToolDef(
                    name="get_db_table_list",
                    description="list tables",
                    input_schema={"type": "object", "properties": {}},
                )
            ],
        )
        assert resp.stop_reason == "tool_use"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_db_table_list"
        # Tools should be sent to the API
        assert fake.last_kwargs["tools"][0]["name"] == "get_db_table_list"

    def test_history_round_trip(self):
        fake = FakeAnthropicClient(
            FakeAnthropicResponse(
                content=[FakeAnthropicBlock(type="text", text="ok")],
                stop_reason="end_turn",
                usage=FakeAnthropicUsage(0, 0),
            )
        )
        client = AnthropicClient(client=fake, api_key="k")
        client.chat(
            messages=[
                Message(role="user", content="Q"),
                Message(
                    role="assistant",
                    content={
                        "text": "looking",
                        "tool_calls": [
                            {"id": "tu_1", "name": "get_db_table_list", "arguments": {}}
                        ],
                    },
                ),
                Message(
                    role="tool",
                    content=[{"tool_use_id": "tu_1", "content": "customers"}],
                ),
            ],
            tools=[],
        )
        msgs = fake.last_kwargs["messages"]
        # Expect 3 messages: user, assistant (with tool_use), user (tool_result).
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["role"] == "user"
        # Last message contains a tool_result block with the right id.
        block = msgs[2]["content"][0]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "tu_1"


# OpenAI adapter -------------------------------------------------------------


class FakeOpenAIFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeOpenAIToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = FakeOpenAIFunction(name, arguments)


class FakeOpenAIMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeOpenAIChoice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason


class FakeOpenAIUsage:
    def __init__(self, prompt_tokens, completion_tokens):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeOpenAIResponse:
    def __init__(self, choices, usage):
        self.choices = choices
        self.usage = usage


class FakeOpenAIChatCompletions:
    def __init__(self, response):
        self._response = response
        self.last_kwargs: dict = {}

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._response


class FakeOpenAIChat:
    def __init__(self, response):
        self.completions = FakeOpenAIChatCompletions(response)


class FakeOpenAIClient:
    def __init__(self, response):
        self.chat = FakeOpenAIChat(response)


class TestOpenAIAdapter:
    def test_text_only(self):
        fake = FakeOpenAIClient(
            FakeOpenAIResponse(
                choices=[
                    FakeOpenAIChoice(
                        FakeOpenAIMessage(content="Hi.", tool_calls=[]),
                        finish_reason="stop",
                    )
                ],
                usage=FakeOpenAIUsage(10, 5),
            )
        )
        client = OpenAIClient(client=fake, api_key="k")
        resp = client.chat(
            messages=[Message(role="user", content="Hello")],
            tools=[],
            system="You are helpful.",
        )
        assert resp.text == "Hi."
        assert resp.stop_reason == "end_turn"
        # System message is the first message
        first = fake.chat.completions.last_kwargs["messages"][0]
        assert first["role"] == "system"
        assert first["content"] == "You are helpful."

    def test_tool_call_translation(self):
        fake = FakeOpenAIClient(
            FakeOpenAIResponse(
                choices=[
                    FakeOpenAIChoice(
                        FakeOpenAIMessage(
                            content=None,
                            tool_calls=[
                                FakeOpenAIToolCall(
                                    "call_1",
                                    "query_db",
                                    '{"sql": "SELECT 1"}',
                                )
                            ],
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=FakeOpenAIUsage(15, 6),
            )
        )
        client = OpenAIClient(client=fake, api_key="k")
        resp = client.chat(
            messages=[Message(role="user", content="Q")],
            tools=[
                ToolDef(
                    name="query_db",
                    description="run sql",
                    input_schema={"type": "object", "properties": {}},
                )
            ],
        )
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].arguments == {"sql": "SELECT 1"}
        assert resp.stop_reason == "tool_use"
