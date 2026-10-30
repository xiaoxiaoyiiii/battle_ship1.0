#!/usr/bin/env python
"""Poll the running stack's health endpoint; exit 0 only on `status == "ok"`.

    ops/healthcheck.py --url http://127.0.0.1:5000/health --timeout 30

Used by the deploy runbook after `systemctl restart battleship` and by the
5-minute rollback script.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime


def _probe(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            body = response.read(8000).decode("utf-8", errors="replace")
            if response.status != 200:
                return False, f"HTTP {response.status}: {body[:200]}"
    except Exception as error:  # noqa: BLE001 - reported, never raised
        return False, f"{type(error).__name__}: {error}"
    try:
        payload = json.loads(body)
    except ValueError:
        return False, f"non-JSON body: {body[:200]}"
    if payload.get("status") != "ok":
        return False, f"status={payload.get('status')!r} checks={payload.get('checks')}"
    checks = payload.get("checks") or []
    summary = ", ".join(f"{item.get('name')}={item.get('status')}" for item in checks)
    return True, f"status ok ({summary})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ops/healthcheck.py", description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5000/health")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args(argv)

    deadline = time.monotonic() + args.timeout
    last = "not checked"
    while True:
        ok, last = _probe(args.url)
        if ok:
            print(f"{datetime.now().isoformat(timespec='seconds')} {args.url}: {last}")
            return 0
        if time.monotonic() >= deadline:
            break
        time.sleep(max(0.1, args.interval))
    print(f"health check FAILED after {args.timeout:.0f}s: {args.url}: {last}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
