# CLAUDE.md — 战舰棋 + 魔法卡

> 面向 AI 代理的索引。**先读这里，别一次读完 `server.py`（8500+ 行）/ `static/game.js`（9000+ 行）/ `static/style.css`（4800+ 行）—— 一律先 grep 定位再分段读。**
> ⚠️ 行号每次提交都会漂移，**本文件里任何行号都只当线索，以 grep 结果为准**。
> ⚠️ **本文件每次对话都会整份注入**，新增内容请控制在几十字级别 —— 长记录写进 `docs/`。
> 最后更新：2026-09-20（新卡批 + 选船优先级镜像）。

---

## 0. 速览

Flask + Flask-SocketIO 的实时双人海战棋，48 条魔法卡 / 场地魔法 / 连锁系统；含账号、战绩排行、段位与排位、等级经验、名片外观、大厅、人机、自定义房、断线重连。

- 线上 http://8.133.180.159:5000/ ｜ 仓库 `xiaoxiaoyiiii/battle_ship1.0` ｜ 生产跑 eventlet
- 核心文件：`server.py`（事件 + 对局）｜ `api.py`（HTTP）｜ `db.py`（SQLite/WAL）｜
  `static/game.js` + `templates/index.html` + `static/style.css`（前端单页）
- 纯规则模块（都**只有一份实现**，前端不许重算）：`ranks.py` 段位 ｜ `leveling.py` 等级经验 ｜
  `achievements.py` 徽章 ｜ `profile_spec.py` 名片外观与解锁 ｜ `wallpaper.py` 壁纸

---

## 1. 运行与测试

```bash
pip install -r requirements.txt
python start_server.py        # 推荐；注意它**硬编码 --port=5000**，换端口要直接 python server.py
python -m pytest tests/ -q    # 基线见下
```

- ⚠️ **必须在项目根目录跑**（`server.py` 用相对路径 `./static/magic_card.json`）。
- 解释器：PATH 上的 `python`（3.12.10，已装 flask）。报 `ModuleNotFoundError: flask` 就是选错了。
- ⚠️ 本机临时目录 ACL 坏过，pytest 若在 setup 报 `PermissionError: Temp\pytest-of-Administrator`，
  先 `New-Item -ItemType Directory -Force .tmp\pytemp`，再
  `$env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP; python -m pytest tests/ -q -p no:cacheprovider`。
- **实测基线（2026-09-20）**：`1905 passed`；跑完约 40 秒。

### 无头浏览器工具（`tools/*.mjs`，比 pytest 更接近真实）
改前端后跑对应那个，**别每次全跑**（单个工具几分钟）：
布局 → `ui_layout_check.mjs` ｜ 名片 → `profile_card_check.mjs` ｜ 排行榜/个人信息 → `profile_leaderboard_check.mjs` ｜
段位/排位 → `ranked_check.mjs` ｜ 段位帮助页 → `rank_help_check.mjs` ｜ 手牌 → `hand_play_check.mjs` ｜
壁纸 → `wallpaper_check.mjs` ｜ 徽章 → `achievements_check.mjs` ｜ 等级 → `level_check.mjs` ｜
音效/BGM → `sfx_check.mjs` / `bgm_check.mjs` ｜ 连锁卡预览 → `chain_preview_check.mjs` ｜ 仁王之盾 → `renwang_board_check.mjs` ｜
大厅 → `lobby_check.mjs`（**双浏览器** —— 大厅的价值就是"别人那边立刻能看到"，单浏览器测不出来）｜
绝处逢生锁卡/击杀即胜 → `last_stand_win_check.mjs`（前端喂事件）＋ `last_stand_win_e2e.mjs`（**真 socket 打完一局**，需 `ENABLE_TEST_EVENTS=1`）｜
更新公告 → `changelog_check.mjs`（入口 / 自动弹一次 / 文案逐字来自接口 / 浮层互斥）
- ⚠️ **真 socket E2E 的 ack 帧是 `43<ackId><JSON>`，没有长度位**；handler 抛异常时**连 ack 都不回**，
  症状都是"客户端超时"（像服务端卡死）→ 先看服务端日志的 traceback，别先怀疑网络。
