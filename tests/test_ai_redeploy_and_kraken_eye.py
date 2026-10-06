# -*- coding: utf-8 -*-
"""「大师 AI 当施法者」时**会拖住对手**的两类卡的回归测试（2026-09-22 批）。

对应作者实测报的两条：

  ── Bug A：重摆类卡把真人拖进布船屏（回光返照）──────────────────────
      原话：「它突然使用了回光返照加灵气复苏，直接把我需要重新摆船的界面
             卡没了，我自己棋盘上甚至一个船都没有了」

      根因：`回光返照` 里 `emit('reset_gameboard', …, to=caster.sid)` 的
      `caster.sid` 在人机房里是 `'ai-'+room_id` —— **没有这条 socket 连接**，
      事件石沉大海；可 `room.state` 已经变成 `placing_ships` 了。
      AI 的自救在 `_ai_master_turn` 的后台循环里，是**异步**的 ——
      中间那段窗口里真人既不在对局里、也没收到任何事件。

  ── Bug B：克苏鲁之眼把"自己给不出坐标"说成"你没选" ─────────────────
      原话：「通过之后都不给我选自己船暴露的机会，就直接结束了选区
             并且弹出克苏鲁之眼生效失败：没有选择一艘船暴露」

      根因：这张卡结算时先要施法者给出**自己那一艘船的坐标**
      （`_pick_cell_from_target`），而 AI 给不出 → `success=False` +
      「请选择一艘自己的战舰」→ `_refund_card_to_hand` 把牌退回，
      真人那边看到的就是「克苏鲁之眼未发动：请选择一艘自己的战舰」。

本文件钉住的核心契约只有一句：
**大师 AI 打出的卡，不许把房间留在"等对手做一件他不知道要做的事"的状态里。**
"""
import inspect
import re

import pytest

import server
from server import Player, PlayerShip, Position


HUMAN = 'human-0'


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def events(monkeypatch):
    """录下所有 emit；并掐掉后台任务与连锁超时定时器（无头环境没有它们）。"""
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: None)
    monkeypatch.setattr(server.socketio, 'emit', lambda *a, **k: None)
    monkeypatch.setattr(server, '_maybe_run_ai_turn', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    return captured


def _build_room(hand, difficulty='master'):
    """两座位人机房：AI 位（`'ai-'+room_id`）+ 真人位 `human-0`，双方各 6 艘船。"""
    room_id = server.room_manager.create_ai_room(HUMAN, 'P2', None, difficulty)
    room = server.room_manager.get_room(room_id)
    room.players[HUMAN] = Player(
        name='P2', ships=[], attacks=[], remaining_ships=0,
        user_id=None, sid=HUMAN)
    room.init_player_magic(HUMAN, server.magic_cards)
    ai_id = server._ai_player_id(room)

    for pid in room.players:
        p = room.players[pid]
        p.ships = [PlayerShip(positions=[Position(x=i, y=0)], hits=[])
                   for i in range(6)]
        p.remaining_ships = 6
        p.max_ships = 6
        p.attacks = []
        p.revealed_positions = []
        p.magic_hand = []

    room.state = 'attacking'
    room.current_attacker = ai_id
    room.current_phase = 'battle'
    room.attack_order = [ai_id, HUMAN]      # AI 先手（回光返照的前置）
    room.round = 3
    room.attacks_remaining = 6
    # 牌堆给几张无害的，避免抽牌类效果撞到空牌堆
    room.magic_deck = [server.MagicCard(n) for n in
                       ['冻结', '轰炸', '增援', '疗愈', '看破！', '无中生有']]
    room.players[ai_id].magic_hand = [server.MagicCard(n) for n in hand]
    return room, ai_id


@pytest.fixture
def master_room():
    """默认手牌 = 回光返照；用完即删房。"""
    room, ai_id = _build_room(['回光返照'])
    try:
        yield room, ai_id
    finally:
        server.room_manager.delete_room(room.id)


def _play(room, pid, name, targets=None):
    """走**玩家真正在用的入口**出牌（不是直接调 apply_magic_effect）。"""
    card = server.MagicCard(name)
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': pid,
        'card': {'name': card.name, 'speed': card.speed, 'type': card.type,
                 'description': getattr(card, 'description', '')},
        'targets': targets or {},
    })


