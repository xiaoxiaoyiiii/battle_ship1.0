# 回放与观战 v2 实施计划

> 执行者：使用 executing-plans 在当前会话独立逐项执行，不派 agent。各任务按复现失败、实现、通过验证的顺序推进。

**目标：** 新录像忠实还原当局规则与状态，观战实时正确同步，两种观看共用只读舞台和连锁/牌效播放。

**架构：** 纯领域观看帧确定状态与可见性；v2 记录有序状态替换和演出，检查点支持跳转；ViewingService 负责动作提交后的录制/发布；Vue 观看舞台与本地播放时钟消费回放或公开观战适配器，不进入玩家状态与 ACK。

**技术栈：** 现有 Python 3.12、FastAPI、python-socketio、Vue 3、TypeScript、Pinia、Canvas，无新增运行依赖。

**设计：** `docs/superpowers/specs/2026-11-02-replay-spectate-v2-design.md`。

## 全局约束

- 独立实施；不桥接、不派发子任务；游戏规则、胜负、自选交互语义不改。
- 遵守 `AGENTS.md` 的 `review/main-ui-vue-port` 约定；禁止覆盖该分支已有脏工作，禁止未经授权新建分支或强制切换。
- E2/E3 词条公开信息对观众可见；其余隐藏信息保持隐藏，观战包不得包含私有选牌草稿、侦察情报或 ACK token。
- 新录像版本 2；兼容读取版本 1；2000 步、512 KiB 大小限制；检查点每 32 个状态事件。
- 现有 REST 入口/鉴权、观战开关、名单/聊天保留；新增出站事件同步契约与前端生成产物。
- 所有测试资产仓外放置，正式实现仓内；不在仓库引入 tests/ 或测试样本。
- 本地独立临时数据库与 5xxx 端口验证；不先动用户现有数据库或 5472 进程。

## 审查重点

1. 同一步多次刷新、无日志状态变化、异步选牌/重摆续做：顺序和最终状态必须一致。
2. E1/E2/E3 与私有侦察混合：只公开词条允许的信息，不把完整回放帧送给观众。
3. 动画尚未落点或暂停时收到新帧：展示不能提前穿帮，跳转必须清旧演出。
4. 重连/迟到/重复数据：新基线替换旧局面，旧 seq 不回滚画面；换房不共用 seq。
5. v1/截断/空间上限：保留内容自洽，不让后期快照污染早期步骤；未录内容不能伪造。

## 执行前准备

- [ ] 阅读设计、诊断报告、当前 `AGENTS.md` 与 `CLAUDE.md`，重新核对分支、脏文件、5472 进程和 DB 路径。
- [ ] 解决指定分支已有脏工作与本任务隔离的问题：禁止 `reset --hard`、强制 branch 移动、覆盖旧工作；如现有串行所有权无法确认，将准确路径/差异列给用户决策。
- [ ] 在本计划自己的进度账本记录完成批次、验证命令/结果、提交 SHA 和明确裁定；恢复时先查账本和 Git，不重做已完成工作。
- [ ] 运行现有诊断复现与前端 typecheck，记录基线。上下文索引本轮已尝试，因 F: 不存在不可用，已回退实际源码精确搜索；不将修索引混入本任务。

## 任务 1：权威观看帧与词条可见性

**文件**

- 新建：`backend/src/battleship/domain/viewing.py`。
- 按需修改：`backend/src/battleship/domain/mutations/rules.py`（仅复用/导出公开投影，不改玩法）；`domain/room/models.py`（只增加观看序号/提交钩子的明确状态）。
- 仓外新建：`D:/develop/battleship-verify/cases/replay-spectate-v2/test_projection.py`。

**接口**

- `build_view_frame(room: Room, *, audience: Literal['replay','spectator']) -> dict[str, Any]`。
- `freeze_rules(room: Room) -> dict[str, Any]`；只从已冻结的房间配置获取本局规则，不能重新 roll 或根据当前 calendar 重选。
- `public_cue(cue: dict[str, Any], room: Room) -> dict[str, Any] | None`：显式白名单公开演出，丢弃私有定位与玩家完成 token。

