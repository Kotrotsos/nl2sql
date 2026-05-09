"""Postgres implementation of :class:`Database` via psycopg v3."""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from ..exceptions import DatabaseError
from ..types import ColumnSchema, ForeignKey, QueryResult, TableSchema
from .base import Database


class PostgresDatabase(Database):
    """Postgres via psycopg (v3). Lazy import so the dep is optional."""

    dialect = "postgres"

    def __init__(self, dsn: str, *, schema: str = "public"):
        try:
            import psycopg  # noqa: F401
        except ImportError as e:  # pragma: no cover - exercised only when psycopg missing
            raise DatabaseError(
                "psycopg is required for PostgresDatabase. "
                "Install with `pip install nl2sql[postgres]`."
            ) from e
        self.dsn = dsn
        self.schema = schema
        self._lock = threading.Lock()
        self._conn = self._open()

    def _open(self):
        import psycopg

        try:
            conn = psycopg.connect(self.dsn, autocommit=True)
        except psycopg.Error as e:
            raise DatabaseError(f"Failed to connect to Postgres: {e}") from e
        return conn

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def list_tables(self) -> list[str]:
        with self._lock, self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_type IN ('BASE TABLE','VIEW')
                ORDER BY table_name
                """,
                (self.schema,),
            )
            return [r[0] for r in cur.fetchall()]

    def get_schema(self) -> dict[str, TableSchema]:
        return {name: self.get_table_schema(name) for name in self.list_tables()}

    def get_table_schema(self, name: str) -> TableSchema:
        with self._lock, self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default,
                       col_description(
                         (table_schema || '.' || table_name)::regclass::oid,
                         ordinal_position)
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (self.schema, name),
            )
            cols_raw = cur.fetchall()
            if not cols_raw:
                raise DatabaseError(f"Unknown table '{name}'.")
            columns = [
                ColumnSchema(
                    name=cn,
                    data_type=dt,
                    nullable=(nl == "YES"),
                    default=str(dv) if dv is not None else None,
                    description=desc,
                )
                for cn, dt, nl, dv, desc in cols_raw
            ]

            cur.execute(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = %s
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
                """,
                (self.schema, name),
            )
            primary_key = [r[0] for r in cur.fetchall()]

            cur.execute(
                """
                SELECT tc.constraint_name,
                       kcu.column_name,
                       ccu.table_name AS ref_table,
                       ccu.column_name AS ref_col
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.table_schema = %s
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'FOREIGN KEY'
                ORDER BY tc.constraint_name, kcu.ordinal_position
                """,
                (self.schema, name),
            )
            grouped: dict[str, list[tuple[str, str, str]]] = {}
            for cname, col, ref_t, ref_c in cur.fetchall():
                grouped.setdefault(cname, []).append((col, ref_t, ref_c))
            foreign_keys = []
            for cname, parts in grouped.items():
                cols_local = [p[0] for p in parts]
                ref_table = parts[0][1]
                ref_cols = [p[2] for p in parts]
                foreign_keys.append(
                    ForeignKey(
                        columns=cols_local, ref_table=ref_table, ref_columns=ref_cols
                    )
                )

            cur.execute(
                """
                SELECT obj_description(
                  (table_schema || '.' || table_name)::regclass::oid)
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
                """,
                (self.schema, name),
            )
            row = cur.fetchone()
            description: Optional[str] = row[0] if row and row[0] else None

        return TableSchema(
            name=name,
            columns=columns,
            primary_key=primary_key,
            foreign_keys=foreign_keys,
            description=description,
        )

    def execute_select(
        self, sql: str, *, timeout_s: float, max_rows: int
    ) -> QueryResult:
        import psycopg

        with self._lock:
            with self._conn.cursor() as cur:
                try:
                    cur.execute(
                        f"SET LOCAL statement_timeout = {int(timeout_s * 1000)}"
                    )
                except psycopg.Error:
                    pass
                t0 = time.monotonic()
                try:
                    cur.execute(sql)
                except psycopg.errors.QueryCanceled as e:
                    raise DatabaseError(f"Query timed out after {timeout_s}s") from e
                except psycopg.Error as e:
                    raise DatabaseError(str(e)) from e
                cols: list[str] = (
                    [d.name for d in cur.description] if cur.description else []
                )
                fetched = cur.fetchmany(max_rows + 1)
                elapsed_ms = (time.monotonic() - t0) * 1000

        truncated_at: int | None = None
        if len(fetched) > max_rows:
            fetched = fetched[:max_rows]
            truncated_at = max_rows

        rows: list[dict[str, Any]] = [
            {col: row[i] for i, col in enumerate(cols)} for row in fetched
        ]
        return QueryResult(
            columns=cols, rows=rows, truncated_at=truncated_at, elapsed_ms=elapsed_ms
        )
