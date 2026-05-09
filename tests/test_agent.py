"""Agent loop tests using the MockLLMClient and a SQLite fixture."""
from __future__ import annotations

import pytest

from nl2sql import Nl2Sql
from nl2sql.db import SqliteDatabase
from nl2sql.llm.base import MockLLMClient


class TestAgentLoop:
    def test_simple_count_via_tool_calls(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        # Scripted: ask for table list, then table schema, then run query, then end.
        responses = [
            {
                "text": "Let me look at the tables.",
                "tool_calls": [
                    {"id": "c1", "name": "get_db_table_list", "arguments": {}}
                ],
                "stop_reason": "tool_use",
            },
            {
                "text": "I'll inspect customers.",
                "tool_calls": [
                    {
                        "id": "c2",
                        "name": "get_tb_table_schema",
                        "arguments": {"name": "customers"},
                    }
                ],
                "stop_reason": "tool_use",
            },
            {
                "text": "Now the count.",
                "tool_calls": [
                    {
                        "id": "c3",
                        "name": "query_db",
                        "arguments": {
                            "sql": "SELECT COUNT(*) AS n FROM customers"
                        },
                    }
                ],
                "stop_reason": "tool_use",
            },
            {
                "text": "There are 5 customers.",
                "tool_calls": [],
                "stop_reason": "end_turn",
            },
        ]
        llm = MockLLMClient(responses=responses)
        n2s = Nl2Sql(db=db, llm=llm, max_iterations=10)
        result = n2s.ask("How many customers?")
        assert result.stopped_reason == "answered"
        assert result.sql is not None
        assert "COUNT" in result.sql.upper()
        assert result.rows == [{"n": 5}]
        assert result.iterations == 4

    def test_max_iterations_caps(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        # Loop forever without producing end_turn
        responses = [
            {
                "text": "",
                "tool_calls": [
                    {"id": f"c{i}", "name": "get_db_table_list", "arguments": {}}
                ],
                "stop_reason": "tool_use",
            }
            for i in range(20)
        ]
        llm = MockLLMClient(responses=responses)
        n2s = Nl2Sql(db=db, llm=llm, max_iterations=3)
        result = n2s.ask("anything")
        assert result.stopped_reason == "max_iterations"
        assert result.iterations == 3

    def test_safety_violation_in_query(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        responses = [
            {
                "text": "Trying to drop.",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "query_db",
                        "arguments": {"sql": "DROP TABLE customers"},
                    }
                ],
                "stop_reason": "tool_use",
            },
            {
                "text": "Sorry, I'll stop.",
                "tool_calls": [],
                "stop_reason": "end_turn",
            },
        ]
        llm = MockLLMClient(responses=responses)
        n2s = Nl2Sql(db=db, llm=llm, max_iterations=10)
        result = n2s.ask("drop the table")
        # Tool should have rejected; agent stops without SQL.
        assert result.sql is None or "DROP" not in (result.sql or "").upper()
        # Check the dispatched tool result was an error.
        tool_steps = [s for s in result.steps if s.kind == "tool_result"]
        assert any(not s.payload["result"]["ok"] for s in tool_steps)

    def test_extracts_sql_from_text_when_no_tool_call(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        # Agent answers in text instead of running query_db.
        responses = [
            {
                "text": "Here you go: ```sql\nSELECT 1 AS one\n```",
                "tool_calls": [],
                "stop_reason": "end_turn",
            }
        ]
        llm = MockLLMClient(responses=responses)
        n2s = Nl2Sql(db=db, llm=llm)
        result = n2s.ask("trivial")
        assert result.sql is not None
        assert "SELECT 1" in result.sql

    def test_records_token_usage(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        responses = [
            {
                "text": "done",
                "tool_calls": [],
                "stop_reason": "end_turn",
                "input_tokens": 100,
                "output_tokens": 25,
            }
        ]
        llm = MockLLMClient(responses=responses)
        n2s = Nl2Sql(db=db, llm=llm)
        result = n2s.ask("trivial")
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 25

    def test_feedback_examples_added_to_prompt(self, sample_db_path, tmp_path):
        from nl2sql.feedback import JsonFeedbackStore

        db = SqliteDatabase(sample_db_path)
        store = JsonFeedbackStore(tmp_path / "fb.json")
        store.record(
            "Top customers by spend",
            "SELECT customer_id, SUM(amount) AS s FROM orders GROUP BY 1",
            correct=True,
            notes="join via customer_id",
        )
        captured = {}

        def _capture(messages, tools):
            return None

        # Wrap MockLLMClient to capture system prompt
        class CapturingMock(MockLLMClient):
            def chat(self, messages, tools, *, max_tokens=4096, system=None):
                captured["system"] = system
                return super().chat(messages, tools, max_tokens=max_tokens, system=system)

        llm = CapturingMock(
            responses=[{"text": "done", "tool_calls": [], "stop_reason": "end_turn"}]
        )
        n2s = Nl2Sql(db=db, llm=llm, feedback=store)
        n2s.ask("Show me top customers by spend")
        assert "Past validated examples" in captured["system"]
        assert "Top customers" in captured["system"]