def _resets_to(events, sid):
    return [d for (ev, d, to, _r) in events
            if ev == 'reset_gameboard' and to == sid]


def _refresh(room):
    return server.room_manager.get_room(room.id)


# ===========================================================================
# A. ★ 重摆类卡：AI 当施法者时房间不许停在 placing_ships
# ===========================================================================
def test_ai_caster_huiguang_does_not_leave_room_in_placing_ships(master_room, events):
    """★★ 核心守卫：大师 AI 打出「回光返照」后，房间**不许**停在 `placing_ships`。

    这是作者实测那条的根因形状：AI 的 `sid` 是 `'ai-'+room_id`，`reset_gameboard`
    发给它等于石沉大海，可 `room.state` 已经是 `placing_ships` ——
    房间于是停在"等施法者摆放"，而施法者是一个没有 UI 的座位。
    真人在那段窗口里既没收到任何事件、也已经不在对局里。

    修法：AI 没有 UI 要等，**当场**把船摆好（走 `handle_place_ships` 同一入口），
    让 `room.state` 在同一个服务端调用里就回到正常。
    """
    room, ai_id = master_room
    resp = _play(room, ai_id, '回光返照')
    assert resp.get('status') == 'success', f'回光返照应当能打出：{resp}'

    room = _refresh(room)
    assert room.state != 'placing_ships', (
        f'★ AI 当施法者时房间不许停在 placing_ships（实际 {room.state}）——'
        f' 真人会卡在既不在对局、又收不到任何事件的窗口里')
    assert room.state == 'attacking', f'应立刻回到 attacking，实际 {room.state}'
    assert len(room.players[ai_id].ships) == 6, 'AI 应已就地摆好 6 艘船'


def test_ai_caster_huiguang_does_not_ask_opponent_to_replace(master_room, events):
    """★★ 对手（真人）不该被要求重新摆船，也不该收到任何 reset_gameboard。

    回光返照只清**施法者自己**的棋盘。AI 当施法者时，它自己的棋盘由服务端
    就地摆好 —— 真人那边一艘船都没动过，所以**一份 `reset_gameboard` 都不该收到**
    （收到就等于把他拽进布船屏，而他的棋盘从没被清空）。
    """
    room, ai_id = master_room
    play_before = len(room.players[HUMAN].ships)
    _play(room, ai_id, '回光返照')
    room = _refresh(room)

    assert _resets_to(events, HUMAN) == [], (
        f'真人**不该**收到 reset_gameboard，实际收到 '
        f'{[d for d in _resets_to(events, HUMAN)]}')
    assert len(room.players[HUMAN].ships) == play_before, (
        '真人的棋盘不该被动过（回光返照只清施法者自己）')
    assert room.players[HUMAN].max_ships == 6, '真人的船数上限不该被动'




def test_ai_caster_baizhe_never_randomizes_human_board():
    """双方重摆卡不能由大师循环替真人自动随机摆船。

    真人收到 reset_gameboard 后必须停在可操作的布船界面；只有 AI 那一侧
    可以由服务端即时补摆。旧代码把 `_ai_place_board` 也调用到 opponent，
    造成真人的棋盘被静默随机填满，前端随后又被状态帧覆盖，表现为界面一闪而过。
    """
    room, ai_id = _build_room(['败者食尘'])
    try:
        resp = _play(room, ai_id, '败者食尘')
        assert resp.get('status') == 'success', resp
        room = _refresh(room)
        assert room.state == 'placing_ships'
        assert room.players[ai_id].ships, 'AI 一侧应已自动完成摆船'
        assert room.players[HUMAN].ships == [], '真人一侧必须等待本人摆船，不能被随机填充'
    finally:
        server.room_manager.delete_room(room.id)


def test_master_redeploy_loop_has_no_human_autoplace_path():
    """灵气复苏和败者食尘共用的 AI 循环不得再调用 opponent 的摆船入口。"""
    source = inspect.getsource(server._ai_master_turn)
    assert '_ai_place_board(room, other)' not in source


