# 落地实现方案 · 交付状态（2026-09-24）

> 对应 `IMPLEMENTATION_PLAN_2026_09_23.md`。**这一份是"哪一期做到哪、拿什么证明"的对照表**，
> 细节在各期自己的文档里（见 §4）。
> 拍板的五件事按用户选择执行：**先落 P** · **按卡分流确认步** · **移动端走 tabs** · **卡面先占位**。

---

## 0. 一期一图（逐期状态 + 证据）

| 期 | 状态 | 证据（命令 / 数字） |
| --- | --- | --- |
| **Phase 0** 摸清安全网 | ✅ 完成 | `docs/PHASE0_BASELINE_2026_09_24.md`：pytest **1565 passed**；紧凑+宽屏全绿；AC6 56/21/**42**/25；记下首页难度下拉 2 项老红 |
| **Phase 1** 视觉层（C 的皮） | ✅ 完成 | 新预设 `data-theme-preset="arena"`（紫金，明暗两态）。`fluent_style_check --only presets`：**8 预设同规范**（字体/圆角/间距签名唯一）+ 强调色两两不同 + 明暗对比度均 ≥4.5:1。AC6 数字与基线**一字不差** |
| **Phase 2** 卡组件与手牌 | ✅ 完成 | 真卡分区（插画/名牌+速阶宝石/说明/类型条）+ Balatro 扇形 + 两级预览。`card_text_fit_check`（新）：**真实 41 张卡名零裁字**、说明按设计截断、三区总高 ≤ 卡高；`hand_play_check` 全绿；宽+紧凑布局全绿 |
| **Phase 3** 对局屏结构（P） | ✅ 完成 | **§10.3 修掉**：遮挡由 12/18/**36** 格 → **0/0**（五个视口）。连锁叠牌 `chain_stack_check`（新）9/9。见 `PHASE3_5_LANDING_2026_09_24.md` |
| **Phase 4** 目标选择态 | ✅ 完成 | 按卡分流。`target_flow_check`（新）**19/19**：无需目标点两次即用；需要目标 → 置灰「在棋盘上选…」→ 选好「确认使用 X！」→ 点空白=取消且不消耗卡 → 确认才发牌；越界被钳制。`target_selection_check` / `chain_target_check` / `chain_preview_check` 全绿 |
| **Phase 5.1** viewport-fit | ✅ 完成 | `viewport-fit=cover` + `env(safe-area-inset-top)` 成对补上（两处）。紧凑四档全绿 |
| **Phase 5.2** 手机一屏一块 | ✅ **实测已在走，无需改** | `board_mode_probe`：五个紧凑视口**全是 tabs**，390×844 格宽 **55.3px**（计划预期的终局值）。计划里"现在判 stack"的前提已过时 —— 改一个已经在正确状态的判据只会把绿的推红 |
| **Phase 5.3** 大卡面抽屉 | ✅ 完成 | `mobile_bigcard_check`（新）7/7：**200×280**（比例 0.7143）、说明完整显示（溢出 0px）。踩到的坑：dock 那条 `56×64` 规则特异度 (0,5,1) 会压住新规则 |
| **Phase 6** 其余屏 | 🟡 **1/8 屏** | **卡牌图鉴**已按真卡收口（`codex_realcard_check`（新）9/9 + 原 `card_compendium_check` 全绿）。剩余：首页 / 结算 / 布阵 / 猜拳 / 大厅 / 排行榜 / 名片设置 |
| **Phase 7** 卡面美术接线 | ✅ **接线完成，等出图** | `card_art_wiring_check`（新）19/19：映射覆盖 41 张、三处渲染位（手牌/连锁/大卡面）都接上、**未出图不破图**（真图层+渐变占位共存）、美术层 `aria-hidden`+`pointer-events:none`。另用真文件端到端验过一次（文件能解码、卡面计算样式指向它） |

---

## 1. Phase 7 只剩"把图放进去"

`tools/gen_card_art_prompts.py` 现在**同时生成** `static/card_art_map.js`（卡名 → `cards/<slug>.webp`，41 条）：

```bash
python tools/gen_card_art_prompts.py     # 重跑提示词 + 同步卡面映射
# 出图后：把 41 个文件按 slug 放进 static/cards/ 即生效，前端**一行都不用改**
```

设计上是"有就显示"：真图是最上面那层 `background-image`，文件不存在时浏览器跳过它、
下面的渐变占位照旧 —— 所以**不需要探测文件是否存在**（省一轮请求），也不会出现破图图标。

---

## 2. 这一轮踩到的三个坑（都写进了代码注释）

1. **特异度**：新组件的规则被既有档位规则压住，表现是"写上了但没生效"——
   大卡面被 `.dock-panel[data-dock-panel="card"] .magic-card`(0,5,1) 缩成 56×64、
   说明溢出 941px；连锁卡被手牌档位规则改成 86×118 撑破布局。
   **对策**：规则里带上真实的 DOM 上下文（`.dock-panel[data-dock-panel="card"]`、`#game-screen >`），
   而不是加 `!important`（`!important` 已有 42 条、预算 40）。
2. **AC6 的 dupSel 顶格（25/25）**：任何"再起一条同选择器的新块"都会超标。
   这一轮为此外科手术了 3 次（把声明**合并进**既有规则）。→ 改 CSS 前先想"能不能并进现有那条"。
3. **测数据要取真实的**：卡内文字盒的第一版工具用**编造的** 7 字卡名断言，
   量出一个真卡永远不会出现的 15px 溢出（实测最长真卡名是 5 汉字 / 9 字符的 `Freezing！`）。
   改成从 `static/magic_card.json` 读全部 41 张做最坏输入后，才是有效判据。

---

## 3. 两条"看着像我的问题、其实不是"（下次别重复排查）

| 现象 | 真相 |
| --- | --- |
| `ui_layout_check` 时红时绿（effect-icon 32px、棋盘∩角标、手牌不可点） | 工具会**真打一局 AI 对局**，AI 打出的卡会让效果角标出现 → 断言随对局状态漂移。连跑 3 次 `--only compact`，手牌可点性稳定通过。**先怀疑状态漂移，再怀疑自己的改动** |
| `level_check` 3 项红（对手称号/标签） | `tools/level_check.mjs` 的改资料 payload **从不发** `friend_requests_open`，而 `profile_spec.py:390` 已把它列为必需字段 → **工具与服务端的既有契约漂移**，与本次改动无关（`server.py`/`api.py`/`profile_spec.py` 本次一行未动）。`rank_help_check` 的 2 项红是我 `--db` 传错，传对后 **46/46 全绿** |

---

## 4. 各期细节文档

- Phase 0 基线：`docs/PHASE0_BASELINE_2026_09_24.md`
- Phase 2 卡内文字盒 + 一处断言重定（附理由）：`docs/CARD_TEXT_FIT_2026_09_24.md`
- Phase 3 §10.3 根因与修法 + Phase 5.2 实测结论 + Phase 5.3：`docs/PHASE3_5_LANDING_2026_09_24.md`

## 5. 新增/改动的工具（都可复跑）

| 工具 | 用途 |
| --- | --- |
| `card_text_fit_check.mjs` | 卡内文字盒（真实卡名最坏输入） |
| `target_flow_check.mjs` | 用牌流程分流（无需目标 / 需要目标 + 取消不消耗卡） |
| `chain_stack_check.mjs` | 连锁叠牌（含"必须落在手牌条内"） |
| `mobile_bigcard_check.mjs` | 手机大卡面（尺寸/比例/说明完整） |
| `card_art_wiring_check.mjs` | 卡面接线（映射覆盖 + 未出图不破图） |
| `codex_realcard_check.mjs` | 图鉴真卡（比例/说明/底图/可滚动） |
| `wide_geometry_probe.mjs` | 宽屏几何 + 逐格遮挡（§10.3 的诊断工具） |
| `board_mode_probe.mjs` | 移动档棋盘模式（side/stack/tabs）与格宽 |

## 6. 变更文件

`static/style.css`（卡组件/连锁叠牌/大卡面/图鉴真卡/宽屏 §10.3/保险区）·
`static/game.js`（卡面渲染四处 + 连锁叠牌 + 扇形 + 目标选择分流 + 图鉴）·
`static/adaptive_layout.js`（只加注释）· `templates/index.html`（viewport / 大卡面容器 / 卡面映射脚本）·
`static/card_art_map.js`（脚本生成）· `tools/`（见上表 + `fluent_style_check` 改 8 预设 + `target_selection_check` 一处断言重定 + `gen_card_art_prompts.py` 增产物）

> **未提交**：本次改动尚未 `git commit`（按项目约定，提交信息只写"改了什么"）。

---

## 7. 收尾时的一次全量复跑（当前代码状态）

```
### pytest                    1565 passed
### CSS lint                  块结构 OK（无缺花括号 / 无多余花括号 / 无畸形嵌套）
### CSS metrics               PASS（56 / 21 / 42 / 25，与 Phase 0 基线一字不差）
### CSS diff vs HEAD          缺失 0 个
### ui_layout_check           全部通过（宽 4 档 + 紧凑 6 档 + 首页）
### fluent_style_check        set 全部通过 · presets 全部通过
### card_text_fit_check       全部通过（6 条断言）
### chain_stack_check         ✓ 全部通过（10 条）
### mobile_bigcard_check      ✓ 全部通过
### codex_realcard_check      ✓ 全部通过
### card_art_wiring_check     ✓ 全部通过
### target_flow_check         ✓ 全部通过
### hand_play_check           ✓ 全部通过
```

另：`dom_contract_check` 全部通过 · `target_selection_check` / `chain_target_check` / `chain_preview_check` /
`card_compendium_check` / `profile_card_check` / `achievements_check` / `stats_modal_check` 全绿 ·
`rank_help_check` 46/46。

---

## 7.1 出图复核（"验证效果"那一轮）改掉了 4 个**属性断言没抓住**的缺陷

`tools/acceptance_shots.mjs`（新）按真实对局出 7 张图 + 2 张卡面 native 近景，
逐张看过之后改了 4 处 —— 当时 §7 的那批门禁**是全绿的**：

| # | 缺陷 | 怎么发现的 | 修法 + 新门禁 |
| --- | --- | --- | --- |
| 1 | 说明框把文字**拦腰切断半行** | 近景图一眼看出（盒高 35px / 行高 13.392px，余 8.2px） | 整行对齐（`flex:0 0 auto` + `max-height` 与 `line-clamp` 同为 3 行）+ 门禁新增"内容盒高度是整行整数倍" |
| 2 | 拉丁卡名 `Freezing！` 被从右边切掉 20px | 同上 | `.card-name { overflow-wrap: anywhere }` + 门禁新增"各文字块/容器 scrollWidth ≤ clientWidth" |
| 3 | 紧凑档类型条装不下「速阶 N」+「普通魔法」 | 门禁新增的容器检查量到溢出 6–8px | 类型块加省略号；紧凑/密集/横屏**隐藏「速阶 N」**（速阶由名牌宝石表达） |
| 4 | 常驻连锁叠牌被**聊天浮窗盖住**（只露半张卡） | 出图复查链那张看出 | 叠牌 `right: 320px` 让开聊天窗 + 门禁新增"矩形真相交"断言 |

> 归档：`docs/images/acceptance_2026_09_24/`（11 张 + 一份 README，写明每张看什么、怎么复跑）。
> 四条的完整记录见 `docs/CARD_TEXT_FIT_2026_09_24.md` §5/§6 与 `docs/PHASE3_5_LANDING_2026_09_24.md` §2。

> 四条都属于同一类：**属性"声明了"不等于渲染出来是对的**。
> 前三条详见 `docs/CARD_TEXT_FIT_2026_09_24.md` §5/§6（含"断言自己也会写错"的两次记录：
> 用含 padding 的 clientHeight 去除行高、以及把"单轴相交"当成叠压）。

---

## 8. 还剩什么

**Phase 6 的 7 个屏**（首页 / 结算 / 布阵 / 猜拳 / 大厅 / 排行榜 / 名片设置）。
不做的原因不是难，而是**这一期的正确单位就是"一屏"**（计划原话："每屏单独上线，跑该屏对应的
`tools/*_check.mjs`"）—— 每屏 0.5–1 天，且每屏都有自己的断言面，捆在一起交无法逐屏验。
示意稿与门禁都现成：`docs/ui_demos/m-arena-pro.html`（首页）· `v-result.html`（结算）·
`w-collection.html`（图鉴，已完成）· `s-mobile.html`（移动三档）。
做法与图鉴这一屏相同：**复用 Phase 2 的真卡组件 + Phase 1 的 arena 预设令牌**，
按屏跑它自己的 `tools/*_check.mjs`，一屏一次上线。
