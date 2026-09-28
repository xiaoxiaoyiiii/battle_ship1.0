# 首页落到示意稿 C（卡牌竞技场）+ 竞技场全套皮肤（2026-09-27）

> 用户指令：「直接实现 demo c 的 ui，完全复刻」。
> 基线：`docs/ui_demos/c-arena.html`（示意稿 C）· 方案：`docs/IMPLEMENTATION_PLAN_2026_09_23.md`。
> 前几期（Phase 0–5.3 / 7 + Phase 6 图鉴与首页第一版）见 `docs/LANDING_STATUS_2026_09_24.md`
> 与 `docs/PHASE6_HOME_2026_09_25.md`。**本轮把首页从"出海区 + 次级入口"升级成 C 的三栏竞技场**，
> 并把 `arena` 预设从"只换强调色"扩成"连面层一起换"（暗色态 = C 的原色），对局屏随之变成 C 的海。

---

## 1. 这一轮改了什么（一屏一图）

| # | 改动 | 位置 |
| --- | --- | --- |
| 1 | **首页 = C 的三栏**：左「指挥官名片」（倾斜 2.2°）· 中「模式 + 热门卡」· 右「四块状态面板」 | `templates/index.html` `#start-screen`、`static/style.css` §35.9 |
| 2 | **arena 预设扩到面层**：页面底/面板/文字/边框/棋盘/格子全部有 C 的一套值，暗色态是 C 的原色（`#0b0d18` / `#151a30` / `#2a3358` / `#e7ecff` / `#7c5cf0` / `#4ec8e0`） | `static/style.css` 令牌区 `html[data-theme-preset="arena"]` 两个块 |
| 3 | **对局屏的「海」**：棋盘加青色内发光 + 大投影，命中红块加霓虹外发光，打空改成青色圆环（C 的 miss 就是环） | `static/style.css` §35.10（选择器带 arena 预设前缀） |
| 4 | **新增只读聚合接口 `/api/home_stats`**：在线 / 休闲队列 / 排位队列 / 可见房间数 | `server.py`（紧跟 `/api/online_count`） |
| 5 | **首页数据全部接真**：名片（名字/段位/等级/战绩）、最近解锁、生涯数据、段位阶梯、热门卡 | `static/game.js` 新增「首页面板」一节（`refreshHomePanels` 等 12 个函数） |
| 6 | 顶栏加「在线 N」胶囊（C 的 `.pill`） | `templates/index.html` `.nav-tools` + `static/style.css` `.nav-pill` |
| 7 | 顺手修两处**静默坏样式**与两处老红（见 §4） | `static/style.css` |
| 8 | **结算屏按示意稿 V 收口**（第二轮追加）：判定头（胜负大字 + 说明 + 对手/段位/用时）+ 四张卡（成就 / 经验 / 段位 / 本局数据）+ 操作行 | `templates/index.html` `#game-over-screen`、`static/style.css` §35.11、`static/game.js` `renderGameOverHead` |

### 1.1 三栏的结构（DOM 顺序 ≠ 视觉顺序）

```
.home-wrap            grid: 320px | minmax(0,1fr) | 348px   (gap 22)
  .home-mid   (col 2)   .home-lead → .home-hero(#find-match/名字/排队状态)
                        → .start-modes(排位 / 人机+难度) → .start-more(自定义 / 大厅)
                        → .card-panel.home-hot(全服热门卡 ×5)
  .home-left  (col 1)   .cmdr-card(#home-commander)：插画 + 名字 + 段位徽 + 等级条
                        (#my-level-strip) + 战绩/最长连胜/胜率 + 查看我的名片
  .home-right (col 3)   最近解锁 · 生涯数据 · 段位阶梯 · 在线情况（四块 .card-panel）
```

DOM 顺序是 **中 → 左 → 右**：窄屏收成单列时「先能开一局，再看自己的名片与状态」；
桌面的左右关系由 `grid-area` 指定，不依赖 DOM 顺序。

**⚠️ 所有 id 一个都没改**（9 个无头工具按 id 点击首页）。等级条从「底部状态行」
搬进了指挥官名片 —— `.start-status` 这个容器从此不存在（它的 3 条规则一并删除，
`fluent_css_diff_vs_head.py` 会报这 3 个"缺失"，属**有意删除**）。

