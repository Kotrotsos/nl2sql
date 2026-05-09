"""Rich-based rendering helpers."""
from __future__ import annotations

from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..types import AgentStep, Result


def render_result(result: Result, console: Console, *, show_trace: bool = True, limit: int = 50):
    if show_trace:
        for i, step in enumerate(result.steps, 1):
            render_step(i, step, console)
    if result.sql:
        console.print(
            Panel(
                Syntax(result.sql, "sql", theme="ansi_light", word_wrap=True),
                title="SQL",
                border_style="cyan",
            )
        )
    if result.rows is not None and result.columns:
        render_rows(result.columns, result.rows, console, limit=limit)
    elif result.error:
        console.print(Panel(Text(result.error, style="red"), title="Error", border_style="red"))

    summary = (
        f"{result.iterations} iter · "
        f"{result.usage.input_tokens} in · "
        f"{result.usage.output_tokens} out · "
        f"{result.elapsed_s:.2f}s · "
        f"{result.stopped_reason}"
    )
    console.print(Text(summary, style="dim"))


def render_step(idx: int, step: AgentStep, console: Console) -> None:
    p = step.payload
    if step.kind == "llm_message":
        text = (p.get("text") or "").strip()
        tcs = p.get("tool_calls") or []
        if text:
            console.print(f"[dim][{idx}][/dim] [bold]assistant[/bold]: {text}")
        for tc in tcs:
            args = tc.get("arguments") or {}
            args_short = ", ".join(
                f"{k}={_short_repr(v)}" for k, v in args.items()
            )
            console.print(
                f"[dim][{idx}][/dim] [yellow]→ tool_call[/yellow] "
                f"[bold]{tc['name']}[/bold]({args_short})"
            )
    elif step.kind == "tool_result":
        name = p.get("name", "?")
        result = p.get("result") or {}
        ok = result.get("ok", False)
        prefix = (
            "[green]← tool_result[/green]" if ok else "[red]← tool_error[/red]"
        )
        content = result.get("content")
        console.print(
            f"[dim][{idx}][/dim] {prefix} [bold]{name}[/bold]: {_short_content(content)}"
        )


def render_rows(columns: list[str], rows: list[dict], console: Console, *, limit: int = 50):
    if not rows:
        console.print("[dim](no rows)[/dim]")
        return
    table = Table(show_header=True, header_style="bold", border_style="dim")
    for c in columns:
        table.add_column(str(c))
    for row in rows[:limit]:
        table.add_row(*[_short_repr(row.get(c)) for c in columns])
    console.print(table)
    if len(rows) > limit:
        console.print(f"[dim]({len(rows) - limit} more rows truncated)[/dim]")


def render_schema(name: str, schema, console: Console):
    table = Table(
        title=f"{name} ({len(schema.columns)} columns)",
        show_header=True,
        header_style="bold",
        border_style="dim",
    )
    table.add_column("column")
    table.add_column("type")
    table.add_column("null")
    table.add_column("default")
    table.add_column("notes")
    pks = set(schema.primary_key)
    for col in schema.columns:
        notes = []
        if col.name in pks:
            notes.append("PK")
        if col.description:
            notes.append(col.description)
        table.add_row(
            col.name,
            col.data_type,
            "yes" if col.nullable else "no",
            col.default or "",
            ", ".join(notes),
        )
    console.print(table)
    for fk in schema.foreign_keys:
        console.print(
            f"[dim]FK ({', '.join(fk.columns)}) → "
            f"{fk.ref_table}({', '.join(fk.ref_columns)})[/dim]"
        )


def _short_repr(v: Any) -> str:
    s = "" if v is None else str(v)
    if len(s) > 80:
        return s[:77] + "..."
    return s


def _short_content(c: Any, *, n: int = 120) -> str:
    if isinstance(c, (list, dict)):
        s = repr(c)
    else:
        s = "" if c is None else str(c)
    if len(s) > n:
        return s[: n - 3] + "..."
    return s
