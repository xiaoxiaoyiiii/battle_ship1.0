# 阶段转换「优先权询问」（方案 D）实施记录

> 日期：2026-09-13 / 14
> 起因：作者实测「速阶3在任何时候都能用，很容易和对方同时使用的其他卡牌抢时点」
> 决策：方案 D —— 保留现有连锁窗口机制，把"对方没速阶3就自动跳过"改成"总是询问"

---

## 1. 问题（作者原话）

> 我现在发现了一个很大的问题，就是因为速阶三在任何时候都可以使用，
> 所以很容易就会和对方同时使用的其他卡牌抢时点了，很容易出 bug。

**实测确认**：P2 在 P1 的准备阶段打出速阶3，P1 随后仍能直接 `enter_battle_phase`，
两张牌的效果落地顺序**没有任何定义**。代码里此前只有「连锁响应窗口」一个仲裁点，
而它有两个缺口：

1. 对方手上没有速阶3时**自动跳过**，玩家失去"我要不要响应"的选择权；
2. 它**不覆盖阶段推进**这类非出牌操作（`enter_battle_phase` / `enter_end_phase`）。

## 2. 方案（作者裁定）

参照游戏王 YGO 的**优先权确认**：

| 决策点 | 结论 |
| --- | --- |
| 何时问 | 只问 **进战斗阶段** / **进结束阶段** |
| 何时不问 | 交回合（本来就被连锁窗口拦着）、攻击（一回合 3~6 次，一局上百次弹窗会毁体验） |
| 对方没速阶3 | **照样问** —— 作者要求"玩家要有选择权，哪怕只有取消按钮" |
| 选项 | 「取消」（= 放弃响应）+ 可点自己的速阶3 |
| 防打扰 | 「拒绝所有阶段转换时点」**开关**（不是一次性按钮，可随时切回） |
| 窗口时长 | 10 秒，与连锁窗口统一（`PRIORITY_SECONDS = CHAIN_RESPONSE_SECONDS`） |
| 无人响应 | 超时视为放弃，**继续原操作**（绝不把对局卡死） |

## 3. 实现位置

### 后端（`server.py`）

| 组件 | 说明 |
| --- | --- |
| `GameRoom.priority_pending` | `{'actor','responder','action','speed3_cards','countdown'}` 或 None |
| `GameRoom.priority_token` | 代际令牌：旧定时器自动作废，防"超时 + 正常响应"双重结算 |
| `GameRoom.priority_continue` | 响应者打了速阶3时，连锁结算完要补做的那次阶段转换 |
| `GameRoom.decline_priority` | `player_id -> bool` 拒绝开关 |
| `_has_request_context()` | 无 socket 上下文（单测直调）时直接放行 |
| `_should_ask_priority()` | 7 条阻断条件，见下 |
| `_ask_priority()` / `_resolve_priority()` / `_priority_continue()` | 询问发起 / 结果处理 / 补做 |
| `_play_speed3_as_priority()` | 窗口内出牌，复用 `handle_use_magic_card` 的全部校验 |
| `@socketio.on('priority_response')` | 客户端回答 |
| `@socketio.on('set_decline_priority')` | 单独切开关 |

`_should_ask_priority` 的阻断条件（都不问，直接放行）：

- 无 socket 请求上下文（单元测试直调 handler）
- 人机房 —— AI 不会主动响应，弹窗只会让人干等
- 对方已掉线（宽限期内）
- 对局已结束（`game_over`）
- 对方已开启「拒绝」开关
- **已有连锁窗口挂起** —— 连锁优先，避免双重弹窗
- 已有未处理的询问 —— 不叠加

### 前端（`static/game.js` + `static/style.css`）

`showPriorityPrompt(data)`：金色「优先权」徽章 + SVG 倒计时圆环 + 速阶3卡列表
+ 拒绝开关 + 取消按钮。没有速阶3时显示「你手上没有速阶3的魔法卡」但**仍然弹窗**。
需要目标的速阶3（轰炸/冻结/探测雷达…）点卡后先走目标选择器，
确认后由 `_dispatchMagicTarget` 回填给 `priority_response`。

