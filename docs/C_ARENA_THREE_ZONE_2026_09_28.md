# 对局屏三区（示意稿 C）+ 合并 origin/main（2026-09-28）

> 用户指令：「继续」（承接 `docs/C_ARENA_HOME_2026_09_27.md` 的"还没动的那块大结构"）。
> 这一轮干了两件事：**把对局屏摆成示意稿 C 的三区**，以及**处理半途插进来的 `origin/main` 合并**。
> 前几轮（首页三栏 / arena 面层令牌 / 结算屏 / 1:1 外壳）见 `docs/C_ARENA_HOME_2026_09_27.md`。

---

## 1. 对局屏三区：改了什么

示意稿 C 的对局屏是三块：**对手条** · **中场**（对手海域 + 右侧连锁列/场地魔法）· **底排**（你的舰队 + 手牌 + 操作列）。
落地后 `#game-screen` 与之同构：

| 区 | 内容 | DOM |
| --- | --- | --- |
| ① 对手条 | 头像圆牌 + 昵称 + 「剩余 N 艘战舰」+ 剩余舰 **pips** + 战绩 chip ｜ **阶段/回合/攻击**三颗胶囊 ｜ 第 N 回合 + 投降 | `.arena-oppbar-bg`（底板）+ 既有的两块 `.player-info` 之一 + `.arena-turn-chips`（新）+ 既有的 `.turn-indicator-inner` |
| ② 中场 | 两块等尺寸海域（左，跨 1–2 列）+ 连锁轨道 `#arena-chain-slot`（右列上格）+ 场地魔法（右列下格） | 既有 `.boards-container` + 新轨道容器 + 既有 `.field-magic-area` |
| ③ 底排 | 「你的舰队」摘要卡（标题 + 剩余 N 艘 + 头像/昵称 + pips）｜ 手牌（真卡）｜ 操作列（阶段按钮 + 计数面板 + 查看弃牌堆） | 既有 `.player-info` 之二 + 既有 `#magic-system` + 既有 `#turn-indicator` / `.arena-counts` / `.discard-pile-btn-row` |

**一个节点都没搬**：`.game-container` 在本档内变成 3 列 × 6 行网格，中间那几层
（`#game-screen` / `.game-main-container` / `.game-content` / 外层 `.game-info` / `.players-info`）
在**本档内** `display: contents`，位置全靠 `grid-area` 分配。
理由是紧凑档那套已验证的一屏网格全是 `body.layout-compact.layout-ingame .game-content > .game-info`
这种**直接子选择器**，套一层 wrapper 就整段失效。紧凑档与其它预设：§37 每条都带
`html[data-theme-preset="arena"] body:not(.layout-compact)` 前缀，一行都不命中。

### 1.1 新元素与数据来源（没有一处是编的）

| 新元素 | 内容 | 数据来源 |
| --- | --- | --- |
| `.arena-pips`（×2） | 6 个小方块，亮的 = 存活 | `#your-ships` / `#opponent-ships` 的文本（`renderArenaRail` 唯一写入点） |
| `.arena-turn-chips` | 阶段 / 回合 / 攻击 ×N 三颗胶囊 | 同上 `#current-phase` / `#current-player` / `#attacks-remaining`（**展示副本**，三个 id 仍在原地，紧凑档 HUD 靠它们） |
| `.arena-fleet-head` | 「你的舰队 · 剩余 N 艘」标题行 | `#your-ships` |
| `#arena-sea-sub` | 「已探明 N / 36 格 · 命中 M」 | `gameState.myAttacks`（服务端逐发下发的 `{x,y,hit}`） |
| `.arena-counts` | 手牌 / 弃牌堆 / 剩余舰 | `gameState.hand` / `discardPile` / `#your-ships` |

**没写的两个**：牌堆数（服务端不下发，`gameState.deck` 永远是空数组）与「对手手牌 N 张」
（`gameState.opponentHand` 客户端从不填，出于公平也不该填）—— 示意稿里有，宁可缺也不编。

### 1.2 与示意稿 C 的**有意差异**