### 1.2 数据来源（没有一处是编的）

| 块 | 接口 | 用到的字段 |
| --- | --- | --- |
| 指挥官名片 | `GET /api/profile` | `username` / `rank_info.{tier_name,sub,points,to_next,is_admiral}` / `level_info` / `wins` / `losses` / `longest_streak` |
| 最近解锁 | `GET /api/achievements` | `name` / `requirement` / `group`（图标复用 `PROFILE_BADGE_GLYPH`）/ `unlocked` / `unlocked_at` |
| 生涯数据 | 同 `/api/profile` | 胜率 = `wins/(wins+losses)` 前端只做一次百分比取整 |
| 段位阶梯 | `GET /api/rank_constants` + `rank_info.tier_index` | `tiers` / `start_points_of_tier` |
| 热门卡 | `GET /api/card_usage` + `window.magicCards` | 全服累计次数排序（新库全 0 时按速阶 1/2/3 轮取） |
| 在线情况 | `GET /api/home_stats`（本轮新增） | `online_count` / `queue.{casual,ranked}` / `lobby_rooms` |

**为什么单开 `/api/home_stats` 而不是收 socket 的 `lobby_state`**：`lobby_state` 只发给
**大厅订阅者**，而 `lobby_subscribe` 会把这个人记进 `lobby_manager.members()` ——
首页为了显示三个数字去订阅，等于让每个停在首页的人都被大厅算作"在大厅"。
新接口只 **读**（来源与大厅同一批：`lobby_manager.presence` / `room_manager.match_queue` /
`_lobby_visible_rooms()`），并有两条 pytest 钉住"与 `build_lobby_state()` 逐项同值"与"不改状态"。

### 1.3 结算屏（示意稿 V）的落地口径

- **三块既有面板一行没动**：#achievement-unlock-panel / #xp-gain-panel / #rank-gain-panel
  的内部 markup 与动画（`showXpPanel` / `showRankGainPanel` /
  `renderAchievementUnlockPanel`）全部原样，只是被 `.over-cols` 排成一行卡片
  （用 `.over-cols > .xxx` 的新选择器覆盖它们的 max-width/margin，避免动既有规则）。
- **判定头与「本局数据」是新写的**，且**只写一次**：`renderGameOverHead(data)`
  由两条 game_over 路径共用（socket 事件 + `room_sync`/`game_state` 回放）。
  改之前那四种结果文案是两份实现，其中一份还少了掉线分支 —— 这次一并收口。
  文案按**视角**分：`reason` 只说"怎么结束的"，不含"谁干的"，败方照抄胜方的话就会出现
  「对方投降 · 你的舰队被击沉」（实测过）。
- **本局数据只用前端已有的权威值**：回合（`gameState.round`，缺了退回 HUD 的 `#game-round`）、
  命中/开火（`gameState.myAttacks`）、剩余战舰（HUD 上服务端下发的两个数字）。
  示意稿里的「用了 N 张魔法卡」**没有前端来源**（`room.magic_history` 不下发）→ 不摆这一行。
- **用时**需要一个起点：`gameState.matchStartedAt` 在「布船界面出现」时打点。
  ⚠️ 正常开局那条路径是**直接 `classList.add('active')`、不走 switchScreen**（两处），
  第一版只挂在 switchScreen 上 → 实测用时恒为「—」；现在三处都打点（含 `applyRoomSync` 重连）。

---

## 2. 与示意稿 C 的**有意差异**（都不是漏做）

