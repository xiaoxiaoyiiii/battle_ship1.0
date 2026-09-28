# 实时观战 —— 第 2 批：快照 / 观众进出 / 观战席 / 观战开关（2026-09-22）

> 第 1 批（`docs/SPECTATE_2026_09_22.md`）只做了地基：事件白/黑名单、`emit` 的第三条腿、
> 两条穷举守卫。**观众当时还进不来**（没有入口、没有加入事件）。
> 本批把观众真的放进来，因此新增的全部是**攻击面**，下面每条都写清"改坏了会怎样"。

---

## 1. 本批交付

| 文件 | 改动 |
| --- | --- |
| `spectate.py` | 座位标签唯一实现（`seat_order`/`seat_label`/`seat_label_map`）、`SPECTATOR_LIMIT=20`、快照禁字段表 `SNAPSHOT_FORBIDDEN_KEYS`、递归坐标剥离 `_strip_coord_keys`、**`game_log` 净化**（第 1 批的真泄漏）、`_pub_magic_chain` 换座位标签 |
| `server.py` | `GameRoom.spectators`（房间级）+ `spectate_join`/`spectate_leave` + `_spectate_*` 辅助 + **`_build_spectate_snapshot`（白名单另建）** + 人数广播 + 断线/回收清理 |
| `db.py` | `user_profile.allow_spectate`（判存在再 ALTER，默认 1）+ `get/set_allow_spectate` |
| `api.py` | `GET/POST /api/spectate/setting` |
| `tests/test_spectate_batch2.py` | **新增 35 条**（快照双向断言 / 通道隔离真 socket / 开关端到端 / 上限 / 观众不能操作 / 进出清理 / 源码级守卫） |
| `tests/test_spectate_guards.py` | 只同步了两处：`KNOWN_EVENTS` 加 3 个新事件、元测试替身 lambda 补 `room=None` 参数（签名契约变了，断言一个字没改） |

`python -m pytest tests/ -q` → **2121 passed**（第 1 批后基线 2086，+35）。

---

## 2. ★ 快照：为什么是"白名单另建"而不是"复用重连快照再删字段"

`_build_room_sync`（`server.py:8698` 一带）有 **41 个顶层键**，其中
`ships[].positions`、`hand`、`opponent_attacks`、`effect_flags`、
`pending_sacrifice*`、放置流程派生字段**全是私有状态**。
它今天安全**只因为**：`to=request.sid` 单发 + 先过座位身份校验。

一旦"放宽它 / 复用它给观众"，重连快照本身就变成了透视接口；
而"逐个删字段"漏一个就是漏洞，**而且不会报错**（教训 #9）。
所以 `_build_spectate_snapshot` **只写"给观众什么"**，没写的一律不存在。

### 字段清单

**给（全部是公开信息）**
`room_id` `state` `current_phase` `current_attacker` `attacks_remaining` `round`
`attack_order` `ranked` `mode` `winner` `game_over_reason` `field_magic`
`sides.p1/p2 = {seat_id, name, remaining_ships, hand_count, attacks[]}`
（`attacks` = **该座位打出去的格**，每格 `x/y/hit/ship_sunk`）
`seat_labels`（原始座位 key → `p1`/`p2`，给实时流对齐用）
`board_attacks.p1/p2`（**落在该棋盘上的格** = 对方打出去的格；与 `attacks` 互为转置，
守卫断言恒等）、`game_logs`、`chain`（净化后）、
`shenwei_holes` / `frozen_area` / `last_stand_cells` / `last_stand_owner`、
`spectator_count` / `spectator_limit` / `spectators`（名单**只给观众自己**）。

**明确不给**（`SNAPSHOT_FORBIDDEN_KEYS`，测试递归扫任意层级）
`ships` `positions` `hits` `sunk_positions` `hand` `magic_hand` `revealed_positions`
`effect_flags` `active_effects` `pending_placement` `pending_sacrifice`
`pending_sacrifice_ships` `opponent_attacks` `sunk_ships` `max_ships`。

