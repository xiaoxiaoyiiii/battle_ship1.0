# main 视觉回归 · 第三轮交互阻塞修复（2026-10-23）

本文件记录 Codex 复验后仍可复现的四项问题（A 横屏连锁、B 手机选目标、C 360×640
重叠、D 玩家公告）的根因、修法与可复现证据。视觉方向与 main 基准对照见
`docs/UI-RESTORATION-REPORT.md`，上一轮的高度预算与 `--cell-bg` 修复见
`docs/UI-FIX-ROUND-20261023.md`。

- 任务标识：`FORK_MAIN_UI_RESTORATION_FIX_20261023_03`
- 分支：`feature/main-ui-restoration`
- 基线提交：`5c8c56f`（第二轮）
- 改动范围：`frontend/src/**`、`backend/src/battleship/domain/social/changelog.py`
  （唯一被允许的后端改动：纯公告数据）、`docs/**`
- 未合并、未部署；PR 仍是 #18（base `review/fork-cloud`）

## 0. 这一轮怎么判定「真的能点」

上一轮的 `flows/real-match.mjs` 有两处会让证据虚高：点击失败时回退到
`el.click()`，且失败只记一行 `FAILED` 不设非零退出码。本轮改为严格口径，
脚本在仓外验证目录 `D:\Codex workspace\battle-ship-ui-verification-20261023`：

- `spec-fix-abc.mjs`：可达性断言 = **先 `getBoundingClientRect()` 判断在视口内**，
  **再 `document.elementFromPoint(中心点)` 判断命中者是自己**，最后用
  `page.mouse.click(x, y)` 在这一点击落——不用 Playwright 的 `click()`，因为它会
  自动滚动隐藏祖先，正好会掩盖「被 `overflow: hidden` 裁掉」这类问题；
- 任何「已选 2 / 2」「按钮可点」的结论都附上面的 rect 与 elementFromPoint 读数；
- `spec-fix-abc.mjs` 任一断言失败即 `process.exit(1)`（本轮全部通过，退出码 0）。

测量环境：独立测试栈 5451（`.tmp/ui4.db`，`SECRET_KEY=fix3-secret`，
`ENABLE_TEST_EVENTS=0`），真实生产前端 `frontend/dist-test`；未接触云端数据。

## 1. A：横屏连锁窗口把「不响应」裁到屏幕外

### 根因

横屏两列布局给 `.game` 加了 `overflow: hidden`，而 `.game-chain-panel` 仍是
`top: 52px` + `max-height: 78vh`：78vh 按**视口**算，而 `.game` 只从导航栏下方
开始（844×390 时高度 326px），面板因此越过舞台底边被裁掉；面板自身
`clientHeight == scrollHeight`（275），即使内部滚动也滚不到底部按钮。

### 修法（`frontend/src/screens/game/game-screen.css`）

1. 桌面基础规则：`max-height: min(560px, calc(100% - 64px))` —— 相对**舞台**而非
   视口，从根上避免越过底边；
2. 横屏块（`orientation: landscape and (max-height: 480px)`）：
   `.game-chain-panel { top: 6px; bottom: 6px; max-height: none }`，即撑满舞台高度
   并在面板内部滚动；
3. 不删任何可交互内容：`overflow: hidden` 只作用在舞台外框，面板滚动条在内部。

### 实测（`node spec-fix-abc.mjs a`）

| 视口 | 舞台 | 面板 | 「不响应」按钮 | elementFromPoint | 真实鼠标点击 |
| --- | --- | --- | --- | --- | --- |
| 844×390 | 64–390（高 326） | 70–384（高 314，client 312 = scroll 312） | y 294–334 | 命中按钮 | 面板关闭（`closedByRealClick: true`） |
| 844×340 | 64–340（高 276） | 70–334（高 264，scroll 275 > client 262，内部滚动） | 滚动后 y 294–334 | 命中按钮 | 面板关闭 |

修复前同尺寸：面板 165–442，按钮 y 389–429，舞台 113–390 且 `overflow: hidden`。

## 2. B：手机选目标浮层盖住要点的棋盘

### 根因

`.game-target__main { flex: 1 1 280px }` 是给桌面横排写的；手机断点把
`.game-target` 改成 `flex-direction: column` 后，`280px` 从**宽度基准**变成
**高度基准**，浮层被撑到近 400px 高，从顶部盖住 30 / 36 格。

### 修法

1. 手机断点（≤719px）：浮层改停靠底边（`top: auto; bottom: 6px`），
   `max-height: min(46vh, 260px)`、内部可滚，`.game-target__main { flex: 0 0 auto }`
   —— 它现在只压在「手牌 + 主按钮」上，而选目标期间这两者本就不参与；
2. 横屏断点：浮层移到右列（`right: 8px; width: min(320px, 100% - 16px)`），
   棋盘在左列完整暴露，同样 `flex: 0 0 auto`；
3. 多选与双棋盘：`神之宣告`（己方两艘）与 `神威！`（先选作用棋盘，再点 3×3
   左上角）都按下述口径实测；手机端「选棋盘」与「海域 tab」是两套独立开关，
   脚本按真实用户路径依次点两者。

### 实测（`elementFromPoint` + 真实鼠标点击）

