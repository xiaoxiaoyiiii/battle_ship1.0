# C+ 周边屏幕 · 实施记录（2026-09-29）

> 承接 `docs/C_PLUS_SCREENS_IMPLEMENTATION_2026_09_29.md`（P0–P5 六批）。
> 基线、差异清单、逐屏状态映射表在 `docs/C_PLUS_BASELINE_2026_09_29.md`。
> 本文件 = **交付了什么 · 与原型哪里不同 · 门禁结果 · 还剩什么**。

---

## 1. 一句话结论

十屏（大厅 / 好友房 / 布船 / 图鉴 / 排行 / 档案 / 结算 / 观战 / 回放 / 设置）
全部换到 C+ 视觉，新增的一切都挂在**两道开发期门控**后面，可整批或逐屏回退；
图鉴与排行多了真实行为（点卡看完整说明、前三名领奖台），设置多了两个**真的作用于全站**
的可读性开关。所有旧 id、事件链、服务端契约、以及被各 `tools/*_check.mjs` 断言的
盒模型结构值一个没动。

---

## 2. 交付物清单

| 文件 | 性质 | 说明 |
| --- | --- | --- |
| `static/arena_screens.css` | **新增** | 十屏的 C+ 样式层（2281 行，274 个块），按「公共词汇 → 逐屏」组织，每条规则都带屏级门控 |
| `static/style.css` §40 | 新增小节 | 两个可读性选项（`data-motion` / `data-contrast`）。**故意不进 arena 门控**，见 §5.1 |
| `templates/index.html` | 改动 | ① `<html>` 上的门控属性 ② 引入新样式表 ③ 图鉴两栏骨架 + 详情栏 ④ 排行榜领奖台容器 ⑤ 布船左右分栏 ⑥ 设置页「即时预览 + 可读性」两节 ⑦ `<head>` 引导脚本补两个属性 |
| `static/game.js` | 改动 | ① 图鉴详情（点卡 → 桌面右栏 / 窄屏详情页）② 领奖台 + 自己那一行 + 「档案 ↗」③ 两个可读性开关的读/写/跟随系统 ④ 排行榜补齐加载态与空态 |
| `api.py` | 改动 | `ARENA_SCREENS_MODE` / `ARENA_SCREEN_LIST` 两个常量 + 注入模板（**唯一的回退开关**） |
| `tools/cplus_screens_check.mjs` | **新增** | 十屏 × 三视口的公共外观契约验收（见 §6） |
| `tools/cplus_path_check.mjs` | **新增** | P5 要的"一条连续路径"：首页 → 大厅 → 部署 → 对局 → 结算 → 回放 → 返回首页（双浏览器、全走真实按钮、零调试事件） |
| `tools/invite_occupy_probe.py` | **新增（补漏）** | 好友邀战 E2E 的 python 侧 socket 陪练。此前**从未入库**，导致那支工具在干净检出上必然全红，见 §6.5 |
| `tools/friend_invite_battle_check.mjs` | 改动 | `PY_HELPER` 从 `.tmp/`（不存在）指向 `tools/`（受版本控制） |
| `tools/card_compendium_check.mjs` | 改动 | 重定一条**过期的死数字断言**（43/41 → 现算，见 §7.1） |
| `changelog.py` | 改动 | 玩家视角公告三条 |
| `docs/C_PLUS_BASELINE_2026_09_29.md` | 新增 | P0 交付物 |
| `docs/C_PLUS_SCREENS_REPORT_2026_09_29.md` | 新增 | 本文件 |

### 2.1 回退开关怎么用

```python
# api.py
ARENA_SCREENS_MODE = 'v2'          # 改成别的一律失效（= 整批回退）
ARENA_SCREEN_LIST = 'lobby room placement collection leaderboard profile ' \
                    'result spectate replay settings'
```

- **整批回退**：`MODE` 改掉，或删掉 `index.html` 里那一行 `<link>`。
  → 十屏立刻回到改动前的样子（新样式表整个不生效；JS 那几处是增量行为，见 §5.3）。
