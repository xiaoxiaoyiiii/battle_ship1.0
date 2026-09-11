# CLAUDE.md — 战舰棋 + 魔法卡

> 面向 AI 代理的项目索引。**先读这里，再按需读源码**——`server.py` 4733 行、`game.js` 5625 行，不要一次读完。
> 基于 commit `35a3131` 实测编写。最后更新：2026-09-11。

---

## 0. 项目速览

Flask + Flask-SocketIO 的实时双人海战棋，叠加 43 条魔法卡（41 唯一卡名）/ 场地魔法 / 连锁系统。含账号、战绩排行、人机对战、自定义房间、断线重连。

- **线上**：http://8.133.180.159:5000/
- **仓库**：`xiaoxiaoyiiii/battle_ship1.0`（GitHub）
- **生产运行**：eventlet

### 文件规模（换行符口径，以 read 工具为准）

| 文件 | 行数 | 说明 |
| --- | --- | --- |
| `server.py` | **4733** | 游戏核心：SocketIO、房间、状态机、魔法卡结算 |
| `static/game.js` | **5625** | 前端全部逻辑（巨型单文件，无模块化） |
| `static/style.css` | 1622 | 样式 + 深/浅色主题 |
| `templates/index.html` | 577 | SPA 模板 |
| `db.py` | 784 | SQLite DAO |
| `api.py` | 186 | Flask 路由 |
| `static/magic_card.json` | 84 | 后端卡牌数据 |
| `static/magic_cards.js` | 49 | 前端卡牌数据 |
| `file.py` | 3 | JSON 读取工具 |

> ⚠️ **行数统计口径**：用 `(Get-Content f -Raw)` 数换行符，**不要用** `Measure-Object -Line`（它漏空行，会少报）。

---

## 1. 运行与测试

```bash
pip install -r requirements.txt
python start_server.py        # 推荐（含依赖检查）
python -m pytest tests/ -q    # 141 passed
```

> ⚠️ **必须在项目根目录运行**——`server.py` 用相对路径 `./static/magic_card.json`；`tests/test_all_magic_cards.py:1088` 也用硬编码相对路径，是全套测试中唯一对 CWD 敏感的。

**实测基线（2026-09-11）**：`141 passed / 0 failed / 0.53s`，6 个测试文件。

---

## 2. 架构

```
浏览器 (index.html + game.js)
  │ Socket.IO                     │ HTTP fetch
  ▼                               ▼
server.py (41 个 socketio 事件)   api.py (Flask 路由)
  └──────────► db.py (SQLite) ◄───┘
        data/battleship.db (WAL)
```

`server.py` 通过 `from api import app` **复用** `api.py` 的 Flask 实例，再挂 `socketio = SocketIO(app, cors_allowed_origins="*")`。

### ⚠️ eventlet monkey_patch 时序问题

```python
11: import db                    # ← 这些在 monkey_patch 之前
12: from api import app          # ←
15: # eventlet 下必须先 monkey_patch...
17: try:
18:     import eventlet
19:     eventlet.monkey_patch()
20: except ImportError:
21:     pass
```

理想情况下 `monkey_patch()` 应是**最先执行**的语句。当前它排在 `db` / `api` / `file` 导入之后——若这些模块在导入期创建了线程或用了标准库 socket/time，patch 不会生效。**当前未观察到故障，但属隐患**。

---

## 3. 游戏流程

```
state:  waiting → placing_ships → rock_paper_scissors → attacking → game_over
phase:                                        preparation → battle → end
```

| 阶段 | 说明 |
| --- | --- |
| `placing_ships` | 各摆 **6 艘单格船** |
| `rock_paper_scissors` | 猜拳定先手；平局清空重来 |
| `preparation` | 可用**速阶 1** 卡、部分场地卡 |
| `battle` | 炮击；攻击次数 = 存活战舰数（受效果影响） |
| `end` | 攻击次数用尽后交出回合 |

**规则要点**：
- 攻击次数 = `存活船数 - 冻结船数`（`frozen_ship_count`）
- 先手抽 1 张，后手抽 2 张
- 胜利条件：击沉对方全部战舰

---

## 4. 核心数据结构（`server.py`）

