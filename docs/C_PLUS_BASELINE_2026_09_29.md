# C+ 周边屏幕 · P0 基线与接口映射（2026-09-29）

> 承接 `docs/C_PLUS_SCREENS_IMPLEMENTATION_2026_09_29.md` §4「P0：确认基线与接口映射」。
> 交付物：① 差异清单 ② 状态映射表 ③ 回归基线。
> 口径：**以当前代码行为为准**，不采信旧文档；旧文档与本文件冲突处已在 §4 逐条列出。

---

## 1. 回归基线（改前实测）

| 门禁 | 改前结果 | 备注 |
| --- | --- | --- |
| `python -m pytest tests/ -q` | **2622 passed / 1 failed**（66.17s） | 红的是 `test_dead_snapshot_key_is_gone_from_the_whole_repo`：全仓扫描扫到 gitignored 的 `.workbuddy/review/**`，环境性假红（与代码无关，2026-09-24 起就是这样） |
| `node tools/ui_layout_check.mjs` | 见 §5 记录 | 含「页面无 JS 异常」 |
| `node tools/fluent_css_metrics.mjs` | hex 100 / rgba 89 / !imp 31 / dupSel 31（阈值 110/180/40/32） | 只量 `static/style.css` |
| `node tools/fluent_style_check.mjs` | 全绿 | 含圆角档位与 arena 形状签名 |
| `node tools/dom_contract_check.mjs` | 全绿 | 静态 id 交叉核对 |
| `node tools/card_compendium_check.mjs` | 全绿 | 43 条目 / 41 唯一 |
| `node tools/codex_realcard_check.mjs` | 全绿 | 卡面比例 0.715 |
| `node tools/lobby_check.mjs` | 全绿 | 双浏览器 |
| `node tools/profile_card_check.mjs` / `profile_leaderboard_check.mjs` | 全绿 | |
| `node tools/spectate_check.mjs` | 全绿 | 四浏览器 |
| `node tools/replay_check.mjs` / `dom_replay_frame_check.mjs` | 全绿 | |

### 1.1 AC6 预算只剩这些余量

`tools/fluent_css_metrics.mjs` 只统计 `static/style.css`：

| 指标 | 当前 | 阈值 | 余量 |
| --- | --- | --- | --- |
| 裸 hex | 100 | 110 | **10** |
| 裸 rgba() | 89 | 180 | 91 |
| `!important` | 31 | 40 | 9 |
| 重复定义选择器 | 31 | 32 | **1** |

⇒ **十屏的新样式一律写进新文件 `static/arena_screens.css`**，不追加进 `style.css`
（实施方案 §5 的建议与这条实测数字同向）。新文件不进 AC6 统计，因此可以自由使用原型词汇；
但纪律照旧：能用令牌就用令牌，不写与令牌等价的裸值。

### 1.2 不能被这轮改到的断言目标

| 目标 | 断言者 | 约束 |
| --- | --- | --- |
| `#find-match` / `#player-name` / `#custom-create-room` / `.modal-content` / `.nav` / `.theme-card` 的 `border-radius` | `fluent_style_check.mjs` | 每个角都必须落在 `{4px, 8px, 12px}` 内 |
| arena 预设的「形状签名」（上列前三者的字体 + 圆角 + 间距） | `fluent_style_check.mjs` | 必须**只有一个取值** —— 改 `#custom-create-room` 的圆角必须同步改 `#find-match` |
| `.game-container` / `.game-content` / `.game-main-container` / `.screen.active` 的 `transform`/`filter`/`backdrop-filter` | `fluent_style_check.mjs` | 必须全为 `none`（否则弹窗改以它为包含块） |
| 棋盘 300×300 / 单格 42px | `ui_layout_check.mjs` | 视觉改动不许动盒模型 |
| `.magic-card` 比例 0.715 + `.card-art` 的 `--card-art-image` 与 ≥3 层背景 | `codex_realcard_check.mjs` | 图鉴必须继续用**真卡组件**，不能换成原型那种扁平磁贴 |
| `#spectate-screen` 的 HTML 字面量 `<div id="spectate-screen" class="screen">` | `tests/test_spectate_batch3.py` | 类名必须以 `screen` 开头，不能加别的类 |
| 每个 `id="*-screen"` 都不许 `classList.add('hidden')` | `tests/test_screen_overlay_registry.py` | 显隐只能靠 `active` |
| `static/game.js` 里所有 `getElementById` 的 id 都要在 `index.html` 存在 | `dom_contract_check.mjs` | 改 id 必须两边同改 |

