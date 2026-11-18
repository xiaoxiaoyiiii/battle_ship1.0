"""指挥官成长经验与防刷规则（纯计算，无 IO）。

规则：
- 1 级起、20 满级；每升 1 级固定 200 经验，满级总经验 3800；满级停止累计，不转给其他角色；
- 仅真人休闲、排位、神秘科技大乱斗、人机计角色经验；每日挑战、自定义房不计；
- 完赛 +20、获胜再 +10（胜局共 30），与局内是否发动技能/发动次数无关；
- 人机局跨角色共享每日账号上限 100（北京时间 0 点切日），余量不足则按剩余帽额截断；
- 反作弊被拦截局与见面第 1 回合零交火投降：胜负双方均不给（0 经验）；
- 正常中盘投降：投降方得 20 完赛经验，胜方得 30（前提未触反作弊拦截）；
- 直接退出 / 掉线超时判负：判负方 0 经验，正常胜方经反作弊通过后照常结算 30。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..tasks import periods
from .catalog import MAX_LEVEL, MAX_XP, XP_PER_LEVEL

COMPLETION_XP = 20
WIN_BONUS_XP = 10
AI_DAILY_XP_CAP = 100

ELIGIBLE_MODES = frozenset({"casual", "ranked", "mystery_tech", "ai"})
FORFEIT_EXIT_REASONS = frozenset({"opponent_disconnected", "disconnect_timeout", "ban_canceled", "ranked_ban_escape"})


def level_for_xp(xp: int) -> int:
    clean_xp = max(0, min(MAX_XP, int(xp or 0)))
    return min(MAX_LEVEL, 1 + clean_xp // XP_PER_LEVEL)


def clamp_xp(xp: int) -> int:
    return max(0, min(MAX_XP, int(xp or 0)))


def cst_day_key(now: float | None = None) -> str:
    return str(periods(now)["daily"]["start"])


def xp_progress_view(xp: int) -> dict[str, Any]:
    total = clamp_xp(xp)
    lvl = level_for_xp(total)
    if lvl >= MAX_LEVEL:
        in_level = XP_PER_LEVEL
        next_level_xp = XP_PER_LEVEL
    else:
        in_level = total % XP_PER_LEVEL
        next_level_xp = XP_PER_LEVEL
    pct = 100 if lvl >= MAX_LEVEL else round((in_level / XP_PER_LEVEL) * 100, 1)
    return {
        "xp": total,
        "level": lvl,
        "max_level": MAX_LEVEL,
        "max_xp": MAX_XP,
        "xp_per_level": XP_PER_LEVEL,
        "level_xp": in_level,
        "level_target_xp": next_level_xp,
        "xp_in_level": in_level,
        "xp_needed": next_level_xp,
        "progress_pct": pct,
        "is_max": lvl >= MAX_LEVEL,
        "is_max_level": lvl >= MAX_LEVEL,
    }


@dataclass(frozen=True)
class CommanderXpDecision:
    raw_xp: int
    granted_xp: int
    reason: str


def compute_match_commander_xp(
    *,
    mode: str | None,
    is_ai_room: bool,
    daily_challenge: bool,
    rewards_eligible: bool,
    is_winner: bool,
    game_over_reason: str | None,
    anticheat_blocked: bool,
    anticheat_rules: list[str] | tuple[str, ...] | None,
    instant_surrender: bool,
    current_commander_xp: int,
    ai_daily_used: int,
) -> CommanderXpDecision:
    """单处计算单局指挥官经验发放结果与拦截原因。"""

    if daily_challenge or mode == "custom" or mode not in ELIGIBLE_MODES:
        return CommanderXpDecision(0, 0, "mode_ineligible")
    if not rewards_eligible:
        return CommanderXpDecision(0, 0, "not_eligible")

    rule_set = set(anticheat_rules or ())
    if not is_ai_room:
        if anticheat_blocked:
            return CommanderXpDecision(0, 0, "anticheat_blocked")
        if instant_surrender or "instant_surrender" in rule_set:
            return CommanderXpDecision(0, 0, "instant_surrender")

    # 直接退出 / 断线超时 / 逃跑判负：判负方 0 经验，正常胜方通过反作弊检查后照常给 +30。
    if not is_winner and (game_over_reason or "") in FORFEIT_EXIT_REASONS:
        return CommanderXpDecision(0, 0, "disconnect_forfeit")

    raw = COMPLETION_XP + (WIN_BONUS_XP if is_winner else 0)
    capped = raw
    reason = "settled"

    if is_ai_room:
        remaining_cap = max(0, AI_DAILY_XP_CAP - max(0, int(ai_daily_used or 0)))
        if remaining_cap <= 0:
            return CommanderXpDecision(raw, 0, "ai_daily_cap_reached")
        if remaining_cap < capped:
            capped = remaining_cap
            reason = "ai_daily_cap_truncated"

    remaining_char_xp = max(0, MAX_XP - clamp_xp(current_commander_xp))
    if remaining_char_xp <= 0:
        return CommanderXpDecision(raw, 0, "max_level_reached")
    if remaining_char_xp < capped:
        capped = remaining_char_xp
        if reason == "settled":
            reason = "max_level_clamped"

    return CommanderXpDecision(raw, max(0, capped), reason)


__all__ = [
    "AI_DAILY_XP_CAP",
    "COMPLETION_XP",
    "ELIGIBLE_MODES",
    "FORFEIT_EXIT_REASONS",
    "WIN_BONUS_XP",
    "CommanderXpDecision",
    "clamp_xp",
    "compute_match_commander_xp",
    "cst_day_key",
    "level_for_xp",
    "xp_progress_view",
]
