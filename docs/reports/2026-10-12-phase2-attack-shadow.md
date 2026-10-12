# Phase 2：攻击流程 Shadow 对照层

## 范围

本阶段把 Combat Kernel 接到旧 `handle_attack` 的只读对照位置，默认不启用，不改变任何玩家可见行为。

新增：

- `application/attack_shadow.py`：比较领域预期与旧 handler 核心结果。
- `server.py` 中的 `COMBAT_SHADOW_MODE` 配置和 shadow 调用点。
- `tests/test_attack_shadow.py`：一致和不一致结果的对照测试。

## 运行方式

默认关闭：

```powershell
Remove-Item Env:COMBAT_SHADOW_MODE -ErrorAction SilentlyContinue
```

本地验证开启：

```powershell
$env:COMBAT_SHADOW_MODE='1'
$env:BATTLESHIP_DB_PATH="$PWD/.tmp/phase2-shadow.db"
python -m pytest -q tests/test_attack_records.py tests/test_shield_and_last_stand.py
```

开启后，领域结果和旧 handler 的 `hit`、`ship_sunk`、`shield_blocked`、攻击次数和剩余战舰数不一致时只写 warning，不阻断旧路径。

## 验证

```text
python -m pytest -q tests/test_attack_shadow.py tests/test_combat_kernel.py tests/test_attack_adapter.py
15 passed in 0.12s

COMBAT_SHADOW_MODE=1 运行真实 handler 回归：
15 passed in 0.87s

python -m pytest -q tests/
1014 passed, 1 warning in 21.52s

python -m py_compile server.py application/attack_shadow.py
通过

node --check static/game.js
通过
```

唯一警告仍为 `server.py:5` 的 Eventlet 弃用提示。

## 边界与后续

- 当前仍由旧 handler 负责房间状态写回、广播、回放、统计、卡牌副作用和终局结算。
- shadow 只比较核心攻击结果，效果额外改变攻击次数或战舰数时需要在后续对照报告中分类，而不是静默视为规则错误。
- 下一步应收集真实 Socket 对局的 shadow 日志，按普通攻击、护盾、强制击杀、沉船和效果副作用分类，再决定是否切换核心写回路径。
