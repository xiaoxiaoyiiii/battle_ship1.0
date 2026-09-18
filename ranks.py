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

def _safe_int(value, default=0):
    """宽容整数转换：None / '' / 脏字符串一律回 `default`，**绝不抛**。

    加减分的因子全是"外部事实"（时长、回合数、沉船数、段位下标…），多因子批把它们
    接到了一起 —— 任何一个脏值抛出去，`_settle_ranked_match` 外面的 `try/except`
    会把**整段结算**吞掉（分一分不加、一条事件不发、页面上毫无提示）。
    所以这一层统一兜住：拿不到就按 0（= 这个因子不给加成）算。
    """
    try:
        return int(value)
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

# ---------------------------------------------------------------------------
# 每局加减分：多因子（2026-09-18 作者要求「变得和经验一样」）
#
# 结构**逐条对齐 `leveling.py`**：`base` + 一串 `bonuses`（明细），
# `points_breakdown()` 里有一条 `assert base + sum(bonuses) == total` ——
# 明细与总数永远对得上，明细**替总数说话**，所以任何一个因子都不许
# "偷偷把 bonus 改小来迁就上限"（那样明细就在撒谎）。规则表见
# `docs/RANKED_2026_09_17.md` §2.5（冻结设计），实现只此一份。
#
# ⚠️ 下面这些就是"哪些因素影响这一局"的全部数字。**改这里就能改平衡**。
# ---------------------------------------------------------------------------
POINTS_WIN_STREAK_STEP = 2      # 连胜：每多一连胜 +2
POINTS_WIN_STREAK_CAP = 10      # 连胜加成封顶（= 5 连胜起不再涨）
POINTS_STREAK_BREAK_SHORT = 8   # 终结 2~3 连败
POINTS_STREAK_BREAK_LONG = 12   # 终结 ≥4 连败
POINTS_STREAK_BREAK_MIN = 2     # 连败至少这么多场才叫"终止连败"
POINTS_STREAK_BREAK_LONG_MIN = 4
POINTS_BLITZ = 6                # 闪电战（快局）
POINTS_BLITZ_SECONDS = 180      # ≤180 秒
POINTS_BLITZ_ROUNDS = 5         # 或 ≤5 个大回合
POINTS_FLAWLESS = 8             # 零伤获胜（自己一艘没沉）
POINTS_PER_SINK = 1             # 击沉：每艘 +1
POINTS_SINK_CAP = 6             # 击沉加成封顶
POINTS_UPSET_SMALL_TIERS = 1    # 越级挑战：对手段位高 1 段就给
POINTS_UPSET_SMALL = 6          # 高 1~2 段
POINTS_UPSET_TIERS = 3          # 高 ≥3 段
POINTS_UPSET = 10               # 高 ≥3 段的值