| 视口 | 卡牌 | 棋盘格可命中 | 真实点击 | 结果读数 |
| --- | --- | --- | --- | --- |
| 390×740 | 神之宣告 | 36 / 36（其中 14 格 `cell--ship` 全部可命中） | 两击选中两艘战舰 → 一击选效果「摧毁对方一艘战舰」 | `已选：2 / 2`，`确认使用` `aria-disabled=false` |
| 390×740 | 神威！ | 36 / 36 | 2 击 | `已选：第 2-4 列，第 1-3 行`，确认可点 |
| 844×390 | 神威！（经小地图开己方浮层） | 36 / 36 | 2 击 | `已选：第 2-4 列，第 1-3 行`，确认可点 |

修复前 390×740：30 / 36 格中心被 `.game-target` 吞掉，只有末行可点。

## 3. C：360×640 各区块相互重叠

### 根因

`.game-body` 是 `flex: 1` 但子项按内容撑高（`.game-board-column` 高 324.8 而容器
只有 290），溢出部分压到场地下方的 tabs 与手牌计数上；`documentElement` 不滚，
所以「整页无滚动」的旧断言看不出来。

### 修法（≤719px 且 ≤700px 高）

1. `.game-body { flex: 0 0 auto }`，让棋盘列按内容高度参与排版，不再被压扁后溢出；
2. 压缩非点按区域：`.game` gap/padding、`.game-status`、`.game-fieldbar`、
   `.game-tab` 高度、手牌最小高；棋盘 `--cell` 下限 38px；
3. 该档隐藏 `.game-rail`（小地图/舰位/日志聊天按钮）——它的可用入口在
   「更多操作」菜单里仍有 `game-log-toggle`、`game-quick-chat-button`、
   `game-more-piles`，不会丢失功能；
4. 主按钮/更多按钮保持 40px（`styles/base.css` 的触控下限）。

### 实测（`node spec-fix-abc.mjs c`）

360×640 各区块 rect（无交叠，`overlaps: []`）：

| 区域 | top | bottom |
| --- | --- | --- |
| HUD | 66 | 130 |
| 场地魔法条 | 132 | 153 |
| 海域 tab | 155 | 189 |
| 棋盘 | 211 | 473 |
| 手牌 | 495 | 590 |
| 主按钮 | 594 | 637 |

`documentElement.scrollHeight = 640`；主按钮中心点 `elementFromPoint` 命中
`button.game-primary`，首张手牌中心点命中 `.card__gems`（手牌内）。360×700 同样
零交叠。

## 4. D：玩家公告

`backend/src/battleship/domain/social/changelog.py` 顶部新增一条
（`date` 取真实提交时间，唯一）：

- 改了主界面和对局界面的配色、排版与按钮，观感更统一
- 修复了手机横屏时连锁按钮被挤出屏幕的问题
- 修复了手机上选目标时提示框挡住棋盘的问题

`GET /api/changelog?limit=3` 返回 `latest = 2026-10-23 04:55`，首页「最近公告」
第一位即这条（截图 `1440/announcement-1440.jpg`）。

## 5. 验证命令（本轮实际输出）

在 `D:/Codex workspace/battle-ship-ui-dsh`：

- `cd frontend && corepack pnpm typecheck` → `$ vue-tsc --noEmit`，退出码 **0**；
- `cd frontend && corepack pnpm build` → `[cards] up to date (50 cards)` +
  `[contract] OK 175d5811dd71…` + `✓ built in 1.92s`，退出码 **0**；
- `node spec-fix-abc.mjs a` / `c` / `b`（仓外验证目录）→ 断言全过，退出码 **0**；
- `git diff --check` → 无输出，退出码 **0**。

按任务要求本轮只跑与这些问题相关的几何/点击断言与必要构建，未重跑全量无关检查。

## 6. 证据

目录：`docs/screenshots/main-ui-restoration/fix-round-3/`

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `844/chain-844x390.jpg` | 注入连锁请求（真实组件与样式） | 面板 70–384 落在舞台内，「不响应」可见可点 |
| `844/chain-844x340.jpg` | 同上 | 更矮横屏：面板内部滚动后按钮仍可达 |
| `390/target-shenzhi-390x740.jpg` | 注入手牌 | 神之宣告：36/36 可命中 |
| `390/target-shenzhi-effect-390x740.jpg` | 注入手牌 | 两舰 + 效果选完后「确认使用」可点（`aria-disabled=false`） |
| `390/target-shenwei-390x740.jpg` | 注入手牌 | 神威！：棋盘 + 海域 tab 后可点 3×3 |
| `844/target-shenwei-zoom-844x390.jpg` | 注入手牌 | 横屏经小地图开己方浮层后可点 |
| `360/game-360x640.jpg` | 注入战场状态 | HUD/场地条/tab/棋盘/手牌/主按钮零交叠 |
| `1440/announcement-1440.jpg` | 真实接口 | 首页展示本轮玩家公告 |

## 7. 仍未覆盖 / 已知限制

1. **桌面/横屏没有「己方海域」常驻棋盘**：`神之宣告` 这类要求自己海域的目标，
   在 844×390 需先点右下小地图打开己方浮层再选（实测 36/36 可命中）。这是既有
   信息架构（与 main 的双棋盘不同），本轮未改，只保证浮层内可完成选择。
2. **手机切换海域后棋盘标题仍写「对手海域」**：`神威！` 实测中 tab 已在我方、
   选择也落在我方海域，但 `.board__title` 文案未随之更新。属于既有文案问题，
   不在本轮四项修复内，如实记录。
3. **仓外 22 条浏览器门禁未执行**：本机无 `D:/develop/battleship-verify/`，本轮
   没有改动任何 `data-testid`。
4. **极矮横屏（如 844×300）未纳入验证**：现有断言覆盖 844×390 / 844×340。
