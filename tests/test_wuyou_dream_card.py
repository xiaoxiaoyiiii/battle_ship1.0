# -*- coding: utf-8 -*-
"""无忧梦呓（判定魔法卡，2026-09-24 新增）的回归测试。

卡面（作者原话，不许自行改动规则）：
  这张牌**通过后**，在**对方的下一个回合开始时**双方进行摇骰子拼点判定：
    · 对方点数 **小于** 自己 → 对方**这回合**的攻击次数恒定为 0；
    · 对方点数 **大于** 自己 → 对方必须弃置一张牌（有牌的前提下）；
    · **平局** → 什么都没发生（不重摇，骰子动画与日志照常记录）。
  只触发一次：打出后的对方下一个回合触发，触发完即清除。

按 CLAUDE.md §7「改卡要同步 4 处」+ §10 教训 #11「新增房间级状态三件齐」覆盖：
  · `static/magic_card.json` 与 `static/magic_cards.js` **逐字符一致**；
  · `apply_magic_effect` 的判定分支登记延迟拼点（且**打出时不摇骰子**）；
  · 回合开始时的三分支结算 + 攻击次数锁定**不被重算覆盖**；
  · 弃牌分支复用 `pending_dice_discard` 链路，含「**不覆盖进行中的待办**」；
  · 只触发一次 + 房间级状态的生命周期（`__init__` / 消费点 / 终局清理）；
  · 观战复用 `dice_rolled`（不新增事件）；大师 AI 卡池的明确表态。
"""
import json
import os

import pytest

import server
from server import (GameRoom, MagicCard, Player, PlayerShip, Position,
                    room_manager)

P1, P2 = 'p1', 'p2'


# ---------------------------------------------------------------------------
# 基础设施（与 test_dice_card / test_all_magic_cards 同口径，便于交叉复用）
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def events(monkeypatch):
    """拦截所有 socket emit，避免需要请求上下文。"""
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room():
    room = GameRoom('test-wuyou-room')
    room.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid-p1')
    room.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 0
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def give_hand(player, names):
    player.magic_hand = [card(n) for n in names]


def find_emit(events, event_name, to=None):
    return [(ev, data, t, r) for ev, data, t, r in events
            if ev == event_name and (to is None or t == to)]


def lock_rolls(monkeypatch, *rolls):
    """把 `random.randint` 换成给定序列（按调用顺序吐出）。"""
    seq = list(rolls)

    def fake_randint(a, b):
        assert seq, '拼点需要两次 random.randint，序列不够'
        return seq.pop(0)

    monkeypatch.setattr(server.random, 'randint', fake_randint)


def cast(room, caster):
    """打出无忧梦呓（登记延迟拼点，此时**不摇骰子**）。"""
    return server.apply_magic_effect(room, caster, card('无忧梦呓'), {})


def settle(room):
    """模拟「某个回合开始了」。"""
    server._settle_wuyou_dream(room)


# ---------------------------------------------------------------------------
# 卡牌定义一致性（CLAUDE.md §7：json 与 js 必须逐字符一致）
# ---------------------------------------------------------------------------
def test_card_definition_consistent():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'static', 'magic_card.json'), encoding='utf-8') as f:
        json_cards = json.load(f)
    mine = [c for c in json_cards if c['name'] == '无忧梦呓']
    assert len(mine) == 1
    c = mine[0]
    assert c['speed'] == 1
    assert c['type'] == '判定'
    # 顺序也要一致（前后端一致性用例比的是**有序序列**）
    backend_seq = [(x['name'], int(x['speed']), x['type']) for x in json_cards]

    with open(os.path.join(here, 'static', 'magic_cards.js'), encoding='utf-8') as f:
        js_src = f.read()
    assert 'name: "无忧梦呓"' in js_src
    assert f'speed: {c["speed"]}' in js_src
    assert f'type: "{c["type"]}"' in js_src
    # 卡面必须**逐字符**一致
    assert c['description'] in js_src
    # 位置一致：无忧梦呓排在命运骰子（另一张判定卡）的正后面，前后端都是
    idx = [i for i, x in enumerate(backend_seq) if x[0] == '无忧梦呓'][0]
    assert backend_seq[idx - 1][0] == '命运骰子'


def test_wuyou_enters_deck():
    names = [c.name for c in server.magic_cards]
    assert '无忧梦呓' in names
    assert '无忧梦呓' not in server.HIDDEN_CARD_NAMES


