# 2026-09-13 全量缺陷审计与修复

> 方法：**真实 socket 双客户端端到端 + 无头 Edge + 全量 pytest** 三条腿互相印证，
> 不采信"看代码猜结论"。所有缺陷都先复现、后修复、再用同一手段复测。
> 本轮基线：修复前 `295 passed`，修复后 **`374 passed / 0 failed`**（六批合计新增 79 条 pytest 回归 + 5 个新的无头浏览器检查工具）。

---

## 1. 实测手段

| 手段 | 命令 | 用途 |
| --- | --- | --- |
| 全量测试 | `& .venv\Scripts\python.exe -m pytest tests/ -q` | 回归基线（本轮 295 → 316） |
| 布局不变量 | `node tools/ui_layout_check.mjs --url http://127.0.0.1:5057/` | 宽屏 + 6 个移动视口 × 10 项，含「页面零 JS 异常」 |
| 战绩弹窗 | `node tools/stats_modal_check.mjs --url ...` | 真库数据下的历史/配色/人机标签/窄屏 |
| 全卡 E2E | `$env:E2E_URL='...'; python tools/e2e_magic_cards.py` | 双客户端按前端真实协议逐张打 42 条 |
| 人机房 | `python tools/verify_ai_room.py`（改端口） | 建人机房→布船→猜拳→AI 自动整回合 |
| **本轮新增**：匹配/重连/整局/终局门禁/连锁窗口 5 组脚本 | 见第 3 节 | 覆盖此前完全没有自动化验证的链路 |

> 跑测试不会再污染正式库：`tests/conftest.py` 把 `BATTLESHIP_DB_PATH` 指向临时目录。
> 修复前实测「一次全套测试就往 `data/battleship.db` 写约 5 行 matches/match_logs」，
> 库里已沉淀数百条 winner_id 为 `u1`/`p1`/`p2` 的测试记录。

---

## 2. 修复清单

### 🔴 P0（可用真实 socket 复现）

| # | 现象 | 根因 | 修法 |
| --- | --- | --- | --- |
| 1 | **终局后 `place_ships` 把对局复活**：`game_over` → `rock_paper_scissors`，且该房间再也不会被 reaper 回收 | 该 handler 只校验房间/玩家/身份与船数据，**不看 `state`** | 新增 `@_require_live_room` 装饰器（写在 `@socketio.on` 内侧） |
| 2 | **终局后 `surrender` 翻转胜负**：胜者在结算界面点投降即变负；登录用户还会二次记账 | 同上，`surrender` 无 `game_over` 守卫、无幂等 | 同上 |
| 3 | **`rps_choice` 非法出拳**：第一人出非法拳 → 结算时 `win_conditions[c1]` 抛 KeyError，handler 异常、双方都拿不到 `rps_result`（猜拳卡死）；第二人出非法拳 → 走 `else` 分支，**出非法拳的一方直接获胜** | 没有枚举校验，任意字符串直接进 `rps_choices` | handler 加枚举校验 + `determine_rps_winner` 兜底（脏数据只判重猜） |

### 🟠 P1

