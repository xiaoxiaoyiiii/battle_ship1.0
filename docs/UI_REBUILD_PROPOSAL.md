# UI 完全重构建议（2026-09-18）

> 结论先行：**不建议"推倒重写前端"**，建议**分 7 期的界面层替换**——先建安全网、再拆结构、最后换皮。
> 本文所有数字都是本轮实测（行号只是线索，会漂移）。
> 配套现状数据：`docs/FRONTEND_TECH_ANALYSIS.md`（较旧）+ 本轮三份审计（页面结构 / CSS / 硬约束）。

---

## 0. 为什么不能直接重写

### 0.1 前端现状体检（实测）

| 指标 | 实测值 | 含义 |
| --- | --- | --- |
| `static/game.js` | 10535 行 / 514KB | 无 class、无 import、无构建链 |
| `templates/index.html` | 1102 行 / 68KB | 9 个 `.screen` + 9 个 `.modal-overlay` 全静态 |
| `static/style.css` | 5472 行 / 203KB | 32 个历史追加分区，**无 BEM、无组件边界** |
| 顶层 `function` | 225 个 + 98 个嵌套 | 两个巨型函数吃掉 3400 行 |
| `getElementById` | 312 次（**125 个是文件头模块级 `const`**） | 元素必须在脚本执行前就存在 |
| `innerHTML =` | 101 次（`escapeHtml` 用了 118 次，收口还算好） | 字符串拼 HTML |
| `gameState` 字段 | 49 个，**601 处引用** | 唯一的"状态存储"，无订阅无校验 |
| CSS 选择器 | 1096 条规则 / 1122 唯一 / **100 个被重复定义** | 45 个是同作用域真重复 |
| `!important` | **56 处**（26 处集中在 2804–2996 压缩布局） | 靠覆盖压制历史规则 |
| 裸颜色 | **343 处 hex，其中 248 处散落**；`rgba()` 426 处里 311 处整条写死 | 只有 41 个变量、110 行定义 |
| `#id` 选择器 | **162 处 / 80 个唯一 id** | 最不可复用的部分 |
| 零引用类名 | 37 个（15 个只在 CSS 里存在） | 死代码 |
| 内联 `on*=` | **0** | ✅ 无内联事件，这是个好底子 |
| 内联 `style=` | index.html 仅 4 处（全是 `display:none` 初值） | ✅ 干净 |

### 0.2 五个结构病灶

1. **屏切换有两套实现**。`switchScreen()`（game.js:6490）有 9 屏，另有 **3 处手写 `classList.remove('active')` 清单**（4938、5872、1348 附近）。
2. **渲染同一份数据存在多套代码**：榜单行点击器两份（`bindLeaderboardUserClick` / `bindRankedUserClick` 近乎逐字相同）、榜单渲染两套风格（createElement vs 拼字符串）、棋盘两条路径（`initBoard` / `initGameBoards`）、日志两条写入（`addGameLog` / `renderServerLog`）。
3. **大量 UI 是 JS 动态造出来再 append 到 `body`**（约 27 处 `document.body.appendChild`）——手牌区 `#magic-system`、两个角落头像、十几个选择面板、提示浮层都不在 `index.html` 里。**所以 `dom_contract_check.mjs` 必须同时扫运行期 `id="x"`**。
4. **布局范式是"浮窗拖拽"**：日志 / 魔法预览 / 聊天三个浮窗在窄屏必然叠压，靠 `adaptive_layout.js` 把它们**搬家**进 `#aux-dock` 三选一（DOM 搬家 + 记录 parent/nextSibling 可逆还原）。这是 phone 上唯一能成立的方案，**不能退回"侧边栏"**。
5. **`style.css` 是 32 段历史追加**，`8.1` 排在 `8` 前面，第 32 节内部子标题写成 `30.1`（编号撞号）。

---

## 1. 不可谈判的约束（先背下来再动手）

### 1.1 八个无头检查工具（行为级，必须全绿）

| 工具 | 校验核心 | 备注 |
| --- | --- | --- |
| `dom_contract_check.mjs` | 代码引用了但页面不存在的 id | **不用浏览器/服务端，几秒出结果**，重构期的第一安全网 |
| `ui_layout_check.mjs` | 宽屏 9 项 + 6 个紧凑视口各 9(+4) 项 | 见下 |
| `profile_card_check.mjs` | 名片 4 分区 / 称号 7 项 / 保存 8 字段 | 会**真注册**一次性账号 |
| `ranked_check.mjs` | 段位榜样式差异化、`#profile-show-rank` 必须是第 5 个开关 | 要求 DB 与服务端同一份 |
| `lobby_check.mjs` | **双浏览器**实时性 | 单浏览器测不出来 |
| `hand_play_check.mjs` / `chain_preview_check.mjs` / `renwang_board_check.mjs` | 手牌自愈 / 连锁预览（`cap===0` 次 emit）/ 点选面板重绘 | renwang 需要 `ENABLE_TEST_EVENTS=1` |
| `wallpaper_check.mjs` / `achievements_check.mjs` / `level_check.mjs` / `rank_help_check.mjs` | 壁纸 / 徽章墙 / 等级 / 帮助页 | wallpaper 是唯一自起服务端的 |

