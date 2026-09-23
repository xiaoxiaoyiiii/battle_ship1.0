# -*- coding: utf-8 -*-
"""对局回放的**纯模块**：记录器 + 终局打包（契约见 `docs/REPLAY_2026_09_23.md` §2~§6）。

与 `ranks.py` / `spectate.py` / `quick_chat.py` 同路数：**纯函数、无 I/O、无 socket、
运行期绝不 `import server`**（CLAUDE.md 教训 #19：`python server.py` 时本模块名是
`__main__`，`import server` 会把整个 server.py 再执行一遍成**另一个模块对象** ——
那份 `socketio` 发不出事件、那份 `room_manager` 建的房在真进程里不存在，
而 pytest 里 server 就叫 `server`，**这类 bug pytest 永远测不到**，
守卫只能是源码级断言，见 `tests/test_replay_guards.py::test_replay_never_imports_server`）。

需要 server 的能力时，由 server.py 在 **import 期注入模块对象**（`bind()`），
本模块**按名字现取**（`_srv('...')`）—— 注入**函数对象**会把测试里的 monkeypatch
静默架空（教训 #19 后半句），所以注入的只有模块对象自己。

## 铁律：记录器**绝不 emit 任何东西**

回放数据里有**双方船位**。一旦这条数据进了对局房间（`emit(...)` / `socketio.emit`），
就是对局双方与观众当场拿到全透视 —— 灾难级泄露，而且**零报错**。
所以本模块连 `emit` / `socketio` 这两个词都不许出现（源码级守卫同上文件）。

## 数据形状（前端的唯一契约）

一条回放 = **现有 `game_logs` 的步骤序列 + 两条稀疏时间线（船位 / 手牌）+ 棋盘重置标记**。
不存每步全量快照（那会让体积涨 5~10 倍）。

* `steps[i] = {i, kind, actor, text, detail}` —— 按行动顺序；
* `ships[i] = {step, p1: [{x, y, alive, sunk, src}], p2: [...]}` —— **只在船位真变时**记一条；
  ⚠️ `src` = 这一格来自哪份数据源（`'ships'` 活船列表 / `'lost'` 显式沉没登记）。
  **同一格最多一条**，`lost` 优先 —— 判据与理由见 `_ship_cells` 的说明；
* `hands[i] = {step, p1: ['卡名', ...], p2: [...]}`      —— **只在手牌真变时**记一条；
* `effects[i] = {step, p1: {...}, p2: {...}}`            —— **只在效果真变时**记一条，
  **只带变了的座位**（与上面两条同一种"稀疏 + 增量"）；字段名**照抄**
  `_build_spectate_snapshot` 的公开效果段：`shield` / `shenwei_holes` / `frozen_area` /
  `last_stand_cells` / `last_stand_owner`（教训 #1：同一件事不许有两套字段名）；
* `board_resets[i] = {step, side}`                        —— `side` 是 `'p1'` / `'p2'`；
* `nodes[i] = {step, kind, label}`                        —— 进度条关键节点，**服务端算一次**。

⚠️ 玩家代号（`p1` / `p2`）**只在 `finalize()` 里按 `room.players` 的插入顺序算一次**
（与 `spectate.seat_order` 同一口径：插入顺序 = 入座顺序）。录制期间一律用**原始 pid**
当键，避免录制与打包两处各算一次而漂移（教训 #1）。
"""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# 版本与硬上限（契约 §3，数字只有这一份）
# ---------------------------------------------------------------------------
#: 回放 JSON 的格式版本。**它同时是"读接口要不要拒收"的判据**（契约 §6）：
#: 版本对不上 ⇒ 明确报错，绝不静默返回半份数据。
REPLAY_VERSION = 1

#: 步数上限（契约 §3）。触限 ⇒ **截断 + 明确标注**，绝不静默。
MAX_STEPS = 2000

#: 落库 blob 的硬上限（512 KB）。**读的时候也按它拒收**（契约 §1、§6）：
#: 坏 blob 不许打爆 1.8 GB 的机器（线上实测：可用 777 MB + 已在 swap）。
MAX_REPLAY_BYTES = 512 * 1024

#: 记录器在**一局之内**允许占用的最大步数 —— 与 `MAX_STEPS` 同一个数，
#: 但它管的是"内存里不许无界增长"（超了就丢弃后续步并打标记）。
_MAX_STEPS = MAX_STEPS

#: 截断时给玩家/前端看的说明（**绝不静默**：契约 §3）。
TRUNCATED_TEXT = '此回放被截断'

#: 回放数据挂在房间上的属性名。放房间级字段而不是 `magic_temp_data`
#: （教训 #30：`magic_temp_data` 有 8 处被整体覆写 `= {}`）。
_ROOM_ATTR = 'replay'

# game_log 的 `type` → 回放步骤的 `kind`。**只做一次映射**，前端按 `kind` 分支。
_KIND_BY_LOG_TYPE = {
    'attack': 'attack',
    'magic': 'magic',
    'quick_chat': 'quick_chat',
    'result': 'game_over',
    'system': 'system',
    'info': 'system',
    'achievements': 'system',
    'xp': 'system',
    'rank': 'system',
}

#: 进度条节点只认这几种（前端按 `kind` 画不同颜色）。
NODE_KINDS = ('magic', 'sunk', 'reset', 'phase', 'game_over', 'truncated')

#: 攻击步里**可以剥掉**的派生字段（只有"客户端能自己算出来"的才配进这张表）。
#:
#: * `shield_blocked` —— 前端重建棋盘只用 `hit` / `ship_sunk` / `target`（契约 §7），
#:   而"被护盾挡下"这件事文案里已经写了；实测每局省 6~7 KB（**信息一点没少**）。
#:   `hit` / `ship_sunk` **不许**剥：它们是"这一格画 ✕ 还是 ○ / 要不要加「沉」"的
#:   直接输入，剥了就得让前端去解析文案（那就长出第二份规则了 —— 教训 #1）。
#: 判据：`'target' in payload`（只有攻击步有 `target`，不会误伤别的 detail）。
_DETAIL_DERIVED_KEYS = ('shield_blocked',)

#: 六个"没有游戏内日志的行动"的 kind（契约 §3 第 2 条）。
ACTION_KINDS = ('place_ships', 'rps_choice', 'enter_battle', 'enter_end',
                'end_turn', 'surrender')

# ---------------------------------------------------------------------------
# 反向注入：server.py 在 import 期把**模块对象自己**交进来（不是一个函数）
# ---------------------------------------------------------------------------
_SERVER = None