| # | 现象 | 修法 |
| --- | --- | --- |
| 4 | 终局后仍可出魔法卡进连锁、`end_turn`/`enter_end_phase` 仍能推进回合 | `@_require_live_room` 覆盖 16 个写操作 handler |
| 5 | 连锁响应窗口开着时**仍可继续攻击**，而 `end_turn` 早已被同一条件拦住（同一状态两种口径） | `handle_attack` 补 `chain/chain_waiting` 校验 |
| 6 | 桃园结义「对方再选一张」被忽略：前端发了 `opponent_choice`，`confirm_magic_target` 固定取"第一张不是施法者选的" | 采用 `opponent_choice`（带合法性回退） |
| 7 | 加百列之光**被前端"补刀"**：后端已按 `field_magic_owner` 保留施法者自己的场地，前端又 emit `remove_field_magic`（而服务端允许归属者自删）把它拆了 | 删除该 emit，场地拆除全权交服务端 + `field_magic_updated` 广播 |
| 8 | 神之宣告**牺牲的两艘船其实是随机的**：`playMagicCard` 对神之宣告提前 return，`own_ships` 选择器与配置**都不可达**，服务端只能 `random.shuffle` 补 | 效果选择后进入"点选两艘自己的船"，`confirmMagicTarget` 把 `effect_choice` 一并带上 |
| 9 | **已沉船仍留在 `player.ships`**（普通击沉只减计数、不移除）→ 钢筋铁骨 `pop()` 可能弹到沉船（零代价发动）；沉船堆出现重复条目 → 复活类卡牌按 `len(sunken_ships)` 恢复时把船数算多（幽灵船） | 钢筋铁骨 / 神之宣告 / 绝处逢生 一律只从"还活着的船"里取，入堆前查重 |
| 10 | 建了但一直没人入座的房间**永不回收**（每误点一次"创建房间/人机对战"泄漏一个 GameRoom） | reaper 增加 `_WAITING_ROOM_TTL`（1 小时）+ `GameRoom.created_at` |
| 11 | **重连后自己棋盘的伤损全部消失**：快照只发"我打出去的格"，前端渲染依赖 `opponentAttacks`，而它只在实时 `attack_result` 里 push | 快照补 `opponent_attacks`，`applyRoomSync` 恢复 |
| 12 | 重连正好落在连锁响应窗口内时**无法再响应**（只存了 `chainWaiting`，没人读） | 响应弹窗抽成 `showChainRequestPrompt`，`room_sync` 时按 `chain_window` 归属补弹 |
| 13 | 连锁结算后「当前连锁 (N)」永久残留（服务端结算只发 `chain_resolved`，不再发 `magic_chain_updated`） | `chain_resolved` 里清空 `gameState.chain` 并刷新 |
| 14 | `get_magic_temp_data` 对任何房内玩家原样返回，**对手可读到桃园结义抽出的候选牌**（卡面写明对方不可见） | 只下发给当事人（按 `caster`/`pending_*` 归属判断） |
| 15 | 场地被拆除后 `gameState.fieldMagic` 仍留着旧卡名（教皇旨意等判断会读到过期场地） | `updateFieldMagicUI` 清空分支同步重置 |
| 16 | 越战越勇文案「攻击次数增加2次」与实现/卡面（净 +1）不符 | 文案改为"击沉对方战舰时攻击次数净增加1" |
| 17 | `/api/leaderboard` 硬编码 100，`?limit=` 被完全忽略（实测 `?limit=2` 返回全部 9 行） | 支持 limit 参数并钳制到 1~100（实测 1→1 行、2→2 行、100→9 行） |
| 19 | **连锁响应窗口内无法给「需要目标」的速阶 3 卡选目标**：点卡后固定发 `targets: []`，神威！/轰炸/冻结/硫磺火焰/探测雷达 的后端分支缺目标直接失败 | 点卡后先走目标选择器，确认后把 targets 回填给 `chain_response`；新增 `tools/chain_target_check.mjs`（24 项无头浏览器断言，真实点选棋盘/弹窗） |
| 20 | **平等条约无法无效化区域魔法造成的船数变化**（溅射/轰炸/硫磺火焰各自内联结算、不写快照）；**无瑕圣心**在区域击沉时只置 `no_damage`、不中断 | 新增 `_on_ship_destroyed`：普通攻击与三种区域魔法共用同一份副作用（快照 + 百亿补贴 + 无瑕圣心中断） |
| 21 | `select_magic_target` 与 `confirm_magic_target` 两套独立实现语义漂移（桃园剩余牌进弃牌堆 vs 放回牌堆、忽略 `opponent_choice`） | `select_magic_target` 只做白名单过滤，随后委托给在用实现 |
| 22 | 12 个 `test_*` 高危事件只有 1 个有回归；**连锁超时/窗口推进/能否响应零覆盖** | 新增 `tests/test_guardrails.py`（24 条：事件参数化 + 连锁纯函数与超时代际令牌） |
| 29 | **卡牌图鉴只有平铺列表**（无检索、无筛选） | 帮助弹窗升级为图鉴：去重 41 张 + 速阶/类型筛选 + 关键词搜索 + 计数 + 空状态。回归：`tools/card_compendium_check.mjs`（16 项） |
| 25 | **冻结的船在棋盘上完全看不出来**（服务端只改 `ship.frozen`，前端从未收到该状态） | `_emit_player_ships`/`_build_room_sync` 带上 `frozen`，冻结与解冻都推送；前端加 `frozen` 类 + CSS 雪花。回归：3 条 pytest + `tools/ui_layout_check.mjs` 3 项浏览器断言 |
| 30 | **探测雷达/雷达子弹的显形只亮 4 秒**（且任何一次重绘都会丢） | 改为持久高亮：`gameState.revealedCells` + 重绘重上色 + 重开棋盘清空。回归：`ui_layout_check.mjs` 3 项（含 4 秒后仍在） |
| 32 | **卡牌没有任何使用数据**（图鉴只有卡面，看不出哪张卡常用） | 新增 `card_usage` 表 + `GET /api/card_usage` + 出牌记账；图鉴显示「使用 N 次」并可按使用次数排序。回归：`tests/test_card_usage.py`（9 条）+ `card_compendium_check.mjs` 新增 3 项 + socket e2e |
| 33 | **BGM 永远不响**（`static/music/` 不存在，6 条路径全 404） | 自动切换到**内置合成环境音**（Web Audio，零素材）+ 暂停/音量/静音联动 + 上/下一首不再触发 404；顺带修掉自动播放被拦时的 console.error 刷屏与状态覆盖。回归：`tools/bgm_check.mjs`（13 项） |
| 31 | **没有任何回合计时**（只有连锁窗口有 10 秒超时，炮击/准备阶段可无限长考） | 后台看门狗 `_auto_act_on_timeouts` + `TURN_TIMEOUT_SECONDS`（默认 90）：超时只做一次保底动作、不判负；每次成功操作重置计时；人机/连锁/点选中/掉线宽限都不催。回归：`tests/test_turn_timer.py`（15 条）+ socket e2e |
| 28 | **全站零音效**（唯一的 `new Audio()` 是 BGM，而 `static/music/` 目录不存在，6 条路径全 404） | 新增 `static/sfx.js` 用 Web Audio 合成 9 个音效（无需素材）+ 设置面板静音开关 + 6 处事件挂钩。回归：`tools/sfx_check.mjs`（17 项） |
| 26 | 自定义房间**没有任何入口生成邀请链接**（`?room=` 自动入房早就写好） | 新增「🔗 复制邀请链接」按钮 + `copyInviteLink()`（剪贴板不可用降级 prompt）。回归：`tools/room_invite_check.mjs`（7 项） |
| 27 | **排行榜被 0 局账号占满**；**背景音乐 6 条路径全 404 却静默停摆** | 排行榜过滤 `wins+losses > 0`；`music_player.js` 整轮音轨失败时明确提示「未找到背景音乐文件」 |
| 23 | **AI 手上有牌却一张都不出**（也不参与连锁）：`_ai_turn_loop` 只会「进战斗→炮击→结束阶段→交回合」 | 新增 `_AI_SAFE_CARDS` 白名单 + `_ai_choose_magic_card`（纯函数）+ `_ai_maybe_play_magic`；三档难度 `easy`/`normal`(默认)/`hard`（再用【失灵！】响应连锁），前端首页 `#ai-difficulty` 下拉框。回归：`tests/test_ai_magic.py`（25 条）+ `tools/ai_difficulty_check.mjs`（9 项无头断言） |
| 24 | AI 出牌会打开连锁窗口，而连锁未结算时 `handle_attack`/`end_turn` 会被门禁拒绝 → **AI 回合停在半途、真人只能干等** | `_ai_turn_loop` 出牌后先等窗口关闭再开炮；收尾的 `enter_end_phase`/`end_turn` 各带 20 次重试。实测：对手持有速阶 3 且不响应时，10 秒超时后 AI 照常打完并交还回合（13.1s） |
| 18 | 前端死函数 7 个（`createRoom`/`joinRoom`/`toggleCustomRoomOptions`/`createSelectionBoard`/`getSelectedCells`/`showReinforcementPrompt`/`showChainableCards`），共 304 行；其中 `createRoom`/`joinRoom` 还引用了从未声明的变量，`showChainableCards` 调用了全项目不存在的 `createCardElement` | 逐个 grep（含 templates）确认零调用后删除；页面零 JS 异常复测通过 |