- **单屏回退**：从 `LIST` 里删掉那个 token（例如 `collection`）。
  → 该屏的样式整块失效，其余九屏不受影响。
- 它**不向玩家暴露**：值是服务端渲染进 `<html>` 的静态属性，界面上没有任何入口。

---

## 3. 公共词汇（十屏共用，都在 `arena_screens.css` §0–§8）

| 词 | 取值 | 出处 |
| --- | --- | --- |
| 面板 | `--surface-strong` 底 + 1px `--border` + **12px** 圆角 + **无阴影** | 示意稿 C 的 `.card-panel` |
| 海 / 大面 | **14px** 圆角 + 青色内发光 | C 的 `.sea` |
| 屏头 | 10px/.19em 的 kicker（紫）+ 24px 左对齐标题 + 12px 副题 | 原型 `.suite-heading` + `.eyebrow` |
| 小标题 | 11px + 字距 .18em + `--muted`，下面一条**虚线** | 原型 `.section-title>span` / `.pf-block-title` |
| 胶囊 | `--fluent-radius-full` + 1px 描边 + 11px 文字，数字一律等宽 | C 的 `.s-tag` / `.t`.stat |
| 主行动 | 紫渐变（`--ax-grad`）+ 辉光；次行动描边；三级透明底 | C 的 `.hero-card` / `.bigbtn` |
| 列表行 | 1px **虚线**分隔 + 悬停淡紫；"我"那一行左侧紫条 | C 的 `.ach` / 原型的 `.self-row` |
| 空态 | 虚线框 + 46/20 内边距 + 150 最小高 | 原型 `.empty`（原型的加载态不存在，是补的） |
| 加载态 | 三条骨架 + 呼吸；`prefers-reduced-motion` 下静止 | 补的（原型全是同步静态样本） |

**颜色一律走别名层**：`--ax-gold: var(--arena-gold, var(--accent))` 这样的写法让
**同一份结构在任何主题预设下都成立** —— arena 预设拿到示意稿 C 的原色，
其余预设（含 `custom`）落到当前预设的通用令牌上。这一层是 §5.1 那条决定的前提。

---

## 4. 逐屏：与原型不同的地方，以及为什么

原型有而正式版**没做**的，逐条给了理由；其余都是"同一套词汇换皮"。

| 屏幕 | 有意不做 / 改做的 | 理由 |
| --- | --- | --- |
| 大厅 | ① 不做「房间卡片网格 + 插图带」，房间仍是列表行<br>② 不做「在线好友」面板 | ① `lobby_check.mjs` 钉着 `.lobby-columns` **恒 3 条 fr 轨道 + 4 块 `.lobby-panel`**；改成卡片网格就得改这条判据，而它守的是"四块面板都在"这个真契约<br>② 正式版的在线好友能力在 `#friends-modal` 里（独立入口），大厅再放一块就是第二个入口 |
| 好友房 | 不做「双方准备 / stepbar」 | 正式房间状态机 `waiting → placing_ships → rps → attacking → game_over` 里**没有 ready 位**；实施方案 §2 明文要求"按现有建房/入房/开局机制展示，不因 UI 改版新增握手协议"。stepbar 同理：这一屏只在 `waiting` 出现，三步条会是纯装饰 |
| 布船 | 布局改成"左棋盘 + 右信息栏"（原型也是两栏），但没有原型的 6 格舰队槽 | 舰队槽要用 `#placed-count` 再画一遍 → 同一个事实两份渲染，正是本项目反复吃亏的形状；计数胶囊已经是那个信息的唯一出口 |
| 图鉴 | 详情用**同一个弹窗内换页**，不是原型的原生 `<dialog>` | 浮层互斥是按类名取全量元素实现的（`closeOverlaysExcept`）：在帮助弹窗之上再叠一层，点开一张卡会把帮助本身关掉。换页法没有这个问题，且窄屏上比嵌套弹窗更好退回 |
| 排行 | ① 前三名领奖台**做**了（数据 = 当前那张表的前三行）<br>② **不做**原型的「积分 / 胜场 / 胜率」指标切换 | ① 两个接口都是服务端排好序的，前三是真数据<br>② 实施方案 §3 要求"按接口实际支持的指标提供排序"——而 `/api/leaderboard` 与 `/api/ranked_leaderboard` **都不支持排序参数**，且前者有 `limit<=100` 的截断。在前端重排只会得到"这一页里的第一名"，页面却写着全服榜 → 宁可没有这个控件 |
| 档案 | 查看面保持 560px 宽的名片（不改成原型的"左卡 + 右三块"） | 那是 `buildProfileCard()` 的既有结构，5 个查看入口共用；重排它要动 `profile_card_check` / `profile_leaderboard_check` 的十几条断言，收益只是排版。本轮把封面罗盘环、无框指标、虚线分区都补上了 |
| 结算 | 判定头是**横向 hero**（徽记 + 判定 + 右侧胶囊），不是原型居中的仪式化大块 | `.over-head` 是 flex row（§35.11 的既有结构，`recent_opponent_check` / `level_check` / `ranked_check` 都在量它）。45° 方块放进 `.over-verdict` 那一列会变成"列的第一行"且光环溢出面板圆角（实测截过图）。徽记因此改成不旋转的圆角方块，挂在 `.over-head::before` 上 |
| 观战 / 回放 | 全部沿用既有结构，只换皮 | 这两屏的**不变量优先**：`.spectate-board` / `.replay-board` 是净化快照与逐帧比对的落点，一格都不能动 |
| 设置 | 预览面板放进「外观与主题」分区顶部，不做原型那种独立右栏 | 正式版是"左导航 + 四分区"（实施方案 §2 要求保留原入口与持久化机制）；再开一栏会与那个契约打架 |

