"""Core dataclasses for nl2sql."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ColumnSchema:
    name: str
    data_type: str
    nullable: bool = True
    description: Optional[str] = None
    default: Optional[str] = None


@dataclass
class ForeignKey:
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


@dataclass
class TableSchema:
    name: str
    columns: list[ColumnSchema]
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    description: Optional[str] = None

    def to_text(self) -> str:
        """Compact textual rendering for prompt injection."""
        lines = [f"TABLE {self.name}"]
        if self.description:
            lines.append(f"  -- {self.description}")
        for col in self.columns:
            null = "NULL" if col.nullable else "NOT NULL"
            line = f"  {col.name} {col.data_type} {null}"
            if col.description:
                line += f"  -- {col.description}"
            lines.append(line)
        if self.primary_key:
            lines.append(f"  PRIMARY KEY ({', '.join(self.primary_key)})")
        for fk in self.foreign_keys:
            lines.append(
                f"  FOREIGN KEY ({', '.join(fk.columns)}) REFERENCES "
                f"{fk.ref_table}({', '.join(fk.ref_columns)})"
            )
        return "\n".join(lines)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated_at: Optional[int] = None
    elapsed_ms: float = 0.0

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: Any  # may be str or structured (tool_use blocks, tool_result blocks)


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "error"]
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: Any = None  # provider-specific raw object, for debugging


@dataclass
class AgentStep:
    kind: Literal["llm_message", "tool_call", "tool_result"]
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


@dataclass
class Result:
    question: str
    sql: Optional[str] = None
    rows: Optional[list[dict[str, Any]]] = None
    columns: Optional[list[str]] = None
    steps: list[AgentStep] = field(default_factory=list)
    iterations: int = 0
    stopped_reason: Literal[
        "answered", "max_iterations", "tool_error", "no_sql", "llm_error"
    ] = "no_sql"
    error: Optional[str] = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "sql": self.sql,
            "rows": self.rows,
            "columns": self.columns,
            "steps": [s.to_dict() for s in self.steps],
            "iterations": self.iterations,
            "stopped_reason": self.stopped_reason,
            "error": self.error,
            "usage": asdict(self.usage),
            "elapsed_s": self.elapsed_s,
        }


@dataclass
class EvalCase:
    """A single evaluation question with expected output."""
    id: str
    question: str
    expected_sql: Optional[str] = None
    expected_rows: Optional[list[dict[str, Any]]] = None
    category: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalCaseResult:
    case_id: str
    question: str
    predicted_sql: Optional[str]
    predicted_rows: Optional[list[dict[str, Any]]]
    expected_rows: Optional[list[dict[str, Any]]]
    passed: bool
    failure_category: Optional[
        Literal["schema", "business_logic", "tool_error", "false_negative", "no_sql"]
    ] = None
    diff: Optional[str] = None
    elapsed_s: float = 0.0
    iterations: int = 0


@dataclass
class EvalReport:
    cases: list[EvalCaseResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=_now)
    finished_at: Optional[datetime] = None

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def accuracy(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    @property
    def failures(self) -> list[EvalCaseResult]:
        return [c for c in self.cases if not c.passed]

    def write_html(self, path: str) -> None:
        from .eval.harness import _render_html_report
        _render_html_report(self, path)

    def write_json(self, path: str) -> None:
        import json
        d = {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "accuracy": self.accuracy,
            "cases": [
                {
                    "case_id": c.case_id,
                    "question": c.question,
                    "predicted_sql": c.predicted_sql,
                    "predicted_rows": c.predicted_rows,
                    "expected_rows": c.expected_rows,
                    "passed": c.passed,
                    "failure_category": c.failure_category,
                    "diff": c.diff,
                    "elapsed_s": c.elapsed_s,
                    "iterations": c.iterations,
                }
                for c in self.cases
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, default=str)
