# Phase 1：Combat Kernel 交付记录

## 范围

本阶段从旧 `server.handle_attack` 的核心规则中抽出纯领域内核，暂不接管旧 Socket handler。

新增：

- `domain/combat.py`：不可变攻击快照、命令、结果、领域事件和规则结算。
- `application/attack_service.py`：旧 `Player/PlayerShip/Position` 形状与领域快照之间的兼容适配。
- `tests/test_combat_kernel.py`：纯规则和领域导入边界测试。
- `tests/test_attack_adapter.py`：旧对象转换和旧 payload 形状测试。

## 已覆盖规则

- 合法坐标和棋盘边界。
- 当前攻击者和攻击次数。
- 重复攻击。
- 未命中、命中和沉船。
- 无敌船只只显形不受伤。
- 护盾挡炮、消耗攻击次数、同格可重试。
- 强制击杀忽略无敌和护盾。
- `AttackResolved`、`ShieldAbsorbed`、`ShipSunk` 领域事件顺序。
- 领域模块不得导入 Flask、Socket.IO、SQLite 或 `server`。

## 兼容策略

- 未修改现有 `server.py`、Socket 事件名、HTTP、数据库、回放或前端。
- `application.attack_service` 只读旧运行时对象，不修改旧对象。
- 旧 handler 的广播、统计、卡牌效果、回放和结算副作用继续由旧实现负责。
- 下一阶段再以 shadow 对照方式接入 `handle_attack`，确认新旧状态和事件一致后才切换。

## 验证

```text
python -m pytest -q tests/test_combat_kernel.py tests/test_attack_adapter.py
12 passed in 0.09s

python -m pytest -q tests/
1011 passed, 1 warning in 21.65s

node --check static/game.js
通过

python -m py_compile domain/combat.py application/attack_service.py
通过
```

唯一警告仍为 `server.py:5` 的 `EventletDeprecationWarning`；本阶段不改变运行时框架。

## 索引证据

使用 EmbeddingGemma CUDA 索引报告：

`F:\CodexData\battle-ship-context-index\reports\context-20261012-102842-35064.md`

报告定位并经源码核对的入口：

- `server.py:5525`：`attack` Socket handler。
- `server.py:5527`：`handle_attack`。
- `server.py:9642`：`resolve_chain`，作为本阶段明确不接管的副作用边界。
- `server.py:4785`：`_finalize_match`，作为本阶段明确不接管的结算边界。

## 未完成项

- 尚未把新内核接入旧 `handle_attack`。
- 尚未建立真实 Socket 对局的新旧 shadow 对照。
- 尚未迁移卡牌、连锁、回放和统计副作用。

这些内容进入后续阶段，不在本提交中隐藏或提前宣称完成。
