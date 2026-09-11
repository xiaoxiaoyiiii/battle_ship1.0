# 战舰棋 + 魔法卡 · 前端与测试技术分析报告

> 分析对象：`C:\Users\Administrator\Documents\ds-harness-desktop\WorkSpace\battle_ship1.0\`
> 分析日期：基于工作区当前 HEAD `35a3131 日志窗和聊天窗改回浮动窗，并把日志逻辑重写一遍`
> 方法：grep 定位 + 分段精读，所有结论均附行号，未作臆测。

## 0. 实测行数校正（重要）

任务书中给出的行数与实际不符，后续开发者请以实测为准：

| 文件 | 任务书声称 | **实测行数** |
|---|---|---|
| `static/game.js` | 5625 | **5625** ✅ |
| `templates/index.html` | 577 | **577** ✅ |
| `static/magic_cards.js` | 49 | **48**（末尾无第 49 行） |
| `static/magic_card.json` | — | **83**（`--` 数据行） |

> 注：`read` 工具报告的 `game.js` 为 5625 行、`index.html` 为 577 行，与任务书一致。
> 早期用 `Get-Content | Measure-Object -Line` 得到的 5071/542 是 PowerShell 对无尾换行文件的计数偏差，**以 read 工具为准**。

---

# A. 前端分析

## 1. `window.gameState` 全部字段

### 1.1 初始化声明（`game.js:804-829`）

| 字段 | 初始值 | 用途 |
|---|---|---|
| `socket` | `null` | socket.io 连接实例，全前端唯一通信句柄 |
| `playerId` | `null` | 本局自己的玩家 ID（登录用户为 uid，游客为 sid） |
| `roomId` | `null` | 当前房间 ID；非空即视为"在局中"（见 `game.js:212`） |
| `playerName` | `'玩家'` | 自己昵称 |
| `opponentName` | `'对手'` | 对手昵称 |
| `ships` | `[]` | 己方战舰数组 |
| `placedShips` | `0` | 摆船阶段已放置数量 |
| `maxShips` | `6` | 本局可摆放船数上限（灵气复苏/败者食尘会改） |
| `isMyTurn` | `false` | 是否轮到自己（由 `updateTurnIndicator` 写入） |
| `myAttacks` | `[]` | 己方所有攻击记录 |
| `opponentAttacks` | `[]` | 对手所有攻击记录 |
| `lastAttack` | `null` | 最近一次攻击（溅射动画依赖 `gameState.lastAttack.x/y`，见 `4471`） |
| `deck` | `[]` | 牌堆 |
| `hand` | `[]` | 手牌（UI 渲染源） |
| `discardPile` | `[]` | 弃牌堆 |
| `chain` | `[]` | 连锁栈（前端只读展示用） |
| `shenweiHoles` | `[]` | 神威！扣掉的区域 `[{player,x1,y1,x2,y2,return_turn}]` |
| `currentPhase` | `null` | 当前阶段：`preparation` / `battle` / `end` |
| `fieldMagic` | `null` | 当前场地魔法**卡名字符串**（注意是名字不是对象，见 `4331, 4332`） |
| `selectedCardIndex` | `-1` | 当前选中的手牌索引，-1 未选中 |
| `inRoom` | `false` | 是否在对局房间中（掉线重连用） |
| `reconnectToken` | `null` | 对局重连 token |
| `frozen` | `false` | 对手掉线宽限期内冻结操作 |
| `opponentGone` | `null` | 对手掉线信息 `{deadline}` |

### 1.2 运行时动态追加字段（**初始化时未声明**）

这些字段在 `gameState` 字面量里**不存在**，首次赋值即隐式创建：

| 字段 | 首次赋值行 | 用途 |
|---|---|---|
| `currentAttacker` | `895`（亦见 `1890, 2044`） | 当前攻击方 playerId。**被 `canPlayCard`/`updatePhaseUI` 大量依赖，却未声明** |
| `round` | `896` | 当前大回合数 |
| `currentMagicCard` | `3510` | 正处于"待使用"状态的卡对象 |
| `currentCardIndex` | `3511` | 上述卡在手牌中的索引 |
| `selectingOnBoard` | `3617` | 防重入闸门：棋盘选区激活时禁止再开选区 |
| `selectionCleanup` | `3547` | 当前选区的清理回调（防止取消后残留高亮） |
| `selectedLine` | `4505`（仅被置 null） | 轰炸选中的行/列 —— **只写不读的疑似僵尸字段** |
| `noMagicCardsThisTurn` | `4449`（仅被置 true） | 无中生有后禁用摸牌 —— **同样只写不读，前端未实际约束** |
| `attacks` | `2359` | reset_gameboard 时清零；与 `myAttacks` 语义重叠 |
| `remainingShips` | `2362` | 仅 reset 时归零 |
| `opponentRemainingShips` | `2363` | 仅 reset 时归零 |

> ⚠️ **坏味道**：`gameState` 混用"已声明"与"隐式追加"，缺字段时不会报错只会 `undefined`，是典型静默失败源。建议统一在 `804-829` 补齐默认值。

---

## 2. 所有 `socket.on` 事件（事件名精确抄写）

共 **58** 处 `socket.on` 注册。分两部分——`setupSocketListeners()` 内（`1711` 起）与散落外部。

### 2.1 局内聊天（独立初始化，`game.js:714`）

| 事件名（精确） | 行号 | handler 行为 / 更新 |
|---|---|---|
| `'chat_message'` | **714** | `appendChatMessage(data.username, data.message, data.isMe)` → 追加 DOM 到 `#in-game-chat-messages`，自动滚底 |

### 2.2 连接与匹配

| 事件名（精确） | 行号 | handler 行为 / 更新 |
|---|---|---|
| `'connect'` | **1714** | 仅 `console.log('Connected to server')` |
| `'connect'` | **1924** | **自动重连主入口**：读 `loadActiveGame()`，有则 `emit('rejoin_room', {room_id, player_id, token})` |
| `'connect'` | **1642** | `createRoom()` 内部的一次性连接回调（建房→再 join_room） |
| `'match_queued'` | **1719** | 移除 `matchStatus` 的 `hidden`，显示"正在寻找匹配" |
| `'match_canceled'` | **1724** | 给 `matchStatus` 加 `hidden` |
| `'match_found'` | **2779** | 显示匹配成功界面（`switchScreen(matchSuccessScreen)` 路径） |

### 2.3 游戏状态与回合

| 事件名（精确） | 行号 | handler 行为 / 更新 |
|---|---|---|
| `'game_state'` | **1729** | **最核心事件**。隐藏所有 screen → 解析 `player_name`/`opponent_name`/`player_id` → 存重连上下文 → 定义并导出 `window.showOpponentStats`（`1811`）→ 按 `data.state` 分支（`waiting`/`placing_ships`/…） |
| `'resume_game'` | **1937** | 服务端提示恢复对局 → `saveActiveGame` + `emit('rejoin_room')` |
| `'reconnect_token'` | **1950** | 写入 `gameState.reconnectToken`，回存 localStorage |
| `'room_sync'` | **1980** | 调 `applyRoomSync(data)`（`890`）恢复：roomId/playerId/phase/round/hand/ships/attacks/shenweiHoles/fieldMagic/opponentName，并隐藏其它界面 |
| `'turn_change'` | **2014** | `gameState.currentPhase = data.phase`；`updateTurnIndicator(data.current_attacker, data.attacks_remaining)` → 更新 `#current-player`/`#attacks-remaining` + `initGameBoards()` |
| `'phase_updated'` | **2042** | 同步 `currentPhase`/`currentAttacker` → `updatePhaseUI()` |
| `'game_over'` | **2021** | 展示结束界面、设置 `#game-result`、`clearActiveGame()` |
| `'reset_gameboard'` | **2353** | 清空 ships/attacks/remainingShips，按 `data.new_max_ships` 重置 → 切到 `shipPlacementScreen` |

### 2.4 攻击相关

| 事件名（精确） | 行号 | handler 行为 / 更新 |
|---|---|---|
| `'attack_result'` | **1996** | `updateAttackDisplay(result)` + 更新 `#attacks-remaining` + `updatePhaseUI()` |
| `'attacks_updated'` | **2008** | 更新 `#attacks-remaining` + `updatePhaseUI()` |
| `'revealed_positions'` | **2891** | 渲染显形格子（雷达子弹/探测雷达/克苏鲁之眼） |

### 2.5 魔法卡与连锁

| 事件名（精确） | 行号 | handler 行为 / 更新 |
|---|---|---|
| `'magic_applied'` | **2399** | `showMessage` + `applyCardEffect(card, caster)` + 遍历 `result.affected_positions` 调 `updateAttackDisplay` 并重绘棋盘 |
| `'field_magic_updated'` | **2162** | 更新 `#current-field-magic` |
| `'magic_chain_updated'` | **2168** | 调 `updateChainUI()`（渲染 `#chain-display`） |
| `'chain_resolved'` | **2173** | **连锁结算总入口**：遍历 `data.results` → `applyCardEffect` → push 弃牌堆 → 按 `result.temp_data_id` 分发 6 种选择 UI（`taoyuan_choice`/`divine_decree`/`lingqi_choice`/`bury_choice`/`shenji_declare`/`shield_choice`）→ `updateHandUI()` |
| `'chain_request'` | **2257** | **响应窗口 UI**：弹 `.magic-prompt`，列出 `data.speed3_cards`，10 秒倒计时，倒计时归零 → `emit('chain_response', {chain:false})` |
| `'magic_chain_error'` | **2248** | 显示错误消息 —— ⚠️ **服务端从不 emit 此事件**（见 §11） |
| `'divine_decree_waiting'` | **2230** | 显示"对方正在选择神之宣告" —— ⚠️ **服务端从不 emit** |
| `'divine_decree_resolved'` | **2235** | 神之宣告完成提示 —— ⚠️ **服务端从不 emit** |
| `'discard_pile_updated'` | **2242** | 更新 `gameState.discardPile` —— ⚠️ **服务端从不 emit** |
| `'hand_updated'` | **2791** | `gameState.hand = data.hand` + `updateHandUI()` |
| `'lingqi_waiting'` | **2343** | `showMessage` 等待提示 |
| `'lingqi_complete'` | **2348** | `showMessage` 完成提示 |
| `'taoyuan_waiting'` | **2857** | 桃园结义等待提示 |
| `'taoyuan_complete'` | **2881** | 桃园结义完成提示 |
| `'shenwei_hole'` | **2797** | 追加 `gameState.shenweiHoles` + `applyShenweiHoles()` |
| `'shenwei_hole_restored'` | **2806** | 移除对应 hole + `applyShenweiHoles()` |

### 2.6 增援 / 圣心 / 掉落

| 事件名（精确） | 行号 | handler 行为 / 更新 |
|---|---|---|
| `'reinforcement_activated'` | **2049** | 显示极限增援倒计时面板 `#reinforcement-countdown` |
| `'reinforcement_turn_updated'` | **2072** | 更新剩余回合数 |
| `'reinforcement_finished'` | **2146** | 隐藏倒计时面板 |
| `'holy_heart_activated'` | **2088** | 显示无暇圣心倒计时 `#holy-heart-countdown` |
| `'holy_heart_turn_updated'` | **2112** | 更新剩余回合数 |
| `'holy_heart_interrupted'` | **2128** | 提示被打断 + 隐藏面板 |
| `'placement_request'` | **2818** | 调 `showPlacementPrompt(data)` 弹出布船点选浮层 |
| `'placement_done'` | **2821** | 关闭布船浮层 |

### 2.7 棋盘同步与掉线

