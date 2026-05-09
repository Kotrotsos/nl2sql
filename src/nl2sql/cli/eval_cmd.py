"""nl2sql eval ... commands."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from ..core import Nl2Sql
from ..eval.harness import _render_html_report, run_eval as _run_eval
from ..eval.livesqlbench import LiveSQLBenchDataset
from ..eval.matching import FlexibleMatcher
from ..types import EvalReport


def register(app: typer.Typer) -> None:
    eval_app = typer.Typer(help="Eval harness.")
    app.add_typer(eval_app, name="eval")

    @eval_app.command("run")
    def run(
        ctx: typer.Context,
        dataset: Path = typer.Argument(...),
        output: Path = typer.Option(Path("./reports/run-001"), "--output"),
        parallel: int = typer.Option(1, "--parallel"),
        repeat: int = typer.Option(1, "--repeat"),
        threshold: Optional[float] = typer.Option(None, "--threshold"),
        limit: Optional[int] = typer.Option(None, "--limit"),
        filter_: Optional[str] = typer.Option(None, "--filter"),
        numeric_tolerance: float = typer.Option(0.01, "--numeric-tolerance"),
    ):
        from .app import _resolve_config, _make_console

        cfg = _resolve_config(ctx)
        console = _make_console(ctx)
        json_mode = ctx.obj.get("overrides", {}).get("json", False)
        db = cfg.build_db()
        llm = cfg.build_llm()

        ds = LiveSQLBenchDataset.from_path(dataset)
        cases = list(ds.cases)
        if filter_:
            cases = [c for c in cases if filter_.lower() in c.question.lower()]
        if limit:
            cases = cases[:limit]

        n2s = Nl2Sql(
            db=db,
            llm=llm,
            hints=cfg.build_hints(),
            knowledge_store=cfg.build_knowledge(),
            feedback=cfg.build_feedback(),
            max_iterations=cfg.max_iterations,
            max_rows_returned=cfg.max_rows_returned,
            query_timeout_s=cfg.query_timeout_s,
            require_select_only=cfg.require_select_only,
            deny_system_tables=cfg.deny_system_tables,
        )

        report = _run_eval(
            dataset=cases,
            system=n2s,
            matcher=FlexibleMatcher(numeric_tolerance=numeric_tolerance),
            parallel=parallel,
            repeat=repeat,
            on_progress=(
                None
                if json_mode
                else lambda i, t, cr: console.print(
                    f"[{i}/{t}] {('[green]\u2713[/green]' if cr.passed else '[red]\u2717[/red]')} "
                    f"{cr.case_id} - {cr.question[:80]}"
                )
            ),
        )

        output.mkdir(parents=True, exist_ok=True)
        report.write_json(output / "report.json")
        report.write_html(output / "report.html")

        if json_mode:
            typer.echo(json.dumps({"accuracy": report.accuracy, "passed": report.passed, "total": report.total, "output": str(output)}))
        else:
            console.print()
            console.print(
                f"Accuracy: [bold]{report.accuracy * 100:.1f}%[/bold] "
                f"({report.passed}/{report.total})"
            )
            console.print(f"Report written to [cyan]{output}[/cyan]")

        if threshold is not None and report.accuracy < threshold:
            console.print(
                f"[red]Accuracy {report.accuracy:.3f} below threshold {threshold:.3f}[/red]"
            )
            raise typer.Exit(2)

    @eval_app.command("show")
    def show(
        ctx: typer.Context,
        report_path: Path = typer.Argument(...),
        failures_only: bool = typer.Option(False, "--failures-only"),
    ):
        from .app import _make_console

        console = _make_console(ctx)
        json_mode = ctx.obj.get("overrides", {}).get("json", False)
        rp = report_path
        if rp.is_dir():
            rp = rp / "report.json"
        data = json.loads(rp.read_text(encoding="utf-8"))
        if json_mode:
            typer.echo(json.dumps(data))
            return
        console.print(
            f"Accuracy: [bold]{data['accuracy'] * 100:.1f}%[/bold] "
            f"({data['passed']}/{data['total']})"
        )
        for c in data["cases"]:
            if failures_only and c["passed"]:
                continue
            mark = "[green]\u2713[/green]" if c["passed"] else "[red]\u2717[/red]"
            console.print(
                f"{mark} {c['case_id']} ({c.get('failure_category') or 'pass'}) - {c['question'][:90]}"
            )
