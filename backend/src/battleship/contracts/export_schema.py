"""把 contracts 导出为可哈希比对的 JSON Schema，并生成前端 TS 常量。

前端消费方式：
* 运行时：`GET /api/contracts/schema` 返回 `{hash, bundle}`，ETag = hash；
* 构建期：`python -m battleship.contracts.export_schema --format ts --out .../events.gen.ts`。

哈希规则：对 `schema_bundle()` 的 canonical JSON（sort_keys + 紧凑分隔符 + UTF-8）
做 SHA-256。bundles 不含自身哈希，导出文件是 `{hash, bundle}` 信封。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .errors import SOCKET_ERROR_CODES, SocketError
from .events_in import DEBUG_EVENTS, INBOUND_EVENTS, InboundEventEnvelope
from .events_out import (
    OUTBOUND_EVENTS,
    ROOM_SYNC_KEYS,
    AckResponse,
    OutboundEventEnvelope,
    RoomSync,
)
from .http_models import (
    ErrorDetail,
    ErrorResponse,
    HealthCheck,
    HealthResponse,
    LatencyStats,
    MetricsResponse,
)
from .identity import (
    IdentityClaim,
    IdentityDecision,
    RoomKind,
    SeatIdentity,
    SocketIdentity,
)

SCHEMA_VERSION = 1
GENERATED_BY = "battleship.contracts.export_schema"
DEFAULT_FRONTEND_TARGET = "frontend/src/socket/events.gen.ts"

_MODELS: dict[str, type[BaseModel]] = {
    "AckResponse": AckResponse,
    "ErrorDetail": ErrorDetail,
    "ErrorResponse": ErrorResponse,
    "HealthCheck": HealthCheck,
    "HealthResponse": HealthResponse,
    "IdentityClaim": IdentityClaim,
    "IdentityDecision": IdentityDecision,
    "InboundEventEnvelope": InboundEventEnvelope,
    "LatencyStats": LatencyStats,
    "MetricsResponse": MetricsResponse,
    "SocketError": SocketError,
    "OutboundEventEnvelope": OutboundEventEnvelope,
    "RoomSync": RoomSync,
    "SeatIdentity": SeatIdentity,
    "SocketIdentity": SocketIdentity,
}


def schema_bundle() -> dict[str, Any]:
    """返回契约包（不含自身哈希，保证可重复计算）。"""

    return {
        "schema_version": SCHEMA_VERSION,
        "title": "battleship-contracts",
        "generated_by": GENERATED_BY,
        "events": {
            "inbound": list(INBOUND_EVENTS),
            "outbound": list(OUTBOUND_EVENTS),
            "debug": list(DEBUG_EVENTS),
        },
        "identity": {
            "room_kinds": [kind.value for kind in RoomKind],
            "spectate_room_prefix": "spectate:",
            "player_key_rules": {
                "matchmaking": "enqueue socket sid (server-issued player_id)",
                "custom": "session user_id, or socket sid for guests",
                "ai": "ai-<room_id>",
                "spectate": "spectate:<room_id>; never a seat",
            },
        },
        "error_codes": list(SOCKET_ERROR_CODES),
        "models": {
            name: model.model_json_schema(mode="validation")
            for name, model in sorted(_MODELS.items())
        },
    }


def canonical_json(value: Any) -> str:
    """canonical JSON：同一份契约在任何机器/任何进程上逐字节一致。"""

    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def schema_hash(bundle: dict[str, Any] | None = None) -> str:
    payload = schema_bundle() if bundle is None else bundle
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def schema_document() -> dict[str, Any]:
    """导出文件/HTTP 响应的信封：hash + bundle。"""

    bundle = schema_bundle()
    return {"hash": schema_hash(bundle), "bundle": bundle}


def export_schema_file(target: str | Path, *, fmt: str = "json") -> dict[str, Any]:
    """写契约文件并返回导出信封。前端 TS 只写 hash/事件清单/接口。"""

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "ts":
        path.write_text(frontend_ts(), encoding="utf-8")
        return {"hash": schema_hash(), "path": str(path)}
    if fmt != "json":
        raise ValueError(f"unknown schema format: {fmt}")

    document = schema_document()
    path.write_text(
        json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return document


def check_schema_file(path: str | Path) -> bool:
    """校验文件与当前 contracts 完全一致（哈希 + bundle canonical 内容）。"""

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    bundle = data.get("bundle")
    if not isinstance(bundle, dict):
        return False
    if data.get("hash") != schema_hash(bundle):
        return False
    return canonical_json(bundle) == canonical_json(schema_bundle())


def _ts_array(name: str, values: tuple[str, ...]) -> str:
    body = ",\n".join(f"  '{value}'" for value in values)
    return f"export const {name} = [\n{body},\n] as const"


def frontend_ts() -> str:
    """生成前端可消费的类型/常量。输出只依赖 contracts，顺序稳定。"""

    digest = schema_hash()
    lines = [
        "// GENERATED from backend contracts (JSON Schema). Do not edit by hand.",
        "// Regenerate: python -m battleship.contracts.export_schema --format ts --out frontend/src/socket/events.gen.ts",
        f"export const CONTRACT_SCHEMA_VERSION = {SCHEMA_VERSION}",
        f"export const CONTRACT_SCHEMA_HASH = '{digest}'",
        "",
        _ts_array("INBOUND_EVENTS", INBOUND_EVENTS),
        "",
        _ts_array("OUTBOUND_EVENTS", OUTBOUND_EVENTS),
        "",
        _ts_array("DEBUG_EVENTS", DEBUG_EVENTS),
        "",
        _ts_array("SOCKET_ERROR_CODES", SOCKET_ERROR_CODES),

        # The reconnect snapshot is the widest server state a screen can receive;
        # the Pinia store mirrors these keys (ticket #21) and a type-level parity
        # check fails the build if a contract field is dropped or misspelled.
        _ts_array("ROOM_SYNC_FIELDS", ROOM_SYNC_KEYS),
        "",
        "export type RoomSyncField = (typeof ROOM_SYNC_FIELDS)[number]",
        "",
        "export type InboundEvent = (typeof INBOUND_EVENTS)[number]",
        "export type OutboundEvent = (typeof OUTBOUND_EVENTS)[number]",
        "export type DebugEvent = (typeof DEBUG_EVENTS)[number]",
        "export type RoomKind = 'matchmaking' | 'custom' | 'ai' | 'spectate'",
        "",
        "export interface SocketIdentity {",
        "  player_id: string | null",
        "  user_id: number | null",
        "}",
        "",
        "export interface InboundEventEnvelope {",
        "  event: string",
        "  data: Record<string, unknown>",
        "  namespace: string",
        "  identity: SocketIdentity | null",
        "}",
        "",
        "export interface OutboundEventEnvelope {",
        "  event: string",
        "  data: Record<string, unknown>",
        "  namespace: string",
        "  to: string | null",
        "  room: string | null",
        "  skip_sid: string | null",
        "}",
        "",
        "export interface SocketError {",
        "  code: string",
        "  message: string",
        "}",
        "",
        "export interface AckResponse {",
        "  status: 'success' | 'error'",
        "  message: string | null",
        "  data: Record<string, unknown> | null",
        "}",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export battleship contracts JSON Schema / TS constants.")
    parser.add_argument("--out", help="output path; omit to write JSON schema to stdout")
    parser.add_argument("--format", choices=("json", "ts"), default="json")
    parser.add_argument("--check", metavar="PATH", help="exit 1 if PATH does not match current contracts")
    parser.add_argument("--print-hash", action="store_true", help="print the canonical schema hash")
    args = parser.parse_args(argv)

    if args.check:
        ok = check_schema_file(args.check)
        print("OK" if ok else "SCHEMA_MISMATCH", args.check)
        return 0 if ok else 1

    if args.print_hash:
        print(schema_hash())
        if not args.out:
            return 0

    if args.out:
        export_schema_file(args.out, fmt=args.format)
        if not args.print_hash:
            print(f"{schema_hash()} {args.out}")
        return 0

    if args.format == "ts":
        sys.stdout.write(frontend_ts())
    else:
        sys.stdout.write(json.dumps(schema_document(), sort_keys=True, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
