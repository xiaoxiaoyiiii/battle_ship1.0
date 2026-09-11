# server.py 技术分析报告（4733 行）

> 分析对象：`server.py`（Flask + Flask-SocketIO，战舰棋 + 魔法卡）
> 分析方式：grep 定位 + 分段精读，全部结论基于源码行号。
> 生成日期：2026-09-10 之后（文件内注释最晚日期 2026-09-10）

---

## 0. 总体结构速览

| 区段 | 行号 | 内容 |
|---|---|---|
| 导入 + monkey_patch | 1–21 | 依赖、eventlet 补丁 |
| `emit()` 封装 | 24–30 | 全局发送函数（含无上下文的 SocketIO 兜底） |
| 日志工具 | 33–73 | `GameLog` / `add_game_log` / `log_magic` / `_log_name` |
| 在线人数 | 77–82 | `online_users` + `/api/online_count` |
| 数据类 | 84–208 | `Position` / `PlayerShip` / `MagicCard` / `EffectFlags` / `Effect` / `Player` |
| `GameRoom` | 210–394 | 房间状态机 + 攻击内联实现 |
| 卡表 & socketio | 397–403 | `magic_cards` 加载、`socketio` 实例、`MAX_CHAT_MSG_LEN` |
| `RoomManager` | 405–580 | 房间/匹配/大厅管理 |
| 身份鉴权 | 583–610 | `_identity_check` / `_identity_ok` |
| 场地魔法工具 | 613–629 | `field_magic_name` / `_place_field_magic` |
| 测试事件 | 635–1085 | 12 个 `test_*` 调试 handler |
| 大厅/房间/连接事件 | 1086–1370 | `lobby` / `create_room` / `join_room` / `connect` / `disconnect` / `chat_message` / `find_match` / `cancel_match` |
| 布船/猜拳 | 1374–1598 | `place_ships` / `rps_choice` + `RPSResult` / `ChainItem` / `AttackResult` / `ChainResult` / `determine_rps_winner` |
| 攻击结算 | 1669–2039 | `frozen_ship_count` / `_check_last_chance` / `handle_attack` |
| 阶段流转 | 2042–2335 | `enter_battle_phase` / `enter_end_phase` / `end_turn` |
| AI | 2342–2410 | `_ai_player_id` / `_ai_place_ships` / `_maybe_run_ai_turn` / `_ai_turn_loop` |
| 教皇旨意攻击 | 2414–2542 | `papal_attack` + `_do_attack` |
| 用卡 + 连锁 | 2545–2772 | `use_magic_card` / `can_play_magic_card` / 连锁函数族 |
| 掉线重连 | 2775–2932 | 宽限、超时判负、token、快照 |
| 神机妙算 / 连锁响应 | 2935–3050 | `_apply_shenji_prediction` / `chain_response` |
| 场地/放置/查询事件 | 3052–3327 | `remove_field_magic` 等 |
| 辅助函数 | 3332–3508 | 神威扣洞、放置流程、`_finish_game` |
| **`apply_magic_effect`** | **3510–4683** | 1173 行巨型 dispatch |
| 收尾 | 4686–4733 | `get_uuid` / `surrender` / `__main__` |

---

## 1. 顶部初始化

### 1.1 eventlet monkey_patch（17–21）

```python
try:
    import eventlet
    eventlet.monkey_patch()
except ImportError:
    pass
```

**顺序问题（关键）**：monkey_patch 位于 **import 语句块中间**——第 7–13 行已经先 `import logging`、`from flask import ...`、`from flask_socketio import ...`、`import db`、`from api import app`，之后才打补丁。

标准做法是 monkey_patch 必须是**任何可能建立网络/线程的模块导入之前**的第一条语句。这里 `api`（内部创建 Flask `app`）与 `db` 已在补丁前导入。实践中 Flask 的 `app` 对象创建本身不建 socket，所以通常不炸；但 `socketio.run()` 走 eventlet 时会依赖补丁已生效这一点。**属隐患，非当前 bug**。文件 15–16 行的注释自己也承认了这个动机："eventlet 下必须先 monkey_patch：否则后台任务里的 time.sleep 会阻塞整个单线程 hub"。

`except ImportError: pass` 意味着**没有 eventlet 时静默降级**——此时 `socketio.start_background_task` 走 threading，而代码里大量 `time.sleep`（如 `_disconnect_timeout` 睡 30s）语义仍成立，但 `emit()` 的兜底分支行为会变。

### 1.2 全局变量

| 变量 | 行号 | 说明 |
|---|---|---|
| `online_users` | 77 | `set()`，存 **socket sid**（不是 user_id） |
| `magic_cards` | 78 | **纯类型注解**，无值；第 398 行才真正赋值 |
| `socketio` | 400 | `SocketIO(app, cors_allowed_origins="*")` |
| `MAX_CHAT_MSG_LEN` | 403 | 100 |
| `room_manager` | 580 | `RoomManager()` 单例 |

第 78 行 `magic_cards: list["MagicCard"]` 是**只有注解没有赋值**的语句——在运行时它是注解表达式，不进 `__dict__` 取值，因此第 147 行 `MagicCard.__init__` 内引用 `magic_cards` 时靠的是第 398 行的全局赋值。这依赖"第 398 行先于任何 MagicCard 实例化"这一顺序（`read_json` 在第 398 行调用，其内部 `MagicCard(**x)` 时 `magic_cards` 尚为**未定义**——见下方可疑点）。

### 1.3 `emit()` 封装（24–30）

```python
def emit(event, data, to=None, room: str | None = None):
    json_data = json.dumps(data, default=lambda o: o.__dict__)
    try:
        return semit(event, json.loads(json_data), to=to, room=room)
    except RuntimeError:
        return socketio.emit(event, json.loads(json_data), to=to, room=room)
```

逐点拆解：

1. **序列化往返**：先 `json.dumps` 再 `json.loads`，把任意对象（`Position` / `MagicCard` / `AttackResult` / `ChainItem` …）用 `default=lambda o: o.__dict__` 压成**纯 dict**。这是把自定义类变成可发送 payload 的统一手段，副作用是**丢弃方法、丢失 `to_dict()` 定制**（如 `ChainResult.to_dict()` 被绕过）。
2. **`to` 与 `room` 同时存在**：`semit(..., to=to, room=room)`。`to=sid` 单播，`room=room_id` 广播。
3. **异常兜底分支（28–30）**：只捕获 `RuntimeError`。Flask-SocketIO 在**没有请求上下文**（后台任务/`start_background_task` 线程）里调用 `flask_socketio.emit` 会抛 `RuntimeError`（"Working outside of request context"），此时改调 `socketio.emit(...)`（服务端主动推送，不依赖请求上下文）。
4. **可疑点**：
   - 只捕 `RuntimeError`，**其他异常（如序列化失败、socket 已断开）会向上冒泡**。`add_game_log`（62–65）自己又包了一层 `try/except Exception: pass`，但**直接调用 `emit` 的地方没有保护**，例如 `draw_card`（314）、`_place_field_magic`（628）。
   - `default=lambda o: o.__dict__` 对**继承 dict 的类**（`ChainResult` 实现了 `__setitem__` 但**不是** dict 子类）正常，但对含不可序列化字段（如 `func` 闭包、`Effect.func`）的对象会在 `json.dumps` **阶段**（try 之外！）就抛 `TypeError`。`Effect` 对象若被塞进 payload 会**直接 500 式崩溃且不被捕获**。
   - `json.dumps` 在 `try` **外部**，所以兜底分支只兜 socket 上下文问题，不兜序列化问题。

---

## 2. 核心类清单

### 2.1 `Position`（84–107）

**类级注解**：`x: int`、`y: int`、`hit: bool = False`、`ship_sunk: bool = False`、`is_sulfur: bool = False`、`is_bomb: bool = False`、`is_splash: bool = False`

**实例字段（`__init__` 93–101）**：`x`、`y`、`ship_sunk`、`is_sulfur`、`round`（**额外，类注解里没有，恒为 `None`**）、`hit`、`is_bomb`、`is_splash`

**方法**：
- `__eq__`（103–107）：支持与 **dict** 或 **Position** 比较。dict 分支比较 `x`/`y`；Position 分支直接取 `.x`/`.y`（**不做类型判断，与 int 比较会 `AttributeError`**）。

**注意**：定义了 `__eq__` 但**没有 `__hash__`**，所以 `Position` **不可哈希**——不能放进 `set`，也不能做 dict 的 key。代码里因此统一用 `(x, y)` 元组做集合运算（如 2396、4031）。

**`round` 字段死值**：类注解无 `round`，`__init__` 赋 `None`，全文件**从未写入**。第 4304 行注释明确承认："使用 damage_dealt_this_turn 而非 a.round，因为 Position.round 从未被赋值"。

### 2.2 `PlayerShip`（110–131）

**类级注解**：`invincible: bool`、`positions: list[Position]`、`hits: list[Position]`、`shield: bool = False`

**实例字段（`__init__` 116–131）**：`invincible = False`、`positions`、`hits`
- **`shield` 未在 `__init__` 中设置**，只在类注解 `= False` 处作为**类属性**存在。首个赋值发生在 `handle_magic_target` 的 `shield_choice` 分支（1660）。读出时 `ship.shield` 会回落到类属性 `False`，**功能上等价**，但 `**kwargs` 被静默吞掉——`PlayerShip(**{'positions': [...], 'hits': [...], 'shield': True})` 里的 `shield` **不会**存为实例属性（被 `**kwargs` 吸收丢弃）。
- **动态追加字段**：`frozen`（首次在 3971 赋值 `ship.frozen = room.round + 1`；删除在 2171 `del s.frozen`）。`frozen_ship_count`（1669–1671）用 `getattr(s, 'frozen', None)` 判存。
- `positions`/`hits` 会做 dict→Position 转换（120–131），所以 `PlayerShip(**x)` 能直接吃 JSON。

