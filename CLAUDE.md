# CLAUDE.md — 战舰棋 + 魔法卡

> 面向 AI 代理的项目索引。**先读这里，再按需读源码**——`server.py` 5757 行、`game.js` 5821 行，不要一次读完。
> 基于 commit `837ab0e` 实测编写。最后更新：2026-09-13（缺陷审计修复批，见 `docs/DEFECT_FIXES_2026_09_13.md`）。
>
> ⚠️ **行号会随每次提交漂移**（本次审计实测：全文件行号普遍偏移 +80~100）。
> 本文件里的行号仅供定位参考，**以 grep 结果为准**。

---

## 0. 项目速览

Flask + Flask-SocketIO 的实时双人海战棋，叠加 43 条魔法卡（41 唯一卡名）/ 场地魔法 / 连锁系统。含账号、战绩排行、人机对战、自定义房间、断线重连。

- **线上**：http://8.133.180.159:5000/
- **仓库**：`xiaoxiaoyiiii/battle_ship1.0`（GitHub）
- **生产运行**：eventlet

### 文件规模（换行符口径，以 read 工具为准）

| 文件 | 行数 | 说明 |
| --- | --- | --- |
| `server.py` | **5757** | 游戏核心：SocketIO、房间、状态机、魔法卡结算 |
| `static/game.js` | **5821** | 前端全部逻辑（巨型单文件，无模块化） |
| `static/style.css` | 2309 | 样式 + 深/浅色主题 + 第 22 节「紧凑（移动端自适应）布局」 |
| `templates/index.html` | 654 | SPA 模板 |
| `static/sfx.js` | 156 | 战斗音效：Web Audio 现场合成（无素材依赖） |
| `static/music_player.js` | 401 | 背景音乐：优先放 mp3，找不到时自动切**合成环境音** |
| `static/adaptive_layout.js` | 419 | 移动端自适应布局：按可用空间在「桌面浮窗」与「一屏网格」间切换 |
| `db.py` | 900 | SQLite DAO（含 `card_usage` 卡牌使用统计） |
| `api.py` | 274 | Flask 路由（13 个，含 `/api/card_usage`） |
| `static/magic_card.json` | 84 | 后端卡牌数据 |
| `static/magic_cards.js` | 49 | 前端卡牌数据 |
| `file.py` | 3 | JSON 读取工具 |

> ⚠️ **行数统计口径**：用 `(Get-Content f -Raw)` 数换行符，**不要用** `Measure-Object -Line`（它漏空行，会少报）。

---

## 1. 运行与测试

```bash
pip install -r requirements.txt
python start_server.py        # 推荐（含依赖检查）
python -m pytest tests/ -q    # 398 passed
```

> ⚠️ **必须在项目根目录运行**——`server.py` 用相对路径 `./static/magic_card.json`；`tests/test_all_magic_cards.py:1088` 也用硬编码相对路径，是全套测试中唯一对 CWD 敏感的。

**实测基线（2026-09-13 缺陷审计修复批后）**：`398 passed / 0 failed`（`test_all_magic_cards.py`、`test_db_core.py`、`test_disconnect_and_eden_shenji.py`、`test_fixes_regression.py`、`test_ui_review_fixes.py`、`test_review_fixes_2026_09_12.py`、`test_review_fixes_batch2.py`、`test_mobile_adaptive_layout.py`、`test_mingzhi_burial_fix.py` 21 条）。

> 🔧 **2026-09-13 个人战绩弹窗 / 人机战绩统计批**（详见 `docs/STATS_AND_AI_RANKING_FIXES.md`）：6 处实测缺陷 —— ①历史行把 `<button>` 塞进 `<table><tbody>` 触发 foster parenting，表头「时间 对手 结果 局内日志」孤立在列表最下方；②胜负配色被通用 `button` 规则的 `background-image` 渐变盖掉，三条胜绩全蓝；③`.user-stats-table` / `.user-history` 在样式表里从未定义；④人机对手显示成裸 ID `ai-4530c8`；⑤胜局的「对局详情」把「对手」显示成自己；⑥**人机对局计入 `users.wins` / 连胜**（排行榜 `ORDER BY wins DESC` → 打电脑即可刷榜）。修法：历史列表改 div 三列网格、`.match-history-btn{background-image:none}` + `.win`/`.lose`、`ai-` 前缀映射「电脑」并加「人机」标签、按胜负取对手、`db.record_match(count_stats=)` + `server._count_stats_for(room)`（人机只写历史、不计统计，6 处调用点全部显式传参）；并合并两份重复的 `showUserStats`/`showMatchDetail`、去掉 `setTimeout` 绑事件与「每次点头像都 append 一个重复 id 弹窗」，新增「加载更多」。回归：`tests/test_stats_display_fixes.py`（14 条）+ `tools/stats_modal_check.mjs`（无头 Edge，27 项，含 `--username` 真实账号端到端）；历史脏数据用 `tools/recompute_ranked_stats.py --apply` 对齐（本机已执行：z1w6qn 3 胜 → 0）。