---

## 5. 三处需要单独交代的工程判断

### 5.1 门控**不含**主题预设（与实施方案 §5 的行文不同）

§5 建议"用 arena 预设和目标屏根类限定作用域"。落地时**没有**把预设放进门控：

- `data-theme-preset="custom"` 的语义是"玩家动过主色微调"。把它排除在外，
  等于**改一下强调色，十个屏整层结构退回 Fluent** —— 那是把布局轴绑在颜色轴上的典型症状。
- §5 自己写着"布局选择与颜色预设分开，避免破坏现有主题契约"；
  首页的 C 三栏（`.home-wrap`）也没绑预设、只绑结构。
- 于是：**结构**由开发开关 + 屏清单管，**颜色**继续全部来自预设给的令牌
  （`--ax-*` 别名层，`var(--arena-x, 兜底)`）。

### 5.2 为什么单开一个 CSS 文件

`tools/fluent_css_metrics.mjs` 的 AC6 预算只统计 `static/style.css`，而那里
hex 只剩 10、重复选择器只剩 1 的余量（实测 100/89/31/31 对阈值 110/180/40/32）。
这十屏的原型词汇有大量裸色，追加进去当场顶爆。新文件不进 AC6 统计，
但纪律照旧：能用令牌就用令牌，**只有令牌里确实没有的颜色**（原型的紫调胶囊底、
金色光晕、海面内发光）才写裸值，且都收在 §0 的别名层里。

### 5.3 JS 那几处新增行为要不要一起回退

样式层是"删 `<link>` 即回退"，但 JS 的三处新增是**增量行为**，不回退也**不会坏**：

| 行为 | 不回退时的表现 |
| --- | --- |
| 图鉴点卡 → 详情 | 桌面右栏（`.ax-codex-detail`）失去样式后仍会写入内容，但会显示成弹窗里一段普通文本；窄屏的换页类名 `.ax-show-detail` 失效 → 详情写进右栏，网格照旧显示 |
| 领奖台 / 自己那一行 / 「档案 ↗」 | `#leaderboard-podium` 的 `.hidden` 初值仍在，但渲染后会被显示成无样式的一段块（功能仍是可点的真实入口） |
| 可读性开关 | 开关仍写 `data-motion` / `data-contrast`，但 §40 的样式在（它不在门控里，不受回退影响） |

