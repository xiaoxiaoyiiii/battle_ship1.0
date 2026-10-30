# 赛季通行证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. All tests and fixtures stay outside the repository.

**Goal:** 在现有每日/每周任务、账号经验、成就和名片外观基础上，增加一个服务端可信、可幂等领取、支持免费轨与豪华轨的赛季通行证权益系统。

**Architecture:** 通行证经验与永久账号经验完全分离。`domain/battle_pass.py` 只负责赛季、等级、任务经验和奖励规则；仓储层保存赛季、玩家进度、奖励目录、领取记录和事件去重；`BattlePassService` 在现有结算事务中消费服务端事实。前端只展示服务端快照和领取结果，不能提交进度或自报资格。首版不接真实支付，豪华资格只作为服务端权益模型和受控开发授予。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy/SQLite、现有 UnitOfWork、Vue 3、Pinia、Vite、现有竞技场设计令牌和 Socket.IO 结算事件。

**Spec:** `docs/superpowers/specs/2026-10-29-season-pass-design.md`（本计划执行前由本计划中的产品规则整理成正式规格；旧提案 `D:/Codex workspace/.codex-remote-attachments/01a17d25-b5b9-7b63-ae71-3be8f0641c2e/d2b7558d-db85-409a-b30e-37bd22b28335/1-DAILY_TASKS_BATTLE_PASS_PROPOSAL.md` 只作为输入，不作为实现契约）。

## Global Constraints

- 永久账号经验和赛季通行证经验必须使用不同字段、不同规则函数和不同接口。
- 所有任务进度、经验、资格和奖励领取均由服务端裁决；客户端不得写入进度。
- 任务经验、奖励授予和领取记录必须在同一事务或具有可证明的幂等补偿路径。
- 现有每日/每周任务保持兼容；通行证不重写已有 `user_task_counters` 的日切和周切口径。
- 首版奖励只复用现有称号、头像框、名片底色；不引入金币、碎片、真实支付、动态卡背或新玩法。
- 仅登录且存在有效账户的玩家获得赛季进度；AI、测试事件、观战和回放不产生通行证经验。
- 现有 `review/main-ui-vue-port` 分支继续使用；不创建新分支，不修改 `main`，不接线上支付。
- 测试、夹具、截图、临时数据库和测试构建全部放在 `D:/CodexData/season-pass-verification-20261029/` 等仓外目录。
- 任何数据库迁移必须保留旧账号数据，空库和已有预览库都能启动；旧账号自动获得当前赛季的零进度记录或按惰性创建处理。

## 已确认产品规则

以下规则已由用户确认，后续实施不能自行改动：

- 首季长度：8 周；服务器时区：`Asia/Shanghai`。
- 等级上限：50 级；通行证毕业经验：20,000；等级由累计经验唯一推导。
- 每日任务仍为 3 个，完成任意 2 个获得当日主要通行证经验；每周任务仍为 3 个，完成任意 2 个获得当周主要经验。
- 每日完成 2 个任务：200 XP；每周完成 2 个任务：800 XP；首季加入较高要求或较多局数的赛季挑战，但不让挑战成为轻度玩家获得中段奖励的唯一入口。
- XP 自动入账；奖励由玩家手动领取；同一等级同一轨道最多领取一次。
- 豪华资格在首版只支持受控服务端/管理授予；中途获得资格后，可以领取当前赛季已达到等级的豪华轨奖励。
- 赛季结束后停止获得 XP，保留 14 天领奖宽限期；宽限期结束后未领取奖励自动补发到账号权益记录。
- 真人排位和真人休闲对局计入通行证经验；自定义房、AI 对局、测试事件、观战、回放不产生通行证经验。
- 奖励类型暂不锁定；允许首版只使用现有称号、头像框、名片底色。最终奖励目录在实现前单独确认。
- 免费轨必须有可感知的奖励；豪华轨只增加外观数量或质量，不提供命中、攻击次数、卡牌强度或胜率优势。

## 奖励灵感（候选，不是已批准目录）

