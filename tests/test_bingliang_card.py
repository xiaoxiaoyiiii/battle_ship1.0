# -*- coding: utf-8 -*-
"""兵粮寸断（判定魔法卡，2026-09-25 新增）的回归测试。

卡面（作者原话，不许自行改动规则）：
  这张牌**只进行一次判定**。当**对方的准备阶段开始时**，摇一次骰子：
    · 点数 **< 3**  → 判定失败，卡牌结束，**不产生任何效果**；
    · 点数 **≥ 3**  → 对方**接下来的两个准备阶段**各跳过一次摸牌，
                       两个准备阶段处理完后清除状态。
  只跳过准备阶段的摸牌，**不影响其他抽牌来源、其他玩家或其他效果**。

按 CLAUDE.md §7「改卡要同步 4 处」+ §10 教训 #11「新增房间级状态三件齐」覆盖：
  · `static/magic_card.json` 与 `static/magic_cards.js` 位置与关键字段一致；
  · `apply_magic_effect` 的判定分支登记延迟判定（且**打出时不摇骰子**）；
  · **只判定一次**：后续两个准备阶段只消耗额度、不再摇骰子；
  · 连续两个准备阶段跳过摸牌，之后恢复；
  · **其他抽牌来源不被误伤**（`draw_card` 本身不拦）；
  · 房间级状态的生命周期（`__init__` / 消费点 / 终局清理 / 大师"未结算"判据）；
  · 判定时点排在发放摸牌**之后**（先手/后手口径一致），源码级守卫。
"""
import json
import os

import pytest

import server
from server import GameRoom, MagicCard, Player, room_manager

P1, P2 = 'p1', 'p2'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# 基础设施（与 test_wuyou_dream_card / test_dice_card 同口径）
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


def make_room(deck_size=40):
    room = GameRoom('test-bingliang-room')
    room.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid-p1')
    room.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    # 造一副足够的牌堆，避免"牌堆空"与"被跳过"混为一谈
    room.magic_deck = [MagicCard(name=f'测试牌{i}', speed=1, type='普通', description='x')
                       for i in range(deck_size)]
    return room


def card(name='兵粮寸断'):
    return MagicCard(name=name)


def _result(caster=P1):
    """与 `apply_magic_effect` 内部同款的结果对象（只有 `.message` 会被用到）。"""
    return server.ChainResult(card=card(), caster=caster, success=True, message='')


def fix_roll(monkeypatch, value):
    """把判定点数固定住（本卡的判定只用 `random.randint(1, 6)`）。"""
    monkeypatch.setattr(server.random, 'randint', lambda a, b: value)


def dice_events(captured):
    return [d for (e, d, _t, _r) in captured if e == 'dice_rolled']


def bingliang_logs(room):
    return [l for l in room.game_logs if '兵粮寸断' in (l.get('text') or '')]


def _deal(room, winner, loser):
    """复刻 `handle_rps_choice` 的发放摸牌（走**同一个**判据）。

    ⚠️ 这里只复刻"发放"这一小段；接线本身由
       `test_deal_site_is_wired_to_the_guard` 做源码级守卫（这类 bug pytest 抓不到）。
    """
    winner_cards = [] if server._bingliang_consume_skip(room, winner) else [room.draw_card(winner)]
    if server._bingliang_consume_skip(room, loser):
        loser_cards = []
    else:
        loser_cards = [room.draw_card(loser), room.draw_card(loser)]
    return winner_cards, loser_cards


# ---------------------------------------------------------------------------
# 1. 卡牌可被识别（4 处同步）
# ---------------------------------------------------------------------------
def test_card_present_in_backend_json():
    with open(os.path.join(ROOT, 'static', 'magic_card.json'), encoding='utf-8') as f:
        cards = json.load(f)
    mine = [c for c in cards if c['name'] == '兵粮寸断']
    assert len(mine) == 1, f'后端卡表应有且只有一条兵粮寸断，实际 {len(mine)}'
    assert mine[0]['speed'] == 1 and mine[0]['type'] == '判定', mine[0]
    assert len(cards) == 50, f'卡池应为 50 条，实际 {len(cards)}'


