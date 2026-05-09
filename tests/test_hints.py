"""DomainHints + KnowledgeStore tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from nl2sql.hints import DictKnowledgeStore, DomainHints


class TestDomainHints:
    def test_empty_hints_is_empty(self):
        h = DomainHints()
        assert h.is_empty() is True

    def test_glossary_makes_non_empty(self):
        h = DomainHints(glossary={"a": "b"})
        assert h.is_empty() is False

    def test_to_dict_round_trip(self):
        h = DomainHints(
            glossary={"locregion": "region code"},
            formulas={"r": "x/y"},
            join_rules=["t1.id = t2.id"],
            column_descriptions={"t.c": "desc"},
        )
        d = h.to_dict()
        h2 = DomainHints.from_dict(d)
        assert h2 == h

    def test_from_yaml(self, tmp_path: Path):
        p = tmp_path / "hints.yaml"
        p.write_text(
            "glossary:\n  region: 'A code'\nformulas:\n  ratio: 'a/b'\n"
            "join_rules:\n  - 't1.id = t2.id'\ncolumn_descriptions:\n  t.c: 'desc'\n"
        )
        h = DomainHints.from_yaml(p)
        assert h.glossary == {"region": "A code"}
        assert h.formulas == {"ratio": "a/b"}
        assert h.join_rules == ["t1.id = t2.id"]
        assert h.column_descriptions == {"t.c": "desc"}


class TestDictKnowledgeStore:
    def test_exact_match(self):
        ks = DictKnowledgeStore({"income": "buckets"})
        assert ks.lookup("income") == "buckets"

    def test_case_insensitive(self):
        ks = DictKnowledgeStore({"Income": "buckets"})
        assert ks.lookup("income") == "buckets"

    def test_substring(self):
        ks = DictKnowledgeStore({"income brackets": "ranges"})
        assert ks.lookup("brackets") == "ranges"

    def test_no_match(self):
        ks = DictKnowledgeStore({"a": "b"})
        assert ks.lookup("c") is None

    def test_empty_topic(self):
        ks = DictKnowledgeStore({"a": "b"})
        assert ks.lookup("") is None

    def test_keys(self):
        ks = DictKnowledgeStore({"a": "1", "b": "2"})
        assert set(ks.keys()) == {"a", "b"}
