# -*- coding: utf-8 -*-
"""段位系统（2026-09-17 新增）。

**唯一的一份规则**：段位表、小级进位、升降级、文案格式、大舰长晋升条件全部在这里算。
前端**不重算**任何东西 —— 它只按服务端下发的 `rank_view` / `label` 渲染
（曲线/档位有两份实现必然漂移，等级系统已经立过这条规矩）。

## 设计（作者 2026-09-17 口述 → 本文档）

* **9 个段位**：二级水手 → 一级水手 → 水手长 → 三副 → 二副 → 大副 → 轮机长 → 船长 → **大舰长**；
* 前 8 个段位**各有 Ⅰ / Ⅱ / Ⅲ 三个小级**，**每小级 100 分**（Ⅰ 最小、Ⅲ 最大）；
* 进位像十进制：`水手长Ⅱ 90分` +20 → `水手长Ⅲ 10分`；降级同理（多扣的跨到下一小级）；
* **最低 0 分**（二级水手Ⅰ 0分），不掉负分；
* **船长**另显示**全服排名**：`船长Ⅲ 2350分 #60`；
* **大舰长**不是靠分堆出来的：要**先到船长**，且**船长池内排名 ≤ 50** 才晋升，显示成 `大舰长 #20`。

## 两个"排名"是两回事（别混）

* **船长池内排名**（`captain_pool_rank`）→ 只用来判断**能不能升大舰长**；
* **全服排名**（`server_rank`）→ 只用来**显示**（船长/大舰长那个 `#N`）。
  作者原话里这两个数都出现过（"在船长段位中的排位分的排名是前五十" vs "我的排名是全服第60"），
  所以这里分开实现、分别下发。

## 只存 points

小级、大段、进度一律由 `rank_view()` 推出来。存"当前段位"这种冗余字段迟早
出现"分到了但段位没更新"的对不上状态（等级系统同一条教训）。

## 可调的三个数

`RANK_WIN_POINTS` / `RANK_LOSE_POINTS` / `RANK_ADMIRAL_MIN_CAPTAINS` 三个环境变量
可以覆盖赢分 / 输分 / 大舰长护栏（都是纯调参，默认值 = 设计稿的值）。
"""
import os
import time


def _env_int(name, default):
    """读一个整数环境变量，非法/缺失一律回默认值（绝不因为配置写错打崩进程）。"""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == '':
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default

# ---------------------------------------------------------------------------
# 段位表
# ---------------------------------------------------------------------------
SUB_POINTS = 100              # 每个小级需要的分数（作者："每个小段位提升需要100排位积分"）
SUBS = ('Ⅰ', 'Ⅱ', 'Ⅲ')        # Ⅰ 最小、Ⅲ 最大

# id 用于前端取图标（static/rank_icons.js 的键）、claim 文案与解锁规则；
# index 就是段位高低（越大越高），别改顺序。
TIERS = [
    {'id': 'sailor2', 'name': '二级水手', 'index': 0},
    {'id': 'sailor1', 'name': '一级水手', 'index': 1},
    {'id': 'bosun', 'name': '水手长', 'index': 2},
    {'id': 'mate3', 'name': '三副', 'index': 3},
    {'id': 'mate2', 'name': '二副', 'index': 4},
    {'id': 'mate1', 'name': '大副', 'index': 5},
    {'id': 'engineer', 'name': '轮机长', 'index': 6},
    {'id': 'captain', 'name': '船长', 'index': 7},
    {'id': 'admiral', 'name': '大舰长', 'index': 8},
]
NORMAL_TIERS = TIERS[:-1]      # 靠分数晋级的 8 个段位
ADMIRAL = TIERS[-1]            # 大舰长：晋升制
CAPTAIN = TIERS[7]             # 船长：升大舰长必须先在它上面
MAX_POINTS_TIER_INDEX = CAPTAIN['index']          # 分数能到的最高段位
TOP_POINTS = len(NORMAL_TIERS) * len(SUBS) * SUB_POINTS   # 船长Ⅲ 的起始分 = 2400

