"""Magic-card use cases: deck/hand sync, targets, registry dispatch (ticket #10).

The socket layer only translates frames. This service owns the protocol-level
order the legacy handler had:

1. identity -> target sanitisation -> frozen/chain/priority/magic-blocked gates;
2. hand membership -> evaluate_cast (playability + per-card requirements +
   ship-pick obligation + registry), the one gate both activation paths use;
3. remove the card and push it on the chain stack;
4. resolve the stack (ticket #12 replaces this direct resolution with the real
   response window), refund on a failed effect, then re-push the authoritative
   hand / ships / effects / phase frames.

No business rule lives here: card behaviour is in
battleship.domain.magic.effects and registered in battleship.domain.magic.registry.
"""

from __future__ import annotations

from ..domain.tasks import record_card_play

import asyncio
import inspect
import json
import random
import time
from typing import Any, Awaitable, Callable

from ..domain import battle as battle_rules
from ..domain import effects
from ..domain import placement as placement_rules
from ..domain import replay as replay_rules
from ..domain.ai import policies
from ..domain.magic import deck as deck_rules
from ..domain.magic import field as field_rules
from ..domain.magic import hooks
from ..domain.magic import interaction as interaction_rules
from ..domain.magic import lifecycle as lifecycle_rules
from ..domain.magic import registry
from ..domain.magic.cards import (
    MAGIC_CARDS,
    MagicCard,
    card_by_name,
    card_from_payload,
)
from ..domain.magic import chain as chain_rules
from ..domain.magic.chain import CHAIN_RESPONSE_SECONDS, ChainItem, ChainResult
from ..domain.magic.effects.base import EffectContext, EffectResult
from ..domain.spectate.rules import AREA_TARGET_BOARDS

#: 多回合持续效果：`room.game_effects` 键 → 卡名（监视栏要显示成同一排区块）。
LONG_EFFECT_BADGES: tuple[tuple[str, str], ...] = (
    ("holy_heart", "无暇圣心"),
    ("reinforcement_check", "极限增援"),
)
from ..domain.magic import contract as contract_rules
from ..domain.magic import precheck as magic_precheck
from ..domain.magic import targets as target_rules
from ..domain.magic import temps as magic_temps
from ..domain.magic.rules import (
    BINGLIANG_FAIL_BELOW,
    BINGLIANG_SKIP_PHASES,
    UNIMPLEMENTED,
    action_wait_reason,
    evaluate_cast,
    field_magic_name,
)
from ..domain.room import (
    Player,
    PlayerShip,
    Position,
    Room,
    RoomPhase,
    RoomState,
    alive_ships,
    build_room_sync,
    is_ship_alive,
)
from ..domain.room.sync import EFFECT_BADGES, _spectate_chain_payload, card_payload
from ..infra.logging import get_logger
from ..infra.timers import TaskRegistry
from .rooms import Connection, EventPublisher, NullPublisher, RoomService
from .priority import guard_phase_write
from .settlement import SettlementService

logger = get_logger("magic")

INVALID_SEAT = {"status": "error", "message": "无效的房间或玩家"}
# 摆船待办不存在/不属于你：魔法侧的取消与提交共用同一句话。
NO_PENDING_PLACEMENT = {"status": "error", "message": "没有等待放置的战舰"}
FINISHED_GAME = {"status": "error", "message": "对局已结束"}
OPPONENT_DISCONNECTED = "对手已掉线，等待重连中"
CHAIN_BUSY = "连锁响应中，请先响应连锁"

#: Fields a client may stage through select_magic_target (whitelist, not blacklist).
SELECTION_TARGET_KEYS = frozenset({
    "caster_choice", "opponent_choice", "card_index", "ship_indices",
    "effect_choice", "prediction", "index", "target_area", "target_line",
    "source", "source_index", "chosen_index",
})

KNOWN_CHOICE_IDS = frozenset({
    "taoyuan_choice", "lingqi_choice", "bury_choice", "wangyang_choice",
    "shield_choice",
})

CARD_DESCRIPTIONS: dict[str, str] = {}


def _init_descriptions() -> None:
    from ..domain.magic.cards import MAGIC_CARDS

    for card in MAGIC_CARDS:
        CARD_DESCRIPTIONS.setdefault(card.name, card.description)


_init_descriptions()