---

## 4. 🐛 实施中发现并修掉的真实缺陷（含复现证据）

### 4.1 ★ 续做动作被自己的身份校验拦下 → 点「取消」后回合直接死掉

**现象**：`priority_pending` 被清空、阶段却永远停在 `preparation`；
双方都没有任何提示，整个回合卡死。

**根因**：`_resolve_priority` 是在**响应者**的 socket 请求里执行的，
而 `_priority_continue` 要代**发起者**重放 `enter_battle_phase`。
那个 handler 开头的 `_identity_ok` 会拿 `request.sid`（响应者的连接）
去比对发起者座位的 sid —— 必然不匹配，重放静默返回 `{'status':'error'}`。

**修法**：`_priority_continue` 把重放丢进 `socketio.start_background_task`，
脱离请求上下文后 `_identity_ok` 走"仅成员校验"分支（与单测同一惯例）。

**证据**（真 socket 双客户端，`tools/e2e_priority_prompt.py`）：

```
修复前： cancel -> {'status': 'success'}   AFTER phase: preparation   ← 死局
修复后： cancel -> {'status': 'success'}   AFTER phase: battle        ← 正常
```

**反证**：把 `_priority_continue` 改回同步执行 → e2e 立刻 8 项变红，
失败信息正是 `取消后阶段推进到 battle -> 'preparation'`。

### 4.2 `priority_continue` 未在 `GameRoom.__init__` 初始化

只在 `_resolve_priority` 里现赋。响应者没打出卡时该属性根本不存在，
任何 `getattr`/直读都可能踩 `AttributeError`。已补初始化 + 回归测试。

### 4.3 `priority_continue` 无人消费

响应者在窗口里打了速阶3 → 挂上 `priority_continue` 就再没人管它，
阶段转换永远不会补做。已接到 `resolve_chain` 收尾（先取出再清空，防重入）。

### 4.4 无头检查工具全都在测 Edge 的内置页（17 个工具）

**现象**：`chain_target_check.mjs` 报「无法连接无头浏览器调试端口」，
其余工具却在"通过"。

**根因**：headless Edge 启动时会自带一个 `edge://sync-confirmation-dialog/`
页面，且它在 `/json/list` 里**稳定排在第一位**（本机实测 3/3 次）。
所有工具都写的是 `list.find(t => t.type === 'page')` —— 连上去的是那个内置页。
**症状是"读不到 gameState / 全项假红"，而不是报错，极难排查。**

**修法**：新增共用的 `pickPage(list)`，只认 `https?|file` 开头的页面。

### 4.5 无头 profile 放在 `C:/Windows/Temp` 会因 ACL 损坏起不来 Edge

本机 `C:/Windows/Temp/chain_target_check_profile` 目录 ACL 损坏
（删不掉、Edge 起不来），表现为"调试端口连不上"。
已把 `chain_target_check.mjs` 的 profile 改到项目内 `.tmp/`（并加进 `.gitignore`）。

---

## 5. 回归与验证

| 层次 | 产物 | 结果 |
| --- | --- | --- |
| 单元 | `tests/test_priority_prompt.py`（**29 条**） | 全绿 |
| 全量 | `python -m pytest tests/ -q` | **664 passed** |
| 前端渲染 | `tools/priority_prompt_check.mjs`（**50 项**，喂真实事件） | 全部通过 |
| 真 socket e2e | `tools/e2e_priority_prompt.py`（**30 项**，9 个场景） | 全部通过 |
| 真实浏览器 | `tools/priority_live_check.mjs`（**17 项**，两个真页面 + 真服务端） | 全部通过 |
| 既有无头套件 | ui_layout / card_compendium / card_selection / sfx / bgm / ai_difficulty / room_invite / stats_modal / state_visual / last_stand / yinxue / chain_negation / shenji_redeploy / chain_target | 全部通过 |

真 socket e2e 覆盖的 9 个场景：