| 事件名（精确） | 行号 | handler 行为 / 更新 |
|---|---|---|
| `'player_ships_updated'` | **2828** | 同步己方船 |
| `'ships_updated'` | **2836** | 同步棋盘（双方） |
| `'opponent_disconnected'` | **1957** | `showOpponentGoneBanner(deadline)` → 右上角红色横幅 + 每秒倒计时 + `gameState.frozen = true` |
| `'opponent_reconnected'` | **1962** | `hideOpponentGoneBanner()` + 提示 |
| `'game_canceled'` | **1967** | 隐藏横幅 + `clearActiveGame()` + 1.5s 后 `resetGame()` |
| `'reconnect_warning'` | **1974** | `clearActiveGame()` + 2s 后 `resetGame()` |

### 2.8 大厅与消息

| 事件名（精确） | 行号 | handler 行为 / 更新 |
|---|---|---|
| `'lobby_update'` | **2754** | 渲染 `#lobby-players-list` / `#lobby-player-count` —— ⚠️ **服务端从不 emit** |
| `'lobby_joined'` | **2767** | 切换加入/离开按钮 —— ⚠️ **服务端从不 emit** |
| `'lobby_left'` | **2773** | 同上 —— ⚠️ **服务端从不 emit** |
| `'message'` | **2843** | `showMessage(data.message \|\| data)` |
| `'game_message'` | **2848** | `showMessage` |
| `'game_log'` | **2813** | `renderServerLog(entry)` → 时间戳+徽章+文本插入 `#game-logs` 顶部 |
| `'error'` | **2851** | `showAlert(data.message \|\| data.msg \|\| data)` |

### 2.9 猜拳 / 其它

| 事件名（精确） | 行号 | handler 行为 / 更新 |
|---|---|---|
| `'rps_result'` | **1985** | 显示 `#rps-result` 文本（内含 `getRPSName` 调用） |
| `'connect'`（一次性） | **5303** | `init()` 内 `?room=` 自动入房；回调后 `socket.off('connect', onceConnect)` |

---

## 3. 所有 `socket.emit` 事件

| 事件名（精确） | 行号 | 触发交互 | 发送数据结构 |
|---|---|---|---|
| `'chat_message'` | **725** | 点发送 / 回车 | `{room_id, message}`（≤100 字符） |
| `'get_reconnect_token'` | **883** | 首次进局 | `{room_id, player_id}` + ack → 存 token |
| `'create_room'` | **1542, 1643** | 点"创建房间" | `{}` + ack |
| `'join_room'` | **1549, 1606, 1650, 1672, 1695, 2786, 5286, 5295** | 加入房间 / URL 自动入房 | `{room_id, player_name}`（部分带 ack） |
| `'find_match'` | **1580** | 点"匹配游戏" | `{player_name}` |
| `'create_ai_room'` | **1600** | 点"人机对战" | `{}` |
| `'cancel_match'` | **1627** | 点"取消匹配" | `{}` + ack |
| `'rejoin_room'` | **1928, 1941** | 断线重连 | `{room_id, player_id, token}` + ack |
| `'join_lobby'` | **2991** | 点"加入匹配"（大厅） | `{}` —— ⚠️ **服务端无此 handler** |
| `'leave_lobby'` | **2997** | 点"离开匹配"（大厅） | `{}` —— ⚠️ **服务端无此 handler** |
| `'place_ships'` | **3207** | 摆船确认 | `{room_id, player_id, ships}` |
| `'rps_choice'` | **3224** | 点石头/剪刀/布 | `{room_id, player_id, choice}` |
| `'attack'` | **3263** | 点对手棋盘格子 | `{room_id, player_id, x, y}` |
| `'surrender'` | **4892** | 点投降 | `{room_id, player_id}` |
| `'use_magic_card'` | **4353** | 使用魔法卡（有目标/无目标统一入口） | `{room_id, player_id, card, targets}` + ack（成功后 `hand.splice` + push 弃牌堆 + `updateHandUI`） |
| `'chain_response'` | **2298, 2312, 2330, 5368, 5389** | 连锁响应 | 放弃：`{room_id, player_id, chain:false}`；接续：`{room_id, player_id, chain:true, card, targets:[]}` |
| `'confirm_magic_target'` | **2566, 2651, 2737, 5603** | 桃园/灵气/埋葬/仁王 选择确认 | `{room_id, player_id, temp_data_id, target_data}` |
| `'get_magic_temp_data'` | **2549, 2609, 2728** | 请求临时选择数据 | `{room_id, player_id, temp_data_id}` + ack |
| `'enter_battle_phase'` | **5446** | 点"进入战斗阶段" | `{room_id, player_id}` + ack |
| `'enter_end_phase'` | **3453, 5468** | 点"结束战斗阶段"（前端先校验剩余攻击次数为 0） | `{room_id, player_id}` + ack |
| `'end_turn'` | **5481** | 点"结束结束阶段" | `{room_id, player_id}` + ack |
| `'request_revealed_positions'` | **4477, 4511, 4523** | 雷达子弹/探测雷达效果 | `{room_id, player_id}` |
| `'line_attack'` | **4499** | `applyCardEffect` 中"轰炸"分支 | `{room_id, player_id, line}` —— 🔴 **僵尸代码，服务端无此事件** |
| `'remove_field_magic'` | **4588** | 拆场地魔法 | `{room_id, player_id}` |
| `'cancel_placement'` | **4799** | 布船浮层点"放弃" | `{room_id, player_id}` |
| `'confirm_reinforcement_position'` | **4807** | 布船浮层点"确认" | `{room_id, player_id, position:{x,y}}` + ack（error 时**不关面板**并显示原因，`4810-4811`） |
| `'get_discard_pile'` | **5176** | 点"查看弃牌堆" | `{room_id, player_id}` + ack |
| `'confirm_shenji_declare'` | **5512** | 神机妙算宣言 | `{room_id, player_id, prediction}` |
| `'papal_attack'` | **5543** | 教皇旨意下弃卡攻击 | `{room_id, player_id, x, y, discard_card_index}` |

---

## 4. 主要函数索引（按职责分组）

### 4.1 初始化与主题
- `init()` **5255** — 入口：`bindEventListeners()` → 预填 `window.__USERNAME` → 按 pathname 分发 SPA 视图（`/leaderboard`/`/login`/`/register`/`/lobby`）→ `?room=` 自动入房 → `createMagicCardUI()` → `initCardTooltip()`
- `bindEventListeners()` **1045** — 巨型绑定函数；帮助弹窗内含**卡牌去重渲染**（`1053-1059` 按 `name|type|speed|description` 去重，故"失灵！"3 张只显示 1 条）
- `createMagicCardUI()` **5235** — **动态注入** `<div id="magic-system">` 含 `#magic-hand` 与 `#chain-display`（`5244-5250`）；有 `#magic-system` 存在性守卫防重复
- `initParticles()` **2** / `animate()` **22** — 粒子 canvas 背景
- `applyPrimaryColor()` **445** / `hexToRgb()` **457** / `darkenHex()` **466** / `lightenHex()` **471** / `shadeHex()` **475** — 主题主色派生

### 4.2 屏幕切换
- `switchScreen(screen)` **2910** — 见 §5
- `showLeaderboard()` **2927** / `showLobby()` **2933** / `fetchLeaderboard()` **2947** / `updateLobbyDisplay()` **2977**（**空实现**，注释说明依赖 `lobby_update` 广播）/ `joinLobbyMatch()` **2986** / `leaveLobbyMatch()` **2995**
- `showLogin()` **3331** / `hideLogin()` **3336** / `showRegister()` **3341** / `hideRegister()` **3346** / `handleLoginSubmit()` **3352** / `handleRegisterSubmit()` **3384**

### 4.3 棋盘渲染
- `initBoard(el, isEditable)` **3001** — 6×6 生成 `.cell`，`isEditable` 时绑 `handleCellClick`
- `initGameBoards()` **3018** — 双棋盘（`#game-player-board` / `#opponent-board`）重绘，含可点击状态
- `applyShenweiHoles()` **3077** — 给神威扣区格子打标记
- `updateAttackDisplay(result)` **3276** — 渲染命中/未命中/击沉
- `updateFieldMagicUI(playerId, card)` **4726**

### 4.4 摆船
- `handleCellClick(x, y)` **3136** — 布船点击
- `randomizeShips()` **3093** — 随机摆放
- `confirmShipPlacement()` **3182** — `emit('place_ships')`（**3207**）
- `renderShipButtons(maxShips)` **2623** — 灵气复苏选船数按钮

### 4.5 猜拳
- `handleRPSChoice(choice)` **3223** — `emit('rps_choice')`（**3224**）
- `getRPSName(choice)` **3320** — ⚠️ **映射错误**，见 §11.1

### 4.6 攻击
- `handleAttack(x, y)` **3236** — `emit('attack')`（**3263**）
- `updateTurnIndicator(currentAttacker, remainingAttacks)` **3312** — 写 `isMyTurn`、更新 UI、`initGameBoards()`

### 4.7 魔法卡
- `canPlayCard(card)` **3472** — 阶段合法性（准备阶段仅速阶1；速阶3随时；结束阶段禁）
- `canPlayAfterHit(card)` **3490** — 溅射/雷达子弹/饮血/越战越勇需上一击命中
- `needsTargetSelection(cardName)` **4033** — 见 §7
- `showMagicTargetSelection(card, index)` **3498** — 总调度，按卡名分发到各选择器
- `playMagicCard(index)` **4313** — 校验链：`freezeAlert()` → `canPlayCard` → `canPlayAfterHit` → 禁忌果实限制（`4331-4336`）→ 需目标则弹选择器，否则 `sendMagicCard(index, [])`
- `sendMagicCard(index, targets)` **4348** — `emit('use_magic_card')`（**4353**）
- `confirmMagicTarget(targetData)` **4376** — **payload 归一化中枢**，见 §7
- `applyCardEffect(card, casterId)` **4433** — 巨型 `switch(card.name)`：动画 + `showMessage` 文案（**"轰炸"分支含僵尸 `line_attack`，4499**）
- `showMagicAnimation(card)` **4641** / `showSplashAnimation(x, y, options)` **4658**

### 4.8 连锁与目标选择器
- `updateChainUI()` **5314** — 渲染 `#chain-display`（列表：连锁 N + 卡名 + 玩家）
- `showChainableCards()` **5331** — ⚠️ **定义但从未被调用**（死代码），其筛选条件是 `card.speed > 栈顶 speed`，与 `chain_request` 的"速阶3"策略不一致
- `createBoardAreaPicker(boardEl, size, onConfirm, onCancel)` **4048** — 真实棋盘 N×N 点选（触摸+鼠标），浮动确认条
- `createSelectionBoard(size, boardId, onConfirm, isOpponentBoard)` **4132** — 通用选区（含对手棋盘模式）
- `clearHighlights()` **3630/4061/4145**、`highlightIndex(idx)` **3634**、`confirmIndex(idx)` **3643**、`getSelectedCells(boardId)` **4301**
- `cleanupPrompt()` **3524** / `cleanupAll()` **3725/3865/3931** / `cleanupConfirm()` **3709** — 选区清理
- `isAdjacentToSelected(x,y)` **3781** / `isConnected(setLike)` **3790** — 硫磺火焰 6 连格校验
- `showTaoyuanChoice(result)` **2443** / `confirmTaoyuanChoice(...)` **2565**
- `showLingqiChoice(result)` **2585** / `confirmLingqiChoice(targetShips)` **2650**
- `showBuryChoice(result)` **2667** / `confirmBuryChoice(cardIndex)` **2736**
- `showShenjiDeclarePrompt()` **5494** / `showPapalDiscardChoice(x, y)` **5526** / `showRenwangChoice()` **5568**