# 船长段的**起始分**（2100）。db 层数"全服船长段有多少人"时用它，
# 所以放在这里由 ranks 单点定义 —— 别在别处再写一遍 2100。
CAPTAIN_FLOOR = CAPTAIN['index'] * len(SUBS) * SUB_POINTS

# ---- 每局加减分（默认值；作者只给了"+20"的例子，扣分幅度是这里定的）----
# 这三个数**可以用环境变量覆盖**（见下面的 `_env_int`）—— 它们是纯调参，
# 上线后想微调不该再走一次"改代码 + 提交 + 部署"。默认值就是设计稿里的值，
# 服务器不配这几个变量时行为完全不变（测试也按默认值断言）。
WIN_POINTS = _env_int('RANK_WIN_POINTS', 20)
LOSE_POINTS = _env_int('RANK_LOSE_POINTS', -15)
MIN_POINTS = 0                 # 最低 0 分

# ---- 大舰长晋升 ----
ADMIRAL_RANK_LIMIT = 50        # 船长池内排名 ≤ 50 才晋升
# ⚠️ 船长池不足这么多人时**不产生大舰长**（否则人少时人人都是大舰长，这个段位就没意义了）。
# ⚠️ 这条护栏的副作用是：**本服现在没有任何人能达到大舰长**（全服一共十几个人）。
#    这是有意的（作者已确认），也留了环境变量 `RANK_ADMIRAL_MIN_CAPTAINS`：
#    想在小服里做一次大舰长晋升演示，把它调小（例如 2）重启即可，不必改代码。
ADMIRAL_MIN_CAPTAINS = _env_int('RANK_ADMIRAL_MIN_CAPTAINS', 50)
ADMIRAL_STICKY = False         # 默认**动态**：条件不再满足会掉回船长


def tier_of_index(index):
    """段位下标 → 段位字典（越界夹到两端，不抛）。"""
    try:
        i = int(index)
    except (TypeError, ValueError):
        i = 0
    i = max(0, min(len(TIERS) - 1, i))
    return TIERS[i]


def tier_by_id(tier_id):
    for t in TIERS:
        if t['id'] == tier_id:
            return t
    return None


def normalize_points(points):
    """分数归一化：整数、非负、下限 0。"""
    try:
        p = int(points)
    except (TypeError, ValueError):
        p = 0
    return max(MIN_POINTS, p)


def apply_delta(points, delta):
    """加/减分 → 新的总分（带 0 分封底）。

    返回 `(new_points, clamped)`：`clamped=True` 表示"本该扣到负数、被按在 0 分了"，
    结算文案可以据此说"已到最低分"。非法 delta 当 0 处理（不抛）。
    """
    before = normalize_points(points)
    try:
        d = int(delta)
    except (TypeError, ValueError):
        d = 0
    raw = before + d
    after = max(MIN_POINTS, raw)
    return after, raw < MIN_POINTS


def sub_index(points):
    """当前小级在本段位里的下标（0/1/2）。

    ⚠️ 到了"分数能到的最高段位"（船长）的第 Ⅲ 小级之后**必须饱和在 Ⅲ**，
    不能再按 `% 3` 回绕 —— 否则 2700 分会被算成船长Ⅱ、3000 分算成船长Ⅰ
    （实测过：分数越高段位反而越低，是个很荒谬的 bug）。
    船长Ⅲ 之上只累加分数、不再变段位。
    """
    p = normalize_points(points)
    raw = p // SUB_POINTS
    if raw >= len(NORMAL_TIERS) * len(SUBS):
        return len(SUBS) - 1
    return raw % len(SUBS)


def progress(points):
    """当前小级里的进度（0~99）——就是作者例子里"水手长Ⅱ 90分"的那个 90。"""
    return normalize_points(points) % SUB_POINTS