def bind(server_module) -> None:
    """由 `server.py` 在 import 期调用：把 server 模块对象交给本模块。

    ⚠️ 注入的是**模块对象**，调用点一律 `getattr(_SERVER, 名字)` 现取
       （`_srv()`）—— 注入函数对象会把测试里的 monkeypatch **静默架空**
       （教训 #19）。没有 server（纯单测）时 `_srv()` 返回 None，
       记录器**照常工作**（它只需要 room 对象，不需要 server 的任何能力）。
    """
    global _SERVER
    _SERVER = server_module


def _srv(name):
    """按名字从注入的 server 模块取属性（取不到返回 None，绝不抛）。"""
    if _SERVER is None:
        return None
    return getattr(_SERVER, name, None)


# ---------------------------------------------------------------------------
# 房间上的状态（三件齐：这里初始化 + 明确消费点 + 回归用例）
# ---------------------------------------------------------------------------
def _state(room):
    """取房间的回放状态；没有就**惰性建**（`GameRoom.__init__` 也建了一份）。"""
    st = getattr(room, _ROOM_ATTR, None)
    if isinstance(st, dict):
        return st
    st = {
        'steps': [],
        'ships': [],        # 船位时间线（稀疏）
        'hands': [],        # 手牌时间线（稀疏）
        'effects': [],      # 场上公开效果时间线（稀疏 + 增量，见 _effects_state）
        'board_resets': [],  # [{step, side}]
        'nodes': [],        # [{step, kind, label}]
        'lost': {},         # 原始 pid → [(x, y), ...]：**主动牺牲**掉、但必须留在时间线里的格
        'last': None,       # 上一次快照（用来判"真的变了吗"）
        'truncated': None,  # None = 没截断；否则是原因字符串
    }
    try:
        setattr(room, _ROOM_ATTR, st)
    except Exception:       # noqa: BLE001 —— 假房间（测试替身）不挂属性也不许抛
        pass
    return st


def reset(room) -> None:
    """清空这一局的录制状态（重开一局 / 终局落库之后）。**唯一实现**。"""
    if room is None:
        return
    try:
        setattr(room, _ROOM_ATTR, None)
    except Exception:       # noqa: BLE001
        pass


def step_count(room) -> int:
    """已经录了多少步（0 = 这局什么行动都没有）。"""
    st = getattr(room, _ROOM_ATTR, None)
    if not isinstance(st, dict):
        return 0
    return len(st.get('steps') or [])


def is_truncated(room):
    """`None` = 没截断；否则返回**原因字符串**（绝不静默，契约 §3）。"""
    st = getattr(room, _ROOM_ATTR, None)
    if not isinstance(st, dict):
        return None
    return st.get('truncated')


# ---------------------------------------------------------------------------
# 稀疏快照
# ---------------------------------------------------------------------------
def _pids(room):
    """座位顺序的原始 pid 列表（与 `spectate.seat_order` 同一口径）。"""
    players = getattr(room, 'players', None)
    if isinstance(players, dict):
        return list(players.keys())
    return []


def _side_label(room, pid):
    """pid → `'p1'` / `'p2'`（认不出来返回 None，绝不回显原始 pid）。"""
    order = _pids(room)
    try:
        idx = order.index(pid)
    except ValueError:
        return None
    return 'p%d' % (idx + 1) if idx < 2 else None


def _is_alive(ship) -> bool:
    """存活判据与全局同一份：`len(hits) < len(positions)`。"""
    try:
        return len(ship.hits) < len(ship.positions)
    except Exception:       # noqa: BLE001 —— 假船对象：按"活着"处理，不炸
        return True


def _ship_cells(room, pid, player):
    """该座位**摆放中/已摆放**的全部船格：`[{'x','y','alive','sunk','src'}]`。

    * `alive` = 这一格所属的船**还没沉**（`len(hits) < len(positions)`）；
    * `sunk`  = 船已沉（前端画「沉」，与实战棋盘同口径）；
    * `src`   = 这一格是**哪一份数据源**说的（见下面那条优先级）。

    ★ **主动牺牲掉的船要留在时间线里**（作者实报："主动牺牲的船会在回放的棋盘中
      直接消失掉 而不是变成红色叉叉"）。`_do_demon_contract_sacrifice` 会
      `player.ships.remove(ship)`，而那些格子在游戏里**双方都看得到沉没位置**
      （那条日志/广播的原文：「公开广播：自己与对手都能看到这艘船被划掉」），
      所以它们必须照 `alive: False` + `sunk: True` 记着 —— 否则回放里凭空消失。

    ⚠️ **"记成沉没"只有一个入口**：`note_ship_lost`（由**主动牺牲**的实现点调用）。
       这里**绝不**去"diff 前后快照猜哪几格消失了" —— 那是从表象反推，会把
       滥竽充数收回的临时船（卡面明写"不会显示沉没"）、神威除外的船、换位的船
       一起误判成沉没（幻想出来的沉船比少画一个叉更难查）。
       同一件事的另外三种成因各有各的撤销口：`note_ship_returned`（船回来了）与
       `note_board_replaced`（棋盘整块换新）。

    ⚠️ 这份数据**只对回放看客**存在（自己/别人战绩里点开的那一屏）。
       它**绝不**经过 `emit()` —— 见模块开头那条铁律。

    ------------------------------------------------------------------
    ★★ 「这一格沉了没」有**两份数据源**时的口径（本批定的，不许静默改）：

    **`lost` 表（显式事实）优先于活船列表（推断）。**

    理由：活船列表推出"沉没"用的是一条**否定式推断** ——
    「这艘船**不在** `player.ships` 里 ⇒ 它沉了」；而 `lost` 表是**实现点当场登记
    的事实**（"这艘船因恶魔契约被献祭了"）。二者冲突时，事实压过推断。
    反过来（活船列表优先）等于让"看不见"盖住"看得见"：同一格同时被两份表提到时
    画成**活船** —— 可 `lost` 那一份是**人看得见的沉没**，画成活船就是
    在一格已经公开划掉的格子上重新画一艘船（幻影活船）。

    ⚠️ 这条优先级**排除了"两份表打架"这个状态本身**：本函数保证
       **同一格最多只出一条**（`lost` 里的格一律不出活船行）。
       所以它不依赖"前端取第一条还是最后一条" —— 前端 `replayCellOf` 的
       `for...break`（取第一条）与"以最后一条为准"的写法在这里**结果相同**。
       这不是巧合，是判据：谁把这里的过滤去掉，`src` 字段就会暴露那格里
       两条说法并存（守卫 `tests/test_replay_lost_priority.py` 当场红）。
    """
    # ① 显式事实那份先取齐（它在合并里**优先**）
    lost = _lost_cells(room, pid)
    lost_set = set(lost)

    # ② 活船列表那份：与 `lost` 撞车的格**整条丢掉**（不是"留一条活船"）
    out = []
    for ship in (getattr(player, 'ships', None) or []):
        try:
            alive = _is_alive(ship)
            for pos in (getattr(ship, 'positions', None) or []):
                x, y = int(pos.x), int(pos.y)
                if (x, y) in lost_set:
                    continue      # 见上面那条优先级：`lost` 说了算（一格只出一条）
                cell = {'x': x, 'y': y, 'alive': alive, 'src': 'ships'}
                if not alive:
                    cell['sunk'] = True
                out.append(cell)
        except Exception:   # noqa: BLE001 —— 假的船对象：跳过这一艘，不炸
            continue

    # ③ 显式事实那份按坐标升序接在后面（`lost` 内部本就保持登记顺序，
    #    这里排一次是为了"同一批坐标换个登记顺序"不改变输出 —— 只影响字节）。
    for (x, y) in sorted(lost):
        out.append({'x': x, 'y': y, 'alive': False, 'sunk': True, 'src': 'lost'})
    return out


