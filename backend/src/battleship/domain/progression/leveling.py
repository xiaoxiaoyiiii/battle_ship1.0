# -*- coding: utf-8 -*-
"""等级与经验（2026-09-17 追加）。

**唯一的一份规则**：等级曲线、每局经验、以及"从 before 到 after 要经过哪几段"的动画路径
全部在这里算。前端**不重算**任何东西 —— 它只按服务端下发的 `segments` 播动画
（否则"曲线"就有了两份实现，迟早漂移：第 2 批已经吃过"判据两份实现"的亏）。

设计取舍（作者 2026-09-17 要求：满级 100，另有账号 101；要有可视化经验条与结算滚动升级动画）：

* **只存 xp，不存 level**。等级一律由 `level_from_xp()` 推出来 ——
  存两个字段就会出现"xp 到了但 level 没更新"这种对不上的状态。
* **曲线**：到达 L 级所需累计经验 `30*(L-1) + 5*(L-1)^2`（L=1 时为 0）。
  L=10 → 675 ｜ L=50 → 13475 ｜ L=100 → 51975 ｜ L=101 → 53030。
  取二次是为了"后面越来越慢"，取小系数是为了在一局约 25~40 经验下不至于像天文数字。
* **封顶**：普通账号 100 级；持有 `level_101` 特权的账号 101 级（`profile_spec.PERK_LEVEL_101`）。
  满级之后经验**仍然记录**（不清零、不溢出成负数），只是不再涨等级 ——
  这样以后要提高上限不用做数据迁移。
* **每局经验**：基础 10 + 胜利 15 + 每击沉 2 + 零伤获胜 10 + 三分钟内获胜 5。
  输也有基础经验（有参与就不空手），赢了明显更多。
"""
import time

# ---- 曲线 ----
MAX_LEVEL = 100           # 普通账号的满级
LEVEL_101 = 101           # 特权账号的满级（profile_spec.PERK_LEVEL_101）


def xp_for_level(level):
    """到达 `level` 级所需的**累计**经验（level ≤ 1 时为 0）。"""
    n = max(0, int(level) - 1)
    return 30 * n + 5 * n * n


def level_from_xp(xp, cap=MAX_LEVEL):
    """累计经验 → 等级（受 cap 封顶）。"""
    xp = max(0, int(xp or 0))
    cap = max(1, int(cap or MAX_LEVEL))
    level = 1
    while level < cap and xp >= xp_for_level(level + 1):
        level += 1
    return level


def level_view(xp, cap=MAX_LEVEL):
    """给接口下发的等级视图（自己看自己、别人看你、排行榜都用它，口径一致）。

    返回的 `into` / `need` / `ratio` 是**当前等级内的进度**：
    满级时 `need = 0`、`ratio = 1.0`（进度条画满，前端不需要特判除零）。
    """
    xp = max(0, int(xp or 0))
    cap = max(1, int(cap or MAX_LEVEL))
    level = level_from_xp(xp, cap)
    if level >= cap:
        return {'xp': xp, 'level': level, 'max_level': cap, 'into': 0, 'need': 0,
                'ratio': 1.0, 'capped': True,
                'next_at': None, 'level_at': xp_for_level(level)}
    base = xp_for_level(level)
    need = max(1, xp_for_level(level + 1) - base)
    into = max(0, xp - base)
    return {'xp': xp, 'level': level, 'max_level': cap, 'into': into, 'need': need,
            'ratio': round(min(1.0, into / need), 4), 'capped': False,
            'next_at': xp_for_level(level + 1), 'level_at': base}


