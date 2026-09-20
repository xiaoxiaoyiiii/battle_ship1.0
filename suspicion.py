# -*- coding: utf-8 -*-
"""嫌疑度累计与阶梯封禁（2026-09-20）—— **纯函数 + 纯数据，不碰数据库、不发事件**。

与 `anticheat.py` / `match_guard.py` / `ranks.py` 同一套路：**规则只此一份**，
可单测、可复算、可解释。

═══════════════════════════════════════════════════════════════════════════
设计要点
═══════════════════════════════════════════════════════════════════════════
`anticheat.py` 判的是**一局**；本模块判的是**一个人长期的行为**。

为什么要分开：
  · 单局判据再准，也只能"不让这一局给分"——对付小号刷分没用（他换个小号继续）；
  · 真正能拦住的是**累计**：一个人反复出现在可疑对局里，本身就是信号；
  · 累计必须**带衰减**：三个月前的可疑局不该和昨天的等权（否则老实人一旦
    犯错就永远翻不了身，"嫌疑度"会变成不可逆的惩罚）。

三个概念，别混：
  · **单局嫌疑度**    —— `anticheat.evaluate()` 的 `score`（一局的）
  · **累计嫌疑度**    —— 本模块：把一个人参与过的所有可疑局按时间衰减加权求和
  · **封禁等级**      —— 由累计嫌疑度**算出来**的（0=正常 / 1=禁排位 / 2=禁匹配 / 3=禁房间）

⚠️ **等级一律由嫌疑度推出来，绝不单独存**。
   存两个字段迟早出现"嫌疑度降了但封禁还在"这种对不上的状态 ——
   这正是本项目"同一件事两份实现必然漂移"的老病根（见 `db.py` 里
   `user_xp` 只存 xp、等级由 `leveling.level_from_xp()` 推的同一理由）。
   唯一例外是**管理员手动解封**：那是人的决定，必须持久化，见 `override`。
"""

import math
from typing import Any

# ---------------------------------------------------------------------------
# 一、累计权重：单局嫌疑度 -> 累计贡献
# ---------------------------------------------------------------------------
# 单局嫌疑度按权重折算进累计。为什么要除：`anticheat` 的 `block` 档是 100，
# 若直接累加，两局就打满封禁 —— 太敏感，一次误判就毁掉一个正常玩家。
#
# 这里用"单局嫌疑度 / DIVISOR"，意思是**约 5 局 block 档才够禁排位**，
# 给误判留了充足的容错空间。
SCORE_DIVISOR = 5.0

# 时间衰减半衰期（天）：14 天前的可疑局，权重减半。
# 选 14 天：够长（覆盖一次刷分狂欢），够短（老实人两周内恢复清白）。
DECAY_HALF_LIFE_DAYS = 14.0

# 累计上限：防止一个人被刷到天文数字（也防止整数溢出式的荒谬展示）
MAX_ACCUMULATED = 1000.0

# 衰减下限：**不能让衰减到 0**。
#
# 为什么（实测撞出来的）：`0.5 ** (age/14)` 在 age 约 1e5 天时会**下溢成 0.0**。
# 语义上"很久以前"贡献为 0 没什么问题，但我们的约定是"衰减只趋近、不回零"
# （人不该因为太久远就完全恢复清白）。与其依赖浮点精度碰巧不为 0，
# 不如给一个明确下限 —— 这样这条性质是**设计出来的**，不是撞出来的。
DECAY_FLOOR = 1e-6


def decay_factor(age_days: float) -> float:
    """时间衰减系数：`0.5 ** (age_days / 半衰期)`，下限 `DECAY_FLOOR`。

    0 天 → 1.0；14 天 → 0.5；28 天 → 0.25；越久越接近下限（**恒 > 0**）。
    """
    try:
        age = max(0.0, float(age_days))
    except (TypeError, ValueError):
        age = 0.0
    return max(DECAY_FLOOR, 0.5 ** (age / DECAY_HALF_LIFE_DAYS))


def match_contribution(match_score, age_days=0.0) -> float:
    """一局对累计嫌疑度的贡献 = 单局嫌疑度 / 折算系数 × 时间衰减。"""
    try:
        s = float(match_score or 0)
    except (TypeError, ValueError):
        s = 0.0
    if s <= 0:
        return 0.0
    return (s / SCORE_DIVISOR) * decay_factor(age_days)


def accumulate(matches) -> float:
    """把一个人参与过的所有可疑局累计起来。

    `matches` = `[{'score': int, 'age_days': float}, ...]`（**由调用方组装**）。

    ⚠️ 本函数只做数学，不查库 —— 取证/复算/测试都用同一份实现。
    """
    total = 0.0
    for m in (matches or ()):
        try:
            total += match_contribution(m.get('score'), m.get('age_days', 0.0))
        except Exception:
            continue
    return min(total, MAX_ACCUMULATED)


# ---------------------------------------------------------------------------
# 二、阶梯封禁：等级由嫌疑度算出来
# ---------------------------------------------------------------------------
# 三档阈值。取整好记，且都明显高于"一次误判"的量级。
#
#   5 局 block(100) = 100 累计 → 正好禁排位
#   10 局 block     = 200 累计 → 禁匹配
#   15 局 block     = 300 累计 → 禁房间
LEVEL_THRESHOLDS = (
    (300.0, 3),    # 禁全部房间功能
    (200.0, 2),    # 禁匹配
    (100.0, 1),    # 禁排位
)