def _hand_names(player):
    """该座位当前手牌的**卡名**列表（顺序即手牌顺序）。"""
    names = []
    for card in (getattr(player, 'magic_hand', None) or []):
        name = getattr(card, 'name', None)
        names.append(str(name) if name is not None else str(card))
    return names


def _snapshot(room):
    """当前局面的一份稀疏快照 `{pid: {'ships': [...], 'hand': [...]}}`。"""
    snap = {}
    for pid in _pids(room):
        player = room.players.get(pid)
        if player is None:
            continue
        snap[pid] = {'ships': _ship_cells(room, pid, player),
                     'hand': _hand_names(player)}
    return snap


# ---------------------------------------------------------------------------
# 主动牺牲掉的船格（作者实报：牺牲的船在回放棋盘上"直接消失"而不是变成红叉）
# ---------------------------------------------------------------------------
# 三个入口，缺一不可：
#   ① `note_ship_lost`      —— **只在主动牺牲的实现点**调用（`_do_demon_contract_sacrifice`
#      与 `绝处逢生` / `钢筋铁骨` 的自牺牲）。数据来源就是那里手上的 `positions`，
#      **不是**"diff 前后快照猜出来的"（从表象反推会把滥竽充数一起误判成沉没）；
#   ② `note_ship_returned`  —— 船回到棋盘（疗愈 / 死者苏生 / 神机妙算重新部署）：
#      旧格的红叉必须跟着消失；
#   ③ `note_board_replaced` —— 棋盘整块换新（灵气复苏 / 败者食尘 / 回光返照）：
#      旧棋盘上的沉船格一起作废。
#
# 存的是**坐标串**而不是船对象：这些坐标只活在"当前这一次录制"里，
# 而且 `player.ships` 那边已经有一份权威的活船格，这里只补"已经不在 ships 里、
# 但玩家看得见沉没"的那几格 —— 不复制活数据、不持有活对象引用。
def _lost_cells(room, pid):
    """该座位当前**登记为牺牲**的格 `[(x, y), ...]`（没有就空表，绝不抛）。"""
    st = getattr(room, _ROOM_ATTR, None)
    if not isinstance(st, dict):
        return []
    table = st.get('lost')
    if not isinstance(table, dict):
        return []
    return list(table.get(pid) or [])


def _xy_ints(positions):
    """`[{'x','y'}]` / `[(x, y)]` / `[[x, y]]` 一律收敛成 `[(x, y), ...]`（去重保序）。

    认不出来的一律丢掉（照 `_xy_pairs` 的口径：**绝不炸**）。
    """
    out = []
    seen = set()
    for item in (positions or []):
        try:
            if isinstance(item, dict):
                xy = (int(item['x']), int(item['y']))
            else:
                xy = (int(item[0]), int(item[1]))
        except Exception:       # noqa: BLE001
            continue
        if xy in seen:
            continue
        seen.add(xy)
        out.append(xy)
    return out


def _forget_lost_cells(room, pid, positions):
    """把这几格从"牺牲"登记里撤掉（船回来了 / 棋盘换新了）。"""
    st = getattr(room, _ROOM_ATTR, None)
    if not isinstance(st, dict):
        return
    table = st.get('lost')
    if not isinstance(table, dict):
        return
    gone = set(_xy_ints(positions))
    if not gone or pid not in table:
        return
    left = [xy for xy in (table.get(pid) or []) if xy not in gone]
    if left:
        table[pid] = left
    else:
        table.pop(pid, None)


def _record_at_current_step(room) -> None:
    """立刻按**当前这一步**（`len(steps) - 1`）记一次快照。

    为什么需要它（本批实测栽过一次）：`_append` 只在**下一步**追加时比对快照，
    所以"撤销牺牲登记"如果只改状态、不推动记录器，**这一帧永远不变** ——
    实测 `handle_confirm_reinforcement` 的 `revive` 分支里注册撤销之后，
    时间线里那一格照样是 `{'alive': False, 'sunk': True}`（回放里红叉不消失），
    因为紧接的 `_finish_placement` 没有日志、下一处日志还在别的函数里。

    ⚠️ 记的是 `len(steps) - 1` = **刚刚发生的那一步**（语义与 `_append` 一致：
       时间线的 `step = k` 表示"第 k 步做完之后的局面"）。
       `len(steps) == 0` 表示这一步都还没被记下来（比如重放/直调内部函数），
       那时不记 —— 下一步追加时会按"变化了"补上，不会丢。

    ★ **同一步只留一行**：`_append` 在追加第 k 步时已经记过一行（那一刻的中间态），
      这里再记一次属于"同一步的第二次快照" —— 处理成**改写那一行**（而不是再追加
      一条 `step` 相同的行）。两条 `step=k` 的行在增量语义下是**同一帧的两份说法**，
      前端逐条叠加上去虽然"看着对"（后者盖前者），但任何按 step 去重的消费者都会算错。
      实测（本批）：不给这一层，"神威！"致死那一帧会让时间线里出现
      `[{step:0,…},{step:0,…}]` 这样两条同 step 的行。
    """
    st = _state(room)
    step = len(st.get('steps') or []) - 1
    if step < 0:
        return
    _record_snapshot(room, st, step)
    _merge_same_step_ships_rows(st, step)