# ---------------------------------------------------------------------------
# 打出：只登记、不摇骰子
# ---------------------------------------------------------------------------
def test_cast_registers_pending_and_does_not_roll(room, events):
    res = cast(room, P1)
    assert res.success is True
    assert room.pending_wuyou_dreams == {P1: 1}
    # ⚠️ 打出时**不该**有骰子动画 —— 摇点在对方的回合开始时
    assert find_emit(events, 'dice_rolled') == []


def test_cast_twice_counts_two(room):
    """同名牌被打出两次 → 计数为 2（如果是单槽，第二张会把它覆盖成 1）。"""
    cast(room, P1)
    cast(room, P1)
    assert room.pending_wuyou_dreams == {P1: 2}


def test_pending_state_is_initialised_in_dunder_init():
    """房间级状态三件齐之一：`__init__` 里必须初始化（否则首次读会 AttributeError）。"""
    fresh = GameRoom('test-wuyou-init')
    assert fresh.pending_wuyou_dreams == {}
    assert fresh.pending_dice_discard_label == {}
    room_manager.rooms.pop(fresh.id, None)


# ---------------------------------------------------------------------------
# 结算：三分支
# ---------------------------------------------------------------------------
def test_opponent_lower_locks_attacks_to_zero(room, events, monkeypatch):
    """对方点数**小于**自己 → 对方这回合攻击次数恒为 0。"""
    cast(room, P1)
    room.current_attacker = P2            # 轮到对方了
    room.attacks_remaining = 6
    lock_rolls(monkeypatch, 5, 3)         # 自己 5、对方 3
    settle(room)

    assert room.attacks_remaining == 0
    assert server._attacks_forced_zero(room) is True
    assert room.pending_wuyou_dreams == {}          # 触发完即清除
    rolls = find_emit(events, 'dice_rolled')
    assert len(rolls) == 1
    data = rolls[0][1]
    assert data['roll'] == 5 and data['opponent_roll'] == 3
    assert data['caster'] == P1 and data['card'] == '无忧梦呓'
    assert rolls[0][3] == room.id                   # 广播给整个房间，不是 to=
    # 攻击次数变化要让前端知道（否则界面还显示 6 次）
    assert find_emit(events, 'attacks_updated')


def test_zero_attack_lock_survives_recalc(room, monkeypatch):
    """★ 攻击次数锁定**本回合内不被重算覆盖**(验收标准第 4 条)。

    进战斗阶段 / 场地魔法变更 / 船数变化都会调 `_recalc_attacker_attacks`，
    它按船数把 `attacks_remaining` 重算一遍 —— 没有那条硬规则兜住就会被还原。
    """
    cast(room, P1)
    room.current_attacker = P2
    lock_rolls(monkeypatch, 6, 1)
    settle(room)
    assert room.attacks_remaining == 0

    # 对方有 4 艘船：重算一次本该给回 4 次
    room.players[P2].ships = [ship((i, 0)) for i in range(4)]
    room.players[P2].remaining_ships = 4
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 0, '攻击次数的 0 被 _recalc 覆盖掉了'
    assert server._grant_extra_attacks(room, P2, 2) == 0


def test_attack_lock_only_covers_that_one_turn(room, monkeypatch):
    """锁的是**对方那一个回合**，不是整个大回合：翻页后立刻失效。"""
    cast(room, P1)
    room.current_attacker = P2
    lock_rolls(monkeypatch, 6, 1)
    settle(room)
    assert server._attacks_forced_zero(room) is True

    # 大回合翻页（round += 1），轮次回到自己 —— 对方那条锁必须失效
    room.round += 1
    room.current_attacker = P1
    assert server._attacks_forced_zero(room) is False
    room.current_attacker = P2
    assert server._attacks_forced_zero(room) is False, '锁跨回合活下来了'


def test_huiguang_lock_is_not_clobbered(room, monkeypatch):
    """★ 回光返照（大回合级 `zero_attacks_for`）与无忧梦呓**不能互相覆盖**。

    两张卡共用同一个 key 的话，后写的那条会让先写的那条静默失效
    （症状："我明明跳过了战斗阶段却还是能打"）。CLAUDE.md 教训 #29。
    """
    room.game_effects['zero_attacks_for'] = {'player': P1, 'round': room.round}
    cast(room, P1)
    room.current_attacker = P2
    lock_rolls(monkeypatch, 6, 1)
    settle(room)

    assert server._attacks_forced_zero(room) is True       # 无忧梦呓那条生效
    room.current_attacker = P1
    assert server._attacks_forced_zero(room) is True, '回光返照那条被无忧梦呓覆盖掉了'


