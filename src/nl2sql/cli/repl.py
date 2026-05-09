"""`nl2sql repl` interactive session."""
from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console

from ..core import Nl2Sql


def register(app: typer.Typer) -> None:
    @app.command(help="Interactive REPL.")
    def repl(ctx: typer.Context):
        from .app import _resolve_config, _make_console
        from .render import render_result, render_schema, render_rows

        cfg = _resolve_config(ctx)
        console = _make_console(ctx)
        db = cfg.build_db()
        llm = cfg.build_llm()
        hints = cfg.build_hints()
        feedback = cfg.build_feedback()
        knowledge = cfg.build_knowledge()

        n2s = Nl2Sql(
            db=db,
            llm=llm,
            hints=hints,
            knowledge_store=knowledge,
            feedback=feedback,
            max_iterations=cfg.max_iterations,
            max_rows_returned=cfg.max_rows_returned,
            query_timeout_s=cfg.query_timeout_s,
            require_select_only=cfg.require_select_only,
            deny_system_tables=cfg.deny_system_tables,
        )

        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import InMemoryHistory
            session = PromptSession(history=InMemoryHistory())
            input_fn = lambda: session.prompt("nl2sql> ")
        except Exception:
            input_fn = lambda: input("nl2sql> ")

        last_result = None
        console.print("[dim]Type \\help for meta-commands, \\quit to exit.[/dim]")

        while True:
            try:
                line = input_fn()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            line = (line or "").strip()
            if not line:
                continue
            if line == "\\quit" or line == "\\q":
                break
            if line.startswith("\\help"):
                console.print(
                    "\\tables, \\schema [t], \\sample <t>, \\hints, \\last, \\trace, "
                    "\\fb good [notes], \\fb bad <correction>, \\quit"
                )
                continue
            if line == "\\tables":
                for t in db.list_tables():
                    console.print(t)
                continue
            if line.startswith("\\schema"):
                parts = line.split(maxsplit=1)
                if len(parts) > 1:
                    render_schema(parts[1], db.get_table_schema(parts[1]), console)
                else:
                    for n, ts in db.get_schema().items():
                        render_schema(n, ts, console)
                continue
            if line.startswith("\\sample"):
                parts = line.split(maxsplit=1)
                if len(parts) > 1:
                    qr = db.execute_select(
                        f"SELECT * FROM {parts[1]} LIMIT 5",
                        timeout_s=cfg.query_timeout_s,
                        max_rows=5,
                    )
                    render_rows(qr.columns, qr.rows, console, limit=5)
                continue
            if line == "\\hints":
                if hints:
                    console.print(hints.to_dict())
                else:
                    console.print("[dim](no hints configured)[/dim]")
                continue
            if line == "\\last":
                if last_result:
                    render_result(last_result, console)
                continue
            if line == "\\trace":
                if last_result:
                    for s in last_result.steps:
                        console.print(s.to_dict())
                continue
            if line.startswith("\\fb good"):
                if last_result and feedback:
                    notes = line[len("\\fb good"):].strip()
                    feedback.record(
                        question=last_result.question,
                        sql=last_result.sql or "",
                        correct=True,
                        notes=notes,
                    )
                    console.print("[green]saved as correct[/green]")
                continue
            if line.startswith("\\fb bad"):
                if last_result and feedback:
                    correction = line[len("\\fb bad"):].strip()
                    feedback.record(
                        question=last_result.question,
                        sql=correction or (last_result.sql or ""),
                        correct=False,
                        notes="user-marked incorrect",
                    )
                    console.print("[red]saved as incorrect[/red]")
                continue
            if line.startswith("\\"):
                console.print(f"[yellow]unknown meta-command: {line}[/yellow]")
                continue

            last_result = n2s.ask(line)
            render_result(last_result, console)