def test_card_present_in_frontend_js_same_position():
    """前后端**顺序与关键字段**一致（一致性测试不校验 description，需人工留意）。"""
    with open(os.path.join(ROOT, 'static', 'magic_card.json'), encoding='utf-8') as f:
        backend = json.load(f)
    with open(os.path.join(ROOT, 'static', 'magic_cards.js'), encoding='utf-8') as f:
        js_src = f.read()

    assert '{ name: "兵粮寸断", speed: 1, type: "判定", description: ' in js_src, (
        '前端那一行的字段顺序/写法与既有行不一致')

    b_seq = [(c['name'], c['speed'], c['type']) for c in backend]
    idx = [i for i, x in enumerate(b_seq) if x[0] == '兵粮寸断'][0]
    assert b_seq[idx - 1][0] == '无忧梦呓', f'后端顺序不对：前一张是 {b_seq[idx - 1]}'

    names = [ln.split('name: "')[1].split('"')[0]
             for ln in js_src.split('\n') if 'name: "' in ln]
    assert '兵粮寸断' in names and '无忧梦呓' in names
    assert names[names.index('兵粮寸断') - 1] == '无忧梦呓', '前端顺序不对'


def test_card_is_not_hidden_and_has_ai_value():
    assert '兵粮寸断' not in server.HIDDEN_CARD_NAMES, '能摸到的卡不该被隐藏'
    import ai_brain
    assert '兵粮寸断' in ai_brain.CARD_BASE_VALUE, '价值表必须覆盖每一张能摸到的卡'
    assert 0 < ai_brain.CARD_BASE_VALUE['兵粮寸断'] <= 100




# ---------------------------------------------------------------------------
# 2. 打出时只登记、不摇骰子
# ---------------------------------------------------------------------------
def test_play_registers_without_rolling(room, events):
    res = server.apply_magic_effect(room, P1, card(), {})
    assert res.success is True, res.message
    assert room.pending_bingliang == {P1: 1}, room.pending_bingliang
    assert dice_events(events) == [], '打出时不许摇骰子（判定点在对方准备阶段）'
    assert not room.bingliang_skip_draw, '还没判定，不该有跳过额度'


def test_two_copies_are_counted_not_overwritten(room):
    """同名卡两张都要算数（教训 #29：单槽 = 隐藏的数据丢失）。"""
    server.apply_magic_effect(room, P1, card(), {})
    server.apply_magic_effect(room, P1, card(), {})
    assert room.pending_bingliang == {P1: 2}, room.pending_bingliang


# ---------------------------------------------------------------------------
# 3. 失败点数不产生任何效果
# ---------------------------------------------------------------------------
def test_fail_roll_produces_no_effect(room, events, monkeypatch):
    for roll in [1, 2]:
        events.clear()
        fix_roll(monkeypatch, roll)
        server._register_bingliang(room, P1, _result())
        room.current_attacker = P2          # 对方（P2）的准备阶段开始
        server._settle_bingliang(room)

        assert room.pending_bingliang == {}, '判定完就该 pop 掉'
        assert room.bingliang_skip_draw == {}, f'{roll} 点应判定失败、不留任何额度'
        assert len(dice_events(events)) == 1
        assert dice_events(events)[0]['roll'] == roll
        assert dice_events(events)[0].get('card') == '兵粮寸断'
        logs = bingliang_logs(room)
        assert any('判定失败' in l['text'] for l in logs), logs


def test_fail_roll_still_lets_target_draw(room, events, monkeypatch):
    """失败后对方照常摸牌（"不产生任何效果"）。"""
    fix_roll(monkeypatch, 1)
    server._register_bingliang(room, P1, _result())
    room.current_attacker = P2
    server._settle_bingliang(room)
    _w, l = _deal(room, P1, P2)
    assert len(l) == 2, '判定失败就不该跳过任何摸牌'