### 2.3 `MagicCard`（134–150）

**类级注解**：`name`、`speed`、`type`、`description`
**实例字段**：同上四个。

**逻辑（140–150）**：若 `speed`/`type`/`description` **三者都非空字符串**，直接用传入值；否则 `filter(lambda x: x.name == name, magic_cards)[0]` 从全局卡表**按名查表**（`[0]` 会在查不到时抛 `IndexError`）。

**隐患**：`MagicCard(**data['card'])`（2549、3011）依赖客户端把三个字段都传全，否则走查表路径；查不到卡名 → `IndexError` 直接 500。

### 2.4 `EffectFlags`（153–162）

**纯类属性**（**无 `__init__`**），因此**每个实例共享初始值、但赋值后变为实例属性**：
`treasure_hunter=False`、`prediction=False`、`subsidy=False`、`no_draw=False`、`forced_kill:int=0`、`vampire=False`、`last_stand=False`、`double_attacks=False`、`battle_spirit=False`

**动态追加**：代码里到处出现的 `room.players[x].effect_flags = room.players[x].effect_flags`（2938、4405、4266、4364、4215…）是**自赋值空操作**，纯噪声。

**致命的清空写法**（2278–2280、2317–2319）：
```python
room.players[p_id].effect_flags.__dict__ = {k: v for k, v in
    room.players[p_id].effect_flags.__dict__.items() if k in permanent_flags}
```
用**白名单过滤 `__dict__`**。因为初始值全在**类属性**上，过滤后实例 `__dict__` 被清空，读属性会回落到类默认值——**这是能工作的**。但 `prediction` 是 `False` 而 2259 行 `pred = getattr(player.effect_flags, 'prediction', 0)` 又 `isinstance(pred, int) and pred > 0` —— `False` 是 `int` 子类但 `> 0` 为假，**侥幸通过**。

### 2.5 `Effect`（164–175）

**字段**：`name`、`phase`、`end_phase`、`priority`、`func`（`__init__` 170–175 全赋值）

**用途**：游戏内钩子对象。`GameRoom.attack`（326–356）遍历 `self.effects` 找 `phase == "before_attack"` / `"after_attack"` 调 `func`。`apply_effect(end_phase)` 按 `end_phase` 弹出。

**半死代码**：全文件**只有 2 处** `Effect(...)` 构造：
- 3531（余音绕梁）：`Effect(card.name, "after_attack", "after_attack", 999, func)`
- 3606（火力全开）：`Effect(card.name, "before_attack", "", 999, func)`

而**唯一的遍历点是 `GameRoom.attack`（332–350）**，它是**旧版内联攻击**，`handle_attack` **完全不调用**它。所以这两个钩子**在真实对局中永不触发**（只有直调 `GameRoom.attack` 的测试路径才会跑）。

### 2.6 `Player`（178–207）

**类级注解**：`magic_hand`、`effect_flags`、`name`、`ships`、`attacks`、`remaining_ships`、`needs_reset`、`revealed_positions`、`max_ships`、`sunken_ships`、`user_id`、`sid`

**实例字段（`__init__` 193–207）**：
`magic_blocked = None`、`damage_dealt_this_turn = 0`、`magic_hand = []`、`effect_flags = EffectFlags()`、`name`、`ships`、`sid`、`attacks`、`remaining_ships`、`needs_reset = False`、`revealed_positions = []`、`max_ships = None`、`user_id`、`sunken_ships = []`

**注意 `magic_blocked`**：`__init__` 里设为 `None`，但 2162 行重置时也设 `None`（不是 `False`）。类型混用 `None`/`True`。
**动态追加字段**：`opponent_attacks`（3662–3663、847–848 **只在 `hasattr` 保护下访问，从未被创建**——纯死分支）。

### 2.7 `GameRoom`（210–394）

**类级注解（211–233）**：`id`、`players`、`state`、`rps_choices`、`attack_order`、`current_attacker`、`attacks_remaining`、`round`、`winner`、`field_magic`、`magic_history`（注释"无写入"）、`game_effects`、`current_phase`、`magic_temp_data`、`magic_discard`、`magic_deck`、**`chain`、`chain_waiting`、`chain_timer`、`chain_window`、`chain_passes`**、`last_attack`、`effects`

**实例字段（`__init__` 234–268）**：
| 字段 | 初值 | 说明 |
|---|---|---|
| `id` | `room_id` | |
| `players` | `{}` | key 约定两套（见 §9） |
| `state` | `'waiting'` | waiting / placing_ships / rock_paper_scissors / attacking / game_over |
| `rps_choices` | `{}` | |
| `attack_order` | `[]` | |
| `current_attacker` | `""` | |
| `attacks_remaining` | `0` | |
| `round` | `1` | |
| `winner` | `""` | |
| **`field_magic`** | `None` | 存**卡牌实例**（非名字） |
| **`magic_history`** | `[]` | `{card, caster, timestamp}`，仅 2741 写入 |
| `game_effects` | `{}` | 键：`holy_heart`/`reinforcement_check`/`demon_contract`/`papal_edict`/`last_chance`/`last_ship_change`/`shenwei_holes`/`excluded_ships`/`prediction_initial_<pid>` |
| `current_phase` | `'preparation'` | preparation / battle / end |
| `magic_temp_data` | `{}` | 临时交互态 |
| **`magic_discard`** | `[]` | **全局**弃牌堆（双方共用一个） |
| **`magic_deck`** | `[]` | **全局共享**牌堆 |
| **`chain`** | `[]` | 连锁栈，元素 `ChainItem` |
| **`chain_waiting`** | `False` | 是否有待响应窗口 |
| **`chain_timer`** | `-1` | **代际令牌**（非时间戳） |
| **`chain_window`** | `None` | 当前窗口归属 player_id |
| **`chain_passes`** | `0` | 连续放弃次数，≥2 结算 |
| `effects` | `[]` | `Effect` 列表（半死，见 2.5） |
| `last_attack` | `None` | 最后攻击快照，供溅射/雷达/越战越勇读 |
| `game_logs` | `[]` | |
| `rps_processed` | `False` | |
| `skip_opponent_turn` | `None` | 神之宣告用；存 **player_id** |
| `skip_next_turn` | `None` | Freezing！用；存 **player_id** |
| `disconnected` | `{}` | pid → `{'deadline','token'}` |
| `disconnect_seq` | `0` | 掉线计时器代际令牌 |
| `reconnect_tokens` | `{}` | pid → 一次性 token |
| `game_over_reason` | `None` | `None` \| `'opponent_disconnected'` |

**动态追加的 room 属性**（`__init__` 之外）：
- `is_ai_room = True`（428，仅 `create_ai_room` 路径；其他路径**不存在**，故代码统一用 `getattr(room, 'is_ai_room', False)`）
- `polar_reversal_applied`（724、827 初始 `False`；3670 置 `True`）
- `lingqi_resurgence_applied`（3285 置 `True`；1403/1410 读+清）

**方法**：
| 方法 | 行号 | 职责 |
|---|---|---|
| `init_player_magic(player_id, magic_cards)` | 270–279 | 清空该玩家手牌；**仅当 `magic_deck` 为空时**才 `copy + shuffle` 建全局牌堆 |
| `pop_effect(name)` | 280–283 | 从 `effects` 移除同名 Effect（边遍历边 `remove`） |
| `apply_effect(end_phase)` | 284–288 | 按 `end_phase` 弹出效果（**无调用点，死代码**） |
| `draw_card(player_id)` | 289–318 | `no_draw` 拦截 → 牌堆空返回 None → `pop(0)` → **重复卡检查**（非"失灵！"且同名同速则弃牌返回 None）→ 入手 → `emit('hand_updated', room=player.sid)` |
| `discard_card(player_id, card)` | 320–324 | 追加到全局弃牌堆 + 从手牌 `index/pop`（**手牌无此卡时 `ValueError`**） |
| `attack(target, attacker_id, enable_effects)` | 326–394 | **旧版内联攻击，已被 `handle_attack` 取代**；会调 `effects` 钩子、更新 `remaining_ships`、`game_over`+`db.record_match` |

**`attack()` 与 `handle_attack` 的关键差异（重复实现）**：
- `GameRoom.attack` 第 352 行 `self.players[attacker_id].remaining_ships -= attack.hit` —— **扣的是攻击者自己的船数**！这明显是 bug（应为 `defender_id`），但因为它**没有被生产路径调用**，所以未暴露。可反证 `attack()` 是废弃原型。

### 2.8 `RoomManager`（405–580）

**字段（406–414）**：`rooms: dict[str, GameRoom]`、`match_queue: [[sids],[names],[user_ids]]`、`lobby_queue = []`、`lobby_members = set()`

**方法**：
| 方法 | 行号 | 职责 |
|---|---|---|
| `create_room(room_id=None)` | 417–422 | uuid4 前 6 位建普通房 |
| `create_ai_room(player_id, name, user_id)` | 424–433 | 建房 + `is_ai_room=True` + 预置 `ai-<room_id>` 的 Player + `init_player_magic` |
| `join_room(room_id, player_id, name, sid)` | 435–452 | ≥2 人拒绝；`user_id=player_id`（**注意：key 即 user_id/sid**） |
| `get_room` / `delete_room` / `get_all_rooms` | 454–467 | |
| `add_to_match_queue` | 470–477 | 只写 `[0]` 和 `[1]`，**不写 `[2]`** |
| `remove_from_match_queue` | 479–488 | 三列都删 |
| `has_player_in_match_queue` | 490–492 | |
| `get_match_queue_size` | 494–496 | |
| `process_match_queue(magic_cards)` | 498–558 | **全文件无调用点 → 死代码** |
| `add/remove/get_lobby_member(s)` | 561–577 | **无调用点 → 死代码**（`lobby_queue` 亦无引用） |

### 2.9 `GameLog`（33–46）
字段：`ts`（`int(time.time())`）、`type`、`text`、`detail`。方法：`to_dict()`。

