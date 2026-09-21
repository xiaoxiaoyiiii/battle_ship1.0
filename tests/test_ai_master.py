# -*- coding: utf-8 -*-
"""大师难度**接线层**的测试：`server.py` 里以 `_is_master` 为界的那些分支。

设计规格：`docs/MASTER_AI_2026_09_21.md`。纯决策层的用例在 `tests/test_ai_brain.py`，
这里只管"接线对不对、会不会把回合卡死、会不会静默失效"。

本文件里的每一条都对应一次**真实事故**（不是推演出来的担心）：

  ① `test_master_card_readiness_never_raises` —— 试算函数里有 `except Exception`，
     `AREA_CARDS` 从 set 改成 dict 后 `dict | set` 抛 TypeError 被它吞掉，
     **大师一张牌都不出**，而"被拒动作 0、卡死 0、胜率 50%"看起来一切正常。
     静默失败是本项目最贵的一类 bug（CLAUDE.md 教训 #32 同型）。

  ② `test_master_difficulty_is_per_seat` —— 房间只有**一个** `ai_difficulty` 字段，
     自对弈度量里两个座位都是 AI 时，对手也套用了大师的卡池与开炮逻辑
     → 量出来的是"大师 vs 大师"，胜率必然贴 50%。

  ③ `test_ai_brain_never_reads_opponent_private_state` —— AI 不许作弊（§4.1）。
"""
import ast
import os

import pytest

import ai_brain
import server
from server import Player, PlayerShip, Position


def _mk_card(name):
    return server.MagicCard(name)


def _mk_full_room(difficulty='master', opponent='human-0'):
    """建一个**两座位**的人机房。

    ⚠️ 必须补上第二个座位：人机房只预置 AI 一个玩家，`_opponent_of` 会返回 None，
    于是所有需要对手信息的闸门都判不成 —— 第一版诊断脚本就是这样量出
    "每张牌都不能打"的（夹具的问题，不是产品的问题）。
    """
    room_id = server.room_manager.create_ai_room('human-0', 'P2', None, difficulty)
    room = server.room_manager.get_room(room_id)
    room.players[opponent] = Player(
        name='P2', ships=[], attacks=[], remaining_ships=0, user_id=None, sid=opponent)
    room.init_player_magic(opponent, server.magic_cards)
    return room_id, room


def _fill_boards(room, ships=6):
    """给双方各摆 `ships` 艘单格船，并让 AI 处于"自己的战斗阶段"。"""
    ai_id = server._ai_player_id(room)
    cells = [(i, 0) for i in range(6)]
    for pid in room.players:
        p = room.players[pid]
        p.ships = [PlayerShip(positions=[Position(x=x, y=y)], hits=[])
                   for (x, y) in cells[:ships]]
        p.remaining_ships = ships
        p.attacks = []
        p.revealed_positions = []
    room.state = 'attacking'
    room.current_attacker = ai_id
    room.current_phase = 'battle'
    room.attack_order = [ai_id, server._opponent_of(room, ai_id)]
    server._recalc_attacker_attacks(room)
    return ai_id


@pytest.fixture
def master_room():
    """一个干净的大师房：用完即删。"""
    room_id, room = _mk_full_room()
    try:
        yield room
    finally:
        server.room_manager.delete_room(room_id)


# ---------------------------------------------------------------------------
# ① 试算闸门：绝不静默失效
# ---------------------------------------------------------------------------

