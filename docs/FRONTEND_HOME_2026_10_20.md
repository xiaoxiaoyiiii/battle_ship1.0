# 首页屏（票 #26）

> 适用：`frontend/src/screens/start/`、`stores/home.ts`、`realtime/home.ts`。
> 本票把 `/`（路由名 `start`，冻结于 #21）从占位迁成**三栏首页**：
> 左「指挥官」· 中「开一局」· 右「在线 + 最近公告」。
> 首次进入时 DOM 顺序是 **中 → 左 → 右**（窄屏先能开一局），三栏的左右关系由
> CSS `grid-template-areas` 指定，不依赖 DOM 顺序。

## 1. 数据流（没有一处是编的）

| 区块 | 接口 / 事件 | 用到的字段 |
| --- | --- | --- |
| 在线面板 | `GET /api/home_stats` | `online_count` / `queue.{casual,ranked}` / `lobby_rooms` |
| 顶栏胶囊 | `GET /api/online_count` | `online_count`（与 `/api/home_stats` 读同一张 presence 表） |
| 指挥官名片 | `GET /api/profile` | `username` / `rank_info.{label,progress,sub_points}` / `level_info.{level,into,need,ratio}` / `wins` / `losses` / `longest_streak` |
| 最近公告 | `GET /api/changelog?limit=3` | `latest` / `entries[].{date,items}` |
| 匹配队列 | `match_queued` / `match_canceled` | `mode` |
| 拒绝提示 | `error` 帧与 `find_match` ack 的 `message` | 原文直出 |

* 读请求全部在 `stores/home.ts` 里，屏只读 Pinia；`StartScreen.vue` 里**没有 fetch**。
* 屏幕只排版服务端值：段位文案用 `rank_info.label`，等级/进度用 `level_info`，
  段位条宽度 = `progress / sub_points`，等级条 = `ratio`（都是服务端字段）。
  唯一的两处算术是「胜率百分比」和「进度条百分比」的取整。
* 缺失值一律 `null` → 渲染 `—`；**失败不会把面板消掉**（`/api/home_stats` 失败时
  显示三行 `—` + 一行说明，profile 失败显示可读提示，公告失败显示空态）。

## 2. 入口与真实行为

| 入口 | 行为 |
| --- | --- |
| 休闲匹配 | `find_match {mode:'casual'}`；`match_queued` 后按钮置灰、显示取消；`cancel_match` 复位 |
| 排位对战 | `find_match {mode:'ranked'}`；游客会被服务端拒绝并显示原文「排位模式需要先登录」 |
| 人机对战 | `create_ai_room {difficulty}` + `join_room`（与旧栈 aiMatch 同两步），收到 `game_state{placing_ships}` 后进 `/placement` |
| 游戏大厅 / 排行榜 / 设置 | 现有路由 `lobby` / `leaderboard` / `settings` |
| 去登录 / 查看名片 | `/login`（迁移窗口内的旧页面）与现有路由 `profile` |

* 匹配成功后由 `game_state{placing_ships}` 驱动跳转，前端不自己判断配对。
* 人机难度沿用旧栈四档：`easy` / `normal` / `hard` / `master`。

## 3. 选择器契约（data-testid）

屏根：`screen-start`（同时带 `data-screen="start"`）。

| testid | 用途 |
| --- | --- |
| start-heading | 标题 |
| start-connection-status | 实时连接状态（`data-connected`） |
| start-online-pill | 顶栏在线人数（`/api/online_count`） |
| start-actions / start-primary-action / start-ranked-action | 主行动入口 |
| start-ai-action / start-ai-difficulty | 人机与难度 |
| start-queue-status / start-queue-cancel | 排队与取消 |
| start-notice | 服务端拒绝/错误原文 |
| start-lobby-link / start-leaderboard-link / start-settings-link | 次级入口 |
| start-player / start-player-name | 指挥官面板与名字 |
| start-player-guest / start-player-error / start-player-loading | 游客 / 读取失败 / 读取中 |
| start-login-link / start-profile-link | 登录与名片入口 |
| start-player-rank / start-player-rank-fill | 段位文案与进度 |
| start-player-level / start-player-level-text / start-player-level-fill | 等级、本级进度与经验条 |
| start-player-record / start-player-winrate / start-player-streak | 战绩 / 胜率 / 最长连胜 |
| start-online / start-online-count | 在线面板 |
| start-queue-casual / start-queue-ranked / start-lobby-rooms | 两个队列与可加入房间数 |
| start-stats-note | 取数失败说明 |
| start-changelog / start-changelog-latest | 公告面板与最新日期 |
| start-changelog-entry-<date> | 单条公告（服务端 date 作稳定 id，日期按契约唯一） |
| start-changelog-empty | 无公告 / 读取失败 |

