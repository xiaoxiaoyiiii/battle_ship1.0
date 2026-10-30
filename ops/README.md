# ops/ — build, migrate, deploy, roll back

Phase 5 has a single stack: **FastAPI + python-socketio + SQLAlchemy/Alembic**,
serving the **Vue 3 build** from `frontend/dist` on the same ASGI app. There is
no legacy stack, no `/legacy` and no `BACKEND_STACK` switch; a leftover value
fails fast instead of silently running the wrong thing.

## Local: one command for the full stack

```powershell
# builds nothing if dist/ exists; migrates a dev database; serves on 5450
python ops/build.py --frontend-only      # once, or when the frontend changes
python ops/run_stack.py --port 5450 --db .tmp/dev.db
```

`ops/run_stack.py` fails closed when:

* `BACKEND_STACK` is set to anything except `rewrite` (the variable is gone);
* `frontend/dist/index.html` is missing (`--build` builds it first);
* the migration fails.

`FRONTEND_MODE=legacy` is rejected by the backend settings at startup, naming
the variable, because the legacy frontend no longer exists.

## Deploy order (production)

```
ops/build.py        # 1. pip install -e backend; pnpm install/build; verify dist
ops/migrate.py      # 2. Alembic upgrade + pre-migration backup + verification
systemctl restart battleship
ops/healthcheck.py  # 3. require {"status":"ok"}
```

`systemctl` runs the unit in [systemd/battleship.service](systemd/battleship.service):
`ExecStartPre` is the migration, `ExecStart` is uvicorn, and every value comes
from `/etc/battleship/battleship.env` (template: [deploy.env.example](deploy.env.example)).
`SECRET_KEY` is required: a missing/blank value aborts before the port binds.

### ops/build.py

```powershell
python ops/build.py --dry-run          # print the plan, change nothing
python ops/build.py                    # install backend deps + build the frontend
python ops/build.py --frontend-only    # skip the pip step
python ops/build.py --skip-install     # reuse frontend/node_modules
```

Verifies `frontend/dist/index.html`, `.vite/manifest.json` and all 48 card
faces (bundled from `frontend/public/card_faces` by Vite).

### ops/migrate.py

```powershell
python ops/migrate.py --dry-run --database <db>   # revision plan, no writes
python ops/migrate.py --database <db>             # backup -> upgrade -> verify
python ops/migrate.py --verify-only --database <db>
```

Backup is a SQLite online copy next to the database
(`<db>.backup-<UTC stamp>-<pid>-<ns>.db`); a failed upgrade restores it and
exits 2. A first-time migration on a missing file creates the schema (and removes
a half-built file on failure).

### Health

```powershell
python ops/healthcheck.py --url http://127.0.0.1:5000/health --timeout 30
```

Exit 0 only when the body says `{"status":"ok", ...}`; it prints the individual
checks (config / database / contracts / socketio). Endpoints: `/health`,
`/healthz`, `/api/health`, plus `/metrics` (counters, gauges, latency, error
rate).

## 5 分钟回滚 runbook

Rollback = previous release/commit + the database backup taken before the bad
migration. `ops/rollback.py` performs the whole sequence and refuses to touch the
service until both the backup (integrity checked) and the target exist.

```powershell
# dry-run: validates backup + target, prints the plan (stop -> restore -> checkout -> build -> health)
python ops/rollback.py --dry-run `
    --database /var/lib/battleship/battleship.db `
    --backup   /var/lib/battleship/battleship.db.backup-20261020T031500Z-....db `
    --to       <previous commit or tag>

# real: systemd deployment (defaults: systemctl stop/restart battleship)
sudo -u battleship /opt/battleship/.venv/bin/python /opt/battleship/ops/rollback.py `
    --database /var/lib/battleship/battleship.db --backup <backup> --to <commit>
```

| 分钟 | 动作 |
| --- | --- |
| 0:00 | 运行 `ops/rollback.py`（它会先校验备份与目标，再停服务） |
| 0:30 | 停服 + 当前库安全副本 + 恢复备份（典型 < 10 s） |
| 1:00 | `git checkout --detach <commit>`（或 `--release-dir` 切软链）+ 前端重建 |
| 2:00 | `systemctl restart battleship`；`ops/healthcheck.py` 轮询直到 ok |
| 3:00 | 冒烟：登录一次、开一局布船、打开一局回放 |
| 4:00 | 在频道公告回滚原因，把备份路径写进票 |
| 5:00 | 交接：当前 commit / release、备份路径、原因 |

失败时脚本以 3 退出并打印手动恢复命令（安全副本 + 上一个 commit）。超过
300 秒会打印 WARNING 并以 4 退出。跨 Phase 5 回滚（回到旧栈）请保留一个旧
release 目录并用 `--release-dir`：旧提交里没有 `ops/build.py`。

## Environment

All variables keep the names the old stack used. `SECRET_KEY` is the only
required one; see [deploy.env.example](deploy.env.example).

| Variable | Default | Notes |
| --- | --- | --- |
| `SECRET_KEY` | — | required; session signing |
| `HOST` / `PORT` | `0.0.0.0` / `5000` | bind address |
| `BATTLESHIP_DB_PATH` | `./battleship.db` | SQLite (WAL) |
| `CORS_ORIGINS` | localhost:5000 | comma separated |
| `TURN_TIMEOUT_SECONDS` | `90` | 0 disables the watchdog |
| `CHAIN_DISPLAY_DELAY_SECONDS` | `1.2` | 0 in tests/replays |
| `ENABLE_TEST_EVENTS` | `0` | debug socket events, never in production |
| `FRONTEND_DIST` | `frontend/dist` | optional build location |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `1` | structured logs |

`BACKEND_STACK`, `LEGACY_WORKTREE`, `FRONTEND_MODE=legacy`, `ARENA_SCREENS_MODE`
and `ARENA_SCREEN_LIST` belonged to the migration window and are rejected.

## Contract artifact

```powershell
$env:PYTHONPATH="backend/src"
python -m battleship.contracts.export_schema --out ..\contracts.schema.json
python -m battleship.contracts.export_schema --check ..\contracts.schema.json
python -m battleship.contracts.export_schema --format ts --out frontend\src\socket\events.gen.ts
```

The TS artifact embeds `CONTRACT_SCHEMA_HASH`; regenerate it whenever contracts
change (`frontend/scripts/check-contract.mjs` fails the build otherwise).

## Gate pointers (out of repository, DECISIONS D4/D7)

Behaviour gates never live in this repository:

* `D:/develop/battleship-verify/cases/30-cleanup` — this ticket: deletion,
  single-stack cold start, route table, build, ops, docs, announcement;
* `cases/4`–`19` — backend HTTP/domain/contract suites;
* `cases/21`–`33` — per-screen SPA suites and the recalibrated browser tools;
* `tools/web/run_all.py` — 22 `data-testid` browser gates (default worktree:
  the integration checkout).

Run them with the shared interpreter and an isolated database per run:

```powershell
cd D:/develop/battleship-verify
$env:PYTHONIOENCODING = 'utf-8'
.venv/Scripts/python.exe -m pytest cases/30-cleanup -q
.venv/Scripts/python.exe tools/web/run_all.py --worktree <worktree>
```