### 2.10 `RPSResult`（1483–1500）
字段：`status`、`message`、`winner`、`loser`、`choices`、`order`。方法：`to_dict()`。

### 2.11 `ChainItem`（1503–1518）
字段：`player_id`、`card`、`targets`、`timestamp`、**`negated = False`**。方法：`to_dict()`。

### 2.12 `AttackResult`（1521–1542）
字段：`attacker`、`x`、`y`、`hit`、`ship_sunk`、`remaining_attacks`、`attacker_remaining_ships`、`defender_remaining_ships`。方法：`to_dict()`。

### 2.13 `ChainResult`（1545–1564）
字段：`card`、`caster`、`success`、`message`。
方法：`__getitem__` / `__setitem__`（用 `getattr`/`setattr` 模拟 dict 访问——所以代码里 `result['message'] = ...` 和 `result.message = ...` **两种写法混用**，如 3636 vs 3602）、`to_dict()`。

**动态追加字段**（`__setitem__` 写上去的，不在 `__init__` 里）：
`temp_data_id`、`cards`、`max_ships`、`affected_positions`、`caster_id`、**`negate_target`**（4735 读）、**`negated`**（4639 写，但**全文件无人读**）、**`negated_skip`**（2716 写，但**全文件无人读**）。

### 2.14 `EffectResult`
**不存在。** `docs/CHAIN_ENGINE_SPEC.md` 第 57 行规划了 `EffectResult`，实际用的是 `ChainResult` 兼任。

---

## 3. 所有 `@socketio.on` 事件（精确事件名 + 行号）

**共 33 个 handler**，按行号排列。事件名**逐字符抄自源码**：

| # | 事件名（精确） | 行号 | handler 函数 | 作用 + 关键校验 |
|---|---|---|---|---|
| 1 | `test_add_all_magic_cards` | 635 | `test_add_all_magic_cards` | 手牌 = 全部卡。**仅校验 `player_id in room.players`，无身份校验** |
| 2 | `test_set_player_ships` | 656 | `test_set_player_ships` | 按 `[3,2,2,1,1,1][:n]` 随机摆船。**无身份校验** |
| 3 | `test_clear_all_effects` | 713 | `test_clear_all_effects` | 清 `game_effects`/`field_magic`/`EffectFlags`/船状态。**无身份校验** |
| 4 | `test_add_specific_magic_card` | 747 | `test_add_specific_magic_card` | 按名加一张。**无身份校验** |
| 5 | `test_get_game_state` | 774 | `test_get_game_state` | 返回状态+双方**完整船位**（含 hits）。**无身份校验 → 信息泄露** |
| 6 | `test_reset_game` | 812 | `test_reset_game` | 重置房间+玩家+连锁（830–833）。**无身份校验** |
| 7 | `create_ai_room` | 856 | `handle_create_ai_room` | `player_id = request.sid`；`join_room(room_id)` **未带 sid 参数** |
| 8 | `test_set_opponent_ships` | 877 | `test_set_opponent_ships` | 改**对手**船。**无身份校验** |
| 9 | `test_end_turn` | 934 | `test_end_turn` | 强制推阶段。**无身份校验** |
| 10 | `test_win_game` | 957 | `test_win_game` | 直接判胜。**无身份校验** |
| 11 | `test_lose_game` | 974 | `test_lose_game` | 直接判负。**无身份校验** |
| 12 | `test_get_magic_cards_list` | 992 | `test_get_magic_cards_list` | 返回全卡表 |
| 13 | `test_auto_attack` | 1007 | `test_auto_attack` | 自动随机攻击 N 次。**无身份校验** |
| 14 | `create_room` | 1090 | `handle_create_room` | `player_id = session.get('user_id', request.sid)`；`join_room(room_id, request.sid)` |
| 15 | `join_room` | 1110 | `handle_join_room` | 同 key 约定；**≥2 人拒绝**；满 2 人 → `state='placing_ships'` + `init_player_magic` ×2 + 逐个 `emit('game_state')` |
| 16 | `connect` | 1170 | `handle_connect` | `online_users.add(sid)`；**扫描全房间找 `p.user_id == session user_id and p.sid != sid`，恰好 1 个时推 `resume_game` + 预发 `reconnect_token`** |
| 17 | `disconnect` | 1208 | `handle_disconnect` | 移除 `online_users`、清匹配队列；遍历房间找 `p.sid == sid` → `start_background_task(_start_disconnect_grace, ...)` 后 **`return`** |
| 18 | `chat_message` | 1230 | `handle_chat_message` | `msg[:100]`；按 `room.players[pid].name == username` 判 `isMe`（**同名会误判**）；无 room 回退单播 |
| 19 | `find_match` | 1256 | `handle_find_match` | 队列以 **`request.sid`** 为 key；同 user_id 两人则都退回队尾；建房后 `join_room(room_id, player1/2)` + `state='placing_ships'` |
| 20 | `cancel_match` | 1347 | `handle_cancel_match` | 按 `request.sid` 出队，兜底按 `user_id` 列 |
| 21 | `place_ships` | 1374 | `handle_place_ships` | **`_identity_ok`**；设 `ships`；**AI 房为 AI 自动摆船**（1386–1389）；`remaining_ships = len(ships)`；双方都摆完 → `rock_paper_scissors` |
| 22 | `rps_choice` | 1417 | `handle_rps_choice` | **`_identity_ok`**；**AI 房自动出拳**（1428–1431）；`rps_processed` 防重入；`determine_rps_winner` → `attack_order`；先手抽 1、后手抽 2；`_maybe_run_ai_turn` |
| 23 | `select_magic_target` | 1602 | `handle_magic_target` | **`_identity_ok`**；处理 `taoyuan_choice`/`bury_choice`/`shield_choice`；默认 `return {'status':'success'}` |
| 24 | **`attack`** | 1696 | `handle_attack` | 见 §4 |
| 25 | `enter_battle_phase` | 2042 | `enter_battle_phase` | `_identity_ok` + `_frozen_reason`；须 `current_attacker == player_id and current_phase == 'preparation'` |
| 26 | `enter_end_phase` | 2085 | `handle_enter_end_phase` | `_identity_ok`；须 `phase == 'battle'`；**`attacks_remaining > 0` 拒绝**；清 `battle_spirit` |
| 27 | `end_turn` | 2138 | `end_turn` | 见下方说明 |
| 28 | `papal_attack` | 2414 | `handle_papal_attack` | 见 §4 附注 |
| 29 | `use_magic_card` | 2545 | `handle_use_magic_card` | 见 §5 前置 |
| 30 | `get_reconnect_token` | 2886 | `handle_get_reconnect_token` | `_identity_ok` → 发 token |
| 31 | `rejoin_room` | 2895 | `handle_rejoin_room` | token 或 `session user_id` 任一通过；重绑 sid、`join_room`、下发 `room_sync` |
| 32 | `confirm_shenji_declare` | 2950 | `handle_confirm_shenji_declare` | `_identity_ok` + `pending_shenji.caster == pid`；`x` 夹取 `[0,6]` |
| 33 | **`chain_response`** | 2987 | `chain_response` | 见 §6 |
| 34 | `remove_field_magic` | 3052 | `handle_remove_field_magic` | `_identity_ok`；场地卡进弃牌堆、`field_magic=None`、广播 |
| 35 | `confirm_reinforcement_position` | 3074 | `handle_confirm_reinforcement` | `_identity_ok` + `pending_placement.caster == pid`；`_placement_error`；复数放置循环 |
| 36 | `cancel_placement` | 3136 | `handle_cancel_placement` | 放弃剩余放置 |
| 37 | `request_revealed_positions` | 3154 | `handle_request_revealed_positions` | 单播己方 `revealed_positions` |
| 38 | `get_magic_temp_data` | 3167 | `get_magic_temp_data` | 原样返回 `room.magic_temp_data` |
| 39 | `confirm_magic_target` | 3177 | `confirm_magic_target` | `taoyuan_choice`（剩余卡**放回牌堆**而非弃牌堆，与 `select_magic_target` 的 1633 行**行为不一致**）/ `lingqi_choice`（重置棋盘、`max_ships=target_ships`、`state='placing_ships'`） |
| 40 | `get_discard_pile` | 3304 | `get_discard_pile` | 返回去重后的全局弃牌堆（`失灵！` 不去重） |
| 41 | `surrender` | 4690 | `handle_surrender` | **无 `_identity_ok`**！用 `session.get('user_id', request.sid)`；判对手胜；**无 `game_over_reason`** |

> 注：`test_get_game_state`（#5）和 `test_set_opponent_ships`（#8）**完全没有身份校验**，任何人知道 `room_id` 即可读对手完整布阵/改对手船数——**生产环境高危**。

---

## 4. `handle_attack`（1696–2039）完整逻辑拆解

### 4.1 取参与房间校验（1698–1708）
```
room_id/attacker_id/target_x/target_y ← data（无 .get，缺键 KeyError）
room = room_manager.get_room(room_id)
if not room or attacker_id not in room.players or not _identity_ok(room, attacker_id): 拒绝
frz = _frozen_reason(room, attacker_id)  → 对手掉线宽限期内拒绝
```

### 4.2 阶段与身份校验（1710–1720）
1. `attacker_id != room.current_attacker` → "还没到你的攻击回合"
2. `room.current_phase != 'battle'` → "当前不是战斗阶段"
3. 同格重复攻击（遍历 `player.attacks` 比 `x/y`）→ "你已经攻击过这个位置了"
4. `_cell_in_shenwei_hole(room, defender_id, x, y)` → "该区域已被神威！扣掉，无法攻击"

### 4.3 命中判定（1730–1963）
遍历 `defender_ships`，`{'x','y'} in ship.positions` → `hit = True`，**然后 `break`（在 1963，所有分支末尾）**。

