# 原 main 界面 → Vue 迁移对照表（2026-10-23）

基准：原 main `d16f706e61acb02a4ca7197cd2a92400c92c568d`（只读参考树 `D:/Codex workspace/main-ui-reference-d16f706`）。
目标：fork 的 Vue3 + TS + Pinia 框架，路由与后端协议不变。

## 一、屏幕对照

| main 屏幕（`templates/index.html`） | fork 组件 | 状态 | 说明 |
| --- | --- | --- | --- |
| `#start-screen`（:151） | `screens/start/StartScreen.vue` | 已按 main 重做（前一 PR） | 三栏：指挥官 / 打法 / 侧栏 + 热门卡横条 |
| `#game-screen`（:515-793） | `screens/game/GameScreen.vue` | **本轮迁移** | 双棋盘常驻 + 左日志 + 右 rail + 底部手牌 |
| `#ship-placement-screen`（:448） | `screens/placement/PlacementScreen.vue` | 视觉已对齐（前一 PR） | 6×6 布船、随机/清空/确认 |
| `#rps-screen`（:496） | `screens/rps/RpsScreen.vue` | 视觉已对齐（前一 PR） | 三选一 + 双方状态 |
| `#lobby-screen`（:800） | `screens/lobby/LobbyScreen.vue` | 视觉已对齐（前一 PR） | 主行动两卡 + 房间列表 + 公屏 |
| `#leaderboard-screen`（:869） | `screens/leaderboard/LeaderboardScreen.vue` | 视觉已对齐（前一 PR） | 战绩榜 / 段位榜 |
| `#game-over-screen`（:932） | `screens/game-over/GameOverScreen.vue` | 视觉已对齐（前一 PR） | 结算分块 + 四个去向 |
| `#spectate-screen`（:1046） | `screens/spectate/SpectateScreen.vue` | 视觉已对齐（前一 PR） | 观战 |
| `#replay-screen`（:1125） | `screens/replay/ReplayScreen.vue` | 视觉已对齐（前一 PR） | 回放 |
| help / profile / settings / admin / friends / changelog 等弹窗 | `screens/profile|settings/*`、`components/CardCollectionOverlay.vue`、`components/AuthOverlay.vue`、`components/HelpOverlay.vue` | 部分 | 对应关系见下表 |

## 二、main 对局 DOM → Vue 结构（本轮）

| main 结构 | fork 对应 | 备注 |
| --- | --- | --- |
| `.game-main-container`（flex + wrap） | `.game-main-container`（flex，左日志 / 中内容 / 右 rail） | 结构对齐 main |
| `.log-container`（固定 280 宽浮动日志窗） | `.log-container`（左列常驻卡 + `game-log-toggle` 打开完整抽屉） | 不再浮动遮挡棋盘 |
| `.game-content`（max-width 900 居中） | `.game-content`（flex 列 + 居中） | |
| `.game-info` + `.arena-turn-chips` + `#effect-status-bar` | `.game-hud`（回合 + 胶囊行 + 双方名/舰数） + `.effect-status-bar` | chip 类名改为 `hud-chip*` |
| `.field-magic-area`（全宽条） | `.field-magic-area`（同一全宽条） | 承载 `data-testid="game-field-magic"` |
| `.boards-container` + 两个 `.board-wrapper` | `.boards-container` + 两个 `.board-wrapper`（己方在左） | **桌面双棋盘常驻**，不再藏进小地图浮层 |
| `.board-tabs`（me / opp） | `.board-tabs`（`.board-tab`，仅紧凑档显示） | 手机/横屏切换海域 |
| `#arena-chain-slot`（连锁结算） | `.arena-rail-panel` 内的连锁列表 + 原 `game-chain-panel` 浮层 | |
| 待使用魔法卡区（`.magic-preview-container`） | `.arena-rail-panel` 内的 `game-detail`（详情面板移到 rail） | 原浮层改为列内面板 |
| `#turn-indicator` 按钮组（进入战斗/结束大回合/结束回合/弃牌） | `.arena-actions`（`game-primary` + `game-more` 菜单） | 保持 data-testid |
| `.arena-counts`（手牌/弃牌堆/剩余舰） | `.arena-counts`（三格计数） | 弃牌堆数量服务端未下发 → 显示「—」+ 查看弃牌堆 |
| 底部手牌 | `.game-hand-wrap` + `.game-hand` + `.card` | 桌面 118×165，紧凑档 64×92（main 同款尺寸） |
| `#aux-dock`（手机三选一面板） | `.game-compact-bar`（主操作 + 更多菜单 + 日志/聊天抽屉） | 手机上不放浮层压棋盘 |

