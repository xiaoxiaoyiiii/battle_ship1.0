"""AI seat turn driver (ticket #13).

This is the only place that turns AI policy decisions into service calls. It
drives **one seat's whole turn** (interactive-card answers included) so an AI
room can never stall and never leaves a pending channel behind.

Seat semantics (lesson #35): a turn belongs to a *seat*, not to a room. The
production hook only accepts the room's computer seat; the seat-agnostic entry
point (run_seat_turn) is the same executor and is what the out-of-repo
self-play harness drives both seats with, so a measurement never runs a copy of
the policy.

Turn shape (legacy _ai_turn_loop / _ai_master_turn):

* easy/normal/hard: enter battle -> (normal/hard) play one safe card -> fire
  until the budget is spent -> enter end -> end turn, retrying while a chain
  window is open (a refused action must never freeze the room);
* master: prepare-phase card window -> enter battle -> interleave card plays
  (up to CARDS_PER_TURN) with shots chosen from recon -> end phase -> end turn.

Every card that opens a pending channel is answered **in the same turn**: the
placement flow (增援 / 死者苏生 / 滥竽充数 / 绝处逢生 / 神机妙算 redeploy), the
temp-data picks (桃园结义 / 亡羊补牢 / 明智埋葬 / 灵气复苏 / 仁王之盾) and the
神机妙算 declaration. A board reset (回光返照 / 败者食尘 / 灵气复苏) is finished
by re-placing the AI board, which gameplay completes inside the same stack frame
(lesson #38).
"""

from __future__ import annotations

import asyncio
import inspect
import random
from typing import Any

from ..domain import placement as placement_rules
from ..domain.ai import master as master_rules
from ..domain.ai import policies
from ..domain.ai.difficulty import ai_seat_id, is_ai_seat
from ..domain.magic import interaction as interaction_rules
from ..domain.magic import temps as magic_temps
from ..domain.magic.rules import can_play_magic_card
from ..domain.room import BOARD_SIZE, Room, RoomState, alive_ships
from ..infra.logging import get_logger
from ..infra.timers import TaskRegistry
from .rooms import Connection, RoomService

logger = get_logger("ai")

#: A seat may owe several placement answers (multi-ship placements). The bound
#: only exists so a broken candidate computation cannot loop forever.
PENDING_CONSUME_STEPS = 12
#: Upper bound for the master turn loop (one action per iteration). A single
#: turn legally needs 6 shots + 3 cards + phase changes, so this is a wall-clock
#: guard against handlers that keep refusing our actions, never a normal exit.
MASTER_TURN_STEPS = 60


def _state(room: Room) -> str:
    return str(getattr(room.state, "value", room.state))


def _phase(room: Room) -> str:
    return str(getattr(room.current_phase, "value", room.current_phase))


