# 实时观战 · 第 3 批（2026-09-22）

> 批次分工：第 1 批 = 安全地基（事件分类表 + `emit` 第三条腿）；
> 第 2 批 = 服务端观众能力（白名单快照 / 观众进出 / 观战开关）；
> **第 3 批（本文件）= 大厅入口 + 观战屏 + 实时流**，做到"玩家点得进去、看得到、看得到实时变化"。
>
> 产品规则由作者裁定，本文件只记录**为什么这么做**与**实测结论**。
> 契约（`lobby_state.matches` 的字段与可见规则）冻结在 `docs/LOBBY_2026_09_18.md` §1.3 ——
> **没有另立一份契约**，这一批是往那份文件里加一节。

---

## 0. 本批交付

| 面 | 交付物 |
| --- | --- |
| 服务端 | `lobby_state.matches`（进行中的对局，观战入口）+ 批量读设置的缓存 + `tests/test_spectate_batch3.py`（28 条） |
| 前端 | 大厅第三块面板「进行中的对局」+ 独立观战屏 `#spectate-screen` + 实时流 + 设置面的观战开关 |
| 玩家公告 | `changelog.py` 一条（玩家第一次看见这个功能） |
| 工具 | `tools/spectate_check.mjs`（**三浏览器**真 socket E2E，61 项） |
| 文档 | 本文件 + `docs/LOBBY_2026_09_18.md` §1.3 / §6 |

---

## 1. 三条不许破的不变量

1. **观众永远拿不到船位。** 快照与实时流里都只有"**已经轰过的格**"
   （`x/y/hit/ship_sunk`）。前端**不许自己推算"某格有船"** ——
   `renderSpectateBoards` 只读 `board_attacks`，函数体里连 `ships` / `positions` /
   `hits` 这些字样都不出现（源码级守卫：
   `test_board_render_reads_only_bombed_cells`）。
   浏览器侧的守卫是 `tools/spectate_check.mjs` 那条
   「观战屏上『船』格数 = 0，**打完之后仍然是 0**」（还有对照腿：玩家的对局屏上
   对方棋盘确实画好了 36 格，证明这个 0 不是"棋盘压根没画"）。
2. **座位对齐只走 `seat_labels`。** 实时流里的事件带的是**原始座位 key**
   （匹配房里就是 socket sid），前端靠服务端下发的 `seat_labels` 映射成 `p1`/`p2`；
   认不出来一律退化成 `unknown`，**绝不回显原始 key**。
3. **观众与玩家的状态是分开的。** 同一个 socket、同一份 `gameState`，但观战屏
   自己一套渲染、绝不碰对局屏的字段（`playerId` / `ships` / `currentPhase`…）。

---

## 2. 为什么观战屏是**独立一块屏**（上一轮勘察的结论，别再试复用）

`game_state` 的 `attacking` 分支**不设 `playerId`**，而 `updateAttackDisplay`
与破盾标记全靠 `result.attacker === gameState.playerId` 决定把这一炮画在哪块棋盘上。
观众复用对局屏 ⇒ `playerId` 是 `undefined` ⇒ **每一炮都被判成"对方的"、两块棋盘全反**。

所以本批新增 `#spectate-screen`，自带一套渲染（`renderSpectate*`），
一个对局屏的函数都不调。E2E 里有一条断言钉住"两块屏不会同时 active"。

> 另一条同样重要的：**不给 `game_state` 发新 state 值** —— 它的 `default` 分支是
> `console.error('Unknown game state')` + 让玩家"刷新页面"。观战走自己的事件。

---

## 3. 实测踩到的坑（这一批最贵的部分）

### 3.1 ★ 把 Python 的格式化写进了 JS —— **不报错、只是静默退化**

```js
const label = 'p%d' % (index + 1);   // ← 我在两处写成了这样
```

JS 里 `%` 是**取余**，`(index + 1) % undefined` = `NaN`，于是：

* `label` 恒为 `"NaN"` → `data['NaN']` 永远是 `undefined` → **棋盘一格都不画**；
* `sides['NaN']` 同理 → 名字/船数/手牌**全退化成默认值**；
* `node --check` **通过**（语法合法），控制台**干干净净**。

这一条正是 CLAUDE.md 教训 #34 的形状（"兜底 + 零报错一起制造假象"），
而且它同时命中了教训 #21（"未知"退化成默认值）。
**发现方式**：E2E 报"两块棋盘都画满 36 格"但名字是 `玩家`
（默认值），把快照与 DOM 并排打出来才看到 `label` 是 `NaN`。

→ 已加**源码级**守卫：`test_spectate_batch3.py` 里扫 `game.js`
（剔掉注释后）禁用 `% (` 这种 Python 式格式化。

### 3.2 页面里**调不到** game.js 的模块级函数

`ensureSocket` / `switchScreen` / `initGameBoards` / `showSettingsPane`
**都不在 `window` 上**。E2E 工具里直接调它们会 `ReferenceError`，
而报出来的位置是"某行第 N 列"，与根因毫无关系。
→ 工具一律走**真实按钮 / 真实事件**；`gameState` 倒是全局的（`window.gameState`）。

### 3.3 变量遮蔽制造了一个与根因无关的异常

工具里先有 `const atkTab = ...`（攻击方那个页面），后面又写了
`for (const atkTab of [A, B])` —— 攻击方被覆盖成 B，之后所有操作打在没进过房的 B 上，
报出来的是 `TypeError: (intermediate value) is not a function`
（B 的 `gameState.socket` 还是 `null`）。
→ 循环变量一律叫 `br` / `conn`；工具里已加注释。

