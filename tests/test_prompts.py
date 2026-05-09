"""Prompt assembly tests."""
from __future__ import annotations

from nl2sql.hints import DomainHints
from nl2sql.prompts import build_system_prompt


class TestBaseRules:
    def test_includes_must_inspect_schema(self):
        sp = build_system_prompt(dialect="sqlite")
        assert "Inspect the schema before writing SQL" in sp

    def test_includes_select_only(self):
        sp = build_system_prompt(dialect="sqlite")
        assert "Run any statement other than SELECT" in sp or "SELECT" in sp

    def test_dialect_substituted(self):
        sp = build_system_prompt(dialect="postgres")
        assert "postgres" in sp


class TestHintSections:
    def test_empty_hints_omits_section_headers(self):
        sp = build_system_prompt(dialect="sqlite", hints=DomainHints())
        assert "## Glossary" not in sp
        assert "## Formulas" not in sp
        assert "## Join rules" not in sp

    def test_glossary_renders(self):
        sp = build_system_prompt(
            dialect="sqlite",
            hints=DomainHints(glossary={"locregion": "Region code, uppercase"}),
        )
        assert "## Glossary" in sp
        assert "locregion" in sp
        assert "Region code, uppercase" in sp

    def test_formulas_render(self):
        sp = build_system_prompt(
            dialect="sqlite",
            hints=DomainHints(formulas={"rate": "a / b"}),
        )
        assert "## Formulas" in sp
        assert "rate" in sp
        assert "a / b" in sp

    def test_join_rules_render(self):
        sp = build_system_prompt(
            dialect="sqlite",
            hints=DomainHints(join_rules=["a.x = b.y"]),
        )
        assert "## Join rules" in sp
        assert "a.x = b.y" in sp


class TestSimilarExamples:
    def test_examples_section_renders(self):
        sp = build_system_prompt(
            dialect="sqlite",
            similar_examples=[
                {"question": "Top customers", "sql": "SELECT 1", "notes": "n"}
            ],
        )
        assert "Past validated examples" in sp
        assert "Top customers" in sp
        assert "SELECT 1" in sp


class TestKnowledgeStoreKeys:
    def test_keys_listed_when_present(self):
        sp = build_system_prompt(
            dialect="sqlite", knowledge_store_keys=["income", "warranty"]
        )
        assert "lookup_hint" in sp
        assert "income" in sp
