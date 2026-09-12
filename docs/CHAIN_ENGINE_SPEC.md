# 连锁与无效化引擎 · 设计稿（CHAIN_ENGINE_SPEC）

> 状态：**⚠️ 设计稿 + 部分过期**。文中的"现状病灶/僵尸代码"描述的是**实施前**的情况，
> 那些问题后来都修掉了（但引擎也没有按第 3 节那样拆成 `engine/`）。**先读下面这段校准**。
> 当前实现的权威说明见 `CLAUDE.md` §8。

---

## 0. 实测校准（2026-09-13，全文件 grep 核对）

| 文档说法 | 实测结果 |
| --- | --- |
| §2「失灵康不到目标」「无效化 ≠ 阻止结算」 | **已修**：`resolve_chain` 逐项出栈时按 `ChainItem.negated` 跳过效果，无效化在结算前生效（结算文案「无效化了X（若其效果已结算则不会回滚）」） |
| §2「误伤旧牌」（`magic_history[-1]` 抓到很早以前的牌） | **已修**：失灵限定"本大回合刚使用"的卡，并校验 `round` |
| §2/§4 `room.pending_magic` + `counter_magic_response` | **已删干净**：`server.py` 全文件 **0 命中**；前端对应 emit/监听也一并清理 |
| §2/§4 `room.last_magic`（只写不读） | **属性已不存在**（`room.last_magic`/`self.last_magic` **0 命中**）；只剩结算函数里的**局部变量** `last_magic = room.magic_history[-1]` |
| §3 计划新增 `engine/chain.py` / `resolution.py` / `negation.py` | **未按此拆分**：实现仍在 `server.py` 内（`_can_respond_chain` / `_advance_chain_window` / `resolve_chain` / `_schedule_chain_timeout`），仓库里没有 `engine/` 目录 |
| §3 计划新增 `chain_window` / `chain_passes` | **已实现**；超时的代际令牌存在 **`room.chain_timer`**（**没有** `chain_token` 字段，token 只是 `_schedule_chain_timeout(room_id, token)` 的参数） |

**与实现的 2 处有意偏差**（不是 bug，别照着文档改回去）：

1. 被无效化的**场地魔法**仍执行"贴了再拆"（避免卡片凭空消失），与 §1.3 的字面描述不同。
2. 「平等条约」**不走** `negate_target` 连锁标记，而是读 `game_effects['last_ship_change']`
   的快照回滚船数变化。

回归测试：`tests/test_guardrails.py`（连锁纯函数 + 超时代际令牌）与
`tests/test_all_magic_cards.py`（42 张卡逐条结算）。

---

## 1. 规则（已与小弈确认）

### 1.1 连锁（响应窗口模型）
- 任意卡牌打出后**不立即结算**，先压入连锁栈。
- 结算前有"响应窗口"，双方可追加**速阶3**卡牌：
  - 一张牌打出后，窗口先给**对方**。
  - 轮到的玩家可打出一张速阶3（压栈），或"放弃"。
  - 对方放弃 → 窗口回到**最后压栈者**，其可继续追加自己的速阶3（**自连锁**）。
  - **连续两次放弃** → 连锁开始结算。
  - 仅当轮到者手牌中确有速阶3才询问；没有则自动视为放弃。
- 结算顺序：**栈顶先出（LIFO，后发先至）**。
- 超时：响应窗口 10 秒，超时视为放弃（保留现有兜底，改用新状态机）。

### 1.2 无效化
- 每个连锁项带 `negated` 标记。
- 结算弹出某项时：
  - `negated == True` → **跳过其效果**（记录"被无效化"），不进历史、不改场地。
  - 否则应用效果；若该效果属"无效化类"，把**其正下方那一项**（下一个待结算项）标记为 `negated`。
- **失灵！**：目标 = 正下方一项（它专康的"上一张"）。
  - 目标为**看破！** → 无效化失败（看破优先级更高）。
  - 目标为**加百列之光** → 失败（加百列免疫失灵）。
- **加百列之光**：目标 = 正下方一项（对方的）+ 当前生效的场地魔法。
- **看破！**：给对手挂 `magic_blocked`，本大回合对方所有魔法卡无效化。看破免疫失灵；看破生效期间对方的失灵无效。
- **平等条约**：使"造成船数改变的那张卡/攻击"无效化（目标同为栈中正下方项）。

### 1.3 场地魔法
- 无效化场地时"**贴了再拆**"：先入场，被康时移入弃牌堆。

---

## 2. 现状病灶（实测）

> ⚠️ **本节描述的是实施前的情况，已全部修复**（见开头 §0 校准表）。保留仅为历史记录。

- **失灵康不到目标**：`magic_history` 只在"结算成功后"写入，而栈是反序结算——失灵先出栈，此时它要康的那张牌还没进历史 → 返回"没有可无效化的魔法卡"。
- **误伤旧牌**：`magic_history` 全场累积，`[-1]` 可能是很早以前的一张牌，失灵会把它 pop 掉。
- **无效化 ≠ 阻止结算**：现在只是 `history.pop()`，目标效果早已执行。
- **双轨记录**：`room.last_magic`（只写不读）与 `magic_history` 两套并存。
- **死代码**：`room.pending_magic` 恒为 None，`counter_magic_response` 恒返回错误；前端仍在 emit。
- **免疫关系散落**：失灵/看破/加百列的互相免疫写在三个不同分支里。

---

## 3. 引擎架构

新增 `engine/`（纯逻辑，**不依赖 socketio**）：

| 模块 | 职责 |
|---|---|
| `chain.py` | `ChainState(stack, window, passes)`；`start()` / `respond()` / `can_respond()` |
| `resolution.py` | `resolve(room)` 逐项出栈；`apply_effect(room, caster, card, targets) -> EffectResult`（现有 `apply_magic_effect` 迁入） |
| `negation.py` | 无效化规则表（失灵/加百列/看破/平等条约 的免疫与目标解析） |

- `server.py` 只保留：socket 收发、鉴权、广播、超时调度、房间生命周期。
- 状态：`room.chain` 改由 `ChainState` 承载；新增 `chain_window`、`chain_passes`。
- 效果结果统一 `EffectResult`，便于测试与广播。

---

## 4. 僵尸代码清单（待删）

> ⚠️ **已全部删除**（`server.py` 全文件 grep 0 命中）。保留仅为历史记录。

- `room.pending_magic` + handler `counter_magic_response`（恒 None，恒报错）。
- 前端 `game.js` 的 `counter_magic_response` emit 与 `magic_negated` 监听。
- `room.last_magic`（只写不读）→ 并入 `magic_history`。
- 复查其它"只写不读"字段与不可达分支。

---

## 5. 分阶段实施

| 阶段 | 内容 | 验收 |
|---|---|---|
| P1 | 删僵尸代码 | 现有 121 测试全绿 |
| P2 | 连锁状态机（窗口/放弃/自连锁/超时） | 新增连锁单测全绿 |
| P3 | 结算引擎 + 无效化 | 新增失灵/加百列/看破/平等条约单测全绿 |
| P4 | 双端 socketio E2E | 真实两客户端跑通连锁+失灵 |

- 全程分支 `feat/chain-engine`，**不 push**。

---

## 6. 待确认

- 自连锁在"对方完全没有速阶3"时是否也允许？按两连弃模型：**允许**（对方自动放弃 → 窗口回到自己）。若你要禁止，我再改。