# ---------------------------------------------------------------------------
# 4. 成功点数：判定只发生一次
# ---------------------------------------------------------------------------
def test_success_rolls_exactly_once(room, events, monkeypatch):
    fix_roll(monkeypatch, 4)
    server._register_bingliang(room, P1, _result())

    room.current_attacker = P2          # 对方准备阶段 #1：判定
    server._settle_bingliang(room)
    assert len(dice_events(events)) == 1, '第一次准备阶段应摇一次'
    assert room.bingliang_skip_draw == {P2: server.BINGLIANG_SKIP_PHASES}

    # 后续准备阶段：**不许再摇骰子**
    server._settle_bingliang(room)
    server._settle_bingliang(room)
    assert len(dice_events(events)) == 1, (
        f'判定只应发生一次，实际摇了 {len(dice_events(events))} 次')
    assert room.pending_bingliang == {}, '判定完就该 pop 掉'


def test_single_roll_not_opponent_contest(room, events, monkeypatch):
    """本卡是**单方判定**：`dice_rolled` 不带 `opponent_roll`（与无忧梦呓的拼点区分）。"""
    fix_roll(monkeypatch, 4)
    server._register_bingliang(room, P1, _result())
    room.current_attacker = P2
    server._settle_bingliang(room)
    data = dice_events(events)[0]
    assert 'opponent_roll' not in data, data
    assert data.get('caster') == P1


# ---------------------------------------------------------------------------
# 5. 连续两个准备阶段跳过摸牌，之后恢复
# ---------------------------------------------------------------------------
def test_two_phases_skipped_then_restored(room, events, monkeypatch):
    fix_roll(monkeypatch, 3)                       # 3 点 = 刚好成功
    server._register_bingliang(room, P1, _result())

    # 对方（P2）的准备阶段 #1：判定 → 挂 2 次额度（**这一个阶段照常摸牌**）
    room.current_attacker = P2
    server._settle_bingliang(room)

    # 准备阶段 #2：P2 的发放被跳过，P1 不受影响
    hand_p2 = len(room.players[P2].magic_hand)
    w, l = _deal(room, P1, P2)
    assert l == [], '第 2 个准备阶段：P2 的发放应被跳过'
    assert len(room.players[P2].magic_hand) == hand_p2
    assert len(w) == 1, 'P1 不受影响，照常摸牌'
    assert room.bingliang_skip_draw == {P2: 1}, room.bingliang_skip_draw
    assert len(dice_events(events)) == 1, '跳过时不许再摇骰子'

    # 准备阶段 #3：仍跳过 → 额度用完、状态清除
    w2, l2 = _deal(room, P1, P2)
    assert l2 == [], '第 3 个准备阶段：仍应跳过'
    assert len(w2) == 1
    assert room.bingliang_skip_draw == {}, '两次用完必须清除状态'

    # 之后（= 第三个"对方的准备阶段"之后）：恢复正常摸牌
    hand_p2b = len(room.players[P2].magic_hand)
    _w3, l3 = _deal(room, P1, P2)
    assert len(l3) == 2, '恢复：后手应重新摸到 2 张'
    assert len(room.players[P2].magic_hand) == hand_p2b + 2
    assert len(dice_events(events)) == 1, '整条链路只判定一次'


def test_skip_covers_whole_preparation_deal(room, events, monkeypatch):
    """跳过的粒度是"这一整个准备阶段的发放"，不是"其中一张"。"""
    fix_roll(monkeypatch, 4)
    server._register_bingliang(room, P1, _result())
    room.current_attacker = P2
    server._settle_bingliang(room)
    _w, l = _deal(room, P1, P2)
    assert len(l) == 0, '后手那 2 张属于同一个准备阶段动作，应整体跳过'
    assert len(room.players[P2].magic_hand) == 0
    skipped = [l for l in bingliang_logs(room) if '摸牌被跳过' in l['text']]
    assert skipped, '跳过要有玩家可见的日志'


