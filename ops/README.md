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
ops/build.py        # 1. 在独立 release 中准备依赖和前端
systemctl stop battleship  # 2. 必须成功；同时停止其他读写此库的进程
systemctl start battleship # 3. ExecStartPre 核验服务状态，再备份、迁移和校验
ops/healthcheck.py  # 4. require {"status":"ok"}
```

`systemctl` runs the unit in [systemd/battleship.service](systemd/battleship.service):
`ExecStartPre` is the migration, `ExecStart` is uvicorn, and every value comes
from `/etc/battleship/battleship.env` (template: [deploy.env.example](deploy.env.example)).
`SECRET_KEY` is required: a missing/blank value aborts before the port binds.

每一步成功后才能继续。生产数据库迁移和恢复均要求全部写入方停止，禁止在旧服务仍运行时手动迁移。
若直接更新正在运行的同一目录，应先停服再更新依赖与代码。旧 Flask 栈首次切换还须准备 Python 3.12、新服务入口和真实旧库路径，不能只拉取代码后重启。

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
python ops/migrate.py --database <db>             # 核验 battleship 停服后再迁移
python ops/migrate.py --service <name> --database <db>
python ops/migrate.py --offline --database <local-db> # 本地隔离库，操作者确认全部写入方停止
python ops/migrate.py --verify-only --database <db>
```

Backup is a SQLite online copy next to the database
(`<db>.backup-<UTC stamp>-<pid>-<ns>.db`); a failed upgrade restores it and
exits 2. A first-time migration on a missing file creates the schema (and removes
a half-built file on failure).

默认通过 systemd 检查服务已停止，无法查询、仍有主进程或正在退出时均拒绝迁移。
服务自身的 `ExecStartPre` 仅在旧进程已退出且 ControlPID 为本迁移进程时允许执行。
`--offline` 不提供生产在线迁移能力，也不能与另一个使用相同库的本地服务并行。
仓储层 `migrate_database()` 是离线操作原语，其他工具调用前也必须停止全部写入方。
直接运行 `python -m battleship.repositories.migrations` 同样须显式加 `--offline`；生产操作使用有服务状态检查的 `ops/migrate.py`。

### 首次开季与每日挑战内容

数据库迁移只创建表，不自动开季。正式开放入口前，通过管理员会话调用
`POST /api/admin/battle-pass/seed`，请求体为 `{"season_id":"deep-sea-1"}`。
缺省开始时间取首次成功请求的服务端时间，作为正式开服时刻；结束时间为其后 8 周，领奖截止为结束后 14 天。
相同 ID 重试会返回首次日期，不会延长赛季。初始化后核对 50 级、18,000 XP，以及真人结算和领取。
后续赛季须使用新的 ID；排位赛季结算规则独立于通行证配置。

每日挑战从 `DAILY_PUZZLES_PATH` 指定的私有 JSON 清单加载，仓库默认清单为空。
正式内容应放在静态目录之外，并让服务账户可读；上线前检查当天与后续日期覆盖、关卡审核结果。
本机生成的隐藏局面不能随前端构建公开发布。

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
sudo /opt/battleship/.venv/bin/python /opt/battleship/ops/rollback.py `
    --database /var/lib/battleship/battleship.db --backup <backup> --to <commit>
```

停服命令失败或 systemd 仍报告运行中时，回滚立即退出且不改数据库。`--service` 可指定实际服务名；自定义停止命令也必须停止该服务。启动命令失败同样返回失败，不以旧健康响应掩盖错误。

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

赛季与邮箱运营补充：`DEBUG_ADMIN_USER_IDS` 仅保留用户本人原有账号，不能填多个账号；测试事件在生产仍保持关闭。`ERROR_LOG_PATH` 保存登录、建房、结算、邮件等失败，默认 `.tmp/logs/errors.log`，生产示例使用 `/var/lib/battleship/logs/errors.log`。每周备份随服务启动，不另装定时器；`BACKUP_DIRECTORY` 默认是数据库同目录的 `backups/`，每 7 天生成 SQLite 一致性快照，保留最近四份，失败记日志后重试。服务账号须能写入日志和备份目录。

首季仍在正式开服时初始化，排位与通行证共用同一配置；下一季须由原受控赛季入口安排不重叠日期。本包不自动提前创建正式赛季。邮箱运营入口为账号菜单的「运营发信」，具体时效与软重置表见 [赛季邮箱运营说明](../docs/SEASON_MAILBOX_V1.md)。

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
