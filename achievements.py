# -*- coding: utf-8 -*-
"""成就 / 徽章的规格与解锁判定（2026-09-17 第 2 批）。

**纯函数 + 常量，无 IO**：这里不 import db / flask / server。调用方（接口层、
结算层、测试）把 stats 传进来即可。与第 1 批的 `profile_spec.py` 分工一致：
`profile_spec` 管「称号 / 标签 / 外观」，本模块管「徽章」。

契约见 `docs/BATCH_2_3_4_PLAN.md` §2.2.2（冻结）：
`BADGES` / `achievement_context(stats)` / `evaluate(stats)` / `catalog(stats, unlocked)`。

⚠️ **判据只有 `evaluate()` 一处**：接口、结算、测试全调它。
不允许在别处再写一遍 `stats['sunk_total'] >= 50` 这种比较 —— 第 1 批的
「两份实现必然漂移」就是这么来的（`_placement_error` 与 `_placement_blocked_cells`
漂移过一次，前端画出「看着能点、点了报错」的格子）。

**数据来源与「可重算」的关系**：
    users            → wins / losses / longest_streak / created_at（现成）
    user_counters    → matches_played / sunk_total / flawless_wins / fastest_win_sec（第 2 批新增，每局结算写一次）
    user_card_usage  → card_uses_total / distinct_cards（第 1 批 + 第 2 批各一个汇总）
    get_user_rank    → rank
判据从这些数字重算，所以**同一份 stats 任何时候都能算出一致的结论**；
`user_achievements` 表只存「首次解锁时间」（用于展示与排序），不是判定的依据。
"""
import time

# ---------------------------------------------------------------------------
# 12 枚徽章（计划 §2.3 的表，逐行对应）
# ---------------------------------------------------------------------------
# 字段冻结为 {id, name, desc, requirement, group}：
#   requirement —— 未解锁时给玩家看的判据文案（与 profile_spec 的池子同风格）
#   group       —— **中文显示名**（里程碑 / 连胜 / 击沉 / 完美 / 卡牌 / 榜单）。
#                  取中文而不是 slug，是为了让前端直接拿它分组显示，
#                  不必在 JS 里再维护一份「slug → 中文」的映射（那是第二份真相）。
BADGES = [
    # ---- 里程碑 ----
    {"id": "first_win", "name": "首胜", "desc": "第一场胜利，海图上从此有了你的航迹",
     "requirement": "赢下 1 场", "group": "里程碑"},
    {"id": "veteran10", "name": "十场老兵", "desc": "甲板上磨出的茧，是十场风浪给的",
     "requirement": "累计对局 10 场", "group": "里程碑"},
    # ---- 连胜 ----
    {"id": "streak5", "name": "五连胜", "desc": "连赢五场，对手开始记住你的名字",
     "requirement": "最高连胜 ≥ 5", "group": "连胜"},
    {"id": "streak10", "name": "十连胜", "desc": "十场不败，这条航迹不用解释",
     "requirement": "最高连胜 ≥ 10", "group": "连胜"},
    # ---- 击沉 ----
    {"id": "sunk50", "name": "五十沉", "desc": "五十艘沉在你的炮口下",
     "requirement": "累计击沉 ≥ 50", "group": "击沉"},
    {"id": "sunk200", "name": "两百沉", "desc": "两百年沉船，海沟都认得你",
     "requirement": "累计击沉 ≥ 200", "group": "击沉"},
    # ---- 完美 ----
    {"id": "flawless", "name": "零伤获胜", "desc": "一艘没损失，就结束了这一局",
     "requirement": "零伤赢下 1 场", "group": "完美"},
    {"id": "flawless5", "name": "完美指挥", "desc": "五次全身而退，靠的不是运气",
     "requirement": "零伤赢下 5 场", "group": "完美"},
    {"id": "speedrun", "name": "闪电战", "desc": "三分钟内解决战斗",
     "requirement": "最快获胜 ≤ 3 分钟", "group": "完美"},
    # ---- 卡牌 ----
    {"id": "cardmaster", "name": "卡牌大师", "desc": "手里有整本卡牌的账",
     "requirement": "累计出牌 ≥ 100", "group": "卡牌"},
    {"id": "allrounder", "name": "全能选手", "desc": "二十种牌路，样样都走过",
     "requirement": "用过 ≥ 20 张不同的卡", "group": "卡牌"},
    # ---- 榜单 ----
    {"id": "rank1", "name": "榜首", "desc": "第 1 名，只有一个人能站的位置",
     "requirement": "排行榜第 1 名", "group": "榜单"},
]

