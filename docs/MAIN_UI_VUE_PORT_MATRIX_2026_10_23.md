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
| help（:1627 九段图鉴 + 计分） | `components/HelpOverlay.vue` | 已迁移，取服务端常量 | `/api/rank_constants`（顶段显示晋升条件）、`/api/profile` 的 catalog 取解锁项；游客如实提示 |
| friends + 私聊（:1761 三列表 / :1781 私聊） | `components/FriendsOverlay.vue` + `stores/dm.ts` + `realtime/friends.ts` | 已迁移，含实时与分页 | friends 系列接口；`friend_message`/`friend_request` 走共享 socket |
| admin（:1717 反作弊弹层 + `static/admin.js`） | `components/AdminOverlay.vue` | **本轮迁移** | 入口按 `/api/admin/me` 的 `is_admin` 渲染；读写走 `/api/admin/*`，服务端鉴权未改 |
| profile（:1367 名片） | `screens/profile/ProfileScreen.vue` | 视觉已对齐，内容态已取证 | 游客态 + 登录态（人机局不计段位，战绩为 0 属规则） |
| settings（:1367-1397 预览 + 主色） | `screens/settings/SettingsScreen.vue` | 已迁移预览与主色 | 本地偏好，写 `--role-action` |
| collection（:1584 图鉴） | `components/CardCollectionOverlay.vue` | 已迁移排序/筛选/详情 | `/api/card_usage` |
| login/register（弹窗） | `components/AuthOverlay.vue` | 视觉已对齐 | 走既有 `/api/login`、`/api/register` |
| changelog（:1367 内嵌公告） | 首页 `/api/changelog` 区块 + `LobbyScreen` 公告条 | 已对齐 | 数据来自后端公告表 |

## 二、main 对局 DOM → Vue 结构（本轮）

| main 结构 | fork 对应 | 备注 |
| --- | --- | --- |
| `.game-main-container`（flex + wrap） | `.game-main-container`（flex，左日志 / 中内容 / 右 rail） | 结构对齐 main |
| `.log-container`（固定 280 宽浮动日志窗） | `.log-container`（左列常驻日志卡，逐条列出本局事件） + `game-log-toggle` 打开完整抽屉 | 左列常驻，不浮动遮挡棋盘 |
| `.game-content`（max-width 900 居中） | `.game-content`（flex 列 + 居中） | |
| `.game-info` + `.arena-turn-chips` + `#effect-status-bar` | `.game-hud`（回合 + 胶囊行 + 双方名/舰数） + `.effect-status-bar` | chip 类名改为 `hud-chip*` |
| `.field-magic-area`（全宽条） | `.field-magic-area`（同一全宽条） | 承载 `data-testid="game-field-magic"` |
| `.boards-container` + 两个 `.board-wrapper` | `.boards-container` + 两个 `.board-wrapper`（己方在左） | **桌面双棋盘常驻**，不再藏进小地图浮层 |
| `.board-tabs`（me / opp） | `.board-tabs`（`.board-tab`，仅紧凑档显示） | 手机/横屏切换海域 |
| `#arena-chain-slot`（连锁结算） | `.arena-rail-panel` 内的连锁列表 + 原 `game-chain-panel` 浮层 | |
| 待使用魔法卡区（`.magic-preview-container`） | `.arena-rail-panel` 内的 `game-detail`（大卡图 + 完整效果文 + 使用/取消） | 原浮层改为列内面板；紧凑档改底部可滚动 sheet |
| `#turn-indicator` 按钮组（进入战斗/结束大回合/结束回合/弃牌） | `.arena-actions`（`game-primary` + `game-more` 菜单） | 保持 data-testid |
| `.arena-counts`（手牌/弃牌堆/剩余舰） | `.arena-counts`（三格计数） | 弃牌堆数量服务端未下发 → 显示「—」+ 查看弃牌堆 |
| 底部手牌（扇形） | `.game-hand-wrap` + `.game-hand` + `.card` + `useHandFan.ts` | 桌面按 main 的 `layoutHand` 算法：卡宽 96–132、`--fan-rot`/`--fan-drop`、描述行数 3–7；紧凑档 64×92 不旋转 |
| `.in-game-chat-container`（可拖动浮窗） | `.game-float` + `useFloatingDrag.ts`（标题栏拖动、边界夹紧） | HUD「聊天」打开；紧凑档仍是抽屉 |
| 顶栏对手剩余舰方块 | `hud-ship-dots`（6 个小方块，沉没变暗） | `game-ships` 文案与 testid 不变 |
| `#aux-dock`（手机三选一面板） | `.game-compact-bar`（主操作 + 更多菜单 + 日志/聊天抽屉） | 手机上不放浮层压棋盘 |