### 1.2 `ui_layout_check.mjs` 的硬契约（重构必须继续满足）

- 宽屏 1600×1000：棋盘 `w>=280`、**`.cell` 数 === 36**；可见阶段按钮水平居中容差 **3px**；投降按钮与 `.turn-indicator-inner h2` 垂直中心差 **<=3px**；`#phase-timing-toggle` 与 11 个写死 id 的矩形**零叠压**（`>1px` 才算撞）；`#magic-card-preview` 与 `#in-game-chat-container` 重叠必须有一维为 0；`.cell.revealed` 数 === 2 且 4.5 秒后仍为 2。
- 6 个紧凑视口（`320x568@2` `336x664@2` `390x844@3` `430x932@3` `664x336@2` 横屏 `768x1024@2`）：**页面一屏不滚动**、**被遮挡格数 === 0**（逐格 `elementFromPoint`）、棋盘 `fullyInView`±1px、面板两两零叠压、`#game-screen` 内所有 `button/.cell/.magic-card/input/.dock-tab` 最小边 **>= tap-1**（`tap` = 视口高 <420 ? **36** : **40**）。
- ⚠️ 脚本里**没有** `300` 这个数（只断言 `>=280`），但 `tests/test_ui_review_fixes.py:55` 断言 `flex: 0 1 340px` 与 `max-width: 340px`，文档多处写 300×300/42px —— **尺寸被三重锁定**，别指望"稍微调小"。
- ⚠️ **凡是含 `position:fixed` 后代的容器，永远不许加 `transform`/`filter`/`backdrop-filter`**：`.game-container`(175)、`.game-main-container`(431)、`.game-content`(440)、`.screen`(214)、`body`(155)。当前它们都干净；玻璃效果放在 `.game-container::before`。新增浮窗挂载点前先读 CSS 注释 187–197。

### 1.3 真正的路障：断言源码字符串的 pytest（**这才是"完全重构"的最大成本**）

`tests/test_ui_review_fixes.py`（117 行）与 `tests/test_mobile_adaptive_layout.py`（124 行）**用 in/re 匹配源码文本**，例如：

```python
assert 'id="effect-status-bar" class="effect-status-bar hidden"' in HTML
assert 'flex: 0 1 340px' in body
assert "enterBattleBtn.style.display = 'inline-block';" in JS
assert "if (screen && screen.id === 'game-screen') ensureGameLogEmptyState();" in JS
assert '你：剩余 <span id="your-ships">6</span> 艘战舰' in HTML
```

再加 `test_stats_display_fixes.py`（`.user-stats-table` 等选择器）、`test_ranks.py`（`.pf-avatar[data-frame="X"]` 每条外观必须有 CSS；`rank_icons.js` 必须在 `game.js` 前）、`test_wallpaper.py`（index.html 必须含 `wallpaper.js`）、`test_ui_review_fixes.py`（`/static/game.js` 必须先于 `/static/adaptive_layout.js`）。

**它们锁的不是行为，是行文。** 任何类名/结构/文案级的重构都会让它们整片红，而红灯给出的信号是"你写错了"，实际是你**改对了**。所以 Phase 0 必须先把这批测试从"源码正则"改成"行为断言 + 契约文档"，否则后面每一期都在跟测试打架。

### 1.4 本地验收的标准命令（必须隔离数据库）

```bash
cd /d/develop/battle_ship1.0        # 必须在项目根（server.py 用相对路径读 ./static/magic_card.json）
BATTLESHIP_DB_PATH=.tmp/uiref.db CORS_ORIGINS=http://127.0.0.1:5070 PORT=5070 \
  ENABLE_TEST_EVENTS=1 python server.py

node tools/dom_contract_check.mjs                                   # 安全网 1（秒级）
node tools/ui_layout_check.mjs --url http://127.0.0.1:5070/ --shots .tmp/shots
python -m pytest tests/ -q                                          # 基线 ~1360 passed
```