**手牌只有张数**：`hand_count = len(magic_hand)`；测试用两张带牌名的假手牌断言
牌名**不出现在快照的任何地方**（正面断言张数、反面断言名字）。

---

## 3. ★ 本批实测发现的**真泄漏**：`game_log` 的 detail 里带着整艘船

第 1 批把 `game_log` 登记成"原样转发"（`None`）。第 2 批实测发现**两个调用点把坐标塞进了日志 detail**：

| `server.py` | detail | 危险程度 |
| --- | --- | --- |
| `_sacrifice_ship`（约 10490） | `{'player','reason','positions': [被牺牲那艘船的**全部**格子]}` | ★★★ 被牺牲的船往往**一格都没挨过炮**（恶魔契约 / 神之宣告 / 命运骰子）→ **把一艘完好战舰的位置直接送出去** |
| 硫磺火焰（约 11836） | `{'caster_id','card_name','sunk_count','affected_positions': […]}` | ★ 那些格子已由 `attack_result` 逐格公开，但按"坐标字段一个都不外发"的口径一并剥掉 |

**为什么第 1 批的穷举守卫没抓到**：守卫用例给 `game_log` 的样例 detail 里
只有**已公开的被轰格**（`target {x,y}`），原样转发当然不泄漏 ——
这正是"样例没有坐标 ≠ 事件没有坐标"，也就是教训 #34 说的"零报错制造假象"。

修法：`spectate._pub_summary_line` + `_strip_coord_keys`（**递归**剥掉
`COORDINATE_KEYS`）。守卫：
`test_game_log_detail_positions_are_stripped`（含"未净化的原始日志**确实**带着
没挨过炮的船坐标"的反向校准）、`test_game_log_event_is_never_passthrough`。

---

## 4. 观战席与通道

```
玩家 ──join_room(room_id)──► socket.io room = <room_id>        ← 93 处房间级广播
观众 ──spectate_join─────► socket.io room = spectate:<room_id> ← 只有净化过的动作
```

* **只进观战通道**：`join_room(spectate.spectate_room_id(room_id), sid)`。
  写成 `join_room(room_id, sid)` 就是一次性透视 —— 有**行为**守卫
  （真 socket 收件：收得到 `attack_result`、收不到 `ships_updated`/`hand_updated`）
  **和源码级**守卫（AST 取 `join_room` 第一个参数必须 `spectate.` 开头）两重。
* **观众绝不写进 `room.players`**：只写房间级的 `room.spectators`。
  这是"全部写操作 handler 天然拒绝观众"的基础（它们的鉴权都是
  `player_id in room.players + _identity_ok`）。守卫有行为断言 + 源码级 AST 扫描
  （并附"把写入插进源码副本 → 扫得出来"的自我校准）。
* `room.spectators = {sid: {'name','user_id','joined_at'}}` —— 房间级字段，
  `__init__` 初始化、消费点、回归用例三件齐（教训 #11）。

### 拒绝清单（每一条都有明确文案）

未登录 / 缺少房间号 / 房间不存在 / 对局已结束 / **还没坐满人** / 人机房 /
**他本人是这局的玩家**（座位 key、座位登记的连接、座位账号三种命中）/
席满 20（文案带数字）/ **双方没有都开观战开关**。

### 读取时机（作者裁定，别改）

**观众进入的那一刻读一次**，之后**永不复查、永不踢人** ——
"打到一半怎么可能能关，这不是在设置里的吗"，**不存在中途切换场景**。
守卫：`test_switch_is_read_once_and_never_kicks_anyone`
（席上的人在中途关掉开关之后**仍然**收得到动作）。

---

## 5. 观战开关存在哪

* 位置：`user_profile.allow_spectate`（**老表加列**，`_migrate_schema` 里
  `PRAGMA table_info` + `ALTER TABLE`，失败只记日志不外抛 —— 教训 #14）；