| 类 | 行号 | 关键字段 |
| --- | --- | --- |
| `Position` | 84 | `x, y, hit, ship_sunk, is_sulfur, is_bomb, is_splash`。`__eq__` 支持与 dict 比较 |
| `PlayerShip` | 110 | `positions, hits, invincible, shield, frozen` |
| `MagicCard` | 134 | `name, speed, type, description`。只传 name 时自动从全局 `magic_cards` 查补 |
| `EffectFlags` | 153 | 玩家级标记：`treasure_hunter(八方来财), prediction(神机妙算), subsidy(百亿补贴), no_draw, forced_kill(int), vampire(饮血), last_stand(绝处逢生), double_attacks, battle_spirit(越战越勇)` |
| `Effect` | 164 | 房间级钩子：`name, phase(before_attack/after_attack), end_phase, priority, func` |
| `Player` | 178 | `name, user_id, sid, ships, attacks, remaining_ships, magic_hand, effect_flags, damage_dealt_this_turn, sunken_ships, revealed_positions, max_ships, magic_blocked` |
| `GameRoom` | 210 | 见下 |
| `RoomManager` | 405 | `rooms, match_queue`（三列平行数组 `[sids, names, user_ids]`） |
| `RPSResult` | 1483 | 猜拳结果 |
| `ChainItem` | 1503 | 连锁栈项，含 **`negated`** 标记 |
| `AttackResult` | 1521 | 攻击结果广播载体 |
| `ChainResult` | 1545 | 连锁结算结果 |

### `GameRoom` 关键字段

```python
# 基础
id, players: dict[str, Player], state, current_phase, round, winner
current_attacker, attacks_remaining, attack_order, rps_choices, rps_processed

# 魔法卡
field_magic           # ⚠️ 存【卡牌实例对象】，不是字符串！空为 None
magic_deck            # 全局共享牌堆（双方共用一副）
magic_discard         # 全局弃牌堆
magic_history         # 使用历史
magic_temp_data       # 临时目标数据

# 连锁
chain: list[ChainItem]
chain_window          # 当前响应窗口归属
chain_passes          # 连续放弃计数
chain_timer / chain_token

# 房间级效果
game_effects: dict    # 'demon_contract' / 'holy_heart' / 'last_chance'
                      # / 'last_ship_change' / 'excluded_ships' 等

# 掉线重连
disconnect_timers / grace_token ...

# 其他
game_logs, is_ai_room, shenwei_holes ...
```

### `GameRoom` 方法

| 方法 | 行号 | 说明 |
| --- | --- | --- |
| `init_player_magic` | 270 | 清空手牌；**仅当 `magic_deck` 为空时**初始化并洗牌 |
| `draw_card` | 289 | 受 `no_draw` 阻止；重名卡（**`失灵！` 例外**）丢弃牌堆 |
| `attack` | 326 | ⚠️ **旧版攻击实现，已被 `handle_attack` 取代**，属死代码 |

> ⚠️ **三套攻击实现并存**：`GameRoom.attack`(326，死代码) / `handle_attack`(1697，**实际生效**) / `_do_attack`(2464，教皇旨意等特定路径)。改动攻击逻辑前**务必确认改的是哪一个**。

---

## 5. Socket.IO 事件（41 个，精确名）

> ⚠️ **事件名易错**，以下为 grep 实测的精确字符串。常见误写：`use_magic`（实为 **`use_magic_card`**）、`end_turn_btn`（实为 **`end_turn`**）、`confirm_reinforcement`（实为 **`confirm_reinforcement_position`**）。

### 主流程（9）

| 行号 | 事件 |
| --- | --- |
| 1170 | `connect` |
| 1208 | `disconnect` |
| 1090 | `create_room` |
| 1110 | `join_room` |
| 856 | `create_ai_room` |
| 1256 | `find_match` |
| 1347 | `cancel_match` |
| 1374 | `place_ships` |
| 1417 | `rps_choice` |

### 对战（10）

| 行号 | 事件 |
| --- | --- |
| 1696 | `attack` |
| 2042 | `enter_battle_phase` |
| 2085 | `enter_end_phase` |
| 2138 | `end_turn` |
| 2414 | `papal_attack` |
| 3154 | `request_revealed_positions` |
| 3074 | `confirm_reinforcement_position` |
| 3136 | `cancel_placement` |
| 4690 | `surrender` |
| 1230 | `chat_message` |

### 魔法卡与连锁（9）

