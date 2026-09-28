# 竞技场（示意稿 C）落地证据 · 2026-09-27

首页从"出海区 + 次级入口"升级成示意稿 C 的**三栏竞技场**，`arena` 预设从"只换强调色"
扩成"连面层一起换"（暗色态 = C 的原色）。完整记录：`docs/C_ARENA_HOME_2026_09_27.md`。

| 文件 | 看什么 |
| --- | --- |
| `01-home-light-1440.png` | 浅色态三栏（**游客**）：倾斜名片 / 主行动紫渐变 / 入口卡（排位金 · 人机+难度 · 自定义 · 大厅）/ 右栏四块面板 / 全服热门卡。游客态应显示"—"与「登录后显示徽章」，**不许出现 0 胜 0 负这种假数据** |
| `02-home-dark-1440.png` | **C 的原色 + 登录态**：段位徽（二级水手Ⅰ）与等级条在名片里、战绩 0 胜 0 负、最近解锁有真实徽章、段位阶梯把当前档标成金色 |
| `03-home-dark-390.png` | 手机单列收敛：无横向溢出（`scrollWidth == clientWidth == 390`）、难度下拉独占一行、热门卡两列 |
| `04-ingame-dark-1600x1000.png` | 对局屏的「海」：棋盘有青色内发光、**6×6 格子比棋盘亮一档**（第一版照 C 字面值写时整块看不清网格）、手牌是真卡 |
| `05-ingame-chain-dark.png` | 连锁叠牌：3 张真卡互相压住、落在手牌条内、不被聊天窗盖（`chain_stack_check` 同时有断言） |
| `06-mobile-hand-dark.png` | 手机 390×844：底部手牌 + 抽屉里的大卡面 |
| `07-result-win-1440.png` | 结算屏（胜）：金色判定头「胜利」+ 三张卡（本局刚解锁 2 枚徽章 / 本局获得 +40 经验 / 本局数据）+ 操作行（加好友 · 再来一局 · 返回主菜单） |
| `08-result-lose-1600x1000.png` | 结算屏（负）：红色判定头；说明必须按视角写（「我方投降 · 你的舰队被击沉」，不是"对方投降"） |
| `09-result-mobile-390.png` | 结算屏 390×844：卡片单列、加好友独占一行、两个按钮并排；`scrollWidth == clientWidth`、`docH == vh`（一屏放得下） |

## 怎么复跑

```bash
# 服务端（工具要的是这两条：CORS_ORIGINS 与 ENABLE_TEST_EVENTS）
BATTLESHIP_DB_PATH=.tmp/arena.db CORS_ORIGINS=http://127.0.0.1:5099 ENABLE_TEST_EVENTS=1 \
  PORT=5099 ./.venv/Scripts/python.exe server.py

# 首页三张（深色那张：先 localStorage 写 theme=dark 再截图）
node tools/page_shot.mjs --url http://127.0.0.1:5099/ --out .tmp/01.png --w 1440 --h 900
node tools/page_shot.mjs --url http://127.0.0.1:5099/ --out .tmp/02.png --w 1440 --h 900 \
  --script "document.documentElement.classList.add('theme-dark')"
node tools/page_shot.mjs --url http://127.0.0.1:5099/ --out .tmp/03.png --w 390 --h 844 --dsf 2

# 对局三张（真打一局）
node tools/acceptance_shots.mjs --url http://127.0.0.1:5099/ --out .tmp/acceptance
```

> ⚠️ 工具用的是**一次性 profile**（每次删干净），所以「登录态」的截图要在同一个 run 里
> 先 `fetch('/login')` 再 `location.reload()`（本轮用的是 `.tmp/shot_login.mjs` 这个变体，
> 它保留 profile 并多一个 `--settle` 等待）。另外**账号是建在服务端那次用的库里的** ——
> 换库（`BATTLESHIP_DB_PATH`）后要重新注册，否则登录会静默失败、截图变成游客态。
