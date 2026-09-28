# 实时观战 —— 第 7 批：那条"红了 5/8"的连锁断言到底是甲还是乙（2026-09-23）

> 第 4 批起 `tools/spectate_check.mjs` 里就有一条断言**一半的次数是红的**：
>
> ```
> ★★ 连锁响应应当实时出现在观众的连锁区
> （⚠️ 已知既有 flakiness：读到时可能已结算；本轮未改动这条路径）
> ```
>
> 第 4/5/6 批都在注释里记了"已知 flakiness"，**没有人查清**。第 6 批报告里
> 甚至写着"这一项**只能靠重试**"。本批把它查到底，并给出可复现的因果证据。

---

## 1. 结论

**（甲）工具脆**。观战者**每次都拿到了**连锁响应：

| 问题 | 答案 | 证据 |
| --- | --- | --- |
| 观战者最终有没有拿到连锁响应？ | **拿到了**，一次不落 | 观众那条连接收到的帧清单里每次都有 `magic_chain_updated(无中生有 + 失灵！)` |
| 红的那几次是哪种？ | **画了又被清空**（不是"没到"，也不是"到了没画"） | `chain_resolved` 那条帧到达时 `domCountBefore = 2`（DOM 里正挂着那两张） |
| 为什么读不到？ | 那一帧 DOM 只存在 **3~17 毫秒**，而工具在 ack 后 **18~33ms** 才第一次读 | 见 §3 的两组毫秒级时间线 |

⇒ **不是玩家可见的缺口**，服务端与前端这一段的语义一直是好的。

---

## 2. 怎么查的（三层证据，全部原始输出）

### ① 服务端层：这一帧到底发不发观众

* `chain_response`（`server.py`，`room.chain.append(...)` 之后）**必然**调
  `emit('magic_chain_updated', {'chain': room.chain}, room=room_id)`；
* `magic_chain_updated` 登记在 `spectate.SPECTATE_EVENTS`（值 = `_pub_magic_chain`），
  所以 `emit` 的第三条腿**会**把它净化后发进 `spectate:<room_id>`；
* `chain_resolved` 也在表里（`None` = 原样转发）。

⇒ 结构上这条动作**一定**到得了观众通道。但这只是"代码上应该"，
  第 6 批的教训是"在表里 ≠ 真的会发"，所以必须实测。

### ② 原始 socket 层：观众这条连接**真的收到了什么**

在观众页面上装一个**帧台账**（`CHAIN_LEDGER_TAP`）：包一层
`gameState.socket.onevent`，对连锁相关的四个事件在**帧到达的那一刻**同时记下
**payload** 与**那一刻 DOM 里画着什么**（`domCountBefore`）。

> 为什么必须"就地记"：事后读 DOM 是**两个不同时刻**的读数，
> 而这里要区分的恰恰是"到了没画"和"画了又被清空"—— 只有同一个瞬间的两个读数才分得开。

失败那次的台账（`.tmp/spectate_runs/exp4_04.log`，毫秒级）：

```json
{"n":3,"rows":[
 {"ev":"magic_chain_updated","t":1790104604975,"chainLen":1,
  "domCountBefore":0,"snapChainLenBefore":0,"names":["p1:无中生有"]},
 {"ev":"magic_chain_updated","t":1790104604988,"chainLen":2,
  "domCountBefore":1,"snapChainLenBefore":1,"names":["p1:无中生有","p2:失灵！"]},
 {"ev":"chain_resolved","t":1790104604992,"chainLen":0,"results":2,
  "domCountBefore":2,"snapChainLenBefore":2,
  "domTextBefore":["第1张 · specBmud22185：失灵！","第2张 · specAmud22185：无中生有"]}]}
```

三件事同时成立：**帧到了**（两张牌都在）→ **被画了**（`domCountBefore=2`）
→ **4 毫秒后被清空**。而工具的逐次轮询是
`[{"i":0,"ms":33,"n":0},{"i":1,"ms":245,"n":0}, … 75 次全 0]` ——
第一次读 DOM 落在 **33ms**，窗口（17ms）早就关了。