POINTS_BRAVE = 5                # 虽败犹荣（击沉 ≥5 艘）
POINTS_BRAVE_SINKS = 5
POINTS_UNDERDOG = 5             # 输给高段位（对手高 ≥2 段）
POINTS_UNDERDOG_TIERS = 2
POINTS_PITY_SHORT = 4           # 连败保护：本局是第 3~4 连败
POINTS_PITY_LONG = 7            # 本局是第 ≥5 连败
POINTS_PITY_MIN = 3
POINTS_PITY_LONG_MIN = 5
POINTS_FAST_LOSS = 3            # 速败减免（≤180 秒落败不重罚）
# ⚠️ **败局下限必须由一行显式的 `cap` 补平**，不许把上面某个 bonus 改小：
#    减免项最多 +20（brave 5 + underdog 5 + pity 7 + fast_loss 3），而 base 只有 −15
#    → 不封的话"打得好的一局败仗"会变成**加分**（输一局反而涨分）。
POINTS_LOSS_FLOOR = -5          # 败局最终 delta 不低于它

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
          普通：`水手长Ⅱ 90分`（**本小段位内已攒的分**）
          船长：`船长Ⅲ 1000分 #60`（同样是本小段位进度分 + 全服排名）
          大舰长：`大舰长 #20`（不带分）

      ⚠️ **船长段显示的也是"本小段位进度分"，不是累计分**（2026-09-18 作者裁决）：
      「船长Ⅲ 1000分」= 进船长Ⅲ 之后又攒了 1000 分（累计 3300）。累计分在 `points`。
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
    # ⚠️ **文案口径统一 = 一律显示「本小段位内已攒的分」**（2026-09-18 作者裁决）。
    # 第一版给船长段显示的是**累计分**（`船长Ⅲ 2350分 #60`），结果作者说
    # 「船长Ⅲ1200分#60」「把我的账号变成船长Ⅲ1000分」时两者对不上 ——
    # 因为 1200 / 1000 都小于船长Ⅲ 的起点 2300，"船长Ⅲ + 四位数"在那个口径下
    # 根本不成立。现在的口径与低段位一致（水手长Ⅱ 90分 就是本小段位 90 分），
    # 「船长Ⅲ 1000分」= 进船长Ⅲ 后又攒了 1000 分（累计 3300）。
    # 累计分仍然通过 `points` 字段下发（段位榜显示的就是它）。
    # ⚠️ **全服排名只挂在船长及以上**（作者："船长和大舰长要能显示全服排名"）。
    # 低段位即使拿得到 `server_rank` 也不显示 —— 否则「水手长Ⅱ 90分 #60」会
    # 让每个人一注册就知道自己是全服第几名，那不是这段位设计想要的东西。
    show_rank = (idx >= MAX_POINTS_TIER_INDEX)
    suffix = (' #' + str(server_rank)) if (show_rank and server_rank) else ''
    if saturated:
        # 船长Ⅲ：后面没有小级了，继续累加即可
        to_next = None
        label = f'{tier["name"]}{sub} {prog}分' + suffix
    else:
        to_next = SUB_POINTS - prog
        label = f'{tier["name"]}{sub} {prog}分' + suffix
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


# ---------------------------------------------------------------------------
# 每局加减分：多因子
#
# ⚠️ **闭包/推导式里的循环变量一律绑默认参数**（`profile_spec._rank_rules` 里那份
#    正确写法同源）：晚绑定会让所有行都拿到**最后一个**阈值，
#    表现为"2 连败和 4 连败给的分一样"，而且不报错。
# ---------------------------------------------------------------------------
def _streak_bonus(prior, rows):
    """按**赛前**的连败数取 (值, 说明)；不匹配返回 (0, '')。

    `rows` 是 `(阈值, 值, 说明)` 的**降序**表，取第一个"够得着"的档。
    """
    n = max(0, _safe_int(prior))
    for threshold, amount, note in (rows or ()):
        if n >= threshold:
            return amount, note
    return 0, ''


def _sink_bonus(sunk, cap):
    """击沉明细：`(条数, 值)` —— 封顶后仍按**真实击沉数**进明细（别改小它是撒谎）。"""
    n = max(0, _safe_int(sunk))
    if n <= 0:
        return 0, 0
    return n, min(cap, n * POINTS_PER_SINK)


def _upset_bonus(my_tier, opp_tier):
    """越级挑战：对手段位比我高几段。返回 `(值, 说明)`，不高就 `(0, '')`。"""
    diff = _safe_int(opp_tier) - _safe_int(my_tier)
    if diff >= POINTS_UPSET_TIERS:
        return POINTS_UPSET, f'越级挑战（对手段位高 {diff} 段）'
    if diff >= POINTS_UPSET_SMALL_TIERS:
        return POINTS_UPSET_SMALL, f'越级挑战（对手段位高 {diff} 段）'
    return 0, ''


