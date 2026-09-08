# ⚓ 战舰游戏（Battleship + 魔法卡）

一个基于 **Flask + Flask-SocketIO** 的实时双人海战棋网页游戏：在经典战舰玩法（布船 → 猜先 → 轮流炮击）之上，叠加了 **43 张魔法卡 / 场地魔法** 的回合制策略系统，支持账号系统、战绩排行、人机对战与自定义房间。

> 在线体验：http://8.133.180.159:5000/

---

## ✨ 功能一览

| 模块 | 说明 |
|---|---|
| 👤 账号系统 | 注册 / 登录 / 登出（Werkzeug 密码哈希）、头像上传、个性签名、修改密码 |
| 🏆 战绩排行 | 胜场/负场/连胜记录，排行榜与个人战绩查询 |
| 🎮 对战模式 | 匹配对战（自动配对）、人机对战（AI）、自定义房间（房间号邀请好友） |
| 🚢 布船阶段 | 6 格棋盘自由布船（单格船 ×6），服务端校验 |
| ✊ 猜先 | 石头剪刀布决定先手，先手先攻 |
| 💥 攻击回合 | 准备阶段 → 战斗阶段 → 结束阶段，攻击次数随存活战舰数变化 |
| 🃏 魔法卡系统 | 41 种卡（43 条目，含重复的"失灵！"）：速阶 1/2/3 与场地魔法，支持连锁响应、弃牌、目标选择 |
| 🌀 场地魔法 | 恶魔契约 / 禁忌果实 / 伊甸园 / 教皇旨意，同时仅 1 张生效，可被顶替或无效化 |
| 🔌 断线重连 | 掉线 30 秒宽限：重连恢复整局；超时判负/取消；对手掉线显示倒计时 |
| 💬 局内聊天 | 房间内实时聊天，窗口可拖拽 |

---

## 🧱 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 后端框架 | Flask ≥ 2.0 | 轻量 Web 框架 |
| 实时通信 | Flask-SocketIO ≥ 5.0 | WebSocket / 长轮询双工通信 |
| 数据存储 | SQLite（WAL 模式） | 本地文件数据库 `data/battleship.db` |
| 密码安全 | Werkzeug `generate_password_hash` / `check_password_hash` | 加盐哈希存储 |
| 前端 | 原生 HTML + CSS + JavaScript | 无构建工具，Jinja2 渲染单页 |
| 生产运行 | eventlet（线上） | 单进程协程，注意需 `eventlet.monkey_patch()` |

---

## 📂 目录结构

```
battle_ship1.0/
├── api.py                 # Flask 应用与 HTTP 路由（登录/注册/排行/资料/首页）
├── server.py              # 核心：SocketIO 事件、房间管理、游戏状态机、魔法卡结算
├── db.py                  # 数据访问层（users / matches / chat_messages / active_games / match_logs）
├── file.py                # JSON 读取工具（加载卡牌配置）
├── start_server.py        # 一键启动脚本（依赖检查 + flask run）
├── start_server.bat       # Windows 双击启动
├── requirements.txt       # Python 依赖
├── CODE_WIKI.md           # 详细代码架构文档（模块/流程/数据模型）
├── templates/
│   └── index.html         # 单页应用：游戏界面、登录注册、排行榜、设置等
├── static/
│   ├── game.js            # 前端游戏逻辑（棋盘、状态机、Socket 事件、UI 渲染）
│   ├── style.css          # 全站样式（深/浅色主题、棋盘、卡牌、响应式）
│   ├── magic_card.json    # 卡牌数据（后端读取）
│   ├── magic_cards.js     # 卡牌数据（前端读取，与 JSON 保持一致）
│   ├── music_player.js    # 背景音乐控制
│   └── socket.io.js       # Socket.IO 客户端库（本地副本）
├── tests/                 # pytest 回归测试（121 个用例）
└── tools/                 # 开发辅助脚本（截图、验收、数据修复等）
```

---

## 🚀 本地运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动

```bash
python start_server.py        # 推荐（自动检查依赖）
# 或
python server.py
# 或 Windows 双击
start_server.bat
```

浏览器打开 <http://localhost:5000> 即可。

