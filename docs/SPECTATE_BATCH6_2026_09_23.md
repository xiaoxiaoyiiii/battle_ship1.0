# 实时观战 —— 第 6 批：两个"用一个容差/一步收尾盖过去"的死角（2026-09-23）

> 上一批（第 5 批，`d6fb195` / `faa9536`）修了 4 个观战缺陷，但留了**两个没查清的
> 死角**，两个都是"用一个容差 / 一步收尾把问题盖过去"的形状 —— 而**放宽断言让它
> 永远是绿的，等于没有断言**。本批把两个都查清，其中一个确认为**真 bug** 并修掉。

---

## 1. 死角 A：两块棋盘"对调"——**是真 bug**，已修

### 1.1 上一批的记录

`tools/spectate_check.mjs` 里那条断言原本写着：

```js
//   容差取 1 格：把"对调一格"这种已知形态放过去，同时仍然能抓住
//   "重摆后的新位置成片冒出来"（那才是真泄漏）。
const tolerance = 1;
check(boardAfter.b1.marks <= Math.max(wantAfter1, boardBefore.b1.marks) + tolerance
   && boardAfter.b2.marks <= Math.max(wantAfter2, boardBefore.b2.marks) + tolerance, ...)
```

上一批做了 6 轮取证（页面侧 applyLog、服务端发布日志、attacks 写操作时间线、逐次读数
对齐）**没有定位到根因**，于是加了容差。**本批删掉了容差**，改成逐格严格相等。

### 1.2 根因（一行代码的方向）

`server._spectate_board_frame` 把**座位方向**的数据翻成了**棋盘方向**
（第 5 批那句 `side['attacks'] = _spectate_player_cells(other)`），
而前端只有**一处**转置 `spectateRebuildBoardAttacks()`
（`board_attacks[p1] = attacks[p2]`），它把两条路径都当**座位方向**处理：

| 路径 | 服务端发的 | 前端存的 | 再转置一次 | 结果 |
| --- | --- | --- | --- | --- |
| 快照 `spectate_sync` | 座位方向 | `sp.attacks` = 座位方向 | 翻一次 | **对** |
| 帧 `spectate_board` | **棋盘方向** | `sp.attacks` = 棋盘方向 | 翻一次 | **翻两次 ⇒ 两块棋盘对调** |

而且这条错误**会被后续每一炮继承**（`sp.attacks` 被整体覆盖成反的那一份，
之后 `spectateOnAttackResult` 继续在反的基底上加格、继续转置成反的棋盘）。

### 1.3 决定性实验（作者指定的那一个）

造一局**双方打出的格明显不同**的局面：p1 打 `{(0,0),(1,1)}`、p2 打 `{(4,4),(5,5)}`
（两组**无交集**）。工具 `tools/dom_spectate_frame_check.mjs` 把**真的** `static/game.js`
放进 vm（带最小 DOM 桩），真的调 `applySpectateSnapshot` / `applySpectateBoardFrame`，
再读它真的画进 `#spectate-board-1` / `#spectate-board-2` 的格子。

**修之前**（把方向写反的代码跑一遍）：

```
=== 路径 A：进席快照 ===
  DOM 第1块棋盘 = (4,4)中 (5,5)中      ← 与服务端一致（快照路径的转置是对的）
  DOM 第2块棋盘 = (0,0)中 (1,1)中
=== 路径 B：进席快照之后收到一个 spectate_board 帧 ===
  DOM 第1块棋盘 = (0,0)中 (1,1)中      ← ★ 变成了 p1 自己打的格（服务端该画 (4,4)(5,5)）
  DOM 第2块棋盘 = (4,4)中 (5,5)中      ← ★ 两块棋盘整体对调
=== 路径 B2：帧之后玩家再开一炮 ===
  DOM 第1块棋盘 = (0,0)中 (1,1)中 (2,3)中   ← 错了之后继续错
```

**修之后**：两条路径、以及"帧之后再开一炮"，逐格全部一致。

### 1.4 修法（"单一实现"）