# ---------------------------------------------------------------------------
# 6. 其他抽牌来源 / 其他玩家不被误伤
# ---------------------------------------------------------------------------
def test_other_draw_sources_are_not_affected(room, events, monkeypatch):
    """额度挂在 P2 身上时，**非准备阶段**的抽牌一律照常。"""
    fix_roll(monkeypatch, 4)
    server._register_bingliang(room, P1, _result())
    room.current_attacker = P2
    server._settle_bingliang(room)
    assert room.bingliang_skip_draw == {P2: 2}

    # ① 直接调底层 draw_card —— 不是"准备阶段的发放"，不该被拦
    got = room.draw_card(P2)
    assert got is not None, '其他抽牌来源被误伤了：draw_card 本身不该被拦截'
    assert room.bingliang_skip_draw == {P2: 2}, '非准备阶段的抽牌不许消耗额度'

    # ② 走一张真实的"摸两张"卡（无中生有）验证同样结论
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.players[P1].magic_hand = [card('无中生有')]
    before = len(room.players[P1].magic_hand)
    res = server.apply_magic_effect(room, P1, card('无中生有'), {})
    assert res.success is True, res.message
    assert len(room.players[P1].magic_hand) == before + 2, '无中生有应照常摸 2 张'
    assert room.bingliang_skip_draw == {P2: 2}, '别的卡不该消耗跳过额度'


def test_other_player_is_not_affected(room, events, monkeypatch):
    fix_roll(monkeypatch, 4)
    server._register_bingliang(room, P1, _result())
    room.current_attacker = P2
    server._settle_bingliang(room)
    w, _l = _deal(room, P1, P2)
    assert len(w) == 1, '额度只挂 P2，P1 照常摸牌'


def test_skip_does_not_leak_between_players(room, events, monkeypatch):
    """两份待判定互相独立：只结算"对方正好是当前行动者"的那一份。"""
    fix_roll(monkeypatch, 4)
    server._register_bingliang(room, P1, _result())
    server._register_bingliang(room, P2, _result())
    room.current_attacker = P2          # 只该结算"打在 P1 身上"的那份（对方 = P2）
    server._settle_bingliang(room)
    assert room.bingliang_skip_draw == {P2: 2}, room.bingliang_skip_draw
    assert room.pending_bingliang == {P2: 1}, (
        'P2 打出的那份要留到 P2 的对方（= P1）的回合才结算')


# ---------------------------------------------------------------------------
# 7. 生命周期（教训 #11：__init__ / 消费点 / 终局清理）
# ---------------------------------------------------------------------------
def test_room_state_initialized():
    fresh = GameRoom('test-bingliang-init')
    try:
        assert fresh.pending_bingliang == {}
        assert fresh.bingliang_skip_draw == {}
    finally:
        room_manager.rooms.pop('test-bingliang-init', None)


def test_finish_game_clears_state(room):
    room.pending_bingliang = {P1: 1}
    room.bingliang_skip_draw = {P2: 2}
    server._finish_game(room, P1, P2, 'test')
    assert room.pending_bingliang == {}, '终局必须清掉待判定，否则房间被判成没收敛'
    assert room.bingliang_skip_draw == {}, '跳过额度不许带进同一房间的下一局'


def test_unsettled_reports_pending_but_not_active_skips(room):
    """待判定算"没结算完"；**已判定通过、还剩几次跳过**不算（它要跨两个准备阶段）。"""
    room.pending_bingliang = {P1: 1}
    assert any('兵粮寸断' in r for r in server._master_unsettled(room, P2)), '待判定应上报'
    room.pending_bingliang = {}
    room.bingliang_skip_draw = {P2: 2}
    assert not any('兵粮寸断' in r for r in server._master_unsettled(room, P2)), (
        '已落地的持续状态不该让房间被判成"没收敛"')


# ---------------------------------------------------------------------------
# 8. 源码级守卫：接线（这类 bug pytest 抓不到，见教训 #19/#38）
# ---------------------------------------------------------------------------