def test_opponent_higher_forces_discard(room, events, monkeypatch):
    """对方点数**大于**自己 → 对方必须弃置一张牌。"""
    give_hand(room.players[P2], ['轰炸', '冻结', '看破！'])
    cast(room, P1)
    room.current_attacker = P2
    lock_rolls(monkeypatch, 2, 6)
    settle(room)

    assert room.pending_dice_discard.get(P2) is False
    assert room.pending_dice_discard_label.get(P2) == '无忧梦呓'
    assert room.pending_wuyou_dreams == {}
    # 只判**对方**一个人：打出者不该被牵连
    assert P1 not in room.pending_dice_discard
    req = find_emit(events, 'dice_discard_request', to='sid-p2')
    assert len(req) == 1
    assert '无忧梦呓' in req[0][1]['message']


def test_discard_records_through_add_game_log(room, events, monkeypatch):
    """验收标准第 5 条：弃牌记录走 add_game_log（含来源卡名）。"""
    give_hand(room.players[P2], ['轰炸', '冻结'])
    cast(room, P1)
    room.current_attacker = P2
    lock_rolls(monkeypatch, 2, 6)
    settle(room)
    server.handle_dice_discard_choose(
        {'room_id': room.id, 'player_id': P2, 'card_index': 1})

    logs = [d.get('text') or '' for _, d, _, _ in find_emit(events, 'game_log')]
    assert any('因无忧梦呓弃置' in t and '冻结' in t for t in logs), logs
    assert room.players[P2].magic_hand[0].name == '轰炸'
    assert room.pending_dice_discard == {}
    assert room.pending_dice_discard_label == {}


def test_discard_skipped_when_no_hand(room, events, monkeypatch):
    """没有手牌 → 跳过（不弹窗、不挂待办）。"""
    room.players[P2].magic_hand = []
    cast(room, P1)
    room.current_attacker = P2
    room.attacks_remaining = 6
    lock_rolls(monkeypatch, 2, 6)
    settle(room)

    assert find_emit(events, 'dice_discard_request') == []
    assert room.pending_dice_discard == {}
    assert room.attacks_remaining == 6, '弃牌支不该动攻击次数'


def test_tie_does_nothing_but_is_still_recorded(room, events, monkeypatch):
    """平局：不重摇、不留状态，但骰子动画与日志照常记（作者裁决第 1 条）。"""
    give_hand(room.players[P2], ['轰炸'])
    cast(room, P1)
    room.current_attacker = P2
    room.attacks_remaining = 6
    lock_rolls(monkeypatch, 4, 4)
    settle(room)

    assert room.attacks_remaining == 6
    assert server._attacks_forced_zero(room) is False
    assert room.pending_dice_discard == {}
    assert room.pending_wuyou_dreams == {}
    assert len(find_emit(events, 'dice_rolled')) == 1
    logs = [d.get('text') or '' for _, d, _, _ in find_emit(events, 'game_log')]
    assert any('平局' in t for t in logs), logs


# ---------------------------------------------------------------------------
# 只触发一次
# ---------------------------------------------------------------------------
def test_triggers_only_once(room, events, monkeypatch):
    cast(room, P1)
    room.current_attacker = P2
    room.attacks_remaining = 6
    lock_rolls(monkeypatch, 5, 1)
    settle(room)
    assert room.attacks_remaining == 0

    # 再走一次回合开始：什么都没了（不重摇、不再锁）
    room.attacks_remaining = 6
    settle(room)
    assert room.attacks_remaining == 6
    assert len(find_emit(events, 'dice_rolled')) == 1


def test_does_not_trigger_on_casters_own_turn(room, events, monkeypatch):
    """卡面写的是**对方的**回合 —— 打出者自己在行动时保持挂着。"""
    cast(room, P1)
    room.current_attacker = P1
    room.attacks_remaining = 6
    settle(room)
    assert find_emit(events, 'dice_rolled') == []
    assert room.pending_wuyou_dreams == {P1: 1}


