"""Database ABC."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from ..types import QueryResult, TableSchema


class Database(ABC):
    dialect: Literal["postgres", "sqlite"]

    @abstractmethod
    def list_tables(self) -> list[str]: ...

    @abstractmethod
    def get_schema(self) -> dict[str, TableSchema]: ...

    @abstractmethod
    def get_table_schema(self, name: str) -> TableSchema: ...

    @abstractmethod
    def execute_select(
        self, sql: str, *, timeout_s: float, max_rows: int
    ) -> QueryResult: ...

    def close(self) -> None:  # pragma: no cover - optional
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
