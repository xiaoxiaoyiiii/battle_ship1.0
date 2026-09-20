# UI 设计问题清单与修复计划（2026-09-19）

> 本文件是**可执行的修复文档**：每条问题都带实测证据、精确位置与验收方式，按「能独立上线」切批。
> 数据来源：两轮多 Agent 并行实测（8 个方向），全部在 `http://127.0.0.1:5070/`（隔离库 `.tmp/uieval.db`）
> 上跑无头浏览器测得，辅以逐像素采样与源码行号。⚠️ 行号会漂移，**以 grep 结果为准**。
>
> 配套原始报告（含全部探针与截图）：`round2/` 与各 `report_*.md`（见 §7 附录）。
> 上一轮的宏观体检表见 `docs/UI_REBUILD_PROPOSAL.md`（部分数字已过期，本文 §1 给出复核值）。

---

## 0. 一句话结论

**这不是"不好看"，是"同一语义有两套实现"导致的系统性失控。** 主题、断点、显隐、屏/浮层、榜单渲染、
错误提示都在成对并存，于是最严重的缺陷全部集中在**响应式断点错位**与**令牌无纪律**两处；
而**官方安全网 `ui_layout_check.mjs` 在这些缺陷下是全绿的**（本文 §1 给出三处盲区根因）。

---

## 1. 必须先修的元问题：安全网有盲区（否则下批改动会重犯）

`node tools/ui_layout_check.mjs --url http://127.0.0.1:5070/` 实测 **全部通过**（本轮复跑确认），
但下列 P0 真实存在。三处根因（`tools/ui_layout_check.mjs`）：

| # | 盲区 | 证据 | 修法 |
| --- | --- | --- | --- |
| M1 | **宽屏只测 1600×1000 一档**（`:331`、`:381`） | 1200–1439px 的断点死区（§2 P0-1/P0-2）完全不在覆盖内 | 加 `1280x800`、`1366x768` 两档宽屏；`COMPACT_VIEWPORTS` 已含 768×1024 |
| M2 | **手牌断言有逃逸口**：`m.handCards > 0 && (m.handVisible \|\| m.handInDock)`（`:434-436`） | `handInDock` 只判"`#magic-system` 的祖先里有 `#aux-dock`"（`:251`），**不判可见、不判可点** | 断言改为"可见且 `elementFromPoint` 命中卡牌中心"的可点计数 > 0 |
| M3 | **触摸目标只扫 `#game-screen` 内 5 类元素**（`:224`） | 导航 10/10 只有 30–32px（§3.4）在 `#game-screen` 之外，永远不会被查 | 抽样范围扩到 `.nav`、`.modal-overlay`、`#lobby-screen` |
| M4 | **只查 11 个写死的区域**（`wideProbe`） | 首页等级条 `#my-level-strip` 的轨道实测 **0px 宽**（§4d T1，我用注册账号独立复现）—— 进度条永远不可见、功能等于不存在，而工具判 PASS | 补一条「可见进度类元素的实际宽度 > 0」的通用断言 |

**M2 已实测反证**（本轮我复跑）：该工具唯一测的宽屏档 1600×1000 上，手牌 `#magic-system`
rect 为 `y=928 h=215 bottom=1143`（视口高 1000）→ 只露出 71.8px，**可点卡牌数 = 0**，而工具判 PASS。

| 视口 | 手牌可见像素 | 可点卡牌数 | 需滚动 | 工具判定 |
| --- | --- | --- | --- | --- |
| 1920×1080 | 151.8px | 2 | 63px | — |
| **1600×1000** | **71.8px** | **0** | **143px** | **PASS** ← 假绿 |
| 1600×900 | 0 | 0 | 243px | — |
| 1440×900 | 0 | 0 | 243px | — |
| 1366×768 | 0 | 0 | 686px | — |
| 1280×800 | 0 | 0 | 653px | — |

> **结论：手牌在 1000–1440px 视口高下都不在首屏内**，1600×1000 正好是"看得到一条边、点不到"最糟的一档。
> 这是 §2 P0-3 的证据来源。修 M1–M3 应作为**第一批**，否则后续每批都在假绿上做决定。

---

## 2. P0：真实功能损坏（用户直接踩到）

### P0-1 · 1200–1439px 断点死区：魔法预览把棋盘顶出首屏
- **现象**：CSS 只在 `@media (min-width:1440px)` 把 `#magic-card-preview` 设为 `position:fixed`
  （`static/style.css:647`），而 `static/adaptive_layout.js:22` 用 `innerWidth>=1200 && innerHeight>=700`
  判「宽屏」。**1200≤w≤1439 两边判据相反** → 预览回落文档流，占满 900px 整行。
- **实测**（我复跑）：1366×768 → 预览 `position:relative`、rect `900×291`、棋盘底 `y=1158 > 768`
  （**完全不可见，需滚 390px**）、`docH=1521`；1280×800 → 预览 ∩ 日志 `115×273`；1199×700 → 正常（走紧凑布局）。
- **影响面**：1280×800 / 1366×768 是最常见的笔记本分辨率。
- **修复**：让 CSS 断点跟随 JS 的 1200/700；或由 `adaptive_layout.js` 输出 `body.layout-wide` 供 CSS 选择。
  同时把预览改为停靠/抽屉，避免与 HUD 竞争。
- **验收**：`1280x800` / `1366x768` 下 `#game-player-board` 的 `getBoundingClientRect().bottom <= innerHeight`。

### P0-2 · 1440px 整档：投降按钮点不动
- **现象**：预览虽为 fixed，但与 HUD 右列重叠。`#surrender-btn` ∩ 预览 = `55×30`，
  `elementFromPoint(按钮中心)` 返回 `magic-card-preview`；`#phase-timing-toggle` ∩ 预览 = `48×40`；
  `#toggle-log` 同样被盖。**持续到 ~1540px 才消失**。
