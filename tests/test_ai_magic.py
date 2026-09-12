# -*- coding: utf-8 -*-
"""AI 出牌（人机对战）回归。

2026-09-13 审计：`_ai_turn_loop` 只会「进战斗→炮击→结束阶段→交回合」，
AI 手里明明有牌却**一张都不出**。现在 AI 会打出一张「安全卡」（见
`_AI_SAFE_CARDS`），本文件锁住三件事：

  1. 白名单里的卡名必须真实存在（防拼写漂移）；
  2. 白名单**不得**包含任何会等待施法者操作的卡 —— 那会让整局卡死；
  3. easy 难度不出牌（保留"打电脑保底能赢"的新手体验）。
"""
import time

import pytest

import server
from server import (ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position,
                    room_manager)

P1 = 'p1'
AI = 'ai-test'


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


def make_room(difficulty='normal'):
    r = GameRoom('ai-room')
    r.is_ai_room = True
    r.ai_difficulty = difficulty
    r.players[AI] = Player(name='AI', ships=[ship((i, 0)) for i in range(6)],
                           attacks=[], remaining_ships=6, sid=AI, user_id=None)
    r.players[P1] = Player(name='human', ships=[ship((i, 1)) for i in range(6)],
                           attacks=[], remaining_ships=6, sid='sid-p1', user_id='u1')
    r.state = 'attacking'
    r.current_attacker = AI
    r.current_phase = 'battle'
    r.attack_order = [AI, P1]
    r.attacks_remaining = 6
    r.round = 1
    room_manager.rooms[r.id] = r
    return r


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)
    room_manager.match_queue = []


# ---------------------------------------------------------------------------
# 1. 白名单本身
# ---------------------------------------------------------------------------
def test_ai_safe_card_names_all_exist():
    names = {c.name for c in server.magic_cards}
    unknown = [n for n in server._AI_SAFE_CARDS if n not in names]
    assert not unknown, f'白名单里有不存在的卡名：{unknown}'


def test_ai_safe_list_excludes_cards_that_need_player_choices():
    """会等待「施法者自己」点选/放置的卡绝不能进白名单（否则整局卡死）。"""
    stall = {'桃园结义', '明智埋葬', '神机妙算', '仁王之盾', '灵气复苏',
             '增援', '死者苏生', '绝处逢生', '回光返照', '神之宣告', '疗愈', '钢筋铁骨'}
    assert not (set(server._AI_SAFE_CARDS) & stall)


@pytest.mark.parametrize('name', sorted(set(server._AI_SAFE_CARDS)))
def test_ai_safe_card_leaves_no_pending_state(room, name):
    """逐张实打：白名单里的卡打完后不得留下待处理状态或未关闭的连锁窗口。"""
    room.players[AI].magic_hand = [card(name)]
    room.players[P1].magic_hand = []          # 对手无速阶3 → 连锁应立刻结算

    played = server._ai_maybe_play_magic(room, AI)

    assert played is True, f'{name} 应当能被 AI 打出'
    assert not room.magic_temp_data.get('pending_placement'), f'{name} 留下待放置状态'
    assert not room.magic_temp_data.get('pending_sacrifice'), f'{name} 留下待牺牲状态'
    assert not room.magic_temp_data.get('pending_shenji'), f'{name} 留下待宣言状态'
    assert room.chain == [] and room.chain_waiting is False, f'{name} 留下了未结算的连锁'
    assert room.current_attacker == AI, f'{name} 不得把回合交出去'


# ---------------------------------------------------------------------------
# 2. 选牌策略
# ---------------------------------------------------------------------------
def test_ai_picks_lowest_speed_safe_card(room):
    room.players[AI].magic_hand = [card('看破！'), card('无中生有')]   # 速2 / 速1
    assert server._ai_choose_magic_card(room, AI) == 1, '优先出速阶更低的卡'


def test_ai_ignores_unsafe_cards(room):
    """手里只有"需要点选"的卡时，AI 应当选择不出牌，而不是把局面卡死。"""
    room.players[AI].magic_hand = [card('桃园结义'), card('明智埋葬'), card('增援')]
    assert server._ai_choose_magic_card(room, AI) is None
    assert server._ai_maybe_play_magic(room, AI) is False
    assert len(room.players[AI].magic_hand) == 3, '不能白扔牌'


def test_ai_skips_cards_not_playable_in_current_phase(room):
    room.current_phase = 'end'      # 结束阶段只能出 Freezing！
    room.players[AI].magic_hand = [card('无中生有')]
    assert server._ai_choose_magic_card(room, AI) is None
    room.current_phase = 'battle'
    assert server._ai_choose_magic_card(room, AI) == 0


# ---------------------------------------------------------------------------
# 3. 难度分档
# ---------------------------------------------------------------------------
def test_easy_difficulty_never_plays(room):
    room.ai_difficulty = 'easy'
    room.players[AI].magic_hand = [card('无中生有')]
    assert server._ai_maybe_play_magic(room, AI) is False
    assert len(room.players[AI].magic_hand) == 1


