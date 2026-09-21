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


def test_ai_consume_own_choice_handles_taoyuan(master_room):
    """桃园结义的挑牌待办必须由 AI 自己回答（否则回合永久卡死）。

    这类卡打出后会把 `magic_temp_data` 设成 `type='taoyuan_choice'` 并等
    **施法者自己**回一个 `caster_choice`，然后**对方**还要回一个 `opponent_choice`。
    AI 房间的对方也是电脑 —— 两个都必须由这里代答，只答一个同样会停在
    「等待对方选择」。
    """
    ai_id = _fill_boards(master_room)
    room = master_room
    served = [server.MagicCard('轰炸'), server.MagicCard('疗愈'),
              server.MagicCard('看破！')]
    room.magic_temp_data = {'type': 'taoyuan_choice', 'caster': ai_id,
                            'opponent': server._opponent_of(room, ai_id),
                            'cards': list(served), 'player_deck_backup': []}

    assert server._ai_consume_own_choice(room, ai_id) is True

    assert not (room.magic_temp_data or {}).get('type'), '挑牌待办没被消费'
    # 最能翻盘的「轰炸」必须留给自己（价值表最高）
    assert any(c.name == '轰炸' for c in room.players[ai_id].magic_hand), \
        'AI 没有把最值的那张挑给自己'


def test_ai_consume_own_choice_handles_wangyang(master_room):
    """亡羊补牢：从弃牌堆候选里挑价值最高的一张。"""
    ai_id = _fill_boards(master_room)
    room = master_room
    room.magic_temp_data = {
        'type': 'wangyang_choice', 'caster': ai_id,
        'cards': [server.MagicCard('看破！'), server.MagicCard('硫磺火焰')],
        'own_card': None,
    }
    assert server._ai_consume_own_choice(room, ai_id) is True
    assert not (room.magic_temp_data or {}).get('type')
    assert any(c.name == '硫磺火焰' for c in room.players[ai_id].magic_hand), \
        'AI 没有挑价值最高的那张'


def test_ai_consume_own_choice_ignores_other_players_pending(master_room):
    """别的玩家的待办不许被 AI 抢答。"""
    ai_id = _fill_boards(master_room)
    room = master_room
    other = server._opponent_of(room, ai_id)
    room.magic_temp_data = {'type': 'taoyuan_choice', 'caster': other,
                            'cards': [server.MagicCard('轰炸')]}
    server._ai_consume_own_choice(room, ai_id)
    assert room.magic_temp_data.get('type') == 'taoyuan_choice', \
        'AI 把别人的挑牌待办吃掉了'


def test_ai_consume_own_choice_never_raises(master_room):
    """消费点也不许静默吞异常：各种残缺 `magic_temp_data` 都要安全。

    这段代码与 `_master_card_readiness` 同型（都在回合循环里、都带兜底），
    一样属于"吞掉就是永久卡死"的位置。
    """
    ai_id = _fill_boards(master_room)
    room = master_room
    for bad in ({'type': 'taoyuan_choice', 'caster': ai_id, 'cards': []},
                {'type': 'wangyang_choice', 'caster': ai_id},
                {'type': 'bury_choice', 'caster': ai_id, 'candidates': []},
                {'type': 'bury_choice', 'caster': ai_id,
                 'candidates': [{'source': 'deck', 'index': 0, 'name': '轰炸'}]},
                {'type': 'lingqi_choice', 'caster': ai_id},
                {'type': 'lingqi_choice', 'caster': ai_id, 'max_ships': 'x'},
                {'type': None, 'caster': ai_id},
                {}):
        room.magic_temp_data = dict(bad)
        try:
            server._ai_consume_own_choice(room, ai_id)
        except Exception as exc:                        # pragma: no cover
            pytest.fail(f'magic_temp_data={bad!r} 时消费点抛异常：{exc!r}')
    # 神机妙算宣言同样不许在残缺状态下抛
    for bad in ({'pending_shenji': {'caster': ai_id}},           # 没有 token
                {'pending_shenji': {'caster': ai_id, 'token': None}},
                {'pending_shenji': {}},                          # 无 caster
                {'pending_shenji': {'caster': 'someone-else'}},
                {}):
        room.magic_temp_data = dict(bad)
        try:
            server._ai_consume_own_shenji(room, ai_id)
        except Exception as exc:                        # pragma: no cover
            pytest.fail(f'pending_shenji={bad!r} 时宣言消费抛异常：{exc!r}')