命中后先处理无暇圣心标记（1738–1739）：
```python
if 'holy_heart' in room.game_effects and not ship.invincible:
    room.game_effects['holy_heart']['no_damage'] = False
```

#### A. 强制击杀分支（`forced_kill > 0`，1742–1852）
- **无视无敌与盾牌**，直接 `ship_sunk = True`、`remaining_ships -= 1`
- 记录 `sunken_ships`、`last_ship_change`（含 `ship` 引用 + `hits_added`，供平等条约回滚）
- **恶魔契约**（1767–1780）：击沉方为 defender → **attacker 随机牺牲一艘**；按 `defender_id` 单播"恶魔契约生效，对方牺牲一艘战舰"（**文案与接收者对不上，见可疑点**）
- **无暇圣心中断**（1783–1789）：`del room.game_effects['holy_heart']` + `emit('holy_heart_interrupted')`
- **饮血**（1792–1794）：`draw_card(attacker_id)` + 单播
- **越战越勇**（1797–1799）：`attacks_remaining += 1` + 广播
- `damage_dealt_this_turn += 1`（1802）
- **绝处逢生**（1805–1825）：直接 `game_over` + 记战绩 + `game_over` 事件 + `return`
- **回光返照**（1828–1829）：`_check_last_chance(...)` → `return`
- **百亿补贴**（1839–1841，注意在 `if ship_sunk:` 内）：`attacks_remaining += 3`，单播给 `defender_id`
- **八方来财**（1844–1846）：`draw_card(defender_id)`，单播给 `defender_id`
- `forced_kill -= 1`（1849）；`<= 0` 时 **`del ... .effect_flags.forced_kill`**（1851–1852）——**删实例属性**，读时回落类默认 `0`

#### B. 普通分支（1853–1962）
1. `ship.invincible` → `ship_sunk = False`（只显形）
2. `elif ship.shield` → `ship_sunk = False`、`ship.shield = False`
3. `else`：
   - 记录 `hits`
   - **回光返照**（1867–1868）`_check_last_chance` → `return`
   - `len(hits) == len(positions)` → `ship_sunk = True`、`remaining_ships -= 1`、`sunken_ships`、`last_ship_change`
     - **百亿补贴**（1889–1891）
     - **恶魔契约**（1894–1906）
     - **八方来财**（1909–1911）
     - **无暇圣心中断**（1914–1920）
     - **饮血**（1923–1925）
     - **越战越勇**（1928–1930）
     - `damage_dealt_this_turn += 1`（1933）
   - **绝处逢生**（1936–1956）→ `return`
   - `emit('ships_updated')`（1959–1962）

### 4.4 收尾（1965–2039）
- `room.last_attack = {...}`（1966–1973）
- `attacks_remaining -= 1`、`max(0, ...)`（1976–1978）
- `player.attacks.append(Position(...))`（1981–1986）——注释称"修复重复攻击校验与 AI 追踪失效"
- `AttackResult` + `add_game_log` + `emit('attack_result')`（1989–2008）
- **game_over 判定**（2011–2028）：`defender.remaining_ships == 0` → `state='game_over'`、`winner=attacker_id`、记日志、`db.record_match`、`emit('game_over')`、`return`
- `attacks_remaining == 0` 时只发 `attacks_updated`，**不自动切换攻击者**（2032–2037）

### 4.5 `_check_last_chance`（1674–1693）
若 `game_effects['last_chance']['caster'] == defender_id` → 攻击者直接胜、记战绩、`game_over`、返回 True。**在强制击杀分支（1828）与普通分支（1867）各调一次**。

### 4.6 重复与可疑之处（重点）

| # | 位置 | 问题 |
|---|---|---|
| **R1** | 1744–1852 vs 1853–1962 | **两套几乎完全相同的击沉后处理**（恶魔契约/无暇圣心/饮血/越战越勇/绝处逢生/百亿补贴/八方来财），约 200 行重复。任一侧改动极易漏改另一侧 |
| **R2** | 1839–1841 vs 1889–1891 | 百亿补贴在**强制击杀分支**位于 `if ship_sunk:` 内，**普通分支**也有一份；但 `_do_attack`（2516–2519）里**同时给 attacker 和 defender 都 +3** —— 三处语义不一致 |
| **R3** | 1780 / 1906 | `emit('message', {...}, to=room.players[defender_id].sid)` —— 恶魔契约牺牲的是 **attacker** 的船，消息却发给 **defender**，文案还是"对方牺牲一艘战舰"。**收件人与文案都对不上**（对比 `_apply_ship_loss_linkage` 3417–3425，那里 `to=sacrifice_player.sid` 才是对的） |
| **R4** | 1851–1852 | `del ...forced_kill` 删实例属性；而 1742 行 `forced_kill > 0` 依赖类默认 `0`。功能可行但脆弱 |
| **R5** | 1855–1861 | `invincible` 分支**不增加 `hits`** → 无敌船永远打不死，且与"只显形"注释相符；但 `damage_dealt_this_turn` 也**不增加**，导致 `Freezing！`/`五险一金` 的"本回合未造成伤害"判定可能误判 |
| **R6** | 1963 `break` | `break` 在**内层 for 的末尾但位于 else 块之外**——只有"命中某艘船"才走到。未命中时循环自然结束，行为正确；但结构极易误读 |
| **R7** | 1734 | `{'x': target_x, 'y': target_y} in ship.positions` 依赖 `Position.__eq__` 的 dict 分支。而 `_do_attack`(2471)、`test_auto_attack`(1042) 用 `Position(...) in ship.positions`（Position 分支）。**两种写法混用** |
| **R8** | 1719 vs 1981 | 重复攻击校验读 `player.attacks`，本次攻击在**校验之后**才 append（1981）——顺序正确，但 `_do_attack`(2527) 与 `papal_attack` 循环 2 次会在**同一格**重复 append（`_do_attack` 无重复校验） |
| **R9** | 1772 / 1898 / 4420 | `random.choice(sacrifice_player.ships)` 后立即 `remove` —— 但 `ships` 含**已沉没但未移除**的船（`sunken_ships` 是另存的），所以可能"牺牲"一艘早就沉了的船 |
| **R10** | 2011 | `defender.remaining_ships == 0` 判负；但 `== 0` 在恶魔契约/神威等叠加路径下可能**降到负数**，`== 0` 会漏判（`_do_attack` 用 `<= 0`，`apply_magic_effect` 用 `<= 0`）。**三处判据不一致** |
| **R11** | 1715 | `current_phase != 'battle'` —— 但 `can_play_magic_card`（2630）允许 battle 阶段用速阶1/2，攻击与用卡共用 battle 阶段。**阶段语义耦合** |
| **R12** | 1966–1973 | `last_attack` 在**未命中**时也写入（`hit: False`），`溅射`(3689)/`雷达子弹`(3821) 各自再查 `.get('hit')`；`越战越勇`(3880) 查 `['ship_sunk']` 用**下标**（KeyError 风险） |

### 4.7 `_do_attack`（2464–2542）—— 第三套攻击实现
从 `handle_attack` "提取"，但**不是同一份逻辑**：
- 无 `forced_kill`、无 `越战越勇`、无 `八方来财`、无 `battle_spirit`
- `hits` 存 **dict**（2476）而非 `Position` —— 与 `handle_attack` 的 1747/1864 存储类型**不一致**
- 2516–2519：`subsidy` **同时给 attacker 和 defender +3**（与 §4.6 R2 冲突）
- 2496–2497 / 4397–4398 / 4436–4437：用 `list(room.players.keys())[0]` / `[1]` 取船数 —— **与 attacker/defender 无对应关系**，广播数值可能是**反的**
- **仅被 `papal_attack`（2454）调用**

---

## 5. `apply_magic_effect`（3510–4683）

### 5.1 签名与返回结构
```python
def apply_magic_effect(room: GameRoom, caster_id: str, card: MagicCard, target_data):
    result = ChainResult(card=card, caster=caster_id, success=True, message='')
```
- **返回**：`ChainResult`（成功默认 `True`），支持 `result.x` 与 `result['x']` 两种访问
- **入口即取对手**：`opponent_id = next(p for p in room.players if p != caster_id)`（3512）—— **单挑假设**，实测房间恒 2 人
- 3535 行 `print(...)` **调试残留**
- 唯一调用点：`resolve_chain`（2730）

### 5.2 完整卡名分支清单（精确卡名 + 行号）

**速阶1（3518 起）**
| 行号 | 卡名 |
|---|---|
| 3519 | `余音绕梁` |
| 3532 | `桃园结义` |
| 3561 | `无中生有` |
| 3570 | `极限增援` |
| 3584 | `无暇圣心` |
| 3599 | `火力全开` |
| 3608 | `灵气复苏` |
| 3632 | `教皇旨意` |
| 3638 | `败者食尘` |

**速阶2（3686 起）**
| 行号 | 卡名 |
|---|---|
| 3687 | `溅射` |
| 3819 | `雷达子弹` |
| 3878 | `越战越勇` |
| 3889 | `神威！` |
| 3952 | `冻结` |
| 3977 | `轰炸` |
| 4082 | `硫磺火焰` |
| 4206 | `探测雷达` |
| 4264 | `饮血` |
| 4270 | `克苏鲁之眼` |
| 4297 | `Freezing！` |
| 4314 | `五险一金` |
| 4328 | `明智埋葬` |
| 4345 | `仁王之盾` |

**速阶3（4361 起）**
| 行号 | 卡名 |
|---|---|
| 4362 | `八方来财` |
| 4368 | `平等条约` |
| 4403 | `百亿补贴` |
| 4409 | `神之宣告` |
| 4445 | `绝处逢生` |
| 4462 | `死者苏生` |
| 4478 | `疗愈` |
| 4495 | `盗亦有道` |
| 4509 | `回光返照` |
| 4536 | `加百列之光` |
| 4554 | `钢筋铁骨` |
| 4572 | `神机妙算` |

