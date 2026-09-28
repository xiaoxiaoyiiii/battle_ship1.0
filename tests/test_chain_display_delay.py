# -*- coding: utf-8 -*-
"""连锁**结算前的展示停留**（`server.CHAIN_DISPLAY_DELAY_SECONDS`）的守卫。

## 为什么有这批用例

第 7 批（`docs/SPECTATE_BATCH7_2026_09_23.md`）查清了那条"红了 5/8"的连锁断言：
观众**每次**都收到了连锁帧、前端也画出来了，只是**那一帧 DOM 只存在 3~17 毫秒** ——
双方都拿不出速阶3 时，`_advance_chain_window` 在**同一个栈帧**里 `resolve_chain`。
作者据此拍板：**结算前留一段固定的展示时间**（不是按牌数留时间，就是固定停一下）。

这个改动的价值全在"看得见"，代价却是三个**不报错**的风险：

1. **无头对局驱动跟着变慢**（250 局/秒、大师 AI 胜率全靠它量）—— 胜率数字会变成
   噪声，而**不会有任何报错**（CLAUDE.md 教训 #36 的形状）；
2. **整局冻死** —— 延迟一旦排不进去 / 任务没跑起来，`room.chain` 会一直挂着，
   而 `room.chain` 非空会把攻击与交回合全拒掉（「连锁结算中」）；
3. **重复结算** —— 迟到的任务在一局已经翻篇的连锁上再跑一次 = 一张牌的效果落地两次。

所以本文件的用例一半验"延迟真的发生了"，另一半专门验上面这三条**不许发生**。

## 用例清单

| # | 用例 | 守什么 |
| --- | --- | --- |
| 1 | `test_both_cannot_respond_resolves_after_the_delay` | ★ 结算**不在同一栈帧**，且约 1.2 秒后才发生 |
| 2 | `test_ten_second_window_path_is_untouched` | 10 秒响应窗口那条路径**行为不变**（就地结算、不排停留） |
| 3 | `test_delay_never_blocks_the_caller` | 延迟**绝不在请求里阻塞**（AI 座位不被卡住的前提） |
| 4 | `test_late_task_never_resolves_twice` | 延迟期间已被别处结算 ⇒ 迟到的任务**不重复结算** |
| 5 | `test_stale_token_does_not_resolve_a_chain_that_grew` | 延迟期间连锁又变了 ⇒ 旧令牌作废（代际令牌） |
| 6 | `test_watchdog_sweeps_an_overdue_display` | ★ 兜底：后台任务没跑起来也**不会挂死** |
| 7 | `test_watchdog_sweep_never_double_resolves` | 反证：看门狗不会对已结算的房间再结算一次 |
| 8 | `test_delay_zero_is_exactly_the_old_behaviour` | 置 0 ⇒ 与改动前**逐字节一致**（同一个栈帧结算） |
| 9 | `test_delay_is_off_for_the_whole_suite` | 整套 pytest 默认是 0（守住"既有用例不跟着变"） |
| 10 | `test_ai_room_unlocks_after_the_delay` | AI 人机房：延迟期间不卡住，到点解锁继续开炮 |
| 11 | `test_watcher_and_players_still_see_the_chain` | ★ 观战者与对局双方在延迟窗口内**看得到连锁区** |

⚠️ 本文件的用例**显式**把延迟打开（`delay_on` fixture）——整套 pytest 默认是 0
（`tests/conftest.py`），否则 2236 条既有用例会在"结算不再同步"上一起变。
"""
import time as _time
import uuid

import pytest

import server
from server import (ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position,
                    room_manager)

import db as db_module


P1, P2 = 'p1', 'p2'
AI = 'ai-chain-display'

# 墙钟允许区间（秒）：下界明显大于 0、上界留足机器慢/调度抖动的余量。
# 要抓的是"**根本不是同一个栈帧**"，不是掐毫秒 —— 掐毫秒只会得到一条会假红的用例（教训 #15）。
_MIN_WAIT, _MAX_WAIT = 1.0, 6.0


# ===========================================================================
# 夹具与助手
# ===========================================================================
@pytest.fixture
def delay_on(monkeypatch):
    """把展示停留打开（整套 pytest 默认是 0，见 `tests/conftest.py`）。"""
    monkeypatch.setattr(server, 'CHAIN_DISPLAY_DELAY_SECONDS', 1.2)
    return 1.2


