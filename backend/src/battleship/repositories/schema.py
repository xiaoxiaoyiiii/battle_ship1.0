"""Schema introspection/verification for the data layer.

This is the only place that decides whether a physical SQLite file still matches the
models. It is intentionally *logical* rather than text-based: SQLite and SQLAlchemy
render equivalent DDL differently, while `PRAGMA table_info` + `index_xinfo` expose
the facts the application depends on (column names/order, affinity type, defaults,
primary keys, unique constraints, index columns and sort direction, views).

Parity note: the legacy DDL used `TEXT PRIMARY KEY` / `INTEGER PRIMARY KEY
AUTOINCREMENT`, for which SQLite reports `notnull=0`; SQLAlchemy models mark every
primary-key column NOT NULL. That single difference is normalized away (for PK
columns only) because no writer may ever store a NULL primary key.
"""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.engine import Connection

from .models import Base

INTERNAL_TABLES = frozenset({"sqlite_sequence", "alembic_version"})
EXPECTED_VIEWS = ("match_history",)


# --------------------------------------------------------------------------- expected


def _index_columns(index: sa.Index) -> list[tuple[str, int]]:
    columns: list[tuple[str, int]] = []
    for expression in index.expressions:
        if isinstance(expression, sa.Column):
            columns.append((expression.name, 0))
            continue
        raw = re.sub(r"\s+", " ", str(expression)).strip()
        name, _, direction = raw.partition(" ")
        columns.append((name, 1 if direction.strip().upper() == "DESC" else 0))
    return columns


def expected_schema() -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for name, table in Base.metadata.tables.items():
        pk_order = [column.name for column in table.primary_key.columns]
        columns = [
            {
                "name": column.name,
                "type": str(column.type.compile(dialect=sqlite_dialect())),
                "nullable": False if column.primary_key else bool(column.nullable),
                "default": (
                    None if column.server_default is None else str(column.server_default.arg)
                ),
                "pk": pk_order.index(column.name) + 1 if column.primary_key else 0,
            }
            for column in table.columns
        ]
        indexes = {
            index.name: {
                "unique": bool(index.unique),
                "columns": _index_columns(index),
            }
            for index in table.indexes
        }
        unique = sorted(
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        )
        tables[name] = {
            "columns": columns,
            "primary_key": pk_order,
            "indexes": indexes,
            "unique": unique,
        }
    return {"tables": tables, "views": list(EXPECTED_VIEWS)}


# ----------------------------------------------------------------------------- actual


def _actual_indexes(connection: Connection, table: str) -> dict[str, Any]:
    indexes: dict[str, Any] = {}
    inspector = sa.inspect(connection)
    for index in inspector.get_indexes(table):
        name = index["name"]
        if not name or name.startswith("sqlite_autoindex"):
            continue
        order: dict[str, int] = {}
        for row in connection.exec_driver_sql(f'PRAGMA index_xinfo("{name}")'):
            if row[5]:  # key column
                order[row[2]] = int(row[3])
        indexes[name] = {
            "unique": bool(index["unique"]),
            "columns": [
                (column, order.get(column, 0)) for column in index["column_names"]
            ],
        }
    return indexes


def actual_schema(connection: Connection) -> dict[str, Any]:
    inspector = sa.inspect(connection)
    tables: dict[str, Any] = {}
    for name in inspector.get_table_names():
        if name in INTERNAL_TABLES:
            continue
        columns = [
            {
                "name": column["name"],
                "type": str(column["type"]),
                "nullable": bool(column["nullable"]),
                "default": column.get("default"),
                "pk": 0,
            }
            for column in inspector.get_columns(name)
        ]
        pk = inspector.get_pk_constraint(name)
        pk_order = list(pk.get("constrained_columns") or [])
        for position, column_name in enumerate(pk_order, start=1):
            for column in columns:
                if column["name"] == column_name:
                    column["pk"] = position
        unique = sorted(
            tuple(constraint.get("column_names") or ())
            for constraint in inspector.get_unique_constraints(name)
        )
        tables[name] = {
            "columns": columns,
            "primary_key": pk_order,
            "indexes": _actual_indexes(connection, name),
            "unique": unique,
        }
    return {
        "tables": tables,
        "views": sorted(name for name in inspector.get_view_names() if name != "sqlite_sequence"),
    }


# ------------------------------------------------------------------------------- diff


def _column_diff(table: str, expected: dict, actual: dict) -> list[str]:
    diffs: list[str] = []
    for key in ("type", "default", "pk"):
        if expected[key] != actual[key]:
            diffs.append(
                f"{table}.{expected['name']}: {key} {expected[key]!r} != {actual[key]!r}"
            )
    if expected["pk"] == 0 and expected["nullable"] != actual["nullable"]:
        diffs.append(
            f"{table}.{expected['name']}: nullable "
            f"{expected['nullable']!r} != {actual['nullable']!r}"
        )
    return diffs


def diff_schemas(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    expected_tables = expected["tables"]
    actual_tables = actual["tables"]

    for name in sorted(set(expected_tables) - set(actual_tables)):
        diffs.append(f"missing table: {name}")
    for name in sorted(set(actual_tables) - set(expected_tables)):
        diffs.append(f"unexpected table: {name}")

    for name in sorted(set(expected_tables) & set(actual_tables)):
        expected_table = expected_tables[name]
        actual_table = actual_tables[name]
        expected_columns = expected_table["columns"]
        actual_columns = actual_table["columns"]
        expected_names = [column["name"] for column in expected_columns]
        actual_names = [column["name"] for column in actual_columns]
        for column_name in expected_names:
            if column_name not in actual_names:
                diffs.append(f"missing column: {name}.{column_name}")
        for column_name in actual_names:
            if column_name not in expected_names:
                diffs.append(f"unexpected column: {name}.{column_name}")
        if set(expected_names) == set(actual_names) and expected_names != actual_names:
            diffs.append(f"column order differs: {name}")
        actual_by_name = {column["name"]: column for column in actual_columns}
        for column in expected_columns:
            if column["name"] in actual_by_name:
                diffs.extend(_column_diff(name, column, actual_by_name[column["name"]]))
        if expected_table["primary_key"] != actual_table["primary_key"]:
            diffs.append(
                f"primary key differs: {name} "
                f"{expected_table['primary_key']} != {actual_table['primary_key']}"
            )
        if expected_table["unique"] != actual_table["unique"]:
            diffs.append(
                f"unique constraints differ: {name} "
                f"{expected_table['unique']} != {actual_table['unique']}"
            )
        for index_name in sorted(
            set(expected_table["indexes"]) | set(actual_table["indexes"])
        ):
            if expected_table["indexes"].get(index_name) != actual_table["indexes"].get(
                index_name
            ):
                diffs.append(
                    f"index differs: {name}.{index_name} "
                    f"{expected_table['indexes'].get(index_name)} != "
                    f"{actual_table['indexes'].get(index_name)}"
                )

    if expected["views"] != actual["views"]:
        diffs.append(f"views differ: {expected['views']} != {actual['views']}")
    return diffs


def verify_schema(connection: Connection) -> list[str]:
    """Return [] when the physical schema matches the models."""
    return diff_schemas(expected_schema(), actual_schema(connection))
