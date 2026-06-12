# 战舰游戏（Battleship + Magic Cards） Code Wiki

> 一个基于 Flask + Flask-SocketIO 的实时双人对战棋盘游戏，融合经典海战棋玩法与魔法卡/场地效果系统，支持玩家注册登录、战绩记录与排行榜。

---

## 1. 项目整体架构

### 1.1 技术栈

| 层级        | 技术 / 库                                              | 说明                                     |
| ----------- | ------------------------------------------------------ | ---------------------------------------- |
| 后端框架    | `Flask >= 2.0.0`                                       | 轻量级 Web 框架                         |
| 实时通信    | `Flask-SocketIO >= 5.0.0`                              | 基于 WebSocket 的双向通信               |
| 数据存储    | `sqlite3`（标准库）                                    | 本地文件数据库（`data/battleship.db`）   |
| 密码加密    | `werkzeug.security.generate_password_hash / check_password_hash` | 用户密码存储与校验 |
| 前端        | 原生 HTML + CSS + JavaScript（无构建工具）             | SPA 风格单页，模板由 Jinja2 渲染        |
| 静态资源    | `static/` 下 CSS / JS / JSON                           | 魔法卡数据同时以 JSON 与 JS 形式提供    |

### 1.2 目录结构

```
battle_ship/
├── api.py                 # Flask 应用实例，HTTP 路由（登录、注册、排行榜、资料修改、首页等）
├── server.py              # 游戏核心：SocketIO 事件处理、游戏房间、魔法卡效果分发
├── db.py                  # 数据库 DAO：用户、对局、聊天、活跃游戏、排行榜
├── file.py                # JSON 文件读取工具（用于读取魔法卡配置）
├── requirements.txt       # 依赖清单
├── start_server.py        # Python 启动脚本（可选：自动检查依赖并启动）
├── start_server.bat       # Windows 一键启动批处理
├── CODE_WIKI.md           # 本文档
├── templates/
│   └── index.html         # 主页面：游戏界面、登录/注册弹窗、排行榜、个人信息等
├── static/
│   ├── style.css          # 全站样式（包括深色模式、棋盘、卡片、弹窗）
│   ├── game.js            # 前端游戏逻辑（棋盘、状态机、SocketIO 事件监听、UI 渲染）
│   ├── magic_cards.js     # 前端魔法卡数据（window.magicCards）
│   ├── magic_card.json    # 后端魔法卡数据（由 server.py 读入）
│   ├── music_player.js    # 背景音乐播放控制（音量、循环、列表、播放/暂停）
│   ├── socket.io.js       # Socket.IO 客户端库（本地副本）
│   ├── test_magic.js      # 前端魔法卡相关测试辅助代码
│   └── avatars/           # 用户头像图片存储目录
└── tests/
    └── test_magic_effects.py  # pytest 单元测试，覆盖核心魔法效果
```

### 1.3 运行时架构