### ③ 服务端轨迹：为什么这一帧只活 17 毫秒

临时给 `_can_respond_chain` / `_advance_chain_window` / `resolve_chain` /
`_schedule_chain_timeout` 加 `DEBUG_CHAIN_TRACE=1` 的打印（**不入库**）：

```
[CHAIN_TRACE] emit magic_chain_updated room='76f3dc'          ← 打出「无中生有」
[CHAIN_TRACE] can_respond? pid='fa30…' speed3=['失灵！'] hand=[3 张] t=…683.166
[CHAIN_TRACE] window OPEN to 'fa30…' timer=0 chain_len=1 t=…683.166
[CHAIN_TRACE] emit magic_chain_updated room='76f3dc'          ← 对方响应「失灵！」
[CHAIN_TRACE] can_respond? pid='e5f2…' speed3=[] hand=['冻结'] t=…683.182
[CHAIN_TRACE] can_respond? pid='fa30…' speed3=[] hand=[2 张]   t=…683.182
[CHAIN_TRACE] resolve_chain room='76f3dc' results=2           t=…683.183
```

**根因**：响应者**只有那一张速阶3**，打出去之后 `_can_respond_chain` 对**双方**
都返回假 ⇒ `_advance_chain_window` 在**同一个栈帧里** `resolve_chain`（**17ms**）。

> ⚠️ 第 4~6 批把它记成"响应把窗口交给对方，10 秒没人接就自动结算" ——
> **那是误判**：10 秒窗口确实存在（下面那条绿轨迹），但它只在一半的局里出现。

绿的那一半（对手手里**还有**速阶3 ⇒ 窗口真的开满 10 秒）：

```
[CHAIN_TRACE] window OPEN to 'b64f…' timer=2 chain_len=2 passes=1 t=…734.626
[CHAIN_TRACE] timeout fired … token=1 t=…744.619
[CHAIN_TRACE] timeout fired … token=2 t=…744.619
[CHAIN_TRACE] resolve_chain room='6e534c' results=2 … t=…744.619   ← 10.0 秒后
```

⇒ **红/绿的分界是"对方手里还剩不剩速阶3"**，也就是开局抽牌的随机性
⇒ 概率约一半 ⇒ 这就是"8 次里红 5 次"。

---

## 3. 判据怎么改的（**不放宽语义**）

旧判据：`waitFor(15s, 轮询 DOM 直到连锁区出现第二张)` ——
它问的是"**某一毫秒的 DOM 里恰好还挂着它吗**"，而那不是不变量。

新判据：**观众那条连接真的收到了什么** —— 台账里存在一帧
`magic_chain_updated`，其 payload 的 `chain` 里**两张牌都在**
（`无中生有` + `失灵！`）。语义一个字没少：

| | 旧 | 新 |
| --- | --- | --- |
| 要求"观众拿到了这张响应" | ✅ | ✅（原始帧） |
| 要求"DOM 里画出来了" | ✅（但只有 17ms 的机会，一半假红） | ✅ 由**同瞬台账**给证（`domCountBefore≥2`），且**渲染真的没画**时会红 |
| 要求"某一毫秒 DOM 恰好非空" | ✅（这才是假红的来源） | ❌ 降级为 `NOTE`（不判负） |

配套加了两条**反向校准**（教训 #34：判据不能空转绿）：

* "结算报文里出现这张卡、但没有连锁帧"**不算**数（判据不认 `chain_resolved`）；
* "只有第一张牌的那一帧"**不算**数（新判据抓得住"第二张没到"）。

以及一条**归因断言**：若抓到了 `chain_resolved` 那条帧，则它到达时
`domCountBefore` 必须 ≥ 2 —— 否则就是"**到了没画**"（那才是真缺陷，会红）。

### 为什么不脆了

