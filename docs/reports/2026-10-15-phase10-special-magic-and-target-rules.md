# 阶段 10：特殊魔法卡与前端目标规则迁移

## 迁移内容

`application/card_special_effects.py` 接管 `神威！`、`神之宣告` 和 `疗愈` 的实际结算。模块通过显式注入使用广播、回放、选船、牺牲、复活和终局结算能力，不反向导入 `server.py`。`server.py` 保留三个兼容包装入口，`apply_magic_effect` 继续负责连锁编排、未知卡处理和最终收口，并在特殊卡模块之后保持原有的立即返回语义。

`application/card_field_effects.py` 现在也接管 `教皇旨意` 的即时归零逻辑，与另外三张场地卡共用同一入口；战斗阶段中途打出时仍会立即广播 `attacks_updated`，不会退回到阶段切换时机。

`application/card_steal_effects.py` 接管 `盗亦有道` 在连锁栈与历史记录之间选择目标、避免重复盗取、从弃牌堆转移卡牌的逻辑；`server.py` 只保留调度和最终收口。

`application/card_temporary_effects.py` 接管 `滥竽充数` 的发动登记和回合末临时战舰回收；放置确认仍复用既有 placement 流程，旧 `_recall_lanyu_ships` 入口保留兼容。

`static/magic_effect_feedback.js` 接管前端 `applyCardEffect` 的卡牌效果提示与广播反馈。它继续使用页面共享的 `gameState` 和 UI 辅助函数，目标选择、Socket 事件和实际状态更新仍由原模块负责。

`static/magic_target_ui.js` 接管魔法卡区域、行列、连续格、神威棋盘和选船目标 UI，通过经典脚本共享作用域调用棋盘 DOM 与 `confirmMagicTarget`，目标提交协议保持不变。

`static/magic_actions.js` 接管魔法卡出牌入口、目标确认后的普通出牌/连锁响应/优先级响应分流，以及神之宣告的二段确认；服务端事件名与 payload 保持不变。

`application/chain_policy.py` 接管连锁响应资格判定（普通玩家速阶 3、绝处逢生锁卡和困难 AI 的失灵响应条件）；`application/chain_window.py` 接管响应窗口轮转，`application/chain_timeout.py` 接管超时推进，`application/chain_ai_response.py` 接管困难 AI 的失灵响应，`server.py` 仅保留兼容入口与动态依赖注入。

阶段转换优先权询问的超时调度已迁入 `application/priority_timeout.py`，超时仍通过服务端兼容入口清理待处理状态并继续原操作。

回合状态机已迁入 `application/turn_state_machine.py`：准备阶段进入战斗阶段的攻击次数重算、翻倍效果、五险一金触发与阶段广播，以及战斗阶段进入结束阶段的状态更新、阶段性效果清理、结束阶段切换到对手准备阶段、回合广播和 AI 驱动集中由应用层协作者处理。

回合结束时下一位行动者的计算及 Freezing、神之宣告等跳过标记的消费也已迁入同一状态机；特殊卡结算和新大回合副作用仍由 `server.py` 编排。

同一大回合内的普通换手也已由状态机统一处理，包括准备阶段重置、攻击次数重算、无忧梦呓/兵粮寸断时点、临时效果清理、状态广播和 AI 驱动。

连锁栈的逐项结算循环已迁入 `application/chain_resolution.py`，负责栈顶顺序、无效化、失败退回、连锁标记和魔法历史；服务端保留效果依赖注入与统一收尾。

阶段转换优先权的结果处理已迁入 `application/priority_resolution.py`，负责取消/超时续接、速阶 3 入链失败回退和连锁结算后的原操作续接。

优先权结束后的后台动作恢复已迁入 `application/priority_continuation.py`，统一处理脱离请求上下文、游戏结束检查和阶段 handler 续接。

优先权询问窗口创建已迁入 `application/priority_prompt.py`，现在窗口打开、结果处理、超时和续接均由应用层协作者负责。

优先权门禁和待处理状态清理已迁入 `application/priority_gate.py`，统一处理请求上下文、人机房、掉线、拒绝开关、连锁占用和等待结束通知。

连锁展示停留、代际令牌校验和看门狗兜底已迁入 `application/chain_display.py`，统一处理延迟结算和过期任务清理。

新大回合前的魔法封锁重置、神威战舰恢复和滥竽充数回收已集中到 `application/round_transition.py`；优先权窗口也统一复用同一个倒计时值，避免同一询问在构造载荷时重复读取动态配置。

掉线宽限启动与到期结算已迁入 `application/disconnect_resolution.py`，集中处理断线令牌、对手通知、取消对局、断线判胜和结束房间清理调度。

攻击前门禁和剩余可攻击格判定已迁入 `application/attack_gate.py`，统一处理阶段、连锁、优先权等待、攻击次数、重复坐标和神威区域校验。

攻击命中后的无敌、护盾、强制击杀、击沉、伤害增益和特殊胜负判定已迁入 `application/attack_resolution.py`；`server.py` 保留攻击记录、战斗 shadow、结果广播和攻击次数收尾。

攻击次数扣减、攻击时间线记录、shadow 对照、攻击结果构造、日志/广播和普通终局判断已迁入 `application/attack_finalization.py`，攻击记录源码守卫同步覆盖该模块。

沉船去重登记、船数扣减、恶魔契约、八方来财和无暇圣心中断已迁入 `application/ship_sunk_effects.py`，普通攻击与区域伤害共享同一副作用入口。

沉船后的百亿补贴、无暇圣心中断、陷阱触发和战舰状态同步也已并入 `ShipSunkEffects`，服务端只保留陷阱交互和兼容入口。

守株待兔陷阱的对手目标计算、提示广播、日志和选船/自动牺牲流程也已并入 `ShipSunkEffects`，击沉副作用边界完整闭合。

待处理询问查询和等待冻结原因也已统一由优先权门禁模块生成，服务端只保留兼容读取入口。

新大回合切入猜拳阶段的基础状态重置也已迁入状态机，统一清理猜拳缓存、阶段和上一大回合遗留的跳过标记。

`application/card_refund.py` 接管卡牌发动条件不满足时按对象引用退回手牌的补偿规则；`server.py` 保留兼容包装并注入事件、日志能力。

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