def test_ai_caster_redeploy_card_never_leaves_ai_side_unplaced():
    """★ 每一张「房间级重摆」卡：AI 打出后**它自己那一半必须已经摆好**。

    `灵气复苏` / `败者食尘` 是**双方一起重摆**，真人确实要重新摆（卡面如此，
    所以他会收到 `reset_gameboard`）—— 但 AI 自己那一半必须当场摆完，
    绝不能出现"AI 没摆完、真人已经在布船屏"的中间态。
    实测那个中间态（`tools/probe_ai_redeploy.py` 修前）：AI 已经摆好 6 艘、
    而真人那边一份事件都没收到、房间却停在 `placing_ships`。

    ⚠️ 这张表**只**收会置 `room.state='placing_ships'` 的卡（三条）。
    `绝处逢生` / 增援 / 死者苏生 / 滥竽充数 走 `pending_placement`、
    `神机妙算` 走 `shenji_redeploy`，都**不改 room.state**，各有一条用例
    单独钉它们（见 `test_pending_placement_cards_do_not_touch_room_state`）。
    """
    for card_name in sorted(server._MASTER_REDEPLOY_CARDS):
        room, ai_id = _build_room([card_name])
        try:
            resp = _play(room, ai_id, card_name)
            if resp.get('status') != 'success':
                pytest.skip(f'{card_name} 在当前局面打不出来（{resp.get("message")}）')
            room = _refresh(room)
            me = room.players[ai_id]
            want = int(me.max_ships or 6)
            assert len(me.ships) == want, (
                f'AI 打出 {card_name} 后必须已经摆好自己的 {want} 艘船，'
                f'实际 {len(me.ships)} 艘')
            assert not getattr(room, 'huiguang_awaiting_placement', False), \
                'huiguang 标记必须被消费掉（收尾是一条互斥链，挂着就会走错分支）'
        finally:
            server.room_manager.delete_room(room.id)


def test_pending_placement_cards_do_not_touch_room_state():
    """反向守卫：走 `pending_placement` / `shenji_redeploy` 的卡**不在**重摆表里。

    `绝处逢生` 只调 `_start_placement`，**不**改 `room.state` —— 把它一起挡掉
    就是白砍卡池（CLAUDE.md 教训 #9：改共用判据前按 kind 逐个表态）。
    这条把"哪几张属于哪一类"钉死，免得下一批有人凭"它也要重摆"把表撑大。
    """
    for not_room_level in ('绝处逢生', '增援', '死者苏生', '滥竽充数', '神机妙算'):
        assert not_room_level not in server._MASTER_REDEPLOY_CARDS, (
            f'{not_room_level} 走 pending_placement / shenji_redeploy，'
            f'不改 room.state，不该进"房间级重摆"闸门')


def test_redeploy_card_is_never_picked_while_room_is_placing():
    """★ 重摆窗口里，候选池一张重摆卡都不许再被选中。

    为什么：两张重摆卡的收尾标记会**同时挂上**，而 `handle_place_ships` 的收尾
    是一条 `if huiguang… elif lingqi…` 的**互斥链** —— 只有一支会被消费，
    另一支永远留着，`lingqi_saved_state` 再也回不去
    （实测：AI 手牌 ['灵气复苏','回光返照']，两张出完后两个标记同时挂上）。
    """
    room, ai_id = _build_room(sorted(server._MASTER_REDEPLOY_CARDS))
    try:
        # 人为把房间摆成"正在等重新摆放"的窗口
        room.state = 'placing_ships'
        room.ai_difficulty = 'master'
        idx, _targets = server._ai_choose_card(room, ai_id, 0)
        assert idx is None, (
            f'重摆窗口内不该选出一张重摆卡，实际选中 '
            f'{room.players[ai_id].magic_hand[idx].name!r}')
    finally:
        server.room_manager.delete_room(room.id)




# ===========================================================================
# B. ★ 克苏鲁之眼：不许"宣称生效但对手没选"，也不许把牌白烧掉
# ===========================================================================