def _merge_same_step_ships_rows(st, step) -> None:
    """把船位时间线里**同一个 `step` 的多行合成一行**（保留最后一份状态）。

    ⚠️ 为什么需要它：`_record_snapshot` 是"同一帧可以记很多次"的（`_append` 每追加一步
       就记一次），而"船真的变了"这件事可能在**同一步里发生第二次**（复活类收尾、
       `神威！` 致死 + 洞）。增量语义下这是**同一帧的两份说法**，前端逐条叠加虽然
       "后者盖前者"看着对，但任何按 `step` 去重的消费者都会算错，白占体积。

    判据只看"最后两行是不是同一步"，所以对"本来就没有重复"的时间线是**空操作**。
    """
    rows = st.get('ships')
    if not isinstance(rows, list) or len(rows) < 2:
        return
    last, prev = rows[-1], rows[-2]
    if not (isinstance(last, dict) and isinstance(prev, dict)):
        return
    if int(last.get('step', -1)) != step or int(prev.get('step', -1)) != step:
        return
    merged = dict(prev)
    merged.update(last)          # 后记的那一份 = 更新后的状态（逐座位替换）
    rows[-1] = merged
    rows.pop(-2)


def refresh_ships(room) -> None:
    """按**当前**局面刷新一次船位时间线（当前这一步）。**幂等**。

    给"船位在**没有日志**的流程里变了"的那几处用（`handle_confirm_reinforcement`：
    复活 / 神机妙算重新部署 / 绝处逢生的唯一一艘；`apply_magic_effect` 的 `神威！`：
    致死格要登记成沉没、神威洞也要进效果时间线 —— 这一整段同样不写"船位变了"的日志）。
    纯状态没变时它什么都不记（`_record_snapshot` 自己比对），所以可以随手调用。

    ⚠️ 它**只记船位**（不记步骤、不 emit）—— 时间线是稀疏的，没变就不写。

    ⚠️ **当前这一步已经有行时，这里是"改写那一行"而不是"再追加一行"**（见
       `_record_at_current_step`）—— 否则时间线里会出现**两条 step 相同的行**：
       前端 `replayFoldTimeline` 逐条叠加时后者会盖掉前者，看着也对，但它同时意味着
       "两条 step=k 的行不相等"（同一帧两份快照），任何按 step 去重的实现都会出错。
    """
    if room is None:
        return
    _record_at_current_step(room)


def note_ship_lost(room, player_id, positions) -> None:
    """喂一口**主动牺牲**（`demon_contract` / `divine_decree` / `dice_sacrifice` /
    `trap_sacrifice` 四种 reason 唯一汇到的那个实现点）。

    `positions` 就用调用方手上的那一份（`[{'x','y'}, ...]`）——**别去 diff 快照**：
    同一格"不再有船"至少有四种成因（牺牲 / 滥竽充数收回 / 换位重摆 / 除外），
    只有"主动牺牲"在游戏里是**双方看得见的沉没**，其余三种该消失就得消失。

    ⚠️ 必须在**那一步的日志之前**调用：喂数据的是 `add_game_log` 末尾的
       `replay.note`，登记晚一步这一帧就记不到沉没格了。
    ⚠️ 本函数**不记步骤、不 emit** —— 只改记录器自家状态。
    """
    if room is None or not player_id:
        return
    cells = _xy_ints(positions)
    if not cells:
        return
    st = _state(room)
    table = st.get('lost')
    if not isinstance(table, dict):
        table = st['lost'] = {}
    now = list(table.get(player_id) or [])
    known = set(now)
    for xy in cells:
        if xy not in known:
            known.add(xy)
            now.append(xy)
    table[player_id] = now


def note_ship_returned(room, player_id, ship) -> None:
    """喂一口**船回到棋盘上**（疗愈 / 死者苏生 / 神机妙算重新部署）。

    ⚠️ **必须在改这艘船的 `positions` 之前调用**（调用方先 `forget` 再搬）——
       否则撤销的是新位置，旧格的红叉会永远留在回放里。

    ⚠️ 本函数**只改登记**，不记快照：登记与"这一帧真的记下来"是两件事，
       而且**必须在船的状态完全落定之后**才记（否则记下来的是中间态）。
       调用方负责在收尾处调 `refresh_ships(room)` —— 实测
       `handle_confirm_reinforcement` 的 `revive` / `shenji_redeploy` 两支
       **全程没有任何日志**（`_finish_placement` 也不写），不补那一次刷新，
       这一帧永远不变、红叉不会消失。
    """
    if room is None or not player_id or ship is None:
        return
    _forget_lost_cells(room, player_id, [{'x': p.x, 'y': p.y}
                                         for p in (getattr(ship, 'positions', None) or [])])


def note_board_replaced(room, board_owner_id=None) -> None:
    """喂一口**棋盘整块换新**（灵气复苏 / 败者食尘 / 回光返照重摆）。

    旧棋盘上的船全没了 ⇒ 留在旧棋盘上的牺牲格也一起作废（不许变成幻影沉船）。
    ⚠️ 与 `note_board_reset` **故意分开**：那一个只擦掉攻击标记（观战也在用同一个失效点），
       而"旧棋盘上的沉船格作废"是回放独有的账，混在一起会让"重置"这个动作
       顺手多出一个语义（下一次有人复用 `note_board_reset` 时就会不期而然地清掉沉船）。
    """
    if room is None:
        return
    st = _state(room)
    table = st.get('lost')
    if not isinstance(table, dict):
        table = {}
        st['lost'] = table
    for pid in ([board_owner_id] if board_owner_id else _pids(room)):
        table.pop(pid, None)
    _record_at_current_step(room)


# ---------------------------------------------------------------------------
# 场上公开效果（作者实报：回放里看不到仁王之盾的护盾格、神威挖的洞、冻结区…）
# ---------------------------------------------------------------------------
# ⚠️ 口径**照抄** `_build_spectate_snapshot` 里的那一份（教训 #1：同一件事只有一份字段名）。
#    那边已经裁定过"这些坐标本来就是有意公开给双方的"：
#      · `shenwei_holes`    —— 卡面公开宣布"N 回合后这些格子有船"；
#      · `frozen_area`      —— 范围对双方公开（`owner` = 落在谁那块棋盘上）；
#      · `last_stand_cells` —— 服务端有意公开（对方要据此知道新船可能在哪，而且得能打）；
#      · `last_stand_owner` —— 上面那批候选格的归属棋盘。
#    回放比观战更宽（回放本来就全透视），但这几项**不是**因为"回放能多给"才加的，
#    而是因为它们本来就是公开信息 —— 别在这里顺手加未公开的东西。
#
# ⚠️ 护盾（仁王之盾 / 卧薪尝胆）**不在 `game_effects` 里**，它记在
#    `PlayerShip.shield` 上（实测：`_apply_magic_effect` 里逐艘 `ship.shield = True`，
#    见 server.py 的'仁王之盾'分支与'卧薪尝胆'分支）。所以这里从船对象取。
#    并发出去的 `shield` 是**坐标对**（`[[x, y], ...]`，与 `last_stand_cells` 同形状），
#    而**不是**每格一条 `{'x','y'}`：按"船"记的话，船沉了 / 被换掉时增量会算不清楚。
_EFFECT_FIELDS = ('shield', 'shenwei_holes', 'frozen_area',
                  'last_stand_cells', 'last_stand_owner')