def test_master_card_readiness_never_raises_for_any_playable_card(master_room):
    """对**每一张**已进池的卡，在任何牌型下 `_master_card_readiness` 都不许抛异常。

    ⚠️ 为什么这条最重要：该函数内部有 `except Exception: return None` 兜底，
       目的只是"别让试算崩了烧掉回合"。但只要它吞掉一个**真 bug**，
       表现就是"大师一张牌都不出"，而且**不报错、不卡死、胜率还像个正常值**。
       实测事故：`AREA_CARDS` 改成 dict 后 `dict | set` 抛 TypeError，
       被这里吞掉 → 大师 0 出牌，而"被拒 0 / 卡死 0"看起来完全健康。

       所以这里**绕过兜底**直接调用主体，用各种局面把它逼一遍。
    """
    ai_id = _fill_boards(master_room)
    room = master_room
    seen = set()

    def probe(label):
        for name in sorted(server._MASTER_ENABLED_CARDS):
            card = _mk_card(name)
            room.players[ai_id].magic_hand = [card]
            try:
                got = server._master_card_readiness(room, ai_id, card)
            except Exception as exc:                    # pragma: no cover
                pytest.fail(f'[{label}] {name} 的试算抛异常：{exc!r}')
            # 返回值只能是 None（打不了）或 dict（可以打）
            assert got is None or isinstance(got, dict), (label, name, got)
            seen.add(name)

    probe('开局')
    # 有手牌 / 有沉船 / 有情报 / 打过一些格 —— 逼出各卡的不同分支
    room.players[ai_id].magic_hand = [_mk_card(n) for n in server._MASTER_ENABLED_CARDS]
    room.players[ai_id].sunken_ships = [room.players[ai_id].ships[0]]
    room.players[ai_id].attacks = [Position(x=i, y=1, hit=(i % 2 == 0)) for i in range(6)]
    room.players[ai_id].revealed_positions = [Position(x=5, y=5)]
    probe('有沉船+有情报')
    room.magic_history.append({'card': _mk_card('轰炸'), 'caster': 'human-0',
                               'timestamp': 0.0, 'round': 1})
    probe('有历史')
    room.field_magic = _mk_card('伊甸园')
    probe('场上有场地')
    room.game_effects['last_ship_change'] = {'source': 'magic', 'round': room.round}
    probe('有船数变化快照')

    assert seen == set(server._MASTER_ENABLED_CARDS), '有卡没被试算到'


def test_master_card_readiness_rejects_a_card_that_would_fail(master_room):
    """反面：前置明显不成立时必须返回 None（否则又是"白烧一张牌"）。"""
    ai_id = _fill_boards(master_room)
    room = master_room
    # 没沉船 → 死者苏生 / 疗愈 都打不出去
    assert room.players[ai_id].sunken_ships == []
    for name in ('死者苏生', '疗愈'):
        assert server._master_card_readiness(room, ai_id, _mk_card(name)) is None, name
    # 溅射：上一发没有命中 → 打不了
    room.last_attack = {'attacker': ai_id, 'x': 0, 'y': 0, 'hit': False, 'ship_sunk': False}
    assert server._master_card_readiness(room, ai_id, _mk_card('溅射')) is None
    # 命中了 → 可以打
    room.last_attack['hit'] = True
    assert server._master_card_readiness(room, ai_id, _mk_card('溅射')) == {}


def test_master_card_readiness_respects_magic_block(master_room):
    """被「看破！」封锁时，**每一张**手牌都必须被判成打不了。

    事故：漏掉这一条时，大师会把整套手牌逐张打出去、逐张被拒
    （1000 局实测 165 次，占大师侧全部被拒动作的 100%）——
    每次都要白跑一遍 handler 并往对局日志刷一条"出牌被拒"。
    所以这条按**整池**断言，而不是抽查一张。
    """
    ai_id = _fill_boards(master_room)
    room = master_room
    room.players[ai_id].magic_hand = [_mk_card(n) for n in server._MASTER_ENABLED_CARDS]
    room.players[ai_id].sunken_ships = [room.players[ai_id].ships[0]]
    room.players[ai_id].magic_blocked = True
    for name in sorted(server._MASTER_ENABLED_CARDS):
        assert server._master_card_readiness(room, ai_id, _mk_card(name)) is None, name
    assert server._ai_master_pick(room, ai_id, 0) == (None, {})
    # 解封后至少要能打出去一张（否则上面的断言可能只是"全都打不了"）
    room.players[ai_id].magic_blocked = None
    idx, _t = server._ai_master_pick(room, ai_id, 0)
    assert idx is not None, '解封后仍打不出任何牌 —— 闸门把正常出牌也关掉了'


