# 基础重构当前状态与原文件拆分清单

> 核对对象：`review/battleship-refactor`，草稿 PR #13。本文最初按 `82ce5e6` 核对 Phase 0–8；随后新增阶段 9 的运行时状态拆分和阶段 10 的七批效果与界面迁移，详见对应阶段报告。本文不表示已合并、已部署或生产主流程已全部切换。

## 总体进度

Phase 0–8 的设计基线、领域模型、观察边界、仓储边界、前端首批拆分与交付门禁均已进入同一条 PR。当前最准确的结论是：**架构边界和部分生产接线已经建立；服务端的核心对局编排与卡牌结算仍集中在 `server.py`，客户端对局界面仍集中在 `static/game.js`。**

### `server.py` 拆出了什么

| 范围 | 新位置 | 当前接线状态 |
| --- | --- | --- |
| 攻击输入、船与棋盘快照、命中/沉船等纯规则 | `domain/combat.py`、`application/attack_service.py` | `handle_attack` 调用新内核做 shadow 对照；旧处理器仍决定生产结果。默认关闭，由 `COMBAT_SHADOW_MODE` 控制。 |
| 准备/战斗/结束与交接状态转换 | `domain/turns.py`、`application/turn_service.py` | 已有纯状态机和旧房间适配器；`server.py` 中进入阶段、结束阶段和换回合的旧路径仍写入实际状态。 |
| 卡牌目标规范化、连锁栈与响应状态 | `domain/cards.py`、`domain/chain.py`、`application/chain_service.py` | 模型与适配器可独立验证；`resolve_chain`、响应处理仍在 `server.py` 执行，卡牌效果按后续批次持续迁移。 |
| 首批七张卡的实际效果 | `application/card_opening_effects.py` | 阶段 10 已在生产结算入口调用；其他卡牌分支、未知卡兜底与最终胜负检查仍在 `server.py`。 |
| 十二张状态与选目标卡的实际效果 | `application/card_status_effects.py` | 阶段 10 第二批已在生产结算入口调用；通过显式传入的五个旧辅助函数结算，失败时提前返回。其余卡牌分支仍在 `server.py`。 |
| 七张侦查与范围伤害卡的实际效果 | `application/card_reveal_effects.py`、`application/card_area_damage_effects.py` | 阶段 10 第三批已在生产结算入口调用；雷达流程合并重复代码，范围伤害继续使用旧沉船与事件辅助函数。 |
| 三张棋盘重置与自救卡的实际效果 | `application/card_board_effects.py` | 阶段 10 第四批已在生产结算入口调用；回放、观战刷新、AI 布船和沉船流程仍注入原辅助函数。 |
| 三张无效化卡及共享判据 | `application/card_negation_effects.py` | 阶段 10 第五批已接管连锁目标、免疫关系、平等条约船数变化判据和实际结算；AI 与真实出牌读取同一份规则。 |
| 命运骰子与共享弃牌待办 | `application/card_dice_effects.py` | 阶段 10 第七批已接管六种结果、弃牌请求、确认和完成广播；服务端保留身份验证与兼容入口。 |
| 选船待办与优先级仲裁 | `application/ship_selection.py` | 阶段 10 第六批已接管按玩家队列、消费、取消、投递和重连投影；牺牲结算仍由服务端编排。 |
| 匹配队列、断线宽限与房间生命周期判断 | `domain/rooms.py`、`application/room_service.py` | 模型与只读适配器已建立；匹配、断线、重连和房间清理仍由原处理器编排。 |
| 房间注册表、入座、人机房及匹配队列运行时 | `application/room_runtime.py` | 阶段 9 已迁走实际运行的 `RoomManager`；Socket 匹配处理器仍在 `server.py`，从同一实例读写。 |
| 旧 `GameRoom` 状态与牌堆操作 | `application/room_state.py` | 阶段 9 已迁走状态初始化和抽弃牌；`server.py` 仅保留成功抽牌后单发事件的适配类。 |
| 玩家、船位和效果标记状态 | `application/player_state.py` | 阶段 9 已迁走实际运行的可变数据类与标记生命周期规则；`MagicCard` 仍在 `server.py`。 |
| 大厅在线状态、消息与公开投影 | `application/lobby_state.py`、`application/lobby_projection.py` | 阶段 9 已接入生产路径；Socket 入口和广播仍留在 `server.py`。 |
| 回放所需的房间观察值 | `application/replay_observation.py` | 生产录制入口已改为传观察快照，`replay.py` 不再直接接收运行中的完整房间；兼容入口仍保留。 |
| 观战公开快照的投影 | `application/spectate_projection.py` | 生产路径已调用投影函数；`server.py` 仍收集公开事实并发送 Socket 事件。 |
| AI 决策观察值、随机源与等待时间 | `domain/observations.py`、`application/observations.py`、`application/ai_runtime.py` | `ai_brain.py` 已从观察值读取决策事实，生产 AI 运行时可注入随机源和等待；游戏规则的所有随机数尚未统一迁移。 |
| 结算反作弊事实 | `domain/observations.py`、`application/observations.py` | `server.py` 通过 `SettlementSnapshot` 生成事实字典，再交给既有反作弊判据。 |
| 数据访问边界及数据库维护 | `infrastructure/persistence.py`、`infrastructure/sqlite_maintenance.py`、`db.py` | `server.py`/`api.py` 共用受限仓储；三个直接 SQL 查询迁至 DAO。仍是单进程 SQLite，暂无版本化迁移。 |

