# -*- coding: utf-8 -*-
"""实时观战的**纯规则**（第 1 批：地基 + 安全，观众暂时还进不来）。

与 `ranks.py` / `anticheat.py` / `quick_chat.py` 同路数：**纯函数、无 I/O、无 socket、
不 import server**（CLAUDE.md 教训 #19：运行期 import server 会再执行一遍整个
server.py，那份 socketio 发不出事件，且本地坏线上好、pytest 永远测不到）。

## 这个模块存在的唯一理由

观战最大的风险不是"功能没做出来"，而是**漏一个事件 = 透视漏洞**：
对局双方收到的房间级广播里，有些 payload 带**整船坐标**（设计上对双方就是公开的），
一旦原样转给观众，观众就能直接读出双方船位。

以前这靠"人肉记住别转发"来保证 —— 那种约定在加第 94 个事件时必然失效。
所以这里把它变成**机器穷举**：

* `SPECTATE_EVENTS`  —— 允许给观众的事件 → 净化函数（`None` = 原样转发）；
* `NOT_FOR_SPECTATORS` —— 明确不给观众的事件 → **理由字符串**（空理由直接报错）；
* `tests/test_spectate_guards.py` 扫 `server.py` 里全部 `emit(...)` 调用点，
  断言**每一个事件名都必须在这两张表里表态**（新人加事件时漏表态 = 测试变红）。

## 净化函数吃什么

净化函数收到的是**已经过 `json.dumps(..., default=lambda o: o.__dict__)` 的普通数据**
（dict / list / str / int / bool / None）—— `emit()` 是唯一入口，它先序列化再净化。
好处是净化函数永远不需要认识 `Player` / `PlayerShip` / `ChainItem` 这些活对象，
也不会有"改坏了活对象"的风险（净化只发生在即将发给观众的那一份上）。

## 两条不许碰的红线

1. **任何发给观众的 payload 里不许出现 `ships` / `positions` / `hits` 字段**，
   也不许出现**未被轰过的**船坐标（`MUST_NOT_LEAK_COORDS` 里的 5 个事件是被测试逐格钉住的）；
2. **不许为了安全把动作也砍掉**：观众必须看得到"谁打了哪一格 / 谁打出了什么卡"。
   净化只删坐标这类**局面信息**，保留"谁做了什么、结果如何"这类**动作信息**。
"""
from __future__ import annotations

# 观战通道的 socket.io room 名前缀。
# ⚠️ 观众**绝不能**进对局的 room（那是 `room.id`）—— 那等于把 93 处房间级广播
#    原样灌给观众（含整船坐标）。观战通道是**独立**的一个 room 名。
SPECTATE_ROOM_PREFIX = 'spectate:'


def spectate_room_id(room_id: str) -> str:
    """对局房间号 → 观战通道的 room 名。"""
    return SPECTATE_ROOM_PREFIX + str(room_id)


def is_spectate_room(room_id) -> bool:
    """这个 room 名是不是观战通道（防止观战通道的广播又拐回观战通道）。"""
    return isinstance(room_id, str) and room_id.startswith(SPECTATE_ROOM_PREFIX)


# 观战席上限（作者裁定：**上限 20 人**）。数字只有这一份：
# `server.handle_spectate_join` 的满员判定与 `_build_spectate_snapshot` 的
# `spectator_limit` 都读它，前端也从快照里拿 —— 前端不许再写一遍 20。
SPECTATOR_LIMIT = 20


# ---------------------------------------------------------------------------
# 座位标签（`p1` / `p2`）—— **全项目唯一实现**
# ---------------------------------------------------------------------------
# 为什么需要它：`room.players` 的 key 有两套约定（CLAUDE.md §6）——
# 自定义房是 `user_id`（游客是 sid），**匹配房一律是入座时的 socket sid**。
# 于是直接把 key 塞进给观众的 payload，观众看到的是一串浏览器连接 id：
# 既看不懂（认不出是哪个座位），又是**不该外发的连接标识**。
#
# 座位标签只在这里算一次：`_pub_magic_chain`（净化）与
# `server._build_spectate_snapshot`（快照）都调它 —— 两处各写一份必然漂移
# （教训 #1）。前端只渲染，不许自己把 sid 映射成 p1/p2。
SEAT_UNKNOWN = 'unknown'