### 4.9 手牌 / 弃牌堆
- `updateHandUI()` **5090** — 渲染 `#magic-hand`；**两段式点击**：未选中→选中+预览，已选中→`playMagicCard(index)`
- `updateCardPreview(card, index)` **4829** / `initCardPreview()` **4852** / `initCardTooltip()` **5219**
- `setupDiscardPileUI()` **5137**（绑定 `#view-discard-pile`、X、点外部、ESC 四种关闭）/ `closeDiscardModal()` **5151** / `loadDiscardPile()` **5175** / `displayDiscardPile(pile)` **5189**
- `createCardElement(card, index)` — 被 `showChainableCards` 引用（`5349`）

### 4.10 阶段
- `updatePhaseUI()` **5399** — 写 `#current-phase` 文案 + 按 `currentAttacker === playerId && phase` 显示对应按钮
- `setupPhaseButtons()` **5442** — 三个按钮的 emit

### 4.11 日志 / 聊天 / 浮窗
- `clearGameLogs()` **1000** / `addGameLog(logText, logType)` **1005** / `toggleGameLog()` **1019** / `renderServerLog(entry)` **1032**
- `initInGameChatSocket()` **710**（含 `chatSocketInitialized` 幂等闸门）/ `sendChatMessage()` **722** / `appendChatMessage(...)` **737** / `setChatVisible(visible)` **753**
- `makeFloatingDraggable(el, handle, storageKey)` **4911** / `makeVisualDraggable(el, handle)` **5008** / `initPreviewDrag()` **5072** / `initLogDrag()` **5080** — 见 §8

### 4.12 断线重连 / 账号 / 其它
- `freezeAlert()` **835** / `ensureOpponentGoneEl()` **839** / `showOpponentGoneBanner(deadline)` **847** / `hideOpponentGoneBanner()` **861**
- `saveActiveGame()` **867** / `clearActiveGame()` **873** / `loadActiveGame()` **878** / `requestReconnectToken()` **881** / `applyRoomSync(data)` **890**
- `showUserStats()` **1084**（内层）与 **1258**（**重复定义**）、`showMatchDetail()` **1184** 与 **1358**（**重复定义**）、`showOpponentStats()` **1783**（嵌套）+ **1811** 导出为 `window.showOpponentStats`
- `showMessage(text, options)` **941** / `showAlert(text)` **989** / `escapeHtml(str)` **746**
- `resetGame()` **3414** — `gameState = {...}` 整体重赋值（**注意：`3422` 处直接赋给裸 `gameState` 而非 `window.gameState`**，后者仍是原对象，见 §11.7）
- `updateCornerNames()` **180** / `updateOpponentAvatarCorner()` **194** / `controlGameElementsVisibility()` **204** / `updateMyAvatarInGame()` **241** / `updateOpponentAvatarInGame(opponentId)` **251** / `updateMusicStatus()` **579** / `initSurrenderBtn()` **4876** / `handleSurrender()` **4884**

---

## 5. 屏幕切换机制

### 5.1 全部 screen id（`index.html`）

| id | 行号 | 说明 |
|---|---|---|
| `start-screen` | 36 | 主菜单（class 含 `active`，默认显示） |
| `custom-room-screen` | 58 | 自定义房间 |
| `match-success-screen` | 112 | 匹配成功 5 秒倒计时 |
| `ship-placement-screen` | 124 | 摆放战舰 |
| `rps-screen` | 138 | 猜拳 |
| `game-screen` | 150 | 对战主界面 |
| `lobby-screen` | 298 | 大厅 |
| `leaderboard-screen` | 313 | 排行榜 |
| `game-over-screen` | 337 | 结束 |

⚠️ `switchScreen` 的数组（**2911**）包含 `startScreen, customRoomScreen, shipPlacementScreen, rpsScreen, gameScreen, leaderboardScreen, lobbyScreen, gameOverScreen`——**恰好 8 个，遗漏了 `match-success-screen`**。因此 `switchScreen(matchSuccessScreen)` 无法移除其它 screen 的 `active`，是潜在叠层 bug（`game_state` 里手写 `matchSuccessScreen.classList.remove('active')`（**1736**）绕过了这个缺陷）。

### 5.2 `switchScreen(screen)` 流程（`2910-2924`）

```
1. screens.forEach(s => s.classList.remove('active'))   // 2913
2. if (screen) screen.classList.add('active')            // 2915
3. hideEls = document.querySelectorAll('.hide-in-game')  // 2918
4. inRoomScreens = ['ship-placement-screen','rps-screen','game-screen','custom-room-screen']  // 2919
5. shouldHide = screen && inRoomScreens.includes(screen.id)  // 2920
6. hideEls.forEach(el => el.style.display = shouldHide ? 'none' : '')  // 2921-2923
```
即：**层叠式 class 切换** + 局内隐藏"登录/注册/排行榜/个人信息/主题"导航项。

### 5.3 完整对局时序

```
[主菜单 start-screen]
  │ #find-match(1580) / #ai-match(1600) / #custom-room(1643)
  ▼
[匹配中] match-status 显示（1719）
  │ 服务端 game_state state=waiting（1814）
  ▼
[匹配成功 match-success-screen] 5 秒倒计时（1853 progress）
  │
  ▼
[摆船 ship-placement-screen]  state=placing_ships（1820）
  │ 点格 handleCellClick(3136) / 随机 randomizeShips(3093)
  │ 确认 confirmShipPlacement → emit('place_ships') (3207)
  ▼
[猜拳 rps-screen]  双方均布船后
  │ handleRPSChoice(3223) → emit('rps_choice') (3224)
  │ rps_result 事件（1985）显示结果文本
  │ 平局 → 留在 rps-screen 重猜；有胜负 → 进入对战
  ▼
[对战 game-screen]
  │ 阶段循环 preparation → battle → end
  │   preparation: 可出速阶1；#enter-battle-phase(5446)
  │   battle:      出攻击 handleAttack(3236)；#enter-end-phase(5468，需攻击次数=0)
  │   end:         #end-turn-btn(5481) → 交回合
  │ 魔法卡随时（速阶3）或限阶段；连锁窗口 chain_request(2257) 打断
  ▼
[结束 game-over-screen]  game_over 事件（2021）
  │ #play-again / #return-to-menu
```

---

## 6. 连锁（Chain）的前端实现

### 6.1 关键词分布

`chain` **2168, 2173, 2257, 2298, 2312, 2330, 4242, 5314-5328, 5331-5396**；`response` 见 `chain_response` 5 处；`negated` / `magic_negated` —— **前端全文未出现**（前端不做无效化判定，完全依赖服务端 `chain_resolved` 的结果）。

### 6.2 响应窗口的展示（`socket.on('chain_request')`，**2257-2340**）

服务端推 `chain_request`，payload 形如：
```js
{ card: {name, speed, ...}, speed3_cards: [...], countdown: 10 }
```

前端行为：
1. 创建 `div.magic-prompt`，`innerHTML` 三段：标题 + `对方发动了魔法卡【${data.card.name}】` + `剩余时间 10 秒` + `data.speed3_cards` 渲染为 `.chain-card-item`（带 `data-card-index`/`data-card-name`/`data-card-speed`）+ 取消按钮
2. `document.body.appendChild(chainPrompt)`（**2284**）
3. **倒计时** `data.countdown || 10`（**2287**），每秒递减并写 `chainPrompt.querySelector('#chain-countdown-time')`；归零 → `clearInterval` + `emit('chain_response', {..., chain:false})` + `removeChild`（**2295-2305**）
4. 取消按钮 → `clearInterval` + `emit('chain_response', {..., chain:false})` + `removeChild`（**2308-2319**）
5. 点某张卡 → `clearInterval` + `emit('chain_response', {room_id, player_id, chain:true, card:selectedCard, targets:[]})` + `removeChild`（**2322-2339**）

### 6.3 结算展示（`socket.on('chain_resolved')`，**2173-2227**）

遍历 `data.results`，每项：`applyCardEffect(result.card, result.caster)`（**2177**）+ `discardPile.push(result.card)`（**2179**）→ 若 `result.temp_data_id` 命中 6 种之一且 `result.caster === gameState.playerId`，弹对应选择 UI：

| `temp_data_id` | 调用 | 行号 |
|---|---|---|
| `'taoyuan_choice'` | `showTaoyuanChoice(result)` | 2189 |
| `'divine_decree'` | `showDivineDecreeChoice(result)` | **2194** 🔴 |
| `'lingqi_choice'` | `showLingqiChoice(result)` | 2200 |
| `'bury_choice'` | `showBuryChoice(result)` | 2206 |
| `'shenji_declare'` | `showShenjiDeclarePrompt(result)` | 2211 |
| `'shield_choice'` | `showRenwangChoice()` | 2216 |

收尾：`updateHandUI()`（**2222**）+ 若 `currentPhase === 'battle'` 则 `enableAttack()`（**2224-2226**，`typeof` 守卫说明该函数可能不存在）。

### 6.4 超时处理（双层）

| 层 | 位置 | 行为 |
|---|---|---|
| 前端 | `2257` handler 内 `setInterval` | 10 秒（`data.countdown`）归零 → 自动 `chain:false` |
| 前端 | `showChainableCards()` **5360-5375** | 30 秒倒计时 → `chain:false`（但该函数是**死代码**，从未调用） |
| 服务端 | `_schedule_chain_timeout` + 代际令牌 | 测试 `test_timeout_pass_advances_window`、`test_chain_timeout_auto_resolves`、`test_chain_timeout_stale_token_noop` 覆盖 |

**矛盾点**：两个前端超时值（10s vs 30s）不一致，且 30s 那条不可达。实际生效的只有 `chain_request` 的 10 秒。

### 6.5 未使用/失效的连锁 UI

- `#chain-prompt-container`（`index.html:274-287`）含 `#chain-timer`/`#chain-cards-list`/`#chain-cancel` —— **完全未被 JS 引用**（JS 用的是动态创建的 `.magic-prompt`），是死 DOM。
- `updateChainUI()`（**5314**）读 `#chain-display`（由 `createMagicCardUI` 注入）—— 但 **`chain_resolved` 与 `magic_chain_updated` 的 handler 都没调用它**（`magic_chain_updated` handler 在 **2168** 确实调了；`chain_resolved` 没有）。因此 `gameState.chain` 实际上**从未被前端填充**（只在 `829` 初始化为 `[]`，全文无 `gameState.chain =` 或 `.push`），`updateChainUI` 永远渲染"当前连锁 (0)"。

---

## 7. 魔法卡目标选择

### 7.1 需要选目标的卡（`needsTargetSelection`，**4033-4044**）

| 卡名 | 选择类型 | 参数 | 作用棋盘 |
|---|---|---|---|
| `冻结` | `area` | `size:3` | `opponent` |
| `探测雷达` | `area` | `size:2` | `opponent` |
| `轰炸` | `line` | — | `opponent` |
| `硫磺火焰` | `continuous` | `length:6` | `opponent` |
| `克苏鲁之眼` | `single` | — | **`self`** |
| `神之宣告` | `own_ships` | `count:2` | — |
| `神威！` | `shenwei` | — | 己方/对方可选 |

其余 34 张卡不需要选目标，直接 `sendMagicCard(index, [])`。

### 7.2 选择器实现