⇒ 若某屏要**彻底**回到改动前，正确做法是 `git revert` 那一批提交（实施方案 §5
"若某屏的 DOM 变更无法通过开关恢复，明确采用回退该批提交"），而不是只删 token。
逐屏 token 的用途是**对比与快速看效果**，不是"半关机"。

---

## 6. 门禁结果

全部在 `.tmp/cplus.db`（移植的测试库）+ 端口 5057 的隔离服务端上跑。

| 门禁 | 结果 |
| --- | --- |
| `python -m pytest tests/ -q` | **2622 passed / 1 failed**（66.55s）—— 与改前基线**逐位一致**；红的仍是 `.workbuddy/**` 那条环境性假红 |
| `tools/cplus_screens_check.mjs`（新增） | **全绿**：十屏 × 三视口（1440×900 / 1280×720 / 390×844）各 4 条 + 图鉴窄屏详情往返 5 条 + 零 JS 异常 |
| `tools/fluent_css_metrics.mjs` | PASS（hex 100 / rgba 89 / !important 33 / dupSel 31，阈值 110/180/40/32） |
| `tools/fluent_css_lint.py` | `style.css` 块结构 OK |
| `tools/fluent_style_check.mjs` | **全部通过** —— 含圆角档位（`#find-match` 12 / `#custom-create-room` 12 / `.modal-content` 12 / `.nav` 8 / `.theme-card` 12）与"arena 形状签名只有一个取值" |
| `tools/dom_contract_check.mjs` | 通过（439 个 id / 396 个引用，`MUST_KEEP` 一个没丢） |
| `tools/card_compendium_check.mjs` | 全部通过 |
| `tools/codex_realcard_check.mjs` | 全部通过（比例 0.715 / 9 行截断 / 底图 3 层 / 可滚动） |
| `tools/card_text_fit_check.mjs` | 全部通过 |
| `tools/ui_layout_check.mjs` | **全部通过**（宽 5 档 + 紧凑 6 档，含"页面无 JS 异常"） |
| `tools/lobby_check.mjs` | 全部通过（三列 = 3 条 fr 轨道 / 四块面板 / 零横向溢出 / 零 JS 异常） |
| `tools/profile_card_check.mjs` | ✓ 全部通过 |
| `tools/profile_leaderboard_check.mjs` | ✓ 全部通过 |
| `tools/dom_replay_frame_check.mjs` | OK 108 项全绿 |
| `tools/replay_check.mjs` | 全部通过（**连跑 2 次**） |
| `tools/sfx_check.mjs` | 全部通过 |
| `tools/bgm_check.mjs` | 全部通过 |
| `tools/spectate_check.mjs` | 146 PASS / **8 FAIL** —— **改前就是红的**，见 §6.1 |
| `tools/wallpaper_check.mjs` | 30 PASS / **3 FAIL** —— **改前就是红的**，见 §6.2 |
| `tools/room_invite_check.mjs` | 全部通过（建房 → 复制邀请链接 → prompt 兜底 → 零 JS 异常） |
| `tools/ranked_check.mjs` | 26 PASS / **3 FAIL** —— **改前就是红的**，见 §6.4 |
| `tools/friend_invite_battle_check.mjs` | **49 PASS / 2 FAIL** —— 那 5 条原来的红是本轮修掉的（helper 从未入库），剩下 2 条改前就有，见 §6.5 |
| `tools/cplus_path_check.mjs` | **新增，全绿** —— 一条连续路径：首页 → 大厅 → 建房 →（B 从大厅加入）→ 部署 → 猜拳 → 对局 → 投降 → 结算 → 首页 → 战绩 → 小局详情 → 回放 → 返回首页，零 JS 异常 |

### 6.1 观战那 8 条红与本次改动无关（对照实验）

症状全部落在同一簇：**服务端连锁栈为空**（`{"chain_len":0,"state":"attacking"}`）、
「没有待处理的连锁请求」、以及"观众那条连接收到的连锁帧里没有那张牌"。
这是 socket/规则层的事实，样式层改不出来。

