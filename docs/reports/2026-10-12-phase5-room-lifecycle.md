# Phase 5：房间、匹配与重连生命周期

## 范围

- 新增 `domain.rooms.MatchQueue`：同模式配对、同账号保护、重复入队保护和确定性出队。
- 新增 `domain.rooms.DisconnectLease`：掉线令牌与宽限截止时间的纯值对象。
- 新增 `domain.rooms.RoomLifecycle`：根据房间阶段、AI 房、双方掉线状态决定取消、判负或忽略。
- 新增 `application.room_service`：从旧 `RoomManager` / `GameRoom` 生成只读领域快照。

本阶段没有替换旧匹配、断线和重连 handler，也没有改变 Socket 载荷；下一步用影子比对接入匹配选择和掉线超时判定。

## 验证

覆盖同模式匹配、同账号保护、重复入队、宽限令牌边界、房间生命周期决策、旧对象适配和框架隔离。完成后运行定向测试、全量 `pytest`、模块编译检查和前端语法检查。
