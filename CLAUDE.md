# CLAUDE.md — 战舰棋 · 竞技场（现代重写版）

> 面向 AI 代理的索引。**先读这里，再 grep 定位，别整文件通读。**
> 行号每次提交都会漂移；本文件里任何行号都只当线索，以 grep 为准。
> 本文件每次对话整份注入 —— 新增内容控制在几十字，长记录写 `docs/`。
> 最后更新：2026-10-20（Phase 5 收尾：#30 删除旧实现，单一新栈）。

---

## 0. 速览

实时双人海战棋 + 48 种魔法卡 + 连锁系统；账号、段位、等级、成就、名片、大厅、人机、
自定义房、断线重连、观战、回放。

- **后端**：FastAPI（ASGI）+ python-socketio + Pydantic v2 + SQLAlchemy 2.x / Alembic，
  入口 `backend/src/battleship/main.py` 的 `app`（`uvicorn battleship.main:app`）。
- **前端**：Vue 3 SFC + TypeScript + Vite + Pinia + vue-router，源码 `frontend/src`，
  构建产物 `frontend/dist` 由后端同一 ASGI 应用托管。
- **运维**：`ops/`（build / migrate / healthcheck / rollback / systemd），见 [ops/README.md](ops/README.md)。
- **只有一个栈**：没有旧实现、没有 `/legacy`、没有 `BACKEND_STACK` 开关。
  旧变量的残留一律 fail-fast（D30）。
- 线上 http://8.133.180.159:5000/ ｜ 仓库 `1w6qn/battle_ship1.0`

---

## 1. 运行与测试

```powershell
python ops/build.py --frontend-only                 # 构建前端（首次或改前端后）
python ops/run_stack.py --port 5450 --db .tmp/dev.db  # 迁移 + uvicorn，一键起全栈
python ops/healthcheck.py --url http://127.0.0.1:5450/health
```

- `SECRET_KEY` 必填，缺失/为空启动即失败并点名变量。
- `FRONTEND_MODE` 只接受 `spa`；写 `legacy` 启动即失败（旧前端已删除）。
- 端口避开 5000/5060/5061；本地验证用 5xxx 段，每次换独立 `BATTLESHIP_DB_PATH`。
- **测试资产不入仓**（D4）：单元/契约/E2E/浏览器门禁都在仓外
  `D:/develop/battleship-verify/cases/`、`tools/web/`；仓内没有 `tests/`、`tools/`。
- 仓外门禁默认对 **integration** worktree 跑（D7），实现期显式传 `--worktree`/env。

### 仓外门禁速查

| 套件 | 覆盖 |
| --- | --- |
| `cases/30-cleanup` | 旧实现已删、单栈冷启动、路由表、构建含 48 卡面、ops dry-run、文档与公告 |
| `cases/4`–`19` | 组合根、数据层、鉴权、房间、布船、对局、魔法、连锁、AI、大厅、成长、排位、观战、回放、HTTP |
| `cases/21`–`33` | 前端壳与逐屏（home/profile/lobby/game/replay/visual/gaps） |
| `tools/web/run_all.py` | 22 个 `data-testid` 浏览器门禁（含截图指纹基线） |

`SKIP` 不是绿色：每条 SKIP 必须有归因（当前允许 rank-help / room / collection）。

---

## 2. 分层与依赖方向

```
backend/src/battleship/
  contracts/     Pydantic 模型 + JSON Schema + 事件清单（唯一契约来源）
  domain/        纯规则：对局/布船/魔法/连锁/段位/经验/成就/反作弊/匹配
  services/      用例编排与事务边界（settlement 是一次提交）
  repositories/  唯一写 SQL 的地方（SQLAlchemy 2.x + Alembic 迁移）
  realtime/      Socket.IO 适配（handlers/emitter/identity/timers）
  http/          REST 路由、会话、错误体、静态与 SPA 托管
  infra/         配置、日志、指标、健康检查、限流
```

- 依赖方向：contracts → domain → services → repositories → realtime/http → infra。
- **domain 不 import 框架与数据库**；services 不拼 SQL；realtime/http 只做协议适配。
- 后台任务（掉线宽限、连锁/回合超时）是 asyncio 定时任务，房间销毁时显式取消。

---

## 3. 冻结契约（改任何一项都要同步两端 + 仓外门禁）

- **Socket.IO**：入站 61（47 普通 + 14 调试，调试事件必须 `ENABLE_TEST_EVENTS=1`）；
  出站 89（82 字面量 + 7 参数化：friend_* / recent_opponent / spectate_joined|left）。
- **HTTP**：49 条冻结路由登记在 `backend/src/battleship/http/routes.py`
  （`LEGACY_ROUTES`，这个名字是历史资产，指"迁移期冻结的客户端面"）。
  新栈另有 health/metrics/contracts/docs 与 SPA 入口，不在这 49 条里。