> 🔧 **2026-09-12 移动端自适应布局批**（详见 `docs/MOBILE_ADAPTIVE_LAYOUT.md`）：对局界面在手机上不可用——桌面多浮窗范式被等比压到手机（断点只改尺寸不改结构）。实测红基线 32 项不通过：320×568 下棋盘 100% 在首屏外且滚过去后 36/36 格被浮窗盖住、日志∩预览 273×181、聊天∩阶段卡 337×123、手牌 `#magic-system` 落在 y≈1577、格子 20.3~35px。修法：新增 `static/adaptive_layout.js`，按【可用空间】选布局（`wide` 保持原样 / `compact` 一屏网格 / 矮屏右列 / 放不下时手牌收进面板槽），三个浮窗搬进 `#aux-dock` 三选一，棋盘尺寸由舞台反推（只锁宽度保正方格），触屏停用浮窗拖拽。修复后 10 项×6 视口全部通过，宽屏（≥1200×700）布局一行未动。
>
> 🔧 **2026-09-12 后端/安全审查修复批**（权威清单见 `docs/FIXES_2026-09-12.md`）：7 个 P0 + 20 余个 P1。要点：
> - **`@_test_event` 装饰器顺序修正**（此前写在 `@socketio.on` 外层 → 门禁完全失效、公网可判胜/白嫖卡/读对方船位）
> - `handle_attack` 补攻击次数与终局校验（此前次数=0 仍可无限攻击、终局后可重复记战绩）
> - `rejoin_room` 令牌判空（`None == None` 可劫持座位）、`/user_stats` 不再泄露 `password_hash`/`token`
> - `select_magic_target` 只接受选择类字段（此前可注入 `pending_placement` 无限增援）
> - 「神机妙算」复活不再产生幽灵船；增援/复活不再退还已消耗的攻击次数
> - 「明智埋葬」「仁王之盾」补上真实链路；百亿补贴按卡面归持卡者；平等条约快照过期；加百列之光/场地归属；回光返照过期；溅射不再让连锁崩溃
>   - ⚠️ 其中「明智埋葬」当时**并未真正修好**（补的分支把候选下标当成施法者自己手牌的下标）：已于同日重新修复，见下行
> - 前端：`init()` 幂等（不再双绑事件）、补齐 `#profile-save-msg`/`#show-opponent-stats`/`#total-ships`、船数广播按收件人视角下发
>
> 🔧 **2026-09-12 明智埋葬真实链路修复**（详见 `docs/FIXES_2026-09-12.md` 第七节）：实测症状为「选中牌后**牌不进弃牌堆、自己也不摸牌**」（手牌为空时直接报「无效的选择」）。根因是 `confirm_magic_target` 里那份**独立实现**把前端下发的候选下标 `card_index` 当成**施法者自己手牌的下标**，选中的那张（牌堆/对方手牌）从未被取出。修法：`select_magic_target` 与 `confirm_magic_target` 共用 `_bury_choice_target()` + `_apply_bury_choice()`（下标统一为 `(source, index)`，前端回传 `source_index`；必须先 `pop` 再进弃牌堆，否则同一张牌会同时留在原处）；补对方手牌同步、施法者校验、`magic_temp_data` 只存纯数据。回归：`tests/test_mingzhi_burial_fix.py`（21 条）。
> - 追加排查「没有触发摸牌效果」：真实浏览器端到端（无头 Edge + CDP，真点手牌与弹窗）实测**链路是通的**（手牌 `["增援"]`→`["增援","五险一金"]`，弃牌堆 +选中的那张，日志有记录）。会让人觉得「没摸到牌」的是三种**规则性静默**情况：牌堆已空 / `no_draw`（无中生有）生效中 / 摸到与手牌重名的牌自动进弃牌堆 —— 现在都会在**成功提示与对局日志里写明原因**（旧提示一律谎报「并摸了一张牌」）。另修前端误导文案：`applyCardEffect` 在玩家**还没点选**时就弹「埋葬卡牌并抽一张新牌」；`playMagicCard` 把「不是你的回合」误报成「当前阶段 preparation 不允许用速阶2」。
>
> **第二批（同批提交）卡牌语义修正**：绝处逢生（牺牲全部 → 玩家在旧位置选一格放唯一一艘）、疗愈（原地复活）、余音绕梁（按攻击阶段而非击杀次数）、神之宣告（采用玩家点选的两艘 + 效果1 由对方点选）、克苏鲁之眼（对方也点选暴露）、失灵！（只能康"本大回合刚使用"的卡）；清理 6 个死监听、修复免空壳大厅（改用 find_match/cancel_match 与 /api/online_count）、补桃园取消按钮（`cancel_magic_selection`）、攻击坐标拒绝小数、空棋盘不再一击判胜、重连快照按 state 路由