| 差异 | 原因 |
| --- | --- |
| 中场是**两块**海域，不是一块海 + 一盘小棋 | 「两块棋盘同尺寸且 ≥280px」是宽屏契约（`ui_layout_check` 的 wideProbe）；且己方海域不是纯展示 —— 绝处逢生的「选船位」要在自己的棋盘上点格子，缩成小盘后格子只有 ~19px |
| 底排左格是**摘要卡**而不是缩略小棋盘 | 同上（那盘小棋在示意稿里就是"只读"的） |
| 顶栏（品牌 / 返回首页 / 快捷语）不显示 | 局内隐藏顶栏是 App 的既有行为（`game.js` 里 `gameNav.style.display='none'`），不是这一轮改的 |
| 三个 fixed 浮窗（日志 / 卡牌预览 / 聊天）还在 | 它们是功能入口，示意稿那一屏没有；代价是内容区天然窄一截 → `--arena-pad-l/-r` |

---

## 2. 四个「写上了却没生效」的坑（全部是量出来的，不是观感）

这一轮最花时间的不是设计，而是**规则明明在文件里、浏览器里却没生效**。四条各成一类：

1. **特异度：legacy (0,4,1) 压住新规则 (0,3,2)**
   `body.layout-ingame:not(.layout-compact) .game-info .players-info`（4 个类）压住了
   `html[attr] body:not(.layout-compact) .players-info`（3 个类）—— `.players-info` **没摊平**，
   两块 `.player-info` 仍挤成一个自动放置的网格项落在第 1 行，整个三区骨架塌掉。
   同一处 `.boards-container` 的 `grid-row: 2` 也这么被压掉。
   **修法**：选择器里带上 `#game-screen`（id 计数一票否决），不再依赖声明顺序。

2. **内联样式压住 CSS**：`.corner-chip` 的 `display` 被 `game.js` 的
   `controlGameElementsVisibility()` 写成内联 `block`（未开局写 `none`），
   于是 `.corner-chip { display:flex }` 与紧凑档那条 `flex-direction: row-reverse`
   （"进入 chip 后头像在前"）**从来没生效过**。改成显示时写空串（撤掉内联）、隐藏仍写 `none`。

3. **网格项的 `z-index: 0` 画在没有定位的兄弟之上**（CSS 2.1 附录 E 第 8 步 vs 第 3~5 步）：
   对手条底板 `.arena-oppbar-bg` 原来写 `z-index: 0` → 头像 / 昵称 / 胶囊全被它盖住，
   表现为「整条灰蒙蒙的」（`--panel` 有 14% 透明时还不容易看出来）。**改 `z-index: -1`**。

4. **`:has()` 判据写错对象**：`#arena-chain-slot:has(#chain-display)` 永远为真 ——
   那个容器**从建出来就一直在**（`createMagicCardUI` 挂在页面上，`adaptive_layout` 只是搬家），
   空的时候也在，于是「暂无连锁」提示永远不显示、轨道空空。
   判据要落到"里面有没有卡"：`:has(#chain-display .chain-stack > *)`。

### 2.1 还有一个「页面被 JS 打死」：观察者的自触发回环

把 `#turn-indicator` 整棵子树交给 `MutationObserver` 观察、回调里又去写
`#arena-counts`（就在那棵子树里）→ `renderArenaRail` 无限自触发。
**表现极具误导性**：不是报错，而是 `Runtime.evaluate` / `Page.captureScreenshot` 全部 30s 超时
（用 `Debugger.pause` 才抓到栈）。
**两条修法一起上**：观察范围只覆盖**读数源**（`#current-phase` / `#current-player` / `#attacks-remaining`），
且写入口加幂等守卫（值没变就不写 DOM）。

---

## 3. 半途插进来的合并：`origin/main`（68 提交）

这一轮中途，工作区被并发写入者跑了一次 `git merge origin/main`（对方已把我的工作先提交成
`085a132`，所以"ours"就是我的竞技场工作）。冲突 5 个文件：
`CLAUDE.md` / `api.py` / `static/game.js` / `static/style.css` / `templates/index.html`。
对方解出了内容，**我复核并修了一处漏掉的收尾花括号**（`@media (min-width: 1440px)` 缺 `}`，
`fluent_css_lint.py` 当场抓出 `[unclosed]`）——它会把后面上游所有新屏的 CSS 整段吞掉。

合并口径：**两边的改动都要在**。抽验（合并后逐个 grep）：