* 默认：**`ALLOW_SPECTATE_DEFAULT = 1`（允许）**，DDL 的 `DEFAULT 1` 与"查不到行"
  的分支都指向这一个常量；
* 语义三态（`db.get_allow_spectate`）：`True` 允许 / `False` 关掉 / **`None` 不知道**
  （uid 为空、不是真账号、读库失败）。`can_spectate(None, …) is False` ——
  **未知退化成"不允许"**（教训 #21：隐私开关朝安全一侧兜）。
  因此**游客座位不可被观战**（匹配房 `Player.user_id` 为 None、
  自定义房游客的 `user_id` 就是 sid，`db.get_user` 查不到 → None）。
* 接口：`GET /api/spectate/setting`、`POST /api/spectate/setting`（`api.py`）。
* ⚠️ **刻意不并进 `POST /api/profile/card`**：那条是"整行语义、缺的键用默认值补齐"，
  而本批不动前端 —— 并进去的话玩家每存一次名片（换称号/边框）就把开关
  **静默改回允许**。守卫：
  `test_saving_profile_card_does_not_reset_spectate_switch`
  （真走名片接口 + 逐列检查 `save_user_profile_extra` 的 SQL 里没有这一列）。

---

## 6. `player_id` → 座位标签（作者已批准，只动净化）

`_pub_magic_chain` 现在**删掉原始 `player_id`**（匹配房里它是 socket sid），
只留 `seat`（`p1`/`p2`）。标签的**唯一实现**在 `spectate.seat_order/seat_label`
（按 `room.players` 的插入顺序 = 入座顺序），快照与实时流共用同一份。
取不到 room（老调用点传的是房间号字符串）时退化成 `unknown` ——
**永远是标签或 unknown，绝不回显原始 id**。

⚠️ 快照里另外给了 `seat_labels`（原始 key → `p1`/`p2`）：实时流
（`attack_result.attacker` / `turn_change.current_attacker`）用的仍是原始 key
（第 1 批已批准原样转发），观众要靠这份映射把两边对上。**这是连接标识，不是凭据；
重连 token 从来不外发。** 前端**不许**自己把 key 猜成 p1/p2。

---

## 7. 没做 / 没验的

* **大厅「进行中的对局」列表是第 3 批**（本批只保证"拿到 room_id 就能进"）；
* **观战席聊天是第 5 批**（本批只给人数，观众名单只出现在自己的快照里）；
* **前端一行没动**（第 4 批）。因此本批**没有**加 `changelog.py` 的玩家公告 ——
  玩家此刻既看不到入口也点不进去，公告会是一句谎话。
  第 1 批同样是这个判断（`git log` / `changelog.py` 里都没有观战条目）。
* **真浏览器实时性未验**：`pytest` 的 `socketio.test_client` 能验"谁收得到什么"
  （收件队列是真的按房间投递的），但**没有**验真浏览器里前端渲染与延迟；
  那要等第 4 批的无头工具（`tools/*.mjs`）。
* 观众断线时**不再调 `leave_room`**：连接已断，socket.io 自己会把 sid 从所有房间摘掉；
  替一条死连接退房没有意义（`_drop_room` 那条路同理，只清 `room.spectators`
  并发 `spectate_ended`）。这两条只有"内存状态"的断言，没有断言 socket.io 内部房间表。

---

## 8. 守卫怎么保证"不是永远绿的"

* 元测试 3 条（把快照/通道/源码改坏 → 断言必须变红）；
* 报告里另有 4 次**手工**演示（改源码 → 跑用例 → 看它变红 → 还原）：
  ① `join_room(room_id)`；② 去掉观战开关判定；③ 往快照塞 `ships`；
  ④ `game_log` 退回原样转发。
* 所有**进出观战**的用例都走真 socket（真 session + 真 `request.sid`），
  刻意避开"`_identity_ok` 无请求上下文时退化成成员校验"那个陷阱。
