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
# 敌船位置模型（只用公开信息 —— 谁也不许读 `opponent.ships`）
# ===========================================================================
#
# ⚠️ 这里**不猜船形**：本项目是单格船（6 艘各占 1 格），所以「哪些格一定是空的」
#    就是全部可推的东西，剩下的只能靠探明与均匀挑 —— 没有船形推理的余地。
#
#    · 打过的格（命中/未命中）→ 绝不可能还有船（单格船，打中就沉）
#    · 自己探明的格（克苏鲁之眼 / 探测雷达）→ **一定有船**
#    · 其余 → 未知
#
# 这三档就是「一炮下去命中概率」的全部依据。当前实现只用到前两档，
# 第三档留给将来（例如对方船数 > 0 时未知格的后验概率）。


def enemy_cell_model(room, ai_id):
    """返回 `(known, safe, unknown)` 三个格子集合 `{(x, y)}`。

    · `known`   —— 一定有敌船（自己探明的，且还没打过）
    · `safe`    —— 一定没有敌船（自己打过的格：单格船，打了就没了）
    · `unknown` —— 还没探过、也没打过的格

    纯读公开信息：`me.revealed_positions`（我探明的）与 `me.attacks`（我轰过的）。
    签名里没有 `ai_id` 之外的输入，绝不遍历 `opponent.ships`。
    """
    me = (getattr(room, 'players', None) or {}).get(ai_id)
    empty = (set(), set(), set())
    if me is None:
        return empty
    attacked = _attacked_cells(me)
    known = _known_enemy_cells(me, exclude=attacked)
    unknown = {c for c in _all_cells() if c not in attacked}
    return known, attacked, unknown


def attack_priority(room, ai_id, cell):
    """单独给一格打分：越大越该打。返回 float，认不出返回 -1。

    `known`(必中) 远高于 `unknown`(可能命中)，两者都远高于 `safe`(必不中)。
    这一条让「按情报开炮」与「别打已知空的格」同时成立 —— 现状是 36 格
    均匀随机，等于**反复往已经证明是空的格子里开炮**。
    """
    try:
        known, safe, _unknown = enemy_cell_model(room, ai_id)
    except Exception:
        return -1.0
    c = _cell_of(cell) or (cell if isinstance(cell, tuple) else None)
    if c is None:
        return -1.0
    if c in known:
        return 3.0
    if c in safe:
        return 0.0
    return 1.0


def threatenable_cells(room, ai_id):
    """还**可能**藏着敌船的格（未知 + 已探明）。空集 = 对面全被打完了。"""
    known, _safe, unknown = enemy_cell_model(room, ai_id)
    return known | unknown


# ===========================================================================
# 开炮
# ===========================================================================