- **`dom_contract_check.mjs`**：不用浏览器、不用服务端、几秒钟 —— 查「代码引用了但页面里不存在的 id」，
  这类引用的表现是 `getElementById` 拿到 `null` 被 `if (el)` 兜掉、**不报错、只是点了没反应**。
- ⚠️ 工具要的服务端必须带 `CORS_ORIGINS=http://127.0.0.1:<端口>`，否则 socket.io **静默连不上**（页面无报错）。
- ⚠️ 本地验证端口**避开 5060/5061**（Fetch 规范的被阻止端口，Node `fetch`/Chrome 拒发而 curl 正常 → 看着像服务器卡死）。
- ⚠️ 无头浏览器用持久 profile，开头按 profile 路径预清理残留进程，profile 放项目内 `.tmp/`。

---

## 2. 架构与启动时序

```
浏览器(index.html + game.js) --socket.io--> server.py <--复用--> api.py(Flask app)
                                    |                      |
                                    +------> db.py(SQLite) <+
```
`server.py` 通过 `from api import app` 复用 Flask 实例，再挂 `SocketIO(app)`。

⚠️ **`eventlet.monkey_patch()` 必须在文件最前面、所有 import 之前**（现在在第 4~8 行）。
它下面一旦有人 import 了会建线程/套接字的标准库，后台任务（掉线宽限 30s、连锁超时 10s）就会阻塞 hub。
**新增 import 一律排在它之后。**

---

## 3. 游戏流程

```
state: waiting → placing_ships → rock_paper_scissors → attacking → game_over
phase:                        preparation → battle → end
```
- 各摆 6 艘单格船；猜拳定先手（先手抽 1 张、后手 2 张）；攻击次数 = **存活船数 − 冻结船数**；击沉对方全部船即胜。
- `TURN_TIMEOUT_SECONDS`（默认 90，0=关）：超时只做保底动作（进战斗 / 随机开火 / 交回合），**不判负**，每次有效操作重新计时。

---

## 4. 关键数据结构（`server.py`）

| 类 | 关键点 |
| --- | --- |
| `Position` | `x,y,hit,ship_sunk,is_sulfur,is_bomb,is_splash`；`__eq__` 支持与 dict 比 |
| `PlayerShip` | `positions, hits, invincible, shield, frozen`。**存活判据 = `len(hits) < len(positions)`** |
| `Player` | `name, user_id, sid, ships, attacks, remaining_ships, magic_hand, effect_flags, sunken_ships, revealed_positions, max_ships, magic_blocked` |
| `GameRoom` | 见下 |
| `RoomManager` | `rooms`；`match_queue` 是**单结构 dict 列表** `{'sid','name','user_id','mode'}`（**不是**平行数组） |

`GameRoom` 要点：`state/current_phase/round/winner/current_attacker/attacks_remaining`；
`field_magic`（⚠️ 存**卡牌实例对象**，取值用 `field_magic_name(room)`）；
`magic_deck`（双方共用一副）/`magic_discard`/`magic_history`/`magic_temp_data`；
`chain`/`chain_window`/`chain_passes`；`game_effects`（`demon_contract`/`holy_heart`/`last_chance`/…）；
`game_logs`/`is_ai_room`/`ranked`/`shenwei_holes`；掉线宽限 `disconnect_timers`/`grace_token`。

> 攻击只有两条路径：`handle_attack`（普通）与 `_do_attack`（教皇旨意弃卡攻击）。旧的 `GameRoom.attack`
> 与 `Effect` 钩子体系**已删除**；余音绕梁/火力全开走 `EffectFlags`。

---

## 5. Socket.IO 事件名（易错，以 grep 为准）

⚠️ 常见误写：`use_magic`（实为 **`use_magic_card`**）、`end_turn_btn`（实为 **`end_turn`**）、
`confirm_reinforcement`（实为 **`confirm_reinforcement_position`**）。

