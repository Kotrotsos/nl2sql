"""`nl2sql hints ...` commands."""
from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Optional

import typer

from ..hints import DomainHints


def register(app: typer.Typer) -> None:
    hints_app = typer.Typer(help="Inspect and validate hints files.")
    app.add_typer(hints_app, name="hints")

    @hints_app.command("validate")
    def validate(
        ctx: typer.Context,
        path: Path = typer.Argument(...),
    ):
        from .app import _resolve_config, _make_console

        cfg = _resolve_config(ctx)
        console = _make_console(ctx)
        json_mode = ctx.obj.get("overrides", {}).get("json", False)

        hints = DomainHints.from_yaml(path)
        db = cfg.build_db()
        schema = db.get_schema()
        all_columns: dict[str, set[str]] = {
            t: {c.name for c in s.columns} for t, s in schema.items()
        }

        errors: list[str] = []
        warnings: list[str] = []

        for key in hints.column_descriptions:
            if "." in key:
                tname, cname = key.split(".", 1)
                if tname not in all_columns:
                    errors.append(
                        f"column_descriptions.{key}: table {tname!r} not found "
                        f"({_did_you_mean(tname, all_columns.keys())})"
                    )
                elif cname not in all_columns[tname]:
                    errors.append(
                        f"column_descriptions.{key}: column not found "
                        f"({_did_you_mean(cname, all_columns[tname])})"
                    )

        for rule in hints.join_rules:
            for token in rule.split():
                if "." in token:
                    cleaned = token.strip(".,;:()")
                    parts = cleaned.split(".")
                    if len(parts) >= 2:
                        tname = parts[0]
                        if tname.isidentifier() and tname not in all_columns:
                            errors.append(
                                f"join_rule references unknown table {tname!r} "
                                f"({_did_you_mean(tname, all_columns.keys())})"
                            )

        if json_mode:
            typer.echo(json.dumps({"errors": errors, "warnings": warnings}))
        else:
            for e in errors:
                console.print(f"[red]✗[/red] {e}")
            for w in warnings:
                console.print(f"[yellow]![/yellow] {w}")
            if not errors and not warnings:
                console.print("[green]✓ hints valid.[/green]")
            else:
                console.print(
                    f"\n{len(errors)} error{'s' if len(errors)!=1 else ''}, "
                    f"{len(warnings)} warning{'s' if len(warnings)!=1 else ''}."
                )
        if errors:
            raise typer.Exit(1)

    @hints_app.command("show")
    def show(
        ctx: typer.Context,
        section: Optional[str] = typer.Option(None, "--section"),
    ):
        from .app import _resolve_config, _make_console

        cfg = _resolve_config(ctx)
        console = _make_console(ctx)
        json_mode = ctx.obj.get("overrides", {}).get("json", False)
        if not cfg.hints_path:
            typer.secho("No hints configured.", fg=typer.colors.YELLOW, err=True)
            raise typer.Exit(1)
        hints = DomainHints.from_yaml(cfg.hints_path)
        out = hints.to_dict()
        if section:
            out = {section: out.get(section, {})}
        if json_mode:
            typer.echo(json.dumps(out, default=str))
        else:
            for k, v in out.items():
                console.print(f"\n[bold]{k}[/bold]")
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        console.print(f"  {k2}: {v2}")
                elif isinstance(v, list):
                    for item in v:
                        console.print(f"  - {item}")


def _did_you_mean(needle: str, candidates) -> str:
    matches = difflib.get_close_matches(needle, list(candidates), n=1)
    return f"did you mean '{matches[0]}'?" if matches else "no close match"