BADGE_TOTAL = len(BADGES)
_BY_ID = {b['id']: b for b in BADGES}

# 「零伤获胜」的最快用时门槛（秒）：3 分钟
SPEEDRUN_SECONDS = 180

# 归一化后的上下文键（调用方只需给这些键，缺的按 0 处理）
CONTEXT_KEYS = ('wins', 'losses', 'longest_streak', 'created_at',
                'matches_played', 'sunk_total', 'flawless_wins', 'fastest_win_sec',
                'card_uses_total', 'distinct_cards', 'rank')


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
def _as_int(value, default=0):
    """把 stats 里的值归一化成非负整数（脏数据 / None / 字符串一律兜住）。

    与 `profile_spec._as_int` 同一套写法：bool 先转 int（True 不该被当成 1 以外的意思），
    None 与不可解析的值给 default，负数夹到 0（负数在统计里没有意义）。
    """
    try:
        if isinstance(value, bool):
            return int(value)
        if value is None:
            return default
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def achievement_context(stats):
    """归一化 stats → 判定上下文。缺字段按 0，脏数据不许抛异常。

    对已经归一化过的上下文再跑一次是幂等的（`evaluate` 内部会调用它，
    所以 `evaluate` 既能吃原始 stats，也能吃 `achievement_context` 的结果）。
    """
    stats = stats if isinstance(stats, dict) else {}
    return {key: _as_int(stats.get(key)) for key in CONTEXT_KEYS}


# ---------------------------------------------------------------------------
# 判据（唯一的一份）
# ---------------------------------------------------------------------------
# id → 判定函数。加新徽章 = 在 BADGES 里加一条 + 在这里加一条，两处一一对应
# （测试 `test_every_badge_has_a_rule_and_vice_versa` 会钉死这个对应关系）。
_RULES = {
    'first_win': lambda c: c['wins'] >= 1,
    'veteran10': lambda c: c['matches_played'] >= 10,
    'streak5': lambda c: c['longest_streak'] >= 5,
    'streak10': lambda c: c['longest_streak'] >= 10,
    'sunk50': lambda c: c['sunk_total'] >= 50,
    'sunk200': lambda c: c['sunk_total'] >= 200,
    'flawless': lambda c: c['flawless_wins'] >= 1,
    'flawless5': lambda c: c['flawless_wins'] >= 5,
    # 0 = 还没有过胜局（或没记录到用时），不能当成「0 秒获胜」
    'speedrun': lambda c: 0 < c['fastest_win_sec'] <= SPEEDRUN_SECONDS,
    'cardmaster': lambda c: c['card_uses_total'] >= 100,
    'allrounder': lambda c: c['distinct_cards'] >= 20,
    # ⚠️ 库里只有**当前**名次（没有历史名次），所以判据是「当前第 1」。
    # 一旦某次结算时判到过第 1，user_achievements 里就留下了解锁时间，
    # 于是从玩家视角看仍然是「曾经登顶」—— 这正是本批想要的效果。
    'rank1': lambda c: c['rank'] == 1,
}


def evaluate(stats):
    """已解锁的徽章 id 集合（**唯一一份判据**）。

    返回 set[str]；stats 为空 / 脏 / None 时返回空集合，绝不抛异常
    （它会被接口层直接调用，一个 500 不该由脏数据引发）。
    """
    ctx = achievement_context(stats)
    return {bid for bid, rule in _RULES.items() if rule(ctx)}


def is_unlocked(badge_id, stats):
    """单枚徽章是否达标（同样走 `evaluate`，不另写比较）。"""
    return badge_id in evaluate(stats)


