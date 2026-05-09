"""`nl2sql feedback ...` commands."""
from __future__ import annotations

import json
import sys
from typing import Optional

import typer

from ..feedback import JsonFeedbackStore


def _store_or_die(ctx) -> JsonFeedbackStore:
    from .app import _resolve_config

    cfg = _resolve_config(ctx)
    if not cfg.feedback_path:
        typer.secho("No feedback store configured (set 'feedback:' in your profile).",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    return JsonFeedbackStore(cfg.feedback_path)


def register(app: typer.Typer) -> None:
    fb_app = typer.Typer(help="Feedback store inspection and review.")
    app.add_typer(fb_app, name="feedback")

    @fb_app.command("list")
    def list_(
        ctx: typer.Context,
        only_correct: bool = typer.Option(False, "--correct"),
        only_incorrect: bool = typer.Option(False, "--incorrect"),
    ):
        from .app import _make_console

        console = _make_console(ctx)
        json_mode = ctx.obj.get("overrides", {}).get("json", False)
        store = _store_or_die(ctx)
        entries = store.list()
        if only_correct:
            entries = [e for e in entries if e.correct]
        if only_incorrect:
            entries = [e for e in entries if not e.correct]
        if json_mode:
            typer.echo(json.dumps([e.to_dict() for e in entries], default=str))
        else:
            for e in entries:
                mark = "[green]✓[/green]" if e.correct else "[red]✗[/red]"
                console.print(
                    f"{mark} [dim]{e.id}[/dim] {e.question[:80]} "
                    f"[dim]({e.recorded_at})[/dim]"
                )

    @fb_app.command("review")
    def review(ctx: typer.Context):
        from .app import _make_console

        console = _make_console(ctx)
        store = _store_or_die(ctx)
        unreviewed = [e for e in store.list() if not e.reviewed]
        if not unreviewed:
            console.print("[dim]No unreviewed entries.[/dim]")
            return
        for i, e in enumerate(unreviewed, 1):
            console.print(
                f"\n[bold][{i}/{len(unreviewed)}][/bold] {e.question}"
            )
            console.print(f"SQL: {e.sql}")
            console.print("[y]es / [n]o / [s]kip / [q]uit?: ", end="")
            ans = sys.stdin.readline().strip().lower()
            if ans.startswith("q"):
                break
            if ans.startswith("s"):
                continue
            correct = ans.startswith("y")
            store.forget(e.id)
            store.record(e.question, e.sql, correct=correct, notes=e.notes, reviewed=True)
        console.print("[green]Done.[/green]")

    @fb_app.command("forget")
    def forget(ctx: typer.Context, entry_id: str = typer.Argument(...)):
        from .app import _make_console

        console = _make_console(ctx)
        store = _store_or_die(ctx)
        ok = store.forget(entry_id)
        if ok:
            console.print(f"[green]Removed {entry_id}.[/green]")
        else:
            console.print(f"[yellow]No entry with id {entry_id}.[/yellow]")
            raise typer.Exit(1)
