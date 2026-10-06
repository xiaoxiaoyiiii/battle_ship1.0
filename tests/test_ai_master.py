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




# ---------------------------------------------------------------------------
# ④ 待办消费：AI 自己开的待办必须有人消费（否则回合永久卡死）
# ---------------------------------------------------------------------------



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
# ⑤ 池外卡的**逐张表态**：每一张都必须能在池外被点到名
#
# 为什么要有这一类用例：`_MASTER_ENABLED_CARDS` 旁边的注释里写了 11 张
# "为什么不开"的理由，但那是**注释** —— 没有用例守着，下一批有人凭
# "价值表分数高"把它加回去时不会有任何东西变红。这批实测把其中三张
# （平等条约 / 克苏鲁之眼 / 其余 9 张）逐张量过，结论全部记在
# `docs/MASTER_AI_2026_09_21.md` §12.6。下面几条守的就是"别凭感觉改回去"。
# ---------------------------------------------------------------------------

def test_pingdeng_tiaoyue_stays_out_of_the_master_pool(master_room):
    """★ 平等条约**不许**回到大师卡池 —— 它是实测出来的负收益卡。

    2026-09-23：5000 局 × 3 个独立种子（同一批局面，只改池子）：

        线上池（含它）   69.4% [68.1,70.6]  70.9% [69.6,72.2]  68.9% [67.6,70.2]
        去掉它           70.9% [69.6,72.2]  72.1% [70.9,73.3]  70.4% [69.1,71.6]

    三个半样本**全部 +1.4~1.5 且区间不重叠**。原因是它的生效条件是
    「**魔法卡**造成的船数变化」，而困难 AI 每局总共只出 1.16 张牌、
    且那 9 张安全卡里一张都不会改船数 —— 打出去实际无事发生，
    只是把一次出牌机会花掉了（出牌机会很稀缺：71% 的决策一张可打的牌都没有）。

    ⚠️ 这条断言的是**卡池**，不是"卡牌本身"：`apply_magic_effect` 的
       平等条约分支、快照台账、`_master_card_readiness` 的闸门**全部原样保留**，
       真人对局里这张牌照常能用。要把它加回大师卡池，必须先在
       "对手真的会改船数"的场合重新量一次并更新这里。
    """
    assert '平等条约' not in server._MASTER_ENABLED_CARDS, (
        '平等条约被加回大师卡池了 —— 它是实测 -1.5 个百分点的负收益卡，'
        '见 server.py 里 _MASTER_ENABLED_CARDS 旁边的实测表')
    # 通道必须还在（别把"AI 不打"误删成"这张卡没了"）：分支与闸门都仍要认这张卡。
    # 用**源码级**断言而不是调 `_master_card_readiness`：后者要链上有"正下方那一项"
    # 才判得成，在本夹具里恒返回 None —— 拿它断言会变成"断言恒真"，
    # 正是本项目最忌讳的假绿。
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'server.py'), encoding='utf-8').read()
    assert "if name == '平等条约':" in src, (
        '平等条约的试算闸门被删了 —— 那是它"此刻能不能打"的判据，'
        '不该跟着卡池一起删（真人对局里这张卡照常能用）')
    assert "elif card.name == '平等条约':" in src, (
        '平等条约的结算分支被删了 —— 卡池开关不该动卡牌实现')










# ---------------------------------------------------------------------------
# ★ 可复现性：决策层绝不许引入"不可复现的随机源"
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# ⑤ 区域卡边长：3×3 / 2×2 不许混
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# ⑥ 三档零回归：大师的开关不许碰到 easy / normal / hard
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# ⑦ 「上一张牌结算完了吗」——作者实报的"出牌太快"到底是不是结算竞态
# ---------------------------------------------------------------------------
#
# 背景（2026-09-22，作者实测第二条反馈）：
#   「我是怕出牌的时候太快了，上一个效果还没结算完下一张牌已经打出来了」
#
# 这句话有两个版本的答案，而且**观感问题**与**真缺陷**的改法完全不同：
#   · 观感 → 加停顿（`_MASTER_CARD_PACING`）；
#   · 真缺陷 → 补等待判据（`_master_settle` 的收敛条件）。
# 所以这里把"结算完"的判据**钉成用例**，而不是靠读代码相信它。
#
# 判据是 `server._master_unsettled(room, ai_id)`：返回空列表 = 真的结算完了。
# 它必须同时覆盖**连锁窗口**与**四条待办通道**（放置 / 宣言 / 弃牌 / 选船）——
# 只看连锁会漏掉"打完一张放置卡、船还没放就接着打下一张"（`handle_attack` /
# `handle_use_magic_card` 恰恰**不**拦 `pending_placement`）。



def test_master_unsettled_catches_chain_and_window(master_room):
    """连锁栈 / 响应窗口没收敛 → 必须判成"没结算完"，且原因里说得出来。"""
    ai_id = _fill_boards(master_room)

    master_room.chain = [server.ChainItem(ai_id, _mk_card('火力全开'), {}, 0.0)]
    reasons = server._master_unsettled(master_room, ai_id)
    assert reasons and any('连锁栈' in r for r in reasons), reasons

    master_room.chain = []
    master_room.chain_waiting = True
    master_room.chain_window = server._opponent_of(master_room, ai_id)
    reasons = server._master_unsettled(master_room, ai_id)
    assert reasons and any('响应窗口' in r for r in reasons), reasons


