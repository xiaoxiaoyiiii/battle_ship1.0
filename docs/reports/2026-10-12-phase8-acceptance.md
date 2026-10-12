# Phase 8 前端模块化与生产交付验收

## 代码范围

- 将客户端初始状态迁至 `static/client_state.js`，Socket 连接与监听迁至 `static/client_socket.js`、`static/client_socket_events.js`，首页数据与渲染迁至 `static/home_panels.js`，卡牌目录查询迁至 `static/card_catalog.js`。原有卡牌数据仍由 `static/magic_cards.js` 提供。模板按依赖顺序加载，继续沿用浏览器经典脚本的共享作用域，未改变 Socket 事件格式。
- 增加 `/health/live` 与 `/health/ready`，后者只读检查 SQLite 关键表；增加发布前配置、完整性、备份与迁移副本预检。生产日志默认 `INFO`，调试和测试事件须显式关闭。
- 增加 PR CI、发布和回滚手册；更新因文件拆分而失效的源码守卫工具。

## 本地验收证据

- `Get-ChildItem static -Filter *.js | ForEach-Object { node --check $_.FullName }`：全部脚本语法通过。
- `node tools/dom_contract_check.mjs`：DOM 契约通过，3 项既有无害悬空引用仍为警告。
- `python -m pytest -q`：**1060 passed，1 warning**；警告为 Eventlet 弃用提示。
- 隔离库、端口 5188 的本地服务：`/health/live` 和 `/health/ready` 均返回 200。`/health/ready` 缺库返回 503 且不会建库，已有测试覆盖。
- Edge 浏览器：客户端状态、卡目录、首页渲染与 Socket 监听函数均加载；Socket 已连接；进入大厅后收到在线玩家状态。`node tools/codex_realcard_check.mjs --url http://127.0.0.1:5188/` 全部通过。
- `node tools/cplus_path_check.mjs --url http://127.0.0.1:5188/` 全部通过：双浏览器真实按钮走通首页→大厅→建房/加入→布船→开炮→结算→回放→首页，全程无 JS 异常。
- `python tools/release_preflight.py --db .tmp/phase8-smoke.db --backup-to .tmp/phase8-smoke-backup.db --migration-copy .tmp/phase8-smoke-migration.db`：配置、数据库完整性、WAL 一致性备份及迁移副本检查通过。另有子进程测试确认首次导入数据库模块不会迁移源库。

## 限制与回滚

- 本阶段没有合并或部署。前端仍使用共享全局作用域，`game.js` 仍承载大量对局界面和交互；这是保持现有接口的分步拆分，后续若改成 ES module 仍需单独迁移与浏览器门禁。
- 服务端早期阶段的一些领域新路径仍处于对照或旁路状态；因此本报告只证明 Phase 8 范围的本地验收，不能宣称全项目已完成线上切换。单进程 Eventlet 与 SQLite 的扩展边界仍在。
- 若当前 PR 的 Phase 8 改动导致问题，可在长期分支上 `git revert` 对应提交并重新运行回归；已发布版本的切换与数据库恢复按 `docs/PHASE8_RELEASE.md` 执行。数据库恢复会丢失备份后的写入，必须先停服并确认损失窗口。

## 下一入口

等待长期 PR 的审查与 CI；合并和部署分别由用户授权。发布窗口再验证真实生产环境的备份位置、服务重启、健康端点、Socket 建连和回滚演练。
