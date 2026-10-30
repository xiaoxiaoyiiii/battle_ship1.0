# 大厅屏（票 #24）

> 适用：frontend/src/screens/lobby、stores/lobby、realtime/lobby。
> 本票把 /lobby 从占位迁成真实 Vue 屏；数据全部来自已实现的大厅事件与好友 HTTP 路由。

## 1. 数据流

    真实 Socket.IO（屏挂载时 acquire，卸载时 release）
      lobby_hello        -> hello.key/name/guest；广播里没有 is_me，前端用 key 自比
      lobby_state        -> 在线/大厅/队列计数、players、rooms、matches
      lobby_chat_history -> 按 seq 合并补缺（绝不清空已有帧）
      lobby_chat         -> 按 seq 去重追加
      match_queued/canceled -> 匹配按钮与取消入口
      friend_invite      -> 收到邀战的提示条（参数化出站事件，见 §5）
      game_state/room_sync -> placing_ships 时进入 /placement（已冻结的路由名）

    好友（HTTP，已实现）
      GET  /api/friends          -> 好友列表（在线/对局中/等级）
      POST /api/friends/invite   -> 服务端建房并推送 friend_invite；邀请者随后 join_room

* 屏幕只格式化服务端值：状态文案、座位数、遥测数字、段位/等级都来自载荷；
  前端只做“可加入 = players < capacity”这类展示判断，不重算房间可见性或匹配规则。
* 房主解散走 close_room；本屏只对“本会话创建的房”显示解散入口，服务端仍会做权限校验。
* 搜索/筛选是本地视图：不额外发请求，也不随 4 秒广播重置。

## 2. 选择器契约（data-testid）

屏根：screen-lobby（同时带 data-screen="lobby"、data-lobby-filter）。

| testid | 用途 |
| --- | --- |
| lobby-heading / lobby-online-count / lobby-lobby-count / lobby-queue-casual / lobby-queue-ranked | 标题与在线/大厅/队列计数 |
| lobby-refresh | 手动刷新（lobby_refresh） |
| lobby-search / lobby-filter-<all\|joinable\|watchable\|full> | 统一搜索与状态筛选 |
| lobby-players / lobby-player-<key> / lobby-player-me / lobby-players-empty | 在线玩家；key 是服务端 key（sid） |
| lobby-rooms / lobby-room-<room_id> / lobby-room-join-<room_id> / lobby-room-close-<room_id> / lobby-rooms-empty | 等待房列表与加入/解散 |
| lobby-room-name / lobby-room-public / lobby-create-room | 建房 |
| lobby-own-room / lobby-own-room-id / lobby-own-room-close | 本会话创建的等待房 |
| lobby-matches / lobby-match-<room_id> / lobby-match-spectate-<room_id> / lobby-matches-empty | 进行中对局与观战入口 |
| lobby-chat / lobby-chat-message-<seq> / lobby-chat-input / lobby-chat-send / lobby-chat-empty | 公屏 |
| lobby-friends / lobby-friends-refresh / lobby-friend-<user_id> / lobby-friend-invite-<user_id> / lobby-friends-guest / lobby-friends-empty | 好友邀战入口 |
| lobby-invite-banner / lobby-invite-accept / lobby-invite-dismiss | 收到的邀战 |
| lobby-match-casual / lobby-match-ranked / lobby-match-cancel / lobby-back-home | 匹配与返回 |
| lobby-notice / lobby-error | 可读的结果与错误提示 |

列表行一律用业务稳定 id（player key / room_id / user_id / chat seq），不用数组下标。

## 3. 入口与开关

* 默认 FRONTEND_MODE=legacy 不变：旧页面继续渲染 #lobby-screen。
* FRONTEND_MODE=spa 时 /lobby 由新壳提供；没有新增逐屏后端分支。
* 建房成功后不跳转（新壳没有自定义房路由）：本屏显示“我的房间”，房主可解散；
  第二人加入后服务端下发 placing_ships，两个客户端都进入已冻结的 /placement。

## 4. 门禁（仓外）

cases/24-lobby：
* test_static.py：双构建/哈希/生产包无测试钩子/vue-tsc/选择器契约/源码不硬编码 impl-24/
  legacy 默认仍服务旧大厅/SPA 深链服务新壳。
* test_browser.py + browser_check.mjs：两个独立 Chromium（各自己的 profile），
  各自注册真实账号、真实 Socket.IO；验证在线数、广播即时可见、双向聊天、
  建房/解散、搜索与四档筛选、观赛入口、真实好友申请/邀战推送/接受后双方进入 /placement；
  桌面/手机无横向溢出与截图基线（baselines/）。

运行：

    $env:T24_WORKTREE='D:/develop/battleship-worktrees/integration'
    $env:PYTHONIOENCODING='utf-8'
    D:/develop/battleship-verify/.venv/Scripts/python.exe -m pytest cases/24-lobby -q

## 5. 已知边界

* friend_invite 是参数化出站事件（D21），不在 events.gen.ts 的字面量清单里；
  realtime/lobby 只在这一处做局部字符串监听，typed client 不放宽。
* 本屏“观战”按钮 push 到 /spectate?room_id=<id>；观战屏（#17）接管加入与快照。
* 大厅通道按 #22 样板在卸载时 release；真正进入对局后的共享连接/重连归对局屏票据。
  游客的 player_id 是 sid，跨屏连接交接必须由对局屏复用同一连接（否则座位会随断开丢失）。
* 后端 lobby_state 的 level/rank/title 仍是占位投影（1/None/空），本屏按服务端值渲染。
* 游客显示名沿用首页写入的 sessionStorage/localStorage 键 battleship.playerName，缺省“玩家”；
  登录用户以服务端会话名为准。