| 行号 | 事件 |
| --- | --- |
| **2545** | **`use_magic_card`**（出牌主入口） |
| 1602 | `select_magic_target` |
| 3177 | `confirm_magic_target` |
| 3167 | `get_magic_temp_data` |
| 3304 | `get_discard_pile` |
| 2987 | `chain_response` |
| 3052 | `remove_field_magic` |
| 2950 | `confirm_shenji_declare` |
| 2414 | `papal_attack` |

### 掉线重连（2）

| 行号 | 事件 |
| --- | --- |
| 2886 | `get_reconnect_token` |
| 2895 | `rejoin_room` |

### 🔴 调试事件（12）—— 全部无鉴权

| 行号 | 事件 | 危害 |
| --- | --- | --- |
| 957 | `test_win_game` | **直接判胜** |
| 974 | `test_lose_game` | 直接判负 |
| 635 | `test_add_all_magic_cards` | **白嫖全部卡** |
| 747 | `test_add_specific_magic_card` | 加指定卡 |
| 877 | `test_set_opponent_ships` | **改对手船数** |
| 656 | `test_set_player_ships` | 改己方船数 |
| 774 | `test_get_game_state` | **泄露双方完整船位** |
| 713 | `test_clear_all_effects` | 清效果 |
| 812 | `test_reset_game` | 重置对局 |
| 934 | `test_end_turn` | 强制结束回合 |
| 1007 | `test_auto_attack` | 自动攻击 |
| 992 | `test_get_magic_cards_list` | 列全部卡 |

> **已实测确认：12 个 handler 中含 `_identity_ok` 的 = 0 个**。对比之下正式 handler（如 `place_ships`/`attack`）都调用了鉴权。
> 且 `static/test_magic.js` 被 `index.html:492` **加载到生产页面**。**公网任何人开控制台即可作弊。**

### 服务端 → 客户端（主要）

`game_state`（总控）、`attack_result`、`ships_updated`、`hand_updated`、`game_over`、`field_magic_updated`、`holy_heart_interrupted`、`rps_result`、`match_queued`、`match_canceled`、`magic_chain_updated`、`chain_resolved`、`game_message`、`message`、`error`、`chat_message`

---

## 6. 身份鉴权（关键陷阱）

`room.players` 的 key 有**两套约定**：

| 场景 | key |
| --- | --- |
| 自定义房 / 人机房（`handle_join_room`） | 登录用户 = `session['user_id']`；游客 = 入座时的 `request.sid` |
| **匹配房**（`handle_find_match:1269`） | **一律是入队时的 socket sid**（登录与否都一样；真实 user_id 只存 `Player.user_id`） |

```python
_identity_check(room, claimed, server_pid, sid)   # 583
# ① claimed == session['user_id']（登录态，容忍重连换 sid）
# ② room.players[claimed].sid == sid（座位登记的连接 == 当前连接）

_identity_ok(room, claimed)                        # 597
# 无请求上下文时（单测直调）跳过连接校验，仅保留成员校验
```

> `_identity_ok` 的无上下文分支是**为测试留的口子**，不是漏洞——但 `test_*` 事件是**真的没调鉴权**。

### 目标选择链路

```
前端选择器 → confirmMagicTarget({target_area|target_line|ship_indices|...})
          → 归一化 payload（game.js:4380-4420 附近，兼容 5 种形态）
          → socket.emit('use_magic_card', {targets})
          → handle_use_magic_card (2545)
          → apply_magic_effect 读 target_data['target_area'/'target_line']
```

后端读取字段：`target_area` `{x1,y1,x2,y2}`（神威！/冻结/探测雷达）、`target_line` `{type:'row'|'col', index}`（**轰炸** 3977）。

> ⚠️ **废弃死代码**：`game.js:4499` 有 `socket.emit('line_attack')`，`gameState.selectedLine` 全文只被赋 `null`（从未赋真实值）→ `if` 恒假、emit 永不执行。**后端无 `line_attack` handler**。轰炸功能**正常**（走上面的 `use_magic_card` 链路）。同类废弃代码还有 `area_attack`（已在最新版移除）。
>
> **这类误判已发生两次**：曾有人据"`selectedArea` 是死代码"断言"范围攻击功能已坏"，实为误报。**判断功能是否正常必须追完整链路（前端 emit 名 ↔ 后端 `@socketio.on` 名），不能只看单点。**

---

## 7. 魔法卡

- **43 条 / 41 唯一卡名**（`失灵！` ×3，**故意**——`draw_card` 去重对其特例放行）
- 速阶：**1=13 / 2=15 / 3=15**；类型：普通 39 + **场地 4**（恶魔契约 / 禁忌果实 / 伊甸园 / 教皇旨意）
- **前后端数据实测零差异**（43/43 逐字段一致，含 description 与顺序）