## 三、有意保留的差异

1. **卡牌不可用原因**：`game-detail__reason` / `.card__reason` 仍是 fork 的必保能力，main 没有对应文案；本轮保留于详情面板与手牌卡面。
2. **右下角全局通知**：`components/ToastHost.vue` + `.app-toasts`，main 无此机制；对局屏桌面停靠右上、手机停靠顶部，避免遮住手牌与主操作。
3. **抽屉式日志/聊天/弃牌堆**：main 用浮动窗口；fork 在对局内用抽屉，避免覆盖棋盘（内容与入口一致）。
4. **紧凑档判据回到 main**：`useAdaptiveGameLayout.ts` 用原 `adaptive_layout.js` 的 `1200×700`（`compact = !(w>=1200 && h>=700)`），棋盘模式按 `.boards-container` 实测预算选 `side/stack/tabs`，尺寸写 `--board-size`；只有 `tabs` 档才显示海域标签。

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

## 七、审查轮 R1 / R2 落地（2026-10-23，基点 23115e1 → 本轮 HEAD）

### R1 对局还原

| 原 main 行为 | Vue 实现 | 证据 | 剩余差异 |
| --- | --- | --- | --- |
| 宽屏判据 1200×700 + `--board-size` 实测预算 | `screens/game/useAdaptiveGameLayout.ts`（`WIDE_MIN_W/WIDE_MIN_H/TIGHT_MAX_H/MIN_CELL/MIN_BOARD` 同值） | `spec-dual-board.mjs`、`spec-compact.mjs` | 由「视口预算 + 调用方量到的 chrome 高」代替原 MutationObserver，极限窗口靠屏内滚动兜底 |
| 双棋盘并排、己方在左、可直接点己方舰格 | `.boards-container` 两个 `.board-wrapper`，`v-show` 由 `boardMode` 决定 | `spec-dual-board.mjs`：1440×900 / 1920×1080 均 PASS，己方舰格 14/14 `elementFromPoint` 命中 | tabs 档（极窄/极矮）仍单棋盘 |
| 左侧聊天 + 日志浮动窗、可拖动 | 左列常驻日志 + `.game-float` 浮动聊天（`useFloatingDrag.ts`）+ 抽屉 | `spec-floating-chat.mjs`：拖动 `{20,470}→{270,472}`，拖出视口夹到 `x=1132`（`1132+300≤1440`） | 日志用列内卡而非浮动窗（避免压棋盘） |
| 右侧竖向连锁牌栈 | `.arena-rail-panel` 连锁列表 + 连锁浮层 + 收起后的 `game-chain-reopen` 胶囊 | `spec-regressions.mjs`（12/12 PASS） | — |
| 独立完整卡牌预览 | rail 内 `game-detail`（大卡图 + 效果全文 + 使用/取消） | `spec-sheet.mjs` | 紧凑档是底部 sheet，可滚动 |
| 底部扇形大卡 | `useHandFan.ts` + `--hand-card-*` / `--fan-rot` / `--fan-drop`（含 `selectedIndex`/`need = w + HAND_TAP_MIN`） | `spec-review3.mjs g`：8 张重叠手牌不溢出（right=1159 < 1440）、选中牌中心命中自身、右邻居整块可点 | 极窄档改不旋转的紧凑排布 |
| 顶栏对手身份/舰数 | `.hud-players` + `hud-ship-dots` | 截图 `shots/port-1440x900-game.png` | — |

### R2 周边功能

