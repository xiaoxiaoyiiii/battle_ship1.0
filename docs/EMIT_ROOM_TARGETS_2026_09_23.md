# `emit` 的收件人：把「玩家 sid」当「房间号」的 9 处（2026-09-23）

> 本批**只改写法**：`emit(..., room=<sid>)` → `emit(..., to=<sid>)`。
> 与观战功能无关（观战只是让这个写法**有后果**的那面镜子）。
> 成果：新守卫 `tests/test_emit_room_targets.py`（19 条），
> `pytest` 基线 2247 → **2266 passed**。

---

## 1. 两个关键字不是同义词

```python
def emit(event, data, to=None, room=None):
    ...  # 先 semit，无请求上下文时退回 socketio.emit
    room_id = _live_room_id(room) if (to is None and room) else None
    if room_id is not None:
        _emit_to_spectators(event, payload, room_id)     # 第三条腿：净化后复制给观战通道
```

* `to=`   = **只发给一条连接**（私人消息，第三条腿不生效）；
* `room=` = 发给一个 **socket.io 房间**（只有"活着的对局房间号"才复制给观众）。

**为什么这么写没当场炸**：socket.io 里每条连接都自带一个以自己 sid 命名的房间，
所以 `room=<sid>` 与 `to=<sid>` 的**收件人集合完全相同** —— 事件照样发到、
玩家照样收到。差别只在"这一发被当成单发还是房间广播"这个**分类**上，
而分类错了的后果是：`emit` 会拿这个 sid 去走观战第三条腿，
被 `_live_room_id` 那层门禁**悄悄**挡掉（不报错、不发、没人知道）。

⚠️ 这正是 CLAUDE.md 教训 #32/#34 的形状：症状被盖住，写法本身还是错的。

---

## 2. 9 处逐处（按 AST 穷举，不按行号）

| # | 函数 | 事件 | 真实意图的判断依据 |
| --- | --- | --- | --- |
| 1 | `GameRoom.draw_card` | `hand_updated` | payload 是**完整手牌**，只能给本人 |
| 2 | `test_add_all_magic_cards` | `hand_updated` | 同上（调试加牌） |
| 3 | `test_add_specific_magic_card` | `hand_updated` | 同上（调试加牌） |
| 4 | `handle_join_room`（房间不存在） | `error` | 提示只对**发起这次 join 的连接**有意义 |
| 5 | `handle_join_room`（房间已满） | `error` | 同上 |
| 6 | `handle_chat_message`（无房间 fallback） | `chat_message` | payload 带 `isMe: True` —— 只对**一个**收件人成立 |
| 7 | `_grant_match_achievements` | `achievements_unlocked` | 注释原文「只发本人」 |
| 8 | `_grant_match_xp` | `xp_gained` | 注释原文「单独推给本人」 |
| 9 | `_emit_rank_events_now` | `rank_changed` | 注释原文「只发本人那一份」 |

**没有一处该改成 `room=<真房间号>`**：9 处全是"只给这一个玩家"，
改成广播会**制造**新缺陷（对手看到别人的手牌 / 结算事件）。
`handle_chat_message` 的另一半（有房间时）本来就是 `room=room.id` 广播，那一条没动。

### ⚠️ 不是"5 处"

`docs/SPECTATE_2026_09_22.md` §4 记的是 **5** 处（`572`/`1697`/`1822`/`3771`/`4072`），
那些行号早已漂移，而且它漏掉了 `xp_gained` 与三处 `request.sid`。
本批按 AST 重新穷举（`emit(...)` 包装 + `semit`），实际是 **9 处**。
另有一处 `socketio.emit(..., room=sid)`（`_push_friend_event`）**是对的**：
那是 python-socketio 直调、`to` 只是 `room` 的别名、不经包装，
守卫因此按"出口标注"把直调排除在外（登记在 `_ALLOWED_SID_ROOM_EMITS` 里并写明理由）。

---

## 3. 改前谁收到 / 改后谁收到：**完全相同**

不是推断，是实测：把 `server.py` 还原成改动前，跑新用例 ——
**13 条红，但红的全是"写法"那一条断言**（`_assert_single_send`），
"本人收到 / 对手没收到 / 旁观没收到"那几句**全绿**。
例：`room=player.sid` 时探针记到的是
`('semit','hand_updated',None,'<sid>')` + `('socketio',…)`（`to` 空、`room` 是 sid），
交付行为一字不差。