- **实测**（我复跑，1440×900）：`pvXsur=55x30`、`surrenderTopEl="magic-card-preview"`；
  1600×1000 恢复正常（`surrenderTopEl="surrender-btn"`）。
- **修复**：浮窗避让 HUD 右列；`#phase-timing-toggle` 的 z-index 提到浮窗之上。
- **验收**：`elementFromPoint(11 个 HUD 控件中心)` 必须命中控件自身。

### P0-3 · 手牌在 1000–1280px 视口高下不可用
- **现象**：`#magic-system` 是 JS 动态挂到对局屏的（`static/game.js:10003-10011`），
  在宽屏布局里排在棋盘之后，页面总高 `1210–1521px`，**手牌落在首屏之外**。
- **实测**：见 §1 的表（1600×1000 可点 0 张，1600×900 及以下完全不显示）。
- **修复**：手牌固定在舞台下方一屏内（或窄屏那样收进 `#aux-dock`）；给 `#magic-system` 设
  `position:sticky; bottom:0` 或纳入对局屏的 grid 行。
- **验收**：在 §1 的 6 个宽屏档里，`可点卡牌数 >= 1`。

### P0-4 · 320×568 与 664×336 横屏：手牌搬进面板槽后实际点不到
- **现象**：手牌被搬进 `#aux-dock` 后槽体仅 52px 高、内容 282px，卡片中心 `elementFromPoint` 返回 `null`；
  320×568 收起时祖先 `dock-body` 为 `display:none` → `clickableCards=0`。
- **证据**：`p_last.mjs` / `p_reach.mjs`（原始报告 `report_game.md` P0-3）、`adaptive_layout.js:82/93/351`、`style.css:2996`。
- **修复**：矮屏别把常驻手牌塞进面板槽，或给卡牌页独立最小可见行 + 滑动提示。
- **验收**：320×568、664×336 下 `clickableCards >= 1`。

### P0-5 · 首页难度下拉文字被原生箭头压住并溢出
- **现象**：`#ai-difficulty` 渲染宽 74.5px，而最长选项「电脑：普通」canvas 实测需 99.6px。
  内容盒只剩 46.9px（**deficit −25.1px**），文字画到内容盒之外，中间 97% 的列是空的。
- **实测**（我复跑，5 个视口全部为负）：
  `1600:box74.48/content46.88/text72/deficit-25.12`、`430:-10.91`、`390:-12.99`、`336:-17.41`、`320:-18.80`。
  决定性对照：`padding-right:40px` **文字位置完全不变** → Windows Chromium 下原生 `<select>` 忽略 `padding-right`。
- **根因**：`style.css:6033-6036` 给 `flex: 0 1 118px`，但原生外观下箭头占位挤压文字。
- **修复**：`appearance:none` + 自绘箭头 + `padding-right:24px` + `flex-basis >= 100px`。
- **验收**：断言「内容盒宽 >= canvas 文字宽」（现有断言只看盒子宽 → 假绿，见 `docs/HOME_NAV_2026_09_19.md` §3）。

### P0-6 · 键盘完全无法操作棋盘与手牌
- **证据**：72 个 `.cell` 与手牌 `tabindex` 全为 0、无 role；对局屏 45 次 Tab 只有 10 个元素循环，
  棋盘/手牌一个都不在；`.cell` 派发 Enter 无响应（`clickFiredByEnter: 0`）。全项目 `tabindex` 出现 **0 次**。
- **位置**：`static/game.js:7203-7213`（`createElement('div')` + 仅 click）、手牌渲染 `renderHandUI()`（grep 确认）。
- **修复**：`cell.tabIndex=0; role="button"` + Enter/Space → `handleAttack(x,y)`；手牌 `div.magic-card` → `<button>`。
- **验收**：`可聚焦格数 === 36`、`可聚焦卡牌数 === 手牌数`。

### P0-7 · 模态框无 dialog 语义 + Tab 逃逸
- **证据**：10 个 `.modal-overlay` 的 `role/aria-modal/aria-labelledby` 全 null，AX 树 dialog 节点 **0**；
  打开 `#help-modal` 连按 7 次 Tab 焦点**全在底层导航上**。
- **修复**：加 `role="dialog" aria-modal="true" aria-labelledby`；打开时聚焦首个可聚焦元素；内部 Tab 循环；关闭归还焦点。
- **验收**：AX 树 dialog 节点数 === 打开的浮层数。

---

## 3. P1：设计层面主要问题

### 3.1 设计令牌无纪律
| 项 | 实测 | 判读 |
| --- | --- | --- |
| `font-size` 取值 | **64 个**，0.7–0.9rem 挤 10 档 | 同屏出现 14.08/14.4/14.72/15.2/15.68/16.32px（我实测），差不到 1px 无层级含义 |
| `border-radius` | **22 个取值** | 无圆角系统 |
| `box-shadow` | 声明 163 次，**归一化后仍 121 种** | 等于没有阴影系统 |
| `!important` | **67 处**（文档记录 56 → **恶化 +11**） | 靠覆盖压制历史规则 |
| 写死 `rgba()` | **317 处**（文档 311 → 恶化） | — |
| hex 颜色 | 347 次，其中 **199 次在令牌块外** | — |
| 零引用类名 | **36 个（28 真死）** | 最集中：`#chain-prompt-container` 12 条空转样式 |
| 分节编号 | 35 个，`30.x` 落在第 32 节内 | 不可作定位依据 |

**修法**：字号收 6 档、圆角收 3 档（6/10/999）、阴影收 4 档（sm/md/lg/glow）、间距走 4px 基尺度。

### 3.2 主题体系名不副实
- 6 个预设**只覆盖 42 个令牌中的 8 个**，只碰主色；`deep` 与 `classic` **逐字段相同（no-op）**。
- 主色同时当**正文色**与**白字背景** → lava/cyber/dusk/aurora 在浅色底造出 **1.81–2.80:1**
  （cyber 的「人机对战」仅 **1.64**）。