- **区域类**（冻结/探测雷达）：`createBoardAreaPicker()`（**4048**）或 `createSelectionBoard(..., true)`（**4132**）—— 真实棋盘悬停预览 + 点击定位 + 浮动确认条。
  - 关键：`clampStart(mx,my)`（**4056-4059**）把起点钳制到 `[0, 6-size]`，避免越界
  - 浮动条 `div.area-picker-bar` 含 `#area-confirm`（初始 `disabled`，选中后启用，**4076-4077, 4085-4090**）与 `#area-cancel`
  - 防重入：`gameState.selectingOnBoard`（**4049, 4139-4140**）
- **神威！**：`#shenwei-pick-self` / `#shenwei-pick-opp`（**3557, 3566**），先选棋盘再选 3×3 区域，payload 额外带 `board`
- **行/列（轰炸）**：`#toggle-line-dir` / `#confirm-line` / `#cancel-line`
- **连续 6 格（硫磺火焰）**：`isAdjacentToSelected`（**3781**）+ `isConnected`（**3790**）在客户端做连通性预校验，`#confirm-continuous`
- **选己方船（神之宣告/克苏鲁之眼）**：`#confirm-magic-ships`
- **选区清理**：`gameState.selectionCleanup` 存 cleanup 回调，`cleanupPrompt()`（**3524**）/`cleanupAll()` 释放，解决"选区取消残留"

### 7.3 最终 payload 格式（`confirmMagicTarget`，**4376-4429**）

兼容 **5 种** 输入格式，归一化后交给 `sendMagicCard`：

| 输入形态 | 归一化产物 |
|---|---|
| 数组 `[{x,y},...]` | `{target_area:{包围盒}, selected_cells: arr}` |
| `{selected_cells:[...]}` | `{target_area:{包围盒}, selected_cells: arr}` |
| `{target_area:{x1,y1,x2,y2}}` | `{target_area, board?}`（`board` 用于神威！） |
| `{target_line:{...}}` | `{target_line}` |
| `{target_cells:[...]}` | `{target_cells}` |
| `{x,y}` | `{target_area:{x1:x,y1:y,x2:x,y2:y}}` |
| 其它 | 原样透传 |

最终 socket 载荷（**4353-4357**）：
```js
emit('use_magic_card', { room_id, player_id, card, targets: payload })
```
成功后（ack `status==='success'`）：`hand.splice(index,1)` + `discardPile.push(card)` + `updateHandUI()`（**4360-4367**）。

> 注释里提到的 legacy 数组格式（**4388**）说明该函数被反复兼容改造过，是**技术债热点**。

---

## 8. 浮窗 / 拖拽

最近提交 `35a3131 日志窗和聊天窗改回浮动窗，并把日志逻辑重写一遍` 落地了以下结构。

### 8.1 两套拖拽机制

| 函数 | 行号 | 定位方式 | 适用 |
|---|---|---|---|
| `makeFloatingDraggable(el, handle, storageKey)` | **4911** | **改 `left/top`**（要求元素 `position: fixed`），并把 `right/bottom` 置 `auto` | 日志窗、聊天窗 |
| `makeVisualDraggable(el, handle)` | **5008** | **只改 `transform: translate()`**，不改布局流 | 魔法卡预览框 `#magic-card-preview` |

`makeFloatingDraggable` 细节：
- 幂等闸门 `el.dataset.floatDragBound === '1'`（**4912-4913**）
- `KEEP_VISIBLE = 48`（**4915**）：至少保留 48px 在视口内，**修复"窗口拖出屏幕"**
- `place()`（**4924-4933**）三重钳制：`Math.min(Math.max(-(b.w - KEEP_VISIBLE), left), maxLeft)` 等
- `restore()`/`save()`（**4935-4951**）用 `localStorage[storageKey]` 记忆 `{left, top}`（存 `getBoundingClientRect()` 结果）
- 鼠标：`mousedown`(左键) + `mousemove`/`mouseup` 挂在 `window`（**4973-4980**）
- 触摸：`touchstart`/`touchmove`/`touchend`，`{passive:false}` + `preventDefault()`（**4982-4993**）
- 句柄内 `button, a, input, select, textarea` 上的按下**不触发拖动**（**4975, 4984**）
- `window.resize` 时重新 `place()`（**4995-4998**）
- 返回 `{restore, save, restored}`（**5002**）

### 8.2 三个浮窗的接线

| 浮窗 | 元素 | 初始化 | storageKey |
|---|---|---|---|
| 日志窗 | `.log-container`（`index.html:153-159`），句柄 `.log-header` | `initLogDrag()` **5080** | `'game_log_pos'` |
| 聊天窗 | `#in-game-chat-container`（`index.html:186-194`），句柄 `#in-game-chat-header` | IIFE `enableDraggableChat()` **760-763** | `'in_game_chat_pos'` |
| 魔法卡预览 | `#magic-card-preview`，句柄 `.preview-header` | `initPreviewDrag()` **5072** | 无（纯视觉偏移） |

⚠️ **时序风险**：聊天窗拖拽 IIFE 在 **760** 立即执行，但 `makeFloatingDraggable` 定义在 **4911**。因函数声明提升（function declaration hoisting）在全局脚本中可用，此处**不会报错**；但若将来把 `game.js` 改为 module 或 `const` 定义，会立即 ReferenceError。属隐性耦合。

### 8.3 日志逻辑重写要点

| 函数 | 行号 | 行为 |
|---|---|---|
| `GAME_LOG_MAX_ENTRIES` | **997** | `const = 200`，防止长对局卡顿 |
| `clearGameLogs()` | **1000** | 新一局清空（在 `game_state` state=placing_ships 分支被调用，**1822**） |
| `addGameLog(text, type)` | **1005** | **`insertBefore(_, firstChild)`**（最新在最上面，**1010**）→ 裁剪尾部至 200（**1011-1013**）→ `scrollTop = 0`（**1015**） |
| `renderServerLog(entry)` | **1032** | 时间戳 `toLocaleTimeString('zh-CN',{hour12:false})` + 类型徽章 `{attack:'攻击', magic:'魔法', result:'结果', info:'信息'}` + 文本，全部 `escapeHtml` |
| `toggleGameLog()` | **1019** | 切 `.collapsed`，同步按钮文本 `▲/▼` 与 `aria-label`/`title` |
| 服务端日志来源 | `socket.on('game_log')` **2813** | 统一入口，**避免前后端重复**（`2004, 2181` 注释明确说明攻击/魔法日志已改为服务端统一推送） |

### 8.4 移动端适配

`initLogDrag()`（**5084-5087**）：**窄屏（<768px）且从未拖动过**（`!drag.restored`）时，自动调用 `toggleGameLog()` 折叠日志窗，避免挡住棋盘。

**接线已核实（✅ 无问题）**：`initLogDrag()` 定义于 **5080**，唯一调用点在 **`initCardPreview()` 内部第 4868 行**，与 `initPreviewDrag()`（4866）、`setChatVisible(true)`（4869）、`initInGameChatSocket()`（4870）、`initSurrenderBtn()`（4872）同处一个初始化块（4865-4872）。
`initCardPreview()` 本身由 `init()` 在 **5310** 调用，因此调用链完整：
```
init() 5255 → initCardPreview() 4852 → 4866 initPreviewDrag() / 4868 initLogDrag()
                                         4869 setChatVisible(true) / 4870 initInGameChatSocket()
```
> 更正说明：本报告早期版本曾怀疑 `initLogDrag` 无调用点，经 `4868` 行核实为**误报**，日志窗浮窗拖拽与移动端自动折叠**均已生效**。

---

## 9. 断线重连的前端处理

### 9.1 持久化契约

`localStorage` key = **`'battle_active_game'`**（`ACTIVE_GAME_KEY`，**833**），值 = `{room_id, player_id, token}`。

| 函数 | 行号 | 说明 |
|---|---|---|
| `saveActiveGame(roomId, playerId)` | **867** | 读旧值保留 `prev.token` 兜底，写回 |
| `loadActiveGame()` | **878** | `JSON.parse(...)` 带 try/catch，失败返回 `null` |
| `clearActiveGame()` | **873** | 移除 key + `inRoom=false` + `reconnectToken=null` |
| `requestReconnectToken(roomId, playerId)` | **881** | `emit('get_reconnect_token', ..., ack)`，成功则存 token 并 `saveActiveGame` |

### 9.2 三条恢复路径

1. **Socket 重连自动恢复**（`socket.on('connect')`，**1924-1936**）
   → `loadActiveGame()` → 有记录则 `emit('rejoin_room', {room_id, player_id, token})`
2. **服务端主动提示**（`socket.on('resume_game')`，**1937-1949**）
   → `saveActiveGame` + `emit('rejoin_room')`（token 取 `gameState.reconnectToken` → `loadActiveGame().token` 兜底）
3. **进入对局时领取 token**（`game_state` handler，**1776-1780**）
   → `inRoom=true` + `saveActiveGame` + 若 `!reconnectToken` 则 `requestReconnectToken`

### 9.3 快照恢复（`applyRoomSync`，**890-909**）

一次写回：`roomId` / `playerId` / `inRoom=true` / `currentPhase` / `currentAttacker` / `round` / `hand` / `ships` / `myAttacks`(来自 `data.attacks`) / `shenweiHoles` / `fieldMagic`(仅当非空) / `opponentName`，然后 `saveActiveGame`，再隐藏所有其它界面防叠层（**908-909** 注释明确说明"这些元素是模块级 const，必须直接引用"）。

⚠️ 未恢复：`discardPile`、`deck`、`chain`、`selectedCardIndex`、`attacksRemaining`（依赖后续事件）。

### 9.4 对手掉线 UI

- `showOpponentGoneBanner(deadline)`（**847-860**）：`deadline` 缺失时兜底 `Date.now()/1000 + (data.seconds || 30)`（**1959**）
- 创建 `#opponent-gone-banner`，`position:fixed; top:12px; right:12px; z-index:9999`（**843**），每秒 `setInterval` 重算 `剩余 Ns`
- 同时 `gameState.frozen = true`（**849**）→ 所有关键操作前置 `freezeAlert()` 守卫（`836`）：
  `playMagicCard`(4317)、三个阶段按钮(5445/5458/5480) 等
- `hideOpponentGoneBanner()`（**861**）复位 `frozen=false` 并清 interval

### 9.5 失败/取消

| 事件 | 行号 | 行为 |
|---|---|---|
| `game_canceled` | **1967** | 隐藏横幅 + `clearActiveGame()` + 1.5s 后 `resetGame()` |
| `reconnect_warning` | **1974** | `clearActiveGame()` + 2s 后 `resetGame()` |

---

## 10. `index.html` 结构

### 10.1 脚本加载顺序（**`index.html:8, 487-494`**）

```
1. <script src="/static/socket.io.js">        第 8 行   ← 本地打包的 socket.io（191KB）
2. <script src="/static/magic_cards.js">      第 487 行  ← 定义 window.magicCards
3. <script>window.__USERNAME = {{ username|tojson }};</script>   第 489 行  ← 注入变量
4. <script src="/static/game.js">             第 490 行  ← 主逻辑（依赖 2、3）
5. <script src="/static/test_magic.js">       第 492 行  ← 测试脚本（31KB，生产也在加载！）
6. <script src="/static/music_player.js">     第 494 行
```
之后再接一段**内联脚本（497-575）**：`updateOnlineCount()`（轮询 `/api/online_count`，DOMContentLoaded + 每 10 秒，含 `requestAnimationFrame` 数字滚动动画）+ 主题切换（读写 `localStorage['theme']`，切 `.theme-dark`）。

