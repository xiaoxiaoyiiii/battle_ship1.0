# C+ 十屏 · 本轮实施报告（交付记录）

日期：2026-09-29。执行对象：`docs/C_PLUS_AGENT_HANDOFF_2026_09_29.md`（下称"任务书"）。
基线 HEAD：`2b1e1825a0d4cec17110e117f6783717e808679d`（工作区另有用户既存改动，见 §8）。
本文**只记本轮真实跑出来的结果**；旧报告 `docs/C_PLUS_SCREENS_REPORT_2026_09_29.md`
保留为历史，其中已失效的当前状态声明在 §7 逐条更正并指回本文。

**当前增量结论见 §12。**§0、§5.5、§6、§7.4、§7.5、§9 和 §10 中的数字与残余项是前一阶段快照，
不能再作为最终状态引用；§12 记录本次补齐、复跑和仍未验证的边界。

---

## 0. TL;DR

| | 基线上的状态 | 本轮结束时 |
| --- | --- | --- |
| `pytest tests/` | 1 failed / 2622 passed（`.workbuddy` 扫描误报） | **0 failed / 2623 passed** |
| `tools/cplus_screens_check.mjs` | 96 PASS / 0 FAIL —— 但门控断言**恒真**、半径断言被静默跳过 | **321 PASS / 0 FAIL**，且带 `--self-test` 自校准 |
| 逐屏门控（`tools/cplus_gate_check.mjs`） | 该工具**不存在**；实测删 token 后 7 屏仍带 C+ 样式 | **223 PASS / 0 FAIL**（8 个服务端配置用例 + 主题轴矩阵） |
| `tools/spectate_check.mjs` | 146 PASS / 8 FAIL | **156 PASS / 0 FAIL**（1 个真产品缺陷 + 1 个工具读法缺陷） |
| `tools/wallpaper_check.mjs` | 30 PASS / 3 FAIL | **33 PASS / 0 FAIL**（工具夹具缺陷，**不是** BMP 解码问题） |
| `tools/ranked_check.mjs` | 26 PASS / 3 FAIL（旧报告）→ 本次基线 69 PASS / 4 FAIL | **73 PASS / 0 FAIL** |
| `tools/friend_invite_battle_check.mjs` | 49 PASS / 2 FAIL | **51 PASS / 0 FAIL（连跑三次）** |
| `tools/lobby_check.mjs` | 全绿 | 全绿（骨架断言未被破坏） |
| `tools/cplus_path_check.mjs` | 全绿 | 全绿（22 项，真实两客户端全链路） |
| `tools/fluent_css_metrics.mjs --summary` | 该模式**不存在** | 新增；C+ 层不再能靠"拆文件"绕过预算 |

新增 8 支定向工具：`cplus_gate_check` / `cplus_state_check` / `cplus_deploy_check` / `cplus_lobby_check` / `cplus_profile_check` / `cplus_room_check` / `cplus_gameover_replay_check`（+ 上一批已有 `cplus_screens_check` / `cplus_path_check`）。

**任务书的 10 条问题（A01–A10）与 4 条工作包（W0/W1/W2/W6）已落地并各有可复跑的证据；
W3/W4/W5 的"布局收口"只完成了一部分**，剩余项在 §7.4 逐屏列出，未完成的不写成完成。

---

## 1. W0 · 固化现场与修复验收（A01 / A10）

### 1.1 A01：门控断言恒真 + 半径断言被跳过【已修，带自校准】

任务书 §3.1 点名的两处：

* `tools/cplus_screens_check.mjs` 里 `hit: !!(list.split(...).indexOf(key) >= 0) || !!(mode === 'v2')`
  —— `indexOf` 先 `!!` 成 boolean 再 `>= 0`，**boolean 与 0 比较恒真**；`||` 又让总开关一开就无视屏清单。
* 返回值字段叫 `r.markerRadius`，判据却读 `screen.markerRadius`（`screen` 上没这个属性）⇒
  `if (r && screen.markerRadius)` 永远不进，十屏一次圆角都没验过。

修法（不保留 OR、不用手抄第二份字符串）：

* 门控谓词 `gateHit(mode, list, key)` 在 Node 侧**只定义一次**，`toString()` 插进探针，
  于是"工具自己判"和"页面里判"不可能漂移。
* 半径判据 `radiusOk(value, allowed)`：**量不到（null/空串）也判不合格**，不再"量不到就跳过"。
* 新增可见性判据 `visibleOk()`：display/visibility/opacity/非零宽高/落在视口内。

自校准（`node tools/cplus_screens_check.mjs --self-test`）：

```
PASS  自校准 · 门控谓词 14 条用例全部正确                        {"wrong":0}
PASS  自校准 · 错误的旧表达式在同一批用例上确实被判错（说明用例有区分力）  {"legacyWrong":"9/14"}
PASS  自校准 · 探针里那份**字符串化之后**的门控谓词行为一致（空白切分没被转义坏） {"wrong":0,"cases":14}
PASS  自校准 · 半径判据 7 条用例全部正确                          {"wrong":0}
PASS  自校准 · 可见性判据 7 条用例全部正确                        {"wrong":0}
✓ 自校准通过（门控/半径/可见性三类断言都能判 FAIL）
```

"生成后测试"是任务书明确要求的那一条：从**真正会发出去的探针文本**里把那段函数抠出来重新求值，
所以 `/\s+/` 被转义坏、或拼接丢大括号，当场就红（这一条在开发中就抓到过一次真问题）。

### 1.2 检查项扩充（任务书 W0 第 3 条）

除原有四项外，`cplus_screens_check` 现在还会量：

* 标记物**可见性**（display/visibility/opacity/宽高/视口）；
* **屏内容器的局部溢出**（不只 `document.scrollWidth`）——逐屏取该屏根容器与后代里最宽的那个；
* **关键按钮是否被浮层/装饰挡住**（`elementFromPoint` 命中判定）；
* **关屏收尾**：残留浮层数、还有没有别的屏 `active`、焦点是否留在已关容器里、本屏是否还占布局高度。

### 1.3 无浏览器 = SKIP（不是 PASS）+ 生命周期（任务书 W0 第 5 条）

* 无浏览器时打印 `SKIP … 这**不是通过**，是未验收。` 并以**退出码 2** 结束
  （原来 `process.exit(0)`，汇总方只看退出码就会当成通过）。
* `--browser` 显式给路径时也做存在性检查（拿不存在的路径去 spawn 报的是 Node 的 ENOENT 栈，像"工具坏了"）。
* 浏览器实例、CDP 连接、服务器进程全部包在 `try/finally` 里，**只杀自己起的那个 pid**，失败路径同样走清理。
* profile 一律落在项目 `.tmp` 下（`--profile` 可覆盖）。

### 1.4 `arena_screens.css` 的语法与预算（A10）

* `tools/fluent_css_lint.py` 增加 `--file`，默认**全量**检查 `style.css + arena_screens.css`。
  实测：两份都 OK；故意删掉一个 `}` 的副本被报出 240 处块结构问题（说明它真的在看）。
* `arena_screens.css` 补上 `/* @@TOKENS-END@@ */` 哨兵。
  **没有它的时候工具的边界是猜的**：退化成"第一个 `/* ---------- 2.` 之前都算令牌区"，
  于是整个第 1 节（屏头规则）被静默排除在 hex/rgba/!important 统计之外。
* `tools/fluent_css_metrics.mjs` 新增 **`--summary`**：按 `<link>` 顺序把两份**正文**拼成一份再量。
  同一选择器在两份里各写一次会算成一次重复（真实层叠里就是后者压前者），
  所以"把样式拆到第二个文件躲预算"这条旁路被堵住了。
* 预算**按作用域分别定、且没有无条件抬高**：
  * `style.css`：hex 110 / rgba 180 / !important 40 / dupSel 32 —— **一个字没动**。
  * `arena_screens.css`：hex **0** / rgba **0** / !important **0** / dupSel 16。
    前三项定成 0 是**比现状更严**（实测它本来就是全零），dupSel 16 是"基线 14 + 2 余量"
    （W1 之后实测降到 **12**，真实余量 4）。
  * `--summary` 的阈值 = 两侧逐项相加，并把"跨文件同名选择器"单独数出来
    （实测 **0**，所以"相加"这个口径成立）。

### 1.5 全仓源码守卫的扫描边界（任务书 W0 第 7 条）

`tests/test_pingdeng_tiaoyue_chain.py::test_dead_snapshot_key_is_gone_from_the_whole_repo`
原来扫到 `.workbuddy/`（`.gitignore` 里的本机审查缓存，含 AI 会话原文，里面有旧键名也有"该怎么删它"的说明）
⇒ 每跑必红且红得没信息。现在显式跳过一批**本机工具/审查缓存**目录，同时补一条
**"扫描面没有变瞎"**断言：受版本控制的正式源码与文档（`server.py` / `api.py` / `static/game.js` /
`templates/index.html` / `docs/CHAIN_ENGINE_SPEC.md` / `CLAUDE.md` / 本测试自身）必须真的在扫描集合里，
且文件数 > 300。**没有删除 `.workbuddy`，也没有放宽到看不见真实残留。**

证据（自证有效）：

```
在仓库根放一个 _guard_probe.py（含旧键名）→ 1 failed
删掉它                                  → 1 passed
```

---

## 2. W1 · 逐屏启用与退回合同（A02）

### 2.1 缺陷与修法

任务书 §1.2 实测的三行，本轮**先复现再修**：

```
总开 v2 + 全清单       hit=true  eyebrow="REPLAY"
总开 v2 + 仅 lobby     hit=true  eyebrow="REPLAY"   ← 两处问题同时出现
总关 off + 空清单      hit=true  eyebrow=null       ← 工具仍错误通过
```

新工具 `tools/cplus_gate_check.mjs` 把这件事变成 **8 个真实服务端配置**的负例
（配置经环境变量 → `api.py` → 模板渲染，**不是**在 DevTools 里改属性）：

| 用例 | 配置 | 期望 |
| --- | --- | --- |
| `full` | `v2` + 完整清单 | 十屏都是"开着"的样子（基线） |
| `off` | `off` + 完整清单 | 十屏全退，且**不留可见的 C+ 新容器** |
| `empty` | `v2` + 空清单 | 等价于全关 |
| `no-replay` / `no-room` | 删掉一个 token | **只**退删掉的那屏，其余九屏签名逐字节等于基线 |
| `only-lobby` | 只留 lobby | 只有 lobby 开着，其余九屏全退 |
| `unknown` | 清单尾加不存在的 token | 不该多开也不该少开任何一屏 |
| `odd-list` | 清单里多余空白 | 空白切分不能被写坏（仍等价全开） |

**基准不是写死的常量**：`full` 下量一遍 = "开着的样子"，`off` 下量一遍 = "关掉的样子"，
其余用例与这两个基准逐字节比对。于是"这一屏该长什么样"永远不需要人工维护常量。

修前 / 修后：

