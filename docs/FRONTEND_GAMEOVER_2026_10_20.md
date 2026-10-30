# 结算屏样板（票 #22）

> 适用：frontend/src/screens/game-over、stores/result、realtime/settlement。
> 本票把 /game-over 从占位迁成真实 Vue 屏，并给后续屏留下可复制的数据/选择器模板。

## 1. 数据流

    真实 Socket.IO
      game_state / room_sync ──> useGameStore（45 键显式镜像，#21）
      game_over ──────────────> useResultStore.gameOver { winner, reason, matchId }
      xp_gained ──────────────> useResultStore.xp
      rank_changed ───────────> useResultStore.rank（休闲局不会到达）
      achievements_unlocked ──> useResultStore.achievements
      ships_updated ──────────> useGameStore 剩余舰数（统计用）

* 通道由 GameOverScreen 在 onMounted 时 acquire、onBeforeUnmount 时 release；
  引用计数保证同屏多组件只开一条连接。state 留在 Pinia，切屏不丢。
* 屏幕只格式化服务端值：胜负 = game_over.winner 与 game_state.player_id 比较；
  回合/命中/剩余舰数取 game_state；段位/经验标签取事件里的 before/after。
  前端不重算段位或经验规则。
* gameOver.matchId 只认 game_over 载荷里的 match_id；没有就隐藏回放入口并给出
  一行说明，绝不从战绩里挑“最新一条”猜本局。
* 回放入口 push 到 { name: 'replay', query: { match_id } }，不新增路由名。

## 2. 选择器契约（data-testid）

屏根：screen-game-over（同时带 data-screen="game-over"）。

| testid | 用途 |
| --- | --- |
| game-over-heading / game-over-verdict / game-over-reason | 标题 / 胜负 / 说明 |
| game-over-players / game-over-self / game-over-opponent / game-over-mode | 双方信息 |
| game-over-stats / game-over-stat-round / game-over-stat-fire / game-over-stat-ships | 本局数据 |
| game-over-rank（-delta/-role/-before/-after/-fill/-note） | 段位，仅 rank_changed |
| game-over-xp（-delta/-level/-progress/-levelup/-fill） | 经验，仅 xp_gained |
| game-over-achievements / game-over-achievement-<id> | 徽章，仅 achievements_unlocked |
| game-over-replay / game-over-replay-note | 回放入口 / 无权威 id 的说明 |
| game-over-play-again / game-over-return-home | 操作 |
| game-over-empty | 深链/刷新没有结算数据时的可读空态 |

规则：同一 testid 一屏只出现一次；列表项用稳定业务 id，不用数组下标。

## 3. 入口与开关

* 默认 FRONTEND_MODE=legacy 不变：旧页面继续渲染 tpl 里的 #game-over-screen。
* FRONTEND_MODE=spa 时 /game-over 由新壳提供；没有新增逐屏后端分支。
* 再来一局 / 返回首页都清空 game/result store 后回 /（与旧栈 resetGame 到首页一致）。

## 4. 门禁（仓外）

cases/22-sample：
* test_static.py：双构建/哈希/生产包无测试钩子/vue-tsc/源码不硬编码 impl-22/
  legacy 默认不变/SPA 深链服务新壳。
* test_browser.py + browser_check.mjs：深链挂载、空态、真实 Socket.IO 两座位
  game_over、可选段位/经验/徽章、回放 query、两个按钮、桌面/手机无横向溢出、
  固定载荷截图基线（baselines/）。

## 5. 已知边界

* 本票只接结算相关事件；recent_opponent（参数化出站事件）暂未消费，等好友入口票。
* 通道由结算屏 acquire。对局屏 #24 落地时也要 acquire 同一通道，否则对局中收到的
  game_over 不会进 store（本票的浏览器门禁先挂载 /game-over 再建局，覆盖的是屏本身）。
* 进行中的对局统计（命中/开火）依赖 game_state/room_sync 的 attacks 快照；逐发
  attack_result 的实时累加属于 #24。