> 🔴 **顺序风险**：`socket.io.js` 在 `<head>`，其余在 `<body>` 尾部，因此 `game.js` 执行时 DOM 已就绪（无 `DOMContentLoaded` 包裹，直接 `document.getElementById`），这是它能工作的原因，也是脆弱点。

### 10.2 注入变量

仅有 **一个**：`window.__USERNAME = {{ username|tojson }};`（**489**），未登录时为 `null`。
被用于：`init()`（**5259**）、`updateCornerNames()`（**181**）、竞态兜底（**278**）。

### 10.3 screen 列表（9 个）

`start-screen`(36)、`custom-room-screen`(58)、`match-success-screen`(112)、`ship-placement-screen`(124)、`rps-screen`(138)、`game-screen`(150)、`lobby-screen`(298)、`leaderboard-screen`(313)、`game-over-screen`(337)。
（含 `.screen` class 者才参与 `switchScreen`；`match-success-screen` 见 §5.1 问题）

### 10.4 模态弹窗列表（8 个，均 `.modal-overlay.hidden`）

`login-modal`(78)、`register-modal`(95)、`profile-modal`(346)、`settings-modal`(385)、`help-modal`(426)、`user-stats-modal`(444)、`match-detail-modal`(453)、`opponent-stats-modal`(464)、`discard-pile-modal`(475) —— 实为 **9 个**。

### 10.5 其它关键容器

- `#particle-canvas`(11) — 粒子背景
- `#game-nav`(13) — 导航栏，`.hide-in-game` 项由 `switchScreen` 控制
- `#game-screen` 内：`.log-container`(153)、`#magic-card-preview`(164)、`#in-game-chat-container`(186)、`.game-info`(195)、`.boards-container`(262)、`#chain-prompt-container`(274，**死 DOM**)、`.discard-pile-btn-row`(290)
- **未在 HTML 中**（由 JS 注入）：`#magic-system` → `#magic-hand`、`#chain-display`（`createMagicCardUI` **5235**）

### 10.6 Jinja2 模板变量

`{% if username %}`(16) / `{{ username }}`(17) / `{{ username|tojson }}`(489)。

---

## 11. 可疑点 / Bug / 坏味道（附行号）

### 11.1 🔴 `getRPSName` 映射反了 —— **确认仍然存在**

`game.js:3320-3327`：
```js
function getRPSName(choice) {
    const names = {
        'rock': '石头',
        'paper': '剪刀',      // ← 应为 '布'
        'scissors': '布'      // ← 应为 '剪刀'
    };
    return names[choice] || choice;
}
```
**证据链**：`index.html:142-144` 中 `data-choice` 为 `rock`/`scissors`/`paper`，按钮文案正确对应 `石头`/`剪刀`/`布`。因此 `paper` 应显示"布"，`scissors` 应显示"剪刀"。**当前实现两者互换**。
**影响**：`rps_result` 提示（**1992**）会显示"你选择了布"当玩家实际点的是剪刀，反之亦然。纯显示 bug，不影响胜负判定（服务端独立计算）。
**修复**：交换 3323/3324 两行的值。

### 11.2 🔴 `showDivineDecreeChoice` 被调用但无定义 —— **确认仍然存在**

`game.js:2194` 调用 `showDivineDecreeChoice(result)`，但在 **整个 `game.js`、`test_magic.js`、`index.html` 中均无此函数定义**（grep 仅 1 处命中，即调用点）。
**影响**：神之宣告经连锁结算返回 `temp_data_id === 'divine_decree'` 且 `caster` 是自己时，抛 `ReferenceError`，**`chain_resolved` handler 中断**——该 `forEach` 后续项不再处理，且 `updateHandUI()`（2222）与 `enableAttack()` 永不执行 → **UI 卡死**。
**关联**：`socket.on('divine_decree_waiting')`(2230)/`'divine_decree_resolved'`(2235) 监听的事件服务端**也不 emit**（见 11.6），三条线索共同指向"神之宣告选择 UI 从未实现"。
**修复**：参照 `showTaoyuanChoice`(2443) 实现，或移除该分支并把选择逻辑改由 `confirm_magic_target` + `temp_data_id` 承担。

### 11.3 🔴 `#effect-indicators` 元素不存在 —— **确认仍然存在**

`game.js:4552`：
```js
document.getElementById('effect-indicators').innerHTML += '<div class="effect-icon" title="百亿补贴">补贴</div>';
```
`#effect-indicators` **在 `index.html` 中不存在，也未被任何 JS 动态创建**（已全文核实 `static/game.js`、`static/test_magic.js`、`static/music_player.js`、`templates/index.html`）。
**影响**：`applyCardEffect` 处理"百亿补贴"时 **`TypeError: Cannot set properties of null`**，同样是 handler 中断。
**修复**：在 `index.html` 加 `<div id="effect-indicators"></div>`，或改为可选链 `?.` 并补充真实容器。

### 11.4 🔴 `socket.emit('line_attack')` 仍存在 —— **确认仍然存在**（`area_attack` 已消失）

`game.js:4499`：
```js
case '轰炸':
    showMessage('轰炸效果生效，目标行/列受到攻击');
    if (gameState.selectedLine) {                       // 4498
        gameState.socket.emit('line_attack', {
            room_id: gameState.roomId, player_id: gameState.playerId, line: gameState.selectedLine
        });
        gameState.selectedLine = null;
    }
    break;
```
- `'area_attack'` —— **已不存在**（0 处命中）✅ 已修复
- `'line_attack'` —— **仍存在**，且 `server.py` 中 0 处命中，**服务端无此事件** 🔴
- 双重死代码：`gameState.selectedLine` **全文只被赋 `null`**（4505），**从未被赋过真实值**，因此 `if` 恒为假，`emit` 永不执行 —— 是"死代码里的死代码"
- 正确的轰炸路径是服务端 `apply_magic_effect` + `target_line`（见 `test_magic_effects.py:38-46`）

### 11.5 🟠 `counter_magic_response` 的 emit —— **已不存在** ✅ 已修复

`game.js` 与 `server.py` 中均 **0 处命中**（SPEC 所述僵尸代码已被清理）。

### 11.6 🔴 新增发现：8 个前端监听的事件，服务端从不 emit

对 `server.py` 全部 41 个 `@socketio.on` handler 与所有 `emit()` 调用点做了穷举比对：

| 前端 `socket.on` | 行号 | 服务端状态 |
|---|---|---|
| `'magic_chain_error'` | 2248 | ❌ 无 |
| `'divine_decree_waiting'` | 2230 | ❌ 无 |
| `'divine_decree_resolved'` | 2235 | ❌ 无 |
| `'discard_pile_updated'` | 2242 | ❌ 无 |
| `'lobby_update'` | 2754 | ❌ 无 |
| `'lobby_joined'` | 2767 | ❌ 无 |
| `'lobby_left'` | 2773 | ❌ 无 |
| `'match_found'` | 2779 | ❌ 无 |

同时前端 `emit` 的两个事件服务端也无 handler：
| 前端 `emit` | 行号 | 服务端 |
|---|---|---|
| `'join_lobby'` | 2991 | ❌ 无 handler |
| `'leave_lobby'` | 2997 | ❌ 无 handler |

**影响**：**整个大厅（Lobby）功能是空壳** —— `joinLobbyMatch`/`leaveLobbyMatch` 发出的事件无人接收，`lobby_update` 永不推送，`updateLobbyDisplay()`（**2977-2983**）本身也是空实现并自带注释承认"暂时不做额外请求"。
**次级影响**：`discard_pile_updated` 缺失意味着弃牌堆只能靠手点 `#view-discard-pile` → `get_discard_pile`(5176) 拉取，不会实时更新。

### 11.7 🟠 `resetGame()` 的赋值目标疑似错误

`game.js:3414-3470` 中 **3422** 处 `gameState = { ... }`（裸标识符）。因 `game.js` 是经典脚本（非 module），裸 `gameState` **就是** `window.gameState` 的引用赋值目标，故**实际行为正确**。但：
- 若将来改为 ES module，`gameState` 会变成模块作用域变量，`window.gameState` 将不再更新 → 全局引用全部失效
- 与 `804` 的 `window.gameState = {...}` 写法不一致，属**风格地雷**

### 11.8 🟡 `showChainableCards()` 是死代码

`showChainableCards()`（**5331-5396**）**全项目无调用点**。它依赖 `createCardElement`（未见于函数声明列表，很可能也不存在）和 `#chainable-cards`、`#confirm-chain`、`#cancel-chain`、`#chain-time` 等**均未创建的 DOM id**。它是"连锁 UI 早期方案"的遗留，与当前基于 `chain_request` 动态弹窗的方案重复。

> 补充：`initLogDrag()` 曾疑似无调用点，经核实**已在 `4868` 被 `initCardPreview()` 正确调用**，见 §8.4 更正说明。

### 11.9 🟠 `#chain-prompt-container` 是死 DOM

`index.html:274-287` 静态定义了 `#chain-timer`/`#chain-cards-list`/`#chain-cancel`，但 JS 全部用**动态创建的 `.magic-prompt`**（**2259**）。该 DOM 与 `style.css` 中的样式均为死重量。

### 11.10 🟠 `gameState.chain` 前端永不填充

`gameState.chain` 仅在 **820** 初始化为 `[]`，全文**无任何赋值或 push**。因此 `updateChainUI()`（**5314**）永远输出"当前连锁 (0)"。`chain_resolved` handler（**2173**）也没有调用 `updateChainUI`。前端连锁可视化实际**不可用**。

### 11.11 🟡 重复定义函数

| 函数 | 定义 1 | 定义 2 | 说明 |
|---|---|---|---|
| `showUserStats` | **1084** | **1258** | 后者覆盖前者；两者版本内容不同（后者可能更完整），前者为死代码 |
| `showMatchDetail` | **1184** | **1358** | 同上 |
| `showOpponentStats` | **1783**（嵌套在 `game_state` handler 内） | **1811** 导出 `window.showOpponentStats` | 嵌套定义 + 全局导出，是"修复作用域崩溃"的补丁式写法 |

### 11.12 🟡 `switchScreen` 漏掉 `match-success-screen`

`2911` 的数组只有 8 项，缺 `matchSuccessScreen`。导致 `switchScreen(matchSuccessScreen)` 无法清除其它 screen 的 `active`。当前靠 `game_state` handler 手动 `classList.remove('active')`（**1736**）绕过。

### 11.13 🟡 `gameState` 字段声明不全

`currentAttacker`、`round`、`currentMagicCard`、`currentCardIndex`、`selectingOnBoard`、`selectionCleanup`、`selectedLine`、`noMagicCardsThisTurn`、`attacks`、`remainingShips`、`opponentRemainingShips` 共 **11 个字段**首次使用即隐式创建（详见 §1.2）。

### 11.14 🟡 只写不读的僵尸状态

- `gameState.selectedLine` —— 仅 4505 置 `null`，无读取真实值处
- `gameState.noMagicCardsThisTurn` —— 仅 4449 置 `true`，前端无任何地方消费；无中生有"本回合双方无法获得魔法卡"的约束**完全依赖服务端**

### 11.15 🟡 生产环境加载测试脚本

`index.html:492` 在生产页面加载 `static/test_magic.js`（31KB），内含 `test_*` 风格的调试工具。服务端也确实注册了 8 个 `test_*` socket 事件（`test_win_game`/`test_lose_game`/`test_add_all_magic_cards` 等）。**这是严重的安全/健壮性隐患**：任何客户端可调用 `test_win_game` 直接获胜。**强烈建议在非 debug 模式下移除。**

### 11.16 🟡 超时值不一致