def test_every_enabled_card_is_actually_a_real_card_name():
    """卡池里的名字必须都在卡表里 —— 写错一个字就等于那张卡永远不出。

    （`CardPool` 拼错卡名不会报错，只会静默少一张牌。）
    """
    real = {c.name for c in server.magic_cards}
    unknown = sorted(server._MASTER_ENABLED_CARDS - real)
    assert not unknown, f'卡池里有卡表里不存在的名字：{unknown}'


def test_card_pool_has_no_overlap_with_hidden_cards():
    """摸不到的卡不许进池（否则"开了却永远不出"，查起来极费劲）。"""
    hidden = set(getattr(server, 'HIDDEN_CARD_NAMES', ()) or ())
    overlap = sorted(server._MASTER_ENABLED_CARDS & hidden)
    assert not overlap, f'池里有谁都摸不到的卡：{overlap}'


def test_master_pick_respects_card_budget(master_room):
    """出牌预算：到顶就一张都不许再打（否则一回合倒光手牌）。"""
    ai_id = _fill_boards(master_room)
    room = master_room
    room.players[ai_id].magic_hand = [_mk_card('轰炸')]
    assert server._ai_master_pick(room, ai_id, 0)[0] == 0
    limit = int(ai_brain.CARDS_PER_TURN)
    assert server._ai_master_pick(room, ai_id, limit) == (None, {})


def test_master_pick_never_returns_a_card_outside_the_pool(master_room):
    """池外的卡即便在手牌里也不许被选中（白名单是唯一入口）。"""
    ai_id = _fill_boards(master_room)
    room = master_room
    room.players[ai_id].magic_hand = [_mk_card('钢筋铁骨'), _mk_card('回光返照')]
    idx, _t = server._ai_master_pick(room, ai_id, 0)
    assert idx is None


# ---------------------------------------------------------------------------
# ② 逐座位难度（度量正确性的前提）
# ---------------------------------------------------------------------------

def test_master_difficulty_is_per_seat():
    """`_is_master` 必须能**按座位**判，不能只看房间。

    事故：`master vs hard` 自对弈时房间只有一个 `ai_difficulty`，
    对手那一侧也套用了大师的卡池与开炮逻辑 → 量出来的是"大师 vs 大师"，
    胜率必然贴 50%（实测修之前正好 50.0%，修完 43.7% —— 那 6 个点就是量错了对象）。
    """
    room_id, room = _mk_full_room(difficulty='master')
    try:
        ai_id = server._ai_player_id(room)
        other = server._opponent_of(room, ai_id)
        # 房间级：全房都是大师
        assert server._is_master(room, ai_id) is True
        assert server._is_master(room, other) is True
        assert server._ai_difficulty_of(room, other) == 'master'
        # 逐座位覆盖：只有 AI 那一侧是大师
        room.ai_difficulty_by_player = {ai_id: 'master', other: 'hard'}
        assert server._is_master(room, ai_id) is True
        assert server._is_master(room, other) is False
        assert server._ai_difficulty_of(room, other) == 'hard'
        # 覆盖为空 = 回到房间级（线上人机房就是这个语义，只有一个电脑座位）
        room.ai_difficulty_by_player = {}
        assert server._is_master(room, other) is True
    finally:
        server.room_manager.delete_room(room_id)


def test_create_ai_room_initialises_per_seat_difficulty():
    """新建人机房必须把逐座位覆盖**初始化成空 dict**。

    ⚠️ 这是「新增房间级状态要三件齐」那条教训（CLAUDE.md 教训 #11）：
       `__init__` 初始化 + 明确消费点 + 回归用例。少一个就会在别的路径上
       读到 AttributeError 或旧值。
    """
    room_id, room = _mk_full_room()
    try:
        assert room.ai_difficulty_by_player == {}
    finally:
        server.room_manager.delete_room(room_id)


# ---------------------------------------------------------------------------
# ③ 不作弊：源码级守卫（行为级在 tests/test_ai_brain.py）
# ---------------------------------------------------------------------------

