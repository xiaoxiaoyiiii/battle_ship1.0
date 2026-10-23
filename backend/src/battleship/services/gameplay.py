"""Gameplay use cases: placement, RPS, phases, turn timer.

The socket layer only translates frames into calls on this service; every rule
lives in :mod:`battleship.domain.placement` / :mod:`battleship.domain.battle`.
Rooms are in-memory (no room table), so this ticket writes no SQL and needs no
unit of work; match settlement (#12) enters through `repositories.UnitOfWork`.

Two seams are injected so later tickets do not have to edit this file:

* `draw_hook(room, player_id) -> Any` -- ticket #10 owns the real deck/hand.
  The RPS resolution calls it once for the first player and twice for the
  second, exactly the frozen 1/2 draw contract; its return value is what
  `game_state.winner_card` / `loser_cards` carry.
* `fire_hook(room, player_id, x, y)` -- ticket #9 owns attack effects. The
  turn watchdog picks an attackable random cell and hands it over; without the
  hook the watchdog reports that firing is not wired yet instead of faking a
  shot or declaring a loss.

`TURN_TIMEOUT_SECONDS` (default 90, 0 disables) only performs fallback
actions. It never declares a loser, and every successful action by the current
attacker restarts the clock.
"""

from __future__ import annotations

import asyncio
import inspect
import random
import time
from typing import Any, Callable

from ..contracts.identity import ai_player_id
from ..domain import battle as battle_rules
from ..domain import effects
from ..domain import placement as placement_rules
from ..domain import replay as replay_rules
from ..domain.magic import hooks
from ..domain.magic import temps as magic_temps
from ..domain.placement import PlacementError
from ..domain.room import (
    Room,
    RoomPhase,
    RoomState,
    card_payload,
    rank_payload,
    turn_timing,
)
from ..infra.logging import get_logger
from .rooms import Connection, EventPublisher, NullPublisher, RoomService

logger = get_logger("gameplay")

INVALID_SEAT = {"status": "error", "message": "无效的房间或玩家"}
FINISHED_GAME = {"status": "error", "message": "对局已结束"}
NO_PENDING_PLACEMENT = {"status": "error", "message": "没有等待放置的战舰"}
OPPONENT_DISCONNECTED = "对手已掉线，等待重连中"
DEFAULT_TURN_TIMEOUT_SECONDS = 90
DEFAULT_TICK_SECONDS = 1.0


def _state_value(room: Room) -> str:
    """Accept both the enum and a legacy plain string stored by older flows."""

    return getattr(room.state, "value", room.state)


def _phase_value(room: Room) -> str:
    return getattr(room.current_phase, "value", room.current_phase)


