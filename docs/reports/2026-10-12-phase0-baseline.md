# Phase 0 基线报告

- 日期：2026-10-12
- 分支：`review/battleship-refactor`
- 基点：`f95ea64 Merge pull request #12 from xiaoxiaiy.../fix/woxin-shield-privacy`
- 工作树：独立重构 worktree，开始时干净

## 1. 代码规模

| 文件 | 行数 | 字节 |
| --- | ---: | ---: |
| `server.py` | 15294 | 806179 |
| `api.py` | 2663 | 131274 |
| `db.py` | 4473 | 217704 |
| `ai_brain.py` | 826 | 39213 |
| `replay.py` | 1350 | 69954 |
| `spectate.py` | 1068 | 57873 |
| `static/game.js` | 17921 | 948193 |
| `static/style.css` | 11142 | 479558 |
| `templates/index.html` | 1887 | 133898 |

`server.py` 当前包含房间、匹配、大厅、对局状态、Socket 入口、卡牌、连锁、结算和调试事件等多类职责。

## 2. Socket 事件契约清单

事件定义集中在 `server.py`，当前共 51 个 `@socketio.on(...)` 装饰器入口。事件按迁移优先级分为：

- 连接与生命周期：`connect`、`disconnect`、`get_reconnect_token`、`rejoin_room`
- 房间与大厅：`create_room`、`join_room`、`close_room`、`find_match`、`cancel_match`、`lobby_subscribe`、`lobby_unsubscribe`、`lobby_refresh`、`lobby_create_room`
- 对局准备与阶段：`place_ships`、`rps_choice`、`enter_battle_phase`、`enter_end_phase`、`end_turn`、`surrender`
- 攻击与卡牌：`attack`、`papal_attack`、`papal_discard`、`use_magic_card`、`select_magic_target`、`confirm_magic_target`、`chain_response`、`priority_response`、`set_decline_priority`
- 回放、观战和聊天：`spectate_join`、`spectate_leave`、`spectate_chat_send`、`chat_message`、`quick_chat`、`request_revealed_positions`、`request_hand_sync`
- 调试/测试：所有 `test_*` 事件和 `debug_status`，必须继续受 `ENABLE_TEST_EVENTS` 门禁保护

精确位置以当前源码为准：`server.py:2254-15160`。

## 3. 配置契约

当前代码读取的关键环境变量：

- `SECRET_KEY`：`api.py:91`
- `CORS_ORIGINS`：Socket 初始化和部署配置必须保持一致
- `ENABLE_TEST_EVENTS`：`server.py:43`
- `DEBUG_ADMIN_USER_IDS`：`server.py:51`
- `BATTLESHIP_DB_PATH`：`db.py:145`
- `CHAIN_DISPLAY_DELAY_SECONDS`：`server.py:8615`
- `TURN_TIMEOUT_SECONDS`：`server.py:8625`
- `FLASK_DEBUG`、`PORT`：`server.py:15291-15293`

`run_prod.py` 不在当前仓库；生产启动契约需要在后续阶段补充可复现入口，但本阶段不改变部署行为。

## 4. 测试基线

执行命令：

```powershell
$env:BATTLESHIP_DB_PATH="$PWD/.tmp/phase0/baseline.db"
$env:PYTHONIOENCODING="utf-8"
python -m pytest -q
```

结果：

```text
999 passed, 1 warning in 26.60s
```

唯一警告：`server.py:5` 的 `EventletDeprecationWarning`。

测试输出同时报告回放内存账最坏常驻 `145499 B`，高于旧契约中的 30 KB 观察值；该差异记录为待调查风险，不在 Phase 0 直接修复。

## 5. Phase 0 已确认的边界

- 现有 HTTP、Socket、数据库和回放格式视为兼容契约。
- 旧工作树中的未提交修改不纳入本分支。
- 领域层不得依赖 Flask、Socket.IO、SQLite 或浏览器代码。
- 后续阶段使用同一长期分支和同一 PR；阶段完成只更新 PR，不合并 `main`。

## 6. HTTP 与静态检查

HTTP 路由主要集中在 `api.py`，当前覆盖账号、资料、好友、排行榜、卡牌统计、回放、观战设置、壁纸、管理接口和页面入口；`server.py` 还提供 `/api/online_count`、`/api/home_stats` 和 `/lobby`。

已执行：

```powershell
node --check static/game.js
python -m py_compile server.py api.py db.py ai_brain.py replay.py spectate.py
```

结果：两项均通过。

## 7. 待补充证据

1. 真实 Socket 对局的攻击、连锁、结算和重连黄金样本。
2. HTTP 路由、状态码和主要响应字段的机器可读清单。
3. 回放 JSON schema 与版本策略。
4. 部署启动、健康检查、备份和回滚的可复现检查。
5. 当前生产配置与仓库默认配置的差异清单。

本报告只记录基线，不表示任何重构代码已经完成。
