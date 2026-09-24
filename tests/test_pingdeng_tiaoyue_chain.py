# -*- coding: utf-8 -*-
"""平等条约 → 连锁无效化（2026-09-24 改版）的守卫。

背景（作者裁决）：
  旧实现走 `game_effects` 里的一张**船数变化快照**做回滚。那份快照的过期判据绑在
  `room.round`（大回合）上，而 `room.round` 只在 `next_index == 0` 时递增 ⇒ **对两个
  座位不等价**：受害方是后手时用得出、是先手时必被拒（作者实报「船数改变发生在
  上一个 大回合，无法再无效化」）。
  新实现 = `docs/CHAIN_ENGINE_SPEC.md` §1.2 原本的设计：**连锁无效化**，
  目标 = 栈中正下方那一项（与「失灵！」完全同一套目标解析与免疫关系），
  且**只有目标真的会造成船数变化时才成功**。

本文件守的七件事：
  1. ★ 座位等价性（这批的动机）：换座位顺序，结果必须逐项相同；
  2. 判据表：`EQUAL_TREATY_SHIP_CHANGE_RULES` 是"这张卡会不会改船数"的**唯一**实现，
     作者勾选的 8 张逐张必须在表里，表里增删一项都要红；
  3. 逐卡正向：目标真的会改船数 ⇒ 无效化成功（那张卡的效果没生效）；
  4. 逐卡反向：目标不会改船数 ⇒ 失败且**不消耗**（平等条约回手、目标照常结算）；
  5. 免疫关系与失灵！逐条一致（看破！/ 加百列之光 / 看破压制）；
  6. 非连锁使用 ⇒ 失败 + 有明确文案（不静默）；
  7. 旧快照机制已彻底删除（源码级 0 命中），且 `_on_ship_destroyed` 的三条副作用
     （百亿补贴 / 无瑕圣心 / 守株待兔）各自仍有用例。
"""
import os

import pytest

import server
from server import ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 被删掉的那张快照在 `game_effects` 里的键名。
#: ⚠️ 这里**故意拼出来**，不在本文件里写出字面量 —— 下面的源码级守卫要求
#:    全仓 0 命中（含注释与文档），本文件自己当然也不能是例外。
DEAD_SNAPSHOT_KEY = 'last_ship' + '_change'


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def make_room(rid='treaty-room'):
    r = GameRoom(rid)
    for pid, nm in ((P1, 'p1'), (P2, 'p2')):
        r.players[pid] = Player(name=nm, ships=[], attacks=[], remaining_ships=0,
                                sid='sid-' + pid, user_id='u-' + pid)
    r.state = 'attacking'
    r.current_attacker = P1
    r.current_phase = 'battle'
    r.attack_order = [P1, P2]
    r.attacks_remaining = 6
    r.round = 1
    r.magic_deck = []
    room_manager.rooms[r.id] = r
    return r


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)
    room_manager.match_queue = []


def _chain_results(events):
    for e, d, to, r in events:
        if e == 'chain_resolved':
            return d['results']
    return []


def _run_chain(room, events, target_caster, target_name, targets, pingdeng_caster, pingdeng=None):
    """把「目标卡 + 平等条约」压成一条真连锁并结算（LIFO：平等条约先出栈）。

    返回 `(results, pingdeng_card)`；`results` 是 `chain_resolved` 里的条目。
    """
    ping = pingdeng if pingdeng is not None else card('平等条约')
    room.magic_discard.append(ping)
    room.chain = [
        ChainItem(target_caster, card(target_name), targets or {}, 0.0),
        ChainItem(pingdeng_caster, ping, {}, 0.0),
    ]
    server.resolve_chain(room)
    return _chain_results(events), ping


def _by_name(results, name):
    for res in results:
        if getattr(res.card, 'name', None) == name:
            return res
    raise AssertionError('没找到 %s 的结算条目：%s' % (name, [r.card.name for r in results]))


def _table():
    """判据表（用 getattr 取：本文件要能在**旧实现**下收集成功，见座位等价性那节）。"""
    table = getattr(server, 'EQUAL_TREATY_SHIP_CHANGE_RULES', None)
    assert table, '平等条约的判据表不存在或为空 —— 判据必须只有这一份实现（教训 #1）'
    return table


