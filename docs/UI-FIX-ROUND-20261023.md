# main 视觉回归 · 第二轮修复记录（2026-10-23）

本文件记录 Codex 复验后提出的四类问题的根因、修法与证据。视觉方向的背景与
main（`d16f706e61acb02a4ca7197cd2a92400c92c568d`）基准对照见
`docs/UI-RESTORATION-REPORT.md`；本文件只写这一轮真正改了什么、凭什么改。

- 分支：`feature/main-ui-restoration`
- 基线提交：`6a212aa`（第一轮）
- 唯一改动范围：`frontend/src/**`、`docs/**`

## 1. 对局界面被挤爆（滚动、溢出，手机手牌/主按钮出屏）

### 根因

对局屏的几何契约写在 `frontend/src/screens/game/game-screen.css` 顶部
（`desktop board side >= 480px`、`hand cards 118x165 (desktop) / 64x92 (mobile)`、
`no page scroll on the game screen`），但实现只用了「单项 clamp」，没有任何
**总高度预算**：

- 棋盘边长 = `clamp(64px, min(9.2vh, 8.6vw), 84px)`，与 HUD、场地条、手牌条、
  CTA 行的高度互不知情，几项相加必然超过视口；
- `.screen-boundary` 的 `min-height: auto` 让 `100dvh` 钉死失效，`min-height: 100vh`
  的壳层随内容长高 → 整页滚动；
- `@media (max-height: 780px)` 的手机卡尺寸规则排在手机断点之后，把手机 64×92
  覆盖成 110×152。

### 修法

1. **总预算公式**：棋盘列引入 `--game-chrome`（视口高度里不属于棋盘的那部分），
   边长改为 `calc((100dvh - var(--game-chrome)) / 6)` 并保留上下限：
   - 桌面（>1100px）：`--game-chrome: 480px`，`clamp(34px, min(9.4vw, …), 92px)`
   - 平板（≤1100px）：`--game-chrome: 470px`，上限 76px
   - 手机（≤719px）：`--game-chrome: 540px`，`clamp(40px, min(11.4vw, …), 52px)`
   - 横屏（≤480px 高）：`--game-chrome: 170px`，上限 64px
2. **壳层定高**：`frontend/src/styles/main-ui.css` 里对局屏独占窗口——
   `body:has([data-testid='screen-game']) .app-shell { height: 100dvh;
   min-height: 0 }`，并解除 `.screen`、`.screen-boundary` 的自动最小高度
   （前者会把内容顶出视口，后者是 flex 包装层）；`.game` 自身
   `flex: 1; min-height: 0; overflow: hidden auto`，预算算不准的极窄窗口退化为
   屏内滚动而不是裁掉手牌。
3. **手机卡尺寸**：`max-height: 780px` 的尺寸规则限定为 `min-width: 720px`
   （它原本只服务矮桌面窗口），手机手牌恢复契约值 64×92。
4. **横屏（844×390 这类）**：对局屏改成两列网格
   `minmax(0, 1fr) 320px`，区域 `board/hud/field/hand/act`——棋盘占满左侧全高，
   右侧自上而下 HUD、场地条、手牌、主行动；主按钮与「更多操作」并排成一行
   （`flex: 1 1 0`，高 36px），否则第二行必然出屏。
5. **卡牌详情在横屏改为贴顶**：桌面沿用「右下浮层」，但在 390px 高的窗口里
   `bottom: 214px` 会把标题与卡图顶出屏幕，改为 `top: 8px` + `max-height:
   calc(100dvh - 90px)` + 内部滚动。
6. **HUD 两行**：≤430px 时 chip 行独立横向滚动（`.game-status__chips
   { flex: 0 0 auto; max-width: 100%; overflow-x: auto }`），对手/己方与舰数
   独占第二行（`flex: 0 0 100%`）。此前 chip 容器会被挤成 `width: 0`，chip 直接
   画在名字上。

