"""Quickstart example.

Creates a small SQLite database in /tmp, asks a question with a MockLLMClient
that scripts the agent's tool calls, then prints the resulting SQL and rows.

For a real run, swap MockLLMClient for AnthropicClient or OpenAIClient and
remove the scripted `responses=...`.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from nl2sql import Nl2Sql
from nl2sql.db import SqliteDatabase
from nl2sql.llm.base import MockLLMClient


def main():
    tmp = Path(tempfile.mkdtemp())
    db_path = tmp / "shop.db"

    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, country TEXT, created_at TEXT);
        INSERT INTO customers VALUES
          (1, 'NL', '2026-01-15'),
          (2, 'US', '2026-02-10'),
          (3, 'NL', '2026-03-05'),
          (4, 'DE', '2026-03-20'),
          (5, 'US', '2026-04-22');
        """
    )
    conn.commit()
    conn.close()

    db = SqliteDatabase(db_path)

    scripted = MockLLMClient(
        responses=[
            {
                "text": "Listing tables.",
                "tool_calls": [
                    {"id": "c1", "name": "get_db_table_list", "arguments": {}}
                ],
                "stop_reason": "tool_use",
            },
            {
                "text": "Inspecting customers.",
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
                "text": "Counting Q1 customers.",
                "tool_calls": [
                    {
                        "id": "c3",
                        "name": "query_db",
                        "arguments": {
                            "sql": (
                                "SELECT COUNT(*) AS new_customers FROM customers "
                                "WHERE created_at >= '2026-01-01' "
                                "AND created_at < '2026-04-01'"
                            )
                        },
                    }
                ],
                "stop_reason": "tool_use",
            },
            {
                "text": "Done.",
                "tool_calls": [],
                "stop_reason": "end_turn",
            },
        ]
    )

    n2s = Nl2Sql(db=db, llm=scripted, max_iterations=8)
    result = n2s.ask("How many customers signed up in Q1 2026?")

    print("SQL:", result.sql)
    print("rows:", result.rows)
    print("stopped_reason:", result.stopped_reason)
    print("iterations:", result.iterations)


if __name__ == "__main__":
    main()