规则与 #22 相同：屏内同一 testid 只出现一次；列表项用业务稳定 id，不用下标。

## 4. 与旧首页的差异（有意）

| 旧首页 | 本票 | 理由 |
| --- | --- | --- |
| 自定义房间入口（等待房/邀请链接） | **未放** | 11 条路由是冻结契约，没有自定义房路由；该流程属于大厅票（#24） |
| 热门卡、最近解锁、段位阶梯 | **未放** | 需要 `/api/card_usage`、`/api/achievements`、`/api/rank_constants`；本票范围是「玩家信息 / 主行动 / 在线与公告」 |
| 图鉴、好友、更新公告浮层 | **未放** | 旧栈是浮层模块，不在 11 屏路由内 |
| 更新公告按钮打开浮层 | 右栏直接显示最近 3 条 | 不新增路由/浮层，同时公告内容仍来自 `/api/changelog` |
| 排队时按钮仍可点（服务端再拒一次） | 排队时按钮置灰 | 阻止重复入队产生的「你已经在匹配队列中」噪音；取消按钮仍在 |
| 未登录时隐藏等级条 | 未登录时名片整块退成游客态 | 游客没有段位/等级，避免展示占位数字 |

## 5. 接线与共享文件

* `realtime/home.ts` 复用 #22 的共享 typed socket（`acquireSettlementChannel`），
  以 `keepAlive: true` 取得连接：**座位绑定在创建它的 socket id 上**，首页跳布船时
  连接不能断（旧栈同样整页只保持一条连接）。
* 为此 `realtime/settlement.ts` 增加了可选参数 `{ keepAlive }`（默认 false，#22 行为不变）。
  这与 #23 在 `realtime/match.ts` 的用法一致；两票合并时该参数是同一处改动。
* 只新增 4 个监听：`match_queued` / `match_canceled` / `error`（home）+ 既有的
  settlement 监听（`game_state` 等）。**没有新增事件名或路由名。**
* `match_queued` 到达即把「等待落位」置位；收到 `game_state{placing_ships}` 后跳
  `placement`。取消、离开或落位完成都会清位。

## 6. 门禁（仓外）

```powershell
$env:T26_WORKTREE = 'D:/develop/battleship-worktrees/integration'   # 默认即 integration（D7）
$env:PYTHONIOENCODING = 'utf-8'
D:/develop/battleship-verify/.venv/Scripts/python.exe -m pytest cases/26-home -q
```

* `test_static.py`：双构建/内容哈希/生产包无测试钩子/vue-tsc/data-testid 源码契约/
  路由名冻结/源码不硬编码 impl-26/legacy 默认仍是旧首页/SPA 模式 `/` 服务新壳/
  四个读接口的字段前置条件。
* `test_browser.py` + `browser_check.mjs`：真实后端 + 测试构建 + 真实 Chromium；
  在线/队列/房间数与 `/api/home_stats`、胶囊与 `/api/online_count`、公告与
  `/api/changelog` 逐项比对；游客态与真实注册后的名片（段位/等级/战绩/胜率/连胜）；
  四个入口路由；三视口布局与无横向溢出；四个读接口被 CDP 阻断时的 `—` 降级；
  休闲排队/取消、游客排位被拒、真实双座位 PvP 配对、登录后排位排队、人机房落位。
* 端口：5407（5408 预留）；CDP profile 在 `cases/26-home/profile`。
* 截图基线：`baselines/`（桌面 1440×900、笔记本 1024×768、手机 390×844、登录态 1440×900），
  重录用 `$env:T26_UPDATE_BASELINES='1'`。

## 7. 已知边界

* `/placement`、`/lobby` 等目标屏在 #23/#24/#25 合并前仍是占位；本票只保证**入口真的
  发出请求并落到对应路由**，不替目标屏补业务。
* 首页只在挂载/连接建立时读一次在线数据，没有轮询（旧栈页脚是 10 秒轮询）；刷新页或
  重新进入首页会重读。
* 人机难度没有写进 `game_state`，浏览器门禁只能断言房间/落位，难度值由服务端
  `_normalize_difficulty` 收口。
* 公告列表取 3 条（接口上限 20），没有「已读」标记；旧栈的 localStorage 已读逻辑不在本票。