⇒ **玩家侧零可见变化 ⇒ 本批不加 `changelog.py` 公告**（加了就是一句谎话）。

---

## 4. `_live_room_id` 的结论：**保留，但不再静默**

它现在**只服务**观战腿："`room=` 里那个值是不是一个活着的对局房间号"。
逐个表态（AST 全量扫 `room=` 共 104 处）：

| `room=` 的值 | 处数 | 表态 |
| --- | --- | --- |
| `room.id` / `room_id` / `getattr(room,'id',None) or None` | 95 | 对局房间号，正常 |
| `spectate.spectate_room_id(...)` | 6 | 5 处是 `socketio.emit` 直发观战通道；1 处是 `emit('spectate_ended', …)` —— **非对局房间名的合法调用**，门禁要挡住它别自我循环 |
| 转发用的形参 `room`（在 `emit` / `semit` 内部） | 2 | 就是它自己 |
| `<sid>` | 1（改之前另加 9） | 本批把 9 处全改成 `to=`；剩下这 1 处是 `_push_friend_event` 的 python-socketio **直调**（不经包装、无第三条腿），已在守卫的例外表里写明理由 |

* **为什么不删**：删掉之后 `emit(..., room=<观战通道名>)` 那一处会去 `sanitize_event`
  再复制一份到 `spectate:<spectate:…>`（虽然 `_emit_to_spectators` 里还有一道
  `is_spectate_room` 早退，但那是"两道都靠别人兜"）；而且"观战腿只认活着的对局房间"
  这句话必须有一处**结构性的**落点。
* **为什么不再静默**：原来它把"不是房间号"这件事**连个痕迹都不留**，
  于是 9 处错用活了很久（门禁的"兜底"变成了"掩盖"）。
  现在返回 None 之前会打一行 `[emit] room=… 不是活着的对局房间 → …请改用 to=`。
  实测：两轮真浏览器观战驱动 + 全套 pytest 的输出里**一次都没出现**
  （唯一会打它的是一条专门验证"不许静默"的用例，它的输出被 pytest 的 capsys 收走）。

---

## 5. 源码级穷举守卫（`tests/test_emit_room_targets.py`）

* **扫描范围**：`server.py` 全部 `emit(...)` / `semit(...)` / `socketio.emit(...)`（AST，不是正则）；
* **判据**：`room=` 的值"看起来是 sid"即报错 —— `*.sid` / `sid` / `*_sid` /
  `getattr(x,'sid')` / `x['sid']`；`room=None`、`room=<房间号变量>`、
  `room=spectate_room_id(...)`、`room=getattr(room,'id',None) or None` 一律合法；
* **只扫 `room=`**：`to=player.sid` 是完全正确的常见写法（全文件 89 处），
  有一条专门的假阳性用例钉住它；
* **能红**：把 `draw_card` 的 `to=player.sid` 改成 `room=player.sid` →
  `test_no_wrapper_emit_passes_a_sid_as_a_room` 与
  `test_all_nine_sites_are_single_sends_now` 同时红（报出 `server.py:1017 draw_card`）→ 改回 → 绿；
* **反面用例**：`to=<sid>` 不许被扫进去（假阳性）、`_ALLOWED_SID_ROOM_EMITS`
  里的写法必须真实存在（登记表不许烂在原地）、例外理由必须非空。

---

## 6. 没做 / 没验的

* **没验真浏览器里"手牌 / 经验 / 段位"的观感**：本批改的是服务端写法，
  收件人集合逐处断言过（真 socket），但**没有**跑前端渲染的无头工具
  （本批没动一行 JS；`node --check` 也没有可跑的改动）；
* `node tools/dom_contract_check.mjs` 过了（与前端无关，按流程跑）；
* `node tools/spectate_check.mjs` 跑了 **2 次，2 次全绿**（各 156 PASS / 0 FAIL），
  这是"修完之后观众没开始收到不该收的东西"的证据；
* 生产环境**只验证到健康检查**，没有真人在线观察日志里有没有 `[emit]` 告警
  （本地两轮驱动里是 0 条，但本地流量与线上不同）。