# ---------------------------------------------------------------------------
# 图鉴
# ---------------------------------------------------------------------------
def _merged_unlocked(stats, unlocked):
    """把「DB 里记着已解锁的」与「按判据现在就该解锁的」并起来。

    为什么取并集：`user_achievements` 只在**每局结算**时写（`_finalize_match`）。
    玩家跨过门槛的瞬间还没打下一局时，DB 里没有这一行 —— 这时按判据算已经解锁了，
    展示成「未解锁」会让玩家觉得「我明明达标了却不给」。
    反过来，DB 里有记录的（哪怕 stats 后来变小了）也算解锁：解锁是**只进不退**的。

    `unlocked` 允许是 {badge_id: unlocked_at} 的 dict，也允许是 set/list（只给 id）。
    """
    ids = set(evaluate(stats))
    if isinstance(unlocked, dict):
        ids |= set(unlocked.keys())
    elif unlocked:
        try:
            ids |= set(unlocked)
        except TypeError:
            # 传了奇怪的东西（数字 / 不可迭代）就当没给，不影响其余判定
            pass
    ids &= set(_BY_ID)          # 库里可能残留已下线的 badge_id，别把它带出来
    return ids


def _unlocked_at(unlocked, badge_id):
    """取首次解锁时间；只知道「解锁了」而不知道时间时给 0。"""
    if isinstance(unlocked, dict):
        value = unlocked.get(badge_id)
        if value is None:
            return 0
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
    return 0


def catalog(stats, unlocked=None):
    """徽章图鉴：**全量 12 枚**，每枚带是否解锁与解锁时间。

    返回 `[{id, name, desc, requirement, group, unlocked, unlocked_at}]`（计划 §2.2.2）。
    `unlocked=None` 表示「只有判据、不查库」（等同传空 dict），方便纯函数场景。

    「未解锁的不下发」由**接口层**决定（`/user_stats` 会按 `unlocked` 过滤）——
    过滤规则只写一次，就是这里产出的 `unlocked` 字段。
    """
    ids = _merged_unlocked(stats, unlocked)
    items = []
    for badge in BADGES:
        items.append({
            'id': badge['id'],
            'name': badge['name'],
            'desc': badge['desc'],
            'requirement': badge['requirement'],
            'group': badge['group'],
            'unlocked': badge['id'] in ids,
            'unlocked_at': _unlocked_at(unlocked, badge['id']) if badge['id'] in ids else 0,
        })
    return items


def unlocked_only(items):
    """从 `catalog()` 的结果里筛出已解锁的（别人视角用：不下发未解锁项）。"""
    return [item for item in (items or []) if item.get('unlocked')]


def count_unlocked(items=None, stats=None, unlocked=None):
    """`{unlocked, total}` —— 接口的 `badge_count`。

    可以传已经算好的 `items`（省一次判定），也可以传 stats/unlocked 现算。
    """
    if items is None:
        items = catalog(stats, unlocked)
    return {'unlocked': sum(1 for item in items if item.get('unlocked')),
            'total': BADGE_TOTAL}


def name_of(badge_id):
    """徽章 id → 名称（播报用：「解锁了新徽章：五连胜」）。未知 id 给空串。"""
    badge = _BY_ID.get(badge_id)
    return badge['name'] if badge else ''


def describe(badge_id):
    """徽章 id → 一句话说明（播报/详情用）。未知 id 给空串。"""
    badge = _BY_ID.get(badge_id)
    return badge['desc'] if badge else ''


def groups():
    """所有分组（按 BADGES 里的出现顺序去重），前端按它分组渲染。"""
    seen = []
    for badge in BADGES:
        if badge['group'] not in seen:
            seen.append(badge['group'])
    return seen


def newly_unlocked(stats, already):
    """相对 `already`（已解锁的 id 集合）新达标的徽章 id 列表（保持 BADGES 顺序）。

    结算层播报用：`_finalize_match` 里 grant 之前先算这个，好知道「这一局新解锁了哪几枚」。
    """
    known = set(already or ())
    return [b['id'] for b in BADGES if b['id'] not in known and _RULES[b['id']](achievement_context(stats))]
