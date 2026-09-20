# 选船类效果的优先级仲裁（2026-09-20）

> 作者实测：「当需要选船的多个效果同时发生的时候，在选船的时候就会卡住选不了。
> 尤其是当恶魔契约生效的时候，如果自己在战斗阶段使用了克苏鲁之眼要自己选船的时候，
> 一点击船在的格子就会弹出『当前没有待牺牲的船』，无法正常让克苏鲁之眼被用出去。」

---

## 1. 根因：三层缺陷叠加

### 1.1 服务端 · 单槽覆盖（**主因**）

`room.magic_temp_data['pending_sacrifice']` 曾经是**一个 dict**，
`_request_ship_pick()` **无条件覆写**它。三个效果共用这一个槽：

| 效果 | `reason` |
| --- | --- |
| 恶魔契约 | `demon_contract` |
| 神之宣告·效果一 | `divine_decree` |
| 克苏鲁之眼 | `kraken_eye` |

**复现链（逐行核实）：**

1. 恶魔契约是**持续场地效果**（`game_effects['demon_contract']=True`），
   在 **6 处**船损路径上触发 → 只要有人掉船就会产生待牺牲；
2. 某船沉没 → `_request_demon_contract_sacrifice` → 向另一方 X 发请求
   → 槽 = `{player: X, reason: 'demon_contract'}`；
3. X 打出克苏鲁之眼 → 向 Y 发请求 → **覆盖**成 `{player: Y, reason: 'kraken_eye'}`；
4. X 点自己船的格子 → 读到 `player != X` → **「当前没有待牺牲的战舰」**。

### 1.2 前端 · 单标志 + 两个捕获监听

- `gameState.selectingOnBoard` 是**一个全局布尔**：恶魔契约的
  `showSacrificePrompt` 与卡牌的单格点选器都会置真；
- 两者都往 `gamePlayerBoard` 挂**捕获阶段** click 监听，捕获按注册顺序触发
  → 先注册的（恶魔契约）赢，点击被当成"牺牲选择"发出去；
- `createBoardAreaPicker` 开头 `if (gameState.selectingOnBoard) return null;`
  —— **静默放弃**，调用方 `picker ? picker.cleanup : null` 什么也不做，
  于是弹窗显示着、棋盘却点不动 = 玩家说的「点了没反应」。

### 1.3 存储位置不安全（顺带修的同类漏洞）

`magic_temp_data` 有 **8 处**被整体覆写 `= {}`
（`1741/1871/3344/7863/7916/7988/8029/8962`）。其中**仁王之盾自己**就写
`room.magic_temp_data = {type:'shield_choice', ...}`。

待选状态放在里面 → 等待玩家点船期间只要他打出另一张会结算的牌，
**待选就被静默抹掉**，该玩家永远等不到那个选择（不报错、只是效果消失）。

---

## 2. 修法

### 2.1 队列取代单槽，且**按玩家分组**

新增房间级字段：

```python
self.pending_ship_picks: list[dict] = []   # {player, reason, message, priority, seq, silent?}
self.ship_pick_seq = 0                     # 单调递增：同优先级先到先得，顺序确定可测
```

- **按玩家独立**：A 的待选与 B 的待选互不影响（单队列做不到这一层）；
- **同一玩家内**：按 `priority` 降序，同优先级按 `seq` 升序。

⚠️ 依 CLAUDE.md 第 11 条「新增房间级状态三件齐」：
`__init__` 初始化 + 明确消费点（`_consume_ship_pick`）+ 回归用例
（`tests/test_ship_pick_priority.py`）。

### 2.2 优先级表（**唯一一份**）

`server.py` 的 `SHIP_PICK_PRIORITY`：

| 优先级 | 效果 | 理由 |
| --- | --- | --- |
| **100** | 恶魔契约 | 持续场地效果，船数**已经变了**，不立刻结算会与后续船数变化打架 |
| **80** | 神之宣告·效果一 | 卡牌自身结算的组成部分，不出结果这张牌等于没打完 |
| **60** | 克苏鲁之眼 | 纯信息披露，延后无任何副作用 |
| **40** | 仁王之盾 | 自己的战术选择，最可延后 |

与 `_MULTITURN_EFFECTS` / `FLAGS_KEEP_ACROSS_TURN` 同一路数：
**规则只写一遍**，新增选船类效果必须在这里登记（否则 `.get(reason, 0)` 会排到最后）。

### 2.3 交付与消费（各只一份实现）

