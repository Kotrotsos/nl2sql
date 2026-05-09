"""`nl2sql ask` command."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from ..core import Nl2Sql
from ..prompts import build_system_prompt
from .render import render_result


def register(app: typer.Typer) -> None:
    @app.command(help="Ask a single question.")
    def ask(
        ctx: typer.Context,
        question: str = typer.Argument(..., help="Natural-language question."),
        max_iterations: Optional[int] = typer.Option(None, "--max-iterations"),
        no_trace: bool = typer.Option(False, "--no-trace"),
        show_prompt: bool = typer.Option(False, "--show-prompt"),
        save_trace: Optional[Path] = typer.Option(None, "--save-trace"),
        explain: bool = typer.Option(False, "--explain"),
        save_feedback: bool = typer.Option(False, "--save-feedback"),
        limit: int = typer.Option(50, "--limit"),
    ):
        from .app import _resolve_config, _make_console

        cfg = _resolve_config(ctx)
        console = _make_console(ctx)
        json_mode = ctx.obj.get("overrides", {}).get("json", False)

        db = cfg.build_db()
        llm = cfg.build_llm()
        hints = cfg.build_hints()
        feedback = cfg.build_feedback()
        knowledge = cfg.build_knowledge()

        if show_prompt:
            sp = build_system_prompt(
                dialect=getattr(db, "dialect", "sqlite"),
                hints=hints,
                knowledge_store_keys=knowledge.keys() if knowledge else None,
            )
            if json_mode:
                typer.echo(json.dumps({"system_prompt": sp}))
            else:
                console.print(sp)
            raise typer.Exit(0)

        n2s = Nl2Sql(
            db=db,
            llm=llm,
            hints=hints,
            knowledge_store=knowledge,
            feedback=feedback,
            max_iterations=max_iterations or cfg.max_iterations,
            max_rows_returned=cfg.max_rows_returned,
            query_timeout_s=cfg.query_timeout_s,
            require_select_only=cfg.require_select_only,
            deny_system_tables=cfg.deny_system_tables,
        )

        if not json_mode:
            console.print(f"[bold]Question[/bold]: {question}\n")
        result = n2s.ask(question)

        if save_trace:
            save_trace.parent.mkdir(parents=True, exist_ok=True)
            with save_trace.open("w", encoding="utf-8") as f:
                for step in result.steps:
                    f.write(json.dumps(step.to_dict(), default=str) + "\n")

        if json_mode:
            typer.echo(json.dumps(result.to_dict(), default=str))
        else:
            render_result(
                result, console, show_trace=not no_trace, limit=limit
            )

        if save_feedback and feedback is not None:
            console.print("\n[bold]Save as feedback?[/bold] [correct/incorrect/skip] (default: skip)")
            ans = sys.stdin.readline().strip().lower() if not json_mode else "skip"
            if ans in ("correct", "c", "y", "yes"):
                feedback.record(question=question, sql=result.sql or "", correct=True)
                console.print("[green]Recorded as correct.[/green]")
            elif ans in ("incorrect", "i", "n", "no"):
                feedback.record(question=question, sql=result.sql or "", correct=False)
                console.print("[red]Recorded as incorrect.[/red]")

        if not result.sql:
            raise typer.Exit(1)
