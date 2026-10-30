#!/usr/bin/env python
"""Build one deployable release: backend dependencies + the Vite frontend.

Deployment order (ops/README.md):

    ops/build.py      # this script: pip install -e backend, pnpm install/build
    ops/migrate.py    # Alembic upgrade + pre-migration backup
    systemctl restart battleship
    ops/healthcheck.py

The script verifies the build output as well: `frontend/dist/index.html`, the
Vite manifest, and all 48 card faces must exist, otherwise the release is not
deployable. `--dry-run` prints the plan without touching anything.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
EXPECTED_CARD_FACES = 48


def _run(command: list[str], cwd: Path, *, dry_run: bool, shell: bool = False) -> int:
    printable = " ".join(command)
    print("$ " + printable)
    if dry_run:
        return 0
    result = subprocess.run(command, cwd=str(cwd), shell=shell)
    if result.returncode != 0:
        print(f"build step failed ({result.returncode}): {printable}", file=sys.stderr)
    return result.returncode


def _pip_available() -> bool:
    probe = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return probe.returncode == 0


def _install_backend(dry_run: bool) -> int:
    if not dry_run and not _pip_available():
        print(
            f"{sys.executable} 没有 pip。请用 python -m venv 创建的解释器运行"
            "（或先 python -m ensurepip），也可以用 --frontend-only 只构建前端。",
            file=sys.stderr,
        )
        return 2
    return _run([sys.executable, "-m", "pip", "install", "-e", str(ROOT / "backend")],
                ROOT, dry_run=dry_run)


def _build_frontend(dry_run: bool, skip_install: bool) -> int:
    if not skip_install:
        pnpm = shutil.which("pnpm")
        if pnpm is None and not dry_run:
            print("pnpm 不在 PATH 上；先安装 pnpm 9+（packageManager 见 frontend/package.json）",
                  file=sys.stderr)
            return 2
        install = ["pnpm", "install"]
        if (FRONTEND / "pnpm-lock.yaml").is_file():
            install.append("--frozen-lockfile")
        # Windows installs pnpm as a .cmd shim: CreateProcess cannot run that
        # directly, so these two commands need the shell there.
        code = _run(install, FRONTEND, dry_run=dry_run, shell=os.name == "nt")
        if code != 0:
            return code
    return _run(["pnpm", "build"], FRONTEND, dry_run=dry_run, shell=os.name == "nt")


def _verify_dist() -> list[str]:
    problems: list[str] = []
    if not (DIST / "index.html").is_file():
        problems.append(f"missing {DIST / 'index.html'} (run pnpm build)")
    manifest = DIST / ".vite" / "manifest.json"
    if not manifest.is_file():
        problems.append(f"missing {manifest}")
    else:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"manifest is not JSON: {exc}")
        else:
            webp = [key for key in data if key.endswith(".webp")]
            if len(webp) != EXPECTED_CARD_FACES:
                problems.append(
                    f"manifest has {len(webp)} card faces, expected {EXPECTED_CARD_FACES}"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ops/build.py", description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the plan only")
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--skip-install", action="store_true",
                        help="reuse frontend/node_modules")
    args = parser.parse_args(argv)

    print(f"# release root: {ROOT}")
    if not args.frontend_only:
        code = _install_backend(args.dry_run)
        if code != 0:
            return code
    if not args.backend_only:
        code = _build_frontend(args.dry_run, args.skip_install)
        if code != 0:
            return code

    if args.dry_run:
        print(f"# verify: {DIST / 'index.html'}, {DIST / '.vite' / 'manifest.json'}, "
              f"{EXPECTED_CARD_FACES} card faces")
        print("# dry-run: nothing was installed or built")
        return 0

    problems = _verify_dist()
    if problems:
        for problem in problems:
            print(f"build verification failed: {problem}", file=sys.stderr)
        return 1
    print(f"# build ok: {DIST} ({EXPECTED_CARD_FACES} card faces)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())