⚠️ 端口避开 **5060/5061**；`CORS_ORIGINS` 必须与 `PORT` 完全一致（含 scheme+host+port），否则 socket.io **静默连不上**、工具全假红。

---

## 2. 已修复：屏/浮层清单漂移（同型缺陷）✅ 2026-09-19

都属 CLAUDE.md 第 11 条那个形状（同一份清单被手抄多份、某一份漏项）。
它们**全都不报错**，只是点了没反应。已全部修复，并加了回归守卫
`tests/test_screen_overlay_registry.py`（5 个用例：在修复前的代码上**全红**、修复后全绿）。

| # | 位置 | 缺陷（修复前） | 修复 |
| --- | --- | --- | --- |
| 1 | `applyRoomSync` / 比赛开局 / `reset_gameboard` 三处 | **给 `.screen` 加 `hidden`，而全仓从不摘除**。`.hidden{display:none !important}` 压过 `.screen.active` → 走过任一路径后，点「游戏大厅」能加上 active 却依然 `display:none`，**页面一片空白**（已实测复现）。 | 屏上只用 `active`，彻底不再写 `hidden` |
| 2 | `game_state` / `reset_gameboard` | 各手抄一份"隐藏所有屏"清单，**两份都漏了 `lobbyScreen` / `leaderboardScreen`** → 在大厅点人机对战会两个屏同时可见。 | 唯一来源 `hideAllScreens()` + `allScreens()` |
| 3 | `closeOverlaysExcept` | 清单只有 6 个 id，而 `.modal-overlay` 有 **9 个** → 漏 `login-modal` / `register-modal` / `discard-pile-modal`，它们不参与互斥、会被后开的面板压住。 | 改按 `.modal-overlay` 类名取，新增浮层自动生效 |

> ❗ **更正**：初稿把缺陷 1 写成"`switchScreen()` 漏了 `matchSuccessScreen`"—— 那是**错的**，
> 实测源码里 `switchScreen` 的数组是完整的 9 屏。真正的漏项在另外两处手抄清单（缺陷 2），
> 而且还有一个更严重、当时没发现的：缺陷 1 的 `hidden` 是**不可逆锁死**。

**治本已完成**：屏走 `hideAllScreens()` 唯一清单，浮层走 `.modal-overlay` 类名 —— 不再有可漂移的手抄清单。
---

## 3. 目标架构

### 3.1 技术选型（推荐 A）

| 方案 | 做法 | 优点 | 代价 | 结论 |
| --- | --- | --- | --- | --- |
| **A. 原生 ESM + 令牌 + 轻量渲染原语（推荐）** | 无构建链，`<script type="module">`；自研 ~200 行 `h()/mount()/store`；Web Components 只用在真复用件 | 保住现有部署/测试/工具链；无 node_modules；`asset_v` 缓存戳机制不变 | 需要自己写状态订阅与 diff 边界 | ✅ 推荐 |
| B. Vite + Preact/htm（无 JSX） | 引入构建，产出 `static/dist/` | 组件化更彻底，生态好 | 要改 index.html 全部 script 标签（**违反现有顺序契约**）、要 node_modules、无头工具全部要重标定、线上部署多一步 | 只在"确定要长期做前端产品化"时选 |
| C. 整站重写（React/Vue + TS） | 全新前端工程 | 最"现代" | 9 个屏 + 101 处 innerHTML + 601 处 `gameState` 引用 + 6 个源码正则测试 + 12 个无头工具都要推倒；服务端 60+ 事件契约要重对 | ❌ 不建议 |

**推荐 A 的理由**：这个项目的"难"不在渲染，在 **60+ 个 socket 事件 × 49 个状态字段 × 12 个无头工具的既有契约**。框架能省的是模板字符串，换不回被推翻的契约成本。而 A 是唯一能让"每期都保持全绿"的路线。

### 3.2 目标结构

```
templates/index.html          # 只剩骨架 + 挂载点（<div id="screen-root">）
static/
  styles/
    tokens.css                # 第 1 层：色彩/间距/圆角/阴影/动效时长（唯一定义处）
    themes.css                # 第 2 层：classic / dark / 具名预设 —— 只覆盖令牌
    base.css                  # 第 3 层：reset + 排版 + 通用原语
    components/*.css          # 第 4 层：按组件分文件，一个组件一个文件
    screens/*.css             # 第 5 层：屏级布局
    responsive.css            # 第 6 层：只放断点，不放颜色
  core/
    dom.js                    # h() / mount() / 事件委托根
    store.js                  # 单一 state + subscribe（替代 601 处裸引用）
    socket.js                 # 唯一的 socket 事件注册表（事件名 → handler）
    navigation.js             # ★ 屏注册表 + 浮层注册表（治 §2 的三个缺陷）
    format.js                 # escapeHtml / 全角冒号文案表 / 数值格式化
  ui/                         # 组件（每个 = 一个渲染函数 + 一个样式文件）
  screens/                    # 9 个屏，各自只做组装
  features/                   # 手牌、连锁、名片、大厅、排位、壁纸…按业务切
```