def test_ai_consume_own_choice_handles_shield_multi_select(master_room):
    """仁王之盾走的是**多选**通道（`ship_indices` 下标），与"点一艘"完全不同。

    ⚠️ 下标是 `caster.ships` 里的位置，**沉船会被服务端跳过** ——
       所以消费点必须自己先把沉船剔掉，否则"选了 3 艘、只有 1 艘加上盾"，
       而玩家/AI 都看不出少加了（不报错）。
    """
    ai_id = _fill_boards(master_room)
    room = master_room
    caster = room.players[ai_id]
    # 让第 0、2 艘沉掉
    for i in (0, 2):
        caster.ships[i].hits = list(caster.ships[i].positions)
    room.magic_temp_data = {'type': 'shield_choice', 'caster': ai_id,
                            'ships': caster.ships}
    assert server._ai_consume_own_choice(room, ai_id) is True
    assert not (room.magic_temp_data or {}).get('type'), '多选待办没被消费'
    # 加盾的必须都是活船，且至多 3 艘
    shielded = [sh for sh in caster.ships if getattr(sh, 'shield', False)]
    assert 1 <= len(shielded) <= 3, f'加盾数量不对：{len(shielded)}'
    for sh in shielded:
        assert server._is_ship_alive(caster, sh), '给沉船加了盾（等于白选）'


def test_ai_consume_own_choice_shield_with_no_alive_ship_is_cleared(master_room):
    """一艘活船都没有时必须把待办清掉，不能留在房间里冻住后续操作。"""
    ai_id = _fill_boards(master_room)
    room = master_room
    caster = room.players[ai_id]
    for sh in caster.ships:
        sh.hits = list(sh.positions)
    room.magic_temp_data = {'type': 'shield_choice', 'caster': ai_id,
                            'ships': caster.ships}
    server._ai_consume_own_choice(room, ai_id)
    assert not (room.magic_temp_data or {}).get('type')
    assert not server._my_ship_picks(room, ai_id), '优先队列里的登记没被清掉'


def test_ai_consume_own_placement_last_stand_uses_the_whitelist(master_room):
    """绝处逢生：候选格**只认 `last_stand_cells` 白名单**，不过默认规则。

    ⚠️ 这条是必须的：绝处逢生把全部战舰都牺牲进 `sunken_ships`，而沉船**仍留在
       `caster.ships` 里** → 默认的"未被己方船占用"会把六个候选格**全判成非法**
       → 一个都放不下 → 流程只能取消，卡白打（而且是"打了没反应"那种）。
       服务端对这条路径本来就是按白名单单独校验的（`handle_confirm_reinforcement`），
       所以消费点的口径也必须跟它一致。
    """
    ai_id = _fill_boards(master_room)
    room = master_room
    caster = room.players[ai_id]
    cells = [(int(p.x), int(p.y)) for sh in caster.ships for p in sh.positions]
    # 模拟绝处逢生：全部船进沉船堆（但仍在 ships 列表里 → 占位）
    caster.sunken_ships = list(caster.ships)
    caster.remaining_ships = 0
    room.game_effects['last_stand_cells'] = [list(c) for c in cells]
    server._start_placement(room, ai_id, 'last_stand', 1)

    server._ai_consume_own_placement(room, ai_id)

    assert not (room.magic_temp_data or {}).get('pending_placement'), \
        '绝处逢生的放置待办没被消费 —— 这一局会永远停在 AI 手上'
    assert room.players[ai_id].remaining_ships == 1, \
        f'应该只放下 1 艘，实际 {room.players[ai_id].remaining_ships}'