**场地（按 `card.type == '场地'` 兜底分支 4588）**
| 行号 | 卡名 | 说明 |
|---|---|---|
| 4588 | `(card.type == '场地')` | 统一 `_place_field_magic` |
| 4593 | `恶魔契约` | `game_effects['demon_contract'] = True` |
| 4596 | `禁忌果实` | 仅文案（实际拦截在 `can_play_magic_card` 2614） |
| 4598 | `伊甸园` | 仅文案 + 条件 `_recalc_attacker_attacks` |
| 4606 | `教皇旨意` | 仅文案（`papal_edict` 在 3635 另一分支设） |

**"已实现的魔法卡"兜底段（4609 起）**
| 行号 | 卡名 |
|---|---|
| 4610 | `失灵！` |
| 4644 | `看破！` |
| 4649 | `增援` |
| 4659 | `else` | `未实现的魔法卡: {name}` |

> **共 45 个具名分支**（含 `场地` 兜底与 `else`）。
> **注意分支顺序陷阱**：`教皇旨意` 在 3632（速阶1段）**已处理**，4588 的 `card.type == '场地'` 分支**永远不会**再命中它（数组是 `elif` 链）；同理场地卡若在前面被具名分支截获，就走不到 4588。

### 5.3 按机制分类

- **抽牌/手牌**：`桃园结义`、`无中生有`、`盗亦有道`、`明智埋葬`
- **船只数量操纵**：`灵气复苏`、`败者食尘`、`神之宣告`、`绝处逢生`、`死者苏生`、`疗愈`、`增援`、`钢筋铁骨`
- **棋盘区域伤害**：`神威！`、`冻结`、`轰炸`、`硫磺火焰`、`溅射`、`探测雷达`、`雷达子弹`、`克苏鲁之眼`
- **效果标记（EffectFlags）**：`余音绕梁`、`火力全开`、`八方来财`、`百亿补贴`、`饮血`、`越战越勇`、`绝处逢生`、`回光返照`
- **延迟结算（game_effects）**：`极限增援`、`无暇圣心`、`回光返照`
- **回合控制**：`Freezing！`、`神之宣告`
- **连锁/无效化**：`失灵！`、`看破！`、`加百列之光`、`平等条约`
- **场地**：`恶魔契约`、`禁忌果实`、`伊甸园`、`教皇旨意`
- **特殊交互**：`神机妙算`、`仁王之盾`

### 5.4 末尾兜底（4669–4683）
```python
if opponent and opponent.remaining_ships <= 0 and room.state != 'game_over':
    → game_over + 记战绩 + emit
```
用 **`<= 0`**（与 `handle_attack` 的 `== 0` 不一致，见 R10）。
**`败者食尘`（3684）与多个早退分支显式 `return result` 绕过此判断**——3682–3683 注释解释了原因。

---

## 6. 连锁系统

### 6.1 连锁栈数据结构

**栈**：`room.chain: list[ChainItem]`（`GameRoom.__init__` 253）
`ChainItem`（1503–1518）：`player_id`、`card`（MagicCard 实例）、`targets`、`timestamp`、**`negated: bool = False`**

**状态字段**（254–257）：
- `chain_waiting: bool` —— 是否有待响应窗口
- `chain_timer: int` —— **代际令牌**（每次开启窗口 +1，非时间戳）
- `chain_window: str | None` —— 当前窗口归属 player_id
- `chain_passes: int` —— 连续放弃次数，`>= 2` 结算

**关键常量**：`CHAIN_RESPONSE_SECONDS = 10`（2639）

### 6.2 响应窗口运作

**入栈**：`use_magic_card`（2590–2600）
1. 卡从手牌移除；**非场地卡**进 `magic_discard`（2583–2584）
2. `room.chain.append(ChainItem(...))`
3. `emit('magic_chain_updated', {'chain': room.chain})`
4. **`room.chain_passes = 0`** —— 新牌打出即清零
5. `_advance_chain_window(room, opponent_id)` —— **先给对方**

**窗口推进** `_advance_chain_window(room, player_id)`（2678–2699）：
```python
while True:
    if not player_id or player_id not in room.players:
        return resolve_chain(room)
    if _can_respond_chain(room, player_id):
        room.chain_window = player_id
        room.chain_waiting = True
        room.chain_timer += 1
        emit('chain_request', {card, speed3_cards, countdown:10}, to=player.sid)
        _schedule_chain_timeout(room.id, room.chain_timer)
        return
    # 无法响应：自动视为放弃
    room.chain_passes += 1
    if room.chain_passes >= 2:
        return resolve_chain(room)
    player_id = _opponent_of(room, player_id)
```

**谁可响应** `_can_respond_chain`（2657–2664）：
- `player_id.startswith('ai-')` → **False（AI 永不参与连锁）**
- `player.magic_blocked` → False（被看破者）
- 手牌中无速阶3 → False

**自连锁**：`chain_response` 打出牌后（3039–3040）`chain_passes = 0` 且窗口交给**对方**；对方无法响应时循环里自动 `passes += 1` 并 `player_id = _opponent_of(...)` 回到自己 → **支持自连锁**，与 SPEC §1.1/§6 一致。

**放弃**（3042–3049）：`chain_passes += 1`；`>= 2` → `resolve_chain`；否则窗口给对方。

**超时** `_schedule_chain_timeout`（2757–2772）：
```python
def _timeout():
    time.sleep(10)
    room = room_manager.get_room(room_id)
    if room and room.chain_waiting and room.chain_timer == token:   # 代际校验
        window_player = room.chain_window
        room.chain_waiting = False; room.chain_window = None
        room.chain_passes += 1
        if room.chain_passes >= 2 or window_player is None:
            resolve_chain(room)
        else:
            _advance_chain_window(room, _opponent_of(room, window_player))
socketio.start_background_task(_timeout)
```
**代际令牌**保证旧定时器作废，避免竞态双重结算。

### 6.3 结算 `resolve_chain`（2702–2754）

```python
while room.chain:
    chain_item = room.chain.pop()        # 栈顶先出（LIFO）
    if chain_item.negated:
        result = ChainResult(..., success=False, message=f'{card.name}被无效化')
        result.negated_skip = True       # ← 无人读
        log_magic(room, player_id, card, '但被无效化')
        if getattr(card, 'type', None) == '场地':   # 贴了再拆
            _place_field_magic(room, player_id, card)
            if room.field_magic is card:
                room.magic_discard.append(card); room.field_magic = None
                emit('field_magic_updated', {...None}, room=room.id)
        results.append(result); continue

    result = apply_magic_effect(room, player_id, card, targets)
    result.caster = player_id
    log_magic(room, player_id, card, result.message if result.success else '')

    if getattr(result, 'negate_target', False) and room.chain:
        room.chain[-1].negated = True     # ← 给"正下方那一项"打标记

    results.append(result)
    if result.success:
        room.magic_history.append({'card': card, 'caster': player_id, 'timestamp': time.time()})

emit('chain_resolved', {'results': results}, room=room.id)
room.chain = []; room.chain_waiting = False; room.chain_window = None; room.chain_passes = 0
```

**与 SPEC 的偏差（重要）**：
- SPEC §1.2 说 `negated == True` 时"**不进历史、不改场地**"；实现在 `negated` 分支里**对场地卡执行了"贴了再拆"**（2719–2725 改场地）——这是**有意为之**的实现选择（注释"避免凭空消失"），但与 SPEC 文字**不一致**。
- SPEC 说 `negated` 项"跳过其效果"——实现确实跳过 `apply_magic_effect`。

### 6.4 无效化（negated）如何实现

**标记链路**：`apply_magic_effect` 里设 `result.negate_target = True`（4540 加百列 / 4627 失灵）→ `resolve_chain` 2735–2736 把 `room.chain[-1].negated = True` → 后续出栈时 2713 命中跳过。

**`_chain_target_below(room, caster_id)`（2667–2675）** —— **定义了但全文件无调用点（死代码）**：
```python
target = room.chain[-1]
if target.player_id == caster_id: return None
return target
```
实际逻辑在 `resolve_chain` 里**内联重写**（2735 行直接 `room.chain[-1]`，**未做"是自己牌则跳过"的判断**）。这是 SPEC 想抽出的 `negation.py` 规则的残留。

### 6.5 四张关键牌的结算逻辑

#### `失灵！`（4610–4642）
1. **有连锁栈时**（4612–4629）：
   - `target = room.chain[-1]`
   - `target.player_id == caster_id` → 失败"没有可无效化的魔法卡"
   - `target.card.name == '看破！'` → 失败"看破！优先于失灵！"
   - `target.card.name == '加百列之光'` → 失败"加百列之光免疫失灵！"
   - 否则 `result.negate_target = True`，`return result`（**提前返回，跳过末尾 4669 兜底**）
2. **无连锁栈时**（4630–4642，回退历史）：
   - `room.magic_history[-1]['caster'] != caster_id` 才处理
   - `看破！`/`加百列之光` → 失败"该魔法免疫失灵！"
   - 否则 `magic_history.pop()` + `result.negated = last_magic`（**`negated` 属性全文件无人读**）

#### `看破！`（4644–4647）
```python
room.players[opponent_id].magic_blocked = True
```
**无免疫检查**（SPEC §1.2 说"看破免疫失灵"——实现在**失灵侧**判断 4619–4622，而非看破侧）。重置点在 `end_turn` 2160–2162（**新大回合开始时**清双方 `magic_blocked`）。
拦截点：`use_magic_card` 2567、`chain_response` 3014、`_can_respond_chain` 2662。

#### `加百列之光`（4536–4552）
```python
negated_count = 0
if room.chain and room.chain[-1].player_id != caster_id:
    result.negate_target = True; negated_count += 1
elif not room.chain and room.magic_history and room.magic_history[-1]['caster'] != caster_id:
    room.magic_history.pop(); negated_count += 1
if room.field_magic:                     # 无条件拆场地！
    negated_count += 1; room.magic_discard.append(room.field_magic)
room.field_magic = None
```
**可疑点**：`if room.field_magic` **无归属判断** —— 会把**自己**的场地卡也拆掉并计入 `negated_count`。

