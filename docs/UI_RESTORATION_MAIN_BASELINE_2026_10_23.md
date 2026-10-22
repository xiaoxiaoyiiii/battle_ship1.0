# main 前端视觉回归（fork ← main）实施记录

- 任务标识：`FORK_MAIN_UI_RESTORATION_20261023_01`
- 分支：`feature/main-ui-restoration`（起点 `review/fork-cloud` @ `316c616bbad5caac2ca8bcd708e87d54243d10f7`）
- 视觉基准：`origin/main` 固定提交 `d16f706e61acb02a4ca7197cd2a92400c92c568d`
- 日期：2026-10-23

## 1. 目标与原则

用户判断「fork 前端整体不如 main」，但明确认可 fork 三件事要留下：

1. 卡牌不可用时的报错说明（限制原因 + 服务端拒绝反馈）。
2. 右下角的全局状态通知。
3. 主界面（首页）比较好看、比较容易点的排版。

因此本次不是「把 main 抄过来」，而是**保留 fork 的 Vue3 + TS + Pinia、后端协议与状态来源，只把 main 的视觉语言与可操作性迁回组件**：不复制 main 的 `game.js`、不退回整页渲染、不整页 iframe、不动数据库/卡牌规则/后端 API。

## 2. main 基准是怎么取的

只读 `git show d16f706:<path>` / `git ls-tree`，未切换、未修改 main 工作树：

| 读取对象 | 取值内容 |
| --- | --- |
| `templates/index.html`（1887 行） | 首页/对局页 DOM 次序、状态胶囊条、场地魔法条、右栏「连锁结算 + 卡牌详情 + 主 CTA + 计数」结构 |
| `static/style.css`（11142 行） | 浅色/深色两套设计令牌、竞技场预设（紫 `#7c5cf0` / 青 `#4ec8e0` / 金 `#c9a24c`）、棋盘面 `radial-gradient(120% 120% at 50% 0%,#1d2a55,#101733 70%)`、首页三栏 280/1fr/292 与 hero 卡尺寸 |
| `static/arena_screens.css`（3594 行） | 面板 12px 圆角 + 1px 描边无阴影、小标题 11px 字距 .14em、胶囊 999px、主行动紫渐变 + glow、次行动描边、分隔 1px 实线 |
| `docs/readme/01-home-live.png`、`04-game-live.png` | 实际观感基准：64px 顶栏、三栏首页、底部热门卡横条；对局页顶部胶囊 HUD + 全宽场地条 + 双 6×6 棋盘 + 右侧连锁/详情/CTA/计数 + 底部大卡手牌 |

## 3. main → fork 对照清单与落点

| main 元素 | fork 落点 | 批次 |
| --- | --- | --- |
| 深蓝底 + 顶部紫光 + 48px 网格 | `frontend/src/styles/main-ui.css` body 规则 | 1 |
| 64px 顶栏、紫色 active 下划线、32px 图标钮 | `main-ui.css` `.app-nav` / `.app-nav__link[aria-current]` / `.app-nav__icon` | 1 |
| 圆角/间距/字号/动效令牌 | `frontend/src/styles/tokens.css` 整份重写 | 1 |
| 主行动紫渐变按钮、次行动描边按钮 | `main-ui.css` `.button--primary/--ghost/--danger` | 1 |
| 右下角通知（毛玻璃 + 左侧色条） | `main-ui.css` `.app-toasts/.app-toast`（沿用 fork 的 `ToastHost`，不改契约） | 1 |
| 三栏首页（指挥官卡 / 打法选择 / 在线与公告）+ 底部卡牌横条 | `screens/start/StartScreen.vue` 模板与样式重写（保留全部 `data-testid`） | 2 |
| 紫色 hero 主卡 + 右侧 `ENTER` 胶囊 | `StartScreen` `.home-play--casual` | 2 |
| 金色 `RANKED` 行 | `StartScreen` `.home-play--ranked`（`color-mix` 取 `--gold` 16% 底 + 金边） | 2 |
| 电脑难度下拉 | `StartScreen` `.home-ai__caps` 四档 segmented | 2 |
| 顶部状态胶囊条 + 全宽「当前生效的场地魔法」条 | `screens/game/GameScreen.vue` HUD 包 chips + 新增 `.game-fieldbar` | 3 |
| 双 6×6 棋盘面 + 命中/未中标记 | `screens/game/BoardPanel.vue`、`game-screen.css`（`--board-bg/--board-border/--cell`） | 3 |
| 右栏「连锁结算」虚线空态 + 卡牌详情 + 主 CTA + 手牌/弃牌堆/剩余舰计数 | `game-screen.css` 右栏面板化 + `.game-detail` 面板化（结构沿用 fork） | 3 |
| 底部大卡手牌（金边选中） | `game-screen.css` `.card` / `.card.is-selected` | 3 |
| 面板 12px 圆角、小标题字距 .14em、胶囊化 | 全屏 scoped CSS 收敛 + `main-ui.css` `.ui-kicker/.ui-chip/.ui-stat` | 4 |
| 6×6 布船棋盘、状态胶囊 | `screens/placement/PlacementScreen.vue` + `--cell/--board-border` | 4 |
| 大厅两个一等行动 | `screens/lobby/LobbyScreen.vue` 快速匹配=紫渐变 hero，创建房间=面板次行动 | 4 |