@pytest.fixture
def events(monkeypatch):
    """把 `server.emit` 换成记账桩（无请求上下文时它本来也会退化，但记账更好断言）。"""
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))
        return None

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


@pytest.fixture
def pending_tasks(monkeypatch):
    """把展示停留的后台任务**接住**（不真跑），由用例决定什么时候让它落地。

    为什么默认不真跑：本文件要逐个验"迟到 / 作废 / 兜底"这些**时序**，真跑等于把
    判定权交给调度器。真后台任务只在那条"量墙钟"的用例（#1）里用一次。
    """
    tasks = []

    def fake_start(target, *args, **kwargs):
        tasks.append((target, args, kwargs))
        return None

    monkeypatch.setattr(server.socketio, 'start_background_task', fake_start)
    # 任务自己会 `socketio.sleep(CHAIN_DISPLAY_DELAY_SECONDS)` —— 手动触发时不必真等
    monkeypatch.setattr(server.socketio, 'sleep', lambda *_a, **_k: None)
    return tasks


def _card(name):
    """按名字造牌（speed/type 照 `magic_card.json` 的真实数据，与手牌查找同源）。"""
    return MagicCard(name=name)


def _ships(row):
    return [PlayerShip(positions=[Position(x, row)], hits=[]) for x in range(6)]


def _make_room(room_id=None, with_accounts=False, ai_room=False):
    """一间"正在打"的房间。

    `with_accounts=True`：两个座位建**真账号**（观战那条路径要 `db` 里有这个人，
    `_spectate_seat_allow` 对查不到的 user_id 一律返回 None = 不允许）。
    `ai_room=True`：按服务端的约定建人机房（AI 座位 id = `ai-<room_id>`，只有两个座位）。
    """
    room = GameRoom(room_id or ('chaindisp-' + uuid.uuid4().hex[:6]))
    if ai_room:
        seats = ((AI, 3), (P1, 0))
        room.is_ai_room = True
        room.ai_difficulty = 'hard'
    else:
        seats = ((P1, 0), (P2, 5))
    for pid, row in seats:
        uid = None
        is_ai = pid.startswith('ai-')
        if with_accounts and not is_ai:
            uid = db_module.create_user(f'chaindisp-{pid}-{uuid.uuid4().hex[:10]}', 'x' * 12)
            assert uid, '建测试账号失败'
        room.players[pid] = Player(name=pid, ships=_ships(row), attacks=[],
                                   remaining_ships=6, sid='' if is_ai else 'sid-' + pid,
                                   user_id=uid)
    room.state = 'attacking'
    room.current_phase = 'battle'
    room.current_attacker = AI if ai_room else P1
    room.attack_order = [pid for pid, _ in seats]
    room.attacks_remaining = 6
    room.round = 3
    room.ranked = False
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = _make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


@pytest.fixture
def ai_room():
    r = _make_room(ai_room=True)
    yield r
    room_manager.rooms.pop(r.id, None)


def _arm(room, caster=None, card_name='无中生有'):
    """摆成"刚打出一张牌、还没人响应过"：连锁里一项、`chain_passes = 0`。"""
    if caster is None:
        caster = room.current_attacker
    room.chain = [ChainItem(caster, _card(card_name), [], _time.time())]
    room.chain_passes = 0
    room.chain_waiting = False
    room.chain_window = None
    return room.chain[0]


def _chain_resolved_count(events):
    return sum(1 for e in events if e[0] == 'chain_resolved')


def _wait_until(cond, timeout=8.0, step=0.02):
    """等到条件成立，返回用掉的时间；超时返回 None。"""
    started = _time.perf_counter()
    while _time.perf_counter() - started < timeout:
        if cond():
            return _time.perf_counter() - started
        _time.sleep(step)
    return None


def _drain(client):
    """把这条连接的收件队列取空，按事件名分组。"""
    out = {}
    for msg in client.get_received():
        out.setdefault(msg['name'], []).append(msg['args'][0] if msg['args'] else None)
    return out


