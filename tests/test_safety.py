"""BDD-style tests for the SQL safety layer."""
from __future__ import annotations

import pytest

from nl2sql.safety import (
    is_safe_select,
    SafetyVerdict,
    enforce_safe_select,
)
from nl2sql.exceptions import SafetyError


class TestSingleStatementCheck:
    def test_simple_select_is_allowed(self):
        verdict = is_safe_select("SELECT 1")
        assert verdict.ok is True
        assert verdict.reason is None

    def test_two_statements_rejected(self):
        verdict = is_safe_select("SELECT 1; SELECT 2;")
        assert verdict.ok is False
        assert "single" in verdict.reason.lower() or "multiple" in verdict.reason.lower()

    def test_trailing_semicolon_allowed(self):
        verdict = is_safe_select("SELECT 1;")
        assert verdict.ok is True

    def test_semicolon_in_string_literal_allowed(self):
        # Semicolons inside string literals must not be parsed as separators.
        verdict = is_safe_select("SELECT 'a;b' AS s")
        assert verdict.ok is True


class TestSelectOnly:
    def test_insert_rejected(self):
        verdict = is_safe_select("INSERT INTO t (x) VALUES (1)")
        assert verdict.ok is False
        assert "select" in verdict.reason.lower()

    def test_update_rejected(self):
        verdict = is_safe_select("UPDATE t SET x = 1 WHERE y = 2")
        assert verdict.ok is False

    def test_delete_rejected(self):
        verdict = is_safe_select("DELETE FROM t")
        assert verdict.ok is False

    def test_drop_rejected(self):
        verdict = is_safe_select("DROP TABLE t")
        assert verdict.ok is False

    def test_create_rejected(self):
        verdict = is_safe_select("CREATE TABLE t (x INTEGER)")
        assert verdict.ok is False

    def test_alter_rejected(self):
        verdict = is_safe_select("ALTER TABLE t ADD COLUMN y INTEGER")
        assert verdict.ok is False

    def test_truncate_rejected(self):
        verdict = is_safe_select("TRUNCATE TABLE t")
        assert verdict.ok is False

    def test_grant_rejected(self):
        verdict = is_safe_select("GRANT SELECT ON t TO public")
        assert verdict.ok is False

    def test_cte_select_allowed(self):
        sql = """
        WITH recent AS (SELECT * FROM customers WHERE created_at > '2026-01-01')
        SELECT COUNT(*) FROM recent
        """
        verdict = is_safe_select(sql)
        assert verdict.ok is True

    def test_subquery_select_allowed(self):
        sql = "SELECT * FROM (SELECT id FROM customers) sub"
        verdict = is_safe_select(sql)
        assert verdict.ok is True


class TestIdentifierDenylist:
    def test_information_schema_rejected(self):
        verdict = is_safe_select("SELECT * FROM information_schema.tables")
        assert verdict.ok is False
        assert "denied" in verdict.reason.lower() or "denylist" in verdict.reason.lower()

    def test_pg_catalog_rejected(self):
        verdict = is_safe_select("SELECT * FROM pg_catalog.pg_class")
        assert verdict.ok is False

    def test_pg_prefix_table_rejected(self):
        verdict = is_safe_select("SELECT * FROM pg_user")
        assert verdict.ok is False

    def test_sqlite_master_rejected(self):
        verdict = is_safe_select("SELECT name FROM sqlite_master")
        assert verdict.ok is False

    def test_sqlite_sequence_rejected(self):
        verdict = is_safe_select("SELECT * FROM sqlite_sequence")
        assert verdict.ok is False

    def test_user_can_disable_denylist(self):
        verdict = is_safe_select(
            "SELECT name FROM sqlite_master", deny_system_tables=False
        )
        assert verdict.ok is True

    def test_user_table_named_pgsomething_allowed(self):
        # Only the pg_ system prefix is denied; arbitrary 'pgsomething' is fine.
        verdict = is_safe_select("SELECT * FROM pgservice")
        assert verdict.ok is True


class TestEnforce:
    def test_enforce_returns_normalised_sql(self):
        normalised = enforce_safe_select("select 1")
        assert isinstance(normalised, str)
        assert "1" in normalised

    def test_enforce_raises_on_insert(self):
        with pytest.raises(SafetyError):
            enforce_safe_select("INSERT INTO t (x) VALUES (1)")

    def test_enforce_raises_on_multi_statement(self):
        with pytest.raises(SafetyError):
            enforce_safe_select("SELECT 1; SELECT 2")


class TestParseFailure:
    def test_garbage_input_rejected(self):
        verdict = is_safe_select("not a sql statement")
        assert verdict.ok is False

    def test_empty_input_rejected(self):
        verdict = is_safe_select("")
        assert verdict.ok is False

    def test_whitespace_only_rejected(self):
        verdict = is_safe_select("   \n   ")
        assert verdict.ok is False
