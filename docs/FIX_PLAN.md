# 战舰游戏修复方案（FIX PLAN）

> 制定日期：2026-09-11 ｜ 依据：`docs/PROJECT_DEFECT_ANALYSIS.md`（所有缺陷均已实测核实）
> 原则：先止血后重构；每项修复必须配回归测试；遵守项目约定（改卡同步 4 处、`失灵！`×3 是故意的、`field_magic` 存实例对象、修前实测复现）。

---

## ✅ 修复执行记录（2026-09-11）

除 Phase 3 的架构级重构（3.1 统一攻击路径 / 3.2 模块拆分 / 3.3 卡牌数据源 / 3.4 对局持久化）外，以下项目已全部落地并通过全量测试（**163 passed**，新增 `tests/test_fixes_regression.py` 19 个回归用例）：

**Phase 0 安全止血**
- index.html 移除 test_magic.js；12 个 `test_*` 事件加 `_test_event` 装饰器，默认关闭（`ENABLE_TEST_EVENTS=1` 启用）
- `SECRET_KEY` → 环境变量 + 随机兜底；`FLASK_DEBUG` 默认关；`CORS_ORIGINS` 默认仅本地；`PORT` 可配置
- requirements.txt 锁版本并补 eventlet / python-socketio / python-engineio / pytest

**Phase 1 功能修复**
- 游客匹配：配对算法重写（跳过同账号记录而非回队重试——同时消除了原实现潜伏的死循环）
- surrender 补 `_identity_ok`；「盗亦有道」改为"转移"（从弃牌堆移除 + 历史条目标记 stolen）
- getRPSName 映射修正；`showDivineDecreeChoice` 兜底改造：出牌前弹选择框（`promptDivineDecreeChoice`），后端从 `targets.effect_choice` 读取，「跳过对方回合」分支恢复可达
- `#effect-indicators` 容器 + 样式补齐，JS 侧判空兜底
- 房间泄漏：后台 reaper（`_reap_ended_rooms`，宽限 120s，首个连接时惰性启动）
- 布船校验（数量=max_ships、坐标 0-5、不重叠）、攻击坐标校验（不消耗次数）、魔法目标 `_sanitize_magic_targets`（use_magic_card 与 chain_response 两入口）
- db：update_user 列名白名单、5 个索引、全部写方法持锁

**Phase 2 健壮性**
- 前端 `ensureSocket()`/`onSocketReady()` 统一连接管理，10 处建连点全部收敛，杜绝孤儿 socket 与 handler 叠加
- 匹配队列改单结构列表 + `RLock`（eventlet 兼容）
- 重连快照补 chain / chain_waiting / active_effects / pending_placement（含 blocked 格子），前端 applyRoomSync 消费
- 头像上传：2MB 上限（MAX_CONTENT_LENGTH）+ 魔数校验；登录/注册/改密限流（同 IP 60s×10）；注册密码 ≥6 位；Cookie SameSite=Lax
- eventlet `monkey_patch()` 移至 server.py 首行（全量测试通过验证）

**文档同步**：README（测试数、安全注意）、CLAUDE.md（修复批记录与基线 163 passed）已更新。

---

## 修复原则与风险红线

1. **顺序不可颠倒**：Phase 0 全部完成前不要做任何重构——安全洞在重构期间持续暴露。
2. **不动 Event 体系的设计决策**：`Effect` 钩子是复活还是删除，属于 Phase 3 的架构决策，Phase 1 只做"让失效卡牌在 `handle_attack` 路径生效"的最小修复。
3. **eventlet monkey_patch 时序问题暂缓**：把 `monkey_patch()` 提到首行会影响所有导入时序，必须单独验证（放 Phase 2 末，配烟雾测试），不与其他改动混批。
4. **每批改动跑全量测试**：`python -m pytest tests/ -q`（基线 141 passed），并在根目录运行（`test_all_magic_cards.py:1088` 对 CWD 敏感）。

---

## Phase 0：安全止血（预计 0.5 天，全部小改动）

