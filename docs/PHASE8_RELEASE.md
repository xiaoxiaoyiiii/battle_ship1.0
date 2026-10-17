# Phase 8 发布与回滚手册

本手册供获得**合并与部署授权后**的发布操作使用。当前长期 PR 仍是草稿，本文不代表已经发布。

## 发布门禁

1. PR 的 Windows CI 通过；在目标提交运行 `python -m pytest -q`、`node tools/dom_contract_check.mjs` 和全部 `static/*.js` 的 `node --check`。
2. 配置 `SECRET_KEY`（至少 32 字符、固定且不入库）、`CORS_ORIGINS`（明确列出实际来源）、`ENABLE_TEST_EVENTS=0`、`FLASK_DEBUG=0`。生产日志默认 `INFO`，可用 `LOG_LEVEL` 调整。
3. 在原服务仍可用时执行 `python tools/release_preflight.py --db data/battleship.db --backup-to <独立备份目录>/<版本>.db --migration-copy <临时目录>/<版本>-migration.db`。两个目标路径必须事先不存在。工具会核对配置、数据库可读性与完整性，用 SQLite backup API 制作含 WAL 已提交事务的快照，并在副本上试跑当前迁移。备份需保存在发布目录之外。
4. 记录发布前的 Git 提交、数据库备份路径与 `systemctl status battleship`。确认没有未保存的服务器本地代码修改。用新的发布目录检出已批准的提交，不覆盖现有运行目录；保留上一版本目录与备份供回滚。
5. 将服务指向新发布目录，执行 `systemctl daemon-reload && systemctl restart battleship`。检查 `systemctl is-active battleship`、`journalctl -u battleship -n 100 --no-pager`、`curl -fsS http://127.0.0.1:5000/health/live` 与 `/health/ready`，再验证首页、Socket 建连、休闲对局、连锁和回放。

`/health/live` 只表示 HTTP 进程能响应；`/health/ready` 只读检查 SQLite `users` 表，失败时返回 503。两者均不公开数据库路径或密钥。监控应分别看两个端点，并观察进程重启、Socket 断连、数据库错误与日志中的异常计数。

## 回滚

1. 如果启动、就绪或真实对局验收失败，立即停止新版本，切回记录的上一版本目录并重启服务；再次核对两个健康端点与 Socket 建连。
2. 数据库若只做了兼容性迁移，先核对旧版本能否读取当前库。**只有确需恢复且接受备份之后数据会丢失时**，停服后将一致性备份复制到数据库位置，再启动旧版本。恢复前另存当前库以供事故分析。
3. 回滚完成后记录失败提交、告警和恢复结果。不要对运行目录执行 `git reset --hard`，也不要在服务运行时直接复制 `.db` 文件来“备份” WAL 数据库。

## 边界

当前服务仍使用单进程 eventlet 与 SQLite。数据库备份和迁移副本验证已实现，自动蓝绿切换、线上监控系统和数据库写入兼容性需要在真实环境按发布窗口另行验收。发布或合并仍需用户分别授权。