**关键设计决定**：

1. **屏与浮层走注册表**：`registerScreen(id, {el, onEnter, onLeave})`、`registerOverlay(id, {el, singleton:true})`。`switchScreen` 与 `closeOverlaysExcept` 只遍历注册表 → **不可能再漏项**。新增时"三件齐"变成"注册即齐"。
2. **手牌区搬进 HTML**：现在 `#magic-system` 由 JS 造了再 append。改成静态挂载点 + 组件渲染，`dom_contract_check` 才能静态覆盖它。
3. **状态用 store + 订阅**：先做**兼容层**——`gameState` 保留为 store 的代理，逐期把读取改成 `store.get()`。这样不用一次性改 601 处。
4. **只保留一份身份**：`window.__USERNAME`（模板注入）与 `gameState.playerName`（8 处赋值）合并。
5. **CSS 五层 + 令牌**：41 个变量 → 约 90 个令牌；**248 处裸 hex 全部收进令牌**；`#id` 选择器（162 处）逐处降级为 class；56 处 `!important` 随浮层范式一起废弃（目标 ≤5 处）。
6. **保留浮窗范式**：宽屏仍是浮窗（可拖拽），窄屏仍由 `#aux-dock` 接管。**不要**改成侧边栏——紧凑视口那 9 项断言是按现在的结构写死的。

---

## 4. 分期实施路线（每期都能独立上线并保持全绿）

### Phase 0 · 立安全网（**先做，无 UI 变化**）
- 把 `tests/test_ui_review_fixes.py` / `test_mobile_adaptive_layout.py` 的**源码正则**换成：① 纯函数单测；② 行为断言（走无头工具或 Flask test client）；③ 把仍然必须锁的"行文契约"抽成一份 `docs/UI_CONTRACT.md`，让 `dom_contract_check.mjs --plan docs/UI_CONTRACT.md` 去读。
- 修 §2 的三个清单缺陷（或直接上屏/浮层注册表）。
- 给 `ui_layout_check.mjs` 加 `--baseline` 快照输出（把 11 个区域的矩形矩形存 JSON），后续每期 diff。
- **验收**：`pytest tests/ -q` 全绿 + `dom_contract_check` 全绿 + `ui_layout_check` 全绿。
- **工作量**：2–3 天。**风险**：低。

### Phase 1 · 拆 `game.js`（纯搬运，零行为变更）
- 按 `core/ ui/ screens/ features/` 切文件，**用原生 ESM**。
- 125 个文件头模块级 `const el = getElementById(...)` 改成惰性取值（`el()` 或 `byId()`），这是"先建安全网"之外最关键的一步，否则模块化后加载顺序一变就全 `null`。
- **保留 script 顺序契约**（`rank_icons.js` → `game.js` → `adaptive_layout.js`）直到 Phase 2 显式改写并同步测试。
- **验收**：三件套全绿 + 手工过一遍 12 个屏的手感。
- **工作量**：5–8 天。**风险**：中（拆分本身机械，但 601 处 `gameState` 引用容易漏改）。

### Phase 2 · 屏与浮层注册表 + 导航重写
- 引入 `navigation.js`；9 屏 + 9 遮罩 + ~27 个动态浮层全部登记（浮层现在挂在 `body` 上，正好统一到 `#overlay-root`）。
- 顺手删 37 个零引用类名、修死代码（`#chain-prompt-container` 是死代码，实际面板由 JS 另建 `.chain-request-prompt`；`#chain-timer` / `#chain-cards-list` / `#aux-dock-body` 无引用）。
- **验收**：`dom_contract_check` + `ui_layout_check` + `lobby_check`（双浏览器）+ `profile_card_check`。
- **工作量**：4–6 天。**风险**：中高（浮层互斥逻辑被广泛依赖，`closeOverlaysExcept` 有 TDZ 注释说明它可能在脚本加载完成前被调用）。