新判据读的是**帧自己的记录**，与"工具什么时候去读"**完全无关**：
帧到了就记一条，不依赖任何一次求值落在哪一毫秒。
唯一能让它红的情形是"观众那条连接压根没收到这一帧"—— 那正是要守的东西。

---

## 4. 工具改动的实测数字

| | 跑了几次 | 全绿 | 红的项 |
| --- | --- | --- | --- |
| 改前（HEAD 的原判据，本机复跑） | 10 | **7** | 3 次全是同一条 `连锁响应应当实时出现在观众的连锁区` |
| 改前（带台账的对照版，历史累计） | 20 | 15 | 5 次同上 |
| 改后（第 7 批最终版） | **24** | **24** | 无 |

> 改后那 24 次里，**判据本身红了 0 次**；第 1 批的 8 次里出现过 1 次
> `（记录）断言落地那一刻 DOM 里还挂着两张` —— 那条同一批就改成了不判负的
> `NOTE`（它读的正是"某一毫秒"，已经不是断言了），之后 16 次全绿。

### 不变量一的隔离扫描（原始数字，改后）

```
PASS  （前提）扫到的 payload 里**确实有坐标**（所以"没扫到坏坐标"才有意义）
      -> {"coordCount":4,"allowedCount":1}
PASS  ★★★ 观众收到过的**每一帧**里都没有船位字段、也没有"没挨过炮"的坐标（不变量 1）
      -> {"bad":[],"badCount":0,"coordCount":4,"total":32,
          "kinds":{"magic_chain_updated":4,"chain_resolved":3,"spectate_board":2,...},
          "allowedCount":1}
PASS  ★★ 自我校准：同一套判据**真的能**抓到"带船位的假帧"（不是一条永远绿的扫描）
      -> {"badCount":4,"bad":["FAKE_LEAK:ships","FAKE_LEAK:positions",
                              "FAKE_LEAK:coord(5,5)","FAKE_LEAK:coord(5,5)"]}
```

自我校准腿 `badCount = 4`（判据是 ≥2）⇒ 这条扫描不是空转绿。
`magic_chain_updated: 4` ⇒ 观众那条连接**确实收到过**连锁帧（本批要证的正是它）。

---

## 5. 新增的 pytest 守卫（`tests/test_spectate_batch7.py`，4 条）

原来"观众能不能看到连锁响应"**只有那条脆工具在守**。第 7 批把服务端这一半
用 `socketio.test_client`（真 session + 真 `request.sid`）钉死：

| # | 用例 | 守什么 |
| --- | --- | --- |
| 1 | `test_chain_response_reaches_spectators` | ★★ 响应之后观众的**收件队列**里有 `magic_chain_updated`，payload 里两张牌都在、座位标签是 `p1`/`p2` |
| 2 | `test_chain_frame_keeps_action_and_drops_player_id` | 净化**没把动作砍掉**、也**没把 `player_id`（socket sid）/`targets` 漏出去**（逐项比键集合） |
| 3 | `test_chain_response_guard_can_fail` | ★★ **证明能红**：把 `chain_response` 里那条广播掐掉 → 用例 1 必须红 |
| 4 | `test_guard_fails_when_event_is_removed_from_the_allow_list` | ★★ **证明能红（第二种口径）**：把事件从 `SPECTATE_EVENTS` 摘掉（默认拒绝）→ 用例 1 必须红 |

### 每一条新守卫"怎么证明能红"（真实改源码，原始输出）

**红测① 掐掉 `chain_response` 里的连锁广播**（把那一行 `emit(...)` 换成 `pass`）：

```
FAILED tests/test_spectate_batch7.py::test_chain_response_reaches_spectators
FAILED tests/test_spectate_batch7.py::test_chain_frame_keeps_action_and_drops_player_id
FAILED tests/test_spectate_batch7.py::test_chain_response_guard_can_fail
3 failed, 1 passed
E  AssertionError: 观众**没有收到**连锁响应这一帧（`magic_chain_updated` 一个都没有）
   —— 这是真缺口（不变量二的连锁响应那一条）：
   {'game_log': [...2 条...], 'chain_resolved': [{'results': [两张牌都在]}],
    'phase_updated': [...]}
E  assert []
```