奖励设计先围绕“舰队身份”和“航海履历”，避免建立新的货币系统。以下条目都可以映射到现有的称号、头像框、名片底色，不需要改变战斗规则。

### 称号方向

| 风格 | 称号灵感 | 适合放置 |
|---|---|---|
| 航海履历 | 远洋见习、潮汐观测员、夜航值更、海图校准师 | 免费轨前中段 |
| 卡牌玩法 | 连锁引航员、法术测绘师、牌阵指挥官、反制专家 | 免费轨中段或任务奖励 |
| 战斗成就 | 破浪先锋、沉舰记录员、风暴猎手、无伤返航 | 免费轨后段或挑战奖励 |
| 深海主题 | 深渊回声、黑潮领航、深海执旗官、海沟守望者 | 豪华轨中后段 |
| 赛季终点 | 深海远征舰长、潮汐统帅、永夜舵手 | 豪华轨最终奖励 |

称号不应把胜率或高段位作为唯一主要来源；至少一部分应通过参与、探索卡牌和完成任务获得，让非竞技高强度玩家也能获得身份感。

### 头像框方向

| 风格 | 视觉灵感 | 适合放置 |
|---|---|---|
| 基础航海 | 铜质罗盘、银色锚链、旧船舷灯 | 免费轨低中段 |
| 海况变化 | 雨幕、浪花、雷云、极光 | 免费轨后段或豪华轨前段 |
| 深海远征 | 深海热泉、蓝色鲸影、荧光水母、黑潮环 | 豪华轨中段 |
| 终点标识 | 金色舵轮、深渊王冠、潮汐星环 | 豪华轨高段和最终奖励 |

头像框是最适合做豪华轨差异的奖励：辨识度高、不会影响棋盘信息，也能复用现有 `profile_spec` 的解锁和装备入口。

### 名片底色方向

| 风格 | 配色建议 | 适合放置 |
|---|---|---|
| 航海图 | 深海蓝、旧纸灰、海军墨绿 | 免费轨 |
| 海况 | 暴雨青灰、暮光紫、极夜蓝 | 免费轨后段 |
| 深海远征 | 黑潮蓝绿、热泉青、深渊黑金 | 豪华轨 |
| 终点主题 | 星海渐变、鎏金潮纹、极光深海 | 豪华轨最终奖励 |

名片底色应保持文字对比度和可读性；动态渐变可以后置，首版先使用静态颜色和纹理令牌。

### 推荐的首季奖励节奏

这只是排布灵感，最终要等奖励数量和美术资产确认：

- 免费轨：以基础称号、基础头像框、基础名片底色交替出现，保证每 2～3 级有一次可见反馈。
- 豪华轨：不增加属性，只提供更完整的深海主题套装；建议每 5 级出现一次明显奖励。
- 25 级：一个中期主题称号或头像框。
- 50 级：一个完整的赛季终点称号；头像框/名片底色不作为本季终点必需品。
- 重复奖励：首版直接跳过已拥有的外观；是否转换为其他奖励暂不设计。

## Review Focus

- **重复结算：**同一个 `match_id`、重连或投降/掉线竞态不能重复增加通行证 XP；由外部回归用例固定。
- **重复领奖：**并发点击、刷新重试、不同浏览器重复领取不能重复授予同一个奖励；由唯一约束和接口测试固定。
- **跨周期：**北京时间日切、周切、赛季结束前后的结算必须归属明确；由固定时间戳测试固定。
- **豪华补领：**先免费升级、后授予豪华资格时只能补领已达到等级的豪华轨奖励；不能回溯不存在的 XP。
- **奖励失败恢复：**奖励资产写入失败时不能留下已领取但未拥有的状态；事务回滚或可安全重试。

---

## Task 0: 固化最终产品规格与首季奖励目录

**Files:**
- Create: `docs/superpowers/specs/2026-10-29-season-pass-design.md`
- Modify: `docs/UPDATES_2026_09_19.md` only if the project’s player-facing wording rules need a pass-specific entry
- Test: `D:/CodexData/season-pass-verification-20261029/product-rules.json`