- 主流程：`connect` `disconnect` `create_room` `join_room` `create_ai_room` `find_match` `cancel_match` `place_ships` `rps_choice`
- 对战：`attack` `enter_battle_phase` `enter_end_phase` `end_turn` `papal_attack` `surrender` `chat_message` `request_revealed_positions` `confirm_reinforcement_position` `cancel_placement`
- 魔法/连锁：`use_magic_card` `select_magic_target` `confirm_magic_target` `get_magic_temp_data` `get_discard_pile` `chain_response` `remove_field_magic` `confirm_shenji_declare`
- 重连：`get_reconnect_token` `rejoin_room` ｜ 另有 `request_hand_sync`（手牌自愈）
- 大厅：`lobby_subscribe` `lobby_unsubscribe` `lobby_refresh` `lobby_create_room` `lobby_chat_send` `close_room`
  （契约见 `docs/LOBBY_2026_09_18.md`；`lobby_state` 是**广播**，没法逐人改 is_me → 前端拿 `lobby_hello.key` 自己比）
- 服务端→客户端：`game_state` `attack_result` `ships_updated` `hand_updated` `game_over` `rps_result` `match_queued` `match_canceled` `magic_chain_updated` `chain_resolved` `field_magic_updated` `game_message` `message` `error` `achievements_unlocked` `xp_gained` `rank_changed`
- ⚠️ 12 个**调试事件**（`test_win_game` / `test_get_game_state` / `test_set_opponent_ships` …）全部带
  `@_test_event`，未设 `ENABLE_TEST_EVENTS=1` 时一律拒绝。**它们没有 `_identity_ok`** —— 一旦为调试打开就是完全敞开的。
- ⚠️ `test_win_game` **只设 state/winner 再 emit，不调 `_finalize_match`** —— 用它验"打完一局给分"会
  "成功但毫无反应"。真结算走**炮击击沉 / 投降 / 掉线判胜**。

---

## 6. 身份鉴权（关键陷阱）

`room.players` 的 key 有两套约定：
- 自定义房 / 人机房：登录用户 = `session['user_id']`；游客 = 入座时的 `request.sid`。
- **匹配房**：**一律是入队时的 socket sid**（真实 user_id 只存 `Player.user_id`）。
  ⚠️ 客户端自己的 `sio.sid` 与它**不一定相同** → 一律用服务端下发的 `player_id`。

`_identity_check(room, claimed, server_pid, sid)`（① 登录态 claim == session ② 座位登记的 sid == 当前连接）；
`_identity_ok` 在**无请求上下文**时跳过连接校验（为单测留的口子，不是漏洞）。

⚠️ **在别人的 socket 请求里重放另一个玩家的操作会被身份校验拦下** → 症状是"服务端状态已清、阶段却不动、
双方零提示"。代他人重放 handler 必须先用 `socketio.start_background_task` 脱离请求上下文。

---

## 7. 魔法卡

- **48 条 / 46 唯一卡名**（`失灵！` ×3 是**故意的**，`draw_card` 去重对它特例放行）；速阶 1=17 / 2=15 / 3=16；
  类型：普通 43 + 场地 4（恶魔契约 / 禁忌果实 / 伊甸园 / 教皇旨意）+ 判定 1（命运骰子）。
- 核心分发 `apply_magic_effect(room, caster_id, card, target_data)`（约 1240 行，42 处 `card.name ==`）。
- ⚠️ **改卡要同步 4 处**：`static/magic_card.json`、`static/magic_cards.js`、`apply_magic_effect` 分支、测试。
  前两者须逐字符一致（一致性测试不校验 `description`，需人工留意）。
- 目标选择：前端 `confirmMagicTarget({target_area|target_line|ship_indices|…})` → `use_magic_card` → 服务端读
  `target_area {x1,y1,x2,y2}`（神威/冻结/探测雷达）与 `target_line {type:'row'|'col',index}`（轰炸）。

---

## 8. 连锁引擎（已实现，不是设计稿）