1. 对方有速阶3 → 弹询问，且**阶段不推进**（本次修的核心）
2. 点取消 → 阶段真正推进到 `battle`
3. 窗口内打出速阶3 → 卡被消耗、生效，阶段随后推进
4. 对方不响应 → 10 秒倒计时到点自动放行（实测 10.3 秒，不会永久卡死）
5. 「拒绝」开关：勾上不再问、关掉恢复问
6. 手上没有速阶3 也照样问（`speed3_cards: []`）
7. 进结束阶段同样询问（需先耗尽攻击次数）
8. 人机房不询问（AI 自己推进，未被卡住）
9. 反证：连锁窗口挂起时不弹优先权询问（且先断言前置条件真的成立）

真实浏览器 e2e 的实测输出：

```
PASS  ★ 防守方的浏览器真的弹出了优先权面板
      {"title":"对方即将进入战斗阶段","badge":"优先权","countdown":"10",
       "cards":["盗亦有道","绝处逢生","失灵！"],"hasToggle":true,"hasCancel":true}
PASS  倒计时在走  ->  {"cd1":"10","cd2":"9"}
PASS  ★ 询问期间发起者的阶段没被推进（本次修的核心）  ->  "preparation"
PASS  ★ 取消后阶段推进到 battle  ->  "battle"
```

---

## 6. 有意为之 / 已知取舍

- **只在两个入口问**：交回合与攻击不问（作者裁定，理由见 §2）。
- **无 socket 上下文直接放行**：`_has_request_context()` 是给单测留的口子，
  与 `_identity_ok` 的无上下文分支同一惯例。不是漏洞，但要知道它的存在。
- **人机房不问**：AI 不会响应，问了就是让真人干等 10 秒。
- **`test_get_game_state` 补了字段**：为让 e2e 能观测阶段与询问状态，
  该调试事件新增 `current_phase` / `priority_pending` / `decline_priority` /
  `chain` / `chain_window`。它由 `@_test_event` 门禁关闭，默认不可用。
- **`test_clear_all_effects` 补了清手牌**：E2E 需要"手上有什么卡"完全可控。
  不带上它，测试就分不清"我发的那张卡"和开局抽到的卡。

---

## 7. 上线后作者反馈「时点没出现、开关也没出现」

作者反馈：**阶段转换的时点没有出现，而且那个自动取消所有时点的按钮也没有出现。**

按层排查，**每一层都是通的**：

| 层 | 怎么验的 | 结果 |
| --- | --- | --- |
| 生产后端 | `tools/prod_priority_check.py` 打 `http://8.133.180.159:5000`（不走 test 事件，纯真实玩家路径） | A/B 有一方真的收到 `priority_request`，载荷 `{'action':'enter_battle_phase','countdown':10}` |
| 生产前端 | `node tools/priority_prompt_check.mjs --url http://8.133.180.159:5000/` | 全部通过（面板、倒计时、开关都在） |
| 本地真实双浏览器 | `tools/priority_live_check.mjs` | 全部通过（防守方浏览器真的弹出了面板） |

排查过程中确认了两个**确实存在、由本批引入**的问题，都修了：

### 7.1 ★ 静态资源没有版本号 → 没刷新过的页面一直在跑旧 `game.js`

`index.html` 引的是 `static/game.js`，没有任何缓存参数。服务端给的
`Cache-Control: no-cache` + ETag 只保证"重新请求时会拿到新的"，
**但没刷新的页面根本不会重新请求** —— 作者浏览器里跑的就是改动前的 `game.js`，
那个版本里没有优先权弹窗，也没有开关。

修法：`api.py` 加 `asset_v(rel_path)`（返回文件 mtime），`index.html` 里所有本地
静态资源都带上 `?v=`：`game.js?v=1789361892` 这种。改了文件 mtime 就变，
浏览器自然重新拉。

> 通用教训：**这个项目没有构建工具、静态资源不带指纹**。凡是改了
> `game.js` / `style.css` / `magic_cards.js` 这类文件，光部署是不够的，
> 必须让 URL 变化（或用户强刷），否则老页面永远看不见新代码。

