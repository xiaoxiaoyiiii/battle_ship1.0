"""Single-match anti-cheat rules (ticket #16).

Ported from the legacy `anticheat.py`, which is the only definition of the
weights and thresholds. This module is pure data + pure functions: no database,
no sockets, no logging side effects. "Should a match be punished" is decided
here; "what action to take" belongs to services/anticheat.py.

Design constraints carried over verbatim:

* facts come from server-side room state only (rounds, hits, ships, duration,
  end reason) -- never from client payloads and never by aligning a user id with
  a socket id (the first version did that and scored 0% recall on 166 known
  cheating matches while all unit tests were green, CLAUDE #20);
* every rule fails open: a dirty fact must never crash settlement (CLAUDE #34
  still applies: the caller reports the result, it just does not block play);
* unknown rounds are -1 and must not satisfy "rounds <= 1" (CLAUDE #21).
"""

from __future__ import annotations

from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Suspicion weights. Values are not arbitrary: they are graded by "how likely
# is this signal in a normal match". The rarer the signal, the heavier it is.
# ---------------------------------------------------------------------------
W: dict[str, int] = {
    # Fatal signals (a normal player practically cannot produce them).
    "sweep_perfect_win": 100,       # all ships sunk in one round, no return fire
    "mirror_positions": 90,         # opponent's layout repeats a historical one
    "instant_surrender": 80,        # round 1 surrender with zero exchange
    # Strong signals.
    "repeat_opponent_burst": 60,    # same opponent several times in minutes
    "one_sided_series": 55,         # 5+ games vs one opponent, one side wins all
    "sub_round_win": 40,            # win within 2-3 rounds
    # Medium signals.
    "zero_engagement_loss": 30,     # loser never lands a hit
    "suspicious_timing": 25,        # matches started back to back
    "win_streak_anomaly": 20,       # abnormal ranked win streak
}