**Interfaces:**
- Produces the exact season key, timestamps, level curve, task XP, reward IDs, eligibility rules and copy consumed by all later tasks.

- [ ] **Step 1: Write the product decision table**

  Record the chosen answers for: 8-week/50-level default, automatic XP, manual claim, 14-day grace, no payment, supported match types, and free/premium reward categories.

- [ ] **Step 2: Freeze the reward catalog**

  Use only existing `profile_spec` IDs for titles, frames and card backgrounds. Every reward gets `{reward_id, kind, payload, duplicate_policy}`. First-season duplicate policy is `skip_if_owned` with no currency conversion.

- [ ] **Step 3: Calculate the three player profiles**

  The external calculator must report expected XP and level for light (3 days/week), regular (5 days/week) and high-frequency (daily) players, including one missed week. It must show that regular players can reach the end without daily full attendance and light players reach meaningful mid-tier rewards.

- [ ] **Step 4: Review the spec before implementation**

  No code or migration starts until the user approves this product table. If the user changes a number, update this spec and the plan’s constants before continuing.

## Task 1: Add pure season, level, task-XP and reward rules

**Files:**
- Create: `backend/src/battleship/domain/battle_pass.py`
- Modify: `backend/src/battleship/domain/tasks.py` only to expose stable task IDs/definitions without changing current API output
- Test: `D:/CodexData/season-pass-verification-20261029/test_battle_pass_rules.py`

**Interfaces:**
- `SeasonConfig(id: str, starts_at: int, ends_at: int, claim_ends_at: int, level_cap: int, total_xp: int, rules_version: int)`
- `RewardDefinition(season_id: str, level: int, track: Literal['free','premium'], kind: str, reward_id: str, duplicate_policy: str)`
- `current_level(xp: int, config: SeasonConfig) -> int`
- `level_xp(level: int, config: SeasonConfig) -> int`
- `pass_segments(before_xp: int, after_xp: int, config: SeasonConfig) -> list[dict[str, int|bool]]`
- `task_reward_xp(period: Literal['daily','weekly'], completed_count: int) -> int`
- `season_state(now: int, config: SeasonConfig) -> Literal['upcoming','active','claim_only','closed']`

- [ ] **Step 1: Write failing rule tests**

  Pin level 1/50 boundaries, XP clamping, no XP after `ends_at`, claims allowed through `claim_ends_at`, invalid season times, daily/weekly 2-of-3 threshold, and segment totals.

- [ ] **Step 2: Run the external tests and confirm they fail**

  Run: `python D:/CodexData/season-pass-verification-20261029/test_battle_pass_rules.py`
  Expected: missing module/functions.

- [ ] **Step 3: Implement the pure rules**

  Use integer XP only. Store cumulative thresholds in the season catalog, derive level from XP, and never let the client reproduce the curve.

- [ ] **Step 4: Run the tests**

  Expected: all rule tests pass without database or framework imports.

- [ ] **Step 5: Commit the pure rule unit**

  Commit message: `新增赛季通行证规则模型`。

## Task 2: Add migrations and repositories with idempotent ownership

**Files:**
- Modify: `backend/src/battleship/repositories/models.py`
- Modify: `backend/src/battleship/repositories/migrations.py`
- Create: `backend/src/battleship/repositories/battle_pass.py`
- Modify: `backend/src/battleship/repositories/unit_of_work.py`
- Test: `D:/CodexData/season-pass-verification-20261029/test_battle_pass_repository.py`

**Schema:**

- `battle_pass_seasons`: `id` primary key, `starts_at`, `ends_at`, `claim_ends_at`, `level_cap`, `total_xp`, `rules_version`, `status`, timestamps.
- `battle_pass_levels`: `(season_id, level)` primary key, cumulative `xp_at`, optional free/premium reward kind and ID.
- `user_battle_pass`: `(user_id, season_id)` primary key, `xp`, `premium_unlocked`, `created_at`, `updated_at`, optimistic `version`.
- `battle_pass_claims`: `(user_id, season_id, level, track)` primary key, reward kind/ID, `claimed_at`, `grant_key`.
- `battle_pass_events`: unique `(user_id, season_id, source_kind, source_id)`, event type, XP delta, payload hash, created timestamp. This is the retry/idempotency ledger, not a client event table.
- `user_cosmetic_rewards`: `(user_id, kind, reward_id)` primary key, source season/level/track, granted timestamp. Existing profile reads union this table with normal unlock rules.