---

## 2. 差异清单：原型 vs 正式实现

原型 = `docs/ui_demos/arena-suite.{html,css,js}`（`?view=` 十屏）。逐屏列出**正式实现缺什么**。

| 屏幕 | 原型有、正式没有（本轮要补） | 正式有、原型没有（必须保留） |
| --- | --- | --- |
| 大厅 | 房间卡片网格（状态胶囊 / 插图带 / 页脚头像 + CTA 分档）、`快速加入` 房间号输入区、`在线好友` 面板、左侧「全部/等待加入/对局中」筛选、搜索框 | `lobby_state` 真实广播、玩家列表（等级/段位/状态）、公屏（含 `data-seq` 去重）、进行中对局列表 + 观战入口、休闲/排位匹配按钮、`close_room`、订阅/退订 |
| 好友房 | `stepbar` 三步、对位 `versus` 席（房主标记 + 准备胶囊）、房号大字邀请区、`对局约定` 规则表 | 真实房号、复制邀请链接（clipboard + prompt 兜底）、解散房间、`?room=` 自动入房、`friend_invite` 提示条 |
| 布船 | 带坐标轴的海域（A–F / 1–6）、右侧「六个位置」信息栏（大号计数 + 6 格舰队槽 + 确认按钮）、`随机/清空` 工具行 | 6 艘单格船上限、取消放置（再点撤回）、`place_ships` ack 保护、断线重连 `room_sync`、绝处逢生的中途重摆 |
| 图鉴 | 桌面右侧详情栏（大卡 + 完整效果 + 类型/速阶胶囊）、手机详情弹窗、搜索 + 分段筛选条 + 计数 | 真卡组件（比例 0.715）、`/api/card_usage` 角标、按速阶/类型筛选、按卡名与效果文本搜索、段位帮助块 |
| 排行 | 前三名领奖台、指标分段（积分/胜场/胜率）、自己那一行高亮 + 左侧紫条、行尾「档案 ↗」 | 两张真实表（`/api/leaderboard`、`/api/ranked_leaderboard`）、页签、加载/空/错误态、游客可用、段位图标与分档配色 |
| 档案 | 左栏舰长卡（封面 + 罗盘环 + 佩戴徽章 + 经验条）、右侧 4 指标 + 徽章陈列 + 最近航迹 | 查看面 / 编辑面分离、5 个查看入口、隐私过滤、徽章墙、留言板、互动（点赞/送花）、对局历史 + 回放入口、10 种背景 / 10 种头像框 / 称号 / 标签 |
| 结算 | 胜负主视觉（45° 徽记 + 光晕 + eyebrow）、`RANK PROGRESS / BATTLE STATS / CAPTAIN EXPERIENCE` 三栏、4 个无框指标 | 真实 `winner`/`reason`（投降/掉线/超时）、平局、积分与经验动画（`xpAnimToken`/`rankAnimToken`）、徽章解锁面板、休闲/人机/排位差异、重连恢复、最近对手加好友按钮 |
| 观战 | 顶部状态条（观战胶囊 + 双方名 + 回合/阶段）、两块等宽海域 + `仅公开信息` 标注、右侧公开战报时间轴、底部 `跟随公开战况` 说明条 | 净化快照（禁字段表）、场地魔法/连锁/观众名单/观战席聊天、权限变化、离开观战、`spectate_board` 实时帧 |
| 回放 | 时间轴（`input[type=range]` + 帧标签）、播放控制（上一步/播放/下一步/倍速 select）、事件列表可点击定位、两块只读海域 | 帧计算 `replayComputeFrame`、稀疏增量船位/手牌时间线、棋盘重置、服务端关键节点、1×/2×/4×、拖动 seek、键盘（←/→/空格/Esc）、来源与截断提示、401/403/404/409 权限错误文案 |
| 设置 | 左侧分组纵向面板（外观/声音/操作与可读性）、右下「即时预览」面板、强调色三色卡、开关行 + 滑杆行 | 4 个分区（look/sound/wp/acct）、主题预设网格（fluent/arena + 6 旧预设）、主色微调、音量接 `bgMusicPlayer`、壁纸引擎、改密码、观战/回放权限（服务端返回值为准） |