- [ ] 先写并运行失败用例：p1 攻击 `(5,1)`，预期出现在 `boards.p2`；复活后标记列表为空；E1 空炮事实保留但可见标记为空。
- [ ] 增加可见性用例：普通对局 hand_count 可见但 hand 不可见；E2 公开双方牌名；E3 公开的点位可见，未公开舰位和私有雷达结果不可见。
- [ ] 增加冻结用例：变更 calendar/卡表后，frame.rules 仍使用 room 中保存的 entries 与实际骰子/舰数；空词条、排位均为空配置。
- [ ] 实现上述纯模块；深复制输出，后续修改 Room 不能倒改已捕获的帧。
- [ ] 运行：`python -B -m unittest discover -s D:/develop/battleship-verify/cases/replay-spectate-v2 -p test_projection.py -v`。预期全部通过，domain 不导入网络/DB。
- [ ] 暂存明确文件并以中文提交，记录 SHA。

## 任务 2：v2 录像、服务提交点与旧格式读取

**文件**

- 新建：`backend/src/battleship/domain/replay_v2.py`、`backend/src/battleship/services/viewing.py`。
- 修改：`domain/replay.py`、`services/replays.py`、`services/magic.py`、`services/gameplay.py`、`services/priority.py`、`services/rooms.py`、`realtime/server.py`；仅为记录/投影/提交接线。
- 仓外测试：`test_recording.py`、`test_replay_access.py`、`test_commit_boundaries.py`。

**接口**

- `record_state(room: Room, *, step: int, cause: str) -> int`：捕获权威帧、生成有序板块替换，返回当前 seq。
- `record_presentation(room: Room, cue: dict[str, Any], *, step: int) -> int`：独立记录演出顺序，不产生规则副作用。
- `finalize_v2(room: Room) -> dict[str, Any] | None`：v2 打包、完整后缀裁剪、大小上限和显式截断。
- `ViewingService.commit(room: Room, *, cause: str = 'state') -> None`（异步）：统一录制和观战发布；同局状态无变化不重复产生状态事件。
- `ViewingService.present(room: Room, cue: dict[str, Any]) -> None`（异步）：保存完整演出并发布净化演出，不等待观众 ACK。

- [ ] 先复现失败：同一 step 连续加两炮应保留两炮；复活删除、重摆替换、C3 弃牌付费后无日志同步都必须记录。
- [ ] 建立所有权威写入口清单：真人动作、AI、超时、阶段续做、选牌/数字/舰船确认、补舰/重摆提交、E3 亮舰、投降/断线终局。逐个测试确实进入同一提交路径。
- [ ] 以房间串行锁最外层成功提交为默认边界；显式覆盖不经该边界的路径。牌效前导、落点、尾声按原发生顺序录入；不改变已有结算等待逻辑。
- [ ] 实现状态板块替换与 32 事件检查点；测试变更后数组清空、同一步多个状态和演出先后、输入对象后续变动不会污染旧帧。
- [ ] 修改读版本集合为 `{1,2}`，保留权限判定和 seats 剥离；验证 401/403/404/409/500，不改变存档用户开关。
- [ ] 测试 2000 步和 512 KiB：保留前缀可还原、截断原因可见；不得拿未来最后帧冒充较早状态。
- [ ] 运行对应三个 test 文件的 unittest；预期全部通过，并校验原有 HTTP 入口与结算落库流程。
- [ ] 中文提交，账本记录写入口清单、测试结果与 SHA。

## 任务 3：实时观战权威流、契约和重连

**文件**

- 修改：`domain/spectate/rules.py`、`services/spectators.py`、`services/viewing.py`、`contracts/events_out.py` 及实际声明对应事件模型的文件、`realtime/server.py`。
- 修改：`frontend/src/realtime/spectate.ts`、`frontend/src/stores/spectate.ts`。
- 生成：`frontend/src/socket/events.gen.ts`，由现有 export_schema 生成，不能手改哈希。
- 仓外测试：`test_spectator_stream.py`、`spectator-store.mjs`。

**接口**