```
改前：212 PASS / 11 FAIL   （只留 lobby 的配置下，room/collection/leaderboard/result/
                            spectate/replay/settings 七屏仍带着 C+ 的标题样式；
                            总关状态下 #codex-detail 与 #settings-preview 是可见空块）
改后：223 PASS / 0 FAIL    （8 个配置用例 + 主题轴矩阵）
```

具体改动：

* `arena_screens.css` 新增 **§0.1 退回合同**：C+ **新加进模板**的容器
  （`#codex-detail` / `#settings-preview` / `#leaderboard-podium`）在"总开关或本屏 token
  任一不满足"时一律 `display:none`。写法是**反过来限定"不该显示"的那一侧**
  （`html:not([data-arena-screens="v2"]) …` / `html[data-arena-screens="v2"]:not([data-arena-screen-list~="X"]) …`），
  写进门里面必然漏掉"总开关关掉"那一半。
* 屏头三组公共规则（标题字号/左对齐、`::before` 版式、副题）**全部改成逐屏 token**。
* eyebrow 文案改成一个自定义属性 `--ax-eyebrow`：版式**一条规则管七屏**，
  各屏只在**屏根容器**上声明自己的文案。被关掉的屏没有这个变量 ⇒
  `content: var(--ax-eyebrow, none)` ⇒ **不生成伪元素**。
  这一步同时把 dupSel 从 16 降到 12（消掉了一批"同一选择器两个块"的死重复）。
* 顺带修了一处**漂移**：标题规则原来写 `#profile-modal .modal-content > h2`，
  而 CMDR 那套 eyebrow／名片皮肤全挂在 `#opponent-stats-modal` 上 ——
  查看面拿不到 24px 标题。现在两个面都归 `profile` 这一个 token。
* `static/game.js` 新增 `isArenaScreenEnabled(key)`，判据就是 `<html>` 上那两个属性
  （**不另建一份清单**）。图鉴详情渲染、领奖台渲染都走它；关掉那一屏时
  连 DOM 都不写。

**⚠️ 两个可读性偏好不受这套门控影响**（任务书 W1 第 5 条要求写明）：
`data-motion`（减少动效）与 `data-contrast`（高对比）是**独立的用户能力**，
`isArenaScreenEnabled()` **不判它们**，CSS 侧也把它们放在 C+ 那一层之外（`style.css` 第 40 节）。
所以把 `ARENA_SCREENS_MODE` 关掉、或删掉某一屏的 token，这两个偏好照样跨屏生效 ——
"退回旧样式"不该把无障碍设置一起退掉。

### 2.2 主题轴与布局轴分开

任务书 §3.3 第 6 条（"结构门控不绑 arena 颜色预设"）在本轮被**验成一条断言**：
`cplus_gate_check` 的第 7 组在 `full` 配置上把主题轴（dark/light × arena/custom/fluent）
挨个换一遍，要求十屏的布局签名**逐字节不变** —— 实测 50/50 通过。

其中 `custom` 一档的驱动方式踩过一次坑并记在工具里：`custom` **不是** `THEME_PRESETS`
的成员，往 `battleship_theme_preset` 里塞 `'custom'` 会被 `applyThemePreset()` 判非法并落回
`arena`（量到 `preset:"arena"`，看着像门控坏了，其实是驱动方式错）。正确做法是写
`battleship_primary_color` 并删掉 preset 键。

---

## 3. W2 · 状态一致性（A03–A07）

新工具 `tools/cplus_state_check.mjs`，用 CDP 的 `Fetch` 域把 HTTP 响应**扣住再按指定顺序放行**，
把竞争条件变成确定性用例。**并且验过这些用例有牙**：把守卫临时改成恒真之后，
A03/A07 一共 4 条由绿转红（见 §3.5）。

### 3.1 A03 排行领奖台（已修）
原状：`fetchLeaderboard` 成功后**没有活动页签判断**就写领奖台；段位榜的 token 切回战绩时也不失效。
现在两条榜的响应都只能从 `publishLeaderboardPodium(tab, token, …)` 落笔，两道门：
① 活动页签相同；② 自己那一代 token 仍是最新。行数据照缓存（切回页签时用），但**领奖台不在活动页签上就不动**。
16 项断言全过，含"战绩→段位（响应反序）"与"段位→战绩（响应反序）"两个方向。

### 3.2 A04 布船提交锁（已修 + W3 的六槽/清空/常驻确认）
见 §4.1，工具 `tools/cplus_deploy_check.mjs`（两视口 × 33 项）。

### 3.3 A05 结算原因文案（已修）
原状（任务书已复现）：胜方视角下 `reason='surrender'` 拼出 **「对方投降 · 击沉对方全部战舰」**。
现在：**"击沉…"只在 reason 为空（正常击沉）时出现**；有明确原因时用中性的"你获胜/你落败"。
覆盖任务书点名的全部情形：正常胜负、双方投降视角、掉线超时、操作超时、平局、未知原因。
另外核对过服务端**实际会发的 reason**（`server.py` 逐个查过）：
不传 / `surrender` / `opponent_disconnected` / 以及 `_finish_game(...)` 透传的**中文自由文本**
（如「神威！清空对方棋盘」）—— 自由文本原样输出，不退回"击沉"。
18 项断言全过。

### 3.4 A06 图鉴统计（已修）
做成 `idle/loading/ready/error` 四态 + 在飞 promise 共享：
* 非 2xx **当失败**（原来 `(r && r.ok) ? r.json() : {}` 会把 4xx/5xx 解析成空对象 ⇒ 界面显示"所有卡都用了 0 次"，一个假的数字）；
* 失败时写"使用次数暂不可用"+**重试**按钮，不再是永久"统计中…"；
* 重试成功后刷新网格**与当前已选详情**（"已用 N 次"能更新）；
* 并发三次调用**只发一个请求**（实测 `fetches:1`）；
* 重绘会整格换 DOM ⇒ 补了**焦点恢复**（按卡名找回同名那一格，不是"第 N 格"，筛完位置会变）。
11 项断言全过。

### 3.4b 图鉴手机详情的键盘路径 + 清掉工程用语（任务书 §W2 收尾的两条）

任务书 §W2 最后一句点名要求："补充图鉴手机详情焦点进入、返回原卡与 Escape 行为，
清理玩家界面的'卡表组件／令牌'等工程解释。" 三条都做了，并且是可断言的：

* **焦点进入**：窄屏点卡后 `.ax-codex-main` 被 `display:none` 收起，焦点留在原格等于"焦点消失"；
  现在焦点跟到详情页里第一个可聚焦元素（「← 返回图鉴」）。
* **返回原卡**：`codexShowList()` 按 `codexPickedName` 找回**同名那一格**并 `focus()`
  （不是"第 N 格" —— 筛完位置会变）；找不到（被筛掉了）才退回网格容器。
* **Escape**：只在**窄屏详情页开着**时用捕获阶段接管 Esc，`preventDefault + stopPropagation`
  —— 第一次 Esc 回列表、第二次交给上层关掉帮助弹窗（桌面档右栏常驻，不接管 Esc）。
* **工程用语**：`#settings-preview` 的副题从"主行动、棋盘格子与说明文字用的都是当前令牌。"
  改成"……都会跟着当前主题变。"；图鉴详情页脚从"手牌 / 连锁 / 图鉴读的是同一份卡表与
  同一个卡面组件，所以……"改成"效果以游戏内实际结算为准。"。

⚠️ 这一轮**顺带修了工具自己的一个坑**：`cplus_screens_check` 的窄屏图鉴流程**没有先打开帮助弹窗**
（上一步的收尾刚把它关掉），于是整棵图鉴都是 `display:none` ——
`offsetParent === null` 让"窄屏档"的判据**假成立**，`.ax-show-detail` 照样被加上，
看着像"切到了详情页"；但焦点落不进不渲染的子树、Esc 也不该被接管。
即"焦点的断言永远红，而且红得像是产品坏了"。现在流程先真的点开 `#help-btn`
并加了一条 `helpOpen === true` 作为后续断言的前提。

对应断言（`cplus_screens_check` 的 390×844 段，实测全绿）：
`focusInDetail` / `escapedToList` / `focusBackOnCard` / `focusAfterButton` 四项 + `helpOpen` 前提项。

### 3.5 A07 回放加载身份（已修）
`replayState.loadToken`：打开/退出/换局都 `++`，成功与失败路径都先核对
"身份没被作废 **且** 回放屏还开着"。第二个条件不能省 —— 只靠 token 时
"退出后再打开同一局"会因为 token 相同而把旧包当新包用。

**用例有牙的证据**（把守卫临时改成 `return true` / 摘掉两道门后重跑）：

```
FAIL  A03 战绩榜的慢响应**没有**覆盖段位榜的领奖台  ->  names:["A2","A1","A3"]（应全为 R*）
FAIL  A03 段位榜的慢响应**没有**覆盖战绩榜的领奖台  ->  names:["R2","R1","R3"]（应全为 A*）
FAIL  A07 A 局慢响应没有覆盖 B 局的回放内容（payload 是 B）  ->  texts:["A-step-0","A-step-1"]
FAIL  A07 退出回放后迟到的回包没有写回 payload      ->  payload:{…A…}
```

恢复守卫后 4 条重新变绿。

---

## 4. W3 已完成的部分（其余见 §7.4）

### 4.1 布船：提交状态机 + 六槽 + 清空 + 常驻确认

原状：一句 `socket.emit('place_ships', …, cb)`，**没有 pending 锁**（双击发两枪）、没有前置校验、
ack 失败只弹 alert、**没有超时处理**、成功之后界面什么都不变。

现在（任务书 W2 的 A04 第 2 / W3 的布船条目）：

| 要求 | 实现 |
| --- | --- |
| 按 room + 部署阶段维护 pending | `deployPending = {phase, roomId, at}`；`deployPhase` 在新开一局 / 卡牌重摆 / 离开这一屏 / 重连时 `++` |
| 确认前验证连接、阶段与六个有效唯一格 | `deployCellsValid()`：恰好 `maxShips` 个**有效且唯一**的格子，越界/重复/数量不符分别给原因 |
| 提交期间锁棋盘/随机/清空/确认 | `updateDeployControls()` 是**唯一刷新口**；棋盘 `pointer-events` + `handleCellClick` 里的真门 |
| ack 成功显示等待对手 | "已提交 · 等待对手摆好，双方都就绪后进入猜拳" |
| 拒绝恢复可修改 | 解锁 + 原样转达服务端原因 + 可再次提交 |
| 超时先同步房间状态再决定能否重试 | 6 秒超时后发 `rejoin_room`，由 `room_sync` 的 `current_phase` 决定"已推进 ⇒ 保持已提交"还是"仍未提交 ⇒ 解锁可重试"；**绝不盲目重发** |
| 退出/重连/新阶段清理或重建 pending | `switchScreen` 里（在 `hideAllScreens()` **之后**，理由见下）与 `socket.on('connect')` 里各一次 |
| 卡牌重摆不能被"已提交过"锁死 | `reset_gameboard` 与「绝处逢生」都调 `newDeployPhase()`；实测重摆后能再次提交 |
| 六槽（从同一 `gameState` 派生） | `#deploy-slots` 六格，写的是 `gameState.ships` 里的坐标 |
| 清空 | `#clear-ships` + `clearShipPlacement()` |
| 确认常驻、未就绪/pending 禁用并解释原因 | 按钮从 `hidden` 改为**常驻 + `disabled`**，原因写在 `#deploy-hint`（`role=status` + `aria-live`） |
| 添加坐标 | `#player-board` 首行/首列用 `::before/::after` + `attr(data-cx/data-cy)` 画 **1 起算**的坐标（不加 DOM 节点，不影响 6×6 网格） |