def seat_order(room) -> list:
    """房间的座位顺序：`['<p1 的 key>', '<p2 的 key>']`（取不到返回空表）。

    `room` 允许传**房间对象**（正常路径）或**房间号字符串**（老调用点与守卫
    用例传的是 `.id`）—— 后者无法解析座位，于是标签一律退化成 `unknown`。
    退化方向是安全的：**宁可显示 unknown，也绝不回显原始 sid**。

    顺序 = `room.players` 的插入顺序 = 入座顺序（匹配房是配对时的 p1/p2）。
    """
    players = getattr(room, 'players', None)
    if isinstance(players, dict):
        return [str(pid) for pid in players]
    return []


def seat_label(room, player_id) -> str:
    """把一个座位的 key 换成 `p1` / `p2`；认不出来返回 `'unknown'`。

    ⚠️ 永远不返回原始 `player_id` —— 调用方拿到的要么是座位标签、要么是
       `unknown`，所以"漏回显 sid"这件事在函数层面就不可能发生。
    """
    if player_id is None or player_id == '':
        return SEAT_UNKNOWN
    order = seat_order(room)
    pid = str(player_id)
    if pid in order:
        return 'p%d' % (order.index(pid) + 1)
    return SEAT_UNKNOWN


def seat_label_map(room) -> dict:
    """`{座位 key: 'p1'/'p2'}`。给需要一次映射多处的调用方用。"""
    return {pid: 'p%d' % (i + 1) for i, pid in enumerate(seat_order(room))}


# ---------------------------------------------------------------------------
# 净化辅助（全部是纯函数）
# ---------------------------------------------------------------------------
# 这些 key 的值**一律是坐标数组** —— 出现在发给观众的任何 payload 的任何层级
# 都是泄漏，必须整条剥掉（不是"清空"，是删掉键本身）。
#
# ⚠️ 2026-09-22 第 2 批补进来的三个（`ship_positions` / `affected_positions` /
#    `revealed_positions`）是**实测发现**的：它们不在第 1 批那两个名字里，
#    而 `game_log` 的 detail 里真的带着坐标（见 `_pub_game_log`）。
COORDINATE_KEYS = (
    'positions', 'sunk_positions', 'ship_positions',
    'affected_positions', 'revealed_positions',
    'ships', 'hits',
)


def _strip_coord_keys(node):
    """**递归**剥掉坐标类 key，返回 (净化后的副本, 删掉的坐标条数)。

    递归是必须的：`game_log` 的 payload 是 `{ts,type,text,detail}`，
    坐标藏在 `detail` 里（`add_game_log(..., {'positions': [...]})`）——
    只扫顶层的话那两个调用点会整条漏过去。

    只删"键名就是坐标字段"的那些；`{'target': {'x':1,'y':2}}` 这类**已经公开的
    被轰格**必须保留（观众要看到"打哪儿了"）。
    """
    dropped = 0
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in COORDINATE_KEYS:
                if isinstance(value, (list, tuple)):
                    dropped += len(value)
                continue
            cleaned, sub = _strip_coord_keys(value)
            out[key] = cleaned
            dropped += sub
        return out, dropped
    if isinstance(node, list):
        out = []
        for value in node:
            cleaned, sub = _strip_coord_keys(value)
            out.append(cleaned)
            dropped += sub
        return out, dropped
    if isinstance(node, tuple):
        out = []
        for value in node:
            cleaned, sub = _strip_coord_keys(value)
            out.append(cleaned)
            dropped += sub
        return out, dropped
    return node, 0