- `SpectatorService.publish_view_frame(room: Room, frame: dict, *, seq: int, cues: list[dict]) -> None`。
- 新出站 `spectate_frame`：`{version:2, room_id, seq, frame, cues}`；`spectate_sync.viewing_frame` 为同形初始基线。
- 前端 `applyViewingFrame(payload: unknown): boolean`：检查 room_id、版本与 seq；接收成功返回 true；只把公开帧放入观看状态。

- [ ] 先运行失败服务用例：“无中生有”前 1 张、后 2 张，观战最终帧 handCount=2；复活、补舰、清标记和冻结均同步。
- [ ] 添加 E2/E3 正例与私有雷达/疗愈落点/ACK token 负例，检查实际观战频道事件内容。
- [ ] 加入、中途加入与重连发送完整基线；新房间重置 seq；迟到/重复帧丢弃，名单/聊天不受影响。播放状态不能被旧镜像增量覆盖。
- [ ] 验证观众不进入玩家 room 或 players，不发送玩家动画完成事件；观众退出、断线和慢动画不改变比赛状态。
- [ ] 更新后端契约，用 `python -B -m battleship.contracts.export_schema --format ts --out <worktree>/frontend/src/socket/events.gen.ts` 生成；设置 PYTHONPATH 指向 backend/src。
- [ ] 运行服务 unittest、仓外 Node 状态测试，以及 `npm run check:contract`、`npm run typecheck`。预期全部通过。
- [ ] 中文提交，账本记录契约变动与 SHA。

## 任务 4：统一前端观看模型和连续战斗舞台

**文件**

- 新建：`frontend/src/screens/viewing/types.ts`、`frame.ts`、`BattleStage.vue`、`ViewingRules.vue`、`viewing.css`。
- 修改：`screens/replay/model.ts`、`stores/replay.ts`、`screens/replay/ReplayScreen.vue`、`screens/spectate/view.ts`、`screens/spectate/SpectateScreen.vue`。
- 复用：`screens/game/BoardPanel.vue`、`BoardCellIcon.vue`、`cellPresentation.ts`；只在需要解耦纯展示时修改，不改 GameScreen 交互。
- 仓外测试：`replay-model.mjs`、`viewing-ui.cjs`。

**接口**

- `decodeRecording(raw: unknown): Recording | null`：显式解析 v1/v2。
- `frameAt(recording: Recording, step: number): ViewFrame`：v2 从最近检查点应用替换，v1 通过兼容适配器恢复。
- `boardCells(frame: ViewFrame, owner: Side): BoardCell[]`：保持棋盘所有者语义，不在多个层重复转置。
- BattleStage 属性：`frame: ViewFrame`、`focus: Side`、`mode: 'replay' | 'spectate'`；全部棋格只读，不发出规则动作。

- [ ] 先运行五份真实 v1 样本的第一炮断言，必须看到方向错误的红灯；为 v2 构造独立预期帧，验证清除、替换和向后跳转。
- [ ] 保留 v1 phase/round/chain 上下文；显示旧录像能力提示，不伪造缺失演出。
- [ ] 搭建单一连续海域舞台：双方棋盘共用容器、中线和玩家定位；授权手牌用实际卡面展示，隐藏手牌只显示数量；规则摘要引用冻结文案。
- [ ] 桌面并列，窄屏上下相邻；保留退出、日志、观战聊天、播放操作与原有可保留的 data-testid。没有攻击/出牌/布船按钮。
- [ ] 验证五种目标尺寸页面无横向溢出，播放条可操作，不重叠文字，规则和日志抽屉不撑坏棋盘。
- [ ] 运行模型/浏览器断言与 typecheck/build；预期上述真实样本方向全通过、页面状态与权威帧一致。
- [ ] 中文提交，账本记录截图路径与 SHA。

## 任务 5：只读演出、暂停倍速与跳转时钟

**文件**

- 新建：`screens/viewing/playback.ts`、`ViewingAnimationLayer.vue`、`useViewingPlayback.ts`。
- 修改：回放/观战屏幕与 store 的播放接线；按需拆分现有 `ChainAnimationOverlay.vue`、`CardEffectOverlay.vue` 的纯绘制适配。
- 复用：`game/chainAnimation.ts`、`chainAnimationCanvas.ts`、`chainStageLayout.ts`、`cardEffects/timeline.ts`、`cardEffects/canvas.ts`。
- 仓外测试：`playback-clock.mjs`、`viewing-animation.cjs`。

