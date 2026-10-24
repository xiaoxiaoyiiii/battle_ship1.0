"""Reusable session factory and transaction boundary.

Business code never opens a Session by hand: it enters :func:`Database.unit_of_work`
and uses the repositories exposed there. A clean exit commits; an exception rolls
back. Repositories only ever receive the session owned by the current unit of work.

SQLite is synchronous, so the boundary is a normal context manager. FastAPI
endpoints may call it from a threadpool; the engine is created with
`check_same_thread=False` and the old stack's WAL/busy_timeout pragmas.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..infra.db import create_engine_for, create_engine_for_url
from .matches import MatchRepository
from .replays import ReplayRepository
from .social import SocialRepository
from .stats import StatsRepository
from .tasks import TaskRepository
from .users import UserRepository


class UnitOfWork:
    """One session = one transaction boundary, with repositories attached."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self.session: Session | None = None
        self._repositories: dict[str, object] = {}

    def __enter__(self) -> "UnitOfWork":
        self.session = self._session_factory()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:  # type: ignore[no-untyped-def]
        assert self.session is not None
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None
            self._repositories.clear()
        return False

    def _require_session(self) -> Session:
        if self.session is None:
            raise RuntimeError("unit of work is not active")
        return self.session

    def _repository(self, key: str, factory):  # type: ignore[no-untyped-def]
        repository = self._repositories.get(key)
        if repository is None:
            repository = factory(self._require_session())
            self._repositories[key] = repository
        return repository

    @property
    def users(self) -> UserRepository:
        return self._repository("users", UserRepository)  # type: ignore[return-value]

    @property
    def matches(self) -> MatchRepository:
        return self._repository("matches", MatchRepository)  # type: ignore[return-value]

    @property
    def replays(self) -> ReplayRepository:
        return self._repository("replays", ReplayRepository)  # type: ignore[return-value]

    @property
    def social(self) -> SocialRepository:
        return self._repository("social", SocialRepository)  # type: ignore[return-value]

    @property
    def stats(self) -> StatsRepository:
        return self._repository("stats", StatsRepository)  # type: ignore[return-value]

    @property
    def tasks(self) -> TaskRepository:
        return self._repository("tasks", TaskRepository)

    def flush(self) -> None:
        self._require_session().flush()

    def commit(self) -> None:
        self._require_session().commit()

    def rollback(self) -> None:
        self._require_session().rollback()


class Database:
    """Owns the engine and hands out units of work."""

    def __init__(
        self,
        database_url: str,
        *,
        path: Path | None = None,
        engine: Engine | None = None,
    ) -> None:
        self.engine: Engine = engine if engine is not None else create_engine_for_url(database_url)
        self.path = path
        self.session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=True,
            future=True,
        )

    @classmethod
    def from_path(cls, database_path: str | Path) -> "Database":
        path = Path(database_path)
        return cls(f"sqlite:///{path.as_posix()}", path=path)

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        return cls(
            settings.database_url,
            path=settings.database_path,
            engine=create_engine_for(settings),
        )

    @contextmanager
    def unit_of_work(self) -> Iterator[UnitOfWork]:
        with UnitOfWork(self.session_factory) as unit_of_work:
            yield unit_of_work

    def session(self) -> Session:
        return self.session_factory()

    def dispose(self) -> None:
        self.engine.dispose()