- 两套主题开关并存且状态可分裂：OS 深色首访时用户未选任何主题，设置页却已把「深海」标为已选；
  点「经典」不会摘掉 `theme-dark`。
- 浅色下金色高光文字全部失守：`.help-rank-strong` **1.44**、`.match-chip` **1.29**、`#ranked-status p` **1.29**。
- 浅色紧凑布局 `.dock-tab` 白字压白底 **1.02:1**（同 tab 深色 6.58）。

**修法**：`--primary` 拆成背景色/正文色两个角色 + `--on-primary`；4 个预设补浅色可读值；
主题单一来源（`theme-dark` 由 preset 派生）。

### 3.3 信息架构与视觉层级
- 首页 7 个同权重入口 + 导航 10 项 = **同屏 17 个可点目标**；两个 filled 按钮并列，
  逐像素亮度显示**排位反而更抢眼**（填充亮度 0.630 vs 0.150）。
- 导航分组竖线对比度 **1.29:1**（图形要求 3:1），且画到**换行后的错误组边界**。
- **登录态导航 53 → 127px（+140%）**；320px 下吃掉 **33.5% 首屏**（5 行 / 190px）；
  导航行数随宽度**振荡**（768px 恰在谷底，宽度 +2px 高度 +40px）。
- h1 与导航品牌共用逐字相同的渐变（把"字面重复"改成了"渐变重复"）；该渐变在 11 个动画相位里，
  导航品牌 **11/11 低于 AA**（最低 2.44）。

### 3.4 交互状态与反馈
- 8 个控件类 `:hover/:active/[disabled]/.loading` **全为 0**（含首页主入口 `.mode-btn`）；
  全局 `[disabled]` 属性选择器 **0 条**；禁用态靠 `opacity:0.5` → `#find-match` 禁用时对比度 **1.00**。
- ESC 只对 3 个模态框生效，点遮罩只对 8 个生效（不互补）；14 组两两打开有 **8 组堆叠**。
- 动态区域 `aria-live` **全局只有 1 条**。
- 触摸目标：导航 **10/10 只有 30–32px**（首页 7 个控件全部 ≥40px —— 首页做对、导航没做）；
  320×568 带 6 个效果时棋盘格掉到 **20.3px**。

---

## 4. P2/P3：一致性债

- 排行榜横滚溢出 195px（同页段位榜用 `table-layout:fixed` 做对了）；战绩榜空态是零 `td` 白板。
- 设置弹窗 ≤336px 高 959px 且关闭按钮滚出视野（`x` 的 top = -394）。
- 掉线横幅压住对手头像角标（重叠 98×37）。
- 游客点排位弹**两条重复 toast**（同文案，压住导航正中）。
- 棋盘格状态字形对比度 1.94–2.86；深色 placeholder 3.41。
- 圆角/间距无 4px 基尺度；`--shadow-glow` 定义 6 次、`var()` 消费 0 次。
- 文案混用：战舰 83 次 vs 舰船 1 次；手牌/卡牌/魔法卡 并存；`Lv.` vs 「等级」。

---

## 4b. 边界数据与异常态（round2/d 实测）

**三态矩阵（加载中 / 空 / 错误）—— 19 个异步区域里 8 个不全。** 标杆是段位榜（三态齐全）
与帮助页段位图鉴；缺口最集中的是**错误态完全缺失**（大厅公屏三态全无、卡牌图鉴无错误态、
对局日志无错误态）与**空态无文案**（战绩榜零 `td` 白板、徽章墙整块藏起）。
空态样式还有 4 套字号并存：`.lobby-empty` 12.8px、`.ranked-empty td`/`.log-empty` **16px**、
`.friends-empty`/`.dm-empty` 13.76px、`.history-empty`/`.guestbook-empty` 13.12px。

**双重反馈是系统性的，不是个例。** 根因：服务端每个失败路径**同时** `emit('error')` + ack `{status:'error'}`，
前端两条都渲染（`game.js:6633` 与 `game.js:4731`）⇒ **一次点击 = 2 条 toast，双击 = 4 条**。
成对点：`server.py:2508`(匹配/排位)、`2168`(join_room)、`2194`(房满)、`2720`(公屏限流)、`6891`(对局已结束)。

| # | 问题 | 实测证据 | 级别 |
| --- | --- | --- | --- |
| E1 | 同类动作弹重复 toast | 游客双击排位 → **4 条**同文案；公屏三连点 → 4 条；匹配三连击 → 2 条 | P2 |
| E2 | 建房双击 → 第一间房被回收、界面留死房间号 | `{toasts:["房间不存在","房间不存在"], roomId:"a8a92a", infoHidden:false}`；根因 `_recycle_host_waiting_rooms`（`server.py:987/2131`） | P2 |
| E3 | **对局中断线零提示**，继续显示陈旧数据 | `gameState.socket.disconnect()` 后 5.2s：无横幅无 toast；`grep "socket.on('disconnect')"` **为空** | P2 |
| E4 | `room_sync` 在非对局屏到达会**强行切屏**，并覆盖结算界面 | 首页派发 `room_sync` → screens 变 `game-screen`；`priority/chain` 弹窗留在结算屏上且**真在倒计时** | P2 |
| E5 | 一条脏 localStorage 导致**每次加载**抛未捕获异常 | `bgm_volume='abc'` → `setVolume (music_player.js:281)` → `audio.volume = NaN` 抛异常，音乐初始化中断 | P2 |
| E6 | 长 toast 在窄屏撑满整屏 | `.game-message` 仅 `min-width:200px`、无 max（`style.css:1706`）：1600px 下 800×293，**390×844 下 200×1280** | P2 |
| E7 | `#find-match`/`#register-submit` 无防重入 | 三连击发 3 次 `find_match`，且 `#find-match` 与 `#match-status` 同时可见 | P2 |
| E8 | 超长用户名/签名只换行不截断 | 好友行 480 汉字 → 行高 **649px**；签名 480 字 → 221px；注册**无长度上限**（`api.py:948`、`db.py:827`）、`#player-name` 是唯一没有 `maxlength` 的输入 | P3 |
| E9 | 90 字用户名下 HUD 两段名牌**重叠 556px** | `#my-username-corner` x68 w1010 与 `#opponent-username-corner` x522 w1010；这两个 corner 由 `game.js:99-175` 运行时创建，**无 max-width/ellipsis**（compact 模式才补了，`style.css:2802`） | P3 |
| E10 | `game_state` 未知分支引用**未声明变量** | 派发未知 state → `ReferenceError: roomInfo is not defined`（`game.js:5256`，全仓无声明）—— 新状态一上线必炸 | P3 |
| E11 | `chain_resolved` 无 `results` 时抛 TypeError | `game.js:5635` `data.results.forEach` 无守卫 | P3 |
| E12 | `#xp-delta` 负数渲染成 `+-50` | `game.js:2168` `'+' + delta`；对照段位面板（`game.js:1998`）有完整分支 | P3 |