def test_ai_brain_never_reads_opponent_private_state():
    """源码级断言：`ai_brain.py` 里不许出现对方私有状态的访问。

    行为测试只覆盖"实际跑到"的分支；这条管"今天没跑、明天会跑"的路径
    （CLAUDE.md 教训 #19 同型：跨模块的约定只能靠源码级断言守住）。
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'ai_brain.py')
    tree = ast.parse(open(path, encoding='utf-8').read())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            # `opponent.ships` 这类：只看属性名，不管挂在谁身上
            # （`.ships` 对本模块是禁读的；自己的船要通过 `_my_ship_cells` 之外的
            #   公开路径拿 —— 实际上本模块自己也不该直接读 ships）
            if node.attr in ('magic_hand', 'magic_deck'):
                bad.append((node.lineno, node.attr))
    assert not bad, f'ai_brain.py 访问了对方私有状态：{bad}'


def test_ai_brain_does_not_import_server():
    """`ai_brain` 不许 import server（CLAUDE.md 教训 #19）。

    `python server.py` 启动时模块名是 `__main__`，运行期 import server 会把
    server.py 再执行一遍成**另一个模块对象**：那份 socketio 发不出事件、
    那份 room_manager 里的房间在真进程里不存在 —— 本地坏、线上好（最难查的一类）。
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'ai_brain.py')
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name != 'server' for a in node.names), 'ai_brain 不许 import server'
        elif isinstance(node, ast.ImportFrom):
            assert node.module != 'server', 'ai_brain 不许 from server import'


# ---------------------------------------------------------------------------
# ④ 待办消费：AI 自己开的待办必须有人消费（否则回合永久卡死）
# ---------------------------------------------------------------------------

def test_ai_has_placement_spot_detects_a_full_board(master_room):
    """满盘（无空格）时必须报"没有落点"，这样放置类卡就不会被打出去。"""
    ai_id = _fill_boards(master_room)
    room = master_room
    assert server._ai_has_placement_spot(room, ai_id) is True
    # 把自己的 36 格全占满（增援不受 6 艘上限，只受棋盘格数限制）
    room.players[ai_id].ships = [
        PlayerShip(positions=[Position(x=x, y=y)], hits=[])
        for x in range(6) for y in range(6)]
    assert server._ai_has_placement_spot(room, ai_id) is False


def test_ai_consume_own_placement_clears_pending(master_room):
    """放置待办必须被 AI 消费掉（这是 `pending_placement` 类卡能开放的前提）。"""
    ai_id = _fill_boards(master_room)
    room = master_room
    caster = room.players[ai_id]
    # 复活流程要有"已阵亡的战舰"可领，否则 `handle_confirm_reinforcement`
    # 会走"没有可复活的战舰"分支直接收尾 —— 那样测的就不是放置本身了。
    dead = caster.ships.pop()
    caster.sunken_ships.append(dead)
    caster.remaining_ships -= 1

    server._start_placement(room, ai_id, 'revive', 1)
    assert room.magic_temp_data.get('pending_placement'), '夹具没建出放置待办'
    assert server._ai_has_placement_spot(room, ai_id) is True, '夹具里没有合法落点'

    server._ai_consume_own_placement(room, ai_id)

    assert not (room.magic_temp_data or {}).get('pending_placement'), \
        '放置待办没被消费 —— 这一局会永远停在 AI 手上'
    assert dead in caster.ships, 'AI 没有真的把那艘船放回来'
    assert dead not in caster.sunken_ships


def test_ai_consume_own_placement_without_legal_cell_cancels(master_room):
    """没有合法落点时必须**显式取消**，绝不留下没人能消费的待办。

    ⚠️ 这是"回合必被交出"的底线：待办留在房间里，`_action_wait_reason` 会把
       后续所有写操作冻住，而 AI 房间的看门狗还会主动跳过这类房间 ——
       整局就静默停在那里，真人零提示（§1.1 缺陷 2 的原形）。
    """
    ai_id = _fill_boards(master_room)
    room = master_room
    room.players[ai_id].ships = [
        PlayerShip(positions=[Position(x=x, y=y)], hits=[])
        for x in range(6) for y in range(6)]
    server._start_placement(room, ai_id, 'revive', 1)
    server._ai_consume_own_placement(room, ai_id)
    assert not (room.magic_temp_data or {}).get('pending_placement'), \
        '没落点时必须取消，不能把待办留在房间里'