# ===========================================================================
# 1. ★★ 主守卫：双方都接不了 ⇒ 结算不在同一栈帧，且约 1.2 秒后发生
# ===========================================================================
def test_both_cannot_respond_resolves_after_the_delay(room, events, delay_on):
    """★★ 双方都没有速阶3 ⇒ 连锁**不许**当场结算，要停约 1.2 秒再结算。

    这条用的**是真后台任务**（本文件唯一一条）：要量的就是墙钟，
    把任务接住自己触发就变成"验我自己写的桩"了。
    """
    _arm(room)

    started = _time.perf_counter()
    server._advance_chain_window(room, P2)
    handoff = _time.perf_counter() - started

    # ① 关键判据：**同一个栈帧里不许结算**（"17ms 一闪而过"就是这么来的）
    assert room.chain, (
        '结算在同一个栈帧里发生了 —— 连锁区还是会一闪而过，本改动等于没做')
    assert handoff < 0.5, f'排一次展示停留不该花 {handoff:.3f}s'
    assert room.chain_display_token is not None, '必须挂上展示停留的令牌'
    assert _chain_resolved_count(events) == 0, '延迟期间一条 chain_resolved 都不该发'
    # 玩家这一侧的"重新同步"读数里连锁还挂着（前端只在 chain_resolved 时才清空）
    assert server._build_room_sync(room, P1)['chain'], '延迟期间重连快照里也该有连锁'

    # ② 到点之前不许结算
    _time.sleep(0.4)
    assert room.chain, '展示停留还没到点就结算了'

    # ③ 到点必须结算
    assert _wait_until(lambda: not room.chain) is not None, '到点后连锁必须结算（不能挂着）'
    total = _time.perf_counter() - started
    assert _MIN_WAIT <= total <= _MAX_WAIT, (
        f'结算应发生在约 {delay_on} 秒后，实际 {total:.3f}s')
    assert room.chain_display_token is None, '结算之后令牌必须清掉'
    assert _chain_resolved_count(events) == 1, '结算报文只能有一次'


# ===========================================================================
# 2. 10 秒窗口那条路径**不动**
# ===========================================================================
def test_ten_second_window_path_is_untouched(room, events, delay_on, monkeypatch):
    """有速阶3 可响应 ⇒ 照旧开满 10 秒窗口；超时后**就地结算**，不留展示停留。

    这是"防止改坏它"的那条：展示停留只加在"双方都接不了 ⇒ 立刻就要结算"那条路径上。
    """
    _arm(room)
    room.players[P2].magic_hand = [_card('失灵！')]
    assert int(room.players[P2].magic_hand[0].speed) == 3, '前提：失灵！是速阶3'

    scheduled = []
    real_schedule = server._schedule_chain_timeout        # 先留一份真实现（下面要直接调它）
    monkeypatch.setattr(server, '_schedule_chain_timeout',
                        lambda room_id, token: scheduled.append((room_id, token)))

    server._advance_chain_window(room, P2)

    assert room.chain_waiting is True and room.chain_window == P2, '窗口应开给能响应的一方'
    assert room.chain, '开窗口时连锁当然还挂着'
    assert room.chain_display_token is None, '开响应窗口**不该**排展示停留'
    reqs = [e for e in events if e[0] == 'chain_request']
    assert reqs and reqs[0][1]['countdown'] == server.CHAIN_RESPONSE_SECONDS == 10
    assert scheduled == [(room.id, room.chain_timer)], '超时兜底照旧要挂上'

    # 超时到点：把 sleep 变空、后台任务只记账，再**手动**跑一次真正的超时体。
    # ⚠️ 这里**不能**让 `start_background_task` 内联执行 —— 内联会把"排了一次展示停留"
    #    伪装成"就地结算了"（展示任务内联跑完，连锁当然也是空的），
    #    于是这条判据会对着一个被改坏的实现照样变绿。
    monkeypatch.setattr(server.time, 'sleep', lambda *_a, **_k: None)
    spawned = []
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda fn, *a, **kw: spawned.append((fn, a)))
    server._schedule_chain_timeout = real_schedule             # 调真实现（不是那个记账桩）
    real_schedule(room.id, room.chain_timer)
    assert [fn.__name__ for fn, _ in spawned] == ['_timeout'], (
        f'排超时兜底时不该顺带排别的东西：{[fn.__name__ for fn, _ in spawned]}')
    spawned[0][0](*spawned[0][1])                              # 触发真正的超时体

    assert room.chain == [], (
        '走满 10 秒窗口那条路径必须**就地结算**（行为与改动前一致）—— '
        '若这里还挂着，就是展示停留被加到了不该加的地方')
    assert room.chain_display_token is None, '10 秒窗口路径不许排出展示停留'
    assert len(spawned) == 1, '10 秒窗口路径**不许**再排一个展示停留的后台任务'
    assert _chain_resolved_count(events) == 1


