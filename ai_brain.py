# -*- coding: utf-8 -*-
"""大师难度 AI 的决策层（纯函数，无 I/O、无 socket、无全局状态）。

设计文档：`docs/MASTER_AI_2026_09_21.md` §4。

⚠️ **本模块不许 `import server`**（CLAUDE.md 教训 #19：运行期 import server 会
   把整个 server.py 再执行一遍成另一个模块对象，那份 socketio 发不出事件）。
   所以这里只依赖传进来的 `room` / `player` 对象，自己算需要的东西。

⚠️ **AI 不许作弊** —— 这是本模块最重要的约束，不是「尽量」：

   本模块跑在服务端，**理论上能直接读到 `room.players[对方].ships`（对方船位）**。
   一旦读了，AI 就变成全知，强度是假的，玩家也会立刻察觉。
   所以只允许读「真人坐在这个座位上也能看到的信息」：

     允许：自己的手牌/船/攻击次数/效果标记
           自己探明的敌船位置（`player.revealed_positions` —— 克苏鲁之眼/探测雷达给的）
           对方的 `remaining_ships`（界面上就显示）
           双方**已经打出去**的攻击记录（`player.attacks`，炮击是公开的）
           弃牌堆、对局日志、场上已发生的公开事件
     禁止：`对方.ships` 的位置与存活、`对方.magic_hand`（卡面明示可见的除外）、
           牌堆的顺序与内容、对方未公开的效果标记

   守卫见 `tests/test_ai_brain.py`：把对方船位改到别处、其余状态不变，
   本模块的输出必须**完全一致**。

⚠️ 所有函数都必须对残缺状态安全：**绝不抛异常**。但「拿不到信息」的返回值
   分两类，不能一刀切（详见 `tests/test_ai_brain.py`）：

     `choose_attack` / `choose_taunt`
         → 没有可打的格 / 不认识的事件，返回 `None`。
           调用方据此去进结束阶段，不会留下待办。

     `resolve_ship_pick` / `resolve_placement`
         → **必须仍然给出一个候选**，信息不足时退化成可复现的随机。
           因为它们回答的是「AI 自己的待办」：返回 None 会让那个待办
           **没人消费** → AI 的回合永远交不出去 —— 正是要消灭的失败模式。
           只有候选集本身为空时才返回 None（那时确实无解，由调用方兜底）。
"""

from __future__ import annotations

import random

# 棋盘边长。现有对局层到处写 `range(6)`，这里给个名字免得又长出一份魔法数。
BOARD_SIZE = 6


# ===========================================================================
# 只读小工具（都只碰「公开信息」）
# ===========================================================================

def _cell_of(pos):
    """把 `Position` 对象或 `{'x','y'}` 字典统一成 `(x, y)`；认不出来返回 None。"""
    if pos is None:
        return None
    if isinstance(pos, dict):
        x, y = pos.get('x'), pos.get('y')
    else:
        x, y = getattr(pos, 'x', None), getattr(pos, 'y', None)
    if isinstance(x, int) and isinstance(y, int):
        return (x, y)
    return None


def _cells_of(ship):
    """一艘船占的格子集合。"""
    out = set()
    for p in (getattr(ship, 'positions', None) or []):
        c = _cell_of(p)
        if c is not None:
            out.add(c)
    return out


def _opponent_id(room, me_id):
    """对局只有两个座位：取另一个。注意匹配房/自定义房的 key 都可能是 sid。"""
    for pid in (getattr(room, 'players', None) or {}):
        if pid != me_id:
            return pid
    return None


def _attacked_cells(player):
    """该玩家**已经轰过**的格子（炮击是公开信息，双方棋盘上都有痕迹）。"""
    out = set()
    for a in (getattr(player, 'attacks', None) or []):
        c = _cell_of(a)
        if c is not None:
            out.add(c)
    return out


def _known_enemy_cells(player, exclude=frozenset()):
    """自己**已经探明**的敌船位置（克苏鲁之眼 / 探测雷达给的）。

    注意语义方向：`players[X].revealed_positions` 是「X 知道的那些位置」，
    不是「X 被暴露的位置」——见 server.py 里克苏鲁之眼把施法者船位加进
    `对手.revealed_positions`。读反了就会拿对手的情报来打对手。
    """
    out = set()
    for p in (getattr(player, 'revealed_positions', None) or []):
        c = _cell_of(p)
        if c is not None and c not in exclude:
            out.add(c)
    return out


def _all_cells():
    return [(x, y) for x in range(BOARD_SIZE) for y in range(BOARD_SIZE)]


# ===========================================================================
# 开炮
# ===========================================================================

def choose_attack(room, ai_id, rng=None):
    """选一格开炮。`(x, y)`；无格可打则 None。

    现状（`server.py` 的 `_ai_turn_loop`）是 36 格**均匀随机**，而且
    **从不读 `revealed_positions`** —— 手上有情报也不用。这是最容易拿到的强度提升。

    规则：
      ① 自己已探明的敌船位置里还有没打过的 → 打它（**必中**）
      ② 否则在未轰过的格子里均匀挑

    ⚠️ 船是**单格船**（6 艘各占 1 格），所以没有「船形推理」的余地，
       情报就是全部优势。想再强只能靠更准的探明手段，不是靠更聪明的猜。
    """
    try:
        rng = rng or random.Random()
        me = (getattr(room, 'players', None) or {}).get(ai_id)
        if me is None:
            return None
        attacked = _attacked_cells(me)
        candidates = [c for c in _all_cells() if c not in attacked]
        if not candidates:
            return None
        known = sorted(_known_enemy_cells(me, exclude=attacked))
        if known:
            return rng.choice(known)          # 已探明 → 必中，优先打掉
        return rng.choice(candidates)
    except Exception:
        return None


