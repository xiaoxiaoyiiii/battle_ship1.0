# 「破盾格还能再打」与「绝处逢生候选格能打」（2026-09-14）

## 1. 作者反馈

> 1. 绝处逢生存在问题。我是这样想的：就是这一方使用绝处逢生通过之后，
>    让原本有船的六个格子高亮标给对方，然后不要是红叉叉，不然的话打不了。
> 2. 仁王之盾存在很大问题。就是攻击到带盾的船之后那个格子会直接变成红叉叉，
>    不能再次攻击了就。改成一个特殊一点的格子样式，能看出来是带盾牌的船被破盾了，
>    然后在同一回合内还是可以再次攻击这个地方的。

## 2. 同一个病灶：「这一格打过了」被当成铁律

`player.attacks`（服务端）→ `board_attacks_updated`（广播）→
`gameState.myAttacks / opponentAttacks`（前端）这条链决定了**两件事**：

1. 格子画不画 ✕；
2. `initGameBoards()` 给不给这个格子绑 `click` —— **没绑就等于点不动**。

所以任何"不该算作已打过"的交互，一旦被记进这个数组，格子就被锁死一整回合。
这次的两条反馈正好各撞一次：

| 现象 | 病灶 |
| --- | --- |
| 打带盾的船 → 格子变红叉、同一回合再也打不了 | 盾把炮弹吃了、船**毫发无伤**，却照样记进 `attacks` |
| 绝处逢生的六个原格 → 红叉、对方以为打不了 | 自牺牲走了通用的「牺牲」通道，前端一律画叉 |

## 3. 仁王之盾

**改法（服务端）**：盾挡下的那一炮**不记进 `attacks`**，并在 `AttackResult` 上新增
`shield_blocked` 字段，让前端知道该画"破盾"而不是命中叉。

```python
elif ship.shield:
    ship_sunk = False
    shield_blocked = True        # ← 新增
    ship.shield = False
    ...
if not shield_blocked:           # ← 新增：被盾挡下的不记账
    room.players[attacker_id].attacks.append(...)
```

- **攻击次数照扣** —— 盾吃掉的是**一发炮弹**，这一点没变；
  变的只是"这一格不算已确认命中"，所以同一回合可以再打一次（盾已经没了，这一炮正常结算伤害）。
- 连续两次打同一格不会被"你已经攻击过这个位置了"拦下：第二炮真正造成伤害时才记账。

**改法（前端）**：`updateAttackDisplay` 一进来先看 `result.shield_blocked`：

- 记进 `gameState.shieldBrokenMine / shieldBrokenOpponent`（**不是** `myAttacks/opponentAttacks`）
- 因此格子仍有 `click` 监听，点下去照样发攻击请求
- 渲染成青蓝虚框 + 盾牌字符 `⛨`，和红叉明确区分

之后这一格真被打中时，把它从 `shieldBroken*` 里剔掉，恢复成正常的 ✕。

## 4. 绝处逢生

**改法（服务端）**：

- 结算那一刻下发 `last_stand_cells`（原本有战舰的格子，唯一一艘新船必在其中），
  广播给双方 —— 这是公开信息，对方要据此知道往哪儿打。
- 换大回合时清掉并补发一次空列表（不留过期线索）。
- `_build_room_sync` 带上它，重连后高亮不丢。

**改法（前端）**：

- `ship_sacrificed` 里 `reason === 'last_stand'` 直接 return：
  **不画叉、也不播报**（旧实现把卡名写死成「恶魔契约」，绝处逢生也被报成恶魔契约）。
- 用 `lastStandCells` 渲染成金色斜纹 + `?`，和红叉、○ 都不同色不同形。
- 这些格子**没有**加 `hit`/`miss` 类，所以照旧绑 `click`，对方点下去就能打。
- 已经打过的候选格让位显示真实结果（`○`/`✕`），不再顶着一个问号。

## 5. 视觉上四种状态必须一眼可分（截图实测）

`tools/shield_laststand_check.mjs` 摆好状态后截图，交给视觉桥读：

> 第三行分别是「红底白 X」「白底灰圆」「蓝底盾牌图标」「三格黄色斜纹 + 棕色 ?」，
> 左上角一格是橙色描边（显形）。

分别是：命中 ✕ / 落空 ○ / **破盾** / **绝处逢生候选** / 卡牌显形 —— 五种状态互不混淆。

## 6. 回归与验证

| 层次 | 产物 | 结果 |
| --- | --- | --- |
| 单元 | `tests/test_shield_and_last_stand.py`（**11 条**） | 全绿 |
| 全量 | `python -m pytest tests/ -q` | **740 passed** |
| 无头前端 | `tools/shield_laststand_check.mjs`（**18 项**：破盾样式/仍可点/真打中后变正常/候选格高亮/不画叉/能点/换回合清除） | 全部通过 |
| 既有无头套件 | heal_revive_click / priority_prompt / priority_live / ui_layout / hand_play / reinforcement_tie / effect_badge / target_selection / papal_discard / chain_target / sfx / bgm / card_compendium / room_invite / stats_modal | 全部通过 |
| 真 socket e2e | e2e_heal_revive_attack / e2e_priority_prompt / e2e_papal_discard | 全部通过 |

**反证**：把 `if not shield_blocked:` 改回无条件记账 →
`test_shield_blocked_cell_is_not_recorded_as_attacked` 与
`test_can_attack_the_same_cell_again_in_the_same_turn` 立刻红。

**顺带修掉一个假红**：`tools/priority_live_check.mjs` 的「倒计时在走」偶发失败
（`cd1=cd2=10`）。根因是无头浏览器把**后台标签页**的 `setInterval` 节流
（两个标签页共用一个窗口，非活动那个被视为 hidden），倒计时正好用 `setInterval(1000)`。
修法：断言前先 `Page.bringToFront` 解除节流，再轮询等它真的变化（最多 8×0.7s）。
连跑两次稳定通过。

## 7. 通用教训

**「已做过某事」的记录，只应该在"这件事真的发生了"时才写。**
这次两处都是"记录的是动作，不是结果"：盾挡下了（动作发生了、结果没发生）、
自牺牲了（动作发生了、但不是被攻击）。把动作当结果记，就会把交互永久/整回合锁死 ——
而且锁死之后**表现是"点了没反应"**，最难查。