**对照实验**：把 `spectate` 从 `ARENA_SCREEN_LIST` 里删掉（= 该屏的 C+ 层整块失效），
重启服务端再跑一次 —— **结果逐字相同：8 FAIL / 146 PASS，红的还是那 8 条**。
⇒ 判为**改前就存在**（本项目对这支工具早有"连锁断言脆"的记录，见
`docs/SPECTATE_BATCH7_2026_09_23.md`：连锁帧只存在 3~17ms；这里连"前提"那条
`chain_len == 1` 都没成立，说明是**出牌那一步**在本次环境里没有形成连锁窗口）。

### 6.2 壁纸那 3 条红也是改前的（HEAD 对照）

症状：缩略图 `/api/wallpaper/preview/...` 的 `<img>` 永远 `complete:false / w:0`，
也就是**无头浏览器解不出那张 BMP 缩略图**。

**对照实验**：`git worktree add .tmp/baseline-tree HEAD`，在**未改动的 HEAD 树**上
跑同一支 `wallpaper_check.mjs`（它自带 fixture 服务端，不依赖我的隔离库）——
**同样 3 FAIL / 30 PASS，红的还是那 3 条**。⇒ 环境性问题（无头 Edge 的 BMP 解码），
与这十屏无关。（对照 worktree 已 `git worktree prune` 清掉。）

### 6.3 一次假红：`replay_check` 第一次跑挂了

第一次是 "连续 5 次都没拿到先手（猜拳是随机的，应属极小概率）" ——
但玩家固定出「剪刀」时，AI 拿到先手的概率是 2/3，**连输 5 次 ≈ 13%**，
不是"极小概率"。同一条命令**连跑 2 次全绿** ⇒ 判为工具的随机性假红，不是回归。
（这一屏本轮只改了 CSS；`REPLAY_STEP_MS` / `REPLAY_SPEEDS` / `#replay-board-1,2`
三条 pytest 冻结项也都在。）

### 6.4 `ranked_check` 那 3 条红：**HEAD 对照逐字相同**（数据驱动）

红的 3 条：`B9 段位榜里同时存在「顶端段位行」与「低段位行」`（返回
`{"skip":"top=false low=true"}` —— 我造的测试库里 6 个段位玩家的分数都在 850–1300，
**没有一个是船长及以上**）、`★ C7 别人关掉「段位公开」时接口给的是 null`、
以及它之后的 `等待超时: 别人名片渲染`（工具自建的 `rb_mid<后缀>` 账号在这个人工库里没落上）。

**对照实验**：`git worktree add .tmp/base2 HEAD` + 把同一份库（含 `-wal`/`-shm`
**必须一起拷**，只拷 `.db` 会读不到 WAL 里刚提交的行）指给它、端口 5058 起服务，
再跑同一支 `ranked_check.mjs` —— **26 PASS / 3 FAIL，红的还是那 3 条**。
⇒ 与这十屏无关。（这一段顺便量出"ranked_check 需要库里真有 ≥1 个顶端段位玩家"。）

### 6.5 `friend_invite_battle_check`：5 条红是**本轮修掉的**，剩下 2 条改前就有

**第一次跑是 43 PASS / 5 FAIL**，5 条全由 `{"ok":false,"error":"python 探针命令超时 #1"}` 派生。
当时我用 HEAD 对照证明"两边一样红"，但**根因不是环境** —— 是**这支工具的陪练脚本
`invite_occupy_probe.py` 从未入库**：

- `friend_invite_battle_check.mjs` 硬编码 `spawn('python', [.tmp/invite_occupy_probe.py, …])`；
- `git log --all -- '*invite_occupy_probe*'` **为空** —— 这个文件从来没有进过版本库；
- 干净检出上那个路径不存在 → python 立刻退出 → 工具永远等不到回话（超时 → 5 条连带红）。
- HEAD 对照之所以"一样红"，是因为**两边都缺这个文件** —— 那条对照只证明了"不是我改坏的"，
  没有证明"改前是好的"。这是我这轮做对照时的一个盲点，记在这里。