* `_spectate_board_frame` **不再翻方向**：直接取 `_spectate_side_payload` 的原始输出，
  与快照 `sides[label].attacks` **逐字段同口径**；
* 前端 `applySpectateSnapshot` 也补上 `spectateRebuildBoardAttacks()` —— 让"棋盘该画什么"
  只剩下**一处**判据来源（`sp.attacks` + 唯一那一次转置），两条入口共用；
* 前端 `applySpectateBoardFrame` 里那句"直接当棋盘用"的注释**改掉了**
  （它正是误导下一个人再翻一次的东西）。

### 1.5 ★ 顺带查出的第二个真缺陷：E2E 那条"服务端真相"探针**从来没读到过东西**

修完方向之后，严格断言仍然红了一次，追下去发现：

```js
// 工具里的探针
out.push({ pid: k, n: ((g.players[k] || {}).attacks || []).length });
```

而 `server.test_get_game_state` **根本没有** `players[].attacks` 这个字段 ⇒
`(… || {}) .attacks || []` **恒为 `[]`** ⇒ "服务端说有 0 格" ⇒
`0 <= Math.max(0, 0) + 1` **永远成立** ⇒ 那条断言（连同它的容差）从加进来那天起
就**没有验过任何东西**。这也是"容差为什么拦不住对调"的第二个原因：
**只数格数的判据对"对调"天生免疫**（对调后两块棋盘格数常常一样）。

修法（三件）：

1. `test_get_game_state` 补上 `players[].attacks`（`{x,y,hit,ship_sunk}` 逐格）；
2. 工具加**探针自检**：`cells` 必须是数组、且此刻至少有一个座位非空 ——
   读错字段会立刻红，而不是静默退化成 0；
3. 对照腿（防守方对局屏）原来拿**攻击方**的格数去比，现在改成比
   **他本人**的 `attacks`，并且**逐格**比（`PLAYER_GLYPH_PROBE` 也加了 `markKeys`）。

### 1.6 第二个收尾缺陷：写着"`emit()` 收尾补一条"，而那句**从来不存在**

`_mark_spectate_board_dirty` 的文档、`GameRoom.__init__` 的注释、
灵气复苏调用点的注释都写着"真正的发送在 `emit()` 收尾" ——
而 `emit()` 里**从来没有任何收口代码**（它只拿得到 `room_id` 字符串，拿不到 room 对象，
写在那里本来就是死代码）。结果：脏标记只被
`_revive_sunken_ships` / `confirm_magic_target` / 败者食尘分支消费过，
其余路径的"收尾帧"一条都发不出去。

本批把收口落到**每个操作自己的末尾**（回光返照分支补上了那一句），
并**把 `resolve_chain` 里那句"假收尾点"删掉**（对已自己收口的卡是空操作，
对没收口的卡又救不了 —— 留着只会让人以为收尾在那儿）。

---

## 2. 死角 B：回光返照之后房间落到 `rock_paper_scissors` —— **既有行为，非本批回归**

### 2.1 复现脚本

`tools/repro_huiguang_room_state.py`（**纯服务端层**，不走前端）：
打一次 `回光返照`，逐帧打印 `state` / `current_phase` / `current_attacker` /
`attacks_remaining` / `ships` 数 / `huiguang_awaiting_placement`，
覆盖"真人施法"与"AI 座位施法"两个场景。

### 2.2 并排输出（当前 `faa9536` vs 第 4 批 `59ae6ab`）

用 `git worktree add .tmp/wt-59ae6ab 59ae6ab` 拉出第 4 批的树，
把**同一个脚本**复制过去跑。**两个场景、逐行相同**：

| 步骤 | `59ae6ab`（第 4 批） | 当前（第 6 批） |
| --- | --- | --- |
| 真人施法 · `apply_magic_effect` 之后 | `state=placing_ships phase=end` | 同左 |
| 真人施法 · `place_ships` 之后 | `state=attacking phase=preparation` | 同左 |
| AI 施法 · `apply_magic_effect` 之后 | `state=attacking`（`_ai_seat_places_board_now` **在第 4 批就已存在**，就地摆完） | 同左 |
| AI 施法 · **脚本再补发一次 `place_ships`** | `state=rock_paper_scissors` | 同左 |