### 实测（`documentElement.scrollHeight` / 关键控件是否在视口内）

| 视口 | 修复前 | 修复后 |
| --- | --- | --- |
| 1920×1080 | 1080（刚好贴边） | 1080，棋盘 92px，手牌 118×165 |
| 1440×900 | 1072–1074（溢出 ~174px） | **900**，棋盘格 70px |
| 390×740 | 955，主按钮 bottom=951（出屏） | **740**，棋盘 262，手牌 64×92，主按钮 692–736 |
| 360×640 | 滚动 | **640**，主按钮 592–636 |
| 844×390（横屏） | 1074（溢出 ~684px） | **390**，棋盘 262，主按钮 348–384 |

## 2. 棋盘格底色丢失（--cell 变量名冲突）

`frontend/src/styles/tokens.css` 用 `--cell` 表示**格子颜色**，而
`frontend/src/screens/game/game-screen.css` 与 `BoardPanel.vue` 用 `--cell`
表示**格子边长**。对局/布船/回放/观战四处颜色声明因此拿到非法值，格子底色退化为
透明，只看得见一格宽的边框——这正是「布局错乱」截图里棋盘是空白的直接原因。

修法：颜色 token 统一改名 `--cell-bg`（`tokens.css` 三套主题），`--cell` 只保留
尺寸语义。`grep -rn -- "--cell" frontend/src` 现在只剩 9 处，全部是
`repeat(6, var(--cell))` / `width/height` 之类的尺寸用法。

## 3. 右下角通知遮挡手牌与主按钮

- 横屏（`orientation: landscape and (max-height: 480px)`）：通知停靠左上，
  避开右侧手牌与 CTA；
- 对局屏桌面：`body:has([data-testid='screen-game']) .app-toasts { top: 76px;
  bottom: auto }`——手牌与主行动占据底边，通知上移到右侧栏上方；
- 手机竖屏沿用已有「通知上移」规则。通知组件本身（队列、错误/成功/状态三类
  样式、可关闭）一行未改。

## 4. 三个主题下对局棋盘颜色

`tokens.css` 重写后 `--cell-bg` / `--board-bg` / `--board-border` 在
`chart`（深海竞技场，默认）、`journal`（航海日志，浅色）、`night`（夜航，高对比）
三套主题都有值。实测（1440×900，取非命中格）格子的 computed `background-color`：
`chart` = `rgb(31, 40, 80)`、`journal` = `rgb(219, 234, 254)`、
`night` = `rgb(20, 41, 77)`；三套主题均非透明，格子 70px。

## 5. 真实交互流程（非夹具）

`flows/real-match.mjs`（在仓外验证目录
`D:\Codex workspace\battle-ship-ui-verification-20261023`）用 Edge + playwright-core
驱动真实前端，打真实 FastAPI + socket.io：首页点「简单」难度 →「开始人机对战」
→ 布船「随机摆放」+「确认放置」→ 猜拳 → 对局 → 点手牌开卡牌详情 →「进入战斗
阶段」→ 点对手棋盘开炮 →「更多操作」→ 日志抽屉 → 聊天发送 → 投降两次点击 →
结算。全程未调用任何 `/api/test/*` 接口，未注入任何状态。

四个尺寸都跑通（1920×1080、1440×900、390×740、844×390），关键读数：

- 跳转链：`/` → `/placement` → `/rps` → `/game` → `/game-over`；
- HUD 读数示例：`第 1 回合 / 准备阶段 / 轮到你 · 舰长9771 / 剩余攻击 5 / 回合计时 01:28 / 你先手 / 休闲对战 / 已连接`；
- 开炮回执：`第1回合 · 舰长9407 攻击 (0,0) — 未命中`（另一次为「命中，击沉战舰」）；
- 通知：选牌后真实弹出 `已选中「回光返照」：再点一次或点「使用此卡」出牌。`；
  投降第一击弹出 `再点一次「确认投降」即判负。…`；
