# 阶段 10：实际卡牌效果迁移

## 第一批：基础效果

`application/card_opening_effects.py` 接管七张卡的生产效果：余音绕梁、桃园结义、无中生有、亡羊补牢、极限增援、无暇圣心、火力全开。`server.py` 的 `apply_magic_effect` 仍负责创建结果、后续其他卡牌分支、未知卡报错，以及卡牌结算后的胜负收口。

新模块只接收房间、施法者、卡牌、结算结果和已有发送函数，不导入服务器或 Socket.IO。返回值区分“未处理”“已处理并继续胜负检查”“已处理且须提前返回”，保留原来准备阶段拒绝、牌堆为空和弃牌区无候选等提前返回路径。成功抽牌仍由 `GameRoom` 适配层按旧事件单发。

相对阶段 9 的最新提交，`server.py` 删除 166 行、新增 9 行；迁移的是实际效果执行，不是并行 shadow 实现。后续卡牌仍需按依赖组逐批迁出，`apply_magic_effect` 尚未完成拆分。

## 验证与边界

- `python -m pytest -q tests/test_hidden_cards.py tests/test_huoli_double_attacks.py tests/test_bingliang_card.py tests/test_all_magic_cards.py`：107 passed，1 个既有 Eventlet 弃用警告；覆盖抽牌、延迟效果与当前攻击次数翻倍。
- `python -m pytest -q`：1060 passed，1 个既有 Eventlet 弃用警告。
- 末次清理模块入口后，`python -m pytest -q tests/test_all_magic_cards.py tests/test_huoli_double_attacks.py tests/test_bingliang_card.py`：103 passed。
- `python -m py_compile server.py application/card_opening_effects.py` 与 `git diff --check`：通过。

本阶段未修改 Socket 契约、回放格式或数据库。回滚为在长期分支回退本提交并运行全量回归。草稿 PR 供用户审查；合并 `main` 与部署仍需分别下令。

## 第二批：状态与选择效果

`application/card_status_effects.py` 接管十二张卡的真实效果：灵气复苏、越战越勇、饮血、Freezing！、五险一金、明智埋葬、仁王之盾、八方来财、百亿补贴、死者苏生、看破！、增援。模块只接收房间状态与明确传入的旧辅助函数，不反向导入 `server.py`。原入口继续负责未知卡兜底、胜负检查和其他卡牌结算；原有失败提前返回通过“已处理、须停止”返回值保留。

相对第一批提交，`server.py` 删除 210 行、新增 13 行；该文件仍约 1.2 万行，`apply_magic_effect` 及主要对局编排还没有完成拆分。源码扫描型区域卡测试原先只读 `server.py`，现同时扫描新模块，确保“仁王之盾”迁出后仍纳入覆盖检查。

验证：`python -m py_compile server.py application/card_status_effects.py` 通过；卡牌与连锁定向测试 91 passed；区域预览测试 27 passed；`python -m pytest -q` 为 1060 passed、1 个既有 Eventlet 弃用警告。