栈 = `room.chain: list[ChainItem]`（每项带 `negated`），LIFO 结算，响应窗口 10 秒；
关键函数 `_can_respond_chain` / `_advance_chain_window` / `resolve_chain` / `_schedule_chain_timeout` / `chain_response`。
⚠️ 两处**有意**偏离 `docs/CHAIN_ENGINE_SPEC.md`：① negated 项仍执行"贴了再拆"（避免凭空消失）；
② `平等条约` 不走 `negate_target`，改读 `game_effects['last_ship_change']` 快照回滚。**别照那份文档改回去**（它 §4 列的僵尸代码已清空）。

---

## 9. 掉线重连 & 人机

- 掉线宽限 30 秒；`_build_room_sync` 是重连快照（33 字段，含 chain / 放置流程 / `opponent_attacks` / `ranked`）。
  ⚠️ **`disconnect` handler 内不能同步 emit**（会卡死 hub），代码里有注释。
- 人机：AI id = `'ai-'+room_id`，`room.is_ai_room=True`，三档 `ai_difficulty` ∈ easy（只炮击）/ normal（每回合一张安全卡）/
  hard（还会用「失灵！」响应连锁）。⚠️ AI 出牌白名单不是随便扩的：桃园结义 / 明智埋葬 / 神机妙算 / 仁王之盾 /
  灵气复苏 / 增援 / 死者苏生 / 绝处逢生 都会等施法者自己点选，AI 打出去会把回合卡死 ——
  要加卡先过 `tests/test_ai_magic.py::test_ai_safe_card_leaves_no_pending_state`。

---

## 10. 踩过的坑（值得记的结论，细节在各 docs）

1. **同一个业务判断有两份实现就一定会漂移**：放置合法性、攻击次数、段位曲线都栽过。
   同一形状再犯一次：`effect_flags` 的回合清理有常量 + `end_turn` 内联两份白名单，注释还指着常量 →
   新标记两边都没登记，换回合时**无声消失**（绝处逢生的"击杀即胜"只活一个回合）。
   → 规则只留一份（`ranks.py`/`leveling.py`/`achievements.py` 就是为此存在），前端只渲染。
   删不掉的镜像（选船优先级要给前端置灰用）必须**用测试钉住两张表**（`test_ship_pick_mirror.py`）：
   命运骰子只登记了服务端、漏了前端镜像 → **不报错**，只是有待选时那张卡不置灰、点了才被拒。
2. **"会兜底"的取数函数不能当判据**：拿 `_match_started_at`（无打点时退回 `created_at`，**恒非 0**）当
   "开没开打"的门禁 = 没门禁 → 赛前投降能刷分。同形状还坑过壁纸批（兜底挑到 `preview.jpg` 冒充动态壁纸）。
3. **"先清空再填充"的渲染必须先校验数据、失败时保留上一帧**（`updateHandUI` 清空后没填回来 → 空白手牌）。
4. **"已做过某事"的记录只在事情真的发生时才写**：把"动作"当"结果"记进 `attacks` → 盾挡下的格子被永久锁死。
5. **取数顺序是命门**：连胜/连败必须在 `record_match` **写库之前**取，否则读到含本局的值（首胜白拿连胜加成）——**不报错**。
6. **模块级函数不许引用函数作用域里的东西**（一天踩过两次 → `ReferenceError` 被 `.then()` 吞掉、页面零提示）。
7. **恒等式断言拦不住"方向写反"**：`base+Σ==total` 全绿，但判据写反会让每局败仗白送 10 分 → 要补显式守卫。
8. **统一入口之后必须反查"还有谁在渲染同一份东西"**：`game.js` 里藏着第二套个人信息渲染，
   靠 **grep 渲染出来的文案**（`当前连胜`）翻出来，比 grep 函数名有效。
9. **改共用函数先 grep 出全部调用点、按 kind 逐个表态**（改放置口径时绝处逢生被漏掉 → 六格全灰点不动）。
10. **白名单与黑名单永远不许有交集**（`allowed` 必须从 `blocked` 里剔除）。
11. **新增房间级状态要三件齐**：`__init__` 初始化 + 明确消费点 + 回归用例；
    分支里**别随手 `return`**（会静默吞掉后续收尾：换人 / 重置阶段 / 广播 —— 同形状栽过三次）。