# ===========================================================================
# 3. 延迟绝不在请求里阻塞（AI 座位不被卡住的前提）
# ===========================================================================
def test_delay_never_blocks_the_caller(room, events, delay_on, pending_tasks):
    """排展示停留必须**立刻返回**：eventlet 是单线程 hub，在请求里 sleep 1.2 秒
    会把整个服务器按住（CLAUDE.md 第 2 节）。

    顺带钉住返回值语义（`True` = 已交给后台任务，还没结算）。
    """
    _arm(room)
    started = _time.perf_counter()
    handed_off = server._advance_chain_window(room, P2)
    elapsed = _time.perf_counter() - started

    assert elapsed < 0.3, f'排一次后台任务花了 {elapsed:.3f}s —— 这是在请求里阻塞了'
    assert handed_off is True, '延迟期间应返回"已交给后台任务"'
    assert len(pending_tasks) == 1, '必须排**恰好一个**后台任务'
    assert room.chain, '返回时连锁当然还没结算'


# ===========================================================================
# 4. ★★ 幂等：延迟期间已被别处结算 ⇒ 迟到的任务不许再结算一次
# ===========================================================================
def test_late_task_never_resolves_twice(room, events, delay_on, pending_tasks):
    """延迟期间连锁被别的路径（超时 / 投降清栈 / 重摆 / 对局结束）结算掉了，
    迟到的任务**不许**再跑一遍结算 —— 那等于一张牌的效果落地两次。
    """
    _arm(room)
    server._advance_chain_window(room, P2)
    assert len(pending_tasks) == 1 and room.chain

    # 别的路径结算（这里用最直接的那条：resolve_chain 自己）
    server.resolve_chain(room)
    assert room.chain == []
    assert room.chain_display_token is None, (
        '任何一次 resolve_chain 都必须清掉展示停留令牌 —— 幂等判据靠它')
    assert _chain_resolved_count(events) == 1

    # 迟到的任务到点醒来
    target, args, _ = pending_tasks[0]
    target(*args)

    assert _chain_resolved_count(events) == 1, (
        '迟到的展示停留任务**重复结算**了（chain_resolved 出现了两次）')
    assert room.chain == []


# ===========================================================================
# 5. ★★ 代际令牌：延迟期间连锁又变长了 ⇒ 旧任务作废
# ===========================================================================
def test_stale_token_does_not_resolve_a_chain_that_grew(room, events, delay_on,
                                                        pending_tasks):
    """延迟期间又打出一张牌（连锁变长）⇒ 旧令牌作废，
    旧任务**不许**把这条更长的连锁按旧长度结算掉。
    """
    _arm(room)
    server._advance_chain_window(room, P2)
    assert len(pending_tasks) == 1
    old_target, old_args, _ = pending_tasks[0]
    old_token = room.chain_timer

    # 又打一张（走真正的出牌入口，形状与线上一致）
    room.players[P2].magic_hand = [_card('冻结')]
    room.current_attacker = P2
    ack = server.handle_use_magic_card({'room_id': room.id, 'player_id': P2,
                                        'card': {'name': '冻结'}, 'targets': {}})
    assert ack and ack['status'] == 'success', ack
    assert len(room.chain) == 2, '前提：连锁真的变长了'
    assert room.chain_timer != old_token, '又排一次停留 ⇒ 令牌必须换代'

    # 旧任务醒来：什么都不许做
    old_target(*old_args)
    assert room.chain, '过期的展示停留任务把新连锁结算掉了'
    assert _chain_resolved_count(events) == 0

    # 新任务醒来：把两条一起结算
    new_target, new_args, _ = pending_tasks[-1]
    assert (new_target, new_args) != (old_target, old_args), '必须又排了一次停留'
    new_target(*new_args)
    assert room.chain == []
    assert _chain_resolved_count(events) == 1


