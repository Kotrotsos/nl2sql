# nl2sql, plan and spec

A Python library that turns natural-language questions into validated SQL queries against a real database, using an agent loop with schema and execution tools. Distilled from the Microsoft ISE article *SQL query generation from natural language* (Ashley Costigane, May 2026).

## 1. Goals and non-goals

### Goals (v1)

1. Provide a single entry point, `Nl2Sql.ask(question) -> Result`, that returns a SQL query plus its executed result rows.
2. Run an agent loop with the four core tools the article identifies: list tables, get full schema, get table schema, and execute SQL. These four together produced 75 to 80 percent accuracy in the article and are the load-bearing primitives.
3. Support **Anthropic** and **OpenAI** as model providers behind a single `LLMClient` interface.
4. Support **Postgres** and **SQLite** out of the box, behind a single `Database` interface, with a path to add other dialects.
5. Let callers attach **domain hints**, both as static strings and as a queryable knowledge store. The article shows hints lift accuracy by 10 to 14 points, so this is not optional flavour, it's a primary feature.
6. Let callers save and reuse **corrected SQL patterns** (the AI/BI Genie feedback mechanism, which lifted accuracy from 69 to 88 percent in the article). v1 ships a simple file-backed store with a clean interface so users can swap in their own.
7. Ship an **eval harness** modelled on LiveSQLBench, with flexible result matching (numeric tolerance, case-insensitive strings, bipartite row matching).

### Non-goals (v1)

- Multi-agent orchestration, planner/executor splits, sub-agents. The article explicitly notes a single agent loop was sufficient; we follow that.
- Write or DDL queries. v1 is read-only, `SELECT` only, enforced.
- Vector search over schema. A flat schema dump fits the prompt for databases up to a few hundred tables; bigger setups can be handled in v2.
- Production observability beyond structured logs. No OpenTelemetry, no metrics endpoints in v1.
- Caching of LLM calls. Out of scope, callers can wrap.
- A web UI or TUI. The CLI ships a rich terminal trace, no full-screen interface in v1.

## 2. The article in one paragraph, for grounding

The ISE team built three NL-to-SQL systems (Copilot CLI, Microsoft Agent Framework, Databricks AI/BI Genie), evaluated them on a LiveSQLBench-derived benchmark of medium-complexity queries against deliberately messy databases, and reached around 75 percent accuracy with custom agent implementations. The findings that drive this library's design are: (a) a small set of schema and execution tools is enough, (b) removing runtime query execution collapses accuracy to 38 percent, so live validation is essential, (c) domain hints injected as prompt context add 10 to 14 points, (d) saving corrected SQL patterns and reusing them adds another 19 points, and (e) the residual error is mostly business-logic confusion that no amount of prompt tuning will fix without domain expertise.

## 3. Library shape

```
nl2sql/
├── __init__.py
├── core.py                  # Nl2Sql class, the public entry point
├── agent.py                 # Agent loop, tool dispatch, message history
├── llm/
│   ├── __init__.py
│   ├── base.py              # LLMClient ABC, ToolDef, Message types
│   ├── anthropic.py         # AnthropicClient
│   └── openai.py            # OpenAIClient
├── db/
│   ├── __init__.py
│   ├── base.py              # Database ABC
│   ├── postgres.py          # PostgresDatabase, via psycopg
│   └── sqlite.py            # SqliteDatabase, via stdlib sqlite3
├── tools.py                 # The four core tools, plus the optional hints tool
├── hints.py                 # DomainHints, KnowledgeStore
├── feedback.py              # FeedbackStore ABC + JsonFeedbackStore
├── safety.py                # SQL allowlist, SELECT-only check, statement-count check
├── prompts.py               # System prompt template, tool descriptions
├── eval/
│   ├── __init__.py
│   ├── harness.py           # run_eval(dataset, system) -> EvalReport
│   ├── matching.py          # flexible result comparison
│   └── livesqlbench.py      # adapter for the LiveSQLBench dataset format
├── cli/
│   ├── __init__.py
│   ├── __main__.py          # `python -m nl2sql`
│   ├── app.py               # Typer app, command registration
│   ├── ask.py               # `nl2sql ask`
│   ├── repl.py              # `nl2sql repl`
│   ├── inspect.py           # `nl2sql inspect schema|tables|table`
│   ├── eval_cmd.py          # `nl2sql eval`
│   ├── feedback_cmd.py      # `nl2sql feedback list|review|forget`
│   ├── hints_cmd.py         # `nl2sql hints validate|show`
│   ├── config.py            # config file loading, profile resolution
│   └── render.py            # rich-based renderers for steps, tables, diffs
├── types.py                 # dataclasses: Result, AgentStep, EvalReport, etc.
└── exceptions.py
```