12. **隐私过滤只有服务端拦得住**：前端断言会假绿（前端看到开关就提前 return、压根不拉数据），
    必须**以别人的身份直读接口**、且**两侧都断言**。
13. **"解锁/开关"类逻辑最容易"看着有、其实永远不触发"**：段位外观曾经因为解锁上下文里**少注入一个
    `rank_tier`**，判定一律按 0 段位算 → 一件都解不开，而接口/前端/测试**全都不报错**。
    → 加此类功能时，**必须有一条"到段位就该解锁"的端到端断言**（走真接口，不是只测纯函数）。
14. **给已存在的老表加列只能"判存在再加"**：`CREATE TABLE IF NOT EXISTS` 对已有表是空操作，
    必须 `PRAGMA table_info` + `ALTER TABLE`（`_add_column_if_missing`），失败只记日志不外抛。
15. **工具假红先怀疑工具**：残留无头进程会让新浏览器静默起不来；`Page.navigate` 后 `readyState` 可能还是旧文档；
    弹窗可见 ≠ 内容就绪；持久 profile 带着上轮 localStorage；后台标签页的 `setInterval` 被节流。
16. **"自动过期"兜底的资源要问一句"过期之前它一直挂在谁眼前"**：等待房 TTL 是 1 小时、大厅又只按
    "房主仍在线"过滤，而房主就是他自己 → 连点「创建房间」在大厅堆出 **7 间同名房**。
    治本是"一人同时只能主持一间 + 给玩家一个主动解散的出口"，不是调小 TTL。
17. **在线表只能有一份**：旧的裸 sid 集合没有名字，想补名字就会长出第二份在线结构 → 直接删掉旧表，
    `/api/online_count` 与大厅统一读 `lobby_manager.presence`。
18. **删/改 CSS 前先 grep 类名**：远程一次重构把帮助页整节样式删掉，而 `index.html`/`game.js`/检查工具
    都还在用那些类 → **功能还在、样式没了**，且检查工具只验溢出，照样全绿。合并时已恢复（第 30 节）。
19. **`python server.py` 启动时模块名是 `__main__`** → **任何模块都不许在运行期 `import server`**：
    那会把整个 server.py 再执行一遍成**另一个模块对象**，那份 `socketio` 发不出事件（**静默丢弃**，
    接口照样回 ok）、那份 `room_manager` 建的房在真进程里不存在；而生产是 `run_prod.py` 起的、
    模块名正常 → **本地坏、线上好**。跨模块能力一律由 server.py 在 import 期**注入模块对象**、
    调用时按名字现取（注入**函数对象**会把测试里所有 monkeypatch 静默架空）。
    ⚠️ 这类 bug **pytest 永远测不到**（pytest 里 server 就叫 `server`、是同一份），守卫只能是**源码级**断言。
20. **判据的输入必须来自同一套 id 空间**：反作弊第一版拿 `matches.winner_id`（**user_id**）去对齐
    日志 `detail.attacker`（**socket sid**）——永远不相等 → 在已知 166 局作弊上**召回率 0%**，
    而 26 条单测**全绿**。→ **单测全绿 ≠ 规则有效，必须在真实标注数据上量召回率**。
21. **"未知"不能退化成"满足条件"**：回合数取不到默认 0，而判据写 `rounds <= 1` →
    老格式日志全被误判。未知一律用 `-1`，判据写 `0 <= rounds <= 1`。
22. **刷分会随清理而迁移**：清完 3 个团伙，对方当天**新建 3 个小号**继续刷。
    → **清历史只是补救，实时闸门才是治本**（反作弊判据必须接进 `_finalize_match`）。
23. **"看着在拦，其实把正常功能一起关掉了"最危险，而且不报错**：匹配规避一作用于
    回环地址，所有本机/内网配对都被降权 → `room.ranked=False` → **排位分静默全部不结算**
    （页面照常开局、接口照常返回）。→ 规避类规则先问"**误伤面**有多大"，
    回环/私有地址必须归一成"不判定"。守卫见 `test_match_guard.py`。