# ===========================================================================
# 6. ★★ 兜底：后台任务没跑起来也不许挂死
# ===========================================================================
def test_watchdog_sweeps_an_overdue_display(room, events, delay_on, monkeypatch):
    """★ 兜底：任务排上了却**永远不跑**（hub 挂了 / 被打成空操作 / 自己抛异常）时，
    看门狗必须把连锁结算掉。

    为什么这是最贵的一条：`room.chain` 非空会把攻击与交回合全拒掉
    （「连锁结算中」），挂住 = **整局冻死**，而"没人结算"这件事不会报错。
    """
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda *a, **kw: None)          # 排上了，但永远不跑

    _arm(room)
    server._advance_chain_window(room, P2)
    assert room.chain, '前提：延迟期间连锁还挂着'

    # 还没到截止时刻：看门狗不许动它
    assert server._sweep_overdue_chain_display(now=_time.monotonic()) == []
    assert room.chain, '展示停留还没到点就被兜底结算了'

    # 过了截止时刻：就地结算
    swept = server._sweep_overdue_chain_display(now=room.chain_display_deadline + 0.1)
    assert swept == [room.id], f'看门狗没有兜底结算：{swept}'
    assert room.chain == [] and room.chain_display_token is None
    assert _chain_resolved_count(events) == 1


def test_watchdog_sweep_never_double_resolves(room, events, delay_on, monkeypatch):
    """反证：已经结算过的房间，看门狗**不许**再结算第二次（幂等）。"""
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda *a, **kw: None)
    _arm(room)
    server._advance_chain_window(room, P2)
    deadline = room.chain_display_deadline
    server.resolve_chain(room)
    assert _chain_resolved_count(events) == 1

    assert server._sweep_overdue_chain_display(now=deadline + 1) == []
    assert _chain_resolved_count(events) == 1, '看门狗重复结算了'


# ===========================================================================
# 7. 置 0 ⇒ 与改动前逐字节一致
# ===========================================================================
def test_delay_zero_is_exactly_the_old_behaviour(room, events, monkeypatch):
    """延迟置 0 ⇒ **同一个栈帧**里结算、不排任何后台任务（= 改动前那一行）。

    无头对局驱动与 2236 条既有用例靠的就是这一条。
    """
    monkeypatch.setattr(server, 'CHAIN_DISPLAY_DELAY_SECONDS', 0.0)
    calls = []
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda fn, *a, **kw: calls.append(fn))

    _arm(room)
    handed_off = server._advance_chain_window(room, P2)

    assert room.chain == [], '置 0 时必须当场结算（既有用例与无头驱动都靠它）'
    assert handed_off is False, '置 0 时应返回"已就地结算"'
    assert room.chain_display_token is None
    assert calls == [], '置 0 时不许再排后台任务'
    assert _chain_resolved_count(events) == 1


def test_delay_is_off_for_the_whole_suite():
    """★ 整套 pytest 默认必须是 0（`tests/conftest.py` 那一行）。

    这条守的是"**既有用例不跟着变**"这个契约本身：谁把 conftest 里那行删掉，
    那些断言 `room.chain == []` 的用例会一起红（而它们测的其实是"结算发生了"），
    本用例则会给出**指向原因**的那条红。
    """
    assert server.CHAIN_DISPLAY_DELAY_SECONDS == 0.0, (
        '整套 pytest 的默认值不是 0 —— 检查 tests/conftest.py 里 '
        'CHAIN_DISPLAY_DELAY_SECONDS 那一行；开着的话既有用例会变慢甚至一起红')