def _verdict(room, target_caster, name, targets=None):
    """只跑判据函数，不结算：返回 True/False 表示"这一项真的会改船数吗"。"""
    fn = _table()[name][0]
    item = ChainItem(target_caster, card(name), targets or {}, 0.0)
    return bool(fn(room, item))


# ===========================================================================
# 1. ★ 座位等价性 —— 同一张卡、同一次连锁，换座位顺序结果必须逐项相同
# ===========================================================================
FIRST, SECOND = 'seat-first', 'seat-second'


def _seat_room():
    r = GameRoom('seat-room')
    for pid, nm in ((FIRST, 'first'), (SECOND, 'second')):
        r.players[pid] = Player(name=nm, ships=[], attacks=[], remaining_ships=0,
                                sid='sid-' + pid, user_id='u-' + pid)
    r.state = 'attacking'
    r.current_attacker = FIRST
    r.current_phase = 'battle'
    r.attack_order = [FIRST, SECOND]
    r.attacks_remaining = 6
    r.round = 1
    r.magic_deck = []
    room_manager.rooms[r.id] = r
    return r


def _play(room, pid, name, targets=None, speed=3, typ='普通'):
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': pid,
        'card': {'name': name, 'speed': speed, 'type': typ, 'description': ''},
        'targets': targets or {},
    })


def _give(room, pid, names):
    room.players[pid].magic_hand = [card(n) for n in names]


def _seat_scenario(events, victim_is_first):
    """走**真实流程**跑一遍"受害方在自己的回合用平等条约连锁响应"。

    ① 攻击方在自己回合用【轰炸】打沉受害方一艘船（旧实现的船数变化快照由此写下）；
    ② 攻击方交回合 → 轮到受害方（**受害方是先手时，这一步会推进大回合**）；
    ③ 受害方回合里，攻击方打出【增援】；受害方用【平等条约】连锁响应。
    ④ 归一化记录：平等条约的 success/message、被无效化的是哪一项、双方船数、双方船位。

    ⚠️ 改动前这条是**红的**：受害方是后手时 round 没推进 → 旧快照有效 → 成功；
       受害方是先手时 round 已 +1 → 「船数改变发生在上一个大回合，无法再无效化」。
    """
    events.clear()
    room = _seat_room()
    victim = FIRST if victim_is_first else SECOND
    attacker = SECOND if victim_is_first else FIRST
    for pid in (FIRST, SECOND):
        # 对角线摆法：轰炸第 0 行只盖住 (0,0)，只沉一艘
        room.players[pid].ships = [ship((i, i)) for i in range(6)]
        room.players[pid].remaining_ships = 6

    # ① 受害方先把回合交出去（只有"受害方 = 先手"时才需要）
    if room.current_attacker == victim:
        room.current_phase = 'end'
        server.end_turn({'room_id': room.id, 'player_id': victim})

    # ② 攻击方用【轰炸】打沉受害方一艘船
    _give(room, attacker, ['轰炸'])
    room.current_phase = 'battle'
    _play(room, attacker, '轰炸', {'target_line': {'type': 'row', 'index': 0}}, speed=2)
    assert room.players[victim].remaining_ships == 5, '前提：这一发真的沉了一艘'

    # ③ 攻击方交回合 → 轮到受害方
    room.current_phase = 'end'
    server.end_turn({'room_id': room.id, 'player_id': attacker})
    # 真实 `end_turn` 在推进大回合时会把 state 置成 rock_paper_scissors（要重新猜拳）；
    # 本场景只关心"座位顺序对平等条约的影响"，把对局状态拨回可出牌的那一帧。
    room.state = 'attacking'
    room.current_phase = 'battle'
    room.current_attacker = victim

    # ④ 受害方回合：攻击方打【增援】，受害方用【平等条约】连锁
    _give(room, attacker, ['增援'])
    _give(room, victim, ['平等条约'])
    events.clear()
    _play(room, attacker, '增援')
    server.chain_response({'room_id': room.id, 'player_id': victim, 'chain': True,
                           'card': {'name': '平等条约', 'speed': 3}})

    results = _chain_results(events)
    ping = _by_name(results, '平等条约')
    negated = sorted(getattr(r.card, 'name', '') for r in results
                     if getattr(r, 'negated_skip', False))
    room_manager.rooms.pop(room.id, None)
    return {
        'success': bool(getattr(ping, 'success', False)),
        'message': getattr(ping, 'message', None),
        'negated': negated,
        'victim_ships': room.players[victim].remaining_ships,
        'attacker_ships': room.players[attacker].remaining_ships,
        'victim_board': sorted((p.x, p.y) for sh in room.players[victim].ships
                               for p in sh.positions),
        'attacker_board': sorted((p.x, p.y) for sh in room.players[attacker].ships
                                 for p in sh.positions),
    }