Total surface area: about a dozen public classes. The four tool functions live in `tools.py` and are bound to a `Database` instance at agent-construction time; the LLM never sees the database directly.

## 4. Public API

The minimum useful program:

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

The fuller form, with hints and feedback:

```python
from nl2sql import Nl2Sql, DomainHints, JsonFeedbackStore
from nl2sql.db import PostgresDatabase
from nl2sql.llm import OpenAIClient

n2s = Nl2Sql(
    db=PostgresDatabase(dsn="postgresql://..."),
    llm=OpenAIClient(model="gpt-5"),
    hints=DomainHints.from_yaml("hints.yaml"),
    feedback=JsonFeedbackStore("./feedback.json"),
    max_iterations=12,
    require_select_only=True,
)

result = n2s.ask("Top 10 customers by 2026 spend, excluding internal accounts")

# After human review:
n2s.feedback.record(
    question=result.question,
    sql=result.sql,
    correct=True,
    notes="internal accounts are flagged by accounts.is_internal",
)
```

### Core types

```python
@dataclass
class Result:
    question: str
    sql: str | None              # None if the agent gave up
    rows: list[dict] | None      # executed result, None on failure
    columns: list[str] | None
    steps: list[AgentStep]       # full trace, for logging or display
    iterations: int
    stopped_reason: Literal["answered", "max_iterations", "tool_error", "no_sql"]
    error: str | None

@dataclass
class AgentStep:
    kind: Literal["llm_message", "tool_call", "tool_result"]
    payload: dict                # tool name + args, or message text, or result
    timestamp: datetime
```

`Result.steps` mirrors the article's interim-message log and is what callers serialise for diagnosis or display.

## 5. The CLI

The CLI is a first-class consumer of the library, not a thin wrapper. It exists for three audiences: developers exploring an unfamiliar database, evaluators running benchmarks, and operators reviewing feedback. Built on Typer (commands and help) and Rich (rendering), invoked as `nl2sql ...` or `python -m nl2sql ...`.

### 5.1 Configuration

The CLI loads config in this order, later overriding earlier:

1. `~/.config/nl2sql/config.yaml`, user defaults
2. `./.nl2sql.yaml` in the current directory, project config
3. `--profile <name>` flag, picks a named profile from either file
4. Environment variables: `NL2SQL_DB_URL`, `NL2SQL_LLM_MODEL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
5. Command-line flags

Sample `.nl2sql.yaml`:

```yaml
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

  prod:
    db: postgresql://reader@db.internal/analytics
    llm:
      provider: openai
      model: gpt-5
    hints: ./hints.prod.yaml
    feedback: s3://nl2sql-feedback/prod.json   # v2, see below
    max_iterations: 15
    require_select_only: true
```

`nl2sql init` scaffolds this file with sensible defaults and a sample `hints.yaml`.

### 5.2 Commands

```
nl2sql ask <question> [options]      Ask a single question, render trace and result
nl2sql repl                           Interactive session against a profile
nl2sql inspect tables                 List all tables in the configured database
nl2sql inspect schema [--table T]     Dump schema, optionally for one table
nl2sql inspect sample <table> [-n 5]  Show n sample rows from a table
nl2sql eval run <dataset>             Run the eval harness, write report
nl2sql eval show <report>             Render a previous report in the terminal
nl2sql feedback list [--correct|--incorrect]   Browse the feedback store
nl2sql feedback review                Walk through unreviewed runs interactively
nl2sql feedback forget <id>           Remove a feedback entry
nl2sql hints validate                 Lint a hints file against the schema
nl2sql hints show [--section S]       Pretty-print the active hints
nl2sql init                           Scaffold .nl2sql.yaml and hints.yaml
nl2sql version                        Print version and resolved profile
```

Global flags on every command: `--profile`, `--db`, `--model`, `--config`, `--quiet`, `--json`, `--no-color`. The two output flags matter: `--json` makes every command emit a single JSON document on stdout for piping (the `Result`, the `EvalReport`, the table list, etc.), while the default human output uses Rich panels and tables.

### 5.3 `nl2sql ask`

The flagship command. Default behaviour: show the agent's reasoning live as it streams tool calls, then render the final SQL with syntax highlighting and the result as a Rich table.

```
$ nl2sql ask "How many customers signed up last quarter?"

