"""System prompt assembly. Hint sections render only if non-empty."""
from __future__ import annotations

from typing import Optional

from .hints import DomainHints

_BASE_PROMPT = """\
You are a SQL analyst with access to a {dialect} database. Your job is to
answer the user's question by exploring the schema, inspecting data when
useful, and returning a single SELECT query that retrieves the answer.

You MUST:
- Inspect the schema before writing SQL. Do not guess column names.
- Run intermediate queries to verify your assumptions about data shape.
- Return the final query by calling query_db, not by describing it in text.

You MUST NOT:
- Run any statement other than SELECT.
- Return more than one SQL statement.
- Stop until you have a query that returns plausible results.

When the question is answered, finish with a brief one-sentence summary of
the result. Do not output additional SQL after the final query_db call.
"""


def build_system_prompt(
    dialect: str,
    *,
    hints: Optional[DomainHints] = None,
    similar_examples: Optional[list[dict]] = None,
    knowledge_store_keys: Optional[list[str]] = None,
) -> str:
    parts: list[str] = [_BASE_PROMPT.format(dialect=dialect)]

    if hints and not hints.is_empty():
        if hints.glossary:
            parts.append("\n## Glossary\n")
            for k, v in hints.glossary.items():
                parts.append(f"- **{k}** — {v}\n")
        if hints.column_descriptions:
            parts.append("\n## Column descriptions\n")
            for k, v in hints.column_descriptions.items():
                parts.append(f"- `{k}`: {v}\n")
        if hints.formulas:
            parts.append("\n## Formulas\n")
            for k, v in hints.formulas.items():
                parts.append(f"- **{k}** = {v}\n")
        if hints.join_rules:
            parts.append("\n## Join rules\n")
            for r in hints.join_rules:
                parts.append(f"- {r}\n")

    if knowledge_store_keys:
        parts.append(
            "\n## Domain knowledge tool\n"
            "A `lookup_hint(topic)` tool is available. Use it when you encounter "
            "an unfamiliar domain term, column name, or business concept.\n"
            "Known topics include: " + ", ".join(knowledge_store_keys) + "\n"
        )

    if similar_examples:
        parts.append(
            "\n## Past validated examples\n"
            "Treat these as guidance, not constraints. They are similar past "
            "questions that were confirmed correct.\n"
        )
        for ex in similar_examples:
            parts.append(
                f"\nQ: {ex['question']}\nSQL:\n```sql\n{ex['sql'].strip()}\n```\n"
            )
            if ex.get("notes"):
                parts.append(f"Notes: {ex['notes']}\n")

    return "".join(parts).strip() + "\n"