def _xy_pairs(values):
    """把 `[(x, y), ...]` / `[[x, y], ...]` / `{'x','y'}` 一律收敛成 `[[x, y], ...]`。"""
    out = []
    for item in (values or []):
        try:
            if isinstance(item, dict):
                out.append([int(item['x']), int(item['y'])])
            else:
                out.append([int(item[0]), int(item[1])])
        except Exception:       # noqa: BLE001 —— 认不出来的一律丢掉，绝不炸
            continue
    return out


def _shield_cells(player):
    """该座位**当前有护盾**的船格坐标（有序，便于逐字比较）。"""
    out = []
    for ship in (getattr(player, 'ships', None) or []):
        try:
            if not getattr(ship, 'shield', False):
                continue
            for pos in (getattr(ship, 'positions', None) or []):
                out.append([int(pos.x), int(pos.y)])
        except Exception:       # noqa: BLE001
            continue
    out.sort()
    return out


def _effects_of(room, pid):
    """某一个座位上**当前**的公开效果（`_EFFECT_FIELDS` 五个字段，一个不少）。

    ⚠️ **归属一律转成座位代号**（`'p1'` / `'p2'`），绝不下发原始 pid / user_id。
       `game_effects` 里这两个字段存的是原始 pid（匹配房里就是入座 sid），
       照原样放进回放 JSON 等于把"谁是谁"送出去（契约 §6：响应里不许有 user_id）。
       —— 这是本批**实测抓到的**：`test_effects_never_leak_a_raw_pid` 第一版就是红的。
    """
    player = (getattr(room, 'players', None) or {}).get(pid)
    effects = getattr(room, 'game_effects', None)
    effects = effects if isinstance(effects, dict) else {}
    player_id = getattr(player, 'sid', None) or pid
    holes = []
    for hole in (effects.get('shenwei_holes') or []):
        try:
            if hole.get('player') != player_id:
                continue
            holes.append({'x1': int(hole['x1']), 'y1': int(hole['y1']),
                          'x2': int(hole['x2']), 'y2': int(hole['y2'])})
        except Exception:       # noqa: BLE001
            continue
    frozen = effects.get('frozen_area')
    frozen_out = None
    if isinstance(frozen, dict) and frozen.get('owner') == player_id:
        # 字段与 `_build_spectate_snapshot` 的那一份**逐个对应**
        # （那边是 `{x1, y1, x2, y2, owner, frozen}`），不顺手多带 `caster` / `until_round`。
        frozen_out = {'x1': int(frozen['x1']), 'y1': int(frozen['y1']),
                      'x2': int(frozen['x2']), 'y2': int(frozen['y2']),
                      'owner': _side_label(room, player_id),
                      'frozen': frozen.get('frozen')}
    owner = effects.get('last_stand_owner')
    out = _empty_effects()
    out['shield'] = _shield_cells(player) if player is not None else []
    out['shenwei_holes'] = holes
    out['frozen_area'] = frozen_out
    # 绝处逢生的候选格只记在**施法者**那一侧（另一侧是空表）
    if owner == player_id:
        out['last_stand_cells'] = _xy_pairs(effects.get('last_stand_cells'))
        out['last_stand_owner'] = _side_label(room, player_id)
    return out


def _empty_effects():
    """一份"什么效果都没有"的效果（**五个字段一个不少**）。

    单独拆出来是为了让"基线"与"真的没有"**逐字段可比** —— 手写一个 `{}` 会
    与 `_effects_of` 的返回值不相等，于是开局永远被判成"变化了"。
    """
    return {'shield': [], 'shenwei_holes': [], 'frozen_area': None,
            'last_stand_cells': [], 'last_stand_owner': None}


def _has_any_effect(value) -> bool:
    """这一份效果里**真的**有没有东西。

    ⚠️ 别写成 `bool(value)`：`_effects_of` 返回的是一个**键一个不少**的 dict
       （五个字段都在，只是值为空表 / None），而**非空 dict 恒为真**
       ⇒ 那个判据恒成立、等于没有判据 —— 于是每局都会在 step 0 记一条
       "五个字段全空"的行（本批实测抓到，本项目的教训 #34 同族：
       看着在判断，其实永远为真，而且不报错）。
    """
    if not isinstance(value, dict):
        return False
    return bool(value.get('shield') or value.get('shenwei_holes')
                or value.get('frozen_area') or value.get('last_stand_cells')
                or value.get('last_stand_owner'))


def _effects_state(room):
    """当前**双方**的公开效果 `{pid: {...}}`（比对增量用）。"""
    return {pid: _effects_of(room, pid) for pid in _pids(room)}