| 示意稿 C | 本轮实现 | 为什么 |
| --- | --- | --- |
| 暗色为唯一形态 | 明暗两根轴的 **arena 预设**：暗色态 = C 的原色，浅色态 = 同一色相的白昼版 | 项目已有"明暗跟随系统"的契约（`fluent_style_check --only dark` 钉着），改默认会推翻它；想要 C 的原色点「深色模式」即可 |
| 按钮 11–12px 圆角 | 受管控件（主行动/次级按钮/输入框/模态/导航/预设卡）保持项目 **4/8px 档位**；新容器（名片/面板/入口卡）用 12px | AC4「预设只换色、形状沿用 Fluent」+ `fluent_style_check` 的圆角档位断言。视觉上 8 与 12 在按钮尺寸上几乎不可辨 |
| 手牌 132×186、对手条、场地魔法面板、牌堆统计 | 沿用**已批准的 P 主次**（对手海域 460 焦点 + 你的海域 352 真棋盘）、真卡手牌（Phase 2 的扇形 + 两级预览）、连锁叠牌常驻 | 这三条是 `IMPLEMENTATION_PLAN_2026_09_23.md` §3.1/§3.2 拍板的结构决定，且被 128 项布局断言钉住；本轮只做"皮"（配色/材质/棋盘质感），不动已被验证的结构 |
| 命中画红色八角星、打空画青环 | 命中仍是**整格红底 + ✕**，只有打空改成青环 | 红叉/圈/盾碎/绝处逢生四态在本项目里是"玩法语义"（`style.css` 里各有一大段注释解释为什么不能互相混用），本轮不为观感牺牲可读性 |
| 「本季数据：平均回合 / 最高段位」 | 换成**真实存在的四个数**：胜率 / 总对局 / 当前连胜 / 最长连胜 | 平均回合与赛季最高段位在本项目没有对应存储（要新表）；首页不摆编出来的数字 |
| 「本周热门卡」 | 「**全服**热门卡」（累计使用次数） | `/api/card_usage` 是全时段全服累计，没有"本周"这个窗口 |
| 段位阶梯：`已过` 打绿点 | 高段在上、当前档金色高亮、已过的低段打绿点 | 示意稿里 `大副Ⅰ(高)` 标成 done、`大副Ⅱ(当前)` 标 now，语义与"已过"相反；这里按"已经走过的段位"给语义 |

---

## 3. 断言重定（1 处，附理由）

`tools/fluent_style_check.mjs` 组 `presets`：

```
旧：check(thDef.datasetThemePreset === 'fluent', '清空 localStorage 后默认预设 = fluent')
新：check(PRESETS.includes(defName), '清空 localStorage 后默认预设是已声明的预设之一（…）')
    + check(!!defPrimary, '默认预设下 --primary 有解析值（预设块命中 html）')
```

- **为什么改**：M1 把默认预设改成了 `arena`（`PHASE6_HOME_2026_09_25.md` §1），
  这条断言从那时起就一直是红的 —— presets 组不是每次改前端都会复跑，所以一直没被撞上。
  本意是"清空 localStorage 后落到一个**已声明**的默认预设"，不是"默认必须是 fluent"。
- **没有放宽**：新断言拦得住"fallback 掉了 / 落到未知名字 / 预设块选择器写错"三种坏法，
  并且额外要求默认预设的强调色**真的解析得出来**。
- **没有重定其它断言**：`#find-match 的计算底色 = 预设强调色`「底色必须不透明」
  「文字对比度 ≥ 4.5:1」「没有残留 linear-gradient」四条**原样保留**，
  所以本轮没有往主行动按钮上加渐变（C 的按钮是渐变的，这里刻意不跟）。

---

## 4. 顺手修掉的四个既有问题（都是"量出来"的，不是观感）

| # | 问题 | 证据 | 修法 |
| --- | --- | --- | --- |
| 1 | `@media (max-width: 560px)` 的窄屏导航规则**从未生效** | `python tools/fluent_css_lint.py` 报 `[unclosed] 第 7056 行 @media (max-width: 420px)` 与三条 `[swallowed]`；浏览器侧 390px 视口量到 `.nav-group` 计算 `display: flex`（期望 `contents`）—— 上一段注释漏写收尾 `*/`，把整块 @media 吞进了注释 | 补上注释收尾，规则恢复生效（`docs/FLUENT_UI_2026_09_21.md` §10.4 记的"注释吞规则"是同一类） |
| 2 | 35.8 节末尾一段"教训：…"文字**没有注释包裹**，静默丢到下一个 `{` | `fluent_css_lint.py` 的 `[swallowed]` 命中（该能力本来就在，是这段从未被复跑过） | 包回注释 |
| 3 | 首页难度下拉内容盒放不下最长选项（**1600×1000 −20px / 390×844 −3.6px**，Phase 0 记的老红） | `ui_layout_check` 的 home 段（本次复跑已转绿：**+48 / +205.6**） | `.home-wrap .mode-ai select { min-width: 9rem }`（宽屏）与窄屏那份 `min-width: 7rem` 一起兜住 |
| 4 | `.start-status` 三条规则成了死规则（容器已从 DOM 删除） | `fluent_css_diff_vs_head.py` 报 3 个缺失 | 删除并写明"等级条改挂在 `.cmdr-card .my-level-strip`" |