连锁响应超时：`chain_request` handler 用 `data.countdown || 10`（**2287**）→ 10 秒；`showChainableCards` 用 30 秒（**5360**）。后者是死代码，但两处不一致反映规格漂移。

### 11.17 🟡 XSS 防护不完整

`escapeHtml()`（**746**）存在且被用于聊天（**741**）、日志（**1039**）、排行榜（**2966**）、战绩（**1143**）、卡牌渲染（**5106-5108**）。
但 `applyCardEffect` 中大量 `showMessage('...')` 为**纯字面量**（安全），而 `'magic_applied'`（**2400**）用模板串拼 `result.card.name` 与 `result.message` **未经 escapeHtml**。若卡名/消息可能被用户输入影响，存在注入面（当前卡名来自服务端常量表，风险低，但不符合防御性编程）。

### 11.18 🟡 聊天窗拖拽的声明顺序耦合

**760-763** 的 IIFE 调用 **4911** 的 `makeFloatingDraggable`，依赖函数声明提升跨越 4000+ 行。可工作但脆弱（见 §8.2）。

### 11.19 🟡 `initGameBoards()` 被 `updateTurnIndicator()` 全量重绘

`3316`：每次回合切换都 `initGameBoards()` 重建 72 个 DOM 节点。若高频触发会有性能与**事件监听残留**风险（未见显式 `removeEventListener`，依赖 `innerHTML = ''` 释放）。

---

# B. 测试分析

## 12. 各测试文件详解

### 12.1 `tests/test_chain_engine.py`（275 行，20 个测试）

**主题**：连锁状态机 + 无效化引擎（对应提交 `ce9d699`）。
**手法**：
- `@pytest.fixture(autouse=True) def events(monkeypatch)`（**22-33**）：`monkeypatch.setattr(server, 'emit', fake_emit)` 捕获所有广播；并 stub `socketio.start_background_task` **阻止真实后台计时器**（关键，避免测试挂起）
- `@pytest.fixture def room`（**36-40**）：`make_room()` 构造真实 `GameRoom`，teardown 时 `room_manager.rooms.pop`
- 直接构造 `server.ChainItem(caster, card, targets, order)` 预置连锁栈，调 `server.resolve_chain(room)` 断言
- 走后门入口：`play()`（**69**）直调 `server.handle_use_magic_card`；`respond()`（**79**）直调 `server.chain_response`

**关键测试**：

| 测试 | 行号 | 断言目的 |
|---|---|---|
| `test_chain_resolves_lifo_and_negated_skips` | 91 | 失灵！栈顶先出（LIFO）、标记下方项、`negated_skip`、被康卡**不进历史** |
| `test_chain_without_negation_applies_effect` | 112 | 无无效化卡时效果正常落（轰炸击沉 2 船） |
| `test_shiling_negates_adjacent_not_stale_history` | 126 | **失灵只康紧邻下方**，不误伤 `magic_history` 里的旧牌（回归"读全场 history"的老 bug） |
| `test_shiling_cannot_negate_kanpo` | 141 | 失灵康不动看破：`results[0].success is False` + 看破仍置 `magic_blocked` |
| `test_shiling_cannot_negate_gabriel` | 154 | 失灵康不动加百列之光 |
| `test_negated_field_card_goes_to_discard` | 168 | 场地被康 = "贴了再拆"，`field_magic is None` 且进弃牌堆（**不凭空消失**） |
| `test_gabriel_negates_adjacent_and_field` | 179 | 加百列**同时**康下方项 + 拆当前场地 |
| `test_play_opens_window_for_opponent` | 196 | 出牌后 `chain_waiting is True`、`chain_window == P2` |
| `test_self_chain_after_opponent_passes` | 205 | **自连锁**：对方放弃后窗口回到自己，可追加第二张速阶3 |
| `test_two_consecutive_passes_resolve` | 222 | **连续两次放弃**才结算（`chain == []`、`chain_waiting is False`） |
| `test_cannot_play_while_window_open` | 234 | 窗口未关不能另开新牌 → `status == 'error'` |
| `test_chain_response_removes_card_from_hand` | 243 | 连锁打出的速阶3 必须**移出手牌 + 进弃牌堆** |
| `test_timeout_pass_advances_window` | 256 | 超时视为放弃并顺延；stub `time.sleep` + 手动触发后台任务 |

### 12.2 `tests/test_disconnect_and_eden_shenji.py`（194 行，10 个测试）

**主题**（文件头注释）：伊甸园攻击次数结算时机 + 神机妙算宣言流程（2026-09-07），外加桃园/取消匹配/教皇/人机布船。
**手法**：`monkeypatch.setattr(server, 'emit', ...)` 捕获广播；构造 `Player(..., user_id=pid)`；直接调内部函数 `server._recalc_attacker_attacks(room)`、`server._ai_place_ships`。

| 测试 | 行号 | 断言目的 |
|---|---|---|
| `test_eden_recalc_on_rps_winner` | 32 | 伊甸园在场时，准备阶段攻击次数 = `6 - 船数`（4 船 → 2） |
| `test_eden_no_attacks_when_full_ships` | 46 | **6 船时应为 0 次**（回归"先给 6 次再变 0"的老 bug） |
| `test_eden_refresh_when_played_in_prep` | 60 | 准备阶段贴伊甸园 → 立即刷新为 `6-n` 并广播 |
| `test_non_eden_uses_ship_count` | 73 | 无伊甸园时按剩余船数（不受影响） |
| `test_shenji_requests_declare_when_no_prediction` | 87 | 未宣言 → 返回 `temp_data_id='shenji_declare'` + 写 `pending_shenji.caster` |
| `test_shenji_confirm_applies_prediction` | 95 | `handle_confirm_shenji_declare` 写 `effect_flags.prediction`、清 `pending_shenji`、建 `prediction_initial_{P1}` |
| `test_shenji_apply_with_existing_prediction` | 111 | 老路径兼容：已有 prediction 时直接落效 |
| `test_taoyuan_result_carries_cards` | 122 | 桃园结果**随附抽到的卡**（客户端无需二次请求） |
| `test_cancel_match_by_sid` | 133 | **按当前连接 sid 出队**（回归"登录用户匹配后无法取消"）；构造 3 组队列验证精确删除 |
| `test_papal_recalc_zero_at_prep` | 148 | 教皇旨意下准备阶段攻击次数直接为 0 |
| `test_bury_result_carries_cards` | 162 | 明智埋葬结果随附手牌 |
| `test_ai_placement_same_rules_as_human` | 173 | AI 布 6 艘**单格船**、坐标不重叠、在 0-5 内 |
| `test_ai_placement_respects_max_ships` | 187 | `max_ships=3` 时 AI 只布 3 艘 |

### 12.3 `tests/test_auth_spoof.py`（116 行，11 个测试）

**主题**：事件鉴权，防伪造 `player_id`。
**手法**：纯函数测试 —— 直接调 `server._identity_check(room, player, server_pid=..., sid=...)`；`_identity_ok` 用 `types.SimpleNamespace` 伪造 `server.session` / `server.request`（**103-104, 113-114**）来模拟 Flask 请求上下文。

| 测试 | 行号 | 断言目的 |
|---|---|---|
| `test_logged_user_matches_passes` | 33 | 登录用户身份一致 → 通过 |
| `test_logged_user_acting_as_other_rejected` | 38 | 登录用户自称他人 → **拒绝**（核心防伪造） |
| `test_match_room_sid_key_convention_ok` | 45 | 匹配房 key = 入队 sid；登录用户声称**本连接** sid 通过，他人 sid 拒绝 |
| `test_match_room_guest_ok` | 56 | 游客匹配房：本 sid 通过、他人拒绝 |
| `test_guest_sid_match_passes` | 65 | 游客 sid 一致通过 |
| `test_guest_sid_mismatch_rejected` | 70 | 游客用他人连接 sid → 拒绝 |
| `test_unknown_player_rejected` | 76 | 幽灵玩家无论何种身份都拒绝 |
| `test_none_room_rejected` | 82 | `room=None` → 拒绝（防崩溃） |
| `test_no_context_valid_member_ok` | 88 | **无 Flask 上下文**直调不崩溃且成员校验通过（保证单元测试路径可用） |
| `test_no_context_unknown_player_rejected` | 94 | 同上，幽灵玩家拒绝 |
| `test_wrapper_logged_user_spoof_rejected` | 99 | 包装层：模拟真实上下文，p2 自称 p1 → 拒绝 |
| `test_wrapper_guest_sid_mismatch_rejected` | 109 | 包装层：游客 sid 不匹配 → 拒绝 |

### 12.4 `tests/test_all_magic_cards.py`（1097 行，**最大文件**）

**主题**：**逐卡覆盖**全部 43 张卡的 `apply_magic_effect` 行为。
**手法**：
- `@pytest.fixture(autouse=True) def events`（19-29）：捕获 emit + **阻止后台任务**
- `@pytest.fixture def room`（31）：构造 + teardown 清理
- 辅助：`ship(*cells)`（52）构造 `PlayerShip`；`card(name)`（56）构造 `MagicCard`；`apply(room, caster, name, target)`（60）；`give_deck`（64）/`give_hand`（68）/`attack(room, attacker, x, y)`（72）
- 断言级别：**直接检查 `room` 对象内部状态**（`remaining_ships`/`ships`/`effect_flags`/`game_effects`/`magic_hand`），而非仅看返回值

**按卡分节的关键测试**（节标题见文件 79-1080 行）：

| 卡 | 测试函数（行号） |
|---|---|
| 失灵！ | `test_shiling_negates_opponent_last_magic`(82)、`fails_without_target`(91)、`cannot_negate_gabriel_light`(96)、`integration_history_written`(104) |
| 溅射 | `damages_four_neighbors`(119)、`requires_prior_hit`(134)、`bypasses_invincible`(142)、`shield_blocks_once`(153) |
| 雷达子弹 | `reveals_eight_cells`(168)、`requires_hit`(181) |
| 越战越勇 | `requires_sunk`(190)、`sets_flag`(197)、`grants_one_extra_attack`(204) |
| 余音绕梁 | `forced_kill_next_attacks`(218) |
| 神威！ | `single_ship_dies`(235)、`multiple_ships_excluded`(245)、`self_board_only_excludes`(257)、`hole_blocks_attack`(269)、`wipes_all_opponent_ships_wins`(280)、`exclusion_triggers_linkage`(290) |
| 增援 | `waits_for_placement`(304)、`can_be_cancelled`(320)、`rejects_attacked_cell`(329)、`full_board_rejected`(339) |
| 恶魔契约 | `binding_on_attack`(349) |
| 八方来财 | `draw_on_ship_change`(367) |
| 平等条约 | `negates_ship_change`(382)、`fails_without_change`(395) |
| 禁忌果实 | `blocks_normal_magic`(403) |
| 硫磺火焰 | `kills_six_cells`(415)、`requires_exactly_six_cells`(429)、`ship_count_correct`(434) |
| 百亿补贴 | `subsidy_on_own_ship_lost`(445) |
| 看破！ | `sets_block_flag`(459)、`blocks_opponent_magic`(464) |
| 冻结 | `marks_ships_frozen`(479) |
| 轰炸 | `row_kills_intersecting_ships`(491)、`column`(501) |
| 探测雷达 | `reveals_2x2`(511) |
| 伊甸园 | `attack_count_6_minus_n`(524) |
| 神之宣告 | `option1_kill_opponent_ship`(540)、`option2_skip_opponent_turn`(554)、`requires_two_ships`(563) |
| 五险一金 | `plus_three_when_no_damage`(573)、`fails_after_damage`(582) |
| 绝处逢生 | `requires_three_ships`(591)、`keeps_one_ship_and_wins_on_kill`(597) |
| 死者苏生 | `revives_last_sunken`(619)、`fails_without_sunken`(638)、`revived_ship_can_be_sunk_again`(643) |
| 疗愈 | `placement_requires_sunken`(665)、`revives_up_to_two`(674) |
| 桃园结义 | `draw_n_and_assign`(695) |
| 无中生有 | `draw_two_and_lock_draw`(719) |
| 饮血 | `draw_on_kill`(733) |
| 极限增援 | `registers_two_turn_check`(748) |
| 教皇旨意 | `zero_attacks`(759) |
| 无暇圣心 | `registered`(772)、`interrupted_by_sink`(779) |
| 盗亦有道 | `steals_opponent_last_card`(791)、`fails_when_own_last`(799) |
| 克苏鲁之眼 | `mutual_reveal`(808) |
| Freezing！ | `skips_opponent_turn`(823)、`fails_after_damage`(831) |
| 回光返照 | `reset_board_and_lose_on_damage`(840)、`requires_first_player`(861) |
| 明智埋葬 | `bury_and_draw`(870)、`fails_empty_hand`(888) |
| 火力全开 | `double_attacks_in_battle_phase`(896) |
| 加百列之光 | `negates_last_and_field`(911) |
| 仁王之盾 | `shields_up_to_three`(924) |
| 钢筋铁骨 | `sacrifice_then_invincible`(950)、`requires_two_ships`(960) |
| 神机妙算 | `declare_prediction`(969)、`requires_declaration`(981) |
| 灵气复苏 | `adjust_ship_count`(991) |
| 败者食尘 | `restart_keep_hands`(1016) |
| 通用/场地 | `field_magic_replacement`(1043)、`field_card_real_flow_crash`(1049) |
| 阶段规则 | `speed3_playable_anytime`(1061)、`speed12_require_own_turn`(1067)、`no_magic_in_end_phase`(1075) |
| **前后端一致性** | `test_frontend_card_data_matches_backend`(**1083**) |