class AiService:
    """Drive AI seats through their turns. Nothing here decides *what* to play."""

    def __init__(
        self,
        rooms: RoomService,
        gameplay: Any,
        battle: Any = None,
        magic: Any = None,
        *,
        rng: Any = None,
        pacing_seconds: float = 0.5,
        settle_poll_seconds: float = 0.3,
        settle_steps: int = 40,
        turn_steps: int = MASTER_TURN_STEPS,
        retry_pause_seconds: float = 0.5,
        retries: int = 20,
        timers: TaskRegistry | None = None,
    ) -> None:
        self.rooms = rooms
        self.gameplay = gameplay
        self.battle = battle
        self.magic = magic
        #: None = the module-level random, which is what random.seed() (drivers,
        #: tests) seeds and what the rest of the backend uses (lesson #36).
        self.rng = rng
        #: Legacy pacing: humans must be able to see which card landed before
        #: the next one; shots are deliberately not paced.
        self.pacing_seconds = max(0.0, float(pacing_seconds))
        self.settle_poll_seconds = max(0.0, float(settle_poll_seconds))
        self.settle_steps = max(1, int(settle_steps))
        self.turn_steps = max(1, int(turn_steps))
        self.retry_pause_seconds = max(0.0, float(retry_pause_seconds))
        self.retries = max(1, int(retries))
        #: Shared with the magic service in production, so destroying a room
        #: also cancels its AI turn; a private registry otherwise.
        self.timers = timers or TaskRegistry()
        self._active: set[tuple[str, str]] = set()

    # ------------------------------------------------------------- utilities

    @staticmethod
    def _connection(room: Room, player_id: str) -> Connection:
        player = room.players.get(player_id)
        sid = (player.socket_id if player is not None else None) or player_id
        user_id = player.user_id if player is not None else None
        return Connection(sid=sid, user_id=user_id)

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _log(self, room: Room, text: str, event_type: str = "magic") -> None:
        """Record one AI action in the room log (the replay recorder sees it)."""

        writer = getattr(self.magic, "log_action", None)
        if writer is None:
            return
        await self._maybe_await(writer(room, text, event_type))

    def _room(self, room_id: str) -> Room | None:
        return self.rooms.get_room(room_id)

    @staticmethod
    def _waiting_on_other_placement(room: Room, player_id: str) -> bool:
        """True while some other seat still has to place its board."""

        return any(
            other != player_id and not (seat.ships or [])
            for other, seat in room.players.items()
        )

    # ------------------------------------------------------- public entries

    async def run_turn(self, room: Room, player_id: str) -> bool:
        """Production hook (gameplay.ai_turn_hook): start the computer seat's turn.

        The whole turn runs as a background task so the 1s turn watchdog never
        waits for a chain window or a pacing pause. A turn already running for
        this seat is not started twice.
        """

        if not room.is_ai_room or player_id != ai_seat_id(room):
            return False
        return await self.start_turn(room, player_id)

    async def start_turn(self, room: Room, player_id: str) -> bool:
        """Start one seat's turn in the background; False if it is already running."""

        key = (room.id, str(player_id))
        if key in self._active:
            return False
        self._active.add(key)
        task = self.timers.spawn(room.id, self._execute(room, str(player_id), key))
        if task is None:
            # No running loop (unit callers): finish inline instead of losing
            # the turn. Never leave the seat's turn unstarted.
            await self._execute(room, str(player_id), key)
        return True

    async def run_seat_turn(self, room: Room, player_id: str) -> bool:
        """Seat-agnostic executor, awaited (tests + the self-play driver)."""

        key = (room.id, str(player_id))
        if key in self._active:
            return False
        self._active.add(key)
        return await self._execute(room, str(player_id), key)

    async def _execute(self, room: Room, player_id: str, key: tuple[str, str]) -> bool:
        try:
            return await self._run_turn(room, player_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - one bad turn must not kill the loop
            # Never silent: a broken turn is how "the AI looks alive but does
            # nothing" starts (lesson #34). The room log is the operator surface.
            logger.error(
                "ai turn failed",
                extra={
                    "room_id": room.id,
                    "player_id": player_id,
                    "error_type": type(error).__name__,
                },
                exc_info=error,
            )
            try:
                await self._log(
                    room, f"AI 回合执行异常（{type(error).__name__}），已中断", "system"
                )
            except Exception:  # noqa: BLE001
                pass
            return False
        finally:
            self._active.discard(key)

    # ----------------------------------------------------------- turn shape

    async def _run_turn(self, room: Room, player_id: str) -> bool:
        if player_id not in room.players:
            return False
        if _state(room) != RoomState.ATTACKING.value:
            return False
        if room.current_attacker != player_id:
            return False
        # A chain window opened by the other seat's last card must settle before
        # we act: attacks / plays are refused while the window is open.
        # 上一轮遗留的本座位待办（如神机妙算宣言）先答掉，否则阶段转换会一直被挡。
        await self.consume_pending(room, player_id)
        room = self._room(room.id) or room
        if room.chain or room.chain_waiting:
            room, ok = await self.settle(room, player_id)
            if not ok:
                return False
        if policies.is_master(room, player_id):
            await self._master_turn(room, player_id)
        else:
            await self._standard_turn(room, player_id)
        return True

    async def _standard_turn(self, room: Room, player_id: str) -> None:
        """easy/normal/hard: one card, then fire, then end the turn."""

        if _phase(room) == "preparation":
            await self._enter_battle(room, player_id)
        await self._play_standard_card(room, player_id)
        await self._wait_chain(room, player_id)

        for _ in range(self.turn_steps):
            room = self._room(room.id)
            if room is None or _state(room) == RoomState.GAME_OVER.value:
                return
            if room.current_attacker != player_id:
                return
            if _phase(room) == "preparation":
                # Defensive parity with the master loop: a card may have moved
                # the turn back to preparation; continue instead of spinning.
                if not await self._enter_battle(room, player_id):
                    return
                continue
            if _phase(room) != "battle":
                break
            if int(room.attacks_remaining or 0) <= 0:
                break
            shot = policies.choose_attack(room, player_id, rng=self.rng)
            if shot is None:
                break
            await self.battle.fire(room, player_id, shot[0], shot[1])
            await self._wait_chain(room, player_id)

        await self._finish_turn(room, player_id)

    async def _master_turn(self, room: Room, player_id: str) -> None:
        """master: preparation window, then cards interleaved with recon shots."""

        played = 0
        budget = int(master_rules.CARDS_PER_TURN)

        # Preparation-phase window: 余音绕梁 can only be played here, and every
        # speed-1/2 card may be played before the phase flips.
        for _ in range(budget):
            room = self._room(room.id)
            if room is None or _state(room) == RoomState.GAME_OVER.value:
                return
            if room.current_attacker != player_id or _phase(room) != "preparation":
                break
            if played >= budget:
                break
            await asyncio.sleep(self.pacing_seconds)
            if not await self._master_play_one(room, player_id, played):
                break
            played += 1
            room, ok = await self.settle(room, player_id)
            if not ok:
                return

        if not await self._enter_battle(room, player_id):
            room = self._room(room.id)
            if room is None or _state(room) == RoomState.GAME_OVER.value:
                return
        room, ok = await self.settle(room, player_id)
        if not ok:
            return

        for _ in range(self.turn_steps):
            room = self._room(room.id)
            if room is None or _state(room) == RoomState.GAME_OVER.value:
                return
            if room.current_attacker != player_id:
                return
            if _state(room) == RoomState.PLACING_SHIPS.value:
                # A card replaced the board. Re-place our half; a human seat
                # that still has to place is simply waited for (there is
                # nothing else the AI may do). The placement completion then
                # puts the room back on the rails by itself.
                await self._place_board(room, player_id)
                room = self._room(room.id)
                if room is None or _state(room) == RoomState.GAME_OVER.value:
                    return
                if _state(room) == RoomState.PLACING_SHIPS.value:
                    if self._waiting_on_other_placement(room, player_id):
                        return
                    room, ok = await self.settle(room, player_id)
                    if not ok:
                        return
                    continue
                room, ok = await self.settle(room, player_id)
                if not ok:
                    return
                continue
            if _state(room) != RoomState.ATTACKING.value:
                room, ok = await self.settle(room, player_id)
                if not ok:
                    return
                continue
            if room.chain or room.chain_waiting:
                room, ok = await self.settle(room, player_id)
                if not ok:
                    return
                continue
            if _phase(room) == "preparation":
                # 回光返照 finishes on the preparation phase with zero attacks;
                # without entering battle the turn could never reach the end
                # phase (the 9-battle gate requires battle) and would freeze.
                if await self._enter_battle(room, player_id):
                    room, ok = await self.settle(room, player_id)
                    if not ok:
                        return
                    continue

            progressed = False
            if played < budget:
                await asyncio.sleep(self.pacing_seconds)
                if await self._master_play_one(room, player_id, played):
                    played += 1
                    progressed = True
                    # Answer our own pending right away: any later action could
                    # be refused by the wait gate.
                    await self.consume_pending(room, player_id)
                room = self._room(room.id)
                if room is None or _state(room) == RoomState.GAME_OVER.value:
                    return
                if room.current_attacker != player_id:
                    return
                if progressed:
                    room, ok = await self.settle(room, player_id)
                    if not ok:
                        return
                    continue

            if int(room.attacks_remaining or 0) > 0:
                shot = policies.choose_attack(room, player_id, rng=self.rng)
                if shot is not None:
                    await self.battle.fire(room, player_id, shot[0], shot[1])
                    room, ok = await self.settle(room, player_id)
                    if not ok:
                        return
                    continue
            break

        await self._finish_turn(room, player_id)

    async def _finish_turn(self, room: Room, player_id: str) -> None:
        """Enter the end phase and hand the turn over, retrying while refused."""

        for _ in range(self.retries):
            room = self._room(room.id)
            if room is None or _state(room) == RoomState.GAME_OVER.value:
                return
            if room.current_attacker != player_id:
                return
            if not (room.chain or room.chain_waiting):
                # 收尾阶段仍可能有本座位的未答待办；先答再换阶段，不靠强跳阶段。
                await self.consume_pending(room, player_id)
                room = self._room(room.id)
                if room is None or _state(room) == RoomState.GAME_OVER.value:
                    return
                if room.current_attacker != player_id:
                    return
            if _state(room) == RoomState.PLACING_SHIPS.value:
                await self._place_board(room, player_id)
                room = self._room(room.id)
                if room is None or _state(room) == RoomState.GAME_OVER.value:
                    return
                if _state(room) == RoomState.PLACING_SHIPS.value:
                    if self._waiting_on_other_placement(room, player_id):
                        return
                    await asyncio.sleep(self.retry_pause_seconds)
                continue
            if room.chain or room.chain_waiting:
                await asyncio.sleep(self.retry_pause_seconds)
                continue
            if _phase(room) == "preparation":
                if not await self._enter_battle(room, player_id):
                    await asyncio.sleep(self.retry_pause_seconds)
                continue
            if _phase(room) == "battle":
                if not await self._enter_end(room, player_id):
                    await asyncio.sleep(self.retry_pause_seconds)
                continue
            if _phase(room) == "end":
                if await self._end_turn(room, player_id):
                    return
                await asyncio.sleep(self.retry_pause_seconds)
                continue
            return

    # ------------------------------------------------------- action calls

    async def _enter_battle(self, room: Room, player_id: str) -> bool:
        ack = await self.gameplay.enter_battle_phase(
            self._connection(room, player_id),
            {"room_id": room.id, "player_id": player_id},
        )
        return bool(ack and ack.get("status") == "success")

    async def _enter_end(self, room: Room, player_id: str) -> bool:
        ack = await self.gameplay.enter_end_phase(
            self._connection(room, player_id),
            {"room_id": room.id, "player_id": player_id},
        )
        return bool(ack and ack.get("status") == "success")

    async def _end_turn(self, room: Room, player_id: str) -> bool:
        ack = await self.gameplay.end_turn(
            self._connection(room, player_id),
            {"room_id": room.id, "player_id": player_id},
        )
        return bool(ack and ack.get("status") == "success")

    async def _play_standard_card(self, room: Room, player_id: str) -> bool:
        index = policies.choose_safe_card_index(room, player_id)
        if index is None:
            return False
        card = room.players[player_id].magic_hand[index]
        ack = await self.magic.use_magic_card(
            self._connection(room, player_id),
            {
                "room_id": room.id,
                "player_id": player_id,
                "card": {
                    "name": card.name,
                    "speed": card.speed,
                    "type": card.type,
                    "description": getattr(card, "description", ""),
                },
                "targets": {},
            },
        )
        if not (ack and ack.get("status") == "success"):
            await self._log(
                room,
                f"AI 出牌被拒（{card.name}）：{(ack or {}).get('message', '')}",
                "system",
            )
            return False
        await self.consume_pending(room, player_id)
        return True

    def master_pick(self, room: Room, player_id: str,
                    cards_played: int = 0) -> tuple[int | None, dict[str, Any]]:
        """Master card choice with the trial-play gate: (hand index, targets)."""

        player = room.players.get(player_id)
        if player is None or not player.magic_hand:
            return None, {}
        if int(cards_played or 0) >= int(master_rules.CARDS_PER_TURN):
            return None, {}
        playable: list[int] = []
        targets_by_index: dict[int, dict[str, Any]] = {}
        for index, card in enumerate(player.magic_hand):
            if getattr(card, "name", None) not in master_rules.MASTER_ENABLED_CARDS:
                continue
            if not can_play_magic_card(room, player_id, card):
                continue
            # Trial play: a card whose target/conditions cannot be produced is
            # dropped **without** spending the play budget.
            targets = master_rules.card_readiness(room, player_id, card)
            if targets is None:
                continue
            if master_rules.is_target_card(getattr(card, "name", None)):
                targets_by_index[index] = targets
            playable.append(index)
        index = master_rules.choose_card(room, player_id, playable)
        if index is None:
            return None, {}
        return index, (targets_by_index.get(index) or {})

    async def _master_play_one(self, room: Room, player_id: str, played: int) -> bool:
        index, targets = self.master_pick(room, player_id, played)
        if index is None:
            return False
        hand = room.players[player_id].magic_hand
        if not (0 <= index < len(hand)):
            return False
        card = hand[index]
        ack = await self.magic.use_magic_card(
            self._connection(room, player_id),
            {
                "room_id": room.id,
                "player_id": player_id,
                "card": {
                    "name": card.name,
                    "speed": card.speed,
                    "type": card.type,
                    "description": getattr(card, "description", ""),
                },
                "targets": targets or {},
            },
        )
        if ack and ack.get("status") == "success":
            return True
        # A trial-play miss is a log line, not a silent retry loop.
        await self._log(
            room,
            f"大师 AI 出牌被拒（{card.name}）：{(ack or {}).get('message', '')}",
            "system",
        )
        return False

    # ------------------------------------------------------- settle / waits

    async def _wait_chain(self, room: Room, player_id: str) -> None:
        for _ in range(self.retries):
            room = self._room(room.id)
            if room is None or _state(room) == RoomState.GAME_OVER.value:
                return
            if not (room.chain or room.chain_waiting):
                # 连锁结算后才会开出的待办（神机妙算宣言、选船等）要在这里就地答复，
                # 否则回合收尾时 enter_end 一直被它挡住，AI 卡在结束阶段。
                await self.consume_pending(room, player_id)
                return
            await asyncio.sleep(self.retry_pause_seconds)

    async def settle(self, room: Room, player_id: str) -> tuple[Room | None, bool]:
        """Wait until nothing is in flight; consume our own pendings meanwhile.

        Returns (room, ok); ok=False means the turn must not continue (room gone,
        game over, or the turn moved on).
        """

        for _ in range(self.settle_steps):
            room = self._room(room.id)
            if room is None:
                return None, False
            if _state(room) == RoomState.GAME_OVER.value:
                return room, False
            if room.current_attacker != player_id:
                return room, False
            # Our own pending answers are ours to give; answer them before
            # judging whether the room is settled, or we wait for ourselves.
            await self.consume_pending(room, player_id)
            room = self._room(room.id)
            if room is None:
                return None, False
            if _state(room) == RoomState.GAME_OVER.value:
                return room, False
            if room.current_attacker != player_id:
                return room, False
            if not self.unsettled(room, player_id):
                return room, True
            await asyncio.sleep(self.settle_poll_seconds)
        room = self._room(room.id)
        if room is not None:
            remaining = "、".join(self.unsettled(room, player_id)) or "未知"
            await self._log(room, f"AI 等待结算收敛超时（{remaining}），继续回合", "system")
        return room, True

    def unsettled(self, room: Room, player_id: str) -> list[str]:
        """Why this seat's turn cannot move on yet ([] = it can).

        Narrowed to **this seat's own** pendings on purpose: a human's placement
        or ship pick is theirs to answer, and waiting on it looks exactly like
        an AI freeze (legacy 2026-09-22). The chain window and a blocked phase
        transition stay room-level: those mean our own action has not landed.
        """

        reasons: list[str] = []
        if room.chain:
            reasons.append(f"连锁栈还有 {len(room.chain)} 项")
        if room.chain_waiting:
            reasons.append(f"连锁响应窗口还开着（轮到 {room.chain_window}）")
        temp = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
        placement = temp.get("pending_placement")
        if isinstance(placement, dict) and placement.get("caster") == player_id:
            reasons.append(f"放置流程未完成（{placement.get('kind')}）")
        shenji = temp.get("pending_shenji")
        if isinstance(shenji, dict) and shenji.get("caster") == player_id:
            reasons.append("神机妙算宣言未完成")
        choice_type = temp.get("type")
        if choice_type and temp.get("caster") == player_id:
            reasons.append(f"卡牌选择未完成（{choice_type}）")
        dice = getattr(room, "pending_dice_discard", None)
        if isinstance(dice, dict) and dice.get(player_id) is False:
            reasons.append("命运骰子弃牌未完成")
        picks = getattr(room, "pending_ship_picks", None)
        if isinstance(picks, list):
            mine = [p for p in picks if isinstance(p, dict) and p.get("player") == player_id]
            if mine:
                reasons.append(
                    "选船待办未完成（" + ",".join(str(p.get("reason")) for p in mine) + "）"
                )
        if getattr(room, "priority_continue", None):
            reasons.append("被拦下的阶段转换还没补上")
        return reasons

    # ----------------------------------------------------- pending consumers

    async def consume_pending(self, room: Room, player_id: str) -> bool:
        """Answer every pending channel this seat owns. True = nothing left."""

        await self.consume_placement(room, player_id)
        room = self._room(room.id)
        if room is None:
            return True
        await self.consume_choice(room, player_id)
        room = self._room(room.id)
        if room is None:
            return True
        # A seat driven by this executor is not necessarily an "ai-" id (the
        # self-play harness drives the other seat through the same executor), so
        # a card like 守株待兔 can queue a ship pick for it instead of answering
        # synchronously. Leaving that queue unanswered both loses the effect and
        # freezes every later settle (it is in "unsettled").
        await self.consume_ship_picks(room, player_id)
        room = self._room(room.id)
        if room is None:
            return True
        await self.consume_shenji(room, player_id)
        return True

    async def consume_placement(self, room: Room, player_id: str) -> bool:
        """Place every queued ship of the seat's placement flow, in place."""

        for _ in range(PENDING_CONSUME_STEPS):
            room = self._room(room.id)
            if room is None or _state(room) == RoomState.GAME_OVER.value:
                return True
            temp = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
            pending = temp.get("pending_placement")
            if not isinstance(pending, dict) or pending.get("caster") != player_id:
                return True
            kind = str(pending.get("kind") or "")
            allow: set[tuple[int, int]] = set()
            if kind == "last_stand":
                allow = {
                    cell
                    for cell in (
                        interaction_rules.cell_xy(item)
                        for item in (room.game_effects.get("last_stand_cells") or [])
                    )
                    if cell
                }
            elif kind == "shenji_redeploy":
                allow = {
                    cell
                    for cell in (
                        interaction_rules.cell_xy(item)
                        for item in (room.game_effects.get("shenji_redeploy_cells") or [])
                    )
                    if cell
                }
            if kind == "last_stand":
                # 绝处逢生 sacrificed every ship; the normal "not occupied by
                # your own ships" rule would reject all six allowed cells
                # (sunken ships stay in player.ships). The server validates this
                # path against the allowed set only, so mirror that.
                legal = sorted(allow)
            else:
                ignore_sunken = kind == "shenji_redeploy"
                legal = []
                for x in range(BOARD_SIZE):
                    for y in range(BOARD_SIZE):
                        if allow and (x, y) not in allow:
                            continue
                        if interaction_rules.placement_error(
                            room, player_id, x, y,
                            allow_cells=allow, ignore_sunken=ignore_sunken,
                        ):
                            continue
                        legal.append((x, y))
            if not legal:
                # No legal cell: cancel explicitly. Never leave a pending nobody
                # can answer (that would freeze the turn forever).
                await self.magic.cancel_placement(room, player_id)
                await self._log(room, "AI 的放置流程没有合法落点，已取消", "system")
                continue
            cell = policies.resolve_placement(room, player_id, kind, legal, rng=self.rng)
            if cell is None:
                await self.magic.cancel_placement(room, player_id)
                await self._log(room, "AI 的放置流程无法决策，已取消", "system")
                continue
            ack = await self.magic.confirm_reinforcement_position(
                self._connection(room, player_id),
                {
                    "room_id": room.id,
                    "player_id": player_id,
                    "position": {"x": int(cell[0]), "y": int(cell[1])},
                },
            )
            if not (ack and ack.get("status") == "success"):
                await self.magic.cancel_placement(room, player_id)
                await self._log(
                    room, f"AI 放置被拒（{ack}），已取消放置流程", "system"
                )
                continue
        return True

    async def consume_choice(self, room: Room, player_id: str) -> bool:
        """Answer the seat's temp-data card pick (桃园/亡羊/埋葬/灵气/仁王)."""

        temp = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
        kind = temp.get("type")
        if not kind or temp.get("caster") != player_id:
            return True

        if kind == "taoyuan_choice":
            cards = list(temp.get("cards") or [])
            if not cards:
                return True
            pick = policies.resolve_choice(
                room, player_id, kind, cards, rng=self.rng
            )
            chosen = cards.index(pick) if pick in cards else 0
            rest = [i for i in range(len(cards)) if i != chosen]
            # In a human flow the opponent picks their own share; in an AI room
            # the AI answers both, handing the opponent the least valuable rest.
            opponent_index = (
                min(
                    rest,
                    key=lambda i: master_rules.card_value(
                        getattr(cards[i], "name", cards[i])
                    ),
                )
                if rest
                else -1
            )
            ack = await self.magic.confirm_magic_target(
                {
                    "room_id": room.id,
                    "player_id": player_id,
                    "temp_data_id": kind,
                    "target_data": {
                        "caster_choice": chosen,
                        "opponent_choice": opponent_index,
                    },
                }
            )
            if not (ack and ack.get("status") == "success"):
                magic_temps.finish(room, kind, owner=seat)
                await self._log(
                    room, f"AI 的桃园结义选择失败（{ack}），已清理待办", "system"
                )
            return True

        if kind == "wangyang_choice":
            cards = list(temp.get("cards") or [])
            if not cards:
                magic_temps.finish(room, kind, owner=seat)
                return True
            pick = policies.resolve_choice(
                room, player_id, kind, cards, rng=self.rng
            )
            chosen = cards.index(pick) if pick in cards else 0
            # The field name is chosen_index (what _confirm_wangyang reads);
            # card_index would only answer "无效的卡牌选择".
            ack = await self.magic.confirm_magic_target(
                {
                    "room_id": room.id,
                    "player_id": player_id,
                    "temp_data_id": kind,
                    "target_data": {"chosen_index": chosen},
                }
            )
            if not (ack and ack.get("status") == "success"):
                magic_temps.finish(room, kind, owner=seat)
                await self._log(
                    room, f"AI 的亡羊补牢选择失败（{ack}），已清理待办", "system"
                )
            return True

        if kind == "bury_choice":
            candidates = list(temp.get("candidates") or [])
            if not candidates:
                magic_temps.finish(room, kind, owner=seat)
                return True
            # Burying a card in the opponent's hand is pure profit (the caster
            # also draws one); burying from the deck is a net wash.
            opponent_side = [c for c in candidates if c.get("source") == "opponent_hand"]
            pool = opponent_side or candidates
            best_name = policies.resolve_choice(
                room, player_id, kind,
                [c.get("name") for c in pool], rng=self.rng,
            )
            chosen = next((c for c in pool if c.get("name") == best_name), pool[0])
            index = candidates.index(chosen)
            ack = await self.magic.confirm_magic_target(
                {
                    "room_id": room.id,
                    "player_id": player_id,
                    "temp_data_id": kind,
                    "target_data": {
                        "source": chosen.get("source"),
                        "source_index": chosen.get("index"),
                        "chosen_index": index,
                    },
                }
            )
            if not (ack and ack.get("status") == "success"):
                magic_temps.finish(room, kind, owner=seat)
                await self._log(
                    room, f"AI 的明智埋葬选择失败（{ack}），已清理待办", "system"
                )
            return True

        if kind == "lingqi_choice":
            try:
                max_ships = int(temp.get("max_ships") or BOARD_SIZE)
            except (TypeError, ValueError):
                max_ships = BOARD_SIZE
            max_ships = max(1, min(BOARD_SIZE, max_ships))
            options = list(range(1, max_ships + 1))
            picked = policies.resolve_choice(
                room, player_id, kind, options, rng=self.rng
            )
            try:
                picked = int(picked)
            except (TypeError, ValueError):
                picked = max_ships
            picked = max(1, min(max_ships, picked))
            ack = await self.magic.confirm_magic_target(
                {
                    "room_id": room.id,
                    "player_id": player_id,
                    "temp_data_id": kind,
                    "target_data": {"target_ships": picked},
                }
            )
            if not (ack and ack.get("status") == "success"):
                magic_temps.finish(room, kind, owner=seat)
                await self._log(
                    room, f"AI 的灵气复苏选择失败（{ack}），已清理待办", "system"
                )
            return True

        if kind == "shield_choice":
            caster = room.players.get(player_id)
            alive_indices = (
                [
                    index
                    for index, ship in enumerate(getattr(caster, "ships", None) or [])
                    if ship not in (caster.sunken_ships or [])
                    and len(ship.hits or []) < len(ship.positions or [])
                ]
                if caster
                else []
            )
            if not alive_indices:
                magic_temps.finish(room, kind, owner=seat)
                return True
            indices = alive_indices[:3]
            ack = await self.magic.confirm_magic_target(
                {
                    "room_id": room.id,
                    "player_id": player_id,
                    "temp_data_id": kind,
                    "target_data": {"ship_indices": indices},
                }
            )
            if not (ack and ack.get("status") == "success"):
                magic_temps.finish(room, kind, owner=seat)
                await self._log(
                    room, f"AI 的仁王之盾选择失败（{ack}），已清理待办", "system"
                )
            return True

        return True

    async def consume_ship_picks(self, room: Room, player_id: str) -> bool:
        """Answer every queued "pick one of your own ships" for this seat.

        The AI seat normally answers synchronously inside request_ship_pick; this
        path covers (a) a seat driven by this executor that is not an ai- id and
        (b) defensive consumption of anything that still reached the queue.
        """

        for _ in range(PENDING_CONSUME_STEPS):
            room = self._room(room.id)
            if room is None or _state(room) == RoomState.GAME_OVER.value:
                return True
            entry = interaction_rules.top_ship_pick(room, player_id)
            if entry is None:
                return True
            reason = str(entry.get("reason") or "")
            if reason == "shield_choice":
                # The multi-select branch (consume_choice) owns this one: it needs
                # the selection, not a single ship. Never leave it queued.
                interaction_rules.consume_ship_pick(room, player_id, reason)
                continue
            player = room.players.get(player_id)
            alive = alive_ships(player) if player is not None else []
            if not alive:
                interaction_rules.clear_ship_picks(room, player_id)
                await self._log(room, "AI 的选船待办无可选战舰，已清理", "system")
                return True
            picked = policies.resolve_ship_pick(
                room, player_id, reason, alive, rng=self.rng
            )
            if picked is None or not picked.positions:
                interaction_rules.clear_ship_picks(room, player_id)
                await self._log(room, "AI 的选船待办无法决策，已清理", "system")
                return True
            ack = await self.magic.confirm_sacrifice(
                self._connection(room, player_id),
                {
                    "room_id": room.id,
                    "player_id": player_id,
                    "position": {
                        "x": int(picked.positions[0].x),
                        "y": int(picked.positions[0].y),
                    },
                },
            )
            if not (ack and ack.get("status") == "success"):
                interaction_rules.consume_ship_pick(room, player_id, reason)
                await self._log(
                    room, f"AI 的选船应答被拒（{ack}），已清理待办", "system"
                )
        return True

    async def consume_shenji(self, room: Room, player_id: str) -> bool:
        """Answer the 神机妙算 declaration window in place."""

        temp = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
        pending = temp.get("pending_shenji")
        if not isinstance(pending, dict) or pending.get("caster") != player_id:
            return True
        value = policies.resolve_choice(
            room, player_id, "shenji_predict", list(range(BOARD_SIZE + 1)),
            rng=self.rng,
        )
        try:
            value = max(0, min(BOARD_SIZE, int(value)))
        except (TypeError, ValueError):
            value = 0
        ack = await self.magic.confirm_shenji_declare(
            self._connection(room, player_id),
            {"room_id": room.id, "player_id": player_id, "prediction": value},
        )
        if not (ack and ack.get("status") == "success"):
            room.magic_temp_data.pop("pending_shenji", None)
            await self._log(
                room, f"AI 的神机妙算宣言失败（{ack}），已清理待办", "system"
            )
        return True

    # ----------------------------------------------------------- board reset

    async def _place_board(self, room: Room, player_id: str) -> bool:
        """Re-place one seat's board after a reset card.

        The AI seat finishes through gameplay.ai_place_board_now, which completes
        the reset inside the same stack frame (a human never sees a placement
        screen they cannot act on, lesson #38). Any other seat is placed through
        the same public place_ships path the self-play harness uses.
        """

        player = room.players.get(player_id)
        if player is None:
            return False
        if is_ai_seat(player_id):
            return bool(await self.gameplay.ai_place_board_now(room, player_id))
        if player.ships:
            return False
        count = placement_rules.expected_ship_count(player)
        cells = [(x, y) for x in range(BOARD_SIZE) for y in range(BOARD_SIZE)]
        (self.rng or random).shuffle(cells)
        payload = [
            {"positions": [{"x": x, "y": y}], "hits": []} for x, y in cells[:count]
        ]
        ack = await self.gameplay.place_ships(
            self._connection(room, player_id),
            {"room_id": room.id, "player_id": player_id, "ships": payload},
        )
        return bool(ack and ack.get("status") == "success")


__all__ = ["AiService", "MASTER_TURN_STEPS", "PENDING_CONSUME_STEPS"]