两处踩坑记在代码注释里：

* `switchScreen` 的守卫**必须排在 `hideAllScreens()` 之后** ——
  `tests/test_screen_overlay_registry.py` 冻结了"switchScreen 第一件事就是 hideAllScreens()"
  这条不变量，第一版写在前面那条测试当场变红（不变量没问题，是我改了语句顺序）。
* 部署状态用 `var` 而不是 `let`：`switchScreen` 由很多入口调用，
  其中有些可能在脚本还没求值到那一行时触发 —— `var` 提升后初值是 `undefined`（守卫跳过），
  `let` 是 TDZ 抛错（整个切屏炸掉）。

**判据更新（任务书记录旧判据的要求）**：三处工具原来断言"摆满 6 格后 `#confirm-ships` 从
`hidden` 变可见"，新约定下 `hidden` 恒不存在。已改为**更强**的断言并保留产品不变量：

| 文件 | 旧判据 | 新判据 |
| --- | --- | --- |
| `tools/cplus_path_check.mjs:253` | `confirmHidden === false` | **未摆满 → `disabled===true`**；摆满 → `disabled===false` |
| `tools/recent_opponent_check.mjs:971` | `btnHidden === false` | `btnDisabled === false` **且六槽 6/6** |
| `tools/friend_invite_battle_check.mjs` | 只记录 `confirmHidden` | 不变（它只是快照字段，没有断言） |

### 4.2 档案：查看面的宽屏两栏

任务书 §4.1「必须补」第 4 条：**查看面**在宽屏扩成「名片 + 数据／徽章／历史」两栏，手机回单栏。
原来宽屏下仍是 `style.css` 的 `.pf-view-modal { max-width:560px }` 那张窄名片，
一列到底、数据/徽章/历史全挤在名字下面。

实现**不动 DOM**，只给查看面加一层 grid（`arena_screens.css` §17.1，`@media (min-width:861px)`）：

* `.pf-cover` 横跨两栏；`.pf-hero`（头像/名字/称号/简介/经验条）占左栏；
  `.pf-stats` / `.pf-badges` / `.pf-favcards` / `.pf-history` / `.pf-guestbook` 依次落右栏；
* 用 `grid-row: 2 / span 99` 而不是给右栏每一项写行号 ——
  哪几块被 hidden（三个 `show_*` 开关 / 没徽章 / 没历史）都不需要改 CSS，右栏自动往上收；
* 只在 861px 以上生效，窄屏保持单栏；
* 只作用于**查看面**（`#opponent-stats-content .pf-card`），编辑面（`#profile-edit` 的 `.pf-editor`）一行不碰。

新工具 `tools/cplus_profile_check.mjs`（真注册一个一次性账号 —— 查看面是异步取数后才渲染的，
未登录时根本不渲染，那样量到的"两栏"是空气）。量的是**几何事实**而不是"看着像两栏"：

```
PASS [1440x900] 查看面是**两栏**（display:grid + 两列）          {"display":"grid","colCount":2}
PASS [1440x900] 名片在**左**、数据在**右**（按 x 坐标比）        {"heroX":333,"statsX":668}
PASS [1440x900] 数据与徽章墙在**同一栏**（x 相同）               {"statsX":668,"badgesX":668}
PASS [1440x900] 封面横跨两栏（比名片那一栏宽）                    {"cover":{"w":764},"hero":{"w":317}}
PASS [1440x900] 弹窗比原来的 560px 窄名片宽                     {"modalW":800}
PASS [390x844] 窄屏回到**单栏**（不是 grid 两列）                {"display":"block","colCount":1}
PASS [390x844] 窄屏下名片与数据块竖着排（x 相同、数据在下方）
```

回归：`profile_card_check` / `profile_leaderboard_check` / `fluent_style_check` 改后重跑**都全过**。
截图：`profile-two-col-1440x900.png` / `mobile-profile-two-col.png`。

### 4.3 大厅：搜索 + 状态筛选 + 卡片行

任务书 W3 的大厅条目里的新功能部分：

* `#lobby-room-search`：**统一**搜索房名 / 房主 / 房间号，同时作用于「房间列表」与「进行中的对局」两块列表；
* `#lobby-room-filter`：全部 / 可加入 / 已满 三档分段；
* 满员房的「加入」按钮**禁用**并写明原因（原来只有 `2/2` 这个数字，玩家要自己换算）；
* 两级空态：「没有符合条件的房间（共 N 间在等…）」vs「暂无等待中的房间，可以创建一桌」；
* 行做成卡片（`surface-strong` + 描边 + 圆角），面板骨架不动；
* **订阅刷新不重置筛选与输入**：筛选值每次从 DOM 现读，没有第二份状态。

骨架不变量：仍是 **4 块 `.lobby-panel` + 桌面档 3 条 fr 轨道**（`lobby_check.mjs` 全绿，
新工具 `cplus_lobby_check.mjs` 也把这两条钉住了）。

---

### 4.4 结算：宽屏居中主视觉

任务书 §4.1 第 5 条要求「结算采用**居中主视觉**与三组真实数据……窄屏折列」。
原来判定头是一条**横向信息条**：徽记 + 胜负大字贴左、对手/段位/用时被 `margin-left:auto`
顶到最右（`style.css` 的 `.over-head { display:flex; align-items:center }`）。
现在（`arena_screens.css` §18.1，`@media (min-width:861px)`）在桌面档把它立成一列并整体居中：
徽记在上、胜负大字居中、三枚元信息胶囊居中排在下面。
`margin-left:auto` 必须显式清掉，否则胶囊仍会被推到右边。

**只改宽屏**：窄屏本来就是折列的（任务书要的是"窄屏折列"而不是"窄屏也居中"）。
`.over-cols` 那三组数据卡一行不动 —— 它已经是 `auto-fit minmax(230px,1fr)`，
宽屏并排、窄屏自动折列，正是要求的行为。徽记是 `.over-head::before`（不是 `.over-verdict::before`），
立成 column 之后它自然成为"居中的第一行"，原先那条"放 .over-verdict 里会溢出色"的顾虑不存在。

判据是**几何事实**而不是"看着像居中"（宽屏上"看着差不多"能差几十像素）：

```
PASS [1440x900] 结算判定头在宽屏是**竖排**（居中主视觉）        {"dir":"column"}
PASS [1440x900] 胜负大字**水平居中**在判定头中线上（±2px）      {"verdictCx":720,"headCx":720}
PASS [1440x900] 对手/段位/用时三枚胶囊也居中                    {"metaCx":720,"headCx":720}
PASS [1280x720] ……（同上 3 条，中线 640）
```

回归：`cplus_gate_check` 223 PASS / 0 FAIL（result 一屏的"开着/关掉"签名仍然成对成立）、
`cplus_path_check` 真实结算路径全过。截图：`result-centered-1440x900.png`。

**仍未做**：结算屏的**"本局回放"入口**（任务书 §W5 要求先追踪 `_finalize_match` /
持久化 / 正常与重连结束 payload 里有没有权威 match id，缺就追加最小兼容字段，
且**不许**读"历史第一条"猜本局）。见 §7.4 第 5 条。

### 4.5 好友房：两格席位 + 规则摘要

任务书 §W3 的好友房条目要求「呈现本人席位与空席／已加入者、真实房号、邀请与规则摘要」，
并划了两条边界：**"双方名称和状态只从真实房间数据取；缺字段显示等待，不伪造第二人"**、
**"不新增 ready 协议"**。

实现（`templates/index.html` 的面板内 + `game.js` 的两个渲染函数）：

* `#custom-room-seats`：两格。席位 1 = 自己（`gameState.playerName`），
  席位 2 = 对手（`gameState.opponentName`，由服务端在 `len(room.players) == 2` 时
  逐人 `emit('game_state', … 'opponent_name': …)` 下发）。
  没对手时显示"等待加入…"+"空"标签。
* `#custom-room-rules`：四条规则，每条都能指到实现处 ——
  棋盘 6×6 / 每人 6 格（数值现读 `#total-ships`，**不写死第二份**）/
  自定义房恒为休闲局（`server.py` 的 `create_room` 注释写明 `ranked` 恒假）/
  双方摆好后猜拳定先手（既有流程）。
* 刷新挂在既有链路的收尾位（`game_state` 处理函数里调 `refreshCustomRoomInfo()`），
  **不新开监听**；四个"显示房间信息"的入口都补了渲染调用
  （漏一个就会出现"从这里进房看不到席位"—— 本项目的老病根形状）。

**一个容易漏的边界**：`gameState.opponentName` 的初值是字面量 `'对手'`，
那不是"有一个叫对手的人"。只有它被服务端改写过才算真的有人 ——
工具专门测了这一档（见下）。

新工具 `tools/cplus_room_check.mjs`（2 视口 ×11）：

```
PASS [1440x900] 席位是两格   [{"label":"席位 1","name":"老船长","tag":"房主","on":true},
                              {"label":"席位 2","name":"等待加入…","tag":"空","on":false}]
PASS [1440x900] **没人进来时席位 2 是等待态**（不伪造第二个人）
PASS [1440x900] opponentName 仍是默认值「对手」时按"没人"处理（不把默认值当玩家）
PASS [1440x900] 对手进来后席位 2 显示真实名字且是"已加入"  {"name":"新水手","tag":"已加入"}
PASS [1440x900] 「每人战舰」的 6 来自 #total-ships（同一份数据，不写死第二份）
PASS [1440x900] game_state 到达后刷新（refreshCustomRoomInfo）也会更新席位
PASS [390x844] 好友房（含席位与规则）无横向溢出
```

回归：`room_invite_check` / `friend_invite_battle_check`（51/0）改后重跑都全过。
截图：`room-seats-1440x900.png` / `mobile-room-seats.png`。

### 4.6 观战：公开信息图例

任务书 §W5 要求观战屏「增加公开信息图例和状态摘要」。这里做的是**图例**这一半，
而且过程中发现"照抄原型的三档色块"会做出**一张对不上的图例**：

* 观战棋盘上"击沉"用的就是**命中那个 ✕**（`game.js` 第 5 批的注释写明：
  字形与实战统一成 ✕，避免同一个局面在两种屏上长得不一样；"沉"这层含义交给
  `title` / `aria-label`）。