╭─ Question ──────────────────────────────────────────────────╮
│ How many customers signed up last quarter?                  │
╰─────────────────────────────────────────────────────────────╯

[1] tool_call  get_db_table_list()
[2] tool_result  customers, orders, products, ... (12 tables)
[3] tool_call  get_tb_table_schema(name='customers')
[4] tool_result  id, email, created_at, country, is_internal
[5] tool_call  query_db("SELECT COUNT(*) FROM customers WHERE created_at >= '2026-01-01' AND created_at < '2026-04-01'")
[6] tool_result  1 row, 1 column

╭─ SQL ───────────────────────────────────────────────────────╮
│ SELECT COUNT(*) AS new_customers                            │
│ FROM customers                                              │
│ WHERE created_at >= '2026-01-01'                            │
│   AND created_at <  '2026-04-01';                           │
╰─────────────────────────────────────────────────────────────╯

┏━━━━━━━━━━━━━━━━┓
┃ new_customers  ┃
┡━━━━━━━━━━━━━━━━┩
│ 1,247          │
└────────────────┘

6 iterations · 4,128 input tokens · 412 output tokens · 2.1s
```

Flags:

```
--max-iterations N         Override the configured limit
--model M                  Override the configured model for this run
--no-trace                 Hide the step-by-step trace, show only SQL and result
--show-prompt              Print the assembled system prompt and exit
--save-trace <path>        Write the full JSONL trace to a file
--explain                  After the result, ask the model for a one-paragraph explanation
--save-feedback            After showing the result, prompt for correct/incorrect/notes
--limit N                  Cap result rows shown (default 50)
```

`--save-feedback` is the bridge from CLI use to the feedback store: every interactive query becomes a candidate for the knowledge base, with a single keystroke.

### 5.4 `nl2sql repl`

An interactive session. Maintains a running history of questions and results within the session, so follow-ups like "now break it down by country" carry context. Prompt-toolkit-driven for line editing, history search, and multi-line input.

REPL meta-commands (prefixed with `\`, like psql):

```
\help                Show all meta-commands
\tables              List tables (alias for `nl2sql inspect tables`)
\schema [table]      Show schema
\sample <table>      Show sample rows
\hints [section]     Show active hints
\last                Show the last result again
\trace               Show the trace of the last query
\save <file>         Save the last SQL to a file
\fb good [notes]     Save last run as correct feedback
\fb bad <correction> Save last run as incorrect with the corrected SQL
\set <key> <value>   Change a config value mid-session (e.g. \set model claude-opus-4-7)
\quit                Exit
```

The REPL is the workhorse for exploring an unfamiliar database. It's also where the feedback flow gets the most use, since the human running it is the one who knows whether the answer is right.

### 5.5 `nl2sql inspect`

Read-only schema and data exploration, no LLM involved. Useful before and during prompt design to see what the agent will see.

```
$ nl2sql inspect tables --json
["amenities", "customers", "households", "orders", "products"]

$ nl2sql inspect schema --table households
households (8 columns)
├─ housenum      INTEGER  PRIMARY KEY
├─ locregion     TEXT     NOT NULL
├─ income_bracket TEXT
├─ ...
└─ FK: locregion → regions(code)

$ nl2sql inspect sample households -n 3
┏━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ housenum ┃ locregion  ┃ income_bracket ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│ 35       │ GUARÁ      │ Medium Income  │
│ ...      │            │                │
```

`inspect sample` is sandboxed by the same safety layer as the agent's `query_db`, capped at `--max-rows`.

### 5.6 `nl2sql eval`

Two subcommands. `eval run` executes the harness against a dataset and writes a report; `eval show` renders a previously-written report.

```
$ nl2sql eval run ./datasets/livesqlbench-medium --parallel 4 --output ./reports/run-001
Running 26 questions across 4 workers...
[████████████████████████] 26/26 in 4m 12s