| # | 缺陷 | 位置 | 修法 | 验收 |
|---|---|---|---|---|
| 0.1 | 调试事件公网可作弊 | `index.html:492`、`server.py:635-1008` | ① 删除 index.html 中的 `<script src="/static/test_magic.js">`；② server.py 顶部加 `ENABLE_TEST_EVENTS = os.environ.get('ENABLE_TEST_EVENTS') == '1'`，12 个 `test_*` handler 首行加 `if not ENABLE_TEST_EVENTS: return`（可写一个装饰器统一处理） | 新增测试：默认配置下 emit `test_win_game` 无效；本地调试开关（不进测试） |
| 0.2 | SECRET_KEY 硬编码 | `api.py:15` | `app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)`。注释说明：未设环境变量时重启会使所有 session 失效（可接受的降级） | 部署脚本/文档补 `SECRET_KEY` 环境变量说明 |
| 0.3 | 生产 debug=True | `server.py:4733` | `debug=os.environ.get('FLASK_DEBUG') == '1'`，默认关闭 | `python server.py` 启动无 Werkzeug 警告 |
| 0.4 | requirements 缺 eventlet、未锁版本 | `requirements.txt` | 补 `eventlet`，全部改为 `==` 锁定当前实测可用版本（`pip freeze` 后人工筛选直接依赖） | 新环境 `pip install -r requirements.txt` 后 `python start_server.py` 可跑 |
| 0.5 | CORS 全放行 | `server.py:400` | `cors_allowed_origins=os.environ.get('CORS_ORIGINS', 'http://8.133.180.159:5000').split(',')`；本地开发默认含 `http://localhost:5000` | 跨域连接被拒、本域正常 |

**注意**：0.2 上线后所有在线用户 session 失效，需公告或低峰操作。

---

## Phase 1：功能性 bug 修复（预计 1-2 天）

### 1.1 游客匹配 `None == None`（P0）
- 位置：`server.py:1285`
- 修法：`if player1_user_id and player1_user_id == player2_user_id:`（登录用户按 user_id 去重，游客按 sid 天然不同，放行配对）
- 测试：新增用例——两个未登录 sid 入队后 `process_match_queue` 能配对成房。

### 1.2 surrender 加鉴权（P1）
- 位置：`server.py:4699`
- 修法：`if player_id not in room.players or not _identity_ok(room, player_id): return ...`
- 测试：在 `test_auth_spoof.py` 增加"非本座位连接不能替人投降"用例；同时**补上对 12 个 `test_*` 事件的鉴权覆盖**（Phase 0 后应测的是"开关关闭时全部无效"）。

### 1.3 盗亦有道复制卡牌（P1）
- 位置：`server.py:4503-4505`
- 修法：从对方 `magic_hand` 中按卡名移除一张（找到则 `remove`），未找到（已被连锁消耗等边界）时改为提示"对方无此卡"并不复制。语义以卡牌描述为准，需实测确认。
- 测试：盗取后对方手牌数 -1、己方 +1；重复盗取第二次失败。

### 1.4 前端文案/引用错误三连（P0-P1）
- `game.js:3320-3327`：`getRPSName` 改回 `'paper': '布', 'scissors': '剪刀'`
- `game.js:2194`：`showDivineDecreeChoice` 未定义——**先实测复现「神之宣告」结算**（项目约定），确认期望交互后：最小方案是在 `chain_resolved` handler 中加存在性守卫并去掉该调用；若需要选择 UI，则补一个简化实现（两个按钮：维持/跳过对方回合）。
- `game.js:4552`：`#effect-indicators`——在 `index.html` 对局界面补该容器元素（或 JS 侧判空跳过）。**推荐补元素**，百亿补贴等效果可视化本就是设计意图。

### 1.5 正常胜负路径房间泄漏（P0）
- 位置：所有 `emit('game_over', ...)`（server.py 1691/1824/1955/2027/2507/2539/3442/3774/4678）与 `handle_surrender`(4690)
- 修法：抽一个 `_finish_game(room_id, winner, reason)` 辅助函数：置 `state='game_over'`、记战绩、emit、统一 `socketio.start_background_task(_cleanup_ended_room, room_id, 120)`。逐点替换现有内联代码（保持消息字段不变，前端兼容）。
- 测试：新增用例——自然击沉获胜与投降后，伪造时间推进（或缩短 delay 注入）断言 `room_id not in room_manager.rooms`。

