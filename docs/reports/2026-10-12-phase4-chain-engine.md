# Phase 4：卡牌目标与连锁状态机

## 范围

- 新增 `domain.cards.normalize_target`，统一区域、行列、格子、船只索引和单格目标的边界检查。
- 新增 `domain.chain.ChainState`，固化连锁 LIFO、响应玩家轮转、连续两次放弃结算和显式无效化。
- 新增 `application.chain_service.build_chain_state`，从旧 `GameRoom` 做只读快照适配。
- 保留旧 `resolve_chain`、卡牌效果和 Socket 事件，尚未切换线上结算路径。

## 约束

坐标固定为 6×6；目标数据只复制允许的兼容字段；领域层不导入 Flask、Socket.IO 或数据库。AI 是否参与响应仍由旧应用层策略决定，领域状态机只管理已确认的响应命令。

## 验证

本阶段通过 `tests/test_chain_engine.py` 的目标规范化、LIFO、响应窗口、无效化、旧房间适配和框架隔离测试；随后运行全量 `pytest`、核心模块编译检查和前端语法检查。旧连锁结算函数保持不变，后续阶段再做影子比对和逐步接入。
