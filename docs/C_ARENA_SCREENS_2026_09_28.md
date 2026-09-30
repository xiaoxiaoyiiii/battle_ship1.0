# 其余 5 屏的 arena 语言（2026-09-28）

> 承接 `docs/C_ARENA_THREE_ZONE_2026_09_28.md`（对局屏三区 + 合并 origin/main）。
> 示意稿 C 只画了**首页与对局屏**，这 5 屏（布阵 / 猜拳 / 大厅 / 排行榜 / 名片设置）
> **没有对照稿** —— 本节按 C 的**词汇**收口，不新造语言。

---

## 1. 收口用的"语法"（都是从示意稿 C 里数出来的，不是新设计）

| 词 | 取值 | 出处（demo C） |
| --- | --- | --- |
| 面板 | `--panel` 底 + 1px `--line`/`--border` + **12px 圆角** + **无阴影** | `.card-panel { border-radius:12px }`，`.opp-bar` 同值；全篇没有 panel 投影 |
| 海 / 大面 | **14px 圆角** + 内发光 | `.sea { border-radius:14px }` |
| 小件 | 9–10px（迷你卡 / 图标块） | `.mini` 9 / `.gobtn .ic` 10 |
| 胶囊 | 999px（按钮、状态、chip） | `.seg button` / `.gobtn .go` / `.tb .track` |
| 小标题 | 11px + 字距 .2em + `--tx3` + 600 | `.card-panel h4 { font-size:11px; letter-spacing:.2em }` |
| 主行动 | 紫渐变 + 辉光 | `.hero-card` 的渐变按钮 / `.bigbtn` |
| 次行动 | 透明底 + 1px 描边 | `.ghost { background:transparent; border:1px solid var(--line2); border-radius:7px }` |
| 数字 | 等宽 | `--mono`（本项目 = `--fluent-font-mono`） |
| 分隔 | 1px dashed | `.ach { border-bottom:1px dashed rgba(59,70,117,.55) }` → 落到 `--arena-line-dash` |

**新代码块**：`static/style.css` §39（39.0 屏头 / 39.1 布阵 / 39.2 猜拳 / 39.3 大厅 /
39.4 排行榜 / 39.5 名片·设置）。全部带 `html[data-theme-preset="arena"]` 前缀 ——
其余 7 个预设沿用 Fluent 外观；前缀同时把特异度抬到 (0,3,x)/(1,1,x)，压得住各屏自己的规则。

⚠️ 只动外观：**id、文案、盒模型的结构值（width / min-height / grid 轨道）一个没改** ——
这些屏各自有 `tools/*_check.mjs` 在跑。

---

## 2. 逐屏改了什么

| 屏 | 改前 → 改后 |
| --- | --- |
| **布阵** | 25.6px 居中标题 → 19px；两行提示 → 12px subtle；「已放置 3/6」→ 等宽数字**胶囊**；按钮分档（确认放置 = 紫渐变 + 辉光，随机摆放 = 描边）；棋盘本来就是 C 的海（§35.10） |
| **猜拳** | 标题 19px；三颗同重按钮 → **三张选择卡**（14px 圆角 + 面板底 + 图标 ✊✌✋ 在上、手势名在下）；悬停 = 紫描边，**选中 = 紫渐变 + 辉光**；结果文案 → 面板化的 chip（等宽数字、左对齐） |
| **大厅** | 面板 → 12px 圆角 + 无阴影；四个统计 → 胶囊（数字等宽）；面板标签 → 11px/.2em **左对齐**；列表行去掉色块底、改**虚线分隔**（"我"那一行留紫）；房间/公屏输入框统一；底部三颗按钮分档（快速匹配 = 主行动紫渐变） |
| **排行榜** | 那条**实心紫表头**去掉 → 11px/.2em 标签 + 1px 底线；行改虚线分隔 + 悬停淡紫；数字列等宽；整张表进 12px 圆角面板；页签 → 胶囊（选中 = 紫调 + 紫描边） |
| **名片 / 设置** | 三个弹窗壳 → 12px 圆角 + `--panel` + 1px 描边 + 无阴影；标题（`#opponent-stats-title` / `.pf-modal-title`）→ 16px **左对齐** + 下分隔线；左导航选中 = 紫调胶囊；分区小标题/字段标签 → 11px/.2em；主题预设卡 12px 圆角（选中 = 紫描边 + 辉光）；保存类按钮 → 紫渐变；名片查看面的顶部横幅走 `--arena-hero-grad`（斜纹层原本就有） |

