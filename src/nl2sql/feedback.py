"""Feedback store: corrected SQL examples replayed on similar questions."""
from __future__ import annotations

import json
import re
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FeedbackEntry:
    id: str
    question: str
    sql: str
    correct: bool
    notes: str = ""
    recorded_at: str = field(default_factory=_now_iso)
    reviewed: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_]+")


def _tokens(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(s or "") if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


class FeedbackStore(ABC):
    @abstractmethod
    def record(
        self,
        question: str,
        sql: str,
        correct: bool,
        notes: str = "",
        *,
        reviewed: bool = True,
    ) -> FeedbackEntry: ...

    @abstractmethod
    def find_similar(
        self, question: str, k: int = 3, *, only_correct: bool = True
    ) -> list[FeedbackEntry]: ...

    @abstractmethod
    def list(self) -> list[FeedbackEntry]: ...

    @abstractmethod
    def get(self, entry_id: str) -> Optional[FeedbackEntry]: ...

    @abstractmethod
    def forget(self, entry_id: str) -> bool: ...


class JsonFeedbackStore(FeedbackStore):
    """File-backed store using token Jaccard similarity for retrieval."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"entries": []}, indent=2))

    def _load(self) -> list[FeedbackEntry]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return []
        out: list[FeedbackEntry] = []
        for raw in data.get("entries", []):
            try:
                out.append(FeedbackEntry(**raw))
            except TypeError:
                # Tolerant of extra fields.
                out.append(
                    FeedbackEntry(
                        id=raw.get("id") or uuid.uuid4().hex[:8],
                        question=raw["question"],
                        sql=raw["sql"],
                        correct=bool(raw.get("correct", False)),
                        notes=raw.get("notes", ""),
                        recorded_at=raw.get("recorded_at", _now_iso()),
                        reviewed=bool(raw.get("reviewed", True)),
                    )
                )
        return out

    def _save(self, entries: list[FeedbackEntry]) -> None:
        self.path.write_text(
            json.dumps(
                {"entries": [e.to_dict() for e in entries]}, indent=2, default=str
            ),
            encoding="utf-8",
        )

    def record(
        self,
        question: str,
        sql: str,
        correct: bool,
        notes: str = "",
        *,
        reviewed: bool = True,
    ) -> FeedbackEntry:
        with self._lock:
            entries = self._load()
            entry = FeedbackEntry(
                id=uuid.uuid4().hex[:8],
                question=question,
                sql=sql,
                correct=correct,
                notes=notes,
                reviewed=reviewed,
            )
            entries.append(entry)
            self._save(entries)
            return entry

    def find_similar(
        self, question: str, k: int = 3, *, only_correct: bool = True
    ) -> list[FeedbackEntry]:
        if not question:
            return []
        q_tokens = _tokens(question)
        scored: list[tuple[float, FeedbackEntry]] = []
        for e in self._load():
            if only_correct and not e.correct:
                continue
            score = _jaccard(q_tokens, _tokens(e.question))
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:k]]

    def list(self) -> list[FeedbackEntry]:
        return self._load()

    def get(self, entry_id: str) -> Optional[FeedbackEntry]:
        for e in self._load():
            if e.id == entry_id:
                return e
        return None

    def forget(self, entry_id: str) -> bool:
        with self._lock:
            entries = self._load()
            new = [e for e in entries if e.id != entry_id]
            if len(new) == len(entries):
                return False
            self._save(new)
            return True