def choose_attack(room, ai_id, rng=None):
    """选一格开炮。`(x, y)`；无格可打则 None。

    现状（`server.py` 的 `_ai_turn_loop`）是 36 格**均匀随机**，而且
    **从不读 `revealed_positions`** —— 手上有情报也不用。这是最容易拿到的强度提升。

    规则：
      ① 自己已探明的敌船位置里还有没打过的 → 打它（**必中**）
      ② 否则在「还没打过」的格子里均匀挑
      ③ 全打完了 → None

    ⚠️ 规则 ② 的分母用 `unknown`（= 未打过 − 已探明为空）而不是整整 36 格：
       单格船**打中即沉**，所以"打过而没中"的格子是**证明为空**的。
       现状的均匀随机会把炮弹反复送进这些格子 —— 那是纯浪费，不是运气问题。

    ⚠️ 船是**单格船**（6 艘各占 1 格），所以没有「船形推理」的余地，
       情报就是全部优势。想再强只能靠更准的探明手段，不是靠更聪明的猜。
    """
    try:
        rng = rng or random.Random()
        me = (getattr(room, 'players', None) or {}).get(ai_id)
        if me is None:
            return None
        known, _safe, unknown = enemy_cell_model(room, ai_id)
        if known:
            return rng.choice(sorted(known))     # 已探明 → 必中，优先打掉
        if unknown:
            return rng.choice(sorted(unknown))
        return None
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

    ⚠️ `trap_setup` 这条是 2026-09-22 补的：旧实现把它和"要牺牲"当成同一件事，
       于是给**要设陷阱**的船也挑"信息价值最低"的那艘 —— 与卡面目的正好相反
       （陷阱希望这艘船尽早被打到）。两条判据现在分开写。

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

        # 守株待兔（trap_setup）是**反向**目标：希望这艘船尽早被打到，让陷阱触发。
        # 所以它挑"对方正在往这片找"的那艘 —— 判据就是邻里被轰过的格数**最多**。
        if str(reason or '') == 'trap_setup':
            return cands[max(range(len(cands)),
                             key=lambda i: (neighbour_hits(cands[i]), -i))]

        # 牺牲/暴露类：越多邻里被轰过 → 泄露代价越小 → 越该拿它去抵账。
        #
        # ⚠️ 试过一版"更讲道理"的启发式：把"周围一格都没被搜过的船"判为最不该牺牲
        #    （对方知道位置就白赚一艘），实测**没有变好**：
        #      同批 2000 局 · 旧版 69.5% / 新版 68.7%（差 0.8 个百分点，在噪声内，
        #      但至少没有证据支持新版）。
        #    → 所以保留这一版。**"讲得通"不等于"更强"**，两版都留在
        #      `tools/master_ablation.py` 的 `ship_old` / `ship_new` 里可随时复测。
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


# ===========================================================================
# 牌价值表
# ===========================================================================
# 这是**调参的主入口**：离线自对弈搜索就是在这张表（外加下面几个乘子）上搜
# （见 docs/MASTER_AI_2026_09_21.md §7.4）。数值按「这张牌大概能换回多少优势」定，
# 分档口径：
#     进攻性（直接减少对方船数）   80-95
#     资源/手牌（换牌、抽牌）      55-75
#     防守/续航（回血、加盾）      50-70
#     条件性（需前置才生效）       基础值 +10，条件不成立时归零（见 _situational）
#     重摆类（回光返照/败者食尘）   30-45，局面越差越加分
#
# ⚠️ 这张表必须覆盖**每一张能摸到的卡**（`钢筋铁骨` 除外，它在
#    `HIDDEN_CARD_NAMES` 里，双方都摸不到）。漏一张的后果是那张牌
#    价值恒为 0 → AI 永远不打它 → 逐卡测试会红。守卫见 tests/test_ai_brain.py。

CARD_BASE_VALUE = {
    # —— 进攻性
    '轰炸': 92,            # 整行/整列，能一次灭多艘
    '火力全开': 88,
    '神威！': 85,
    'Freezing！': 85,      # 直接跳掉对方的整个回合
    '死者苏生': 85,        # 沉船回来等于直接追回船差
    '余音绕梁': 82,
    '滥竽充数': 82,        # 补满船数（大回合末收回）
    '神之宣告': 80,
    '五险一金': 80,
    '硫磺火焰': 80,
    '冻结': 78,
    '无暇圣心': 78,
    '增援': 78,
    '命运骰子': 76,        # 期望为正但方差大
    '极限增援': 75,
    '绝处逢生': 75,
    '探测雷达': 74,        # 情报卡：先探明再打，价值靠后续兑现
    '明智埋葬': 74,        # 能看到对方手牌，埋掉最能翻盘的那张
    '看破！': 72,
    '疗愈': 72,
    '守株待兔': 72,
    '无中生有': 70,
    '卧薪尝胆': 70,
    '教皇旨意': 70,        # 需要配「弃卡换攻击」才划算（见 T7）
    '桃园结义': 70,
    '溅射': 70,
    '百亿补贴': 68,
    '八方来财': 68,
    '饮血': 68,
    '神机妙算': 68,
    '仁王之盾': 66,
    '越战越勇': 66,
    '盗亦有道': 66,
    '失灵！': 65,          # 主要走连锁，不主动打
    '亡羊补牢': 65,
    '禁忌果实': 64,
    '雷达子弹': 62,
    '恶魔契约': 62,
    '伊甸园': 60,
    '加百列之光': 60,
    '灵气复苏': 60,
    '平等条约': 58,
    '克苏鲁之眼': 55,      # 代价是暴露自己一艘船
    '回光返照': 45,        # 重摆：局面越差越值
    '败者食尘': 40,
}

