"""Typer CLI for nl2sql. The flagship entry point."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .. import __version__
from ..exceptions import ConfigError, Nl2SqlError
from .config import Config, load_config

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="nl2sql — natural-language to SQL via an agent loop.",
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ---- top-level callback wires global flags ---------------------------------


def _global_callback(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Named profile from config file."
    ),
    db: Optional[str] = typer.Option(None, "--db", help="Database URL override."),
    model: Optional[str] = typer.Option(
        None, "--model", help="LLM model override."
    ),
    config_path: Optional[Path] = typer.Option(
        None, "--config", help="Path to a config file."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress."),
    json_out: bool = typer.Option(
        False, "--json", help="Emit JSON on stdout, errors on stderr."
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Disable styled output."),
):
    ctx.ensure_object(dict)
    ctx.obj["overrides"] = {
        "profile": profile,
        "db": db,
        "model": model,
        "config_path": str(config_path) if config_path else None,
        "quiet": quiet,
        "json": json_out,
        "no_color": no_color,
    }


app.callback()(_global_callback)


def _make_console(ctx: typer.Context) -> Console:
    no_color = ctx.obj.get("overrides", {}).get("no_color", False) if ctx.obj else False
    return Console(no_color=no_color, soft_wrap=False)


def _resolve_config(ctx: typer.Context) -> Config:
    o = ctx.obj.get("overrides", {})
    try:
        return load_config(
            profile=o.get("profile"),
            db_override=o.get("db"),
            model_override=o.get("model"),
            config_path=o.get("config_path"),
        )
    except ConfigError as e:
        typer.secho(f"Config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)


# ---- version ---------------------------------------------------------------


@app.command(help="Print version and resolved profile.")
def version(ctx: typer.Context):
    cfg = None
    try:
        cfg = _resolve_config(ctx)
    except typer.Exit:
        pass
    out = {"version": __version__}
    if cfg:
        out.update(
            {
                "profile": cfg.profile,
                "db": cfg.db_url,
                "model": cfg.llm_model,
                "provider": cfg.llm_provider,
            }
        )
    if ctx.obj.get("overrides", {}).get("json"):
        typer.echo(json.dumps(out, indent=2))
    else:
        console = _make_console(ctx)
        console.print(f"[bold]nl2sql[/bold] {__version__}")
        if cfg:
            console.print(
                f"profile: [cyan]{cfg.profile or '(default)'}[/cyan]"
            )
            console.print(f"db:      {cfg.db_url}")
            console.print(f"llm:     {cfg.llm_provider}/{cfg.llm_model}")


# ---- subcommand registration is in submodules ------------------------------

import importlib

for _modname in (
    "ask",
    "inspect",
    "init",
    "eval_cmd",
    "feedback_cmd",
    "hints_cmd",
    "repl",
):
    _mod = importlib.import_module(f"nl2sql.cli.{_modname}")
    _mod.register(app)


def _run_cli():
    try:
        app()
    except Nl2SqlError as e:
        typer.secho(f"nl2sql error: {e}", fg=typer.colors.RED, err=True)
        sys.exit(2)


if __name__ == "__main__":
    _run_cli()