# 两张表的**机器可读版本**（帮助页与结算面板都吃它）。`scoring_table()` 由它渲染，
# 数字不在这里写第二遍 —— 否则"帮助里写 +20、代码里是 +25"这种漂移迟早出现。
_WIN_ROWS = (
    {'key': 'base', 'label': '胜利', 'value': WIN_POINTS, 'condition': '恒定'},
    {'key': 'win_streak', 'label': '连胜加成',
     'value': f'+{POINTS_WIN_STREAK_STEP} × N（封顶 +{POINTS_WIN_STREAK_CAP}）',
     'condition': f'N = 本局是第几连胜（含本局），N ≥ 2 才给'},
    {'key': 'streak_break', 'label': '终止连败',
     'value': f'+{POINTS_STREAK_BREAK_SHORT} / +{POINTS_STREAK_BREAK_LONG}',
     'condition': f'终结 {POINTS_STREAK_BREAK_MIN}~{POINTS_STREAK_BREAK_LONG_MIN - 1} 连败 / '
                  f'终结 ≥{POINTS_STREAK_BREAK_LONG_MIN} 连败'},
    {'key': 'blitz', 'label': '闪电战', 'value': f'+{POINTS_BLITZ}',
     'condition': f'≤{POINTS_BLITZ_SECONDS} 秒 或 ≤{POINTS_BLITZ_ROUNDS} 个大回合'},
    {'key': 'flawless', 'label': '零伤获胜', 'value': f'+{POINTS_FLAWLESS}',
     'condition': '自己一艘船都没沉'},
    {'key': 'sinks', 'label': '击沉战舰',
     'value': f'+{POINTS_PER_SINK} × 击沉数（封顶 +{POINTS_SINK_CAP}）',
     'condition': '每击沉一艘 +1'},
    {'key': 'upset', 'label': '越级挑战',
     'value': f'+{POINTS_UPSET_SMALL} / +{POINTS_UPSET}',
     'condition': f'对手段位高 {POINTS_UPSET_SMALL_TIERS}~{POINTS_UPSET_TIERS - 1} 段 / '
                  f'高 ≥{POINTS_UPSET_TIERS} 段'},
)

_LOSE_ROWS = (
    {'key': 'base', 'label': '失败', 'value': LOSE_POINTS, 'condition': '恒定'},
    {'key': 'brave', 'label': '虽败犹荣', 'value': f'+{POINTS_BRAVE}',
     'condition': f'本局击沉 ≥{POINTS_BRAVE_SINKS} 艘'},
    {'key': 'underdog', 'label': '输给高段位', 'value': f'+{POINTS_UNDERDOG}',
     'condition': f'对手段位高 ≥{POINTS_UNDERDOG_TIERS} 段'},
    {'key': 'pity', 'label': '连败保护',
     'value': f'+{POINTS_PITY_SHORT} / +{POINTS_PITY_LONG}',
     'condition': f'本局是第 {POINTS_PITY_MIN}~{POINTS_PITY_LONG_MIN - 1} 连败 / '
                  f'第 ≥{POINTS_PITY_LONG_MIN} 连败'},
    {'key': 'fast_loss', 'label': '速败减免', 'value': f'+{POINTS_FAST_LOSS}',
     'condition': f'≤{POINTS_BLITZ_SECONDS} 秒落败'},
    {'key': 'cap', 'label': '减免上限', 'value': '负值补平',
     'condition': f'败局最终 delta 不低于 {POINTS_LOSS_FLOOR}'},
)