24. **不能把函数插进"装饰器 + 它的函数"之间**：加的三个辅助函数写在
    `@socketio.on('find_match')` 与 `handle_find_match` 中间 → 装饰器注册成了错的处理器，
    37 个用例全红。新增辅助函数一律放装饰器**之前**。
25. **`register_friend_backend(**names)` 的键是"校验清单"，不是改名映射**：
    查找用的是**调用方传的名字**去 getattr。写成别名（`admin_user_ids='真实函数名'`）
    → 拿到 None → **管理员自己也进不去**，且不报错。键必须等于真实函数名。
26. **环境变量只在 systemd 里**：命令行手跑脚本时 `DEBUG_ADMIN_USER_IDS` 是 None →
    `is_admin` 恒 false → **线上正常、手测假红**。验收脚本要带 env 再跑。
27. **封禁等级一律由嫌疑度推算，绝不单独存**（同 `user_xp` 只存 xp）：
    存两份迟早"分数降了封禁还在"。唯一例外是管理员手动覆盖，那必须持久化+可审计。
28. **反作弊统计不能只从 `matches` 推**：回滚工具会**删对局**，
    删证据就等于洗白嫌疑度 → 分数必须单独落表（`match_suspicion`）。
29. **单槽 = 隐藏的数据丢失**：`pending_sacrifice` 是一个 dict，被第二个请求覆写时
    **不报错**，只在先那个玩家点船时以「当前没有待牺牲的战舰」暴露。
    → 同一时刻可能有多方请求的状态，一律用**按 owner 分组的队列**
    （详见 `docs/SHIP_PICK_PRIORITY_2026_09_20.md`）。
30. **`magic_temp_data` 不是可靠的家**：它有 8 处被整体覆写 `= {}`。
    跨"玩家交互等待期"的状态必须放**房间级字段**，否则等待期间打出别的卡就把它抹掉。
31. **`selectingOnBoard` 这种裸布尔是"无主的状态"**：只说"有人在选"、不说"是谁"，
    两个模式抢同一块棋盘时后者只能静默失败 → 要记**归属**（kind + label）才能给出提示。
32. **静默 `return null` 是最贵的写法**：`picker ? picker.cleanup : null` 把"启动失败"
    抹成"什么都没发生"，玩家侧就是「点了没反应」。**失败必须带原因**。
33. **别把"偏好"当"判据"**：`match_guard` 的 `assessed`（这一对配得好不好）曾被拿去决定
    `room.ranked`（这一局给不给排位分）→ 小社区里最常见的「和刚打过的人再打一局」
    **全部静默不结算**（赢的不加分、输的不扣分，玩家以为排位坏了）。
    → **"给不给分"只看对局内容**（`anticheat` 判据）；配对偏好只影响排序。
    ⚠️ 这类 bug **纯函数测不出来**（`match_guard` 单测全绿），
    必须走**真实 `find_match`** 才钉得住（见 `test_ranked_match.py` 的两条 rematch 守卫）。

---

## 11. 开发约定

1. **不要一次读完大文件** —— 先 grep 定位。
2. **重活交子智能体**（独立上下文，不撑爆主会话）。
3. **修 bug 前先实测复现** —— 本项目静态分析已多次误报。
4. **不要用脚本做全局字符串替换**（涉及反引号与 `${}` 时尤其危险，曾静默改坏 10 处模板字符串）；
   改完立刻 `node --check` + 跑对应无头工具。
5. **⚠️ 别用 PowerShell 的 `Get-Content -Raw | Set-Content` 改 UTF-8 源码**：本机按 GBK 读写会把中文注释写成
   非法 UTF-8（`node --check` 报错、read 工具读不了）。用编辑工具，或 python 显式 `encoding='utf-8'`。
6. **改 `style.css` 之后必跑 `node tools/ui_layout_check.mjs --url …`**：它逐视口钉棋盘 300×300 / 单格 42px /
   浮窗零叠压 / 对局页一屏不滚动。视觉改动只允许动颜色/阴影/渐变/transform/opacity/动画，**不许动盒模型尺寸**。