> 🔧 **2026-09-11 安全/健壮性修复批**：本文件第 11 节的 P0/P1 问题已修复（详见 `docs/FIX_PLAN.md` 与 `tests/test_fixes_regression.py`）。要点：
> - 12 个 `test_*` 事件默认关闭（`ENABLE_TEST_EVENTS=1` 启用）；`test_magic.js` 已从 index.html 移除
> - `SECRET_KEY`/`CORS_ORIGINS`/`PORT`/`FLASK_DEBUG` 均改为环境变量；默认关 debug
> - 游客匹配 bug（`None==None`）修复；匹配队列改为单结构列表 + RLock，同账号去重不会死循环
> - 已结束房间由后台 reaper（`_reap_ended_rooms`，宽限 120s）统一回收，修复内存泄漏
> - place_ships / attack / 魔法目标均有服务端校验；surrender 有 `_identity_ok`
> - requirements.txt 已锁版本并补 eventlet；db 层写操作统一持锁 + 列名白名单 + 补索引
> - game.js：`ensureSocket()` 统一连接管理（不再重复建连）；`#effect-indicators` 已补；猜拳文案映射已修正；「神之宣告」出牌前可选效果（`promptDivineDecreeChoice` → `targets: {effect_choice}`）
> - eventlet `monkey_patch()` 已移至 server.py 首行（在所有 import 之前）
> - 已删除死代码：`process_match_queue`、lobby 三方法（前端仍监听的 lobby 事件为历史遗留空壳）

> 🔧 **2026-09-12 UI 审查修复批**（截图逐像素审查，详见 `docs/UI_REVIEW_FIXES.md`）：
> - `#effect-status-bar` 默认 `hidden` + `initEffectStatusBarSync()`——不再渲染成一条空白横条
> - `updatePhaseUI()` 阶段按钮 `block` → `inline-block`——不再贴在阶段卡片左边
> - `.board-wrapper{flex:0 1 340px}`——两块棋盘不再一大一小（300×300，单格 42px）
> - 游戏日志补空状态占位 `.log-empty`；玩家信息行文案改「你：剩余 6 艘战舰」；中文界面冒号统一全角
> - `static/avatars/default.png` 由 1×1 透明图换成 96×96 占位头像
> - 回归：`tests/test_ui_review_fixes.py`（9 条）+ `tools/ui_layout_check.mjs`（无头浏览器布局不变量，见下一批）

> 🔧 **2026-09-12 移动端自适应布局批**（`tools/ui_layout_check.mjs` 已扩成两段式：宽屏 1600×1000 跑原有 9 项，另在 320×568 / 336×664 / 390×844 / 430×932 / 664×336 横屏 / 768×1024 六个视口上跑 10 项移动端不变量，含"展开面板槽后"复测）。详见 `docs/MOBILE_ADAPTIVE_LAYOUT.md`。

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

### ✅ eventlet monkey_patch 时序（2026-09-13 复核：已正确）

```python
1: # eventlet 下必须先 monkey_patch，且必须早于任何可能使用 socket/ssl/threading
2: # 的标准库导入：否则后台任务里的 time.sleep 会阻塞整个单线程 hub
3: # （掉线宽限 30s / 连锁超时 10s 都会让服务器假死）。
4: try:
5:     import eventlet
6:     eventlet.monkey_patch()
7: except ImportError:
8:     pass
```

`monkey_patch()` 现在位于 **文件第 4~8 行、所有 import 之前**（前面只有注释），是 2026-09-11 那批修好的。**新增任何 import 时必须继续排在它之后**——一旦有人在它上面 import 了会创建线程/套接字的标准库，后台任务就会阻塞 eventlet hub。

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
- **回合思考计时**：`TURN_TIMEOUT_SECONDS`（默认 90 秒，0 = 关闭）。超时只做一次**保底动作**、不判负；每做一次有效操作就重新计时（见 §11 第 31 条）

---

## 4. 核心数据结构（`server.py`）

| 类 | 行号 | 关键字段 |
| --- | --- | --- |
| `Position` | 84 | `x, y, hit, ship_sunk, is_sulfur, is_bomb, is_splash`。`__eq__` 支持与 dict 比较 |
| `PlayerShip` | 110 | `positions, hits, invincible, shield, frozen` |
| `MagicCard` | 134 | `name, speed, type, description`。只传 name 时自动从全局 `magic_cards` 查补 |
| `EffectFlags` | 153 | 玩家级标记：`treasure_hunter(八方来财), prediction(神机妙算), subsidy(百亿补贴), no_draw, forced_kill(int), vampire(饮血), last_stand(绝处逢生), double_attacks, battle_spirit(越战越勇)` |
| ~~`Effect`~~ | — | **已删除**（2026-09-11：唯一遍历点 `GameRoom.attack` 不可达，余音绕梁/火力全开已改走 EffectFlags） |
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
chain_timer（超时代际令牌，注意没有 chain_token 字段）

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
| `init_player_magic` | 274 | 清空手牌；**仅当 `magic_deck` 为空时**初始化并洗牌 |
| `draw_card` | 293 | 受 `no_draw` 阻止；重名卡（**`失灵！` 例外**）丢弃牌堆 |