* 所以图例**只有两档**（命中 ✕ / 落空 ○），第三档会在界面上指向一个不存在的颜色。
  文案里如实说明"击沉的格子也是 ✕，悬停或读屏会说明"。

色块用的是**棋盘同一批令牌**（`--hit-fire` / `--miss-dot`），所以换主题、开高对比时
它跟着变，不会出现"图例说红、棋盘上是别的颜色"。

另一个真实的布局坑：`.spectate-body` 是 `display:flex; flex-wrap:wrap`，
图例是它的第一个子元素 —— 不写 `flex-basis:100%` 它会跟两块棋盘挤同一行，
把棋盘顶下去（工具量的就是"图例宽度 == body 宽度"这一条）。

```
PASS [1440x900] spectate 的公开信息图例横跨整行（不跟棋盘挤同一行）  {"w":1396,"bodyW":1396}
PASS [1440x900] spectate 的图例只有两档（命中/落空，与棋盘实际观感一致）
PASS [1440x900] spectate 的图例命中色就是棋盘命中用的 --hit-fire  {"hitBg":"rgb(194, 42, 62)"}
PASS [1440x900] spectate 的图例落空块画出了 --miss-dot 的点（不是一块空底色）
PASS [1440x900] spectate 的图例写明了"没打过的格子看不出有没有船"
（三视口各 4 条）
```

回归：`spectate_check` 156 PASS / 0 FAIL。
截图：`spectate-legend-1440x900.png` / `mobile-spectate-legend.png`。

**仍未做**：观战的"状态摘要"其余部分（原型那种把战况分区重排的组织方式）。

### 4.7 回放：双盘主区 + 紧邻其下的时间轴 + 右侧事件栏

任务书 §W5 要求「桌面双棋盘在主区，**时间轴与播放控件紧邻其下**，右侧安排事件列表
及可切换的手牌／效果信息；真实数据与 `replayComputeFrame` 保持不变」。

原结构的问题不是"缺 CSS"而是**容器放错了**：`.replay-body` 是 `flex-wrap` 的裸 flex
（两块棋盘各占 `1 1 280px`，右栏跟着挤），而 `.replay-controls`（含 `#replay-track`）
落在 body **外面** ⇒ 时间轴在最底下，跟它控制的棋盘隔了一整栏。

改动（`templates/index.html` + `arena_screens.css` §22.1）：

* `.replay-body` → 两列 grid（主区 `minmax(0,1fr)` / 侧栏 `minmax(240px,320px)`）；
* 新增两个**纯容器** `.replay-main`（纵排）与 `.replay-boards`（两块棋盘并排，
  `auto-fit minmax(260px,1fr)`，窄屏自动折列）；
* `.replay-controls` 整块搬进 `.replay-main`，紧贴棋盘下面；顺序（prev/play/next/track）不变；
* 侧栏限高 `62vh` 并允许自己滚动（对局记录可以很长，不该把整屏撑长）；
* 窄屏折成单列，且**主区仍在前面** —— 手机上先看到棋盘与时间轴，再往下才是手牌/记录。

**一个 id、一个类名都没改**（`#replay-board-1/2`、`#replay-track`、`#replay-prev/play/next`、
`#replay-logs`… 全在原位），只换了父容器。`tools/replay_check.mjs` 与
`dom_replay_frame_check.mjs` 都按 id 取元素（后者用的是 DOM stub），所以重排对它们透明 ——
改完两个都重跑过。

判据是**几何关系**，不是"看着像"：

```
PASS [1440x900] replay 回放主体是两列 grid（主区 + 侧栏）        {"display":"grid"}
PASS [1440x900] replay 两块棋盘**并排**在主区                    {"boardsSideBySide":true}
PASS [1440x900] replay 时间轴/播放控件在棋盘**下方**             {"controlsBelowBoards":true}
PASS [1440x900] replay 控件与棋盘**紧邻**（间距 < 80px）         {"gap":24}
PASS [1440x900] replay 进度条在播放控件那一行里                  {"trackInControls":true}
PASS [1440x900] replay 事件侧栏在主区**右侧**                    {"sideRightOfMain":true,"sideW":320}
PASS [390x844] replay 窄屏下主区（棋盘+控件）排在侧栏前面        {"wide":false,"display":"flex"}
（1280×720 同上 5 条）
```

**顺带修了工具的一句错话**：`replay_check` 在挑不到合适回放时，无论哪种情况都报
"回放里 attack 步为 0" —— 而实测两次失败里根本没有 0 步的候选（是"没有候选"或"步数不够"）。
现在报错文案由**实测形状**生成（列出每份候选的 `steps` / `attack步` / `status`），
不再把人指向错方向。改完连跑 3 次全绿。

截图：`replay-layout-1440x900.png` / `mobile-replay-layout.png`。

### 4.8 结算： 「本局回放」真实入口（含一处静默吞掉的参数）

任务书 §W5 对这条的要求很具体，而且**预先写明了该怎么做**：
「先追踪 `_finalize_match`、持久化和正常／重连结束 payload 的真实 match id。
缺少权威标识时追加最小兼容字段（名称按当前代码定），确认记录已可读取与权限后启用；
**不读取"历史第一条"猜本局**。」

**追踪结果**：`match_id` 由 `db.record_match` 内部生成（`uuid4`），此前**从未离开过那个函数**。
所以按任务书说的加了一个**最小兼容字段**：`record_match(..., out_match_id=<list>)` ——
成功时把本局 id 追加进去。用出参而不是改返回值，是因为"成功返回 `True`"是既有契约
（`tests/test_db_core.py` 有 `is True` 的断言钉着），改它要动一批调用点。

链路：`db.record_match` →（出参）`_finalize_match` 写 `room.match_id` →
6 处 `emit('game_over', …)` 统一改走新的 `_game_over_payload(room, extra)` →
客户端 `rememberGameOverMatchId(data)` → `#over-replay-btn` 显隐 → `openGameOverReplay()`。

**⚠️ 本轮踩到的一个"静默"坑（值得单独记）**：`db.py` 底部有一层
**模块级转发函数** `record_match(...)`，而 `server.py` 是 `import db` 后调**它**的
（不是 `Database.record_match`）。我只给下面那个方法加了参数 ⇒ 调用方拿到
`TypeError: unexpected keyword argument`，而 `_finalize_match` 那段正好被
`except Exception: pass` 包着 ⇒ **异常彻底消失**。
症状是"战绩/回放都不写、`game_over` 载荷里没有 `match_id`"，
排查时看着像业务逻辑没走到（我一开始甚至怀疑是 socket 会话没带登录身份）。
**教训**：给 `db.py` 的方法加参数时，**必须同步加在模块级转发层**。

**"不猜"这条被做成了断言**（`tools/cplus_gameover_replay_check.mjs`，18 项）：

* 负例（不需要对局）：
  `B1` 有 id → 入口出现（证明下一条不是恒真）；
  `B2` 没有 id → 入口隐藏且内部 id 清空；
  `B3` 此时点它**不会**进回放屏（不会拿别的一局来凑）。
* 真链路（两个真客户端打到结算）：
  `A9` 结算屏拿到**本局的** match_id；
  `A10` 入口可见可点；
  `A11` 用这个 id 打 `/api/replay` 得 200 + `success`（**记录可读取 + 权限通过**，
        正是任务书要求"确认…后启用"的那一步）；
  `A12` 这份回放有内容（`steps=4`）；
  `A13/A13b/A14/A15` 点入口进回放屏、数据加载完成、步骤数 > 0、无错误态。

```
PASS A9  结算屏拿到了**本局的**权威 match_id  ->  {"id":"9e76a161-…","hidden":false,"disabled":false}
PASS A11 用这个 id 打 /api/replay 拿到成功响应  ->  {"status":200,"ok":true,"success":true,"steps":4,"you_are":"p1"}
PASS A14 回放屏加载出了**步骤**  ->  {"players":"gorep730969 vs 回放对手","total":"4","status":"回放已加载…"}
PASS B2  没有 match_id 时入口**隐藏**且内部 id 被清空（不猜一局）
```

**一处如实的能力边界**：重连落在**已经结束**的对局上时走的是 `game_state` 的
`game_over` 分支，那条载荷**不带** `match_id`（它是 `game_over` 事件专有的）⇒
那种场景下入口不显示。代码注释里写明了这一点，并说明**刻意不去** fetch 战绩补一个
（那正是任务书禁止的猜法）。要在那条路径上也有入口，得让 `game_state` 的
`game_over` 分支也带上 id —— 那是**另一处**最小兼容字段，本轮没有做。

截图：`gameover-replay-1440x900.png`（真实对局）。

## 5. W6 · 历史红项逐个归因（A09）

任务书 §W6 要求"每项建立 issue 记录：复现步骤、真实根因、产品／工具／环境分类、修复及当前结果"。
本轮的诊断**派了三个只读子代理**并行做，结论如下（每条都给了 `file:line` 级证据）。

### 5.1 观战连锁：146/8 → 156/0 · **1 个真产品缺陷**

| 项 | 内容 |
| --- | --- |
| 复现 | 自己的服务端（隔离库）+ `node tools/spectate_check.mjs --url …`，与旧报告**同样的 8 条**一起红 |
| 真根因 | `static/game.js` 的 `renderSpectateChain` 按 `item.card.name`（对象）读卡名，而净化后的 `chain[].card` 是**卡名字符串**（`spectate.py:503` 的 `'card': card_name`，由 `tests/test_spectate_batch2.py:356` 的 `item['card'] == '卧薪尝胆'` 钉住）⇒ 观众永远看到「（未知卡牌）」 |
| 分类 | **(a) 产品缺陷**（另有一个工具侧同形状读法） |
| 连带 | 另外 7 条是**时序级联**：工具第一条 poll 等一个永远不会出现的文案，烧完 15 秒超时；而连锁响应窗口只有 **10 秒**（`server.py` 的 `CHAIN_RESPONSE_SECONDS`），于是后面读到的都已经是"没有待处理的连锁请求" |
| 修法 | ① `game.js` 的 `cardNameOf(item)` 兼容三种形态（字符串／对象／旧字段名）；② `tools/spectate_check.mjs` 的读取表达式同改 |
| 当前结果 | **156 PASS / 0 FAIL** |
| 澄清 | 旧报告的推断"出牌那一步没有形成连锁窗口"与"观众收到的连锁帧里没有那张牌"**都被证伪**：最小探针显示 `chain_waiting=True, chain_window=p2`，而且帧里带着 `card: "无中生有"` —— 两侧都是**读法**问题 |

### 5.2 壁纸：30/3 → 33/0 · **工具夹具缺陷，不是 BMP 解码问题**