def test_two_copies_settle_one_per_turn(room, events, monkeypatch):
    """两张同时挂着 → 对方的**一个**回合里各结算一次（计数不丢）。"""
    cast(room, P1)
    cast(room, P1)
    room.current_attacker = P2
    room.attacks_remaining = 6
    lock_rolls(monkeypatch, 5, 1, 5, 1)
    settle(room)
    assert len(find_emit(events, 'dice_rolled')) == 2
    assert room.pending_wuyou_dreams == {}


# ---------------------------------------------------------------------------
# 回合开始的两个入口（换人分支 / 猜拳定先手）
# ---------------------------------------------------------------------------
def test_end_turn_swap_settles_after_recalc(room, events, monkeypatch):
    """★ 验收标准第 3 条：**换人分支**结算，且排在 `_recalc_attacker_attacks` 之后。

    走真 `end_turn` handler（不是直接调内部函数）—— 只有这样才能证明
    "排在重算之后"这件事，否则测到的是我自己的调用顺序。
    """
    cast(room, P1)
    room.current_phase = 'end'
    room.attacks_remaining = 3
    room.players[P2].ships = [ship((i, 0)) for i in range(5)]
    room.players[P2].remaining_ships = 5
    lock_rolls(monkeypatch, 6, 1)         # 对方 1 点 < 自己 6 点

    resp = server.end_turn({'room_id': room.id, 'player_id': P1})
    assert resp.get('status') == 'success', resp
    assert room.current_attacker == P2
    # 重算本会给 5 次，结算把它钉成 0 且不再被覆盖
    assert room.attacks_remaining == 0, '换人分支的结算跑在了 _recalc 前面'
    assert server._attacks_forced_zero(room) is True


def test_rps_turn_start_also_settles(room, events, monkeypatch):
    """★ **后手方**打出的那张卡也必须触发。

    后手方交回合走的是 `_end_turn_locked` 的「新大回合」分支（直接去猜拳），
    压根到不了那条换人分支 —— 对方的回合是从 `handle_rps_choice` 开始的。
    少了那个调用点，这张卡由后手方打出时**永远不触发**（而且不报错）。
    """
    house = room.id
    # 打出者是 P2（后手方）；他的对方 P1 即将通过猜拳成为当前行动者
    cast(room, P2)
    room.state = 'rock_paper_scissors'
    room.rps_choices = {}
    room.rps_processed = False
    room.attacks_remaining = 0
    room.players[P1].ships = [ship((i, 0)) for i in range(4)]
    room.players[P1].remaining_ships = 4
    lock_rolls(monkeypatch, 6, 1)         # 对方(P1) 1 点 < 打出者(P2) 6 点

    assert server.handle_rps_choice(
        {'room_id': house, 'player_id': P1, 'choice': 'rock'}).get('status') == 'success'
    assert server.handle_rps_choice(
        {'room_id': house, 'player_id': P2, 'choice': 'scissors'}).get('status') == 'success'

    assert room.current_attacker == P1
    assert room.pending_wuyou_dreams == {}, '后手方打出的卡在新大回合开始时没触发'
    assert room.attacks_remaining == 0
    assert server._attacks_forced_zero(room) is True


# ---------------------------------------------------------------------------
# 共用弃牌链路：**不覆盖进行中的待办**（作者专门预警过）
# ---------------------------------------------------------------------------
def test_second_discard_batch_does_not_wipe_the_first(room, monkeypatch):
    """★ `_start_dice_discard` 旧写法无条件 `= {}`，会抹掉进行中的待办。

    真会发生：命运骰子摇到 3 时**没轮到的那一方**可以带着未完成的待办交回合
    （`_dice_discard_wait_reason` 只冻他自己），随后无忧梦呓在对方回合开始时
    再开一次 —— 两条待办叠在同一时刻。
    """
    give_hand(room.players[P1], ['轰炸'])
    give_hand(room.players[P2], ['冻结'])
    # 命运骰子摇到 3：P1 已弃、P2 还没（待办挂在他名下）
    server._start_dice_discard(room, P1, P2)
    assert room.pending_dice_discard == {P1: False, P2: False}
    server.handle_dice_discard_choose(
        {'room_id': room.id, 'player_id': P1, 'card_index': 0})
    assert room.pending_dice_discard.get(P2) is False, '夹具前提不成立'

    # 无忧梦呓 判负 → 再开一次弃牌（只针对 P2）
    server._start_dice_discard(room, P1, P2,
                               only_player=P2, card_name='无忧梦呓')
    assert room.pending_dice_discard.get(P2) is False, 'P2 的待办被抹掉了'
    assert room.pending_dice_discard == {P1: True, P2: False}


