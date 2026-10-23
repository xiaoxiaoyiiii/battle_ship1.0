# 原 main 界面迁进 Vue 框架：当前状态与验证记录

> 本文件记录**当前提交的实际状态**。历史过程（第一轮迁壳层、第二轮对局结构、第三轮可达性修复）
> 统一收在文末「九、历史小节」，不与当前结论混排。
> 分支 `feature/main-ui-vue-port` → PR #19（draft，base `review/fork-cloud`）。

## 一、结论速览

- 桌面（宽 ≥1200 且高 ≥700，判据同原 `static/adaptive_layout.js`）：对局双棋盘并排、己方在左、
  可直接点己方舰格；左列常驻游戏日志；右列连锁结算 / 卡牌详情 / 计数 / 主行动；底部扇形手牌。
- 紧凑档（不满足上面的宽高）：单棋盘 + 海域标签，底部操作条 + 日志/聊天/弃牌抽屉，
  卡牌详情为底部 sheet，选目标时收起手牌与主行动条把位置让给目标面板。
- 周边：好友（含实时私聊、>50 条历史分页）、玩法与段位帮助（服务端常量 + catalog 解锁）、
  图鉴（速阶/类型独立筛选、使用次数排序、点卡详情）、设置（主色 + 棋盘/命中/主行动预览）、
  反作弊管理（管理员才可见）。
- 保留的三项 fork 能力：卡牌不可用原因、右下角全局通知、首页分区易点排版。

## 二、验证（本轮可复跑，2026-10-23 09:10）

环境：独立栈端口 **5458**，独立库 `.tmp/r3.db`，`ENABLE_TEST_EVENTS=0`，生产构建
（`corepack pnpm --dir frontend build`）；管理员检查时用 `DEBUG_ADMIN_USER_IDS=<临时管理员 id>` 重启同一栈。
脚本目录：`D:/Codex workspace/battle-ship-main-vue-verification-20261023`。

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 审查批定向检查 | `BASE_URL=http://127.0.0.1:5458 node spec-review3.mjs all` | **PASS**（24 项：a0–a3 / b1–b4 / c1–c3 / d1–d4 / e1–e4 / g1–g3） |
| 管理员入口 | `BASE_URL=http://127.0.0.1:5458 ADMIN_USER=<adm> ADMIN_UID=<uid> node spec-admin.mjs` | **PASS**（a0/b0/b1 + c1–c5） |
| 回归（连锁/缩放/护盾） | `BASE_URL=http://127.0.0.1:5458 node spec-regressions.mjs` | **PASS**（12/12） |
| 桌面双棋盘 | `node spec-dual-board.mjs 1440x900 1920x1080` | PASS（两块 361px、己方在左、己方舰格 14/14 可命中） |
| 紧凑档几何 | `node spec-compact.mjs` | PASS（390×740 / 360×640 / 844×390 无重叠、主操作可命中、无整页滚动） |
| 浮层可达性 | `node spec-sheet.mjs` | PASS（手机详情 + 连锁 5 个按钮全部 `elementFromPoint` 命中） |
| 选目标可达性 | `node spec-target-compact.mjs` | PASS（神之宣告/神威！：36 格全可点、点击被接受） |
| 浮动聊天拖动 | `node spec-floating-chat.mjs` | PASS（拖到 `x=1132` 被夹在视口内） |
| 社交/帮助 | `node spec-social-help.mjs` | PASS（真实双账号加好友、私聊、9 段阶梯 + 7/7 计分） |
| 图鉴/设置 | `node spec-collection-settings.mjs` | PASS（筛选/排序/详情、主色切换与恢复） |
| 真实对局（桌面/手机） | `node flows/port-match.mjs wide` / `phone` | PASS（首页 → 人机 → 布船 → 猜拳 → 进战斗 → 开炮 → 日志/计数 → 详情 → 无控制台错误） |
| 内容态取证 | `node flows/content-screens.mjs` / `node flows/replay-content.mjs` | 结算/资料/回放有内容；观战本仓仅空态（见下） |
| 类型检查 | `cd frontend && corepack pnpm typecheck` | 退出 0 |
| 生产构建 | `cd frontend && corepack pnpm build` | `[cards] up to date (50 cards)` / `[contract] OK` / `✓ built`，退出 0 |
| 空白检查 | `git diff --check` | 退出 0 |

### 观战（真实链路，证据不在本仓）