- [ ] **Step 1: Write migration tests**

  Test empty database migration, existing preview database migration, downgrade refusal policy, table indexes, and unique constraints for event/claim/reward rows.

- [ ] **Step 2: Implement migration `0003_battle_pass`**

  Preserve all existing rows. Seed no live season in the migration; a later controlled seed creates a season explicitly.

- [ ] **Step 3: Implement repository methods**

  Required methods: `get_current_season(now)`, `get_season(id)`, `get_or_create_progress(user_id, season_id)`, `add_event_once(...)`, `add_xp(...)`, `unlock_premium(...)`, `claim_once(...)`, `grant_cosmetic_once(...)`, `progress_snapshot(...)`.

- [ ] **Step 4: Verify transaction behavior**

  A failed reward grant must roll back both the claim row and the cosmetic row. A repeated event or claim must return the original result without adding XP or a second reward.

- [ ] **Step 5: Run migration/repository tests and commit**

  Commit message: `新增赛季通行证数据表与幂等仓储`。

## Task 3: Integrate settlement and existing task progress

**Files:**
- Create: `backend/src/battleship/services/battle_pass.py`
- Modify: `backend/src/battleship/services/settlement.py`
- Modify: `backend/src/battleship/services/tasks.py`
- Modify: `backend/src/battleship/domain/room/models.py` only if a frozen settlement fact needs a new field
- Modify: `backend/src/battleship/services/progression.py` only to keep permanent XP separate and emit a pass snapshot if required
- Test: `D:/CodexData/season-pass-verification-20261029/test_battle_pass_settlement.py`

**Interfaces:**
- `BattlePassService.apply_settlement(room: Room, uow: UnitOfWork, context: SettlementContext) -> list[dict]`
- `BattlePassService.snapshot(user_id: str, now: int) -> dict`
- `BattlePassService.claim(user_id: str, season_id: str, level: int, track: str, now: int) -> dict`
- `BattlePassService.grant_premium(user_id: str, season_id: str, source: str, now: int) -> dict`

- [ ] **Step 1: Write settlement tests before implementation**

  Cover a valid registered human match, AI/test/custom exclusion according to the approved rule, duplicate `match_id`, surrender/forfeit race, card play count, win count, and cross-season settlement.

- [ ] **Step 2: Build a frozen pass event from `SettlementContext`**

  Consume the same authoritative winner, mode, registered account, card-use and match facts used by existing task/XP settlement. Never infer facts from frontend payloads or replay display data.

- [ ] **Step 3: Apply pass XP in the existing UnitOfWork**

  Call `add_event_once` before XP mutation. Daily/weekly task progress remains in `user_task_counters`; pass XP is calculated from the resulting server-side task completion threshold and recorded under the season event ledger.

- [ ] **Step 4: Emit a private `battle_pass_xp_gained` result frame**

  The frame contains season ID, before/after XP, level, segments and newly available reward levels. It must be sent only to the account owner and must not replace existing `xp_gained`.

- [ ] **Step 5: Run settlement tests and commit**

  Expected: 25+ external cases pass, including repeated settlement and rollback cases.

  Commit message: `接入结算与赛季通行证经验`。

## Task 4: Add profile, season and claim HTTP contracts

**Files:**
- Create: `backend/src/battleship/http/routers/battle_pass.py`
- Modify: `backend/src/battleship/main.py` or router registration module
- Modify: `backend/src/battleship/contracts/events_out.py` and generated contract output if the new socket event is retained
- Modify: `backend/src/battleship/services/profile.py` to expose owned pass cosmetics through the same effective-equipment filter
- Test: `D:/CodexData/season-pass-verification-20261029/test_battle_pass_http.py`

**HTTP contracts:**