class GameplayService:
    """Use cases for one room's placement / RPS / phase / turn lifecycle."""

    def __init__(
        self,
        rooms: RoomService,
        *,
        turn_timeout_seconds: int = DEFAULT_TURN_TIMEOUT_SECONDS,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        draw_hook: Callable[[Room, str], Any] | None = None,
        fire_hook: Callable[[Room, str, int, int], Any] | None = None,
        ai_turn_hook: Callable[[Room, str], Any] | None = None,
        ai_delay_seconds: float = 0.5,
        rng: Any | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.rooms = rooms
        self.turn_timeout_seconds = int(turn_timeout_seconds)
        # Ticket #52: no post-hoc stamping. The composition root already injected
        # the timeout into RoomService (one source for the reconnect snapshot);
        # here we only fail fast if the two wiring points disagree.
        configured = self.rooms.turn_timeout_seconds
        if configured is not None and int(configured) != self.turn_timeout_seconds:
            raise ValueError(
                "turn timeout mismatch: RoomService has "
                + str(configured)
                + " but GameplayService was built with "
                + str(self.turn_timeout_seconds)
            )
        self.tick_seconds = float(tick_seconds)
        self.draw_hook = draw_hook
        self.fire_hook = fire_hook
        # Ticket #13 owns the real AI layer (services.ai installs this hook).
        # Without the hook the fallback below keeps an AI room playable instead
        # of freezing on the AI seat's turn.
        self.ai_turn_hook = ai_turn_hook
        self.ai_delay_seconds = max(0.0, float(ai_delay_seconds))
        # Default to the module-level RNG, exactly like the legacy handlers, so
        # `random.seed(...)` (and monkeypatching) keeps tests reproducible.
        self.rng = rng or random
        self.clock = clock or (lambda: time.time())
        self._publisher: EventPublisher = NullPublisher()
        self._task: asyncio.Task | None = None
        # Ticket #11 hooks: magic owns judgement settling, flag cleanup and the
        # mid-round reset placement completion. Optional so #8 callers keep working.
        self.magic: Any = None
        self.turn_start_hook: Callable[[Room, str], Any] | None = None
        self.draw_skip_hook: Callable[[Room, str], Any] | None = None
        self.after_draw_hook: Callable[[Room, str], Any] | None = None
        self.round_end_hook: Callable[[Room], Any] | None = None

    # ------------------------------------------------------------------ wiring

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    def start(self) -> None:
        """Start the turn watchdog on the running event loop (idempotent)."""

        if self._task is not None:
            return
        self._task = asyncio.get_running_loop().create_task(self._watch_loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(self.tick_seconds)
            try:
                await self.sweep_timeouts()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # one bad room must not stop the watchdog
                logger.error(
                    "turn watchdog sweep failed",
                    extra={"error_type": type(error).__name__},
                    exc_info=error,
                )

    # --------------------------------------------------------------- helpers

    def _seat(self, connection: Connection, data: dict[str, Any]):
        room = self.rooms.get_room(data.get("room_id"))
        player_id = data.get("player_id")
        if (
            room is None
            or not player_id
            or player_id not in room.players
            or not self.rooms.identity_ok(room, str(player_id), connection)
        ):
            return None, None
        return room, str(player_id)

    @staticmethod
    def _name(room: Room, player_id: str) -> str:
        player = room.players.get(player_id)
        return (player.name or player_id) if player is not None else str(player_id)

    def _note_enter_battle(self, room: Room, player_id: str) -> None:
        actor = self._name(room, player_id)
        replay_rules.note_action(
            room,
            "enter_battle",
            f"{actor} 进入战斗阶段",
            {"player": player_id, "attacks_remaining": room.attacks_remaining,
             "round": room.round},
            actor,
        )

    def _note_enter_end(self, room: Room, player_id: str) -> None:
        actor = self._name(room, player_id)
        replay_rules.note_action(
            room,
            "enter_end",
            f"{actor} 进入结束阶段",
            {"player": player_id, "round": room.round},
            actor,
        )

    def _note_end_turn(self, room: Room, player_id: str) -> None:
        actor = self._name(room, player_id)
        replay_rules.note_action(
            room,
            "end_turn",
            f"{actor} 结束了回合",
            {"player": player_id, "current_attacker": room.current_attacker,
             "round": room.round},
            actor,
        )

    @staticmethod
    def _frozen_reason(room: Room, player_id: str) -> str | None:
        for pid in room.disconnected:
            if pid != player_id:
                return OPPONENT_DISCONNECTED
        return None

    def _start_timer(self, room: Room, now: float | None = None) -> None:
        room.turn_started_at = self.clock() if now is None else now
        room.turn_timer_attacker = room.current_attacker or None

    def _touch_turn(self, room: Room, player_id: str) -> None:
        if room.current_attacker == player_id:
            self._start_timer(room)

    def touch_turn(self, room: Room, player_id: str) -> None:
        """Public seam for the battle service: a successful action restarts 90s."""

        self._touch_turn(room, player_id)

    def _turn_timing(self, room: Room) -> dict[str, int | None]:
        """The countdown payload shared by every turn-starting frame."""

        return turn_timing(room, self.turn_timeout_seconds)

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _draw(self, room: Room, player_id: str) -> Any:
        """Draw seam: explicit hook first, then a room-level `draw_card`.

        Ticket #10 may implement `Room.draw_card` without touching this service;
        until then the hook default returns None (legacy draws from an empty deck
        also yield None).
        """

        if self.draw_hook is not None:
            return await self._maybe_await(self.draw_hook(room, player_id))
        method = getattr(room, "draw_card", None)
        if callable(method):
            return await self._maybe_await(method(player_id))
        return None

    async def _emit_message(self, room: Room, player_id: str, note: str) -> None:
        player = room.players.get(player_id)
        if player is not None and player.socket_id:
            await self._publisher.emit("message", {"text": note}, to=player.socket_id)
        await self._publisher.emit(
            "game_message", {"message": note, "type": "warning"}, room=room.id
        )

    # ------------------------------------------------------------- placement

    async def place_ships(self, connection: Connection,
                          data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if _state_value(room) == RoomState.GAME_OVER.value:
            return dict(FINISHED_GAME)

        player = room.players[player_id]
        # 只有「开局布船」和「自己确实欠着重布」时才允许提交棋盘。战斗进行中随手上交
        # 一份棋盘会重置对手已有的布局并把对局打回猜拳——这是破坏性副作用，先拒。
        placing_phase = _state_value(room) == RoomState.PLACING_SHIPS.value
        if not placing_phase and not player.needs_reset:
            return {"status": "error", "message": "战斗进行中不能重新布置战舰"}
        try:
            ships = placement_rules.validate_placement(
                data.get("ships"), placement_rules.expected_ship_count(player)
            )
        except PlacementError as error:
            return {"status": "error", "message": str(error)}
        # 灵气复苏这类「只能摆在原船位」的卡：白名单由发牌方写进 game_effects。
        allowed = (room.game_effects.get("reset_allowed_cells") or {}).get(player_id)
        if allowed is not None:
            allowed_cells = {(int(cell["x"]), int(cell["y"])) for cell in allowed}
            submitted = {
                (int(pos.x), int(pos.y)) for ship in ships for pos in ship.positions
            }
            if not submitted <= allowed_cells:
                return {"status": "error", "message": "只能在原本有战舰的格子上重新布置"}
        placement_rules.apply_placement(player, ships)

        # AI room: the human's submission also fills the AI seat (legacy).
        if room.is_ai_room:
            seat_id = ai_player_id(room.id)
            ai = room.players.get(seat_id)
            if ai is not None and seat_id != player_id and not ai.ships:
                placement_rules.auto_place_ai(room, seat_id, self.rng)

        if placement_rules.all_players_placed(room):
            handled = await self._complete_reset_placement(room, player_id)
            if not handled:
                # Deliberate direct assignment (DECISIONS D1): the legacy handler
                # has no state gate, so re-placing during battle falls back to RPS.
                room.state = RoomState.ROCK_PAPER_SCISSORS
                room.rps_choices = {}
                room.rps_processed = False
                await self._publisher.emit(
                    "game_state",
                    {"state": RoomState.ROCK_PAPER_SCISSORS.value, **rank_payload(room)},
                    room=room.id,
                )

        actor = self._name(room, player_id)
        replay_rules.note_action(
            room,
            "place_ships",
            f"{actor} 布好了 {len(ships)} 艘战舰",
            {"player": player_id, "ships": len(ships)},
            actor,
        )
        self._touch_turn(room, player_id)
        # Ticket #51: the opponent's placement screen learns "already placed"
        # from the same authoritative snapshot (no new event, no new field).
        await self.rooms.push_room_sync(room)
        return {"status": "success"}

    async def cancel_placement(self, connection: Connection,
                               data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)

        pending = (room.magic_temp_data or {}).get("pending_placement")
        if not pending or pending.get("caster") != player_id:
            return dict(NO_PENDING_PLACEMENT)
        if self.magic is not None:
            result = await self.magic.cancel_placement(room, player_id)
            await self.rooms.push_room_sync(room)
            return result
        magic_temps.finish(room, "pending_placement", owner=player_id)
        player = room.players.get(player_id)
        if player is not None and player.socket_id:
            await self._publisher.emit(
                "message", {"text": "已放弃剩余放置"}, to=player.socket_id
            )
        await self.rooms.push_room_sync(room)
        return {"status": "success"}

    async def _complete_reset_placement(self, room: Room, player_id: str) -> bool:
        """Finish a mid-game board reset (回光返照 / 灵气复苏 / 败者食尘)."""

        def _settle_obligations() -> None:
            for seat in room.players.values():
                seat.needs_reset = False
            room.game_effects.pop("reset_allowed_cells", None)

        if getattr(room, "huiguang_awaiting_placement", False):
            room.huiguang_awaiting_placement = False
            _settle_obligations()
            room.state = RoomState.ATTACKING
            room.current_attacker = player_id
            room.current_phase = RoomPhase.PREPARATION
            room.attacks_remaining = 0
            room.game_effects["zero_attacks_for"] = {
                "player": player_id,
                "round": room.round,
            }
            # Start the clock before the frame that advertises its deadline.
            self._start_timer(room)
            await self._publisher.emit(
                "game_message",
                {"message": "回光返照：棋盘已重摆，本回合无法攻击（攻击次数为 0）"},
                room=room.id,
            )
            await self._publisher.emit(
                "game_state",
                {
                    "state": RoomState.ATTACKING.value,
                    "current_attacker": room.current_attacker,
                    "current_phase": RoomPhase.PREPARATION.value,
                    "attacks_remaining": room.attacks_remaining,
                    "round": room.round,
                    **rank_payload(room),
                    **self._turn_timing(room),
                },
                room=room.id,
            )
            return True

        if getattr(room, "lingqi_resurgence_applied", False):
            room.lingqi_resurgence_applied = False
            saved = getattr(room, "lingqi_saved_state", None) or {}
            room.lingqi_saved_state = None
            room.attack_order = saved.get("attack_order") or list(room.players)
            room.current_attacker = saved.get("current_attacker") or room.attack_order[0]
            _settle_obligations()
            room.round = saved.get("round", room.round)
            phase = saved.get("current_phase", RoomPhase.PREPARATION.value)
            room.current_phase = RoomPhase(phase) if phase in (
                item.value for item in RoomPhase
            ) else RoomPhase.PREPARATION
            room.state = RoomState.ATTACKING
            if room.current_phase == RoomPhase.PREPARATION:
                battle_rules.recalc_attacker_attacks(room)
            else:
                room.attacks_remaining = saved.get(
                    "attacks_remaining", room.attacks_remaining
                )
            if getattr(room, "polar_reversal_applied", False):
                room.polar_reversal_applied = False
                room.attacks_remaining = 0
            self._start_timer(room)
            await self._publisher.emit(
                "game_message",
                {"message": "双方已重新摆放战舰，继续当前回合", "type": "info"},
                room=room.id,
            )
            await self._publisher.emit(
                "game_state",
                {
                    "state": RoomState.ATTACKING.value,
                    "current_attacker": room.current_attacker,
                    "current_phase": _phase_value(room),
                    "attacks_remaining": room.attacks_remaining,
                    "round": room.round,
                    **rank_payload(room),
                    **self._turn_timing(room),
                },
                room=room.id,
            )
            return True

        return False

    async def ai_place_board_now(self, room: Room, player_id: str) -> bool:
        """Ticket #11 lesson #38: an AI caster must finish its own reset board
        inside the same stack frame; humans never see a placing screen."""

        if not room.is_ai_room or not str(player_id).startswith("ai-"):
            return False
        placement_rules.auto_place_ai(room, player_id, self.rng)
        if placement_rules.all_players_placed(room):
            await self._complete_reset_placement(room, player_id)
        return True

    # ------------------------------------------------------------------- RPS

    async def rps_choice(self, connection: Connection,
                         data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if _state_value(room) == RoomState.GAME_OVER.value:
            return dict(FINISHED_GAME)

        choice = data.get("choice")
        if choice not in battle_rules.RPS_CHOICES:
            return {"status": "error", "message": "无效的出拳"}

        if room.is_ai_room:
            ai_id = ai_player_id(room.id)
            if ai_id in room.players and ai_id not in room.rps_choices:
                forced = getattr(room, "test_ai_rps_choice", None)
                room.rps_choices[ai_id] = (
                    forced
                    if forced in battle_rules.RPS_CHOICES
                    else self.rng.choice(battle_rules.RPS_CHOICES)
                )
                if hasattr(room, "test_ai_rps_choice"):
                    delattr(room, "test_ai_rps_choice")

        room.rps_choices[player_id] = choice
        if len(room.rps_choices) < len(room.players):
            # Ticket #51: the waiting seat sees "opponent has chosen" live via
            # room_sync.rps_choices instead of only after a rejoin.
            await self.rooms.push_room_sync(room)

        if len(room.rps_choices) == len(room.players) and not room.rps_processed:
            room.rps_processed = True
            outcome = battle_rules.resolve_rps(room.rps_choices, list(room.players))
            await self._publisher.emit("rps_result", outcome.to_dict(), room=room.id)

            if outcome.status == "tie" or len(outcome.order) < 2:
                room.rps_choices = {}
                room.rps_processed = False
                # A tie clears both choices: push the reset so neither screen
                # keeps showing the other side as "already chosen".
                await self.rooms.push_room_sync(room)
                return {"status": "success", "message": "平局，重新猜拳"}

            room.attack_order = list(outcome.order)
            winner, loser = outcome.order[0], outcome.order[1]
            room.current_attacker = winner
            battle_rules.recalc_attacker_attacks(room)

            if self.turn_start_hook is not None:
                await self._maybe_await(self.turn_start_hook(room, winner))
            # #37：猜拳定先手后的小回合开始；与旧 hook 同位，状态已落定。
            await hooks.emit(
                room,
                hooks.TURN_START,
                {
                    "room_id": room.id,
                    "player_id": winner,
                    "round": room.round,
                },
            )

            # Frozen draw contract: first player 1 card, second player 2 cards.
            # 兵粮寸断 only skips this preparation-phase handout, not any other
            # draw source (the card text is explicit).
            skip_winner = False
            if self.draw_skip_hook is not None:
                skip_winner = bool(await self._maybe_await(self.draw_skip_hook(room, winner)))
            winner_card = None if skip_winner else await self._draw(room, winner)
            skip_loser = False
            if self.draw_skip_hook is not None:
                skip_loser = bool(await self._maybe_await(self.draw_skip_hook(room, loser)))
            if skip_loser:
                loser_card1 = None
                loser_card2 = None
            else:
                loser_card1 = await self._draw(room, loser)
                loser_card2 = await self._draw(room, loser)
            if self.after_draw_hook is not None:
                await self._maybe_await(self.after_draw_hook(room, winner))

            room.state = RoomState.ATTACKING
            if not room.match_started_at:
                room.match_started_at = self.clock()
            room.current_phase = RoomPhase.PREPARATION
            self._start_timer(room)

            await self._publisher.emit(
                "game_state",
                {
                    "state": RoomState.ATTACKING.value,
                    "current_attacker": winner,
                    "current_phase": RoomPhase.PREPARATION.value,
                    "attacks_remaining": room.attacks_remaining,
                    "winner_card": card_payload(winner_card) if winner_card else None,
                    "loser_cards": [
                        card_payload(card) if card else None
                        for card in (loser_card1, loser_card2)
                    ],
                    "round": room.round,
                    "attack_order": list(room.attack_order),
                    **rank_payload(room),
                    **self._turn_timing(room),
                },
                room=room.id,
            )
            actor = self._name(room, winner)
            replay_rules.note_action(
                room,
                "rps_choice",
                f"{actor} 猜拳取胜，先手",
                {"first": winner, "round": room.round},
                actor,
            )

        return {"status": "success"}

    # ---------------------------------------------------------------- phases

    async def _emit_phase(self, room: Room) -> None:
        await self._publisher.emit(
            "phase_updated",
            {
                "current_phase": _phase_value(room),
                "current_attacker": room.current_attacker,
            },
            room=room.id,
        )

    async def enter_battle_phase(self, connection: Connection,
                                 data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if _state_value(room) == RoomState.GAME_OVER.value:
            return dict(FINISHED_GAME)
        frozen = self._frozen_reason(room, player_id)
        if frozen:
            return {"status": "error", "message": frozen}

        error = battle_rules.enter_battle(room, player_id)
        if error:
            return {"status": "error", "message": error}
        # #37：阶段已落定后才发（enter_battle 内部改了 phase 与攻击次数）。
        await hooks.emit(
            room,
            hooks.PHASE_ENTER,
            {
                "room_id": room.id,
                "player_id": player_id,
                "phase": _phase_value(room),
            },
        )

        await self._publisher.emit(
            "attacks_updated",
            {
                "current_attacker": room.current_attacker,
                "attacks_remaining": room.attacks_remaining,
            },
            room=room.id,
        )
        await self._emit_phase(room)
        self._note_enter_battle(room, player_id)
        self._touch_turn(room, player_id)
        return {"status": "success"}

    async def enter_end_phase(self, connection: Connection,
                              data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if _state_value(room) == RoomState.GAME_OVER.value:
            return dict(FINISHED_GAME)
        frozen = self._frozen_reason(room, player_id)
        if frozen:
            return {"status": "error", "message": frozen}

        error = battle_rules.enter_end(room, player_id)
        if error:
            return {"status": "error", "message": error}
        # #37：结束阶段同样在 phase 变更之后发。
        await hooks.emit(
            room,
            hooks.PHASE_ENTER,
            {
                "room_id": room.id,
                "player_id": player_id,
                "phase": _phase_value(room),
            },
        )

        await self._emit_phase(room)
        self._note_enter_end(room, player_id)
        self._touch_turn(room, player_id)
        return {"status": "success", "message": "已进入结束阶段"}

    async def _apply_turn_end(self, room: Room, player_id: str) -> dict | None:
        result = battle_rules.resolve_turn_end(room, player_id)
        if result is None:
            return None
        # Same single recording point as legacy's try/finally: all success
        # branches (new round / next player / skipped) record exactly once.
        self._note_end_turn(room, player_id)
        # #37：换人之前先发 TURN_END；turn 租约不在此时过期（见 on_turn_switch）。
        await hooks.emit(
            room,
            hooks.TURN_END,
            {
                "room_id": room.id,
                "player_id": player_id,
                "round": room.round,
                "kind": result.kind,
                "current_attacker": room.current_attacker,
            },
        )

        if result.kind == "skip_stages":
            # 神之宣告 skips the opponent inside the same big round; legacy does
            # not prune per-turn flags here (the skipped seat never acted).
            await self._emit_phase(room)
            await self._publisher.emit(
                "turn_skipped",
                {
                    "skipped": player_id,
                    "current_attacker": room.current_attacker,
                    "round": room.round,
                },
                room=room.id,
            )
            self._start_timer(room)
            return {"status": "success", "message": "神之宣告：对方本回合被跳过"}

        if result.kind == "new_round":
            # #37：ROUND_END 在旧 round_end_hook 之前；round 租约在 hook 里过期，
            # ROUND_START 在 hook 之后、重新猜拳的 game_state 帧之前。
            await hooks.emit(
                room,
                hooks.ROUND_END,
                {"room_id": room.id, "round": room.round},
            )
            if self.round_end_hook is not None:
                outcome = await self._maybe_await(self.round_end_hook(room))
                if isinstance(outcome, dict) and outcome.get("game_over"):
                    return {
                        "status": "success",
                        "game_over": True,
                        "winner": outcome.get("winner"),
                    }
            self._start_timer(room)
            await hooks.emit(
                room,
                hooks.ROUND_START,
                {"room_id": room.id, "round": room.round},
            )
            await self._publisher.emit(
                "game_state",
                {
                    "state": RoomState.ROCK_PAPER_SCISSORS.value,
                    "round": room.round,
                    **rank_payload(room),
                    **self._turn_timing(room),
                },
                room=room.id,
            )
            return {"status": "success", "new_round": True}

        if self.turn_start_hook is not None:
            await self._maybe_await(self.turn_start_hook(room, room.current_attacker))
        if self.after_draw_hook is not None:
            await self._maybe_await(self.after_draw_hook(room, room.current_attacker))
        if self.magic is not None:
            await self.magic.on_turn_switch(room)
        # #37：换人后的小回合开始。turn 租约已先在 on_turn_switch 过期并投影，
        # 订阅者看到的是清理后的状态（放在过期之前会让他们读到旧角标）。
        await hooks.emit(
            room,
            hooks.TURN_START,
            {
                "room_id": room.id,
                "player_id": room.current_attacker,
                "round": room.round,
            },
        )
        await self._emit_phase(room)
        # Start the next seat's clock before the frame goes out: the frame
        # carries the same anchor the watchdog will compare against.
        self._start_timer(room)
        await self._publisher.emit(
            "turn_change",
            {
                "current_attacker": room.current_attacker,
                "attacks_remaining": room.attacks_remaining,
                "phase": _phase_value(room),
                **self._turn_timing(room),
            },
            room=room.id,
        )
        return {"status": "success"}

    async def end_turn(self, connection: Connection,
                       data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if _state_value(room) == RoomState.GAME_OVER.value:
            return dict(FINISHED_GAME)
        frozen = self._frozen_reason(room, player_id)
        if frozen:
            return {"status": "error", "message": frozen}
        if room.chain or room.chain_waiting:
            return {"status": "error", "message": battle_rules.CHAIN_BUSY_ERROR}

        ack = await self._apply_turn_end(room, player_id)
        if ack is None:
            return {"status": "error", "message": battle_rules.END_TURN_ERROR}
        return ack

    # ---------------------------------------------------------------- debug

    async def debug_end_turn(self, room_id: str | None) -> dict:
        """test_end_turn: force the phase ladder forward, without the guards.

        Legacy parity: battle -> end, end -> the next attacker's preparation
        with the budget refilled from that seat's ship count. It emits no frame
        (the E2E reads the authoritative state through test_get_game_state).
        """

        room = self.rooms.get_room(room_id)
        if room is None:
            return {"status": "error", "message": "无效的房间"}
        phase = _phase_value(room)
        if phase == RoomPhase.BATTLE.value:
            room.current_phase = RoomPhase.END
        elif phase == RoomPhase.END.value:
            order = list(room.attack_order or room.players)
            if not order or room.current_attacker not in order:
                return {"status": "error", "message": "回合顺序为空"}
            index = order.index(room.current_attacker)
            next_id = order[(index + 1) % len(order)]
            room.current_attacker = next_id
            room.current_phase = RoomPhase.PREPARATION
            player = room.players.get(next_id)
            room.attacks_remaining = int(player.remaining_ships) if player else 0
        return {"status": "success", "message": "回合已结束"}

    async def debug_reset_game(self, room_id: str | None) -> dict:
        """test_reset_game: back to an empty placing-ships room.

        The legacy event only cleared the fields that existed then; this also
        clears the pending-interaction state added by later tickets (ship
        picks, dice discards) and restarts the big round, so a reset room never
        carries a half-resolved card into the next E2E scenario.
        """

        room = self.rooms.get_room(room_id)
        if room is None:
            return {"status": "error", "message": "无效的房间"}
        room.state = RoomState.PLACING_SHIPS
        room.attack_order = []
        room.current_attacker = ""
        room.attacks_remaining = 0
        room.current_phase = RoomPhase.PREPARATION
        room.round = 1
        room.winner = ""
        room.game_over_reason = None
        room.field_magic = None
        room.field_magic_owner = None
        room.game_effects = {}
        room.last_attack = None
        magic_temps.clear(room)
        room.chain = []
        room.chain_waiting = False
        room.chain_window = None
        room.chain_passes = 0
        room.chain_timer = -1
        room.chain_display_token = None
        room.chain_display_deadline = None
        room.pending_dice_discard = {}
        room.pending_dice_discard_label = {}
        room.pending_ship_picks = []
        room.priority_pending = None
        room.decline_priority = {}
        room.turn_started_at = None
        room.turn_timer_attacker = None
        for player in room.players.values():
            player.ships = []
            player.remaining_ships = 0
            player.attacks = []
            player.magic_hand = []
            player.damage_dealt_this_turn = 0
            player.sunken_ships = []
            player.revealed_positions = []
            player.needs_reset = True
        # #38：整对象重置统一走 reset_all（match 边界清租约 + 投影）。
        effects.reset_all(room)
        return {"status": "success", "message": "游戏状态已重置"}

    # --------------------------------------------------------------- timeout

    async def sweep_timeouts(self, now: float | None = None) -> list[str]:
        """One watchdog pass. Returns the rooms that performed a fallback action."""

        now = self.clock() if now is None else now
        acted: list[str] = []
        for room in list(self.rooms.get_all_rooms().values()):
            if _state_value(room) != RoomState.ATTACKING.value:
                continue
            player_id = room.current_attacker
            if not player_id or player_id not in room.players:
                continue
            # AI seats are never left to the 90s human clock. The real AI layer
            # (ticket #13) installs ai_turn_hook; the local fallback below only
            # picks a random legal cell / advances the phase so a room with no
            # hook installed still cannot stall.
            if room.is_ai_room and player_id == ai_player_id(room.id):
                if await self._drive_ai(room, player_id, now):
                    acted.append(room.id)
                continue
            if self.turn_timeout_seconds <= 0:
                continue
            if room.turn_timer_attacker != player_id:
                self._start_timer(room, now)
                continue
            if room.turn_started_at is None:
                self._start_timer(room, now)
                continue
            if now - room.turn_started_at < self.turn_timeout_seconds:
                continue
            if room.chain or room.chain_waiting:
                continue
            if room.disconnected:
                continue
            temp = room.magic_temp_data or {}
            if (
                temp.get("pending_placement")
                or temp.get("pending_shenji")
                or any(
                    isinstance(pick, dict) and pick.get("player") == player_id
                    for pick in room.pending_ship_picks
                )
            ):
                continue
            if await self._timeout_action(room, player_id, now):
                acted.append(room.id)
        return acted

    async def _drive_ai(self, room: Room, player_id: str, now: float) -> bool:
        """One AI-seat fallback action. Ticket #13 replaces this via ai_turn_hook."""

        if room.chain or room.chain_waiting or room.priority_pending:
            return False
        if room.disconnected:
            return False
        temp = room.magic_temp_data or {}
        shenji = temp.get("pending_shenji")
        own_shenji = isinstance(shenji, dict) and shenji.get("caster") == player_id
        if (
            temp.get("pending_placement")
            or (temp.get("pending_shenji") and not (own_shenji and self.ai_turn_hook is not None))
            or any(
                isinstance(pick, dict) and pick.get("player") == player_id
                for pick in room.pending_ship_picks
            )
        ):
            return False
        if room.turn_timer_attacker != player_id:
            self._start_timer(room, now)
            return False
        if room.turn_started_at is None:
            self._start_timer(room, now)
            return False
        if now - room.turn_started_at < self.ai_delay_seconds:
            return False

        if self.ai_turn_hook is not None:
            await self._maybe_await(self.ai_turn_hook(room, player_id))
            if _state_value(room) == RoomState.ATTACKING.value and room.current_attacker == player_id:
                self._start_timer(room, now)
            return True

        if _phase_value(room) == "preparation":
            if battle_rules.enter_battle(room, player_id) is not None:
                return False
            await self._publisher.emit(
                "attacks_updated",
                {
                    "current_attacker": room.current_attacker,
                    "attacks_remaining": room.attacks_remaining,
                },
                room=room.id,
            )
            await self._emit_phase(room)
            self._note_enter_battle(room, player_id)
        elif _phase_value(room) == "battle":
            player = room.players[player_id]
            cells = battle_rules.attackable_cells(player)
            if not cells or room.attacks_remaining <= 0:
                if battle_rules.enter_end(room, player_id) is not None:
                    return False
                await self._emit_phase(room)
                self._note_enter_end(room, player_id)
            elif self.fire_hook is None:
                return False
            else:
                x, y = self.rng.choice(cells)
                await self._maybe_await(self.fire_hook(room, player_id, x, y))
        elif _phase_value(room) == "end":
            if await self._apply_turn_end(room, player_id) is None:
                return False
        else:
            return False

        if _state_value(room) == RoomState.ATTACKING.value and room.current_attacker == player_id:
            self._start_timer(room, now)
        return True

    async def _timeout_action(self, room: Room, player_id: str, now: float) -> bool:
        note: str | None = None
        if _phase_value(room) == "preparation":
            if battle_rules.enter_battle(room, player_id) is None:
                await self._publisher.emit(
                    "attacks_updated",
                    {
                        "current_attacker": room.current_attacker,
                        "attacks_remaining": room.attacks_remaining,
                    },
                    room=room.id,
                )
                await self._emit_phase(room)
                self._note_enter_battle(room, player_id)
                note = "思考超时：已自动进入战斗阶段"

        elif _phase_value(room) == "battle":
            player = room.players[player_id]
            cells = battle_rules.attackable_cells(player)
            if not cells or room.attacks_remaining <= 0:
                if battle_rules.enter_end(room, player_id) is None:
                    await self._emit_phase(room)
                    self._note_enter_end(room, player_id)
                    note = "思考超时：已自动进入结束阶段"
            else:
                x, y = self.rng.choice(cells)
                if self.fire_hook is None:
                    # Ticket #9 owns attack effects; do not fake a shot.
                    note = "思考超时：自动开火待攻击能力接入"
                else:
                    await self._maybe_await(self.fire_hook(room, player_id, x, y))
                    note = f"思考超时：已自动开火 ({x},{y})"

        elif _phase_value(room) == "end":
            ack = await self._apply_turn_end(room, player_id)
            if ack is not None:
                note = (
                    "思考超时：已自动进入新的大回合"
                    if ack.get("new_round")
                    else "思考超时：已自动交出回合"
                )

        if note is None:
            self._start_timer(room, now)
            return False

        await self._emit_message(room, player_id, note)
        # end_turn already restarted the clock for the next attacker; the other
        # fallback actions happened on the same player's clock.
        if room.turn_timer_attacker == player_id:
            self._start_timer(room, now)
        return True