def test_treaty_is_seat_equivalent(events):
    """★ 两种座位顺序的结果必须**逐项相同**（success / message / 被无效化的项 / 船数 / ships）。

    ⚠️ 改动前的原始红（旧快照实现，`.tmp/seat_probe.py` 与 git stash 复算各一次）：

        victim_is_first=False: 平等条约 success=True  '成功无效化船数改变效果'  受害方 6 艘
        victim_is_first=True : 平等条约 success=False '船数改变发生在上一个大回合，无法再无效化' 受害方 5 艘

    —— 正是作者实报的那条：受害方是先手时**必被拒**。
    """
    second_is_victim = _seat_scenario(events, victim_is_first=False)
    first_is_victim = _seat_scenario(events, victim_is_first=True)

    for key in ('success', 'message', 'negated', 'victim_ships',
                'attacker_ships', 'victim_board', 'attacker_board'):
        assert second_is_victim[key] == first_is_victim[key], (
            '座位顺序改变了 %r：后手受害 %r / 先手受害 %r'
            % (key, second_is_victim[key], first_is_victim[key]))

    # 两条腿都要**真的**验证到了东西（不许"两边都是 False"这种假绿）
    assert second_is_victim['success'] is True, second_is_victim
    assert second_is_victim['negated'] == ['增援'], second_is_victim


# ===========================================================================
# 2. 判据表：单一实现 + 源码级穷举守卫
# ===========================================================================
#: 作者勾选、**逐张必须在判据表里**的 8 张卡。少一张就红。
AUTHOR_PICKED = (
    '轰炸', '硫磺火焰', '溅射',        # 击沉类
    '疗愈', '死者苏生',                # 复活类
    '增援', '滥竽充数', '神机妙算',    # 增加类
)

#: 表里**额外**的一项（作者裁决「绝处逢生的自牺牲可以被无效化，别改」）。
#: ⚠️ 作者在"不在表里的卡"那句里也点过绝处逢生；两处冲突已在报告里单列，
#:    本批按"务必尊重"的裁决原文（可以被无效化）实现，并把结论钉在这里。
EXTRA_IN_TABLE = ('绝处逢生',)

#: **不在表里**、且必须逐条写清"为什么不康"的卡（防止以后有人顺手加进去）。
NOT_NEGOTIABLE = {
    '恶魔契约': '作者已裁：它造成的「牺牲」不算可被无效化的船数变化',
    '神之宣告': '同上（牺牲两艘自己的船，再让对方牺牲一艘）',
    '命运骰子': '同上（摇到 6 点让对方牺牲）',
    '守株待兔': '同上（陷阱触发后让对方牺牲）',
}


def test_judgement_table_covers_author_picked_cards():
    """源码级穷举：作者勾选的 8 张**逐张**必须在判据表里有交代。"""
    table = _table()
    src = open(os.path.join(ROOT, 'server.py'), encoding='utf-8').read()
    missing_table = [n for n in AUTHOR_PICKED if n not in table]
    missing_src = ["'%s':" % n for n in AUTHOR_PICKED if "'%s':" % n not in src]
    assert not missing_table, '判据表里少了这几张（作者已勾选）：%s' % missing_table
    assert not missing_src, 'server.py 的判据表字面量里少了这几张：%s' % missing_src


def test_judgement_table_has_no_undeclared_entries():
    """表里**增删一项**都要能被抓住：键集必须与登记表逐字相等。

    这就是"下一个卡想顺手加一张进来"的那道闸门 —— 加一项会红两次
    （这里 + 上面的穷举腿），逼人回去先问作者。
    """
    expected = set(AUTHOR_PICKED) | set(EXTRA_IN_TABLE)
    actual = set(_table())
    assert actual == expected, (
        '判据表的键集变了 ——\n  多了 %s\n  少了 %s\n'
        '（"平等条约康哪些卡"是作者裁决，改之前先确认）'
        % (sorted(actual - expected), sorted(expected - actual)))