> ✅ **攻击实现已统一（2026-09-11）**：原 `GameRoom.attack`（旧版死代码）与 `Effect` 钩子体系已删除。现在只有两条路径：`handle_attack`（普通攻击，强制击杀/普通共用一套 `_apply_ship_sunk_effects` 结算）与 `_do_attack`（教皇旨意弃卡攻击，不消耗常规次数）。`余音绕梁`（forced_kill 标记）/`火力全开`（double_attacks 标记）经 **EffectFlags 在真实路径生效**，不再依赖 Effect 钩子。

---

## 5. Socket.IO 事件（43 个，精确名）

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

### 🔧 调试事件（12）—— 已由 `@_test_event` 门禁关闭（默认不可用）

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

> ✅ **2026-09-13 实测**：12 个 handler 全部带 `@_test_event`（装饰器在 `@socketio.on` 内侧，顺序正确），未设 `ENABLE_TEST_EVENTS=1` 时一律返回「调试事件未启用」；`static/test_magic.js` 已从 `index.html` 移除（文件仍在仓库里，但页面不加载）。
> ⚠️ 这 12 个 handler **仍然没有 `_identity_ok`**：一旦有人为了调试把 `ENABLE_TEST_EVENTS=1` 打开，它们就是完全敞开的。

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

核心分发函数：**`apply_magic_effect(room, caster_id, card, target_data)`**（2026-09-13 实测：约 1240 行，**42 处 `card.name ==` 覆盖 41 个唯一卡名**，与 JSON 双向一一对应；行号已漂移到 4000+ 区间，用 grep 定位）

场地魔法：`_place_field_magic`(621) 存入 `room.field_magic`（**实例对象**）；顶替旧卡时旧卡实例进弃牌堆。

---

## 8. 连锁与无效化引擎

**已实现**（不是设计稿）。`docs/CHAIN_ENGINE_SPEC.md` 是一份**实施前的设计稿**，
2026-09-13 已在它开头补了实测校准表：文档里抱怨的毛病当时都修掉了，但引擎
**并没有**按它第 3 节那样拆成 `engine/` 目录 —— 实现仍在 `server.py` 里。

| 组件 | 行号 | 说明 |
| --- | --- | --- |
| `_can_respond_chain` | 2657 | 能否响应 |
| `_advance_chain_window` | 2678 | 推进响应窗口 |
| `resolve_chain` | 2702 | 逐项出栈结算（**negated 项跳过效果**） |
| `_schedule_chain_timeout` | 2757 | 超时调度 |
| `chain_response` | 2987 | 玩家响应 handler |
| `_speed3_cards` | 2650 | 取速阶 3 手牌 |

**机制**：栈 = `room.chain: list[ChainItem]`，每项带 `negated` 标记；结算 LIFO（后发先至）；响应窗口 10 秒超时。

**⚠️ 与 SPEC 的两处偏差**（有意为之，别照文档改回去）：
1. SPEC 说 negated 项"不改场地"，实现里**仍执行"贴了再拆"**（2791 附近，注释说明是为"避免凭空消失"）—— 有意为之
2. `平等条约` **不走** `negate_target` 连锁标记，改为读 `game_effects['last_ship_change']` 快照回滚（4368-4401）

**⚠️ SPEC 过期点（2026-09-13 实测）**：§4 列的僵尸代码 `pending_magic` / `counter_magic_response`
**已全部清理（全文件 0 命中）**；`room.last_magic` **属性也已不存在**（只剩结算函数里的局部变量
`last_magic = room.magic_history[-1]`）；§2 抱怨的两条**均已修复**。**读 SPEC 前先读本节。**

---

## 9. 掉线重连

| 组件 | 行号 | 说明 |
| --- | --- | --- |
| `_start_disconnect_grace` | 2779 | 掉线宽限（**30 秒**） |
| `_disconnect_timeout` | 2799 | 超时判负/取消 |
| `_issue_reconnect_token` | 2852 | 发重连 token |
| `_build_room_sync` | 2858 | 重连快照 |
| `handle_rejoin_room` | 2896 | 重连恢复 |

> ✅ **2026-09-13 实测**：快照已补全（33 字段），含 `chain` / `chain_waiting` / `chain_window` / `active_effects` / `pending_placement` / `pending_sacrifice` / `opponent_attacks`（本次新增）等。
> 重连落在连锁窗口内时，前端会按 `chain_window` 归属补弹响应窗口。