Accuracy: 76.9% (20/26)
  Schema-only failures:    1
  Business-logic failures: 4
  Tool-error failures:     1

Report written to ./reports/run-001/
  - report.html    (rendered)
  - report.json    (machine-readable)
  - traces/        (one JSONL per question)

$ nl2sql eval show ./reports/run-001 --failures-only
```

The `eval show` view groups failures by category (matching the article's taxonomy: schema, business-logic, tool errors, evaluation false-negatives), and lets you drill into any single trace with `--trace <question-id>`.

Useful flags: `--limit N` (run only first N questions, for smoke testing), `--filter <pattern>` (run only matching questions), `--repeat N` (run each question N times for variance analysis), `--matcher numeric_tolerance=0.001` (override matcher config inline).

### 5.7 `nl2sql feedback`

The feedback loop is the article's highest-leverage capability (19 points), so the CLI gives it real surface area.

```
$ nl2sql feedback list
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ id ┃ question                          ┃ correct ┃ recorded    ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━┩
│ 7  │ Top customers by Q1 spend         │ ✓       │ 2 days ago  │
│ 8  │ Houses in Guará with TV service   │ ✗       │ 1 day ago   │
│ 9  │ Warranty claim rate by category   │ ✓       │ 3 hours ago │

$ nl2sql feedback review
[1/3 unreviewed] "Top customers by Q1 spend, excluding internal"
SQL: SELECT customer_id, SUM(amount) ...
Result: 10 rows

Was this correct? [y/n/skip/quit]: y
Notes (optional): internal flag is accounts.is_internal, agent figured it out

[2/3 unreviewed] ...
```

`feedback review` walks through unreviewed `Result`s saved during prior runs (the `--save-feedback` flag on `ask` and the REPL's `\fb` commands write rows here in an "unreviewed" state). This is how a team builds up a high-quality knowledge base over time without anyone having to write JSON by hand.

### 5.8 `nl2sql hints validate`

Lints a hints file against the live schema. Catches the obvious mistakes: `column_descriptions` for columns that don't exist, `join_rules` referencing nonexistent tables, malformed YAML.

```
$ nl2sql hints validate ./hints.yaml
✗ column_descriptions.households.locregon: column not found (did you mean 'locregion'?)
✗ join_rules[2]: table 'orderss' does not exist (did you mean 'orders'?)
✓ glossary: 12 entries, all keys map to known columns or terms
✓ formulas: 4 entries, syntax valid

2 errors, 0 warnings.
```

Validation runs against the actual configured database, so it's specific. Returns non-zero on errors, suitable for CI.

### 5.9 Output, exit codes, scripting

Every command exits non-zero on user-facing failure (config errors, validation errors, eval failures below a `--threshold`, etc.) and zero on success. With `--json`, all output is a single JSON document on stdout, errors go to stderr. This makes the CLI scriptable:

```bash
# Scripted: ask a question, parse the SQL out, save it
nl2sql ask "..." --json | jq -r .sql > query.sql

# Scripted: fail CI if eval drops below 70%
nl2sql eval run ./bench --threshold 0.70 || exit 1
```

`--quiet` suppresses the trace and progress bars but keeps the final result. `--no-color` disables Rich's styling for log capture. Together they make the CLI well-behaved inside CI logs and shell pipelines.

### 5.10 Why Typer and Rich, not Click + plain prints

Typer gives us type-driven argument parsing (the same dataclasses we use in the library) and excellent `--help` output for free. Rich gives us syntax-highlighted SQL, Rich tables for results, and tree views for schemas, all of which are load-bearing for usability since the agent's output is structured. Both are stable, well-maintained, and don't fight the library's import-first design.

## 6. The agent loop

This is the heart of the library. Pseudocode:

```
messages = [system_prompt, user_question_with_hints]
for i in range(max_iterations):
    response = llm.chat(messages, tools=TOOLS)
    messages.append(response)

    if response.stop_reason == "end_turn":
        return extract_final_sql_and_execute(response)

    for tool_call in response.tool_calls:
        result = dispatch(tool_call, db)
        messages.append(tool_result_message(tool_call.id, result))