def scoring_table():
    """上面两张表的机器可读版本（**帮助页与结算面板只从这份渲染**）。

    `win` / `lose` 两条各是一串 `{'key','label','value','condition'}`；
    值有档位的（连胜 / 终止连败 / 越级 / 连败保护）写成 `'+8 / +12'` 这种文案，
    档位阈值同时给在 `condition` 里 —— 前端不需要（也不许）自己写死任何一个数字。
    """
    return {
        'win': [dict(row) for row in _WIN_ROWS],
        'lose': [dict(row) for row in _LOSE_ROWS],
        'loss_floor': POINTS_LOSS_FLOOR,
        'blitz_seconds': POINTS_BLITZ_SECONDS,
        'blitz_rounds': POINTS_BLITZ_ROUNDS,
        'win_streak_cap': POINTS_WIN_STREAK_CAP,
        'sink_cap': POINTS_SINK_CAP,
        'upset_tiers': POINTS_UPSET_TIERS,
        'brave_sinks': POINTS_BRAVE_SINKS,
        'underdog_tiers': POINTS_UNDERDOG_TIERS,
        'win_streak_step': POINTS_WIN_STREAK_STEP,
        'streak_break_min': POINTS_STREAK_BREAK_MIN,
        'streak_break_long_min': POINTS_STREAK_BREAK_LONG_MIN,
        'pity_min': POINTS_PITY_MIN,
        'pity_long_min': POINTS_PITY_LONG_MIN,
        'base_win': WIN_POINTS,
        'base_lose': LOSE_POINTS,
    }


def match_points(win, *, win_streak=0, lose_streak=0, loss_streak_broken=0,
                 seconds=0, rounds=0, sunk=0, lost=0,
                 my_tier=0, opp_tier=0) -> int:
    """本局能加/扣多少分（**含败局下限 `POINTS_LOSS_FLOOR`**，但**不含 0 分封底**）。

    0 分封底在更外层（`apply_delta` / `db.add_rank_points` 的 `MAX(0, ...)`）——
    这里只管"这一局本来该多少分"。明细见 `points_breakdown`（同一个总数，别各算一份）。

    参数语义（**照契约来，别自作主张**）：
      · `win_streak` = 本局是第几连胜（**含本局**，首胜 = 1）；
      · `lose_streak` = 本局是第几连败（含本局）；
      · `loss_streak_broken` = 本局胜利所**终结**的连败数（没有则 0）；
      · `seconds` / `rounds` = 本局用时与大回合数（闪电战判据：**任一**达标即可；
        **0 = 没有可信数据**，不算闪电战）；
      · `sunk` = 本局击沉对手几艘；`lost` = 自己沉了几艘；
      · `my_tier` / `opp_tier` = 双方段位下标（`points_tier_index`，结算**前**取）。

    ⚠️ **"零伤获胜"是肯定式结论**：要 `sunk > 0`（真的打沉过对方）**且** `lost <= 0`。
      `sunk=0` 的含义是"对手一艘没沉"（那本来就没打赢的痕迹）—— 真链路里对手的船被
      魔法移走时 `_dead_ship_count` 同样是 0。所以**不带战况只写 `match_points(True)`
      拿到的就是基础分**（没有 +8），这是有意的：少给一个加成，好过多编一个。

    ⚠️ 这几个参数**必须由调用方在写库之前取好**（连胜/连败一写库就变成"含本局"的值，
    见 `server._finalize_match` 开头那段）—— 传进来的值一律按"赛前事实"使用。
    """
    base, bonuses, total = points_breakdown(
        win, win_streak=win_streak, lose_streak=lose_streak,
        loss_streak_broken=loss_streak_broken, seconds=seconds, rounds=rounds,
        sunk=sunk, lost=lost, my_tier=my_tier, opp_tier=opp_tier)
    return int(total)