Codex 用公开注册/登录/建房/布船/猜拳/攻击接口造两位真实玩家 + 一位真实观众，在
`ENABLE_TEST_EVENTS=0` 的独立库上跑通观战：72 格双棋盘、攻击实时更新、390×740 切视角、观战聊天，
`pageErrors=[]`。脚本 `codex-real-spectate.mjs`，截图 `codex-r2-shots/real-spectate-1440x900.png`、
`real-spectate-390x740.png`。本仓 `content-spectate-1440x900.png` 只是空态截图。

## 三、截图来源（逐类标注）

| 截图 | 来源 |
| --- | --- |
| `shots/port-*.png`、`shots/sheet-*.png`、`shots/friends-*.png`、`shots/help-*.png`、`shots/collection-detail-*.png`、`shots/settings-preview-*.png`、`shots/admin-1440x900.png`、`shots/content-*.png` | **真实服务器链路**：5458 独立栈 + 真实临时账号（`QA_*`、`adm_*`），必要时先做真实操作（加好友、发消息、打一局人机、点卡、处置）再截图 |
| `shots/fan-*.png`、`shots/float-chat-*.png`、`shots/dual-*.png`、`shots/compact-*.png` | **夹具**：`fixtures/game-layout.js` / `fixtures/hand-eight.js` / `fixtures/chain-nonempty.js` 注入战场状态，用于布局与可达性量测（夹具只写浏览器内状态，不碰服务端数据） |
| `shots/screens-*.png` | 逐屏巡检（每条路由真实加载，未造对局） |
| `codex-r2-shots/real-spectate-*.png` | 真实观战链路（Codex 生成，见上） |

## 四、本轮（审查第三批）修了什么

1. **私聊切换竞态（P1）**：新增 `frontend/src/stores/dm.ts`，每会话一个递增 token + `AbortController`，
   迟到回包不再覆盖当前会话；`send` 捕获发起时会话，回包只落回该会话；切换不清空新会话草稿。
2. **私聊实时收信 + 刷新更新**：新增 `frontend/src/realtime/friends.ts`，复用共享 socket 订阅
   `friend_message` / `friend_request`（引用计数释放）；刷新会重读当前会话。
3. **>50 条历史**：「加载更早的消息」按 `before=<最早 id>` 翻页，`mergeMessages` 按 id 去重升序，
   与实时消息合并。
4. **真实牌栈下「收起」失效**：`chainHasContent` / `chainPanelOpen` 统一展开语义，收起只改可见性，
   请求、倒计时、重开入口都保留。
5. **帮助段位信息**：顶段显示服务端 `admiral_rank_limit` / `admiral_min_captains` 的晋升条件；
   各段解锁项取 `/api/profile` 的 `catalog`；游客如实提示，不编造阈值。
6. **管理员入口**：新增 `frontend/src/components/AdminOverlay.vue`（嫌疑度总览 / 玩家详情 / 手动处置 /
   干预历史 / 违规记录），入口只在 `/api/admin/me` 返回 `is_admin` 时渲染，服务端鉴权未改。
7. **手牌事实核对**：`useHandFan.ts` 早有 `selectedIndex` 与 `need = w + HAND_TAP_MIN`；
   用 8 张重叠手牌实测（不溢出、选中牌与右邻居都可点），此前「选中加宽未实现」的说法有误，已更正。

## 五、已知差异（当前仍存在）

1. 紧凑档单棋盘：与 main 的 `adaptive_layout.js` 同类；桌面必须双棋盘，由 `spec-dual-board.mjs` 钉住。
2. 日志用左列常驻卡（main 是可拖浮动窗），聊天是浮动窗 + 紧凑档抽屉：为避免遮挡棋盘的有意选择。
3. 弃牌堆数量服务端未下发 → 计数显示「—」，另给「查看弃牌堆」。
4. 人机局不计段位分，资料页战绩为 0（规则）；段位进度条需真实排位局。
5. 管理员处置历史的 `actor` 显示账号 id（后端原样返回，与原 main 一致）。
6. 仓外 22 条 `data-testid` 浏览器门禁未跑（本机无 `D:/develop/battleship-verify` 基线）。

## 六、迁移模块清单（新增/改动）

- `screens/game/useAdaptiveGameLayout.ts`（1200×700 判据 + 棋盘模式预算）、`useHandFan.ts`（扇形手牌）、
  `useFloatingDrag.ts`（浮动窗拖动）
