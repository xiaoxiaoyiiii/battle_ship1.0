# 前端壳（Vue 3 + Vite）约定与接线（票 #21）

> 适用：`frontend/` 目录、`data-testid` 选择器契约、静态托管开关。
> 本票只交付**壳**：11 屏占位、路由、Pinia 状态镜像、typed socket、错误边界、构建产物与托管接线。
> 各屏业务在 #22–#28；总切换在 #20。

## 1. 运行

```powershell
cd frontend
pnpm install
pnpm dev            # Vite 开发服务器（/api 与 /socket.io 代理到 127.0.0.1:5000）
pnpm typecheck      # vue-tsc --noEmit
pnpm build          # 生产构建 -> frontend/dist（钩子被编译删除）
pnpm build:test     # 测试构建 -> frontend/dist-test（注入 __BS_TEST__）
```

`pnpm build` 先跑 `scripts/check-contract.mjs`：它用后端 `export_schema --print-hash` 取权威契约哈希，
与 `src/socket/events.gen.ts` 里的 `CONTRACT_SCHEMA_HASH` 比对，不一致直接失败（退出码 1）。
解释器查找顺序：`BATTLESHIP_PYTHON` → 本仓 `.venv` → 共享 `D:/develop/battleship-verify/.venv` → PATH 的 `python`；
都找不到时**故意失败**（不允许发布未校验的契约）。

契约变更后重新生成（不要手改 `events.gen.ts`）：

```powershell
$env:PYTHONPATH = "$PWD/../backend/src"
python -m battleship.contracts.export_schema --format ts --out frontend/src/socket/events.gen.ts
```

## 2. 路由（名称已冻结，不新增）

| 路径 | 路由名 | 屏 | 占位组件 |
| --- | --- | --- | --- |
| `/` | start | 首页 | `StartScreen.vue` |
| `/placement` | placement | 布船 | `PlacementScreen.vue` |
| `/rps` | rps | 猜拳 | `RpsScreen.vue` |
| `/game` | game | 对局 | `GameScreen.vue` |
| `/lobby` | lobby | 大厅 | `LobbyScreen.vue` |
| `/leaderboard` | leaderboard | 排行 | `LeaderboardScreen.vue` |
| `/profile` | profile | 档案 | `ProfileScreen.vue` |
| `/settings` | settings | 设置 | `SettingsScreen.vue` |
| `/replay` | replay | 回放 | `ReplayScreen.vue` |
| `/spectate` | spectate | 观战 | `SpectateScreen.vue` |
| `/game-over` | game-over | 结算 | `GameOverScreen.vue` |

* 全部路由**懒加载**（每屏一个 chunk），首屏不下载各屏业务代码。
* 未知路径由 `/:pathMatch(.*)*` **重定向**到 `/`（没有新增 `not-found` 路由名）。
* 路由切换有明确的加载态：`router.beforeEach` 置位、`afterEach/onError` 清位；壳渲染
  `[data-testid="route-loading"]`，根节点同时带 `data-route-loading="true|false"`。

## 3. `data-testid` 选择器契约

**无头工具只认 `data-testid`。DOM id 仅供 aria/锚点，不是工具契约，不要新增被工具引用的 id。**

命名规则：

| 层级 | 规则 | 示例 |
| --- | --- | --- |
| 屏根 | `screen-<route>`，同屏恰好一个 | `screen-game`、`screen-game-over` |
| 屏内交互/展示 | `<route>-<role>` | `game-end-turn`、`lobby-refresh`、`game-over-replay` |
| 壳 | `app-*` | `app-shell`、`app-nav`、`app-screen-boundary`、`app-screen-error` |
| 导航 | `nav-<route>` | `nav-lobby`、`nav-game-over` |
| 加载/错误 | `route-loading`、`app-screen-error-retry` | — |

规则细节：

1. 屏根还带 `data-screen="<route>"`，用于“当前只有一屏挂载”的断言（`[data-testid^="screen-"][data-screen]`）。
2. 同一 testid 在一个屏内只能出现一次；列表项用 `<route>-<role>-<stable-id>`（房间号/座位等稳定键，不用数组下标）。
3. 交互元素（button/input/可点卡片）必须有 testid；纯装饰不加。
4. 占位组件已经给出示例：`screen-start` + `start-primary-action`、`screen-game` + `game-primary-action` …
   业务屏迁移时沿用同一规则，不要求保留旧 DOM id。