**修法**：把陪练补成受版本控制的一等文件 `tools/invite_occupy_probe.py`，并把 `PY_HELPER`
指过去。它实现了工具期望的三条命令（`mkroom` / `joinroom` / `occupy_probe_only`）与
`probe_connected` / `cmd_result` / `fatal` 三种输出；两处容易踩的坑都写进了它的注释：
  ① **必须"登录失败就注册再登录"** —— 工具只注册 A/B/A3/B3 四个身份，
     探针的 `invchk_p/q/r<后缀>` 从来没人注册过，那是陪练自己的活；
  ② 身份复核**不能读 `/api/profile` 的 `profile.username`**（那个字段不存在），
     要读首页 HTML 的 `window.__USERNAME`（与工具那支 `authCookie()` 同一口径）。

**结果：49 PASS / 2 FAIL**（`python 探针命令超时` 彻底消失，B 组边界用例全绿：
重复 join 被拒、第三个身份被「房间已满」挡住）。

剩下的 2 条 **在 HEAD 上逐字相同**（同库、同工具、helper 两边都有 → 49/2）：
- `★ 9s 两边摆船 + 确认之后这一局真的开起来了（A3 侧切到猜拳/对局屏）`
  —— 失败发生在**场景③（解散后重新邀战的那一局）**；
- `★ 9t 第二次邀战建的那间房里坐着 A3 + B3 两个人` —— 派生（那一刻房已不存在）。

⇒ 判为**改前就存在的缺陷/环境问题**（在"解散房间 → 再邀一次"这条边界上第二次开局的
那一段），与 C+ 十屏无关。**主流程的"部署与开局"是绿的**：
`★ 7 [修复后要求] 两边都推进到了猜拳/对局屏（= 这一局真的能开） -> {"A":["rps-screen"],"B":["rps-screen"]}`
—— 所以实施方案 §4 P3 要求的"两个真实浏览器走完整创建、邀请、加入、部署与开局"
**拿到了全绿证据**。

## 7. 过程中修掉/重定的东西

### 7.1 `tools/card_compendium_check.mjs` 的过期死数字（**改前就是红的**）

断言写死 `unique === 41 && raw === 43`。卡表在 `a1fbc4e`（新增兵粮寸断）之后变成
**50 条目 / 48 唯一**，这条自那以后一直是红的 —— 红的是**工具**不是功能。
同一条判据已在 `tools/codex_realcard_check.mjs` 里改过（"从 `static/magic_card.json`
现算唯一卡名数，而不是再换一个死数字"），这里按同一口径补齐。
（已确认 `magic_card.json` / `magic_cards.js` / 本工具在本轮之前都未被改动。）

### 7.2 看图看出来的一个真缺陷：名片编辑面的左导航四颗全像"选中"

**症状**：编辑面（`#profile-modal` 的 `#profile-edit`）那颗左导航，四颗按钮在 arena 下
全是**不透明的实心紫**，而"选中"那一颗反而是淡紫（`--primary-50`）——
于是**选中态看不出来**（实测计算值：未选 `rgb(157,132,245)` = `--primary`，
选中 `rgba(124,92,240,.16)`）。

**根因**：`.pf-editor-nav-item` 只被并进了那个"盒模型 + 文字色"的分组规则
（`style.css:5580`），**漏了背景**；而基础规则是
`button, .btn, .modal-btn { background-color: var(--primary) }`。
`.settings-nav-item` 有自己单独一条规则（`:5753`）里写了 `background: transparent`，
所以设置面没这个毛病 —— 两屏同形不同命，正是"同一个形状两份写法定会漂移"的老病根。

**修法**：在 C+ 层里给定 profile 的未选项显式 `background-color: transparent`，
选中项 = 紫调胶囊 + 品牌色描边 + `--text` + 左侧 3px 紫条（与大厅/观战"我那一行"同一手法）。

### 7.3 顺带收掉的一处层级噪音