def _scrub_positions(data: dict) -> tuple[dict, int]:
    """删掉 payload 里的坐标字段，返回 (净化后的副本, 删掉了几个坐标)。

    第 1 批只有这一层；第 2 批把它换成 `_strip_coord_keys` 的薄封装
    （**同一件事只留一份实现** —— 教训 #1）。对外语义不变，
    只是现在连嵌套层级里的坐标也一起剥掉。
    """
    return _strip_coord_keys(data)


def _as_int(value, default=0):
    """把可能是 str/None 的计数字段收敛成 int（绝不抛）。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _pub_shields_added(data, room=None):
    """卧薪尝胆：给全部存活船加盾 —— **动作**是"谁加了几艘"，**不是**"船在哪"。"""
    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    out['count'] = _as_int(out.get('count'))
    return out


def _pub_trap_set(data, room=None):
    """守株待兔：有人给自己一艘船打了陷阱 —— 保留"谁设了陷阱"，删掉是哪艘（坐标）。"""
    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    return out


def _pub_shield_absorbed(data, room=None):
    """仁王之盾挡下一炮 —— 保留"谁的盾破了"，**绝不保留**挨打那艘船的坐标。

    ⚠️ 这一条非常要紧：它广播的是**遭受攻击的那艘船的全部坐标**。
       挨打的那一格（攻击方打出的 x/y）在 `attack_result` 里是公开的，
       但整艘船的其它格子**没有**随之公开 —— 原样转发就是白送一艘船的完整位置。
    """
    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    return out


def _pub_trap_triggered(data, room=None):
    """守株待兔触发：对方要牺牲两艘。保留归属与牺牲数量，删掉被击沉那艘船的坐标。"""
    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    out['sacrificed'] = _as_int(out.get('sacrificed'))
    return out


def _pub_ship_sacrificed(data, room=None):
    """某艘船被牺牲（恶魔契约 / 绝处逢生）—— 动作可见，船在哪不可见。"""
    if not isinstance(data, dict):
        return None
    out, dropped = _scrub_positions(data)
    out['sacrificed_cells'] = dropped        # 让观众知道"这艘船有几格"，但不知道是哪几格
    return out


def _pub_summary_line(data, room=None):
    """"谁做了什么"的明文日志：**文字与归属都留着，坐标一律剥掉**。

    ★ 第 2 批实测发现的**真泄漏**（第 1 批漏掉的）：

    `server.add_game_log(room, text, 'magic', {'player':…, 'positions': […]})` ——
    `_sacrifice_ship` 那条日志把**被牺牲那艘船的全部格子**放进了 detail
    （`server.py` 约 10490）。而被牺牲的船往往**一格都没挨过炮**
    （恶魔契约 / 神之宣告 / 命运骰子），于是原样转发 = 把一艘完好战舰的位置
    直接送给观众 —— 正是核心不变量 #1 说"永远不许"的那件事。
    另一处（硫磺火焰，约 11836）带 `affected_positions`：那些格子虽然
    已由 `attack_result` 逐格公开，但按"坐标字段一个都不外发"的口径一并剥掉。

    第 1 批把 `game_log` 登记成"原样转发"的时候没抓到它 —— 因为守卫用例给的
    样例 detail 里只有已公开的被轰格。**样例没有坐标 ≠ 事件没有坐标**，
    这正是教训 #34 说的"零报错制造假象"，所以现在按事件名统一剥。
    """
    if not isinstance(data, dict):
        return None
    out, _ = _strip_coord_keys(data)
    return out


def _pub_magic_chain(data, room=None):
    """连锁栈：保留"谁打出了什么卡、有没有被康"，**剥掉 `targets`**。

    两个理由：
    1. `ChainItem.targets` 是**客户端提交上来的原始目标**（`data.get('targets', [])`），
       形状不受控 —— 既可能是船序号也可能是格子坐标，服务端**不做清洗**就塞进 broadcast。
       原样转发等于把一个形状未知的袋子里可能装着的坐标送给观众。
    2. `ChainItem` 被 `emit` 的 `default=lambda o: o.__dict__` 全量序列化，
       所以 `player_id`（**匹配房里是 socket sid**）原本也在 payload 里。

    ## `player_id` → 座位标签（第 2 批，作者已批准）

    原样下发 `player_id` 有两个毛病：观众看到一串看不懂的 sid；而且那是
    **连接标识**，不该外发。现在**删掉原始 `player_id`，只留 `seat`**
    （`p1`/`p2`，由 `seat_label` 算，全项目唯一一份实现）。

    ⚠️ 别改回"保留 player_id 再加个别名"—— 那等于 sid 照样发出去。
       `tests/test_spectate_batch2.py` 有一条守卫断言净化结果里
       **不出现原始 sid / user_id 字符串**。
    """
    if not isinstance(data, dict):
        return None
    chain = data.get('chain')
    if not isinstance(chain, (list, tuple)):
        return {'chain': [], 'chain_len': 0}
    out = []
    dropped = 0
    for item in chain:
        if isinstance(item, dict):
            entry = {k: v for k, v in item.items() if k not in ('targets', 'player_id')}
            if isinstance(item.get('targets'), (list, tuple)):
                dropped += len(item['targets'])
        else:
            entry = {}
        entry['seat'] = seat_label(room, item.get('player_id') if isinstance(item, dict) else None)
        out.append(entry)
    return {'chain': out, 'chain_len': len(out), 'targets_dropped': dropped}


# ---------------------------------------------------------------------------
# 允许给观众的事件表
# ---------------------------------------------------------------------------
# 值 = 净化函数；None = 原样转发（该事件的 payload 天然不含局面秘密）。
#
# ⚠️ **默认拒绝**：不在这张表里的事件一律不发观众（见 `sanitize_event`）。
#    往这里加事件之前先问一句"它的 payload 里有没有坐标 / 完整手牌 / 对方看不见的东西"。
#
# ⚠️ **在表里 ≠ 真的会发**：`emit` 的第三条腿只对**广播类**（`room=<对局房间号>`）
#    生效。表里有几个事件实际是 `to=<sid>` 或 `room=<sid>` 发的（`chat_message`、
#    `opponent_disconnected`、`opponent_reconnected`、`achievements_unlocked`、
#    `xp_gained`、`rank_changed`），它们**一个字节都到不了观战通道**：
#      · `to=<sid>`          → 单发不复制（私人消息，不是对局动作）；
#      · `room=<sid>`（误用）→ 被 `_live_room_id` 的门禁挡掉（sid 不是对局房间）。
#    留在表里是**穷举分类**的要求（每一处 emit 都必须表态），不是"观众能看到"的承诺。
SPECTATE_EVENTS = {
    # —— 核心动作：开炮与它的结果 ——
    # payload = attacker/x/y/hit/ship_sunk/remaining_attacks/双方剩余船数/shield_blocked。
    # 被攻击的那一格**本来就公开**（双方都看着那一炮打下去），必须给 ——
    # 少了它观众只能看到"有人在打"，看不到"打哪儿、中没中"。
    'attack_result': None,
    # —— 回合计时/阶段 ——
    'turn_change': None,
    'turn_skipped': None,
    'phase_updated': None,
    'attacks_updated': None,
    # —— 连锁 ——
    'magic_chain_updated': _pub_magic_chain,  # ★ 剥掉客户端提交的 targets
    'chain_resolved': None,
    # —— 打法记录（明文，观众最直接的信息来源）——
    # ★ `game_log` 的 **detail 里带过整艘船的坐标**（牺牲战舰那条）→ 必须净化。
    #   文字本身（`text`）是公开的，剥的只是 detail 里的坐标字段。
    'game_log': _pub_summary_line,
    'game_message': None,
    # 通用提示（`emit('message', ...)`，18 处）：payload 是 `{'message': str, 'type': str}`，
    # 全是给人看的文案，不含任何局面数据。它有时 `room=room.id`、有时 `to=<sid>`；
    # 单发那一半本来就到不了观战通道（单发不复制），广播那一半正是观众该看的。
    'message': None,
    # —— 猜拳结果：先手是谁对双方公开，观众当然也该看到 ——
    'rps_result': None,
    # —— 玩家之间的聊天（观众可见）——
    'chat_message': None,
    # —— 棋盘上的公开标记 ——
    # 神威洞：卡面就是"公开宣布 N 回合后这些格子有船"，双方都看得见 → 给。
    'shenwei_hole': None,
    'shenwei_hole_restored': None,
    # 冻结区：同上，范围是对双方公开的。
    'frozen_area': None,
    # 绝处逢生的"候选格"：服务端**有意公开**给双方（对方要据此知道唯一那艘新船可能在哪，
    # 而且这些格子必须能打）—— 所以它属于"公开信息"，不是泄漏。
    'last_stand_cells': None,
    'lanyu_recalled': None,
    # —— 场地魔法：贴了什么卡对双方都是公开的 ——
    'field_magic_updated': None,
    # —— 跨回合效果角标 ——
    'reinforcement_activated': None,
    'reinforcement_turn_updated': None,
    'holy_heart_activated': None,
    'holy_heart_interrupted': None,
    'holy_heart_turn_updated': None,
    'holy_heart_cleared': None,
    'reinforcement_cleared': None,
    'demon_contract_cleared': None,
    # —— 判定魔法 ——
    'dice_rolled': None,
    'dice_discard_complete': None,
    # —— 陷阱 ——
    'trap_expired': None,
    'trap_set': _pub_trap_set,               # ★ 含坐标 → 净化
    'trap_triggered': _pub_trap_triggered,   # ★ 含坐标 → 净化
    # —— 护盾 ——
    'shields_added': _pub_shields_added,     # ★ 含全部存活船坐标 → 净化（最严重的一处）
    'shield_absorbed': _pub_shield_absorbed,  # ★ 含挨打那艘船坐标 → 净化
    # —— 牺牲 ——
    'ship_sacrificed': _pub_ship_sacrificed,  # ★ 含坐标 → 净化
    # —— 对局终止 ——
    'game_over': None,
    'game_canceled': None,
    'opponent_disconnected': None,
    'opponent_reconnected': None,
    # 结算播报（给观众看"谁赢了、加了什么"）—— 只含"谁的账号"这类**账号级**公开信息，
    # 不含任何对局秘密或船只坐标。
    'achievements_unlocked': None,
    'xp_gained': None,
    'rank_changed': None,
    # —— 观战通道自己的一套（第 2 批）——
    # 这三个是**服务端直接发往 `spectate:<room_id>` 通道**的事件，不经 `emit` 的
    # 第三条腿（第三条腿只认"对局房间号"，观战通道名会被 `_live_room_id` 挡掉，
    # 于是不会自我循环）。它们天然只对观众有意义：
    'spectate_sync': None,           # 中途加入的**一次性快照**（只发给该观众）
    'spectate_count_changed': None,  # 观战人数变化（**只含人数，不含名单**）
    'spectate_ended': None,          # 对局房间被回收 → 观战结束
    # —— 观战席名单与观战席聊天（第 4 批）——
    # ★★ 本批最要紧的一条：**这五个只在观战通道里发**，对局双方**一个字节都收不到**。
    #    保证它的不是"发完再挑人过滤"（那种写法迟早漏），而是**通道本身**：
    #    观众只 `join_room('spectate:<id>')`、**从不进对局 room**，而玩家只在对局 room 里。
    #    两个 room 没有任何交集 ⇒ 隔离是结构性的，不是判断出来的。
    #    守卫：tests/test_spectate_batch4.py 用**真 socket** 两侧同时收件断言
    #    （观众收得到、两个玩家都收不到），并对 `spectate_chat_send` 做**源码级**扫描
    #    禁止它碰 `add_game_log`（那是**房间级广播**，一走玩家当场就看到）。
    'spectate_roster': None,         # 观战席名单 {spectators:[{name,joined_at}],count,limit}
    'spectate_joined': None,         # 有观众入席 {name}（只有**显示名**，无 uid/sid）
    'spectate_left': None,           # 有观众离席 {name}
    'spectate_chat': None,           # 观战席聊天 {name,message,ts}（**对局双方不可见**）
    # 观众自己那份"我叫什么"：用来把名单里**自己**那一行标出来。
    # 只单发给本人（`to=sid`），且**只含显示名** —— 座位识别仍只靠 `sides[].seat_id`
    # 与 `seat_labels`，这里不引入任何新的连接标识。
    'spectate_you': None,
}


# ---------------------------------------------------------------------------
# 明确不给观众的事件表
# ---------------------------------------------------------------------------
# 值 = **理由字符串**。空理由 = 没想清楚 → 直接报错（见 `_validate`）。
NOT_FOR_SPECTATORS = {
    # —— 整份局面快照：带 ships[].positions（有的还带 hand）——
    'game_state': '整份局面快照，含 ships[].positions 与对方攻击记录 —— 给了就是透视',
    'room_sync': '重连快照，41 个顶层键含 ships[].positions + hand（最毒的一处）',
    # —— 手牌：只看得到张数，看不到内容 ——
    'hand_updated': '手牌**内容**。观众只能看张数，不能看牌面',
    'active_effects': '按座位下发的效果角标，payload 是本方 effect_flags 全量',
    # —— 船只本体 ——
    'ships_updated': '本方船只的完整状态（含 positions / hits）',
    'player_ships_updated': '本方船只的完整状态（含 positions / hits）',
    'board_attacks_updated': '本方棋盘上的攻击记录（含 hit/ship_sunk 逐格结果）',
    'revealed_positions': '探测类卡揭示的坐标 —— 那是**付费情报**，不是公开信息',
    # —— 等待玩家交互的私有请求（只有当事玩家能回答）——
    'sacrifice_request': '牺牲选船请求：只有当事玩家能回答，观众看到也无法操作',
    'sacrifice_cancelled': '牺牲选船请求的取消（同上）',
    'placement_request': '布船/选格请求：只有当事玩家能回答',
    'placement_done': '布船完成回执（发给当事玩家）',
    'reset_gameboard': '重摆棋盘指令（发给当事玩家，会改他的界面状态）',
    'dice_discard_request': '命运骰子弃牌请求：只有当事玩家能回答',
    'chain_request': '连锁响应请求：只有当事玩家能回答，且会暴露他手上有什么',
    'priority_request': '优先权请求：私有的询问窗口',
    'priority_waiting': '优先权等待态：按座位下发',
    'priority_waiting_end': '优先权等待态解除：按座位下发',
    'priority_setting_updated': '优先权个人设置（账号级偏好，与对局无关）',
    # —— 其它按座位下发的私有事件 ——
    'taoyuan_complete': '桃园结义的选牌回执（发给当事玩家）',
    'taoyuan_choice': '与 taoyuan_complete 同源的选牌回执（`_safe_emit_to_player` 的三元分支）',
    'lingqi_complete': '灵气复苏的选牌回执（发给当事玩家）',
    'wangyang_complete': '滥竽充数的选牌回执（发给当事玩家）',
    'lingqi_waiting': '灵气复苏的等待态（发给对方）',
    'taoyuan_waiting': '桃园结义的等待态（发给对方）',
    'shenji_waiting': '神机妙算宣言窗口（发给对方）',
    'shenji_waiting_end': '神机妙算宣言窗口结束（发给对方）',
    # —— 匹配 / 大厅 / 连接（与某一局对局无关，观众不该收到）——
    'match_queued': '匹配队列回执（发给入队者本人）',
    'match_canceled': '取消匹配回执（发给本人）',
    'quick_chat': '局内快捷语（产品需求只要求观众看得到"玩家之间的聊天"）',
    'lobby_state': '大厅状态（发给在大厅的人；观战者已经不在大厅了）',
    'lobby_hello': '大厅 hello（同上）',
    'lobby_chat': '大厅聊天（不是对局内聊天）',
    'lobby_chat_history': '大厅聊天历史（同上）',
    'resume_game': '断线续玩回执（发给本人）',
    'reconnect_token': '重连令牌 —— **绝对不能**给第三方',
    'reconnect_warning': '重连警告（发给本人）',
    # —— 错误提示：发给谁只对谁有意义 ——
    'error': '错误提示：只对发起操作的那个连接有意义',
}


# 这些事件的原 payload 里**必然**带船坐标 —— 净化后必须一个都不剩。
# `tests/test_spectate_guards.py` 逐格钉住它们（这是本批最要紧的断言）。
MUST_NOT_LEAK_COORDS = (
    'shields_added',
    'shield_absorbed',
    'trap_set',
    'trap_triggered',
    'ship_sacrificed',
)

# 净化后**必须仍然带**这些字段（动作信息）—— 防的是"为了安全把该给的也砍了"。
MUST_KEEP_ACTION_FIELDS = {
    'attack_result': ('attacker', 'x', 'y', 'hit'),
    'shields_added': ('player', 'count'),
    'shield_absorbed': ('player',),
    'trap_set': ('player',),
    'trap_triggered': ('owner', 'sacrificed'),
    'ship_sacrificed': ('player',),
    # 日志那条：剥掉坐标之后**文字与归属必须还在** ——
    # 否则观众会从"看得到对局日志"退化成"日志一片空白"。
    'game_log': ('ts', 'type', 'text', 'detail'),
}

# 这些 key 出现在发给观众的 payload 里 = 已经是泄漏，测试直接判失败。
FORBIDDEN_PAYLOAD_KEYS = ('ships', 'positions', 'hits', 'sunk_positions')

# ---------------------------------------------------------------------------
# 观战快照（`server._build_spectate_snapshot`）的**禁字段表**
# ---------------------------------------------------------------------------
# 快照是**白名单另建**的（绝不复用 `_build_room_sync` 再删字段 —— 它有 41 个
# 顶层键，逐个删必然漏一个）。这张表是那件事的机器守卫：快照里**任何层级**
# 出现这些 key 就是泄漏，`tests/test_spectate_batch2.py` 递归扫它。
#
# 每一条都对应一个"若出现就等于透视"的东西：
#   ships / positions / hits / sunk_positions —— 船在哪（核心不变量 #1）；
#   hand / magic_hand                           —— 手牌**内容**（只能给张数）；
#   revealed_positions                          —— 探测卡揭示的坐标，是**付费情报**；
#   effect_flags / active_effects               —— 按座位下发的私有角标；
#   pending_placement / pending_sacrifice / pending_sacrifice_ships
#                                               —— 等待玩家交互的私有状态；
#   opponent_attacks                            —— 重连快照的私有键名（我方棋盘受击记录）；
#   sunk_ships / max_ships                      —— 对局私有计数。
SNAPSHOT_FORBIDDEN_KEYS = (
    'ships', 'positions', 'hits', 'sunk_positions',
    'hand', 'magic_hand', 'revealed_positions',
    'effect_flags', 'active_effects',
    'pending_placement', 'pending_sacrifice', 'pending_sacrifice_ships',
    'opponent_attacks', 'sunk_ships', 'max_ships',
)


# ---------------------------------------------------------------------------
# 校验 + 净化入口
# ---------------------------------------------------------------------------

def _validate():
    """模块导入期自检：两张表必须自洽。

    * 白名单与黑名单**绝不许有交集**（CLAUDE.md 教训 #10）；
    * `NOT_FOR_SPECTATORS` 的每个理由必须是**非空字符串**（写不出理由 = 没想清楚）；
    * `MUST_NOT_LEAK_COORDS` / `MUST_KEEP_ACTION_FIELDS` 里的事件必须是**允许给观众**的。
    """
    both = set(SPECTATE_EVENTS) & set(NOT_FOR_SPECTATORS)
    if both:
        raise ValueError('事件分类表自相矛盾（既给又不给）：%s' % sorted(both))
    for event, reason in NOT_FOR_SPECTATORS.items():
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('NOT_FOR_SPECTATORS 里的 %r 必须写明理由' % event)
    for event in MUST_NOT_LEAK_COORDS:
        if event not in SPECTATE_EVENTS:
            raise ValueError('%r 被要求"不许泄漏坐标"，却不在 SPECTATE_EVENTS 里' % event)
    for event in MUST_KEEP_ACTION_FIELDS:
        if event not in SPECTATE_EVENTS:
            raise ValueError('%r 被要求"保留动作字段"，却不在 SPECTATE_EVENTS 里' % event)
    # 快照的禁字段表与事件 payload 的禁字段表**不许互相矛盾**：
    # 后者是前者的子集（快照把 payload 那一套也一并禁掉）。
    stray = set(FORBIDDEN_PAYLOAD_KEYS) - set(SNAPSHOT_FORBIDDEN_KEYS)
    if stray:
        raise ValueError('快照禁字段表漏了事件 payload 的禁字段：%s' % sorted(stray))
    # 剥字段用的名字表必须覆盖"禁字段表"里所有坐标类字段 ——
    # 否则 `_strip_coord_keys` 会放过一个测试判红、而净化放行的键（两张表打架）。
    unscrubbed = set(FORBIDDEN_PAYLOAD_KEYS) - set(COORDINATE_KEYS)
    if unscrubbed:
        raise ValueError('COORDINATE_KEYS 漏了：%s' % sorted(unscrubbed))


_validate()


def is_spectatable(event) -> bool:
    """这个事件名允不允许发给观众。不在表里 = 不允许（默认拒绝）。"""
    return isinstance(event, str) and event in SPECTATE_EVENTS


def sanitize_event(event, data, room=None):
    """把一个事件净化成"可以发给观众"的版本。

    * 事件不在 `SPECTATE_EVENTS` → 返回 `None`（**默认拒绝**，调用方据此不发）；
    * 表里的值是 `None` → 原样返回；
    * 表里给了净化函数 → 返回它的结果（返回 `None` 同样表示"这次不发"）。

    `room`：**房间对象**（正常路径，`_emit_to_spectators` 传的就是它）或
    房间号字符串（老调用点 / 守卫用例按 `.id` 传）。净化函数的签名统一是
    `fn(data, room=None)`，需要的自己从 `room` 取座位等房间级信息；
    取不到 room 时必须**退化成安全的一侧**（例如座位标签退化成 `unknown`，
    绝不回显原始 sid）。
    """
    if not is_spectatable(event):
        return None
    fn = SPECTATE_EVENTS[event]
    if fn is None:
        return data
    return fn(data, room)


# ---------------------------------------------------------------------------
# 允许观战的判据
# ---------------------------------------------------------------------------

def can_spectate(allow_a, allow_b) -> bool:
    """这一局能不能被别人观战。

    **双方都允许**才算允许（作者裁定：观战开关是玩家的全局设置，只由自己的设置决定）。
    缺一边（`None` / 游客没有设置 / 读不到）= 不允许 —— **未知一律退化成"不允许"**，
    不能退化成"满足条件"（CLAUDE.md 教训 #21：隐私开关的方向必须朝安全那一侧兜）。
    """
    return bool(allow_a) and bool(allow_b)
