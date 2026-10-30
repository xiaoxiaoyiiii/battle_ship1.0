"""对局回放服务（ticket #18）：落库开关、读接口权限、设置读写。

分层：
* 纯记录器/打包在 battleship.domain.replay（绝不碰 socket/DB）；
* 本模块只做用例编排：用 #5 的 UnitOfWork / 仓储读写，不写裸 SQL；
* HTTP 路由只做请求解析与响应形状（见 http/routers/replay.py）。

隐私与失败方向（旧栈契约 + DECISIONS D13）：
* 读回放要求登录；能看 = 本人是参与者，或任一真实参与者 show_history=1；
* allow_replay 读库失败一律按**不记录**（fail-closed），并打日志；
* 设置读失败返回 None（接口 503 "不知道"），绝不谎报成允许；
* 响应里剥掉 seats（uid -> p1/p2 只在服务端算 you_are）。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from ..domain import replay as replay_rules
from ..infra.logging import get_logger
from ..repositories import Database

logger = get_logger("replay")

REPLAY_VERSION = replay_rules.REPLAY_VERSION
MAX_REPLAY_BYTES = replay_rules.MAX_REPLAY_BYTES


@dataclass(frozen=True)
class ReplayResponse:
    """One HTTP answer: status code + legacy-shaped body."""

    status: int
    body: dict[str, Any]


def build_replay(room) -> dict[str, Any] | None:
    """Settlement hook: the finished room's real replay payload (None = 0 steps)."""
    return replay_rules.finalize(room)


def _allow_replay_for(uow, user_id: str) -> bool:
    profile = uow.social.get_profile(user_id)
    if not profile:
        return True  # never touched the switch -> legacy default on
    value = profile.get("allow_replay")
    if value is None:
        return True
    return bool(int(value))


def allowed_for_match(database: Database, winner_user_id: str | None,
                      loser_user_id: str | None) -> bool:
    """Whether this match may keep a replay (any participant off => no replay)."""
    seats = [uid for uid in (winner_user_id, loser_user_id) if uid]
    if not seats:
        return False
    try:
        with database.unit_of_work() as uow:
            return all(_allow_replay_for(uow, uid) for uid in seats)
    except Exception as error:  # noqa: BLE001 - fail-closed, never leak a replay
        logger.error(
            "read allow_replay failed; keeping no replay",
            extra={"error_type": type(error).__name__},
            exc_info=error,
        )
        return False


def read_allow_replay(database: Database, user_id: str) -> bool | None:
    """The setting for /api/replay/setting GET; None = unreadable (503)."""
    try:
        with database.unit_of_work() as uow:
            return _allow_replay_for(uow, user_id)
    except Exception as error:  # noqa: BLE001
        logger.error(
            "read replay setting failed",
            extra={"error_type": type(error).__name__},
            exc_info=error,
        )
        return None


def save_allow_replay(database: Database, user_id: str, on: bool) -> bool:
    try:
        with database.unit_of_work() as uow:
            uow.social.save_profile(
                user_id,
                {"allow_replay": 1 if on else 0},
                updated_at=int(time.time()),
            )
        return True
    except Exception as error:  # noqa: BLE001
        logger.error(
            "save replay setting failed",
            extra={"error_type": type(error).__name__},
            exc_info=error,
        )
        return False


def _participants(row: dict[str, Any]) -> list[str]:
    return [uid for uid in (row.get("winner_user_id"), row.get("loser_user_id")) if uid]


def _show_history(uow, user_id: str) -> bool:
    """Fail closed: any read error means "not published"."""
    try:
        profile = uow.social.get_profile(user_id)
        if not profile:
            return False
        return bool(int(profile.get("show_history") or 0))
    except Exception:  # noqa: BLE001
        return False


def _error(status: int, message: str) -> ReplayResponse:
    return ReplayResponse(status, {"success": False, "error": message})


def read_replay(database: Database, match_id: str, viewer_uid: str | None) -> ReplayResponse:
    """The whole GET /api/replay/<match_id> decision, in one place."""
    if not viewer_uid:
        return _error(401, "未登录")

    try:
        with database.unit_of_work() as uow:
            row = uow.replays.get(match_id)
            if row is None:
                return _error(404, "这局没有可回放的行动")

            participants = _participants(row)
            allowed = str(viewer_uid) in {str(uid) for uid in participants}
            if not allowed:
                allowed = any(_show_history(uow, uid) for uid in participants)
            if not allowed:
                return _error(403, "你没有权限查看这一局的回放")

            try:
                size = int(row.get("bytes") or 0)
            except (TypeError, ValueError):
                size = 0
            if size > MAX_REPLAY_BYTES:
                logger.error(
                    "replay blob over the byte cap; refusing to serve",
                    extra={"match_id": match_id, "bytes": size},
                )
                return _error(500, "这条回放数据异常（体积超限），已拒绝加载")

            blob = row.get("replay") or ""
            if len(str(blob).encode("utf-8")) > MAX_REPLAY_BYTES:
                logger.error(
                    "replay blob over the byte cap (actual bytes); refusing to serve",
                    extra={"match_id": match_id},
                )
                return _error(500, "这条回放数据异常（体积超限），已拒绝加载")

            try:
                payload = json.loads(blob)
            except Exception as error:  # noqa: BLE001 - corrupt row: report + delete
                logger.error(
                    "replay blob is corrupt; deleting the bad row",
                    extra={"match_id": match_id, "error_type": type(error).__name__},
                )
                uow.replays.delete(match_id)
                return _error(500, "这条回放已损坏，无法回放")
            if not isinstance(payload, dict):
                logger.error(
                    "replay blob is not a JSON object; deleting the bad row",
                    extra={"match_id": match_id},
                )
                uow.replays.delete(match_id)
                return _error(500, "这条回放已损坏，无法回放")

            try:
                version = int(payload.get("version") or 0)
            except (TypeError, ValueError):
                version = 0
            if version != REPLAY_VERSION:
                logger.error(
                    "unsupported replay version",
                    extra={"match_id": match_id, "version": payload.get("version")},
                )
                return _error(409, "这条回放的格式版本不支持")

            you_are = replay_rules.you_are(payload, row, viewer_uid)
            # seats maps uid -> p1/p2; it is server-side metadata only.
            public_payload = {key: value for key, value in payload.items() if key != "seats"}
            return ReplayResponse(200, {
                "success": True,
                "replay": public_payload,
                "you_are": you_are,
            })
    except Exception as error:  # noqa: BLE001 - never leak a half payload
        logger.error(
            "read replay failed",
            extra={"match_id": match_id, "error_type": type(error).__name__},
            exc_info=error,
        )
        return _error(500, "读取回放失败，请稍后重试")