- `stores/dm.ts`（私聊会话：竞态防护 / 分页 / 未读 / 草稿）、`realtime/friends.ts`（好友与私信推送）
- `components/HelpOverlay.vue`、`components/FriendsOverlay.vue`、`components/AdminOverlay.vue`
- `components/CardCollectionOverlay.vue`（筛选/排序/详情）、`screens/settings/SettingsScreen.vue`（主色 + 预览）
- `screens/game/GameScreen.vue` + `game-screen.css`（main 对局结构：HUD / 场地条 / 双棋盘 / rail / 手牌 / 浮窗）

## 七、历史小节（过程记录，不代表当前结论）

1. **第一轮**：壳层令牌 + 首页三栏 + 对局改 main DOM（双棋盘雏形）→ 提交 `578ff98`、`3d9c391`。
2. **第二轮**：紧凑档三处可达性（详情 sheet、连锁浮层、选目标）+ 日志判据修正 → 提交 `56229fc`、`23115e1`。
3. **第三轮（R1/R2）**：composables、好友/帮助/图鉴/设置迁移、逐屏取证 → 提交 `c527437`；
   随后补极矮横屏手牌与 sheet 叠层 → 提交 `c80ad9e`。
4. **审查第三批（本提交）**：私聊竞态/实时/分页、非空连锁收起、帮助顶段、管理员入口、手牌核对。

> 说明：前几轮报告里写的「紧凑档 ≤719px / ≤520px」「聊天只有抽屉」「测试栈 5455」等描述
> 都已被后续提交取代，当前结论以上面第一、二节为准。

## 八、审查轮第四批（2026-10-23 09:52，基点 776bf06）

### 8.1 三项交互（先复现失败，再修，再跑同一路径）

| 项 | 根因 | 修法 | 证据（命令 / 结果） |
| --- | --- | --- | --- |
| 取消分页后 `loadingOlder` 永久锁死 | 只有一个 `token`：新 `open` 顶掉令牌，旧 `loadOlder` 直接 `return`，`finally` 不存在 | `stores/dm.ts` 改为 `openSeq`/`olderSeq` 两套序号 + `controllers` 键 `${kind}:${name}`，收尾只清自己那次 | `node spec-review4.mjs pagination` → PASS 2（held=1 证明 race 路径被走到；迟到的「更早一页」仍被合并到 70 条，「加载更早」不残留 disabled/「正在读取」） |
| 只有链栈、没有响应窗口时收不起 | `match.collapseChainWindow()` 只在 `chainWindow` 存在时写 collapsed | 改为无条件写视图状态；入口由组件 `chainHasContent` 控制；重开文案区分「待响应」与「连锁结算（第 N 张）」 | `node spec-review4.mjs chain` → PASS 5（非空链栈 1 张、收起后 overlay=0/reopen=1、链栈未清空、文案不含「待响应」） |
| 私聊实时生命周期与标读 | 只在面板挂载时订阅；关闭即 `off`；当前会话收到 push 只合并不标读 | `App.vue` 登录期间常驻 `acquireFriendsChannel`；`dm.setVisible` 区分「面板是否可见」；当前可见会话才 `POST /api/friends/messages/read`（在途 pending 补发）；关闭时累计未读 + 通知 + 导航角标 | `node spec-review4.mjs lifecycle` → PASS 6（打开时可见且 unread=0、关闭后 unread=1 + 通知 + 角标 1、重开后可见且 unread=0） |

### 8.2 原 main 对局区域迁移（本轮补齐）

