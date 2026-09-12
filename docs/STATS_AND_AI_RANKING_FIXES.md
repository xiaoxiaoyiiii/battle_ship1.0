# 个人战绩弹窗 / 人机战绩统计 修复记录（2026-09-13）

> 触发：线上账号 `z1w6qn` 的「个人战绩」弹窗截图（3 条历史战绩全蓝、表头跑到最下面、
> 对手显示成 `ai-4530c8`）。逐条实测复现后再改，验证方式见文末。

## 一、问题清单与修法

| # | 症状 | 根因 | 修法 |
| --- | --- | --- | --- |
| 1 | 「时间 对手 结果 局内日志」这行表头孤零零躺在历史列表**最下方** | 历史行是 `<button>`，被直接拼进 `<table><tbody>`。`button` 不是合法的 tbody 子元素，HTML 解析器在 "in table body" 模式下启用 **foster parenting**，把按钮挪到 `<table>` 之前，`tbody` 变空，表头于是留在表后 | 历史列表改为 **div 三列网格**（`.history-list` / `.history-head` / `.match-history-btn`），表头与数据行共用同一套列宽，不再依赖 `table` |
| 2 | 三条胜利记录**全是蓝色**，胜负不分色 | 代码给行内联了 `background-color:#4caf50` / `#f44336`，但 `style.css` 第 3 节的通用规则 `button{background:var(--primary-gradient)}` 设的是 **background-image**（渐变），渐变绘制在内联背景色之上 → 实测渲染色 `#1973cf` | `.match-history-btn{background-image:none}` + `.win` / `.lose` 两个修饰类，底色由 `--success` / `--danger` 提供 |
| 3 | 人机对手显示成内部 ID `vs ai-4530c8` | AI 玩家 `user_id=None`（`server.py` 的 `create_ai_room`），`matches.loser_id='ai-<room_id>'` 在 `users` 表里没有对应行 → `LEFT JOIN` 得到 `loser_name=NULL` → 前端回退裸 ID | 新增 `isAiOpponent()` / `opponentDisplayName()`，`ai-` 前缀统一显示为**电脑**，并加「人机」标签 |
| 4 | 点开**胜局**的对局详情，「对手」栏显示的是**自己** | `game.js` 里写的是 `matchData.winner_name \|\| matchData.loser_name` —— 赢的局 `winner_name` 就是本人 | 按胜负取真正的一方（`isWin ? loser_name : winner_name`） |
| 5 | `.user-stats-table` / `.user-history` 两个类**样式表里从未定义** | JS 一直在用，CSS 从来没有 | 补第 23 节：表格内边距 / 分隔线 / 数值右对齐，历史三列网格，窄屏（≤560px）降级为「时间 / 对手」两行 + 右侧结果跨行 |
| 6 | 人机对局计入 `users.wins` / 连胜 → 打电脑就能刷排行榜 | `_finish_*` 一律调 `db.record_match(...)`；排行榜 `ORDER BY wins DESC`。`z1w6qn` 的「3 胜 0 负 3 连胜」**全部来自人机** | `db.record_match(..., count_stats=)`，人机局只写 `matches`（历史可回看）不计入统计；`server._count_stats_for(room)` 统一判据，6 处调用点全部显式传参 |

附带修掉的同类缺陷：

- `showUserStats` / `showMatchDetail` 各有**两份逐字重复的定义**（后者静默覆盖前者），`formatLogs` 定义了从未使用 → 合并为一份，并导出 `window.renderUserStatsHTML` / `window.renderMatchDetailHTML` 供无头回归检查直接调用。
- 历史按钮事件靠 `setTimeout(..., 100)` 绑定 → 改为 `innerHTML` 赋值后同步绑定（容器内 `querySelectorAll`）。
- 点一次头像就 `appendChild` 一个 **id 重复**的 `#user-stats-modal`，关闭只加 `hidden` 永不回收 → 统一走 `getStatsModalContent()` 复用页面里的静态弹窗；顺带去掉 `<p><table>` 这种非法嵌套。
- 表头第 4 列「局内日志」没有对应数据列 → 表头改为三列。
- 历史固定 20 条且无出口 → 增加「加载更多」（每次 +20，上限 100，与 `db.get_match_history` 的上限一致）。