### 12.5 `tests/test_magic_effects.py`（58 行，3 个测试）

**主题**（文件头）：溅射 / 轰炸 / 硫磺火焰 返回 `affected_positions` 的回归测试（"修复旧夹具"）。
**手法**：最小化 —— 只 stub `emit`，直接调 `server.apply_magic_effect`。

| 测试 | 行号 | 断言目的 |
|---|---|---|
| `test_splash_returns_affected_positions` | 26 | 溅射对 (3,3) 周围杀伤，返回的 `affected_positions` 含 (3,2) |
| `test_bomb_returns_affected_positions` | 38 | 轰炸 row index=2 返回 `success`（**注意：未断言 positions 内容**，见 §15） |
| `test_sulfur_returns_affected_positions` | 49 | 硫磺火焰 6 格，返回含 (2,0) |

### 12.6 `tests/test_magic_resolution_flows.py`（359 行，14 个测试）

**主题**（文件头）：魔法卡**跨回合结算闭环**（极限增援/无暇圣心/神机妙算/跳过回合/教皇旨意）。
**手法**：
- `new_round_cycle(room)`（**47-53**）—— **关键辅助**：让双方各走完 end 阶段以触发 `end_turn` 的 `next_index == 0` 新大回合分支。这是测试"跨回合"效果的核心技巧
- `end_turn(room, pid)`（43）直接调 `server.end_turn({'room_id','player_id'})`
- `monkeypatch.setattr(server.time, 'sleep', lambda s: None)` + `start_background_task` 立即执行（**329-331**），把异步超时变同步

| 测试 | 行号 | 断言目的 |
|---|---|---|
| `test_jixian_full_resolution_fewer_ships_wins` | 59 | 极限增援：第 1 大回合仅倒计时（`remaining_turns` 2→1），第 2 大回合船少的 P2 获胜 |
| `test_wuxia_shengxin_full_resolution_caster_wins` | 80 | 无暇圣心：两回合无伤害 → 施法者 P1 获胜 |
| `test_wuxia_shengxin_no_win_when_damaged` | 92 | `no_damage=False` 时**不推进倒计时**（保持 2），不结算 |
| `test_shenji_end_phase_restore_predicted_loss` | 106 | 神机妙算预言命中（预测 1、实减 1）→ 船数恢复、`sunken_ships` 清空、`effect_flags.prediction` 归 0 |
| `test_shenji_prediction_miss_keeps_loss` | 127 | 预言失准（预测 2、实减 1）→ 损失保留 |
| `test_freezing_full_skip_back_to_caster` | 144 | Freezing！跳过对方整回合，`end_turn` 后**回到 P1 准备阶段** |
| `test_shenzhi_option2_full_skip` | 156 | 神之宣告选项 2 同样跳过对方回合 |
| `test_jiaohuang_papal_attack_two_hits` | 172 | 教皇旨意弃 1 张卡攻击同一格两次 → 2 格船被击沉、手牌清空 |
| `test_jiaohuang_papal_attack_requires_card` | 189 | 无手牌时 `papal_attack` → `status == 'error'` |
| `test_taoyuan_single_ship_gives_self` | 202 | n=1 时优先给自己；经 `confirm_magic_target(temp_data_id='taoyuan_choice')` 闭环验证 |
| `test_huiguang_skips_own_battle_phase` | 224 | 回光返照：`current_phase == 'end'` + `needs_reset is True` |
| `test_baizhe_then_place_ships_flow` | 235 | 败者食尘：`state == 'placing_ships'`、双方 `max_ships` 互换(2/1)、**手牌保留** |
| `test_dongjie_reduces_attack_count_and_thaws` | 253 | 冻结：3 船全冻 → 攻击次数 0；跨 2 个大回合后第 3 回合解冻（`frozen is None`） |
| `test_shenwei_excluded_ships_return_next_round` | 286 | 神威！：3 船除外 2 → 下大回合全部回归、`excluded_ships` 清理 |
| `test_juechu_keeps_hand_and_blocks_other_cards` | 309 | 绝处逢生：**不再清空手牌**（回归）+ 生效回合内 `can_play_magic_card` 为 False；清 `effect_flags` 后解除 |
| `test_chain_timeout_auto_resolves` | 327 | 服务端超时兜底：自动结算、`chain_waiting` 清、船被击沉 |
| `test_chain_timeout_stale_token_noop` | 347 | **代际令牌失配的旧定时器不重复结算**（幂等性回归） |

---

## 13. 实际运行测试结果

```
$ cd C:\Users\Administrator\Documents\ds-harness-desktop\WorkSpace\battle_ship1.0
$ python -m pytest tests/ -q
........................................................................ [ 51%]
.....................................................................    [100%]
141 passed in 0.53s
```

### 结论

| 指标 | 值 |
|---|---|
| **通过** | **141** |
| **失败** | **0** |
| **错误** | **0** |
| 跳过 / xfail | 0 |
| 耗时 | **0.53 s** |
| pytest | ✅ 已安装 |

**补充观察**：
- 全套 141 个测试 **0.53 秒**跑完，说明全部是**纯内存单元测试**（无网络、无真实 socket、无 DB），且 `start_background_task` 被统一 stub。
- 此前存在的 `tools/remove_xfail_markers.py`（29 行）印证历史上曾有 xfail 标记，现已全部转为**必须通过**，即 141 个全是硬断言。
- `tests/e2e_magic_report.json`（420 行）与 `tools/e2e_magic_cards.py`（327 行）、`tests/screenshots/*.jpg`（8 张）表明曾做过 E2E/截图验证，但这些**不参与 `pytest tests/`**。

---

## 14. 魔法卡前后端数据一致性

### 14.1 比对结果：**完全一致 ✅**

用 Python 提取 `magic_cards.js` 中 43 个对象字面量并与 `magic_card.json` 逐字段比对：

| 指标 | `magic_card.json` | `magic_cards.js` | 一致？ |
|---|---|---|---|
| 总条目数 | **43** | **43** | ✅ |
| 唯一卡名数 | **41** | **41** | ✅ |
| 字段集合 | `name, speed, type, description` | `name, speed, type, description` | ✅ |
| **逐条目字段差异** | — | — | **0 / 43** |
| 名称顺序 | — | — | ✅ 完全相同 |
| 完整四元组 `(name, speed, type, description)` | — | — | ✅ 完全相同 |

**速阶分布**：
| speed | 数量 |
|---|---|
| 1 | **13** |
| 2 | **15** |
| 3 | **15** |
| **合计** | **43** |

**类型分布**：`普通` **39** / `场地` **4**

**唯一重复卡名**：`失灵！` × **3**（索引 0、1、2），三张条目内容完全相同。
（其余 40 个卡名各 1 张，41 = 40 + 1）

### 14.2 完整卡表（按文件顺序）

| # | 卡名 | 速阶 | 类型 |
|---|---|---|---|
| 0 | 失灵！ | 3 | 普通 |
| 1 | 失灵！ | 3 | 普通 |
| 2 | 失灵！ | 3 | 普通 |
| 3 | 溅射 | 2 | 普通 |
| 4 | 雷达子弹 | 2 | 普通 |
| 5 | 越战越勇 | 2 | 普通 |
| 6 | 余音绕梁 | 1 | 普通 |
| 7 | 神威！ | 2 | 普通 |
| 8 | 增援 | 3 | 普通 |
| 9 | 恶魔契约 | 2 | **场地** |
| 10 | 八方来财 | 3 | 普通 |
| 11 | 平等条约 | 3 | 普通 |
| 12 | 禁忌果实 | 1 | **场地** |
| 13 | 硫磺火焰 | 2 | 普通 |
| 14 | 百亿补贴 | 3 | 普通 |
| 15 | 看破！ | 2 | 普通 |
| 16 | 冻结 | 2 | 普通 |
| 17 | 轰炸 | 2 | 普通 |
| 18 | 探测雷达 | 2 | 普通 |
| 19 | 伊甸园 | 1 | **场地** |
| 20 | 神之宣告 | 3 | 普通 |
| 21 | 五险一金 | 2 | 普通 |
| 22 | 绝处逢生 | 3 | 普通 |
| 23 | 死者苏生 | 3 | 普通 |
| 24 | 疗愈 | 3 | 普通 |
| 25 | 桃园结义 | 1 | 普通 |
| 26 | 无中生有 | 1 | 普通 |
| 27 | 饮血 | 2 | 普通 |
| 28 | 极限增援 | 1 | 普通 |
| 29 | 教皇旨意 | 1 | **场地** |
| 30 | 无暇圣心 | 1 | 普通 |
| 31 | 盗亦有道 | 3 | 普通 |
| 32 | 克苏鲁之眼 | 2 | 普通 |
| 33 | Freezing！ | 2 | 普通 |
| 34 | 回光返照 | 1 | 普通 |
| 35 | 明智埋葬 | 2 | 普通 |
| 36 | 火力全开 | 1 | 普通 |
| 37 | 加百列之光 | 3 | 普通 |
| 38 | 仁王之盾 | 1 | 普通 |
| 39 | 钢筋铁骨 | 3 | 普通 |
| 40 | 神机妙算 | 3 | 普通 |
| 41 | 灵气复苏 | 1 | 普通 |
| 42 | 败者食尘 | 1 | 普通 |

### 14.3 一致性由测试守护

`tests/test_all_magic_cards.py:1083` `test_frontend_card_data_matches_backend` 用正则
```python
r'name:\s*"([^"]+)",\s*speed:\s*(\d+),\s*type:\s*"([^"]+)"'
```
提取前端三元组并与后端 JSON 的 `(name, speed, type)` 序列做 `==` 断言，**包含顺序**。当前通过。

