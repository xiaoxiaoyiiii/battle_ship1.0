# 基础重构当前状态与原文件拆分清单

> 核对对象：`review/battleship-refactor`，截至 `82ce5e6`；对应草稿 PR #13。本文记录审查前状态，不表示已合并、已部署或生产主流程已全部切换。

## 总体进度

Phase 0–8 的设计基线、领域模型、观察边界、仓储边界、前端首批拆分与交付门禁均已进入同一条 PR。当前最准确的结论是：**架构边界和部分生产接线已经建立；服务端的核心对局编排与卡牌结算仍集中在 `server.py`，客户端对局界面仍集中在 `static/game.js`。**

### `server.py` 拆出了什么

| 范围 | 新位置 | 当前接线状态 |
| --- | --- | --- |
| 攻击输入、船与棋盘快照、命中/沉船等纯规则 | `domain/combat.py`、`application/attack_service.py` | `handle_attack` 调用新内核做 shadow 对照；旧处理器仍决定生产结果。默认关闭，由 `COMBAT_SHADOW_MODE` 控制。 |
| 准备/战斗/结束与交接状态转换 | `domain/turns.py`、`application/turn_service.py` | 已有纯状态机和旧房间适配器；`server.py` 中进入阶段、结束阶段和换回合的旧路径仍写入实际状态。 |
| 卡牌目标规范化、连锁栈与响应状态 | `domain/cards.py`、`domain/chain.py`、`application/chain_service.py` | 模型与适配器可独立验证；`resolve_chain`、响应处理及卡牌效果仍在 `server.py` 执行。 |
| 匹配队列、断线宽限与房间生命周期判断 | `domain/rooms.py`、`application/room_service.py` | 模型与只读适配器已建立；匹配、断线、重连和房间清理仍由原处理器编排。 |
| 回放所需的房间观察值 | `application/replay_observation.py` | 生产录制入口已改为传观察快照，`replay.py` 不再直接接收运行中的完整房间；兼容入口仍保留。 |
| 观战公开快照的投影 | `application/spectate_projection.py` | 生产路径已调用投影函数；`server.py` 仍收集公开事实并发送 Socket 事件。 |
| AI 决策观察值、随机源与等待时间 | `domain/observations.py`、`application/observations.py`、`application/ai_runtime.py` | `ai_brain.py` 已从观察值读取决策事实，生产 AI 运行时可注入随机源和等待；游戏规则的所有随机数尚未统一迁移。 |
| 结算反作弊事实 | `domain/observations.py`、`application/observations.py` | `server.py` 通过 `SettlementSnapshot` 生成事实字典，再交给既有反作弊判据。 |
| 数据访问边界及数据库维护 | `infrastructure/persistence.py`、`infrastructure/sqlite_maintenance.py`、`db.py` | `server.py`/`api.py` 共用受限仓储；三个直接 SQL 查询迁至 DAO。仍是单进程 SQLite，暂无版本化迁移。 |

这些项目不是等量地从 `server.py` 剪切出去。相对 `origin/main`，该文件的 PR 差异为 **新增 145 行、删除 157 行**。它仍定义 `PlayerShip`、`MagicCard`、`Player`、`GameRoom`、`RoomManager`，保留匹配、布船、攻击、回合、连锁、卡牌效果、重连和结算的主要 Socket 编排。尤其 `handle_attack`、`resolve_chain`、`apply_magic_effect` 还在原文件。新领域实现与旧规则并存的部分仍有漂移风险，后续切换须逐条验证，再删除重复规则。

### `static/game.js` 拆出了什么

| 新文件 | 从原文件移出的内容 | 当前边界 |
| --- | --- | --- |
| `static/client_state.js` | 客户端初始状态与共享变量 | 仍通过浏览器经典脚本共享作用域访问。 |
| `static/client_socket.js` | `ensureSocket`、`onSocketReady` 等连接入口 | 负责连接生命周期入口。 |
| `static/client_socket_events.js` | `setupSocketListeners` 和 Socket 事件监听注册、回调 | 回调仍直接修改共享状态和界面；尚未成为独立的事件/状态架构。 |
| `static/home_panels.js` | 首页名片、统计、成就、段位、在线情况及热门卡数据与渲染 | 首页逻辑已集中到独立脚本。 |
| `static/card_catalog.js` | 卡牌名称查询与图鉴目录查询 | 卡牌原始数据继续由既有 `static/magic_cards.js` 提供。 |

相对 `origin/main`，`static/game.js` **删除 2,535 行、没有新增行**；新增五个脚本合计 2,539 行。模板按依赖顺序加载它们。`game.js` 仍有约 14,304 个非空行，保留布船、对局棋盘、卡牌交互、好友、回放/观战等大量界面逻辑。这一轮属于实体文件拆分，尚未迁成 ES module，也未消除共享全局状态。

## 阶段完成度与交付边界

- Phase 0–1：设计与契约基线、攻击纯规则内核已建立。
- Phase 2–5：攻击 shadow、回合状态机、卡牌/连锁模型、房间模型已建立；**主要旧生产写路径尚未切换**。
- Phase 6：回放、观战、AI、反作弊的观察边界已接入生产路径；回放常驻内存的约 30 KB 目标尚未达到，兼容入口仍在。
- Phase 7：HTTP/Socket 的仓储入口和 SQLite 维护工具已接入；连接池、业务级事务、版本化迁移和多实例状态共享仍未实现。
- Phase 8：前端首批拆分、健康端点、发布预检、备份/回滚手册和 Windows PR CI 已建立；尚未在真实生产环境演练部署与回滚。

截至上述提交，本地全量回归与 Windows CI 均为 **1060 passed、1 个既有 Eventlet 弃用警告**；前端脚本语法、DOM 契约、隔离库健康检查、双浏览器对局链路和发布预检已有 Phase 8 验收记录，详见 `2026-10-12-phase8-acceptance.md`。这些证据支持审查当前 PR，不等于证明上线环境已完成切换。PR 保持草稿；合并 `main` 和部署均等待用户另行指令。

## 原设计目标尚缺的验收关口

1. **规则唯一性**：将攻击、回合、连锁、卡牌效果和房间生命周期逐条切到新应用/领域路径，比较实际 Socket 事件、状态、回放与结算，再删除旧规则的重复判定。现有 shadow 与只读适配器不能替代这个验收。
2. **完整契约证据**：Phase 0 记录了事件和路由清单，但其基线报告仍将真实连锁、重连、结算黄金样本、机器可读 HTTP 契约和回放版本策略列为待补证据。仓库已有相关测试，仍需按原门槛整理覆盖范围并补齐缺口，不能据文件名推定门槛通过。
3. **部署与观测闭环**：已有隔离库预检、健康端点和发布手册；真实环境的备份位置、进程重启、Socket 建连、监控告警及回滚演练未在此 PR 验证。`/health/ready` 目前只检查 SQLite 关键表，不代表完整对局服务就绪。
4. **数据与扩展边界**：仍采用单进程内存房间/匹配状态和 SQLite 单连接；跨仓储操作事务、版本化迁移以及多实例状态和广播通道尚无实现。下一次实际 schema 变更前须先完成迁移与回退机制。

这些关口是后续阶段的实际完成条件。草稿 PR 的绿色测试只证明当前测试覆盖的范围通过，不应单独作为整体生产级完成证明。