核心分发函数：**`apply_magic_effect(room, caster_id, card, target_data)`**（**3510-4683，约 1173 行，45 个具名卡分支**）

场地魔法：`_place_field_magic`(621) 存入 `room.field_magic`（**实例对象**）；顶替旧卡时旧卡实例进弃牌堆。

---

## 8. 连锁与无效化引擎

**已实现**（不是设计稿）——但 `docs/CHAIN_ENGINE_SPEC.md` 与实现有出入。

| 组件 | 行号 | 说明 |
| --- | --- | --- |
| `_can_respond_chain` | 2657 | 能否响应 |
| `_advance_chain_window` | 2678 | 推进响应窗口 |
| `resolve_chain` | 2702 | 逐项出栈结算（**negated 项跳过效果**） |
| `_schedule_chain_timeout` | 2757 | 超时调度 |
| `chain_response` | 2987 | 玩家响应 handler |
| `_speed3_cards` | 2650 | 取速阶 3 手牌 |

**机制**：栈 = `room.chain: list[ChainItem]`，每项带 `negated` 标记；结算 LIFO（后发先至）；响应窗口 10 秒超时。

**⚠️ 与 SPEC 的两处偏差**（SPEC 未更新）：
1. SPEC 说 negated 项"不改场地"，实现里**仍执行"贴了再拆"**（2791 附近，注释说明是为"避免凭空消失"）—— 有意为之
2. `平等条约` **不走** `negate_target` 连锁标记，改为读 `game_effects['last_ship_change']` 快照回滚（4368-4401）

**⚠️ API 文档过时**：SPEC §4 声称的僵尸代码 `pending_magic` / `counter_magic_response` / `last_magic` **均已清理（0 处残留）**；§2 抱怨的"失灵康不到目标""无效化≠阻止结算"**均已修复**。**读 SPEC 前先读本节。**

---

## 9. 掉线重连

| 组件 | 行号 | 说明 |
| --- | --- | --- |
| `_start_disconnect_grace` | 2779 | 掉线宽限（**30 秒**） |
| `_disconnect_timeout` | 2799 | 超时判负/取消 |
| `_issue_reconnect_token` | 2852 | 发重连 token |
| `_build_room_sync` | 2858 | 重连快照 |
| `handle_rejoin_room` | 2896 | 重连恢复 |

> ⚠️ **`_build_room_sync` 快照缺口**：不含 `chain` / `magic_temp_data` / 放置流程状态 / `game_effects`。**若玩家在连锁窗口或复活放置中途掉线重连，客户端会缺上下文**。

**eventlet 注意**：`disconnect` handler 内**不能同步 emit**（会卡死 hub），代码中有多处相关注释。

---

## 10. 人机对战

| 组件 | 行号 |
| --- | --- |
| `_ai_player_id` | 2345 |
| `_ai_place_ships` | 2353 |
| `_maybe_run_ai_turn` | 2369 |
| `_ai_turn_loop` | 2379 |
| `handle_create_ai_room` | 857 |

AI 玩家 id = `'ai-' + room_id`；`room.is_ai_room = True`。真人摆完船后为 AI 自动布船；AI 在真人出拳后自动出拳。

---

## 11. 已知问题（均已实测）

### 🔴 P0

| # | 位置 | 问题 |
| --- | --- | --- |
| 1 | `server.py` 12 个 `test_*` | **全部无鉴权** + `index.html:492` 生产加载 `test_magic.js` → **公网可作弊** |
| 2 | `game.js:2194` | **`showDivineDecreeChoice` 被调用但全项目无定义** → 「神之宣告」抛 ReferenceError，`chain_resolved` handler 中断 |
| 3 | `game.js:4552` | **`#effect-indicators` 在 `index.html` 中不存在**（0 处） → 「百亿补贴」TypeError |
| 4 | `server.py:1285` | **游客之间永远匹配不上**：`player1_user_id == player2_user_id`，两个游客的 user_id **都是 `None`** → `None == None` 恒真 → 被当作"自己"无限放回队列 |

### 🟡 P1

| # | 位置 | 问题 |
| --- | --- | --- |
| 5 | `game.js:3323-3324` | `getRPSName` 映射互换：`paper→'剪刀'`、`scissors→'布'`（**显示错**，猜拳结果文案反了） |
| 6 | `server.py:4690` | `surrender` **无 `_identity_ok`**（仅检查 `player_id in room.players`） |

