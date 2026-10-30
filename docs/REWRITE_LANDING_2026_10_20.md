# 重写落地（Phase 5，2026-10-20）

> 票 #30 的交付说明。旧实现已从仓库删除；这里是新架构的"从哪看、怎么跑、门禁是什么、
> 出问题怎么回滚、还剩什么"的唯一入口。历史文档保留在 `docs/`，但只作考古。

---

## 1. 架构

```
浏览器（Vue 3 SPA, frontend/dist）
   │  socket.io（对局/大厅/观战/聊天）        HTTP（账号/排行/回放/公告/健康）
   ▼                                            ▼
uvicorn ── FastAPI app（backend/src/battleship/main.py）
   │              │
   │              ├── realtime/  python-socketio handler（61 入站 / 89 出站）
   │              ├── http/      REST 路由 + SQLAlchemy 会话 + SPA/静态托管
   │              ├── services/  用例编排（结算=单事务）
   │              ├── domain/    纯规则（无框架、无数据库）
   │              └── repositories/  唯一 SQL 位置
   ▼
SQLite（WAL，Alembic 版本化，21 张业务表 + 索引 + 视图）
```

- **运行时只有一份应用**：`uvicorn battleship.main:app` 以字符串目标导入，避免
  "`__main__` 与模块各建一份"的历史双实例坑。
- **前后端同源**：Vite 构建产物由同一个 ASGI 应用托管（`/assets` 内容哈希 + 一年
  immutable，页面 `no-cache`），没有第二个静态服务器。
- **没有事件循环补丁**：后台任务（掉线宽限、连锁/回合超时）是 asyncio 定时任务，
  房间销毁时取消。
- **只有一个栈**：`/legacy`、`BACKEND_STACK`、`FRONTEND_MODE=legacy`、
  `ARENA_SCREENS_*` 全部移除；残留 env 启动即失败（D30）。

---

## 2. 目录

```
backend/
  pyproject.toml           依赖（fastapi/uvicorn/python-socketio/pydantic/sqlalchemy/alembic/werkzeug）
  alembic.ini  migrations/ 首个 revision = 0001_initial_schema
  src/battleship/
    main.py                组合根：配置 → 日志 → 路由 → SPA → Socket.IO ASGI
    config.py              Pydantic Settings；SECRET_KEY 必填，缺失即失败
    contracts/             事件清单、Pydantic 模型、JSON Schema 导出
    domain/                对局、布船、魔法/连锁、AI、反作弊、匹配、成长、社交、观战
    services/              用例编排与事务边界
    repositories/           SQLAlchemy 模型、UoW、迁移与 schema 校验
    realtime/              Socket.IO server/handlers/emitter/identity/timers
    http/                  路由、会话、错误体、SPA 托管、限流
    infra/                 配置落地、结构化日志、指标、健康检查、限流
frontend/
  public/card_faces/       48 张卡面（Vite 构建期打包成内容哈希资产）
  src/screens/             11 屏（start/placement/rps/game/lobby/leaderboard/profile/
                           settings/replay/spectate/game-over）
  src/stores/              Pinia（game/home/lobby/match/placement/rps/result/replay/settings/...）
  src/realtime/, src/socket/   typed socket 客户端与生成的事件类型
  src/router/index.ts      11 条冻结路由
  src/styles/              tokens/base/components/screens
ops/
  build.py                 后端安装 + 前端构建 + 产物校验（48 卡面）
  migrate.py               Alembic + 备份 + 校验（systemd ExecStartPre）
  healthcheck.py           /health 轮询
  rollback.py              5 分钟回滚（备份恢复 + 切 commit/release + 健康检查）
  run_stack.py             本地一键起全栈（fail-fast）
  systemd/battleship.service, deploy.env.example, README.md
static/avatars/            唯一的运行期用户数据（头像，冻结 URL /static/avatars/...）
docs/, docs/adr/           设计/决策；历史文档保留
```

被删除（Phase 5）：旧后端全部根模块与启动脚本、旧 `requirements.txt`、`templates/`、
`static/` 下的旧前端资产（`static/card_faces` 已迁入 `frontend/public`）、仓内
`tests/` 与 `tools/`（仓外 `battleship-verify` 有对照副本）、以及重复的根
`changelog.py`（公告现在只有后端一份真源）。

---

## 3. 契约

