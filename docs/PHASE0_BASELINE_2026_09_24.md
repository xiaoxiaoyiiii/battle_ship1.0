# Phase 0 基线清单（2026-09-24）

> 落地 `IMPLEMENTATION_PLAN_2026_09_23.md` 的 Phase 0：不改任何代码，只出基线数字与"会被改到的断言"清单。
> 后面每一期红了，都拿这份对照：是新问题还是老问题。

---

## 0. 基线数字（工作树现状，含 Fluent 未提交改动）

| 门禁 | 命令 | 结果 | 关键数字 |
| --- | --- | --- | --- |
| pytest | `python -m pytest tests/ -q` | ✅ 全绿 | **1565 passed**（27s；文档记的旧基线 ~1360 已过时） |
| 布局-宽屏 | `ui_layout_check.mjs --only wide` | ⚠️ **2 项老红** | 见 §1.4 |
| 布局-紧凑+平板 | `ui_layout_check.mjs`（默认） | ✅ 全绿 | 31 项 PASS |
| CSS 块结构 | `fluent_css_lint.py` | ✅ OK | 无缺/多花括号、无畸形嵌套 |
| CSS 度量 | `fluent_css_metrics.mjs` | ✅ PASS | hex **56**/90 · rgba **21**/180 · !important **42**(去注释27)/40 · dupSel **25**/25（**顶格**） |
| CSS 对比 HEAD | `fluent_css_diff_vs_head.py` | ✅ 缺失 0 | 选择器 1326 → 1329 |

> ⚠️ **dupSel 已顶到预算上限 25/25**。任何会新增重复选择器的改动（Phase 1 新预设、Phase 2 卡组件）
> 都会直接让它超标 → 新规则必须**合并进既有选择器**，不能再起新块。这是 Phase 1/2 的硬约束。

---

## 1. 会被各期改到的断言清单

### 1.1 读源码字符串的 pytest（Phase 1–5 都可能踩）

| 文件 | 断言什么 | 会被哪期踩 |
| --- | --- | --- |
| `test_ui_review_fixes.py` | `.board-wrapper` 的 `flex: 0 1 340px` / `.board` 的 `max-width: 340px`（**钉死棋盘尺寸**）；阶段按钮 `inline-block`；预览浮窗锚右上 | **Phase 3**（棋盘尺寸）、Phase 1（若动浮窗） |
| `test_mobile_adaptive_layout.py` | `body.classList.toggle('layout-ingame'` 等 adaptive_layout.js 判据 | **Phase 5.2**（改判据走 tabs） |
| `test_stats_display_fixes.py` | `.user-stats-table`/`.match-history-btn.win/.lose` 等类存在 | Phase 6（结算/战绩屏） |
| `test_screen_overlay_registry.py` | `.screen` 元素、`.modal-overlay` ≥9 个 | Phase 6（各屏） |
| `test_wallpaper.py` / `test_ranks.py` | `index.html` 引了 `wallpaper.js`/`rank_icons.js` 且顺序对 | 一般不踩 |
| `test_guardrails.py` | server.py 源码级守卫（与 UI 无关） | 不踩 |

### 1.2 `ui_layout_check.mjs` 里会被盒模型改动影响的断言

| 类别 | 断言 | 会被哪期踩 |
| --- | --- | --- |
| 手牌 | 「手牌可见且可点」「整条手牌都在视口内」 | **Phase 2**（真卡尺寸/扇形） |
| 棋盘 | 「两块棋盘同尺寸且 ≥280px」「棋盘完整落在首屏内」「格子零遮挡」 | **Phase 3**（M/P/U） |
| 浮窗 | 「预览与聊天不重叠」「HUD 未被浮窗盖住」 | Phase 2（若改预览窗）、Phase 3 |
| 紧凑档 | 「零纵向滚动」「触摸 ≥40px」「开面板后棋盘仍可见」 | **Phase 5**（重定判据） |

### 1.3 Phase 4 专属（用牌流程）

现有流程 = "点一次进待使用、再点一次尝试使用"（`updateHandUI` 的 click handler + `playMagicCard`）。
改成分流（无需目标点两次即用 / 需要目标选完再确认）会动到：
- `hand_play_check.mjs`、`target_selection_check.mjs`、`chain_target_check.mjs`
- `tests/` 里 `magic_*` / 出牌相关的行为断言

### 1.4 ⚠️ 基线就有的 2 项老红（**非本次改动引入**）

```
[home] 1600x1000 难度下拉内容盒放得下最长选项文字
[home] 390x844   难度下拉内容盒放得下最长选项文字
```
对局屏（wide/compact）全绿；红的是**首页难度下拉**。记入基线，后续各期若仍只有这 2 项红 = 没引入新问题。

---

## 2. 结论

- 安全网完好：pytest / lint / metrics / 布局对局屏全绿。
- **两个真约束**要带进后面每一期：① dupSel 顶格 25/25；② 首页难度下拉 2 项老红（别误判成新问题）。
- 盒模型红线（CLAUDE.md §11.6）+ 浮窗基准红线（§11.7）+ AC6 预算 + AC4 七预设只换色，四条都在 §0 表里有对应门禁。