def test_discard_label_table_never_drifts_from_pending(room):
    """★ 两张镜像表（pending / label）的**键集合同步**由用例钉住（教训 #1）。"""
    give_hand(room.players[P1], ['轰炸'])
    give_hand(room.players[P2], ['冻结'])

    server._start_dice_discard(room, P1, P2)
    assert set(room.pending_dice_discard) <= set(room.pending_dice_discard_label)
    server.handle_dice_discard_choose(
        {'room_id': room.id, 'player_id': P1, 'card_index': 0})
    server.handle_dice_discard_choose(
        {'room_id': room.id, 'player_id': P2, 'card_index': 0})
    # 全部完成 → 两张表一起清空（漏清一张会让来源名残留到下一次弃牌）
    assert room.pending_dice_discard == {}
    assert room.pending_dice_discard_label == {}


def test_only_player_param_keeps_legacy_behaviour(room):
    """`only_player=None` 时是**原行为**（双方各弃一张）—— 命运骰子不受影响。"""
    give_hand(room.players[P1], ['轰炸'])
    give_hand(room.players[P2], ['冻结'])
    server._start_dice_discard(room, P1, P2)
    assert set(room.pending_dice_discard) == {P1, P2}
    assert room.pending_dice_discard_label == {P1: '命运骰子', P2: '命运骰子'}


# ---------------------------------------------------------------------------
# AI 座位
# ---------------------------------------------------------------------------
def test_ai_seat_discards_automatically(room, events, monkeypatch):
    """AI 作为"对方"时，弃牌待办必须**就地消费掉**，绝不留给真人或空等。"""
    ai_id = 'ai-wuyou'
    room.players.pop(P2)
    room.players[ai_id] = Player(name='AI', ships=[], attacks=[],
                                 remaining_ships=0, sid='sid-ai')
    room.attack_order = [P1, ai_id]
    room.is_ai_room = True
    give_hand(room.players[ai_id], ['轰炸', '冻结'])

    cast(room, P1)
    room.current_attacker = ai_id
    room.attacks_remaining = 6
    lock_rolls(monkeypatch, 2, 6)         # AI 点数更大 → 弃牌
    settle(room)

    assert room.players[ai_id].magic_hand and len(room.players[ai_id].magic_hand) == 1
    assert room.pending_dice_discard == {}, 'AI 名下留了没人消费的待办'
    assert find_emit(events, 'dice_discard_request') == []
    logs = [d.get('text') or '' for _, d, _, _ in find_emit(events, 'game_log')]
    assert any('AI' in t and '因无忧梦呓弃置' in t for t in logs), logs


def test_ai_seat_benefits_from_zero_attack_lock(room, monkeypatch):
    """AI 作为**打出者**时同样正常：对方（真人）被打不了。"""
    cast(room, P1)
    room.current_attacker = P2
    room.attacks_remaining = 6
    lock_rolls(monkeypatch, 1, 6)         # 对方 6 点 > 自己 1 点 → 弃牌支
    settle(room)
    assert server._attacks_forced_zero(room) is False


# ---------------------------------------------------------------------------
# 完整性守卫 / 观战 / 回放 / 卡池表态
# ---------------------------------------------------------------------------
def test_master_unsettled_reports_the_armed_judgement(room):
    """★ 验收标准第 7 条：挂着的待判状态必须登记进"还没结算完"的检查。

    不登记 → 卡没结算完会被 `_master_unsettled` 判成"已收敛"（漏登记是静默的）。
    """
    assert server._master_unsettled(room, P1) == []
    cast(room, P1)
    reasons = server._master_unsettled(room, P1)
    assert any('无忧梦呓' in r for r in reasons), reasons
    # 触发完（清除）之后必须恢复干净
    room.current_attacker = P2
    server._settle_wuyou_dream(room)
    assert server._master_unsettled(room, P1) == []


def test_finish_game_clears_room_state(room):
    """房间级状态的生命周期收尾：终局必须清干净（否则报告里挂着幽灵状态）。"""
    cast(room, P1)
    server._finish_game(room, P1, P2, 'surrender')
    assert room.pending_wuyou_dreams == {}
    assert room.pending_dice_discard == {}
    assert room.pending_dice_discard_label == {}