def test_ai_consume_own_choice_buries_opponent_card(master_room):
    """明智埋葬：**优先埋对方手里最值的那张**，而不是自己牌堆里的。

    埋牌会同时给自己摸一张，所以"埋对方的"是纯赚；埋自己牌堆的好牌等于
    把好牌扔掉再换一张。这条口径错了不会报错，只是白亏一张牌。
    """
    ai_id = _fill_boards(master_room)
    room = master_room
    room.players[ai_id].magic_hand = []
    room.magic_temp_data = {
        'type': 'bury_choice', 'caster': ai_id,
        'candidates': [
            {'source': 'deck', 'index': 0, 'name': '硫磺火焰'},        # 自己牌堆、价值高
            {'source': 'opponent_hand', 'index': 0, 'name': '轰炸'},   # 对方手牌、价值最高
        ],
    }
    assert server._ai_consume_own_choice(room, ai_id) is True
    assert not (room.magic_temp_data or {}).get('type')
    # 对方的「轰炸」必须被埋掉（从对局层看就是那张牌不再在对方手里）
    assert not any(c.name == '轰炸'
                   for c in room.players[server._opponent_of(room, ai_id)].magic_hand), \
        '没有埋掉对方手里最能翻盘的那张'


# ---------------------------------------------------------------------------
# ⑦ 放置阶段自救：棋盘被卡牌整批换掉后必须能自己爬回来
# ---------------------------------------------------------------------------

def test_ai_place_board_fills_and_finishes(master_room):
    """`_ai_place_board` 必须既摆上船、又触发收尾（回到 attacking）。

    ⚠️ 只调 `_ai_place_ships` 是不够的：那会留下 `state=='placing_ships'`，
       而 `enter_end_phase` / `end_turn` 全被拒 → 回合永远交不出去。
       「回光返照」当年就是靠这条把 AI 硬死锁的（§1.1 缺陷 2）。
    """
    ai_id = _fill_boards(master_room)
    room = master_room
    room.players[ai_id].ships = []
    room.players[ai_id].remaining_ships = 0
    room.state = 'placing_ships'
    room.huiguang_awaiting_placement = True
    room.players[ai_id].max_ships = 6

    assert server._ai_place_board(room, ai_id) is True
    assert len(room.players[ai_id].ships) == 6, '没有摆满'
    assert room.state != 'placing_ships', \
        '摆了船却没触发收尾 —— 回合会永远停在 AI 手上'
    # 回光返照的收尾：留在自己回合、准备阶段，且攻击次数被锁 0
    assert room.current_attacker == ai_id
    assert room.current_phase == 'preparation'
    assert room.attacks_remaining == 0


def test_ai_place_board_is_idempotent(master_room):
    """已经摆好的棋盘不该被重复摆（否则每次进循环都会重摆一次）。"""
    ai_id = _fill_boards(master_room)
    room = master_room
    before = list(room.players[ai_id].ships)
    assert server._ai_place_board(room, ai_id) is False
    assert room.players[ai_id].ships == before, '已经摆好的棋盘被重摆了'


def test_master_card_readiness_covers_every_enabled_card(master_room):
    """池里**每一张**卡都要有明确表态：要么能打，要么有明确理由判不能打。

    这条守的是"新加一张卡却忘了给它写闸门"——症状是那张卡永远不出、或者
    打出去必被拒（本批实测：`看破！` 漏闸门 → 1000 局 165 次被拒）。
    """
    ai_id = _fill_boards(master_room)
    room = master_room
    room.players[ai_id].magic_hand = [_mk_card(n) for n in server._MASTER_ENABLED_CARDS]
    checked = 0
    for name in sorted(server._MASTER_ENABLED_CARDS):
        got = server._master_card_readiness(room, ai_id, _mk_card(name))
        assert got is None or isinstance(got, dict), (name, got)
        checked += 1
    assert checked == len(server._MASTER_ENABLED_CARDS) > 20


# ---------------------------------------------------------------------------
# ★ 可复现性：决策层绝不许引入"不可复现的随机源"
# ---------------------------------------------------------------------------