### 2.1 原型里「只用于选稿、不进正式游戏」的部分（按实施方案 §2 剔除）

- 左侧固定侧栏 + 10 屏导航 + `01 / 10` 页码 + `#page-stepper` 前后屏切换。
- 页脚的 `C+ DESIGN SYSTEM` 字串与示例 toast。
- 全部示例数值（在线 12 人 / 房间号 `A7C2E1` / 1,240 分 / 4 艘预置船 / 8 步固定事件）。
- 设置页的三色强调色卡：正式的主题轴是**主题预设**（8 个）+ 主色微调，不是三色。
- 「双方准备」握手：正式房间状态机里没有 ready 位（见 §4）。

---

## 3. 状态映射表

> 每一屏：**DOM id（冻结）· 事件监听 · 数据来源 · 进入/销毁**。
> 事件名以 `grep` 为准；括号里是 `static/game.js` 行号（会漂移，只当线索）。

### 3.1 大厅 `#lobby-screen`

| 项 | 内容 |
| --- | --- |
| 容器 id | `#lobby-screen` › `.lobby-topbar`（`#lobby-player-count` `#lobby-in-lobby-count` `#lobby-queue-casual` `#lobby-queue-ranked` `#lobby-refresh`）· `.lobby-columns` › 4 个 `.lobby-panel`（`#lobby-players-list` / `#lobby-rooms-list` + `.lobby-create-row`（`#lobby-room-name` `#lobby-room-public` `#lobby-create-room`） / `#lobby-matches-list` / `#lobby-chat-messages` + `#lobby-chat-input` `#lobby-chat-send`）· `.button-group`（`#join-lobby-match` `#lobby-ranked-match` `#leave-lobby-match` `#back-to-main-from-lobby`） |
| 监听 | click：`#lobby-refresh` `#lobby-create-room` `#lobby-chat-send` `#join-lobby-match` `#lobby-ranked-match` `#leave-lobby-match` `#back-to-main-from-lobby`；委托 click：`.lobby-player[data-username]`→`showUserProfile`、`.lobby-room-join`→`joinLobbyRoom`、`.lobby-match-spectate`→`joinSpectate`；`#lobby-chat-input` 回车→`sendLobbyChat` |
| 收 | `lobby_hello`（`gameState.lobbyKey`）、`lobby_state`、`lobby_chat_history`、`lobby_chat`、`match_queued`、`match_canceled` |
| 发 | `lobby_subscribe` / `lobby_unsubscribe` / `lobby_refresh` / `lobby_create_room` / `join_room` / `lobby_chat_send` / `find_match` / `cancel_match` |
| 进入 | `showLobby()`（`switchScreen` + `lobbySubscribed = true` + `lobby_subscribe`）；入口：导航 `a[href="/lobby"]`、`#lobby-btn`、`popstate`、初次路由 |
| 销毁 | `switchScreen` 里的 `leaveLobbySubscription()`（`switchScreen` 之外的路径不会退订，与观战/回放同形状） |

### 3.2 好友房 `#custom-room-screen`

| 项 | 内容 |
| --- | --- |
| 容器 id | `#custom-room-screen` › `.button-group`（`#custom-create-room` `#custom-join-room`）· `#custom-room-id-input`（`#custom-room-code` `#custom-confirm-join`）· `#custom-room-info`（`#custom-current-room-id`、`#invite-link-row`（`#copy-invite-link` `#invite-link-text` `#invite-link-msg`）、`#custom-close-room-row`（`#custom-close-room` `#custom-close-room-msg`））· `#back-to-main` |
| 监听 | click：`#custom-create-room` `#custom-join-room` `#custom-confirm-join` `#custom-close-room` `#copy-invite-link` `#back-to-main` |
| 收 | 无专属监听。靠 `game_state`（`waiting` / `placing_ships`）与 `room_sync` 推进 |
| 发 | `create_room` / `join_room` / `close_room` |
| 进入 | `showCustomRoomWaiting(roomId)`（大厅建房/入房 ack 后）· `joinRoomById()`（`?room=` 与 `friend_invite` 共用）· `#custom-room` 按钮 |
| 销毁 | `game_state` 任意态 / `applyRoomSync` / `reset_gameboard` 都会隐藏两个面板；没有监听器需要拆除（都是一次性绑定） |