另：首页要"刚好一屏"（示意稿 C 在 1440×900 上就是放满的），为此把**首页专属**的
容器/页面内边距与四块面板的内边距各收了一档（`body:has(#start-screen.active)`、
`.game-container:has(#start-screen.active)`）——实测登录态 1440×900 的
`documentElement.scrollHeight` 从 **1013px → 900px**（不再多出一屏滚动）。

---

## 5. 本轮门禁（当前代码状态，命令都可复跑）

| 门禁 | 结果 |
| --- | --- |
| `python -m pytest tests/ -q` | **1567 passed**（含本轮新增 2 条 `home_stats` 用例） |
| `node tools/ui_layout_check.mjs --url …` | **全部通过**（宽 4 档 + 紧凑 6 档 + 首页两档；两条老红已转绿） |
| `node tools/fluent_style_check.mjs --url …` | **全部通过**（set / presets / dark 三组） |
| `node tools/dom_contract_check.mjs --url …` | 通过（3 项既有 WARN 不变） |
| `python tools/fluent_css_lint.py` | 块结构 OK（它本来就会报 `[swallowed]`/`[unclosed]`，本轮正是靠它抓到 §4 的两处） |
| `node tools/fluent_css_metrics.mjs` | **PASS**：hex 56 / rgba 26 / `!important` 27 / **dupSel 25（顶格）** |
| `python tools/fluent_css_diff_vs_head.py` | 缺失 3 个 = `.start-status` 及其两条后代（**有意删除**，容器已不存在） |
| `chain_stack_check` · `card_text_fit_check` · `card_art_wiring_check` · `mobile_bigcard_check` | 全部通过 |
| `recent_opponent_check`（结算屏「加好友」按钮的落点） | **52/52 通过**（按钮插在 `#game-result` 之后，本次改结构后复跑） |
| `ranked_check`（结算屏 `#rank-gain-panel` 三局真链路） | 71 通过 / 2 失败 = **既有工具-服务端契约漂移**（D3/D4：保存载荷少 `friend_requests_open`，与 `LANDING_STATUS_2026_09_24.md` §3 记的同一条） |
| `unlock_notice_check` | 5 项红 = **环境前置缺失**（它要 `.tmp/seed_perk_user.py` 先给库里种一个特权账号，该种子脚本不在仓库里）；与本轮改动无关 |
| `level_check`（结算屏经验面板 + 首页等级条） | 结算屏相关断言**全通过**；仅剩既有 3 项（对手称号/标签，同上契约漂移） |
| `node tools/level_check.mjs` | 仅剩既有 3 项红（对手称号/标签，`LANDING_STATUS_2026_09_24.md` §3 已记录的工具-服务端契约漂移）；**首页等级条两项通过** |

### 5.1 「dupSel 顶格 25/25」这一轮踩了两次

`dupSel` 是**同一 (at-rule 上下文, 选择器) 出现两次以上**的选择器个数，阈值 25 且已顶格：

1. `#ranked-match .mbtn-go` 在同一块里写了两次 → 合并成一条；
2. `.home-wrap .start-modes` 先出现在分组规则里、又单独起了一条覆盖 → 拆成分组**不再共用**的两条规则
   （`.start-modes` 一条、`.start-more` 一条）。

> 结论：**改这个文件时，"能不能并进既有那条规则"必须先想一遍**；分组规则里的某个成员
> 想单独覆盖，就会立刻超标。

---

## 6. 证据图片（归档，逐张看过）

`docs/images/arena_2026_09_27/`：