def points_breakdown(win, *, win_streak=0, lose_streak=0, loss_streak_broken=0,
                     seconds=0, rounds=0, sunk=0, lost=0,
                     my_tier=0, opp_tier=0):
    """`(base, bonuses, total)`：明细逐条列出来再求和，保证"明细加起来 == 总数"。

    `bonuses` 每项 `{'key','label','value'}`，`label` 是**给玩家看的中文**（服务端给，
    前端只管显示）。`match_points` 直接吃这里的 `total` —— 两者永远是同一个数。

    ⚠️ **`base` 不进 `bonuses`**：它是"这一局是赢/输"的底子，不是加成项 ——
    明细里的每一行都是**额外**加减的东西。所以"干净的一局"（没有任何因子达标）
    `bonuses` 就是**空列表**、`total == base`（赢 +20 / 输 −15），
    而 `base + sum(bonuses) == total` 永远成立。（第一版把 `base` 也塞进明细、
    同时又拿它当起点，等于**把基础分算了两遍**：赢一局凭空变 +40。
    这种错不报错，只是分全错 —— 靠 `test_bare_call_is_just_the_base` 钉住。）

    ⚠️ **败局的 `cap` 那一行不能省**：减免项（虽败犹荣 / 输给高段位 / 连败保护 /
    速败减免）最多能加 +20，而 base 只有 −15 → 不封的话"输一局反而加分"。
    所以：只有把总分**顶到下限之上**（含顶成正数）时才补一行 `cap` 把它压回
    `POINTS_LOSS_FLOOR`(−5)；**普通败局（本来就低于下限）不加任何行**。
    **不许偷偷把某个 bonus 改小**来凑数（那样 `base + sum(bonuses) == total`
    仍然"成立"，但明细在撒谎）。
    """
    out = []

    def _add(key, label, amount):
        # ⚠️ 参数名不叫 `value`：调用方里 `value` 正被当循环变量用（读起来会串）
        out.append({'key': key, 'label': label, 'value': int(amount)})

    if win:
        base = int(WIN_POINTS)
        streak = _safe_int(win_streak)
        if streak >= 2:
            _add('win_streak', f'{streak} 连胜',
                 min(POINTS_WIN_STREAK_CAP, POINTS_WIN_STREAK_STEP * streak))
        amount, note = _streak_bonus(loss_streak_broken, (
            (POINTS_STREAK_BREAK_LONG_MIN, POINTS_STREAK_BREAK_LONG, '终结长连败'),
            (POINTS_STREAK_BREAK_MIN, POINTS_STREAK_BREAK_SHORT, '终结连败'),
        ))
        if amount:
            _add('streak_break', note, amount)
        sec, rnd = _safe_int(seconds), _safe_int(rounds)
        # ⚠️ 用时/回合数为 0 表示"没有可信数据"（不是 0 秒获胜），不许当成闪电战
        if (sec > 0 and sec <= POINTS_BLITZ_SECONDS) \
                or (rnd > 0 and rnd <= POINTS_BLITZ_ROUNDS):
            _add('blitz', '闪电战', POINTS_BLITZ)
        # ⚠️ 零伤是**肯定式**结论：要"真的击沉过对方"（sunk > 0）且"自己一艘没沉"
        #    才给。两边都是 0（对手一艘没沉、自己也没沉）属于"根本没打到对方"——
        #    改造前那种局也没有任何加成，别凭空多给 +8。
        #    （真链路上会走到：对方船全被魔法移走时 `_dead_ship_count` 也是 0。）
        if _safe_int(sunk) > 0 and _safe_int(lost) <= 0:
            _add('flawless', '零伤获胜', POINTS_FLAWLESS)
        count, amount = _sink_bonus(sunk, POINTS_SINK_CAP)
        if amount:
            _add('sinks', f'击沉 {count} 艘', amount)
        amount, note = _upset_bonus(my_tier, opp_tier)
        if amount:
            _add('upset', note, amount)
    else:
        base = int(LOSE_POINTS)
        if max(0, _safe_int(sunk)) >= POINTS_BRAVE_SINKS:
            _add('brave', '虽败犹荣', POINTS_BRAVE)
        if _safe_int(opp_tier) - _safe_int(my_tier) >= POINTS_UNDERDOG_TIERS:
            _add('underdog', '输给高段位', POINTS_UNDERDOG)
        amount, note = _streak_bonus(lose_streak, (
            (POINTS_PITY_LONG_MIN, POINTS_PITY_LONG, '连败保护（长连败）'),
            (POINTS_PITY_MIN, POINTS_PITY_SHORT, '连败保护'),
        ))
        if amount:
            _add('pity', note, amount)
        sec = _safe_int(seconds)
        if sec > 0 and sec <= POINTS_BLITZ_SECONDS:
            _add('fast_loss', '速败减免', POINTS_FAST_LOSS)

    total = base + sum(row['value'] for row in out)
    # 败局的**减免项**（虽败犹荣 / 输给高段位 / 连败保护 / 速败减免）最多能加 +20，
    # 而 base 只有 −15 → 不封的话"打得好的一局败仗"会被顶到 −5 以上、甚至变成正数
    # （输一局反而涨分）。所以：只要算出来的败局总分**高于下限**，就用一行显式的
    # 负值把它压回下限。
    # ⚠️ 方向别写反：这里是"**高于**下限才压"（`total > POINTS_LOSS_FLOOR`）。
    #    写成 `total < POINTS_LOSS_FLOOR` 会把**普通败局**（本来就在下限之下）也
    #    当成越界，于是每一局败仗都白拿 +10（−15 变 −5）—— 实测踩过：判据反过来写，
    #    分全错、断言却"通过"了，因为补的那一行恰好把总数抬到了它自己声明的目标上。
    # ⚠️ 这一行也**不许**改成把某个 bonus 改小：那样 `base + sum(bonuses) == total`
    #    仍然"成立"，但每一行都是假的（明细在撒谎）。
    if not win and total > POINTS_LOSS_FLOOR:
        _add('cap', '减免上限', POINTS_LOSS_FLOOR - total)
        total = POINTS_LOSS_FLOOR
    assert base + sum(row['value'] for row in out) == total, '明细之和必须等于总数'
    return int(base), out, int(total)