#### `平等条约`（4368–4401）
**不受连锁框架约束**：不走 `negate_target`，而是直接读 `room.game_effects['last_ship_change']`（由攻击/神威等路径写入）并**回滚**：
- `pop('last_ship_change')`
- `affected_player.remaining_ships += count`
- `ship` 加回 `ships`、从 `sunken_ships` 移除
- **移除 `hits_added`**（4390–4393，注释："避免回滚后成为打不死的幽灵船"）
- 广播 `ships_updated`（**用 `list(room.players.keys())[0]/[1]`，与 R2/`_do_attack` 同样的索引错位问题**）

与 SPEC §1.2 的"目标同为栈中正下方项"**不符**——实现是"读 `last_ship_change` 快照回滚"，而非连锁标记。

### 6.6 是否已按 `docs/CHAIN_ENGINE_SPEC.md` 实现？

**结论：SPEC 已"部分实现"，但架构从未按 SPEC 落地。**

| SPEC 要求 | 实际状态 |
|---|---|
| 新建 `engine/` 目录（`chain.py`/`resolution.py`/`negation.py`） | **不存在**（已确认项目根目录无 `engine/`）。全部逻辑仍在 `server.py` |
| `ChainState(stack, window, passes)` 类 | **无此类**；用 `GameRoom` 的 4 个裸字段代替 |
| `EffectResult` 统一结果类型 | **无此类**；用 `ChainResult` 兼任 |
| `negation.py` 集中免疫规则表 | **未做**；免疫判断散落在 4619–4626（失灵分支内） |
| 响应窗口/放弃/自连锁/超时 | **已实现**（`_advance_chain_window`/`chain_response`/`_schedule_chain_timeout`），与 SPEC §1.1 **一致** |
| `negated` 标记 + 跳过结算 | **已实现**（2735–2736 / 2713） |
| 场地"贴了再拆" | **已实现**（2719–2725），但**连 `negated` 项也改场地**，与 SPEC §1.2 文字不符 |
| 失灵康"正下方一项" | **已实现**（4612–4629），SPEC §2 的"失灵康不到目标"病灶**已修复** |
| 失灵误伤旧牌 | `magic_history` 仍在累积，`[-1]` 仍可能是旧牌（仅无连锁栈的直调路径 4631 会走到） |
| 失效化 ≠ 阻止结算 | **已修复**（`negated` 真正跳过 `apply_magic_effect`） |

**因此：SPEC 的 P2（连锁状态机）与 P3（无效化）在 server.py 内以"就地实现"方式完成了功能，但 P1 清理与 SPEC §3 的架构重构（`engine/` 拆分）均未执行。**

---

## 7. 掉线重连机制

### 7.1 常量与字段
- `DISCONNECT_GRACE_SECONDS = 30`（2776）
- `room.disconnected: {pid: {'deadline': float, 'token': int}}`（265）
- `room.disconnect_seq: int`（266）
- `room.reconnect_tokens: {pid: str}`（267）—— `secrets.token_hex(16)`（2853）
- `room.game_over_reason`（268）

### 7.2 时序

**掉线** `handle_disconnect`（1208–1227）：
1. 移出 `online_users`、清匹配队列
2. 遍历所有房间找 `p.sid == sid` → `start_background_task(_start_disconnect_grace, room_id, player_id=pid)` → **`return`（只处理第一个匹配房间）**

**宽限启动** `_start_disconnect_grace`（2779–2796）：
- `time.sleep(0.2)` 让 disconnect 收尾（注释：避免在 disconnect 处理器内同步 emit 卡死 eventlet hub）
- 守卫：房间不存在 / `state == 'game_over'` / 已在 `disconnected` → 直接返回
- `disconnect_seq += 1`；`deadline = now + 30`
- **单播** `opponent_disconnected {player_id, seconds:30, deadline}` 给**对手**
- `start_background_task(_disconnect_timeout, room_id, player_id, token)`

**宽限期内封锁** `_frozen_reason`（2844–2849）：只要 `room.disconnected` 里存在**非自己**的 pid → 返回 `'对手已掉线，等待重连中'`。
调用点：`handle_attack`(1706)、`enter_battle_phase`(2050)、`end_turn`(2146)、`papal_attack`(2425)、`use_magic_card`(2555)。

**超时结算** `_disconnect_timeout`（2799–2836）：
```python
time.sleep(30)
entry = room.disconnected.get(player_id)
if not entry or entry.get('token') != token: return   # 已重连/已处理
room.disconnected.pop(player_id, None)
other = next((p for p in room.players if p != player_id), None)
ai_room = getattr(room, 'is_ai_room', False)
pre_battle = room.state in ('placing_ships', 'rock_paper_scissors')

if ai_room or pre_battle or other is None or other in room.disconnected or room.state == 'game_over':
    # 取消对局，不计战绩
    emit('game_canceled', {...}, room=room_id)
    room_manager.delete_room(room_id)      # 立即删
    return

# 正式对局：在场方判胜，计入战绩
room.state = 'game_over'; room.winner = other
room.game_over_reason = 'opponent_disconnected'
db.record_match(...)
emit('game_over', {'winner': other, 'reason': 'opponent_disconnected'}, room=room_id)
socketio.start_background_task(_cleanup_ended_room, room_id, 120)   # 保留 2 分钟
```

**重连** `handle_rejoin_room`（2895–2932）：
1. 校验：`room.reconnect_tokens[pid] == token` **或** `session['user_id'] == pid`（二者任一）
2. `state == 'game_over'`：
   - `game_over_reason == 'opponent_disconnected' and winner != pid` → 单播 `reconnect_warning` + 3 秒后清房
   - 否则单播 `error {'对局已结束'}`
   - **返回 `success`**
3. 否则重绑：`room.players[pid].sid = request.sid`、`join_room(room_id, request.sid)`
4. `was_reconnect = pid in room.disconnected` → `pop`
5. 单播 `opponent_reconnected` 给对手
6. **仅当 `was_reconnect`** 才发 `room_sync`（`_build_room_sync`）

**主动恢复** `handle_connect`（1170–1206）：扫描全房间，条件 `p.user_id == server_pid and p.sid != sid`，**恰好 1 个候选**时推 `resume_game` + 预发 `reconnect_token`。

**token 获取** `handle_get_reconnect_token`（2886–2892）：`_identity_ok` 通过则 `_issue_reconnect_token`。

### 7.3 快照 `_build_room_sync`（2858–2883）
下发字段：`room_id`、`state`、`current_phase`、`current_attacker`、`attacks_remaining`、`round`、`attack_order`、`player_id`、`player_name`、`opponent_name`、`is_ai_room`、`winner`、`game_over_reason`、`field_magic`（名或空串）、`remaining_ships`、`ships`（位置）、`hand`、`attacks`、`opponent_remaining_ships`、`shenwei_holes`。

**缺口**：**不含** `chain` / `chain_waiting` / `chain_window` / `magic_temp_data` / `game_effects` / `revealed_positions` / `magic_discard`。重连时若正处于连锁窗口，客户端会**丢失连锁上下文**；`pending_placement`（复活/增援中途）也会丢——**重连即卡死在该交互**。

---

## 8. 人机对战 AI

**入口**：`create_ai_room`（856–874）
- `player_id = request.sid`（**注意：没用 `session['user_id']`，与其他 handler 的 key 约定不同**）
- `room_manager.create_ai_room(...)`（424–433）：`is_ai_room = True`、预置 `ai-<room_id>` 的 Player、`init_player_magic`
- `join_room(room_id)` —— **未传 sid 参数**（Flask-SocketIO 在请求上下文内会隐式用当前 sid，能工作，但与 #14/#15 的显式写法不一致）

**AI 识别 `_ai_player_id`（2345–2350）**：`pid.startswith('ai-')`。**注意**：`_can_respond_chain`（2659）用同样前缀判断 AI 是否可响应连锁。

**AI 布船 `_ai_place_ships`（2353–2366）**：
- `player.ships = []`、`remaining_ships = 0`
- `max_ships = int(getattr(player, 'max_ships', 6) or 6)`（默认 6，兼容灵气复苏/败者食尘后的动态值）
- **36 格 `shuffle` 后取前 `max_ships`** → **全 1 格船**（`PlayerShip(positions=[Position(x,y)], hits=[])`）
- **与人类规则"完全一致"仅在人机房**：`handle_place_ships`（1383）直接接受客户端 `ships`，**服务端不校验人类船只形状**

**触发点**：
- `place_ships` 1386–1389：人类摆完 → `if ai_id and player_id != ai_id and not room.players[ai_id].ships: _ai_place_ships(...)`
- `rps_choice` 1428–1431：`if ai_id and ai_id not in room.rps_choices: room.rps_choices[ai_id] = random.choice([...])`
- `rps_choice` 1469 / `end_turn` 2332：`_maybe_run_ai_turn(room)`

**`_maybe_run_ai_turn`（2369–2376）**：非 AI 房 / `game_over` / 非 AI 回合 → 返回；否则 `start_background_task(_ai_turn_loop, room.id)`

**`_ai_turn_loop`（2379–2410）**：
```python
time.sleep(1)
if not room or game_over: return
if not ai_id or room.current_attacker != ai_id: return
enter_battle_phase({'room_id':..., 'player_id': ai_id})
for _ in range(40):                       # 硬上限 40
    if game_over or current_attacker != ai_id: return
    if room.attacks_remaining <= 0: break
    attacked = {(a.x, a.y) for a in room.players[ai_id].attacks}
    candidates = [(x,y) in 6x6 if not in attacked]
    if not candidates: break
    x, y = random.choice(candidates)      # ← 纯随机，无任何策略
    handle_attack({'room_id':..., 'player_id': ai_id, 'x': x, 'y': y})
    time.sleep(0.3)
if game_over or current_attacker != ai_id: return
handle_enter_end_phase({...})
time.sleep(0.5)
end_turn({...})
except Exception as e: print(f'AI turn error: {e}')
```