- **页面**：只有一个 SPA 入口（`GET /` + catch-all）；`/lobby`、`/leaderboard`
  等是客户端路由。`/legacy` 已删除（404）。
- **ack**：`43<ackId><JSON>`，没有长度位；handler 抛异常时不回 ack（客户端会超时）。
- **身份**：匹配房 `room.players` 的 key 是入队 sid；真实 user_id 在 `Player.user_id`，
  客户端一律用服务端下发的 `player_id`。
- **回放**：只有 HTTP（`GET /api/replay/<match_id>`，200/401/403/404/409/500）。
- **错误体**：已录制的线上路由保持旧形状 `{"error":"..."}`（D19）；4 条未录制路由
  仍是结构化 `{"error":{code,message,field}}`（D26）。
- **契约产物**：`contracts/export_schema.py` 导出 JSON Schema 与
  `frontend/src/socket/events.gen.ts`；构建前 `frontend/scripts/check-contract.mjs`
  校验哈希，契约改了必须重新生成并重跑构建。
- **卡表**：卡面数据单一来源 = 后端 `domain/magic/data/magic_card.json`（build 期由
  `frontend/scripts/sync-card-data.mjs` 生成前端 `src/cards/card_data.json`，勿手改）；
  新卡 = 牌表一条 + `@register` 一个效果，见 [docs/ADD_A_MAGIC_CARD.md](docs/ADD_A_MAGIC_CARD.md)。

---

## 4. 前端

- 11 条冻结路由：`start / placement / rps / game / lobby / leaderboard / profile /
  settings / replay / spectate / game-over`（`frontend/src/router/index.ts`）。
- 状态在 Pinia store（`frontend/src/stores`），**没有 `window.gameState`**；字段有
  Schema 与默认值（`gameStateSchema.ts`）。
- 交互契约是 `data-testid`，不是 DOM id；测试钩子只在 test 构建里注入
  （`__BS_TEST_HOOKS__`），生产构建剔除。
- 卡面：`frontend/public/card_faces/*.webp`（48 张），由 `src/cards/cardArt.ts`
  的 `import.meta.glob` 在构建期打包成内容哈希资产；缺图返回 `null`，卡片退化无美术层。
  `publicDir: false`：同一批图不会在 dist 里再出现一份未哈希拷贝。
- 视觉基线是 C+ 十屏；只允许改颜色/阴影/渐变/transform/opacity，不许动盒模型尺寸；
  改样式后必须跑 `tools/web/run_all.py` 对应工具 + 截图指纹。
- 音效/BGM 是 Web Audio 现场合成，没有素材依赖。

---

## 5. 部署、迁移、回滚

- 顺序：`ops/build.py` → `ops/migrate.py`（Alembic + 备份 + 校验）→
  `systemctl restart battleship` → `ops/healthcheck.py`。
- systemd 单元：`ops/systemd/battleship.service`（uvicorn，`EnvironmentFile`）；
  环境变量模板：`ops/deploy.env.example`。
- 回滚：`ops/rollback.py`（校验备份与目标 → 停服 → 安全副本 → 恢复备份 →
  切 commit/release → 重建前端 → 健康检查），预算 5 分钟；步骤见 `ops/README.md`。
- 数据库：Alembic 首个 revision 表达 21 张业务表 + 索引 + 视图；空库与旧库都可重复执行。

---

## 6. 旧栈教训（历史结论，仍然适用）

> 旧实现已删除；这些结论来自那 13k+ 行单文件后端的真实事故，重写没有豁免它们。

1. **同一个业务判断有两份实现就一定会漂移**（放置合法性、攻击次数、段位曲线都栽过）。
   → 规则只留一份；删不掉的镜像（前端置灰要用的表）必须用测试钉住两张表。
2. **"会兜底"的取数函数不能当判据**：无打点时退回 `created_at`（恒非 0）让"开没开打"
   变成没门禁 → 赛前投降能刷分。未知一律用 `-1`，判据写显式区间。
3. **"先清空再填充"的渲染必须先校验数据、失败时保留上一帧**，否则空白手牌。
4. **"已做过某事"只在事情真的发生时才写**：把"动作"当"结果"记进 `attacks`，
   会让盾挡下的格子被永久锁死。
5. **取数顺序是命门**：连胜/连败必须在写库之前取，否则首胜白拿连胜加成，且不报错。
6. **静默 `return null` / 兜底 `except` 是最贵的写法**：AI 出牌闸门吞掉 TypeError 后
   "一张牌都不出"看起来完全健康。失败必须带原因；兜底 except 必配"绝不静默"的守卫。
7. **恒等式拦不住方向写反**：`base+Σ==total` 全绿，判据写反仍会让每局败仗送分。
8. **统一入口之后必须反查"还有谁在渲染同一份东西"**：靠 grep 渲染出来的文案，
   比 grep 函数名有效。
