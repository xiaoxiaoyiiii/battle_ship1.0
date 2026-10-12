# 阶段 9：移出 `server.py` 的大厅与房间运行时

## 本轮范围

- `application/lobby_state.py` 接管在线表、大厅成员、公屏消息、发言间隔和资料缓存。`server.py` 只注入公开资料查询函数，保留 Socket 入口和广播。
- `application/lobby_projection.py` 接管玩家状态、房间可见性、重复等待房回收和 `lobby_state` 公开数据投影。`server.py` 仍提供房间、仓储、等级/段位及观战列表等依赖，不复制规则。
- `application/room_runtime.py` 接管房间注册表、入座、人机房创建及匹配队列。旧 `GameRoom`、`Player`、卡池和 AI 运行时由 `server.py` 注入，生产处理器继续使用同一个 `room_manager` 实例。
- `application/room_state.py` 接管旧 `GameRoom` 的状态初始化、牌堆初始化、抽牌和弃牌；`server.py` 保留很薄的 `GameRoom` 适配类，成功抽牌后仍向本人发送既有 `hand_updated` 事件。隐藏卡集合由适配类按调用时读取，保持旧行为。
- `application/player_state.py` 接管 `Position`、`PlayerShip`、`EffectFlags`、`Player` 及效果标记生命周期表。`MagicCard` 仍在 `server.py`，新模块不反向导入服务器。

这是**已接入生产调用的代码迁移**，不属于 shadow 模型。相对本轮开始的提交，`server.py` 删除 937 行、新增 43 行；新模块不反向导入 `server.py`、Flask 或 Socket.IO。旧的事件名、payload 和房间对象结构不变。

## 验证

- `python -m py_compile server.py application/lobby_state.py application/lobby_projection.py application/room_runtime.py application/room_state.py application/player_state.py`：通过。
- `python -m pytest -q tests/test_lobby.py tests/test_match_mode.py tests/test_room_seating.py tests/test_match_guard.py tests/test_ai_brain.py`：28 passed，1 个既有 Eventlet 弃用警告。
- `python -m pytest -q tests/test_hidden_cards.py tests/test_emit_room_targets.py tests/test_bingliang_card.py tests/test_room_seating.py`：36 passed，1 个既有 Eventlet 弃用警告，覆盖抽牌单发、隐藏卡与房间状态适配。
- `tests/test_ship_removal_sites.py` 的穷举扫描已扩到 `application/player_state.py`，仍要求每一处修改 `*.ships` 的代码在登记表中有对应条目；定向测试 2 passed。
- `python -m pytest -q`：1060 passed，1 个既有 Eventlet 弃用警告。大厅 Socket 流程、房间入座、匹配模式、人机对局及其他现有回归均在全量测试中。
- `git diff --check`：通过。

## 仍需继续拆分

`GameRoom` 的状态字段已移入独立模块，但它仍是旧可变结构；攻击、回合、连锁、卡牌效果的生产编排仍留在 `server.py`。本轮使大厅和房间状态有了独立所有者，但没有声称完成整个服务端拆分。下一轮应围绕一个对局写路径做垂直迁移，先验证实际状态与事件等价，再删除其旧实现；避免仅增加新模型而让两个实现长期并存。

回滚方式：在长期分支回退本轮提交并重跑全量测试。没有数据库 schema 或客户端协议变更；PR 只供审查，合并与部署另等用户指令。
