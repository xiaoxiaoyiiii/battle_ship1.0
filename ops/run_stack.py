#!/usr/bin/env python
"""Local one-command full stack: frontend check -> migrate -> uvicorn.

    python ops/run_stack.py --port 5000 --db .tmp/dev.db

There is exactly one stack after Phase 5. Production does not use this script
(systemd runs uvicorn directly, see ops/systemd/battleship.service); it exists so
a developer can boot everything with one command.

Fail-fast rules (D30):

* a stale migration-window stack selector in the environment exits 2 instead of
  silently running something else (see `_guard_stack_env`);
* the frontend build must exist. Pass `--build` to build it, otherwise the
  script names the missing file and the command to fix it;
* a legacy frontend mode is rejected by the backend settings at startup.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"


def _guard_stack_env() -> bool:
    value = (os.environ.get("BACKEND_STACK") or "").strip().lower()
    if value and value != "rewrite":
        print(
            "启动失败: BACKEND_STACK=" + value + " 已移除（Phase 5 只有新栈）。"
            "请从环境变量/EnvironmentFile 中删除 BACKEND_STACK。",
            file=sys.stderr,
        )
        return False
    return True


def _resolve_dist(explicit: str | None) -> Path:
    candidate = explicit or os.environ.get("FRONTEND_DIST")
    return Path(candidate).resolve() if candidate else ROOT / "frontend" / "dist"


def _migrate(database: Path) -> int:
    result = subprocess.run(
        [sys.executable, str(ROOT / "ops" / "migrate.py"), "--database", str(database)],
        cwd=str(ROOT),
    )
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ops/run_stack.py", description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5000")))
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--db", default=os.environ.get("BATTLESHIP_DB_PATH", "./battleship.db"))
    parser.add_argument("--frontend-dist", default=None)
    parser.add_argument("--build", action="store_true", help="build the frontend first")
    parser.add_argument("--skip-migrate", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not _guard_stack_env():
        return 2

    dist = _resolve_dist(args.frontend_dist)
    if not (dist / "index.html").is_file():
        if args.build:
            code = subprocess.run(
                [sys.executable, str(ROOT / "ops" / "build.py"), "--frontend-only"],
                cwd=str(ROOT),
            ).returncode
            if code != 0:
                return code
        if not (dist / "index.html").is_file():
            print(
                f"启动失败: 找不到前端构建产物 {dist / 'index.html'}。"
                "先运行 python ops/build.py（或 pnpm build），或加 --build。",
                file=sys.stderr,
            )
            return 2

    database = Path(args.db).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print(f"root: {ROOT}")
        print(f"dist: {dist}")
        print(f"database: {database}")
        print(f"migrate: {'skipped' if args.skip_migrate else 'python ops/migrate.py --database ' + str(database)}")
        print(f"serve: uvicorn battleship.main:app --host {args.host} --port {args.port}")
        print(f"open: http://{args.host}:{args.port}/health")
        print("dry-run: nothing was started")
        return 0

    if not args.skip_migrate:
        code = _migrate(database)
        if code != 0:
            print("migration failed; refusing to start", file=sys.stderr)
            return code

    os.environ["BATTLESHIP_DB_PATH"] = str(database)
    os.environ["PORT"] = str(args.port)
    os.environ["HOST"] = args.host
    os.environ.setdefault("CORS_ORIGINS", f"http://127.0.0.1:{args.port}")
    os.environ.setdefault("FRONTEND_DIST", str(dist))
    if str(BACKEND_SRC) not in sys.path:
        sys.path.insert(0, str(BACKEND_SRC))
    os.chdir(ROOT)

    import uvicorn

    uvicorn.run(
        "battleship.main:app",
        host=args.host,
        port=args.port,
        log_config=None,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
