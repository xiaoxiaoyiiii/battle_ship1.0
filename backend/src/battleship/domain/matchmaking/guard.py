"""Matchmaking avoidance (ticket #16) -- pure functions, no sockets/database.

Ported from the legacy `match_guard.py`. The rule set is soft avoidance plus a
hard fallback, because avoidance must never deadlock the queue: at night two
players who just played each other, or share one flat's IP, must still be able
to start a match.

* Hard block (never pair): the same account (two tabs), and same public IP
  where BOTH accounts are already flagged.
* Soft penalty (order only): same public IP, recent opponent.

**The load-bearing invariant**: "did this pair avoid each other?" is a
preference. "Does this match count for rank points?" is decided by anti-cheat
on match content. The legacy stack once wrote
`room.ranked = (mode == ranked) and assessed`, which silently stopped ranking
the most common small-community match ("the same opponent again") while every
page and endpoint kept working. See CLAUDE #33.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

#: A recent opponent is avoided for this long. The legacy constant had no
#: consumer (DECISIONS D11); we keep the number and do NOT invent a time filter
#: here either -- the recent-opponent set already comes from the last N matches.
RECENT_OPPONENT_COOLDOWN_SEC = 30 * 60

#: How many recent matches define "recent opponent".
RECENT_OPPONENT_LOOKBACK = 8

SCORE_BASE = 1000
PENALTY_SAME_IP = 400
PENALTY_RECENT_OPPONENT = 300
PENALTY_SAME_IP_DIRTY = 10_000


def usable_ip(ip: Any) -> str:
    """Return the IP only when it can be judged; loopback/private -> "".

    Same reasoning as the legacy `_usable_ip`: applying same-IP avoidance to
    loopback or private addresses turns every local/LAN pair into "not the
    preferred pair". If that value ever decided ranking, every local match would
    silently stop counting (CLAUDE #23). Only addresses that look public are
    judged; the parser is deliberately conservative.
    """
    text = str(ip or "").strip()
    if not text:
        return ""
    low = text.lower()
    if low in ("localhost", "::1", "0.0.0.0", "::"):
        return ""
    if low.startswith("::ffff:"):
        # Must strip by the prefix length, not by split(":")[-1].
        return usable_ip(text[len("::ffff:"):])
    if low.startswith("127.") or low.startswith("10.")             or low.startswith("192.168.") or low.startswith("169.254."):
        return ""
    if low.startswith("172."):
        try:
            second = int(low.split(".")[1])
        except (IndexError, ValueError):
            return ""
        if 16 <= second <= 31:
            return ""
    if low.startswith("fe80:") or low.startswith("fc") or low.startswith("fd"):
        return ""
    return text


class Candidate:
    """One queued player plus the facts used to rank a pair (pure data)."""

    __slots__ = ("sid", "uid", "mode", "ip", "recent_foes", "ip_dirty", "waited_sec")

    def __init__(
        self,
        sid: str,
        uid: str | None = None,
        mode: str = "",
        ip: Any = None,
        recent_foes: Iterable[str] = (),
        ip_dirty: bool = False,
        waited_sec: int = 0,
    ) -> None:
        self.sid = sid
        self.uid = uid
        self.mode = mode
        self.ip = usable_ip(ip)
        self.recent_foes = tuple(recent_foes or ())
        self.ip_dirty = bool(ip_dirty)
        self.waited_sec = int(waited_sec or 0)


def _same_account(a: Candidate, b: Candidate) -> bool:
    return a.uid is not None and a.uid == b.uid


def hard_block(a: Candidate, b: Candidate) -> str:
    """Reason this pair must never be created ("" = allowed).

    Only rules where pairing is worse than waiting belong here.
    """
    if _same_account(a, b):
        return "same_account"
    if a.ip and a.ip == b.ip and a.ip_dirty and b.ip_dirty:
        return "same_ip_dirty"
    return ""


def pair_score(a: Candidate, b: Candidate) -> int:
    """Higher is better. Sorting only -- never a settlement criterion."""
    score = SCORE_BASE
    if a.ip and a.ip == b.ip:
        score -= PENALTY_SAME_IP
        if a.ip_dirty or b.ip_dirty:
            score -= PENALTY_SAME_IP_DIRTY
    if b.uid and b.uid in a.recent_foes:
        score -= PENALTY_RECENT_OPPONENT
    if a.uid and a.uid in b.recent_foes:
        score -= PENALTY_RECENT_OPPONENT
    score += min(int(a.waited_sec), 600) // 10
    score += min(int(b.waited_sec), 600) // 10
    return score


def pick_pair(queue: Sequence[Candidate]) -> tuple[int | None, int | None, bool]:
    """Pick one pair from the queue.

    Returns `(i, j, assessed)` where `assessed` is only "was this the pair the
    avoidance rules preferred?" (True = neither side took a soft penalty).
    It must never be used to decide ranking (CLAUDE #33).

    No pair available -> `(None, None, False)` and the queue is left untouched,
    so a new arrival can still pair later.
    """
    best: tuple[int, int, int] | None = None
    for i in range(len(queue)):
        a = queue[i]
        for j in range(i + 1, len(queue)):
            b = queue[j]
            if a.mode != b.mode:
                continue
            if hard_block(a, b):
                continue
            score = pair_score(a, b)
            if best is None or score > best[0]:
                best = (score, i, j)
    if best is None:
        return None, None, False

    score, i, j = best
    return i, j, score >= SCORE_BASE