Phase 0–8 时，这些项目并非等量地从 `server.py` 剪切出去：相对 `origin/main`，当时该文件的 PR 差异为新增 145 行、删除 157 行。阶段 9 又从当前生产路径实移了大厅、房间与玩家状态代码。`server.py` 仍定义 `MagicCard` 和薄层 `GameRoom` 适配类，保留匹配、布船、攻击、回合、连锁、卡牌效果、重连和结算的主要 Socket 编排。尤其 `handle_attack`、`resolve_chain`、`apply_magic_effect` 还在原文件。新领域实现与旧规则并存的部分仍有漂移风险，后续切换须逐条验证，再删除重复规则。

阶段 10 第二批从 `server.py` 的真实 `apply_magic_effect` 再移出十二个分支，相对前次提交删除 210 行、补入 13 行调用与导入代码；源码扫描守卫同步覆盖新模块。`server.py` 仍约 1.2 万行，当前拆分远未解决核心对局编排过度集中的问题。

阶段 10 第三批再移出七个侦查与范围伤害分支，相对前次提交删除 523 行、补入 30 行；当时 `server.py` 约 11,723 个非空行。代码分布改善，但多个应用层效果仍依赖 `server.py` 的旧辅助函数，需要继续迁走编排与共享规则，收窄这些回调边界。

阶段 10 第四批再移出败者食尘、绝处逢生、回光返照三个分支，`server.py` 删除 314 行、增加 21 行适配调用；完成后约 11,428 个非空行。相关回放与房间重置规则仍由旧辅助函数承担。全量回归为 1063 passed，提交 `8b4a4d5` 的 Windows CI 已通过。

阶段 10 第五批再移出平等条约、失灵！、加百列之光及其共享判据，删除 355 行、增加 24 行适配与调度代码；当前 `server.py` 约 11,140 个非空行。全量回归为 1066 passed、1 个既有 Eventlet 弃用警告。攻击、回合、连锁调度及其余卡牌结算仍集中在原文件；这批完成不代表整体重构完成。

阶段 10 第六批迁出选船待办编排到 `application/ship_selection.py`：按玩家隔离队列、优先级与顺序、去重、消费、取消、重连投影及投递均由模块管理。服务端保留 AI 策略适配和兼容名称，本批净减少 282 行；随后第七批迁出骰子效果后，`server.py` 为 10,731 个非空行。全量回归 1068 passed；实际牺牲结算与 Socket 输入验证仍需继续拆分。

阶段 10 第七批把命运骰子和共享弃牌待办迁入 `application/card_dice_effects.py`，把回放播放器迁入 `static/replay_player.js`。`server.py` 再删除 208 行、增加 17 行；`static/game.js` 再删除 1,144 行、增加 7 行说明与接线，当前分别为 10,731 与 13,210 个非空行。全量回归 1069 passed；回放逐格检查 108 项、DOM 契约和真实 Edge 回放流程均通过。实际攻击、连锁、重连输入验证和剩余卡牌编排仍集中在服务端。