设置面里音频（播放/上一首/下一首）与壁纸（扫描/导入/应用）那 8 颗控件走的是基础按钮规则，
默认就是**实心紫** —— 一度让设置面出现 8 颗"主行动"，把"主行动只有一颗"这条层级冲掉了。
现在它们统一降到描边档，全屏唯一的实心主行动是底部那颗「保存」。

### 7.4 一次自己踩的坑（记下来免得下次再犯）

给图鉴条目加 4px 内边距 → 卡片是 `width:100%; max-width:168px` 而 **高写死 235px**，
内容盒变小后卡片缩到 **163×235**，比例掉到 0.693，
`codex_realcard_check` 的 0.715 判据当场红。→ 外层容器 padding 必须是 0。

### 7.5 一次工具口径的坑（自查用）

查"哪些按钮底色是实心主色"时，第一次写的探针用
`#leaderboard-tabs .lb-tab` 当"未选中"、`#leaderboard-tabs .lb-tab.active` 当"选中" ——
但页签的**第一颗本来就是选中的**，两条选择器命中的是同一个元素，
于是得出"选中/未选一模一样"的假结论。正确的取法是 `:not(.active)`。
（真结论：页签未选 = `--surface-muted` 不透明底 + `--text-subtle`，
选中 = 紫调 + 品牌描边 + `--text` + 内描边环 —— 区分是够的。）

---

## 8. 还剩什么

1. **没有提交**。实施方案 §4 的 P5 写着"每批独立提交"，但本次会话是在
   "只改、不提交"的前提下推进的（仓库规矩：提交/推送只在明确要求时做）。
   改动集合见 `git status`；建议提交时按批拆（P1 公共层+图鉴 / P2 三屏 /
   P3 三屏 / P4 三屏 / 文档与工具），或者至少把
   `static/arena_screens.css` + `templates/index.html` + `api.py` 放一起
   （三者是同一个开关的三条腿，拆开会出现"样式在、门控不在"的中间态）。
2. **`custom` 与其余 7 个预设下的观感没逐屏出图**：结构会在、颜色会落到各自预设的
   令牌上（§5.1 那个决定的预期结果）。`fluent_style_check` 已覆盖 8 预设 × 明暗两态的
   形状与对比度，但没有像 arena 那样逐屏截图核对。
3. **原型里"选稿用"的部分一律没做**：侧栏、10 屏导航、`01 / 10` 页码、前后屏切换、
   页脚字串 —— 实施方案 §2 已定为"只用于选稿，不进入正式游戏"。
4. **大厅没有"房间卡片网格"**（见 §4 第一行）：要做得先和 `lobby_check` 的
   "3 条 fr 轨道"判据重新对齐口径。
5. **四处改前就红的门禁**：`spectate_check` 的 8 条连锁断言（§6.1）、
   `wallpaper_check` 的 3 条 BMP 缩略图断言（§6.2）、`ranked_check` 的 3 条（§6.4）、
   `friend_invite_battle_check` 的 2 条（§6.5，场景③"解散后重新邀战"的第二局）。
   都不在本次范围内，但**都还没修** —— 下次动这些地方时它们会继续红，
   别误判成新回归（判据：按那四节的做法跑一遍对照，或直接读它们各自的"已知红"条目）。
   ★ 本轮顺带修掉的是"**工具本身在干净检出上跑不起来**"这一档（§6.5 的陪练缺失）：
   那类问题最坑 —— 它让"改前对照"也一起红，于是对照实验只能证明"不是我改坏的"，
   证明不了"改前是好的"。下次做对照前先确认**工具自己能不能跑**。
6. **对局屏与紧凑档没碰**：实施方案 §2 明确"本轮不重做已实现的首页和对局主屏"，
   所以 `.board-tab` / `.dock-tab` 这类局内控件的"实心紫底色"没动
   （§7.5 的审计里能看到它们，属于另一屏的事）。

## 9. 出图存档

- 十屏 × 三视口（1440×900 / 1280×720 / 390×844）= 30 张：
  `.tmp/cplus/final2/<视口>/<屏>.png`（由 `cplus_screens_check.mjs --shots` 落盘）