## 三、有意保留的差异

1. **卡牌不可用原因**：`game-detail__reason` / `.card__reason` 仍是 fork 的必保能力，main 没有对应文案；本轮保留于详情面板与手牌卡面。
2. **右下角全局通知**：`components/ToastHost.vue` + `.app-toasts`，main 无此机制；对局屏桌面停靠右上、手机停靠顶部，避免遮住手牌与主操作。
3. **抽屉式日志/聊天/弃牌堆**：main 用浮动窗口；fork 在对局内用抽屉，避免覆盖棋盘（内容与入口一致）。
4. **紧凑档（≤719px 宽或 ≤520px 高）**：单棋盘 + 海域标签，与 main 的 `adaptive_layout.js` 同类做法；桌面（≥720×520）必须双棋盘常驻。

## 四、验证入口

- 结构门禁：`D:/Codex workspace/battle-ship-main-vue-verification-20261023/spec-dual-board.mjs`（桌面双棋盘）
- 紧凑门禁：同目录 `spec-compact.mjs`（390×740 / 360×640 / 844×390：不重叠、棋盘在视口内、格宽 ≥34px、主操作可命中）
- 浮层可达性：同目录 `spec-sheet.mjs`（手机卡牌详情、连锁响应浮层每个按钮都过 `elementFromPoint`）
- 选目标可达性：同目录 `spec-target-compact.mjs`（神之宣告 / 神威！：36 格全可点、点击被接受）
- 真实链路：同目录 `flows/port-match.mjs wide|phone`（首页 → 人机 → 布船 → 猜拳 → 进战斗阶段 → 开炮 → 卡牌详情 → 控制台无错误）
- 截图：同目录 `shots/`

## 五、本轮补记（2026-10-23 08:10）

1. **左列日志为空不是界面问题**：一局从「准备阶段」开始，未按主按钮进入战斗阶段时服务端不接受任何炮击；
   真实链路脚本补上「进入战斗阶段 + 等 `--attackable`」后，日志逐条出现
   （`第1回合 · 舰长XXXX 攻击 (0,0) — 未命中`）。紧凑档没有常驻日志卡，改由底部「日志」按钮打开抽屉，
   因此手机上的判据用「开火计数 + 最近一条事件文案」。
2. **紧凑档三处必须可达**：卡牌详情（底部面板，`使用此卡`/`取消选择` 在视口内）、
   连锁响应（`game-chain-overlay` 浮层，5 个按钮全部可命中）、选目标（`.game-target` 在紧凑档改为
   静态停靠、`is-picking` 时收起手牌与主行动条，把位置让给目标面板）。
3. **选目标期间棋盘必须跟手**：紧凑档一次只显示一块棋盘，选目标时按目标棋盘自动切到对应海域；
   期间隐藏海域标签（浮层自带「我的棋盘 / 对手棋盘」），避免两套开关互相打脸。
4. **详情面板不再叠在连锁位上**：紧凑档详情的底部面板只留卡牌信息，不再重复「连锁结算」空面板。


## 六、审查轮回归修复（2026-10-23，RED → GREEN）

复跑脚本（仓外）：`BASE_URL=http://127.0.0.1:5457 node spec-regressions.mjs`，修复前 `RESULT: FAIL (5)`，修复后 `RESULT: PASS`（12/12）。

1. **收起连锁会丢掉待响应请求**：`stores/match.ts` 拆开「收起」与「清空」——新增 `chainWindowCollapsed`、
   `collapseChainWindow()`、`expandChainWindow()`；`closeChainWindow()` 只在协议层（`chain_resolved`、开局 `reset()`）调用。
   面板收起后手牌上方出现 `game-chain-reopen` 提示条（含剩余秒数），点开恢复同一个请求与倒计时；`game-chain-close`、
   `game-chain-open` 都改为收起语义。
2. **选目标途中切手机尺寸卡住**：紧凑档可见海域的 watch 依赖加入 `compact`，布局变化时重新同步 `zoomOpen`
   （目标在己方→显示己方棋盘）；watch 移到 `compact`/`zoomOpen` 声明之后，避免 getter 立即求值触发 TDZ。
3. **护盾在对方海域误选己方舰**：`onCell` 的 `shieldChoice` 分支先判 `board !== 'self'` 直接拒绝并给出提示，
   不再按坐标匹配己方舰船。