def _record_snapshot(room, st, step):
    """快照与上一次**逐字段比对**，真变了才各追加一条时间线（稀疏 + **增量**）。

    ⚠️ 判据必须是"**真的变了吗**"而不是"有没有调用"：`add_game_log` 在 37 个点被调，
    绝大多数调用并不改船位/手牌 —— 每次都记一条会让体积涨 5~10 倍（契约 §0）。

    ★ 每条只写**这一条里真的变了的座位**（另一侧不出现）：前端把它当成**增量**、
    按 `step` 升序合并（契约 §7 的"船位 = 时间线里最后一个 `step ≤ k` 的条目"
    按此实现）。实测（seed=17、5 回合、82 步的真对局）两条时间线合计常驻 19 KB，
    其中只有开局那条同时带 p1/p2，其余每条只带一侧。

    ★ `effects` 用**完全同一种**稀疏 + 增量口径（作者实报：回放里看不到效果格）。
    它比另两条更"安静"：绝大多数步两个座位都没变化，所以一条都不记。
    """
    snap = _snapshot(room)
    last = st.get('last')
    last_effects = st.get('last_effects')
    effects_now = _effects_state(room)

    def _row(kind_key):
        return {'step': step,
                **{side: snap[pid][kind_key]
                   for pid in snap
                   for side in [_side_label(room, pid)]
                   if side and _changed(pid, kind_key)}}

    def _changed(pid, kind_key):
        if last is None:
            return True
        return (last.get(pid) or {}).get(kind_key) != snap[pid][kind_key]

    ships_row = _row('ships')
    hands_row = _row('hand')
    # `step` 之外一个座位都没有 = 什么都没变（理论上不会走到：调用方先比过）
    if len(ships_row) > 1:
        st['ships'].append(ships_row)
    if len(hands_row) > 1:
        st['hands'].append(hands_row)

    # 效果时间线：**同一种"真变了才记 + 只带变了的座位"**（稀疏 + 增量）。
    # ⚠️ 这条是**逐字段替换**语义（不是合并）：某一侧出现时，它带着 `_EFFECT_FIELDS`
    #    的全部字段，前端把 `step ≤ k` 的条目叠上去即可 —— 与 `ships`/`hands` 一致。
    #
    # ⚠️ 两条**都不能省**（各有各的坑，本批都实测踩过）：
    #   ① "**变成空**"必须记 —— 盾被打掉之后前端要靠这条空表把盾**撤掉**，
    #      漏了就永远画着一个不存在的盾（`_has_any_effect(now)` 为假也不许跳过）；
    #   ② "**从头到尾都空**"不许记 —— 绝大多数局一个效果都没有，
    #      "每局一条空行"纯属白占体积，而且它会让前端多画一次空效果。
    #      判据必须同时看**上一次**：只有"以前也没有、现在也没有"才算什么都没发生。
    # ⚠️ 这里不能省 `last_effects` 的赋值：它是"下次跟谁比"的基线，
    #    漏了会让下一条把同一份状态**再记一次**。
    effects_row = {'step': step}
    changed = []
    for pid, value in effects_now.items():
        side = _side_label(room, pid)
        if not side:
            continue
        # ⚠️ 基线（还没有上一次快照）按**全空**算：开局"一个效果都没有"不是变化，
        #    记进去只会白占一条（与上面第 ② 条同一个道理）。
        before = (last_effects or {}).get(pid) or _empty_effects()
        if before != value:
            effects_row[side] = value
            changed.append((before, value))
    if len(effects_row) > 1 and any(
            _has_any_effect(before) or _has_any_effect(now)
            for (before, now) in changed):
        st['effects'].append(effects_row)

    st['last'] = snap
    st['last_effects'] = effects_now


# ---------------------------------------------------------------------------
# 步骤
# ---------------------------------------------------------------------------
def _actor_name(room, pid):
    """pid → 显示名（取不到退回 pid 本身，与 `server._log_name` 同口径）。"""
    player = (getattr(room, 'players', None) or {}).get(pid)
    name = getattr(player, 'name', None) if player is not None else None
    return str(name or pid) if (name or pid) else None


def _step_detail(payload):
    """只留可以 JSON 化的标量/小结构（不复制活对象，教训：别序列化活数据）。

    ⚠️ **攻击步要剥掉两个派生字段**（`hit` / `ship_sunk` 保留，`shield_blocked` 不留）：
       它们是**同一件事的第二次表达** —— 前端的棋盘重建只读 `hit` / `ship_sunk` /
       `target`（契约 §7），文案里也已经写了"被护盾挡下"。实测每局能省下 6~7 KB
       （82 步的局里这一步占 19.5 KB → 12.5 KB），而**一个字节的信息都没少**。
    """
    if not isinstance(payload, dict):
        return {}
    drop = _DETAIL_DERIVED_KEYS if 'target' in payload else ()
    out = {}
    for k, v in payload.items():
        if k in drop:
            continue
        if v is None or isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        elif isinstance(v, (list, tuple)) and all(
                isinstance(x, (str, int, float, bool)) for x in v):
            out[str(k)] = list(v)
        elif isinstance(v, dict):
            inner = {str(k2): v2 for k2, v2 in v.items()
                     if isinstance(v2, (str, int, float, bool))}
            if inner:
                out[str(k)] = inner
    return out


def _mark_node(st, step, kind, label):
    """记一个进度条关键节点（`kind` 必须在 `NODE_KINDS` 里）。"""
    if kind not in NODE_KINDS:
        return
    st['nodes'].append({'step': step, 'kind': kind, 'label': str(label)})


def _append(room, kind, text, detail=None, actor=None):
    """所有步骤的**唯一追加点**：封顶 + 快照 + 关键节点。"""
    st = _state(room)
    step = len(st['steps'])
    if step >= _MAX_STEPS:
        # 内存里不许无界增长。触限**明确标注**（绝不静默，契约 §3）。
        if not st['truncated']:
            st['truncated'] = '%s（超过 %d 步）' % (TRUNCATED_TEXT, _MAX_STEPS)
            _mark_node(st, step, 'truncated', TRUNCATED_TEXT)
        return None
    entry = {
        'i': step,
        'kind': str(kind),
        'actor': actor,
        'text': str(text),
        'detail': _step_detail(detail),
    }
    st['steps'].append(entry)
    _record_snapshot(room, st, step)
    _node_from_step(st, step, entry)
    return entry


def _node_from_step(st, step, entry):
    """服务端**算一次**关键节点（前端不重新推导，契约 §3）。"""
    kind = entry.get('kind')
    detail = entry.get('detail') or {}
    if kind == 'magic':
        _mark_node(st, step, 'magic', '使用【%s】' % detail.get('card', '魔法卡'))
    elif kind == 'attack':
        if detail.get('ship_sunk'):
            target = detail.get('target') or {}
            _mark_node(st, step, 'sunk',
                       '击沉战舰 (%s,%s)' % (target.get('x'), target.get('y')))
        elif detail.get('hit'):
            target = detail.get('target') or {}
            _mark_node(st, step, 'hit', '命中 (%s,%s)' % (target.get('x'), target.get('y')))
    elif kind == 'game_over':
        _mark_node(st, step, 'game_over', entry.get('text') or '对局结束')


def note(room, entry) -> None:
    """喂一口**游戏内日志**（`add_game_log` 末尾调，一处覆盖 38 个记录点）。

    `entry` 是 `server.GameLog.to_dict()` 的形状：`{ts, type, text, detail}`。
    本函数**不改 entry、不 emit、不写 game_logs** —— 只往房间的回放状态里追加一步。
    """
    if room is None or not isinstance(entry, dict):
        return
    log_type = entry.get('type') or 'info'
    detail = entry.get('detail') if isinstance(entry.get('detail'), dict) else {}
    actor_pid = detail.get('attacker') or detail.get('caster') or detail.get('winner')
    _append(room,
            _KIND_BY_LOG_TYPE.get(log_type, 'system'),
            entry.get('text') or '',
            detail,
            _actor_name(room, actor_pid) if actor_pid else None)