| 原 main | Vue 实现 | 数据来源 | 证据 |
| --- | --- | --- | --- |
| 好友三列表 + 私聊 | `components/FriendsOverlay.vue`（好友/申请/私聊），导航好友按钮接入 | `GET /api/friends`、`POST /api/friends/respond|remove`、`GET|POST /api/friends/messages`、`/messages/read` | `spec-social-help.mjs`：两个真实临时账号建立好友并互发消息，面板内发送成功（`friends-1440x900.png`、`friends-390x740.png`） |
| 玩法与段位帮助（九段 + 计分） | `components/HelpOverlay.vue`（头像菜单「玩法与帮助」） | `GET /api/rank_constants`（不写死任何数字；失败显示「段位规则暂不可用」） | 同脚本：9 段阶梯 + 胜利 7 行/失败 7 行真实数据（`help-1440x900.png`、`help-390x740.png`） |
| 设置预览 + 主色选择器 | `SettingsScreen.vue` 新增主色预设 + 棋盘/命中/主次行动预览；`stores/ui.ts` 的 `accent`/`setAccent` | 本地偏好（写 `--role-action`，可恢复跟随主题） | `spec-collection-settings.mjs`：主色 `#9d84f5 → #4ec8e0` 立即生效、可恢复（`settings-preview-1440x900.png`） |
| 图鉴使用次数排序 + 速阶/类型独立筛选 + 点卡详情 | `CardCollectionOverlay.vue`（筛选条 + 排序 + 详情侧栏；手机详情在列表上方） | `GET /api/card_usage` | 同脚本：速阶筛选、类型叠加、点卡详情、手机详情在视口内（`collection-detail-1440x900.png`、`collection-detail-390x740.png`） |

### 逐屏有内容证据（真实临时账号，`flows/content-screens.mjs` / `flows/replay-content.mjs`）

| 屏幕 | 状态 | 证据 | 说明 |
| --- | --- | --- | --- |
| 资料 `profile` | 已登录、有段位/等级/战绩框架 | `content-profile-1440x900.png` | 人机局不计段位，`总场次` 仍为 0；架构性内容（名片/徽章/回放入口）可见 |
| 结算 `game-over` | 有内容 | `content-gameover-1440x900.png` | 显示本局结果与「本局回放」按钮 |
| 回放 `replay` | 有内容 | `content-replay-1440x900.png` | `第 1/12 步`、双视角棋盘、6 艘舰、播放/步进、双方手牌与事件列表 |
| 观战 `spectate` | **真实链路有内容**（本仓脚本只截到空态） | `codex-r2-shots/real-spectate-1440x900.png`、`real-spectate-390x740.png`（Codex 用公开接口造两位玩家 + 一位观众） | 72 格双棋盘、攻击实时更新、390×740 切视角、观战聊天；本仓 `content-spectate-1440x900.png` 仅空态截图 |

### 复核时补的两处紧凑档可达性修复

- **极矮横屏（844×390，`data-tight`）手牌被裁成窄条**：`grid-template-rows` 的手牌行改成 `minmax(84px, 1fr)`、卡面 56×78、隐藏手牌信息行；`.game-hand-head` 全档 `pointer-events: none`（纯信息，不应吃掉点击）。
  证据：`spec-target-compact.mjs` 的「手牌首张不可点（elementFromPoint=game-hand-wrap）」由 FAIL 转 PASS，844×390 神威！随后 36/36 可点。
- **紧凑档打开卡牌详情 sheet 时手牌行与按钮重叠**：`.game[data-layout="compact"].is-sheet .game-hand-wrap { display: none }`，避免底部两层叠在一起。
  证据：`spec-target-compact.mjs`（先真实点击「使用此卡」再选格）恢复 PASS。
- 极矮横屏隐藏胶囊行（`.hud-chips`），只保留回合 / 双方 / 舰数 / 聊天按钮，避免半截被压。

### 本轮剩余缺口（如实，2026-10-23 09:10 更新）

1. 人机局不计段位分，资料页战绩数字为 0（规则如此）；段位进度条要有真实排位局才有数字。
2. 仓外 22 条 `data-testid` 浏览器门禁仍未跑（本机无 `D:/develop/battleship-verify` 基线）。
3. 管理员处置历史里的 `actor` 显示的是账号 id（后端 `override_history.actor` 原样返回），原 main 同样如此，未另做用户名映射。

## 八、审查轮第三批（2026-10-23 09:10，基点 c80ad9e）