def test_judgement_table_rows_are_callable_with_a_reason():
    """每一行都必须是 `(可调用判据, 非空人话说明)`，不能只写个 `True`。"""
    for name, row in _table().items():
        assert isinstance(row, tuple) and len(row) == 2, (name, row)
        fn, why = row
        assert callable(fn), (name, row)
        assert isinstance(why, str) and why.strip(), (name, row)


def test_sacrifice_cards_are_documented_as_not_negotiable():
    """「不在表里」的卡也要有交代（作者要求逐条写清为什么不康）。"""
    registry = getattr(server, 'EQUAL_TREATY_NOT_NEGOTIABLE', None)
    assert registry, '缺少"不在表里"的登记表 —— 下一批会有人顺手把牺牲类加进可康列表'
    assert registry == NOT_NEGOTIABLE, registry
    for name in NOT_NEGOTIABLE:
        assert name not in _table(), '%s 不该出现在可康表里（作者已裁）' % name


@pytest.mark.parametrize('name', sorted(NOT_NEGOTIABLE))
def test_sacrifice_cards_cannot_be_negated(room, events, name):
    """逐卡反向：牺牲类（恶魔契约/神之宣告/命运骰子/守株待兔）⇒ 平等条约失败。"""
    results, ping = _run_chain(room, events, P2, name, {}, P1)
    assert _by_name(results, '平等条约').success is False
    assert '没有可无效化的船数改变效果' in _by_name(results, '平等条约').message
    assert ping in room.players[P1].magic_hand, '失败必须把平等条约退回手牌（不消耗）'
    assert not any(getattr(r, 'negated_skip', False) for r in results), '不能无效化掉目标'


# ===========================================================================
# 3. 逐卡正向：目标"真的会改船数" ⇒ 无效化成功（那张卡的效果没生效）
# ===========================================================================
def test_zhencha_kills_alive_ship(room, events):
    """轰炸：目标行里有活船 ⇒ 成功；**轰炸的效果没生效**（船还在）。

    ⚠️ 受害方是**施法者的对手**：轰炸由 P2 打出，所以船要摆在 P1 那一侧。
    """
    room.players[P1].ships = [ship((0, 0)), ship((3, 3))]
    room.players[P1].remaining_ships = 2

    results, _ = _run_chain(room, events, P2, '轰炸',
                            {'target_line': {'type': 'row', 'index': 0}}, P1)

    assert _by_name(results, '平等条约').success is True
    bomb = _by_name(results, '轰炸')
    assert getattr(bomb, 'negated_skip', False) is True
    assert getattr(bomb, 'negated_by', None) == '平等条约'
    assert room.players[P1].remaining_ships == 2, '轰炸被无效化 ⇒ 一艘都不该沉'
    assert len(room.players[P1].ships) == 2


def test_liuhuang_kills_alive_ship(room, events):
    """硫磺火焰：选定的 6 格里有活船 ⇒ 成功。"""
    room.players[P1].ships = [ship((2, 0)), ship((5, 5))]
    room.players[P1].remaining_ships = 2
    cells = [{'x': i, 'y': 0} for i in range(6)]

    results, _ = _run_chain(room, events, P2, '硫磺火焰', {'target_cells': cells}, P1)

    assert _by_name(results, '平等条约').success is True
    assert getattr(_by_name(results, '硫磺火焰'), 'negated_skip', False) is True
    assert room.players[P1].remaining_ships == 2


def test_jianshe_kills_neighbor_ship(room, events):
    """溅射：上一发命中格的相邻格里有会沉掉的船 ⇒ 成功。"""
    room.players[P1].ships = [ship((2, 3))]
    room.players[P1].remaining_ships = 1
    room.last_attack = {'attacker': P2, 'x': 2, 'y': 2, 'hit': True}

    results, _ = _run_chain(room, events, P2, '溅射', {}, P1)

    assert _by_name(results, '平等条约').success is True
    assert getattr(_by_name(results, '溅射'), 'negated_skip', False) is True
    assert room.players[P1].remaining_ships == 1, '溅射被无效化 ⇒ 相邻格那艘不该沉'