**eventlet 注意**：`disconnect` handler 内**不能同步 emit**（会卡死 hub），代码中有多处相关注释。

---

## 10. 人机对战

| 组件 | 行号（会漂移，用 grep 定位） |
| --- | --- |
| `_ai_player_id` / `_ai_place_ships` | 2540 附近 |
| `_maybe_run_ai_turn` / `_ai_turn_loop` | 2564 附近 |
| `handle_create_ai_room` | 764 |
| **`_AI_SAFE_CARDS` / `_ai_choose_magic_card` / `_ai_maybe_play_magic`** | AI 出牌白名单与选牌（2026-09-13 新增） |
| **`_ai_can_negate_chain_top` / `_ai_chain_respond`** | 困难难度：AI 用【失灵！】响应连锁 |

AI 玩家 id = `'ai-' + room_id`；`room.is_ai_room = True`；`room.ai_difficulty` ∈ `easy|normal|hard`。真人摆完船后为 AI 自动布船；AI 在真人出拳后自动出拳。

**三档难度（2026-09-13 新增，前端首页 `#ai-difficulty` 下拉框）**

| 难度 | 行为 |
| --- | --- |
| `easy` 简单 | **只炮击、不出牌**（保留"打电脑保底能赢"的新手体验） |
| `normal` 普通（默认） | 每回合额外打出一张**安全卡**（见 `_AI_SAFE_CARDS`） |
| `hard` 困难 | 普通 + 对方出牌且康得动时，用【失灵！】响应连锁 |

⚠️ **白名单不是随便扩的**：桃园结义 / 明智埋葬 / 神机妙算 / 仁王之盾 / 灵气复苏 / 增援 /
死者苏生 / 绝处逢生 都会**等待施法者自己**点选或放置，AI 打出去就会把整局卡死在那一回合。
要加卡，先在 `tests/test_ai_magic.py::test_ai_safe_card_leaves_no_pending_state` 里过一遍。

⚠️ **AI 出牌可能打开连锁窗口**，而连锁未结算时 `handle_attack` / `end_turn` 都会被门禁拒绝
（见 §11 第 5 条）。因此 `_ai_turn_loop` 出牌后会**先等窗口关闭再开炮**，收尾的
`enter_end_phase` / `end_turn` 也带重试 —— 少了任何一处，AI 回合就会停在半途、真人只能干等。

---

## 11. 已知问题（2026-09-13 全量实测重写）

> ⚠️ **本节此前整章过期**：所列的 P0/P1 早已全部修好，却仍被当成待办，导致重复排查。
> 2026-09-13 用「真实 socket 双客户端 + 无头浏览器 + 全量测试」重测后重写。
> 逐条证据、复现命令与剩余待办见 `docs/DEFECT_FIXES_2026_09_13.md`。

### ✅ 早已修复（勿再当待办）

| 曾经的问题 | 现状与验证 |
| --- | --- |
| 12 个 `test_*` 事件无鉴权 / 生产页面加载 `test_magic.js` | 全部加 `@_test_event` 门禁（默认关闭）；`index.html` 已不加载该脚本 |
| `showDivineDecreeChoice` 未定义 → ReferenceError | 已改用 `promptDivineDecreeChoice`（出牌前选效果） |
| `#effect-indicators` 不存在 → 百亿补贴 TypeError | `index.html` 中该元素存在，调用处另有存在性守卫 |
| 游客之间永远匹配不上（`None == None`） | 匹配循环显式放行 None；**实测两个游客成功配对** |
| `getRPSName` 布/剪刀互换 | 映射已正确（`paper→布`、`scissors→剪刀`） |
| `surrender` 无 `_identity_ok` | 已加身份校验 + 终局守卫 |
| 大厅（Lobby）8 个空壳事件监听 | 已清理；大厅改走 `find_match`/`cancel_match`。⚠️ `/lobby` 路由仍在但页面无入口 |
| `gameState.chain` 永不填充 | 已填充且能显示（`#chain-display` 由 JS 动态注入，不在 index.html 里） |
| `switchScreen` 漏 `matchSuccessScreen` | 已注册（9 屏齐全） |
| `Effect` 钩子 / `GameRoom.attack` / `process_match_queue` / `apply_effect` / `_chain_target_below` / `line_attack` | 已全部删除（grep 0 命中） |
| `_build_room_sync` 缺 chain / 放置流程状态 | 已补齐（32 字段），本次又补了 `opponent_attacks` |
| 胜负判据 `==0`/`<=0` 混用 | 胜负路径 7 处已统一为 `<=0` |
| eventlet `monkey_patch()` 排在 `db`/`api` 导入之后 | **2026-09-13 复核：已在文件第 4 行、所有 import 之前**（2026-09-11 修好，文档此前未同步） |

### 🔴 2026-09-13 本轮修复（缺陷审计批）

