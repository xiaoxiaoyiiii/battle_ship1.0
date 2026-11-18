"""P1-1 败者食尘：核实“先清盘后校验 / 文案张冠李戴 / double_command 可达性”。

这些测试记录现入口的真实行为。审查说的“函数内先清盘，再因非准备阶段失败并退卡，
且报错写成另一张卡”在 483e459 的 polar_reversal 中不存在（该函数自引入起就无失败分支）。
因此本文件不是“修复前应当失败”的回归，而是对外部怀疑的复现/证伪。
"""
from __future__ import annotations

import asyncio

from battleship.domain.magic.cards import card_by_name
from battleship.domain.magic.chain import ChainItem
from battleship.domain.magic.rules import can_play_magic_card, evaluate_cast
from battleship.domain.mystery_tech import effects as tech
from battleship.domain.room import RoomPhase, RoomState
from battleship.services.rooms import Connection
from test_mystery_tech_flow import stack


CARD = "败者食尘"
SPEED1_ONLY_PREP = "速阶1的魔法卡只能在自己的准备阶段使用"


def _board_fingerprint(room):
    return {
        "state": getattr(room.state, "value", room.state),
        "ships": {
            pid: [(p.x, p.y) for ship in player.ships for p in ship.positions]
            for pid, player in room.players.items()
        },
        "remaining": {pid: player.remaining_ships for pid, player in room.players.items()},
        "polar": bool(getattr(room, "polar_reversal_applied", False)),
    }


def _ready_attacking(room, *, attacker: str, phase: RoomPhase):
    room.state = RoomState.ATTACKING
    room.current_attacker = attacker
    room.current_phase = phase
    room.round = 1
    room.attacks_remaining = 3
    for player in room.players.values():
        player.needs_reset = False


def test_polar_reversal_is_speed_one():
    card = card_by_name(CARD)
    assert int(card.speed) == 1
    assert card.name == CARD


def test_normal_entry_rejects_battle_without_clearing_board():
    async def run():
        r, rooms, g, magic, battle, pub, clock = stack()
        try:
            _ready_attacking(r, attacker="a", phase=RoomPhase.BATTLE)
            card = card_by_name(CARD)
            r.players["a"].magic_hand = [card]
            before = _board_fingerprint(r)
            assert evaluate_cast(r, "a", card) == SPEED1_ONLY_PREP
            ack = await magic.use_magic_card(
                Connection(sid="a", user_id="a"),
                {"room_id": r.id, "player_id": "a", "card": card.to_payload()},
            )
            assert ack["status"] == "error"
            assert ack["message"] == SPEED1_ONLY_PREP
            assert CARD not in (ack.get("message") or "")
            assert "伊甸园" not in (ack.get("message") or "")
            assert "回光返照" not in (ack.get("message") or "")
            assert "灵气复苏" not in (ack.get("message") or "")
            assert r.players["a"].magic_hand == [card]
            assert _board_fingerprint(r) == before
        finally:
            await magic.stop()

    asyncio.run(run())


def test_normal_entry_rejects_end_phase_and_opponent_turn_without_clearing_board():
    async def run():
        r, rooms, g, magic, battle, pub, clock = stack()
        try:
            card = card_by_name(CARD)
            cases = (
                ("a", RoomPhase.END, SPEED1_ONLY_PREP),
                ("b", RoomPhase.PREPARATION, "速阶1的魔法卡只能在自己的回合使用（现在不是你的回合）"),
                ("b", RoomPhase.BATTLE, "速阶1的魔法卡只能在自己的回合使用（现在不是你的回合）"),
            )
            for attacker, phase, message in cases:
                _ready_attacking(r, attacker=attacker, phase=phase)
                r.players["a"].magic_hand = [card]
                before = _board_fingerprint(r)
                assert evaluate_cast(r, "a", card) == message
                ack = await magic.use_magic_card(
                    Connection(sid="a", user_id="a"),
                    {"room_id": r.id, "player_id": "a", "card": card.to_payload()},
                )
                assert ack == {"status": "error", "message": message}
                assert r.players["a"].magic_hand == [card]
                assert _board_fingerprint(r) == before
        finally:
            await magic.stop()

    asyncio.run(run())


def test_own_preparation_is_a_legal_normal_entry():
    r, rooms, g, magic, battle, pub, clock = stack()
    _ready_attacking(r, attacker="a", phase=RoomPhase.PREPARATION)
    card = card_by_name(CARD)
    r.players["a"].magic_hand = [card]
    assert evaluate_cast(r, "a", card) is None
    assert can_play_magic_card(r, "a", card)


def test_double_command_can_reach_clear_from_battle_via_use_magic_card():
    """双重指令按设计绕过速阶限制；败者食尘没有单独卡面时点，战斗阶段可走到清盘。"""
    async def run():
        r, rooms, g, magic, battle, pub, clock = stack()
        try:
            _ready_attacking(r, attacker="a", phase=RoomPhase.BATTLE)
            tech.apply(r, "a", "double_command", g.rng)
            card = card_by_name(CARD)
            r.players["a"].magic_hand = [card]
            assert evaluate_cast(r, "a", card) is None
            before_ships = _board_fingerprint(r)["ships"]
            assert before_ships["a"] and before_ships["b"]
            ack = await magic.use_magic_card(
                Connection(sid="a", user_id="a"),
                {"room_id": r.id, "player_id": "a", "card": card.to_payload()},
            )
            assert ack["status"] == "success", ack
            if r.chain:
                await magic.resolve_chain(r)
            assert r.state == RoomState.PLACING_SHIPS
            assert r.polar_reversal_applied is True
            assert all(player.needs_reset for player in r.players.values())
            assert all(player.ships == [] for player in r.players.values())
            assert CARD not in [c.name for c in r.players["a"].magic_hand]
        finally:
            await magic.stop()

    asyncio.run(run())


def test_double_command_can_chain_polar_reversal_on_opponent_battle_turn():
    async def run():
        r, rooms, g, magic, battle, pub, clock = stack()
        try:
            _ready_attacking(r, attacker="b", phase=RoomPhase.BATTLE)
            tech.apply(r, "a", "double_command", g.rng)
            card = card_by_name(CARD)
            r.players["a"].magic_hand = [card]
            r.chain = [ChainItem("b", card_by_name("看破！"))]
            r.chain_waiting = True
            r.chain_window = "a"
            ack = await magic.chain_response(
                Connection(sid="a", user_id="a"),
                {
                    "room_id": r.id,
                    "player_id": "a",
                    "chain": True,
                    "card": card.to_payload(),
                },
            )
            assert ack["status"] == "success", ack
            if r.chain:
                await magic.resolve_chain(r)
            assert r.state == RoomState.PLACING_SHIPS
            assert r.polar_reversal_applied is True
            assert all(player.ships == [] for player in r.players.values())
        finally:
            await magic.stop()

    asyncio.run(run())