def segments(before_xp, after_xp, cap=MAX_LEVEL):
    """`before_xp → after_xp` 的**动画路径**：一段一条，段内 bar 从 from 填到 to。

    为什么由服务端给：等级曲线只有这里一份。前端拿到段之后只管播动画，
    不需要（也不允许）自己算"下一级要多少经验"。

    每段：`{level, from, to, need, ratio_from, ratio_to, level_up}`
      · 升级的那一段 `to == need`、`level_up=True`（前端在这一段播"条子重置"的动画）；
      · 最后一段 `to` 可能小于 `need`（这一局没升满）。
    满级之后不再产生新段（`capped=True` 时给一个"经验条画满"的收尾段）。
    """
    before_xp = max(0, int(before_xp or 0))
    after_xp = max(before_xp, int(after_xp or 0))
    cap = max(1, int(cap or MAX_LEVEL))
    out = []
    lv = level_from_xp(before_xp, cap)
    xp = before_xp
    if lv >= cap:
        # 已满级：没有等级可升，给一条"满格"的收尾段，前端照样有东西可播
        return [{'level': lv, 'from': xp_for_level(cap), 'to': xp, 'need': 0,
                 'ratio_from': 1.0, 'ratio_to': 1.0, 'level_up': False}]
    guard = 0
    while xp < after_xp and guard < 200:
        guard += 1
        base = xp_for_level(lv)
        nxt = xp_for_level(lv + 1)
        need = max(1, nxt - base)
        if after_xp >= nxt and lv < cap:
            out.append({'level': lv, 'from': xp - base, 'to': need, 'need': need,
                        'ratio_from': round(min(1.0, (xp - base) / need), 4), 'ratio_to': 1.0,
                        'level_up': True})
            xp = nxt
            lv += 1
            if lv >= cap:
                break
        else:
            out.append({'level': lv, 'from': xp - base, 'to': after_xp - base,
                        'need': need,
                        'ratio_from': round(min(1.0, (xp - base) / need), 4),
                        'ratio_to': round(min(1.0, (after_xp - base) / need), 4),
                        'level_up': False})
            xp = after_xp
    if not out:
        base = xp_for_level(lv)
        need = 0 if lv >= cap else max(1, xp_for_level(lv + 1) - base)
        out.append({'level': lv, 'from': xp - base, 'to': xp - base, 'need': need,
                    'ratio_from': round(min(1.0, (xp - base) / need), 4) if need else 1.0,
                    'ratio_to': round(min(1.0, (xp - base) / need), 4) if need else 1.0,
                    'level_up': False})
    return out


# ---- 每局经验 ----
XP_BASE = 10        # 参与就有
XP_WIN = 15         # 胜利
XP_PER_SINK = 2     # 每击沉一艘
XP_FLAWLESS = 10    # 零伤获胜
XP_FAST_WIN = 5     # 三分钟内获胜


def match_xp(win, sunk=0, flawless=False, fast=False):
    """一局能拿多少经验。**服务端算**，前端只显示。

    输也有基础经验（+0 会让人觉得白打一局）；额外奖励只在**获胜**时才给，
    否则"输得漂亮"反而比"赢了"拿得多。
    """
    xp = XP_BASE
    if win:
        xp += XP_WIN
        xp += max(0, int(sunk or 0)) * XP_PER_SINK
        if flawless:
            xp += XP_FLAWLESS
        if fast:
            xp += XP_FAST_WIN
    return int(xp)


def xp_breakdown(win, sunk=0, flawless=False, fast=False):
    """经验的**明细**（结算界面可以逐条列出"哪来的经验"）。

    和 `match_xp` 同源：一条一条列出来再求和，保证"明细加起来 == 总数"。
    """
    rows = [('参与对局', XP_BASE)]
    if win:
        rows.append(('胜利', XP_WIN))
        if sunk:
            rows.append((f'击沉 {int(sunk)} 艘', max(0, int(sunk)) * XP_PER_SINK))
        if flawless:
            rows.append(('零伤获胜', XP_FLAWLESS))
        if fast:
            rows.append(('闪电战（≤3 分钟）', XP_FAST_WIN))
    total = sum(v for _, v in rows)
    assert total == match_xp(win, sunk, flawless, fast)
    return [{'label': k, 'xp': v} for k, v in rows]


def cap_for(has_level_101=False):
    """满级上限：普通 100，持特权 101。"""
    return LEVEL_101 if has_level_101 else MAX_LEVEL


def curve(max_level=MAX_LEVEL):
    """曲线快照（前端画"下一级还要多少"时用；不下发也没关系，接口已经给了 need）。"""
    return {'max_level': int(max_level), 'base_xp': XP_BASE, 'win_xp': XP_WIN,
            'per_sink_xp': XP_PER_SINK, 'flawless_xp': XP_FLAWLESS, 'fast_win_xp': XP_FAST_WIN,
            'thresholds': [{'level': lv, 'at': xp_for_level(lv)} for lv in range(1, int(max_level) + 1)]}