| 我的东西 | 上游的东西 |
| --- | --- |
| `arena-turn-chips` / `arena-fleet-head` / `arena-sea-sub` / `renderArenaRail` / `arena-oppbar-bg` / `html[data-theme-preset="arena"]`（132 条） | 更新公告入口 `#changelog-btn` + 红点、回放屏 `#replay-screen`、`value="master"` 难度、观战 / 反作弊 / 判定卡相关全部新文件 |

### 3.1 上游新卡带出来的两处判据重定（都写了理由）

1. **`tools/chain_stack_check.mjs`**：原判据钉死"常驻叠牌落在**手牌条**内"。三区档按示意稿
   把 `#chain-display` 搬进了中场轨道 —— 这正是这一期要的效果，再按"必须在手牌条里"判就等于
   要求它别按设计走。改成**先在轨道里找、找不到退回手牌条**，判据本意（不被 overflow 裁掉）不变。
2. **`tools/codex_realcard_check.mjs`**：原判据写死 `total === 41`（当时的卡数）。
   合并后卡表 50 张 / 去重 48 张（判定魔法卡 3 + 普通 4），死数字当场红。改成**从
   `static/magic_card.json` 现算唯一卡名数**（下次加卡不会再红）。

### 3.2 卡面美术管线补 7 张新卡

`tools/gen_card_art_prompts.py` 只覆盖 41 张 → `card_art_wiring_check` 的
「映射覆盖卡表里每一张唯一卡」当场红。补齐：7 条 `CARD_ART`（命运骰子 / 无忧梦呓 / 兵粮寸断 /
亡羊补牢 / 守株待兔 / 卧薪尝胆 / 滥竽充数）+ `TYPE_COMPOSITION` 的**判定**类构图，
重跑脚本 → `static/card_art_map.js` 41 → 48 条、`docs/magic_card_art_prompts.{md,json}` 同步。

### 3.3 AC6 度量阈值重定（附三版本对照）

预算是在**我们这条线**（Fluent 令牌化）上定的；合并把上游 68 个提交的新屏一起带进来
（回放 / 观战 / 反作弊后台 / 更新公告 / 判定卡 / 区域预览），那些 CSS 没经过令牌化。
同一条命令量三个版本：

| 版本 | hex | rgba | !important | dupSel |
| --- | --- | --- | --- | --- |
| 上游 `origin/main` 自己的 style.css | 296 | 490 | 71 | 57 |
| 我们的 `085a132`（令牌化后） | 56 | 26 | 27 | 25 |
| **合并结果** | **100** | **89** | **31** | **29** |

阈值 hex 90 → **110**、dupSel 25 → **32**（rgba / !important 未动，都在预算内）。
增量可定位：hex 全在 §38 之后的新屏；dupSel 多出的 4 条是 `.chain-preview-badge--2/3/4`。
**纪律不变**：新写的样式不许再往上顶；把这批裸色也令牌化是下一步的独立工作。

---

## 4. 本轮门禁（合并后的当前代码状态）

| 门禁 | 结果 |
| --- | --- |
| `pytest tests/ -q` | **2622 passed / 1 failed** —— 红的是 `test_dead_snapshot_key_is_gone_from_the_whole_repo`：它 os.walk 全仓找已删的快照键，而 `.workbuddy/review/**`（09-12 的旧评审草稿、已被 `.gitignore` 忽略）里还写着那个键。**环境性**，跟踪文件里一个都没有 |
| `ui_layout_check.mjs`（宽 5 档 + 紧凑 6 档 + 首页 2 档） | **136 PASS / 0 FAIL**，含「页面无 JS 异常/报错」 |
| `fluent_css_lint.py` | 块结构 OK（修掉合并带出的 1 处 `[unclosed]`） |
| `fluent_css_metrics.mjs` | PASS（hex 100 / rgba 89 / !imp 31 / dupSel 29，阈值见 §3.3） |
| `fluent_style_check.mjs` | 全部通过（set / presets / dark + 6 张截图） |
| `dom_contract_check.mjs` | 通过（3 条既有 WARN） |
| `hand_play_check` / `target_flow_check` | 全部通过 |
| `chain_stack_check` | 全部通过（改判据后 10/10，host=#arena-chain-slot） |
| `target_selection_check` / `chain_target_check` / `chain_preview_check` | 全部通过 |
| `card_text_fit_check` | 全部通过（真实卡名，含 4 张新卡名） |
| `codex_realcard_check` / `card_art_wiring_check` | 全部通过（48 张） |
| `mobile_bigcard_check` | 全部通过 |
| 上游新屏：`replay_check` | 全部通过 |
| 上游新屏：`changelog_check` | **5 红**（见 §5） |