def test_master_never_wastes_a_turn_on_a_card_it_cannot_target():
    """★★ 核心契约：AI 打完一张牌之后，不许留下"等对手做一件他不知道要做的事"。

    判据用**可观察事实**：AI 走 `_ai_maybe_play_magic`（真实出牌入口）之后，
    不许出现「卡进了弃牌堆（= 打出过）却又被退回手牌」这种白烧，
    也不许给真人留下一个他从来不知道要处理的待选。
    """
    room, ai_id = _build_room(['克苏鲁之眼'])
    try:
        room.players[ai_id].revealed_positions = []
        room.players[HUMAN].revealed_positions = [Position(x=i, y=0) for i in range(4)]
        human_hand_before = len(room.players[HUMAN].magic_hand)
        played = server._ai_maybe_play_magic(room, ai_id)
        room = _refresh(room)

        # "被退回手牌"的可观察形态 = 出了一张牌，但那张牌又躺回手牌里
        ai_hand_names = [c.name for c in room.players[ai_id].magic_hand]
        assert not (played and '克苏鲁之眼' not in ai_hand_names), \
            '不该把克苏鲁之眼打出去（它必然被退回，等于白烧一次出牌机会）'
        assert '克苏鲁之眼' not in [c.name for c in room.magic_discard], \
            '克苏鲁之眼不该留在弃牌堆 —— 那张牌在施法者自己那一半就死了'
        picks = [p for p in (room.pending_ship_picks or [])
                 if p.get('player') == HUMAN]
        assert picks == [], (
            f'不许给真人留下一个他从没被告知过的待选：{picks}')
        assert len(room.players[HUMAN].magic_hand) == human_hand_before
    finally:
        server.room_manager.delete_room(room.id)




def test_ai_caster_trap_pending_placement_cards_are_honest():
    """★ 同类站点逐个表态：`_request_ship_pick` 的返回值**不许**当同步结果用。

    `_request_ship_pick` 对 AI 座位**同步代选**（返回一艘船），对真人**只入队**
    并返回 `None`。所以每个调用点都必须能回答："返回值是 None（= 真人还没选）
    时，我这个效果说了什么？"——克苏鲁之眼那个站点当初答错了（无条件宣称
    「双方各暴露一艘战舰位置」）。这里把**守株待兔**那个站点钉住：
    AI 当施法者、对手是真人时，陷阱设置必须真的落到 AI 头上（AI 可同步代选），
    而陷阱被踩中后向**真人**要的牺牲必须真的入队、并真的通知到他。
    """
    room, ai_id = _build_room(['守株待兔'])
    try:
        resp = _play(room, ai_id, '守株待兔')
        assert resp.get('status') == 'success', f'守株待兔应当能打出：{resp}'
        room = _refresh(room)
        trapped = [sh for sh in room.players[ai_id].ships if getattr(sh, 'trap', False)]
        assert trapped, ('AI 当施法者时陷阱必须真的设置上（`_request_ship_pick` 的 '
                         'AI 同步代选那一路）——不能只留一句"请选择要设置陷阱的战舰"')
        assert [p for p in (room.pending_ship_picks or [])
                if p.get('player') == ai_id] == [], \
            'AI 自己的选船不该入队（它有同步代选入口）'

        # ★ 让**真人**踩中那艘陷阱船（把行动权交给真人）
        room.current_attacker = HUMAN
        room.current_phase = 'battle'
        room.attacks_remaining = 3
        pos = trapped[0].positions[0]
        hresp = server.handle_attack({
            'room_id': room.id, 'player_id': HUMAN, 'x': pos.x, 'y': pos.y})
        assert hresp.get('status') == 'success', f'这一炮应当能打：{hresp}'
        room = _refresh(room)
        picks = [p for p in (room.pending_ship_picks or [])
                 if p.get('player') == HUMAN and p.get('reason') == 'trap_sacrifice']
        assert picks, ('踩中守株待兔后，真人必须拿到"点选要牺牲的战舰"的待选 —— '
                       '`_request_ship_pick` 对他返回 None 是**正常**的（那是"还没选"），'
                       '但效果方绝不能因此把这件事当成"已经做完了"')
    finally:
        server.room_manager.delete_room(room.id)


# ===========================================================================
# C. ★ 节奏：大师**出牌**不许"快到看不清"，**开炮**要快
# ===========================================================================
#
# ⚠️ 本条在本批被**改写过一次**，原因值得记下来：
#   第一次的契约是「出牌 / 开炮 / 阶段转换三处都必须有节奏停顿」—— 那是照着
#   `_MASTER_ACTION_PACING = 0.8` 一个常量被四处共用的实现写的。
#   作者实测第二条反馈是「攻击的时候可以快一点」，于是那个共用常量被拆成
#   `_MASTER_CARD_PACING`（只管出牌）。**行为契约变了，用例就必须跟着变** ——
#   把旧契约留在测试里，等于用测试把"每一炮都白等 0.8 秒"钉成永久行为。