def test_ai_consume_own_ship_picks_clears_queue(master_room):
    """AI 名下的选船待办也必须能消费掉。"""
    ai_id = _fill_boards(master_room)
    room = master_room
    # AI 房间的 _request_ship_pick 是同步代选，正常不入队；这里手工塞一条，
    # 模拟"状态异常时兜底消费"这条路径。
    room.pending_ship_picks = [{'player': ai_id, 'reason': 'demon_contract',
                                'message': 'x', 'priority': 50, 'seq': 1}]
    assert server._my_ship_picks(room, ai_id), '夹具没建出待选'
    assert server._ai_consume_own_ship_picks(room, ai_id) is True
    assert not server._my_ship_picks(room, ai_id), '选船待办没被消费'


# ---------------------------------------------------------------------------
# ⑤ 区域卡边长：3×3 / 2×2 不许混
# ---------------------------------------------------------------------------

def test_area_cards_and_line_cells_sets_are_disjoint_and_hashable():
    """三张形状表必须是**集合**且两两不相交。

    ⚠️ `_is_master_target_card` 里要 `AREA_CARDS | LINE_CARDS | CELLS_CARDS`：
       一旦有人把边长之类的元数据塞进这三张表（改成 dict），这里就会 TypeError，
       而它在 `_master_card_readiness` 的兜底 except 里**静默变成"都不能打"**。
    """
    for name, table in (('AREA_CARDS', ai_brain.AREA_CARDS),
                        ('LINE_CARDS', ai_brain.LINE_CARDS),
                        ('CELLS_CARDS', ai_brain.CELLS_CARDS)):
        assert isinstance(table, set), f'{name} 必须是 set'
    assert not (ai_brain.AREA_CARDS & ai_brain.LINE_CARDS)
    assert not (ai_brain.AREA_CARDS & ai_brain.CELLS_CARDS)
    assert not (ai_brain.LINE_CARDS & ai_brain.CELLS_CARDS)
    # 并集必须能算出来（这就是 server 里那一行的形状）
    assert ai_brain.AREA_CARDS | ai_brain.LINE_CARDS | ai_brain.CELLS_CARDS


def test_probe_radar_uses_two_by_two(master_room):
    """探测雷达是 **2×2**（卡面与实现都这么写），不许按 3×3 圈。"""
    ai_id = _fill_boards(master_room)
    card = _mk_card('探测雷达')
    got = server._master_card_readiness(master_room, ai_id, card)
    assert got is not None
    area = got['target_area']
    assert area['x2'] - area['x1'] == 1 and area['y2'] - area['y1'] == 1, area


# ---------------------------------------------------------------------------
# ⑥ 三档零回归：大师的开关不许碰到 easy / normal / hard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('difficulty', ['easy', 'normal', 'hard'])
def test_non_master_difficulties_still_use_the_old_card_pool(difficulty):
    """easy / normal / hard 的选牌必须仍走 `_ai_choose_magic_card`（9 张安全卡）。"""
    room_id, room = _mk_full_room(difficulty=difficulty)
    try:
        ai_id = _fill_boards(room)
        # 一张池外、一张安全卡：非大师只能选到安全卡
        room.players[ai_id].magic_hand = [_mk_card('神威！'), _mk_card('无中生有')]
        assert not server._is_master(room, ai_id)
        idx, targets = server._ai_choose_card(room, ai_id, 0)
        if difficulty == 'easy':
            assert idx is None, 'easy 不该出牌'
        else:
            assert idx == 1, '非大师档必须选安全卡里那张'
            assert targets == {}, '非大师档不该带目标'
    finally:
        server.room_manager.delete_room(room_id)