# ---- 进度条动画路径（与 `leveling.segments` 同形）----
def _sub_floor(index):
    """进入小级 `index` 的**起始分**（0 → 0，1 → 100 … 与 `progress` 同一口径）。"""
    i = max(0, int(index))
    tier = points_tier_index(i * SUB_POINTS)   # 用同一个函数反推，别自己再算一遍段位
    return tier * len(SUBS) * SUB_POINTS + (i - tier * len(SUBS)) * SUB_POINTS


def _sub_index_of(points):
    """`points` 落在第几个小级里（**跨段位连续编号**，与 `_sub_floor` 严格互逆）。"""
    p = normalize_points(points)
    return points_tier_index(p) * len(SUBS) + sub_index(p)


def _segment_of(low, high, sub_up):
    """一个点区间的段（`low`/`high` 都是**绝对分**；同一小级内，或 `sub_up` 时正好走满）。"""
    floor = _sub_floor(_sub_index_of(low))
    need = max(1, SUB_POINTS)
    inside = max(0, min(need, high - floor))
    return {
        'from': int(max(0, low - floor)),
        'to': int(inside),
        'need': int(need),
        'ratio_from': round(max(0.0, min(1.0, (low - floor) / need)), 4),
        'ratio_to': round(inside / need, 4),
        'sub_up': bool(sub_up),
        'tier_id': tier_of_index(points_tier_index(low))['id'],
        'sub': SUBS[sub_index(low)],
    }


def _segment_of_saturated(low, high):
    """饱和段位（船长Ⅲ 及以上）用的一段：条子**单调累加**，不再"走满就归零"。

    ⚠️ 与普通段位的关键差别：这里**不是**小级内的进度（`progress()` 在饱和后会回绕），
    而是"进入船长Ⅲ 之后又攒了多少分"（与 `rank_view` 的 `progress` 同一口径：
    从船长Ⅲ 的起始分 2400 起算）。所以 `to` 可以超过 `need`（= 100），
    `ratio` 一律夹到 1.0（前端画的就是满格）。`sub_up` 恒 False —— 没有下一个小级可升。
    """
    anchor = _sub_floor(_sub_index_of(low))     # 饱和后在 2400 处恒定
    offset = SUB_POINTS + (low - anchor)
    to = offset + max(0, high - low)            # `to - from == high - low`，路径不丢步
    return {
        'from': int(offset),
        'to': int(to),
        'need': int(SUB_POINTS),
        'ratio_from': round(min(1.0, offset / SUB_POINTS), 4),
        'ratio_to': round(min(1.0, to / SUB_POINTS), 4),
        'sub_up': False,
        'tier_id': tier_of_index(points_tier_index(low))['id'],
        'sub': SUBS[sub_index(low)],
    }