def test_normal_difficulty_plays_and_consumes_card(room):
    room.ai_difficulty = 'normal'
    room.players[AI].magic_hand = [card('无中生有')]
    before = len(room.players[AI].magic_hand)

    assert server._ai_maybe_play_magic(room, AI) is True

    assert len(room.players[AI].magic_hand) == before - 1, '打出的牌应从手牌移除'
    assert room.magic_history, '应当留下出牌记录'


def test_unknown_difficulty_falls_back_to_normal():
    r = GameRoom('ai-room-2')
    try:
        room_manager.create_ai_room('sid-x', 'x', None, 'impossible')
        created = [rm for rm in room_manager.get_all_rooms().values() if rm.is_ai_room]
        assert created and created[-1].ai_difficulty == 'normal'
    finally:
        for rm_id, rm in list(room_manager.get_all_rooms().items()):
            if rm.is_ai_room:
                room_manager.rooms.pop(rm_id, None)

# ---------------------------------------------------------------------------
# 4. 困难难度：AI 会用【失灵！】响应连锁
# ---------------------------------------------------------------------------
def _chain_room(difficulty='hard', ai_hand=('失灵！',), top_card='无中生有', top_caster=None):
    r = make_room(difficulty)
    if ai_hand:
        r.players[AI].magic_hand = [card(n) for n in ai_hand]
    r.players[P1].magic_hand = []
    r.chain = [ChainItem(top_caster or P1, card(top_card), [], time.time())]
    r.chain_waiting = True
    r.chain_window = AI
    r.chain_timer = 1
    return r


def test_easy_and_normal_ai_never_join_chain(room):
    room.players[AI].magic_hand = [card('失灵！')]
    room.chain = [ChainItem(P1, card('无中生有'), [], time.time())]
    for level in ('easy', 'normal'):
        room.ai_difficulty = level
        assert server._can_respond_chain(room, AI) is False, level


def test_hard_ai_joins_chain_only_with_lingwu(room):
    room.chain = [ChainItem(P1, card('无中生有'), [], time.time())]
    room.ai_difficulty = 'hard'
    room.players[AI].magic_hand = [card('冻结')]        # 没有失灵！
    assert server._can_respond_chain(room, AI) is False
    room.players[AI].magic_hand = [card('失灵！')]
    assert server._can_respond_chain(room, AI) is True


def test_hard_ai_wont_negate_its_own_card(room):
    room.chain = [ChainItem(AI, card('无中生有'), [], time.time())]
    room.ai_difficulty = 'hard'
    room.players[AI].magic_hand = [card('失灵！')]
    assert server._can_respond_chain(room, AI) is False


@pytest.mark.parametrize('top', ['看破！', '加百列之光'])
def test_hard_ai_wont_negate_immune_cards(room, top):
    """卡面写明了看破！/加百列之光 不受失灵！影响，AI 不该白康一次。"""
    room.chain = [ChainItem(P1, card(top), [], time.time())]
    room.ai_difficulty = 'hard'
    room.players[AI].magic_hand = [card('失灵！')]
    assert server._can_respond_chain(room, AI) is False


def test_ai_chain_respond_negates_opponent_card(monkeypatch):
    monkeypatch.setattr(server.time, 'sleep', lambda *_: None)
    r = _chain_room()
    try:
        human_hand_before = len(r.players[P1].magic_hand)
        ai_hand_before = len(r.players[AI].magic_hand)

        server._ai_chain_respond(r.id, 1)

        assert len(r.players[AI].magic_hand) == ai_hand_before - 1, 'AI 的失灵！应当被消耗'
        assert len(r.players[P1].magic_hand) == human_hand_before, '被康掉的卡不得再产生效果'
        assert r.chain == [] and r.chain_waiting is False, '连锁应当结算完毕'
        names = [getattr(h.get('card'), 'name', h.get('card')) for h in r.magic_history]
        assert '失灵！' in names, 'AI 的出牌要留在历史里'
    finally:
        room_manager.rooms.pop(r.id, None)


def test_ai_chain_respond_gives_up_when_it_cannot_negate(monkeypatch):
    monkeypatch.setattr(server.time, 'sleep', lambda *_: None)
    r = _chain_room(top_card='看破！')
    try:
        server._ai_chain_respond(r.id, 1)
        # 放弃后窗口顺延给对手；对手没有速阶3 → 连锁结算完
        assert r.chain == [], '放弃也必须把连锁推进下去，不能留着半开窗口'
    finally:
        room_manager.rooms.pop(r.id, None)


def test_ai_chain_respond_ignores_stale_token(monkeypatch):
    monkeypatch.setattr(server.time, 'sleep', lambda *_: None)
    r = _chain_room()
    try:
        server._ai_chain_respond(r.id, 99)      # 过期令牌
        assert r.chain_waiting is True, '过期任务不得改动窗口'
        assert len(r.chain) == 1
    finally:
        room_manager.rooms.pop(r.id, None)