- 聊天：`玩家W5OZ7c：gg，布局验证中`；
- 结算页标题：`结算`；
- 控制台错误：0（`page.on('pageerror')` 与 `console.error` 均为空）。

**卡牌不可用原因**：真实对局里两次手牌恰好都可用，所以真机证据是「可用卡牌不显示
原因」；服务端拒绝文案的证据来自夹具截图
`1440/game-reason-1440.jpg`（`无法使用雷达子弹：你这一局还没有攻击过`，渲染路径与
真机相同：`game-card-detail-reason` + 手牌上的 `card__reason`）。

## 6. 证据清单

目录：`docs/screenshots/main-ui-restoration/fix-round/<尺寸>/<名称>.jpg`

`real` = 真实链路截图（`flows/real-match.mjs`）；`fixture` = 用
`window.__BS_TEST__.battle` 注入战场状态后截图（组件与样式是同一份，仅跳过
匹配等待；用于布局/主题取证）。

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `1920/home-1920.jpg` | real | 首页，chart 主题 |
| `1920/placement-1920.jpg` | real | 布船（随机摆放后） |
| `1920/game-1920.jpg` | real | 对局 |
| `1920/game-detail-1920.jpg` | fixture | 卡牌详情长文 |
| `1920/game-more-1920.jpg` | real | 「更多操作」菜单 |
| `1920/game-log-1920.jpg` | real | 游戏日志抽屉 |
| `1920/game-over-1920.jpg` | real | 结算 |
| `1440/home-1440.jpg` | real | 首页（1440×900） |
| `1440/game-1440.jpg` | real | 对局（修复后无页面滚动） |
| `1440/toast-1440.jpg` | real | 右下角状态通知（选牌提示） |
| `1440/game-reason-1440.jpg` | fixture | 卡牌不可用原因（服务端文案） |
| `1440/detail-landscape-844.jpg` | fixture | 横屏卡牌详情贴顶 |
| `390/home-390.jpg` | real | 首页 |
| `390/game-390.jpg` | fixture | 对局（HUD 两行后） |
| `390/gameover-390.jpg` | fixture | 结算（390×740） |
| `390/game-detail-390.jpg` | real | 卡牌详情 |
| `390/game-latest-390.jpg` | fixture | HUD 单行回归对比（问题现场） |
| `844/home-844.jpg` | real | 横屏首页（844×390） |
| `844/game-844.jpg` | fixture | 横屏两列布局 |
| `themes/game-journal-1440.jpg` | fixture | 航海日志（浅色）主题棋盘 |
| `themes/game-night-1440.jpg` | fixture | 夜航（高对比）主题棋盘 |

## 7. 未覆盖 / 已知限制

1. **仓外 22 条浏览器门禁未执行**：它们依赖 `D:/develop/battleship-verify/`，
   本机不存在，只用 `data-testid` 契约自查（本轮没有改任何 `data-testid`）。
2. **桌面仍是「单棋盘 + 己方海域浮层」**：与 main 的「两块棋盘并排」不同，
   改动会牵动 `data-board-mode` 与浮层可见性语义，本轮不动，只做视觉。
3. **资料页/回放页/观战页只有空态或游客态截图**：需要真实账号（登录接口在真实
   栈上可用，但本轮没有注册账号），因此这三页只作为「令牌与共用组件收敛」的证据。
4. **RPS 在窄屏偶尔先显示「重新同步后才能看到对手状态」**：真实流程脚本用重复
   出拳驱动才能推进（见 `flows/real-match.mjs` 的循环）。这是既有状态同步行为，
   与本轮视觉改动无关，未修，按要求只报告。
5. **通知与右侧栏在桌面短暂重叠**：通知上移到右侧栏上方后仍会覆盖小地图区域，
   属于「瞬时可关闭」的可接受重叠，未再引入新的层级规则。