### 2.1 顺带接上的一条真缺陷：猜拳出拳零反馈

`handleRPSChoice()` 此前**只 emit，不动 DOM**（点击前后页面完全一样），而 markup 里那个
`#rps-waiting`（"已出拳，等待对手…"）写好了却一直是**死代码**。这次接上：

- 点中 → 那张卡加 `.picked`（紫渐变）+ `aria-pressed=true` + 显示 `#rps-waiting`；
- `rps_result` 回来 → `setRPSWaiting(false)` 收回（平局要再点一次，所以是收回而不是锁死）；
- 进猜拳屏（`switchScreen`）先清一次，平局重进不会带着"已出拳"的状态。

⚠️ 反馈在 emit **之前**就给：这一屏没有别的加载态，等 ack 再亮会让人以为没点上。
进屏清状态那一句写在 `switchScreen` 里（与 `markMatchStart()` 同一处），
所有进猜拳屏的路径（正常流程 / 重连 / 工具直驱）都覆盖到。

---

## 3. 两处"看着像问题其实不是"

| 现象 | 真相 |
| --- | --- |
| `ranked_check` 停在「等待超时: 段位榜出现真实行」 | 工具要求**库里已有 ≥5 个真实段位玩家**（它自己不打段位局，且文档明说不能用 `test_win_game` 桩）。本轮用的 `.tmp/zone3.db` 是空库 → `/api/ranked_leaderboard` 只有 constants、没有行。换一个打过段位赛的库即可，与样式无关 |
| `fluent_style_check` 的 `[set] 模态 .modal-content 圆角必须在 {4,8,12}` 一度红 | 我第一版给弹窗壳写的是 14px（照"面板 14"的旧印象）。**数了一下示意稿：面板是 12px，只有 `.sea` 是 14px** —— 改成 12px 后既更贴 demo 也让这条断言绿了（没有放宽任何阈值） |

---

## 4. 本轮门禁

| 门禁 | 结果 |
| --- | --- |
| `pytest tests/ -q` | **2622 passed / 1 failed**（红的是 `.workbuddy/**` 那条环境性守卫，见三区文档 §5） |
| `ui_layout_check.mjs` | **136 PASS / 0 FAIL**（宽 5 档 + 紧凑 6 档 + 首页 2 档，含"页面无 JS 异常"） |
| `fluent_css_lint.py` | 块结构 OK |
| `fluent_css_metrics.mjs` | PASS（hex 100 / rgba 89 / !imp 31 / dupSel 29，阈值见三区文档 §3.3） |
| `fluent_style_check.mjs` | 全部通过（set / presets / dark + 6 张截图） |
| `dom_contract_check.mjs` | 通过 |
| `lobby_check.mjs` | 全部通过（四块面板 / 三列 / 无水平溢出 / 零 JS 异常） |
| `profile_card_check.mjs` | 全部通过 |
| `profile_leaderboard_check.mjs` | 全部通过 |
| `ranked_check.mjs` | 见 §3（需要带段位数据的库） |

出图看效果：`.tmp/screens/`（before-\* / after2-\* / final-\*：布阵 · 猜拳 · 大厅 · 排行榜 ·
段位榜 · 名片查看 · 名片编辑 · 设置，共 8 张一组）。

---

## 5. 还剩什么

- **每屏自己的"结构级"收口**没做：这一轮统一的是**语言**（面板 / 标签 / 按钮 / 胶囊 / 分隔 /
  数字），没有重排任何一屏的骨架。若某一屏要像首页/对局屏那样"按 C 重做结构"，
  那是各自一次上线的事（各自有 `tools/*_check.mjs`）。
- **上游新屏**（回放 / 观战 / 公告 / 反作弊后台）用的是上游自己的视觉语言，**没跟随** arena 令牌；
  要不要统一是下一个决策点。
- 上游那批裸色（§38 之后的 hex 增量 ~44 处）令牌化 = 把 AC6 阈值收回去的独立工作。