| # | 问题（修复前实测现象） | 修法 |
| --- | --- | --- |
| 1 | **终局后 `place_ships` 把 `game_over` 倒回 `rock_paper_scissors`**：对局复活，该房间此后永不被 reaper 回收 | 新增 `@_require_live_room` 门禁 |
| 2 | **终局后 `surrender` 可翻转胜负**（胜者在结算界面点投降即变负，登录用户还会二次记账） | 同上 |
| 3 | **`rps_choice` 非法值**：`players[0]` 出非法拳 → 结算 handler 抛 KeyError、猜拳卡死；`players[1]` 出非法拳 → **非法方获胜** | handler 枚举校验 + `determine_rps_winner` 兜底 |
| 4 | 终局后仍可出魔法卡进连锁 / `end_turn` / `enter_end_phase` 推进回合 | 门禁覆盖 16 个写操作 handler |
| 5 | **连锁窗口开着时仍可继续攻击**（`end_turn` 却已被拦，同一状态两种口径） | `handle_attack` 补同一条件 |
| 6 | **桃园结义「对方再选一张」被忽略**（前端发了 `opponent_choice`，后端固定取第一张） | `confirm_magic_target` 采用该字段 |
| 7 | **加百列之光被前端「补刀」**：后端已按归属保留施法者自己的场地，前端又 emit `remove_field_magic` 把它拆了 | 删除该 emit（场地拆除全权交服务端 + 广播） |
| 8 | **神之宣告牺牲的两艘船其实是随机的**：`playMagicCard` 提前 return，`own_ships` 选择器不可达 | 效果选择后接点选两艘自己的船 |
| 9 | **已沉船仍留在 `player.ships`** → 钢筋铁骨 `pop()` 可能弹到沉船（零代价发动）、沉船堆重复条目致复活时船数虚增 | 钢筋铁骨 / 神之宣告 / 绝处逢生 一律只取"活船" |
| 10 | **建了但没人入座的房间永不回收**（每次误点建房泄漏一个 GameRoom） | reaper 增加 `_WAITING_ROOM_TTL`（1 小时） |
| 11 | **重连后自己棋盘的伤损全部消失** | 快照补 `opponent_attacks` + 前端恢复 |
| 12 | 重连落在连锁响应窗口内无法响应 | 响应弹窗抽成 `showChainRequestPrompt`，`room_sync` 时按窗口归属补弹 |
| 13 | 连锁结算后「当前连锁 (N)」永久残留 | `chain_resolved` 里清空并刷新 |
| 14 | `get_magic_temp_data` 把桃园候选牌**泄露给对手** | 只下发给当事人 |
| 15 | **跑一次 pytest 就往正式库写假对局**（库内已沉淀数百条 u1/p1 记录） | `tests/conftest.py` 用环境变量隔离数据库 |
| 16 | 越战越勇文案「+2」与实现/卡面「净 +1」不符 | 文案已改 |
| 17 | `/api/leaderboard` 硬编码 100，`?limit=` 被完全忽略（实测 `?limit=2` 仍返回全部） | 支持 limit 并钳制到 1~100 |
| 18 | 前端死函数 `createRoom`/`joinRoom`/`toggleCustomRoomOptions`/`createSelectionBoard`/`getSelectedCells`/`showReinforcementPrompt`/`showChainableCards`（含调用未定义函数的不可达分支），共 304 行 | 逐个 grep 确认零调用后删除（页面零 JS 异常复测通过） |
| 19 | **连锁响应窗口内无法给「需要目标」的速阶 3 卡选目标**：点卡后固定发 `targets: []`，神威！/轰炸/冻结/硫磺火焰/探测雷达 的后端分支缺目标会直接失败 | 点卡后先走目标选择器、确认后再把 targets 回填给 `chain_response`；新增 `tools/chain_target_check.mjs`（24 项无头浏览器断言） |
| 20 | **平等条约无法无效化区域魔法造成的船数变化**（溅射/轰炸/硫磺火焰各自内联结算、不写快照）；**无瑕圣心**在区域击沉时只置 no_damage、不中断 | 新增 `_on_ship_destroyed` 统一副作用：普通攻击与三种区域魔法共用同一份（快照 + 百亿补贴 + 无瑕圣心中断） |
| 21 | `select_magic_target` 与 `confirm_magic_target` 是两套独立实现，语义已漂移（桃园剩余牌进弃牌堆 vs 放回牌堆、忽略对方自选的 opponent_choice） | `select_magic_target` 只做白名单过滤，随后委托给在用实现 |
| 22 | 12 个 `test_*` 高危事件只有 1 个有回归覆盖；**连锁超时 / 窗口推进 / 能否响应零覆盖** | 新增 `tests/test_guardrails.py`（24 条：12 个事件参数化拒绝 + 连锁纯函数与超时代际令牌） |
| 23 | **AI 手上有牌却一张都不出**，也不参与连锁（人机对战完全用不上 41 张卡） | 新增 `_AI_SAFE_CARDS` 白名单 + `_ai_choose_magic_card`（纯函数）+ `_ai_maybe_play_magic`；**三档难度** `easy`（不出牌）/ `normal`（每回合一张安全卡，默认）/ `hard`（再用【失灵！】响应连锁），前端首页 `#ai-difficulty` 下拉框 | 
| 24 | AI 出牌会**打开连锁窗口**，而连锁未结算时 `handle_attack`/`end_turn` 会被门禁拒绝 → AI 回合停在半途、真人干等 | `_ai_turn_loop` 出牌后**先等窗口关闭再开炮**；收尾的 `enter_end_phase`/`end_turn` 各带 20 次重试 |
| 25 | **冻结的船在棋盘上完全看不出来**：服务端只改了 `ship.frozen`，前端从未收到过这个状态 → 玩家不知道哪几艘船本回合不提供攻击次数 | `_emit_player_ships` / `_build_room_sync` 带上 `frozen`；冻结时与解冻时都推送；前端 `initGameBoards` 加 `frozen` 类 + CSS `:before` 雪花。回归：3 条 pytest + `ui_layout_check.mjs` 3 项浏览器断言 |
| 26 | 自定义房间**没有任何入口生成邀请链接**（`?room=XXXX` 自动入房早就写好，只能口头报房间号） | 房间号旁新增「🔗 复制邀请链接」按钮 + `copyInviteLink()`（剪贴板不可用时降级 prompt）。回归：`tools/room_invite_check.mjs`（7 项，含真实建房与降级路径） |
| 27 | **排行榜被 0 局账号占满**（人机不计统计后新账号全是 0 胜 0 负却排在前列）；**背景音乐 6 条路径全 404 却静默停摆**，玩家完全不知道发生了什么 | 排行榜过滤 `wins+losses > 0`；`music_player.js` 统计失败音轨，整轮失败就明确提示「未找到背景音乐文件」而不是静默 `playNext` |
| 28 | **全站零音效**（唯一的 `new Audio()` 是 BGM，而 `static/music/` 目录根本不存在，6 条预设路径全 404） | 新增 `static/sfx.js`：用 Web Audio **现场合成** 9 个音效（命中/落空/击沉/摸牌/出牌/连锁/回合/胜负），**不需要任何音频素材**；game.js 挂钩 `attack_result`/`game_over`/`turn_change`/`hand_updated`/`chain_request`/`sendMagicCard`；设置面板加「音效静音」开关。回归：`tools/sfx_check.mjs`（17 项，桩 AudioContext + 真实事件） |
| 29 | **卡牌图鉴只有一段平铺列表**（无检索、无筛选，41 张卡里想找一张只能翻） | 帮助弹窗升级为图鉴：去重展示 41 张唯一卡 + **按速阶/类型筛选** + **卡名/效果关键词搜索** + 「共 N / 41 张」计数 + 空状态提示。回归：`tools/card_compendium_check.mjs`（16 项） |
| 30 | **探测雷达/雷达子弹的显形只亮 4 秒**（服务端是持久记录，前端 `setTimeout` 4 秒后就把高亮擦掉；而且任何一次棋盘重绘都会丢） | 改为持久高亮：存进 `gameState.revealedCells`、重绘时重新上色、重开棋盘时清空。回归：`ui_layout_check.mjs` 新增 3 项（含「4 秒后仍在」与「重绘后仍在」） |
| 31 | **没有任何回合计时**：此前只有连锁窗口有 10 秒超时，炮击/准备阶段可以无限长考，对手只能干等 | 新增后台看门狗 `_auto_act_on_timeouts`（`TURN_TIMEOUT_SECONDS`，默认 90 秒）：超时只做一次**保底动作**（准备→进战斗 / 战斗→随机开火一发 / 结束→交出回合），**不判负**；门禁装饰器在每次成功操作后重置计时（只惩罚完全卡住的人）；人机房 / 连锁窗口 / 等待点选 / 有人掉线宽限中一律不催。回归：`tests/test_turn_timer.py`（15 条）+ 真 socket e2e（3 秒超时下 10.2 秒自动开火并广播「思考超时」） |
| 32 | **卡牌没有任何使用数据**（图鉴只有卡面，看不出哪张卡常被用） | 新增 `card_usage` 表 + `GET /api/card_usage` + 出牌时记账（`record_card_use`，入链时刻计一次）；图鉴每张卡显示「使用 N 次」角标并支持**按使用次数排序**。回归：`tests/test_card_usage.py`（9 条）+ `card_compendium_check.mjs` 新增 3 项 + 真 socket e2e（打出一张卡后接口计数 0→1） |
| 33 | **BGM 永远不响**：`static/music/` 目录不存在，6 条预设路径全 404 —— 上一轮只做到「明确报错」，播放器仍然是废的 | 整轮音轨失败后自动切到**内置合成环境音**（Web Audio：三正弦 + 极慢 LFO 扫低通，零素材），界面写明「已自动切换」；暂停/继续/音量/静音都作用到合成音；上/下一首不再把 404 循环拉起来。顺带修掉**自动播放被拦时的 5 条 console.error 刷屏**，以及它把「已切到合成音」的状态覆盖回未播放。回归：`tools/bgm_check.mjs`（13 项） |