return Result(stopped_reason="max_iterations", ...)
```

Notes:

- The loop is provider-agnostic. `LLMClient.chat()` returns a normalised response with `.text`, `.tool_calls`, and `.stop_reason`. Each provider adapter handles its own message-format quirks internally.
- `extract_final_sql_and_execute` does one thing: pulls the last SQL the agent ran successfully via `query_db`, or, failing that, parses the last SQL block from the assistant's final text. We prefer the executed query because we already know it ran.
- `max_iterations` defaults to 10. The article doesn't specify a number, but Copilot CLI runs ranged across single-digit tool calls per query in the example given.

### The four tools (signatures)

```python
def get_db_table_list() -> list[str]
def get_db_schema() -> dict[str, TableSchema]
def get_tb_table_schema(name: str) -> TableSchema
def query_db(sql: str) -> QueryResult     # rows + columns + truncated_at
```

`query_db` enforces three things before execution: it runs the SQL through `safety.is_safe_select(sql)` (rejects DML/DDL/multi-statement), it caps result rows at `max_rows_returned` (default 200, prevents the agent eating its own context with a `SELECT *`), and it caps total query duration at `query_timeout_s` (default 10). These are not optional, they are hard rails.

### Optional fifth tool: domain hint lookup

When `hints` is configured with a `KnowledgeStore` (rather than a flat string), the agent gets a fifth tool:

```python
def lookup_hint(topic: str) -> str | None
```

This mirrors the article's "additional clarification agent tool providing domain knowledge", which moved Agent Framework accuracy from 65 to 69 percent. The default `DictKnowledgeStore` does substring matching on topic keys; users can plug in vector search.

## 7. The LLM interface

```python
class LLMClient(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        max_tokens: int = 4096,
    ) -> LLMResponse: ...

@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict           # JSON schema

@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "stop_sequence"]
    usage: TokenUsage
```

`AnthropicClient` and `OpenAIClient` both translate to and from this normalised shape. We use the official `anthropic` and `openai` Python SDKs as dependencies; we do not roll our own HTTP. Streaming is not supported in v1 because the agent loop needs the full message before deciding whether to dispatch tools.

## 8. The database interface

```python
class Database(ABC):
    dialect: Literal["postgres", "sqlite"]

    @abstractmethod
    def list_tables(self) -> list[str]: ...
    @abstractmethod
    def get_schema(self) -> dict[str, TableSchema]: ...
    @abstractmethod
    def get_table_schema(self, name: str) -> TableSchema: ...
    @abstractmethod
    def execute_select(self, sql: str, *, timeout_s: float, max_rows: int) -> QueryResult: ...

@dataclass
class TableSchema:
    name: str
    columns: list[ColumnSchema]
    primary_key: list[str]
    foreign_keys: list[ForeignKey]
    description: str | None      # populated if the dialect supports COMMENT ON

@dataclass
class ColumnSchema:
    name: str
    data_type: str
    nullable: bool
    description: str | None      # COMMENT ON COLUMN, or column docs from hints
```

Both dialects pull `description` from native comments where present (Postgres has `COMMENT ON COLUMN`, SQLite doesn't, so it falls back to whatever the user attaches via `DomainHints.column_descriptions`).

The article notes Postgres-specific JSON access patterns (`->>`); we don't add JSON helpers to the schema view in v1. The schema dump shows that columns are JSON-typed; the agent figures out the rest, exactly as the article's example demonstrates with `dwelling_specs->>'Dwelling_Class'`.

## 9. Domain hints and the knowledge store

Two shapes:

```python
# Static hints, injected into the system prompt
DomainHints(
    glossary={"locregion": "Region code, uppercase, no diacritics"},
    formulas={"warranty_claim_rate": "returns_with_warranty / total_returns * 100"},
    join_rules=["households.housenum links to properties.houselink"],
    column_descriptions={"households.locregion": "..."},
)

# Queryable hints, exposed as a tool
class KnowledgeStore(ABC):
    @abstractmethod
    def lookup(self, topic: str) -> str | None: ...