| 文件 | 看什么 |
| --- | --- |
| `01-home-light-1440.png` | 浅色态三栏（游客）：名片斜卡 / 主行动 / 入口卡 / 四块面板 / 热门卡 |
| `02-home-dark-1440.png` | **C 的原色**，登录态：段位徽 + 等级条在名片里、最近解锁有真实徽章、段位阶梯高亮当前档 |
| `03-home-dark-390.png` | 手机一列收敛（无横向溢出）、难度下拉独占一行 |
| `04-ingame-dark-1600x1000.png` | 对局屏的「海」：棋盘青色内发光、格子亮一档、手牌真卡 |
| `05-ingame-chain-dark.png` | 连锁叠牌（3 张真卡，落在手牌条内、不被聊天窗盖） |
| `06-mobile-hand-dark.png` | 手机 390×844 手牌 + 抽屉大卡面 |
| `07-result-win-1440.png` | 结算屏（胜）：金色判定头 + 徽章/经验/本局数据三张卡 + 操作行 |
| `08-result-lose-1600x1000.png` | 结算屏（负）：红色判定头，说明是「我方投降 · 你的舰队被击沉」 |
| `09-result-mobile-390.png` | 结算屏 390×844：卡与按钮各占一行（`scrollWidth == clientWidth == 390`，`docH == 844` 一屏放得下） |

> ⚠️ **改完 `templates/index.html` 必须重启服务端**：Flask 在非 debug 模式下会**缓存 Jinja 模板**，
> 只改文件不重启 → 浏览器拿到的是旧 DOM（实测：新加的元素 `getElementById` 全是 null，
> 而 `static/*.js` 是新版 → 出现"JS 在跑、元素不在"的怪象）。`static/*.js|css` 不受影响。

复跑（服务端要带 `ENABLE_TEST_EVENTS=1`，工具要的 `CORS_ORIGINS` 见 CLAUDE.md §1）：

```bash
# 首页（浅色 / 深色 / 手机）
node tools/page_shot.mjs --url http://127.0.0.1:5099/ --out .tmp/home.png --w 1440 --h 900
node tools/page_shot.mjs --url http://127.0.0.1:5099/ --out .tmp/home-dark.png --w 1440 --h 900 \
  --script "document.documentElement.classList.add('theme-dark')"
# 对局屏（真打一局，出 7 张图）
node tools/acceptance_shots.mjs --url http://127.0.0.1:5099/ --out .tmp/acceptance
```

---

## 7. 还差什么（下一屏）

- **其余 5 屏**（布阵 / 猜拳 / 大厅 / 排行榜 / 名片设置）仍是旧的 Fluent 皮 ——
  arena 预设的面层已经把它们整体染成 C 的色调（颜色跟着令牌走），但**结构**没按 C 收口。
  按计划仍是"一屏一次上线"，各跑各的 `tools/*_check.mjs`。
- **卡面真图**：热门卡缩略图已经接上 `applyCardArt`（`.hcard .ha` 带 `.card-art` 类，
  真图存在即显示、不存在保持渐变占位），把 41 张放进 `static/cards/` 即可，无需改代码。
- 首页「指挥官名片」的插画位（`.cmdr-art`）目前是渐变 + 金色环，等有头像/卡面素材后可换真图。

---

## 8. 第二轮：按「一比一复刻 demo」重做外壳与首页（同日晚）

用户要求**一比一复刻 demo 的效果**（不再要"改编版"）。这一轮把与示意稿不一致的地方
按 `docs/ui_demos/c-arena.html` 的原值逐条对齐 —— 对照基准是同一视口下的并排截图
（`docs/images/arena_2026_09_27/00-demo-c-reference.png` vs `10-home-1to1-1440.png`）：