# ===========================================================================
# 选船（替 AI 回答「选一艘自己的战舰」）
# ===========================================================================

def resolve_ship_pick(room, ai_id, reason, candidates, rng=None):
    """在**候选活船**里替 AI 挑一艘。`candidates` 由调用方算好（只含活船）。

    现状是 `random.choice(alive)`（server.py 的 `_request_ship_pick`），
    等于随机送一条船。按目的分策略：

      要牺牲 / 要被窥探的（demon_contract / divine_decree / dice_sacrifice /
      trap_sacrifice / kraken_eye）→ 挑**信息价值最低**的那艘：
        周围格被对方轰得越多，说明那片区域对方**已经探过**，
        暴露或失去它带来的新信息越少。

      守株待兔（trap_setup）→ 反过来挑**最可能先挨打**的船，
        让陷阱尽早触发；用「周围被轰过的格数最多」近似「对方正在往这片区域找」。

    ⚠️ 只用 `对方.attacks`（公开的炮击记录）来判断，不看 `对方.ships`。
    """
    try:
        rng = rng or random.Random()
        cands = [s for s in (candidates or []) if s is not None]
        if not cands:
            return None
        opp_id = _opponent_id(room, ai_id)
        opp = (getattr(room, 'players', None) or {}).get(opp_id) if opp_id else None
        probed = _attacked_cells(opp) if opp is not None else set()
        if not probed:
            # 对方还没开过炮 → 无信息可用，退化成确定性随机（注入的 rng 保证可复现）
            return rng.choice(cands)

        def neighbour_hits(ship):
            """这艘船周围（含自身格）有多少格是对方已经轰过的。"""
            n = 0
            for (x, y) in _cells_of(ship):
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if (x + dx, y + dy) in probed:
                            n += 1
            return n

        # 牺牲/暴露类：越多邻里被轰过 → 泄露代价越小 → 越该拿它去抵账
        best = max(range(len(cands)), key=lambda i: (neighbour_hits(cands[i]), -i))
        return cands[best]
    except Exception:
        return None


# ===========================================================================
# 放置（替 AI 回答「新船放哪」）
# ===========================================================================

def resolve_placement(room, ai_id, kind, candidates, rng=None):
    """在**合法候选格**里挑一个放新船。`candidates` 由调用方按各卡规则算好。

    规则：尽量放在**对方已经轰过**的格子 —— 对方无法重复轰同一格，
    放在那里等于免挨打（前提是这张卡允许，所以本函数只在给定候选里挑）。

    ⚠️ 各张卡对候选格有各自限制（例如滥竽充数的卡面写「未被对方打过的空格」），
       调用方算出的 `candidates` 已经是合法集，本函数**不做二次过滤**。
    """
    try:
        rng = rng or random.Random()
        cands = [c for c in (candidates or []) if c is not None]
        if not cands:
            return None
        opp_id = _opponent_id(room, ai_id)
        opp = (getattr(room, 'players', None) or {}).get(opp_id) if opp_id else None
        probed = _attacked_cells(opp) if opp is not None else set()

        def safety(cell):
            """该格「被对方轰过」得满分；否则看四邻被轰过的数量（对方在扫这片）。"""
            c = _cell_of(cell) or (cell if isinstance(cell, tuple) else None)
            if c is None:
                return -1
            if c in probed:
                return 100                      # 对方打过的格 → 不会再打
            x, y = c
            return sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                       if (x + dx, y + dy) in probed)

        best = max(range(len(cands)), key=lambda i: (safety(cands[i]), -i))
        return cands[best]
    except Exception:
        return None


# ===========================================================================
# 嘲讽
# ===========================================================================
# 台词做成数据表（照 quick_chat.py 的形状）：纯数据 + 纯函数，便于人工过一遍。
# 尺度：只在关键节点说话；有底气但不做人身攻击、不刷屏。
# 每个 event 多条候选，由 rng 挑，避免每局一模一样。

TAUNT_LINES = {
    # 自己击沉对方一艘
    'sink_opponent_ship': [
        '这一艘，我早就画好圈了。',
        '沉得挺干脆。',
        '你的阵型，比你想的好猜。',
    ],
    # 对方打空
    'opponent_missed': [
        '那片海我替你省了。',
        '再来，我等你找。',
        '这一炮，差得有点远。',
    ],
    # 自己被打沉一艘
    'lost_own_ship': [
        '好炮。这一下我认。',
        '记住这格了？那我也记住你了。',
        '互换，不亏。',
    ],
    # 对方打出高价值卡
    'opponent_played_big': [
        '大手笔。希望值这个价。',
        '舍得下本，那我也认真了。',
    ],
    # 对方只剩 1 艘
    'about_to_win': [
        '就剩一艘了，你藏好。',
        '最后一艘。别让我先找到。',
    ],
    # 自己落后 ≥2 艘
    'behind': [
        '现在你领先。别急着庆祝。',
        '落后两艘而已，牌还在我手里。',
    ],
    # 从落后追平/反超
    'comeback': [
        '追上来了。',
        '刚才那两艘，我记账了。',
    ],
}


def choose_taunt(room, ai_id, event, rng=None):
    """按关键节点挑一句台词；返回 str 或 None（None = 这次不说话）。

    只负责「说什么」，**不负责频率限制**——「同一 event 每局最多一次 +
    两次间隔 ≥20 秒」的状态归调用方管（它才知道房级状态与时序）。
    """
    try:
        lines = TAUNT_LINES.get(str(event or ''))
        if not lines:
            return None
        rng = rng or random.Random()
        return rng.choice(list(lines))
    except Exception:
        return None