# 出牌阈值：低于它就不打（宁可留手，也不白烧一张）。
PLAY_THRESHOLD = 50
# 每回合出牌预算（现状是 1 张；大师放到 3 张，但不到处倒手牌）。
CARDS_PER_TURN = 3

# 「必须刚命中/刚击沉才有意义」的卡 —— 条件不成立时价值归零。
# 现状是这几张随机打出去只会被退牌，等于废牌（CLAUDE.md 里记着）。
NEEDS_LAST_HIT = {'溅射', '雷达子弹'}
NEEDS_LAST_SUNK = {'越战越勇', '饮血'}


def card_value(name):
    """某张牌的基础价值；没登记的返回 0（调用方据此不打它）。"""
    try:
        return int(CARD_BASE_VALUE.get(str(name or ''), 0))
    except Exception:
        return 0


def _last_attack(room):
    """上一次炮击的结果快照（公开信息）。拿不到就返回空 dict。"""
    la = getattr(room, 'last_attack', None)
    return la if isinstance(la, dict) else {}


def _situational(room, ai_id, name):
    """局势乘子。返回一个 float 系数（1.0 = 不修正，0.0 = 这张牌现在别打）。

    只读公开信息：自己的船、对方的剩余船数（界面上就显示）、上一次炮击结果、
    双方手牌**张数**（不是内容）。
    """
    me = (getattr(room, 'players', None) or {}).get(ai_id)
    if me is None:
        return 0.0
    opp_id = _opponent_id(room, ai_id)
    opp = (getattr(room, 'players', None) or {}).get(opp_id) if opp_id else None

    my_ships = int(getattr(me, 'remaining_ships', 0) or 0)
    opp_ships = int(getattr(opp, 'remaining_ships', 0) or 0) if opp else 0
    behind = opp_ships - my_ships          # >0 = 我落后

    k = 1.0

    # ① 条件卡：前置不成立就是废牌，价值直接归零
    la = _last_attack(room)
    if name in NEEDS_LAST_HIT and not la.get('hit'):
        return 0.0
    if name in NEEDS_LAST_SUNK and not la.get('ship_sunk'):
        return 0.0

    # ② 卧薪尝胆：卡面要求「自己船数 < 对方」
    if name == '卧薪尝胆' and behind <= 0:
        return 0.0

    # ③ 重摆类：只有局面很差时才值得把盘面推倒重来
    if name in ('回光返照', '败者食尘'):
        if behind >= 2:
            k *= 1.8
        elif behind <= 0:
            k *= 0.5

    # ④ 落后时进攻卡加码、领先时防守卡加码
    if name in ('轰炸', '神威！', '神之宣告', '硫磺火焰'):
        k *= 1.0 + min(0.4, 0.15 * max(0, behind))
    if name in ('疗愈', '仁王之盾', '卧薪尝胆', '无暇圣心'):
        k *= 1.0 + min(0.4, 0.15 * max(0, -behind))

    # ⑤ 手牌少时抽牌类更值钱
    hand = len(getattr(me, 'magic_hand', None) or [])
    if name in ('无中生有', '八方来财', '亡羊补牢') and hand <= 2:
        k *= 1.5

    # ⑥ 克苏鲁之眼：**双方各暴露一艘**。单格船下"被暴露 = 必被击沉"，
    #    所以它不是纯收益，而是**信息交换**：换到对方一艘、赔上自己一艘。
    #    只有在自己手里的情报比对方少时才划算（对方已经知道我几艘船了，
    #    再暴露一艘的边际代价小；而我因此多知道它一艘）。
    #    ⚠️ 实测：不做这个判别时它会成为大师出得最多的一张（占比 31%），
    #       等于每局白送对方几次必中。
    if name == '克苏鲁之眼':
        mine_known = len(set(_known_enemy_cells(me)))
        theirs_known = 0
        if opp is not None:
            theirs_known = len(set(_known_enemy_cells(opp)))
        if theirs_known <= mine_known:
            k *= 0.35          # 我的情报不少于对方 → 这次交换不划算
        else:
            k *= 1.4
        missed = len(_attacked_cells(me))
        if missed >= 20:       # 残局：已知格够多，情报卡价值下降
            k *= 0.6

    return k


