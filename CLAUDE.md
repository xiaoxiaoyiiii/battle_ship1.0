# CLAUDE.md — 战舰棋开发入口

> 更新于 2026-11-04，上线维护阶段。协作、分支和授权以 [AGENTS.md](AGENTS.md) 为准。
> 先按任务定位源码和下方文档；历史数字、路径和结果仅代表其记录时刻，执行前核对。

## 项目与源码入口

仓库：[xiaoxiaoyiiii/battle_ship1.0](https://github.com/xiaoxiaoyiiii/battle_ship1.0)。后端为 FastAPI、python-socketio、Pydantic v2、SQLAlchemy 2 / Alembic；前端为 Vue 3、TypeScript、Vite、Pinia。

| 位置 | 职责 |
| --- | --- |
| [backend/src/battleship/main.py](backend/src/battleship/main.py) | 应用组合根，`uvicorn battleship.main:app` |
| [backend/src/battleship/config.py](backend/src/battleship/config.py) | 环境配置与校验 |
| `backend/src/battleship/contracts/` | Pydantic 模型、事件与生成契约 |
| `backend/src/battleship/domain/` | 对局、魔法、连锁、成长与排位规则 |
| `backend/src/battleship/services/`、`repositories/` | 用例和事务边界、SQL 与迁移 |
| `backend/src/battleship/realtime/`、`http/`、`infra/` | 协议适配、静态托管及运行设施 |
| `frontend/src/`、`frontend/dist/` | 前端源码、由后端托管的构建产物 |

`domain` 保持规则独立于 Web 框架和数据库；服务编排通过仓储访问数据，HTTP / Socket 层负责协议适配。胜负、结算和隐私过滤以服务端为权威，前端消费授权状态。

## 本机运行

- 日常开发树：`D:/Codex workspace/battle-ship-codex-ranked-ban-v1-20261102`，分支见根 `AGENTS.md`。
- 既有试玩：<http://127.0.0.1:5472/lobby>；库为 `D:/Codex workspace/battle-ship-local-play/.tmp/preview.db`。启动入口为 `D:/Codex workspace/Start-Battleship-5472.cmd`，先查端口，保留现有服务和 Tailscale 转发。
- 临时验证另选空闲 5xxx 端口，避开 5000 / 5060 / 5061 和正在使用的 5472；`ops/run_stack.py` 会迁移所指定的库，不能指向现有试玩或生产数据。
- `SECRET_KEY` 必填；`FRONTEND_MODE` 只接受 `spa`。配置名称与默认值查 `backend/src/battleship/config.py`；私有关卡通过 `DAILY_PUZZLES_PATH` 指定，不复制进仓库。

以下命令在开发树根目录执行。先构建前端，再启动独立验证服务；5450 仅在空闲时使用。仅验证通用界面时可使用默认关卡配置，每日挑战验收须另准备独立私有清单。

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run build

$py = 'C:/Users/Administrator/AppData/Local/Programs/Python/Python312/python.exe'
$verifyDb = Join-Path $env:TEMP ('battleship-verify-' + [guid]::NewGuid().ToString('N') + '.db')
$env:SECRET_KEY = & $py -c 'import secrets; print(secrets.token_hex(32))'
$env:CORS_ORIGINS = 'http://127.0.0.1:5450'
$env:ENABLE_TEST_EVENTS = '0'
& $py ops/run_stack.py --port 5450 --db $verifyDb
```

使用独立终端保存本轮环境；已有依赖时无需为每次验证重新安装。仅在独立测试服务且门禁确有需要时启用调试事件。

## 验证与门禁

- 仓外验证根为 `D:/develop/battleship-verify/cases/`。运行前检查入口是否存在、导入的源码目录、环境和数据库；旧脚本可能硬编码另一棵工作树，不能默认套用历史 `integration` 目录。
- 前端代码改动运行 `npm --prefix frontend run typecheck` 和 `npm --prefix frontend run build`，再验证受影响页面、主题、桌面与窄屏交互。
- **构建与依赖同一 `dist` 的 HTTP / 浏览器验证串行执行**：Vite 配置为 `emptyOutDir: true`，构建过程中会清理输出。
- 后端规则与数据改动运行对应的隔离库回归；共享棋盘、选择器或状态投影改动同时检查实战、回放、观战调用方。
- 纯文档和 Git 维护检查差异、编码、引用与分支状态，不要求启动游戏或构建前端。缺少工具、跳过项和未覆盖场景明确报告。

以下是已存在的定位入口，不是统一全量命令；先读脚本并确认其验证目标，特别区分 `test_*` 与会改库或部署的历史操作脚本。

| 目录（相对验证根） | 文件 | 用途 |
| --- | --- | --- |
| `season-mailbox-v1-20261103/` | `test_season_mailbox.py` | 跨季、重置与邮件幂等 |
| `season-mailbox-v1-20261103/` | `test_http.py`、`test_operations.py` | 赛季邮箱接口与运维行为 |
| `daily-challenge-v1/` | `test_daily.py`、`test_service.py`、`test_generate.py` | 每日挑战规则、服务与生成管道 |
| `launch-admin-20261104/` | `test_launch_admin.py` | 管理权限与测试局隔离 |
| `launch-live-mail-20261104/` | `test_opening.py`、`test_beta_gift.py` | 开季与感谢信隔离回归 |

## 契约与前端约束

- Socket 入站、出站清单查 `backend/src/battleship/contracts/events_in.py`、`events_out.py`，页面路由查 `frontend/src/router/index.ts`；不在此重复维护易漂移的数量。
- `backend/src/battleship/http/routes.py` 的 `LEGACY_ROUTES` 是 49 条历史兼容记录，不是当前 HTTP 接口总数；新增接口查 `http/routers/` 和应用注册。保持既有客户端兼容。
- 契约改动同步两端及相关门禁。`contracts/export_schema.py` 支持 `--format ts --out`；生成前端 `frontend/src/socket/events.gen.ts` 后，构建中的 `frontend/scripts/check-contract.mjs` 校验哈希。
- 卡表源为 `backend/src/battleship/domain/magic/data/magic_card.json`，由 `frontend/scripts/sync-card-data.mjs` 生成前端数据，勿手改生成文件。当前为 50 条记录、48 个唯一卡名、48 张卡图；记录数、卡名、卡图和可 Ban 池分别核对。
- 卡图经 `frontend/src/cards/cardArt.ts` 打包为哈希资源；`publicDir: false` 避免重复复制。测试钩子 `__BS_TEST_HOOKS__` 只在 test 构建启用。
- 状态位于 Pinia stores，字段约定见 `frontend/src/stores/gameStateSchema.ts`；匹配座位的 `player_id` 与账号 `user_id` 分开处理。
- 回放经 HTTP 获取；回放与观战共用 `frontend/src/screens/viewing/BattleStage.vue`，保持只读、只消费服务端授权事实，不发送实战操作或自行重算规则。
- 视觉以最新获批方案和当前实现为准。“只动颜色、不动盒模型”适用于日常微调；获批布局修改需验证响应式和交互，并有依据地更新基线，不能为通过断言直接删判据。
- 卡牌采样音效位于 `frontend/src/audio/assets/`；牌效声音消费服务端公开完成提示，避免回放或观战泄露未授权信息。

## 生产运维入口

- 公网入口为 <http://8.133.180.159:5000/lobby>。SSH 使用现有别名 `battleship-server`，服务为 `battleship.service`。
- 2026-11-04 首发使用独立 release 与 Python 3.12 环境，运行代码位于 `/opt/battleship-releases/` 下；`/opt/battleship` 是旧代码及原数据位置。操作前用 systemd 的 `WorkingDirectory`、`ExecStart` 和进程 cwd 确认实际版本。
- 真库为 `/opt/battleship/data/battleship.db`，头像为 `/opt/battleship/static/avatars`；密钥、私有关卡、日志和备份独立保存，路径与权限按实际配置核对。
- [ops/README.md](ops/README.md)、`ops/systemd/battleship.service` 和 `ops/deploy.env.example` 是流程与模板入口；与现网配置不一致时先核对，不能直接替换现网。
- 获准发布时，从批准提交构建新的独立 release，保留真库；确认所有写入方停止，制作并核验切换前备份，再迁移、切换服务入口和做健康检查。不原地覆盖运行中的 release。
- **代码回退与数据恢复分别评估**。上线后新数据必须保留；`ops/rollback.py` 会恢复所选备份，且切换布局未必等同现网，不能直接当作生产通用回滚入口。停服、恢复均须当次授权。
- 数据查询边界见 [AGENTS.md](AGENTS.md)。首季已开始，历史开季、改期、内测奖励和首发切换脚本仅供审计，不因文件存在而重跑。

## 协作与桥接入口

- 恢复外部协作或运维前，按需读本机交接：`D:/Codex workspace/战舰棋新对话交接-20261104-上线状态与双桥接.md`。其中旧分支快照由当前 `AGENTS.md` 覆盖；会话、版本、PID 和发送目标现场核对。
- DSH：先读 `C:/Users/Administrator/Documents/ds-harness-desktop/WorkSpace/.codex-loop/bridge-v1/README.md` 和当前源码；任务模板在同级 `dual-agent-worktrees/TASK_TEMPLATE.md`。核对目标会话、鉴权、真实 `CODEX_THREAD_ID`、显式 `--thread` 与独立 `--state`，先只读检查和 dry-run，再按授权执行 live。
- DSH 回复以对应轮结束、回复原文和目标窗口实际收到为验收；`delivered` 仅是投递状态，超时后先查既有交换，不重复派活。桥运行时不编辑其源码。
- Grok / Sage 的发送命令与 routine 另行核对实际 Codex 目标；本机空闲不证明云端自动化已停用。未找到真实可用的发送通道时提供可粘贴通知，不声称已送达。

## 按任务查阅

| 任务 | 入口 |
| --- | --- |
| 赛季、邮箱与运营 | [SEASON_MAILBOX_V1.md](docs/SEASON_MAILBOX_V1.md) |
| 每日挑战与候选生成 | [DAILY_CHALLENGE_V1.md](docs/DAILY_CHALLENGE_V1.md) |
| 回放、观战与公开投影 | [REPLAY_SPECTATE_V2.md](docs/REPLAY_SPECTATE_V2.md) |
| 通行证 | [season-pass-design.md](docs/superpowers/specs/2026-10-29-season-pass-design.md) |
| 布局、主题与视觉基线 | [主题与视觉方案](docs/前端视觉优化方案-20261026.md)、[重设计规格](docs/UI_REDESIGN_SPEC_2026_10_20.md) |
| 新增魔法卡 | [ADD_A_MAGIC_CARD.md](docs/ADD_A_MAGIC_CARD.md) |
| 连锁、排位、人机 | [连锁规格](docs/CHAIN_ENGINE_SPEC.md)、[排位规则](docs/RANKED_2026_09_17.md)、[大师 AI](docs/MASTER_AI_2026_09_21.md) |
| 管理员测试隔离与政策 | [LEGAL_POLICY.md](docs/LEGAL_POLICY.md)、`backend/src/battleship/http/routers/admin_console.py` |
| 领域术语与 ADR | [domain.md](docs/agents/domain.md) |
| 重写历史 | [REWRITE_LANDING_2026_10_20.md](docs/REWRITE_LANDING_2026_10_20.md)、[架构决策](docs/adr/0001-modern-rewrite.md) |
| 排查结算、AI 选择、隐私和共享组件等历史易错点 | [历史工程经验](docs/agents/历史工程经验.md)，22 条原有经验按需保留 |

历史文档中的旧源码结构、部署命令和测试结果按记录时点理解，当前任务先核对实际调用方与数据边界。