**✅ 已证实无问题（别再改）**：XSS 转义**全站正确**（注入 `<script>`/`onerror` 到公屏/房名/玩家名/聊天/签名/好友行/排行榜，
`window.__XSS` 保持 unset，全部渲染为文本；唯一例外是卡牌图鉴 `game.js:2729` 未转义，但数据源是仓库静态 JSON）；
- **脏 localStorage 其余全部被容忍**（非法主题/预设/颜色/`battle_active_game` 非法 JSON / 200KB / `1e400` / `__proto__` 注入 / 非法 wallpaper 对象）；
  **唯一会炸的只有 `bgm_volume` 非数字**（E5）。
- **段位「0 分封底」文案实测正确**（`{delta:0,clamped:true}` → 「已到 0 分下限，本局未扣分」，未出现「±0」；`game.js:1988-2004`）。
- **单卡最长文案四处均不截断不撑破**：`Freezing！` / `恶魔契约`（125 字）在手牌、预览、弃牌堆（`line-clamp:3`）、连锁面板。
- **数字类边界全部安全**：`Lv.9999999`、`99999999`、`-1`、`12345%` 注入后无布局崩坏。

---

## 4c. 此前从未评估的 6 个屏（round2/a 实测）

被测：`#ship-placement-screen`、`#rps-screen`、`#match-success-screen`、`#custom-room-screen`、
`#game-over-screen`（+ 重连路径）。视口 1600×1000 / 1280×800 / 768×1024 / 430×932 / 390×844 / 320×568 / 664×336(横)。
⚠️ 服务端在评估中途退出，标 `[static]` 的结论在**本地静态镜像**（index.html + 原始 static/ 拷贝）上取得，
DOM/CSS/前端 JS 与真实服务端同一份；标 `[live]` 的是服务端在场时测得。

**共同结论：这 6 屏骨架都在，但「关键时刻的视觉信号」普遍缺失** —— 主行动与次行动等重、
点选后零反馈、胜负这一行与附属面板同权、而窄屏/横屏下**唯一可操作的按钮被推出首屏**。

### P1

| # | 现象 | 证据 |
| --- | --- | --- |
| S1 | **布船屏：「确认放置」与「随机摆放」像素级等重**（7 个视口 `identical=true`：背景/颜色/字号/阴影/宽高全等） | `style.css:1414` 只有 `.placement-actions button` 通用规则，**无任何 `#confirm-ships` 规则**；邻近的 `#placement-confirm`/`#placement-cancel`（`style.css:1421`）指向**另一个元素**（局内补船浮窗）—— 名字相近的失效规则 |
| S2 | **布船屏：说明文字不足以让玩家知道怎么放/怎么改** | 屏内全部文案实测 `['放置你的战舰','点击格子放置战舰 (共6艘)','已放置：0/6','随机摆放','确认放置']`，`mentionsRemove=false`（不含"再点/移除"）；船是 1×1，"共6艘"实为"占 6 格" |
| S3 | **结算屏：胜负这一行与三块面板完全同权，且胜/负/掉线胜/投降胜四种文案零差异** | 四文案实测 `{fs:18.4px, fw:700, color:rgb(15,23,42), shadow:none, cls:""}` 全等；`#game-result` 与 `#xp-delta`(17.92px 高饱和蓝)、`#rank-delta`(17.92px 金) 同权甚至更弱；`grep "#game-result" style.css` **零命中** |
| S4 | **结算屏：0 分封底警告色在浅色主题只有 1.57:1** | `.rank-clamp-note{color:#ffb0b0}`（`style.css:4800`）对面板实际渲染色 `#f6f4e7` 逐像素 **1.57:1**（白底 1.74，渐变上 1.44–1.50）；深色主题 6.02:1 —— **只有浅色坏** |
| S5 | **结算屏：320×568 与横屏下两个唯一按钮被推出首屏** | `geo_go`：320×568 按钮 `t=825 b=891`（下方 **323px**）；664×336 `b=737`（下方 **401px**）；390×844 恰好贴底；**重连路径会更糟**（导航恢复后 390×844 到 `b=1011`） |
| S6 | **猜拳屏：点选后零反馈**（点击前后快照完全相同：`disabled:false`、`aria-pressed:null`、无 spinner） | `game.js:4531` 只 `emit`；"等待双方出拳…"只在重连路径写（`game.js:1390`） |
| S7 | **自定义房：三个状态不互斥，输入行一直留在屏上** | 点「加入房间」→ `inputHidden=false`；随后建房成功 → `inputHidden` **仍 false**、`infoHidden:false`，两者同时在屏（`st3_custom_overlap_390x844.png`）；`game.js:4513` 只 `remove('hidden')`，`customCreateRoom` 从不收起 |
| S8 | **自定义房：「解散房间」不可逆，却与「返回主菜单」同为描边次级按钮，无确认/撤销/反馈** | 实测 `confirmCalls=0`，点击即 `emit('close_room')`；`#custom-close-room-msg`（`index.html:172`）**game.js 从不写入**（只有 `:5012` 置空）；复制/解散/返回三按钮 computed 全等（`background-image:none`、同色 border/color） |

