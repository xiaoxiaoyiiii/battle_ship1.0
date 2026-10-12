# 阶段 10 首批：实际卡牌效果迁移

## 迁移范围

`application/card_opening_effects.py` 接管七张卡的生产效果：余音绕梁、桃园结义、无中生有、亡羊补牢、极限增援、无暇圣心、火力全开。`server.py` 的 `apply_magic_effect` 仍负责创建结果、后续其他卡牌分支、未知卡报错，以及卡牌结算后的胜负收口。

新模块只接收房间、施法者、卡牌、结算结果和已有发送函数，不导入服务器或 Socket.IO。返回值区分“未处理”“已处理并继续胜负检查”“已处理且须提前返回”，保留原来准备阶段拒绝、牌堆为空和弃牌区无候选等提前返回路径。成功抽牌仍由 `GameRoom` 适配层按旧事件单发。

相对阶段 9 的最新提交，`server.py` 删除 166 行、新增 9 行；迁移的是实际效果执行，不是并行 shadow 实现。后续卡牌仍需按依赖组逐批迁出，`apply_magic_effect` 尚未完成拆分。

## 验证与边界

- `python -m pytest -q tests/test_hidden_cards.py tests/test_huoli_double_attacks.py tests/test_bingliang_card.py tests/test_all_magic_cards.py`：107 passed，1 个既有 Eventlet 弃用警告；覆盖抽牌、延迟效果与当前攻击次数翻倍。
- `python -m pytest -q`：1060 passed，1 个既有 Eventlet 弃用警告。
- 末次清理模块入口后，`python -m pytest -q tests/test_all_magic_cards.py tests/test_huoli_double_attacks.py tests/test_bingliang_card.py`：103 passed。
- `python -m py_compile server.py application/card_opening_effects.py` 与 `git diff --check`：通过。

本阶段未修改 Socket 契约、回放格式或数据库。回滚为在长期分支回退本提交并运行全量回归。草稿 PR 供用户审查；合并 `main` 与部署仍需分别下令。