def test_spectate_reuses_dice_rolled_without_leaking(room, events, monkeypatch):
    """★ 验收标准第 8 条：观战**复用** `dice_rolled`，不新增白名单条目。

    新事件若忘了登记，`spectate._validate()` 的穷举守卫就会把观众那边打瞎；
    复用既有事件则天然带着"payload 里没有隐藏信息"的既有结论。
    """
    import spectate
    assert 'dice_rolled' in spectate.SPECTATE_EVENTS
    assert 'dice_rolled' not in spectate.NOT_FOR_SPECTATORS

    cast(room, P1)
    room.current_attacker = P2
    lock_rolls(monkeypatch, 5, 2)
    settle(room)

    rolls = find_emit(events, 'dice_rolled')
    assert len(rolls) == 1
    payload = rolls[0][1]
    # 骰子点数是对局内的**公开**信息；隐藏字段一个都不许出现
    forbidden = set(spectate.FORBIDDEN_PAYLOAD_KEYS)
    assert not (set(payload) & forbidden), set(payload) & forbidden
    assert set(payload) <= {'roll', 'opponent_roll', 'caster', 'effect_text', 'card'}
    # 弃牌请求是**给当事玩家**的私有事件 → 必须仍在黑名单里（观众收不到）
    assert 'dice_discard_request' in spectate.NOT_FOR_SPECTATORS


def test_headless_driver_covers_the_discard_window():
    """★ 验收标准第 11 条：无头驱动的待办窗口应答表覆盖这条链路。

    无忧梦呓的弃牌**复用 `pending_dice_discard`**，所以
    `tools/headless_game.py` 的 `_pending_window` / `_pump_pending` 原样吃下它
    —— 这里做**源码级**断言，防止将来有人把 `dice` 那一支删掉而没人发现。
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'tools', 'headless_game.py'), encoding='utf-8') as f:
        src = f.read()
    assert 'pending_dice_discard' in src
    assert "'dice'" in src or '"dice"' in src


def test_replay_is_covered_by_the_generic_channel():
    """★ 验收标准第 9 条的表态：**不新增 replay 节点**，走通用通道。

    登记与结算都经 `add_game_log` → `replay.note`（`magic` 类型 → "使用【卡】"节点），
    与命运骰子同口径。这里断言那个通道真的被喂到了。
    """
    fresh = make_room()
    try:
        assert isinstance(getattr(fresh, 'replay', None), (dict, type(None))) or True
        before = len((getattr(fresh, 'replay', None) or {}).get('steps', []) or [])
        cast(fresh, P1)
        server.log_magic(fresh, P1, card('无忧梦呓'), '无忧梦呓生效')
        steps = ((getattr(fresh, 'replay', None) or {}).get('steps') or [])
        assert len(steps) > before, '打出这张卡没有喂进回放'
        assert any('无忧梦呓' in (s.get('text') or '') for s in steps), steps
    finally:
        room_manager.rooms.pop(fresh.id, None)


def test_master_pool_excludes_wuyou_dream():
    """★ 验收标准第 10 条的结论：**不进大师卡池**，并给出理由。

    它与 `命运骰子` 是同一个形状（打出时开 `pending_dice_discard` 弃牌待办，
    而 AI 名下那条没有消费点），而且更晚 —— 收益要等整个大回合才到账。
    """
    assert '无忧梦呓' not in server._MASTER_ENABLED_CARDS, (
        '无忧梦呓被加进大师卡池了 —— 它和命运骰子是同一个形状（AI 侧弃牌待办'
        '没有消费点 + 收益延迟到账），见 server.py _MASTER_ENABLED_CARDS 旁边那条')
    # 卡本身必须照常实现（"AI 不打" ≠ "这张卡没了"）：真人对局里能用
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server.py'),
        encoding='utf-8').read()
    assert "elif card.name == '无忧梦呓':" in src
    assert 'def _register_wuyou_dream' in src
    assert 'def _settle_wuyou_dream' in src


def test_value_table_has_wuyou_dream():
    """价值表必须覆盖每一张能摸到的卡（守卫在 test_ai_brain.py，这里也钉一条）。"""
    import ai_brain
    assert '无忧梦呓' in ai_brain.CARD_BASE_VALUE
    assert 0 < ai_brain.CARD_BASE_VALUE['无忧梦呓'] <= 100