### 3.3 布船 `#ship-placement-screen`（+ `#match-success-screen` + `#rps-screen` 同一流程）

| 项 | 内容 |
| --- | --- |
| 容器 id | `#ship-placement-screen` › `#player-board`（36 个 `.cell[data-x][data-y]`）· `#ships-placed`（`#placed-count` `#total-ships`）· `.placement-actions`（`#random-ships` `#confirm-ships`）<br>`#match-success-screen` › `#opponent-info` `#opponent-chips` `#match-self-rank` `#countdown-timer` `.countdown-bar > .countdown-fill` `#start-now`<br>`#rps-screen` › `.rps-choice[data-choice]` `#rps-waiting` `#rps-result` `#rps-round` |
| 监听 | `#player-board` 委托 click→`handleCellClick` · `#random-ships` · `#confirm-ships` · `.rps-choice` ×3（读 `data-choice`） |
| 收 | `game_state`（`placing_ships` / `rock_paper_scissors` / `attacking`）、`room_sync`、`reset_gameboard`、`rps_result` |
| 发 | `place_ships`（`{room_id, player_id, ships}`）、`rps_choice` |
| 进入 | `game_state{placing_ships}`（含 5 秒倒计时 → `initBoard`）· `applyRoomSync` · `reset_gameboard`（绝处逢生） |
| 销毁 | 无定时器需要拆；`initBoard` 会重建 36 格 |
| ⚠️ 冻结 | `#player-board` 是**布船**棋盘；对局自己的棋盘是 `#game-player-board`（两个 id 别混） |
| ⚠️ 冻结 | `#ships-placed` 是外层 `<p>`，JS 只写 `#placed-count`（写外层会毁掉子元素） |
| ⚠️ 死代码 | `#start-now`（匹配成功屏的「立即开始」）**没有任何 JS 接线**，`#placement-hint` / `#invite-link-text` / `#custom-close-room-msg` 同样无生产者 —— 本轮不新增行为，也不删元素 |

### 3.4 图鉴（`#help-modal` 内的 `#help-magic-cards`）

| 项 | 内容 |
| --- | --- |
| 容器 id | `#help-modal` › `.modal-content.wide-modal` › `#help-content` › `#compendium-search` `#compendium-sort` `#compendium-speed` `#compendium-type` `#compendium-count` · `#help-magic-cards` · `#help-rank-section`（`#help-rank-tiers` `#help-rank-scoring{-win,-lose}` `#help-rank-error`） |
| 监听 | 打开：`#help-btn` click → `closeOverlaysExcept('help-modal')` + `renderCardCompendium()` + `loadCardUsage()` + `renderRankHelp()`；关闭：`#help-modal-close` / 遮罩 click；筛选：`#compendium-search|sort|speed|type` 的 `input` + `change` → `renderCardCompendium` |
| 数据 | `window.magicCards`（`static/magic_cards.js`，43 条 / 41 唯一）· `GET /api/card_usage`（一次性缓存）· `GET /api/rank_constants` · `GET /api/profile`（解锁文案）· 卡面 `applyCardArt()` + `window.CARD_ART_MAP` |
| 卡条目契约 | `.magic-card-help[data-card-name][data-card-speed][data-card-type][data-card-uses]` › `.magic-card.codex-card` › `.card-art`（`--card-art-image`）`+ .card-nameplate + .card-desc + .card-typebar` |
| 销毁 | 弹窗只是 `.hidden`；卡片事件一次性绑定（当前**没有**卡片点击行为） |

### 3.5 排行 `#leaderboard-screen`

