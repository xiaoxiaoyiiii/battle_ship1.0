# 新增一张魔法卡（一页版）

> **单一来源**：`backend/src/battleship/domain/magic/data/magic_card.json` 是唯一权威；
> `frontend/scripts/sync-card-data.mjs` 在 build 前生成 `frontend/src/cards/card_data.json`。
> 不要手改生成物。仓外守卫：`D:/develop/battleship-verify/cases/34-magic-hooks/test_card_data.py`
> （逐条相等 + 行序 + 生成幂等 + 48 个卡名都有实现）。

加一张卡 = **牌表一条 + 一个 `@register` 效果 + 注册 +（按需）条件/目标/交互 + 生成前端数据 + 仓外测试**。
下面每一步都对应一个会静默失败的点，照着做即可。

## 0. 先确认卡池是否冻结

50 条 / 48 个唯一卡名 / 「失灵！」×3 是玩家可见的冻结契约，写死在多处：

| 位置 | 常量 |
| --- | --- |
| `domain/magic/cards.py` | `CARD_COUNT`、`UNIQUE_CARD_COUNT`、`DUPLICATE_ALLOWED` |
| `frontend/scripts/sync-card-data.mjs` | `CARD_COUNT`、`UNIQUE_CARD_COUNT`、`DUPLICATE_ALLOWED` |
| `ops/build.py` | `EXPECTED_CARD_FACES = 48`（构建后校验 manifest 里的卡面数） |
| `frontend/src/cards/cardArt.ts` | `CARD_ART_SLUGS` 名称→slug 表（另有 48 张 webp） |
| 仓外 `cases/10-magic` / `30-cleanup` / `34-magic-hooks` | 50/48/3、48 卡面、48 个实现 |

**替换一张卡**（保持 50/48）只动牌表与效果；**扩池到第 49 张**必须同时改上表全部计数，
否则红的是 build 与仓外门禁，不是功能本身。

## 1. 加牌表数据

在 `magic_card.json` 里追加一行（四个键，顺序固定）：

```json
{ "name": "测试风暴", "speed": 3, "type": "普通", "description": "对 3×3 区域造成一次攻击。" }
```

- `speed` 只能是 1/2/3；`type` 只能是 `普通`/`场地`/`判定`；卡名全局唯一（除「失灵！」）。
- 生成前端副本：`node frontend/scripts/sync-card-data.mjs`（`pnpm build` 也会跑）。
  输出 `[cards] synced 50 cards -> ...` 或 `up to date`；两个 JSON 必须进同一个提交。
- 绝不要用编辑器直接改 `frontend/src/cards/card_data.json`：守卫会逐条比对，改了必红。

## 2. 写效果并注册

在 `domain/magic/effects/batch_a.py`（立即结算）、`batch_b.py`（交互/场地/判定）、
`chain_cards.py`（连锁牌）或新模块里写：

```python
from ..registry import register
from .base import EffectContext, EffectResult


@register("测试风暴")
async def test_storm(ctx: EffectContext) -> EffectResult:
    area = ctx.area()
    if area is None:
        return EffectResult(False, "请选择目标区域")
    # ... 用 ctx.emit / ctx.log / ctx.rng 完成结算 ...
    return EffectResult(True, "测试风暴命中目标区域")
```

- 纯规则：效果模块**不许** import `server`、`socketio`、数据库；要发事件就用 `ctx.emit(事件名, 载荷, room=/to=)`。
- 可用能力全在 `effects/base.py` 的 `EffectContext`：`draw`、`log`、`finish`、`place_field`、
  `tear_down_field`、`request_ship_pick`、`start_placement`、`start_dice_discard`、`open_shenji`、
  `recalc_attacks`、`sacrifice_ship`、`reveal_to`、`rng` 等。
- 失败返回 `EffectResult(False, "具体原因")`，服务层据此退牌；不要 `return None`，也不要
  `try/except` 吞异常（`resolve_chain` 有兜底日志，但兜底不是设计）。
- **注册的最后一个动作容易被忘**：`domain/magic/registry.py` 底部是按模块 import 触发注册的
  （`from .effects import batch_a ...`）。新建效果模块必须在这里补一行 import，否则
  `implemented_cards()` 缺这张卡，34 守卫和出牌校验都会红。

## 3. 条件、目标、后续交互、AI

| 要加的东西 | 改哪里（当前实现） |
| --- | --- |
| 全局出牌规则（阶段/速阶/行动者/禁忌果实/教皇…） | `domain/magic/rules.py`：`can_play_magic_card` + `playability_reason` |
| 卡专属发动条件（如"上一发命中"） | `rules.py` 的 `last_attack_requirement_reason` 等；两条激活路径（`use_magic_card` / `chain_response`）的校验顺序以 `services/magic.py` 现状为准 |
| 区域/行列/格子目标校验 | `services/magic.py` 的 `sanitize_targets`（坐标 0..5） |
| 区域卡打哪块棋盘 | `domain/spectate/rules.py` 的 `AREA_TARGET_BOARDS`：`self` / `opponent` / `choice` |
| 前端点选形状 | `frontend/src/screens/game/view.ts` 的 `MAGIC_TARGET_DESCRIPTORS`（只影响 UI，服务端权威） |
| 需要玩家再选一次（待选队列） | 效果里写 `room.magic_temp_data = {"type": ..., "caster": ...}` 并返回 `temp_data_id`；在 `services/magic.py` 的 `KNOWN_CHOICE_IDS` 与 `confirm_magic_target` 分派加分支 |
| 大师 AI 会不会打 | `domain/ai/master.py` 的 `MASTER_ENABLED_CARDS` |
| 普通/困难 AI 会不会打 | `domain/ai/policies.py` 的 `AI_SAFE_CARDS` |