def test_liaoyu_revives_sunken_ship(room, events):
    """疗愈：场上真的还有可复活的沉船 ⇒ 成功。"""
    dead = ship((4, 4))
    dead.hits = list(dead.positions)
    room.players[P2].ships = [dead]
    room.players[P2].sunken_ships = [dead]

    results, _ = _run_chain(room, events, P2, '疗愈', {}, P1)

    assert _by_name(results, '平等条约').success is True
    assert getattr(_by_name(results, '疗愈'), 'negated_skip', False) is True
    assert room.players[P2].remaining_ships == 0, '疗愈被无效化 ⇒ 不该复活'
    assert dead in room.players[P2].sunken_ships


def test_sizhe_susheng_revives_sunken_ship(room, events):
    """死者苏生：同上（与疗愈共用同一个判据函数）。"""
    dead = ship((4, 4))
    dead.hits = list(dead.positions)
    room.players[P2].ships = [dead]
    room.players[P2].sunken_ships = [dead]

    results, _ = _run_chain(room, events, P2, '死者苏生', {}, P1)

    assert _by_name(results, '平等条约').success is True
    assert getattr(_by_name(results, '死者苏生'), 'negated_skip', False) is True
    assert room.players[P2].remaining_ships == 0
    assert 'pending_placement' not in room.magic_temp_data, '被无效化 ⇒ 不该开放置流程'