def test_ai_brain_never_creates_an_unseeded_rng():
    """`ai_brain` 里不许出现 `random.Random()` —— 那是**用系统熵播种**的。

    ⚠️ 这是一个真实缺陷（2026-09-22 修）。原写法是
       `rng = rng or random.Random()`，本意是"没传就随便用一个"，
       实际后果有两层：

         · **生产**：AI 的开炮 / 放置 / 选船其实是熵随机的 ——
           模块头上"注入 rng 是为了可复现"那句注释是假的；
         · **度量**：无头驱动器的 `random.seed(seed)` 管不到它，
           **同一 seed 跑同一局会得到不同结果**。实测（同一进程内跑 6 次 seed=1）：
           回合数在 3~11 之间跳、胜负都会翻。
           我据此做过的每一张卡的能力对照，里面都掺了这个噪声。

       正确写法是退化到**模块级 `random`**（`ai_brain._rng`）：驱动器与
       `handle_attack` 都把 `random.seed()` 打在同一份全局状态上，
       整局从猜拳到开炮才走同一条可复现的序列。

    这条必须是**源码级**断言：只要有人再写一次 `random.Random()`，
    由它驱动的那些决策就会静默变成不可复现，而**任何行为测试都测不出来**
    （单测只跑一次，看不出"跑两次不一样"）。
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'ai_brain.py')
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'Random'
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'random'
                and not node.args):
            bad.append(node.lineno)
    assert not bad, (
        f'ai_brain.py 第 {bad} 行用了无参 `random.Random()`（系统熵播种）—— '
        f'请改用 `_rng(rng)`，否则决策不可复现')


def test_ai_brain_rng_helper_falls_back_to_global_random():
    """`_rng(None)` 必须退化到**模块级 `random`**（可被 seed 控制），不是新实例。"""
    import random as _random
    _random.seed(12345)
    got_a = [ai_brain._rng(None).random() for _ in range(3)]
    _random.seed(12345)
    got_b = [ai_brain._rng(None).random() for _ in range(3)]
    assert got_a == got_b, '_rng(None) 不受 random.seed 控制 → 决策不可复现'
    # 传进来的 rng 必须原样使用（不能忽略调用方的注入）
    mine = _random.Random(7)
    assert ai_brain._rng(mine) is mine


def test_headless_game_is_deterministic_for_a_fixed_seed():
    """★ 度量工具的复现性守卫：同一 seed 连跑两次必须**逐字段相同**。

    这是无头模拟器的**根本契约**（`docs/MASTER_AI_2026_09_21.md` §7.2
    「固定种子可复现」），但它此前**没有任何用例守着** ——
    于是 `ai_brain` 里的熵随机源活了很久没被发现，
    期间所有"改动前 / 改动后"的对照都在噪声里读数字。

    ⚠️ 断言的是**不止胜率**：胜负相同但回合数/动作数不同，同样说明
       中间某一步的随机序列已经分叉了（这正是当时的症状：
       同一 seed 的胜者一样、回合数却在 3~11 之间跳）。

    ⚠️ 比较前要把**座位 id 归一化**：房间 id 是 `uuid4()` 生成的，
       AI 座位 id = `'ai-' + room_id`，所以两次跑出来的 id 必然不同 ——
       那是房间标识、不是决策，混进来只会让这条用例永远红。
       归一化之后比的是**动作序列本身**（谁做了什么、按什么顺序）。
    """
    import io
    import contextlib

    hg = pytest.importorskip('tools.headless_game')

    def run_once():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = hg.play_game(lambda: hg.make_policy('master'),
                             lambda: hg.make_policy('hard'), seed=1)
        # 座位 id → 固定别名（p1 = AI 座位、p2 = 对手座位）
        alias = {r.p1: 'P1', r.p2: 'P2'}
        acts = tuple((kind, alias.get(pid, pid), detail)
                     for kind, pid, detail in r.actions)
        return (alias.get(r.winner, r.winner), r.rounds, r.stalled, acts)

    first, second = run_once(), run_once()
    assert first == second, (
        '同一 seed 两次跑出不同结果 → 决策层引入了不可复现的随机源。'
        f'\n  第一次: winner={first[0]} rounds={first[1]} actions={len(first[3])}'
        f'\n  第二次: winner={second[0]} rounds={second[1]} actions={len(second[3])}')


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