| main 区域 | Vue 实现 | 证据 | 仍存在差异 |
| --- | --- | --- | --- |
| 对手身份顶条 + 己方舰队摘要（`players-info`/`arena-fleet-head`/`arena-pips`） | `.hud-players` 内两个 `.arena-player`（头像首字、名字、剩余舰、pips 方块），宽屏为顶栏下方独立一行；手牌左侧 fixed `.arena-fleet` | `shots/main4j-1907x996-detail.png`、`shots/port-1440x900-game.png`（真实对局） | 已接真实头像与战绩弹窗（`usePlayerCards.ts`，走 `/user_stats`）；仅当服务端下发 `opponent_registered=true` 且非人机才查 `/user_stats`；人机/游客/无对手退回首字并给文案，同名游客不再显示他人资料（见 8.5） |
| 左侧聊天 + 可拖动/可收起日志（原为两块浮动窗） | `.game-float` + `useFloatingDrag`：聊天（左上，默认常驻、可关；快捷语从输入行按需展开并跟随浮窗）、日志（其下，可拖/可收起/可放大；两者位置记入 localStorage `in_game_chat_pos`/`game_log_pos`，缩放后夹回视口） | `spec-floating-chat.mjs` PASS；真实两账号链路里拖动→刷新→位置恢复 PASS | 紧凑档仍是抽屉，但抽屉改为 `position:fixed`，任意滚动位置打开都可见 |
| 竖向连锁轨道（`arena-chain-slot`） | 宽屏右列拆 `96px` 轨道 + 操作列；空态保留高度，叠牌 `76×114`、`-38px` | `shots/main4j-1907x996-detail.png`、`spec-review4.mjs chain` | 轨道比原 main 的叠牌比例略小 |
| 独立完整卡牌详情（`style.css:1821-1841`） | 卡名 → `156px` 宽、2:3 卡面 → 规则（局部滚动）→ 使用/取消；`shot` 里卡面 158px 高 | `shots/main4j-1907x996-detail.png`（face 156×234）、`port-1440x900-detail.png` | 极小高度时卡面按 `max-height:158px` 缩放 |
| 手牌完整原画 + 扇形 | `useHandFan` 保留；`.card--art` 隐藏重复文字层，`card__art` 铺满；不可用原因缩成底部深色小条 | `shots/main4c-390x740.png`、`port-390x740-detail.png`（`reason:true`） | 无卡图时回退文字卡 |
| 中场比例与操作列 | `.game-main-container` 左留 300px 给浮窗；`.arena-rail` 96+190 网格 | `shots/main4j-1907x996-detail.png` | 与 main 的 308/320 留白略有差异 |

### 8.3 证据口径（逐类标注）

- **真实服务器链路**（独立库、`ENABLE_TEST_EVENTS=1` 仅用于对局夹具以外）：`shots/port-1440x900-*`、`shots/port-390x740-*`（`flows/port-match.mjs` 真实走完首页→人机→布船→猜拳→战斗→开炮）。
- **夹具布局**（注入 `game_state`，仅为把棋盘/手牌填满）：`shots/main4*.png`（1907×996 / 1440×900 / 390×740 / 360×640 / 844×390）。
- **纯几何门禁**：`spec-dual-board.mjs`、`spec-compact.mjs`、`spec-sheet.mjs`、`spec-target-compact.mjs`、`spec-floating-chat.mjs`、`spec-review4.mjs`。
- 入库副本：`docs/screenshots/main-ui-restoration/r4/`（8 张 JPEG）。

### 8.4 原 main 对照图

- 原 main：`main-ui-reference-d16f706/docs/readme/04-game-live.png`（1907×996）。
- 新版同视口：`docs/screenshots/main-ui-restoration/r4/vue-1907x996-game-detail.jpg`（1907×996）。

### 8.5 当前结论（R2，替代前面各轮对应断言）

- 头像 / 战绩：已接。顶栏与舰队卡显示账号真实头像，点头像或「战绩」开弹窗；极窄/极矮档身份条隐藏，入口在「更多操作 → 对手战绩」。
- 快捷语：默认不常驻，输入行按钮展开，跟随聊天浮窗，发送成功后收起。
- 浮窗位置：日志 `game_log_pos`、聊天 `in_game_chat_pos`，刷新恢复，缩放/旋转后夹回视口。
- 紧凑档抽屉（聊天/日志/弃牌共用 `.game-drawer`）：原为 `.game` 内 absolute，`.game` 滚动后打开会把标题与关闭按钮顶出视口（360×640，scrollTop=125，关闭钮中心 y=-2）。现为 `position:fixed`。证据：`drawer-scroll.mjs` 在旧样式下 360×640 的聊天/日志/弃牌各 FAIL（关闭钮不在视口），新样式 360×640、390×740、844×390 共 21 项 PASS，全部为真实滚轮 + 真实 `mouse.click`，不回滚到顶部。
- **已解（对手资料归属，R3）**：局内 `opponent_name` 仍只是显示昵称，不作身份。服务端在入座时按认证连接（`Connection.user_id`，会话签名）给 `Player.registered`（默认 false；`services/rooms.py` create_room/join_room/同身份重入，`services/matchmaking.py` 排队项→入座；人机恒 false），**不能**用 `Player.user_id` 判断——自定义房游客的 `user_id` 就是 sid，非空。`opponent_seat_state` 同处加性输出 `opponent_registered`（`game_state` 与 `room_sync` 一致，追加在 `opponent_online` 之后；无对手/人机/游客为 false）。已登录排队项的名字改取认证用户名，游客仍用自填昵称。前端 `usePlayerCards` 仅在 `opponent_registered===true` 且非人机时查 `/user_stats`，否则中止在途请求并清空旧资料；缺字段按 false。座位键约定与结算未动。