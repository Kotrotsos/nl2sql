"""Domain hints and knowledge stores."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DomainHints:
    """Static hints injected into the system prompt."""

    glossary: dict[str, str] = field(default_factory=dict)
    formulas: dict[str, str] = field(default_factory=dict)
    join_rules: list[str] = field(default_factory=list)
    column_descriptions: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (
            self.glossary
            or self.formulas
            or self.join_rules
            or self.column_descriptions
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "DomainHints":
        import yaml

        p = Path(path)
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "DomainHints":
        return cls(
            glossary=dict(data.get("glossary", {}) or {}),
            formulas=dict(data.get("formulas", {}) or {}),
            join_rules=list(data.get("join_rules", []) or []),
            column_descriptions=dict(data.get("column_descriptions", {}) or {}),
        )

    def to_dict(self) -> dict:
        return {
            "glossary": self.glossary,
            "formulas": self.formulas,
            "join_rules": self.join_rules,
            "column_descriptions": self.column_descriptions,
        }


class KnowledgeStore(ABC):
    """Queryable hints, exposed to the agent as the ``lookup_hint`` tool."""

    @abstractmethod
    def lookup(self, topic: str) -> Optional[str]:
        """Return the entry whose key best matches ``topic``, or ``None``."""

    def keys(self) -> list[str]:  # pragma: no cover - default impl
        return []


class DictKnowledgeStore(KnowledgeStore):
    """In-memory store, substring match on lowercased keys."""

    def __init__(self, entries: dict[str, str]):
        self._entries = dict(entries)

    def lookup(self, topic: str) -> Optional[str]:
        if not topic:
            return None
        t = topic.strip().lower()
        # Exact match first.
        for k, v in self._entries.items():
            if k.lower() == t:
                return v
        # Substring match (either direction).
        for k, v in self._entries.items():
            kl = k.lower()
            if t in kl or kl in t:
                return v
        return None

    def keys(self) -> list[str]:
        return list(self._entries.keys())
