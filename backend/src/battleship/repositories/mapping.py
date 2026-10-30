"""Small helpers to turn ORM rows into plain dictionaries."""

from __future__ import annotations

from typing import Any


def instance_dict(instance: Any) -> dict[str, Any]:
    return {column.name: getattr(instance, column.name) for column in instance.__table__.columns}


def row_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)
