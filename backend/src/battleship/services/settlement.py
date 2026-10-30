"""The single match-settlement transaction boundary (ticket #9, DECISIONS D12).

One match ending writes, in this order and in one SQLAlchemy unit of work:

1. matches (mode = ranked / casual / ai / custom / NULL)
2. match_logs
3. match_replays (ticket #18's real recorder; skipped when any participant
   disabled replay or the room recorded no steps)
4. users wins / losses / current_streak / longest_streak
5. user_counters (sunk_total / matches_played / flawless_wins / fastest_win_sec)
6. registered settlement hooks (rank / xp / achievements / anticheat, tickets #15/#16)

Any failure rolls the whole unit of work back: there is never a match row without
its log/replay/stats. Settlement is idempotent per room (room.settled), so a
surrender racing a disconnect forfeit cannot double-count the same match.

Business code never writes SQL here; the UnitOfWork repositories are the only
persistence surface.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from ..domain import replay as replay_rules
from ..domain.room import Room
from ..domain.settlement import SettlementFacts, settlement_facts
from ..infra.logging import get_logger
from ..repositories import Database, UnitOfWork
from .tasks import settle_tasks

logger = get_logger("settlement")

REPLAY_PLACEHOLDER_VERSION = 1


@dataclass(frozen=True)
class SettlementContext:
    """Everything a settlement hook may need, frozen before the commit."""

    match_id: str
    timestamp: int
    facts: SettlementFacts
    replay_saved: bool
    replay: Any = None
    #: Read-only facts captured before the write transaction (pre-match streaks,
    #: pre-match tiers). Hooks must never re-read these after the core writes.
    pre: dict[str, Any] = field(default_factory=dict)
    #: Wire frames produced by hooks. BattleService emits the "before" ones
    #: before game_over and the "after" ones after it (legacy order).
    events: list[dict[str, Any]] = field(default_factory=list)
    #: True when the anti-cheat pre-hook decided this match must not move rank
    #: points (ticket #16). It only gates ranking: wins/XP/badges still settle.
    blocked: bool = False


@dataclass(frozen=True)
class SettlementResult:
    ok: bool
    match_id: str | None = None
    skipped: bool = False
    error: str | None = None
    events: tuple[dict[str, Any], ...] = ()
    #: Anti-cheat gate verdict, surfaced for callers/tests and the settlement UI.
    blocked: bool = False


#: A hook runs inside the same unit of work, after the core rows.
SettlementHook = Callable[[Room, UnitOfWork, SettlementContext], None]
#: A read-only hook runs before the transaction; it returns extra context.
SettlementPreHook = Callable[[Room, SettlementFacts], dict[str, Any]]
ReplayBuilder = Callable[[Room], Any]


class SettlementService:
    """Persist one finished match, exactly once, atomically."""

    def __init__(
        self,
        database: Database | None = None,
        *,
        replay_builder: ReplayBuilder | None = None,
        replay_gate: Callable[[str | None, str | None], bool] | None = None,
        hooks: Sequence[SettlementHook] | None = None,
    ) -> None:
        self.database = database
        self.replay_builder = replay_builder
        # One gate for "may this match keep a replay" (ticket #18 fills it with
        # the allow_replay read). The default keeps legacy callers/tests that
        # wire only a builder working: participants imply a replay.
        self.replay_gate = replay_gate
        self.hooks: list[SettlementHook] = list(hooks or ())
        self.pre_hooks: list[SettlementPreHook] = []
        self._lock = threading.Lock()

    def add_hook(self, hook: SettlementHook) -> None:
        self.hooks.append(hook)

    def add_pre_hook(self, hook: SettlementPreHook) -> None:
        """Register a read-only fact collector used before the write transaction."""

        self.pre_hooks.append(hook)

    def settle(self, room: Room, winner_id: str, loser_id: str) -> SettlementResult:
        with self._lock:
            if room.settled:
                cached = room.settlement_result
                return SettlementResult(
                    ok=True,
                    match_id=getattr(cached, "match_id", None),
                    skipped=True,
                )

            try:
                facts = settlement_facts(room, winner_id, loser_id)
            except KeyError as error:
                logger.error(
                    "settlement skipped: seat missing",
                    extra={"room_id": room.id, "missing": str(error)},
                )
                return SettlementResult(
                    ok=False, skipped=True, error=f"seat missing: {error}"
                )

            if self.database is None or (
                not facts.winner_user_id and not facts.loser_user_id
            ):
                # Legacy record_match is only called when at least one seat has
                # an account id. Domain/unit callers also have no persistence;
                # mark the room so a repeated finish does not re-run effects.
                result = SettlementResult(ok=True, skipped=True)
                room.settled = True
                room.settlement_result = result
                return result

            match_id = str(uuid.uuid4())
            timestamp = int(time.time())
            pre = self._run_pre_hooks(room, facts)
            events: list[dict[str, Any]] = []
            try:
                replay = self._build_replay(room) if self._replay_allowed(facts) else None
                context = SettlementContext(
                    match_id=match_id,
                    timestamp=timestamp,
                    facts=facts,
                    replay_saved=bool(replay),
                    replay=replay,
                    pre=pre,
                    events=events,
                    blocked=bool(pre.get("anticheat_blocked")),
                )
                with self.database.unit_of_work() as uow:
                    self._write_match(uow, room, context)
                    if facts.count_stats:
                        self._write_user_stats(uow, facts)
                    settle_tasks(room, uow, context)
                    for hook in self.hooks:
                        hook(room, uow, context)
            except Exception as error:  # noqa: BLE001 - the UoW already rolled back
                logger.error(
                    "match settlement failed; transaction rolled back",
                    extra={
                        "room_id": room.id,
                        "winner": winner_id,
                        "loser": loser_id,
                        "error_type": type(error).__name__,
                    },
                    exc_info=error,
                )
                # Same memory discipline as legacy: a failed write must not
                # leave a 512 KB recording hanging on a finished room.
                replay_rules.reset(room)
                return SettlementResult(ok=False, error=str(error))

            # Legacy reset the recorder in a finally after record_match: the blob
            # is already in the context, the room no longer needs the recording.
            replay_rules.reset(room)
            result = SettlementResult(
                ok=True, match_id=match_id, events=tuple(events),
                blocked=bool(context.blocked),
            )
            room.match_id = match_id
            room.settled = True
            room.settlement_result = result
            return result

    def _run_pre_hooks(self, room: Room, facts: SettlementFacts) -> dict[str, Any]:
        """Collect read-only pre-match facts. Failures never block settlement."""

        collected: dict[str, Any] = {}
        if self.database is None:
            return collected
        for hook in self.pre_hooks:
            try:
                collected.update(hook(room, facts) or {})
            except Exception as error:  # noqa: BLE001 - pre-facts are optional
                logger.error(
                    "settlement pre-hook failed; continuing with defaults",
                    extra={"room_id": room.id, "error_type": type(error).__name__},
                    exc_info=error,
                )
        return collected

    # ------------------------------------------------------------------ writes

    def _replay_allowed(self, facts: SettlementFacts) -> bool:
        """One gate decision, before anything is written (fail-closed)."""
        if not (facts.winner_user_id or facts.loser_user_id):
            return False
        if self.replay_gate is None:
            return True
        return bool(self.replay_gate(facts.winner_user_id, facts.loser_user_id))

    def _build_replay(self, room: Room) -> Any:
        if self.replay_builder is not None:
            return self.replay_builder(room)
        # Ticket #18 replaces this placeholder with the real replay payload.
        # Version 1 keeps legacy readers from rejecting the row outright, while
        # the explicit placeholder flag tells #18 it is not a real recording.
        return {
            "version": REPLAY_PLACEHOLDER_VERSION,
            "placeholder": True,
            "room_id": room.id,
            "winner": room.winner or None,
            "round": room.round,
            "steps": [],
        }

    def _write_match(self, uow: UnitOfWork, room: Room,
                     context: SettlementContext) -> None:
        facts = context.facts
        uow.matches.create(
            match_id=context.match_id,
            # Legacy falls back to the seat id (guest sid / ai-*) for matches.
            winner_id=facts.winner_user_id or facts.winner_id,
            loser_id=facts.loser_user_id or facts.loser_id,
            timestamp=context.timestamp,
            mode=facts.mode,
        )
        uow.matches.add_log(
            context.match_id,
            json.dumps(room.game_logs or [], ensure_ascii=False),
        )
        if context.replay_saved:
            uow.replays.save(
                context.match_id,
                context.replay,
                winner_user_id=facts.winner_user_id,
                loser_user_id=facts.loser_user_id,
                created_at=context.timestamp,
            )

    def _write_user_stats(self, uow: UnitOfWork, facts: SettlementFacts) -> None:
        winner = uow.users.get(facts.winner_user_id)
        if winner is not None:
            streak = int(winner.current_streak or 0) + 1
            uow.users.update(
                facts.winner_user_id,
                wins=int(winner.wins or 0) + 1,
                current_streak=streak,
                longest_streak=max(streak, int(winner.longest_streak or 0)),
            )
            uow.stats.bump_counters(
                facts.winner_user_id,
                sunk_total=facts.winner_sunk,
                matches_played=1,
                flawless_wins=1 if facts.winner_flawless else 0,
                fastest_win_sec=facts.duration_seconds,
            )

        loser = uow.users.get(facts.loser_user_id)
        if loser is not None:
            uow.users.update(
                facts.loser_user_id,
                losses=int(loser.losses or 0) + 1,
                current_streak=0,
            )
            uow.stats.bump_counters(
                facts.loser_user_id,
                sunk_total=facts.loser_sunk,
                matches_played=1,
            )