### P2（要点）

| # | 现象 | 证据 |
| --- | --- | --- |
| S9 | 结算屏 320×568 下封底长句换行，与失利 chip 仅差 4px | `deltaH=48`（2 行），delta 右缘 227 vs chip 左缘 231 |
| S10 | 结算屏明细小字 **11.84px + ~4.0:1** | `#xp-progress-text`/`#xp-breakdown`/`#rank-progress-text`/`#rank-points-text`；面板渐变上 3.93–4.11:1，像素实测 4.24/4.76 |
| S11 | **结算屏经验条动画要等 5.2 秒** | 页内 rAF 实测 Lv.4→Lv.8（262XP/5 段）**5243ms**；段位明细 1732ms（`SEG_MS=700`+`RESET_MS=420`、`650`+`380`） |
| S12 | 结算屏进度行无 `flex-wrap`，把「49 / 55」压成竖排 | 390×844 `#xp-progress-text` 实测 **18px 宽 × 51px 高**（`style.css:4483`/`4775`） |
| S13 | 结算屏满格金条无任何说明 | `capped` 时 `#rank-progress-text` 被隐藏（`game.js:2075`），`#rank-admiral-note` 又需 `admiral_reason`（`:2053`）→ 两条都不显示 |
| S14 | **重连回结算屏丢失胜负结果** | `applyRoomSync`（`game.js:1391`）只 `switchScreen` 不写 `#game-result`；实测 `resultText=""`，屏上只剩两个按钮 |
| S15 | 自定义房错误 toast 压在导航条上，且同一条弹两次 | toast `top:20px`（`game.js:1442`），390×844 nav `bottom 116.8` → 重叠；输错房号 `count=2`（ack + `socket.on('error')` 两路） |
| S16 | **自定义房失败文案指向页面上并不存在的链接** | `game.js:4931`「复制失败，请手动复制上面的链接」，实测 `hasUrl=false`、`anchorCount=0` |
| S17 | 自定义房房号输入框移动端不可用/不好用 | `inputmode=null`、`maxlength=-1`、`autocapitalize=null`；可输入 50 字符（`scrollWidth 428` vs `clientWidth 204`）；房号是小写十六进制且服务端不归一大小写；**没有"复制房号"入口** |
| S18 | 匹配成功屏最坏 chip 组合把倒计时条挤出首屏 | 真实上限（1 等级+1 称号+1 段位+3 标签）：320×568 chip 块 **4 行 / 114px**，`#countdown-bar` bottom **727**（vh 568）；664×336 同样不可见 |
| S19 | 匹配成功屏人机/游客局整块对手信息为空 | `[live]` 人机局 `/user_stats?username=AI` → `{stats:null}` → `chipsHidden=true`；游客 `selfHidden=true` |
| S20 | 布船屏 320×568 格子 **40px**，低于 44px 触控目标 | 棋盘 267px → `.cell` 40×40（1600 下 49、390 下 52） |
| S21 | 布船屏横屏棋盘 340px 比视口 336px 还高 | `docH=592`、`vOver=256`，确认出现后底部 215px 在屏外 |
| S22 | **猜拳屏回合数在正常链路上不会更新（页头会撒谎）** | `#rps-round` 只在带 `round` 的 `game_state` 里更新（`game.js:5218`），首次进入猜拳的广播**不带 round**（`server.py:2863`）→ 回退 `\|\| 1`；重连路径完全不设（`game.js:1388`） |
| S23 | 布船屏「回光返照」把确认按钮在 0/6 时显示且可点 | `game.js:9133-9137` 先置 0 再 `remove('hidden')`；实测 `confirmShown=true/confirmDisabled=false/placed=0`，点了发空 ships |
| S24 | 结算屏 12 枚徽章时面板高达 762px | 390×844 实测 `h=762`、`vOver=493`（4 枚 = 280–312px） |
| S25 | 猜拳选项三者视觉**完全相同**（纯文字无图标），结果文字与正文同色 | `btnVisualIdentical=true`、`childCount=[0,0,0]`；`#rps-result` 16px 同色无底色 |
| S26 | 结果与切屏几乎同帧，玩家看不到停留 | `[live]` 120ms 采样里同一帧 `rpsActive:false, gameActive:true` |

### P3（要点）
- S27 匹配成功屏 5 秒**没有任何跳过入口**（`buttons:0, links:0`），倒计时条按 20% 跳变非连续动画。
- S28 猜拳屏旧结果文字不随新一轮点击清掉（`game.js:5219` 只在 `game_state` 里 hide）。
- S29 自定义房用 `<h1>`，同级内屏全用 `<h2>`（computed 20 vs 18.4px）。

### ✅ 该批正常的部分
手动布船可用（点空格 +1、点已放置格 −1，计数实时）；布船屏导航按契约隐藏（`game.js:5165/5216`）；
匹配成功屏倒计时数字与进度条同源一致；`#leaderboard-table` 之外的表在长名下不溢出。

---
## 4d. 社交与个人化内页（round2/b2 实测）

**结论：个人化的「零件」比「内容组织」做得好。** 等级条/徽章墙/主题卡/消息气泡单件都成立，
但凡是「要在正确的位置给人看信息」的地方都塌了。

### P1