def segments(before_points, after_points) -> list:
    """`before → after` 的**进度条动画路径**：一段一条，段内条子从 `from` 填到 `to`。

    为什么由服务端给（与 `leveling.segments` 完全相同的理由）：**这条曲线只能有一份实现**。
    前端拿到段之后只管播动画，不需要（也不允许）自己算"下一个小级要多少分"。

    每段 `{'from','to','need','ratio_from','ratio_to','sub_up','tier_id','sub'}`：
      · `from` / `to` / `need` 都是**分数**（`leveling.segments` 给的是经验）——
        前端渲染进度条只用 `ratio_from` / `ratio_to`；
      · `sub_up=True` 的那段 = "走满 → 前端在这里播【条子重置后继续涨】"；
      · 最后一段 `to` 可能小于 `need`（这一局没升满）。
    **没涨分**（`after <= before`，例如输一局扣分）→ 返回**空列表**：掉分的动画由前端按
    `demoted` / `before` / `after` 自己演，服务端不硬造一条"往回倒"的路径
    （倒着播进度条在两边都会是 bug 源）。船长Ⅲ 及以上**没有下一个小级**，
    单独走 `_segment_of_saturated`（单调累加、不归零）。
    """
    before = normalize_points(before_points)
    after = normalize_points(after_points)
    if after <= before:
        return []

    out = []
    guard = 0
    pos = before
    while pos < after and guard < 200:
        guard += 1
        floor = _sub_floor(_sub_index_of(pos))
        nxt = floor + SUB_POINTS
        if nxt <= pos:
            # ⚠️ 船长Ⅲ 及以上（`sub_index()` 在那里饱和在 Ⅲ）：`nxt` 会**不大于** pos，
            #    若照下面的分支写就会"一边 pos = nxt、一边空转"——先吐一个零长度段，
            #    然后转满 200 圈吐 200 条一模一样的段（实测踩过一次）。
            out.append(_segment_of_saturated(pos, after))
            pos = after
        elif after >= nxt:
            # 这一小级走满 → 前端在这里播"条子重置"
            out.append(_segment_of(pos, nxt, True))
            pos = nxt
        else:
            out.append(_segment_of(pos, after, False))
            pos = after
    if not out:
        # 理论到不了（before < after 时上面至少产出一段）；给一条"原地"段兜底
        out.append(_segment_of(before, after, False))
    return out


def constants():
    """段位规则的快照（接口下发，前端画进度条/写文案时不用猜）。"""
    return {'sub_points': SUB_POINTS, 'subs': list(SUBS),
            'tiers': [dict(t) for t in TIERS], 'top_points': TOP_POINTS,
            'captain_floor': CAPTAIN_FLOOR,
            'win_points': WIN_POINTS, 'lose_points': LOSE_POINTS, 'min_points': MIN_POINTS,
            # 每局加减分的多因子表（帮助页与结算面板都吃它；**别在别处再写一遍数字**）。
            # ⚠️ 上面 win_points / lose_points / captain_floor 这些键**不许删** ——
            #    接口与既有测试都在用（`'scoring'` 是**追加**，不是替换）。
            'scoring': scoring_table(),
            'admiral_rank_limit': ADMIRAL_RANK_LIMIT,
            'admiral_min_captains': ADMIRAL_MIN_CAPTAINS,
            'admiral_sticky': ADMIRAL_STICKY,
            'start_points_of_tier': {t['id']: t['index'] * len(SUBS) * SUB_POINTS for t in NORMAL_TIERS}}


def settled_at():
    return int(time.time())
