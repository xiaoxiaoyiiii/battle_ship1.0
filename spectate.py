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


# ---------------------------------------------------------------------------
# 净化辅助（全部是纯函数）
# ---------------------------------------------------------------------------

def _scrub_positions(data: dict) -> tuple[dict, int]:
    """删掉 payload 里的坐标字段，返回 (净化后的副本, 删掉了几个坐标)。

    当前项目里坐标字段只有这两个名字（`positions` / `sunk_positions`）。
    `ships` / `hits` 是"坐标数组"的同族字段，一并删掉 —— 宁可多删也不放行。
    """
    out = {}
    dropped = 0
    for key, value in data.items():
        if key in ('positions', 'sunk_positions', 'ships', 'hits'):
            if isinstance(value, (list, tuple)):
                dropped += len(value)
            continue
        out[key] = value
    return out, dropped


def _as_int(value, default=0):
    """把可能是 str/None 的计数字段收敛成 int（绝不抛）。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _pub_shields_added(data):
    """卧薪尝胆：给全部存活船加盾 —— **动作**是"谁加了几艘"，**不是**"船在哪"。"""
    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    out['count'] = _as_int(out.get('count'))
    return out


def _pub_trap_set(data):
    """守株待兔：有人给自己一艘船打了陷阱 —— 保留"谁设了陷阱"，删掉是哪艘（坐标）。"""
    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    return out


def _pub_shield_absorbed(data):
    """仁王之盾挡下一炮 —— 保留"谁的盾破了"，**绝不保留**挨打那艘船的坐标。

    ⚠️ 这一条非常要紧：它广播的是**遭受攻击的那艘船的全部坐标**。
       挨打的那一格（攻击方打出的 x/y）在 `attack_result` 里是公开的，
       但整艘船的其它格子**没有**随之公开 —— 原样转发就是白送一艘船的完整位置。
    """
    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    return out


def _pub_trap_triggered(data):
    """守株待兔触发：对方要牺牲两艘。保留归属与牺牲数量，删掉被击沉那艘船的坐标。"""
    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    out['sacrificed'] = _as_int(out.get('sacrificed'))
    return out


def _pub_ship_sacrificed(data):
    """某艘船被牺牲（恶魔契约 / 绝处逢生）—— 动作可见，船在哪不可见。"""
    if not isinstance(data, dict):
        return None
    out, dropped = _scrub_positions(data)
    out['sacrificed_cells'] = dropped        # 让观众知道"这艘船有几格"，但不知道是哪几格
    return out


def _pub_magic_chain(data):
    """连锁栈：保留"谁打出了什么卡、有没有被康"，**剥掉 `targets`**。

    两个理由：
    1. `ChainItem.targets` 是**客户端提交上来的原始目标**（`data.get('targets', [])`），
       形状不受控 —— 既可能是船序号也可能是格子坐标，服务端**不做清洗**就塞进 broadcast。
       原样转发等于把一个形状未知的袋子里可能装着的坐标送给观众。
    2. `ChainItem` 被 `emit` 的 `default=lambda o: o.__dict__` 全量序列化，
       所以 `player_id`（**匹配房里是 socket sid**）也在 payload 里。
       本批按"不改对局逻辑"的约束只做标注说明，不做替换 —— 见下面 `seat` 字段。

    保留的是观众真正需要的那部分：卡名、入链顺序、有没有被无效化（以及被哪张康的）。
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
            entry = {k: v for k, v in item.items() if k != 'targets'}
            if isinstance(item.get('targets'), (list, tuple)):
                dropped += len(item['targets'])
        else:
            entry = {}
        # ⚠️ `player_id` 在匹配房里是**座位登记的 socket sid**。本批不改对局逻辑，
        #    因此仍随 payload 下发；观众拿它只能当"这是同一个座位的第 N 次出牌"用。
        #    要不要换成座位标签（'p1'/'p2'）留给后续批次与作者定夺。
        entry['seat'] = entry.get('player_id') if entry.get('player_id') else 'unknown'
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
    'game_log': None,
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
}

# 这些 key 出现在发给观众的 payload 里 = 已经是泄漏，测试直接判失败。
FORBIDDEN_PAYLOAD_KEYS = ('ships', 'positions', 'hits', 'sunk_positions')


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


_validate()


def is_spectatable(event) -> bool:
    """这个事件名允不允许发给观众。不在表里 = 不允许（默认拒绝）。"""
    return isinstance(event, str) and event in SPECTATE_EVENTS


def sanitize_event(event, data, room=None):
    """把一个事件净化成"可以发给观众"的版本。

    * 事件不在 `SPECTATE_EVENTS` → 返回 `None`（**默认拒绝**，调用方据此不发）；
    * 表里的值是 `None` → 原样返回；
    * 表里给了净化函数 → 返回它的结果（返回 `None` 同样表示"这次不发"）。

    `room` 可选：目前没有净化函数需要它，留着是为了后续批次（例如按房间状态
    确认某个坐标确实已经公开）不必再改 `emit` 的调用形状。
    """
    if not is_spectatable(event):
        return None
    fn = SPECTATE_EVENTS[event]
    if fn is None:
        return data
    return fn(data)


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