**HTTP**：49 条冻结客户端路由（`backend/src/battleship/http/routes.py` 的
`LEGACY_ROUTES`，名字是历史资产）+ 新栈附加的 health/metrics/contracts/docs +
SPA 入口（`GET /` 与 catch-all）。`/legacy` 不再注册（404）；`/lobby`、
`/leaderboard` 等由 SPA catch-all 服务。

**Socket.IO**：入站 61（47 普通 + 14 调试，调试事件受 `ENABLE_TEST_EVENTS` 门控）；
出站 89（82 字面量 + 7 个参数化：`friend_request/accepted/invite/message`、
`recent_opponent`、`spectate_joined/left`）。ack 形如 `43<ackId><JSON>`，没有长度位。

**身份**：匹配房座位 key = 入队 sid；真实 user_id 在 `Player.user_id`；客户端用服务端
下发的 `player_id`。观战只进 `spectate:<room_id>`，不写进 `room.players`。

**错误体**：已录制路由保持旧形状 `{"error": "..."}`（D19）；`POST /login(JSON)`、
`POST /register(JSON)`、`GET /api/profile(401)`、`/api/change_password` 仍是结构化
`{"error":{code,message,field}}`（D26，历史遗留，未收录在录制样本里）。

**数据**：SQLite/WAL；Alembic 版本表 `alembic_version`；结算（对局 + 回放 + 用户统计/
段位/经验）在同一事务提交（D12）。迁移前 SQLite 在线备份，失败自动恢复。

**前端**：11 条冻结路由；`data-testid` 是门禁契约；没有 `window.gameState`；
测试钩子只在 test 构建注入；卡面从 `frontend/public/card_faces` 在构建期 import，
缺图返回 `null`（卡片退化无美术层）。

**契约产物**：`contracts/export_schema.py` 可导出 JSON Schema 与
`frontend/src/socket/events.gen.ts`；`frontend/scripts/check-contract.mjs` 在
`pnpm build` 前校验 `CONTRACT_SCHEMA_HASH`。

---

## 4. 门禁

测试资产不入仓（D4）；门禁都对**集成分支工作区**跑（D7）。

| 门禁 | 命令 | 覆盖 |
| --- | --- | --- |
| Phase 5 收尾 | `pytest cases/30-cleanup` | 旧文件/旧导入消失、单栈冷启动、路由表、48 卡面、ops dry-run、文档与公告 |
| 后端 | `pytest cases/4`–`19` | 组合根、数据层、鉴权、房间、布船、对局、魔法、连锁、AI、大厅、成长、排位、观战、回放、HTTP |
| 逐屏 | `pytest cases/21`–`28`、`31`、`33` | 壳与每屏静态/行为契约 |
| 浏览器 | `tools/web/run_all.py` | 23 个 `data-testid` 工具 + D33 截图指纹基线 |

`SKIP` 不算绿，当前允许的归因只有 rank-help / room（collection 已由 overlay + review-fixes 工具覆盖）。

Phase 5 记录的证据（2026-10-20，impl/30-cleanup @ d907b1e + 本票改动）：

- `cases/30-cleanup`：**229 passed**（含真实 Chromium 冷启动冒烟、`/legacy` 404、
  旧 cookie 一次性重登提示、48 张 webp 进 manifest/资产、ops dry-run 与真实迁移备份）；
- 六屏回归 `cases/21`–`28`、`31`、`33`：全绿（21:11 / 22:8 / 23:10 / 24:8 /
  25:12 / 26:10 / 27:10 / 28:13 / 31:20 / 33:5）；
- 后端抽样 `cases/4`、`6`、`7`、`9`、`14`、`17`、`18`、`19`：全绿
  （27 / 26 / 16 / 37 / 26 / 39 / 21 / 25）；
- `tools/web/run_all.py`：**20 PASS / 2 SKIP / 0 FAIL**；SKIP 为 `rank-help`
  （help 屏未迁移）与 `cplus-screens`（room/collection 归因），
  `cplus-path` 双浏览器全链路通过。
- 公告是首页可见内容，改了它就让 `layout` / `changelog` / `wallpaper` 的截图基线
  发生**真实**变化；按 D33 只重录这四处指纹基线（home、layout-start、changelog、
  wallpaper-settings），其余屏未动。

### 2026-10-20 两轴审查修复的门禁（本批）