def choose_card(room, ai_id, playable, rng=None):
    """从**可打的手牌下标**里挑一张，返回下标；都不值得打则 None。

    `playable` 由调用方算好（= `can_play_magic_card` 通过的那些下标）——
    本模块不许 import server，所以「能不能打」由调用方判定，这里只判「值不值得打」。

    ⚠️ 这是「分析局势选牌」的核心，现状是「从 9 张安全卡里挑速阶最低的那张」，
       完全不看局势。这里改成：基础价值 × 局势乘子，取最高分且**严格高于阈值**。
       宁可不出手，也不白烧一张（白烧会被 `_refund_card_to_hand` 退回来，
       等于白白浪费一次出牌时机）。
    """
    try:
        me = (getattr(room, 'players', None) or {}).get(ai_id)
        if me is None:
            return None
        hand = list(getattr(me, 'magic_hand', None) or [])
        best_i, best_v = None, 0.0
        for i in (playable or []):
            if not isinstance(i, int) or i < 0 or i >= len(hand):
                continue
            name = getattr(hand[i], 'name', None)
            v = card_value(name) * _situational(room, ai_id, name)
            if v > best_v:
                best_i, best_v = i, v
        if best_i is None or best_v < PLAY_THRESHOLD:
            return None
        return best_i
    except Exception:
        return None


# ===========================================================================
# 目标选择（区域 / 行列 / 连续格）
# ===========================================================================

# 各卡需要哪种目标形状。现状这些卡对 AI 一律**打不出去**（缺 target_data
# 就被判 success=False 退回），所以这张表就是「T2 档能不能开」的开关。
#
# ⚠️ 这三张是**集合**（成员判断/并集用），边长另外放在 `AREA_SIZE`。
#    第一版把边长直接写进 AREA_CARDS（dict）→ server 里 `AREA_CARDS | LINE_CARDS`
#    变成 `dict | set` → TypeError → 被 readiness 的兜底 except 吞掉 →
#    **大师一张牌都不出，而"被拒动作 0、卡死 0"看起来一切正常**。
#    "两张含义不同的表共用一个名字"就是这么长出来的：集合就是集合，
#    尺寸就是尺寸，分开写。
AREA_CARDS = {'神威！', '冻结', '探测雷达'}
LINE_CARDS = {'轰炸'}                          # 整行/整列
CELLS_CARDS = {'硫磺火焰'}                     # 连续 6 格

# 区域卡的边长 —— **按各卡自己的实现**，不是一律 3×3。实测：
#   · 神威！/ 冻结 → 3×3（`area['x1']..area['x2']` 是闭区间）
#   · 探测雷达     → **2×2**（卡面与 `apply_magic_effect` 注释都写 2*2）
# 写错边长的后果不是报错，而是**选区比卡面大一圈**：多圈的格子白送信息（甚至白送伤害）。
AREA_SIZE = {'神威！': 3, '冻结': 3, '探测雷达': 2}
DEFAULT_AREA_SIZE = 3