def points_tier_index(points):
    """纯按分数算的段位下标（不含大舰长）。"""
    p = normalize_points(points)
    idx = p // (SUB_POINTS * len(SUBS))
    return max(0, min(MAX_POINTS_TIER_INDEX, idx))


def rank_view(points, is_admiral=False, server_rank=None, captain_pool_rank=None):
    """段位视图（接口与前端都吃这一份）。

    返回：
      · `tier_id` / `tier_name` / `tier_index` —— 段位本体（大舰长时 index=8）；
      · `sub`（'Ⅰ'/'Ⅱ'/'Ⅲ'，大舰长为 `''`）/ `progress`（本小级进度 0~99）；
      · `points`（累计分）/ `to_next`（离下一小级还差几分）；船长Ⅲ 与 大舰长 为 `None`；
      · `label` —— **给玩家看的完整文案**，两种格式：
          普通：`水手长Ⅱ 90分`（进度）
          船长：`船长Ⅲ 2350分 #60`（累计分 + 全服排名）
          大舰长：`大舰长 #20`（不带分）
      · `server_rank` / `captain_pool_rank` 原样带回，前端不用再算。
    """
    p = normalize_points(points)
    if is_admiral:
        # ⚠️ 排名前的空格不能省：船长是「船长Ⅲ 2300分 #60」，大舰长不带分数
        # 但同样是「大舰长 #20」。第一版写成了 `大舰长#20`，两种文案不一致。
        label = ADMIRAL['name'] + ((' #' + str(server_rank)) if server_rank else '')
        # ⚠️ 键集必须与下面那条分支**完全一致**（大舰长也要有 `saturated`）：
        # 同一个"段位视图"出现两种形状，调用方就得对每个键写 `if key in view` ——
        # 前端同事实测时正是被这条绊了一下（它没有 `saturated`，只能改用
        # `to_next is None` 判"没有下一级"）。空 `sub` 是**唯一**一处有意的差异。
        return {'tier_id': ADMIRAL['id'], 'tier_name': ADMIRAL['name'],
                'tier_index': ADMIRAL['index'], 'sub': '', 'progress': 0,
                'points': p, 'to_next': None, 'sub_points': SUB_POINTS,
                'is_admiral': True, 'saturated': True, 'label': label,
                'server_rank': server_rank, 'captain_pool_rank': captain_pool_rank}

    idx = points_tier_index(p)
    tier = tier_of_index(idx)
    sub = SUBS[sub_index(p)]
    # 到了船长Ⅲ（分数能到的顶段）之后：进度用**单调累加**，不再按 %100 回绕
    # （回绕会让进度条在 2400/2800 分时突然归零，看着像掉段）。
    saturated = (idx >= MAX_POINTS_TIER_INDEX and sub == SUBS[-1])
    if saturated:
        base = MAX_POINTS_TIER_INDEX * len(SUBS) * SUB_POINTS + (len(SUBS) - 1) * SUB_POINTS
        prog = p - base
    else:
        prog = progress(p)
    if saturated:
        # 船长Ⅲ：后面没有小级了，继续累加即可
        to_next = None
        label = f'{tier["name"]}{sub} {p}分' + ((' #' + str(server_rank)) if server_rank else '')
    else:
        to_next = SUB_POINTS - prog
        if idx >= MAX_POINTS_TIER_INDEX:
            # 船长Ⅰ/Ⅱ：显示累计分 + 全服排名
            label = f'{tier["name"]}{sub} {p}分' + ((' #' + str(server_rank)) if server_rank else '')
        else:
            label = f'{tier["name"]}{sub} {prog}分'
    return {'tier_id': tier['id'], 'tier_name': tier['name'], 'tier_index': idx,
            'sub': sub, 'progress': prog, 'points': p, 'to_next': to_next,
            'sub_points': SUB_POINTS, 'is_admiral': False, 'saturated': saturated,
            'label': label, 'server_rank': server_rank, 'captain_pool_rank': captain_pool_rank}