⇒ **不是第 5 批引入的回归**，也不是本批引入的。

### 2.3 真因："房间落到猜拳"是**脚本自己多打的那一次调用**造成的

* 施法者是 AI 时，`apply_magic_effect` 在**同一个栈帧**里就把 AI 的棋盘摆完了
  → 施法者的 `huiguang_awaiting_placement` 被消费掉、`state` 回到 `attacking`（**正确**）；
* **然后 E2E 的"收尾"无条件**又对**已经摆好船**的座位补发了一次 `place_ships`
  → `handle_place_ships` 里两个专用分支都已失效（`huiguang_awaiting_placement` 已 False、
  `lingqi_resurgence_applied` 本来就不是）→ 掉进通用分支 `room.state = 'rock_paper_scissors'`；
* 工具再用 `settleRoomToAttacking` 推回 attacking ⇒ **看起来**像"回光返照的副作用"，
  真因被盖住了。

### 2.4 玩家走得到吗 —— **走不到**

`reset_gameboard` 是 `to=caster.sid` **单发**：

* 施法者是 AI ⇒ 那份事件发给 `'ai-'+room_id`（**没有这条连接**）⇒ 真人**收不到** ⇒
  前端不会把他拽进布船界面 ⇒ 他没有任何入口发出第二次 `place_ships`；
* 真人施法 ⇒ 他那一份收得到，而且**必须真的摆完**才离开布船界面（摆完就是正解）。

服务端**确实没有**"棋盘没在等摆放就拒绝"的闸门（重复调用会被照收）——
本批**没有**去加那道闸门：那会改变既有行为（灵气复苏 / 败者食尘 / 开局布船共用这个入口），
而且**没有任何玩家路径能发出那第二次调用**。按作者要求："需要用户拍板就明确写出来并停下"。

### 2.5 工具侧的处理（不再偷偷推回）

E2E 的收尾改成：**先读服务端状态，只有 `placing_ships` 才补发 `place_ships`**，
并新增两条断言：

* `（收尾）房间**不在** placing_ships ⇒ 不补发 place_ships（真实玩家在没有布船界面时不会发这一条）`
* `★★（收尾）重摆流程走完之后房间**本来就在 attacking** —— 不需要任何工具侧补救`

`settleRoomToAttacking` 保留（万一真落到猜拳时不至于把后面的小节一起染红），
但它的注释已改成"它**不再是某个缺陷的遮羞布**"，且调用点会如实断言"本来就在 attacking"。

---

## 3. 本批交付

| 文件 | 改动 |
| --- | --- |
| `server.py` | `_spectate_board_frame` 方向口径统一（**不再翻**）；`applySpectateSnapshot` 侧补 `spectateRebuildBoardAttacks`；`test_get_game_state` 补 `players[].attacks`；回光返照分支补收口；`resolve_chain` 删掉"假收尾点" |
| `static/game.js` | `applySpectateSnapshot` 补唯一那次转置的调用；`applySpectateBoardFrame` 的方向注释改写（它正是误导来源） |
| `spectate.py` | 无需改动（帧的三级白名单与方向无关） |
| `tests/test_spectate_batch5.py` | 4 条用例的方向断言同步（帧与快照**同向**） |
| `tests/test_spectate_batch6.py` | **新增 13 条**：同向断言 / 真跑 `game.js` 的逐格比对 / 自校准 / 源码级"方向只许一处" / 收尾帧契约 |
| `tests/test_spectate_batch6_huiguang_state.py` | **新增 4 条**：回光返照后的房间状态 + 死角 B 的既有行为钉住 |
| `tools/dom_spectate_frame_check.mjs` | **新增**：不用浏览器、跑真 `game.js` 的逐格方向检查（12 项） |
| `tools/spectate_check.mjs` | 删掉 1 格容差 → 逐格严格相等；加探针自检、读数冻结、自我校准；收尾改成按状态决定；对照腿逐格比 |
| `tools/repro_huiguang_room_state.py` | **新增**：死角 B 的服务端层复现（可跨版本并排跑） |
| `changelog.py` | 加一条玩家公告（棋盘左右颠倒） |