- **AI 白名单不登记 = AI 永远不打这张卡**（默认安全，不是 bug）。要登记，必须让 AI 能就地
  产生目标、且不留任何待办；否则回合会被待办卡死。登记后跑 `cases/13-ai`。
- 新交互**不要**直接改 `magic_temp_data` 的读取点而不登记 `KNOWN_CHOICE_IDS`：客户端会收到
  「无效的临时数据ID」，而服务端看不出错。
- 目标归属漏登记（区域卡）时 `sanitize_targets` 不会校验棋盘，前端预览可能画在错误的一侧。

## 4. 生成 + 测试 + 构建

```powershell
node frontend/scripts/sync-card-data.mjs          # 生成前端副本（幂等）
$env:T10_WORKTREE = '<worktree>'
$env:T11_WORKTREE = '<worktree>'
$env:T12_WORKTREE = '<worktree>'
$env:T34_WORKTREE = '<worktree>'
D:/develop/battleship-verify/.venv/Scripts/python.exe -m pytest D:/develop/battleship-verify/cases/10-magic -q -p no:cacheprovider
# 11-magic-b / 12-chain / 34-magic-hooks 各自单独跑（conftest 同名不能混跑）
python ops/build.py --frontend-only               # 构建前会自动再跑一次 sync，并校验 48 张卡面
```

- 卡行为测试写到仓外（D4），放在对应的 `cases/10-magic`、`11-magic-b`、`12-chain`；
  每张新卡至少覆盖：**打出成功**、**条件不满足时拒绝且不扣牌**、**结算失败退牌**、
  **emit 事件名/收件人/载荷**、**目标越界**、涉及连锁时加一条连锁/无效化用例。
- 数据守卫 `cases/34-magic-hooks/test_card_data.py` 自动覆盖"新卡在牌表但没实现"；
  扩池时它里面的 `CARD_COUNT/UNIQUE_CARD_COUNT` 也要一起改。
- 改完先 `git status`：生成脚本幂等时前端文件**不会**出现在 diff 里；出现就是有人手改了。

## 5. 最小演练（虚构「测试风暴」，演练完请删除）

1. 牌表加一行（见 §1），跑 sync。
2. `batch_a.py` 加 `@register("测试风暴")` 效果（见 §2），无需改 `registry.py`（模块已在底部 import）。
3. 区域卡：`AREA_TARGET_BOARDS["测试风暴"] = "opponent"`，前端 `MAGIC_TARGET_DESCRIPTORS` 加
   `{ kind: 'area', size: 3, board: 'opponent' }`。
4. 仓外补一条走真实 `use_magic_card` 的用例（成功 + 区域越界各一条），跑 10/34 与 build。
5. 删掉 1–4 的全部改动（含前端生成的 `card_data.json`），再跑一次 34 确认回到 48。

## 6. 常见坑

- **失灵！×3**：牌表故意 3 条，`draw_card` 去重对它特例放行；改成 2 条会让 `cards.py` 启动即抛。
- **隐藏卡**：`HIDDEN_CARD_NAMES`（钢筋铁骨）不进共享牌堆、只进图鉴；新卡想"藏着"就加进去，
  但它的效果仍必须实现（48 守卫按卡名而不是按牌堆）。
- **判定卡不是"结算完就结束"**：命运骰子 / 无忧梦呓 / 兵粮寸断 会把状态挂到 `pending_*` /
  `game_effects`，由阶段开始/结束的管线消费；必须写跨回合用例，只断言 `use_magic_card` 返回会假绿。
- **场地卡**：进场走 `ctx.place_field`；被无效化时只进弃牌堆、不顶掉现有场地（连锁用例覆盖）。
- **AI 白名单**：不登记不会报错，只是 AI 一张都不打；登记了但 AI 生成不了目标，会卡住回合。
- **卡面**：`frontend/public/card_faces/<slug>.webp` + `cardArt.ts` 名称表；缺图只是退化无美术，
  但扩池时 `ops/build.py` 会按 48 张卡面校验而失败。
- **出站事件冻结**：89 个出站事件名不许为一张新卡新增；复用现有事件（`attack_result`、
  `magic_chain_updated`、`active_effects` 等）并在测试里钉住。
- **文案即契约**：`message` 是玩家看到的字，仓外测试按原文断言，改字视为契约变更。
