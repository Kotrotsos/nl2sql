"""Agent loop: dispatches tools, accumulates messages, extracts final SQL."""
from __future__ import annotations

import re
from typing import Any, Optional

from .db.base import Database
from .exceptions import LLMError
from .feedback import FeedbackStore
from .hints import DomainHints, KnowledgeStore
from .llm.base import LLMClient
from .prompts import build_system_prompt
from .tools import ToolDispatch, render_tool_result_for_llm
from .types import (
    AgentStep,
    LLMResponse,
    Message,
    Result,
    TokenUsage,
)


_FENCED_SQL_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_sql_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    m = _FENCED_SQL_RE.search(text)
    if m:
        return m.group(1).strip()
    # Fallback: any text starting with SELECT/WITH
    stripped = text.strip()
    head = stripped.split(None, 1)[0].upper() if stripped else ""
    if head in ("SELECT", "WITH"):
        return stripped
    return None


def run_agent(
    *,
    question: str,
    db: Database,
    llm: LLMClient,
    hints: Optional[DomainHints] = None,
    knowledge_store: Optional[KnowledgeStore] = None,
    feedback: Optional[FeedbackStore] = None,
    max_iterations: int = 10,
    max_rows_returned: int = 200,
    query_timeout_s: float = 10.0,
    require_select_only: bool = True,
    deny_system_tables: bool = True,
) -> Result:
    dispatch = ToolDispatch(
        db=db,
        knowledge_store=knowledge_store,
        max_rows_returned=max_rows_returned,
        query_timeout_s=query_timeout_s,
        require_select_only=require_select_only,
        deny_system_tables=deny_system_tables,
    )

    similar_examples = None
    if feedback is not None:
        try:
            sim = feedback.find_similar(question, k=3, only_correct=True)
            similar_examples = [
                {"question": e.question, "sql": e.sql, "notes": e.notes} for e in sim
            ]
        except Exception:
            similar_examples = None

    system_prompt = build_system_prompt(
        dialect=getattr(db, "dialect", "sqlite"),
        hints=hints,
        similar_examples=similar_examples,
        knowledge_store_keys=knowledge_store.keys() if knowledge_store else None,
    )

    history: list[Message] = [Message(role="user", content=question)]
    steps: list[AgentStep] = []
    last_query_result: dict[str, Any] | None = None
    last_query_sql: str | None = None
    total_usage = TokenUsage()
    stopped_reason = "no_sql"
    error: Optional[str] = None
    iterations = 0

    for i in range(max_iterations):
        iterations = i + 1
        try:
            resp: LLMResponse = llm.chat(
                history,
                tools=dispatch.tool_definitions,
                system=system_prompt,
            )
        except LLMError as e:
            stopped_reason = "llm_error"
            error = str(e)
            break

        total_usage = TokenUsage(
            input_tokens=total_usage.input_tokens + resp.usage.input_tokens,
            output_tokens=total_usage.output_tokens + resp.usage.output_tokens,
        )

        steps.append(
            AgentStep(
                kind="llm_message",
                payload={
                    "text": resp.text,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in resp.tool_calls
                    ],
                    "stop_reason": resp.stop_reason,
                },
            )
        )

        # Persist the assistant turn to history.
        history.append(
            Message(
                role="assistant",
                content={
                    "text": resp.text,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in resp.tool_calls
                    ],
                },
            )
        )

        if resp.stop_reason == "end_turn" and not resp.tool_calls:
            stopped_reason = "answered" if last_query_sql else "no_sql"
            break

        if not resp.tool_calls:
            # No tool calls and not end_turn: nudge the loop forward by feeding back.
            history.append(Message(role="user", content="Continue."))
            continue

        # Dispatch each tool call sequentially.
        tool_results_payload = []
        for tc in resp.tool_calls:
            steps.append(
                AgentStep(
                    kind="tool_call",
                    payload={"id": tc.id, "name": tc.name, "arguments": tc.arguments},
                )
            )
            result = dispatch.dispatch(tc.name, tc.arguments)
            steps.append(
                AgentStep(
                    kind="tool_result",
                    payload={"id": tc.id, "name": tc.name, "result": result},
                )
            )
            if tc.name == "query_db" and result.get("ok"):
                last_query_result = result.get("content")
                last_query_sql = result.get("sql") or tc.arguments.get("sql")
            tool_results_payload.append(
                {
                    "tool_use_id": tc.id,
                    "content": render_tool_result_for_llm(result),
                    "is_error": not result.get("ok", False),
                }
            )

        history.append(Message(role="tool", content=tool_results_payload))
    else:
        stopped_reason = "max_iterations"

    sql: Optional[str] = last_query_sql
    rows: Optional[list[dict[str, Any]]] = None
    columns: Optional[list[str]] = None
    if last_query_result and isinstance(last_query_result, dict):
        rows = last_query_result.get("rows")
        columns = last_query_result.get("columns")

    if sql is None:
        # Try to extract from the last assistant text.
        for step in reversed(steps):
            if step.kind == "llm_message":
                txt = step.payload.get("text")
                cand = _extract_sql_from_text(txt or "")
                if cand:
                    sql = cand
                    break

    if sql and stopped_reason == "no_sql":
        stopped_reason = "answered"

    return Result(
        question=question,
        sql=sql,
        rows=rows,
        columns=columns,
        steps=steps,
        iterations=iterations,
        stopped_reason=stopped_reason,
        error=error,
        usage=total_usage,
    )