### 🟠 P2

| # | 位置 | 问题 |
| --- | --- | --- |
| 7 | `server.py:1744-1962` | `handle_attack` **两套近乎逐行重复的分支**（强制击杀 vs 普通，约 200 行），已产生语义漂移：恶魔契约消息收件人错（牺牲 attacker 的船却通知 defender）、百亿补贴三处给谁加次数不一致、game_over 判据 `==0` 与 `<=0` 混用 |
| 8 | 多处 | **大厅（Lobby）是空壳**：前端监听 8 个服务端从不 emit 的事件（`lobby_update`/`lobby_joined`/`lobby_left`/`match_found` 等），前端 emit 的 `join_lobby`/`leave_lobby` 后端无 handler |
| 9 | `game.js` | `gameState.chain` 前端**永不填充** → `updateChainUI()` 永远显示"当前连锁 (0)" |
| 10 | `game.js:2911` | `switchScreen` 的 screen 数组仅 8 项，**漏了 `matchSuccessScreen`** |

### 🟠 死代码

- `server.py:326` `GameRoom.attack`（旧版攻击）
- `server.py:498` `process_match_queue`、561-577 lobby 三方法
- `server.py:284` `apply_effect`
- **`Effect` 体系**：唯一遍历点在 `GameRoom.attack`（不可达）→ **`余音绕梁`/`火力全开` 的 Effect 钩子永不触发**
- `server.py:2667` `_chain_target_below`（零调用，逻辑被 `resolve_chain` 内联重写）
- `game.js:4499` `line_attack` emit 链

### 🟠 其他数据问题

- **`盗亦有道`（4495-4507）只 append 到己方手牌、不从对方移除** → 卡牌被复制，可反复盗取
- `加百列之光`（4536-4550）拆场地时**无归属判断**，会拆掉自己的场地
- `神之宣告` 的 `effect_choice` 从 `magic_temp_data` 读，但**无任何 handler 写入** → 分支 2（跳过对方回合）不可达
- 快照缺口见第 9 节

### 🟠 测试代码问题

- `test_magic_effects.py:38` `test_bomb_returns_affected_positions` **名不符实**，从不该字段断言 → 等价空测试
- `test_disconnect_and_eden_shenji.py:36` 赋值后立即被 39 行覆盖 → **无效赋值**
- `test_disconnect_and_eden_shenji.py:37` 等处 `[PlayerShip(...)] * 4` **列表乘法产生共享引用**（非 4 个独立对象）
- `test_all_magic_cards.py` 一致性测试**只比对 `(name,speed,type)`，漏 `description`**
- `test_auth_spoof.py` **完全没覆盖 12 个 `test_*` 事件**

---

## 12. 开发约定

1. **改魔法卡要同步 4 处**：`magic_card.json`、`magic_cards.js`、`apply_magic_effect` 分支、测试。前两者须逐字符一致（当前一致性测试不校验 `description`，需人工留意）
2. **`失灵！` 重复 3 份是故意的**，勿"修正"
3. **`field_magic` 存实例对象**，用 `field_magic_name(room)` 取值
4. **改攻击逻辑先确认三套实现改的是哪个**（见第 4 节）
5. **不要一次读完 `server.py`/`game.js`** —— 先 grep 定位再分段读
6. **重活交子智能体**（独立上下文，不撑爆主会话）
7. **修 bug 前必须实测复现** —— 本项目静态分析已出过多次误报（见第 6 节）
8. **文档与代码已脱节**：`CHAIN_ENGINE_SPEC.md`、`README.md`（称 121 个测试，实为 141）均有过时内容

---

## 13. 深度文档

| 文件 | 内容 |
| --- | --- |
| `docs/SERVER_PY_ANALYSIS.md` | server.py 4733 行全量分析（类/事件/攻击结算/魔法分发/连锁） |
| `docs/FRONTEND_TECH_ANALYSIS.md` | 前端 + 测试深度分析（827 行，58 个 socket.on、33 个 emit、函数索引、19 条 bug） |
| `docs/CHAIN_ENGINE_SPEC.md` | 连锁引擎设计稿（⚠️ 部分已过时，见第 8 节） |
| `README.md` | 面向用户的功能/玩法说明（⚠️ 测试数已过时） |