### 3.4 `Page.reload` / 整页导航期间**不能等 CDP 回执**

导航会换掉文档，那条命令的响应常常永远不回 → `timeout Page.reload`，
而页面其实已经好了。**症状是"只印了一条 PASS 就中断"**（不报哪一步）。
→ 工具里改成 `navigate()`（只管发）+ `awaitReady()`（轮询 readyState 且给短超时）。

### 3.5 一条会**挂死整条求值**的写法

在页面里调 `gameState.socket.off(...)` / `removeListener(...)` 会抛
`TypeError: (intermediate value) is not a function`
（同一个 socket 上 `.emit` / `.on` 都正常），Promise 永远不落地 →
CDP 求值 20 秒后超时 → 工具在"前面全绿"之后突然中断。
→ 改成"只登记一次回调、自己到点 resolve"，根本不解绑。

### 3.6 登录/注册的 302 会把浏览器拖去抓整个首页

E2E 靠 `/register` + `/login` 造三个登录账号，而成功时服务端 302 到首页 ——
**跟着跳**的话浏览器要去抓几十个静态资源，实测偶发地慢到超出任何合理等待，
症状是"注册这一步直接中断"，而**服务端日志里那条注册其实成功了**
（于是下一次运行的所有断言都对不上号）。
→ fetch 加 `redirect: 'manual'` + 显式超时 + 失败重试。

### 3.7 假红比真红更贵：三条自己造出来的假红

| 假红 | 真相 |
| --- | --- |
| 「对局日志已经渲染进观战屏 → 0」 | 布船与猜拳**不写对局日志**（`add_game_log` 的调用点全是动作类），这一刻本来就该是空的 |
| 「保存成功提示 → 不是『已保存』」 | 保存成功后**紧接着**会把提示换成对状态的描述，读到的时刻不同文案就不同 |
| 「再点开关 → `want:false`，服务端还是 false」 | 勾选态是**异步**跟着 POST 走的，"翻转"会翻到同一个值 → 改成"设成指定值 + 轮询等服务端确认" |

### 3.8 第三方注入脚本的报错

本机卡巴斯基往每个页面注入脚本，它自己会打一条
`获取在线人数失败: TypeError: Failed to fetch`。
不滤掉的话"页面零 JS 异常"这一项**永远假红**。

### 3.9 大厅列表与进席判据必须同口径

列表判一次（`_lobby_live_matches`）、进席再判一次（`handle_spectate_join`）——
两处一旦分开，症状就是"列表在骗人"（点进去被拒），而且**不报错**。
→ `test_listing_and_join_agree_on_the_same_room` 用**真 socket** 把两边逐一对上。

---

## 4. 实测结果

| 门 | 命令 | 结果 |
| --- | --- | --- |
| 全量单测 | `python -m pytest tests/ -q` | **2153 passed**（基线 2122，本批 +31） |
| 本批守卫 | `python -m pytest tests/test_spectate_batch3.py -q` | **28 passed** |
| 语法 | `node --check static/game.js` | 通过 |
| DOM 契约 | `node tools/dom_contract_check.mjs` | ✓（新增 id 全部对得上） |
| 布局回归 | `node tools/ui_layout_check.mjs --url http://127.0.0.1:5099/` | 见 §5 |
| **三浏览器 E2E** | `node tools/spectate_check.mjs --url http://127.0.0.1:5099/` | **61 项全部通过** |

E2E 的关键断言（都是真 socket + 真浏览器，全程**不刷新观众页面**）：

* 丙在大厅的「进行中的对局」里看到这一局（双方名字 / 回合 / 观战人数 / 观战按钮）；
* 丙点「观战」→ 进入**独立的**观战屏（不是对局屏，两块屏不共存）；
* ★★ 观战屏上「船」格数 = **0**（打完之后仍然是 0）；
* ★★ 甲打一炮 → 丙那边**实时**多一格，且只落在**挨打那一位**的棋盘上（没画反）；
* 日志同步多一条；
* 甲在**设置面里真的点开关** → 这一局从丙的列表里消失；再打开 → 回来；
* 丙退出 → 人数回到 0、观战屏清空、被送回大厅。

---

## 5. 已知未验证 / 存疑

1. **多观众并发**：E2E 只有 1 个观众。上限 20 与"名单只给观众自己"由
   `tests/test_spectate_batch2.py` 的服务端用例覆盖（真 socket），
   但"20 个人同时看会不会有性能/广播问题"**没有实测**。
2. **实时延迟**：只断言了"最终会到"（15 秒窗口），**没有量延迟数字**。
3. **广域网络**：全部验证都在 127.0.0.1 上；跨网络/弱网的表现未知。
4. **观战屏在窄屏（手机）下的布局**：新样式走的是既有变量、flex 换行，
   但**没有为观战屏单独跑过移动视口断言**（`ui_layout_check` 钉的是对局屏那一屏）。
5. **连锁 / 场地魔法 / 跨回合角标在观战屏上的实时更新**：代码里接了
   `magic_chain_updated` / `chain_resolved` / `field_magic_updated`，
   但 E2E 只覆盖了"开炮"这一条动作流 —— 其余几条是**读代码**得出的，没有实测。
6. 观众**看不到**对方手牌内容、看不到未轰过的船位 —— 这两条由服务端白名单
   （第 1/2 批）保证，本批只是不在前端把它们画出来。