## 4. Pinia：gameState 显式镜像

* `src/stores/gameStateSchema.ts` 是**唯一**的状态形状定义：45 个 `RoomSync` 键 + 2 个仅
  `game_state` 出现的键（`winner_card` / `loser_cards`），每个字段都有 `type/nullable/default/note`。
* `RoomSync` 键清单由 contracts 生成到 `events.gen.ts` 的 `ROOM_SYNC_FIELDS`；类型级 parity 守卫让
  `vue-tsc` 在字段增删/改名时失败（前后端必须同步）。
* `defaultGameState()` 按 schema 逐字段克隆默认值（数组/对象不共享引用）；`useGameStore` 的初始状态即默认值。
* `applyServerState(payload)` 只接收 schema 内字段；未知键进入 `unknownFields` 并在 dev 控制台告警，
  不再有 `window.gameState` 这类裸全局。
* 仓外门禁会通过测试构建的 `__BS_TEST__` 读取 schema 字段、默认值与服务端哈希；生产构建没有这个入口。

## 5. Typed Socket.IO 客户端

* `src/socket/client.ts`：`createTypedSocket()` 的 `emitEvent`/`on` 只接受 `events.gen.ts` 里的
  61 个入站 / 89 个出站事件名（82 字面量 + 7 参数化，DECISIONS D21）。
* ack 超时 reject；`checkContract()` 在连接时拉 `GET /api/contracts/schema` 并比对哈希，
  不一致只上报（`onContractMismatch` + console），不炸壳；**构建期**不一致才硬失败。
* 连接带 `withCredentials`，沿用会话 Cookie。

## 6. 构建产物与后端托管

* 产物：`frontend/dist`（生产）/ `frontend/dist-test`（测试），文件名含内容哈希
  （`assets/<name>-<hash>.js`），同时输出 `.vite/manifest.json`；入口/动态 chunk 均可从 manifest 解析。
* 后端开关（默认不变）：

  | 环境变量 | 默认 | 作用 |
  | --- | --- | --- |
  | `FRONTEND_MODE` | `legacy` | `spa` = 由新壳接管页面入口 |
  | `FRONTEND_DIST` | 空 | 覆盖 dist 目录（相对路径按仓库根解析） |

* `spa` 模式（`backend/src/battleship/http/routers/frontend.py`）：
  * `/assets/*` 静态托管，`Cache-Control: public, max-age=31536000, immutable`；
  * `/` 与任意非保留深链返回 `index.html`（`no-cache`），并带 `X-Frontend-Build`（manifest 字节 SHA-256 前 16 位）；
  * `/api/*`、`/socket.io`、`/static/*`、`/login|register|logout`、`/legacy` 等不落入 SPA 回退；
  * 带扩展名但不存在的路径返回 404，不返回 HTML；
  * 缺 dist 时**启动失败**并提示 `pnpm build`，不做静默回退。
* 不另起静态服务器进程；dist 挂在现有 ASGI app 上。切流动作归 #20。

## 7. 测试钩子（只在测试构建）

* 生产：`vite.config.ts` 把 `__BS_TEST_HOOKS__` 常量折叠为 `false`，测试入口、
  crash 注入器与 `__BS_TEST__` 全部被 tree-shake；仓外门禁扫描 `dist/assets/*.js` 断言不存在这些标记。
* 测试构建（`pnpm build:test`）暴露 `window.__BS_TEST__`：当前路由、加载历史、契约哈希、
  远端哈希读取、gameState schema/默认值、`crashNext(routeName)`。
* 错误边界：`ScreenBoundary.vue` 用 `onErrorCaptured` 包住 `<router-view>`；单屏 setup/render 抛错时
  只显示 `app-screen-error`，壳与导航仍可用，切换路由自动恢复。测试构建通过 slot 注入一个必抛错的
  `CrashProbe` 验证该路径。

## 8. 偏差与遗留

1. `window.__BOOT__` 启动数据未在本票实现（spec 提到，但 #21 验收未要求）；当前壳不依赖服务端注入变量。
2. 各屏业务、浮层、移动端布局、真实 socket 数据接线分别在 #22–#28。
3. `FRONTEND_MODE` 默认仍是 `legacy`：切流与回滚编排归 #20；本票只提供可用的托管接线。
4. 旧前端仍使用 DOM id；`data-testid` 只在新壳内建立，旧工具重标定在 Phase 0 之后逐屏进行。
