# Phase 3：回合与阶段状态机

## 范围

本阶段抽出准备、战斗、结束和回合交接的纯状态机，不改变现有 Socket 事件或 `GameRoom` 字段。

新增：

- `domain/turns.py`：阶段转换、玩家顺序、回合计数和跳过作用域。
- `application/turn_service.py`：旧房间对象到状态机快照的只读适配。
- `tests/test_turn_state_machine.py`：状态机规则和导入边界测试。

## 规则边界

- 攻击次数由应用层按场地、船数和卡牌效果计算，状态机只保存结果。
- `preparation → battle` 只改变阶段和次数。
- `battle → end` 只有在没有剩余攻击次数，或没有可攻击格时允许。
- `end → preparation` 会切换当前攻击者并清空下一回合的攻击次数。
- 最后一位玩家结束后进入新大回合并递增 `round`。
- `skip_opponent_turn`、`skip_next_turn` 和 `skip_opponent_stages` 保持不同作用域。
- 卡牌效果、连锁结算、摸牌、冻结和回放副作用仍留在旧应用层。

## 验证

```text
python -m pytest -q tests/test_turn_state_machine.py
12 passed in 0.07s

python -m pytest -q tests/
1026 passed, 1 warning in 21.29s
```

唯一警告仍为 `server.py:5` 的 Eventlet 弃用提示。

## 当前状态

本阶段先建立纯状态机和只读适配器，尚未替换 `enter_battle_phase`、`handle_enter_end_phase` 或 `_end_turn_locked` 的写回逻辑。下一阶段收集状态机预测与旧 handler 的真实对局对照，再决定接管顺序。