### 7.2 ★ 开关只在弹窗里 → 勾上之后自己把自己锁死

「拒绝所有阶段转换时点」这个开关原先**只存在于优先权弹窗内部**。
而它一旦被勾上，服务端就不再发询问 → 弹窗不再出现 →
**玩家永远没有机会把它取消**。作者说的"那个自动取消所有时点的按钮没有出现"，
大概率就是这个：上一局（或上一次误点）勾上之后，弹窗再也不来了，按钮自然也看不见。

中途试过在对局界面放一个常驻按钮，但**撞了两条移动端不变量**
（`ui_layout_check.mjs` 报 `阶段按钮在卡片内水平居中`、
`landscape-664x336 展开面板槽后仍不产生纵向滚动`，外加触控目标 ≥40px 不达标）——
`.game-info` 那块区域塞不下任何控件。

最终做法：放进**设置弹窗**的「对局设置」区，`#decline-priority-setting`。
模态框不受那三条不变量约束，而且"这是个设置"也更符合直觉。
两个入口（弹窗内的 `#decline-priority-toggle` 与设置里的 checkbox）**共用同一份状态**，
`syncDeclinePriorityUI()` 同时同步两处。

顺带补上两条持久化，否则"记住我的选择"这件事只在单个房间内成立：

- **localStorage**（`battleship_decline_priority`）：服务端那份 `decline_priority`
  是**房间级**的（`GameRoom.__init__` 初始化），换房就重置。玩家"不想被问"
  是个跨局意愿，所以本地记住，`bindDeclinePriorityToggle()` 启动时读回。
- **进新房间补推**：`ensureDeclinePrioritySynced()` 挂在 `updatePhaseUI()` 上，
  每个房间推一次（按 `declinePrioritySyncedRoom` 去重，不会刷屏）。

回归：`tools/priority_prompt_check.mjs` 场景 8 已改写为针对设置面板的 checkbox
（全套共 **50 项**，含"不需要任何弹窗就能改回来"这条专门守死结的断言）。
反证：把 `bindDeclinePriorityToggle` 的绑定目标改回已删除的 `#decline-priority-btn`
→ 立刻 5 项红，确认这些断言真的在守这个行为。

---

## 8. 作者二次反馈：「等待时对方不能暂停行动」+「开关要放在局内」

> 阶段转换时点实装还是有点失败了。在等待阶段转换的响应的时候，对方不能暂停行动。
> 询问阶段转换开关效果是在局内开关的，就是做成一个开关放在局内，而不是在设置中。

作者选定：**① 等待期间把发起方冻住；② 开关做成局内常驻，设置面板里那份删掉。**

### 8.1 ★ 等待窗口以前根本没"拦住"任何东西

`_ask_priority` 只做了两件事：把 `priority_pending` 记上、给对方发 `priority_request`。
**发起方那边零提示**，而且他仍然能继续开炮、出牌、交回合 ——
`handle_attack` / `handle_use_magic_card` / `end_turn` 当时都只挡连锁窗口，不看 `priority_pending`。

于是这个窗口的意义被架空了：对方正在决定要不要打速阶3，这边已经把攻击打完了，
窗口结束时 `_priority_continue` 再把阶段转换补上 —— "拦下来问一句"等于没拦。

连带的第二个洞：`_should_ask_priority` 看到已有 `pending` 会返回 False，
于是**双击**「进入战斗阶段」会直接跳过询问、当场推进阶段。

**修法**（`_priority_wait_reason`）：

- 新增冻结判定：`priority_pending['actor'] == player_id` → 返回拒绝文案。
- 挂到 5 个写操作上：`handle_attack` / `handle_use_magic_card` / `end_turn` /
  `enter_battle_phase` / `handle_enter_end_phase`（后两个在 `_priority_confirmed` 时放行，
  那是续做重放路径）。
- 只冻发起方。响应者不受影响 —— 他此刻要做的正是"响应"，走 `priority_response`
  （`test_only_the_actor_is_frozen` 用"拒绝原因是另一条规则"来区分这两者）。