### 🧪 顺带修好的测试问题

- 3 个用例先把对手打光（对局已结束）再调 `confirm_sacrifice`/`handle_enter_end_phase`，
  在新门禁下必然失败 —— 已给对手多留一艘船，**保留原意**（牺牲校验 / 公开广播 / 余音绕梁按阶段消耗）。
- 新增 `tests/test_defect_fixes_round1.py`（21 条）锁住以上每一条。

---

## 3. 复现 / 复测脚本（本轮新增，未入库，临时目录）

| 脚本 | 覆盖 |
| --- | --- |
| `e2e_match_reconnect.py` | 两个游客匹配到同一房间 / token 重连 / 伪造 token 被拒 / 快照字段 |
| `e2e_full_game.py` | 游客匹配 → 布船 → 猜拳 → 战斗 → 6 炮击沉 → 双方 `game_over` |
| `e2e_verify_postgame.py` | 终局后用 `test_get_game_state` 直接读服务端状态，确认 place_ships/end_turn/attack/surrender 全被拒且 `state` 仍是 `game_over` |
| `e2e_chain_attack.py` | 连锁窗口开着时攻击与结束回合都被拦 |
| `e2e_defects.py` | 非法出拳 / 终局后布船 / 终局后投降 |

复测结论（修复后）：
- 整局对战正常走完，胜者判定正确，终局后攻击被拒；
- 游客匹配 + 重连 + 伪造 token 拒绝全部 PASS，`room_sync` 已含 `opponent_attacks`；
- 终局后 6 类写操作全部返回「对局已结束」，`state` 稳定停在 `game_over`；
- 全卡 E2E 结果与修复前**完全一致**（34 PASS / 1 合法拒绝 / 0 崩溃 / 7 效果未生效），无回归；
- 无头 Edge 布局与战绩弹窗检查仍全绿，页面零 JS 异常。

---

## 4. 仍未处理（有意留到下一批）

2. 卡牌使用统计 / 复盘 / 观战。
3. `/user_stats` 公可枚举用户名（含任意用户完整局内日志）—— 是否收紧属于产品决策。
4. `gameState.effect_flags` / `activeEffects` 等仍只写不读。
5. `CHAIN_ENGINE_SPEC.md` 与实现有出入（见 `CLAUDE.md` §8）。

## 5. 未提交说明

本轮改动全部在**工作区**（未 commit）：
`server.py`、`static/game.js`、`db.py`、`CLAUDE.md`、`README.md`、
`tests/conftest.py`（新）、`tests/test_defect_fixes_round1.py`（新）、`docs/DEFECT_FIXES_2026_09_13.md`（新）。