| 项 | 内容 |
| --- | --- |
| 分类 | **(b) 工具缺陷 ×2 + (c) 环境** |
| 真根因 ① | 壁纸区块在**默认隐藏的设置分区**里（`<section class="settings-pane hidden" data-pane="wp">`），隐藏时 `#wp-section` 的 rect 是 0×0、里面的 `<img>` 根本不会被请求。工具只做了 `scrollIntoView`（`static/wallpaper.js` 自己就记着这个坑，要走 `openSettingsModal('wp')`） |
| 真根因 ② | 工具起的夹具服务端**没设 `CORS_ORIGINS`**，而它用的是随机空闲端口 ⇒ 页面的 socket.io 握手一直 400、客户端不停重连（实测 245 次请求 / 137 个 4xx，对照加上后 24 次 / 0 个 4xx）⇒ **浏览器端请求队列被挤住**，`/api/wallpaper/media/…` 发出去永远没有响应（CDP 只有 `requestWillBeSent`、没有 `responseReceived`，Werkzeug 访问日志里也没这条 GET），而 `curl` 打同一个 URL 是 `206`／2~12ms |
| 证伪 | 旧报告把第 2 条读成"无头 Edge 的 BMP 解码问题"。实测：`data:image/bmp;base64` 下 `naturalWidth=96, naturalHeight=60`；夹具 BMP 本身有效（Pillow 可开，96×60 RGB）；**BMP 是文档化的产品要求**（`docs/WALLPAPER_ENGINE.md` 与 `wallpaper.py` 的 `MEDIA_EXT`/`MIME` 都注册了 `.bmp`）⇒ 不需要任何依赖升级或格式替换 |
| 修法 | 工具加 `CORS_ORIGINS`（并在夹具启动注释里写明为什么）；断言前先切到 wp 分区 |
| 当前结果 | **33 PASS / 0 FAIL** |

### 5.3 段位榜：旧报告 26/3 → 本次基线 69/4 → 73/0

| 项 | 内容 |
| --- | --- |
| 澄清 | 旧报告的 **26/3 复现不出来**。同一条命令（工具自 2026-09-18 未改）给出的是 69 通过 / 4 失败，**失败集合也不一样**。26 这个数只能解释为**中途中断**：工具在等「别人名片渲染」时**没有 `.catch()`**，超时直接抛进外层 handler ⇒ `检查中断`，后面约 44 条检查根本没跑 |
| 真缺陷 1 | **(a) 产品缺陷**：`arena_screens.css` 的排行榜统一皮肤 `#ranked-table tbody td { background-image:none; box-shadow:none }`（特异度 (1,2,3)）压掉了 `style.css` 里表达"高段位行更重"的两条（(1,2,1)/(1,2,2)）⇒ B13 实测 `{"top":"none","low":"none"}`，**顶端档和普通行长得一模一样**。`docs/RANKED_2026_09_17.md` 把这条写成产品语义，所以本轮把两档重新声明回来（用 C+ 令牌，令牌区允许裸 rgba） |
| 真缺陷 2（本轮自己引入、本轮发现） | 上面那条修完第一版写成 `box-shadow: inset 4px 0 0 var(--ax-gold-strong), 0 0 12px var(--ax-glow-vio)` —— `--ax-glow-vio` 本身就是一整条 shadow，替换后长度过多 ⇒ **整条声明在计算值阶段非法** ⇒ `box-shadow` 落回 `none`。B14 当场红（`{"top":"none","low":"none"}`），改成一整层即可 |
| 工具缺陷 ×3 | ① `toggle.order.length === 5` 陈旧（加了 `#profile-friend-requests` 后恒假）；② `Object.keys(post).length === 10` 陈旧（多了 `friend_requests_open`）；③ 手机档遮挡采样只数**视口内**的采样点，而段位列在 844 折叠线以下（`rect.y=1276`）⇒ `samples` 恒 0、`samples>=3` 永远不成立（**假的遮挡失败**，`occluded` 一直是 0）。前两条只保留索引/必需字段断言（多一个字段不是缺陷，少一个才是），第三条先 `scrollIntoView` 再量 |
| 工具缺陷 4（顺带发现） | `OCCLUSION_PROBE` 把 `opacity:0` 的元素也算作遮挡物。实测遮挡物是行内的 `<span class="ax-open" aria-hidden="true">档案 ↗</span>`，平时 `opacity:0` 根本看不见；现在只把"看得见"的元素算作遮挡物（并把实测到的 `opacity` 记进证据） |
| 顺带的真问题 | 同一元素在 390×844 下被挤成 **10px 宽 × 42px 高**的竖条，而且**溢出了自己的单元格**落在段位列上（键盘 focus 时才显形）⇒ 窄屏直接不显示它（纯装饰，行本身已是带 `title` 的按钮） |
| 当前结果 | **73 PASS / 0 FAIL** |

### 5.4 好友邀战：49/2 → 51/0（连跑三次）· **1 个真产品缺陷**

| 项 | 内容 |
| --- | --- |
| 复现 | 自己的服务端 + `node tools/friend_invite_battle_check.mjs --url …`，同一命令 **49/2 与 51/0 各出现一次** ⇒ 竞态 |
| 真根因 | ① `server.py` 的 `game_canceled` 广播**载荷里没有 `room_id`**；② `game.js` 的处理器无条件认下：`clearActiveGame()` + 1.5 秒后 `resetGame()`（= 整页跳回 `/`）。于是**上一个已解散房间**的取消广播会把已经进了新房间的玩家踢回首页。实测：`对局取消` 后 1.5s NAV 到 `/`，而那条取消属于上一局；服务端日志同一时刻打了"删除房间 …（对手掉线/未开局，取消对局）" |
| 分类 | **(a) 产品缺陷** |
| 修法 | 服务端在这条载荷里补 `room_id`；客户端在**两边都有 room_id 且不相等**时忽略（只有一边有就照旧认下，不改旧服务端行为） |
| 另一个真实缺陷（顺带发现，已修） | **无暇圣心**的终局分支只 `room.state='game_over'` + 广播，**从不调 `_finalize_match`** ⇒ 真打完的一局在战绩里查不到、回放也没有。紧邻的极限增援那条早已改成统一收口 `_finish_game_win(...)` 并留了同样的注释，这一条被漏掉了。最小探针：直接驱动该分支，`_finalize_match` 调用数为 **0**；同批账号在库里只有败场没有对应胜场。现在走同一个收口（`_finish_game_win` 自带幂等，两次广播不会重复计战绩） |
| 修这个缺陷时踩的坑 | 第一版复用了上面极限增援分支里的 `player1_id`/`player2_id`，而那两个名字**只在那条分支里绑定** ⇒ `UnboundLocalError`，`tests/test_headless_game.py` 两条当场红。改成从 `room.players` 里取"不是赢家的那个" |
| 工具卫生 | 浏览器 profile 跨运行复用，客户端 `connect` 时会把 `localStorage['battleship_active_game']` 里的房间拿去 `rejoin_room`（自动重连是设计如此）⇒ 上一次运行留下的尾巴让这一次**开局就不干净**（实测基线 `roomId:"21ff16"` + `rps-screen`）。工具现在在导航**之前**用 CDP `Storage.clearDataForOrigin` 清一次。⚠️ 用 CDP 而不是"多导航两次"：多出来的导航会改变时序，把 4c 那条**本来只是偶发**的探针断言打得更不稳（第一版就是那样，三次连跑两次 4c 红） |
| 当前结果 | **51 PASS / 0 FAIL × 3 次**（脚本 9i–9t 全过，含"解散后再邀战"） |

### 5.5 回放：猜拳随机性 + 魔数步数

| 项 | 内容 |
| --- | --- |
| 分类 | **(b) 测试/工具缺陷**（产品侧的"AI 随机出拳 + 先手优势"是设计，不是缺陷） |
| 机制（精确） | 工具每次尝试都出 `rock`、AI 是独立随机（`server.py` 的 `random.choice(['rock','paper','scissors'])`），所以"我方先手"每次是 **1/2**；拿不到先手就放弃这一局重开。**平局处理是对的**，能打断它的是**输的那一手**，不是平局 |
| 旧说法的错误 | 旧报告写"AI 拿到先手概率 2/3 ⇒ 连输 5 次 ≈ 13%" 与现码不符（现码三个手势轮着出）。真实是 2⁻⁵ ≈ **3.1%**，而工具自己的报错写"应属极小概率" |
| 本轮改动 | ① 尝试上限 5 → 8，并把概率**写对**（2⁻⁸ ≈ 0.4%），报错里明确说明"这是随机性，不是产品缺陷"；② `SHOTS_NEEDED = 6` 这个**魔数**去掉，改成从**实际拿到的那份回放**上量：`≥1` 个 attack 步（0 步意味着这局是被某张卡直接结束的）+ `≥7` 总步（下面要连点 6 次「下一步」并断言 `k=6`，步数不足时 `k` 会在末尾封顶）。实测 14 次连跑里有 **4 次（≈29%）**是"5 炮收工"导致的**假红**，报的还是"回放里 attack 步为 0"这种误导性理由 |
| 现状说明（**残余**） | 这一步把"假红"消掉了，但没有让**夹具获取**变成确定性的：拿不到先手仍然会红（0.4%）。真正的确定性做法需要服务端支持可注入的 AI 出拳，不在本轮范围。**这一条不写成"已解决"，写成本轮残余项**（§7.5） |
| 澄清 | `tests/test_replay_*.py`（180 passed）**没有**猜拳随机性 —— 它们传的是显式选择（如 `'rock'/'scissors'`），所以 pytest 侧的"回放受猜拳影响"是不成立的 |

---

## 6. 逐屏差异表（任务书要求）

图例：**✅ 已落地并有证据** ／ **◐ 部分** ／ **✗ 未做（见 §7.4）**
"证据"列为可直接复跑的检查项或截图文件（截图都在 `docs/cplus_shots/`）。