def solve_delta(before_points, after_points):
    """结算用的"变化摘要"（前端据此播文案与动画）。

    返回 `{delta, points_before, points_after, before, after, promoted, demoted,
    tier_up, tier_down, clamped}`：`promoted/demoted` 是**小级/大段**的升降
    （大舰长由调用方另行判断，这里只管分数段位）。
    """
    b = normalize_points(before_points)
    a = normalize_points(after_points)
    vb = rank_view(b)
    va = rank_view(a)
    return {
        'delta': a - b,
        'points_before': b,
        'points_after': a,
        'before': vb,
        'after': va,
        'promoted': va['tier_index'] > vb['tier_index'] or (
            va['tier_index'] == vb['tier_index'] and SUBS.index(va['sub']) > SUBS.index(vb['sub'])),
        'demoted': va['tier_index'] < vb['tier_index'] or (
            va['tier_index'] == vb['tier_index'] and SUBS.index(va['sub']) < SUBS.index(vb['sub'])),
        'tier_up': va['tier_index'] > vb['tier_index'],
        'tier_down': va['tier_index'] < vb['tier_index'],
    }


def can_promote_to_admiral(points, captain_pool_rank, captain_pool_size):
    """能不能升大舰长。三个条件**全部**满足才行（作者："要先到船长 + 船长池内排名前五十"）：

    1. 分数已经到船长段位（`points >= 船长Ⅰ 起始分`）；
    2. 船长池内排名 ≤ `ADMIRAL_RANK_LIMIT`；
    3. 船长池人数 ≥ `ADMIRAL_MIN_CAPTAINS`（人太少时不产生大舰长，否则这个段位没意义）。

    返回 `(ok, reason)`：`reason` 是**给玩家看的中文原因**，前端/接口直接展示。
    """
    p = normalize_points(points)
    if points_tier_index(p) < MAX_POINTS_TIER_INDEX:
        return False, '需要先达到船长段位'
    if captain_pool_rank is None:
        return False, '还没有船长段位的排名数据'
    if captain_pool_size is not None and int(captain_pool_size) < ADMIRAL_MIN_CAPTAINS:
        return False, f'船长段位满 {ADMIRAL_MIN_CAPTAINS} 人后开放晋升（当前 {int(captain_pool_size)} 人）'
    if int(captain_pool_rank) > ADMIRAL_RANK_LIMIT:
        return False, f'船长段位内排名需进入前 {ADMIRAL_RANK_LIMIT}（当前第 {int(captain_pool_rank)}）'
    return True, ''


def is_admiral(row, captain_pool_rank=None, captain_pool_size=None):
    """某人当前是不是大舰长。

    `row` 是 `user_rank` 那行（含 `is_admiral` 粘性标记，若启用粘性）。
    默认**动态**：每次结算重算；`ADMIRAL_STICKY=True` 时曾晋升过就保留。
    """
    row = row or {}
    if ADMIRAL_STICKY and int(row.get('is_admiral') or 0):
        return True
    ok, _ = can_promote_to_admiral(row.get('points') or 0, captain_pool_rank, captain_pool_size)
    return ok


def win_points():
    return WIN_POINTS


def lose_points():
    return LOSE_POINTS


def constants():
    """段位规则的快照（接口下发，前端画进度条/写文案时不用猜）。"""
    return {'sub_points': SUB_POINTS, 'subs': list(SUBS),
            'tiers': [dict(t) for t in TIERS], 'top_points': TOP_POINTS,
            'captain_floor': CAPTAIN_FLOOR,
            'win_points': WIN_POINTS, 'lose_points': LOSE_POINTS, 'min_points': MIN_POINTS,
            'admiral_rank_limit': ADMIRAL_RANK_LIMIT,
            'admiral_min_captains': ADMIRAL_MIN_CAPTAINS,
            'admiral_sticky': ADMIRAL_STICKY,
            'start_points_of_tier': {t['id']: t['index'] * len(SUBS) * SUB_POINTS for t in NORMAL_TIERS}}


def settled_at():
    return int(time.time())
