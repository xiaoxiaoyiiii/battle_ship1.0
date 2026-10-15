# 阶段 10：特殊魔法卡与前端目标规则迁移

## 迁移内容

`application/card_special_effects.py` 接管 `神威！`、`神之宣告` 和 `疗愈` 的实际结算。模块通过显式注入使用广播、回放、选船、牺牲、复活和终局结算能力，不反向导入 `server.py`。`server.py` 保留三个兼容包装入口，`apply_magic_effect` 继续负责连锁编排、未知卡处理和最终收口，并在特殊卡模块之后保持原有的立即返回语义。

`application/card_field_effects.py` 现在也接管 `教皇旨意` 的即时归零逻辑，与另外三张场地卡共用同一入口；战斗阶段中途打出时仍会立即广播 `attacks_updated`，不会退回到阶段切换时机。

`application/card_steal_effects.py` 接管 `盗亦有道` 在连锁栈与历史记录之间选择目标、避免重复盗取、从弃牌堆转移卡牌的逻辑；`server.py` 只保留调度和最终收口。

`application/card_temporary_effects.py` 接管 `滥竽充数` 的发动登记和回合末临时战舰回收；放置确认仍复用既有 placement 流程，旧 `_recall_lanyu_ships` 入口保留兼容。

`static/magic_effect_feedback.js` 接管前端 `applyCardEffect` 的卡牌效果提示与广播反馈。它继续使用页面共享的 `gameState` 和 UI 辅助函数，目标选择、Socket 事件和实际状态更新仍由原模块负责。

`static/magic_target_ui.js` 接管魔法卡区域、行列、连续格、神威棋盘和选船目标 UI，通过经典脚本共享作用域调用棋盘 DOM 与 `confirmMagicTarget`，目标提交协议保持不变。

`static/magic_actions.js` 接管魔法卡出牌入口、目标确认后的普通出牌/连锁响应/优先级响应分流，以及神之宣告的二段确认；服务端事件名与 payload 保持不变。

`application/chain_policy.py` 接管连锁响应资格判定（普通玩家速阶 3、绝处逢生锁卡和困难 AI 的失灵响应条件）；窗口计时、广播和实际连锁结算仍由 `server.py` 编排。

前端新增 `static/magic_rules.js`，承接魔法卡使用阶段门禁、命中前置条件、绝处逢生锁卡判断和 `MAGIC_TARGET_DESCRIPTORS`；`static/magic_target_ui.js` 承接目标选择器，目标发送逻辑仍在 `game.js`。模板按依赖顺序在 `game.js` 前加载新脚本。经典脚本共享作用域保留现有页面、浏览器工具和旧入口兼容。

源码级回放与区域预览守卫同步扫描迁出的模块：船位移除、剩余船数、区域目标和无忧梦呓实现检查不再硬编码旧的 `server.py` 位置。

## 验证

- `python -m pytest -q`：1069 passed，1 个既有 Eventlet 弃用警告。
- 特殊卡、回放、观战和目标预览定向测试：通过。
- 所有静态脚本 `node --check`：通过。
- `node tools/dom_contract_check.mjs`：DOM 契约通过，保留 3 条已核实无害的悬空提示。
- `node tools/dom_replay_frame_check.mjs`：108 项逐格回放断言通过。
- `python -m py_compile server.py application/card_special_effects.py application/card_field_effects.py application/card_steal_effects.py application/card_temporary_effects.py` 与 `git diff --check`：通过。
- 隔离 SQLite 启动服务后，首页和 `/api/rank_constants` HTTP smoke：通过。

## 兼容与剩余范围

事件名、回放载荷、卡牌行为和旧服务端函数入口保持不变。卡牌效果已全部接入应用模块；`game.js` 仍保留目标选择器组件和对局渲染，攻击、连锁和放置编排仍待拆分。后续迁移继续保留兼容入口并同步源码守卫。