| 项 | 内容 |
| --- | --- |
| 容器 id | `#leaderboard-screen` › `#leaderboard-tabs`（`#lb-tab-record` `#lb-tab-ranked`）· `#leaderboard-container`（`#leaderboard-table` `#leaderboard-error`）· `#leaderboard-ranked-container`（`#ranked-table` `#ranked-error`）· `#back-to-main-from-leaderboard` |
| 监听 | `#leaderboard-tabs` 委托 `.lb-tab[data-tab]`→`setLeaderboardTab`；`#back-to-main-from-leaderboard`；行委托（`bindLeaderboardUserClick` / `bindRankedUserClick`，`dataset.userClickBound` 保证只绑一次） |
| 数据 | `GET /api/leaderboard` · `GET /api/ranked_leaderboard?limit=100&offset=0`（`rankedFetchToken` 防竞态） |
| 进入 | 导航 `a[href="/leaderboard"]` 委托 click / `popstate` / 初次路由 → `showLeaderboard()` |
| 状态 | 加载行、`.ranked-empty`、错误 div（保留上一帧）、游客可用 |

### 3.6 档案（查看面 `#opponent-stats-modal` + 编辑面 `#profile-modal`）

| 项 | 内容 |
| --- | --- |
| 容器 id | 查看面：`#opponent-stats-modal` › `.modal-content.pf-view-modal` › `#opponent-stats-title` `#opponent-stats-content`（注入 `#profile-view` 卡片树）；编辑面：`#profile-modal` › `.profile-modal-card` › `#profile-edit`（`.pf-editor-nav` 4 项 + 4 个 `.pf-pane`）· `.pf-edit-foot`（`#profile-card-save` `#profile-edit-cancel` `#profile-save-msg`） |
| 入口（4+1） | `#show-profile` / `#cmdr-card-btn` / 对局内 `#avatar-corner` `#opponent-avatar-corner` / `#show-user-stats` / 排行与大厅行委托 |
| 数据 | `GET /user_stats[?username=]` · `GET /api/profile` · `POST /api/profile/card` · `POST /api/profile/signature|avatar|like` · `GET|POST /api/profile/message(s)` · `GET /api/friends` |
| 进入/销毁 | 查看面 `showUserProfile()` → `closeOverlaysExcept('opponent-stats-modal')`；编辑面 `openMyProfileEditor()` → `closeOverlaysExcept('profile-modal')`；保存后 `setProfileMode('view')` + 重开查看面（跨入口刷新即靠这条） |

### 3.7 结算 `#game-over-screen`

| 项 | 内容 |
| --- | --- |
| 容器 id | `#game-over-screen.screen.over-screen` › `.over-wrap`（`.over-head#over-head` `#game-result` `#over-sub` `#over-opponent` `#over-opp-rank` `#over-duration`）· `.over-cols`（`#achievement-unlock-panel` `#xp-gain-panel`（`#xp-delta` `#xp-bar-fill` `#xp-progress-text` `#xp-breakdown` `#xp-levelup` `#xp-from` `#xp-to`） `#rank-gain-panel`（`#rank-delta` `#rank-icon-before/after` `#rank-bar-fill` `#rank-progress-text` `#rank-promote` `#rank-clamp-note` `#rank-admiral-note`） `.over-stats`（`#over-stat-round` `#over-stat-fire` `#over-stat-ships`））· `.game-over-buttons`（`#play-again` `#return-to-menu`；`#recent-opponent-add` 由 JS 插为**兄弟**节点） |
| 收 | `game_over`（`winner` / `reason`）· `game_state{game_over}` · `room_sync` · `achievements_unlocked` · `xp_gained` · `rank_changed` · `recent_opponent` |
| 销毁 | `resetGame()`：清 `pendingUnlockBadges`、`xpAnimToken++`、`hideRankGainPanel()`、隐藏经验面板、断开 socket、`location.href='/'`（整页重载） |
| ⚠️ 冻结 | 屏幕内所有 id 由 HTML 注释冻结；`.over-screen` 类名必须留 |

### 3.8 观战 `#spectate-screen`