7. **含 `position:fixed` 后代的元素不能加 `transform`/`filter`/`backdrop-filter`**
   （`.game-container`/`.game-content`/`.game-main-container`/`.screen`），否则浮窗会改以它为基准定位。
8. **跑 e2e / 工具要隔离数据库**：`BATTLESHIP_DB_PATH=.tmp/xxx.db`，别往正式库写测试数据。
9. **本机连 GitHub/PyPI 时通时断**：`bash tools/relay.sh …` 走云服务器中转；日常发布用
   `bash push.sh`（服务器当 GitHub 出入口）+ `bash deploy.sh`（拉代码 + 重启 + 健康检查）。
   本机与远端 SHA 会不一致（服务器重新 apply 补丁）→ **用 `git rev-parse HEAD^{tree}` 对比内容**；
   若分叉先 `git fetch server main:refs/remotes/server/main --force` 再 `git rebase server/main`。
10. **提交 / 推送说明只写"改了什么"**：一句话，**不写**根因分析、排查过程、验证清单、改了哪些文件，
    **也不写**账号参数调整（等级 / 段位 / 解锁 / 特权）。细节写进 `docs/` 与代码注释。
11. **⚠️ 本文件每次对话整份注入** —— 新增一条要顺手删一条同样长的旧内容；长文写 `docs/`。
12. **每批更新往 `changelog.py` 最上面加一条玩家公告**：口语、≤ 40 字、不写技术词与账号参数。
    那是玩家唯一看得到的"这次改了什么"，漏加不报错但等于没写（规矩见 `docs/UPDATES_2026_09_19.md`）。

---

## 12. 深度文档（按需读，不要全读）

`docs/DEPLOYMENT.md`（部署与事故）｜ `docs/BATCH_2_3_4_PLAN.md`（第 2/3/4 批 + 段位批 §13）｜
`docs/RANKED_2026_09_17.md`（段位系统：规则、契约、多因子计分、帮助页、实施教训）｜
`docs/PROFILE_CARD_2026_09_17.md` + `…_PLAN.md`（个人信息名片/外观）｜
`docs/BATCH_2026_09_17.md`（11 条对局缺陷）｜ `docs/DEFECT_FIXES_2026_09_13.md`（全量缺陷审计）｜
`docs/PRIORITY_PROMPT_2026_09_13.md`（阶段转换优先权）｜ `docs/HAND_DESYNC_2026_09_14.md`（手牌消失）｜
`docs/REINFORCEMENT_TIE_2026_09_14.md`（增援平局卡死）｜ `docs/SHIELD_AND_LASTSTAND_2026_09_14.md`（破盾格/绝处逢生）｜
`docs/LAST_STAND_WIN_2026_09_19.md`（绝处逢生击杀即胜的跨回合生命周期 + 真 socket E2E 的踩坑）｜
`docs/WALLPAPER_ENGINE.md`（动态壁纸）｜ `docs/STATS_AND_AI_RANKING_FIXES.md`（战绩弹窗/人机统计）｜
`docs/MOBILE_ADAPTIVE_LAYOUT.md`（移动端布局）｜ `docs/UI_REVIEW_FIXES.md`（UI 审查）｜
`docs/LOBBY_2026_09_18.md`（大厅系统：契约 + 4 个实测问题）｜
`docs/FRIENDS_2026_09_18.md`（好友功能：产品判断 / 接线陷阱 / 契约）｜
`docs/UI_REBUILD_PROPOSAL.md`（UI 完全重构建议：现状体检 + 7 期路线）｜
`docs/UPDATES_2026_09_19.md`（更新公告：文案规矩 + 每批加一条）｜
`docs/SHIP_PICK_PRIORITY_2026_09_20.md`（选船优先级仲裁：单槽覆写根因 + 队列 + 教训）｜ `README.md`（用户向说明）

> ⚠️ **部署前确认环境变量**：代码新增 `os.environ.get('XXX')` 时，服务器 systemd 必须同步配置 ——
> 漏配会导致"服务能起来但带着错误默认值运行"（曾因漏配 `CORS_ORIGINS` 让线上所有操作卡十几秒）。