> ⚠️ 该测试**不校验 `description`**，而 `description` 是玩家可见的核心信息。见 §15。

---

## 15. 测试覆盖盲区 与 测试代码本身的问题

### 15.1 覆盖盲区

#### A. 前端零自动化测试 🔴
全部 141 个测试都在 **Python 服务端**。`static/game.js`（5625 行）、`test_magic.js`（744 行）**没有任何单元测试或 E2E 断言**。
直接后果 —— §11 中列出的**所有前端 bug 全部逃过测试**：
- `getRPSName` 映射反（3320）
- `showDivineDecreeChoice` 未定义（2194）
- `#effect-indicators` 不存在（4552）
- `emit('line_attack')` 无对应 handler（4499）
- 8 个监听不存在服务端事件（§11.6）
- `initLogDrag()` 未被调用（§11.8）

#### B. 前端↔后端事件契约无测试 🔴
没有测试断言"前端 `socket.on(X)` 的事件名必须在 `server.py` 中有 `emit('X')`"，反之亦然。这是 §11.6 那 10 个不匹配能长期潜伏的根本原因。**建议补一个静态契约测试**：解析 `game.js` 的 `socket.on('...')` 与 `server.py` 的 `emit('...')` / `@socketio.on('...')` 做集合比对。

#### C. DOM id 契约无测试 🟠
`#effect-indicators`（4552）这类"引用了不存在元素"的问题，本可用一个静态检查（或 Playwright 冒烟）拦住。

#### D. `description` 字段未做一致性守护 🟠
`test_frontend_card_data_matches_backend`（1083）只比 `(name, speed, type)`。当前 `description` 恰好一致，**但无回归保护**，未来单边改动会静默漂移。

#### E. 断线重连的服务端路径覆盖薄 🟠
`test_disconnect_and_eden_shenji.py` 的文件名含 "disconnect"，但实际**没有任何测试覆盖 `rejoin_room` / token 校验 / 宽限期冻结 / `room_sync` 快照**。仅测了"取消匹配按 sid 出队"。前端 §9 的整套重连逻辑**完全未验证**。

#### F. 前端渲染分支未覆盖（服务端侧）🟠
例如 `chain_resolved` 中 `temp_data_id === 'divine_decree'` 分支在服务端无测试（`test_all_magic_cards` 只测了 `apply_magic_effect` 的状态变化，未测"客户端如何消费"），因此前端崩溃点（§11.2）无人发现。

#### G. 并发/竞态无覆盖 🟡
无测试模拟"两面同时出牌""超时与手动响应竞争"（部分由 `test_chain_timeout_stale_token_noop` 代际令牌覆盖，属良好实践，但仅此一例）。

#### H. 安全测试仅覆盖身份伪造 🟡
`test_auth_spoof.py` 只测 `_identity_check`。**`test_*` 系列 socket 事件**（`test_win_game` / `test_lose_game` / `test_add_all_magic_cards` 等 8 个，可在生产页面调用）**完全没有鉴权测试**，而 `index.html:492` 还在生产加载 `test_magic.js`。**这是最高危的盲区。**

### 15.2 测试代码本身的问题

#### 1. `test_magic_effects.py:38-46` —— 断言强度不足 🟠
```python
def test_bomb_returns_affected_positions():
    ...
    res = server.apply_magic_effect(room, P1, MagicCard('轰炸'), {'target_line': {'type':'row','index':2}})
    assert res.success is True        # ← 只断言 success
```
函数名与文件头都声称测"**returns affected_positions**"，但**根本没有断言 `affected_positions` 的内容**（对比 `test_splash`(34-35) 和 `test_sulfur`(58) 都断言了）。**测试名与断言不符**，该测试对 `affected_positions` 回归无任何保护力。等价于空测试。

#### 2. `test_all_magic_cards.py:1088-1090` —— 硬编码相对路径 🟠
```python
backend = read_json('./static/magic_card.json')
with open('./static/magic_cards.js', encoding='utf-8') as f:
```
依赖 **CWD 必须是项目根**。若从别处运行 `pytest`（如 IDE 指定 rootdir、或 `python -m pytest tests/` 从父目录），该测试会因 `FileNotFoundError` 失败/报错。应用 `pathlib.Path(__file__).parents[1]` 定位。其余 140 个测试无此问题（纯内存），所以**只有这 1 个测试对 CWD 敏感**——这也解释了为何从项目根运行时全绿。

#### 3. 全局 `simulate`/`emit` monkeypatch 覆盖不全 🟡
各文件各自定义 `fake_emit`，签名 `(event, data, to=None, room=None)`。若 `server.py` 中某处用关键字参数以外的方式调用 `emit`（如位置传 `namespace`），stub 会 `TypeError`。当前无失败说明签名匹配，但属**隐式契约**。

#### 4. `test_disconnect_and_eden_shenji.py:32` —— 测试名与内容不符 🟡
`test_eden_recalc_on_rps_winner` 名字含 "rps"，但函数体**没有做任何猜拳动作**：先设 `room.state='rock_paper_scissors'`（36），随即在 **39** 行覆盖为 `'attacking'`、**40** 行设 `current_phase='preparation'`，然后直接调 `_recalc_attacker_attacks`。第 36 行的赋值是**无效行（dead assignment）**，"rps winner"路径并未真正被模拟。属**误导性测试**。

#### 5. `test_disconnect_and_eden_shenji.py:37` —— 危险的列表乘法 🟡
```python
room.players[P1].ships = [PlayerShip(positions=[], hits=[])] * 4
```
`[obj] * 4` 创建的是 **4 个指向同一对象的引用**，不是 4 个独立对象。此处测试恰好不修改元素故通过，但**若未来测试改成逐个改船属性，会因共享引用产生假通过/假失败**。同样写法见 **53, 66, 79, 155** 行。应改为 `[PlayerShip(...) for _ in range(4)]`。

#### 6. `test_magic_resolution_flows.py:47-53` —— `new_round_cycle` 依赖脆弱 🟡
```python
def new_round_cycle(room):
    room.current_attacker = P1
    room.current_phase = 'end'
    end_turn(room, P1)
    room.current_phase = 'end'   # 注释：当前攻击者已是 P2
    return end_turn(room, P2)
```
`end_turn` 不校验 `player_id == current_attacker` 的一致性（测试里 `end_turn(room, P2)` 传 P2，但依赖上一步已把 attacker 切成 P2）。**该辅助函数内联了服务端的回合推进假设**，若服务端 `end_turn` 改变校验（例如新增身份校验），这批测试会集体以难以诊断的方式失败。

#### 7. `test_chain_engine.py:99` / `test_magic_effects.py:34` —— 依赖"不写 `success`"的隐式契约 🟡
多处用 `assert getattr(results[0], 'negate_target', False) is True`（`test_chain_engine.py:103, 105, 138`）**通过 `getattr` 默认值探测动态属性**。这意味着这些属性是运行时附加的，**若无 IDE/类型提示保护，改名即静默失效**（默认 `False` 让断言"恰好"失败，尚可察觉，但属脆弱设计）。

#### 8. 测试对内部私有函数直接调用 🟡
`server._recalc_attacker_attacks`（`test_disconnect:42,56,81,158`）、`server._schedule_chain_timeout`（`test_chain_engine:270`、`test_magic_resolution_flows:340,357`）、`server._ai_place_ships`（`test_disconnect:178,193`）、`server._identity_check`/`_identity_ok`（`test_auth_spoof` 全文）。
**利**：定位精准、跑得快。**弊**：与实现强耦合，重命名/重构私有函数会导致大面积测试改动，属**测试与实现耦合过紧**。

#### 9. 后台任务 stub 的两种不一致写法 🟡
- `test_chain_engine.py:31-32`：`lambda target, *a, **k: None`（**不执行**）
- `test_magic_resolution_flows.py:330-331` 与 `347-351`：`lambda target, *a, **k: target(*a)`（**立即执行**）

两种策略各有用途（前者"不让计时器跑"，后者"把异步变同步"），但同一项目内混用且无注释说明，**新读者容易误判**。建议统一封装成 fixture。

#### 10. 缺失 fixture 复用 🟡
`make_room()` / `ship()` / `card()` / `give_hand()` 在 **4 个测试文件里重复定义**（`test_chain_engine.py:43,57,61,65`；`test_magic_resolution_flows.py:20,35,39`；`test_all_magic_cards.py:38,52,56,68`；`test_disconnect_and_eden_shenji.py:22,18`）。应提取到 `conftest.py`。

#### 11. 未使用 import 🟡
多处 import 了未使用的符号，例如 `test_chain_engine.py:14` 导入 `room_manager`（在 `40`、`53` 实际有用，OK），但 `test_magic_resolution_flows.py:3` 的 `pytest`、`test_chain_engine.py:11` 的 `pytest` 等仅用于 fixture 装饰器（正常）。**此项经核查无实质问题** —— 撤回。

---

## 附录 A：修复优先级建议

| 优先级 | 问题 | 位置 |
|---|---|---|
| **P0** | 生产环境加载 `test_magic.js` + 无鉴权的 `test_*` socket 事件（可被任意客户端调用直接获胜） | `index.html:492`；`server.py` 8 个 `test_*` handler |
| **P0** | `showDivineDecreeChoice` 未定义 → 神之宣告时 `chain_resolved` handler 崩溃、UI 卡死 | `game.js:2194` |
| **P0** | `#effect-indicators` 不存在 → 百亿补贴时 `applyCardEffect` 崩溃 | `game.js:4552` |
| **P1** | `getRPSName` paper/scissors 映射互换（显示错误） | `game.js:3323-3324` |
| **P2** | 清理 `emit('line_attack')` + `gameState.selectedLine` 双重死代码 | `game.js:4498-4506` |
| **P2** | 清理/补齐 8 个无对应服务端事件的 `socket.on`，并决定大厅功能去留 | `game.js:2230-2242, 2754-2779` |
| **P2** | `switchScreen` 数组补 `matchSuccessScreen` | `game.js:2911` |
| **P2** | `gameState` 11 个隐式字段补齐声明 | `game.js:804-829` |
| **P3** | 删除死代码 `showChainableCards` / `#chain-prompt-container`；修复 `gameState.chain` 永不填充 | `game.js:5331`；`index.html:274` |
| **P3** | 补前端契约测试（socket 事件名、DOM id、description 一致性） | `tests/` |
| **P3** | `test_magic_effects.py:38` 补 `affected_positions` 断言；`test_disconnect...:37` 修列表乘法 | 各测试文件 |

## 附录 B：关键常量速查

| 常量 | 值 | 位置 |
|---|---|---|
| `GAME_LOG_MAX_ENTRIES` | `200` | `game.js:997` |
| `ACTIVE_GAME_KEY` | `'battle_active_game'` | `game.js:833` |
| `KEEP_VISIBLE`（浮窗） | `48` px | `game.js:4915` |
| 日志窗 storageKey | `'game_log_pos'` | `game.js:5083` |
| 聊天窗 storageKey | `'in_game_chat_pos'` | `game.js:762` |
| 主题 storageKey | `'theme'` | `index.html:550, 567, 571` |
| 连锁超时 | `data.countdown \|\| 10` 秒 | `game.js:2287` |
| 棋盘尺寸 | 6×6（72 格 = 双方各 36） | `game.js:3003, 3021` |
| 默认船数 | `6` | `game.js:812` |
| 匹配倒计时 | 5 秒 | `index.html:116`；`game.js:1853` |
| 卡牌总数 / 唯一卡名 | 43 / 41 | `magic_card.json` |