**接口**

- `ViewingPlayback`：`load(recording)`、`play()`、`pause()`、`setSpeed(1|2|4)`、`seek(step)`、`enqueue(packet)`、`advance(now)`、`dispose()`。
- `advance` 返回当前只读帧和演出帧；now 来自注入时钟。观看层不读/写玩家 game store，不发规则或 ACK。
- 实时队列上限 32 个包或累计演出 8 秒；超过任一值清除过期演出并恢复最新完整权威帧。新局/重连先清旧队列。

- [ ] 先用可控时钟断言暂停不推进、2×/4×时长按比例、动画命中前后状态正确；旧固定 900ms 切步方案应无法满足这些断言。
- [ ] 测试多卡连锁顺序、单卡展示、失灵无效化、失败牌效、自选完成后的结算；只展示记录结果。
- [ ] 在动画中向前/向后 seek、换录像、退出，断言旧卡面/格子高亮/声音/计时器均取消，跳过区间不重播。
- [ ] 观战积压、重连、页面隐藏和减少动态效果，断言最终状态正确、队列有界，玩家推进不等待观众。
- [ ] 运行时钟测试、浏览器演出检查与 typecheck。预期真实多卡样本/新局都有可见连锁和对应结果，不再只有顶部文字。
- [ ] 中文提交，账本记录时序证据与 SHA。

## 任务 6：真实对局、词条矩阵与完整收尾

**文件**

- 仓外新建：`test_mutation_matrix.py`、`live-match.cjs`、`verify.py` 和 `evidence/`。
- 仓内更新：本设计/计划进度、与协议相关的项目说明；不提交本机用户录像或临时账号数据。

- [ ] 实际双玩家加观众运行新完整比赛；使用隔离 DB / 5xxx 端口，完成后从真实 HTTP 读回录像，逐动作比较权威状态、观战投影与回放帧。
- [ ] 覆盖 14 个现有词条及合法代表组合：A1+复活/补舰、A4+C3无合法牌、B3跨双方小回合、C3在对方准备阶段付费、D1骰子、D2第5大回合、E1重复空格炮击、E2手牌、E3永久公开与重摆/复活。
- [ ] 覆盖 needs_reset / 绝处逢生、选牌和选数字、弃牌、护盾/冻结/孔洞/场地、自选交互中断与恢复、投降终局；结果必须遵守真实规则，不由播放状态决定胜负。
- [ ] 保留五份 v1 历史样本兼容，检查权限和截断提示；旧样本不能声称补回从未保存的数据。
- [ ] 运行仓外全部新增门禁；前端 typecheck、契约检查和生产 build；检查 diff 与中文文档/提交信息。
- [ ] 实际查看目标尺寸截图和演出，验证页面无溢出、按键无重叠、旧棋盘信息卡被统一舞台替代；不只凭编译成功判定体验。
- [ ] 自审整个变更：重点检查 public/full 帧隔离、落库限额、异步写入口、播放器取消、玩家动画 ACK 完全不受影响。用户要求独立完成，自行复核，不派审查 agent。
- [ ] 输出结果报告、测试数/失败与未覆盖项、截图、提交 SHA。需要更新 5472 或远端前，核对本任务授权和原进程/路径，不覆盖旧工作。

## 计划自审记录

- 设计覆盖：数据正确性、词条冻结、E2/E3 用户决定、公开信息隔离、只读舞台、演出、旧格式与上限分别有对应任务和验收。
- 接口衔接：任务 1 的 ViewFrame 供 2/3/4 使用；任务 2 的 seq/检查点供 4/5；任务 3 的包供 5；任务 4 的舞台消费 5 的展示帧，不读取玩家 store。
- 依赖风险：当前仓外旧门禁目录并非完整历史套件，不能承诺其全部存在或已通过；本计划新建必要的独立门禁，不引入仓内测试资产。
- 状态：用户已明确确认按此方案独立执行；进度见本计划专属账本。