- 新增事件：`priority_waiting`（发给**发起方**，带 `action_text` / `countdown`）、
  `priority_waiting_end`（`_clear_priority` 里发，漏发的话发起方会永远停在"等待中"）。
- `_build_room_sync` 补 `priority_waiting`：重连正好落在窗口里时能恢复冻结状态。

### 8.2 局内开关：绝对定位 + 窄屏改浮标

按作者要求，开关从设置面板搬到**对局信息区（阶段卡片 `#turn-indicator`）右上角**，
设置面板那一整块已删除。

两个布局坑（都是实测量出来的，不是猜的）：

1. **不能和阶段按钮排在同一行**。宽屏有一条不变量「阶段按钮在卡片内水平居中」
   （逐按钮量中心点、容差 3px），多一个 `inline-block` 就会把它们整体挤偏。
   改用 `position: absolute`（`#turn-indicator` 加 `position: relative`）→ 不参与流式布局，
   居中不受影响、卡片高度也不变（横屏 664x336 的"零纵向滚动"余量只有 1px）。
2. **窄屏卡片里根本放不下第二个触控目标**。实测各视口下"阶段按钮右侧剩余空间"：

   | 视口 | 卡片 | 按钮右侧剩余 |
   | --- | --- | --- |
   | 1600×1000 | 900×160 | **383px** |
   | 1000×900 / 430×932 / 390×844 / 320×568 / 768×1024 | 193×42 | **1px** |
   | 664×336（横屏） | 193×38 | **1px** |

   也就是说紧凑/矮屏下硬塞就会压住「进入战斗阶段」——
   第一次实现就是这么翻车的，截图交给视觉桥一看就露了（"询问中 appears overlaid on the blue button"）。
   所以 `body.layout-compact/layout-tight` 下把它改成**屏幕右上角的固定浮标**
   （`position: fixed; top/right: 6px`），那里四周是空的。

顺带给 `ui_layout_check.mjs` 加了一条新不变量：
**「阶段时点」开关不压任何东西**（阶段按钮 / 两个棋盘 / 手牌 / 面板槽 / 两个头像角标 /
回合标题 / 投降按钮），宽屏与 6 个紧凑视口各查一遍。这条才是真正守住"控件不打架"的东西 ——
只验居中是不够的，居中照样能压住按钮。

### 8.3 回归与验证

| 层次 | 产物 | 结果 |
| --- | --- | --- |
| 单元 | `tests/test_priority_prompt.py` 新增 **11 条**（等待提示只发发起方 / 攻击·出牌·交回合·进阶段全被拒 / 双击不能绕过 / 响应者不受影响 / 响应后·超时后解冻 / 无事不误冻） | 全绿 |
| 全量 | `python -m pytest tests/ -q` | **729 passed** |
| 无头前端 | `tools/priority_prompt_check.mjs`（新增场景 8 局内开关 + 场景 9 等待冻结） | 全部通过 |
| 真实双浏览器 | `tools/priority_live_check.mjs`（等待期间横幅/按钮禁用/重复点击被拒/取消后解冻） | 全部通过 |
| 布局不变量 | `ui_layout_check.mjs`（含新加的"开关不压任何东西"，6 视口 + 宽屏） | 全部通过 |
| 既有无头套件 | hand_play / reinforcement_tie / effect_badge / target_selection / papal_discard / chain_target / sfx / bgm / card_compendium / room_invite / stats_modal | 全部通过 |

**反证**：把 `handle_attack` 里的冻结判定改成 `wait = None`
→ `test_actor_cannot_attack_while_waiting` 立刻红，确认断言真的在守这个行为。

### 8.4 顺手修掉的一个测试工具假红

`tools/reinforcement_tie_check.mjs` 偶发红：无头浏览器闪断会让服务端进入 30 秒掉线宽限，
期间所有写操作被冻结 → 连锁结算不了 → 极限增援没生效，看起来像产品 bug。
已加 `waitUnfrozen()`（等两边都不在宽限期）+ 出牌重试，并在输出里打印提示文本，
避免以后把环境抖动误判成回归。