| # | 现象 | 证据 |
| --- | --- | --- |
| T1 | **首页等级条与名片经验条的轨道宽度为 0，进度条永远不可见**，只剩「Lv.1 0/35」两个数字 | **我独立复现**（注册账号后）：`strip [668,463,107.56,31]`、`.mls-bar` **`w:0 h:10`**、`barFlex:"1 1 auto"`、`barCssW:"0px"`、fill `width:0%`；390×844 同样 0 宽。根因 `style.css:4462` `.my-level-strip .mls-bar{flex:1 1 auto}` + 轨道无 `min-width`，在内容宽为 0 的 flex 行里被收缩到 0。名片内 `.pf-xp` 同样 0 宽（`[551,276,0,8]`）。**注意：原来的 1600×1000 布局检查判了 PASS** —— 因为该元素不是它检查的 11 个区域之一 |
| T2 | 改过「一句话状态」后点 `×` 或「取消」，**不提示、直接丢弃草稿** | 脏态 `{confirms:[], hidden:true}`，重开后状态为空串；`game.js:399`（× 只关窗）、`:4311`（取消只清 `profileEditData`） |
| T3 | **320px 下分区导航被裁**：`🔒账号与密码` 项 `[378,78,122,39]` 完全在 modal（右边界 285）之外，且无滚动提示 | 编辑面与设置面同形：`navScrollW 463 / navClientW 228` |

### P2（要点）

| # | 现象 | 证据 |
| --- | --- | --- |
| T4 | **编辑面没有任何名片预览** —— 改底色/边框/称号只能「保存→关窗→去查看面」才能看到效果 | `previewExists:false`（5 个视口全 false） |
| T5 | 320px 下「保存名片」只在账号分区可见，card/avatar/title 分区 `inView:false` | `out_editor.txt:1038-1041` |
| T6 | 「保存签名」的回执在**另一个位置**（foot 的 `#profile-save-msg`）：1600 距按钮 171px，320 直接跑出视口 | 按钮 `index.html:746`、回执 `:759`；320 实测 `msgR [36,567,...]` 而视口高 568 |
| T7 | 称号 13 项里 11 项锁定，**解锁条件只写 `title`**（触摸设备完全看不到为什么不能选），点未解锁项零反应 | 11 项 `disabled + opacity .45 + title="未解锁：总场次 ≥ 20"` |
| T8 | 名片底色是 **58×34 纯色块、没有任何文字**（11 个里 9 个锁定，名称也只在 `title`） | `index.html:660-670` |
| T9 | 好友三段**没有段内空态**：某段 0 行时只剩 27px 标题（只有三段全空才有一句话）⇒「待确认 0 条」与「申请加载失败」长得一样 | 三段 `rows:0, listH:0, listHTML:""` |
| T10 | 接受/拒绝/撤回**没有任何成功回执**，列表静默位移 | 1300ms 采样 36 次 `#friends-msg` 全为空串 |
| T11 | 服务端下发了 `limits{max_friends:50, requests_per_hour:10}` 并注释要求前端显示，**前端从未渲染** | `api.py:1601`；实测能拿到 `limits`，`game.js` 除注释外无用法 |
| T12 | 「加载更早的消息」只钉在**列表顶部**且无 scroll 监听，50 条会话要滚回 ~3700px 才看得见 | `loadMore.rect [743,245]` 而 `listScrollTop:3735`；`game.js:12061` 只有 click |
| T13 | 60 条历史那屏 modal 高 **3818px**，「加载更多」在 y=3741；窄屏表头 `display:none` ⇒ 胜/负变成无表头孤立色字 | `out_nr.txt` |
| T14 | 三个状态（未公开/无战绩/用户不存在）只有文字差别，**「用户不存在」塌成 132px 高一行**，标题仍写「xxx 的个人信息」，无返回/重试 | `game.js:3903` |
| T15 | 弃牌堆卡片描述 3 行硬截断，卡片是**纯 DIV 无点击无展开**，截掉的内容不可恢复；320px 下 12 张只能看到 2 张 + 双层滚动 | `style.css:2355` `-webkit-line-clamp:3`；`game.js:9969`（无监听） |
| T16 | 帮助页**没有目录/锚点**，「段位与排位」在 1600 下位于 y=3100（要翻过 41 张卡） | `{scrollH:6062, anchorLinks:0}`；390 下容器 8143 |
| T17 | 跨页链接落错分区：从设置点「前往个人信息编辑」回到的是**名片**分区，而「账号与密码」分区里**根本没有改密码控件** | `game.js:4128`、`:4375-4380`；实测 `accountPaneHasPassword:false` |

### P3（要点）
- T18 未读 pill 无上限（未读可达 3 位数）；T19 好友行 3 个操作钮 27px 高、320px 下每行 137px；
- T20 消息气泡无头像/无日期分组，我/对方只靠左右对齐 + 两种都很浅的蓝底；每条重复带 11.2px 时间戳；
- T21 对话空态/发送失败/加载失败**三处提示位置各不相同**；T22 数字块 `0最高连胜` / `—胜率` / `0总场次`（`0` 与 `—` 混用）；
- T23 段位图鉴 9 行每行 220–241px 高（信息量不匹配）、计分表用 DIV 网格渲染（纯文本连成串）；
- T24 壁纸分区 `#wp-list` **0 个子项**、无当前壁纸缩略图，320px 下 label 高 67–141px；
- T25 主题预设会**静默清掉自定义主色**（无提示）；T26 标签上限提示出现在弹窗底部 foot（距刚点的 chip 86px）；
- T27 会话视图里弹窗 `h2` 被隐藏、标题降级成 span，返回按钮仅 55×26。

### ✅ 该批正常的部分
气泡左右分侧与 max-width 78%/88% 合理；私聊「加载更早」翻页锚点漂移仅 **0.06px**（实现正确）；
发送失败提示在输入行下方且 320px 下仍在屏内；主题预设点击即时生效（`--primary` 正确切换）；
徽章墙「已解锁 1 / 12」计数正确。