### Phase 3 · CSS 令牌化 + 分层（**这一期才动样式，视觉先不变**）
- 抽出 `tokens.css`，把 248 处裸 hex 与 311 处写死 `rgba()` 全部收编；`themes.css` 只做令牌覆盖。
- 按 `components/` 拆文件，消除 45 处同作用域重复，`!important` 降到 ≤5。
- 把 162 处 `#id` 选择器降级为 class（**注意**：`ui_layout_check` 里有 11 个写死的 id 要保留成元素 id，只是 CSS 不该用 id 选）。
- **验收**：`ui_layout_check`（宽屏 + 6 紧凑视口）+ `node tools/ui_layout_check.mjs --shot` 目视对比 + `test_ui_review_fixes.py` 里的尺寸断言必须已被 Phase 0 重写。
- **工作量**：5–7 天。**风险**：中（盒子模型一动就是整片红，**严格只改颜色/阴影/渐变/transform/opacity/动画**）。

### Phase 4 · 视觉重设计（真正的"重构感"）
- 在令牌层之上做新视觉：字阶、间距节奏、层级阴影、动效曲线。
- **只准动**：颜色 / 阴影 / 渐变 / transform / opacity / 动画时长。**不准动**盒模型尺寸（棋盘 `>=280`、`.cell` === 36、触摸目标 40/36px）。
- 交付三档主题：`classic` / `dark` / 一个新具名预设，全部只覆盖令牌。
- **工作量**：5–8 天。**风险**：中。

### Phase 5 · 组件化收尾（消重复）
- 榜单：合并 `bindLeaderboardUserClick` / `bindRankedUserClick`；两套渲染合一。
- 棋盘：`initBoard` / `initGameBoards` 合一（注意 `dataset.*Bound` 幂等重绑机制要保留，棋盘每次重建都靠它）。
- 日志：`addGameLog` / `renderServerLog` 合一，`.log-empty` 空状态守卫必须留（`ensureGameLogEmptyState`）。
- 手牌 / 弃牌堆 / tooltip 共用同一套卡片渲染。
- **验收**：`hand_play_check` + `chain_preview_check` + `renwang_board_check` + `achievements_check`。
- **工作量**：4–6 天。**风险**：中（手牌自愈 `request_hand_sync` 的边界很细）。

### Phase 6 · 布局范式收编
- 把 `adaptive_layout.js` 的 DOM 搬家逻辑并入正式的路由/布局层，**保留可逆还原 + 触屏停用拖拽 + resize 跳过**三条约束。
- 只在 `body.layout-compact.layout-ingame` 下生效（登录/大厅/排行榜不受影响）。
- **工作量**：3–5 天。**风险**：中高（搬家的 parent/nextSibling 记录一旦错，宽屏浮窗坐标会被写坏）。

**合计约 28–43 个工作日**，可拆成 7 次独立上线。任何一期结束都应该满足：`pytest tests/ -q`（~1360 passed）+ `dom_contract_check` + 对应无头工具全绿。

---

## 5. 风险登记

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| **源码正则测试** | 每期整片假红，把有效改动误判成错误 | Phase 0 必须先重写这批测试（**最高优先级**） |
| 模块化后 125 个模块级 DOM 常量变 `null` | 静默失效：`if (el)` 兜掉、点了没反应、**不报错** | Phase 1 全部改成惰性取值 + `dom_contract_check` 每改一版就跑 |
| 盒子模型被无意改动 | 6 个紧凑视口整片红，一屏滚动/棋盘被遮挡 | 视觉改动只动颜色/阴影/渐变/transform/opacity/动画 |
| 在 `.screen`/`.game-content` 上加 transform | 浮窗定位基准改变，全盘错位 | 加 `ui_layout_check` 的宽屏 9 项当门禁；新增挂载点前读 CSS 注释 187–197 |
| socket 事件名/身份契约被改坏 | 服务端状态已清、阶段不动、双方零提示 | 事件名以 grep 为准（`use_magic_card` 而非 `use_magic`）；代他人重放 handler 必须先 `start_background_task` 脱离请求上下文 |
| 工具假红 | 误判为代码问题 | 先怀疑工具：残留无头进程、持久 profile 带旧 localStorage、`readyState` 还是旧文档、后台标签 `setInterval` 被节流 |
| 测试写进正式库 | 生产数据被污染 | 一律 `BATTLESHIP_DB_PATH=.tmp/xxx.db`；`profile_card_check`/`achievements_check` 会真注册账号，**不得指向生产** |

---

## 6. 一句话取舍

**把"完全重构"理解成"界面层替换 + 契约先行"，而不是"重写前端"。**
收益最大的三件事，按性价比排序：① 屏/浮层注册表（消灭"手抄清单"，已实证 3 个缺陷）；② CSS 令牌化（消灭 248 处裸色 + 56 处 `!important`）；③ 消重复（榜单/棋盘/日志/卡片各留一份）。这三件做完，视觉想怎么换都不再牵一发动全身。