**可疑点**：
- AI 直接**以 `ai_id` 调用 `handle_attack`**；`handle_attack` 内的 `_identity_ok(room, ai_id)` 在**后台任务无请求上下文**时走 `server_pid is None and sid is None` 分支（608–609）→ 只校验成员资格 → **通过**。这条兜底正是 AI 能在后台驱动的原因，同时也是**测试/后台路径绕过连接鉴权**的通用后门。
- **AI 永不参与连锁**（2659），所以 AI 手里的速阶3 卡在响应窗口会被无限"自动放弃"——`_advance_chain_window` 的 while 循环会顺延给对方。
- 攻击纯随机、不利用 `revealed_positions`，**无难度分级**。
- `random.choice(candidates)` 用全局 `random`；但 `_ai_place_ships` 里 `import random as _rnd`（2356）**局部重复导入**（同模块，纯噪声）。

---

## 9. 身份鉴权

### 9.1 `_identity_check`（583–594）
```python
def _identity_check(room, claimed_player_id, server_pid, sid):
    if not room or claimed_player_id not in room.players:
        return False
    if server_pid and claimed_player_id == server_pid:
        return True
    return room.players[claimed_player_id].sid == sid
```
**两套 key 约定**（docstring 584–589 明确说明）：
1. **自定义房 / 人机房**（走 `join_room`）：`room.players` 的 key = **登录用户的 session `user_id`**；游客则 = 入座时的 `sid`
2. **匹配房**（走 `find_match`）：key = **入匹配队列时的 socket sid**（无论是否登录；`user_id` 只存在 `Player.user_id` 字段里）

因此放行条件为"**满足任一**"：
- ① 声称的 `player_id == 会话 user_id`（登录态；**容忍重连后 sid 变化**）
- ② `room.players[claimed_player_id].sid == 当前 sid`（key=sid 的流程，以及登录用户同连接场景）

### 9.2 `_identity_ok`（597–610）
```python
try: server_pid = session.get('user_id')
except RuntimeError: server_pid = None
try: sid = request.sid
except RuntimeError: sid = None
if server_pid is None and sid is None:
    return room is not None and claimed_player_id in room.players
return _identity_check(room, claimed_player_id, server_pid, sid)
```
**核心兜底（608–609）**：两个都取不到（后台任务/`start_background_task`/单测直调）→ **降级为仅成员校验**。

**使用者（15 个 handler）**：`place_ships`、`rps_choice`、`select_magic_target`、`attack`、`enter_battle_phase`、`enter_end_phase`、`end_turn`、`papal_attack`、`use_magic_card`、`get_reconnect_token`、`rejoin_room`、`confirm_shenji_declare`、`chain_response`、`remove_field_magic`、`confirm_reinforcement_position`、`cancel_placement`、`request_revealed_positions`、`get_magic_temp_data`、`confirm_magic_target`、`get_discard_pile`。

**未使用者（风险）**：
- **全部 12 个 `test_*` handler**（635–1085）
- **`surrender`（4690）** —— 用 `session.get('user_id', request.sid)` 直接当 `player_id`，**不校验 `Player.sid`**。匹配房（key=sid）里登录用户会因 key 不匹配而失败；游客从**另一个连接**发 `surrender` 也能成功
- **`create_room` / `join_room` / `find_match` / `chat_message`** —— 靠"自己构造 player_id"隐式保护

### 9.3 会话依赖
`session.get('user_id')` / `session.get('username')` 来自 `api.py` 的 Flask session（本文件未定义登录逻辑）。**游客模式**下 `session` 无 `user_id`，全部退化为 `request.sid`。

---

## 10. 可疑点 / 死代码 / 不一致（附行号）

### 10.1 SPEC §4 提到的僵尸代码——**逐项核实**

| SPEC §4 声称 | 实际状态 | 证据 |
|---|---|---|
| `room.pending_magic` 恒为 `None` | ✅ **已删除**。全文件 **0 处** `pending_magic` | grep `pending_magic` → 无匹配 |
| `counter_magic_response` 恒返回错误 | ✅ **已删除**。全文件 **0 处** | grep → 无匹配 |
| `room.last_magic`（只写不读） | ✅ **已删除**。全文件 **0 处** `room.last_magic` | 唯一 `last_magic` 是 **4632 行的局部变量**（`last_magic = room.magic_history[-1]`），在 4633/4638/4639 被**读**——那是正常局部变量，非僵尸字段 |

> **结论：SPEC §4 列出的三项僵尸代码均已清理干净（P1 已完成）。**

### 10.2 仍然存在的死代码

| 行号 | 对象 | 说明 |
|---|---|---|
| 280–283 / 284–288 | `GameRoom.pop_effect` / `apply_effect` | `apply_effect` **零调用**；`pop_effect` 仅被 3530（余音绕梁闭包，而该闭包自身不可达）调用 |
| 164–175 + 3531/3606 | `Effect` 类 + 2 处构造 | 唯一遍历点 `GameRoom.attack`(332–350) **不被生产代码调用** |
| 326–394 | `GameRoom.attack` | **旧版攻击实现**，已被 `handle_attack` 取代；内部 352 行 `attacker.remaining_ships -= attack.hit` 是错误逻辑（应为 defender），从未暴露 |
| 498–558 | `RoomManager.process_match_queue` | **零调用**（`handle_find_match` 自己内联了匹配逻辑 1275–1343） |
| 561–577 | `add/remove/get_lobby_member(s)` | **零调用** |
| 412 | `RoomManager.lobby_queue` | **零引用** |
| 2667–2675 | `_chain_target_below` | **零调用**；逻辑被 `resolve_chain` 2735 内联重写 |
| 2716 | `result.negated_skip = True` | **写了无人读** |
| 4639 | `result.negated = last_magic` | **写了无人读** |
| 221 | `magic_history` 类注解注释"无写入" | **注释过时**：2741 明确写入 |
| 3662–3663 / 847–848 | `player.opponent_attacks` | 只在 `hasattr` 保护下访问/清空，**从未被创建** |
| 98 / 4304 注释 | `Position.round` | **只赋 `None`，永不更新**（4304 注释自认） |
| 3535 | `print(f"Applying magic effect: ...")` | 调试残留，每次用卡都打 |
| 2356 | `import random as _rnd` | 局部重复导入 |

### 10.3 `magic_history` 的读写不对称（SPEC §2 部分残留）

- **写**：仅 2741（`resolve_chain` 中 `result.success` 时）
- **读**：4497/4503（盗亦有道）、4542/4543（加百列无栈回退）、4631–4639（失灵无栈回退）
- **SPEC §2 的"误伤旧牌"风险仍在**：`magic_history` 全场累积不清空，`[-1]` 可能是很早的牌。但由于**正常路径总有连锁栈**（`use_magic_card` 一律入栈 2591），4630 的"无栈回退"分支在真实对局中**几乎不可达**——只有 `apply_magic_effect` 被**直接调用**（测试路径）才走。

### 10.4 前后端/数据结构不一致

| 位置 | 不一致 |
|---|---|
| 2476 vs 1747/1864 | `_do_attack` 存 `hits` 为 **dict**；`handle_attack` 存 **Position** |
| 1633 vs 3225 | `select_magic_target` 的剩余牌进**弃牌堆**；`confirm_magic_target` 的剩余牌**放回牌堆** |
| 1888–1891 vs 2516–2519 | 百亿补贴：`handle_attack` 只给 defender +3；`_do_attack` 给**双方**都 +3 |
| 2011 vs 2536 vs 4670 | game_over 判据：`== 0` / `<= 0` / `<= 0` **三种混用** |
| 2496–2497 / 4397–4398 / 4436–4437 | 用 `list(room.players.keys())[0]/[1]` **冒充** player/opponent，广播数值可能颠倒 |
| 3035 vs 2591 | `chain_response` 与 `use_magic_card` 都 `append(ChainItem)`，但 `chain_response` **不校验 `card.type != '场地'`**（3033 无条件进弃牌堆；`use_magic_card` 2583 有判断） |
| 3074 事件名 vs 文档 | 事件名是 **`confirm_reinforcement_position`**（非 `confirm_reinforcement`）；handler 函数名才是 `handle_confirm_reinforcement` |
| 1660 | `handle_magic_target` 的 `shield_choice` 分支 `return` 在 1665，`room.magic_temp_data = {}` 在 1662 —— 顺序正确但 1665 的 `return {'status':'success'}` 使该分支**无 `message`** |

### 10.5 线程/并发隐患

| 行号 | 问题 |
|---|---|
| 17–21 | monkey_patch **位置过晚**（在 flask/flask_socketio/db/api 导入之后） |
| 24–30 | `emit()` 只捕 `RuntimeError`；`json.dumps` 在 `try` **之外**，序列化失败不被兜底 |
| 1223–1227 | `handle_disconnect` 找到**第一个**匹配房间就 `return`，**玩家同时在多房间时只处理一个** |
| 2782 | `_start_disconnect_grace` 用 `time.sleep(0.2)` 而非事件驱动；若 eventlet 未生效则阻塞线程 0.2s 可接受，但**依赖 monkey_patch** |
| 2757–2772 / 2799–2836 | 两个后台任务各 `time.sleep(10/30)` —— **强依赖 monkey_patch**，否则占满线程 |
| 2381–2408 | `_ai_turn_loop` 累积 `sleep(1 + 40×0.3 + 0.5) ≈ 13.5s` 单线程占用 |

### 10.6 安全/校验缺口（生产风险）

