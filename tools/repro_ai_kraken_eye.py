# -*- coding: utf-8 -*-
"""复现：大师 AI 当施法者时的「克苏鲁之眼」把**真人的待选**当成"没选"。

用户原话
────────
    「大师AI使用克苏鲁之眼的通过也很有问题 通过之后都不给我选自己船暴露的机会
      就直接结束了选区并且弹出克苏鲁之眼生效失败：没有选择一艘船暴露 这太诡异了」

复现到的是**哪一层**
──────────────────
服务端 handler 层（无头）。三项可观察事实代替"真人的界面"：

  · 真人的 socket 有没有收到待选请求事件（前端据此弹出"请点选一艘自己的战舰"）；
  · 服务端 `pending_ship_picks` 里有没有真人的 `kraken_eye` 待选；
  · `apply_magic_effect` 的返回值里 `success` 与 `message` 说了什么
    （前端把它显示成"生效"提示 —— 用户看到的那句假话就在这里）。

用法：
    python tools/repro_ai_kraken_eye.py
退出码 1 = 复现到了（有缺陷）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
from server import Player, PlayerShip, Position


EVENTS = []


def install():
    def fake_emit(event, data, to=None, room=None):
        EVENTS.append((event, data, to, room))

    server.emit = fake_emit
    server.socketio.start_background_task = lambda *a, **k: None
    server.socketio.emit = lambda *a, **k: None
    server._maybe_run_ai_turn = lambda *a, **k: None
    server._schedule_chain_timeout = lambda *a, **k: None


def build_room():
    room_id = server.room_manager.create_ai_room('human-0', 'P2', None, 'master')
    room = server.room_manager.get_room(room_id)
    room.players['human-0'] = Player(
        name='P2', ships=[], attacks=[], remaining_ships=0,
        user_id=None, sid='human-0')
    room.init_player_magic('human-0', server.magic_cards)
    ai_id = server._ai_player_id(room)
    for pid in room.players:
        p = room.players[pid]
        p.ships = [PlayerShip(positions=[Position(x=i, y=0)], hits=[]) for i in range(6)]
        p.remaining_ships = 6
        p.max_ships = 6
        p.attacks = []
        p.revealed_positions = []
        p.magic_hand = []
    room.state = 'attacking'
    room.current_attacker = ai_id
    room.current_phase = 'battle'
    room.attack_order = [ai_id, 'human-0']
    room.round = 3
    room.attacks_remaining = 6
    room.magic_deck = [server.MagicCard(n) for n in
                       ['冻结', '轰炸', '增援', '疗愈', '看破！', '无中生有']]
    room.players[ai_id].magic_hand = [server.MagicCard('克苏鲁之眼')]
    # ⚠️ 这张牌的"值不值得打"由 `ai_brain._situational` 的局势乘子决定：
    #    对方已知的情报 ≥ 我已知的情报 → ×0.35（55×0.35=19 < 阈值 50 → 不出）。
    #    所以要把局面摆成"对方比我更了解我的棋盘"（对方攻击过、已有显形记录），
    #    这才是作者实测里它会真的被打出来的那种局面。
    room.players[ai_id].revealed_positions = []            # 我知道对方 0 格
    room.players['human-0'].revealed_positions = [
        Position(x=i, y=0) for i in range(4)]               # 对方知道我 4 格
    return room, ai_id


def main():
    install()
    room, ai_id = build_room()

    print('=' * 76)
    print('复现：大师 AI 打出「克苏鲁之眼」')
    print('=' * 76)

    # ── ① 大师 AI 的候选池里到底有没有这张牌、它给出的目标是什么 ────────
    hand = room.players[ai_id].magic_hand
    print(f'\n[① 卡池与试算]')
    print(f'    克苏鲁之眼 在 _MASTER_ENABLED_CARDS 里：'
          f'{"克苏鲁之眼" in server._MASTER_ENABLED_CARDS}')
    card = hand[0]
    targets = server._master_card_readiness(room, ai_id, card)
    print(f'    _master_card_readiness(克苏鲁之眼) = {targets!r}')
    print(f'    → AI 的"选自己一艘船"要经由 target_data：'
          f'{server._pick_cell_from_target(targets or {})!r}')
    idx, picked_targets = server._ai_choose_card(room, ai_id, 0)
    print(f'    _ai_choose_card → 下标={idx!r} 目标={picked_targets!r} '
          f'（选中的牌={hand[idx].name if isinstance(idx, int) else None!r}）')
    ai_targets_from_readiness = targets

    # ── ② 走 AI 的真实出牌入口 ────────────────────────────────────────
    print(f'\n[② 走 _ai_maybe_play_magic（AI 真实出牌入口）]')
    EVENTS.clear()
    played = server._ai_maybe_play_magic(room, ai_id)
    room = server.room_manager.get_room(room.id)
    print(f'    _ai_maybe_play_magic 返回 = {played}')
    for ev, data, to, _r in EVENTS:
        print(f'    emit {ev} → to={to!r} data={data}')
    res = None
    for ev, data, to, _r in EVENTS:
        if ev == 'message':
            print(f'    ★ 真人在界面上看到的那句：{data.get("text")!r}')
    del res          # 只用来占位，别把下面的判据变量写混

    # ── ③ 直接结算一次，看返回值的 success / message ───────────────────
    print(f'\n[③ apply_magic_effect 的返回值（前端据此显示"生效"）]')
    res = server.apply_magic_effect(room, ai_id, server.MagicCard('克苏鲁之眼'), {})
    print(f'    success={res.success!r}  message={res.message!r}')
    # ③ 这一层的判据：**不许给真人留一个从没被告知过的待选**
    # （⑤ 那一层会故意给真人入队，所以这个判据必须在这里取，不能放到最后）
    leftover_picks = [p for p in (room.pending_ship_picks or [])
                      if p.get('player') == 'human-0']
    print(f'    真人 pending_ship_picks = {leftover_picks}')
    print(f'    真人的待选请求事件 = '
          f'{[d for (e, d, to, _r) in EVENTS if e == "sacrifice_request" and to == "human-0"]}')

    # ── ⑤ 给 AI 一个合法的 target（假设 AI 真能表达"我选这艘船"） ──────
    print(f'\n[⑤ 如果 AI **真的**给得出自己那一格，走到对手那一半]')
    EVENTS.clear()
    res2 = server.apply_magic_effect(room, ai_id, server.MagicCard('克苏鲁之眼'),
                                     {'x': 0, 'y': 0})
    print(f'    success={res2.success!r}  message={res2.message!r}')
    picks = [p for p in (room.pending_ship_picks or [])
             if p.get('player') == 'human-0' and p.get('reason') == 'kraken_eye']
    print(f'    真人 kraken_eye 待选 = {len(picks)} 项')
    print(f'    AI 自己收到的显形位置 = '
          f'{[(p.x, p.y) for p in room.players[ai_id].revealed_positions]}  '
          f'← 对手还没选，这里必然是空')
    honest = (res2.success is not False and picks
              and res2.message != '双方各暴露一艘战舰位置'
              and '等待' in res2.message)
    print(f'    → 文案诚实（没宣称"双方各暴露"）：{honest}')

    # ── 结论 ──────────────────────────────────────────────────────────
    print('\n' + '=' * 76)
    fixed = (ai_targets_from_readiness is None and idx is None and played is False
             and res.success is False and leftover_picks == [] and honest)
    server.room_manager.delete_room(room.id)
    if fixed:
        print('已修复（这是**修之后**的结果）：')
        print('  ① 大师的试算闸门把克苏鲁之眼判成**打不了**（AI 给不出自己那一格），')
        print('  ② 它因此不会被选中、不会被打出、也不会再出现"白打一次又被退回"，')
        print('  ③ 万一走到对手那一半，文案也如实说"等待对方选择"，不再宣称已完成。')
        print('=' * 76)
        return 0
    print('仍有问题：见上面逐项输出。')
    print('=' * 76)
    return 1


if __name__ == '__main__':
    sys.exit(main())