# Level thresholds (the legacy names, not the stepped-ban levels).
LEVEL_RECORD = 30
LEVEL_FLAG = 60
LEVEL_BLOCK = 100


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Safe read from a dict or an object; never raises."""
    try:
        if isinstance(obj, Mapping):
            return obj.get(key, default)
        return getattr(obj, key, default)
    except Exception:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ===========================================================================
# Rule 1: predictable layout -- the direct fingerprint of a human target
# ===========================================================================
def rule_sweep_perfect_win(facts: dict) -> list[dict]:
    """One side sinks every ship in round 0/1 while the other never fires.

    Deliberately independent of "who won": matches.winner_id stores a user id
    while attack logs store a socket id, and the first version aligned those two
    id spaces (0% recall). The shape itself is stronger evidence.
    """
    out: list[dict] = []
    try:
        rounds = int(facts.get("rounds", -1))
        attackers = facts.get("attackers") or []
        max_hits = _int(facts.get("max_hits"))
        foe_ships = _int(facts.get("foe_ships"))
        only_one_shooter = len(set(attackers)) <= 1

        if (
            only_one_shooter
            and foe_ships > 0
            and max_hits >= foe_ships
            and 0 <= rounds <= 1
        ):
            out.append({
                "rule": "sweep_perfect_win",
                "weight": W["sweep_perfect_win"],
                "detail": (
                    f"第 {rounds} 回合内单方连续击沉全部 {max_hits} 艘，"
                    f"另一方全程一枪未发 —— 船位可预测（人肉靶子）"
                ),
            })
    except Exception:
        pass
    return out


def rule_mirror_positions(facts: dict) -> list[dict]:
    """The opponent's ship signature already appeared in this account's history."""
    out: list[dict] = []
    try:
        sig = facts.get("foe_position_signature")
        past = facts.get("past_signatures") or []
        if sig and sig in past:
            n = list(past).count(sig)
            out.append({
                "rule": "mirror_positions",
                "weight": W["mirror_positions"],
                "detail": f"对手船位与该账号历史上 {n} 局完全相同（船位未变，疑似固定靶子）",
            })
    except Exception:
        pass
    return out


# ===========================================================================
# Rule 2: surrender on sight / zero exchange
# ===========================================================================
def rule_instant_surrender(facts: dict) -> list[dict]:
    """Round 1 surrender after the match really started, with no hits either way."""
    out: list[dict] = []
    try:
        if facts.get("ended_by") != "surrender":
            return out
        rounds = _int(facts.get("rounds"))
        attacker_hits = _int(facts.get("attacker_total_hits"))
        defender_hits = _int(facts.get("defender_total_hits"))
        if rounds <= 1 and attacker_hits == 0 and defender_hits == 0:
            out.append({
                "rule": "instant_surrender",
                "weight": W["instant_surrender"],
                "detail": "开局第 1 回合、双方零次有效攻击即投降",
            })
    except Exception:
        pass
    return out


def rule_zero_engagement_loss(facts: dict) -> list[dict]:
    """The losing side never lands a hit (three exemptions, all measured).

    1. A surrender is legitimate; instant surrender is handled by its own rule.
    2. An empty board (ships never placed, or the match never really started)
       produces the same "zero hits" shape but is not a player refusing to play.
    3. Therefore the opponent must actually have ships to shoot at.
    """
    out: list[dict] = []
    try:
        if facts.get("ended_by") == "surrender":
            return out
        loser_hits = _int(facts.get("loser_total_hits"))
        rounds = _int(facts.get("rounds"))
        foe_ships = _int(facts.get("foe_ships"))
        total_ships = _int(facts.get("total_ships"))
        if foe_ships <= 0 or total_ships <= 0:
            return out
        if rounds >= 2 and loser_hits == 0:
            out.append({
                "rule": "zero_engagement_loss",
                "weight": W["zero_engagement_loss"],
                "detail": f"败方 {rounds} 个回合内零次有效攻击（全程不还手）",
            })
    except Exception:
        pass
    return out


# ===========================================================================
# Rule 3: match manipulation -- repeatedly meeting the same opponent
# ===========================================================================
def rule_repeat_opponent_burst(facts: dict) -> list[dict]:
    """Same opponent three or more times within five minutes."""
    out: list[dict] = []
    try:
        gaps = facts.get("opponent_gaps_sec") or []
        if len(gaps) < 3:
            return out
        fast = [g for g in gaps if _int(g) <= 300]
        if len(fast) >= 3:
            out.append({
                "rule": "repeat_opponent_burst",
                "weight": W["repeat_opponent_burst"],
                "detail": (
                    f"与同一对手 {len(gaps)} 局中，{len(fast)} 局的间隔在 5 分钟内"
                    f"（最短 {min(_int(g) for g in fast)} 秒）—— 疑似同时排队对刷"
                ),
            })
    except Exception:
        pass
    return out


def rule_one_sided_series(facts: dict) -> list[dict]:
    """Five or more games against one opponent, one side never wins."""
    out: list[dict] = []
    try:
        n = _int(facts.get("opponent_total_games"))
        w = _int(facts.get("opponent_wins"))
        losses = _int(facts.get("opponent_losses"))
        if n >= 5 and (w == 0 or losses == 0):
            loser = "本方" if w == 0 else "对方"
            out.append({
                "rule": "one_sided_series",
                "weight": W["one_sided_series"],
                "detail": f"与同一对手交手 {n} 局，{loser}一局未胜（100% 一边倒）",
            })
    except Exception:
        pass
    return out


# ===========================================================================
# Rule 4: timing and streak anomalies
# ===========================================================================
def rule_suspicious_timing(facts: dict) -> list[dict]:
    """Matches started back to back (bulk restart) or finished within 30s."""
    out: list[dict] = []
    try:
        gap = _int(facts.get("since_last_match_sec"), -1)
        duration = _int(facts.get("duration_sec"))
        if 0 <= gap <= 20:
            out.append({
                "rule": "suspicious_timing",
                "weight": W["suspicious_timing"],
                "detail": f"距上一局仅 {gap} 秒（批量重开特征）",
            })
        elif duration > 0 and duration <= 30:
            out.append({
                "rule": "suspicious_timing",
                "weight": W["suspicious_timing"],
                "detail": f"本局用时仅 {duration} 秒",
            })
    except Exception:
        pass
    return out


def rule_win_streak_anomaly(facts: dict) -> list[dict]:
    """A ranked win streak far outside the normal distribution."""
    out: list[dict] = []
    try:
        streak = _int(facts.get("ranked_win_streak"))
        if streak >= 12:
            out.append({
                "rule": "win_streak_anomaly",
                "weight": W["win_streak_anomaly"],
                "detail": f"排位已连胜 {streak} 场（异常值）",
            })
    except Exception:
        pass
    return out


# ===========================================================================
# Rule 5: end shape -- a very short win
# ===========================================================================
def rule_sub_round_win(facts: dict) -> list[dict]:
    """Win within 2-3 rounds (strong, but not as strong as a perfect sweep)."""
    out: list[dict] = []
    try:
        rounds = _int(facts.get("rounds"))
        sunk = _int(facts.get("sunk"))
        if 2 <= rounds <= 3 and sunk > 0:
            out.append({
                "rule": "sub_round_win",
                "weight": W["sub_round_win"],
                "detail": f"{rounds} 个回合内结束对局（击沉 {sunk} 艘）",
            })
    except Exception:
        pass
    return out


RULES = (
    rule_sweep_perfect_win,
    rule_mirror_positions,
    rule_instant_surrender,
    rule_repeat_opponent_burst,
    rule_one_sided_series,
    rule_zero_engagement_loss,
    rule_suspicious_timing,
    rule_win_streak_anomaly,
    rule_sub_round_win,
)


def evaluate(facts: dict) -> dict:
    """Evaluate one match; always returns a complete, explainable verdict.

    ```
    {"score": int, "level": "clean|record|flag|block",
     "reasons": [...], "rules": [...], "blocked": bool}
    ```

    Fails open: any exception degrades to "clean" instead of breaking settlement.
    """
    reasons: list[dict] = []
    try:
        for fn in RULES:
            try:
                reasons.extend(fn(facts or {}) or [])
            except Exception:
                continue
    except Exception:
        reasons = []

    score = sum(_int(reason.get("weight")) for reason in reasons)
    if score >= LEVEL_BLOCK:
        level = "block"
    elif score >= LEVEL_FLAG:
        level = "flag"
    elif score >= LEVEL_RECORD:
        level = "record"
    else:
        level = "clean"

    return {
        "score": score,
        "level": level,
        "reasons": reasons,
        "rules": [reason.get("rule") for reason in reasons],
        "blocked": level == "block",
    }


def explain(result: dict) -> str:
    """Human-readable audit text (logs / admin detail); never raises."""
    try:
        if not result or result.get("level") == "clean":
            return "无异常"
        parts = [
            f"{reason.get('rule')}(+{reason.get('weight')}): {reason.get('detail')}"
            for reason in (result.get("reasons") or [])
        ]
        return f"嫌疑度 {result.get('score')} [{result.get('level')}] — " + "；".join(parts)
    except Exception:
        return "（判定结果无法解释）"