- 逐屏细看：`.tmp/cplus/shots2/`（第一轮）与 `.tmp/cplus/probe-*.png`（各次探针）
- 这些都在 `.tmp/`（gitignored），**不是交付物**；要长期留档就把需要的几张
  拷进 `docs/ui_demos/shots/` 并写进对应的 docs。

---

## 10. 分批提交（实施方案 §4 P5「每批独立提交、独立验收」）

提交在**分支 `cplus-screens`** 上（工作区当时就处于"用户已暂存了一批与本轮无关的改动"的
状态，按"在默认分支上先开分支"的规矩，没有直接落到 `main`）：

| 批 | commit | 主要内容 |
| --- | --- | --- |
| P1 | `4d8e643` | 新增 `static/arena_screens.css`（公共层 §0–§9 + 图鉴，683 行）、`api.py` 门控、图鉴详情接线、`card_compendium_check` 的过期断言重定、基线文档 |
| P2 | `e1829f4` | 领奖台与本人高亮、名片与设置换皮、两个可读性开关（含 `style.css` §40） |
| P3 | `14d1029` | 大厅 / 好友房 / 布船（含 `#ship-placement-screen` 的左右分栏） |
| P4 | `7011106` | 结算判定头、回放与观战换皮 |
| P5 | `HEAD`（收尾批） | 跨屏验收工具、好友邀战陪练补回、`changelog.py` 公告、CLAUDE.md 索引、本报告 |


> ⚠️ P5 的 hash 不写死：这份报告本身就属于 P5，而"把 hash 写进报告"会改变 P5 的 hash
> （自指）。要看具体 hash 用 `git log --oneline main..HEAD`（顺序是 P5 → P1）。
> P1–P4 的 hash 是稳定的，可以直接引用。

每批**单独验收**用到的工具与结果（都是前面几节里跑过的同一条命令）：

| 批 | 该批的验收入口 | 结果 |
| --- | --- | --- |
| P1 | `codex_realcard_check` · `card_compendium_check` · `card_text_fit_check` · `dom_contract_check` · 新图鉴的窄屏详情往返 | 全绿（卡面比例 0.715 / 说明不截断 / 底图 3 层） |
| P2 | `profile_card_check` · `profile_leaderboard_check` · `fluent_style_check`（圆角与形状签名）· `fluent_css_metrics`（AC6） | 全绿；`ranked_check` 的 3 条红为数据驱动（§6.4） |
| P3 | `lobby_check` · `room_invite_check` · `friend_invite_battle_check` · `ui_layout_check` | 全绿 / 2 条改前就有的红（§6.5） |
| P4 | `replay_check`（连跑 2 次）· `dom_replay_frame_check`（108 项）· `spectate_check` | 全绿 / 8 条改前就有的红（§6.1） |
| P5 | `pytest`（2622/1，与基线逐位一致）· `cplus_screens_check` · `cplus_path_check` | 全绿 |

### 10.1 一处必须说清楚的事：共享文件里带着用户既有的暂存改动

开工前工作区就已经有**用户已暂存的改动**（`git diff --cached` 13 个文件 / 1051 行），
而我这轮的改动是**叠在它们之上**的（`arena_screens.css` 覆盖它们的 §39、
`index.html` 挨着它们加的三栏标记）。所以四个共享文件
（`static/game.js` / `templates/index.html` / `static/style.css` / `CLAUDE.md`）
在这些提交里**同时包含它们已暂存的那部分** —— 这不是顺手捎带，而是"我的 hunk 需要那个基准"
（把两者拆开会产生无法工作的中间树）。

- 与本轮**无关**的 9 个暂存文件（卡面提示词、`card_art_map`、`chain_stack_check`、
  `fluent_css_metrics`、`gen_card_art_prompts` 等）**原样留在暂存区**，一个都没进这些提交；
- 用户既有暂存的完整快照（可恢复用）留在 `.tmp/preexisting-staged.patch`；
- `main` **没有动**：合并与否由作者决定（`git merge --ff-only cplus-screens` 即可快进）。
