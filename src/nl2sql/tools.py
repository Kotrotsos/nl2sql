"""The four core tools, plus optional ``lookup_hint``.

These wrap a :class:`Database` and (optionally) a :class:`KnowledgeStore`. The
LLM only ever sees tool definitions and tool-call results, never the database.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from .db.base import Database
from .exceptions import DatabaseError, SafetyError
from .hints import KnowledgeStore
from .safety import enforce_safe_select
from .types import QueryResult, ToolDef


# JSON schemas for the tool definitions
_NO_ARGS_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}

_TABLE_NAME_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string", "description": "Exact table name."}},
    "required": ["name"],
    "additionalProperties": False,
}

_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {
            "type": "string",
            "description": "A single SELECT statement. SELECT only, no DML/DDL.",
        }
    },
    "required": ["sql"],
    "additionalProperties": False,
}

_LOOKUP_HINT_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {
            "type": "string",
            "description": "Domain term, glossary key, or short phrase to look up.",
        }
    },
    "required": ["topic"],
    "additionalProperties": False,
}


def _tool_defs(include_hint: bool) -> list[ToolDef]:
    defs = [
        ToolDef(
            name="get_db_table_list",
            description=(
                "List all tables and views in the database. Use this first to "
                "see what is available."
            ),
            input_schema=_NO_ARGS_SCHEMA,
        ),
        ToolDef(
            name="get_db_schema",
            description=(
                "Return the full schema for every table: column names, types, "
                "primary keys, foreign keys."
            ),
            input_schema=_NO_ARGS_SCHEMA,
        ),
        ToolDef(
            name="get_tb_table_schema",
            description=(
                "Return the schema for a single table by exact name. "
                "Use after get_db_table_list to focus on one table."
            ),
            input_schema=_TABLE_NAME_SCHEMA,
        ),
        ToolDef(
            name="query_db",
            description=(
                "Execute a single SELECT statement and return the rows. "
                "SELECT only; multi-statement, INSERT, UPDATE, DELETE, DDL "
                "are rejected. Result rows are capped."
            ),
            input_schema=_QUERY_SCHEMA,
        ),
    ]
    if include_hint:
        defs.append(
            ToolDef(
                name="lookup_hint",
                description=(
                    "Look up a domain hint or glossary entry by topic. "
                    "Returns null if no entry matches."
                ),
                input_schema=_LOOKUP_HINT_SCHEMA,
            )
        )
    return defs


@dataclass
class ToolDispatch:
    """Bound tool dispatcher: runs the four tools against a database."""

    db: Database
    knowledge_store: Optional[KnowledgeStore] = None
    max_rows_returned: int = 200
    query_timeout_s: float = 10.0
    require_select_only: bool = True
    deny_system_tables: bool = True

    @property
    def tool_definitions(self) -> list[ToolDef]:
        return _tool_defs(include_hint=self.knowledge_store is not None)

    @property
    def names(self) -> set[str]:
        return {t.name for t in self.tool_definitions}

    def dispatch(self, name: str, arguments: dict) -> dict[str, Any]:
        """Run one tool. Always returns a dict with ``ok`` and ``content`` keys."""
        try:
            if name == "get_db_table_list":
                tables = self.db.list_tables()
                return {"ok": True, "content": tables}
            if name == "get_db_schema":
                schema = self.db.get_schema()
                return {
                    "ok": True,
                    "content": {tn: ts.to_text() for tn, ts in schema.items()},
                }
            if name == "get_tb_table_schema":
                tname = arguments.get("name")
                if not tname:
                    return {"ok": False, "content": "Missing argument 'name'."}
                ts = self.db.get_table_schema(tname)
                return {"ok": True, "content": ts.to_text()}
            if name == "query_db":
                sql = arguments.get("sql", "")
                if self.require_select_only:
                    try:
                        sql = enforce_safe_select(
                            sql,
                            deny_system_tables=self.deny_system_tables,
                            dialect=getattr(self.db, "dialect", None),
                        )
                    except SafetyError as e:
                        return {"ok": False, "content": f"Rejected by safety: {e}"}
                qr: QueryResult = self.db.execute_select(
                    sql,
                    timeout_s=self.query_timeout_s,
                    max_rows=self.max_rows_returned,
                )
                return {
                    "ok": True,
                    "sql": sql,
                    "content": {
                        "columns": qr.columns,
                        "rows": qr.rows,
                        "row_count": qr.row_count,
                        "truncated_at": qr.truncated_at,
                        "elapsed_ms": qr.elapsed_ms,
                    },
                }
            if name == "lookup_hint":
                if not self.knowledge_store:
                    return {"ok": False, "content": "No knowledge store configured."}
                topic = arguments.get("topic", "")
                hit = self.knowledge_store.lookup(topic)
                return {
                    "ok": True,
                    "content": hit if hit is not None else f"No hint matched '{topic}'.",
                }
            return {"ok": False, "content": f"Unknown tool '{name}'."}
        except DatabaseError as e:
            return {"ok": False, "content": f"Database error: {e}"}
        except Exception as e:  # pragma: no cover - defensive
            return {"ok": False, "content": f"Tool error: {e}"}


def render_tool_result_for_llm(payload: dict[str, Any]) -> str:
    """Render a dispatch result as a string the LLM will see."""
    return json.dumps(payload, default=str, ensure_ascii=False)
