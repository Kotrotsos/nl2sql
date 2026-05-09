"""SQLite Database adapter tests."""
from __future__ import annotations

import pytest

from nl2sql.db import SqliteDatabase
from nl2sql.exceptions import DatabaseError


class TestListTables:
    def test_lists_user_tables(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        tables = db.list_tables()
        assert "customers" in tables
        assert "orders" in tables
        assert "products" in tables

    def test_excludes_system_tables(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        tables = db.list_tables()
        assert all(not t.startswith("sqlite_") for t in tables)


class TestSchema:
    def test_get_table_schema_returns_columns(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        ts = db.get_table_schema("customers")
        names = [c.name for c in ts.columns]
        assert names == ["id", "email", "country", "is_internal", "created_at"]

    def test_primary_key_detected(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        ts = db.get_table_schema("customers")
        assert ts.primary_key == ["id"]

    def test_foreign_keys_detected(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        ts = db.get_table_schema("orders")
        ref_tables = {fk.ref_table for fk in ts.foreign_keys}
        assert {"customers", "products"} <= ref_tables

    def test_get_schema_returns_all_tables(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        schema = db.get_schema()
        assert {"customers", "orders", "products"} <= set(schema.keys())

    def test_unknown_table_raises(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        with pytest.raises(DatabaseError):
            db.get_table_schema("does_not_exist")


class TestExecuteSelect:
    def test_simple_count(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        qr = db.execute_select(
            "SELECT COUNT(*) AS n FROM customers", timeout_s=5, max_rows=10
        )
        assert qr.columns == ["n"]
        assert qr.rows == [{"n": 5}]

    def test_returns_rows_as_dicts(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        qr = db.execute_select(
            "SELECT id, country FROM customers ORDER BY id",
            timeout_s=5,
            max_rows=10,
        )
        assert qr.rows[0] == {"id": 1, "country": "NL"}

    def test_truncates_at_max_rows(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        qr = db.execute_select(
            "SELECT id FROM customers ORDER BY id", timeout_s=5, max_rows=2
        )
        assert len(qr.rows) == 2
        assert qr.truncated_at == 2

    def test_invalid_sql_raises(self, sample_db_path):
        db = SqliteDatabase(sample_db_path)
        with pytest.raises(DatabaseError):
            db.execute_select(
                "SELECT * FROM nonexistent", timeout_s=5, max_rows=10
            )