| 函数 | 职责 |
| --- | --- |
| `_top_ship_pick(room, pid)` | 该玩家当前该处理的那一项（优先级最高） |
| `_dispatch_ship_pick(room, pid)` | 把它下发给前端（幂等，无事不发） |
| `_consume_ship_pick(room, pid, reason)` | 消费栈顶 + **自动投递下一项** |
| `_register_simple_ship_pick(...)` | 只登记、不发事件（仁王之盾：它有自己的多选 UI） |
| `_clear_ship_picks(room, pid=None)` | 终局 / 重摆棋盘时清空 |
| `_ship_pick_blocked_reason(room, pid, card)` | 出牌闸门 |

### 2.4 低优先级被挡住 → **拒绝出牌 + 明确文案**（不排队）

在 `use_magic_card` 里加**针对性**闸门（只拦选船类卡，见 `_SHIP_PICK_CARDS`）：

> 「请先完成「恶魔契约」的选船，再使用这张卡」

**为什么不做"排队后延迟重放"：** 语义上卡面就是"**必须先**牺牲船，**然后**才能暴露"；
排队要额外处理"施法目标已被打沉"等一串边界，风险远大于收益；
拒绝则失败可见、玩家立刻能重试。

### 2.5 前端

| 改动 | 说明 |
| --- | --- |
| `gameState.boardSelection` | 记**选区归属**（`{kind, reason, label}`）—— 单靠 `selectingOnBoard` 只知道"有人在选"，不知道"是谁在选" |
| `createBoardAreaPicker` | 被占用时**不再静默 `return null`**，改为弹出「请先完成「X」的点选」 |
| `SACRIFICE_LABELS` / `SHIP_PICK_PRIORITIES` / `SHIP_PICK_CARD_NAMES` | 前端**镜像**服务端优先级，仅用于置灰与提示 |
| `.magic-card.pick-blocked` | 被挡的选船卡置灰 + 悬停说明 |

⚠️ 前端那份优先级**不是第二套判据**：真正的放行/拒绝由服务端裁决
（`_ship_pick_blocked_reason`），前端只是让玩家不必先点一下才知道不行。

---

## 3. 实施教训

1. **单槽 = 隐藏的数据丢失**。`{'player': X}` 被第二次请求覆写时，
   **没有任何报错**，只在 X 点船时以一句「当前没有待牺牲的战舰」暴露。
   → 凡是"同一时刻可能有多方请求"的状态，一律用**按 owner 分组的队列**，
   不要用单槽。

2. **`magic_temp_data` 不是可靠的家**。它有 8 处整体覆写。
   跨"玩家交互等待期"的状态**必须**放房间级字段。

3. **`selectingOnBoard` 这种裸布尔是"无主的状态"**。
   它只说"有人在选"，不说"是谁"。两个模式抢同一块棋盘时，
   后来的那个只能静默失败。→ 记**归属**（kind + label），才能给出有意义的提示。

4. **静默 `return null` 是最贵的写法**。`picker ? picker.cleanup : null`
   把"启动失败"抹成了"什么都没发生"，玩家侧表现为「点了没反应」，
   排查时要一路反推。**失败必须带原因**。

5. **改共用判据要 grep 全部调用点**。改 `_clear_board_effects` 的
   `list(room.players)` → `[caster_id]` 时误伤了灵气复苏（`caster_id` 在那个作用域
   根本不存在），一次弄红 7 个用例。**收成单行编辑也要核对参数语义。**

---

## 4. 验收

| 项 | 结果 |
| --- | --- |
| 全量测试 | **1788 passed / 0 failed**（新增 `tests/test_ship_pick_priority.py` 18 条） |
| 复现链（生产实测） | 恶魔契约 + 克苏鲁之眼：**两边都能各自完成选择**，不再报「当前没有待牺牲的战舰」 |
| 优先级顺序 | 排在后面的高优先级项**先**交付；消费后自动投递下一项 |
| 出牌闸门 | 低优先级卡被拒且**文案非空**；非选船卡不受影响 |
| 存储独立性 | 两次 `magic_temp_data` 整体覆写后待选仍在 |
| 反向守卫 | 单个恶魔契约照常牺牲一艘；**沉船仍不能被选来抵账** |
| 前端 | `node --check` 通过；`dom_contract_check.mjs` 全绿 |
| 服务 | `active`、HTTP 200、0 条错误 |

---

## 5. 未纳入本批（已知同类风险）

**放置类**（`pending_placement`）：增援 / 死者苏生 / 神机妙算 / 绝处逢生。
交互是"**选空格放船**"而不是"点已有的船"，流程不同，本批未动。
但它们同样住在 `magic_temp_data` 里，**有同样的被整体覆写抹掉的风险**。

**`pending_shenji`**（神机妙算宣言窗口）同理。

若要一并治理，做法相同：搬到房间级字段 + 明确消费点 + 回归用例。