逐屏收敛（批次 4）还覆盖：`settings`（分组标题改 11px 字距 kicker、虚线分隔改实线）、`rps`（三种手势改 128px 高等宽大按钮 + 悬停上浮，触屏可点）、`leaderboard`/`profile`/`game-over`/`replay`/`spectate`（裸色与错误色值换令牌，回放/观战棋盘格统一为 main 棋盘面）、`CardCollectionOverlay`/`MatchFoundOverlay`/`AppWallpaper`（裸色收敛）。

## 4. 三项保留优点的实现位置

1. **卡牌不可用说明**：`GameScreen.vue` 的 `cardDisabled()` 仍走规则层 `cardDisabledReason()`，手牌上渲染 `.card__reason`（琥珀色，2 行截断），详情面板渲染 `[data-testid="game-card-detail-reason"]` 的 `.game-detail__reason`，被拒时同时走 `say()` + Toast。截图 `screenshots/main-ui-restoration/game-reason-1920.jpg` 三处同时在位。
2. **全局通知**：`components/ToastHost.vue` 未改结构，只换 `main-ui.css` 里的观感（右下 20px、10px 圆角、毛玻璃、左侧 3px 语义色条）。手机断点下改为顶部横幅（`@media (max-width:719px)`），避免盖住对局页底部手牌与主 CTA。
3. **主界面排版**：`StartScreen` 三栏 + hero/次行动/磁贴分层，按钮高度 38–84px，手机端单列且主行动最先出现。

## 5. 改动文件

- 新增：`frontend/src/styles/main-ui.css`、`docs/screenshots/main-ui-restoration/*.jpg`、本文档。
- 重写：`frontend/src/styles/tokens.css`、`frontend/src/screens/start/StartScreen.vue`。
- 修改：`frontend/src/main.ts`（追加 `main-ui.css` import，位置在 `base.css` 之后）、`screens/game/{GameScreen.vue,BoardPanel.vue,game-screen.css}`、`screens/{placement,lobby,settings,rps,leaderboard,profile,game-over,replay,spectate}/*`、`components/{AuthOverlay,CardCollectionOverlay,MatchFoundOverlay,AppWallpaper}`。

三套主题键保持不变（`chart` / `journal` / `night`，见 `stores/ui.ts:36-38`、`screens/settings/SettingsScreen.vue:46`），只换取值：

| 主题 | 锚定的 main 外观 |
| --- | --- |
| `chart`（默认） | main 竞技场暗：`#0b0d18 / #10142a / #151a30`，紫 `#9d84f5`、青 `#4ec8e0`、金 `#c9a24c` |
| `night` | main 深色 Fluent：`#0a1428 / #0e1c33 / #12233f`，主色 `#2f8fdd` |
| `journal` | main 浅色 Fluent：`#dbeafe / #eff6ff / #ffffff`，深蓝字 `#0f172a`、主色 `#1565c0` |