def note_action(room, kind, label, detail=None, actor=None) -> None:
    """喂一口**没有游戏内日志的行动**（契约 §3 第 2 条的 6 个单一实现点）。

    ⚠️ **绝不往 `room.game_logs` 加行**：游戏内日志是既有玩家可见功能，
       本批不改它的显示（加行会让玩家那边凭空多出几条他们没见过的日志）。

    * `kind`   —— 步骤种类（六个之一，见 `ACTION_KINDS`），前端按它画节点；
    * `label`  —— 给玩家看的这一步在做什么（进 `text`，同时做进度条节点文案）；
    * `detail` —— 可选的小 dict（只留标量）；
    * `actor`  —— 可选：行动者的显示名。
    """
    if room is None:
        return
    entry = _append(room, kind, label, detail, actor)
    if entry is not None and kind in ACTION_KINDS:
        _mark_node(_state(room), entry['i'], 'phase', str(label))


def note_board_reset(room, board_owner_id=None) -> None:
    """喂一口**棋盘重置**（复用第 5 批为观战加的 4 个失效点，一处地方两个消费方）。

    * `board_owner_id` = 哪一位的棋盘被换掉了（`回光返照` 只清施法者那一块）；
      传 None 表示双方都换（`灵气复苏` / `败者食尘`）。

    ⚠️ **不能只靠 attack 步反推**：重摆之后棋盘"变干净了"，攻击历史里没有这件事
       （第 5 批那个 bug 的回放版，见契约 §9 表格）。
    """
    if room is None:
        return
    st = _state(room)
    step = len(st['steps'])
    targets = [board_owner_id] if board_owner_id else _pids(room)
    for pid in targets:
        side = _side_label(room, pid)
        if side:
            st['board_resets'].append({'step': step, 'side': side})
    label = '棋盘重置（%s）' % (_actor_name(room, board_owner_id) if board_owner_id
                                else '双方')
    _mark_node(st, step, 'reset', label)


# ---------------------------------------------------------------------------
# 终局打包
# ---------------------------------------------------------------------------
def _blob_bytes(payload) -> int:
    """这一份 payload 落库会占多少字节（`ensure_ascii=False`，与 db 侧一致）。"""
    return len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def _trim_timeline(rows, max_step):
    """把时间线砍到 `step <= max_step`（**保留 step == max_step 的最后一条**）。

    ⚠️ 时间线是**增量**（每条只带变了的座位），所以合并时必须把 `step <= max_step`
       的条目**全部按序叠上去**，不能只取最后一条。
    ⚠️ 也不能简单 `row['step'] <= max_step` 就完：截断点那一帧可能是
       `step == 保留步数`（终局快照）—— 那一帧正是"打完之后"的最终局面，
       砍掉它前端就永远画不出终局棋盘。
    """
    return [row for row in rows if int(row.get('step', -1)) <= max_step]


def build(room):
    """把房间里的录制内容打包成**回放 JSON**（`dict`，可 `json.dumps`）。

    单独拆出来是为了给守卫用例直接断言"打包出来的形状"，不必走落库。
    """
    st = getattr(room, _ROOM_ATTR, None)
    st = st if isinstance(st, dict) else {}
    order = _pids(room)
    names = {}
    for idx, pid in enumerate(order[:2]):
        player = room.players.get(pid)
        names['p%d' % (idx + 1)] = str(getattr(player, 'name', '') or '')

    # 步骤里的 `_side`（录制期用原始 pid 当键）换成 `p1`/`p2`。
    steps = []
    for entry in list(st.get('steps') or []):
        row = dict(entry)
        sides = row.pop('_side', None)
        if sides:
            row['sides'] = sides
        steps.append(row)

    # 「这局什么时候开打的」**只有一个判据**：`server._match_started_at(room)`
    # —— 优先 `room.match_started_at`（猜拳结束、真正进入 attacking 时打点），
    # 没有打点才退回 `room.created_at`。**这里不许自己读 `created_at`**：那会让同一个概念
    # 长出第二份判据（教训 #1），而且自定义房可能建好后放很久才开局，
    # 直接读 `created_at` 会把"对局时间"标早十几分钟。
    # 纯单测没注入 server 时（`_srv()` 返回 None）退回 `created_at`：只影响这一个**展示**字段，
    # 它不参与任何门禁 —— 教训 #2 禁的是"拿会兜底的取数函数当判据"，不是禁展示用兜底。
    started_at = 0
    _started_fn = _srv('_match_started_at')
    if _started_fn is not None:
        started_at = int(_started_fn(room) or 0)
    if not started_at:
        started_at = int(getattr(room, 'created_at', 0) or 0)

    payload = {
        'version': REPLAY_VERSION,
        'p1_name': names.get('p1', ''),
        'p2_name': names.get('p2', ''),
        # ★ 「谁是哪一块棋盘」的**权威口径**，落库时与 blob 一起存进
        #   `match_replays.replay_seats`（读接口按它算 `you_are`）。
        #   ⚠️ 它是 `原始 pid → 'p1'/'p2'`，**绝不下发**（契约 §6：响应里不许有 user_id）；
        #      读接口只把请求者的 uid 在服务端换成代号，返回的是代号。
        'seats': _seats_payload(room),
        'started_at': started_at,
        'steps': steps,
        'ships': list(st.get('ships') or []),
        'hands': list(st.get('hands') or []),
        'effects': list(st.get('effects') or []),
        'board_resets': list(st.get('board_resets') or []),
        'nodes': list(st.get('nodes') or []),
        'truncated': st.get('truncated'),
    }
    return payload