| 维度 | demo 的原值 | 落地 |
| --- | --- | --- |
| 外壳 | 全幅（`body{background:#0b0d18}` + `body::before` 光柱），**没有窗口卡片** | arena 下 `.game-container` 去壳（透明/无描边/无阴影/无圆角）、`body` 去内边距、`::before` 毛玻璃层不显示；只有 `.modal-overlay` 保留亚克力 |
| 底色 | 紫光柱 + **斜向条纹**（`repeating-conic-gradient(from 200deg at 50% -10%)`）+ 青色副光 | 三段并进 `--bg-page`（暗色态），与 demo 同一组参数 |
| 顶栏 | `.topbar` 透明、品牌两行（15px + 10.5px 字距）、导航链接靠左、工具是 ghost 按钮 | 全部照做（含 `⚓ 战舰棋 · 竞技场 / BATTLESHIP ARENA` 两行品牌） |
| 圆角 | 面板 14 / 入口与主行动 12 / 小件 9-10 / 胶囊 999 | arena 自带一套形状档（`RADIUS_ALLOWED` 增加 12px） |
| 面板 | **无阴影** | arena 下面板/判定头去阴影 |
| 字号 | 13px 基准：入口标题 19px、面板标签 11px/.2em、数值 19px mono、卡片名 11.5-12.5px | 首页与结算屏按 demo 的值逐条设定 |
| 首页 hero | 单行入口（图标 + 标题 + 说明 + ENTER） | 名字输入与主行动**搬出 hero**、成为其下一条窄行（流程需要"游客先起名"，hero 本体与 demo 一致） |
| 首页三栏 | 300 / 1fr / 340，gap 22 | 同值 |
| 难度控制 | `.seg` 三颗胶囊 | 保留原生 `<select>`（工具按 `options` 量文字宽度）但画成同一颗青色胶囊 |
| 自定义/大厅 | 无图标的两列卡 | 去掉图标 |
| 指挥官名片 | 裸进度条（无胶囊壳）+ 三行：近 N 场 / 最长连胜 / **累计击沉** | 进度条脱壳；三行改为 战绩 / 最长连胜 / 累计击沉 —— `累计击沉` 由 `/api/profile` 新增的 `counters`（库里一直有的 `user_counters.sunk_total`）提供，**不是编的** |
| 最近解锁 | 未解锁也画**这枚徽章自己的图标**（灰一档），不用锁头 | 照做（锁头会把四行变成四个一样的图标） |
| 明暗默认 | demo 是暗色设计 | **没有显式选择时默认深色**（用户显式选浅色仍尊重） |

### 8.1 这一轮重定的三处断言（都写了理由）

1. `fluent_style_check` 的**圆角档** `{4px,8px}` → `{4px,8px,12px}`：arena 的入口/主行动
   按示意稿就是 12px，压成 8px 就不叫复刻。
2. `fluent_style_check` 的 **AC4 签名**"8 个预设完全一致" → "**除 arena 外的 7 个**完全一致
   + arena 自身自洽"：arena 现在是一整套设计（含形状），不再只是"另一套配色"。
3. `fluent_style_check --only dark` 的三条：由"跟随系统（系统浅色→必须浅色）"改为
   **"没有显式选择 → 默认深色；显式选择优先且跨重载保持；引导脚本仍在 `<head>` 且在样式表之前"**。

### 8.2 对局屏：已经 1:1 的部分 / 还没动的部分

**已对齐**：全幅外壳、配色（暗紫金 + 青色海）、棋盘的青色内发光与格子亮度、命中红块外发光、
打空青环、手牌真卡、连锁叠牌、HUD 变成一条红调渐变的横条（`.opp-bar` 观感）、
两块棋盘改名「你的海域 / 对手海域」。

**还没动（下一步的大块）**：示意稿的对局屏是**三区**（对手条 + 中场[对手海域 + 右侧连锁列/场地魔法]
+ 底排[你的舰队小盘 + 手牌 + 操作列]），而当前实现是"HUD 行 + 两块棋盘 + 手牌 + 停靠面板"。
这是结构改动，会牵动 `ui_layout_check` 的 128 项与 `game.js` 里大量状态渲染（还有此前拍板的
"对手海域为焦点 + 你的海域真棋盘"），所以单开一批做，不在本轮内混。

> ⚠️ 紧凑档（手机/横屏）**故意不套这套外壳**：它有一套已验证过的移动布局，
> 而且实测"给紧凑档的 HUD 加 8px 内边距 + 描边"会立刻把对局页顶出 20px 纵向滚动、
> 手牌被挤出可视区（`ui_layout_check` 当场红）。demo 本身也是桌面布局。