| 项 | 内容 |
| --- | --- |
| 容器 id | `#spectate-screen`（类名字面量冻结）› `.spectate-topbar`（`#spectate-phase` `#spectate-turn` `#spectate-attacks` `#spectate-field-magic` `#spectate-count` `#spectate-limit` `#spectate-leave`）· `.spectate-players`（`#spectate-player-{1,2}` `#spectate-name-{1,2}` `#spectate-ships-{1,2}` `#spectate-hand-{1,2}`）· `.spectate-body`（`#spectate-board-{1,2}` `#spectate-board-title-{1,2}` · `.spectate-side`：`#spectate-roster-count` `#spectate-roster` `#spectate-chat` `#spectate-chat-input` `#spectate-chat-send` `#spectate-chain` `#spectate-logs`） |
| 发 | `spectate_join` / `spectate_leave` / `spectate_chat_send` |
| 收 | `spectate_sync` / `_count_changed` / `_roster` / `_you` / `_joined` / `_left` / `_chat` / `_ended` / `_board` + `attack_result` `magic_chain_updated` `chain_resolved` `game_log` `turn_change` `phase_updated` `field_magic_updated` `game_over` `chat_message`（除 `spectate_*` 外全部 `active` 门控） |
| 不变量 | 净化快照只带 `{seat_id,name,remaining_ships,hand_count,attacks}`；前端 `spectateCellOf` 白名单 `{x,y,hit,ship_sunk}`，`spectateRebuildBoardAttacks()` 是**唯一**的转置点（`board_attacks.p1 = attacks.p2`），未命中的格子留空 |
| 销毁 | `leaveSpectateScreen()` 清状态 + 抹 DOM + 回大厅；**无定时器**。⚠️ 走导航离开不会清 `gameState.spectate.active` |

### 3.9 回放 `#replay-screen`

| 项 | 内容 |
| --- | --- |
| 容器 id | `#replay-screen` › `#replay-players-title` `#replay-status` · `.replay-topbar`（`#replay-source` `#replay-step-index` `#replay-step-total` `#replay-step-kind` `#replay-step-actor` `#replay-truncated` `#replay-speed-group`（`.replay-speed-btn[data-replay-speed]`））· `.replay-players`（`#replay-name-1/2` `#replay-ships-1/2`）· `.replay-body`（`#replay-board-1/2` + `#replay-hand-title-1/2` `#replay-hand-1/2` `#replay-current` `#replay-logs`）· `.replay-controls`（`#replay-prev` `#replay-play` `#replay-next` `#replay-track`（`#replay-track-fill` `#replay-track-nodes` `#replay-track-thumb`））· `#replay-node-tip` · `#replay-leave` |
| 数据 | `GET /api/replay/<match_id>`（**无 socket**，`tests/test_replay_frontend.py` 守这条）+ `GET|POST /api/replay/setting` |
| 进入/销毁 | `openReplayForMatch()` → `switchScreen` + fetch；`leaveReplayScreen()` → `resetReplayState()`（杀 `replayState.timer`）+ 断开捕获的 socket + 回首页 |
| ⚠️ 隐患（本轮**不改行为**，只记录） | 走导航/`popstate` 离开不会拆回放定时器；`switchScreen` 也不清 `gameState.spectate.active` |
| ⚠️ 冻结 | `REPLAY_STEP_MS = 900`、`REPLAY_SPEEDS = [1,2,4]`、`#replay-board-1/2` 三条由 pytest 守 |

### 3.10 设置 `#settings-modal`

| 项 | 内容 |
| --- | --- |
| 容器 id | `#settings-modal` › `.settings-modal-card` › `.settings-wrap`（`.settings-nav` 4 项 `look/sound/wp/acct` + `.settings-panes`）· `#settings-save-btn` |
| 各分区 | `look`：`#theme-preset-grid`（`.theme-group[data-group]` ×2）`#primary-color-picker` `#theme-preset-hint`｜`sound`：`#music-volume` `#volume-display` `#music-loop-mode` `#music-toggle-play` `#music-next` `#music-previous` `#music-muted` `#sfx-muted` `#current-track`｜`wp`：`#wp-section` 一整套（`#wp-now-playing` `#wp-opacity` `#wp-dim` `#wp-blur` `#wp-fit` `#wp-scan` `#wp-toggle-play` `#wp-clear` `#wp-list` `#wp-path(-import)` `#wp-url(-import)` `#wp-status`）｜`acct`：`#change-password-form`（`#old-password` `#new-password` `#change-password-msg`）`#settings-allow-spectate` `#settings-spectate-msg` `#settings-allow-replay` `#settings-replay-msg` `#settings-goto-profile` |
| 入口 | `#settings-btn`（look）· `#music-btn`（sound）· `#wallpaper-btn`（wp）· `#profile-goto-account`（acct） |
| 数据 | `GET|POST /api/spectate/setting` · `GET|POST /api/replay/setting` · `POST /api/change_password` · `GET /api/wallpapers` `POST /api/wallpaper/scan_path` · 音频走 `window.bgMusicPlayer`（`static/music_player.js`） |
| 持久化 | `localStorage`：`theme` `battleship_theme_preset` `bgm_volume` `bgm_loop_mode` `bgm_muted`…；观战/回放权限走**服务端返回值**（不回显本地猜测） |

