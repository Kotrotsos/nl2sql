"""`nl2sql inspect ...` commands."""
from __future__ import annotations

import json
from typing import Optional

import typer

from ..exceptions import DatabaseError
from ..safety import enforce_safe_select
from .render import render_rows, render_schema


def register(app: typer.Typer) -> None:
    inspect_app = typer.Typer(help="Read-only schema and data exploration.")
    app.add_typer(inspect_app, name="inspect")

    @inspect_app.command("tables")
    def tables(ctx: typer.Context):
        from .app import _resolve_config, _make_console

        cfg = _resolve_config(ctx)
        console = _make_console(ctx)
        json_mode = ctx.obj.get("overrides", {}).get("json", False)
        db = cfg.build_db()
        names = db.list_tables()
        if json_mode:
            typer.echo(json.dumps(names))
        else:
            for n in names:
                console.print(n)

    @inspect_app.command("schema")
    def schema(
        ctx: typer.Context,
        table: Optional[str] = typer.Option(None, "--table", "-t"),
    ):
        from .app import _resolve_config, _make_console

        cfg = _resolve_config(ctx)
        console = _make_console(ctx)
        json_mode = ctx.obj.get("overrides", {}).get("json", False)
        db = cfg.build_db()

        if table:
            ts = db.get_table_schema(table)
            if json_mode:
                typer.echo(
                    json.dumps(
                        {
                            "name": ts.name,
                            "columns": [
                                {
                                    "name": c.name,
                                    "type": c.data_type,
                                    "nullable": c.nullable,
                                    "default": c.default,
                                    "description": c.description,
                                }
                                for c in ts.columns
                            ],
                            "primary_key": ts.primary_key,
                            "foreign_keys": [
                                {
                                    "columns": fk.columns,
                                    "ref_table": fk.ref_table,
                                    "ref_columns": fk.ref_columns,
                                }
                                for fk in ts.foreign_keys
                            ],
                            "description": ts.description,
                        }
                    )
                )
            else:
                render_schema(ts.name, ts, console)
        else:
            full = db.get_schema()
            if json_mode:
                out = {n: ts.to_text() for n, ts in full.items()}
                typer.echo(json.dumps(out))
            else:
                for n, ts in full.items():
                    render_schema(n, ts, console)

    @inspect_app.command("sample")
    def sample(
        ctx: typer.Context,
        table: str = typer.Argument(...),
        n: int = typer.Option(5, "-n", "--n"),
        max_rows: int = typer.Option(50, "--max-rows"),
    ):
        from .app import _resolve_config, _make_console

        cfg = _resolve_config(ctx)
        console = _make_console(ctx)
        json_mode = ctx.obj.get("overrides", {}).get("json", False)
        db = cfg.build_db()

        # Resolve table to make sure it exists.
        ts = db.get_table_schema(table)
        sql = f"SELECT * FROM {ts.name} LIMIT {int(n)}"
        sql = enforce_safe_select(
            sql, deny_system_tables=cfg.deny_system_tables, dialect=db.dialect
        )
        qr = db.execute_select(
            sql, timeout_s=cfg.query_timeout_s, max_rows=min(max_rows, n)
        )
        if json_mode:
            typer.echo(json.dumps({"columns": qr.columns, "rows": qr.rows}, default=str))
        else:
            render_rows(qr.columns, qr.rows, console, limit=n)