- `GET /api/battle-pass`: authenticated owner snapshot; returns current season, server time, state, XP, level, both tracks, claim states, task summary and premium status.
- `POST /api/battle-pass/claim`: body `{season_id, level, track}`; server checks owner, season claim window, level reached, track entitlement, catalog ID and existing claim; returns the idempotent claim result.
- `POST /api/admin/battle-pass/grant-premium`: admin-only development/operations endpoint, disabled outside the configured local/admin capability. It is not a payment endpoint.

- [ ] **Step 1: Write contract tests**

  Cover guest 401, malformed level/track, upcoming/closed season, level not reached, free claim, premium denied, premium after unlock, repeat claim, and ownership reflected in `/api/profile`.

- [ ] **Step 2: Implement read-only snapshot**

  Build the complete response from server rows and the pure rule module. Never accept a client-supplied XP or level.

- [ ] **Step 3: Implement idempotent claim**

  Use one transaction for eligibility check, claim insert and cosmetic grant. A duplicate request returns the original reward state, not a second grant.

- [ ] **Step 4: Implement controlled premium grant**

  Record operator/source and timestamp. Do not add payment-provider fields or pretend this completes payment.

- [ ] **Step 5: Run HTTP and contract checks and commit**

  Commit message: `新增赛季通行证接口与领奖权益`。

## Task 5: Build the season-pass frontend

**Files:**
- Create: `frontend/src/screens/season/SeasonPassScreen.vue`
- Create: `frontend/src/stores/seasonPass.ts`
- Create: `frontend/src/components/SeasonPassTrack.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/screens/start/StartScreen.vue` and `HomeTasks.vue` for entry/summary only
- Modify: `frontend/src/realtime/settlement.ts` and result screen for XP/available-reward notice
- Test: `D:/CodexData/season-pass-verification-20261029/season-pass-browser.mjs`

**UI behavior:**

- Desktop: season header, countdown, XP/level summary, horizontally scrollable dual-track reward strip, task summary and claim panel.
- Mobile: one level card at a time with previous/next controls; no page-wide horizontal overflow; free and premium tracks remain visually distinct but readable.
- Locked, claimable, claimed and premium-locked states must be distinct.
- Claim buttons use the server response as authority; optimistic XP or reward ownership is forbidden.
- Guest view explains login requirement without showing fake progress.

- [ ] **Step 1: Write browser assertions**

  Assert current season loads, one level can be claimed, repeat claim is harmless, premium lock is shown, mobile width has no horizontal page overflow, and result XP links to the season screen.

- [ ] **Step 2: Implement Pinia store**

  Methods: `load()`, `claim(level, track)`, `reset()`, `availableRewards`, `state`; abort stale requests and preserve the latest server snapshot.

- [ ] **Step 3: Implement desktop and mobile components**

  Reuse existing tokens, card art conventions, AppOverlay and accessibility patterns. Do not add a second theme system.

- [ ] **Step 4: Add navigation and settlement entry points**

  Add one clear home/profile entry and a compact “通行证 +N XP” result notice without replacing the existing permanent XP display.

- [ ] **Step 5: Run typecheck, production build and browser checks**

  Commit message: `新增赛季通行证页面与领取流程`。

## Task 6: Add season seed, operations, migration and failure recovery

**Files:**
- Create: `backend/src/battleship/domain/battle_pass_catalog.py` or a versioned seed file
- Create: `ops/seed_battle_pass.py` with dry-run and idempotent apply modes
- Modify: `ops/README.md`
- Modify: `docs/UPDATES_2026_09_19.md` if release copy is approved
- Test: `D:/CodexData/season-pass-verification-20261029/test_battle_pass_ops.py`

- [ ] **Step 1: Define a versioned first-season catalog**

  Include season timestamps, all 50 level thresholds, 50 free rewards, 50 premium rewards, and rules version. Reuse only verified profile IDs; fail closed on missing assets.

- [ ] **Step 2: Implement dry-run seed**

  Dry-run reports inserts/updates without changing the database. Apply mode is idempotent and refuses to overwrite an active season with a different rules version.