### 1.6 布船/攻击输入校验（P1，README 与代码不符项）
- `server.py:1374-1392` `handle_place_ships`：校验 `ships` 为列表、长度 == 当前 `max_ships`（默认 6）、每个坐标为 0-5 整数且互不重复。校验失败返回 error 并不落盘。
- `server.py:1700-1701` `handle_attack`：`int()` 转换 + 0-5 边界检查，越界直接返回 error（不消耗攻击次数）。
- 魔法目标 `target_area`/`target_line`：在 `handle_use_magic_card`(2549) 入口做同样的范围归一化校验。
- 测试：越界/重叠/超量布船被拒；越界攻击不消耗次数。

### 1.7 db 层快速加固（P1）
- `db.py:183` `update_user`：列名白名单 `_ALLOWED_USER_COLS = {'signature','avatar','wins','losses','current_streak','longest_streak','token',...}`，不在白名单的 key 抛 ValueError。
- 补索引（init_db 中 `CREATE INDEX IF NOT EXISTS`）：`matches(winner_id)`、`matches(loser_id)`、`matches(timestamp)`、`users(token)`、`chat_messages(timestamp)`。
- 测试：现有 141 用例全绿即可（db 改动保守）。

---

## Phase 2：健壮性加固（预计 2-3 天）

### 2.1 前端 socket 生命周期
- 位置：`game.js` 10 处 `io.connect(...)`（935/1537/1575/1595/1638/1669/1692/2937/2988/5281）
- 修法：抽 `connectSocket()`：若 `gameState.socket` 存在先 `removeAllListeners()` + `close()`，再建连并 `setupSocketListeners()`。一次性替换全部 10 处。
- 风险：断线重连逻辑（`rejoin_room` 链路）依赖旧连接的场景需手测——**必须真人双开浏览器实测一整局含掉线重连**。
- 测试：jest 或手测脚本断言旧 socket closed；最小化用自动验收脚本 `tools/` 风格。

### 2.2 匹配队列并发安全
- 位置：`server.py:479-492`（三列平行数组）及 1256-1368 全部读写点
- 修法：改单结构列表 `match_queue: list[dict{'sid','name','user_id'}]` + `threading.Lock`（eventlet 下 monkey_patched 的锁可用）；`find_match`/`cancel_match` 全程持锁。
- 测试：并发入队/取消的模拟用例；两真人匹配、取消后重新匹配的实测。

### 2.3 db 并发写保护
- 位置：`db.py` 全部写方法
- 修法（二选一，推荐 A）：
  - A：所有写方法统一 `with self._lock:`（改动小，风险低）；
  - B：改为每次操作新建连接（`with sqlite3.connect(...) as conn`），删全局 conn/cursor（改动大，彻底）。
- 同步修：token 明文 → 存 SHA-256 哈希（登录时哈希后查询）；`clear_temp_data` 不再全量清 token（token 持久化后天然不需要）。
- 测试：现有用例全绿 + 新增并发写 stats 的冒烟用例。

### 2.4 重连快照补全
- 位置：`_build_room_sync`(2858)
- 修法：补充 `chain`（仅当 `room.chain` 非空）、`magic_temp_data`、`game_effects` 摘要、若处于复活/放置流程则带 `placement_pending` 标记。前端 `rejoin_room` handler 对新字段做可选渲染。
- 验收：连锁窗口中途掉线重连，客户端能看到当前连锁栈。

### 2.5 HTTP 面加固
- `api.py`：`app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024`（头像 2MB 上限）；头像保存前读前几字节校验 PNG/JPG/GIF magic number。
- 登录/注册限流：引入简单内存计数（同 IP 60 秒 10 次）或 `flask-limiter`；`/login`、`/api/login`、`/register` 三处。
- Session Cookie：`SESSION_COOKIE_HTTPONLY=True`（默认已是）、`SESSION_COOKIE_SAMESITE='Lax'`。
- 注册密码强度：与服务端 `change_password` 对齐，≥6 位。

### 2.6 eventlet monkey_patch 时序（独立验证批）
- `server.py:11-21`：把 `eventlet.monkey_patch()` 移到文件最顶（所有 import 之前），用 `python server.py` + 一局完整对战 + 掉线重连做烟雾测试；同时在 `flask run`（无 eventlet）路径确认 ImportError 分支仍正常。**此项单独提交，出问题可单独回滚。**

---

## Phase 3：架构级重构（可选，按维护意愿决定，预计 1-2 周）