def test_master_unsettled_catches_pending_placement(master_room):
    """★ 这条正是"打完一张放置卡、船还没放就接着打下一张"的形状。

    `handle_use_magic_card` 只拦 `chain_waiting`，**不拦** `pending_placement`
    （那个只由 `_action_wait_reason` 拦）。所以只判连锁的实现会在这里放行 ——
    即"上一个效果还没结算完，下一张牌已经打出来了"。
    """
    ai_id = _fill_boards(master_room)
    # 形状照 `_start_placement` 写（kind/remaining/total/placed 一个都不能少：
    # `handle_confirm_reinforcement` 会读 `remaining`，少一个就 KeyError）。
    master_room.magic_temp_data['pending_placement'] = {
        'caster': ai_id, 'kind': 'reinforce',
        'remaining': 1, 'total': 1, 'placed': 0}
    reasons = server._master_unsettled(master_room, ai_id)
    assert reasons and any('放置流程' in r for r in reasons), reasons










def test_master_turn_never_plays_a_card_before_the_previous_one_settled():
    """★ 本节的**核心**回归：跑真实的 `_ai_master_turn`，逐张牌检查"前一张结算完了"。

    用真实的 `_ai_master_turn`（不是复刻）在一局人机房里跑大师的一个回合，
    在**每一次** `handle_use_magic_card` / `handle_attack` 之前抓一次房间状态：
    只要有任何一次是在"还有未结算项"时动的，就说明"上一个效果还没结算完，
    下一张牌已经打出来了"真的发生了。

    ⚠️ 这个回合本来就是**多张牌**的（大师每回合最多 `CARDS_PER_TURN` 张），
       所以它确实会覆盖"连打第 2、3 张"的路径 —— 手牌按"最可能被打出"的顺序排。
    """
    import threading
    import time as _time
    import tools.headless_game as hg

    room_id, room = _mk_full_room()
    try:
        # 棋盘要错开：`_fill_boards` 给双方摆了**同一批格子**，狙击会直接命中；
        # 这里让双方各占一行，避免"AI 与真人共用格子"这种不可能的局面。
        ai_id = _fill_boards(room)
        opp = server._opponent_of(room, ai_id)
        for pid, row in ((ai_id, 0), (opp, 1)):
            p = room.players[pid]
            p.ships = [PlayerShip(positions=[Position(x=x, y=row)], hits=[])
                       for x in range(6)]
            p.remaining_ships = 6
        server._recalc_attacker_attacks(room)
        # 手牌：这几张都在池里、门槛低、容易真的打出去（顺序也会影响先打哪张）
        room.players[ai_id].magic_hand = [_mk_card(n) for n in
                                          ('火力全开', '看破！', '无中生有',
                                           '极限增援', '百亿补贴')]

        violations = []
        plays = []
        orig_use = server.handle_use_magic_card
        orig_atk = server.handle_attack

        def use_spy(data):
            if data.get('player_id') == ai_id:
                unsettled = server._master_unsettled(
                    server.room_manager.get_room(room_id) or room, ai_id)
                if unsettled:
                    violations.append(('出牌前', data.get('card'), list(unsettled)))
                plays.append(('card', (data.get('card') or {}).get('name')))
            return orig_use(data)

        def atk_spy(data):
            if data.get('player_id') == ai_id:
                unsettled = server._master_unsettled(
                    server.room_manager.get_room(room_id) or room, ai_id)
                if unsettled:
                    violations.append(('开炮前', (data.get('x'), data.get('y')),
                                       list(unsettled)))
                plays.append(('shot', f"{data.get('x')},{data.get('y')}"))
            return orig_atk(data)

        # ⚠️ 只替换 `time.sleep` 为"立刻返回"：节奏停顿与连锁轮询等待加起来
        #    会让这条用例跑十几秒，而本用例验的是**结算顺序**，不是墙钟。
        #    决策与结算逻辑一行不改（连 `_MASTER_SETTLE_STEPS` 都不动）。
        real_sleep = server.time.sleep
        server.time.sleep = lambda *_a, **_k: None
        server.handle_use_magic_card = use_spy
        server.handle_attack = atk_spy
        driver = hg.HeadlessGame(lambda: hg.make_policy('master'),
                                 None, seed=1)
        try:
            driver.room = room
            driver.p1, driver.p2 = ai_id, opp
            driver.policies = {}

            def run_master():
                server._ai_master_turn(room_id, room, ai_id)

            thread = threading.Thread(target=run_master, daemon=True)
            thread.start()
            deadline = _time.monotonic() + 30
            while thread.is_alive() and _time.monotonic() < deadline:
                # 替真人一侧把连锁与待办搬完（无头环境没有真人也没有定时器）
                live = server.room_manager.get_room(room_id)
                if live is None:
                    break
                if live.chain or live.chain_waiting:
                    driver._pump_chain()
                else:
                    driver._pump_pending()
                _time.sleep(0.001)
            thread.join(5)
            assert not thread.is_alive(), '真实的大师回合循环在 30 秒内没返回（卡死了）'
        finally:
            server.time.sleep = real_sleep
            server.handle_use_magic_card = orig_use
            server.handle_attack = orig_atk

        assert not violations, (
            '发现"上一个效果还没结算完就动下一个"：\n  '
            + '\n  '.join(repr(v) for v in violations[:5]))
        cards = [name for kind, name in plays if kind == 'card']
        shots = [d for kind, d in plays if kind == 'shot']
        assert len(cards) >= 1, f'大师一张牌都没打出去（出牌路径没被覆盖）: {plays}'
        assert shots, f'大师一炮都没开（开炮路径没被覆盖）: {plays}'
        # ★ 回合结束时也不许留下未结算项（否则下一个回合会在脏状态上开始）
        final_room = server.room_manager.get_room(room_id) or room
        assert server._master_unsettled(final_room, ai_id) == [], (
            '大师回合结束时房间里还挂着未结算项：'
            + str(server._master_unsettled(final_room, ai_id)))
    finally:
        server.room_manager.delete_room(room_id)
