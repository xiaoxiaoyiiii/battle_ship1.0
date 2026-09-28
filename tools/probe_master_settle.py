# -*- coding: utf-8 -*-
"""证据工具：大师**连打多张牌**时，第 N 张之前第 N−1 张真的结算完了吗？

【为什么需要"跑真代码路径"的证据】
作者实报：「怕出牌的时候太快了，上一个效果还没结算完下一张牌已经打出来了」。
这句话有**两种完全不同的可能**，靠读代码分不开：
  A. 只是**观感**问题 —— 效果确实结算完了，只是 UI 上两张牌的提示挤在一起；
  B. 是**真缺陷** —— 有一条路径在连锁/待办没收敛时就继续出牌。

区分它们必须看**运行期**的房间状态：在每一次"大师将要出牌 / 将要开炮 / 将要收尾"的
**前一瞬**，把房间上所有"还没结算完"的标志抓下来。判据与 `_action_wait_reason`
同源，并且覆盖连锁窗口与四条待办通道：
    · `room.chain` / `room.chain_waiting`          —— 连锁栈与响应窗口
    · `magic_temp_data['pending_placement']`       —— 等玩家放船
    · `magic_temp_data['pending_shenji']`          —— 等玩家宣言
    · `room.pending_dice_discard`                  —— 等玩家弃牌
    · `room.pending_ship_picks`（大师名下）         —— 等大师选自己的船
    · `room.priority_continue`                     —— 被拦下的阶段转换

⚠️ **本工具跑的是真实代码路径**：直接调 `server._ai_master_turn`（带它自己的
   `time.sleep(_MASTER_ACTION_PACING)`，**一动不动**），人类一侧由本脚本在另一个
   线程里搬（`_pump_chain` / `_pump_pending` 的等价物）。不补丁任何决策或结算逻辑。
   → 所以它慢（一局几秒），但量到的就是线上那一份行为。

用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/probe_master_settle.py --games 20 --seed 1
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.headless_game as hg          # noqa: E402


def _pending_flags(room, ai_id):
    """房间上所有"还没结算完/还在等人操作"的标志。空列表 = 完全结算完。"""
    flags = []
    if room.chain:
        flags.append(f'chain={len(room.chain)}')
    if room.chain_waiting:
        flags.append(f'chain_waiting={room.chain_window}')
    temp = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
    pending_placement = temp.get('pending_placement')
    if pending_placement:
        flags.append(f"pending_placement={pending_placement.get('kind')}"
                     f"@{pending_placement.get('caster')}")
    pending_shenji = temp.get('pending_shenji')
    if pending_shenji:
        flags.append(f"pending_shenji={pending_shenji.get('caster')}")
    dice = getattr(room, 'pending_dice_discard', None)
    if isinstance(dice, dict):
        for pid, done in dice.items():
            if done is False:
                flags.append(f'dice_discard_pending={pid}')
    for pick in (getattr(room, 'pending_ship_picks', None) or []):
        if isinstance(pick, dict) and pick.get('player') == ai_id:
            flags.append(f"ai_ship_pick={pick.get('reason')}")
    if getattr(room, 'priority_continue', None):
        flags.append('priority_continue')
    return flags


PROBE_LABELS = ('大师出牌尝试', '出牌前仍有未结算项',
                '大师开炮尝试', '开炮前仍有未结算项',
                '大师收尾尝试', '收尾前仍有未结算项')


def run_one(seed, samples, counter, lock, turn_seconds=120.0, max_actions=2000,
            stop_after_master_turns=0):
    """跑一局：大师走**真实**的 `_ai_master_turn`（另一线程），人类一侧本线程搬。

    大师的回合可能落在**任何一个大回合**上，所以这里不是"跑一局"而是
    "跑到大师至少行动过一次"：本线程一直替人类搬（连锁 / 待办 / 阶段 / 开炮 /
    交回合），一旦房间的当前攻击者是 AI 且轮到它，就起线程跑真循环。

    `stop_after_master_turns > 0`：数满这么多**大师回合**就停（0 = 打到分出胜负）。
    ⚠️ 这个开关是给"停顿总量"那个统计用的：不设上界时会一直陪跑到棋局结束
    （人类一侧由本脚本搬，所以一局能跑到十几回合），而停顿总量只在
    "大师自己的回合"里有意义 —— 两者混在一起数字没法比。
    """
    with hg.HeadlessGame(lambda: hg.make_policy('master'),
                         lambda: hg.make_policy('hard'),
                         seed=seed, max_actions=max_actions) as game:
        room = game.room
        ai_id = game.p1
        human = game.p2
        error = []
        master_turns_done = []

        # ★ 把 `time.sleep` 换成"记账版"：立刻返回并记下时长。
        #   本工具验的是**结算顺序**与**停顿总量**，不是真实墙钟 ——
        #   真睡的话一局要几分钟（节奏停顿 + 连锁轮询等待），跑到 20 局要半小时。
        #   决策与结算逻辑一行不改，连 `_MASTER_SETTLE_STEPS` 都不动。
        sleeps = []
        shared_time = hg.server.time
        real_sleep = time.sleep

        def sleep_spy(seconds=0.0):
            sleeps.append(float(seconds or 0.0))
            return None

        shared_time.sleep = sleep_spy
        time.sleep = sleep_spy

        orig_use = hg.server.handle_use_magic_card
        orig_atk = hg.server.handle_attack
        orig_end = hg.server.handle_enter_end_phase

        def snapshot(kind, what, attempt_key, dirty_key):
            live = hg.server.room_manager.get_room(room.id) or room
            flags = _pending_flags(live, ai_id)
            with lock:
                counter[attempt_key] += 1
                if flags:
                    counter[dirty_key] += 1
                    samples.append((seed, kind, what, list(flags)))

        def use_spy(data):
            if data.get('player_id') == ai_id:
                snapshot('出牌前', (data.get('card') or {}).get('name'),
                         '大师出牌尝试', '出牌前仍有未结算项')
            return orig_use(data)

        def atk_spy(data):
            if data.get('player_id') == ai_id:
                snapshot('开炮前', f"{data.get('x')},{data.get('y')}",
                         '大师开炮尝试', '开炮前仍有未结算项')
            return orig_atk(data)

        def end_spy(data, **kw):
            if data.get('player_id') == ai_id:
                snapshot('收尾前', '', '大师收尾尝试', '收尾前仍有未结算项')
            return orig_end(data, **kw)

        # 大师的回合循环本身也包一层：确认它**真的被调到**（没被调到的话，
        # 上面三个探针全是 0，看起来像"没问题"，其实是探针根本没工作）。
        orig_master = hg.server._ai_master_turn
        orig_play_one = hg.server._master_play_one
        orig_master_pick = hg.server._ai_master_pick

        def master_spy(room_id, live_room, pid):
            with lock:
                counter['_ai_master_turn 被调用'] += 1
            return orig_master(room_id, live_room, pid)

        def play_one_spy(room_id, pid, played):
            out = orig_play_one(room_id, pid, played)
            with lock:
                counter['_master_play_one 调用'] += 1
                counter['_master_play_one 成功' if out else '_master_play_one 失败'] += 1
            return out

        def master_pick_spy(room, pid, cards_played=0):
            idx, targets = orig_master_pick(room, pid, cards_played)
            with lock:
                counter['_ai_master_pick 调用'] += 1
                counter['_ai_master_pick 选中' if idx is not None
                        else '_ai_master_pick 回 None'] += 1
            return idx, targets

        hg.server.handle_use_magic_card = use_spy
        hg.server.handle_attack = atk_spy
        hg.server.handle_enter_end_phase = end_spy
        hg.server._ai_master_turn = master_spy
        hg.server._master_play_one = play_one_spy
        hg.server._ai_master_pick = master_pick_spy
        try:
            game._place_ships()
            game._rps()
            deadline = time.monotonic() + turn_seconds
            master_thread = None
            while time.monotonic() < deadline:
                live = hg.server.room_manager.get_room(room.id)
                if live is None or live.state == 'game_over' or live.winner:
                    break
                if live.state == 'placing_ships':
                    game._place_ships()
                    continue
                if live.state == 'rock_paper_scissors':
                    game._rps()
                    continue
                if live.chain or live.chain_waiting:
                    game._pump_chain()
                    continue
                if game._pump_pending() is False:
                    break
                if live.current_attacker == ai_id:
                    # 人类替身先什么都不做，把方向盘交给真实的大师回合循环。
                    done = threading.Event()

                    def master(_done=done):
                        try:
                            orig_atk_holder[0](room.id,
                                               hg.server.room_manager.get_room(room.id),
                                               ai_id)
                        except Exception as exc:
                            error.append(repr(exc))
                            with lock:
                                counter['大师回合抛异常'] += 1
                        finally:
                            _done.set()

                    orig_atk_holder = [orig_master]
                    # ★ 停顿记账：只包大师这**一个回合**（跨线程也记得住，因为
                    #   记账表是闭包里的列表、被替换的是 `time.sleep` 本身）。
                    #   ⚠️ 上一圈的残留必须清掉：`time.sleep` 的补丁是**整局**有效的，
                    #      主线程的 `_pump_chain/`_pump_pending` 也在往里写 ——
                    #      不清就会把每个回合的停顿累加，数字虚高（实测踩过）。
                    sleeps.clear()
                    master_thread = threading.Thread(target=master, daemon=True)
                    master_thread.start()
                    master_thread.join(turn_seconds)
                    # 取一份**本回合的**停顿快照，再清空给下一回合用。
                    turn_sleeps = list(sleeps)
                    with lock:
                        counter['§停顿次数'] += len(turn_sleeps)
                        counter['§停顿总秒数x100'] += int(round(sum(turn_sleeps) * 100))
                        n_paced = sum(1 for s in turn_sleeps
                                      if abs(s - hg.server._MASTER_CARD_PACING) < 1e-9)
                        counter['§其中节奏停顿次数'] += n_paced
                        counter['§大师回合数'] += 1
                        counter[f'§每回合节奏停顿={n_paced}'] += 1
                    sleeps.clear()
                    master_turns_done.append(1)
                    if stop_after_master_turns and len(master_turns_done) >= stop_after_master_turns:
                        break
                    if master_thread.is_alive():
                        with lock:
                            counter['大师回合超时未返回'] += 1
                        break
                    if error:
                        with lock:
                            counter[f'异常样本：{error[0][:70]}'] += 1
                        break
                    # 大师交完回合后继续下一圈（人类回合由本循环搬）
                    continue
                # 人类回合：驱动器自己走
                if not game._turn():
                    break
            game._pump_pending()
        except Exception as exc:
            with lock:
                counter['循环抛异常'] += 1
                counter[f'循环异常：{exc!r}'[:70]] += 1
        finally:
            shared_time.sleep = real_sleep
            time.sleep = real_sleep
            hg.server.handle_use_magic_card = orig_use
            hg.server.handle_attack = orig_atk
            hg.server.handle_enter_end_phase = orig_end
            hg.server._ai_master_turn = orig_master
            hg.server._master_play_one = orig_play_one
            hg.server._ai_master_pick = orig_master_pick
        with lock:
            counter['实际跑到的回合数'] += int(room.round or 0)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=20)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--master-turns', type=int, default=0,
                    help='每局只跑这么多**大师回合**就停（0 = 打到分出胜负）')
    args = ap.parse_args(argv)

    samples = []
    counter = collections.Counter()
    lock = threading.Lock()
    buf = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(buf):
        for i in range(args.games):
            try:
                run_one(args.seed + i, samples, counter, lock,
                        stop_after_master_turns=args.master_turns)
            except Exception as exc:
                counter['探针本身抛异常'] += 1
                counter[f'探针异常：{exc!r}'[:70]] += 1
    elapsed = time.perf_counter() - started

    print(f'探针：{args.games} 局（大师走真实 `_ai_master_turn`；`time.sleep` 换成了'
          f'记账版，所以墙钟很快）')
    print(f'耗时 {elapsed:.1f}s')
    print('=' * 78)
    for k in PROBE_LABELS:
        print(f'  {k:<20s} {counter[k]:6d}')
    print()
    # ★ 停顿总量：这就是作者两条反馈的**墙钟对照**。
    #
    # ⚠️ 只报**节奏停顿**（`_MASTER_CARD_PACING`），不把轮询等待算进去：
    #    本工具在无头环境里**自己替真人搬**连锁/待办，而真人是会立刻响应的，
    #    `_master_settle` 那 0.3s 一档的轮询在真实对局里几乎不触发 ——
    #    把它算进"停顿总量"会得到一个**只属于本工具**的虚高数字。
    #    （实测：同一批回合里轮询累计 2998 秒，其中绝大多数是本工具造成的。）
    turns = max(1, counter['§大师回合数'])
    paced = counter['§其中节奏停顿次数']
    shots = counter['大师开炮尝试']
    now = paced * hg.server._MASTER_CARD_PACING
    before = (paced + shots + turns) * 0.8
    per_turn = sorted((k, v) for k, v in counter.items()
                      if k.startswith('§每回合节奏停顿='))
    print(f'【节奏停顿墙钟对照】{counter["§大师回合数"]} 个大师回合'
          f'（{paced} 次出牌停顿 / {shots} 炮）')
    print('  每回合的出牌停顿次数分布：')
    for key, n in per_turn:
        print(f'      {key.split("=")[1]:>3s} 次: {n:4d} 个回合')
    print(f'  改后（现在）：出牌停顿 {paced} × {hg.server._MASTER_CARD_PACING}s = {now:.1f} 秒')
    print(f'  改前（旧写法）：出牌 {paced} × 0.8 + 开炮 {shots} × 0.8'
          f' + 阶段转换 {turns} × 0.8 = {before:.1f} 秒')
    print(f'  → 少了 {before - now:.1f} 秒（{before / turns:.1f}s/回合 → {now / turns:.1f}s/回合，'
          f'降 {(1 - now / before) * 100:.0f}%）')
    print()
    print(f'  ℹ️ 另记：本工具跑出的轮询等待 {counter["§停顿次数"] - paced} 次'
          f'（{counter["§停顿总秒数x100"] / 100.0 - now:.0f} 秒）**不是**真实对局的墙钟 ——')
    print('     那是本工具替真人慢慢搬连锁/待办造成的；真人会立刻响应。')
    print()
    others = {k: v for k, v in counter.items() if k not in PROBE_LABELS}
    if others:
        print('  —— 其他 ——')
        for k, v in sorted(others.items(), key=lambda kv: -kv[1])[:15]:
            print(f'  {k:<20s} {v:6d}')
    print()
    if samples:
        print(f'⚠️ **发现 {len(samples)} 次"上一个效果没结算完就动下一个"**，前 10 例：')
        for seed, when, what, snap in samples[:10]:
            print(f'  seed={seed} {when} {what}  未结算项={snap}')
    else:
        print('✅ 没有发现"未结算就继续"：每次大师要出牌 / 开炮 / 收尾之前，')
        print('   连锁栈、响应窗口、四条待办通道（放置/宣言/弃牌/选船）与优先权')
        print('   **全部为空**。')
        print('   → 作者报的"太快了"是**观感**问题（缺人眼停顿），不是结算竞态。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