| 屏 | C+ 视觉 | 本轮新增/修正 | 证据 | 差距 |
| --- | --- | --- | --- | --- |
| 大厅 | ✅ | 搜索（房名/房主/房号，两块列表统一）、状态筛选三档、满员房禁用+说明、两级空态、卡片行 | `cplus_lobby_check`（3 视口 ×17）、`lobby_check`、`lobby-filter-1440x900.png` | ◐ 原型那种"中央房间卡片网格"的大排布**未做**（骨架是冻结的 3 轨道 + 4 面板） |
| 好友房 | ✅ | **两格席位**（自己/对手，缺对手就显示等待）+ **规则摘要四条**；流程侧修了 `game_canceled` 载荷缺 `room_id` | `cplus_room_check`（2 视口 ×11）、`friend_invite_battle_check` 51/0 ×3、`room_invite_check`、`room-seats-1440x900.png` | — |
| 布船 | ◐ | 六槽、清空、坐标、常驻确认+禁用原因、提交状态机、重连还原 | `cplus_deploy_check`（2 视口 ×33）、`cplus_path_check`、`realpath-05-placement.png` | ◐ "六槽"目前是坐标格；原型的**舰位预览图**未做 |
| 图鉴 | ✅ | 统计四态 + 重试 + 并发共享 + 详情刷新 + 焦点恢复；窄屏详情页的焦点进入/返回原卡/Escape；清掉玩家界的工程用语 | `cplus_state_check --cases a06`（11 项）、`cplus_screens_check` 的 390×844 段（12 项）、`collection.png` / `mobile-collection-detail.png` | ◐ 筛选栏空间与桌面详情在低高度下的滚动未专门收口 |
| 排行 | ✅ | 领奖台身份两道门；**修回**高段位两档的行重（渐变 + 左侧条/发光） | `cplus_state_check --cases a03`（16 项）、`ranked_check` 73/0、`leaderboard.png` | ✗ 未新增排序指标（任务书明确禁止为演示控件新增全服排序协议） |
| 档案 | ✅ | 查看面补齐 24px 标题（原来挂在错 id 上）；**宽屏两栏结构已落地**（名片在左、数据／徽章／历史在右，窄屏回单栏） | `cplus_profile_check`（3 视口 ×8）、`profile_card_check`、`profile_leaderboard_check`、`profile-two-col-1440x900.png` | — |
| 结算 | ✅ | 结束原因按 reason × 视角生成唯一准确解释；**宽屏居中主视觉**（判定头竖排、胜负大字与元信息胶囊对齐中线 ±2px）；**「本局回放」真实入口**（本局权威 match id，没有 id 就隐藏、绝不猜一局） | `cplus_state_check --cases a05`（18 项）、`cplus_screens_check` 宽屏段（6 项）、`cplus_gameover_replay_check`（真链路 15 项 + 负例 3 项）、`realpath-07-result.png` / `gameover-replay-1440x900.png` | — |
| 观战 | ✅ | **修好观众永远看不到卡名**（1 个真产品缺陷）；**公开信息图例**（两档颜色 + "没打过的格子看不出有没有船"） | `spectate_check` 156/0、`cplus_screens_check` 图例段（3 视口 ×4）、`spectate-legend-1440x900.png` | ◐ C+ 战况组织的其余部分未做 |
| 回放 | ✅ | 加载身份（generation + 活动屏）修好；**双盘在主区、时间轴/播放控件紧邻其下、事件侧栏在右** | `cplus_state_check --cases a07`、`cplus_screens_check` 布局段（3 视口 ×5–6）、`replay_check` 连跑 3 次、`dom_replay_frame_check` 108 项、`replay-layout-1440x900.png` | ◐ 手机“单盘切换”方案未做（现在是**纵向折列**，手牌与错误提示都在） |
| 设置 | ✅ | 退回合同管住了 `#settings-preview`（关掉时不再留空块） | `cplus_gate_check`（settings 屏逐屏签名 + 容器残留）、`settings.png` | ◐ 预览里的"令牌"等技术用语未清理 |

---

## 7. 已知问题与环境限制

### 7.1 本轮的验证环境（可复现）

* 独立测试实例：端口 **5097**，库 `.tmp/cplus-agent/e2e.db`，
  `CORS_ORIGINS=http://127.0.0.1:5097`、`ENABLE_TEST_EVENTS=1`、`TURN_TIMEOUT_SECONDS=0`，
  `host=127.0.0.1`（**不是** `0.0.0.0`）。
  启动脚本：`.tmp/cplus-agent/start.sh`（另有 `start-rank.sh` 5093 / `start-invite.sh` 5094）。
* 用户既有的 5000 / 5057 **全程未动**；5060 / 5061 未使用。
* 浏览器：`C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`（无头）。
* 工具 profile 一律落在 `.tmp` 下（`--profile` 可覆盖）。

### 7.1b ⚠️ 本轮的一次操作失误：误停了用户的 5000 开发实例（已恢复，需确认）

**发生了什么**：会话开始时 `netstat` 显示 `:5000`（pid 40916）与 `:5057`（pid 40808）两个实例在跑。
本轮中途为了重启自己的 5097 测试实例，执行了

```bash
pkill -f "port=5097"; pkill -f "server.socketio.run"
```

**第二条是一个过宽的模式**：它匹配任何命令行里含 `server.socketio.run` 的进程，
而任务书 §7 推荐的启动方式正是 `python -c "import server; … server.socketio.run(…)"`。
`:5057` 的 pid 从头到尾没变（说明它是用别的命令起的，没被匹配到），
但 `:5000` 在之后就不再监听了 —— **极可能是被这条 pkill 一起杀掉的**（我没有直接证据证明是这个原因，
但也没有别的解释，且这正是任务书 §7 "不要擅自停止或重配" 明令禁止的动作）。

**处置**：已用项目的默认启动方式恢复：`python server.py`
（默认 `data/battleship.db`、`host=0.0.0.0`、`port=5000`，`server.py` 的 `__main__` 就是这么起的），
恢复后 `curl http://127.0.0.1:5000/` 返回 200。
**我无法知道用户当时是否带了自定义环境变量**（`PORT` / `BATTLESHIP_DB_PATH` / `ENABLE_TEST_EVENTS` /
`FLASK_DEBUG` …）—— 如果有，现在的实例用的是默认值，请按原样重配。
重启后该实例提供的是**当前工作区**的代码（模板与静态件在启动时读盘），这一点与之前不同。

**教训（写给下一个 Agent）**：清理自己起的进程时**按 pid 精确杀**，
绝不要用 `pkill -f <库/函数名>` 这类会匹配到别人命令行里的模式。

### 7.2 一处**外部环境**限制（不是本项目的问题）

`pytest --basetemp=.tmp/<新目录>/x` 在这个环境会失败：pytest 9.1.1 的 `TempPathFactory`
建 basetemp 时 `mkdir(mode=0o700)` **没有 `parents=True`**，父目录不存在就 `FileNotFoundError`
（表现为 43 个 setup error）。**先 `mkdir -p` 父目录**即可。这不是本项目代码的问题，别去改它。

### 7.3 旧的"已知红"清单已作废（本轮逐条给了当前结果）

* `.workbuddy` 全仓扫描 → 已修扫描边界（§1.5）。
* 观战连锁 → 156/0（§5.1）。壁纸 BMP → 33/0（§5.2）。段位榜 → 73/0（§5.3）。
  好友邀战 → 51/0 ×3（§5.4）。
* **别的工具/测试是否还红：本轮只重跑了上面这些 + `lobby_check` / `cplus_path_check` /
  `pytest` 全量。**`room_invite_check` / `friends_check` / `ui_layout_check` 等**没有**在本轮重跑，
  不能按"上游都绿"来假设（`ui_layout_check` 按既有记录会随对局状态漂移，
  判回归要在合并前的树上跑同样次数对照）。

### 7.4 未完成项（逐屏差异表里 ✗ / ◐ 的具体含义）

按任务书 §4.1「必须补」逐条对：

1. 大厅卡片／筛选 —— **筛选与卡片行已做**；原型那种整页房间卡片网格**未做**。
2. 房间席位／规则 —— **已做**（见 §4.5）。
3. 部署清空与六槽／提交反馈 —— **已做**；舰位预览未做。
4. 档案宽屏左右结构 —— **已做**（见 §4.2）。
5. 结算居中主视觉／正确原因／「本局回放」入口 —— **三条都已做**（原因见 §3.3、居中主视觉见 §4.4、回放入口见 §4.8）。
   入口需要先追踪 `_finalize_match` / 持久化 / 正常与重连结束 payload 里有没有权威 match id
   （任务书 §W5 明确要求"缺少权威标识时追加最小兼容字段"，且**不许**读"历史第一条"猜本局）。
6. 回放双盘下方时间轴与事件栏 —— **已做**（见 §4.7）。
7. 观战公开信息图例 —— **已做**（见 §4.6）；"状态分区"的其余部分**未做**。

W4/W5 的其余视觉收口（图鉴筛选栏空间、排行前三名/本人行、设置主次按钮统一、
结算窄屏折列、回放手机**单盘切换**方案）**未做**。

**剩余工作量的性质**：这些几乎全是"布局与信息架构"的改动，按任务书 §4.3 应当
"先改 `arena_screens.css`、目标屏容器、`game.js` 对应渲染函数"，并且**必须**配真实截图与可操作性证据
（§9 明确写"不要只完成 CSS 就宣布整屏完成"）。本轮没有在缺证据的情况下把它们标成完成。

### 7.5 本轮引入或留下的残余问题

1. **回放夹具的 0.4% 随机红**（§5.5）：要靠服务端可注入的 AI 出拳才能真确定性。
2. **`arena_screens.css` 里 11 个 `ax-*` 类是死代码**：`ax-bar` / `ax-cols` / `ax-kicker` /
   `ax-num` / `ax-panel` / `ax-panel-title` / `ax-row` / `ax-row-main` / `ax-row-sub` / `ax-seg` / `ax-side`。
   它们是一套"共享词汇"，但正式实现最后都走了逐屏选择器，产品里**一次都没用到**（实测：
   CSS 里定义 52 个 `ax-*` 类，产品代码用到 41 个）。本轮**没有删**：W3–W5 的剩余布局工作会用上
   其中一部分（本轮的 `.lobby-seg` 就是新写的同类）。**这是"注释过度承诺"的一种**，
   已在此如实记录，别再声称它们都在用。
3. `deployResyncTimer` 有两条路径（`room_sync` 到达 / 8 秒兜底），
   但**没有覆盖"`rejoin_room` 的 ack 成功、而房间已不存在"**这一种（服务端会回 `status:'error'`，
   已处理；若它既不 error 也不发 `room_sync`，会走 8 秒兜底，用户最多多等 8 秒）。
4. `game_canceled` 的客户端守卫是"两边都有 `room_id` 且不相等才忽略"。
   旧服务端（不带 `room_id`）的行为**没有变**，这是刻意的兼容选择。

---

## 8. 工作区与回退

### 8.1 工作区状态（开工时就有用户既存改动，**未 reset、未覆盖**）

```
 M CLAUDE.md              M api.py                M server.py
 M static/arena_screens.css                       M static/game.js
 M templates/index.html
 M tests/test_pingdeng_tiaoyue_chain.py
 M tools/cplus_path_check.mjs   M tools/cplus_screens_check.mjs
 M tools/fluent_css_lint.py     M tools/fluent_css_metrics.mjs
 M tools/friend_invite_battle_check.mjs           M tools/ranked_check.mjs
 M tools/recent_opponent_check.mjs                M tools/replay_check.mjs
 M tools/spectate_check.mjs     M tools/wallpaper_check.mjs
?? tools/cplus_gate_check.mjs  ?? tools/cplus_state_check.mjs
?? tools/cplus_deploy_check.mjs ?? tools/cplus_lobby_check.mjs
?? docs/cplus_shots/           ?? docs/C_PLUS_AGENT_DELIVERY_2026_09_29.md
（另有开工前就存在的 staged/untracked 改动与 Demo，见 `git status --short`：CLAUDE.md 的既存改动、
  docs/C_ARENA_*、static/card_art_map.js、tools/chain_stack_check.mjs 等**都不是本轮改的**）
```

**没有提交、没有推送。** 任务书 §9 要求"用户未要求提交则交付清晰文件列表与差异"。

### 8.2 配置退回（可选，不改代码）

两个开关就是 `api.py` 顶部的两个常量（现在也可用同名环境变量覆盖，**默认值与原来完全相同**）：