---

## 4. 旧文档与当前代码的冲突（以代码为准）

| 旧说法 | 实际 |
| --- | --- |
| `docs/C_ARENA_SCREENS_2026_09_28.md` §1「面板 = 12px 圆角」 | 与示意稿一致，本轮沿用 12px；只有 `.sea`/海面用 14px |
| 同文 §1 表格写 `.ach` 用 `--arena-line-dash` | 令牌存在（`--arena-line-dash`），本轮直接复用 |
| `templates/index.html:314-316` 注释说 `#invite-link-text` 会被填入邀请链接 | **从未被读写**；`copyInviteLink()` 用 `navigator.clipboard`，兜底走 `window.prompt` |
| `templates/index.html:326-327` 注释说解散房间有确认弹窗 | `closeCustomRoom()` 直接 `close_room`，没有二次确认 |
| `#placement-hint` 是布船提示 | JS 与 CSS 都没引用它；`.placement-hint` 的样式属于**局内**动态浮层 `#placement-prompt` |
| `#start-now`「立即开始」按钮 | 无任何 JS 接线（点击无反应） |
| ADI「双方准备」 | 正式房间状态机 `waiting → placing_ships → rock_paper_scissors → attacking → game_over` 里**没有 ready 位**；实施方案 §2 已要求按现有机制展示、不新增握手协议 |

---

## 5. 实测记录

### 5.1 改前（本基线，2026-09-29 实测）

- `python -m pytest tests/ -q` → **2622 passed / 1 failed**（66.17s）
- `node tools/fluent_css_metrics.mjs` → hex 100 / rgba 89 / !important 31 / dupSel 31（PASS）
- `node tools/dom_contract_check.mjs` → 通过
- `node tools/codex_realcard_check.mjs` → 改前已加入（本轮唯一改到它的是图鉴容器，见下）
- `node tools/card_compendium_check.mjs` → **1 FAIL：写死的「43 条目 / 41 唯一」与 50/48 的卡表不符**
  （`a1fbc4e` 之后一直如此，本轮按 `codex_realcard_check` 的既有口径重定为现算）
- `node tools/spectate_check.mjs` → 改前即 **8 FAIL**（连锁簇；本轮以"关掉该屏 C+ 层"做对照，
  红的还是那 8 条，见实施记录 §6.1）
- `node tools/wallpaper_check.mjs`（**不带 `--url`**）→ 改前即 **3 FAIL**（BMP 缩略图解码；
  本轮以 HEAD worktree 做对照，完全一致，见实施记录 §6.2）
- `node tools/friend_invite_battle_check.mjs` → 改前 **43 PASS / 5 FAIL**。⚠️ 那 5 条的根因是
  **这支工具的 python 陪练 `invite_occupy_probe.py` 从未入库**（干净检出上必然全红），
  本轮补进版本库并指向 `tools/` → **49 PASS / 2 FAIL**；剩下 2 条（场景③重新邀战那一局）
  以 HEAD 对照确认改前就有。见实施记录 §6.5。
- `node tools/ranked_check.mjs` → 改前即 **3 FAIL**（数据驱动：库里没有顶端段位玩家 /
  工具自建的第二个账号没落上；HEAD 对照一致，见实施记录 §6.4）

### 5.2 改后

见 `docs/C_PLUS_SCREENS_REPORT_2026_09_29.md` §6（含每支工具的结果与两条对照实验的做法）。
