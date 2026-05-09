"""LiveSQLBench dataset adapter (and a generic JSONL fallback)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from ..types import EvalCase


@dataclass
class LiveSQLBenchDataset:
    """A directory- or file-backed dataset of NL2SQL questions.

    Recognised layouts:
    - A single .jsonl file with one case per line, fields:
      ``id``, ``question``, ``expected_sql`` (optional), ``expected_rows``
      (optional list of dicts), ``category`` (optional).
    - A directory containing ``cases.jsonl`` plus optional metadata.
    """

    cases: list[EvalCase]
    name: str = "livesqlbench"

    def __iter__(self) -> Iterator[EvalCase]:
        return iter(self.cases)

    def __len__(self) -> int:
        return len(self.cases)

    @classmethod
    def from_path(cls, path: str | Path) -> "LiveSQLBenchDataset":
        p = Path(path)
        if p.is_dir():
            jsonl = p / "cases.jsonl"
            if not jsonl.exists():
                raise FileNotFoundError(f"No cases.jsonl in {p}")
            return cls.from_jsonl(jsonl)
        return cls.from_jsonl(p)

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "LiveSQLBenchDataset":
        cases: list[EvalCase] = []
        with Path(path).open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                cases.append(
                    EvalCase(
                        id=str(obj.get("id") or len(cases) + 1),
                        question=obj["question"],
                        expected_sql=obj.get("expected_sql"),
                        expected_rows=obj.get("expected_rows"),
                        category=obj.get("category"),
                        metadata={
                            k: v
                            for k, v in obj.items()
                            if k
                            not in (
                                "id",
                                "question",
                                "expected_sql",
                                "expected_rows",
                                "category",
                            )
                        },
                    )
                )
        return cls(cases=cases, name=Path(path).stem)
