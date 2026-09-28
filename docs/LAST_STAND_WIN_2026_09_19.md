# 绝处逢生「击杀即胜」的生命周期修复（2026-09-19）

## 作者反馈

> 「修复一下绝处逢生魔法卡的问题 就是他的击中对方的船自己直接获胜的效果只会在绝处逢生生效的那一个回合有效 到了下一个回合就没有这个效果了
> 我的本意是只要绝处逢生通过了 接下来所有回合只要自己的攻击打死了对方的船 那就直接判定自己获胜」

## 根因：一个标记兼职两件事

`EffectFlags.last_stand` 这**一个**布尔值同时表示两件生命周期完全不同的事：

| 含义 | 卡面依据 | 该活多久 |
| --- | --- | --- |
| 发动回合内自己的其余魔法卡全部无效 | 「在绝处逢生生效的**回合**」 | 本回合，换回合即清 |
| 击杀对方任何一艘船即直接获胜 | 「**接下来**，只要自己击杀对方的任何一艘船」 | 活到对局结束 |

于是第 2 件事跟着第 1 件一起在换小回合时被清掉 —— 效果只活一个回合。

### 更隐蔽的一层：清理白名单有两份实现

`server.py` 顶部有一个常量 `FLAGS_KEEP_ACROSS_TURN`（小回合切换保留哪些标记），
但 `end_turn` 里**另有一份写死的内联列表**：

```python
permanent_flags = ['holy_heart', 'reinforcement_check', 'no_draw', 'prediction', 'forced_kill']
```

而那个常量的注释还指着它说「分类见 FLAGS_KEEP_ACROSS_TURN」—— 两份互相漂移。
本项目 `CLAUDE.md` 踩坑 #1 早就写过「同一个业务判断有两份实现就一定会漂移」，
这次正是它：**任何新标记两边都不会登记，于是换回合时无声消失**。
这次顺手把内联那份删掉，统一走常量（唯一实现）。

## 改法

### 1. 拆成两个标记

```python
last_stand: bool = False      # 绝处逢生：发动回合的锁卡（换小回合即清）
last_stand_win: bool = False  # 绝处逢生：本局后续击杀即胜（活到对局结束）
```

- `FLAGS_KEEP_ACROSS_TURN` 加入 `last_stand_win`
- `FLAGS_KEEP_ACROSS_ROUND` 从空集改为 `{'last_stand_win'}`（大回合重新猜拳时也保留）
- `end_turn` 里那份内联白名单删除，改调 `_prune_effect_flags(room, FLAGS_KEEP_ACROSS_TURN)`

### 2. 判胜收紧为「真的打死了一艘船」

原实现只判「造成了伤害」就获胜 —— 普通命中（甚至一炮没打沉）都能直接赢，
那不是卡面写的「**击杀**了对方的任何一艘船」。现在要求：

```python
if (room.players[attacker_id].effect_flags.last_stand_win
        and (ship_sunk or has_forced_kill)):
```

`ship_sunk` 为真时 `_apply_ship_sunk_effects` 已经扣过 `remaining_ships`，
所以判胜即「击杀」。强制击杀（余音绕梁）本身就是击杀，同样算数。

### 3. 角标拆成两条（生命周期不同就要分开显示）

角标元组加了第 4 位**显示后缀**：

```python
('last_stand',     '绝处逢生', _EFFECT_EXPIRY_TURN,  '锁卡'),
('last_stand_win', '绝处逢生', _EFFECT_EXPIRY_MATCH, '击杀即胜'),
```

⚠️ 元组第 2 位**必须仍是真实卡名**「绝处逢生」：浮层靠 `name` 回查卡面原文，
有测试钉着这条契约（`test_effect_badges.py::test_all_badge_labels_exist_as_cards`）。
最初把标签直接写成「绝处逢生·封锁魔法卡」就被这条测试拦下了 —— 说明区分两个角标
**不能靠改卡名**，要靠单独的 `label` 字段。

### 4. 关闭「击杀即胜 = 还在锁卡」的误判（前端）

服务端下发的角标对象现在带 `key`（标记名）/ `name`（卡名）/ `label`（显示名）三个字段，
`room_sync` 另加两个显式布尔：`last_stand_lock` / `last_stand_win`。