```
┌─────────────────────────── Client (Browser) ───────────────────────────┐
│   index.html  ──►  style.css  ──►  game.js / magic_cards.js            │
│   Socket.IO Client  <───────────►  Socket.IO Server (server.py)         │
│   Fetch HTTP API  <───────────►  Flask App (api.py)                     │
└────────────────────────────────────────────────────────────────────────┘
              │
              ▼ HTTP / WebSocket (端口 5000)
┌─────────────────────────── Server ─────────────────────────────────────┐
│                                                                        │
│   Flask App (api.py)                                                   │
│     ├─ /, /register, /login, /logout                                 页面/会话        │
│     ├─ /lobby, /leaderboard                                          SPA 视图         │
│     ├─ /api/profile, /api/profile/signature, /api/profile/avatar     资料 API          │
│     ├─ /api/change_password, /api/login, /api/leaderboard            用户 API          │
│     └─ /api/online_count                                               在线人数统计     │
│                                                                        │
│   Socket.IO (server.py)                                                │
│     ├─ create_room, join_room, find_match, cancel_match             匹配 & 房间        │
│     ├─ place_ships, rps_choice, attack                               对战阶段          │
│     ├─ use_magic, select_magic_target, chain_cancel                  魔法卡 / 连锁     │
│     ├─ chat_message                                                   局内聊天          │
│     ├─ connect / disconnect                                            连接管理         │
│     └─ test_*                                                          调试事件         │
│                                                                        │
│   RoomManager ──► GameRoom  ──► Player { ships, attacks, magic_hand }  │
│                     │                                                  │
│                     └──► 阶段状态机：waiting → placing_ships →         │
│                                          rock_paper_scissors →         │
│                                          preparation → battle → end →  game_over  │
│                                                                        │
│   Database (db.py)                                                     │
│     ├─ users        (id, username, password_hash, wins, losses, streak, signature, avatar, token) │
│     ├─ matches      (id, winner_id, loser_id, timestamp)              │
│     ├─ match_logs   (match_id, logs JSON)                             │
│     ├─ active_games (user_id, room_id, updated_at)                    │
│     └─ chat_messages (id, user_id, username, content, timestamp)      │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 游戏流程（阶段状态机）

每个 `GameRoom` 都有一个显式的 `state` 字段和一个更细粒度的 `current_phase` 字段。

1. **waiting**：玩家加入房间 / 匹配等待。
2. **placing_ships**：双方各放置 6 艘战舰。
3. **rock_paper_scissors**：猜拳决定先手。先手抽 1 张牌，后手抽 2 张。
4. **attacking**：主战斗阶段，内部可再细分：
   - **preparation（准备阶段）**：玩家可使用速度阶 1 的魔法卡。
   - **battle（战斗阶段）**：正常攻击、使用速度阶 2 的魔法卡、命中后结算。
   - **end（结束阶段）**：结算延迟效果（如“极限增援”“无暇圣心”）。
5. **game_over**：有一方剩余战舰为 0 或触发立即胜负的魔法效果。

**攻击次数规则**：默认 `attacks_remaining = 当前攻击者的 remaining_ships`，可被魔法卡修改。

---

## 3. 关键后端模块与类

### 3.1 `api.py`

- **`app = Flask(__name__)`**：全局 Flask 应用，模板目录 `templates/`，静态目录 `static/`。
- **HTTP 路由**：
  - `/`：首页，渲染游戏入口。
  - `/register`, `/login`, `/logout`：用户注册 / 登录 / 登出。
  - `/lobby`, `/leaderboard`：SPA 视图，由前端根据状态渲染。
  - `/user_stats`：查询指定 username 的战绩。
  - `/api/profile`：获取当前登录用户资料。
  - `/api/profile/signature`（POST）：修改个性签名。
  - `/api/profile/avatar`（POST，multipart/form-data）：上传头像图片，保存到 `static/avatars/<uid>_avatar.<ext>`。
  - `/api/change_password`（POST）：修改密码，校验原密码后更新 `password_hash`。
  - `/api/leaderboard`：返回排行榜 JSON，按胜场 / 最长连胜排序。
  - `/api/online_count`：返回当前在线人数（由 `server.py` 维护的 `online_users` 集合大小）。
  - `/api/login`：基于用户名 + 密码 Hash 的 token 登录接口（调试/扩展用途）。

### 3.2 `db.py`

数据访问层，核心类 `Database`，并在模块级初始化单例 `db = Database()`。
同时提供与类方法同名的顶层函数封装，兼容旧代码调用 `db.get_user(...)` 或直接 `get_user(...)`。

**数据库表**：

| 表              | 用途                                                     |
| --------------- | -------------------------------------------------------- |
| `users`         | 用户账号：`id, username, password_hash, wins, losses, current_streak, longest_streak, created_at, signature, avatar, token` |
| `matches`       | 对局记录：`id, winner_id, loser_id, timestamp`          |
| `match_logs`    | 对局详细日志（JSON 序列化）                              |
| `chat_messages` | 聊天消息                                                 |
| `active_games`  | 当前进行的对局（`user_id, room_id, updated_at`）         |

**关键方法**：

- `create_user(username, password_hash) → uid`：创建新用户，返回 UUID。
- `get_user(uid="", username="") → dict | None`：按 id 或用户名查询。
- `update_user(uid, **kwargs) → bool`：通用更新字段。
- `update_user_signature / avatar / password_hash`：专用更新方法。
- `record_match(winner_id, loser_id, logs=None) → bool`：
  - 记录胜负；
  - 更新胜场 +1、败场 +1；
  - 维护 `current_streak`（胜方 +1 / 败方归零）与 `longest_streak`。
- `get_match_history(uid, limit=20)`：返回用户参与过的对局。
- `_get_leaderboard(limit=10)` / `get_leaderboard(limit=10)`：按胜场与最长连胜排序。
- `get_token_by_password(username, password_hash)`：生成并保存 token。
- `clear_temp_data()`：清空 `active_games` 与所有 token（重启时）。

**视图**：`match_history`（JOIN users + matches + match_logs）便于前端一次性查询。

**日志**：使用 `logging` 模块，写入 `data/db.log` 并输出到控制台。

### 3.3 `file.py`

- `read_json(filepath: str) → list | dict`：打开 UTF-8 JSON 文件并反序列化，供 `server.py` 读取魔法卡配置。

### 3.4 `server.py` — 游戏核心（重点）

#### 顶层结构

```python
online_users = set()                             # 在线 socket.sid 集合
magic_cards = read_json('./static/magic_card.json')  # 魔法卡数据库（后端使用）
socketio = SocketIO(app, cors_allowed_origins="*")
room_manager = RoomManager()                     # 全局房间管理器实例
```

#### 核心类

**`Position`**：棋盘格子
- 字段：`x, y, hit, ship_sunk, is_sulfur, is_bomb, is_splash, round`
- `__eq__` 重载：支持与 `{'x':..., 'y':...}` dict 比较。

**`PlayerShip`**：玩家单艘战舰
- `positions: list[Position]`
- `hits: list[Position]`
- 其他运行时状态：`invincible`（无敌）、`shield`（盾牌）

**`MagicCard`**：魔法卡定义
- `name, speed, type, description`
- 构造时若只提供 `name`，会在 `magic_cards` 列表中查找补全其余字段。

**`CateredMagicCard`**：玩家正在使用的一张魔法卡
- `caster_id, card, target_data`

**`EffectFlags`**：玩家级效果标志
- `treasure_hunter, prediction, subsidy, no_draw, forced_kill, vampire, last_stand, double_attacks, battle_spirit`

**`Effect`**：Room 级效果（用于 `before_attack / after_attack` 钩子）
- `name, phase, end_phase, priority, func`

**`Player`**：玩家状态
- `name, user_id, sid`（身份）
- `ships, attacks, remaining_ships`（棋盘 / 攻击记录）
- `magic_hand: list[MagicCard]`（手牌）
- `effect_flags: EffectFlags`（当前生效效果标记）
- `damage_dealt_this_turn`（用于"五险一金"等判定）

**`GameRoom`**：单个对局
- `id, players, state, round, winner`
- **魔法卡系统字段**：`field_magic`（当前场地魔法）、`magic_history`、`magic_deck`（共享牌堆）、`magic_discard`（弃牌堆）、`last_magic`、`pending_magic`、`magic_temp_data`
- **连锁系统**：`chain, chain_waiting, chain_timer`
- **效果钩子**：`effects: list[Effect]`，用于 `before_attack / after_attack`
- **方法**：
  - `init_player_magic(player_id, magic_cards)`：初始化牌堆 / 手牌
  - `draw_card(player_id)`：从共享牌堆抽卡；受 `no_draw` 限制；避免重复卡（自动丢入弃牌堆）
  - `discard_card(player_id, card)`：把手牌丢进弃牌堆
  - `pop_effect(name)`, `apply_effect(end_phase)`：添加 / 移除效果钩子
  - `attack(target, attacker_id="", enable_effects=True)`：执行一次攻击 + 效果结算 + 触发 game_over 判断

**`RoomManager`**：多房间管理
- `rooms: dict[str, GameRoom]`：所有房间
- `match_queue, lobby_members` 等状态
- 方法：
  - `create_room() -> id`
  - `join_room(room_id, player_id, ...) -> bool`
  - `get_room(room_id)`
  - `delete_room(room_id)`
  - `add_to_match_queue / remove_from_match_queue`
  - `process_match_queue(magic_cards)`：批量匹配，创建房间、初始化双方玩家、初始化魔法卡

**辅助数据类**：

- `GameLog(text, event_type, payload=None)`：对局内事件日志。
- `RPSResult(status, message, winner, loser, choices, order)`：猜拳结果。
- `AttackResult(attacker, x, y, hit, ship_sunk, remaining_attacks, attacker_remaining_ships, defender_remaining_ships)`：攻击结果，用于向客户端广播。
- `ChainItem(player_id, card, targets, timestamp)`：连锁栈条目。
- `ChainResult(card, caster, success, message)`：连锁结算结果。

#### 魔法卡效果分发

核心函数（位于 `server.py`）：

```python
def apply_magic_effect(room, player_id, card, target_data):
    """
    根据 card.name 派发不同的魔法处理逻辑。
    返回 { 'success': bool, 'message': str, 'affected_positions': [...], ... }
    """