| 问题 | 根因 | 修法 | 证据 |
| --- | --- | --- | --- |
| 私聊切换竞态 | `openThread` 先切 `activeName`，异步回包无条件覆盖 `messages` | 新增 `stores/dm.ts`：每会话递增 `token` + `AbortController`，迟到回包丢弃；`send` 捕获发起时会话，只落回该会话 | `spec-review3.mjs a`：a0 证明 race 路径被走到（held=1），a2 内容不再被串，a3 草稿保留 |
| 私聊无实时收信、刷新不更新 | 面板没有 socket 订阅，`loadFriends` 对已有会话不重读 | 新增 `realtime/friends.ts`（`acquireFriendsChannel` 复用共享 socket，引用计数释放）；`loadFriends` 末尾对当前会话 `dm.open` | `spec-review3.mjs b`：b1 不点刷新即出现、b2 其他会话未读角标、b3/b4 刷新更新且不清空 |
| >50 条历史无法查看 | `limit=50` 写死、`has_more` 被丢弃 | `dm.loadOlder` 用 `before=最早 id`，`mergeMessages` 按 id 去重升序 | `spec-review3.mjs c`：首屏 50 + 「加载更早」，翻到 68 条，id 升序 94..166 |
| 有真实牌栈时「收起」失效 | 浮层 `v-if` 让 `chainList.length` 绕过 `chainCollapsed` | `chainHasContent` / `chainPanelOpen` 两个 computed 统一语义，收起只改可见性 | `spec-review3.mjs d`：d1 非空牌栈打开、d2/d3 收起后 overlay=false + reopen=true、d4 重开倒计时 99→98 未重置 |
| 帮助缺顶段条件与解锁 | 一律画「N 分起」，顶段没有起始分 | 顶段显示服务端 `admiral_rank_limit`/`admiral_min_captains` 条件；解锁项取 `/api/profile` 的 `catalog`（游客如实提示） | `spec-review3.mjs e`：e1 晋升条件、e2 阈值 50/50、e3 游客提示、e4 catalog 解锁 |
| 管理员入口未迁 | 前一轮矩阵把 admin 行去掉且没有组件 | 新增 `components/AdminOverlay.vue`（总览/详情/处置/历史），入口按 `/api/admin/me` 渲染 | `spec-admin.mjs`：a0 is_admin、b0 游客无入口、b1 未登录接口 401、c1–c5 入口/列表/搜索/详情/处置历史 |
| 手牌「选中加宽未实现」说法有误 | `useHandFan.ts` 早已实现 `selectedIndex` + `need` | 不做重复机制，改报告 | `spec-review3.mjs g` 3/3 PASS |

## 九、审查轮第四批（2026-10-23 09:52，基点 776bf06）

| 项 | 状态 | 说明与证据 |
| --- | --- | --- |
| 分页锁死 | 已修 | `dm.ts` 两套序号 + `finally` 只清自己；`spec-review4.mjs pagination` PASS 2 |
| 仅链栈收起 | 已修 | `collapseChainWindow()` 无条件写视图状态、重开文案分支；`spec-review4.mjs chain` PASS 5 |
| 私聊生命周期/标读 | 已修 | `App.vue` 登录期常驻订阅 + `dm.setVisible/markRead`；`spec-review4.mjs lifecycle` PASS 6 |
| 对手身份条 | 已迁，头像为账号真实头像，带战绩弹窗 | `.hud-players` 双 `.arena-player`；`real-chain.mjs` 两账号真实匹配 PASS；人机/游客兜底 `ai-guest.mjs` PASS。**遗留**：同名游客昵称会被当成注册账号（需后端字段，见报告 8.5） |
| 己方舰队摘要 | 已迁 | `.arena-fleet`（fixed 左下，`game-self-fleet`） |
| 浮动聊天 + 可拖日志 | 已迁，位置记忆，快捷语按需 | `useFloatingDrag`（`game_log_pos`/`in_game_chat_pos`，刷新恢复）；快捷语从输入行展开；紧凑档抽屉 `position:fixed`（`drawer-scroll.mjs` 360×640/390×740/844×390 PASS） |
| 竖向连锁轨道 | 已迁 | 宽屏 96px 轨道 + 叠牌 76×114/-38px；空态保留高度 |
| 独立完整卡牌详情 | 已迁 | 卡名 → 156px 2:3 卡面 → 规则（局部滚动）→ 使用/取消 |
| 手牌完整原画 | 已迁 | `.card--art` 隐藏重复文字层，卡面铺满；不可用原因保留为底部小条 |
| 观战内容态 | 已复验（引用） | `codex-r2-shots/real-spectate-1440x900.png`、`real-spectate-390x740.png`（Codex 真实双玩家 + 观众链路） |
