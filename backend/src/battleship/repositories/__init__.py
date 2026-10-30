"""Persistence layer: the only place in the backend that writes SQL.

Public entry points:

* :class:`~battleship.repositories.unit_of_work.Database` -- engine + session factory;
* :class:`~battleship.repositories.unit_of_work.UnitOfWork` -- transaction boundary
  with `users` / `matches` / `replays` / `social` / `stats` repositories;
* :mod:`~battleship.repositories.models` -- SQLAlchemy models for the 21 legacy tables;
* :mod:`~battleship.repositories.migrations` -- backup/upgrade/verify runner.
"""

from .unit_of_work import Database, UnitOfWork

__all__ = ["Database", "UnitOfWork"]
