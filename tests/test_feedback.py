"""JsonFeedbackStore tests."""
from __future__ import annotations

from pathlib import Path

from nl2sql.feedback import JsonFeedbackStore


class TestRecordAndList:
    def test_record_returns_entry(self, tmp_path: Path):
        store = JsonFeedbackStore(tmp_path / "fb.json")
        e = store.record("Q?", "SELECT 1", correct=True, notes="ok")
        assert e.id
        assert e.correct is True
        assert e.notes == "ok"

    def test_list_returns_recorded(self, tmp_path: Path):
        store = JsonFeedbackStore(tmp_path / "fb.json")
        store.record("Q1", "SELECT 1", correct=True)
        store.record("Q2", "SELECT 2", correct=False)
        entries = store.list()
        assert len(entries) == 2

    def test_persists_across_instances(self, tmp_path: Path):
        path = tmp_path / "fb.json"
        s1 = JsonFeedbackStore(path)
        s1.record("Q1", "SELECT 1", correct=True)
        s2 = JsonFeedbackStore(path)
        assert len(s2.list()) == 1


class TestSimilarity:
    def test_similar_returns_overlapping_tokens(self, tmp_path: Path):
        store = JsonFeedbackStore(tmp_path / "fb.json")
        store.record(
            "Top customers by spend in 2026",
            "SELECT customer_id, SUM(amount) FROM orders GROUP BY 1",
            correct=True,
        )
        store.record(
            "How many warranty claims last quarter",
            "SELECT COUNT(*) FROM claims",
            correct=True,
        )
        sim = store.find_similar("Top customers by 2026 spend", k=1)
        assert len(sim) == 1
        assert "customers" in sim[0].question.lower()

    def test_only_correct_filters(self, tmp_path: Path):
        store = JsonFeedbackStore(tmp_path / "fb.json")
        store.record("Top customers", "SELECT 1", correct=False)
        sim = store.find_similar("top customers", only_correct=True)
        assert sim == []

    def test_empty_query_returns_empty(self, tmp_path: Path):
        store = JsonFeedbackStore(tmp_path / "fb.json")
        store.record("Q", "SELECT 1", correct=True)
        assert store.find_similar("") == []


class TestForget:
    def test_forget_existing_returns_true(self, tmp_path: Path):
        store = JsonFeedbackStore(tmp_path / "fb.json")
        e = store.record("Q", "SELECT 1", correct=True)
        assert store.forget(e.id) is True
        assert store.list() == []

    def test_forget_unknown_returns_false(self, tmp_path: Path):
        store = JsonFeedbackStore(tmp_path / "fb.json")
        assert store.forget("nonexistent") is False