---

## 4. 每条新守卫"怎么证明能红"

| # | 守卫 | 怎么改坏 | 红的样子 |
| --- | --- | --- | --- |
| 1 | `_spectate_board_frame` 方向（红测①） | 把 `frame['sides'][…] = _spectate_side_payload(…)` 改回第 5 批的 `side['attacks'] = _spectate_player_cells(other)` | 工具 4/12 红（第 1 块画成 `(0,0)(1,1)`、该画 `(4,4)(5,5)`）；pytest 3 红；batch5 另有 4 红 |
| 2 | 前端那唯一一处转置（红测②） | `spectateRebuildBoardAttacks` 里 `p1: attacks.p1` / `p2: attacks.p2` | 工具 5/12 红（快照路径反过来、帧之后那条新炮画错板） |
| 3 | `_ai_seat_places_board_now` 那一句（红测③） | 注释掉 `apply_magic_effect` 回光返照分支里的调用 | batch6_huiguang 2 红，报 `AI 座位施法后房间没有回到 attacking（实际 'placing_ships'）` |
| 4 | 收尾帧契约（红测④） | 注释掉回光返照分支末尾的 `_flush_spectate_board_if_dirty(room)` | `帧 = [(0,0,True,False),(1,1,True,False)]` vs `服务端 = […,(3,3,True,False)]` → 红 |
| 5 | 死角 B 的既有行为（红测⑤） | 把 `handle_place_ships` 的 `huiguang_awaiting_placement` 分支删掉 | `test_huiguang_leaves_the_room_in_attacking[False]` 红 |

**★ 本批两次"判据自己骗自己"的现场（都记在代码注释里，防止再踩）**：

1. `test_dom_tool_can_actually_fail` 第一版拿 `_spectate_board_frame` 的输出当"参考帧" ——
   服务端方向被翻反时**两份一起翻反** ⇒ 工具照样全绿 ⇒ 自校准与主用例**同时假绿**。
   改成"两份帧都从快照现场构造"，与服务端实现解耦。
2. 收尾帧契约第一版把"标记之后又改了棋盘"挂在 `_emit_board_attacks` 上 ——
   而它在**标记之前**就跑了 ⇒ 改动被"标记那一刻的帧"顺手带上 ⇒ 最后一条帧照样是真值 ⇒
   **两处收口都注释掉，13 条全绿**。改挂在 `_mark_spectate_board_dirty` **之后**才红。

---

## 5. 实测数字

| 项 | 结果 |
| --- | --- |
| `pytest tests/ -q` | **2232 passed**（上一批基线 2215，+17） |
| `node --check static/game.js` | 通过 |
| `node tools/dom_contract_check.mjs` | ✓ DOM 契约对账全部通过（3 条已核实无害的 WARN） |
| `node tools/dom_spectate_frame_check.mjs` | **12 项全绿**（方向写反时 4/12 红、转置写反时 5/12 红） |
| `node tools/spectate_check.mjs` | **8 次运行 · 3 次全绿 · 5 次各红 1 项** —— 5 次红的全部是同一条**第 4 批既有**的 flakiness（`连锁响应应当实时出现在观众的连锁区`，第 4 批的注释里原本就标着"已知既有 flakiness：读到时可能已结算；本轮未改动这条路径"）。<br>★ **本批新增/收紧的任何一条断言，8 次里一次都没红过**（`Select-String '^FAIL.*(探针自检\|逐格严格相等\|没有对调\|读数冻结\|自我校准\|两块棋盘本该画\|收尾)'` 命中数 = **0**）。<br>★ 本批**没有改动那条连锁路径**（`git diff` 里没有它相关的增删行）—— 它的 flakiness 是**既有**的、不是重试掩盖的；8 次里 3 次全绿，失败项与第 5 批报告记录的**是同一项**。 |