> 若用较新版本 Werkzeug 且直接 `python server.py` 报 "Werkzeug web server is not designed to run in production"，这是 Flask-SocketIO 的显式保护。开发时可用 `flask run` 或加 `allow_unsafe_werkzeug=True`；**生产环境请用 eventlet/gevent**。

### 3. 跑测试

```bash
python -m pytest tests/ -q
```

---

## 🎮 玩法说明

1. **登录/注册** 后选择模式：匹配对战 / 人机对战 / 自定义房间
2. **布船**：在 6×6 棋盘放置 6 艘单格战舰（可点击或随机）
3. **猜先**：石头剪刀布，胜者先手
4. **回合流程**：
   - **准备阶段**：可使用速阶 1/2 魔法卡（部分场地卡）
   - **战斗阶段**：炮击对方棋盘；攻击次数 = 存活战舰数（受场地/卡牌效果影响）
   - **结束阶段**：攻击次数用尽后交出回合
5. **魔法卡**：速阶 1/2 限己方回合准备/战斗阶段，速阶 3 任意时机（含连锁响应）；场地魔法全场仅 1 张
6. **胜利条件**：击沉对方全部战舰

---

## 🃏 魔法卡系统

- **卡池**：43 条目 / 41 个唯一卡名（"失灵！"×3）
- **速阶分布**：速阶 1 = 13 张，速阶 2 = 15 张，速阶 3 = 15 张
- **类型分布**：普通 39 张 + 场地 4 张（恶魔契约 / 禁忌果实 / 伊甸园 / 教皇旨意）
- **连锁机制**：对手持有速阶 3 卡时可响应连锁（限时 10 秒，超时自动结算）
- **代表卡牌**：
  - `败者食尘`：重启对局、保留手牌，双方回到布船阶段
  - `伊甸园`：双方攻击次数变为 `6 - 自身战舰数`（每回合准备阶段结算）
  - `教皇旨意`：攻击次数归 0，改为弃置魔法卡攻击（一次弃卡 = 攻击两次）
  - `神机妙算`：宣言船数减少量，命中则减免
  - `桃园结义`：从牌堆抽 N 张，自己先选 1 张，对方再选 1 张

---

## 🗄️ 数据模型（SQLite）

| 表 / 视图 | 用途 |
|---|---|
| `users` | 账号、密码哈希、头像、签名、战绩统计 |
| `matches` | 对局记录（胜者/败者/时间） |
| `chat_messages` | 局内聊天记录 |
| `active_games` | 活跃对局（预留） |
| `match_logs` | 对局过程日志 |
| `match_history`（视图） | 战绩查询用视图 |

---

## 🧪 测试

```bash
python -m pytest tests/ -q      # 121 passed
```

| 测试文件 | 覆盖 |
|---|---|
| `test_all_magic_cards.py` | 全部魔法卡效果与边界 |
| `test_magic_effects.py` | 溅射/轰炸/硫磺火焰等区域效果 |
| `test_magic_resolution_flows.py` | 跨回合结算闭环（增援/无暇圣心/教皇旨意弃卡等） |
| `test_auth_spoof.py` | Socket 事件身份鉴权（防伪造 player_id） |
| `test_disconnect_and_eden_shenji.py` | 掉线宽限/重连、伊甸园结算时机、神机妙算宣言、AI 布船规则 |

---

## 🔐 安全与运维注意

- ⚠️ `api.py` 的 `SECRET_KEY` 目前为**硬编码**，部署到公网前建议改为环境变量注入的随机值。
- ⚠️ `test_*` 调试事件对外暴露，公网部署建议加环境开关或移除。
- `cors_allowed_origins="*"` 建议按部署域名收紧。
- 使用 eventlet 运行**必须**在导入应用前调用 `eventlet.monkey_patch()`，否则后台计时任务中的 `time.sleep` 会阻塞整个单线程服务器。
- 建议生产环境启用 HTTPS、数据库定期备份。

---

## 📖 延伸阅读

- 详细架构与逐模块说明见 [`CODE_WIKI.md`](./CODE_WIKI.md)

---

## 📄 License

本项目为个人学习/娱乐项目。魔法卡牌名称与效果设计灵感来自各类卡牌游戏，仅供交流学习使用。