注意这条红色证据**顺带把"对照腿"给了**：收件队列里 `game_log` 与
`chain_resolved` 都在（说明这条连接当时活着、而且在收事件），
**唯独**少了那一帧 —— 所以"没收到"不是"什么都没收到"。

**红测② 把事件从允许表摘掉**：

```
FAILED tests/test_spectate_batch7.py::test_chain_response_reaches_spectators
FAILED tests/test_spectate_batch7.py::test_chain_frame_keeps_action_and_drops_player_id
FAILED tests/test_spectate_batch7.py::test_guard_fails_when_event_is_removed_from_the_allow_list
3 failed, 1 passed
```

**还原之后**：`4 passed`，且 `server.py` / `spectate.py` 与 `HEAD`
**逐字节相同**（`git show HEAD:<file>` 对比 sha256 ⇒ `True`）。

---

## 6. 本批交付

| 文件 | 改动 |
| --- | --- |
| `tools/spectate_check.mjs` | 加**连锁事件台账**（帧到达瞬间同时记 payload 与 DOM）；把那条断言从"轮询 DOM"换成"读这条连接收到了什么"；加两条反向校准 + 一条归因断言；"某一毫秒 DOM"那条降级为 `NOTE`（不判负） |
| `tests/test_spectate_batch7.py` | **新增 4 条**（主守卫 + 净化口径 + 两条"证明能红"） |
| `changelog.py` | **不加**（见 §7） |
| `CLAUDE.md` | 教训 #15 补一句"就地记 vs 事后读"（与 §12 文档索引同步） |

`server.py` / `spectate.py` / `static/game.js` / `templates/index.html`
**一个字都没有改** —— 本批是工具 + 测试。

---

## 7. 为什么不加玩家公告

`changelog.py` 是**玩家唯一看得到的"这次改了什么"**，所以只有**玩家可见的变化**
才加。本批的结论是（甲）：玩家侧的行为**一个字节都没变**（观战者本来就收得到
连锁响应，本来就画得出来），改的是**我们自己工具的判据**。加公告会是一句谎话 ——
与第 1、2 批"观众还进不来所以不加"同一个判断。

---

## 8. 本轮**仍未验证**的部分（如实列出）

1. **另一半（10 秒窗口）在真浏览器里的"内容"断言**：换判据后工具**不再保证**
   读到那两张 DOM（它固定等满 15 秒轮询），所以"DOM 上的文字是
   `第1张 · <乙>：失灵！`"这两条内容断言大多数运行走"跳过"那一支。
   内容对不对改由 **pytest 守卫**（帧的 payload）负责 —— 帧与 DOM 之间那一段
   （`renderSpectateChain` 真的把 `seat` 映射成玩家名）**只在恰好读到的那几次**
   被验过（改后 24 次里读到过若干次，全部通过；但这是"碰上就验、碰不上不验"）。
2. **"17ms 内被清空"这个数值本身**：它是本机（本机 Chrome/Edge + eventlet +
   本机网络）测出来的。**没有**在生产服务器上量过这个时间窗。
3. **`_advance_chain_window` 在双方都接不了时"同帧结算"是不是期望行为**：
   本批**只观测、没有改**。它带来一个玩家可见的观感差异 ——
   对手还有速阶3 时观众能盯着连锁区看 10 秒，没有时那一帧一闪而过。
   作者若认为需要"结算前留一小段展示时间"，那是**另一件事**（改的是对局节奏，
   不是观战），本批不做决定。
4. **`_schedule_chain_timeout` 的旧定时器**：轨迹里每次结算前都有两条
   `timeout fired`（token=1 与 token=2）同时醒。代际令牌让它们只生效一次
   （没有双重结算），**本批没有去动它**，也没有专门为它加守卫 ——
   只如实记在这里。
5. **`tools/spectate_check.mjs --shot`**（截图）本批没跑。
