"""SQLite implementation of :class:`Database`."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..exceptions import DatabaseError
from ..types import ColumnSchema, ForeignKey, QueryResult, TableSchema
from .base import Database


_SYSTEM_TABLE_PREFIXES = ("sqlite_",)


class SqliteDatabase(Database):
    """SQLite via stdlib :mod:`sqlite3`."""

    dialect = "sqlite"

    def __init__(self, path: str | Path):
        self.path = str(path)
        # check_same_thread=False because we serialise calls with our own lock.
        try:
            self._conn = sqlite3.connect(
                self.path, check_same_thread=False, timeout=30.0
            )
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to open SQLite database {self.path}: {e}") from e
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def list_tables(self) -> list[str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table','view') ORDER BY name"
            )
            return [
                row[0]
                for row in cur.fetchall()
                if not row[0].startswith(_SYSTEM_TABLE_PREFIXES)
            ]

    def get_schema(self) -> dict[str, TableSchema]:
        return {name: self.get_table_schema(name) for name in self.list_tables()}

    def get_table_schema(self, name: str) -> TableSchema:
        # Quote identifier safely.
        ident = name.replace('"', '""')
        with self._lock:
            try:
                cols = self._conn.execute(
                    f'PRAGMA table_info("{ident}")'
                ).fetchall()
            except sqlite3.Error as e:
                raise DatabaseError(f"Unknown table '{name}': {e}") from e
            if not cols:
                raise DatabaseError(f"Unknown table '{name}'.")
            fks_raw = self._conn.execute(
                f'PRAGMA foreign_key_list("{ident}")'
            ).fetchall()

        columns: list[ColumnSchema] = []
        primary_key: list[str] = []
        for row in cols:
            # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
            cname = row[1]
            ctype = row[2] or "TEXT"
            notnull = bool(row[3])
            default = row[4]
            pk_idx = row[5] or 0
            columns.append(
                ColumnSchema(
                    name=cname,
                    data_type=str(ctype).upper(),
                    nullable=not notnull,
                    default=str(default) if default is not None else None,
                )
            )
            if pk_idx:
                primary_key.append(cname)

        # Group FKs by id.
        fk_map: dict[int, list[tuple[str, str]]] = {}
        fk_table: dict[int, str] = {}
        for row in fks_raw:
            # id, seq, table, from, to, on_update, on_delete, match
            fid = row[0]
            fk_table[fid] = row[2]
            fk_map.setdefault(fid, []).append((row[3], row[4]))
        foreign_keys: list[ForeignKey] = []
        for fid, pairs in fk_map.items():
            cols_local = [p[0] for p in pairs]
            cols_ref = [p[1] for p in pairs]
            foreign_keys.append(
                ForeignKey(
                    columns=cols_local,
                    ref_table=fk_table[fid],
                    ref_columns=cols_ref,
                )
            )

        return TableSchema(
            name=name,
            columns=columns,
            primary_key=primary_key,
            foreign_keys=foreign_keys,
        )

    def execute_select(
        self, sql: str, *, timeout_s: float, max_rows: int
    ) -> QueryResult:
        # SQLite has no native per-statement timeout; we approximate with
        # a progress handler that aborts after the budget is spent.
        deadline = time.monotonic() + max(0.05, timeout_s)
        aborted = {"v": False}

        def _progress():
            if time.monotonic() > deadline:
                aborted["v"] = True
                return 1
            return 0

        with self._lock:
            self._conn.set_progress_handler(_progress, 1000)
            t0 = time.monotonic()
            try:
                cur = self._conn.execute(sql)
            except sqlite3.OperationalError as e:
                self._conn.set_progress_handler(None, 0)
                if aborted["v"]:
                    raise DatabaseError(f"Query timed out after {timeout_s}s") from e
                raise DatabaseError(str(e)) from e
            except sqlite3.Error as e:
                self._conn.set_progress_handler(None, 0)
                raise DatabaseError(str(e)) from e

            try:
                # Fetch one extra row to detect truncation.
                fetched = cur.fetchmany(max_rows + 1)
                cols = [d[0] for d in (cur.description or [])]
            finally:
                self._conn.set_progress_handler(None, 0)

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