```

主要处理的卡牌类型：

- **反制**：失灵！、看破！、加百列之光、平等条约
- **攻击增强**：溅射、雷达子弹、越战越勇、饮血、余音绕梁、火力全开、Freezing！
- **区域伤害**：神威！、硫磺火焰、轰炸、冻结、探测雷达
- **场地魔法**：禁忌果实、教皇旨意、伊甸园、恶魔契约
- **复活/恢复**：死者苏生、疗愈、桃园结义、仁王之盾、钢筋铁骨
- **胜利条件**：绝处逢生、回光返照、无暇圣心、极限增援
- **资源调度**：增援、无中生有、明智埋葬、盗亦有道、克苏鲁之眼
- **对局重置/调整**：灵气复苏、败者食尘、百亿补贴、五险一金、神之宣告、神机妙算

每张卡的详细效果请参考 `static/magic_card.json` 与 `static/magic_cards.js`（文本描述一致）。

#### Socket.IO 事件清单

| 事件                        | 方向       | 说明                                              |
| --------------------------- | ---------- | ------------------------------------------------- |
| `connect / disconnect`      | 客户端→服务端 | 加入 / 离开 `online_users`                        |
| `create_room`               | 客户端→服务端 | 创建自定义房间                                   |
| `join_room`                 | 客户端→服务端 | 加入指定房间（房间满后进入 placing_ships）        |
| `find_match / cancel_match` | 客户端→服务端 | 匹配队列                                         |
| `place_ships`               | 客户端→服务端 | 提交己方 6 艘战舰坐标                             |
| `rps_choice`                | 客户端→服务端 | 提交石头 / 剪刀 / 布                             |
| `attack`                    | 客户端→服务端 | 普通攻击一个格子                                 |
| `use_magic`                 | 客户端→服务端 | 使用一张手牌（根据 card.speed 触发连锁或即时效果） |
| `select_magic_target`       | 客户端→服务端 | 提交魔法卡目标选择（桃园结义、埋葬、仁王之盾等） |
| `enter_battle_phase / enter_end_phase / end_turn_btn` | 客户端→服务端 | 阶段切换 |
| `chat_message`              | 双向       | 房间内聊天                                       |
| `test_*`                    | 双向       | 调试接口（添加魔法卡、清效果、查看状态）         |
| `game_state`                | 服务端→客户端 | 推送最新阶段、玩家状态、remaining_ships           |
| `attack_result`             | 服务端→客户端 | 推送一次攻击的命中、击沉与剩余攻击次数            |
| `ships_updated`             | 服务端→客户端 | 双方船数变化                                     |
| `hand_updated`              | 服务端→客户端 | 手牌更新                                         |
| `game_over`                 | 服务端→客户端 | 游戏结束，包含 winner                            |
| `error / message`           | 服务端→客户端 | 错误与提示消息                                   |

#### 工具函数 `emit(event, data, to=None, room=None)`

封装了 `socketio.emit`，在发送前使用 `json.dumps(..., default=lambda o: o.__dict__)` 将任意对象安全转换为 JSON。

### 3.5 `tests/test_magic_effects.py`

基于 `pytest` 的单元测试，通过 `monkeypatch` 替换 `server.emit` 捕获事件，直接构造 `GameRoom` 与玩家，调用 `apply_magic_effect` 后断言结果。

- `make_room()`：构造最小可用房间。
- `test_splash_returns_affected_positions`：验证"溅射"返回受影响格子列表。
- `test_bomb_returns_affected_positions`：验证"轰炸"选择一行 / 一列后受影响格子。

---

## 4. 前端模块（JavaScript）

### 4.1 `templates/index.html`

- **结构**：单页应用风格，通过 `screen` 元素的 `active` 类切换不同视图：
  - `start-screen`：输入昵称、匹配 / 自定义房间入口
  - `custom-room-screen`：自定义房间 ID 输入 / 展示
  - `ship-placement-screen`：放置战舰
  - `rps-screen`：猜拳
  - `game-screen`：主游戏界面（双方棋盘 + 魔法卡 + 日志 + 聊天）
  - `lobby-screen`：大厅（未深度使用）
  - `leaderboard-screen`：排行榜
  - `game-over-screen`：胜负结算
- **模态弹窗**：登录、注册、个人资料、对局详情、帮助、设置、弃牌堆查看、对手战绩等。
- **脚本加载顺序**：`magic_cards.js → 注入 username → game.js → test_magic.js → music_player.js`。
- **背景动画**：`<canvas id="particle-canvas">` 实现粒子雨（蓝色半透明圆）。
- **在线人数轮询**：`fetch('/api/online_count')` 每 10 秒刷新一次。
- **深色模式**：切换 `html.theme-dark`，保存到 `localStorage.theme`。

### 4.2 `static/game.js`

- **状态**：维护本地房间 ID、玩家 ID、棋盘渲染状态、魔法卡手牌、当前阶段 UI。
- **Socket.IO 连接**：所有与 `server.py` 的事件交换都在此封装。
- **关键函数（按职责分）**：
  - `init()`：DOM 事件绑定、Socket.IO 事件监听入口。
  - `initParticles()`：Canvas 粒子动画。
  - `switchScreen(screenId)`：切换不同视图屏幕。
  - `renderBoard(boardElement, player, opponentView=false)`：渲染 6x6 棋盘，根据是否对方视角显示未命中格子为空白。
  - `placeShip(x, y)`：放置战舰到指定格子。
  - `handleAttackResponse(data)`：处理一次攻击的返回，更新命中状态。
  - `renderHand(hand)`：渲染玩家手牌，点击选中后进入"待使用"状态。
  - `useMagicCard(card)`：向服务端发送 `use_magic` 事件。
  - `openMagicTargetSelector(card)`：对需要额外目标选择的卡（如桃园结义、仁王之盾、明智埋葬、轰炸、冻结等）显示交互弹窗，收集目标后发送 `select_magic_target`。
  - `enterBattlePhase() / enterEndPhase()`：向服务端发送阶段切换事件。
  - `changePassword`、`updateProfile`、`loadLeaderboard`、`loadUserStats` 等用户功能。

### 4.3 `static/magic_cards.js`

```javascript
window.magicCards = [
    { name: "失灵！", speed: 3, type: "普通", description: "..." },
    ...
];
```

作为前端渲染与测试用的数据源，与 `static/magic_card.json` **必须保持一致**。

### 4.4 `static/music_player.js`

基于 HTML5 `<audio>` 的简易多轨播放器，提供：
- 播放 / 暂停 / 上一首 / 下一首
- 音量滑块、循环模式（单曲 / 全部 / 不循环）
- 播放状态持久化（localStorage）
- 默认曲目列表在脚本末尾以数组形式定义，如 `static/music/...`

### 4.5 `static/style.css`

- 基于 CSS 变量的主题：`--primary, --bg, --fg, --muted, --danger`
- `.theme-dark` 覆盖变量实现深色模式
- `.board / .cell / .ship / .hit / .miss`：棋盘相关样式
- `.btn`：主按钮样式
- `.modal-overlay / .modal-content`：通用弹窗样式
- `.magic-card`：魔法卡卡片排版
- `.reinforcement-countdown / .holy-heart-countdown`：倒计时提示

---

## 5. 关键数据结构与示例

### 5.1 一艘战舰（JSON 序列化后）

```json
{
  "positions": [{"x": 3, "y": 2}],
  "hits": [],
  "invincible": false,
  "shield": false
}
```

### 5.2 一次攻击结果（服务端→客户端）

```json
{
  "attacker": "player-uuid",
  "x": 3,
  "y": 2,
  "hit": true,
  "ship_sunk": true,
  "remaining_attacks": 4,
  "attacker_remaining_ships": 5,
  "defender_remaining_ships": 3
}
```

### 5.3 魔法卡

```json
{
  "name": "神威！",
  "speed": 2,
  "type": "普通",
  "description": "选定己方或对方 3x3 区域，暂时除外所有战舰……"
}
```

---

## 6. 依赖关系

### 6.1 Python 依赖

`requirements.txt`：

```
Flask>=2.0.0
Flask-SocketIO>=5.0.0
Werkzeug>=2.0.0
```

### 6.2 模块依赖图

```
api.py ──► db.py
           ▲
           │
