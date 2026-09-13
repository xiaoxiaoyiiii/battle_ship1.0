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
| 前端渲染 | `tools/priority_prompt_check.mjs`（**32 项**，喂真实事件） | 全部通过 |
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