DictKnowledgeStore({"income brackets": "...", "warranty claims": "..."})
```

`DomainHints` serialises into the system prompt under explicit headings (`## Glossary`, `## Formulas`, `## Join rules`). Article example:

> Income Classification (value_illustration): Illustrates the income brackets for household economic status. Ranges from 'Low Income' to 'Very High Income'. Null indicates undisclosed or irregular income.

That maps directly to a `glossary` entry keyed on column name.

## 10. Feedback store

The article shows that capturing corrected SQL and replaying it on similar future questions adds 19 points. That mechanism is the third capability in the priority ranking, so v1 ships a working implementation, just a small one.

```python
class FeedbackStore(ABC):
    @abstractmethod
    def record(self, question: str, sql: str, correct: bool, notes: str = "") -> None: ...
    @abstractmethod
    def find_similar(self, question: str, k: int = 3) -> list[FeedbackEntry]: ...

class JsonFeedbackStore(FeedbackStore):
    """File-backed, fuzzy-match by token Jaccard. Good enough for hundreds of entries."""
```

When a feedback store is configured, similar past entries get appended to the system prompt under `## Past validated examples`, with question, SQL, and notes. The agent is told to treat them as guidance, not constraints. Recording is an explicit caller action, not automatic; the library does not assume any given run was correct.

A v2 path is obvious here: swap `JsonFeedbackStore` for a vector-backed store. The interface accommodates that without changes.

## 11. Safety

Three layers, all in `safety.py`:

1. **Single-statement check.** Reject anything that parses to more than one statement. We use `sqlglot.parse` for this rather than splitting on semicolons (which breaks on string literals containing semicolons).
2. **SELECT-only allowlist.** Walk the parsed AST, reject if the root is not `SELECT` or a CTE wrapping a `SELECT`. Also reject any node of type `Insert`, `Update`, `Delete`, `Create`, `Drop`, `Alter`, `Truncate`, `Grant`, `Revoke`.
3. **Identifier denylist** (configurable). By default, refuse to touch `pg_*`, `information_schema`, `sqlite_master`, `sqlite_sequence`. Callers running data exploration can disable this, callers running this against production data should not.

`require_select_only=True` is the default, and is the only sane default. Disabling it requires passing `allow_writes=True` explicitly, which is not a v1 feature regardless; the flag is reserved for v2.

## 12. Eval harness

Mirrors the article's evaluation flow:

```python
from nl2sql.eval import run_eval, LiveSQLBenchDataset

dataset = LiveSQLBenchDataset.from_path("./livesqlbench/medium")
report = run_eval(
    dataset=dataset,
    system=n2s,
    matcher=FlexibleMatcher(
        numeric_tolerance=0.01,
        case_insensitive_strings=True,
        row_matching="bipartite",
    ),
    parallel=4,
)

print(report.accuracy)            # 0.7308
print(report.failures[0].diff)
report.write_html("./eval-report.html")
```

`FlexibleMatcher` implements the article's three rules: numeric tolerance, case-insensitive string compare, and bipartite row matching. The bipartite case is the subtle one; the matcher computes a maximum matching between predicted and ground-truth rows where two rows match if all common columns compare equal under the other rules. This handles duplicate-row cases correctly.

The harness emits one trace file per question, in the same shape the article describes (call/return JSON lines), so failures can be diagnosed without re-running.

## 13. Prompts

The system prompt is templated and lives in `prompts.py`. Skeleton:

```
You are a SQL analyst with access to a {dialect} database. Your job is to answer
the user's question by exploring the schema, inspecting data when useful, and
returning a single SELECT query that retrieves the answer.

You MUST:
- Inspect the schema before writing SQL. Do not guess column names.
- Run intermediate queries to verify your assumptions about data shape.
- Return the final query by calling query_db, not by describing it in text.

You MUST NOT:
- Run any statement other than SELECT.
- Return more than one SQL statement.
- Stop until you have a query that returns plausible results.

{glossary_section}
{formulas_section}
{join_rules_section}
{past_examples_section}
```

The four MUST/MUST NOT items come directly from the article's findings: schema exploration before SQL, runtime validation, single-statement, SELECT-only. They are not negotiable.

The hints sections render only if `DomainHints` provides them, so an empty configuration produces a clean prompt with no dangling headers.

