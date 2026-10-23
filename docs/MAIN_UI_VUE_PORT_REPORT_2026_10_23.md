# 原 main 界面迁进 Vue 框架：实施与验证记录（2026-10-23）

任务：把原 main 前端（`d16f706`）的**结构与视觉**整体迁进 fork 的 Vue3 + TS + Pinia 单栈，
不是继续美化 fork。分支 `feature/main-ui-vue-port`，基点 `9a8d4af`（`origin/review/fork-cloud`）。

## 一、做了什么

### 1. 壳层与令牌（前序提交）
- `frontend/src/styles/tokens.css`：chart / night / journal 三主题按 main 取值（竞技场暗、深色 Fluent、浅色 Fluent）。
- `frontend/src/styles/main-ui.css`：64px 顶栏、按钮基元、Toast、覆盖层、输入控件、滚动条。
- 保留 fork 的两项必备能力：**卡牌不可用原因**（详情面板 `game-card-detail-reason` + 卡面 `card__reason`）、
  **右下角全局通知**（`ToastHost`；对局桌面停靠右上、手机停靠顶部，避免压住手牌与主操作）。

### 2. 首页（`screens/start/StartScreen.vue`）
三栏：指挥官卡 / 「选择一种打法」（紫色 hero + ENTER 徽章 + 金色 RANKED + 人机难度分段）/ 在线与公告；
「卡牌」展示条并入中栏底部（与 main 的「全服热门卡」同位置），1440×900 页高 1124 → 935。

### 3. 对局（`screens/game/GameScreen.vue` + `game-screen.css`）
- 换成 main 的 DOM：`.game-main-container` = 左列游戏日志 / 中列 `.game-content`（HUD + 场地魔法条 + 双棋盘）/
  右列 `.arena-rail`（连锁结算、卡牌详情、手牌/弃牌/剩余舰计数、主行动）+ 底部手牌。
- **桌面双棋盘常驻、己方在左**，可直接点己方舰格（不再靠小地图浮层）。
- 紧凑档（`≤719px 宽` 或 `≤520px 高`，与 main 的 adaptive_layout 同类）：单棋盘 + 海域标签，
  棋盘按剩余高度取正方形；底部条提供主行动 + 日志/聊天/弃牌入口。
- 选目标：紧凑档收起手牌与主行动条，把位置让给目标面板；可见棋盘跟随目标海域（`is-picking`）。

### 4. 玩家公告
`backend/src/battleship/domain/social/changelog.py` 新增一条（2 行，均 ≤40 字），
`GET /api/changelog` 首条即本批更新。

## 二、验证（可复跑，全部在本轮执行）

证据目录：`D:/Codex workspace/battle-ship-main-vue-verification-20261023`（Edge + playwright-core，
`BASE_URL=http://127.0.0.1:5455`，测试栈用独立库 `.tmp/port.db`，`ENABLE_TEST_EVENTS=1`）。

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 桌面双棋盘 | `node spec-dual-board.mjs 1440x900 1920x1080` | PASS（两块 361px 棋盘、己方在左、己方舰格 14/14 可命中） |
| 紧凑档几何 | `node spec-compact.mjs` | PASS（390×740 / 360×640 / 844×390：无重叠、无整页滚动、主按钮可命中） |
| 浮层可达性 | `node spec-sheet.mjs` | PASS（手机卡牌详情 352×238、`使用此卡` 可命中；连锁浮层 5 个按钮全部 `elementFromPoint` 命中） |
| 选目标可达性 | `node spec-target-compact.mjs` | PASS（神之宣告 390/360：36 格全可点、两击「已选 2 / 2」；神威！390/844：区域选择被接受） |
| 周边弹层 | `node spec-overlays.mjs` | PASS（图鉴 1120×794 / 390 宽 366×653；登录 460×426） |
| 逐屏巡检 | `node spec-screens.mjs` | 10 条路由两种尺寸均无横向溢出；页高见下 |
| 真实链路（桌面） | `node flows/port-match.mjs wide` | PASS：首页 → 人机 → 布船 → 猜拳 → 进入战斗阶段 → 开炮 → 日志新增 → 卡牌详情 → 控制台无错误 |
| 真实链路（手机） | `node flows/port-match.mjs phone` | PASS：同上（手机日志走抽屉，判据用开火计数 + 最近事件文案） |
| 类型检查 | `cd frontend && corepack pnpm typecheck` | 退出 0 |
| 生产构建 | `cd frontend && corepack pnpm build` | `[cards] up to date (50 cards)` / `[contract] OK 175d5811…` / `✓ built in 1.75s`，退出 0 |
| 空白检查 | `git diff --check` | 退出 0 |

逐屏页高（1440×900 / 390×740）：home 935 / 2250、placement 900 / 853、rps 900 / 740、
lobby 1149 / 1686、leaderboard 900 / 740、profile 900 / 740、settings 908 / 2170、
replay 900 / 740、spectate 900 / 740、game-over 900 / 740。

## 三、已知差异与限制（如实）

1. **紧凑档单棋盘**：手机与手机横屏只显示一块棋盘（标签切换），与 main 的 `adaptive_layout.js` 同类；
   桌面（≥720 宽且 ≥520 高）必须双棋盘常驻，已由 `spec-dual-board.mjs` 钉住。
2. **日志/聊天/弃牌堆用抽屉**：main 是浮动窗口；fork 在对局内用抽屉 + 紧凑档底部入口，避免覆盖棋盘。
3. **弃牌堆数量**：服务端未下发数量，计数格显示「—」并提供「查看弃牌堆」。
4. **仓外 22 条浏览器门禁未跑**：本机没有 `D:/develop/battleship-verify` 基线，`data-testid` 全量保留但未做外部回归。
5. **真实链路只覆盖人机**：双人对局与观战/回放的实战未在本轮跑（观战/回放页面已做逐屏巡检）。
6. **截图来源标注**：`shots/port-*`、`shots/sheet-*`、`shots/spec-*` 为真实服务器链路或夹具；
   `shots/screens-*` 为逐屏巡检；夹具用途已在对应 spec 脚本注释里写明。