```bash
# 整批退回（十屏一起回旧样式）
ARENA_SCREENS_MODE=off python server.py
# 单屏退回（例：只退 replay）
ARENA_SCREEN_LIST="lobby room placement collection leaderboard profile result spectate settings" python server.py
```

**退回后的实测证据**（`node tools/cplus_gate_check.mjs`，8 个用例 + 主题轴矩阵）：

* `off` / `empty`：十屏签名全部等于"关掉的样子"，且 `#codex-detail` / `#settings-preview` /
  `#leaderboard-podium` 都不可见（§0.1 的退回合同）；
* `no-replay` / `no-room`：**只有**被删 token 的那一屏退，其余九屏与前缀基线**逐字节相同**；
* `only-lobby`：只有 lobby 开着；
* `unknown` / `odd-list`：与全开基线完全一致（未知 token 无效、多余空白不切断 token）；
* **每一种配置下十屏的可用性锚点（关键控件）都在位且可见** —— "退回 = 可用的旧体验"，
  不是"把操作也一起弄没了"。

⚠️ 任务书 §W1 第 6 条：**不要宣称"删掉 `<link>` 就等于全部功能回退"** ——
`isArenaScreenEnabled()` 判的就是 `<html>` 上那两个属性，删 link 只退外观、不退 JS 能力。
真正的"完整源代码回退"要走 §8.3。

### 8.3 源码回退（按改动分组）

| 想退掉 | 要回退的文件 |
| --- | --- |
| 门控与验收工具（W0/W1） | `tools/cplus_screens_check.mjs`、`tools/cplus_gate_check.mjs`、`tools/fluent_css_lint.py`、`tools/fluent_css_metrics.mjs`、`tests/test_pingdeng_tiaoyue_chain.py`、`api.py` 的两个常量 |
| 逐屏门控（W1） | `static/arena_screens.css`（§0.1 退回合同 + 屏头三组规则的 token + `--ax-eyebrow`）、`static/game.js` 的 `isArenaScreenEnabled` 及其三处调用 |
| 状态一致性（W2） | `static/game.js` 的 `loadCardUsage`/`cardUsageState`、`publishLeaderboardPodium`、`confirmShipPlacement` 一族、`replayState.loadToken`、`gameOverReasonText` |
| 布船/大厅/档案/结算/好友房/观战（W3–W5） | `templates/index.html` 的 `.ax-deploy-side` / `.lobby-filterbar` / `#custom-room-seats` / `#custom-room-rules` / `#spectate-legend`、`static/game.js` 的 deploy 状态机、大厅筛选、`renderCustomRoomSeats`/`renderCustomRoomRules`、`static/arena_screens.css` §4.1a / §13.2 / §17.1 / §18.1 / §12.1 / §20.1 |
| 历史红项（W6） | `server.py`（`game_canceled` 加 `room_id`、无暇圣心走 `_finish_game_win`、`_game_over_payload`）、`db.py`（`out_match_id` 出参，**模块级转发层也要同步**）、`static/game.js`（`cardNameOf`、`game_canceled` 守卫）、`static/arena_screens.css`（段位两档） |
| 本轮新增的工具与截图 | 直接删 `tools/cplus_*.mjs`、`docs/cplus_shots/` |

依赖关系：**`api.py` 的门控常量 + 模板属性 + 样式加载是一组**，必须一起退
（任务书 §9 点名过这一点）。

---

## 9. 复跑手册（本轮实际用过的命令与结果）

```bash
# 静态契约
node tools/dom_contract_check.mjs          # ✓ 442 个 id / 400 个静态引用 / 3 个已核实无害警告
python tools/fluent_css_lint.py            # ✓ style.css + arena_screens.css 块结构都 OK
node tools/fluent_css_metrics.mjs          # ✓ style.css PASS（阈值未动）
node tools/fluent_css_metrics.mjs --file static/arena_screens.css   # ✓ PASS（hex/rgba/!imp 全 0）
node tools/fluent_css_metrics.mjs --summary                          # ✓ PASS（跨文件同名选择器 0）

# 自校准（不起浏览器、不连服务器）
node tools/cplus_screens_check.mjs --self-test     # ✓ 5 组自校准
node tools/cplus_screens_check.mjs --browser /nonexistent/x.exe     # SKIP + 退出码 2

# 起独立实例（5097）
bash .tmp/cplus-agent/start.sh

# 十屏外壳 / 门控 / 状态 / 布船 / 大厅
node tools/cplus_screens_check.mjs --url http://127.0.0.1:5097/ --shots .tmp/cplus-agent/screens-final  # ✓ 321 PASS
node tools/cplus_gate_check.mjs           # ✓ 223 PASS（8 配置用例 + 主题轴；不需要 --url，自己起服务端）
node tools/cplus_state_check.mjs --url http://127.0.0.1:5097/   # ✓ A03/A05/A06/A07 全过
node tools/cplus_deploy_check.mjs --url http://127.0.0.1:5097/  # ✓ 2 视口 ×33
node tools/cplus_lobby_check.mjs --url http://127.0.0.1:5097/   # ✓ 3 视口 ×17
node tools/cplus_path_check.mjs --url http://127.0.0.1:5097/    # ✓ 22（真实两客户端全链路）

# 既有工具（本轮修过的）
node tools/lobby_check.mjs --url http://127.0.0.1:5097/         # ✓ 全部通过（3 轨道 + 4 面板）
node tools/spectate_check.mjs --url http://127.0.0.1:5097/      # ✓ 156 PASS / 0 FAIL
node tools/wallpaper_check.mjs                                  # ✓ 33 PASS / 0 FAIL（自带夹具）
node tools/ranked_check.mjs --url http://127.0.0.1:5093/ --db <该实例的库>   # ✓ 73/0
node tools/friend_invite_battle_check.mjs --url http://127.0.0.1:5094/       # ✓ 51/0（连跑 3 次）

# 全量
python -m pytest tests/ -q -p no:cacheprovider --basetemp=.tmp/cplus-agent/pytest-final
#   ✓ 2623 passed, 1 warning（基线是 1 failed / 2622 passed）
```

`wallpaper_check` 自带夹具（按任务书 §7 不机械追加 URL）；
`dom_spectate_frame_check` 需要 `DSH_SPEC_PAYLOAD`（由观战 pytest 驱动，裸运行不算验收）——
**本轮没有裸跑它**。

### 9.1 任务书 §6 逐屏验收矩阵：本轮实际跑过的工具与结果

任务书 §7 要求"最终报告列明每个实际命令、环境、pass/fail/skip 数量，不只写'测试通过'"。
下面**每一行都是本轮真跑过的**（环境：独立实例 5097 / CORS 放行 / `ENABLE_TEST_EVENTS=1` /
`TURN_TIMEOUT_SECONDS=0`；无头 Edge；另有两台专用实例 5093 段位、5094 好友）。

| 屏 | 工具 | 结果 |
| --- | --- | --- |
| 大厅 | `lobby_check.mjs --url 5097` | ✓ 全部通过（`{"cols":3,"panels":4,"overflow":0}`） |
| 大厅 | `cplus_lobby_check.mjs --url 5097`（本轮新增） | ✓ 3 视口 ×17 |
| 好友房 | `room_invite_check.mjs --url 5097` | ✓ 全部通过 |
| 好友房 | `cplus_room_check.mjs --url 5097`（本轮新增） | ✓ 2 视口 ×11 |
| 好友房 | `friend_invite_battle_check.mjs --url 5094` | ✓ 51 PASS / 0 FAIL（连跑 3 次） |
| 部署 | `cplus_deploy_check.mjs --url 5097`（本轮新增） | ✓ 2 视口 ×33 |
| 部署 | `cplus_path_check.mjs --url 5097` | ✓ 22 PASS（真实两客户端全链路） |
| 图鉴 | `card_compendium_check.mjs --url 5097` | ✓ 全部通过 |
| 图鉴 | `codex_realcard_check.mjs --url 5097` | ✓ 全部通过（48 张卡） |
| 图鉴 | `card_text_fit_check.mjs --url 5097` | ✓ 全部通过（含 320×568 紧凑档） |
| 图鉴 | `cplus_state_check.mjs --cases a06` | ✓ 11 项 |
| 排行 | `ranked_check.mjs --url 5093 --db <该实例的库>` | ✓ 73 PASS / 0 FAIL |
| 排行 | `profile_leaderboard_check.mjs --url 5097` | ✓ 全部通过 |
| 排行 | `cplus_state_check.mjs --cases a03` | ✓ 16 项（含响应反序） |
| 档案 | `profile_card_check.mjs --url 5097` | ✓ 全部通过 |
| 结算 | `cplus_state_check.mjs --cases a05` | ✓ 18 项（reason × 视角矩阵） |
| 结算 | `cplus_screens_check.mjs` 宽屏段（居中主视觉） | ✓ 6 项（1440/1280 各 3） |
| 结算 | `cplus_gameover_replay_check.mjs --url 5097`（本轮新增） | ✓ 18 项（真链路 + 负例） |
| 结算 | `cplus_path_check.mjs`（真投降 → 真结算） | ✓ |
| 回放 | `replay_check.mjs --url 5097` | ✓ 全部通过（**连跑 3 次**） |
| 回放 | `dom_replay_frame_check.mjs` | ✓ 108 项全绿 |
| 回放 | `pytest tests/test_replay_*.py` | ✓ 180 passed |
| 回放 | `cplus_state_check.mjs --cases a07` | ✓（含 A 慢/B 快、退出后回包） |
| 回放 | `cplus_screens_check.mjs` 布局段 | ✓ 3 视口 ×5–6（双盘并排/控件紧邻/侧栏在右） |
| 观战 | `spectate_check.mjs --url 5097` | ✓ 156 PASS / 0 FAIL |
| 观战 | `cplus_screens_check.mjs` 图例段 | ✓ 3 视口 ×4 |
| 观战 | `pytest tests/test_spectate*.py` | ✓ 167 passed |
| 设置 | `fluent_style_check.mjs --url 5097` | ✓ 全部通过（23.8 秒） |
| 设置 | `sfx_check.mjs --url 5097` | ✓ 全部通过 |
| 设置 | `bgm_check.mjs --url 5097` | ✓ 全部通过 |
| 设置 | `wallpaper_check.mjs`（自带夹具） | ✓ 33 PASS / 0 FAIL |
| — | `dom_contract_check.mjs` | ✓ 442 id / 400 引用 / 3 个已核实无害警告 |
| — | `fluent_css_lint.py` | ✓ style.css + arena_screens.css 都 OK |
| — | `fluent_css_metrics.mjs` / `--file arena` / `--summary` | ✓ PASS / PASS / PASS |
| — | `pytest tests/`（全量） | ✓ 2623 passed, 0 failed |

**本轮没有跑**（因此不能按"上游都绿"假设）：`ui_layout_check.mjs`、
`acceptance_shots.mjs`、`wide_geometry_probe.mjs` 等与本轮改动无直接关系的工具。
`ui_layout_check` 按既有记录会随对局状态漂移，判回归要在合并前的树上跑同样次数对照。

