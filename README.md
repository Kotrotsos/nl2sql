# nl2sql

Natural-language-to-SQL with a single agent loop, real schema introspection, executed validation, domain hints, and a feedback store.

Distilled from the Microsoft ISE article *SQL query generation from natural language* (Ashley Costigane, May 2026). The article shows the load-bearing primitives are: (a) a small set of schema and execution tools, (b) live query execution, (c) injected domain hints (+10 to 14 points accuracy), and (d) a feedback store of corrected SQL (+19 points). This library implements all four behind a clean Python API and a Typer/Rich CLI.

## Install

```bash
pip install nl2sql-agent                    # core, imports as `nl2sql`
pip install "nl2sql-agent[anthropic]"       # + Anthropic
pip install "nl2sql-agent[openai]"          # + OpenAI
pip install "nl2sql-agent[postgres]"        # + Postgres driver
pip install "nl2sql-agent[all]"             # everything
```

> The PyPI distribution name is `nl2sql-agent` because the unqualified `nl2sql` namespace was already taken by an unrelated stub. The Python import path is unchanged: `from nl2sql import Nl2Sql`.

## Quickstart

```python
from nl2sql import Nl2Sql
from nl2sql.db import SqliteDatabase
from nl2sql.llm import AnthropicClient

n2s = Nl2Sql(
    db=SqliteDatabase("./customers.db"),
    llm=AnthropicClient(model="claude-opus-4-7"),
)

result = n2s.ask("How many customers signed up last quarter?")
print(result.sql)
print(result.rows)
```

## CLI

```bash
nl2sql init                              # scaffold .nl2sql.yaml
nl2sql ask "How many orders this month?"
nl2sql repl                              # interactive
nl2sql inspect tables
nl2sql inspect schema --table households
nl2sql eval run ./datasets/livesqlbench-medium --output ./reports/run-001
nl2sql feedback list
nl2sql hints validate ./hints.yaml
```

Every command supports `--json` for piping, `--profile`, `--db`, `--model`, `--quiet`, `--no-color`.

## Library shape

- `nl2sql.Nl2Sql` — public entry point
- `nl2sql.db` — `SqliteDatabase`, `PostgresDatabase`, `Database` ABC
- `nl2sql.llm` — `AnthropicClient`, `OpenAIClient`, `LLMClient` ABC, `MockLLMClient` for testing
- `nl2sql.tools` — the four core tools the agent calls
- `nl2sql.hints` — `DomainHints`, `KnowledgeStore`
- `nl2sql.feedback` — `FeedbackStore`, `JsonFeedbackStore`
- `nl2sql.safety` — SELECT-only check, single-statement, identifier denylist
- `nl2sql.eval` — `run_eval`, `FlexibleMatcher`, `LiveSQLBenchDataset`
- `nl2sql.cli` — Typer app

## Safety

By default the agent can only run `SELECT`. The safety layer parses with `sqlglot`, rejects multi-statement input, rejects non-`SELECT` roots, and refuses to touch `pg_*`, `information_schema`, `sqlite_master`, `sqlite_sequence`. Result rows are capped (default 200) and queries are timed out (default 10 s).

## Testing

```bash
pip install -e ".[dev,all]"
pytest -q
pytest --html=test-report.html --self-contained-html
```

## Documentation

See `docs/index.html` (light/dark mode, print-friendly) for the full reference.

## License

MIT.
