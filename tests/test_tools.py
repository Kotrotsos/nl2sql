"""ToolDispatch tests."""
from __future__ import annotations

import pytest

from nl2sql.db import SqliteDatabase
from nl2sql.hints import DictKnowledgeStore
from nl2sql.tools import ToolDispatch


class TestToolDefinitions:
    def test_four_tools_default(self, sample_db_path):
        d = ToolDispatch(db=SqliteDatabase(sample_db_path))
        names = {t.name for t in d.tool_definitions}
        assert names == {
            "get_db_table_list",
            "get_db_schema",
            "get_tb_table_schema",
            "query_db",
        }

    def test_lookup_hint_added_when_knowledge_store_present(self, sample_db_path):
        d = ToolDispatch(
            db=SqliteDatabase(sample_db_path),
            knowledge_store=DictKnowledgeStore({"income": "info"}),
        )
        names = {t.name for t in d.tool_definitions}
        assert "lookup_hint" in names


class TestDispatch:
    def test_get_db_table_list(self, sample_db_path):
        d = ToolDispatch(db=SqliteDatabase(sample_db_path))
        r = d.dispatch("get_db_table_list", {})
        assert r["ok"] is True
        assert "customers" in r["content"]

    def test_get_db_schema(self, sample_db_path):
        d = ToolDispatch(db=SqliteDatabase(sample_db_path))
        r = d.dispatch("get_db_schema", {})
        assert r["ok"] is True
        assert "customers" in r["content"]
        assert "TABLE customers" in r["content"]["customers"]

    def test_get_table_schema(self, sample_db_path):
        d = ToolDispatch(db=SqliteDatabase(sample_db_path))
        r = d.dispatch("get_tb_table_schema", {"name": "customers"})
        assert r["ok"] is True
        assert "email" in r["content"]

    def test_get_table_schema_missing_arg(self, sample_db_path):
        d = ToolDispatch(db=SqliteDatabase(sample_db_path))
        r = d.dispatch("get_tb_table_schema", {})
        assert r["ok"] is False

    def test_query_db_runs_select(self, sample_db_path):
        d = ToolDispatch(db=SqliteDatabase(sample_db_path))
        r = d.dispatch("query_db", {"sql": "SELECT COUNT(*) AS n FROM customers"})
        assert r["ok"] is True
        assert r["content"]["rows"][0]["n"] == 5

    def test_query_db_blocks_insert(self, sample_db_path):
        d = ToolDispatch(db=SqliteDatabase(sample_db_path))
        r = d.dispatch("query_db", {"sql": "INSERT INTO customers (id, email, created_at) VALUES (99, 'x@y', '2026-01-01')"})
        assert r["ok"] is False
        assert "rejected" in r["content"].lower() or "select" in r["content"].lower()

    def test_query_db_blocks_multi_statement(self, sample_db_path):
        d = ToolDispatch(db=SqliteDatabase(sample_db_path))
        r = d.dispatch("query_db", {"sql": "SELECT 1; SELECT 2"})
        assert r["ok"] is False

    def test_unknown_tool(self, sample_db_path):
        d = ToolDispatch(db=SqliteDatabase(sample_db_path))
        r = d.dispatch("does_not_exist", {})
        assert r["ok"] is False
        assert "unknown" in r["content"].lower()

    def test_lookup_hint_hit(self, sample_db_path):
        d = ToolDispatch(
            db=SqliteDatabase(sample_db_path),
            knowledge_store=DictKnowledgeStore({"income": "buckets"}),
        )
        r = d.dispatch("lookup_hint", {"topic": "income"})
        assert r["ok"] is True
        assert r["content"] == "buckets"

    def test_lookup_hint_miss(self, sample_db_path):
        d = ToolDispatch(
            db=SqliteDatabase(sample_db_path),
            knowledge_store=DictKnowledgeStore({"income": "buckets"}),
        )
        r = d.dispatch("lookup_hint", {"topic": "warranty"})
        assert r["ok"] is True
        assert "no hint" in r["content"].lower()