LEVEL_NONE = 0
LEVEL_NO_RANKED = 1
LEVEL_NO_MATCH = 2
LEVEL_NO_ROOM = 3

LEVEL_NAMES = {
    0: '正常',
    1: '禁止排位',
    2: '禁止匹配',
    3: '禁止房间',
}


def level_from_score(score) -> int:
    """累计嫌疑度 -> 封禁等级（0~3）。**唯一入口**。"""
    try:
        s = float(score or 0)
    except (TypeError, ValueError):
        s = 0.0
    for threshold, level in LEVEL_THRESHOLDS:
        if s >= threshold:
            return level
    return LEVEL_NONE


def level_name(level) -> str:
    """等级的展示文案（前端只渲染，不自己拼 —— 与 `ranks.rank_view` 同规矩）。"""
    try:
        return LEVEL_NAMES.get(int(level), '未知')
    except (TypeError, ValueError):
        return '未知'


def next_threshold(score) -> float:
    """还差多少分进入下一档（已到顶返回 0）。"""
    try:
        s = float(score or 0)
    except (TypeError, ValueError):
        s = 0.0
    for threshold, _level in reversed(LEVEL_THRESHOLDS):
        if s < threshold:
            return round(threshold - s, 1)
    return 0.0


# ---------------------------------------------------------------------------
# 三、能力判定：某等级还能不能做某事
# ---------------------------------------------------------------------------
# 三个能力，逐级收紧（等级越高，被禁的越多）。
CAP_RANKED = 'ranked'      # 打排位
CAP_MATCH = 'match'        # 发起匹配（含休闲）
CAP_ROOM = 'room'          # 建房 / 加入自定义房

_CAP_REQUIRED_MAX_LEVEL = {
    CAP_RANKED: LEVEL_NO_RANKED - 1,   # 需 level < 1 → level 必须为 0
    CAP_MATCH: LEVEL_NO_MATCH - 1,     # 需 level < 2
    CAP_ROOM: LEVEL_NO_ROOM - 1,       # 需 level < 3
}


def capability_allowed(level, cap: str) -> bool:
    """该封禁等级下，某能力是否可用。

    ⚠️ **白名单与黑名单不许有交集**（本项目第 10 条教训）：
    这里只有一份"最高允许等级"表，不做两套判断。
    """
    try:
        lv = int(level or 0)
    except (TypeError, ValueError):
        lv = 0
    limit = _CAP_REQUIRED_MAX_LEVEL.get(cap)
    if limit is None:
        return True                     # 未知能力不拦（失败开放）
    return lv <= limit


def blocked_capabilities(level) -> list:
    """该等级下被禁的能力清单（展示用）。"""
    return [c for c in (CAP_RANKED, CAP_MATCH, CAP_ROOM)
            if not capability_allowed(level, c)]


def denial_message(level, cap: str) -> str:
    """被拦时的玩家可读文案。

    ⚠️ **不解释判据细节**（不告诉对方"你哪一局被抓了"）——
    那等于教作弊者怎么规避。只说结论与申诉途径。
    """
    if capability_allowed(level, cap):
        return ''
    what = {
        CAP_RANKED: '排位赛',
        CAP_MATCH: '匹配',
        CAP_ROOM: '房间',
    }.get(cap, '该功能')
    return (f'你的账号暂时无法使用{what}。'
            f'这通常是因为系统检测到异常对局。如有疑问请联系管理员。')


# ---------------------------------------------------------------------------
# 四、最终等级：嫌疑度 + 管理员覆盖
# ---------------------------------------------------------------------------
def effective_level(score, override=None) -> int:
    """实际生效的封禁等级。

    `override` 是**管理员的手动决定**（`None` = 没干预）：
      · `override` 为 dict 且带 `'level'` → **以管理员为准**（可以调高也可以调低）
      · `'cleared'` 为真 → 视为 0（解封）

    ⚠️ 管理员覆盖**优先于算法**：这是"人的决定 > 机器判断"。
    但覆盖要落库留存（谁、什么时候、为什么），否则无法审计 —— 见 `db` 侧。
    """
    try:
        if isinstance(override, dict):
            if override.get('cleared'):
                return LEVEL_NONE
            if override.get('level') is not None:
                lv = int(override['level'])
                return max(0, min(lv, LEVEL_NO_ROOM))
    except (TypeError, ValueError):
        pass
    return level_from_score(score)


def build_report(uid, matches, override=None, username=None) -> dict:
    """组装给管理后台用的**一个人**的完整嫌疑度报告。

    ⚠️ 只返回叶子字段组成的小对象，**绝不把服务端活数据塞进来**
    （与 `rank_view` 同规矩：可以 JSON 化，可以直接下发给前端）。
    """
    try:
        score = accumulate(matches)
    except Exception:
        score = 0.0
    lv = effective_level(score, override)
    return {
        'user_id': uid,
        'username': username,
        'suspicion': round(score, 1),
        'level': lv,
        'level_name': level_name(lv),
        'next_threshold': next_threshold(score),
        'blocked': blocked_capabilities(lv),
        'overridden': bool(isinstance(override, dict) and
                           (override.get('cleared') or override.get('level') is not None)),
        'override_reason': (override or {}).get('reason') if isinstance(override, dict) else None,
        'match_count': len(matches or ()),
    }