- [ ] **Step 3: Add restart and recovery checks**

  Seed interruption, server restart, missing reward asset, expired season and retrying a failed claim must all be recoverable without duplicate grants.

- [ ] **Step 4: Run against a copied preview database only**

  Verify row counts, old profile responses, task responses and current 5472 health. Never seed the user’s live preview database until separately approved.

## Task 7: Full verification and release gate

**Files:**
- Create: `D:/CodexData/season-pass-verification-20261029/full-season-pass-e2e.mjs`
- Create: `D:/CodexData/season-pass-verification-20261029/season-pass-release-report.md`
- Modify: no repository production files unless a verification defect is found

- [ ] **Step 1: Run backend pure/repository/HTTP tests**

  Required evidence: rule boundaries, migration on empty/existing DB, task/settlement idempotency, claim idempotency, premium backfill, cross-period and expired-season behavior.

- [ ] **Step 2: Run two-browser tests**

  Required evidence: two accounts cannot claim each other’s progress, owner-only XP frames, simultaneous claim requests produce one reward, and mobile layout remains within viewport.

- [ ] **Step 3: Run existing project gates**

  `pnpm exec vue-tsc --noEmit`, `pnpm run check:contract`, production build, existing backend regression suite, and `git diff --check`.

- [ ] **Step 4: Review the release report**

  Confirm no payment claims, no test assets in the repository, no changes to permanent XP semantics, and no migration data loss.

- [ ] **Step 5: Only after user approval, commit/push/deploy**

用户已确认进入实现；本轮只推送代码，不修改 5472 的现有预览数据库。

## Scope Exclusions for the First Release

- No real payment provider, order, refund, webhook, chargeback or entitlement purchase flow.
- No wallet, coins, fragments or conversion economy.
- No new campaign, BO3, survival, cooperative PvE or other battle mode.
- No dynamic card backs, projectile effects or new animation asset pipeline as pass rewards.
- No spectator/replay XP.
- No client-side developer switch that grants premium or XP.

## 本轮实现状态

- 已完成纯规则、迁移、幂等仓储、真人结算接入、挑战进度、HTTP 接口和首页通行证卡片。
- 奖励目录已冻结为现有称号、头像框和名片底色；50 级豪华轨为单个 `season_deep_1` 终点称号。
- 赛季结束后的自动补发采用懒触发：玩家在关闭赛季后读取通行证时，在同一事务中补发所有已达等级且未领取的奖励；唯一键保证重复读取安全。
- 运维通过管理员接口先创建首季目录，再开放赛季；没有在迁移中隐式写入活动赛季，也没有接入支付。
- 暂未实现结算 Socket 的独立 `battle_pass_xp_gained` 帧，现有结算永久经验事件保持不变；首页读取快照即可看到通行证经验。

## 已确认与仍待决定

已确认：

1. 8 周、50 级、20,000 XP。
2. 首版豪华资格只做管理员/内部授予，不接真实支付。
3. XP 自动入账、奖励手动领取、赛季结束后 14 天宽限并自动补发。
4. 真人排位和真人休闲对局计入；自定义房、AI、测试、观战、回放不计入。

已确认：

1. 排位和休闲真人对局全部计入。
2. 自定义房排除。
3. 首季加入高要求或多局数的赛季挑战。
4. 50 级终点奖励采用单个终极称号；未来可扩展可佩戴的赛季/段位徽章系统。

仍待决定：

1. 首季最终奖励目录和每一级的具体排布。
2. 赛季挑战的具体数量、目标和 XP 分配。
3. 首季终点称号的最终文案与美术主题。

## Self-Review Checklist

- [x] 旧提案中的每日/每周任务、账号等级、成就、图鉴、卡牌统计等已实现能力没有重复列为新功能。
- [x] 赛季经验与永久经验分离，所有新增写入位于现有结算事务边界内。
- [x] 领取、重复结算、跨周期、豪华补领、旧账号迁移和失败恢复均有专门任务与测试位置。
- [x] 首版排除了支付、金币、碎片和不存在的新玩法。
- [x] 测试资产全部仓外，计划末尾明确用户批准后才进入实现。
