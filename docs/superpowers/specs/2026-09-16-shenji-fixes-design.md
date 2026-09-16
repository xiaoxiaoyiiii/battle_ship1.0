# 神机妙算三处缺陷修复 · 设计稿（2026-09-16）

> 作者实测报的三个问题：
> ① 预言过程中没有等待窗口、也不冻结对方；
> ② 结算判定失败 —— 宣言「减少 1 艘」、实际被打沉 2 艘，回合结束却报**预言成功**；
> ③ 预言成功后的重新部署**只能放原位置/被打过的格子**，放不到对方没打过的空格。
>
> 结论：**①② 是同一条链条**，③ 是另一处独立的前后端契约错位。

---

## 1. 复现（先建循环，再动代码）

`.tmp/shenji_repro2.py`（临时脚本，不进仓库）：

```
1. P1 打出神机妙算        → pending_shenji={'caster':'p1'}，快照=None
2. 宣言还没确认，P2 开炮   → status=success   ← 没被冻结（问题 ①）
3. P1 这时才宣言「减少1」  → 快照={'ships':5,'sunken':1}  ← 第2步那艘被并入基线
4. 宣言后 P2 再打一炮      → P1 累计被打沉 2 艘
5. 结束大回合判定          → diff = 2-1 = 1 == pred 1 → 报「预言成功」（问题 ②）
```

对照：宣言**之后**才开打（`.tmp/shenji_repro.py`）→ diff=2 ≠ pred=1 → 正确判失败。
所以复现的关键是「宣言窗口那段时序」，两件事叠加才成病。

## 2. 病根

| # | 病根 | 证据 |
| --- | --- | --- |
| ① | `pending_shenji` 只是个标志，**没有任何门禁引用它**。全项目只有宣言处理器自己与回合计时看门狗提到它（`server.py:4415` 反而因此**跳过催促**） | 复现第 2 步 `status=success` |
| ② | 基线（快照）在**宣言确认那一刻**才拍，而卡牌在**打出那一刻**就已生效 → 两者之间打掉的船被并进基线 → `diff` 少算 → `diff == pred` 误判成功 | 复现第 3、5 步 |
| ③ | `allowed` 一个字段两种语义：绝处逢生当**白名单**（只准这些格），神机妙算当**豁免名单**（这些格即使被打过也放行）。前端 `game.js` 对两者一律按白名单处理（`if (blocked.has(key) \|\| (allowed && !allowed.has(key)))` → 禁点且不绑 click）→ 除原位置外全部点不动 | 代码实证；后端 `_placement_error` 本就允许未打过的空格，是前端把它挡了 |

## 3. 修法

**① 宣言窗口 = 冻结对方 + 等待横幅 + 超时**（仿既有优先权机制）

- 新增 `_shenji_wait_reason(room, player_id)`：`pending_shenji` 存在期间**只冻结非施法者**
  （施法者要能宣言，冻了他就死锁）。
- 新增 `_action_wait_reason()` = 神机妙算窗口 > 阶段转换优先权，替换原先 5 处
  `_priority_wait_reason(...)` 调用点（attack / enter_end / enter_battle / end_turn / use_magic_card）。
- 新增事件 `shenji_waiting`（发给**对方**）与 `shenji_waiting_end`；
  `_build_room_sync` 补 `shenji_waiting`，重连要能恢复横幅与冻结（只给非施法者那份）。
- 前端：固定定位横幅「等待对方神机妙算宣言中」+ 阶段按钮禁用，
  与既有 `priority_waiting` 横幅同一套做法、位置错开 64px 以免同时出现时互相盖住。
- **超时 30 秒**（`SHENJI_DECLARE_SECONDS`）：冻结对方之后不能让一个人挂机把两边一起卡死。
  超时语义**复用玩家自己点「取消」的语义**（卡不退回、效果作废），并一并清掉基线；
  用代际令牌（`token`）保证"已宣言/已取消"后旧定时器作废。

**② 基线改在【出牌那一刻】拍**

- 新增 `_snapshot_shenji_baseline()`，在 `_open_shenji_declare_window()` 里调用（即打出卡时）。
- `_apply_shenji_prediction()` 改为**只写数值 x**；仅在基线缺失的老路径
  （`magic_temp_data['prediction']` 直接落效 / 旧对局）才补拍一次，
  **绝不在已有基线时重拍** —— 重拍正是 ② 的成因。

**③ 神机妙算不再下发 `allowed`**

- `_emit_placement_request()`：神机妙算分支去掉 `payload['allowed']`，
  原位置改为"从 `blocked` 里剔除"（本来就已经这么做了）。
  `allowed` 只保留绝处逢生的白名单语义。

## 4. 明确不动

卡面数据（`magic_card.json` / `magic_cards.js`）、`apply_magic_effect` 的其它分支、
AI 白名单（神机妙算本就在"需玩家点选、不得进白名单"名单里）、绝处逢生的白名单行为。

## 5. 验证

- 新增 `tests/test_shenji_declare_fixes.py`（14 条）：修前 **8 红**，修后全绿。
  覆盖：对方三种写操作被拒且理由是宣言窗口 / 施法者仍能宣言 / 宣言后对方解冻 /
  基线在出牌时拍且宣言不重拍 / 2 沉 1 判失败 / 正好 1 沉判成功 /
  未打过空格可放且不下发白名单 / 超时清窗清基线并解冻 / 旧令牌作废。
- 更新 `tests/test_shenji_redeploy_flow.py`：原「原位置必须在 allowed 里」编码的是**旧契约**，
  改为断言不再下发白名单。
- `tools/shenji_redeploy_check.mjs`（无头 Edge）：假 payload 去掉 `allowed`，
  新增「对方没打过的空格 (2,3) 能点**且能选中**」的真实回归断言；
  顺带把它的无头 profile 从 `C:/Windows/Temp` 挪到项目内 `.tmp/`（文档里记过的 ACL 坑）。
- 全量 `pytest tests/ -q`：**808 passed**。

## 6. 已知边界

- 冻结只挡"写操作"（开炮/出牌/交回合/阶段转换），不看聊天与查看类操作。
- 人机房里被冻的是 AI：`_ai_turn_loop` 的攻击重试会一直失败到窗口关闭（最长 30 秒）后成功，
  不会卡死，但那一回合 AI 会显得慢一拍。