def _temp_payload(value: Any) -> Any:
    """把待选择项序列化成线上 JSON：卡牌/战舰对象展开成 dict，不能变成 repr 字符串。"""

    if isinstance(value, dict):
        return {str(key): _temp_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_temp_payload(item) for item in value]
    if hasattr(value, "model_dump"):
        return _temp_payload(value.model_dump())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class MagicService:
    def __init__(
        self,
        rooms: RoomService,
        settlement: SettlementService | None = None,
        *,
        clock: Callable[[], float] | None = None,
        rng: Any | None = None,
        touch_turn: Callable[[Room, str], None] | None = None,
        chain_entry_delay_seconds: float = 0.8,
        chain_display_delay_seconds: float = 1.2,
        chain_response_seconds: float = CHAIN_RESPONSE_SECONDS,
        ai_chain_delay_seconds: float = 0.8,
        timers: TaskRegistry | None = None,
    ) -> None:
        self.rooms = rooms
        self.settlement = settlement
        self.clock = clock or time.time
        self.rng = rng or random
        self.touch_turn = touch_turn
        self.chain_entry_delay_seconds = max(0.0, float(chain_entry_delay_seconds))
        # 0 reproduces the pre-display-delay behaviour exactly (tests/headless).
        self.chain_display_delay_seconds = max(0.0, float(chain_display_delay_seconds))
        self.chain_response_seconds = max(0.0, float(chain_response_seconds))
        self.ai_chain_delay_seconds = max(0.0, float(ai_chain_delay_seconds))
        self.timers = timers or TaskRegistry()
        self._publisher: EventPublisher = NullPublisher()
        self.finish_hook: Callable[..., Awaitable[Any]] | None = None
        #: Ticket #8 owns the placement completion path; #11 injects it so an
        #: AI caster can finish a reset board inside the same stack frame.
        self.ai_place_hook: Callable[[Room, str], Awaitable[bool]] | None = None
        self.ai_choice_hook: Callable[[Room, str], Awaitable[bool]] | None = None
        self._interaction_waits: dict[str, tuple[tuple, float]] = {}
        self.shenji_timeout_seconds = 30.0
        self._shenji_tasks: dict[tuple[str, int], asyncio.Task] = {}
        # Ticket #13 (priority) fills this; without it the chain still resolves.
        self.priority_continue_hook: Callable[..., Awaitable[Any]] | None = None
        # A destroyed room must not leave a 10s timer or a display task behind.
        hooks = getattr(rooms, "destroy_hooks", None)
        if hooks is not None:
            hooks.append(self.cancel_room_timers)

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    @property
    def effects(self) -> Any:
        """只读的事件总线入口（#37）：模块函数入口，不新增全局单例。"""

        return effects

    # ----------------------------------------------------------------- helpers

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
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    @staticmethod
    def _state(room: Room) -> str:
        return getattr(room.state, "value", room.state)

    @staticmethod
    def _phase(room: Room) -> str:
        return getattr(room.current_phase, "value", room.current_phase)

    def _frozen_reason(self, room: Room, player_id: str) -> str | None:
        for pid in room.disconnected:
            if pid != player_id:
                return OPPONENT_DISCONNECTED
        return None

    async def log_action(self, room: Room, text: str,
                        event_type: str = "magic") -> None:
        """Public logging seam for other services (the AI turn driver).

        One implementation of "append to the room log + feed the replay recorder
        + emit game_log"; a second copy elsewhere would drift from this one.
        """

        await self._add_log(room, text, event_type)

    async def _add_log(self, room: Room, text: str, event_type: str = "magic",
                       detail: dict | None = None) -> None:
        entry = {
            "ts": int(self.clock()),
            "type": event_type,
            "text": text,
            "detail": detail,
        }
        room.game_logs.append(entry)
        # Same single replay feed as BattleService.add_log (ticket #18).
        replay_rules.note(room, entry)
        await self._publisher.emit("game_log", entry, room=room.id)

    async def _emit_hand(self, player: Player) -> None:
        if not player.socket_id:
            return
        await self._publisher.emit(
            "hand_updated",
            {"hand": [card_payload(card) for card in player.magic_hand]},
            to=player.socket_id,
        )

    async def _emit_ships_updated(self, room: Room) -> None:
        for pid, player in room.players.items():
            opponent_id = room.opponent_of(pid)
            opponent = room.players.get(opponent_id) if opponent_id else None
            if not player.socket_id:
                continue
            await self._publisher.emit(
                "ships_updated",
                {
                    "player_remaining_ships": player.remaining_ships,
                    "opponent_remaining_ships": opponent.remaining_ships if opponent else 0,
                },
                to=player.socket_id,
            )

    async def _emit_player_ships(self, room: Room, player_id: str) -> None:
        player = room.players.get(player_id)
        if player is None or not player.socket_id:
            return
        await self._publisher.emit(
            "player_ships_updated",
            {"ships": battle_rules.player_ships_payload(player)},
            to=player.socket_id,
        )

    @staticmethod
    def _card_info(name: str) -> dict[str, Any]:
        """监视栏用的卡面信息：名称/速阶/类型/服务端文案（取不到就留空）。"""

        card = None
        try:
            card = card_by_name(name)
        except Exception:  # pragma: no cover - 卡表异常不该拖垮整帧
            card = None
        if card is None:
            return {
                "name": name,
                "speed": None,
                "type": None,
                "description": CARD_DESCRIPTIONS.get(name, ""),
            }
        return {
            "name": card.name,
            "speed": int(card.speed) if getattr(card, "speed", None) is not None else None,
            "type": getattr(card, "type", None),
            "description": getattr(card, "description", None) or CARD_DESCRIPTIONS.get(name, ""),
        }

    @staticmethod
    def _badges(room: Room, player_id: str, player: Player | None) -> list[dict[str, Any]]:
        """本局的持续效果：一次性 flags + 多回合 game_effects 两类合并。

        多回合效果（极限增援、无暇圣心）存在 `room.game_effects` 里而不是
        `player.effect_flags`，旧实现完全看不到它们，监视栏自然缺块。
        """

        if player is None:
            return []
        badges: list[dict[str, Any]] = []
        flags = player.effect_flags
        for attr, label, expiry, suffix in EFFECT_BADGES:
            if not getattr(flags, attr, None):
                continue
            badges.append({
                "name": label,
                "key": attr,
                "label": f"{label}·{suffix}" if suffix else label,
                "description": CARD_DESCRIPTIONS.get(label, ""),
                "expires": expiry,
                "card": MagicService._card_info(label),
            })

        game_effects = room.game_effects if isinstance(room.game_effects, dict) else {}
        for key, label in LONG_EFFECT_BADGES:
            info = game_effects.get(key)
            if not isinstance(info, dict) or info.get("caster") != player_id:
                continue
            remaining = info.get("remaining_turns")
            try:
                remaining_value = int(remaining) if remaining is not None else None
            except (TypeError, ValueError):
                remaining_value = None
            badges.append({
                "name": label,
                "key": key,
                "label": f"{label}·剩余{remaining_value}回合" if remaining_value else label,
                "description": CARD_DESCRIPTIONS.get(label, ""),
                "expires": f"剩余{remaining_value}回合" if remaining_value else "本大回合结束（重新猜拳）时失效",
                "card": MagicService._card_info(label),
            })
        return badges

    async def _emit_active_effects(self, room: Room) -> None:
        field_name = field_magic_name(room)
        field_info = self._card_info(field_name) if field_name else None
        field_owner = getattr(room, "field_magic_owner", None)
        for pid, player in room.players.items():
            if not player.socket_id:
                continue
            opponent_id = room.opponent_of(pid)
            opponent = room.players.get(opponent_id) if opponent_id else None
            await self._publisher.emit(
                "active_effects",
                {
                    "self": self._badges(room, pid, player),
                    "opponent": self._badges(room, opponent_id, opponent) if opponent else [],
                    "field": field_info,
                    "field_owner": field_owner,
                },
                to=player.socket_id,
            )

    async def _emit_card_discarded(self, room: Room, player_id: str | None,
                                   card: Any, reason: str) -> None:
        """#37：牌真正进入弃牌堆之后广播 CARD_DISCARDED（每张一次）。"""

        await hooks.emit(
            room,
            hooks.CARD_DISCARDED,
            {
                "room_id": room.id,
                "player_id": player_id,
                "card": getattr(card, "name", None),
                "reason": reason,
            },
        )

    # -------------------------------------------------------------------- draw

    async def draw(self, room: Room, player_id: str) -> MagicCard | None:
        """Gameplay draw hook: shared deck + duplicate rule + hand frame."""

        result = deck_rules.draw_card(room, player_id, rng=self.rng)
        player = room.players.get(player_id)
        if player is not None and result.card is not None:
            # #37：唯一真实摸牌点（gameplay._draw 只是转调它，重复发会算两次）。
            await hooks.emit(
                room,
                hooks.CARD_DRAWN,
                {
                    "room_id": room.id,
                    "player_id": player_id,
                    "card": result.card.name,
                },
            )
            await self._emit_hand(player)
        elif player is not None and result.duplicate is not None:
            # deck.draw_card 把重复的牌直接塞进弃牌堆（domain 不发事件）。
            await self._emit_card_discarded(
                room, player_id, result.duplicate, "duplicate"
            )
        return result.card

    # ------------------------------------------------------------- ship picks

    async def _emit_ship_pick_request(self, room: Room, entry: dict[str, Any]) -> None:
        if entry.get("silent"):
            return
        player = room.players.get(entry.get("player"))
        if player is None or not player.socket_id:
            return
        alive = alive_ships(player)
        if not alive:
            return
        await self._publisher.emit(
            "sacrifice_request",
            {
                "reason": entry.get("reason"),
                "message": entry.get("message") or "请点选一艘自己的战舰",
                "ships": [
                    {"positions": [{"x": p.x, "y": p.y} for p in ship.positions]}
                    for ship in alive
                ],
            },
            to=player.socket_id,
        )

    async def _dispatch_ship_pick(self, room: Room, player_id: str) -> None:
        entry = interaction_rules.top_ship_pick(room, player_id)
        if entry is not None:
            await self._emit_ship_pick_request(room, entry)

    async def request_ship_pick(
        self, room: Room, chooser_id: str, reason: str, message: str,
        allow_duplicate: bool = False, silent: bool = False,
        *, source_id: str | None = None,
    ) -> PlayerShip | None:
        """Ask one player to click an own living ship.

        AI seats answer synchronously (the human never sees a stalled board);
        humans are queued by priority and receive a sacrifice_request frame.
        """

        chooser = room.players.get(chooser_id)
        if chooser is None:
            return None
        alive = alive_ships(chooser)
        if not alive:
            return None
        if room.is_ai_room and str(chooser_id).startswith("ai-"):
            # Master seats value the pick (sacrifice the ship whose neighbourhood
            # the opponent already probed); the other tiers keep the legacy
            # uniform random choice. Never return None here: leaving a ship pick
            # unanswered is what freezes the AI's turn (lesson #38).
            return policies.resolve_ship_pick(
                room, chooser_id, reason, alive, rng=self.rng
            )

        previous_seq = room.ship_pick_seq
        existing = interaction_rules.register_ship_pick(
            room, chooser_id, reason, message,
            allow_duplicate=allow_duplicate, silent=silent,
        )
        registered = existing or next((pick for pick in room.pending_ship_picks if pick.get('seq', 0) > previous_seq), None)
        if registered is not None and source_id is not None:
            registered['source_caster'] = source_id
        if existing is not None:
            await self._emit_ship_pick_request(room, existing)
            return None
        entry = interaction_rules.top_ship_pick(room, chooser_id)
        if entry is not None:
            await self._emit_ship_pick_request(room, entry)
        return None

    @guard_phase_write
    async def confirm_sacrifice(self, connection: Connection,
                                data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        entry = interaction_rules.top_ship_pick(room, player_id)
        if entry is None:
            return {"status": "error", "message": "当前没有待牺牲的战舰"}
        reason = str(entry.get("reason") or "demon_contract")
        position = data.get("position") or {}
        try:
            cell = (int(position.get("x")), int(position.get("y")))
        except (TypeError, ValueError):
            return {"status": "error", "message": "请选择一艘自己的战舰"}
        ship = interaction_rules.find_ship_at(room.players[player_id], cell, alive_only=True)
        if ship is None:
            return {
                "status": "error",
                "message": "必须选择自己【还活着】的战舰所在的格子（已沉没的船不能选）",
            }

        if reason == "kraken_eye":
            interaction_rules.consume_ship_pick(room, player_id, "kraken_eye")
            other_id = room.opponent_of(player_id)
            if other_id and other_id in room.players:
                room.players[other_id].revealed_positions.extend(ship.positions)
                if room.players[other_id].socket_id:
                    await self._publisher.emit(
                        "revealed_positions",
                        {"positions": [{"x": p.x, "y": p.y} for p in ship.positions]},
                        to=room.players[other_id].socket_id,
                    )
            await self._dispatch_ship_pick(room, player_id)
            await self._sync_each_seat(room)
            return {"status": "success", "message": "已暴露一艘战舰的位置"}

        if reason == "trap_setup":
            interaction_rules.consume_ship_pick(room, player_id, "trap_setup")
            ship.trap = True
            await self._add_log(
                room,
                f"第{room.round}回合 · {self._name(room, player_id)} 的【守株待兔】为一艘战舰设置陷阱",
                "magic",
                {"caster": player_id, "card": "守株待兔"},
            )
            await self._publisher.emit(
                "trap_set",
                {
                    "player": player_id,
                },
                room=room.id,
            )
            await self._dispatch_ship_pick(room, player_id)
            await self._sync_each_seat(room)
            return {"status": "success", "message": "已为一艘战舰设置陷阱（本回合该船被击沉时对方需牺牲两艘）"}

        if reason not in interaction_rules.SACRIFICE_REASONS:
            label = interaction_rules.SHIP_PICK_LABELS.get(reason, "该效果")
            return {
                "status": "error",
                "message": f"当前待处理的是「{label}」的选船，请用面板上的确认按钮提交，"
                           f"不要直接点船格（这条路径只用于牺牲类效果）",
            }
        await self._sacrifice_ship(room, player_id, ship, reason, source_id=entry.get('source_caster'))
        return {"status": "success", "message": "已选择一艘战舰"}

    async def _sacrifice_ship(self, room: Room, player_id: str,
                              ship: PlayerShip, reason: str = "demon_contract", *, source_id: str | None = None) -> None:
        player = room.players.get(player_id)
        if player is None or ship is None or ship not in player.ships:
            return
        interaction_rules.consume_ship_pick(room, player_id, reason)
        player.ships.remove(ship)
        battle_rules.mark_ship_sunken(player, ship)
        player.remaining_ships = max(0, int(player.remaining_ships) - 1)
        if not room.chain_resolving and source_id == room.current_attacker and source_id != player_id:
            room.players[source_id].ship_reductions_this_turn += 1
        positions = [{"x": p.x, "y": p.y} for p in ship.positions]
        await self._publish_sunken_cells(room, player_id, positions)
        replay_rules.note_ship_lost(room, player_id, positions)
        reason_text = {
            "divine_decree": "神之宣告",
            "dice_sacrifice": "命运骰子",
            "trap_sacrifice": "守株待兔",
            "iron_bones": "钢筋铁骨",
        }.get(reason, "恶魔契约")
        await self._add_log(
            room,
            f"第{room.round}回合 · {self._name(room, player_id)} 因{reason_text}牺牲一艘战舰",
            "magic",
            {"player": player_id, "reason": reason, "positions": positions},
        )
        await self._publisher.emit(
            "ship_sacrificed",
            {"player": player_id, "positions": positions, "reason": reason},
            room=room.id,
        )
        await self.on_ship_destroyed(room, player_id, ship)
        await self._emit_ships_updated(room)
        await self._emit_player_ships(room, player_id)

        if reason != "demon_contract":
            await self._mirror_contract_loss(room, player_id)
        await self._dispatch_ship_pick(room, player_id)
        await self._sync_each_seat(room)

        # 二次确认发生在连锁收尾之后，必须在这里结算最后一艘献祭的败局。
        # 效果执行中的献祭仍交给原效果处理，避免把重部署的中间态判负。
        if player.remaining_ships <= 0 and not room.game_effects.get("contract_suppress"):
            opponent_id = room.opponent_of(player_id)
            if opponent_id and room.state != RoomState.GAME_OVER:
                await self.finish(room, opponent_id, player_id, reason=f"{reason_text}献祭最后一艘战舰")

    async def _publish_sunken_cells(self, room: Room, player_id: str,
                                    positions: list[dict[str, int]]) -> None:
        """献祭掉的战舰格要像被击中一样公开标成红色叉叉。

        旧行为只把船从 `player.ships` 里删掉再同步自家棋盘，对手视角一格都没有，
        看起来像船凭空消失。这里把这些格子写进**对手**的 `attacks`（hit/ship_sunk）
        后广播棋盘：双方看到同一片击沉痕迹，且不会暴露其它隐藏船。
        """

        opponent_id = room.opponent_of(player_id)
        opponent = room.players.get(opponent_id) if opponent_id else None
        if opponent is None:
            return
        seen = {(p.x, p.y) for p in opponent.attacks}
        changed = False
        for cell in positions:
            key = (int(cell["x"]), int(cell["y"]))
            if key in seen:
                continue
            opponent.attacks.append(Position(x=key[0], y=key[1], hit=True, ship_sunk=True))
            seen.add(key)
            changed = True
        if changed:
            await self._emit_board_attacks(room)

    async def _trigger_ship_trap(self, room: Room, owner_id: str,
                                 sunk_ship: PlayerShip) -> None:
        opponent_id = room.opponent_of(owner_id)
        if not opponent_id or opponent_id not in room.players:
            return
        alive = alive_ships(room.players[opponent_id])
        need = min(2, len(alive))
        positions = [{"x": p.x, "y": p.y} for p in sunk_ship.positions]
        if need <= 0:
            await self._publisher.emit(
                "trap_triggered",
                {
                    "owner": owner_id,
                    "sunk_positions": positions,
                    "sacrificed": 0,
                    "message": "陷阱触发，但对方没有可牺牲的战舰",
                },
                room=room.id,
            )
            return
        await self._publisher.emit(
            "trap_triggered",
            {
                "owner": owner_id,
                "sunk_positions": positions,
                "sacrificed": need,
                "message": f"陷阱触发！对方需牺牲{need}艘战舰",
            },
            room=room.id,
        )
        await self._add_log(
            room,
            f"第{room.round}回合 · {self._name(room, owner_id)} 的【守株待兔】陷阱被踩中，"
            f"对方需牺牲{need}艘战舰",
            "magic",
            {"owner": owner_id, "card": "守株待兔", "sacrifice": need},
        )
        for _ in range(need):
            picked = await self.request_ship_pick(
                room, opponent_id, "trap_sacrifice",
                "守株待兔：请点选一艘战舰牺牲", True, False,
                source_id=owner_id,
            )
            if picked is not None:
                await self._sacrifice_ship(room, opponent_id, picked, "trap_sacrifice", source_id=owner_id)

    # --------------------------------------------------------------- placement

    def _pending_placement(self, room: Room) -> dict[str, Any] | None:
        temp = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
        pending = temp.get("pending_placement")
        return pending if isinstance(pending, dict) else None

    async def _emit_placement_request(self, room: Room, player_id: str) -> None:
        pending = self._pending_placement(room)
        player = room.players.get(player_id)
        if pending is None or pending.get("caster") != player_id or player is None or not player.socket_id:
            return
        kind = pending.get("kind")
        payload: dict[str, Any] = {
            "kind": kind,
            "remaining": pending.get("remaining"),
            "total": pending.get("total"),
            "placed": pending.get("placed"),
            "blocked": interaction_rules.placement_blocked_for(room, player_id, pending),
        }
        allowed = interaction_rules.placement_allowed_for(room, pending)
        if allowed:
            payload["allowed"] = allowed
        if kind == "shenji_redeploy":
            payload["message"] = (
                "预言成功：请选择这艘战舰重新部署的位置（原位置或对方未打过的格子）"
            )
        elif kind == "lanyu":
            payload["message"] = (
                "滥竽充数：请选择补充战舰的部署位置（未被攻击过的空格，大回合结束时收回）"
            )
        await self._publisher.emit("placement_request", payload, to=player.socket_id)

    async def _start_placement(self, room: Room, caster_id: str, kind: str,
                               count: int, *, mirrored: bool = False) -> None:
        # 摆船也是「待选择项」：必须走队列，否则和灵气/仁王这类 type 选择项互相覆盖，
        # 连续两张增援也会把上一张的进度盖掉。
        magic_temps.store(room, {
            "pending_placement": {
                "caster": caster_id,
                "kind": kind,
                "remaining": count,
                "total": count,
                "placed": 0,
                "mirrored": mirrored,
            },
        })
        await self._activate_magic_temp(room)

    @guard_phase_write
    async def confirm_reinforcement_position(
        self, connection: Connection, data: dict[str, Any] | None = None
    ) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        pending = self._pending_placement(room)
        if pending is None or pending.get("caster") != player_id:
            return dict(NO_PENDING_PLACEMENT)
        position = data.get("position") or {}
        if position.get("x") is None or position.get("y") is None:
            return {"status": "error", "message": "请选择放置位置"}
        try:
            x, y = int(position["x"]), int(position["y"])
        except (TypeError, ValueError):
            return {"status": "error", "message": "请选择放置位置"}

        kind = pending.get("kind")
        if kind == "last_stand":
            allowed = {
                xy for xy in (
                    interaction_rules.cell_xy(a)
                    for a in (room.game_effects.get("last_stand_cells") or [])
                ) if xy
            }
            if (x, y) not in allowed:
                return {"status": "error", "message": "只能放在原本有自己战舰的格子上"}
        elif kind == "shenji_redeploy":
            allow = {
                xy for xy in (
                    interaction_rules.cell_xy(a)
                    for a in (room.game_effects.get("shenji_redeploy_cells") or [])
                ) if xy
            }
            error = interaction_rules.placement_error(
                room, player_id, x, y, allow_cells=allow, ignore_sunken=True)
            if error:
                return {"status": "error", "message": error}
        else:
            error = interaction_rules.placement_error(room, player_id, x, y)
            if error:
                return {"status": "error", "message": error}

        caster = room.players[player_id]
        if kind == "shenji_redeploy":
            targets = list(room.game_effects.get("shenji_redeploy_ships") or [])
            revived = None
            while targets:
                candidate = targets.pop(0)
                if candidate in caster.sunken_ships:
                    revived = candidate
                    break
            room.game_effects["shenji_redeploy_ships"] = targets
            if revived is None:
                await self._finish_placement(room, player_id, kind)
                return {"status": "error", "message": "没有可重新部署的战舰"}
            while revived in caster.sunken_ships:
                caster.sunken_ships.remove(revived)
            replay_rules.note_ship_returned(room, player_id, revived)
            revived.positions = [Position(x=x, y=y)]
            revived.hits = []
            revived.shield = False
            revived.invincible = False
            revived.frozen = None
            if revived not in caster.ships:
                caster.ships.append(revived)
            caster.remaining_ships += 1
            self._clear_attacks_on_cells(room, player_id, revived.positions)
            message = f"神机妙算：战舰已重新部署到 ({x},{y})"
        elif kind == "revive":
            if not caster.sunken_ships:
                await self._finish_placement(room, player_id, kind)
                return {"status": "error", "message": "没有可复活的战舰"}
            revived = caster.sunken_ships.pop()
            while revived in caster.sunken_ships:
                caster.sunken_ships.remove(revived)
            replay_rules.note_ship_returned(room, player_id, revived)
            revived.positions = [Position(x=x, y=y)]
            revived.hits = []
            revived.shield = False
            revived.invincible = False
            revived.frozen = None
            if revived not in caster.ships:
                caster.ships.append(revived)
            caster.remaining_ships += 1
            self._clear_attacks_on_cells(room, player_id, revived.positions)
            message = f"复活战舰已部署到 ({x},{y})"
        elif kind == "last_stand":
            new_ship = PlayerShip(positions=[Position(x=x, y=y)], hits=[])
            caster.ships.append(new_ship)
            caster.remaining_ships += 1
            self._clear_attacks_on_cells(room, player_id, new_ship.positions)
            message = f"绝处逢生：唯一一艘战舰已部署到 ({x},{y})"
        elif kind == "lanyu":
            new_ship = PlayerShip(positions=[Position(x=x, y=y)], hits=[])
            caster.ships.append(new_ship)
            caster.remaining_ships += 1
            self._clear_attacks_on_cells(room, player_id, new_ship.positions)
            lanyu = room.game_effects.setdefault("lanyu_temp_ships", {})
            lanyu.setdefault(player_id, []).append(new_ship)
            message = f"补充战舰已部署到 ({x},{y})（大回合结束时收回）"
        else:
            new_ship = PlayerShip(positions=[Position(x=x, y=y)], hits=[])
            caster.ships.append(new_ship)
            caster.remaining_ships += 1
            self._clear_attacks_on_cells(room, player_id, new_ship.positions)
            message = f"增援战舰已部署到 ({x},{y})"

        pending["remaining"] = int(pending.get("remaining") or 0) - 1
        pending["placed"] = int(pending.get("placed") or 0) + 1
        if not pending.get(contract_rules.MIRRORED_PLACEMENT) and kind != "last_stand":
            # 真实多了一艘（增援/复活/神机重布）：恶魔契约要求对手也补一艘。
            await self._mirror_contract_gain(room, player_id, 1)
        await self.notify_treasure(room, 1)
        await self._emit_ships_updated(room)
        await self._emit_player_ships(room, player_id)
        if caster.socket_id:
            await self._publisher.emit("message", {"text": message}, to=caster.socket_id)
        if int(pending.get("remaining") or 0) > 0:
            await self._emit_placement_request(room, player_id)
        else:
            await self._finish_placement(room, player_id, kind)
        replay_rules.refresh_ships(room)
        await self._emit_board_attacks(room)
        return {"status": "success", "message": message}

    async def cancel_placement(self, room: Room, player_id: str) -> dict:
        pending = self._pending_placement(room)
        if pending is None or pending.get("caster") != player_id:
            return dict(NO_PENDING_PLACEMENT)
        if pending.get("kind") == "last_stand":
            cells = room.game_effects.get("last_stand_cells") or []
            if cells:
                cell = self.rng.choice(cells)
                position = {"x": cell[0], "y": cell[1]}
                # In-room fast path: identity was already checked by the seat.
                await self.confirm_reinforcement_position(
                    Connection(sid=room.players[player_id].socket_id or player_id),
                    {"room_id": room.id, "player_id": player_id, "position": position},
                )
                return {"status": "success", "message": "已随机放置唯一一艘战舰"}
        await self._finish_placement(room, player_id, str(pending.get("kind")))
        player = room.players.get(player_id)
        if player and player.socket_id:
            await self._publisher.emit("message", {"text": "已放弃剩余放置"}, to=player.socket_id)
        # Legacy ack shape for the generic cancel path: no extra message key.
        return {"status": "success"}

    async def _emit_effect_notice(self, room: Room, player_id: str, card: str, result: str) -> None:
        """只广播已落地的效果摘要，不把选择引导或私有手牌内容当作结果。"""
        await self._publisher.emit(
            "game_message",
            {"type": "magic_effect", "message": f"{self._name(room, player_id)}的「{card}」：{result}"},
            room=room.id,
        )

    async def _finish_placement(self, room: Room, player_id: str, kind: str) -> None:
        pending = self._pending_placement(room) or {}
        placed = int(pending.get("placed") or 0)
        baseline = pending.get("contract_baseline")
        magic_temps.finish(room, "pending_placement", owner=player_id)
        if kind == "last_stand":
            room.game_effects.pop("last_stand_cells", None)
            room.game_effects.pop("last_stand_owner", None)
        if kind == "shenji_redeploy":
            room.game_effects.pop("shenji_redeploy_cells", None)
            room.game_effects.pop("shenji_redeploy_ships", None)
        player = room.players.get(player_id)
        if player and player.socket_id:
            await self._publisher.emit(
                "placement_done", {"kind": kind}, to=player.socket_id
            )
        if kind == "last_stand":
            self._apply_last_stand_attacks(room, player_id)
        else:
            self._sync_attacks_after_ship_change(room, player_id, placed)
        await self._publisher.emit(
            "attacks_updated",
            {
                "current_attacker": room.current_attacker,
                "attacks_remaining": room.attacks_remaining,
            },
            room=room.id,
        )
        if baseline is not None:
            await self._mirror_contract_delta(room, player_id, room.players[player_id].remaining_ships - int(baseline))
        # 放弃尚未放置的部分不能伪报成功；已放置的部分只汇总播报一次。
        card = {
            "reinforce": "增援", "revive": "死者苏生", "last_stand": "绝处逢生",
            "lanyu": "滥竽充数", "shenji_redeploy": "神机妙算", "contract_gain": "恶魔契约",
        }.get(kind)
        if placed > 0 and card:
            result = f"已复活并部署{placed}艘战舰" if kind == "revive" else f"已部署{placed}艘战舰"
            await self._emit_effect_notice(room, player_id, card, result)
        await self._activate_magic_temp(room)
        await self._sync_each_seat(room)

    @staticmethod
    def _sync_attacks_after_ship_change(room: Room, player_id: str,
                                        ships_added: int = 1) -> None:
        if room.state != RoomState.ATTACKING:
            return
        if room.current_attacker != player_id or ships_added <= 0:
            return
        if battle_rules.attacks_forced_zero(room):
            return
        field = field_magic_name(room)
        if field == "教皇旨意":
            per_ship = 0
        elif field == "伊甸园":
            per_ship = -1
        else:
            per_ship = 1
        if per_ship:
            room.attacks_remaining = max(
                0, int(room.attacks_remaining) + per_ship * ships_added
            )

    @staticmethod
    def _apply_last_stand_attacks(room: Room, player_id: str) -> None:
        if room.state != RoomState.ATTACKING or room.current_attacker != player_id:
            return
        if battle_rules.attacks_forced_zero(room):
            room.attacks_remaining = 0
            return
        field = field_magic_name(room)
        if field == "教皇旨意":
            base = 0
        elif field == "伊甸园":
            base = max(0, 6 - int(room.players[player_id].remaining_ships or 0))
        else:
            base = 1
        bonus = int(getattr(room.players[player_id].effect_flags, "subsidy_bonus", 0) or 0)
        room.attacks_remaining = max(0, base + bonus)

    @staticmethod
    def _clear_attacks_on_cells(room: Room, board_owner_id: str,
                                positions: list[Position]) -> None:
        cells = {(p.x, p.y) for p in positions}
        opponent_id = room.opponent_of(board_owner_id)
        if not cells or not opponent_id or opponent_id not in room.players:
            return
        room.players[opponent_id].attacks = [
            attack for attack in room.players[opponent_id].attacks
            if (attack.x, attack.y) not in cells
        ]

    # --------------------------------------------------------------- play card

    @guard_phase_write
    async def use_magic_card(self, connection: Connection,
                             data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        existing = self.rooms.get_room(data.get("room_id"))
        if existing is not None and existing.state == RoomState.GAME_OVER:
            return dict(FINISHED_GAME)
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if room.state == RoomState.GAME_OVER:
            return dict(FINISHED_GAME)
        try:
            card = card_from_payload(data.get("card"))
        except Exception as error:  # noqa: BLE001 - client data, never crash the handler
            return {"status": "error", "message": f"魔法卡数据无效: {error}"}

        targets, target_error = sanitize_targets(data.get("targets", {}), card.name)
        if target_error:
            return {"status": "error", "message": target_error}
        # 状态级预检（例如神之宣告必须选满两艘活舰）：扣牌之前拒绝，零副作用。
        selection_error = magic_precheck.precheck(room, player_id, card.name, targets)
        if selection_error:
            return {"status": "error", "message": selection_error}

        frozen = self._frozen_reason(room, player_id)
        if frozen:
            return {"status": "error", "message": frozen}
        player = room.players[player_id]
        opponent_id = room.opponent_of(player_id)
        if opponent_id is None:
            return {"status": "error", "message": "房间人数不足"}

        if room.chain_waiting or room.chain_resolving:
            return {"status": "error", "message": CHAIN_BUSY}
        wait = action_wait_reason(room, player_id)
        if wait:
            return {"status": "error", "message": wait}
        if player.magic_blocked and getattr(player, "magic_blocked_round", room.round) == room.round:
            return {"status": "error", "message": "你的魔法卡已被看破，本回合无法使用"}
        if not any(
            candidate.name == card.name and candidate.speed == card.speed
            for candidate in player.magic_hand
        ):
            return {"status": "error", "message": "你没有这张魔法卡"}
        # §7：唯一的 pre-cast 评估；连锁路径调用同一个函数（顺序与文案一份）。
        refusal = evaluate_cast(room, player_id, card)
        if refusal:
            return {"status": "error", "message": refusal}

        # #37：宣告通过全部闸门、扣牌之前发 CAST_BEFORE（filter 带可改写目标）。
        await hooks.emit(
            room,
            hooks.CAST_BEFORE,
            {
                "room_id": room.id,
                "player_id": player_id,
                "card": card.name,
                "speed": card.speed,
                "targets": targets,
            },
        )
        # Remove the declared copy, then push it on the chain. Non-field cards
        # go to the shared discard pile immediately (legacy).
        for index, candidate in enumerate(player.magic_hand):
            if candidate.name == card.name and candidate.speed == card.speed:
                player.magic_hand.pop(index)
                break
        if card.type != "场地":
            room.magic_discard.append(card)
            await self._emit_card_discarded(room, player_id, card, "play")
        await self._emit_hand(player)
        # Replay: the card leaves the hand at this instant, not at resolution.
        # The step also carries the stack *including* this card (note_chain),
        # so the replay top bar can show the chain of every play.
        item = ChainItem(player_id, card, targets, self.clock())
        replay_rules.note_chain(room, list(room.chain) + [item])
        replay_rules.note_card_played(room, player_id, card)

        room.chain.append(item)
        record_card_play(room, player_id, now=self.clock())
        # #37：支付完成、已入连锁之后发 CAST_PAID（此后失败只能按连锁规则退牌）。
        await hooks.emit(
            room,
            hooks.CAST_PAID,
            {
                "room_id": room.id,
                "player_id": player_id,
                "card": card.name,
                "speed": card.speed,
                "chain_size": len(room.chain),
            },
        )
        await self._publisher.emit(
            "magic_chain_updated", _spectate_chain_payload(room), room=room.id
        )
        # The response window starts on the opponent; a card that nobody can
        # answer falls through both passes and resolves (after the display
        # delay, unless it is 0).
        await self._open_chain_window(room, player_id)
        return {"status": "success", "message": f"魔法卡{card.name}已加入连锁"}

    # ------------------------------------------------------------ chain engine

    async def _open_chain_window(self, room: Room, caster_id: str) -> None:
        room.chain_passes = 0
        if self.chain_entry_delay_seconds > 0 and room.chain:
            # 先让双方看到飞入，再发出chain_request并开始完整响应倒计时。
            # 等待期间不开放窗口，旧计时器或抢跑响应不能改变这条连锁。
            room.chain_timer += 1
            token = room.chain_timer
            room.chain_waiting = True
            room.chain_window = None
            task = self.timers.spawn(room.id, self._chain_entry_then_open(room.id, token, caster_id))
            if task is not None:
                return
            room.chain_waiting = False
        await self._advance_chain_window(room, room.opponent_of(caster_id))

    async def _chain_entry_then_open(self, room_id: str, token: int, caster_id: str) -> None:
        await asyncio.sleep(self.chain_entry_delay_seconds)
        room = self.rooms.get_room(room_id)
        if (room is None or room.state != RoomState.ATTACKING
                or room.chain_timer != token or not room.chain
                or not room.chain_waiting or room.chain_window is not None):
            return
        room.chain_waiting = False
        await self._advance_chain_window(room, room.opponent_of(caster_id))

    async def _advance_chain_window(self, room: Room, player_id: str | None,
                                    *, display_delay: bool = True) -> None:
        """Hand the window to the player who may respond, or resolve.

        A player who cannot respond is recorded as a pass and the window moves
        to the opponent; two consecutive passes end the chain. `display_delay`
        is False only on the 10-second timeout path (legacy: that path must not
        add a second pause after the window already stayed open for 10s).
        """

        while True:
            if not player_id or player_id not in room.players:
                await self.resolve_chain(room)
                return
            if chain_rules.can_respond(room, player_id):
                room.chain_window = player_id
                room.chain_waiting = True
                room.chain_timer += 1
                token = room.chain_timer
                top = room.chain[-1]
                player = room.players[player_id]
                target_preview = None
                # 目标已经在入链时由服务端校验过。响应者只需要知道对手
                # 选中了自己棋盘的范围，才能决定是否用失灵；神威！是唯一
                # 的双向选板卡，选择对手自己的棋盘也按规则公开。增援、
                # 点船和其它自用效果不会进入这个预览字段。
                if top.player_id != player_id:
                    public_chain = _spectate_chain_payload(room)
                    public_items = public_chain.get("chain", [])
                    if isinstance(public_items, list) and public_items:
                        candidate = public_items[-1]
                        preview = candidate.get("preview") if isinstance(candidate, dict) else None
                        if isinstance(preview, dict) and (
                            top.card.name == "神威！" or preview.get("board") == "opponent"
                        ):
                            target_preview = preview
                await self._publisher.emit(
                    "chain_request",
                    {
                        "card": card_payload(top.card),
                        # Self-chain: the window can come back to the last
                        # caster, so the client must not assume "opponent".
                        "caster": top.player_id,
                        # 窗口归属写进载荷：自连锁时 caster 就是自己，前端只看
                        # caster 会把它当成「对方在连锁」而不显示响应面板。
                        "responder": player_id,
                        "self_chain": top.player_id == player_id,
                        "speed3_cards": [
                            card_payload(card)
                            for card in chain_rules.usable_speed3_cards(room, player_id)
                        ],
                        "target_preview": target_preview,
                        "countdown": CHAIN_RESPONSE_SECONDS,
                    },
                    to=player.socket_id,
                )
                self._schedule_chain_timeout(room.id, token)
                if player_id.startswith("ai-"):
                    self._schedule_ai_response(room.id, token)
                return
            room.chain_passes += 1
            if room.chain_passes >= 2:
                await self._finish_chain(room, display_delay=display_delay)
                return
            player_id = room.opponent_of(player_id)

    async def _finish_chain(self, room: Room, *, display_delay: bool = True) -> bool:
        """End the chain; returns True when a delayed resolve task was queued."""

        if not display_delay or self.chain_display_delay_seconds <= 0:
            await self.resolve_chain(room)
            return False
        room.chain_timer += 1
        token = room.chain_timer
        room.chain_display_token = token
        room.chain_display_deadline = (
            time.monotonic() + self.chain_display_delay_seconds + 5.0
        )
        task = self.timers.spawn(room.id, self._chain_display_then_resolve(room.id, token))
        if task is None:
            # No running loop: never leave the chain hanging; resolve inline.
            chain_rules.clear_display(room)
            await self.resolve_chain(room)
            return False
        return True

    async def _chain_display_then_resolve(self, room_id: str, token: int) -> None:
        await asyncio.sleep(self.chain_display_delay_seconds)
        room = self.rooms.get_room(room_id)
        if room is None or room.chain_display_token != token:
            return
        chain_rules.clear_display(room)
        if not chain_rules.display_still_current(room, token):
            return
        await self.resolve_chain(room)

    def _schedule_chain_timeout(self, room_id: str, token: int) -> None:
        self.timers.spawn(room_id, self._chain_timeout(room_id, token))

    async def _chain_timeout(self, room_id: str, token: int) -> None:
        await asyncio.sleep(self.chain_response_seconds)
        room = self.rooms.get_room(room_id)
        if room is None or not room.chain_waiting or room.chain_timer != token:
            return
        window_player = room.chain_window
        room.chain_waiting = False
        room.chain_window = None
        room.chain_passes += 1
        if room.chain_passes >= 2 or window_player is None:
            # The 10s window already displayed the chain; no extra pause.
            await self.resolve_chain(room)
            return
        await self._advance_chain_window(
            room, room.opponent_of(window_player), display_delay=False
        )

    def _schedule_ai_response(self, room_id: str, token: int) -> None:
        self.timers.spawn(room_id, self._ai_chain_respond(room_id, token))

    async def _ai_chain_respond(self, room_id: str, token: int) -> None:
        """Hard AI: spend 失灵！ when it can, otherwise pass immediately."""

        await asyncio.sleep(self.ai_chain_delay_seconds)
        room = self.rooms.get_room(room_id)
        if room is None or getattr(room.state, "value", room.state) == "game_over":
            return
        if not room.chain_waiting or room.chain_timer != token:
            return
        ai_id = room.chain_window
        if not ai_id or not ai_id.startswith("ai-"):
            return
        player = room.players.get(ai_id)
        if player is None:
            return
        card = next((card for card in player.magic_hand if card.name == "失灵！"), None)
        if card is None or not chain_rules.ai_can_negate_chain_top(room, ai_id):
            await self.chain_response(
                None, {"room_id": room_id, "player_id": ai_id, "chain": False}
            )
            return
        ack = await self.chain_response(
            None,
            {
                "room_id": room_id,
                "player_id": ai_id,
                "chain": True,
                "card": {"name": card.name},
                "targets": [],
            },
        )
        if not (ack and ack.get("status") == "success"):
            await self.chain_response(
                None, {"room_id": room_id, "player_id": ai_id, "chain": False}
            )

    @guard_phase_write
    async def chain_response(self, connection: Connection | None,
                             data: dict[str, Any] | None = None) -> dict:
        """Answer the open window: play a speed-3 card or pass.

        `connection=None` is the internal AI path: the player id is trusted
        because no client can reach this method without the socket adapter,
        which always passes a verified connection.
        """

        data = data if isinstance(data, dict) else {}
        room = self.rooms.get_room(data.get("room_id"))
        player_id = data.get("player_id")
        if (
            room is None
            or not player_id
            or player_id not in room.players
            or (connection is not None
                and not self.rooms.identity_ok(room, str(player_id), connection))
        ):
            return dict(INVALID_SEAT)

        chain = bool(data.get("chain", False))
        card_payload_data = data.get("card")
        raw_targets = data.get("targets", [])
        if isinstance(raw_targets, dict):
            targets, target_error = sanitize_targets(
                raw_targets,
                card_payload_data.get("name")
                if isinstance(card_payload_data, dict)
                else None,
            )
            if target_error:
                return {"status": "error", "message": target_error}
        else:
            targets = raw_targets

        if not room.chain_waiting:
            return {"status": "error", "message": "没有待处理的连锁请求"}
        if room.chain_window != player_id:
            return {"status": "error", "message": "当前不是你的连锁响应窗口"}

        # Closing the window is what makes late/stale answers impossible — but it
        # happens only when this answer actually commits (a chained card, a pass,
        # or a deliberate refusal-pass). Pure validation failures below leave the
        # window open for the same player: closing it there left `chain_waiting`
        # false with no window and no timer, i.e. a chain that never resolved
        # (the 10s timeout also returns early once `chain_waiting` is false).
        if chain and card_payload_data:
            try:
                card = card_from_payload(card_payload_data)
            except Exception as error:  # noqa: BLE001 - client data
                return {"status": "error", "message": f"魔法卡数据无效: {error}"}
            player = room.players[str(player_id)]
            # 看破！ suppress: pass and advance, never leave the window half-open.
            if player.magic_blocked and getattr(player, "magic_blocked_round", room.round) == room.round:
                room.chain_waiting = False
                room.chain_window = None
                await self._pass_after_refusal(room, str(player_id))
                return {"status": "error", "message": "你的魔法卡已被看破，无法连锁"}

            hand_card = next(
                (
                    candidate
                    for candidate in player.magic_hand
                    if candidate.name == card.name and candidate.speed == card.speed
                ),
                None,
            )
            if hand_card is None:
                return {"status": "error", "message": "你没有这张魔法卡"}
            card = hand_card
            if int(card.speed) != 3:
                return {"status": "error", "message": "只能使用速阶3的卡牌进行连锁"}

            selection_error = magic_precheck.precheck(room, str(player_id), card.name, targets if isinstance(targets, dict) else {})
            if selection_error:
                return {"status": "error", "message": selection_error}

            # §7：与 use_magic_card 同一个 pre-cast 评估（禁忌果实 / 绝处逢生 /
            # 卡专属条件 / 待选船 / 未接入）。拒绝后让过并推窗，绝不留半开窗口。
            refusal = evaluate_cast(room, str(player_id), card)
            if refusal:
                room.chain_waiting = False
                room.chain_window = None
                await self._pass_after_refusal(room, str(player_id))
                return {"status": "error", "message": refusal}

            room.chain_waiting = False
            room.chain_window = None

            # 第二条支付路径：与 use_magic_card 发同一对事件（复审 finding 7）。
            await hooks.emit(
                room,
                hooks.CAST_BEFORE,
                {
                    "room_id": room.id,
                    "player_id": str(player_id),
                    "card": card.name,
                    "speed": card.speed,
                    "targets": targets,
                },
            )
            for index, candidate in enumerate(player.magic_hand):
                if candidate.name == card.name and candidate.speed == card.speed:
                    player.magic_hand.pop(index)
                    break
            room.magic_discard.append(card)
            await self._emit_card_discarded(room, str(player_id), card, "chain")
            await self._emit_hand(player)
            # Replay: chained play is a play, recorded at the same moment; the
            # step carries the stack after this play (same single seam).
            item = ChainItem(str(player_id), card, targets, self.clock())
            replay_rules.note_chain(room, list(room.chain) + [item])
            replay_rules.note_card_played(room, str(player_id), card, chained=True)

            room.chain.append(item)
            record_card_play(room, str(player_id), now=self.clock())
            await hooks.emit(
                room,
                hooks.CAST_PAID,
                {
                    "room_id": room.id,
                    "player_id": str(player_id),
                    "card": card.name,
                    "speed": card.speed,
                    "chain_size": len(room.chain),
                },
            )
            await self._publisher.emit(
                "magic_chain_updated", _spectate_chain_payload(room), room=room.id
            )
            # A new card clears the pass count; the window goes to the opponent
            # and can come back for self-chaining.
            room.chain_passes = 0
            await self._open_chain_window(room, str(player_id))
            return {"status": "success", "message": f"魔法卡{card.name}已加入连锁"}

        # 明确放弃：先关窗再计一次 pass（与 chained/refused 两条提交路径一致）。
        room.chain_waiting = False
        room.chain_window = None
        room.chain_passes += 1
        if room.chain_passes >= 2:
            await self._finish_chain(room)
        else:
            await self._advance_chain_window(room, room.opponent_of(str(player_id)))
        return {"status": "success", "message": "放弃连锁"}

    async def _pass_after_refusal(self, room: Room, player_id: str) -> None:
        room.chain_passes += 1
        if room.chain_passes >= 2:
            await self._finish_chain(room)
        else:
            await self._advance_chain_window(room, room.opponent_of(player_id))

    async def resolve_chain(self, room: Room) -> list[ChainResult]:
        """Resolve once; a re-entrant call during async effects is a no-op."""

        if room.chain_resolving:
            return []
        room.chain_resolving = True
        try:
            return await self._resolve_chain(room)
        finally:
            room.chain_resolving = False

    async def _resolve_chain(self, room: Room) -> list[ChainResult]:
        """Resolve LIFO. Negated items are skipped (DECISIONS D2)."""

        results: list[ChainResult] = []
        while room.chain:
            item = room.chain.pop()
            if getattr(item, "negated", False):
                by = getattr(item, "negated_by", None)
                detail = (
                    f"{item.card.name}被{by}无效化"
                    if by
                    else f"{item.card.name}被无效化"
                )
                result = ChainResult(
                    card=item.card,
                    caster=item.player_id,
                    success=False,
                    message=detail,
                    negated_skip=True,
                    negated_by=by,
                )
                # A negated field card only goes to the discard pile; it must
                # never replace or tear down the field already in play.
                if item.card.type == "场地" and room.field_magic is not item.card:
                    room.magic_discard.append(item.card)
                    await self._emit_card_discarded(
                        room, item.player_id, item.card, "negated"
                    )
                suffix = f"但被{by}无效化" if by else "但被无效化"
                await self._add_log(
                    room,
                    f"第{room.round}回合 · {self._name(room, item.player_id)} 使用了"
                    f"【{item.card.name}】{suffix}",
                    "magic",
                    {"caster": item.player_id, "card": item.card.name},
                )
                results.append(result)
                continue

            effect = registry.effect_for(item.card)
            if effect is None:
                effect_result = EffectResult(
                    False, UNIMPLEMENTED.format(name=item.card.name)
                )
            else:
                try:
                    before_counts = {pid: p.remaining_ships for pid, p in room.players.items()}
                    # 一张魔法的中间态不触发契约。效果成功后按实际净变化统一结算，
                    # 兼容原地复活、批量击杀、献祭，避免多处回调重复结算。
                    with contract_rules.suppressed(room):
                        effect_result = await effect(self._context(room, item))
                    if effect_result.success and item.card.name == '败者食尘':
                        for task_room, token in list(self._shenji_tasks):
                            if task_room == room.id:
                                self._cancel_shenji_task(task_room, token)
                        self._interaction_waits.pop(room.id, None)
                    after_counts = {pid: p.remaining_ships for pid, p in room.players.items()}
                    opponent_id = room.opponent_of(item.player_id)
                    if effect_result.success and item.card.name not in ('灵气复苏', '败者食尘', '回光返照') and opponent_id and after_counts[opponent_id] < before_counts[opponent_id]:
                        room.players[item.player_id].ship_reductions_this_turn += before_counts[opponent_id] - after_counts[opponent_id]
                    if effect_result.success and not effect_result.game_over and room.state != RoomState.GAME_OVER and item.card.name not in contract_rules.NO_MIRROR_CARDS:
                        if item.card.name == "绝处逢生":
                            deferred = False
                            for temp in [room.magic_temp_data, *room.magic_temps.values()]:
                                pending = temp.get("pending_placement") or {}
                                if pending.get("kind") == "last_stand" and pending.get("caster") == item.player_id:
                                    pending["contract_baseline"] = before_counts[item.player_id]
                                    deferred = True
                            # AI可在效果调用内同步放好唯一战舰，此时没有待部署项可延后。
                            if not deferred:
                                await self._mirror_contract_delta(room, item.player_id, after_counts[item.player_id] - before_counts[item.player_id])
                        else:
                            for pid, count in after_counts.items():
                                await self._mirror_contract_delta(room, pid, count - before_counts[pid])
                except Exception as error:  # one bad card must not kill the room
                    logger.error(
                        "magic effect failed",
                        extra={
                            "room_id": room.id,
                            "card": item.card.name,
                            "error_type": type(error).__name__,
                        },
                        exc_info=error,
                    )
                    effect_result = EffectResult(
                        False, "魔法卡效果结算失败，卡牌已退回手牌"
                    )

            extra = dict(effect_result.extra or {})
            if effect_result.temp_data_id:
                extra.setdefault("temp_data_id", effect_result.temp_data_id)
            if effect_result.negate_target and room.chain:
                room.chain[-1].negated = True
                room.chain[-1].negated_by = item.card.name
            chain_result = ChainResult(
                card=item.card,
                caster=item.player_id,
                success=effect_result.success,
                message=effect_result.message,
                negate_target=effect_result.negate_target,
                affected_positions=effect_result.affected_positions,
                game_over=effect_result.game_over,
                extra=extra,
            )
            await self._add_log(
                room,
                f"第{room.round}回合 · {self._name(room, item.player_id)} 使用了"
                f"【{item.card.name}】"
                + (
                    f"，{effect_result.message}"
                    if effect_result.success and effect_result.message
                    else ""
                ),
                "magic",
                {"caster": item.player_id, "card": item.card.name},
            )
            if not effect_result.success and not effect_result.game_over:
                await self._refund(
                    room, item.player_id, item.card, effect_result.message
                )
            elif effect_result.success:
                entry = {
                    "card": item.card,
                    "caster": item.player_id,
                    "timestamp": self.clock(),
                    "round": room.round,
                }
                ledger = room.game_effects.get("stolen_cards") or {}
                if id(item.card) in ledger:
                    entry["stolen"] = True
                room.magic_history.append(entry)

            # Negation marks the item directly below *after* this one resolved,
            # which is exactly the next item to pop.
            if chain_result.negate_target and room.chain:
                room.chain[-1].negated = True
                room.chain[-1].negated_by = item.card.name
            results.append(chain_result)
            if effect_result.success and not effect_result.game_over and room.state != RoomState.GAME_OVER:
                opponent_id = room.opponent_of(item.player_id)
                opponent = room.players.get(opponent_id) if opponent_id else None
                if (
                    opponent is not None
                    and opponent.remaining_ships <= 0
                    and room.state == RoomState.ATTACKING
                    and not opponent.needs_reset
                ):
                    await self.finish(
                        room, item.player_id, opponent_id,
                        reason=f"{item.card.name}清空对方棋盘",
                    )
                    chain_result.game_over = True

        await self._publisher.emit(
            "chain_resolved",
            {"results": [result.to_dict() for result in results]},
            room=room.id,
        )
        room.chain = []
        room.chain_waiting = False
        room.chain_window = None
        room.chain_passes = 0
        chain_rules.clear_display(room)
        # The stolen-card ledger is merged; clear it so ids cannot be reused.
        room.game_effects.pop("stolen_cards", None)

        # #37：连锁闸门清空之后（且既有 wire chain_resolved 已发）才广播，
        # 订阅者看到的是最终状态，不会撞上半重置的房间。
        await hooks.emit(
            room,
            hooks.CHAIN_RESOLVED,
            {
                "room_id": room.id,
                "count": len(results),
                "results": [result.to_dict() for result in results],
            },
        )

        await self._emit_active_effects(room)
        for player in room.players.values():
            await self._emit_hand(player)
        await self._emit_ships_updated(room)
        for pid in room.players:
            await self._emit_player_ships(room, pid)
        await self._sync_each_seat(room)
        # Legacy order: phase_updated comes after every sync frame, even on the
        # game-over path (game_over itself was emitted by the effect).
        await self._publisher.emit(
            "phase_updated",
            {
                "current_phase": self._phase(room),
                "current_attacker": room.current_attacker,
            },
            room=room.id,
        )

        # A priority prompt interrupted by a speed-3 response resumes now.
        cont = room.priority_continue
        if cont and self.priority_continue_hook is not None:
            room.priority_continue = None
            await self._maybe_await(self.priority_continue_hook(room, cont))
        return results

    # ------------------------------------------------------- timer lifecycle

    def cancel_room_timers(self, room_id: str) -> int:
        """Destroy hook: cancel every background wait owned by one room."""

        self._interaction_waits.pop(room_id, None)

        room = self.rooms.get_room(room_id)
        if room is not None:
            chain_rules.clear_display(room)
        return self.timers.cancel_room(room_id)

    def pending_chain_tasks(self, room_id: str | None = None) -> int:
        return self.timers.pending(room_id)

    async def stop(self) -> None:
        """Server shutdown: cancel every chain/display/AI wait."""

        self._interaction_waits.clear()
        await self.timers.cancel_all()

    def _context(self, room: Room, item: ChainItem) -> EffectContext:
        opponent_id = room.opponent_of(item.player_id)
        assert opponent_id is not None

        async def emit(event: str, data: dict[str, Any], *, to: str | None = None,
                       room_id: str | None = None) -> None:
            await self._publisher.emit(event, data, to=to, room=room_id)

        async def draw(player_id: str) -> MagicCard | None:
            return await self.draw(room, player_id)

        async def log(text: str, event_type: str = "magic",
                      detail: dict | None = None) -> None:
            await self._add_log(room, text, event_type, detail)

        async def finish(winner: str, loser: str, reason: str) -> None:
            await self.finish(room, winner, loser, reason)

        async def sync_ships() -> None:
            await self._emit_ships_updated(room)

        async def sync_player_ships(player_id: str) -> None:
            await self._emit_player_ships(room, player_id)

        async def sync_hand(player_id: str) -> None:
            player = room.players.get(player_id)
            if player is not None:
                await self._emit_hand(player)

        async def sync_active_effects() -> None:
            await self._emit_active_effects(room)

        async def on_ship_sunk(player_id: str, ship: Any) -> None:
            await self.on_ship_sunk(
                room, player_id, ship, magic=True, attacker_id=item.player_id
            )

        async def notify_treasure(times: int, exclude: str | None) -> None:
            await self.notify_treasure(room, times, exclude_player_id=exclude)

        async def grant_attacks(n: int) -> int:
            gained = battle_rules.grant_extra_attacks(room, item.player_id, n)
            if gained:
                await self._publisher.emit(
                    "attacks_updated",
                    {
                        "current_attacker": room.current_attacker,
                        "attacks_remaining": room.attacks_remaining,
                    },
                    room=room.id,
                )
            return gained

        async def maybe_wuxian() -> bool:
            return await self.maybe_wuxian(room, item.player_id)

        async def emit_passthrough(event: str, data: dict[str, Any], *,
                                   to: str | None = None,
                                   room: str | None = None) -> None:
            await self._publisher.emit(event, data, to=to, room=room)

        async def request_ship_pick(chooser_id: str, reason: str, message: str,
                                    allow_duplicate: bool = False,
                                    silent: bool = False):
            return await self.request_ship_pick(
                room, chooser_id, reason, message, allow_duplicate, silent, source_id=item.player_id
            )

        async def sacrifice_ship(player_id: str, ship: Any, reason: str) -> None:
            await self._sacrifice_ship(room, player_id, ship, reason, source_id=item.player_id)

        async def on_ship_destroyed(player_id: str, ship: Any) -> None:
            await self.on_ship_destroyed(
                room, player_id, ship, attacker_id=item.player_id
            )

        async def start_placement(player_id: str, kind: str, count: int) -> None:
            await self._start_placement(room, player_id, kind, count)

        async def start_dice_discard(caster_id: str, opponent: str,
                                     only_player: str | None, card_name: str) -> None:
            await self.start_dice_discard(room, caster_id, opponent, only_player, card_name)

        async def open_shenji(player_id: str) -> None:
            await self.open_shenji(room, player_id)

        async def apply_shenji(player_id: str, value: int) -> None:
            await self.apply_shenji(room, player_id, value)

        async def place_field(card: MagicCard) -> None:
            await self.place_field(room, card)

        async def tear_down_field():
            return await self.tear_down_field(room, item.player_id)

        async def recalc_attacks() -> None:
            await self._recalc_attacks(room)

        async def clear_board_effects(player_ids: list[str], why: str) -> None:
            await self.clear_board_effects(room, player_ids, why)

        async def clear_multiturn(why: str) -> None:
            await self.clear_multiturn_effects(room, why)

        async def ai_place_board(player_id: str) -> bool:
            return await self._ai_place_board(room, player_id)

        async def emit_board_attacks() -> None:
            await self._emit_board_attacks(room)

        async def reveal_to(player_id: str, positions: list[Position],
                            kind: str | None = None) -> None:
            await self._reveal_to(room, player_id, positions, kind)

        async def begin_shenji_redeploy(player_id: str, count: int) -> int:
            return await self.begin_shenji_redeploy(room, player_id, count)

        async def refresh_replay_ships() -> None:
            await self._refresh_replay_ships(room)

        async def emit_frame(event: str, data: dict[str, Any]) -> None:
            await self._publisher.emit(event, data, room=room.id)

        return EffectContext(
            room=room,
            caster_id=item.player_id,
            opponent_id=opponent_id,
            card=item.card,
            targets=item.targets if isinstance(item.targets, dict) else {},
            emit=emit_passthrough,
            draw=draw,
            log=log,
            finish=finish,
            sync_ships=sync_ships,
            sync_player_ships=sync_player_ships,
            sync_hand=sync_hand,
            sync_active_effects=sync_active_effects,
            on_ship_sunk=on_ship_sunk,
            notify_treasure=notify_treasure,
            grant_attacks=grant_attacks,
            maybe_wuxian=maybe_wuxian,
            request_ship_pick=request_ship_pick,
            sacrifice_ship=sacrifice_ship,
            on_ship_destroyed=on_ship_destroyed,
            start_placement=start_placement,
            start_dice_discard=start_dice_discard,
            open_shenji=open_shenji,
            apply_shenji=apply_shenji,
            place_field=place_field,
            tear_down_field=tear_down_field,
            recalc_attacks=recalc_attacks,
            clear_board_effects=clear_board_effects,
            clear_multiturn_effects=clear_multiturn,
            ai_place_board=ai_place_board,
            emit_board_attacks=emit_board_attacks,
            reveal_to=reveal_to,
            begin_shenji_redeploy=begin_shenji_redeploy,
            refresh_replay_ships=refresh_replay_ships,
            emit_frame=emit_frame,
            rng=self.rng,
        )

    async def _refund(self, room: Room, player_id: str, card: MagicCard,
                      message: str) -> None:
        player = room.players.get(player_id)
        if player is None:
            return
        if not any(candidate is card for candidate in player.magic_hand):
            player.magic_hand.append(card)
        for index, candidate in enumerate(room.magic_discard):
            if candidate is card:
                room.magic_discard.pop(index)
                break
        await self._emit_hand(player)
        if player.socket_id:
            await self._publisher.emit("message", {"text": message}, to=player.socket_id)

    # ------------------------------------------------------------------ ending

    async def finish(self, room: Room, winner: str, loser: str, reason: str) -> Any:
        # One ending funnel: every pending magic interaction dies with the match.
        interaction_rules.clear_ship_picks(room)
        self._interaction_waits.pop(room.id, None)
        magic_temps.clear(room)
        for room_id, token in list(self._shenji_tasks):
            if room_id == room.id:
                self._cancel_shenji_task(room_id, token)
        room.pending_dice_discard = {}
        room.pending_dice_discard_label = {}
        room.dice_discard_queue = {}
        room.pending_wuyou_dreams = {}
        room.pending_bingliang = {}
        room.bingliang_skip_draw = {}
        try:
            if self.finish_hook is None:
                return None
            return await self._maybe_await(
                self.finish_hook(room, winner, loser, reason=reason)
            )
        finally:
            # 终局收尾：订阅与租约都不许活过这一局；投影回到默认值。
            # （跑在漏斗之后，GAME_OVER 订阅者仍能看到终局事件。）
            effects.clear(room)
            effects.project_effect_flags(room)

    # --------------------------------------------------------------- target API

    @guard_phase_write
    async def select_magic_target(self, connection: Connection,
                                  data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        target_data = data.get("target_data")
        if not isinstance(target_data, dict):
            return {"status": "error", "message": "目标数据格式错误"}
        safe = {
            key: value for key, value in target_data.items()
            if key in SELECTION_TARGET_KEYS
        }
        room.magic_temp_data = {**(room.magic_temp_data or {}), **safe}
        temp_data_id = data.get("temp_data_id")
        if temp_data_id in KNOWN_CHOICE_IDS:
            return await self.confirm_magic_target({
                "room_id": room.id,
                "player_id": player_id,
                "temp_data_id": temp_data_id,
                "target_data": safe,
            })
        return {"status": "success"}

    async def _sync_each_seat(self, room: Room) -> None:
        """给每个座位各推一份权威快照（同一事件、按人裁剪，不新增协议）。"""

        for seat_id, seat in room.players.items():
            if not seat.socket_id:
                continue
            await self._publisher.emit(
                "room_sync",
                build_room_sync(
                    room,
                    str(seat_id),
                    turn_timeout_seconds=int(
                        getattr(self.rooms, "turn_timeout_seconds", 0) or 0
                    ),
                ),
                to=seat.socket_id,
            )

    async def _with_promoted_choice(self, room: Room, result: dict, confirmer: str) -> dict:
        """确认完一项后，把下一项交给**它的主人**。

        队列里下一项常常是另一个人的（两人先后放仁王之盾）。这时不能把别人的候选
        船位塞进这个确认者的回包——那等于泄露信息且让他的面板跳到别人的待办上；
        改为给每个座位各推一份权威快照，谁的待办谁自己看到。
        """

        promoted = room.magic_promoted
        room.magic_promoted = None
        await self._activate_magic_temp(room)
        await self._sync_each_seat(room)
        if not promoted:
            return result
        owner = magic_temps.owner_of(promoted) or ""
        key = magic_temps.key_of(promoted) or ""
        ok = isinstance(result, dict) and result.get("status") == "success"
        if not ok or (owner and owner != confirmer):
            await self._sync_each_seat(room)
            return result
        if not key:
            return result
        result = dict(result)
        result["next_temp_data_id"] = key
        result["next_temp"] = _temp_payload(promoted)
        return result

    @guard_phase_write
    async def confirm_magic_target(self, connection: Connection | dict[str, Any],
                                   data: dict[str, Any] | None = None) -> dict:
        # select_magic_target re-enters through a plain dict (legacy shape).
        if isinstance(connection, dict):
            payload = connection
            room = self.rooms.get_room(payload.get("room_id"))
            player_id = payload.get("player_id")
            if room is None or not player_id or player_id not in room.players:
                return dict(INVALID_SEAT)
        else:
            payload = data if isinstance(data, dict) else {}
            room, player_id = self._seat(connection, payload)
            if room is None:
                return dict(INVALID_SEAT)
        temp_data_id = payload.get("temp_data_id")
        target_data = payload.get("target_data")
        target_data = target_data if isinstance(target_data, dict) else {}
        temp = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
        if temp_data_id in KNOWN_CHOICE_IDS and (
            temp.get("type") != temp_data_id
            or temp.get("caster") not in (None, player_id)
        ):
            return {"status": "error", "message": "当前没有待处理的魔法卡选择"}
        handler = {
            "taoyuan_choice": self._confirm_taoyuan,
            "lingqi_choice": self._confirm_lingqi,
            "bury_choice": self._confirm_bury,
            "wangyang_choice": self._confirm_wangyang,
            "shield_choice": self._confirm_shield,
        }.get(temp_data_id)
        if handler is None:
            if temp_data_id not in KNOWN_CHOICE_IDS:
                return {"status": "error", "message": "无效的临时数据ID"}
            return {"status": "error", "message": "当前没有待处理的魔法卡选择"}
        result = await handler(room, player_id, temp, target_data)
        # 灵气仍需双方重摆，仁王之盾已有专属事件，神机宣言也不是最终效果。
        completed = {
            "taoyuan_choice": ("桃园结义", "已完成卡牌分配"),
            "bury_choice": ("明智埋葬", "已埋葬一张魔法卡"),
            "wangyang_choice": ("亡羊补牢", "已取回一张魔法卡"),
        }.get(temp_data_id)
        if result.get("status") == "success" and completed:
            await self._emit_effect_notice(room, player_id, *completed)
        return await self._with_promoted_choice(room, result, player_id)

    async def _confirm_taoyuan(self, room: Room, player_id: str,
                               temp: dict[str, Any], target_data: dict[str, Any]) -> dict:
        if temp.get("type") != "taoyuan_choice" or temp.get("caster") != player_id:
            return {"status": "error", "message": "当前没有待处理的桃园结义选择"}
        cards = temp.get("cards") or []
        if not isinstance(cards, list) or not cards:
            return {"status": "error", "message": "没有可分配的卡牌"}
        try:
            caster_choice = target_rules.strict_int(target_data.get("caster_choice"))
        except (TypeError, ValueError):
            return {"status": "error", "message": "无效的卡牌选择"}
        caster = room.players[player_id]
        if caster_choice is None or not 0 <= caster_choice < len(cards):
            return {"status": "error", "message": "无效的卡牌选择"}
        opponent_id = room.opponent_of(player_id)
        opponent = room.players.get(opponent_id) if opponent_id else None
        if opponent is None:
            return {"status": "error", "message": "房间人数不足"}
        if caster.effect_flags.no_draw or opponent.effect_flags.no_draw:
            room.magic_deck.extend(cards)
            magic_temps.finish(room, 'taoyuan_choice', owner=player_id)
            await self._sync_each_seat(room)
            return {"status": "error", "message": "无中生有生效中，候选卡已放回牌堆，无法获得卡牌"}
        caster.magic_hand.append(cards[caster_choice])

        opponent_choice = -1
        if len(cards) > 1:
            requested = -1
            try:
                requested = int(target_data.get("opponent_choice", -1))
            except (TypeError, ValueError):
                requested = -1
            if 0 <= requested < len(cards) and requested != caster_choice:
                opponent_choice = requested
            else:
                opponent_choice = next(
                    (index for index in range(len(cards)) if index != caster_choice), -1
                )
            if 0 <= opponent_choice < len(cards):
                opponent.magic_hand.append(cards[opponent_choice])
        remaining = [
            card for index, card in enumerate(cards)
            if index not in (caster_choice, opponent_choice)
        ]
        room.magic_deck += remaining
        magic_temps.finish(room, "taoyuan_choice", owner=player_id)
        await self._emit_hand(caster)
        await self._emit_hand(opponent)
        if opponent.socket_id:
            await self._publisher.emit(
                "taoyuan_complete", {"message": "对方桃园结义结算完成"},
                to=opponent.socket_id,
            )
        took = cards[opponent_choice].name if 0 <= opponent_choice < len(cards) else None
        await self._add_log(
            room,
            f"第{room.round}回合 · {self._name(room, player_id)} 的【桃园结义】分配："
            f"自己拿「{cards[caster_choice].name}」"
            + (f"，对方拿「{took}」" if took else "，没有对方那一份")
            + (f"，其余 {len(remaining)} 张放回牌堆" if remaining else ""),
            "magic",
            {"card": "桃园结义", "mine": cards[caster_choice].name,
             "theirs": took, "returned": len(remaining)},
        )
        replay_rules.note_hand_change(
            room,
            f"{self._name(room, player_id)} 的【桃园结义】分配了 {len(cards)} 张候选牌",
            {"card": "桃园结义", "mine": cards[caster_choice].name,
             "theirs": took, "returned": len(remaining)},
            self._name(room, player_id),
        )
        return {"status": "success", "message": "桃园结义选择完成"}

    async def _confirm_lingqi(self, room: Room, player_id: str,
                              temp: dict[str, Any], target_data: dict[str, Any]) -> dict:
        if temp.get("type") != "lingqi_choice" or temp.get("caster") != player_id:
            return {"status": "error", "message": "当前没有待处理的灵气复苏选择"}
        try:
            max_ships = int(temp.get("max_ships"))
        except (TypeError, ValueError):
            return {"status": "error", "message": "可选择的船数范围无效"}
        try:
            target_ships = int(target_data.get("target_ships"))
        except (TypeError, ValueError):
            return {"status": "error", "message": "无效的船数选择"}
        if target_ships < 1 or target_ships > max_ships:
            return {"status": "error", "message": f"无效的船数选择，应在1-{max_ships}之间"}

        # 卡面「只可以在自己原本有战舰的地方进行调整」：清空之前先把各自的原船位记下来，
        # 由 `place_ships` 在真正写入前校验（含沉船位，复活/重摆都可能用到）。
        # 用 `placement_rules.own_board_cells`：除活舰与沉船外，还包括被【神威！】
        # 暂时除外、下一大回合要回原位的船 —— 它们同样属于「自己原本有战舰的地方」。
        # 漏掉这一项会让该座位白名单为空，AI 摆 0 艘后 `all_players_placed` 永假，
        # 房间会卡在 placing_ships（有人提交后一直等对面摆船）。
        room.game_effects["reset_allowed_cells"] = {
            pid: placement_rules.own_board_cells(room, pid)
            for pid in room.players
        }
        frames = lifecycle_rules.clear_board_effects(room, list(room.players), "灵气复苏")
        frames += lifecycle_rules.clear_multiturn_effects(room, "灵气复苏")
        interaction_rules.clear_ship_picks(room)
        for player in room.players.values():
            player.ships = []
            player.sunken_ships = []
            player.attacks = []
            player.remaining_ships = 0
            player.needs_reset = True
            player.revealed_positions = []
            player.max_ships = target_ships
        replay_rules.note_board_reset(room)
        replay_rules.note_board_replaced(room)
        magic_temps.finish(room, "lingqi_choice", owner=player_id)
        # AI seats take their new board inside this stack frame (lesson #38).
        await self._ai_place_any(room)
        room.lingqi_saved_state = {
            "attack_order": list(room.attack_order),
            "current_attacker": room.current_attacker,
            "current_phase": getattr(room.current_phase, "value", room.current_phase),
            "round": room.round,
            "attacks_remaining": room.attacks_remaining,
        }
        room.state = RoomState.PLACING_SHIPS
        room.lingqi_resurgence_applied = True
        for frame, payload in frames:
            await self._publisher.emit(frame, payload, room=room.id)
        for pid, player in room.players.items():
            if player.socket_id:
                await self._publisher.emit(
                    "reset_gameboard",
                    {
                        "new_max_ships": target_ships,
                        "reset_allowed_cells": room.game_effects["reset_allowed_cells"].get(pid),
                        "message": f"灵气复苏生效，双方需要重新摆放{target_ships}艘战舰",
                    },
                    to=player.socket_id,
                )
        opponent_id = room.opponent_of(player_id)
        if opponent_id and room.players[opponent_id].socket_id:
            await self._publisher.emit(
                "lingqi_complete", {"message": "对方灵气复苏结算完成"},
                to=room.players[opponent_id].socket_id,
            )
        return {"status": "success", "message": "灵气复苏船数选择完成"}

    async def _confirm_bury(self, room: Room, player_id: str,
                            temp: dict[str, Any], target_data: dict[str, Any]) -> dict:
        if temp.get("type") != "bury_choice" or temp.get("caster") != player_id:
            return {"status": "error", "message": "当前没有待处理的明智埋葬选择"}
        source = target_data.get("source")
        if source is None:
            source = "deck"
        if source not in ("deck", "opponent_hand"):
            return {"status": "error", "message": "无效的选择"}
        candidates = temp.get("candidates") or []

        def as_index(value):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            return value

        expected = None
        index = as_index(target_data.get("source_index"))
        if index is not None:
            expected = next(
                (c.get("name") for c in candidates
                 if c.get("source") == source and c.get("index") == index),
                None,
            )
        if index is None:
            flat = as_index(target_data.get("card_index"))
            if flat is not None and flat < len(candidates):
                candidate = candidates[flat]
                if candidate.get("source") == source:
                    index = as_index(candidate.get("index"))
                    expected = candidate.get("name")
            if index is None:
                index = flat
        if index is None:
            return {"status": "error", "message": "无效的选择"}
        if source == "deck":
            pile = room.magic_deck
            opponent = None
        else:
            opponent_id = room.opponent_of(player_id)
            opponent = room.players.get(opponent_id) if opponent_id else None
            if opponent is None:
                return {"status": "error", "message": "无效的选择"}
            pile = opponent.magic_hand
        if not (0 <= index < len(pile)):
            return {"status": "error", "message": "无效的选择"}
        if expected and pile[index].name != expected:
            moved = next((i for i, card in enumerate(pile) if card.name == expected), None)
            if moved is None:
                return {"status": "error", "message": "选中的卡牌已不在原处"}
            index = moved
        buried = pile.pop(index)
        room.magic_discard.append(buried)
        await self._emit_card_discarded(room, player_id, buried, "bury")
        magic_temps.finish(room, "bury_choice", owner=player_id)
        deck_before = len(room.magic_deck)
        drawn = await self.draw(room, player_id)
        if opponent is not None:
            await self._emit_hand(opponent)
        if drawn is not None:
            detail = f"埋葬了「{buried.name}」，并摸到了「{drawn.name}」"
        elif room.players[player_id].effect_flags.no_draw:
            detail = f"埋葬了「{buried.name}」，但「无中生有」生效中，本大回合无法摸牌"
        elif deck_before == 0:
            detail = f"埋葬了「{buried.name}」，但牌堆已空，没能摸到牌"
        else:
            detail = f"埋葬了「{buried.name}」，摸到的牌与手牌重复，已直接进弃牌堆"
        await self._add_log(
            room,
            f"第{room.round}回合 · {self._name(room, player_id)} 的【明智埋葬】{detail}",
            "magic",
            {"caster": player_id, "card": "明智埋葬", "buried": buried.name},
        )
        return {"status": "success", "message": detail}


    async def _confirm_wangyang(self, room: Room, player_id: str,
                                temp: dict[str, Any], target_data: dict[str, Any]) -> dict:
        if temp.get("type") != "wangyang_choice" or temp.get("caster") != player_id:
            return {"status": "error", "message": "当前没有待处理的亡羊补牢选择"}
        cards = temp.get("cards") or []
        if not isinstance(cards, list) or not cards:
            return {"status": "error", "message": "没有可挑选的卡牌"}
        try:
            chosen_index = int(target_data.get("chosen_index", -1))
        except (TypeError, ValueError):
            chosen_index = -1
        if not (0 <= chosen_index < len(cards)):
            return {"status": "error", "message": "无效的卡牌选择"}
        chosen = cards[chosen_index]
        if room.players[player_id].effect_flags.no_draw:
            room.magic_discard.extend(cards)
            if temp.get('own_card') is not None:
                room.magic_discard.append(temp['own_card'])
            magic_temps.finish(room, 'wangyang_choice', owner=player_id)
            await self._sync_each_seat(room)
            return {"status": "error", "message": "无中生有生效中，候选卡已退回弃牌堆，无法获得卡牌"}
        room.players[player_id].magic_hand.append(chosen)
        for index, card in enumerate(cards):
            if index != chosen_index:
                room.magic_discard.append(card)
                await self._emit_card_discarded(room, player_id, card, "wangyang")
        own_card = temp.get("own_card")
        if own_card is not None:
            room.magic_discard.append(own_card)
            await self._emit_card_discarded(room, player_id, own_card, "wangyang")
        magic_temps.finish(room, "wangyang_choice", owner=player_id)
        await self._emit_hand(room.players[player_id])
        opponent_id = room.opponent_of(player_id)
        if opponent_id and room.players[opponent_id].socket_id:
            await self._publisher.emit(
                "wangyang_complete",
                {"message": f"对方亡羊补牢选择了「{chosen.name}」", "chosen": chosen.name},
                to=room.players[opponent_id].socket_id,
            )
        await self._add_log(
            room,
            f"第{room.round}回合 · {self._name(room, player_id)} 的【亡羊补牢】"
            f"从弃牌区取回「{chosen.name}」加入手牌",
            "magic",
            {"caster": player_id, "card": "亡羊补牢", "chosen": chosen.name},
        )
        return {"status": "success", "message": f"已将「{chosen.name}」加入手牌"}

    async def _confirm_shield(self, room: Room, player_id: str,
                              temp: dict[str, Any], target_data: dict[str, Any]) -> dict:
        if temp.get("type") != "shield_choice" or temp.get("caster") != player_id:
            return {"status": "error", "message": "当前没有待处理的仁王之盾选择"}
        caster = room.players[player_id]
        raw = target_data.get("ship_indices") or []
        if not isinstance(raw, list) or not raw:
            return {"status": "error", "message": "请至少选择一艘战舰"}
        selected: list[PlayerShip] = []
        skipped = 0
        seen: set[int] = set()
        for raw_index in raw[:3]:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if not (0 <= index < len(caster.ships)) or index in seen:
                continue
            seen.add(index)
            if not is_ship_alive(caster, caster.ships[index]):
                skipped += 1
                continue
            caster.ships[index].shield = True
            selected.append(caster.ships[index])
        if not selected:
            return {"status": "error", "message": "无效的选择（已沉没的船不能加护盾）"}
        magic_temps.finish(room, "shield_choice", owner=player_id)
        interaction_rules.consume_ship_pick(room, player_id, "shield_choice")
        await self._emit_player_ships(room, player_id)
        await self._publisher.emit(
            "shields_added",
            {
                "player": player_id,
                "count": len(selected),
                "positions": [{"x": p.x, "y": p.y} for ship in selected for p in ship.positions],
                "ships": [
                    [{"x": p.x, "y": p.y} for p in ship.positions] for ship in selected
                ],
            },
            room=room.id,
        )
        if caster.socket_id:
            await self._publisher.emit(
                "message", {"text": f"已为{len(selected)}艘战舰添加护盾"}, to=caster.socket_id
            )
        message = f"为{len(selected)}艘战舰添加了护盾"
        if skipped:
            message += f"（{skipped}艘已沉没，已跳过）"
        return {"status": "success", "message": message}

    async def get_magic_temp_data(self, connection: Connection,
                                  data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        temp = room.magic_temp_data or {}
        top_pick = self._top_ship_pick(room, player_id)
        owner = magic_temps.owner_of(temp)
        if owner == player_id:
            return {"status": "success", "data": _json_temp(temp)}
        if top_pick is not None:
            # 只是轮到你点一艘船（例如神之宣告里对方挑牺牲舰）：只给「你自己的选船
            # 信息」，不把别人待选卡牌的候选内容顺带吐出来。
            return {
                "status": "success",
                "data": {
                    "type": "ship_pick",
                    "reason": str(top_pick.get("reason") or ""),
                    "message": str(top_pick.get("message") or ""),
                },
            }
        return {"status": "error", "message": "没有等待你处理的魔法卡选择"}

    @staticmethod
    def _top_ship_pick(room: Room, player_id: str) -> dict[str, Any] | None:
        return interaction_rules.top_ship_pick(room, player_id)

    async def get_discard_pile(self, connection: Connection,
                               data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, _player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        cards = deck_rules.unique_discard_pile(room.magic_discard)
        return {
            "status": "success",
            "discard_pile": [card_payload(card) for card in cards],
        }


    @guard_phase_write
    async def cancel_magic_selection(self, connection: Connection,
                                     data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        temp = room.magic_temp_data or {}
        if magic_temps.owner_of(temp) != player_id:
            return {"status": "error", "message": "当前没有等待你处理的选择"}
        pending = temp.get("pending_placement")
        if pending and pending.get("caster") == player_id:
            return {"status": "error", "message": "放置尚未完成，请用放置面板的「放弃」"}
        if temp.get("caster") and temp.get("caster") != player_id:
            return {"status": "error", "message": "当前不是你的选择"}
        cancelled = magic_temps.key_of(temp)
        cards = temp.get("cards")

        shenji = temp.get("pending_shenji")
        if isinstance(shenji, dict) and shenji.get("caster") == player_id:
            self._cancel_shenji_task(room.id, shenji.get("token"))
            room.game_effects.pop(f"prediction_initial_{player_id}", None)
            await self._publisher.emit(
                "shenji_waiting_end", {"reason": "declaration_timeout"}, room=room.id
            )
            await self._publisher.emit(
                "message", {"text": "神机妙算宣言已取消，本次效果作废"}, room=room.id
            )

        if cancelled == "wangyang_choice":
            for card in cards or []:
                if isinstance(card, MagicCard):
                    room.magic_discard.append(card)
                    await self._emit_card_discarded(room, player_id, card, "cancel")
            own = temp.get("own_card")
            if isinstance(own, MagicCard):
                room.magic_discard.append(own)
                await self._emit_card_discarded(room, player_id, own, "cancel")
        elif isinstance(cards, list):
            room.magic_deck.extend(card for card in cards if isinstance(card, MagicCard))
        if cancelled == "shield_choice":
            interaction_rules.consume_ship_pick(room, player_id, "shield_choice")
        magic_temps.finish(room, cancelled, owner=player_id)
        await self._activate_magic_temp(room)
        await self._sync_each_seat(room)

        if cancelled in ("taoyuan_choice", "lingqi_choice"):
            opponent_id = room.opponent_of(player_id)
            if opponent_id and opponent_id in room.players:
                label = "桃园结义" if cancelled == "taoyuan_choice" else "灵气复苏"
                event = "taoyuan_complete" if cancelled == "taoyuan_choice" else "lingqi_complete"
                if room.players[opponent_id].socket_id:
                    await self._publisher.emit(
                        event,
                        {
                            "cancelled": True,
                            "message": f"对方取消了{label}（已放回牌堆），本回合继续",
                        },
                        to=room.players[opponent_id].socket_id,
                    )
        if cancelled == "wangyang_choice":
            opponent_id = room.opponent_of(player_id)
            if opponent_id and room.players[opponent_id].socket_id:
                await self._publisher.emit(
                    "wangyang_complete",
                    {"cancelled": True, "message": "对方取消了亡羊补牢（弃牌区已还原）"},
                    to=room.players[opponent_id].socket_id,
                )
        player = room.players.get(player_id)
        if player and player.socket_id:
            await self._publisher.emit("message", {"text": "已取消本次选择"}, to=player.socket_id)
        return {"status": "success", "message": "已取消本次选择"}

    async def notify_treasure(self, room: Room, times: int = 1,
                              exclude_player_id: str | None = None) -> int:
        total = 0
        holders = [
            pid for pid, player in room.players.items()
            if getattr(player.effect_flags, "treasure_hunter", False)
        ]
        for pid in holders:
            if exclude_player_id is not None and pid == exclude_player_id:
                continue
            for _ in range(max(0, int(times))):
                await self.draw(room, pid)
                total += 1
        return total

    async def _request_demon_contract_sacrifice(self, room: Room, lost_player_id: str) -> None:
        sacrifice_id = room.opponent_of(lost_player_id)
        if not sacrifice_id:
            return
        picked = await self.request_ship_pick(
            room, sacrifice_id, "demon_contract",
            "恶魔契约生效：请点选一艘自己的战舰牺牲", True, False,
            source_id=lost_player_id,
        )
        if picked is not None:
            await self._sacrifice_ship(room, sacrifice_id, picked, "demon_contract", source_id=lost_player_id)

    async def _mirror_contract_loss(self, room: Room, lost_player_id: str) -> None:
        """一方少了一艘：另一方也要牺牲一艘（契约在场时由 on_ship_sunk 调用）。"""

        if not contract_rules.enabled(room):
            return
        sacrifice_id = room.opponent_of(lost_player_id)
        if not sacrifice_id:
            return
        with contract_rules.mirroring(room):
            await self._request_demon_contract_sacrifice(room, lost_player_id)

    async def _mirror_contract_gain(self, room: Room, gained_player_id: str, count: int = 1) -> None:
        """一方多出 N 艘：另一方也获得 N 艘部署（走同一条摆船义务队列）。"""

        gain = int(count or 0)
        if gain <= 0 or not contract_rules.enabled(room):
            return
        deploy_id = room.opponent_of(gained_player_id)
        if not deploy_id:
            return
        with contract_rules.mirroring(room):
            await self._start_placement(room, deploy_id, "contract_gain", gain, mirrored=True)

    async def _mirror_contract_delta(self, room: Room, player_id: str, delta: int) -> None:
        if delta > 0:
            await self._mirror_contract_gain(room, player_id, delta)
        elif delta < 0:
            for _ in range(-delta):
                await self._mirror_contract_loss(room, player_id)

    @staticmethod
    def _last_attacker(room: Room) -> str | None:
        """炮击路径的击杀者：resolve_attack 已把这一发写进 room.last_attack。"""

        last = room.last_attack or {}
        attacker = last.get("attacker")
        return attacker if attacker in room.players else None

    async def on_ship_sunk(self, room: Room, defender_id: str, ship: Any,
                           *, magic: bool = False,
                           attacker_id: str | None = None) -> None:
        defender = room.players.get(defender_id)
        if defender is None:
            return
        # 单一漏斗：炮击（battle.sink_hooks）与效果（ctx.on_ship_sunk）都到这里。
        # SHIP_SUNK 全项目只在这里发一次（battle 层不再补发第二帧）。
        await hooks.emit(
            room,
            hooks.SHIP_SUNK,
            {
                "room_id": room.id,
                "owner_id": defender_id,
                "defender_id": defender_id,
                "ship": ship,
                "attacker_id": attacker_id or self._last_attacker(room),
                "remaining_ships": defender.remaining_ships,
                "magic": bool(magic),
            },
        )
        if "holy_heart" in room.game_effects:
            room.game_effects.pop("holy_heart", None)
            await self._publisher.emit(
                "holy_heart_interrupted",
                {"reason": "有战舰被击沉，无暇圣心效果中断"},
                room=room.id,
            )
        if getattr(ship, "trap", False):
            ship.trap = False
            await self._trigger_ship_trap(room, defender_id, ship)
        if contract_rules.enabled(room):
            await self._mirror_contract_loss(room, defender_id)
        # 八方来财只响应对方造成的船数变化；自己主动击沉对方（包括轰炸等
        # 魔法造成的击沉）不能让自己摸牌。优先使用调用链传入的攻击者，
        # 旧路径再回退到 last_attack。
        last = room.last_attack or {}
        source_attacker = attacker_id or last.get("attacker")
        await self.notify_treasure(room, 1, exclude_player_id=source_attacker)
        await self._emit_player_ships(room, defender_id)

    async def on_ship_destroyed(self, room: Room, owner_id: str, ship: Any,
                               *, attacker_id: str | None = None) -> None:
        owner = room.players.get(owner_id)
        if owner is None:
            return
        # 效果摧毁的唯一发射点（百亿补贴等订阅者在这里看到 owner_id）。
        await hooks.emit(
            room,
            hooks.SHIP_DESTROYED,
            {
                "room_id": room.id,
                "owner_id": owner_id,
                "ship": ship,
                "attacker_id": attacker_id or self._last_attacker(room),
                "remaining_ships": owner.remaining_ships,
            },
        )
        if "holy_heart" in room.game_effects:
            room.game_effects.pop("holy_heart", None)
            await self._publisher.emit(
                "holy_heart_interrupted",
                {"reason": "有战舰被击沉，无暇圣心效果中断"},
                room=room.id,
            )
        if getattr(ship, "trap", False):
            ship.trap = False
            await self._trigger_ship_trap(room, owner_id, ship)

    async def on_damage(self, room: Room, attacker_id: str, outcome: Any) -> None:
        attacker = room.players.get(attacker_id)
        if attacker is None or not getattr(outcome, 'ship_sunk', False):
            return
        if attacker.effect_flags.vampire:
            await self.draw(room, attacker_id)
            if attacker.socket_id:
                await self._publisher.emit(
                    "message", {"text": "饮血效果发动，抽一张卡"}, to=attacker.socket_id
                )
        if attacker.effect_flags.battle_spirit:
            gained = battle_rules.grant_extra_attacks(room, attacker_id, 2)
            if gained:
                await self._publisher.emit(
                    "attacks_updated",
                    {
                        "current_attacker": room.current_attacker,
                        "attacks_remaining": room.attacks_remaining,
                    },
                    room=room.id,
                )
                if attacker.socket_id:
                    await self._publisher.emit(
                        "message", {"text": "越战越勇效果发动，攻击次数净增加1"},
                        to=attacker.socket_id,
                    )

    async def on_attacks_exhausted(self, room: Room, player_id: str) -> None:
        await self.maybe_wuxian(room, player_id)

    async def maybe_wuxian(self, room: Room, player_id: str) -> bool:
        player = room.players.get(player_id)
        if player is None or not getattr(player.effect_flags, "wuxian", False):
            return False
        if field_magic_name(room) == "教皇旨意" or battle_rules.attacks_forced_zero(room):
            return False
        if room.current_attacker != player_id:
            return False
        if room.attacks_remaining > 0:
            return False
        if player.damage_dealt_this_turn > 0:
            return False
        # #38：五险一金触发即消费租约。
        effects.consume_flag(room, player_id, "wuxian")
        room.attacks_remaining += 3
        await self._add_log(
            room,
            f"第{room.round}回合 · {self._name(room, player_id)} 触发五险一金，攻击次数 +3",
            "magic",
            {"player": player_id, "card": "五险一金"},
        )
        if player.socket_id:
            await self._publisher.emit(
                "message",
                {"text": "五险一金生效：攻击次数已用尽且未造成伤害，攻击次数 +3"},
                to=player.socket_id,
            )
        await self._publisher.emit(
            "attacks_updated",
            {
                "current_attacker": room.current_attacker,
                "attacks_remaining": room.attacks_remaining,
            },
            room=room.id,
        )
        await self._emit_active_effects(room)
        return True


    # ---------------------------------------------------------- shenji window

    def _snapshot_shenji_baseline(self, room: Room, caster_id: str) -> None:
        player = room.players.get(caster_id)
        if player is None:
            return
        sunken = list(player.sunken_ships or [])
        room.game_effects[f"prediction_initial_{caster_id}"] = {
            "ships": player.remaining_ships,
            "sunken": len(sunken),
            "sunken_ids": [id(ship) for ship in sunken],
        }

    async def open_shenji(self, room: Room, caster_id: str) -> None:
        token = int(getattr(room, "magic_temp_seq", 0)) + 1
        magic_temps.store(room, {"pending_shenji": {"caster": caster_id, "token": token}})
        await self._activate_magic_temp(room)

    async def settle_interaction_timeout(self, room: Room, now: float, seconds: float) -> bool:
        """沿用思考时限完成互动义务；不直接越过阶段，也不在重连宽限期代选。"""
        temp = magic_temps.active(room)
        picks = room.pending_ship_picks or []
        dice = room.pending_dice_discard or {}
        signature = (
            temp.get("id"), magic_temps.owner_of(temp), temp.get("type"),
            tuple((p.get("player"), p.get("reason")) for p in picks),
            tuple(sorted(pid for pid, done in dice.items() if done is False)),
        )
        if seconds <= 0 or not interaction_rules.pending_action_reason(room, room.current_attacker):
            self._interaction_waits.pop(room.id, None)
            return False
        if room.disconnected or room.chain or room.chain_waiting:
            self._interaction_waits.pop(room.id, None)
            return False
        previous = self._interaction_waits.get(room.id)
        if previous is None or previous[0] != signature:
            self._interaction_waits[room.id] = (signature, now)
            return False
        if now - previous[1] < seconds or self.ai_choice_hook is None:
            return False
        owners = {magic_temps.owner_of(temp)} | {p.get("player") for p in picks}
        for owner in owners:
            if owner in room.players:
                await self.ai_choice_hook(room, owner)
        for pid, done in list((room.pending_dice_discard or {}).items()):
            if done is False and pid in room.players:
                await self.dice_discard_choose(
                    Connection(sid=room.players[pid].socket_id or pid),
                    {"room_id": room.id, "player_id": pid, "card_index": 0},
                )
        self._interaction_waits.pop(room.id, None)
        await self._activate_magic_temp(room)
        await self._sync_each_seat(room)
        await self._publisher.emit("message", {"text": "魔法选择思考超时，已自动完成当前选择"}, room=room.id)
        return True

    async def _activate_magic_temp(self, room: Room) -> None:
        """只激活队首：延迟启动宣言倒计时，并让非当前回合的AI也能答复自己的义务。"""
        temp = magic_temps.active(room)
        owner = magic_temps.owner_of(temp)
        if not owner:
            return
        if owner.startswith("ai-") and room.is_ai_room and self.ai_choice_hook is not None:
            if not room.game_effects.get("activating_ai_choice"):
                room.game_effects["activating_ai_choice"] = True
                try:
                    await self.ai_choice_hook(room, owner)
                finally:
                    room.game_effects.pop("activating_ai_choice", None)
            return
        if temp.get("pending_placement"):
            await self._emit_placement_request(room, owner)
        pending = temp.get("pending_shenji")
        if not isinstance(pending, dict):
            return
        token = pending["token"]
        if (room.id, token) in self._shenji_tasks:
            return
        caster_id = owner
        self._snapshot_shenji_baseline(room, caster_id)
        opponent_id = room.opponent_of(caster_id)
        if opponent_id and room.players[opponent_id].socket_id:
            await self._publisher.emit(
                "shenji_waiting",
                {"caster": caster_id, "text": "等待对方神机妙算宣言中"},
                to=room.players[opponent_id].socket_id,
            )
        task = asyncio.create_task(self._shenji_timeout(room.id, token))
        self._shenji_tasks[(room.id, token)] = task
        task.add_done_callback(lambda _done: self._shenji_tasks.pop((room.id, token), None))

    def _cancel_shenji_task(self, room_id: str, token: Any) -> None:
        if not isinstance(token, int):
            return
        task = self._shenji_tasks.pop((room_id, token), None)
        if task is not None:
            task.cancel()

    async def _shenji_timeout(self, room_id: str, token: int) -> None:
        try:
            await asyncio.sleep(max(0.0, float(self.shenji_timeout_seconds)))
        except asyncio.CancelledError:
            return
        room = self.rooms.get_room(room_id)
        if room is None:
            return
        pending = (room.magic_temp_data or {}).get("pending_shenji") or {}
        if pending.get("token") != token:
            return
        caster = pending.get("caster")
        magic_temps.finish(room, "pending_shenji", owner=caster)
        if caster:
            room.game_effects.pop(f"prediction_initial_{caster}", None)
        await self._publisher.emit(
            "shenji_waiting_end", {"reason": "declaration_timeout"}, room=room.id
        )
        await self._publisher.emit(
            "message", {"text": "神机妙算宣言超时，本次效果作废"}, room=room.id
        )
        await self._activate_magic_temp(room)
        await self._sync_each_seat(room)

    async def apply_shenji(self, room: Room, caster_id: str, value: int) -> None:
        player = room.players.get(caster_id)
        if player is None:
            return
        x = max(0, min(6, int(value)))
        # #38：prediction 是 round 边界的整数租约（大回合结束时随投影清零）。
        effects.grant_flag(
            room, caster_id, "prediction", boundary=effects.BOUNDARY_ROUND, value=x
        )
        if f"prediction_initial_{caster_id}" not in room.game_effects:
            self._snapshot_shenji_baseline(room, caster_id)
        room.magic_temp_data.pop("prediction", None)
        pending = (room.magic_temp_data or {}).get("pending_shenji") or {}
        self._cancel_shenji_task(room.id, pending.get("token"))
        magic_temps.finish(room, "pending_shenji", owner=caster_id)
        opponent_id = room.opponent_of(caster_id)
        if opponent_id and room.players[opponent_id].socket_id:
            await self._publisher.emit(
                "shenji_waiting_end", {"reason": "declared"},
                to=room.players[opponent_id].socket_id,
            )
            await self._publisher.emit(
                "message",
                {"text": f"对方宣言神机妙算：船数减少{x}时生效"},
                to=room.players[opponent_id].socket_id,
            )
        await self._activate_magic_temp(room)
        await self._sync_each_seat(room)

    @guard_phase_write
    async def confirm_shenji_declare(self, connection: Connection,
                                     data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        pending = (room.magic_temp_data or {}).get("pending_shenji")
        if not pending or pending.get("caster") != player_id:
            return {"status": "error", "message": "没有待宣言的神机妙算"}
        try:
            x = max(0, min(6, int(data.get("prediction", 0))))
        except (TypeError, ValueError):
            return {"status": "error", "message": "宣言数值无效"}
        await self.apply_shenji(room, player_id, x)
        return {"status": "success", "message": f"已宣言：船数减少{x}时不减少"}

    # ------------------------------------------------------------ judgement

    async def settle_wuyou_dream(self, room: Room) -> None:
        pending = getattr(room, "pending_wuyou_dreams", None)
        if not isinstance(pending, dict) or not pending:
            return
        current = room.current_attacker
        if not current or current not in room.players:
            return
        hits = [
            caster_id for caster_id in list(pending)
            if caster_id in room.players and room.opponent_of(caster_id) == current
        ]
        for caster_id in hits:
            times = int(pending.pop(caster_id) or 0)
            for _ in range(times):
                await self._apply_wuyou_dream(room, caster_id, current)

    async def _apply_wuyou_dream(self, room: Room, caster_id: str,
                                 opponent_id: str) -> None:
        caster_roll = int(self.rng.randint(1, 6))
        opponent_roll = int(self.rng.randint(1, 6))
        if opponent_roll < caster_roll:
            outcome = "opponent_zero_attacks"
            effect_text = "打出者点数更高：对方本回合的攻击次数恒定为 0"
        elif opponent_roll > caster_roll:
            outcome = "opponent_discard"
            effect_text = "打出者点数更低：对方必须弃置一张手牌"
        else:
            outcome = "tie"
            effect_text = "平局：什么都没发生"
        await self._publisher.emit(
            "dice_rolled",
            {
                "roll": caster_roll,
                "opponent_roll": opponent_roll,
                "caster": caster_id,
                "effect_text": effect_text,
                "card": "无忧梦呓",
                "duration_ms": 3600,
            },
            room=room.id,
        )
        await self._add_log(
            room,
            f"第{room.round}回合 · 【无忧梦呓】拼点："
            f"{self._name(room, caster_id)} {caster_roll} 点 vs "
            f"{self._name(room, opponent_id)} {opponent_roll} 点 —— {effect_text}",
            "magic",
            {"card": "无忧梦呓", "caster": caster_id, "opponent": opponent_id,
             "caster_roll": caster_roll, "opponent_roll": opponent_roll,
             "outcome": outcome},
        )
        if outcome == "opponent_zero_attacks":
            room.attacks_remaining = 0
            entry = room.game_effects.get("zero_attacks_turn")
            if not isinstance(entry, dict):
                entry = {}
            entry[opponent_id] = room.round
            room.game_effects["zero_attacks_turn"] = entry
            await self._publisher.emit(
                "attacks_updated",
                {
                    "current_attacker": room.current_attacker,
                    "attacks_remaining": room.attacks_remaining,
                },
                room=room.id,
            )
        elif outcome == "opponent_discard":
            await self.start_dice_discard(
                room, caster_id, opponent_id, opponent_id, "无忧梦呓"
            )

    async def settle_bingliang(self, room: Room) -> None:
        current = room.current_attacker
        if not current or current not in room.players:
            return
        pending = getattr(room, "pending_bingliang", None)
        if not isinstance(pending, dict) or not pending:
            return
        hits = [
            caster_id for caster_id in list(pending)
            if caster_id in room.players and room.opponent_of(caster_id) == current
        ]
        for caster_id in hits:
            times = int(pending.pop(caster_id) or 0)
            for _ in range(times):
                await self._roll_bingliang(room, caster_id, current)

    async def _roll_bingliang(self, room: Room, caster_id: str, target_id: str) -> None:
        roll = int(self.rng.randint(1, 6))
        if roll < BINGLIANG_FAIL_BELOW:
            outcome = "fail"
            effect_text = "判定失败：不产生任何效果"
        else:
            outcome = "skip_draw"
            effect_text = "判定成功：对方接下来的两个准备阶段各跳过一次摸牌"
        await self._publisher.emit(
            "dice_rolled",
            {"roll": roll, "caster": caster_id, "effect_text": effect_text,
             "card": "兵粮寸断", "duration_ms": 3200},
            room=room.id,
        )
        await self._add_log(
            room,
            f"第{room.round}回合 · 【兵粮寸断】判定："
            f"{self._name(room, caster_id)} 打出，"
            f"{self._name(room, target_id)} {roll} 点 —— {effect_text}",
            "magic",
            {"card": "兵粮寸断", "caster": caster_id, "target": target_id,
             "roll": roll, "outcome": outcome},
        )
        if outcome == "skip_draw":
            skips = getattr(room, "bingliang_skip_draw", None)
            if not isinstance(skips, dict):
                skips = {}
                room.bingliang_skip_draw = skips
            skips[target_id] = int(skips.get(target_id) or 0) + BINGLIANG_SKIP_PHASES

    async def consume_bingliang_skip(self, room: Room, player_id: str) -> bool:
        skips = getattr(room, "bingliang_skip_draw", None)
        if not isinstance(skips, dict):
            return False
        left = int(skips.get(player_id) or 0)
        if left <= 0:
            return False
        if left - 1 > 0:
            skips[player_id] = left - 1
        else:
            skips.pop(player_id, None)
        await self._add_log(
            room,
            f"第{room.round}回合 · 【兵粮寸断】"
            f"{self._name(room, player_id)} 的准备阶段摸牌被跳过（剩余 {max(0, left - 1)} 次）",
            "magic",
            {"card": "兵粮寸断", "player": player_id, "remaining": max(0, left - 1)},
        )
        return True


    async def start_dice_discard(self, room: Room, caster_id: str, opponent_id: str,
                                 only_player: str | None = None,
                                 card_name: str = "命运骰子") -> None:
        pending = getattr(room, "pending_dice_discard", None)
        if not isinstance(pending, dict):
            pending = {}
            room.pending_dice_discard = pending
        labels = getattr(room, "pending_dice_discard_label", None)
        if not isinstance(labels, dict):
            labels = {}
            room.pending_dice_discard_label = labels
        targets = (only_player,) if only_player else (caster_id, opponent_id)
        ai_id = None
        if room.is_ai_room:
            ai_id = next((pid for pid in room.players if str(pid).startswith("ai-")), None)
        for pid in targets:
            player = room.players.get(pid)
            if player is None:
                continue
            if pending.get(pid) is False:
                room.dice_discard_queue.setdefault(pid, []).append(card_name)
                continue
            if not player.magic_hand:
                pending[pid] = True
                labels[pid] = card_name
                continue
            if pid == ai_id:
                discarded = player.magic_hand.pop(0)
                room.magic_discard.append(discarded)
                await self._emit_card_discarded(room, pid, discarded, "dice")
                await self._emit_hand(player)
                await self._add_log(
                    room,
                    f"第{room.round}回合 · {self._name(room, pid)} 因{card_name}弃置「{discarded.name}」",
                    "magic",
                    {"player": pid, "card": discarded.name,
                     "reason": "dice_discard", "source": card_name},
                )
                pending[pid] = True
                labels[pid] = card_name
            else:
                pending[pid] = False
                labels[pid] = card_name
                if player.socket_id:
                    await self._publisher.emit(
                        "dice_discard_request",
                        {
                            "message": f"{card_name}：请选择一张手牌弃置",
                            "reason": "dice_discard",
                            "card": card_name,
                        },
                        to=player.socket_id,
                    )
        await self._check_dice_discard_complete(room)

    async def _check_dice_discard_complete(self, room: Room) -> None:
        pending = getattr(room, "pending_dice_discard", None)
        if not isinstance(pending, dict) or not pending:
            return
        if all(pending.values()):
            room.pending_dice_discard = {}
            room.pending_dice_discard_label = {}
            room.dice_discard_queue = {}
            await self._publisher.emit("dice_discard_complete", {}, room=room.id)

    async def _advance_dice_discard(self, room: Room, player_id: str) -> None:
        """完成一项后提升同一人的下一项，保留叠加判定的每次义务。"""
        queue = room.dice_discard_queue.get(player_id, [])
        if queue and room.players[player_id].magic_hand:
            source = queue.pop(0)
            room.pending_dice_discard[player_id] = False
            room.pending_dice_discard_label[player_id] = source
            player = room.players[player_id]
            if player.socket_id:
                await self._publisher.emit('dice_discard_request', {
                    'message': f'{source}：请选择一张手牌弃置',
                    'reason': 'dice_discard', 'card': source,
                }, to=player.socket_id)
        else:
            room.dice_discard_queue.pop(player_id, None)
            room.pending_dice_discard[player_id] = True
        await self._check_dice_discard_complete(room)

    @guard_phase_write
    async def dice_discard_choose(self, connection: Connection,
                                  data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        pending = getattr(room, "pending_dice_discard", None)
        if not isinstance(pending, dict) or pending.get(player_id) is not False:
            return {"status": "error", "message": "当前没有等待你弃牌的魔法效果"}
        labels = getattr(room, "pending_dice_discard_label", None)
        source = "命运骰子"
        if isinstance(labels, dict):
            source = labels.get(player_id) or source
        player = room.players[player_id]
        if not player.magic_hand:
            await self._advance_dice_discard(room, player_id)
            await self._sync_each_seat(room)
            return {"status": "success", "message": "没有手牌可弃，已跳过"}
        try:
            index = int(data.get("card_index"))
        except (TypeError, ValueError):
            return {"status": "error", "message": "无效的卡牌位置"}
        if not (0 <= index < len(player.magic_hand)):
            return {"status": "error", "message": "无效的卡牌位置"}
        discarded = player.magic_hand.pop(index)
        room.magic_discard.append(discarded)
        await self._emit_card_discarded(room, player_id, discarded, "dice")
        await self._emit_hand(player)
        await self._add_log(
            room,
            f"第{room.round}回合 · {self._name(room, player_id)} 因{source}弃置「{discarded.name}」",
            "magic",
            {"player": player_id, "card": discarded.name,
             "reason": "dice_discard", "source": source},
        )
        await self._advance_dice_discard(room, player_id)
        await self._sync_each_seat(room)
        return {"status": "success", "message": f"已弃置「{discarded.name}」"}

    @guard_phase_write
    async def papal_discard(self, connection: Connection,
                            data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        existing = self.rooms.get_room(data.get("room_id"))
        if existing is not None and existing.state == RoomState.GAME_OVER:
            return dict(FINISHED_GAME)
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        if room.state == RoomState.GAME_OVER:
            return dict(FINISHED_GAME)
        if not field_rules.field_active(room):
            return {"status": "error", "message": "教皇旨意未生效"}
        if room.current_attacker != player_id:
            return {"status": "error", "message": "还没到你的攻击回合"}
        if self._phase(room) != "battle":
            return {"status": "error", "message": "当前不是战斗阶段"}
        if battle_rules.attacks_forced_zero(room):
            return {"status": "error", "message": "当前效果使攻击次数恒定为0，不能通过弃牌获得攻击次数"}
        player = room.players[player_id]
        if not player.magic_hand:
            return {"status": "error", "message": "没有可弃置的魔法卡"}
        raw_index = data.get("discard_card_index")
        if raw_index is None:
            index = 0
        else:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                return {"status": "error", "message": "无效的弃卡位置"}
            if not (0 <= index < len(player.magic_hand)):
                return {"status": "error", "message": "无效的弃卡位置"}
        discarded = player.magic_hand.pop(index)
        room.magic_discard.append(discarded)
        await self._emit_card_discarded(room, player_id, discarded, "papal")
        room.attacks_remaining += 2
        await self._emit_hand(player)
        await self._publisher.emit(
            "attacks_updated",
            {"current_attacker": room.current_attacker,
             "attacks_remaining": room.attacks_remaining},
            room=room.id,
        )
        await self._add_log(
            room,
            f"第{room.round}回合 · {self._name(room, player_id)} 教皇旨意弃置"
            f"「{discarded.name}」，攻击次数 +2",
            "magic",
            {"player": player_id, "card": discarded.name},
        )
        if player.socket_id:
            await self._publisher.emit(
                "message",
                {"text": f"已弃置「{discarded.name}」：攻击次数 +2，现在可以正常攻击了"},
                to=player.socket_id,
            )
        return {
            "status": "success",
            "discarded": discarded.name,
            "attacks_remaining": room.attacks_remaining,
            "message": f"已弃置「{discarded.name}」，攻击次数 +2",
        }

    @guard_phase_write
    async def remove_field_magic(self, connection: Connection,
                                 data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self._seat(connection, data)
        if room is None:
            return dict(INVALID_SEAT)
        owner = getattr(room, "field_magic_owner", None)
        if room.field_magic and owner is not None and owner != player_id:
            return {"status": "error", "message": "只能移除自己的场地魔法"}
        if room.field_magic:
            await self.tear_down_field(room, player_id)
        return {"status": "success"}


    # ----------------------------------------------------------- round cleanup

    async def clear_board_effects(self, room: Room, player_ids: list[str],
                                  why: str) -> None:
        frames = lifecycle_rules.clear_board_effects(room, player_ids, why)
        for frame, payload in frames:
            await self._publisher.emit(frame, payload, room=room.id)

    async def clear_multiturn_effects(self, room: Room, why: str) -> None:
        had_demon = room.game_effects.get("demon_contract") is not None
        frames = lifecycle_rules.clear_multiturn_effects(room, why)
        if had_demon and not room.game_effects.get("demon_contract"):
            await self._publisher.emit(
                "sacrifice_cancelled", {"reason": "demon_contract"}, room=room.id
            )
        for frame, payload in frames:
            await self._publisher.emit(frame, payload, room=room.id)

    async def _restore_due_shenwei(self, room: Room) -> None:
        before = {pid: p.remaining_ships for pid, p in room.players.items()}
        await self._restore_due_shenwei_inner(room)
        for pid, p in room.players.items():
            await self._mirror_contract_delta(room, pid, p.remaining_ships - before[pid])

    async def _restore_due_shenwei_inner(self, room: Room) -> None:
        entries = room.game_effects.get("excluded_ships") or []
        due = [entry for entry in entries if int(entry.get("return_turn") or 0) <= room.round]
        for entry in due:
            entries.remove(entry)
            owner = room.players.get(entry.get("player"))
            if owner is None:
                continue
            returned = 0
            for ship in entry.get("ships") or []:
                if ship in owner.ships or getattr(ship, "_detached", False):
                    continue
                owner.ships.append(ship)
                owner.remaining_ships += 1
                returned += 1
            if returned:
                await self.notify_treasure(room, returned)
                await self._emit_player_ships(room, entry["player"])
        if not entries:
            room.game_effects.pop("excluded_ships", None)
        if due:
            await self._emit_ships_updated(room)
        holes = room.game_effects.get("shenwei_holes") or []
        for hole in [h for h in holes if int(h.get("return_turn") or 0) <= room.round]:
            holes.remove(hole)
            await self._publisher.emit(
                "shenwei_hole_restored", {"player": hole.get("player")}, room=room.id
            )
        if not holes:
            room.game_effects.pop("shenwei_holes", None)

    async def _recall_lanyu(self, room: Room) -> dict[str, Any] | None:
        before = {pid: p.remaining_ships for pid, p in room.players.items()}
        result = await self._recall_lanyu_inner(room)
        for pid, p in room.players.items():
            await self._mirror_contract_delta(room, pid, p.remaining_ships - before[pid])
        return result

    async def _recall_lanyu_inner(self, room: Room) -> dict[str, Any] | None:
        lanyu = room.game_effects.pop("lanyu_temp_ships", None)
        if not lanyu:
            return None
        changed: dict[str, int] = {}
        for player_id, ship_list in lanyu.items():
            player = room.players.get(player_id)
            if player is None:
                continue
            removed = 0
            for ship in ship_list:
                if ship not in player.ships:
                    continue
                if not is_ship_alive(player, ship):
                    continue
                player.ships.remove(ship)
                player.remaining_ships -= 1
                removed += 1
            if removed:
                changed[player_id] = removed
                await self._emit_player_ships(room, player_id)
        if not changed:
            return None
        await self._emit_ships_updated(room)
        for player_id, count in changed.items():
            await self._publisher.emit(
                "lanyu_recalled", {"player": player_id, "count": count}, room=room.id
            )
            await self._add_log(
                room,
                f"第{room.round}回合 · {self._name(room, player_id)} 的【滥竽充数】"
                f"临时战舰已收回({count}艘)",
                "magic",
                {"player": player_id, "card": "滥竽充数", "count": count},
            )
        for player_id in changed:
            player = room.players[player_id]
            if player.remaining_ships <= 0 and len(player.ships) > 0:
                opponent_id = room.opponent_of(player_id)
                if opponent_id:
                    await self.finish(
                        room, opponent_id, player_id,
                        reason="滥竽充数临时战舰已收回，无战舰可用",
                    )
                    return {"game_over": True, "winner": opponent_id,
                            "reason": "滥竽充数临时战舰已收回，无战舰可用"}
        return None

    async def on_new_big_round(self, room: Room) -> dict[str, Any] | None:
        await self._restore_due_shenwei(room)
        recalled = await self._recall_lanyu(room)
        if recalled and recalled.get("game_over"):
            return recalled

        for player_id, player in room.players.items():
            thawed = False
            for ship in player.ships:
                if getattr(ship, "frozen", None) and int(ship.frozen) < room.round:
                    ship.frozen = None
                    thawed = True
            if thawed:
                await self._emit_player_ships(room, player_id)
            cleared_trap = False
            for ship in player.ships:
                if getattr(ship, "trap", False):
                    ship.trap = False
                    cleared_trap = True
            if cleared_trap:
                await self._emit_player_ships(room, player_id)
                await self._publisher.emit(
                    "trap_expired", {"player": player_id}, room=room.id
                )

        area = room.game_effects.get("frozen_area")
        if isinstance(area, dict) and int(area.get("until_round") or 0) < room.round:
            room.game_effects.pop("frozen_area", None)
            await self._publisher.emit("frozen_area", {"cleared": True}, room=room.id)

        room.game_effects.pop("last_chance", None)
        room.game_effects.pop("zero_attacks_round", None)
        if room.game_effects.pop("last_stand_cells", None):
            room.game_effects.pop("last_stand_owner", None)
            await self._publisher.emit(
                "last_stand_cells", {"cells": [], "owner": None}, room=room.id
            )

        check = room.game_effects.get("reinforcement_check")
        if isinstance(check, dict):
            if room.round > int(check.get("activated_round", room.round - 1)) + 1:
                check["remaining_turns"] = int(check.get("remaining_turns") or 0) - 1
            remaining = int(check.get("remaining_turns") or 0)
            await self._publisher.emit(
                "reinforcement_turn_updated", {"remaining_turns": remaining}, room=room.id
            )
            if remaining <= 0:
                ids = list(room.players)
                if len(ids) >= 2:
                    first, second = ids[0], ids[1]
                    first_ships = int(room.players[first].remaining_ships)
                    second_ships = int(room.players[second].remaining_ships)
                    winner = None
                    if first_ships < second_ships:
                        winner = first
                    elif second_ships < first_ships:
                        winner = second
                    if winner is None:
                        room.game_effects.pop("reinforcement_check", None)
                        await self._publisher.emit(
                            "message",
                            {"text": "极限增援结算时双方船数相同，无人获胜，效果结束"},
                            room=room.id,
                        )
                    else:
                        loser = second if winner == first else first
                        await self.finish(room, winner, loser, reason="极限增援生效")
                        return {"game_over": True, "winner": winner,
                                "reason": "极限增援生效，船数少的一方获胜"}

        heart = room.game_effects.get("holy_heart")
        if isinstance(heart, dict):
            heart["remaining_turns"] = int(heart.get("remaining_turns") or 0) - 1
            remaining = int(heart.get("remaining_turns") or 0)
            await self._publisher.emit(
                "holy_heart_turn_updated", {"remaining_turns": remaining}, room=room.id
            )
            if remaining <= 0:
                winner = heart.get("caster")
                loser = next((pid for pid in room.players if pid != winner), None)
                if winner and loser and heart.get('no_damage'):
                    await self.finish(room, winner, loser, reason="无暇圣心结算")
                    return {"game_over": True, "winner": winner,
                            "reason": "无暇圣心笼罩大地 愿这方世界不再有战争"}
                room.game_effects.pop('holy_heart', None)

        for player_id, player in list(room.players.items()):
            # 先读宣言值（round 租约还没过期），大回合边界统一 expire 掉。
            prediction = int(getattr(player.effect_flags, "prediction", 0) or 0)
            if prediction <= 0:
                continue
            saved = room.game_effects.get(f"prediction_initial_{player_id}")
            if isinstance(saved, dict):
                diff = int(saved.get('ships') or 0) - int(player.remaining_ships or 0)
                if diff == prediction:
                    await self.begin_shenji_redeploy(
                        room, player_id, prediction,
                        already_sunken_ids=saved.get("sunken_ids"),
                    )
                    room.game_effects.pop(f"prediction_initial_{player_id}", None)

        # #38：大回合边界清掉 round 与 turn 租约，再投影回 effect_flags。
        effects.expire(room, effects.BOUNDARY_ROUND)
        effects.project_effect_flags(room)
        await self._emit_active_effects(room)
        return None

    async def on_turn_switch(self, room: Room) -> None:
        """小回合边界：只过期 turn 租约（round/match 的跨回合效果保留）。"""

        effects.expire(room, effects.BOUNDARY_TURN)
        effects.project_effect_flags(room)
        await self._emit_active_effects(room)

    async def begin_shenji_redeploy(self, room: Room, player_id: str, count: int,
                                    already_sunken_ids: list[int] | None = None) -> int:
        player = room.players.get(player_id)
        if player is None:
            return 0
        sunken = list(player.sunken_ships or [])
        if already_sunken_ids is None:
            fresh = sunken[-int(count):] if count else []
        else:
            before = set(already_sunken_ids)
            fresh = [ship for ship in sunken if id(ship) not in before]
        n = min(int(count), len(fresh))
        if n <= 0:
            return 0
        chosen = fresh[:n]
        original_cells = [[pos.x, pos.y] for ship in chosen for pos in ship.positions]
        room.game_effects["shenji_redeploy_cells"] = original_cells
        room.game_effects["shenji_redeploy_ships"] = chosen
        await self._start_placement(room, player_id, "shenji_redeploy", n)
        return n

    async def place_field(self, room: Room, card: MagicCard) -> None:
        old = field_rules.place_field_magic(room, room.current_attacker or "", card)
        await self._publisher.emit(
            "field_magic_updated",
            {"player_id": room.field_magic_owner, "card": card_payload(card)},
            room=room.id,
        )
        if old is not None and getattr(old, "name", None) != card.name:
            await self._recalc_attacks(room)
            # field.place_field_magic 把旧场地塞进弃牌堆（domain 里不发事件）：
            # 弃牌事件统一由拥有这次调用的服务层补，且每张牌只发一次。
            await self._emit_card_discarded(
                room, room.field_magic_owner, old, "field_replaced"
            )
        # #37：场地已落位（顶替旧场地也已清掉其标记），此时才发 FIELD_ENTERED。
        await hooks.emit(
            room,
            hooks.FIELD_ENTERED,
            {
                "room_id": room.id,
                "player_id": room.field_magic_owner,
                "card": card.name,
                "previous": getattr(old, "name", None),
            },
        )

    async def tear_down_field(self, room: Room, caster_id: str) -> Any:
        torn = field_rules.tear_down_field_magic(room, caster_id)
        if torn is not None:
            await self._recalc_attacks(room)
            await self._publisher.emit(
                "field_magic_updated", {"player_id": caster_id, "card": None},
                room=room.id,
            )
            if room.state == RoomState.ATTACKING:
                await self._publisher.emit(
                    "attacks_updated",
                    {"current_attacker": room.current_attacker,
                     "attacks_remaining": room.attacks_remaining},
                    room=room.id,
                )
            # field.tear_down_field_magic 已把这张场地移入弃牌堆（domain 不发事件）。
            await self._emit_card_discarded(
                room, caster_id, torn, "field_teardown"
            )
            # #37：场地确实离场（已被移入弃牌堆、标记已清）之后发 FIELD_LEFT。
            await hooks.emit(
                room,
                hooks.FIELD_LEFT,
                {
                    "room_id": room.id,
                    "player_id": caster_id,
                    "card": getattr(torn, "name", None),
                },
            )
        return torn

    async def _recalc_attacks(self, room: Room) -> None:
        battle_rules.recalc_attacker_attacks(room)

    async def _emit_board_attacks(self, room: Room) -> None:
        for player_id, player in room.players.items():
            opponent_id = room.opponent_of(player_id)
            opponent = room.players.get(opponent_id) if opponent_id else None

            def cells(owner):
                if owner is None:
                    return []
                return [
                    {"x": a.x, "y": a.y, "hit": bool(a.hit),
                     "ship_sunk": bool(getattr(a, "ship_sunk", False))}
                    for a in (owner.attacks or [])
                ]

            if player.socket_id:
                await self._publisher.emit(
                    "board_attacks_updated",
                    {"my_attacks": cells(player), "opponent_attacks": cells(opponent)},
                    to=player.socket_id,
                )

    async def _reveal_to(self, room: Room, player_id: str,
                         positions: list[Position], kind: str | None = None) -> None:
        player = room.players.get(player_id)
        if player is None or not positions:
            return
        payload = []
        for position in positions:
            x, y = int(position.x), int(position.y)
            if not any(p.x == x and p.y == y for p in player.revealed_positions):
                player.revealed_positions.append(Position(x=x, y=y))
            payload.append({"x": x, "y": y})
        if payload and player.socket_id:
            await self._publisher.emit(
                "revealed_positions", {"positions": payload, "kind": kind},
                to=player.socket_id,
            )

    async def _ai_place_board(self, room: Room, player_id: str) -> bool:
        if self.ai_place_hook is None:
            return False
        return bool(await self._maybe_await(self.ai_place_hook(room, player_id)))

    async def _refresh_replay_ships(self, room: Room) -> None:
        replay_rules.refresh_ships(room)

    async def _ai_place_any(self, room: Room) -> None:
        for pid in list(room.players):
            if (
                room.is_ai_room
                and str(pid).startswith("ai-")
                and not room.players[pid].ships
            ):
                await self._ai_place_board(room, pid)


    # ------------------------------------------------------------------ debug

    async def debug_add_card(self, room_id: str | None, player_id: str | None,
                             card_name: str) -> dict:
        from ..domain.magic.cards import card_by_name

        room = self.rooms.get_room(room_id)
        if room is None or not player_id or player_id not in room.players:
            return {"status": "error", "message": "无效的房间或玩家"}
        card = card_by_name(card_name)
        if card is None:
            return {"status": "error", "message": f"未找到名为 {card_name} 的魔法卡"}
        room.players[player_id].magic_hand.append(card)
        await self._emit_hand(room.players[player_id])
        return {"status": "success", "message": f"已添加 {card_name}"}

    async def debug_add_all_cards(self, room_id: str | None,
                                  player_id: str | None) -> dict:
        from ..domain.magic.cards import MAGIC_CARDS

        room = self.rooms.get_room(room_id)
        if room is None or not player_id or player_id not in room.players:
            return {"status": "error", "message": "无效的房间或玩家"}
        room.players[player_id].magic_hand = list(MAGIC_CARDS)
        await self._emit_hand(room.players[player_id])
        return {"status": "success", "message": f"已添加 {len(MAGIC_CARDS)} 张魔法卡到手牌"}

    async def debug_clear_all_effects(self, room_id: str | None) -> dict:
        """test_clear_all_effects: wipe every effect and hand, then re-sync hands.

        The legacy event deliberately wiped the hands too ("手上有什么卡" must be
        fully controllable in E2E) and pushed a per-seat hand_updated.
        """

        room = self.rooms.get_room(room_id)
        if room is None:
            return {"status": "error", "message": "无效的房间"}
        room.game_effects = {}
        room.field_magic = None
        room.field_magic_owner = None
        room.last_attack = None
        magic_temps.clear(room)
        for player in room.players.values():
            for ship in player.ships:
                ship.invincible = False
                ship.shield = False
                ship.trap = False
            player.sunken_ships = []
            player.damage_dealt_this_turn = 0
            player.magic_hand = []
            await self._emit_hand(player)
        # #38：整对象重置统一走 reset_all（match 边界清租约 + 投影）。
        effects.reset_all(room)
        return {"status": "success", "message": "已清除所有魔法效果"}

    def debug_get_magic_cards_list(self) -> dict:
        """test_get_magic_cards_list: the frozen card table for E2E / collection."""

        return {
            "status": "success",
            "magic_cards": [card.to_payload() for card in MAGIC_CARDS],
        }

    async def debug_get_multi_area_chain(self, room_id: str | None,
                                         player_id: str | None) -> dict:
        """test_get_multi_area_chain: a public chain payload with two areas.

        Built through the real constructors (ChainItem + sanitize_targets +
        public chain payload) instead of hand-written dicts, and the room's
        chain stack is restored afterwards so a debug probe never disturbs a
        live match.
        """

        room = self.rooms.get_room(room_id)
        if room is None or not player_id or player_id not in room.players:
            return {"status": "error", "message": "无效的房间或玩家"}
        caster_id = str(player_id)
        opponent_id = room.opponent_of(caster_id)
        cases = (
            (caster_id, "轰炸", {"target_line": {"type": "row", "index": 4}}),
            (caster_id, "克苏鲁之眼",
             {"target_area": {"x1": 2, "y1": 2, "x2": 2, "y2": 2}}),
        )
        items: list[ChainItem] = []
        for cid, name, targets in cases:
            card = card_by_name(name)
            if card is None:
                return {"status": "error", "message": f"卡表里没有 {name}"}
            normalised, error = sanitize_targets(dict(targets), name)
            if error:
                return {"status": "error", "message": error}
            items.append(ChainItem(cid, card, normalised, self.clock()))
        saved = room.chain
        try:
            room.chain = items
            payload = _spectate_chain_payload(room)
        finally:
            room.chain = saved
        return {
            "status": "success",
            "chain": payload,
            "opponent_id": opponent_id,
        }

    @staticmethod
    def _name(room: Room, player_id: str) -> str:
        player = room.players.get(player_id)
        return (player.name or player_id) if player else player_id


def _json_temp(value: Any) -> Any:
    if isinstance(value, MagicCard):
        return card_payload(value)
    if isinstance(value, PlayerShip):
        return {"positions": [{"x": p.x, "y": p.y} for p in value.positions]}
    if isinstance(value, Position):
        return {"x": value.x, "y": value.y}
    if isinstance(value, dict):
        return {key: _json_temp(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_temp(item) for item in value]
    return value



# --------------------------------------------------------------------- helpers


def sanitize_targets(targets: Any, card_name: str) -> tuple[dict[str, Any], str | None]:
    """Validate/normalise target_area, target_line and target_cells (legacy copy)."""

    if not isinstance(targets, dict):
        return {}, None

    area = targets.get("target_area")
    if isinstance(area, dict):
        for key in ("x1", "y1", "x2", "y2"):
            if key not in area:
                return targets, "目标区域参数缺失"
            value = target_rules.strict_int(area[key])
            if value is None:
                return targets, "目标区域坐标非法"
            if not (0 <= value <= 5):
                return targets, "目标区域坐标超出棋盘范围"
            area[key] = value

    line = targets.get("target_line")
    if isinstance(line, dict):
        if line.get("type") not in ("row", "col"):
            return targets, "目标行列参数非法"
        index = target_rules.strict_int(line.get("index"))
        if index is None:
            return targets, "目标行列坐标非法"
        if not (0 <= index <= 5):
            return targets, "目标行列坐标超出棋盘范围"
        line["index"] = index

    for key in ("target_cells", "selected_cells"):
        cells = targets.get(key)
        if isinstance(cells, list):
            for cell in cells:
                if not isinstance(cell, dict):
                    return targets, "目标格子格式错误"
                x = target_rules.strict_int(cell.get("x"))
                y = target_rules.strict_int(cell.get("y"))
                if x is None or y is None:
                    return targets, "目标格子坐标非法"
                if not (0 <= x <= 5 and 0 <= y <= 5):
                    return targets, "目标格子坐标超出棋盘范围"
                cell["x"], cell["y"] = x, y

    declared = AREA_TARGET_BOARDS.get(card_name)
    if declared is not None:
        board = targets.get("board")
        if declared in ("self", "opponent"):
            if board is not None and board != declared:
                return targets, "目标棋盘归属与卡牌不一致"
            targets["board"] = declared
        elif declared == "choice" and board not in ("self", "opponent"):
            return targets, "请选择目标棋盘（自己或对方）"
    shape_error = target_rules.validate(card_name, targets)
    if shape_error:
        return targets, shape_error
    return targets, None


__all__ = [
    "AREA_TARGET_BOARDS",
    "MagicService",
    "SELECTION_TARGET_KEYS",
    "sanitize_targets",
]