## 6. 验证记录

均在 `D:/Codex workspace/battle-ship-ui-dsh` 执行（PowerShell/Git-Bash，端口 5450 独立测试栈）：

```text
$ git diff --check
（无输出，退出码 0）

$ cd frontend && corepack pnpm typecheck      # vue-tsc --noEmit
退出码 0（无诊断输出）

$ cd frontend && corepack pnpm build          # sync-card-data + check-contract + vite build
[cards] up to date (50 cards)
[contract] OK 175d5811dd71c826dd750b3b4b098ee59f517f46f3422390879254b4dd063f03
✓ 213 modules transformed.
dist/assets/GameScreen-BAkidhnu.js   63.13 kB │ gzip: 21.37 kB
dist/assets/index-C_JwIb6v.js       199.20 kB │ gzip: 75.98 kB
✓ built in 1.70s
退出码 0
```

测试栈（独立库 + 临时密钥，未触碰任何真实环境）：

```text
SECRET_KEY=dev-only-secret-key ENABLE_TEST_EVENTS=1 BATTLESHIP_DB_PATH=.tmp/ui.db \
FRONTEND_DIST=frontend/dist-test python ops/run_stack.py --port 5450 --db .tmp/ui.db \
  --frontend-dist frontend/dist-test
GET /health -> 200 {"status":"ok",...}
```

截图清单（`docs/screenshots/main-ui-restoration/`，Edge headless + Playwright，`battleship.ui.theme` 预设主题）：

| 文件 | 尺寸 | 场景 |
| --- | --- | --- |
| `home-1920.jpg` | 1920×1080 | 首页，chart 深色 |
| `home-journal-1920.jpg` | 1920×1080 | 首页，journal 浅色 |
| `home-390.jpg` | 390×844 | 首页，手机单列 |
| `game-1920.jpg` | 1920×1080 | 对局：HUD 胶囊 + 场地条 + 6×6 棋盘 + 右栏 + 手牌 + 主 CTA |
| `game-detail-1920.jpg` | 1920×1080 | 卡牌详情面板（速阶/类型/效果/使用此卡） |
| `game-reason-1920.jpg` | 1920×1080 | 卡牌不可用原因：横幅 + 卡片行内原因 + 详情原因 + 通知 |
| `game-390.jpg` | 390×844 | 对局手机：棋盘 tab、舰位、手牌、CTA 全部可直接点 |
| `placement-1440.jpg` / `placement-390.jpg` | 1440×900 / 390×844 | 布船 |
| `lobby-1440.jpg` / `lobby-390.jpg` | 1440×900 / 390×844 | 大厅（紫 hero + 次行动 + 房间列表） |
| `gameover-1440.jpg` | 1440×900 | 结算（段位/经验/再战） |
| `settings-1440.jpg` | 1440×900 | 设置 |
| `rps-1440.jpg` / `rps-390.jpg` | 1440×900 / 390×844 | 猜拳 |
| `spectate-1440.jpg` | 1440×900 | 观战（无直播时的空态） |

## 7. 已知差异 / 未覆盖

- **对局页在 1440×900 会滚动约 174px**：`game-screen.css` 顶部几何契约（棋盘边长 ≥480、手牌 118×165、桌面无滚动）在 900px 高度上无法同时成立——本次新增的全宽场地魔法条占 28px，剩余为改造前既有溢出。按「不动几何契约」原则保留现状，未压小棋盘/手牌去换零滚动。
- **回放页**需要真实 `match_id` 才能渲染棋盘，本次只取证空态；棋盘格样式已统一（`ReplayScreen.vue`、`SpectateScreen.vue` 的 `.cell`）。
- **资料页**为游客态截图（`需要先登录`）；登录态的卡片/段位样式随首页指挥官卡同步改过，但未做登录态取证（需要账号）。
- **观战页**当前没有进行中的对局，只取证空态。
- 仓外 22 条浏览器门禁（`D:/develop/battleship-verify/`）不在本机，**未执行**；`data-testid` 全部保留，未改动契约。
