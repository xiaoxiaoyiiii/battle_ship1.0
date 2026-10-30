"""结构化日志：JSON 行 + 房间/座位/事件上下文。

旧栈是 Flask/eventlet 的自由文本日志，排查一局对局要在几千行里 grep。
这里用 contextvars 记录 `room_id / player_id / seat / event / request_id`，
每条日志自动带上；HTTP 中间件与 Socket.IO 适配层负责填上下文。
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, TextIO

_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "battleship_log_context", default={}
)

# 这些上下文键一定会写进 JSON 行（其余 extra 也会被带上）。
_CONTEXT_KEYS = (
    "request_id",
    "room_id",
    "player_id",
    "seat",
    "event",
    "method",
    "path",
    "status",
    "duration_ms",
)

_RESERVED_RECORD_KEYS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def bind_context(**fields: Any) -> contextvars.Token:
    """在 contextvar 上合并字段；返回 token 供上层 reset。"""

    merged = {**_CONTEXT.get(), **{k: v for k, v in fields.items() if v is not None}}
    return _CONTEXT.set(merged)


def clear_context() -> None:
    _CONTEXT.set({})


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    token = bind_context(**fields)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = _CONTEXT.get()
        for key in _CONTEXT_KEYS:
            if key in context:
                payload[key] = context[key]
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_KEYS or key.startswith("_"):
                continue
            if key in payload:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


class HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = _CONTEXT.get()
        suffix = " ".join(f"{key}={value}" for key, value in sorted(context.items()) if value is not None)
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname} {record.name}: {record.getMessage()}"
        if suffix:
            base = f"{base} | {suffix}"
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        return base


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = True,
    stream: TextIO | None = None,
    force: bool = False,
) -> None:
    """配置根 logger。

    `force=True` 供测试/独立脚本使用；应用启动时不清空 uvicorn 已有的 handler，
    只追加一个结构化 handler（避免与 uvicorn 的访问日志互相覆盖）。
    """

    root = logging.getLogger()
    if force:
        root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    already = any(getattr(handler, "_battleship_structured", False) for handler in root.handlers)
    if already and not force:
        return

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(StructuredJsonFormatter() if json_output else HumanFormatter())
    handler._battleship_structured = True  # type: ignore[attr-defined]
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    if name.startswith("battleship"):
        return logging.getLogger(name)
    return logging.getLogger(f"battleship.{name}")