def _my_ship_cells(room, ai_id):
    """自己所有船占的格（自己的船对自己是可见的，不算作弊）。"""
    me = (getattr(room, 'players', None) or {}).get(ai_id)
    out = set()
    for sh in (getattr(me, 'ships', None) or []):
        out |= _cells_of(sh)
    return out


def _score_cells(room, ai_id, cells, self_harm=False):
    """一组格子对 AI 的价值。逐格按 `attack_priority` 累加，再叠加自己的船。

    逐格口径（与 `choose_attack` **同一套模型**，避免"开炮很聪明、选区域却很蠢"）：
      · 已探明敌船     +3     打中就是实打实一艘（神威！还额外触发"区域内恰好1艘→直接击沉"）
      · 未知格         +1     还可能藏着船（信息 + 命中期望）
      · 打过而没中的格  0     单格船打中即沉 → 这格**证明是空的**，再打纯属浪费
      · 自己的船       -20/格 对会打到自己人的卡（神威！打己方棋盘）是实打实的代价
    """
    me = (getattr(room, 'players', None) or {}).get(ai_id)
    if me is None:
        return -1.0
    known, safe, _unknown = enemy_cell_model(room, ai_id)
    mine = _my_ship_cells(room, ai_id)
    s = 0.0
    for c in cells:
        c = _cell_of(c) if not isinstance(c, tuple) else c
        if c is None:
            continue
        if c in known:
            s += 3.0
        elif c not in safe:
            s += 1.0
        if c in mine:
            s += -20.0 if self_harm else -1.0
    return s


def _area_cells(x, y, size=3):
    """以 (x,y) 为左上角的 size×size 区域（越界自动裁掉）。"""
    return [(a, b) for a in range(x, x + size) for b in range(y, y + size)
            if 0 <= a < BOARD_SIZE and 0 <= b < BOARD_SIZE]


def _window_positions(size):
    """所有 size×size 窗口的左上角（正方形，所以起点上限是 `BOARD_SIZE - size`）。"""
    n = BOARD_SIZE - size
    return [(x, y) for x in range(n + 1) for y in range(n + 1)]


def resolve_target(room, ai_id, card, rng=None):
    """替 AI 选目标，返回可直接交给 `handle_use_magic_card` 的 `targets` dict。

    认不出的卡返回 `None` —— 调用方据此**不要打这张牌**
    （继续打只会被判失败并退牌，白费一次出牌时机）。
    """
    try:
        name = str(getattr(card, 'name', card) or '')
        # 神威！ 的目标是【别人棋盘】——`apply_magic_effect` 里 `board` 缺省就是
        # 'opponent'，所以这里按对方棋盘算，区域里的**自己船**才是代价。
        self_harm = name == '神威！'

        if name in AREA_CARDS:
            size = int(AREA_SIZE.get(name, DEFAULT_AREA_SIZE))
            best, best_s = None, None
            for x, y in _window_positions(size):
                cells = _area_cells(x, y, size)
                s = _score_cells(room, ai_id, cells, self_harm=self_harm)
                if best_s is None or s > best_s:
                    best, best_s = (x, y), s
            if best is None:
                return None
            x, y = best
            # ⚠️ `board` 必须显式带上：apply_magic_effect 读 `target_data.get('board')`，
            #    缺省是 'opponent'；显式给出才能让"打哪块棋盘"这件事在日志里看得出来。
            return {'target_area': {'x1': x, 'y1': y, 'x2': x + size - 1,
                                    'y2': y + size - 1},
                    'board': 'self' if self_harm else 'opponent'}

        if name in LINE_CARDS:
            best, best_s = None, None
            for i in range(BOARD_SIZE):
                for kind, cells in (('row', [(x, i) for x in range(BOARD_SIZE)]),
                                    ('col', [(i, y) for y in range(BOARD_SIZE)])):
                    s = _score_cells(room, ai_id, cells)
                    if best_s is None or s > best_s:
                        best, best_s = (kind, i), s
            if best is None:
                return None
            kind, i = best
            return {'target_line': {'type': kind, 'index': i}}

        if name in CELLS_CARDS:
            n = 6                              # 硫磺火焰：自由连选 6 格
            best, best_s = None, None
            for y in range(BOARD_SIZE):        # 横向滑动窗口
                for x in range(0, BOARD_SIZE - n + 1):
                    cells = [(x + k, y) for k in range(n)]
                    s = _score_cells(room, ai_id, cells)
                    if best_s is None or s > best_s:
                        best, best_s = cells, s
            for x in range(BOARD_SIZE):        # 纵向
                for y in range(0, BOARD_SIZE - n + 1):
                    cells = [(x, y + k) for k in range(n)]
                    s = _score_cells(room, ai_id, cells)
                    if best_s is None or s > best_s:
                        best, best_s = cells, s
            if best is None:
                return None
            return {'target_cells': [{'x': a, 'y': b} for a, b in best]}

        return None
    except Exception:
        return None


