"""CLI smoke tests using Typer's CliRunner."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nl2sql.cli.app import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli_env(monkeypatch, sample_db_path, tmp_path):
    # Prevent picking up a user's real ~/.config/nl2sql/config.yaml.
    monkeypatch.setenv("NL2SQL_DB_URL", f"sqlite:///{sample_db_path}")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestVersion:
    def test_version_prints(self, runner, cli_env):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "nl2sql" in result.output

    def test_version_json(self, runner, cli_env):
        result = runner.invoke(app, ["--json", "version"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "version" in data


class TestInspect:
    def test_inspect_tables(self, runner, cli_env, sample_db_path):
        result = runner.invoke(app, ["inspect", "tables"])
        assert result.exit_code == 0
        assert "customers" in result.output

    def test_inspect_tables_json(self, runner, cli_env):
        result = runner.invoke(app, ["--json", "inspect", "tables"])
        assert result.exit_code == 0
        names = json.loads(result.output)
        assert "customers" in names

    def test_inspect_schema_table(self, runner, cli_env):
        result = runner.invoke(app, ["inspect", "schema", "--table", "customers"])
        assert result.exit_code == 0
        assert "email" in result.output

    def test_inspect_sample(self, runner, cli_env):
        result = runner.invoke(app, ["inspect", "sample", "customers", "-n", "2"])
        assert result.exit_code == 0


class TestInit:
    def test_init_creates_files(self, runner, cli_env):
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert (cli_env / ".nl2sql.yaml").exists()
        assert (cli_env / "hints.yaml").exists()


class TestHints:
    def test_hints_validate_clean(self, runner, cli_env):
        # Write a hints file referencing existing column.
        (cli_env / "hints.yaml").write_text(
            "column_descriptions:\n  customers.email: 'email address'\n"
        )
        result = runner.invoke(app, ["hints", "validate", str(cli_env / "hints.yaml")])
        assert result.exit_code == 0

    def test_hints_validate_finds_typo(self, runner, cli_env):
        (cli_env / "hints.yaml").write_text(
            "column_descriptions:\n  customers.emial: 'typo column'\n"
        )
        result = runner.invoke(app, ["hints", "validate", str(cli_env / "hints.yaml")])
        assert result.exit_code != 0
        # Suggests the closest match
        assert "email" in result.output


class TestFeedbackCli:
    def test_feedback_list_empty(self, runner, cli_env):
        # Configure a feedback path through a project config.
        (cli_env / ".nl2sql.yaml").write_text(
            f"""\
default_profile: dev
profiles:
  dev:
    db: sqlite:///{cli_env}/sample.db
    llm:
      provider: mock
    feedback: {cli_env}/fb.json
"""
        )
        # Re-use sample db from fixture path; symlink not needed since config wins
        result = runner.invoke(
            app,
            [
                "--config",
                str(cli_env / ".nl2sql.yaml"),
                "--profile",
                "dev",
                "--db",
                "sqlite:///" + str(cli_env / "ignored.db"),
                "feedback",
                "list",
            ],
        )
        # Either empty list or a fresh file.
        # We just want exit_code 0 for a recognised store.
        assert result.exit_code in (0,)
