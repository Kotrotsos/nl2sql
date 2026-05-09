"""Shared test fixtures."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_sqlite_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture
def sample_db_path(tmp_path: Path) -> str:
    """A small fixture database with customers/orders/products."""
    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            country TEXT,
            is_internal INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            ordered_at TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        INSERT INTO customers (id, email, country, is_internal, created_at) VALUES
            (1, 'a@example.com', 'NL', 0, '2026-01-15'),
            (2, 'b@example.com', 'US', 0, '2026-02-10'),
            (3, 'c@example.com', 'NL', 1, '2026-02-20'),
            (4, 'd@example.com', 'DE', 0, '2026-03-05'),
            (5, 'e@example.com', 'US', 0, '2026-04-22');
        INSERT INTO products (id, name, price, category) VALUES
            (1, 'Widget',  9.99, 'gadget'),
            (2, 'Gizmo',  19.99, 'gadget'),
            (3, 'Sprocket', 4.50, 'part');
        INSERT INTO orders (id, customer_id, product_id, amount, ordered_at) VALUES
            (1, 1, 1, 19.98, '2026-01-20'),
            (2, 2, 2, 19.99, '2026-02-12'),
            (3, 4, 3,  9.00, '2026-03-06'),
            (4, 1, 2, 19.99, '2026-03-15'),
            (5, 5, 1,  9.99, '2026-04-25');
        """
    )
    conn.commit()
    conn.close()
    return str(db_path)