## 14. Logging and tracing

Every `AgentStep` is appended to `Result.steps` and, optionally, written to a JSONL trace file as the run progresses. The format matches the article's example:

```
{"type": "call", "function": "get_db_table_list", "arguments": {}}
{"type": "return", "result": "amenities\nhouseholds\n..."}
```

This is deliberate, callers who want to compare the library's runs to the ISE results can use the same diagnostic format.

## 15. Dependencies

| Package    | Purpose                          | Required |
| ---------- | -------------------------------- | -------- |
| anthropic  | Anthropic API client             | Yes      |
| openai     | OpenAI API client                | Yes      |
| psycopg    | Postgres driver (v3, async-ready) | Yes     |
| sqlglot   | SQL parsing for safety checks    | Yes      |
| typer     | CLI framework                    | Yes      |
| rich      | Terminal rendering for traces, tables, diffs | Yes |
| pyyaml    | Config file and hints parsing    | Yes      |
| sqlite3   | Stdlib, SQLite driver            | Stdlib   |
| pydantic  | Optional, for typed config       | No       |

We avoid SQLAlchemy as a dependency. It's overkill for what we need (read schema, execute SELECT) and adds a heavy import. If users want a SQLAlchemy-backed `Database`, that's a v2 contrib.

## 16. Tests

Three layers, in order of cost:

1. **Unit tests** for safety, matching, hint serialisation, prompt assembly, feedback similarity. No network, no LLM, no database. These run in seconds and gate every commit.
2. **Integration tests** with SQLite and a recorded `LLMClient` (replays canned tool-call transcripts). Verifies the agent loop, tool dispatch, and result extraction without spending API tokens. Recorded transcripts are checked in.
3. **End-to-end smoke tests** against a small Postgres fixture (Docker compose), with real Anthropic and OpenAI calls. Run nightly, not on every commit. Gated by API keys, skipped if absent.

The eval harness, run against a LiveSQLBench subset, is its own thing. We don't run it in CI, it's the user-facing benchmark we expose.

## 17. Known limitations, called out so users don't trip

- **Business-logic errors are not solved by this library.** Quoting the article: domain expertise, comprehensive test coverage, and iterative refinement are required. We surface hints and feedback as the mechanisms for encoding domain knowledge, but we cannot infer it.
- **Schema dumps are flat strings injected into the prompt.** Databases with thousands of tables will blow the context window. v2 adds vector-indexed schema retrieval.
- **No streaming of intermediate steps.** Callers polling for progress get the final `Result`. v2 adds a callback hook on each `AgentStep`.
- **Single-database scope.** v1 binds one `Nl2Sql` instance to one `Database`. Cross-database queries are out of scope.

## 18. Implementation order

A suggested order, mostly to make sure each layer can be tested before the next builds on it:

1. `db/`, both Postgres and SQLite, with a fixture-based unit test
2. `safety.py` with sqlglot
3. `tools.py` wrapping the database
4. `llm/base.py` + the two adapters, against recorded transcripts
5. `prompts.py` and `hints.py`
6. `agent.py`, the loop itself
7. `core.py`, the public `Nl2Sql` class
8. `feedback.py`
9. `cli/`, starting with `inspect` and `ask` (no LLM dependency for inspect, fast feedback), then `repl`, `feedback`, `hints`, then `eval` once the harness lands
10. `eval/` last, since it consumes everything else

Each step has its own tests, and the agent loop in step 6 is the only thing that touches all the pieces. The CLI in step 9 is a thin layer over the library; building it before the eval harness gives us a usable tool early without blocking on benchmark work.

## 19. Open questions, to flag before writing code

1. Should `Nl2Sql.ask` be sync, async, or both? Library-style code in 2026 leans async-first; the LLM and database calls are all I/O. My default is to write the core async, with a thin sync wrapper, but happy to flip.
2. Should we expose token usage and cost in `Result`? Trivial to add, pulls a number from each provider's response. Worth it.
3. Where do we surface partial results when the agent hits `max_iterations`? Current proposal: return whatever the last successful `query_db` returned, with `stopped_reason="max_iterations"`. Alternative: return nothing and force the caller to inspect `steps`.

If those land in obvious places I'll bake them in; if they're contentious we resolve before coding.