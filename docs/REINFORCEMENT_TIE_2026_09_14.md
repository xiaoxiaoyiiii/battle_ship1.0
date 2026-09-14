# 「极限增援」平局把回合卡死（2026-09-14）

## 1. 作者反馈

> 极限增援卡牌出现问题。当双方船数相等时不会判定谁获胜，但是游戏会直接卡死，
> 无法进行下一步操作，就是不能结束阶段了按钮直接消失了。

## 2. 根因：结算分支从 `end_turn` 里提前 `return`，把整段收尾跳过了

`server.py` 的 `end_turn` 里有这么一层结构（示意）：

```python
if room.current_attacker == player_id and room.current_phase == 'end':
    ...
    if next_index == 0:                       # ← 进入新大回合
        room.round += 1
        ...                                    # 神威回归 / 解冻 / 伤害统计归零 …

        if 'reinforcement_check' in room.game_effects:
            ...
            if remaining_turns <= 0:
                if 船少的一方: winner = …
                else:
                    room.game_effects.pop('reinforcement_check', None)
                    emit('message', {…'无人获胜'…})
                    return {'status': 'success'}   # ← 元凶
                return {…'game_over'…}

        if 'holy_heart' in room.game_effects:
            ...

        # ↓↓↓ 真正的收尾，平局时全被跳过 ↓↓↓
        room.state = 'rock_paper_scissors'      # 回到猜拳
        room.current_phase = 'preparation'
        emit('game_state', {'state': 'rock_paper_scissors', 'round': room.round})
        return {'status': 'success', 'new_round': True}
```

平局那条 `return` 之前，`room.round` 已经 +1 了。所以结算之后：

| | 结算后的值 | 应该是 |
| --- | --- | --- |
| `room.round` | 已 +1（偷偷加了） | +1 |
| `room.state` | 仍是 `attacking` | `rock_paper_scissors` |
| `room.current_phase` | 仍是 `end` | `preparation` |
| 广播的事件 | 只有 `message` + `reinforcement_turn_updated` | 还要有 `game_state` |

**客户端一条"回合推进了"的广播都没收到**，界面就停在旧阶段：
交回合按钮不再出现（或按了没有任何变化），只剩一个点了没反应的按钮 ——
正是作者说的"下一步不了、按钮直接消失"。

## 3. 实测复现（`tools/reinforcement_tie_check.mjs`，真实浏览器 + 真服务端）

两个真页面，真打出「极限增援」，把双方船数调成相等，然后逐回合推进到大回合边界。
**反证（把旧的 `return` 加回去跑同一个工具）**：

```
=== 结算后的客户端状态 ===
  服务端: {"state":"attacking","phase":"end","round":4}      ← 卡在 attacking + end
FAIL  ★ 平局后进入新大回合（state=rock_paper_scissors，而不是卡在 attacking+end）
FAIL  ★ 双方客户端都切到了猜拳界面（收到了状态广播，不是停在对局屏干等）
        -> {"A":["game-screen"],"B":["game-screen"]}          ← 两边都还停在对局屏
```

修好之后同一个工具：

```
--- 第 5 步（round=3 phase=preparation state=attacking）---
    ack = {"status":"success","new_round":true} -> round= 4 ... state= rock_paper_scissors
    提示: ["showMessage: 极限增援结算时双方船数相同，无人获胜，效果结束"]
PASS  ★ 平局不判胜负（作者裁定）
PASS  ★ 平局后进入新大回合（state=rock_paper_scissors）
PASS  ★ 回合数正常 +1（不是原地不动，也不是靠玩家再点一次才 +2）
PASS  ★ 双方客户端都切到了猜拳界面（收到了状态广播）
PASS  ★ 打完猜拳能回到对局（没有卡死）
```

## 4. 修法

平局分支**不再 `return`**，只做两件事，然后让流程照常往下走：

```python
room.game_effects.pop('reinforcement_check', None)   # 作废这张卡
emit('message', {…'无人获胜，效果结束'…}, room=room_id)
check = None        # ⚠️ 别让收尾那行又把它塞回 game_effects
```

两处细节别丢：

1. **`check = None` 是必需的**。紧跟着的收尾是
   `room.game_effects['reinforcement_check'] = check`，`check` 还指着那个 dict，
   不置空就会把效果塞回去 → 下个大回合再判一次（违反"作废"的初衷）。
2. 船数不同时仍然是 `_finish_game_win` + 广播 `game_over` + `return`——
   那条路径本来就该结束对局，`return` 是对的。

## 5. 回归与验证

| 层次 | 产物 | 结果 |
| --- | --- | --- |
| 单元 | `tests/test_reinforcement_tie.py`（**9 条**：平局继续对局 / 必须有状态广播 / 效果不复燃 / 回合只 +1 / 非平局照旧判胜负 / 计时未到不结算） | 全绿 |
| 全量 | `python -m pytest tests/ -q` | **719 passed** |
| 真实浏览器端到端 | `tools/reinforcement_tie_check.mjs`（两个真页面 + 真服务端，含"切到猜拳界面"这条能证明客户端可继续的断言） | 全部通过 |
| 既有无头套件 | hand_play / priority_prompt / priority_live / ui_layout / effect_badge / target_selection / papal_discard / chain_target / sfx / bgm / card_compendium / room_invite / stats_modal | 全部通过 |

**通用教训**：在一段"做完这件事还要继续往下做"的流程里，
**分支里随手 `return` 会静默吞掉后续的收尾**（换人、重置阶段、广播）。
这个项目里同一形状的坑已经出现过三次（绝处逢生/连锁续做、优先权 `_priority_continue`、
这次的极限增援平局）。判断标准很简单：
**这个 `return` 是"提前结束整个操作"，还是"只想跳过这一步"？**
后者一律改成置标志位、让流程自然往下走。

## 6. 顺带修好的一处观测能力

`test_get_game_state` 补了 `round`（大回合数）。极限增援 / 无暇圣心这类
按大回合计数的效果，E2E 必须能观测到"回合到底有没有推进" ——
少了它，这次的回归断言只能间接推断。该事件由 `@_test_event` 门禁关闭，线上不可用。
