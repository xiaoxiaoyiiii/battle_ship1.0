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

## 第三批：侦查与范围伤害

`application/card_reveal_effects.py` 接管雷达子弹、冻结、探测雷达、克苏鲁之眼；两种雷达共用一个内部的公开格子与空格探测流程。`application/card_area_damage_effects.py` 接管溅射、轰炸、硫磺火焰。它们在真实卡牌结算入口执行，并通过显式传入的旧辅助函数完成沉船、恶魔契约及事件发送；失败提前返回、未知卡处理和结算后胜负检查仍由原入口保留。

相对第二批提交，`server.py` 删除 523 行、新增 30 行，净减少 493 行；按当前非空行统计仍有约 11,723 行。范围伤害分支虽已迁出，`handle_attack`、`resolve_chain`、神威及大量其他卡牌效果仍在 `server.py`，不能据此宣称服务端拆分完成。

源码扫描守卫同步覆盖新增模块：区域预览继续发现全部区域目标卡，战舰增删登记继续覆盖轰炸与硫磺火焰。攻击记录守卫原先只有扫描器、没有真正执行的登记核对测试；本批补齐双向核对，并登记两种雷达共用的攻击写入点。新增两例运行时断言检查雷达对空格的攻击时间线和事件顺序。

验证：`python -m py_compile server.py application/card_reveal_effects.py application/card_area_damage_effects.py`、`git diff --check`；相关卡牌与源码守卫定向测试通过；`python -m pytest -q` 为 1063 passed、1 个既有 Eventlet 弃用警告。Windows CI 结果以本批提交的检查为准。

## 第四批：棋盘重置与自救

`application/card_board_effects.py` 接管败者食尘、绝处逢生、回光返照。三个效果分别负责双侧重摆、牺牲后单船部署、单侧重摆；回放重置归属、观战棋盘刷新和 AI 当场布船继续走原有函数，通过显式参数传入。败者食尘的提前终止返回语义保留。

源码守卫现在也扫描新模块里的 `ships` / `attacks` 写入和回放板面重置点，并把登记从旧 `apply_magic_effect` 调整到 `apply_board_card_effect`。`server.py` 本批删除 314 行、增加 21 行调度代码。定向回归 94 passed；语法检查与 `git diff --check` 通过。提交前全量回归为 1063 passed；提交 `8b4a4d5` 的 Windows CI 已通过。

## 第五批：连锁无效化与共享判据

`application/card_negation_effects.py` 接管平等条约、失灵！、加百列之光的真实结算，并拥有连锁目标解析、免疫关系、九项船数变化判据及四项不适用规则。`NegationEffects` 不保存房间状态，也不导入服务器；共享的存活、坐标、空位查询和拆场动作通过六个显式依赖注入。AI 的判词入口、原有诊断表与实际结算使用同一个实例中的规则，服务端仅保留延迟查询适配与兼容名称。

保留原有提前返回、场地拆除、历史记录回退和失灵的类型分发优先级。该模块不会自行消费连锁栈；卡牌入栈、逐项出栈、响应计时和胜负收口仍由 `server.py` 编排。本批从 `server.py` 删除 355 行、补入 24 行，净减少 331 行；当前非空行数为 11,140。累计已有 32 个卡名的效果迁至六个卡牌模块，阶段 10 尚未完成。

验证：连锁与全卡牌定向回归 117 passed；新增独立运行时查询隔离、查询失败拒绝无效化，以及服务端查询替换后 AI/真实结算一致性的三项测试。源码守卫同时检查新模块实现与生产调用入口。`python -m pytest -q` 最终为 1066 passed、1 个既有 Eventlet 弃用警告；语法检查与 `git diff --check` 通过。远端 CI 以本批提交检查为准。