| 行号 | 问题 |
|---|---|
| 635–1085 | **12 个 `test_*` 事件无任何身份校验**，且都注册在生产 `socketio` 上。`test_get_game_state`(774) 泄露双方**完整船位+hit**；`test_set_opponent_ships`(877) 可**改对手船数**；`test_win_game`(957) 可**直接判胜**。**必须加环境开关或移除** |
| 4690 | `surrender` 无 `_identity_ok` |
| 856–874 | `create_ai_room` 用 `request.sid` 而非 `session['user_id']`，与 `create_room`/`join_room` 的 key 约定**不一致**，AI 房里登录用户的 `reconnect_token`/`rejoin_room` 路径会走不通 |
| 1256–1343 | `find_match` 中 `player1_user_id == player2_user_id` 判"自己匹配自己"——**两个游客的 `user_id` 都是 `None`** → 恒等 → **两个游客永远匹配不上**，会无限 `continue` 推回队尾（**潜在死循环**，虽然每轮都 pop 再 append，实际是"两个游客在队列里永远配不成"） |
| 1244 | `chat_message` 用**玩家名**判 `isMe`，**同名玩家会互串** |
| 3095–3112 | `confirm_reinforcement_position` 放置新船**不校验 `max_ships` 上限**（复活分支 `remaining_ships += 1` 无上限检查；`apply_magic_effect` 的 `疗愈`/`死者苏生` 有 `>= 6` 检查，但放置阶段本身没有） |
| 323 | `discard_card` 用 `.index(card)` —— 手牌无此卡时 **`ValueError`** 未捕获 |
| 147 | `MagicCard` 查表 `[0]` —— 卡名不存在时 **`IndexError`** |
| 1698–1701 / 2549 / 1592 | `data['...']` 直接下标 —— 缺键 **`KeyError`** 返回 500 而非结构化错误 |

### 10.7 逻辑正确性可疑点

| 行号 | 问题 |
|---|---|
| 2062–2071 (火力全开 double_attacks) | 用 `remaining_ships * 2` 覆盖 `attacks_remaining` —— **不是"翻倍当前次数"**，而是"按船数重算×2"，与卡面"本回合攻击次数翻倍"**语义不符**。且 `Effect` 钩子（3606）里的 `attacks_remaining *= 2` **永不触发**（钩子不可达） |
| 2450 / 2452 | `papal_attack` 固定循环 **2 次** `_do_attack`，但 `_do_attack` **不扣 `attacks_remaining`**（`papal` 路径下攻击次数本就是 0）——依赖 2434 的 `papal_edict` 检查 |
| 2442–2448 | `discard_card_index` 越界时**既不弃牌也不报错**，直接继续执行攻击（`discarded` 变量未初始化，但后续未使用 → 侥幸不 NameError） |
| 2614–2616 | `禁忌果实` 拦截在 `can_play_magic_card`，但 `chain_response`（2988–3049）**不调用 `can_play_magic_card`** → 连锁时能绕过禁忌果实限制 |
| 3035 | `chain_response` 打出的牌**不经 `can_play_magic_card`**，只校验"在手牌 + speed==3" → 绝处逢生期（2607）、禁忌果实期都能连锁 |
| 1719 | 重复攻击校验在**校验后**才 append，但 `溅射`/`雷达子弹`/`轰炸`/`硫磺火焰` 会**大量 append** `caster.attacks` → 之后普通攻击的可选格被**大幅压缩**（可能提前耗尽棋盘） |
| 3694 / 3826 | `溅射`/`雷达子弹` 读 `room.last_attack` 但**不检查 `round`** —— 上一回合的 `last_attack` 若未被清理仍可用（`last_attack` 仅在攻击时覆盖，`end_turn` **不重置**） |
| 3880 | 越战越勇用 `room.last_attack['ship_sunk']` **下标访问**，而 3689/3821 用 `.get()` |
| 4411–4443 | `神之宣告` 牺牲 2 艘，但 `effect_choice` 从 `magic_temp_data.get('effect_choice', 1)` 读——**没有任何 handler 写入过 `effect_choice`** → **恒走分支 1**，分支 2（跳过对方回合）**不可达** |
| 4453–4455 | `绝处逢生` `random.choice(caster.ships)` 后 `caster.ships = [remaining_ship]` —— 被丢弃的船**未进 `sunken_ships`**，也不减 `remaining_ships`（直接设为 1）→ 与 `钢筋铁骨`(4562)/`神之宣告`(4420) 的处理方式**不一致** |
| 4562 | `钢筋铁骨` 用 `caster.ships.pop()`（**列表末尾**），非随机 |
| 4598–4605 | `伊甸园` 分支仅在 `state == 'attacking' and current_phase == 'preparation'` 时重算攻击次数；但 2058–2059 的 `enter_battle_phase` 里 `6 - remaining_ships` **无 `max(0, ...)`**（`_recalc_attacker_attacks` 2980 有）→ 可能为负 |
| 2064 | `attacks_remaining = remaining_ships * 2` 同样**无 `max(0, ...)`**，且**不用 `_recalc_attacker_attacks`** |
| 2258–2272 | 神机妙算判定用 `len(player.sunken_ships) - saved['sunken']`；但复活路径（3100 `sunken_ships.pop()`）会**减少**该计数 → 与"预测减少船数"语义交织，**可能误判** |
| 2938 | `player.effect_flags = player.effect_flags` 自赋值空操作（同类噪声见 4215/4266/4405/4364/4603） |
| 4272–4273 | `克苏鲁之眼` 要求 `caster.ships and opponent.ships` 都非空 |
| 4495–4507 | `盗亦有道` 只 `append` 到 `caster.magic_hand`，**不从对方手牌/历史移除** → 卡牌**复制**而非转移（历史项仍在，可被反复盗取） |
| 4536–4550 | `加百列之光` 无条件拆**自己**的场地（无归属判断） |
| 2719–2725 | `negated` 的场地卡仍执行"贴了再拆" —— SPEC §1.2 说"不改场地"，实现**有意偏离**（需 SPEC 更新或代码修正） |
| 1688 / 2024 / 2831 / 3438 / 4678 / 4715 | `db.record_match` 的 `winner_user_id or attacker_id` —— 游客时把 **sid 当 user_id** 写库（注释称 `db.record_match` 会忽略不存在的用户，属**依赖下游容错**） |
| 2011 | `defender.remaining_ships == 0` 在 `remaining_ships` 变负时**误判**（见 R10） |
| 1450–1456 | `polar_reversal_applied` 分支设 `attacks_remaining = 0`，但 **`else` 分支同时写了 1455 和 1456**（先按船数算，再 `_recalc_attacker_attacks` 覆盖）→ 1455 是**冗余语句** |

---

## 11. 给后续开发者的行动建议（按优先级）

### P0 — 安全（必须立刻处理）
1. **`test_*` handler 全部加环境开关**（如 `if not app.config['TEST_MODE']: return error`），或移出生产 `socketio` 注册。当前任何人可判胜/读对手布阵/改对手船数。
2. `surrender`(4690) 补 `_identity_ok`。
3. `find_match`(1285) 修游客 `user_id=None` 恒等导致的**游客互配不上**问题。

### P1 — 一致性（机械化可做）
4. 统一 game_over 判据为 `<= 0`（2011、2536、4670）。
5. 统一百亿补贴语义（1839/1889/2516）。
6. 修 `_do_attack` 的 `list(room.players.keys())[0]/[1]` 索引错位（2496/4397/4436）。
7. 恶魔契约消息收件人（1780/1906 → 应为 `sacrifice_player.sid`）。
8. `chain_response` 补 `can_play_magic_card` 校验 + 场地卡进弃牌堆判断。
9. `加百列之光` 拆场地加归属判断。

### P2 — 架构（按 SPEC 执行）
10. **真正落地 `engine/`**：`chain.py`（`ChainState`）/ `resolution.py`（`apply_magic_effect` 迁入 + `EffectResult`）/ `negation.py`（失灵/看破/加百列/平等条约 免疫表）。
11. 删除 §10.2 全部死代码（`GameRoom.attack`、`process_match_queue`、lobby 方法、`_chain_target_below`、`apply_effect`、`Effect` 体系或将其接入真实路径）。
12. `_build_room_sync` 补 `chain`/`magic_temp_data`/`pending_placement`/`game_effects`，修重连丢上下文。
13. 把 `handle_attack` 的 200 行重复段抽成 `_resolve_sink(room, attacker_id, defender_id, ship, idx, forced)`。

### P3 — 可维护性
14. 移除所有 `x = x` 自赋值噪声（2938/4215/4266/4364/4405/4603）。
15. 移除 3535 的 `print`。
16. 补 `Position.__hash__` 或统一用 tuple（当前混用 dict/Position 比较）。
17. `magic_history` 加长度上限或按大回合清理。
18. 所有 `data['x']` 改 `data.get('x')` + 结构化错误返回。

---

## 附：文档事件名勘误表（供核对历史文档）

之前文档中出现过的事件名错误，以下是**源码中的准确拼写**：

| 易错写法 | ✅ 源码准确事件名 | 行号 |
|---|---|---|
| `confirm_reinforcement` | **`confirm_reinforcement_position`** | 3074 |
| `cancel_reinforcement` | **`cancel_placement`** | 3136 |
| `get_temp_data` | **`get_magic_temp_data`** | 3167 |
| `confirm_target` | **`confirm_magic_target`** | 3177 |
| `discard_pile` | **`get_discard_pile`** | 3304 |
| `magic_target` | **`select_magic_target`** | 1602 |
| `enter_battle` | **`enter_battle_phase`** | 2042 |
| `enter_end` | **`enter_end_phase`** | 2085 |
| `use_magic` | **`use_magic_card`** | 2545 |
| `create_ai` | **`create_ai_room`** | 856 |
| `reconnect_token` | **`get_reconnect_token`** | 2886 |
| `shenji_declare` | **`confirm_shenji_declare`** | 2950 |
| `revealed_positions` | **`request_revealed_positions`** | 3154 |

**共 41 个 `@socketio.on` 注册**（含 12 个 `test_*`）。