按收益排序，**每项独立分支独立验收**：

### 3.1 统一攻击路径（收益最大）
- 现状：`GameRoom.attack`(326 死代码) / `handle_attack`(1697) / `_do_attack`(2464) 三套并存，`handle_attack` 内部还有约 200 行"强制击杀 vs 普通"重复分支，已语义漂移（恶魔契约通知对象错、`==0` vs `<=0` 混用）。
- 方案：
  1. 删除 `GameRoom.attack` 与 `_chain_target_below`(2667)；
  2. `handle_attack` 抽出公共结算函数 `_resolve_attack(room, attacker, defender, x, y, forced_kill=False)`，两条分支只保留差异参数；
  3. Effect 体系二选一：**方案 A（推荐）**——把 `before_attack/after_attack` 钩子遍历移植进 `_resolve_attack`，让「余音绕梁」「火力全开」恢复生效；**方案 B**——删 Effect 类，两张卡的效果在 `apply_magic_effect` 里直接以 flags/hook 方式实现。选 A 则顺带修语义漂移的三个点。
- 验收：为余音绕梁/火力全开补"真实对局触发"测试（当前缺失）；全量回归 + 真人对战实测。

### 3.2 server.py 模块化拆分
- 拆为 `server/` 包：`rooms.py`（RoomManager/GameRoom/数据类）、`auth.py`（身份校验）、`events_flow.py`（房间/流程事件）、`events_battle.py`（攻击/回合）、`magic.py`（apply_magic_effect 及各卡分支）、`chain.py`（连锁引擎）、`reconnect.py`（掉线重连）。`apply_magic_effect` 1173 行按卡组拆分。
- 好处：修卡牌不再在 4000 行里定位；测试可按模块导入。

### 3.3 卡牌数据单一数据源
- `magic_card.json` 为唯一源，构建/启动时生成 `magic_cards.js`（或前端运行时 fetch JSON，删掉 js 副本）；一致性测试改为全字段（含 description）比对。

### 3.4 对局持久化（可选）
- 复活 `active_games` 表：每回合结束序列化房间关键字段（state/ships/hand/effects），重启时能恢复"游戏已结束"的准确态并提示玩家重开（完整热恢复成本高，可只做优雅降级）。多 worker 横向扩展依赖此项 + 房间路由粘性（单机 eventlet 场景可不做）。

### 3.5 死代码清理
- 一次性删除：`GameRoom.attack`（若 3.1 未做则此处删）、`process_match_queue`(498)、lobby 三方法(561-577)、`apply_effect`(284)、`game.js:4499` `line_attack` 链、`selectedLine` 残留。清理后更新 CLAUDE.md 行号索引。

---

## 测试补充计划（随 Phase 1/2 落地）

| 新测试 | 覆盖 |
|---|---|
| `test_test_events_disabled` | 默认配置 12 个 test_* 事件全部无效 |
| `test_guest_matching` | 双游客配对成功 |
| `test_surrender_auth` | 非座位连接无法替人投降 |
| `test_place_ships_validation` | 越界/重叠/超量被拒 |
| `test_attack_bounds` | 越界攻击不消耗次数 |
| `test_room_cleanup` | 自然胜负/投降后房间被回收 |
| `test_daoyouyoudao` | 盗卡后双方手牌数正确、二次盗取失败 |
| 一致性测试增强 | 卡牌数据比对加入 description 字段 |

**回归基线**：每批改动后 `python -m pytest tests/ -q`（当前 141 passed / 0.53s），大改动（Phase 2.1/3.x）额外做真人双开实测：完整对局一局 + 连锁响应 + 掉线重连 + 投降。

---

## 执行顺序与依赖图

```
Phase 0 (止血) ──► Phase 1 (功能修复) ──► Phase 2 (健壮性) ──► Phase 3 (重构, 可选)
   0.1-0.5 任意顺序        1.4 依赖 0.1(开关)        2.6 独立批次         3.1 依赖死代码确认
                           1.5 改 game_over 各点      2.2 依赖 1.1 修复    3.2 依赖 3.1 完成
```

- Phase 0 + 1.1 + 1.2 合为第一批提交（一次部署解决公网风险）。
- Phase 3 是否启动取决于项目定位：学习/娱乐项目建议只做 3.1 + 3.5，3.2-3.4 视维护成本决定。
