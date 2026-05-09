"""SQL safety layer: single statement, SELECT-only, identifier denylist.

Implements three checks the spec calls hard rails:

1. Single statement (parse with sqlglot, reject multi-statement).
2. Root expression must be SELECT or a CTE wrapping SELECT.
3. Identifier denylist by default: pg_*, information_schema, sqlite_master,
   sqlite_sequence. Configurable via ``deny_system_tables=False``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import sqlglot
from sqlglot import exp

from .exceptions import SafetyError


# Forbidden statement types in the AST. These are top-level rejects regardless
# of where they appear (subqueries, CTE bodies, etc.).
_FORBIDDEN_NODES: tuple[type, ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.AlterColumn,
    exp.TruncateTable,
    exp.Grant,
    exp.Command,  # generic catch-all for unparsed DDL like TRUNCATE/GRANT
)

# System / metadata tables we never want the agent reading by default.
_DEFAULT_DENY_PREFIXES = ("pg_", "sqlite_")
_DEFAULT_DENY_EXACT = frozenset(
    {
        "information_schema",
        "sqlite_master",
        "sqlite_sequence",
        "sqlite_temp_master",
        "pg_catalog",
    }
)


@dataclass
class SafetyVerdict:
    ok: bool
    reason: Optional[str] = None
    normalised_sql: Optional[str] = None


def _iter_table_names(tree: exp.Expression) -> Iterable[str]:
    """Yield every table identifier the AST references."""
    for table in tree.find_all(exp.Table):
        if table.this is None:
            continue
        # Both schema-qualified and bare names. We yield each part, lowercased.
        if table.db:
            yield str(table.db).lower()
        if table.name:
            yield str(table.name).lower()


def _is_denied(name: str) -> bool:
    n = name.lower()
    if n in _DEFAULT_DENY_EXACT:
        return True
    for pfx in _DEFAULT_DENY_PREFIXES:
        if n.startswith(pfx):
            # pg_user, pg_class, sqlite_master, etc.
            return True
    return False


def _is_select_root(stmt: exp.Expression) -> bool:
    """True if the statement is a SELECT or a CTE wrapping a SELECT."""
    if isinstance(stmt, exp.Select):
        return True
    if isinstance(stmt, exp.Subquery):
        return _is_select_root(stmt.this)
    if isinstance(stmt, exp.With):
        # WITH ... SELECT ...
        return _is_select_root(stmt.this) if stmt.this else False
    if isinstance(stmt, exp.Union):
        # UNION/INTERSECT/EXCEPT of SELECTs
        return True
    return False


def is_safe_select(
    sql: str,
    *,
    deny_system_tables: bool = True,
    dialect: Optional[str] = None,
) -> SafetyVerdict:
    """Inspect ``sql`` and return a verdict.

    Never raises. Use :func:`enforce_safe_select` to convert a bad verdict
    into a :class:`SafetyError`.
    """
    if sql is None or not sql.strip():
        return SafetyVerdict(ok=False, reason="Empty SQL.")

    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError as e:
        return SafetyVerdict(ok=False, reason=f"Parse error: {e}")
    except Exception as e:  # pragma: no cover - defensive
        return SafetyVerdict(ok=False, reason=f"Parse error: {e}")

    statements = [s for s in statements if s is not None]
    if not statements:
        return SafetyVerdict(ok=False, reason="No parseable statement.")
    if len(statements) > 1:
        return SafetyVerdict(
            ok=False, reason="Multiple statements not allowed; expected a single SELECT."
        )

    stmt = statements[0]

    # Forbidden statement nodes anywhere in the tree.
    for node in stmt.walk():
        # sqlglot's walk yields (expression, parent, key)
        expr = node[0] if isinstance(node, tuple) else node
        if isinstance(expr, _FORBIDDEN_NODES):
            return SafetyVerdict(
                ok=False,
                reason=f"Only SELECT is allowed; saw {type(expr).__name__}.",
            )

    if not _is_select_root(stmt):
        return SafetyVerdict(
            ok=False,
            reason=f"Only SELECT is allowed; saw {type(stmt).__name__}.",
        )

    if deny_system_tables:
        for name in _iter_table_names(stmt):
            if _is_denied(name):
                return SafetyVerdict(
                    ok=False,
                    reason=f"Identifier '{name}' is on the system-table denylist.",
                )

    try:
        normalised = stmt.sql(dialect=dialect)
    except Exception:
        normalised = sql.strip().rstrip(";")
    return SafetyVerdict(ok=True, normalised_sql=normalised)


def enforce_safe_select(
    sql: str,
    *,
    deny_system_tables: bool = True,
    dialect: Optional[str] = None,
) -> str:
    """Run :func:`is_safe_select` and raise :class:`SafetyError` on failure.

    Returns the normalised SQL on success.
    """
    verdict = is_safe_select(
        sql, deny_system_tables=deny_system_tables, dialect=dialect
    )
    if not verdict.ok:
        raise SafetyError(verdict.reason or "SQL rejected by safety layer.")
    return verdict.normalised_sql or sql