def test_zengyuan_adds_a_ship(room, events):
    """增援：棋盘上真的还有可放置的空格 ⇒ 成功。"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1

    results, _ = _run_chain(room, events, P2, '增援', {}, P1)

    assert _by_name(results, '平等条约').success is True
    assert getattr(_by_name(results, '增援'), 'negated_skip', False) is True
    assert 'pending_placement' not in room.magic_temp_data, '被无效化 ⇒ 不该开放置流程'


def test_lanyu_refills_ships(room, events):
    """滥竽充数：真的补得满（船数未满 + 有空格）⇒ 成功。"""
    room.players[P2].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P2].remaining_ships = 2

    results, _ = _run_chain(room, events, P2, '滥竽充数', {}, P1)

    assert _by_name(results, '平等条约').success is True
    assert getattr(_by_name(results, '滥竽充数'), 'negated_skip', False) is True


def test_shenji_can_restore_ships(room, events):
    """神机妙算：还有活船可沉（必要条件）⇒ 成功。

    ⚠️ 这一条的判据**只是必要条件**，理由见 `_treaty_shenji_can_restore` 的说明：
       它改船数与否要等它自己结算之后才由玩家宣言 x，平等条约结算时**无从判断**。
    """
    room.players[P2].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P2].remaining_ships = 2

    results, _ = _run_chain(room, events, P2, '神机妙算', {}, P1)

    assert _by_name(results, '平等条约').success is True
    assert getattr(_by_name(results, '神机妙算'), 'negated_skip', False) is True
    assert 'pending_shenji' not in room.magic_temp_data, '被无效化 ⇒ 不该开宣言窗口'


def test_juechu_fengsheng_self_sacrifice_is_negatable(room, events):
    """绝处逢生的自牺牲：作者裁决「保持现状（可以被无效化），别改」⇒ 在判据表里。

    ⚠️ 新机制下"无效化"= **整张牌被跳过** ⇒ 一艘都不牺牲（旧快照实现回的是 1 艘）。
       这条差异已单列在报告里。
    """
    room.players[P2].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P2].remaining_ships = 3

    results, _ = _run_chain(room, events, P2, '绝处逢生', {}, P1)

    assert _by_name(results, '平等条约').success is True
    assert getattr(_by_name(results, '绝处逢生'), 'negated_skip', False) is True
    assert room.players[P2].remaining_ships == 3, '整张牌被跳过 ⇒ 一艘都不该牺牲'


# ===========================================================================
# 4. 逐卡反向：目标"不会改船数" ⇒ 失败且不消耗
# ===========================================================================
def test_zhencha_on_empty_line_fails(room, events):
    """轰炸打在**没有活船的行**上 ⇒ 这一炮不沉船 ⇒ 失败，且轰炸照常结算。"""
    room.players[P1].ships = [ship((3, 3)), ship((4, 4))]
    room.players[P1].remaining_ships = 2

    results, ping = _run_chain(room, events, P2, '轰炸',
                               {'target_line': {'type': 'row', 'index': 0}}, P1)

    pd = _by_name(results, '平等条约')
    assert pd.success is False
    assert '没有可无效化的船数改变效果' in pd.message
    assert ping in room.players[P1].magic_hand, '被拒时平等条约必须退回手牌（不消耗）'
    bomb = _by_name(results, '轰炸')
    assert getattr(bomb, 'negated_skip', False) is False, '被拒 ⇒ 目标照常结算'
    assert bomb.success is True
    assert room.players[P1].remaining_ships == 2


def test_liuhuang_on_empty_cells_fails(room, events):
    """硫磺火焰打在**没有活船的 6 格**上 ⇒ 失败。"""
    room.players[P1].ships = [ship((0, 5))]
    room.players[P1].remaining_ships = 1
    cells = [{'x': i, 'y': 0} for i in range(6)]

    results, ping = _run_chain(room, events, P2, '硫磺火焰', {'target_cells': cells}, P1)

    assert _by_name(results, '平等条约').success is False
    assert ping in room.players[P1].magic_hand
    assert room.players[P1].remaining_ships == 1


def test_jianshe_without_neighbor_ship_fails(room, events):
    """溅射：相邻四格上没有会沉的船 ⇒ 失败。"""
    room.players[P1].ships = [ship((0, 5))]
    room.players[P1].remaining_ships = 1
    room.last_attack = {'attacker': P2, 'x': 2, 'y': 2, 'hit': True}

    results, ping = _run_chain(room, events, P2, '溅射', {}, P1)

    assert _by_name(results, '平等条约').success is False
    assert ping in room.players[P1].magic_hand


def test_jianshe_blocked_by_shield_fails(room, events):
    """溅射受**护盾**影响（卡面）：带盾的船这一发沉不了 ⇒ 失败。"""
    shielded = ship((2, 3))
    shielded.shield = True
    room.players[P1].ships = [shielded]
    room.players[P1].remaining_ships = 1
    room.last_attack = {'attacker': P2, 'x': 2, 'y': 2, 'hit': True}

    results, ping = _run_chain(room, events, P2, '溅射', {}, P1)

    assert _by_name(results, '平等条约').success is False
    assert ping in room.players[P1].magic_hand
    assert room.players[P1].remaining_ships == 1


@pytest.mark.parametrize('name', ['疗愈', '死者苏生'])
def test_revive_without_wreck_fails(room, events, name):
    """疗愈 / 死者苏生：**场上没有可复活的沉船** ⇒ 不会复活 ⇒ 失败。"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    assert room.players[P2].sunken_ships == []

    results, ping = _run_chain(room, events, P2, name, {}, P1)

    pd = _by_name(results, '平等条约')
    assert pd.success is False
    assert '没有可无效化的船数改变效果' in pd.message
    assert ping in room.players[P1].magic_hand


