# -*- coding: utf-8 -*-
"""绝处逢生「击杀即胜」必须活到对局结束，而不是只有发动当回合（作者反馈 2026-09-19）。

作者原话：
    「他的击中对方的船自己直接获胜的效果只会在绝处逢生生效的那一个回合有效
      到了下一个回合就没有这个效果了
      我的本意是只要绝处逢生通过了 接下来所有回合只要自己的攻击打死了对方的船
      那就直接判定自己获胜」

根因是**一个标记兼职两件事**：`last_stand` 同时表示
  ① 发动回合内自己的其余魔法卡全部无效（卡面写「在……生效的回合」→ 该过期）
  ② 击杀对方任何一艘船即直接获胜（作者裁定 → 该永久）
于是 ② 跟着 ① 一起在换小回合时被清掉。

更隐蔽的一层：换小回合的清理**另有一份写死的内联白名单**，
而常量 `FLAGS_KEEP_ACROSS_TURN` 的注释还指着它说"分类见这里"——
两个名单互相漂移，任何新标记都会在换回合时无声消失。这次一并收口成一份。

这里钉住三层：标记的**生命周期**、**真的跨回合还能赢**、以及**判胜必须真击沉**。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    """拦截 socket emit；并关掉优先权询问，别让 end_turn 卡在阶段转换窗口上。"""
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task', lambda t, *a, **k: None)
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_priority_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_has_request_context', lambda: False)
    return captured


def make_room():
    room = GameRoom('last-stand-win-room')
    # P1：6 艘单格船（发动绝处逢生会把它们全部牺牲掉）
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p1')
    # P2：6 艘单格船，摆在 y=1 方便直接开炮；其中 (0,1) 那艘打一炮就沉（单格）
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(i, 1)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room.magic_deck = [MagicCard(n) for n in ['冻结', '疗愈', '绝处逢生']]
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def play_last_stand(room, caster=P1, place=(1, 0)):
    """走真实结算发动绝处逢生，并完成"唯一一艘船"的放置。"""
    room.players[caster].magic_hand = [MagicCard('绝处逢生')]
    res = server.apply_magic_effect(room, caster, MagicCard('绝处逢生'), {})
    assert res.success is True, res.message
    return server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': caster, 'position': {'x': place[0], 'y': place[1]}})


def attack(room, x, y, attacker=P1):
    return server.handle_attack({'room_id': room.id, 'player_id': attacker, 'x': x, 'y': y})


def end_turn_as(room, player):
    room.current_attacker = player
    room.current_phase = 'end'
    return server.end_turn({'room_id': room.id, 'player_id': player})


def game_over_events(events):
    return [d for e, d, _t, _r in events if e == 'game_over']


# ===========================================================================
# 1. 发动当场：两个标记都要打上，且是【两个】而不是一个
# ===========================================================================
def test_playing_the_card_arms_both_flags(room):
    """★ 发动后既锁卡、也挂上击杀即胜。"""
    play_last_stand(room)

    flags = room.players[P1].effect_flags
    assert flags.last_stand is True, '发动回合要锁住自己的其余魔法卡'
    assert flags.last_stand_win is True, '要挂上"击杀即胜"'


# ===========================================================================
# 2. 生命周期：锁卡过期，击杀即胜留下
# ===========================================================================
def test_lock_expires_but_win_survives_turn_switch(room):
    """★ 核心回归：换小回合后锁卡解除，但"击杀即胜"还在。

    这就是作者报的那条 —— 此前两者一起被清，效果只活一个回合。
    """
    play_last_stand(room)

    end_turn_as(room, P1)

    flags = room.players[P1].effect_flags
    assert flags.last_stand is False, '锁卡只持续发动回合，换回合该解除'
    assert flags.last_stand_win is True, \
        '击杀即胜必须留下 —— 它活到对局结束，不该跟着锁卡一起过期'


def test_win_flag_survives_big_round_switch(room):
    """大回合（重新猜拳）也不能把"击杀即胜"清掉。"""
    play_last_stand(room)

    # P2 交回合 → next_index 绕回 0，进大回合分支
    end_turn_as(room, P2)

    assert room.players[P1].effect_flags.last_stand_win is True, \
        '大回合切换也不能清掉击杀即胜'


def test_win_flag_is_not_cleared_by_prune(room):
    """直接钉住两份白名单：小回合与大回合都必须保留 last_stand_win。"""
    assert 'last_stand_win' in server.FLAGS_KEEP_ACROSS_TURN
    assert 'last_stand_win' in server.FLAGS_KEEP_ACROSS_ROUND
    # 反证：锁卡标记不该进任何一份白名单
    assert 'last_stand' not in server.FLAGS_KEEP_ACROSS_TURN
    assert 'last_stand' not in server.FLAGS_KEEP_ACROSS_ROUND


# ===========================================================================
# 3. 真正跨回合还能赢（端到端，而不是只看标记）
# ===========================================================================
def test_kill_wins_on_the_following_turn(room, events):
    """★ 换了回合之后打死对方一艘船，依然直接获胜。"""
    play_last_stand(room)
    end_turn_as(room, P1)          # 换到下一个回合（原实现就是在这里丢的效果）

    # 新回合轮到 P1：回到战斗阶段
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attacks_remaining = 6
    events.clear()

    attack(room, 0, 1)             # (0,1) 是单格船，一炮即沉

    assert room.state == 'game_over', f'击杀敌舰应当直接获胜，实际 state={room.state}'
    assert room.winner == P1
    got = game_over_events(events)
    assert got and got[-1]['winner'] == P1, '必须广播 game_over 给双方'


def test_kill_wins_two_big_rounds_later(room, events):
    """★ 再过两个大回合也依然有效 —— 效果活到对局结束，不是"下一个回合"。"""
    play_last_stand(room)
    end_turn_as(room, P1)
    end_turn_as(room, P2)          # 大回合
    end_turn_as(room, P1)          # 再换一个小回合
    end_turn_as(room, P2)          # 再一个大回合

    assert room.players[P1].effect_flags.last_stand_win is True

    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attacks_remaining = 6
    events.clear()

    attack(room, 1, 1)

    assert room.winner == P1, '无论隔了多少回合，击杀即胜都应生效'


# ===========================================================================
# 4. 反证：不该赢的不能赢
# ===========================================================================
def test_sinking_a_ship_on_the_very_turn_also_wins(room, events):
    """反证的另一半：发动当回合击杀当然也要赢（别把新判据改得太严）。"""
    play_last_stand(room)
    events.clear()

    attack(room, 0, 1)

    assert room.winner == P1, '发动当回合击杀同样要获胜'


def test_plain_hit_does_not_win(room, events):
    """★ 「击杀」≠「命中」：打在空格上不获胜。"""
    play_last_stand(room)
    events.clear()

    attack(room, 5, 5)             # 空格，什么都没打中

    assert room.state != 'game_over', '没打死船就不该获胜'
    assert not room.winner, f'不该有胜者，实际 winner={room.winner!r}'


def test_hitting_without_sinking_does_not_win(room, events):
    """★ 大船挨了一炮但没沉，不算"击杀"，不能获胜。"""
    # 把 (0,1) 换成一艘两格船，一炮打不沉
    room.players[P2].ships[0] = PlayerShip(
        positions=[Position(0, 1), Position(0, 2)], hits=[])
    play_last_stand(room)
    events.clear()

    attack(room, 0, 1)             # 打中但只掉一半

    assert room.state != 'game_over', \
        '船还没沉就不是击杀，不该获胜（原实现只判"造成伤害"）'
    assert not room.winner, f'不该有胜者，实际 winner={room.winner!r}'


def test_shielded_hit_does_not_win(room, events):
    """被仁王之盾挡下的一炮没造成伤害，更谈不上击杀。"""
    room.players[P2].ships[0].shield = True
    play_last_stand(room)
    events.clear()

    attack(room, 0, 1)

    assert room.state != 'game_over', '盾挡下的攻击不算击杀'
    assert not room.winner, f'不该有胜者，实际 winner={room.winner!r}'


def test_flag_without_the_card_still_wins(room, events):
    """直接置标记也要判胜（隔离卡牌发动流程，单独钉判据本身）。"""
    room.players[P1].effect_flags.last_stand_win = True
    events.clear()

    attack(room, 0, 1)

    assert room.winner == P1


def test_lock_alone_does_not_grant_a_win(room, events):
    """★ 反证：只有锁卡标记（last_stand）时不能获胜。

    原实现读的就是这个标记，所以这条能抓住"判据读错标记"的回归。
    """
    room.players[P1].effect_flags.last_stand = True
    events.clear()

    attack(room, 0, 1)

    assert room.state != 'game_over', '锁卡不等于击杀即胜，不该获胜'
    assert not room.winner, f'不该有胜者，实际 winner={room.winner!r}'


def test_opponent_cannot_borrow_the_effect(room, events):
    """★ 效果只归发动者：P2 打沉 P1 的船不能靠 P1 的效果获胜。"""
    room.players[P1].effect_flags.last_stand_win = True
    room.current_attacker = P2
    events.clear()

    attack(room, 0, 0, attacker=P2)

    assert room.winner != P2, '效果是施法者自己的，不能给对方用'
    assert room.state != 'game_over'


# ===========================================================================
# 5. 重连快照：两个标记都要能恢复，且不能互相顶替
# ===========================================================================
def test_room_sync_exposes_both_flags(room):
    """★ 重连后前端要能分辨"锁卡"和"击杀即胜" —— 两者生命周期不同。"""
    play_last_stand(room)

    sync = server._build_room_sync(room, P1)
    assert sync['last_stand_lock'] is True and sync['last_stand_win'] is True

    # 换回合后再取一次：锁卡没了，击杀即胜还在
    end_turn_as(room, P1)
    sync = server._build_room_sync(room, P1)
    assert sync['last_stand_lock'] is False, '锁卡过期后必须下发 False，否则前端继续拦出牌'
    assert sync['last_stand_win'] is True, '击杀即胜要一直下发'

def test_room_sync_does_not_leak_room_effects_into_active_effects(room):
    """★ `active_effects` 只发玩家身上的标记，不能混进房间级效果。

    此前它发的是 `room.game_effects.keys()`，而 last_stand_cells /
    last_stand_owner 都恰好以 'last_stand' 开头 —— 于是"候选格还在场"的
    任何时刻，前端都按前缀匹配判定"锁卡生效中"，把玩家的牌白拦下来。
    """
    play_last_stand(room)

    sync = server._build_room_sync(room, P1)
    active = sync['active_effects']
    assert 'last_stand_cells' not in active, \
        f'房间级效果不该出现在 active_effects 里，实际={active}'
    assert 'last_stand_owner' not in active
    # 而真正的玩家标记要在
    assert 'last_stand_win' in active


# ===========================================================================
# 6. 角标：两条分开，且各自的失效时机写对
# ===========================================================================
def test_badges_show_two_separate_effects(room):
    """★ 角标不能合成一条 —— 合成后玩家无法判断"还能不能靠击杀赢"。"""
    play_last_stand(room)

    badges = server._effect_badges(room.players[P1])
    by_key = {b['key']: b for b in badges}
    assert 'last_stand' in by_key and 'last_stand_win' in by_key, by_key
    assert by_key['last_stand']['expires'] == server._EFFECT_EXPIRY_TURN
    assert by_key['last_stand_win']['expires'] == server._EFFECT_EXPIRY_MATCH
    # ⚠️ 卡名必须都是「绝处逢生」—— 浮层靠 name 回查卡面原文，
    # 写成「绝处逢生·击杀即胜」就取不到说明（test_effect_badges 钉着这条契约）。
    assert by_key['last_stand']['name'] == '绝处逢生'
    assert by_key['last_stand_win']['name'] == '绝处逢生'
    # 但**显示名**必须能区分，否则两个角标长得一模一样
    assert by_key['last_stand']['label'] != by_key['last_stand_win']['label'], by_key
    assert by_key['last_stand_win']['label'] == '绝处逢生·击杀即胜'
    # 说明文字两条都要取到（取空就是又把卡名写花了）
    assert by_key['last_stand']['description'], '锁卡角标要能取到卡面说明'
    assert by_key['last_stand_win']['description'] == by_key['last_stand']['description']


def test_badge_survives_turn_switch_while_lock_goes_away(room):
    """换回合后角标只剩"击杀即胜"那一条。"""
    play_last_stand(room)
    end_turn_as(room, P1)

    keys = {b['key'] for b in server._effect_badges(room.players[P1])}
    assert keys == {'last_stand_win'}, keys