---

## 10. 截图索引（`docs/cplus_shots/`）

| 文件 | 内容 | 状态标注 |
| --- | --- | --- |
| `lobby.png` / `mobile-lobby.png` | 大厅默认态 | **shell**（直接切屏，非真实订阅数据） |
| `lobby-filter-1440x900.png` / `lobby-filter-390x844.png` | 大厅筛选栏（本轮新增功能） | 真实渲染 + 夹具载荷 |
| `room.png` / `mobile-room.png` | 好友房 | shell |
| `room-seats-1440x900.png` / `mobile-room-seats.png` | 好友房**两格席位 + 规则摘要**（本轮新增） | 受控载荷（席位/规则由渲染函数画出，非真实双客户端） |
| `placement.png` / `mobile-placement.png` | 布船（六槽/清空/常驻确认） | **entered**（真实初始化棋盘 + 随机摆放） |
| `deploy-1440x900.png` / `deploy-390x844.png` | 布船提交后的锁定态 | 受控假 socket |
| `collection.png` / `mobile-collection.png` / `mobile-collection-detail.png` | 图鉴列表 / 手机详情页 | **entered**（真实卡表 + 真实卡面） |
| `leaderboard.png` / `mobile-leaderboard.png` | 排行（含高段位行重） | shell（无真实榜单数据） |
| `profile.png` / `mobile-profile.png` | 档案 | **游客态**（未登录 ⇒ 空档案，**不能**当"本人档案"验收） |
| `profile-two-col-1440x900.png` / `mobile-profile-two-col.png` | 档案查看面**宽屏两栏 / 手机单栏**（本轮新增结构） | **真实登录账号**（`cplus_profile_check` 自己注册） |
| `result.png` / `mobile-result.png` | 结算 | shell |
| `result-centered-1440x900.png` / `mobile-result-centered.png` | 结算**居中主视觉**（本轮新增结构） | shell（判定头文案由测试置入，未走真实结算） |
| `gameover-replay-1440x900.png` | 结算「本局回放」入口 + 点开后的回放屏 | **真实对局**（两客户端真打到结算） |
| `spectate.png` / `mobile-spectate.png` | 观战 | shell |
| `spectate-legend-1440x900.png` / `mobile-spectate-legend.png` | 观战**公开信息图例**（本轮新增） | shell |
| `replay.png` / `mobile-replay.png` | 回放 | shell |
| `replay-layout-1440x900.png` / `mobile-replay-layout.png` | 回放**新布局**（双盘主区 + 紧邻其下的时间轴 + 右侧事件栏）（本轮新增） | shell |
| `settings.png` / `mobile-settings.png` | 设置 | **entered** |
| `realpath-01-home.png` … `realpath-08-replay.png` | **真实两客户端全链路**（首页→大厅→建房/加入→部署→猜局→对局→结算→回放） | **真实数据**（`cplus_path_check`） |

⚠️ `cplus_screens_check` 会在截图目录写一份 `MANIFEST.json`，逐张标注
`shell` / `entered` 与门控值；**"直接切屏的空壳"不能当作"这一屏有数据时的样子"的验收**。
有数据态由 `cplus_path_check` / `spectate_check` / `replay_check` / `ranked_check` 各自覆盖。

---

## 11. 文档索引

* 任务书（本轮执行对象）：[`docs/C_PLUS_AGENT_HANDOFF_2026_09_29.md`](C_PLUS_AGENT_HANDOFF_2026_09_29.md)
* 本报告：[`docs/C_PLUS_AGENT_DELIVERY_2026_09_29.md`](C_PLUS_AGENT_DELIVERY_2026_09_29.md)
* 历史（保留，但当前状态以本报告为准）：
  [`C_PLUS_SCREENS_REPORT_2026_09_29.md`](C_PLUS_SCREENS_REPORT_2026_09_29.md)、
  [`C_PLUS_SCREENS_IMPLEMENTATION_2026_09_29.md`](C_PLUS_SCREENS_IMPLEMENTATION_2026_09_29.md)、
  [`C_PLUS_BASELINE_2026_09_29.md`](C_PLUS_BASELINE_2026_09_29.md)
* 设计参考：`docs/ui_demos/arena-suite.html` / `.css` / `.js`
* 相关既有文档：`RANKED_2026_09_17.md`（高阶行的视觉加权是产品语义）、
  `WALLPAPER_ENGINE.md`（`.bmp` 是登记过的格式）、`LOBBY_2026_09_18.md`（大厅四态契约）、
  `SPECTATE_*.md`（观战净化契约）、`CHAIN_ENGINE_SPEC.md`
* `CLAUDE.md` 的深度文档索引及 C+ 说明：前一阶段保留了既存改动；
  本次只校正调试事件数量、度量范围和源码回退描述，见 §12。

---

## 12. 2026-09-29 增量收口与复验（当前结论）

本节接续前一阶段的 W0–W6 实现。复验基于同一 HEAD 的工作区，
独立服务端为 `127.0.0.1:5098`，数据库为 `.tmp/cplus-agent/e2e-current.db`，
`ENABLE_TEST_EVENTS=1` 仅用于本地回放夹具。5097 端口已被占用，因此未干扰该实例；
本节没有提交、推送或部署，既有 staged／unstaged／untracked 改动均保留。

### 12.1 本次补齐

| 工作包 | 改变 | 核验边界 |
| --- | --- | --- |
| W3 大厅 | 搜索与状态筛选位于四块真实内容之前；等待房改为响应式卡片，显示真实房号和可加入状态；在线玩家、可观战对局、公屏与创建入口仍在；320px 卡片元数据可换行 | `cplus_lobby_check` 的五视口布局、过滤和局部溢出断言通过；`lobby_check` 的双浏览器真实功能通过。旧“三列 fr”断言改为真实主区／侧栏布局断言，保留业务覆盖 |
| W4 图鉴 | 桌面详情栏限制在可用高度内独立滚动，手机恢复自然高度 | `codex_realcard_check`：48 张正式卡、长列表滚动至最后一张均通过；既有图鉴筛选与详情状态证据见 §9.1 |
| W5 观战 | 桌面战况摘要按五块组织，手机两列；人数与上限作为一组显示；图例随屏级门控关闭 | 真实四客户端 `spectate_check` 通过，截图在下表；净化信息与实时对局隔离仍由原数据路径负责 |
| W6 回放夹具 | 新增受 `ENABLE_TEST_EVENTS`、调试调用者、AI 房及猜拳阶段约束的 `test_set_ai_rps_choice`；AI 出拳只消费一次预置值；`replay_check` 固定合法先手并按结算 payload 的本局 `gameOverMatchId` 验证回放 | 本地真实 AI 对局与回放工具通过；生产环境开关关闭、非法出拳和错误阶段由新 Python 测试覆盖；前一阶段 §5.5／§7.5 的 0.4% 随机夹具红已消除 |
| W0／文档 | `cplus_screens_check` 的大厅标记更新到新的主面板；`CLAUDE.md` 校正调试事件数量、CSS 度量和源码回退说明 | 十屏工具及门控矩阵复跑通过 |

### 12.2 本次实际复跑

| 命令（均在项目根目录） | 结果 |
| --- | --- |
| `python -m pytest tests/ -q -p no:cacheprovider --basetemp=.tmp/cplus-agent/pytest-full-final` | **2625 passed，0 failed，1 warning**；62.46s |
| `node tools/cplus_screens_check.mjs --url http://127.0.0.1:5098/ --port 9469 --profile .tmp/cplus-agent/screens-current-profile-2 --shots .tmp/cplus-agent/screens-current-2` | 全部 PASS；十屏 shell／entered 与几何断言 |
| `node tools/cplus_gate_check.mjs --base-port 9411` | 全部 PASS；八种服务端配置与主题轴 |
| `node tools/cplus_lobby_check.mjs --url http://127.0.0.1:5098/ --port 9473 --profile .tmp/cplus-agent/lobby-escalated-8 --shots docs/cplus_shots` | 全部 PASS；1440×900、1280×720、390×844、320×568、664×336 |
| `node tools/lobby_check.mjs --url http://127.0.0.1:5098/ --shot .tmp/cplus-agent/lobby-real-current.png` | 全部 PASS；双浏览器建房／加入／公屏等 |
| `node tools/cplus_path_check.mjs --url http://127.0.0.1:5098/ --shots .tmp/cplus-agent/path-current` | 22 项通过；真实双客户端首页→大厅→房间→布船→对局→结算→回放 |
| `node tools/spectate_check.mjs --url http://127.0.0.1:5098/ --spectate-shot docs/cplus_shots/spectate-live-2026-09-29.png` | 全部 PASS；真实四客户端观战和隐私断言 |
| `node tools/replay_check.mjs --url http://127.0.0.1:5098/ --shot .tmp/cplus-agent/replay-current.png` | 全部 PASS；固定 AI 先手后的真实本局回放 |
| `node tools/codex_realcard_check.mjs --url http://127.0.0.1:5098/ --shot .tmp/cplus-agent/codex-current.png` | 全部 PASS；48 张卡与长列表滚动 |
| `node tools/fluent_style_check.mjs --url http://127.0.0.1:5098/ --port 9474 --shots .tmp/cplus-agent/fluent-current` | 全部 PASS；预设、明暗和持久化 |
| `node tools/dom_contract_check.mjs`；`python tools/fluent_css_lint.py`；`node tools/fluent_css_metrics.mjs --file static/arena_screens.css`；`node tools/fluent_css_metrics.mjs --summary` | 均 PASS；448 个 id／405 个引用，3 个已知警告；C+ 重复选择器 15／16，合并 46／48 |

### 12.3 可查看的截图与未覆盖范围

| 图片 | 数据性质 |
| --- | --- |
| `docs/cplus_shots/lobby-1440x900.png`、`lobby-390x844.png`、`lobby-320x568.png`、`lobby-664x336.png` | 响应式大厅布局，**受控夹具载荷**，用于卡片与筛选几何检查 |
| `docs/cplus_shots/lobby-live-2026-09-29.png`、`result-live-2026-09-29.png`、`replay-live-2026-09-29.png` | `cplus_path_check` 的**真实双客户端流程** |
| `docs/cplus_shots/spectate-live-2026-09-29.png` | `spectate_check` 的**真实多客户端观战** |

真实双人路径、观战、回放、逐屏门控和五档大厅布局均已复验。§7.4 是前一阶段待办快照，
其中大厅卡片／筛选、图鉴详情滚动、观战战况排版已在本次补齐。其余屏的实现与先前
定向验证见 §4 和 §9.1；本次没有重新逐一手工检查所有「屏幕 × 状态 × 主题」组合，
也没有把 shell 截图当作真实数据验收。手机回放采用纵向可滚动双盘，布船仍以坐标六槽
反馈而非原型舰船剪影呈现。源码回退需按改动分组还原对应补丁；仅去掉 CSS link 不等于完整回退。