### 🟠 仍未处理（按"感知收益 ÷ 成本"排序）

| 项 | 说明 | 产出归属 |
| --- | --- | --- |
| 无复盘/观战 | 回合计时（第 31 条）与卡牌使用统计（第 32 条）已完成 | P2-9/10 |
| `/user_stats` 公可枚举用户名（含任意用户完整局内日志） | 凭据字段已不泄露；是否收紧属于产品决策 | 安全/体验 |

---

## 12. 开发约定

1. **改魔法卡要同步 4 处**：`magic_card.json`、`magic_cards.js`、`apply_magic_effect` 分支、测试。前两者须逐字符一致（当前一致性测试不校验 `description`，需人工留意）
2. **`失灵！` 重复 3 份是故意的**，勿"修正"
3. **`field_magic` 存实例对象**，用 `field_magic_name(room)` 取值
4. **改攻击逻辑先确认三套实现改的是哪个**（见第 4 节）
5. **不要一次读完 `server.py`/`game.js`** —— 先 grep 定位再分段读
6. **重活交子智能体**（独立上下文，不撑爆主会话）
7. **修 bug 前必须实测复现** —— 本项目静态分析已出过多次误报（见第 6 节）
8. **不要用脚本做全局字符串替换**（尤其涉及 `` ` `` 与 `${}` 时）：2026-09-13 有一次
   `` `$` `` → `$` 的全量替换，静默改坏了 `game.js` 里 **10 处**模板字符串
   （颜色转换 / 日志渲染 / 倒计时 / 自动布船 / 选区 key / 连锁卡列表），
   语法检查全红。改法是**只改目标块**（正则锚定整段）+ 改完立刻 `node --check`
   + 跑无头工具（它们会真的走这些代码路径）。
9. **文档与代码已脱节**：`CHAIN_ENGINE_SPEC.md`、`README.md` 均有过时内容。
   历史教训：`CLAUDE.md` 第 11 节的「已知问题」曾**整章过期**（所列 P0/P1 全部早已修好），
   2026-09-13 已按实测重写——**引用本文件任何一条结论前，先用 grep 到代码里确认**。
10. **跑 e2e 的服务端要隔离数据库**：`BATTLESHIP_DB_PATH=C:\Windows\Temp\e2e.db`。
   全卡 e2e 会真的打 42 张牌，不隔离就会往正式库写 40 多条卡牌使用统计。

---

## 13. 深度文档

| 文件 | 内容 |
| --- | --- |
| **`docs/DEPLOYMENT.md`** | **部署说明：服务器环境、必需环境变量、更新流程、事故记录 —— 部署前必读** |
| `docs/SERVER_PY_ANALYSIS.md` | server.py 4733 行全量分析（类/事件/攻击结算/魔法分发/连锁） |
| `docs/FRONTEND_TECH_ANALYSIS.md` | 前端 + 测试深度分析（827 行，58 个 socket.on、33 个 emit、函数索引、19 条 bug） |
| **`docs/UI_REVIEW_FIXES.md`** | **2026-09-12 截图 UI 审查修复记录（含逐条证据、端到端验证方式、有意不改的项）** |
| **`docs/MOBILE_ADAPTIVE_LAYOUT.md`** | **2026-09-12 移动端自适应布局：实测问题清单、四种布局模式、端到端不变量与取舍** |
| **`docs/STATS_AND_AI_RANKING_FIXES.md`** | **2026-09-13 个人战绩弹窗 / 人机战绩统计：6 条缺陷的根因与实测证据、数据口径变更、验证方式** |
| **`docs/DEFECT_FIXES_2026_09_13.md`** | **2026-09-13 全量缺陷审计与修复：实测方法、逐条缺陷与复现方式、修复内容、剩余待办** |
| `docs/CHAIN_ENGINE_SPEC.md` | 连锁引擎设计稿（⚠️ 实施前的文档，开头已补 2026-09-13 实测校准表） |
| `README.md` | 面向用户的功能/玩法说明（测试数/文件清单已校准） |

> ⚠️ **部署前务必确认环境变量**：代码若新增 `os.environ.get('XXX')`，服务器 systemd 必须同步配置。
> 漏配会导致「服务能起来但带着错误默认值运行」——2026-09-12 就因漏配 `CORS_ORIGINS` 导致线上所有操作卡十几秒。详见 `docs/DEPLOYMENT.md` 第 5 节。
