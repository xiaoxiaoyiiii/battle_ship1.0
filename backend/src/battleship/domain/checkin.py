"""每日签到规则：沪时自然日、当月累计、里程碑与称号文案。不读写数据库。"""
from __future__ import annotations

import time
from calendar import monthrange
from datetime import date, datetime

from .tasks import BEIJING

TIMEZONE = "Asia/Shanghai"
DAILY_TIDE = 15
SOURCE_KIND = "checkin"
MILESTONES = (
    {"days": 7, "tide": 80},
    {"days": 14, "tide": 150},
    {"days": 30, "tide": 300},
)
TITLE_MILESTONE_DAYS = 30


def now_seconds(now: float | None = None) -> int:
    return int(time.time() if now is None else now)


def civil_date(now: float) -> date:
    """用与航海任务同一套北京时间，不采用客户端传来的日期。"""
    return datetime.fromtimestamp(float(now), BEIJING).date()


def title_identity(year: int, month: int) -> dict[str, str]:
    year = int(year)
    month = int(month)
    if not 1 <= month <= 12:
        raise ValueError("月份无效")
    return {
        "id": f"checkin_{year:04d}_{month:02d}",
        "name": f"潮汐签到·{year}年{month}月",
    }


def parse_title_id(reward_id: str) -> tuple[int, int] | None:
    if not isinstance(reward_id, str) or not reward_id.startswith("checkin_"):
        return None
    year_text, separator, month_text = reward_id[len("checkin_"):].partition("_")
    if separator != "_" or len(year_text) != 4 or len(month_text) != 2:
        return None
    if not year_text.isdigit() or not month_text.isdigit():
        return None
    month = int(month_text)
    if not 1 <= month <= 12:
        return None
    return int(year_text), month


def daily_source_id(day: str) -> str:
    return f"daily:{day}"


def milestone_source_id(year: int, month: int, days: int) -> str:
    return f"milestone:{int(year):04d}-{int(month):02d}:{int(days)}"


def pending_milestones(month_count: int, claimed: set[int]) -> list[dict[str, int]]:
    return [
        dict(item) for item in MILESTONES
        if month_count >= item["days"] and item["days"] not in claimed
    ]


def build_state(*, now: int, checked_days: list[int], claimed: set[int],
                balance: int, owned: bool) -> dict:
    today = civil_date(now)
    title = title_identity(today.year, today.month)
    count = len(checked_days)
    milestones = []
    for item in MILESTONES:
        row = {
            "days": item["days"],
            "tide": item["tide"],
            "reached": count >= item["days"],
            "claimed": item["days"] in claimed,
        }
        if item["days"] == TITLE_MILESTONE_DAYS:
            row["title"] = {"id": title["id"], "name": title["name"]}
        milestones.append(row)
    today_checked = today.day in checked_days
    return {
        "timezone": TIMEZONE,
        "server_time": int(now),
        "year": today.year,
        "month": today.month,
        "today": today.isoformat(),
        "today_checked": today_checked,
        "month_count": count,
        "checked_days": list(checked_days),
        "days_in_month": monthrange(today.year, today.month)[1],
        "rewards": {"daily": DAILY_TIDE, "milestones": milestones},
        "title": {"id": title["id"], "name": title["name"], "owned": bool(owned)},
        "balance": int(balance),
        "show_red_dot": not today_checked,
    }