9. **改共用函数先 grep 出全部调用点、按 kind 逐个表态**（放置口径改动漏掉一张卡 →
   六格全灰点不动）。
10. **白名单与黑名单永远不许有交集**；新增房间级状态要三件齐：`__init__` 初始化 +
    明确消费点 + 回归用例；分支里别随手 return（会静默吞掉后续收尾）。
11. **隐私过滤只有服务端拦得住**：前端断言会假绿，必须用别人的身份直读接口、两侧都断言。
12. **"解锁/开关"最容易"看着有、其实永远不触发"**：必须有一条走真接口的端到端断言。
13. **在线表只能有一份**：旧的裸 sid 集合补名字就会长出第二份结构 → 统一读同一个 presence。
14. **工具假红先怀疑工具**：残留无头进程、旧文档 readyState、持久 profile 都会假红；
    "只能靠重试"本身就是没查清的信号。判据要就地记在事件到达的那一刻。
15. **别把"偏好"当"判据"**：配对偏好只影响排序，绝不决定"给不给排位分"。
16. **被测对象是"某个座位"而不是"某个房间"时，判据必须能按座位取**；
    看到漂亮数字先问"这会不会是什么东西的复制品"。
17. **随机源必须可复现**：无参 `random.Random()` 用系统熵播种，会让所有对照实验变成噪声。
18. **AI 座位上的交互必须就地同步完成**；要等真人回答的卡，回答之前不许返回成功，
    更不许宣称完成；AI 给不出交互参数就别打那张卡。
19. **单槽 = 隐藏的数据丢失**：同一时刻可能有多方请求的状态，用按 owner 分组的队列；
    裸布尔（"有人在选"）要记归属（kind + label）。
20. **清理函数必须自己 `removeEventListener`**，不能只把引用置空。
21. **模块名是 `__main__` 时不许被别的模块 import**：新栈用 `uvicorn` 导入
    `battleship.main:app` 字符串目标，避免同一应用被建两份。
22. **部署环境变量只在 systemd 里**：命令行手测少了 env 会得到假红/假绿；
    验收脚本要按部署环境带 env 再跑。

---

## 7. 文档索引（按需读，不要全读）

| 文档 | 内容 |
| --- | --- |
| [docs/REWRITE_LANDING_2026_10_20.md](docs/REWRITE_LANDING_2026_10_20.md) | 重写落地：架构、目录、契约、门禁、回滚、残余 |
| [docs/ADD_A_MAGIC_CARD.md](docs/ADD_A_MAGIC_CARD.md) | 新增魔法卡：牌表 + 效果 + 卡面 + 门禁 |
| [docs/adr/0001-modern-rewrite.md](docs/adr/0001-modern-rewrite.md) | 重写决策与替代方案 |
| [ops/README.md](ops/README.md) | 构建/迁移/部署/5 分钟回滚 runbook |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 历史部署事故记录（旧栈），现行步骤看 ops |
| `docs/CHAIN_ENGINE_SPEC.md` | 连锁引擎规格 |
| `docs/RANKED_2026_09_17.md` | 段位与排位 |
| `docs/MASTER_AI_2026_09_21.md` | 大师 AI 设计与度量 |
| `docs/SPECTATE_*` · `docs/REPLAY_2026_09_23.md` | 观战与回放 |
| `docs/UPDATES_2026_09_19.md` | 玩家公告文案规矩 |
| `docs/agents/domain.md` | 领域文档（GLOSSARY + `docs/adr/`）约定 |

历史 `docs/` 里的行号与旧文件结构只作考古，不要照着改新代码。

---

## 8. 开发约定

1. 不要一次读完大文件 —— 先 grep 定位。
2. 重活交子智能体；独立上下文不撑爆主会话。
3. 修 bug 前先实测复现（静态分析在本项目多次误报）。
4. 不要用脚本做全局字符串替换（反引号与 `${}` 尤其危险）；改完立刻 typecheck + 跑门禁。
5. 不用 `Get-Content -Raw | Set-Content` 改 UTF-8 源码（本机按 GBK 读写会写坏中文）；
   用编辑工具或 python 显式 `encoding='utf-8'`。含中文的 `.ps1` 必须存 UTF-8 带 BOM。
6. 跑 E2E / 工具要隔离数据库：`BATTLESHIP_DB_PATH=.tmp/xxx.db`。
7. 分支与写入交接遵循根目录 `AGENTS.md`；后续默认在用户指定的既有分支工作。
8. **提交说明只写"改了什么"**：一句话，不写根因分析、验证清单、账号参数。
9. **每批更新往 `backend/src/battleship/domain/social/changelog.py` 最上面加一条玩家公告**：
   口语、≤40 字、不写技术词与账号参数（规矩见 `docs/UPDATES_2026_09_19.md`）。
10. 测试、夹具、截图基线不入仓（D4）；新门禁写到仓外 `cases/<票>/`。