### 隔离扫描（不变量 1）的原始数字

```
PASS  （前提）扫到的 payload 里**确实有坐标**（所以"没扫到坏坐标"才有意义）
      -> {"coordCount":4,"allowedCount":1}
PASS  ★★★ 观众收到过的**每一帧**里都没有船位字段、也没有"没挨过炮"的坐标（不变量 1）
      -> {"bad":[],"badCount":0,"coordCount":4,"total":32,
          "kinds":{...,"spectate_board":2,...},"allowedCount":1}
PASS  ★★ 自我校准：同一套判据**真的能**抓到"带船位的假帧"（不是一条永远绿的扫描）
      -> {"badCount":4,"bad":["FAKE_LEAK:ships","FAKE_LEAK:positions",
                              "FAKE_LEAK:coord(5,5)","FAKE_LEAK:coord(5,5)"]}
```

自我校准腿 `badCount` = **4**（判据是 ≥2），说明这条扫描不是空转绿。
另外 `"spectate_board":2` 说明观众那条连接**确实收到过两条棋盘帧**
（回光返照那一段：标记时一条 + 收尾一条），扫描覆盖到了新事件。

### 四条核心不变量

1. ★ **观战者永远收不到船位** —— 原始收件扫描 `badCount=0`（含自我校准腿）；
   帧的三级白名单过滤仍在（`tests/test_spectate_batch5.py` 全绿）；
2. ★ **双方动作都看得见** —— 本批额外把"棋盘逐格"钉死（观战与实战同口径）；
3. ★ **实时 + 中途进席有快照** —— `spectate_sync` / `spectate_board` 两条路径逐格一致；
4. ★ **观战席与观战聊天对局中双方不可见（上限 20）** —— E2E 的名单/聊天隔离腿全绿。

### 安全边界重新确认

* **原地复活可以暴露**（格子本就公开）：`疗愈` 那一格来自 `attacks` 历史 ✅；
* **增援 / 死者苏生 / 滥竽充数 / 神机妙算的新位置继续保密**：
  `test_redeploy_keeps_the_new_position_secret` 仍绿，且帧的数据源仍是 `Player.attacks`
  （新位置没挨过炮，在这个列表里根本不存在）✅。

---

## 6. 本轮**仍未验证**的部分（如实列出）

1. **真浏览器里"帧路径"的端到端逐格比对**：`tools/spectate_check.mjs` 里那条严格断言
   跑的是"快照进席 + 回光返照后的 DOM"，**不是**"p1 打 {(0,0),(1,1)}、p2 打 {(4,4),(5,5)}"
   的构造局面（E2E 造不出那种干净局面）。那个构造局面是在
   `tools/dom_spectate_frame_check.mjs`（vm + 最小 DOM 桩）里验的 ——
   它跑的是**真的 game.js**，但 DOM 是桩，不是真浏览器。
2. **`疗愈` / `死者苏生` 在真浏览器里的观战棋盘**：pytest 钉住了帧的内容，
   E2E 没有覆盖（E2E 只覆盖了回光返照那条）。
3. **`handle_place_ships` 没有"没在等摆放就拒绝"的闸门** —— 既有行为，
   本批只钉住不动它（见 §2.4，需要作者拍板才改）。
4. **6 格以上的棋盘**：本批所有断言都是 6×6（`spectateBoards` 的渲染循环硬编码 6×6）。
5. **`spectate_check.mjs` 那条既有 flakiness** 的根因（"连锁响应实时性"读到时可能已结算）
   **没有**在本轮调查，也没有修 —— 本轮 8 次里它红了 5 次。这一项**只能靠重试**，
   本批没有让它变稳定（也没有让它变差：本轮没碰过那条路径）。
6. **观战席聊天/开关那一整段**：本批一个字没改，靠 E2E 回归覆盖。