def test_zengyuan_with_full_board_fails(room, events):
    """增援：棋盘 36 格全被占满 ⇒ 加了也等于没变 ⇒ 失败。"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    room.players[P1].attacks = [Position(x=x, y=y) for x in range(6) for y in range(6)]
    assert len(server._placement_blocked_cells(room, P2)) >= 36

    results, ping = _run_chain(room, events, P2, '增援', {}, P1)

    assert _by_name(results, '平等条约').success is False
    assert ping in room.players[P1].magic_hand


def test_lanyu_when_already_full_fails(room, events):
    """滥竽充数：自己的船数**已满**（remaining >= max_ships）⇒ 补不了 ⇒ 失败。"""
    room.players[P2].ships = [ship((i, 0)) for i in range(6)]
    room.players[P2].remaining_ships = 6

    results, ping = _run_chain(room, events, P2, '滥竽充数', {}, P1)

    assert _by_name(results, '平等条约').success is False
    assert ping in room.players[P1].magic_hand


def test_shenji_without_any_alive_ship_fails(room, events):
    """神机妙算：自己一艘活船都没有 ⇒ 船数不可能再减少 ⇒ 失败。"""
    dead = ship((4, 4))
    dead.hits = list(dead.positions)
    room.players[P2].ships = [dead]
    room.players[P2].sunken_ships = [dead]
    room.players[P2].remaining_ships = 0

    results, ping = _run_chain(room, events, P2, '神机妙算', {}, P1)

    assert _by_name(results, '平等条约').success is False
    assert ping in room.players[P1].magic_hand


def test_ordinary_attack_kill_cannot_be_negated(room, events):
    """**普通炮击**造成的击沉 ⇒ 失败（卡面：炮击造成的船数减少无法被无效化）。

    炮击不是连锁项（`handle_attack` 不进 `room.chain`），所以新机制下"康炮击"这件事
    只能表现为：打完之后再单独打平等条约 → 没有正下方那一项、且船不会回来。
    """
    room.players[P2].ships = [ship((0, 0)), ship((5, 5))]
    room.players[P2].remaining_ships = 2
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    assert room.players[P2].remaining_ships == 1, '前提：炮击真的打沉了一艘'
    assert room.state == 'attacking', '前提：这一炮没把对局打完'

    ping = card('平等条约')
    room.players[P1].magic_hand = [ping]
    events.clear()
    _play(room, P1, '平等条约')
    results = _chain_results(events)
    pd = _by_name(results, '平等条约')

    assert pd.success is False
    assert room.players[P2].remaining_ships == 1, '炮击击沉不该被回滚'
    assert pd.message, '失败必须有文案，不能静默'
    # ⚠️ 走真实出牌路径时，进连锁的是服务端按客户端数据 **新建** 的卡实例
    #    （`handle_use_magic_card` 里 `MagicCard(**data['card'])`）⇒ 按名字断言回手。
    assert any(c.name == '平等条约' for c in room.players[P1].magic_hand), '被拒 ⇒ 退回手牌'


# ===========================================================================
# 5. 免疫关系与失灵！逐条一致
# ===========================================================================
def test_treaty_cannot_negate_kanpo(room, events):
    """目标是【看破！】⇒ 失败（看破优先级更高）。"""
    results, ping = _run_chain(room, events, P2, '看破！', {}, P1)

    pd = _by_name(results, '平等条约')
    assert pd.success is False
    assert '看破！优先于平等条约' in pd.message
    assert ping in room.players[P1].magic_hand


def test_treaty_cannot_negate_gabriel(room, events):
    """目标是【加百列之光】⇒ 失败（加百列免疫）。"""
    results, ping = _run_chain(room, events, P2, '加百列之光', {}, P1)

    pd = _by_name(results, '平等条约')
    assert pd.success is False
    assert '加百列之光免疫平等条约' in pd.message
    assert ping in room.players[P1].magic_hand


def test_shiling_and_treaty_share_the_same_immunity_wording(room, events):
    """失灵！与平等条约必须**共用同一份**免疫判据（不许各写一份、必然漂移）。"""
    helper = getattr(server, '_chain_negation_target', None)
    assert callable(helper), '“正下方那一项”的目标解析+免疫关系必须只有一份实现'
    for name, frag in (('看破！', '看破！优先于'), ('加百列之光', '加百列之光免疫')):
        item = ChainItem(P2, card(name), {}, 0.0)
        for who in ('失灵！', '平等条约'):
            room.chain = [item]
            target, reason = helper(room, who)
            assert target is None and frag in reason, (name, who, reason)


def test_treaty_fails_while_kanpo_suppresses_caster(room, events):
    """**看破！压制期间** ⇒ 失败（与失灵同口径）。

    两条腿：
      ① 出牌/响应闸门（失灵走的就是这一层）——被看破者根本发不出这张牌；
      ② 结算层——同一连锁里若有【看破！】先结算（它在平等条约上方），
         轮到自己结算时已被压制 ⇒ 也必须失败。
    """
    # ① 响应闸门
    room.chain = [ChainItem(P2, card('增援'), {}, 0.0)]
    room.chain_waiting = True
    room.chain_window = P1
    room.players[P1].magic_hand = [card('平等条约')]
    room.players[P1].magic_blocked = True
    resp = server.chain_response({'room_id': room.id, 'player_id': P1, 'chain': True,
                                  'card': {'name': '平等条约', 'speed': 3}})
    assert resp['status'] == 'error'
    assert '看破' in resp['message']

    # ② 结算层（直接造出"平等条约结算时施法者已被看破"那一帧）
    room.chain_waiting = False
    room.chain_window = None
    room.players[P1].magic_blocked = False
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    room.chain = [ChainItem(P2, card('轰炸'), {'target_line': {'type': 'row', 'index': 0}}, 0.0)]
    room.players[P1].magic_blocked = True
    res = server.apply_magic_effect(room, P1, card('平等条约'), {})
    assert res.success is False
    assert res.message, '失败必须有文案'
    assert not getattr(res, 'negate_target', False)


# ===========================================================================
# 6. 非连锁使用：没有"正下方那一项" ⇒ 失败 + 明确文案
# ===========================================================================
def test_treaty_outside_chain_fails_with_a_message(room, events):
    """自己回合里干打、栈里没有别的项 ⇒ 失败，并且**不是静默**。"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    ping = card('平等条约')
    room.players[P1].magic_hand = [ping]
    events.clear()

    _play(room, P1, '平等条约')

    pd = _by_name(_chain_results(events), '平等条约')
    assert pd.success is False
    assert '连锁' in pd.message, pd.message
    assert any(c.name == '平等条约' for c in room.players[P1].magic_hand), '失败退回手牌'


