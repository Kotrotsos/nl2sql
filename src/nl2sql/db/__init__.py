"""Database adapters."""
from .base import Database
from .sqlite import SqliteDatabase

__all__ = ["Database", "SqliteDatabase", "PostgresDatabase"]


def __getattr__(name: str):
    if name == "PostgresDatabase":
        from .postgres import PostgresDatabase  # lazy psycopg import
        return PostgresDatabase
    raise AttributeError(name)