> **本轮未覆盖（别误以为已测）**：好友行的「在线 / 对局中」状态（两个账号同时在线时服务端 presence 未识别，素材里全是「离线」）；
> 8+ 好友在 1600 下的长列表（复用了既有 8 行数据）；`#user-stats-modal` 未单独截图（与查看面共用 `#opponent-stats-content`）。

---

## 5. 结构性重复（重构成本的真实来源）

| 重复项 | 位置 |
| --- | --- |
| 榜单行点击器两份近乎逐字相同 | `game.js:4859` / `game.js:6798` |
| 榜单渲染两套 | `renderRankedTable` 拼串 vs `fetchLeaderboard` 用 `createElement` |
| 棋盘初始化两条路径 | `initBoard` / `initGameBoards` |
| 日志两条写入 | `addGameLog` / `renderServerLog` |
| 动态挂载点 | **30 处** `document.body.appendChild`（手牌区、角标、十几个选择面板都不在 `index.html`） |
| 显隐三套机制 | 13 个元素靠 `style.display`、36 个靠 `hidden` 类、其余靠 `active` |
| 巨型函数 | `game.js` 288 个顶层函数，`bindEventListeners` 1928 行 + `setupSocketListeners` 1682 行 |

---

## 6. 修复批次（每批可独立上线）

### 批次 1 · 补安全网（**先做，无 UI 变化**）
1. `ui_layout_check.mjs` 加 1280×800 / 1366×768 宽屏档（修 M1）。
2. 手牌断言改成"可点计数 > 0"（修 M2）。
3. 触摸目标抽样扩到 `.nav` / `.modal-overlay`（修 M3）。
4. 难度下拉断言改成"内容盒宽 >= 文字宽"（见 P0-5）。
- **验收**：改完**立刻**应出现红灯（P0-1~P0-5 会被抓出）；这是本批唯一目标。

### 批次 2 · 断点与布局（修 P0-1/P0-2/P0-3）
- CSS 断点跟随 JS 的 1200/700；预览改停靠；手牌进首屏；HUD 与浮窗避让。

### 批次 3 · 令牌与主题（修 P0-5、§3.1、§3.2）
- 拆 `--primary` 角色令牌；预设补浅色可读值；字号/圆角/阴影收档。

### 批次 4 · 可达性（修 P0-6、P0-7、§3.4）
- 棋盘/手牌键盘化；模态框 dialog 语义 + 焦点接管；导航触摸目标提到 40px。

### 批次 5 · 一致性收口（修 §4、§4b、§5）
- 榜单渲染合一、日志写入合一、空态三态统一、文案统一。
- 服务端失败只走 ack 一条路（消 §4b E1/E2 的重复 toast）；`#find-match`/`#custom-create-room` 加防重入。

### 批次 6 · 关键时刻的视觉信号（修 §4c，纯前端）
- 布船屏 `#confirm-ships` 与「随机摆放」区分主次（S1/S2）；猜拳加选中/等待态（S6/S25）。
- 结算屏按胜负切 class、字号高于面板数字（S3）；窄屏/横屏把两个按钮固定为底部 sticky 条（S5/S24）；
  经验动画整段封顶 2.5s 或可跳过（S11）；`flex-wrap` 修「49 / 55」竖排（S12）。
- 自定义房状态互斥 + 解散走 `button.danger` + 补确认（S7/S8/S16）。

### 批次 7 · 社交与个人化内页（修 §4d）
- **先修 T1（等级条/经验条 0 宽）** —— 它让「等级」这个功能在视觉上完全不存在，一行 CSS 即可（给轨道 `flex-basis`/`min-width`）。
- 编辑面：加名片预览（T4）、保存按钮吸底（T5/T6）、锁定项显示条件而非只写 `title`（T7/T8）、脏态关窗确认（T2）、分区导航窄屏可达（T3）。
- 好友/私聊：段内空态（T9）、操作回执（T10）、渲染 `limits`（T11）、「加载更早」吸顶或滚动触发（T12）、历史列表限高（T13）。
- 其它：弃牌堆卡片可展开（T15）、帮助页加锚点目录（T16）、跨页链接带 pane 参数（T17）。

### 批次 8 · 异常态与边界（修 §4b）
- 加 `socket.on('disconnect')` 提示（E3）；`room_sync` 按屏判断（E4）；`setVolume` 加 `isFinite` 守卫（E5）；
  toast 加 `max-width`/`max-height`/数量上限（E6）；HUD 名牌补 `max-width`+ellipsis（E9）；
  注册加用户名长度上限 + `#player-name` 补 `maxlength`（E8）；删 `roomInfo` 死代码（E10）。

### 批次 9 · 性能与传输（独立于 UI，ROI 最高）
见 §7，实测收益最大的一条（gzip）只改服务端一个中间件。

---

## 7. 性能与加载预算（实测，4G/4xCPU 模拟）

### 7.1 首屏预算
| 指标 | 实测 | 判读 |
| --- | --- | --- |
| 首屏明文总量 | **1,130,572 B**（18 个请求） | 无 gzip、HTTP/1.1、`Cache-Control: no-cache` |
| `game.js` | 615,248 B = **53.6%** | `static/game.js` |
| `style.css` | 236,205 B = 20.7% | — |
| `socket.io.js` | 191,001 B = 16.7% | 三者合计 **91%** |
| FCP / LCP | **3,976 / 4,392 ms** | LCP 元素是首页 `BUTTON.secondary`（不是大图）⇒ 卡在脚本+样式 |
| DCL / load | 6,195 / 6,219 ms | 带宽反推 6.9s，吻合 |
| 局域网冷加载 FCP | 116 ms | **局域网完全无感，问题只在移动网络** |
| 开启 gzip 后 | 312,152 B（**−72.9%**）、FCP 1,196ms、LCP 1,620ms | 代理实测，非推算 |