前端 `isLastStandActive()`（出牌门禁）改为按**标记名**判定。
原实现按卡名前缀匹配（`s.indexOf('last_stand') === 0`），而「击杀即胜」的角标名也叫
「绝处逢生」→ **锁卡过期后前端仍以为在锁卡**，玩家点魔法卡被本地拒掉、弹
「绝处逢生生效中」，而服务端其实放行。保留旧卡名兜底，但只在「新口径标记一个都没出现」
时才生效（升级瞬间不能把门禁整个放开）。

### 5. `active_effects` 不再混入房间级效果

`_build_room_sync` 的 `active_effects` 以前发的是 `room.game_effects.keys()`，
而 `last_stand_cells` / `last_stand_owner` 都**恰好以 `last_stand` 开头** ——
于是「候选格还在场」的任何时刻，前端都按前缀匹配判定「锁卡生效中」。
现在只发玩家身上真实存在的 `effect_flags` 名字（`_PUBLIC_EFFECT_FLAGS`）。

### 6. 浮层回查按标记名（子智能体实测发现）

`effectOfBadge()` 用 `e.name === btn.dataset.effectName` 回查，两条角标卡名相同 →
永远命中第一条，「击杀即胜」的浮层显示成锁卡的元数据
（失效时机写成「本回合结束时失效」，与「活到对局结束」自相矛盾；
因为两条 `description` 本来就相同，只有失效时机露馅）。
改为优先按 `key` 匹配，`hideEffectPopover`/`sameOpen` 的浮层身份也一并改用 `key`。

## 验证

| 项 | 结果 |
| --- | --- |
| `pytest` 全量 | **1483 passed** |
| 新增 `tests/test_last_stand_win_persists.py` | 17 条（标记生命周期 / 跨回合获胜 / 判胜必须真击沉 / 重连快照 / 角标） |
| `tools/last_stand_win_check.mjs`（前端，无头 Edge 喂真实事件） | 53 PASS / 0 FAIL |
| `tools/last_stand_win_e2e.mjs`（**真 socket 打完一局**，另实现最小 socket.io 客户端） | 全部通过 |
| `tools/effect_badge_check.mjs`（既有角标工具，防回归） | 全部通过 |
| **反证** | 把 `last_stand_win` 从白名单撤掉 → **7 条立刻变红**（含两条端到端），恢复后 17 条全绿 |

真 socket 端到端覆盖的是纯 pytest 覆盖不到的那段协议流程：
建房 → 双方摆船 → 真猜拳 → 出牌 → 连锁响应窗口 → 放唯一一艘船 →
把攻击次数打光 → 进结束阶段 → 交回合（对方回合也走一遍）→ **大回合重新猜拳** →
换回合后击杀 → `game_over` 广播给双方且胜者是施法者。

## 实施过程中踩的坑（都是「症状像服务端坏了」的假象）

1. **socket.io ack 帧格式**：是 `43<ackId><JSON>`，中间**没有长度位**。
   先按普通事件解析（漏掉回包）→ 又按「长度前缀」解析（把 JSON 截成 `"["`、
   `JSON.parse` 静默失败）→ 两种写法的症状都是**客户端超时**，看着像服务端不响应。
2. **handler 抛异常时连 ack 都不回**：布船负载少了 `hits` 字段 →
   `PlayerShip.__init__() missing 1 required positional argument` →
   客户端只看到超时。最后靠**服务端日志里的 traceback** 才定位。
   → 所以「客户端超时」要先去看服务端日志，别急着怀疑网络/协议。
3. **失败是静默的**：`end_turn` / `set_decline_priority` 写错字段都只回 `error`、
   状态不变。不校验返回值的话，后面「换回合后」的断言其实还在测同一个回合 —— **假绿**。
4. **`end_turn` 只在 end 阶段生效**：battle → end 要走 `enter_end_phase`，
   「交一次回合」是两步；且**带着剩余攻击次数不能进结束阶段**。
5. **大回合会重新猜拳**：`round += 1` 后 state 变 `rock_paper_scissors`，
   不猜拳就进不了 attacking。
6. **脚本书写约定**：P1/P2 的 id 别从 `Object.keys(players)` 猜顺序
   （两个都是服务端分配的 sid，顺序不保证）—— `join_room` 的 ack 会给 P2 的 id，
   剩下那个才是 P1 的。`set_decline_priority` 的字段是 `decline`（不是 `decline_all`）。