### `static/game.js` 拆出了什么

| 新文件 | 从原文件移出的内容 | 当前边界 |
| --- | --- | --- |
| `static/client_state.js` | 客户端初始状态与共享变量 | 仍通过浏览器经典脚本共享作用域访问。 |
| `static/client_socket.js` | `ensureSocket`、`onSocketReady` 等连接入口 | 负责连接生命周期入口。 |
| `static/client_socket_events.js` | `setupSocketListeners` 和 Socket 事件监听注册、回调 | 回调仍直接修改共享状态和界面；尚未成为独立的事件/状态架构。 |
| `static/home_panels.js` | 首页名片、统计、成就、段位、在线情况及热门卡数据与渲染 | 首页逻辑已集中到独立脚本。 |
| `static/card_catalog.js` | 卡牌名称查询与图鉴目录查询 | 卡牌原始数据继续由既有 `static/magic_cards.js` 提供。 |
| `static/replay_player.js` | 回放 DOM、帧解算、时间线、棋盘/手牌渲染、播放与设置 | 通过经典脚本共享作用域与 `game.js` 的入口衔接；HTTP 回放和观战隔离契约保持。 |

相对 `origin/main`，`static/game.js` **删除 3,679 行、增加 7 行说明与接线**；六个前端辅助脚本承接迁出内容。模板按依赖顺序加载它们。`game.js` 仍有 13,210 个非空行，保留布船、对局棋盘、卡牌交互、好友、观战等大量界面逻辑；回放播放器已独立成文件。这一轮仍使用经典脚本共享作用域，尚未迁成 ES module，也未消除共享全局状态。

## 阶段完成度与交付边界

- Phase 0–1：设计与契约基线、攻击纯规则内核已建立。
- Phase 2–5：攻击 shadow、回合状态机、卡牌/连锁模型、房间模型已建立；**主要旧生产写路径尚未切换**。
- Phase 6：回放、观战、AI、反作弊的观察边界已接入生产路径；回放常驻内存的约 30 KB 目标尚未达到，兼容入口仍在。
- Phase 7：HTTP/Socket 的仓储入口和 SQLite 维护工具已接入；连接池、业务级事务、版本化迁移和多实例状态共享仍未实现。
- Phase 8：前端首批拆分、健康端点、发布预检、备份/回滚手册和 Windows PR CI 已建立；尚未在真实生产环境演练部署与回滚。

截至最新批次，本地全量回归为 **1069 passed、1 个既有 Eventlet 弃用警告**；回放逐格 108 项、DOM 契约和真实浏览器回放流程均通过。前端脚本语法、隔离库健康检查、双浏览器对局链路和发布预检已有 Phase 8 验收记录，详见 `2026-10-12-phase8-acceptance.md`。这些证据支持审查当前 PR，不等于证明上线环境已完成切换。PR 保持草稿；合并 `main` 和部署均等待用户另行指令。

## 原设计目标尚缺的验收关口

1. **规则唯一性**：将攻击、回合、连锁、卡牌效果和房间生命周期逐条切到新应用/领域路径，比较实际 Socket 事件、状态、回放与结算，再删除旧规则的重复判定。现有 shadow 与只读适配器不能替代这个验收。
2. **完整契约证据**：Phase 0 记录了事件和路由清单，但其基线报告仍将真实连锁、重连、结算黄金样本、机器可读 HTTP 契约和回放版本策略列为待补证据。仓库已有相关测试，仍需按原门槛整理覆盖范围并补齐缺口，不能据文件名推定门槛通过。
3. **部署与观测闭环**：已有隔离库预检、健康端点和发布手册；真实环境的备份位置、进程重启、Socket 建连、监控告警及回滚演练未在此 PR 验证。`/health/ready` 目前只检查 SQLite 关键表，不代表完整对局服务就绪。
4. **数据与扩展边界**：仍采用单进程内存房间/匹配状态和 SQLite 单连接；跨仓储操作事务、版本化迁移以及多实例状态和广播通道尚无实现。下一次实际 schema 变更前须先完成迁移与回退机制。

这些关口是后续阶段的实际完成条件。草稿 PR 的绿色测试只证明当前测试覆盖的范围通过，不应单独作为整体生产级完成证明。