def _shrink(payload):
    """blob 超过 `MAX_REPLAY_BYTES` 时**截断并明确标注**（绝不静默，契约 §3）。

    截断顺序（先砍最不重要的）：
      ① 步数折半（同时把时间线砍到同一位置）；
      ② 时间线砍到只剩最后一条；
      ③ 关键节点只留前 200 个。

    仍然超限（理论上不可能：2000 步 × 几百字节 ≈ 几百 KB 以内）时，
    只留最小的合法骨架 + 明确标注 —— **绝不返回半份能骗过前端的 JSON**。
    """
    payload = dict(payload)
    payload['truncated'] = '%s（超过 %d KB）' % (TRUNCATED_TEXT, MAX_REPLAY_BYTES // 1024)
    original_steps = len(payload.get('steps') or [])

    def _too_big(p):
        return _blob_bytes(p) > MAX_REPLAY_BYTES

    # ① 步数折半（直到装得下或只剩 1 步）
    while _too_big(payload) and len(payload.get('steps') or []) > 1:
        keep = max(1, len(payload['steps']) // 2)
        payload['steps'] = payload['steps'][:keep]
        payload['ships'] = _trim_timeline(payload.get('ships') or [], keep)
        payload['hands'] = _trim_timeline(payload.get('hands') or [], keep)
        payload['effects'] = _trim_timeline(payload.get('effects') or [], keep)
        payload['board_resets'] = [r for r in (payload.get('board_resets') or [])
                                   if int(r.get('step', 0)) <= keep]
        payload['nodes'] = [n for n in (payload.get('nodes') or [])
                            if int(n.get('step', 0)) <= keep]

    # ② 时间线只留最后一条（前端仍能画出终局那一帧）
    if _too_big(payload):
        for key in ('ships', 'hands', 'effects'):
            rows = payload.get(key) or []
            payload[key] = rows[-1:] if rows else []

    # ③ 节点只留前 200 个
    if _too_big(payload):
        payload['nodes'] = (payload.get('nodes') or [])[:200]

    # ④ 兜底：只留最小骨架（步骤全砍）。**仍然带明确标注**。
    if _too_big(payload):
        payload['steps'] = []
        payload['ships'] = []
        payload['hands'] = []
        payload['effects'] = []
        payload['board_resets'] = []
        payload['nodes'] = []

    payload['truncated_steps'] = original_steps - len(payload['steps'])
    return payload


def finalize(room):
    """产出最终 JSON 的**唯一入口**：打包 → 上限校验 → 返回 `dict`（或 None）。

    返回 `None` 表示这局**没有可回放的内容**（0 步）—— 契约 §9：生产里真有这种行，
    那时 `has_replay=false`，前端把按钮置灰并写明原因。

    ⚠️ 本函数**不清空内存**：清空是落库之后的收尾（`server._finalize_match` 在
       `finally` 里调 `reset(room)`），保证"落库失败也不会把录制内容留在房间里"。
    """
    if room is None:
        return None
    if step_count(room) <= 0:
        return None
    payload = build(room)
    if _blob_bytes(payload) > MAX_REPLAY_BYTES:
        payload = _shrink(payload)
    return payload


def blob_bytes(payload) -> int:
    """公开的字节数计算（测试与调用方都用它，避免两处各算一次）。"""
    return _blob_bytes(payload or {})


def deep_size(obj, _seen=None) -> int:
    """对象图的常驻字节数（只算**容器自身**，不重复算共享对象）。

    用来兑现契约 §1 那条内存账（"记录器每局常驻 ≤30 KB"）—— 它是**实测量**，
    不是估算：`sys.getsizeof` 只给容器本身的大小，所以这里沿容器递归累加，
    并用 id 去重（两个步骤共用同一个字符串时只算一次，与真实内存一致）。
    """
    import sys
    if _seen is None:
        _seen = set()
    oid = id(obj)
    if oid in _seen:
        return 0
    _seen.add(oid)
    size = sys.getsizeof(obj, 0)
    if isinstance(obj, dict):
        for k, v in obj.items():
            size += deep_size(k, _seen) + deep_size(v, _seen)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            size += deep_size(item, _seen)
    return size


# ---------------------------------------------------------------------------
# 保留策略 / 权限的**客户端**辅助（判定在 db.py 与 server.py，这里只做纯计算）
# ---------------------------------------------------------------------------
def replay_participants(winner_user_id, loser_user_id):
    """落库时记的"参与者"两列：`{'winner': ..., 'loser': ...}`（无账号为 None）。

    ⚠️ **不能从 `matches.winner_id` 反推**：实测那一列里混着 uuid / `ai-*` /
       游客 sid，长度上无法可靠区分（契约 §2 的理由）。
    """
    return {'winner': winner_user_id or None, 'loser': loser_user_id or None}


def _seats_payload(room):
    """`{原始 pid: 'p1'|'p2'}`（只有**真账号**进得来；取不到的座位不出现）。

    这是"谁是哪一块棋盘"的**唯一权威口径**：`p1_name` / `p2_name` 同上，都来自
    `room.players` 的插入顺序（= 入座顺序）。落库时跟着 blob 一起存，
    读接口按它算 `you_are` —— **不能**用"胜者就是 p1"去推（那只是巧合，见 `you_are`）。
    """
    seats = {}
    for pid in _pids(room):
        player = (getattr(room, 'players', None) or {}).get(pid)
        uid = getattr(player, 'user_id', None)
        side = _side_label(room, pid)
        if uid and side:
            seats[str(uid)] = side
    return seats


def you_are(payload, match_row, viewer_uid):
    """请求者在这条回放里是哪一位：`'p1'` / `'p2'` / `None`（旁观者）。

    ⚠️ **返回的只有代号，绝不下发任何 user_id**（契约 §6）。

    ★ 判据是 `payload['seats']`（落库时按 `room.players` 的**插入顺序**记下的
      `uid → p1/p2`），也就是 `p1_name` / `p2_name` 的**同一份口径**。
      作者实报的缺陷：原来写成"胜者 ⇒ p1、败者 ⇒ p2"，而插入顺序与胜负**毫无关系** ——
      于是败者被当成 p1、赢的那位被当成 p2，界面上 `（你）` 挂到了**对面**那一侧，
      而 `p1_name` 是"AI"、`(你)` 就标在 AI 上（截图实证）。
      这是一个**方向写反**型的 bug（教训 #7）：单测全绿是因为夹具里恰好让
      `winner == p1`（对称局面测不出方向）。

    * 老 blob（没有 `seats`：本批之前落的）退回旧口径 —— 它**可能**是错的，
      但"少一个自我标识"比"标到对面"危害小，而且这些老回放会随 30 局窗口自然过期。
    """
    if not viewer_uid or not isinstance(match_row, dict):
        return None
    viewer_uid = str(viewer_uid)
    seats = (payload or {}).get('seats')
    if isinstance(seats, dict):
        side = seats.get(viewer_uid)
        if side in ('p1', 'p2'):
            return side
        # `seats` 里没有他 **且** 他也不是这一局的参与者 ⇒ 旁观者，返回 None 是对的。
        if viewer_uid not in (str(match_row.get('winner_user_id') or ''),
                              str(match_row.get('loser_user_id') or '')):
            return None
        # 落到这里 = 本局参与者、但录制时没拿到他的 uid（游客坐席 / AI 坐席）。
        # 他确实有一块棋盘，只是说不出是哪一块 —— 退回胜负口径（可能错，但比不标好）。
    # —— 老回放（没有 `seats` 字段）与上面这条兜底路径共用同一判据 ——
    if match_row.get('winner_user_id') and str(match_row['winner_user_id']) == viewer_uid:
        return 'p1'
    if match_row.get('loser_user_id') and str(match_row['loser_user_id']) == viewer_uid:
        return 'p2'
    return None