server.py ─┴─► file.py ──► static/magic_card.json
      │
      └─► static/
         ├─ magic_cards.js  (前端魔法卡数据, 与 magic_card.json 同步)
         ├─ game.js         (前端游戏逻辑)
         ├─ style.css       (样式)
         ├─ music_player.js (背景音乐)
         └─ socket.io.js    (Socket.IO 客户端)

templates/index.html ──► 渲染时引用以上所有 static/ 文件
tests/test_magic_effects.py ──► server.py (通过 import server)
```

**同步约定**：`static/magic_card.json` 与 `static/magic_cards.js` 中卡牌数据应始终保持同一版本（名称、速阶、类型、描述一致）。后端由 `server.py` 读 JSON，前端由 `magic_cards.js` 定义 `window.magicCards`。

---

## 7. 启动与运行方式

### 7.1 安装依赖

```bash
pip install -r requirements.txt
```

### 7.2 启动服务器

**Windows 一键启动**：

```bat
start_server.bat
```

**或手动启动（推荐开发时）**：

```bash
set FLASK_APP=server.py
python -m flask run --host=0.0.0.0 --port=5000
```

**或使用 Python 启动脚本**：

```bash
python start_server.py
```

启动后：
- 主页面：http://localhost:5000/
- 登录 / 注册：页面顶部导航；游客也可直接"匹配游戏"或"自定义房间"。
- 首次启动会自动创建 `data/battleship.db` 并创建所有表。

### 7.3 运行测试

```bash
pip install pytest
pytest tests/
```

`tests/test_magic_effects.py` 会直接导入 `server` 模块并测试 `apply_magic_effect` 的纯逻辑。

---

## 8. 开发与调试提示

- **在线人数**：`GET /api/online_count`，数据维护于 `server.online_users` set（socket.sid）。
- **魔法卡调试**：`server.py` 注册了一组 `test_*` Socket 事件，可直接在浏览器控制台通过 `socket.emit('test_add_all_magic_cards', {...})` 快速测试。
- **日志**：`data/db.log` 与 `logging` 模块统一管理；对局中重要事件通过 `GameLog` 写入 `room.game_logs`，最终在对局结束时保存到 `match_logs.logs`（JSON）。
- **头像存储**：图片保存到 `static/avatars/<uid>_avatar.<ext>`，数据库只存 URL 路径。
- **`.gitignore`**：已忽略 `*.db`、`avatars/`、`*.mp3`、`*.log`、Python 缓存等。

---

## 9. 模块索引（快速跳转）

| 文件                                                        | 职责                              |
| ----------------------------------------------------------- | --------------------------------- |
| `api.py`                                                    | Flask 路由、账户、资料、排行榜     |
| `server.py`                                                 | 游戏主循环、SocketIO 事件、魔法效果 |
| `db.py`                                                     | SQLite 数据访问层                  |
| `file.py`                                                   | JSON 读取工具                      |
| `templates/index.html`                                      | 主页面 SPA 模板                    |
| `static/game.js`                                            | 前端游戏逻辑 / UI 渲染             |
| `static/magic_cards.js`                                     | 前端魔法卡定义                     |
| `static/magic_card.json`                                    | 后端魔法卡定义                     |
| `static/style.css`                                          | 全站样式                           |
| `static/music_player.js`                                    | 背景音乐控制                       |
| `tests/test_magic_effects.py`                               | 魔法卡效果单元测试                 |
| `start_server.bat` / `start_server.py`                      | 启动脚本                           |
| `requirements.txt`                                          | 依赖清单                           |

---

> 维护者注：当新增 / 修改魔法卡时，需要同步：
> 1. `static/magic_card.json`（服务端使用）
> 2. `static/magic_cards.js`（前端使用）
> 3. `server.py` 中 `apply_magic_effect` 内对应分支
> 4. 必要时补充 `tests/test_magic_effects.py`