## 二、数据口径变更

**人机对局从 2026-09-13 起不计入胜场 / 负场 / 连胜 / 排行榜**，但仍写入 `matches` 表（历史里可见，带「人机」标签，弹窗内有说明文案）。

历史数据用 `tools/recompute_ranked_stats.py` 一次性对齐（默认预演，`--apply` 才写库）：

    python tools/recompute_ranked_stats.py            # 预演
    python tools/recompute_ranked_stats.py --apply    # 写回

本机 `data/battleship.db` 已执行：`z1w6qn` 胜场 3→0、连胜 3→0；用户 `111` 负场 1→0（该局的对手是 AI）。
重算只统计「双方都不是 `ai-` 前缀」的对局，按 `timestamp` 升序重放，可反复对账（幂等）。

## 三、验证

1. **单元 / 静态回归**：`tests/test_stats_display_fixes.py`（14 条）—— 覆盖 `count_stats` 语义、
   人机房与真人房结算各自传入的 `count_stats`、`server.py` 里**每一处** `db.record_match` 都必须带
   `count_stats=`（防止以后新增调用点漏传）、前端不再用 `tbody` 承载按钮、渲染函数唯一、
   `.match-history-btn` 必须显式 `background-image: none`、重算工具的幂等性。
2. **真浏览器回归**：`tools/stats_modal_check.mjs`（无头 Edge + CDP，27 项）—— 直接调用页面里的
   真实渲染函数后测量 DOM 与计算样式：
   - 表头在数据行**之前**（含 `compareDocumentPosition` 顺序断言）、与数据行**逐列对齐**（±2px）；
   - `tbody` 里按钮数 = 0，`background-image` 为 `none`，胜局 `rgb(14,159,110)` / 负局 `rgb(229,57,53)`；
   - 人机行显示「电脑」而不是 `ai-xxxxxx`，且带「人机」标签与说明；
   - 对局详情：赢的局显示对方名、输的局显示对方名、人机局显示电脑；
   - 窄屏 390px：无水平溢出、时间列不被截断、结果列仍可见、有「加载更多」；
   - `--username z1w6qn` 用**真实账号数据**端到端跑一遍（本次实测：胜场 0 / 负场 0 / 历史 3 条人机胜）。
3. **全套**：`python -m pytest tests/ -q` → **295 passed / 0 failed**。

用法（需要先起一个放行该来源的服务端）：

    PORT=5000 CORS_ORIGINS=http://127.0.0.1:5000 python server.py
    node tools/stats_modal_check.mjs --url http://127.0.0.1:5000/ --username z1w6qn

## 四、有意不改的项

- **AI 名称仍存 `ai-<room_id>`**：不引入假的 `users` 行，避免污染排行榜查询；展示层映射即可。
- **历史默认仍取 20 条**：超过一页时给「加载更多」，不做无限滚动。
- **老数据不自动重算**：重算会改动线上用户数字，必须是显式动作（`--apply`），不在启动时静默执行。

## 五、补充：`--cookie` 登录态检查（2026-09-13 实测）

未登录时 `index.html` 不渲染 `#show-user-stats` 入口，点击检查会自动跳过。
需要覆盖「点导航栏 → fetch → 渲染 → 绑事件」这条完整链路时，用一个固定 `SECRET_KEY` 起服务端并注入
一个真实 session 即可（不需要密码、不写库）：

    # 1) 用固定 SECRET_KEY 起服务端
    $env:PORT='5000'; $env:SECRET_KEY='stats-check-secret'
    python server.py
    # 2) 用同一个 key 签一个 session（flask 自带的 SecureCookieSessionInterface，
    #    payload 为 {'user_id': <users.id>, 'username': <users.username>}）
    # 3) 跑检查
    node tools/stats_modal_check.mjs --url http://127.0.0.1:5000/ --username z1w6qn --cookie <session 值>

实测输出（28 项全部通过）：

    入口接线: 弹窗隐藏=false 内容="用户名 z1w6qn 胜场 0 负场 0 当前连胜 0 最长连胜 0 人机对局保留在历史中，不计入胜场 / 连胜，也不进"
    PASS  点「个人战绩」能打开弹窗并渲染内容
    PASS  页面无 JS 异常/报错