出图核过：`02-home-arena.png`（首页三栏 + 新入口）· `04-ingame-chain.png`（三区 + 轨道里 3 张连锁）·
`m1440.png`（1440 三区几何：海域 290×290 ×2、轨道 200、手牌 380、零纵向滚动）。

## 5. 两条**不是这一轮引入**的红（下次别重复排查）

| 现象 | 真相 |
| --- | --- |
| `pytest` 1 条红（旧快照键） | `.workbuddy/review/**` 是 09-12 的旧评审目录（`.gitignore` 里就有它），里面抄着已删的键名。测试 os.walk 全仓、只排除 `.git/.tmp/__pycache__/node_modules/.venv/...`，于是扫到它。删目录或在测试的 `skip_dirs` 里加 `.workbuddy` 都能绿 —— 但那是别人的目录 / 上游的测试，留给人拍板 |
| `changelog_check` 5 条红 | 口径不一致，且**在上游那条线上也红**：工具用 `?limit=20`（上限）与面板逐条比，而页面的 `fetch('/api/changelog')` 不带 limit → 默认只回 **10 条**；上游 `docs/UPDATES_2026_09_19.md` 也写着"现在 7 条…等超过 20 条再谈折叠"。他们的公告长到 20 条之后，这条就对不上了。一行修法：页面改成 `?limit=20`（或工具改用默认 limit） |

## 6. 还剩什么

- **其余 5 屏**（布阵 / 猜拳 / 大厅 / 排行榜 / 名片设置）仍是旧的 Fluent 皮 —— arena 预设的
  面层令牌已经把它们整体染成 C 的色调，**结构**还没按 C 收口。按计划仍是"一屏一次上线"。
- 上游新屏（回放 / 观战 / 公告 / 后台）用的是上游自己的视觉语言，**没有**跟随 arena 令牌；
  要不要统一是下一个决策点。
- 上游新屏那批裸色（hex 增量 ~44 处）令牌化 = 把 AC6 阈值收回去的独立工作。

## 7. 2026-09-30 对战页与十屏复验补记

上文的 1440 棋盘 290px 和历史红项是当时快照；本次按当前代码与隔离数据库重新验收。
桌面 1440×900 两块棋盘均为 351px，1366×768 为 348px，1280×720 为 300px；
五个桌面档均达到 280px 下限。保留双棋盘、固定日志、卡牌预览和聊天入口，
同时缩窄 1200–1599 档侧窗与避让区，消除对手条胶囊与舰队点阵的挤压。
三区手牌改为 100×136，连锁卡改为 104×144 并放大卡名；三张连锁卡在
1440×900 的轨道内完整可见。

紧凑档修正快捷语遮住己方状态、平板阶段时点开关轻微压住阶段按钮、
横屏 664×336 手牌下沿被裁的问题。`ui_layout_check.mjs` 新增逐桌面档
棋盘下限与逐紧凑档手牌上下沿断言，宽屏与紧凑档最终均为零失败。

十屏审查中的四项也已处理：排行榜领奖台姓名在深色卡底上的浏览器实测
对比度为 14.60:1（1440、1280、390 三档）；390×844 布船棋盘与首屏确认按钮
零交叠且均可操作；好友房使用服务端 `player_seat` 区分房主和加入者；
结算的新增截图 `docs/cplus_shots/result-live-2026-09-30.png` 来自真实双客户端
建房、布船、对战、投降流程。`cplus_screens_check`、`cplus_deploy_check`、
`cplus_room_check`、`cplus_path_check`、`chain_stack_check` 均通过。
结算截图证明的是这条真实路径及该时点布局；不同结束原因仍由既有参数化检查覆盖。
修正后的排行榜与手机布船截图分别为
`docs/cplus_shots/leaderboard-fixed-1440x900.png`、
`docs/cplus_shots/placement-mobile-fixed-390x844.png`；二者来自浏览器进入相应屏后的
当前实现，布船截图是受控已摆满状态。