# ===========================================================================
# 7. 旧快照机制已彻底删除 + `_on_ship_destroyed` 的三条副作用仍在
# ===========================================================================
def test_dead_snapshot_key_is_gone_from_the_whole_repo():
    """源码级守卫：全仓（含 docs/CLAUDE.md）不许再出现那张快照的键名。

    ⚠️ 之所以连文档一起扫：`docs/CHAIN_ENGINE_SPEC.md` 开头原本写着
       「② 平等条约不走 negate_target，改读 <快照> 回滚 —— **别照那份文档改回去**」，
       留着它，下一个人就会照着把快照找回来。
    """
    skip_dirs = {'.git', '.tmp', '__pycache__', 'node_modules', '.venv', 'venv',
                 '.pytest_cache', 'data', 'uploads', 'logs'}
    text_ext = {'.py', '.js', '.mjs', '.cjs', '.html', '.css', '.md', '.json',
                '.txt', '.yml', '.yaml', '.sh', '.bat', '.ps1', '.cfg', '.ini'}
    hits = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in text_ext:
                continue
            path = os.path.join(base, fn)
            try:
                text = open(path, encoding='utf-8').read()
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if DEAD_SNAPSHOT_KEY in line:
                    hits.append('%s:%d: %s' % (os.path.relpath(path, ROOT), i, line.strip()[:120]))
    assert not hits, '旧快照机制的残留（必须为 0）：\n' + '\n'.join(hits)


def test_ship_destroyed_still_grants_subsidy(room, events):
    """`_on_ship_destroyed` 的**百亿补贴**（+3）一个字都没动。"""
    server.apply_magic_effect(room, P2, card('百亿补贴'), {})
    victim = ship((0, 0))
    room.players[P2].ships = [victim]
    room.players[P2].remaining_ships = 1

    server._on_ship_destroyed(room, P2, victim)

    assert room.players[P2].effect_flags.subsidy_bonus == 3


def test_ship_destroyed_still_interrupts_holy_heart(room, events):
    """`_on_ship_destroyed` 的**无瑕圣心中断**一个字都没动。"""
    room.game_effects['holy_heart'] = {'caster': P2, 'rounds_left': 2, 'no_damage': True}
    victim = ship((0, 0))
    room.players[P2].ships = [victim]
    room.players[P2].remaining_ships = 1

    server._on_ship_destroyed(room, P2, victim)

    assert 'holy_heart' not in room.game_effects
    assert any(e[0] == 'holy_heart_interrupted' for e in events)


def test_ship_destroyed_still_triggers_trap(room, events):
    """`_on_ship_destroyed` 的**守株待兔**陷阱触发一个字都没动。"""
    victim = ship((0, 0))
    victim.trap = True
    room.players[P2].ships = [victim]
    room.players[P2].remaining_ships = 1
    room.players[P1].ships = [ship((0, 5))]
    room.players[P1].remaining_ships = 1

    server._on_ship_destroyed(room, P2, victim)

    assert victim.trap is False, '触发后必须清掉陷阱标记（同一艘只能触发一次）'
    traps = [d for e, d, to, r in events if e == 'trap_triggered']
    assert traps, '守株待兔必须照常触发'