- **新增仓外套件** `cases/review-fixes`：**34 passed**。覆盖单一实现（AST 全仓
  唯一 def + 重导出同一对象 + 行为表）、`/api/home_stats` 与 `lobby_state` 同
  口径且失败必须带日志、三个占位 router 删除、14 个 `test_*` 事件逐个过真
  socket 与门禁、`window.__BOOT__` 注入/幂等/契约 hash、回放
  phase/round/chain 记录器、恢复的分享包、11 条冻结路由未被 overlay 偷偷
  新增。
- **新增浏览器工具** `tools/web/review-fixes.mjs`（`run_all.py` 现为 23 个
  工具）：**49 checks PASS**。真实 Chromium + 真实 Socket.IO：拦掉两个计数
  API 后首页仍用 `__BOOT__` 渲染、真实双人对局触发匹配成功 overlay（5 秒倒
  计时 + 缺字段占位 + 跳布船，无新路由）、图鉴 50 张按 18/18/14 分批 + 按类
  型分组 + 搜索、真实本机壁纸的应用/暂停/取消与 localStorage、真实对局
  （含一张魔法卡）的回放顶栏 phase/大回合/连锁。
- **全量回归**（本批逐套复跑，全部 exit 0）：
  - `cases/4`–`19`：27 / 45(1 skip) / 26 / 16 / 23 / 37 / 44 / 33 / 29 /
    30 / 26 / 32 / 62 / 39 / 21 / 25；
  - `cases/21`–`28`、`31`、`33`：11 / 8 / 10 / 8 / 12 / 10 / 10 / 13 /
    20 / 5；
  - `cases/30-cleanup`：**225 passed**；
  - `tools/web/run_all.py`：**21 PASS / 2 SKIP / 0 FAIL**（SKIP = `rank-help`
    与 `cplus-screens` 的 room 归因）。
- **重录的指纹基线（仅真实变化处，D33）**：`home-desktop/laptop/mobile/
  signed-in`（首页新增图鉴入口 + 新公告）、`replay-desktop/mobile`（顶栏新增
  phase/大回合/连锁）、`layout-start-desktop` 与 `changelog-home-desktop`
  （同一批首页改动）。其余屏未动。
- **构建/类型**：`pnpm typecheck`、`pnpm build`、`pnpm build:test` 均 exit 0；
  `frontend/scripts/sync-card-data.mjs` 在构建期校验 50/48 卡表计数。

### 旧栈 pytest 基线（为什么门禁被重定）

spec 的验收门禁写着"旧栈 pytest 基线（2395 条）"，但那个数字是 Phase 0 的
历史记录，不是当前可复算的值：

- `cases/3-baseline` 是对**旧栈工作树**跑的旧测试；当前树没有 `server.py`/
  `api.py`/`db.py`，这些用例按定义不可移植（它们 `import server`、断言源码
  字符串）。
- 据 #3 实测：旧栈工作树**当前树 999 passed**；`6317877^`（删除旧实现前的
  最后一个提交）能收集到 **2625** 条；**2395 是历史快照值**，既不是 999 也
  不是 2625。三条数字互相不可替代，任何一条都不能当"当前门禁"。
- 因此门禁重定为：仓外 `cases/review-fixes` + `cases/4`–`19`（新栈行为）
  + 六屏浏览器门禁 + `tools/web/run_all`（含指纹）。旧栈基线只保留为
  "同一输入的行为对照"（`fixtures/`），不再作为 CI 红线。

**已退役的门禁**：`cases/20-gate` 的"迁移窗口"断言（旧页面仍 200、双栈并行；
`test_migration_window.py` 已显式 skip）随旧实现删除而失效；`cases/3-baseline`
的旧栈 pytest 只对旧栈工作树有效。它们的价值已由上面四类门禁接管，不再作为红线。

---

## 5. 回滚

`ops/rollback.py` 的固定顺序：校验备份（`PRAGMA integrity_check`）与目标 commit/
release → 停服 → 当前库安全副本 → 恢复备份 → 切 commit（`git checkout --detach`）
或 release 软链 → 重建前端 → 启动并轮询 `/health`。预算 5 分钟，超时打印 WARNING。

- 部署顺序：`ops/build.py` → `ops/migrate.py` → `systemctl restart battleship` →
  `ops/healthcheck.py`。
- systemd：`ops/systemd/battleship.service`（uvicorn，`EnvironmentFile`，
  `ExecStartPre` 跑迁移）。
- 跨 Phase 5 回滚（回到旧栈）必须保留一个旧 release 目录并用 `--release-dir`：
  旧提交里没有新栈的构建脚本。runbook 见 `ops/README.md`。