# ===========================================================================
# 挑牌（弃牌堆 / 牌堆 / 对方手牌 / 数值）
# ===========================================================================

def resolve_choice(room, ai_id, kind, options, rng=None):
    """替 AI 在各种「挑一张」的等待里做选择。

    `options` 由调用方按卡面规则算好（候选卡对象列表，或数值列表）。
    一律挑**价值最高**的那个；价值相同的按下标最小（保证可复现）。
    """
    try:
        opts = list(options or [])
        if not opts:
            return None

        # 灵气复苏：选一个船数。自己船多就保持自己船数；落后则取「对方船数 − 1」，
        # 但必须落在候选集里（卡面限制 x 不得大于双方最大船数）。
        if kind == 'lingqi_choice':
            nums = [int(o) for o in opts if str(o).lstrip('-').isdigit()]
            if not nums:
                return opts[0]
            me = (getattr(room, 'players', None) or {}).get(ai_id)
            mine = int(getattr(me, 'remaining_ships', 0) or 0)
            opp_id = _opponent_id(room, ai_id)
            opp = (getattr(room, 'players', None) or {}).get(opp_id) if opp_id else None
            theirs = int(getattr(opp, 'remaining_ships', 0) or 0) if opp else 0
            want = mine if mine >= theirs else max(1, theirs - 1)
            return min(nums, key=lambda n: (abs(n - want), n))

        # 神机妙算：宣言「我这一大回合会减少几艘船」。预言命中 → 那些船不减少。
        # 已知信息：我这几艘船、对方**还剩几次攻击**（攻击次数是公开的）。
        # 直觉上应当宣言"最可能被打掉的艘数"；但没有对方船位信息时，
        # 期望命中的艘数并不由我决定，所以这里取一个**保守但非零**的值：
        #   · 对方还有多少攻击次数 → 最多可能被打掉这么多；
        #   · 但不能超过我自己的船数。
        # ⚠️ 这是一个**启发式**，不是最优解。它被 `tools/master_ablation.py`
        #    的实测数字检验：改坏它胜率会掉，改好会涨。
        if kind == 'shenji_predict':
            nums = [int(o) for o in opts if str(o).lstrip('-').isdigit()]
            if not nums:
                return opts[0]
            me = (getattr(room, 'players', None) or {}).get(ai_id)
            mine = int(getattr(me, 'remaining_ships', 0) or 0)
            incoming = int(getattr(room, 'attacks_remaining', 0) or 0)
            want = min(mine, max(0, incoming))
            return min(nums, key=lambda n: (abs(n - want), n))

        # 其余都是「挑一张牌」：取价值最高
        def val(o):
            return card_value(getattr(o, 'name', o))

        best = max(range(len(opts)), key=lambda i: (val(opts[i]), -i))
        return opts[best]
    except Exception:
        return None
