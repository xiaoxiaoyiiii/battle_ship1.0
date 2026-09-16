# 连锁请求界面重做 + 卡牌预览 + 绝处逢生候选格归属（2026-09-16）

作者一次提的三件事（外加一件运维）：

1. 连锁请求里要能看卡牌效果（桌面悬停 / 手机点击弹窗）
2. 连锁请求界面要跟「阶段转换时点请求」一样好看
3. 绝处逢生生效后，自己棋盘的候选格被画到了**对手棋盘**上，误导自己的攻击
4. 删掉服务器上 321MB 的 4K 壁纸原文件

---

## 1. 连锁请求弹窗重做（#1 + #2）

`static/game.js` 的 `showChainRequestPrompt` + `static/style.css`。

**视觉复用策略**：DOM **内层**复用 `priority-*` 作视觉基类（面板/徽标/圆环/卡牌/按钮），
连锁专属差异走 `chain-request-*`（蓝色 accent、描述行）。改整体质感只需改
`.priority-*` 一处，两个弹窗同时生效。

⚠️ **外层只挂 `chain-request-prompt`，不挂 `priority-prompt`**：
`showPriorityPrompt` 里有 `document.querySelectorAll('.priority-prompt').forEach(remove)`
的清理逻辑，共用会让"打开优先权弹窗"顺手删掉连锁弹窗。外层类名是"这是哪个弹窗"的
语义锚点，必须唯一。

**卡牌预览**（复用已有机制，无需改服务端）：
- `lookupCard(name)`（前端卡面数据带 `description`）+ `showCardTooltip`（悬停浮层）
  + `showCardDetail`（点击详情窗）
- 卡面上另显示**描述摘要**（46 字截断），桌面不悬停也看得到大意
- 触摸设备：`matchMedia('(hover: hover)')` 为 false 时，点第一次只弹详情、
  点第二次才打出（避免"想看效果"被当成"确认出牌"），并给出「再看一次即打出」提示

**保留的行为**：需要目标的速阶3卡仍走 `needsTargetSelection` → 目标选择器 →
回填 `targets` 给 `chain_response`（09-13 第 19 条修复）；绝处逢生生效中不弹窗、
自动放弃并说明；10 秒倒计时到点自动放弃；点遮罩不产生任何响应（避免误触=误放弃）。

## 2. 绝处逢生候选格归属（#3）

**病灶**：`initGameBoards()` 里两块棋盘是两个独立循环，候选格只写在**对手棋盘**那个
循环；服务端 `last_stand_cells` 载荷也不带归属 → 自己放绝处逢生时，自己棋盘的候选格
被画到对手棋盘上（作者实测）。

**修法**：服务端加 `owner`（`game_effects['last_stand_owner']`，随候选格一起清、重连
快照一起下发）；前端 `gameState.lastStandOwner`，按归属决定画在哪块棋盘：
owner 是我 → 我的棋盘；否则 → 攻击目标棋盘。文案也按角色区分。仍然只加
`.last-stand-candidate`，**绝不加 `hit`/`miss`**（09-14 教训：一画叉玩家就以为打不了）。

## 3. 运维（#4）

删除 `/opt/battleship/static/wallpapers/longzu-huiliyi.mp4`（321MB）。目录从 331M → 9.5M，
4K 链接 404、1080p 仍 200。保留 1080p（线上正在用）。

## 4. 验证

| 层 | 结果 |
| --- | --- |
| pytest | **812 passed**（809 + 新增 3 条：载荷带 owner / 重连快照带 owner / 清理时一并清） |
| 无头工具（12 个） | chain_target_check（含新增 D1–D8 预览断言）、last_stand_board_check（**新建**，10 条棋盘归属断言）、priority_prompt_check、chain_hand_and_baizhe、chain_negation_message、last_stand_message、shield_laststand、state_visual、sfx、ui_layout、hand_play、papal_discard —— **全部通过** |
| 手机端（真触摸模拟） | `(hover: hover)=false`、提示语是触摸版、描述未被容器裁切、无横向溢出 |
| 视觉 | CDP 截图（宽屏浅/深 + 390×844）经 modlens 复核：徽标+圆环+卡牌（卡名/速阶/描述）+按钮，结构合格 |

## 5. 踩到的两个坑（值得记）

1. **改了链弹窗的 DOM 类名后，12 条工具断言变红 —— 是工具选择器过时，不是功能坏了**。
   逐个把 `.chain-card-item`/`.magic-prompt` 等旧选择器更新后全绿。
   **教训：DOM 改名必须同步搜一遍 `tools/`，否则会把"工具过时"误判成"功能回归"。**
2. **两条我自己新写的 pytest 一开始就红**：绝处逢生要求 ≥3 艘战舰才能发动，我只给了 2 艘，
   `apply` 直接失败 → owner 根本没写入。**教训：写"验证某字段被写入"的测试前，先确认
   前置条件真的成立**，否则红灯会被误读成功能 bug。
3. 一条既有测试（`test_ui_review_fixes.py` 的全角冒号）断言 `剩余时间：` 存在于 game.js ——
   倒计时改成圆环后该文案消失，已更新并注明原因（圆环由 chain_target_check 断言）。

## 6. 已知边界

- 同一大回合双方都放绝处逢生时，`game_effects['last_stand_cells']` 是房间级单键、
  后者覆盖前者 —— 既有设计限制，本次未扩。
- `_finish_placement('last_stand')` 会清掉候选格数据但**不广播**（客户端保留高亮直到
  换大回合）—— 既有行为，本次未改。
