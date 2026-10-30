# ADR-0001：前后端现代化重写

## Status

Accepted（2026-10-20，Phase 5 收尾）。相关：spec #1、票 #2–#33、DECISIONS D1–D35。

## Context

旧实现是 Flask + Flask-SocketIO + eventlet 的单体：后端两个上万行模块、前端一个
无构建的全局脚本单页（上万行 JS + 400KB+ 单文件 CSS），105+ 个测试文件直接 import
服务端模块，12+ 个无头工具按 DOM id 点击，还有一批断言源码字符串的用例。

症状不是"某功能不好用"，而是**每次改动都可能悄悄弄坏别的东西**：规则在两处实现
（放置合法性、攻击次数、段位曲线）必然漂移；断线重连/观战/回放这类跨屏链路尤其脆；
脚本加载顺序或行号变化会静默失败；线上协议没有类型，字段拼错只在运行时暴露。
维护与 AI 代理都无法在小上下文里安全地改任意一块。

约束：

- 玩家数据（账号、段位、等级、成就、名片、好友、聊天、回放）必须保留；
- 对局规则、Socket.IO/HTTP 线上契约、C+ 十屏视觉必须保持；
- 团队规模小、无独立 QA，门禁必须自动化且可回滚；
- 测试资产按 spec 不进入新架构仓库。

## Decision

用现代分层架构重写两端，**把线上协议契约作为唯一迁移缝**：

1. **后端**：FastAPI（ASGI）+ python-socketio + Pydantic v2 + SQLAlchemy 2.x + Alembic；
   分层 contracts → domain → services → repositories → realtime/http → infra；
   领域规则只有一份实现；SQL 只在仓储层；后台任务改 asyncio 定时器，删除 eventlet
   monkey patch。
2. **前端**：Vue 3 SFC + TypeScript + Vite + Pinia + vue-router；11 条冻结路由；
   `data-testid` 取代 DOM id 作为工具契约；样式按 tokens/base/components/screens 分层；
   构建产物由同一 ASGI 应用托管，内容哈希缓存。
3. **迁移策略**：先冻结/录制协议 → 新后端先让旧前端照常跑 → 逐屏迁到 Vue →
   Phase 5 删除旧实现。每一期以仓外契约回放/浏览器门禁/领域对照为验收。
4. **收尾（Phase 5）**：删除旧后端与旧前端资产；`/legacy`、`BACKEND_STACK`、
   `FRONTEND_MODE=legacy` 一并移除；缺省配置一律 fail-fast；部署顺序
   build → migrate → restart → health；`ops/rollback.py` 提供 5 分钟回滚。
5. **测试资产策略**：测试、夹具、截图基线只放仓外（`battleship-verify`）；
   仓内只保留实现与配置。

## Alternatives（替代方案与未选原因）

- **A：原生 JS 单页 + 原语化重构（不引入构建链）**：改动小、风险低，但解决不了
  "没有类型/没有模块边界/脚本顺序脆弱"的根因，AI 代理仍无法安全改大文件。
- **A′：Vue 但不带构建链（浏览器内模板编译）**：保留了无构建的部署简单性，
  但放弃 TS 类型检查、SFC 作用域样式与内容哈希，性能与可维护性都不达标。
- **继续 Flask + 增量修补**：eventlet 的时序约束、两套全局状态、单文件巨型模块
  都是结构性问题，修补只能把风险挪到下一个人。
- **保留双栈长期并行**：双份实现就是双份漂移；迁移窗口仅用于切流，Phase 5 必须删除。

## Consequences

正向：

- 规则单份实现，修复只改一处；Pydantic/TS 在编译或校验期暴露字段错误；
- 协议契约有单一来源（contracts + 生成的 TS 类型 + 哈希校验）；
- 部署可回滚（备份 + 上一版 commit/release + 健康检查，预算 5 分钟）；
- 浏览器门禁只认 `data-testid`，不再依赖脚本顺序/源码字符串；
- 缺省配置 fail-fast：漏配 `SECRET_KEY`、残留旧栈变量都会在绑定端口前失败。

代价与风险：

- 迁移期投入大（29 张子票），且旧录制基线（无连锁帧、RNG 敏感、墙钟掉线）不再是
  Phase 5 红线，部分逐事件回归转为行为门禁；
- 新前端构建链引入 Node/pnpm 依赖，部署顺序多了 build 步骤；
- 已知功能缺口保留并记录在 `docs/REWRITE_LANDING_2026_10_20.md` §6
  （动态壁纸应用/播放、help/collection/room 屏、两份 `field_magic_name` 等）；
- 跨 Phase 5 回滚需要保留旧 release 目录（旧提交没有新栈的构建脚本）。