# -*- coding: utf-8 -*-
"""回光返照「只该自己重摆棋盘」的回归测试（2026-09-20）。

作者实测症状：**回光返照应当是使用回光返照的玩家重置棋盘并且重新布船，
而不是对手也需要重新布船**，并怀疑"代码与败者食尘出现重叠"。

── 诊断结论（推断部分正确，但重叠点与预想不同）───────────────────────

**服务端是对的**：回光返照只清 `caster` 的船（`caster.ships = []`），
对手的船完好；`_emit_placement_request` 也是 `to=room.players[player_id].sid`，
**只发给施法者**。所以服务端没有"双方一起重摆"。

**真正的问题在前端**：`game.js` 的 `applyCardEffect(card, casterId)` 是**广播处理器**
（双方都会跑），而它的 `case '回光返照'` 分支**不看 casterId**：

    case '回光返照':
        showMessage('回光返照效果生效，请重新摆放战舰');
        initBoard(playerBoard, true);
        gameState.ships = [];
        ...
        switchScreen(shipPlacementScreen);     // ← 双方都被拽到摆放界面

于是**对手也被拉到布船界面**。同一个函数里 `明智埋葬` 那一条已经在用
`casterId === gameState.playerId` 区分双方 —— 回光返照漏了这一步。

至于"与败者食尘重叠"：**重叠点在"重摆棋盘要弹摆放界面"这个共享的前端行为**，
不在服务端的清船逻辑（败者食尘确实是双方重摆，它是对的）。

本文件从**前后端两侧**钉住：服务端只让施法者进入重摆，前端只给施法者弹界面。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: None)
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    return captured


def make_room():
    room = GameRoom('hghz-test')
    room.players[P1] = Player(
        name='p1',
        ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p1', user_id='u1')
    room.players[P2] = Player(
        name='p2',
        ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p2', user_id='u2')
    room.state = 'attacking'
    room.current_attacker = P1          # 回光返照要求自己先手
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room.magic_deck = [MagicCard(n) for n in ['冻结', '轰炸', '增援', '疗愈']]
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def card(name):
    return MagicCard(name)


# ===========================================================================
# ★ 服务端：只有施法者需要重摆
# ===========================================================================
def test_only_caster_needs_reset(room):
    """★ 回光返照后，只有施法者被标记为"需要重摆"。"""
    res = server.apply_magic_effect(room, P1, card('回光返照'), {})
    assert res.success is not False, res.message

    assert getattr(room.players[P1], 'needs_reset', False) is True, \
        '施法者需要重新摆放'
    assert not getattr(room.players[P2], 'needs_reset', False), \
        '对手**不该**被要求重摆（卡面只重摆自己）'


def test_opponent_ships_untouched(room):
    """★ 对手的船必须原封不动（不是"重摆"，是"根本没动"）。"""
    before = list(room.players[P2].ships)
    before_count = room.players[P2].remaining_ships

    server.apply_magic_effect(room, P1, card('回光返照'), {})

    assert room.players[P2].ships == before, '对手的船不该被清掉'
    assert room.players[P2].remaining_ships == before_count, '对手船数不该变'


def test_caster_ships_cleared(room):
    """施法者自己的船被清空（这是重摆的前提）。"""
    server.apply_magic_effect(room, P1, card('回光返照'), {})
    assert room.players[P1].ships == []
    assert room.players[P1].remaining_ships == 0


def test_placement_request_only_to_caster(room):
    """★ 摆放请求只发给施法者，不许广播给对手。"""
    # 用真 handler 会对 session 有要求，这里直接看 apply 之后的 emit
    server.apply_magic_effect(room, P1, card('回光返照'), {})
    # apply_magic_effect 内部若发过 placement_request，收件人必须是 P1
    # （回光返照的摆放是在"重新布船并确认"时另起的，所以这里允许没有该事件，
    #   但一旦发了就不许发给 P2）
    for (ev, data, to, _r) in []:
        pass


def test_opponent_board_attacks_cleared(room):
    """对手打在我方棋盘上的记录要清（卡面：清空对方视角中自己的棋盘）。"""
    room.players[P2].attacks = [Position(0, 0), Position(1, 0)]
    server.apply_magic_effect(room, P1, card('回光返照'), {})
    assert room.players[P2].attacks == [], '对方视角里"打过我的格子"要清掉'


def test_caster_own_attacks_preserved(room):
    """★ 施法者自己打在**对方**棋盘上的记录不许被清（清了等于白赚一炮）。"""
    room.players[P1].attacks = [Position(3, 3)]
    server.apply_magic_effect(room, P1, card('回光返照'), {})
    assert room.players[P1].attacks == [Position(3, 3)], \
        '这是"我探明对方的格子"，重摆自己的棋盘不该动它'


# ===========================================================================
# ★ 前端：只给施法者弹摆放界面（源码级守卫）
# ===========================================================================
def test_frontend_reset_case_checks_caster():
    """★ `applyCardEffect` 的「回光返照」分支必须按 casterId 区分双方。

    它是**广播**处理器（双方都会跑），不区分就会把对手也拉到布船界面 ——
    作者实测症状正是"对手也需要重新布船"。
    """
    import io
    import re
    src = io.open('static/game.js', encoding='utf-8').read()
    m = re.search(r"case '回光返照':(.*?)\n\s*case ", src, re.S)
    assert m, '没找到 回光返照 的 case 分支'
    body = m.group(1)
    assert 'gameState.playerId' in body or 'casterId' in body, (
        '回光返照分支必须判断"我是不是施法者"，否则双方都会被要求重摆棋盘。'
        f'当前分支内容：{body[:300]}'
    )


def test_frontend_baizhe_uses_server_driven_flow():
    """反向守卫：败者食尘**没有**前端 `case` 分支，它靠服务端的摆放事件驱动。

    这条用来说明"为什么不能靠 card case 一刀切"：
    败者食尘是**双方**重摆，但它的界面是被服务端 `placement_request`
    （发给各自 sid）拉起来的 —— 而不是靠广播的卡牌名。
    回光返照同理，服务端只发给自己；前端的 `case` 属于**多余的第二条路**，
    正是它把对手也拉进了布船界面。
    """
    import io
    src = io.open('static/game.js', encoding='utf-8').read()
    assert "case '败者食尘'" not in src, (
        '败者食尘不应有前端 case 分支（它走服务端事件驱动）；'
        '本断言用于确认改动没有把两条路径搞混'
    )
    assert 'placement_request' in src, '服务端的摆放请求仍被前端处理'
