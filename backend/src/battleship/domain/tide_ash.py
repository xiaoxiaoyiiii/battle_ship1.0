"""潮汐徽记独立账本规则，不提供经验兑换。"""

CURRENCY = "tide_ash"
MATCH_COMPLETION_TIDE = 8
MATCH_WIN_TIDE = 4
DAILY_MATCH_CAP = 60
TASK_TIDE = {"daily": 20, "weekly": 80}
FREE_GAP_TIDE = 15
PREMIUM_GAP_TIDE = 20
DUPLICATE_TIDE = 20


def capped_grant(requested: int, granted: int, cap: int) -> int:
    """帽额耗尽仍返回零，由仓储记录幂等来源。"""
    return min(max(0, int(requested)), max(0, int(cap) - int(granted)))