- 失败路径：脚本以 3 退出并打印"安全副本 + 上一个 commit + 启动命令"。

---

## 6. 残余与已知偏差

> 2026-10-20 两轴 code-review 修复后的状态。已关闭的条目保留结论，仍未处理的
> 写明"为什么保留"；没有"看情况"。

1. **动态壁纸：已关闭**。设置屏的壁纸区块恢复为真实壁纸库（扫描本机 → 应用 →
   播放/暂停 → 取消），`AppWallpaper` 在 SPA 内渲染 `<video>/<img>` 背景，选择
   存在 `localStorage`（键 `battleship.wallpaper.v1`）。扫描仍只对本机回环开放
   （沿用旧栈的隐私边界），远端浏览器看到的是服务端给出的原因，不是空白。
2. **帮助/段位说明屏：仍缺失**。11 条冻结路由里没有 help；这是 spec 的已知偏差，
   不是回归。**卡面图鉴（collection）已关闭**：做成从首页/设置进入的 overlay
   （不新增路由），数据在构建期从后端卡表复制（单一来源），按速阶/类型分组、
   分批渲染。`tools/web` 仍按 room 归因 SKIP 整屏检查（overlay 由新的
   review-fixes 工具覆盖），collection 不再需要单独的归因。
3. **两份 `field_magic_name`：已关闭**。canonical 在 `domain/room/models.py`
   （兼容卡实例 / dict / 裸字符串），`magic/rules.py` 与 `magic/field.py` 只做
   import；`action_wait_reason` 同样收敛到 `domain/battle.py`。仓外
   `cases/review-fixes` 用 AST 断言"全仓只有一个 def"，并断言重导出是同一个对象。
4. **错误体双轨（D19 / D26）：保留，且这是对 spec 用户故事 45 的有意偏离**。
   用户故事 45 要求"校验失败返回结构化错误（字段 + 原因）"，但已录制的线上客户端
   按 `{"error": "..."}` 解析；把 49 条冻结路由改成结构化体会让旧 toast 显示
   `[object Object]`，属于"看起来更规范、用户看到坏消息"的破坏性变更。因此录制过
   的路由维持旧形状（D19），只有 4 条未录制路由（login/register JSON、profile 401、
   change_password）用结构化体（D26）。偏离的验收条件：新形状只出现在没有录制样本
   的路径上，且错误文本仍可读。
5. **观战/回放历史差异：部分关闭**。回放的 phase / 大回合 / 连锁时间线已在服务端
   记录器补齐并在回放屏顶栏展示（步骤上稀疏携带，payload 额外导出
   `phases/rounds/chains`，旧字段不变）；"观战结束不自动跳大厅""回放卡面只显示
   卡名"仍是 D31 的已知偏差。
6. **旧录制基线**：`fixtures/contract` 的对局录制没有连锁帧，AI 样本对 RNG 敏感，
   掉线宽限是墙钟；`cases/20-gate` 的逐事件比对不再是 Phase 5 红线。
7. **头像仍放在 `static/avatars`**：这是玩家数据不是旧前端资产，保留同一冻结 URL，
   避免历史名片图片 404；其余 `static/` 内容已删除。
8. **卡面与卡表都不做运行期拷贝**：`frontend/vite.config.ts` 关闭 `publicDir`，
   由 `import.meta.glob` 产出内容哈希资产；`pnpm dev` 不再是"起全栈"的入口，
   本地统一走 `ops/run_stack.py`。图鉴卡表走同一路线：
   `frontend/scripts/sync-card-data.mjs` 在构建期从后端 `magic_card.json` 复制并
   校验 50/48 计数，失败即中断构建，不手工维护第二份。
9. **玩家公告**：本批追加一条（匹配成功倒计时 / 图鉴 / 动态壁纸）；旧 cookie 的
   提示仍由 SPA 入口按一次性语义注入（不依赖已删除的模板）。
10. **两个已关闭的实现问题**：`window.__BOOT__` 已按 spec 实现（服务端在 SPA
    index.html 注入身份 / 在线计数 / 契约 hash / 构建号，幂等且模板字节按
    (path, mtime, size) 缓存；前端优先读它，缺失或降级时回退 API）；14 个
    `test_*` 调试事件全部实现并仍受 `ENABLE_TEST_EVENTS` + 白名单门禁。
    `.trae-html-share-packages/`（不在 spec 删除清单里）已从删除前提交恢复。