# ===========================================================================
# 8. AI 人机房不会被这段延迟卡住
# ===========================================================================
def test_ai_room_unlocks_after_the_delay(ai_room, events, delay_on, pending_tasks):
    """AI 人机房同样走这条路（AI 自己可能就是"接不了"的那一方）：
    延迟期间房间是"连锁挂着"（与 10 秒窗口同口径，不是死锁），到点必须解锁继续开炮。
    """
    _arm(ai_room, caster=P1)

    # ① 排停留**不许**阻塞调用方：`_ai_chain_respond` 与 AI 回合循环都在后台任务里跑，
    #    这里真 sleep 1.2 秒等于把 AI 的节奏按住（也把整个 hub 按住）。
    started = _time.perf_counter()
    server._advance_chain_window(ai_room, AI)
    assert _time.perf_counter() - started < 0.3

    # ② 延迟期间：AI 的"还没结算"门禁看得见连锁（这是它本该等的状态，不是新加的门禁）
    assert ai_room.chain and ai_room.chain_waiting is False
    assert server._master_unsettled(ai_room, AI), 'AI 侧应看到连锁还没结算'
    assert server.handle_attack({'room_id': ai_room.id, 'player_id': AI,
                                 'x': 0, 'y': 0})['status'] == 'error', (
        '延迟期间攻击仍按原口径被「连锁结算中」拒掉')

    # ③ 到点结算 ⇒ 必须解锁
    target, args, _ = pending_tasks[0]
    target(*args)
    assert ai_room.chain == [], '展示停留到点后必须结算'
    ack = server.handle_attack({'room_id': ai_room.id, 'player_id': AI, 'x': 0, 'y': 0})
    assert ack.get('status') == 'success', f'结算之后 AI 座位必须能继续开炮：{ack}'


# ===========================================================================
# 9. ★★ 观战者与对局双方在延迟窗口内**看得到**连锁区
# ===========================================================================
def test_watcher_and_players_still_see_the_chain(delay_on, monkeypatch):
    """★★ 本改动的**目的**：延迟窗口内连锁区还挂着。

    判据用**真观众连接**（`socketio.test_client`，与 `test_spectate_batch7.py` 同一套）：
    这条连接收到了带牌的 `magic_chain_updated`，而**整整 1.2 秒里没有 `chain_resolved`**
    —— 前端正是只在 `chain_resolved` 时才清空连锁区。到点结算之后才收到它。

    ⚠️ 这条用例**不打桩 `server.emit`**：要验的就是"真的发到了观众通道"。
    """
    room = _make_room(with_accounts=True)
    watcher = None
    try:
        # 观众：真登录会话 + 真连接（观战只限登录用户）
        http = server.app.test_client()
        uid = db_module.create_user('chaindisp-watch-' + uuid.uuid4().hex[:10], 'x' * 12)
        assert uid
        with http.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = '观众'
        watcher = server.socketio.test_client(server.app, flask_test_client=http)
        assert watcher.emit('spectate_join', {'room_id': room.id},
                            callback=True)['status'] == 'success', '观众应能入席'
        watcher.get_received()                       # 丢掉进席噪音

        # 把后台任务接住：本用例要的是"窗口内还挂着"，不是量墙钟
        tasks = []

        def fake_start(target, *args, **kwargs):
            tasks.append((target, args, kwargs))

        monkeypatch.setattr(server.socketio, 'start_background_task', fake_start)
        monkeypatch.setattr(server.socketio, 'sleep', lambda *_a, **_k: None)

        # 打出一张牌（与 `handle_use_magic_card` 压栈后那一次广播同形状）
        _arm(room)
        server.emit('magic_chain_updated', {'chain': room.chain}, room=room.id)
        assert _drain(watcher).get('magic_chain_updated'), (
            '前提不成立：观众连连锁帧都没收到（那这条用例证明不了任何事）')

        # 双方都接不了 ⇒ 排上展示停留
        server._advance_chain_window(room, P2)
        assert room.chain and len(tasks) == 1

        # ★ 延迟窗口内：观众侧没有任何"清空连锁区"的指令
        got = _drain(watcher)
        assert 'chain_resolved' not in got, (
            '延迟窗口内就发了 chain_resolved —— 观众那边的连锁区已经被清空了')
        # 玩家侧同口径：重新同步（重连/刷新）拿到的快照里连锁也还挂着
        assert server._build_room_sync(room, P1)['chain'], '玩家侧重连快照里也还该有连锁'

        # 到点结算 ⇒ 这时候才清空
        target, args, _ = tasks[0]
        target(*args)
        assert _drain(watcher).get('chain_resolved'), (
            '结算了却没告诉观众 —— 观众的连锁区会一直挂着不消失')
    finally:
        if watcher is not None:
            try:
                watcher.disconnect()
            except Exception:                          # noqa: BLE001 - 清理失败不该让用例变红
                pass
        room_manager.rooms.pop(room.id, None)
