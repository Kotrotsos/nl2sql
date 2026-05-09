"""`nl2sql init` scaffolds .nl2sql.yaml and a starter hints.yaml."""
from __future__ import annotations

from pathlib import Path

import typer


_TEMPLATE_CONFIG = """\
default_profile: dev

profiles:
  dev:
    db: sqlite:///./customers.db
    llm:
      provider: anthropic
      model: claude-opus-4-7
    hints: ./hints.yaml
    feedback: ./feedback.json
    max_iterations: 10
    require_select_only: true
"""

_TEMPLATE_HINTS = """\
glossary:
  # column or term -> human-readable description
  # locregion: "Region code, uppercase, no diacritics."

formulas:
  # name -> formula
  # warranty_claim_rate: "returns_with_warranty / total_returns * 100"

join_rules: []
  # - "households.housenum links to properties.houselink"

column_descriptions: {}
  # households.locregion: "Region code, uppercase."
"""


def register(app: typer.Typer) -> None:
    @app.command(help="Scaffold a .nl2sql.yaml and starter hints.yaml.")
    def init(
        ctx: typer.Context,
        force: bool = typer.Option(False, "--force"),
        target: Path = typer.Option(None, "--target"),
    ):
        target = target or Path.cwd()
        cfg_path = target / ".nl2sql.yaml"
        hints_path = target / "hints.yaml"
        wrote = []
        if cfg_path.exists() and not force:
            typer.secho(f"{cfg_path} already exists (use --force to overwrite).",
                        fg=typer.colors.YELLOW)
        else:
            cfg_path.write_text(_TEMPLATE_CONFIG, encoding="utf-8")
            wrote.append(str(cfg_path))
        if hints_path.exists() and not force:
            typer.secho(f"{hints_path} already exists (use --force to overwrite).",
                        fg=typer.colors.YELLOW)
        else:
            hints_path.write_text(_TEMPLATE_HINTS, encoding="utf-8")
            wrote.append(str(hints_path))
        for p in wrote:
            typer.secho(f"wrote {p}", fg=typer.colors.GREEN)
        if not wrote:
            raise typer.Exit(1)