### 7.2 阻塞点
- `index.html` 有 **9 个 `<script src>`，0 defer / 0 async / 0 module，全同步**；
  且 **`socket.io.js`(191KB) 在 `<head>` 第 8 行同步**。
- 阻断实验：只挡 `style.css` → FCP 2,472ms；只挡 `socket.io.js` → 2,944ms；两者都挡 → **308ms**。
  ⇒ **FCP 被 head 里这两次串行下载门控，吃掉约 3.7s。**
- `game.js` 解析+编译仅 **3.0ms**（@4x 1.4ms）⇒ **编译不是瓶颈，下载才是**。
- 常驻定时器 4 个：`game.js:282` 每 **2s** 轮询 `controlGameElementsVisibility`（纯写 display）、
  `index.html:1167` 每 10s 打 `/api/online_count`、`game.js:191/201` 每 20s。

### 7.3 动画与主线程
| 场景 | 主线程占用 | 说明 |
| --- | --- | --- |
| 首页静止 | **10.61%/s**，FPS 41.6 | 什么都不做也占 10% |
| 隐藏 `#particle-canvas` | 4.59%/s，FPS 52 | **粒子占 57%**（约 78% 成本在 `stroke()` 光栅化，无节流） |
| 关全部 animation/transition | `RecalcStyle` −96% | 33 个 `@keyframes`、21 处 `infinite`、**`will-change` = 0**，24 个用 `box-shadow`（非合成属性） |
| 关动画 + 隐藏 canvas | 2.16%/s，FPS 60 | 装饰性开销约 **4.2%/s** |
| 对局屏静止 @320px+4xCPU | **18.4%/s** | 移动端明显 |

### 7.4 明确否定项（别浪费人力）
- ✅ **手牌渲染 43 张仅 0.5ms**（`DocumentFragment` + `replaceChildren`）；日志 200 条追加 **0ms**（O(1)）；**无内存/监听器泄漏**（GC 后回落）；DOM 深度 13 健康。
- ⚠️ **上一轮"36 个零引用类名"能省的量级被高估**：可证明死掉的只有 **6 个规则块 ≈ 650 B（0.31%）**；
  CSS 真正可压的是**注释 16.2% + CRLF 4.9%**。`game.js` 拆分后被 gzip 稀释，排最后。

### 7.5 性能修复项（按 ROI）
1. **开 gzip**（服务端中间件）：−72.9% 传输，FCP 3,976→1,196ms。**改一处，收益最大。**
2. **`socket.io.js` 移出 `<head>` / 加 `defer`**；4 个可选脚本（wallpaper/adaptive/music/debug 共 66KB）加 `defer`
   ⇒ `domInteractive` 提前 **2.1s**。
3. **粒子 canvas** 降频到 30fps 或粒子 60→20 ⇒ 首页占用 −57%。
4. `no-cache` → `immutable`：二次访问 11 次 304 → 0，暖 FCP 520→208ms。
5. 无限动画改合成属性 / 加 `will-change` ⇒ 再省 1–1.5%/s。
6. 删 `game.js:282` 的 2s 轮询（已有 `gameStateUpdate` 事件驱动）。

---

## 8. 附录：原始报告与复现

| 报告 | 内容 |
| --- | --- |
| `report_css.md` | CSS 设计系统、主题矩阵、令牌统计 |
| `report_nav.md` | 首页/导航/大厅/浮层信息架构 |
| `report_game.md` | 对局内界面（多视口） |
| `report_a11y.md` | 无障碍/对比度/键盘/语义 |
| `round2/a/report_screens.md` | 此前未评估的 6 个屏 + 结算屏 |
| `round2/b2/report_social.md` | 社交/个人化内页内容层（含等级条 0 宽） |
| `round2/c/report_perf.md` | 前端性能与加载预算（4G 实测） |
| `round2/d/report_edge.md` | 边界数据与异常态（三态矩阵） |

### 8.1 契约校正（别再当缺陷报）

两路子智能体在实测中都撞到同一批"幽灵 id"，已逐个核对源码确认：

| 名字 | 真实情况 |
| --- | --- |
| `#nav-user` | **不存在 id**。导航用户名是 class `.nav-user`（`templates/index.html:71`） |
| `#avatar-corner` / `#opponent-avatar-corner` / `#my-username-corner` / `#opponent-username-corner` | **不在模板里**，由 `game.js:99-175` 在运行期创建（`game.js:105/120/131` 设 `id`）。模板第 364 行出现 `#avatar-corner` 只是**注释里的说明文字** |
| `#rank-delta` / `#rank-clamp-note` | 确实存在（`templates/index.html:601` / `:623`） |

> 这正是 `dom_contract_check.mjs` 存在的理由 —— 它已把这类"运行期创建"标为**不算问题（44 个）**。
> ⚠️ 与 §1 M4 呼应：`#avatar-corner` 这种运行期创建的角标**没有 `max-width`/`ellipsis`**
> （compact 模式才补，`static/style.css:2802`），是 §4b E9「90 字用户名下两块名牌重叠 556px」的根因。

**本地验收命令**（必须隔离数据库）：
```bash
cd /d/develop/battle_ship1.0
BATTLESHIP_DB_PATH=.tmp/uiref.db CORS_ORIGINS=http://127.0.0.1:5070 PORT=5070 \
  ENABLE_TEST_EVENTS=1 python server.py
node tools/dom_contract_check.mjs
node tools/ui_layout_check.mjs --url http://127.0.0.1:5070/ --shots .tmp/shots
python -m pytest tests/ -q
```
⚠️ 端口避开 5060/5061；`CORS_ORIGINS` 必须与 `PORT` 完全一致（否则 socket.io 静默连不上、工具假红）。
