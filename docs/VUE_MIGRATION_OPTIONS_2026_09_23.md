# Vue 重写的三个方案（2026-09-23）

回应"使用 Vue 重写"。**先说清一件事**：`docs/UI_REBUILD_PROPOSAL.md` §3.1 已经评估过这个选项，
结论是"❌ 不建议"，理由是 **9 个屏 + 101 处 innerHTML + 601 处 `gameState` 引用 + 6 个源码正则测试
+ 12 个无头工具都要推倒，服务端 60+ 事件契约要重对**。

但那条结论针对的是 **C 案（带构建链的整站重写）**，不是 Vue 本身。Vue 可以不带构建链用，
所以本文件把三案摆开，逐条给出代价与不可逆点。

---

## 0. 先明确：真正的成本不是渲染，是四份契约

这个项目里"换框架"能省的是模板字符串；**换不回**的是下面四份契约：

| 契约 | 规模 | 被谁依赖 |
| --- | --- | --- |
| **DOM id** | 12 个无头工具**全按 id 点击/断言**；`dom_contract_check.mjs` 查悬空 id | `tools/*.mjs`、`tests/` |
| **脚本加载顺序** | `/static/game.js` 必须先于 `/static/adaptive_layout.js`（有测试断言）；`rank_icons.js` 必须在 `game.js` 前；`wallpaper.js` 必须出现在 index.html | `tests/test_ranks.py`、`test_wallpaper.py` |
| **源码文本** | `tests/test_ui_review_fixes.py`(117 行) 与 `test_mobile_adaptive_layout.py`(124 行) **用 in/re 匹配源码字符串**，例：`assert '你：剩余 <span id="your-ships">6</span> 艘战舰' in HTML` | pytest（1565 条） |
| **socket 事件** | 服务端 60+ 事件、`gameState` 49 字段 | `server.py` / `api.py` |

**所以任何重写方案的 Phase 0 都一样**：把第 3 类（源码正则）改成"行为断言 + 契约文档"，
否则后面每一期都在跟测试打架，而红灯的信号是"你写错了"、实际是你改对了（`UI_REBUILD_PROPOSAL` §1.3 原话）。

---

## 1. 三案对比

### A · 原生 ESM + 轻量渲染原语（既有推荐，无 Vue）
- **做法**：`<script type="module">` + 自研 ~200 行 `h()/mount()/store`；Web Components 只用在真复用件。
- **保住**：部署（无构建）、测试、12 个无头工具、`asset_v` 缓存戳、脚本顺序契约。
- **代价**：状态订阅与 diff 边界要自己写。
- **适合**：主要目标是"把 UI 收拾干净"，而不是"上框架"。

### A′ · **Vue 3 渐进式（无构建链）** ← 我推荐这条
- **做法**：把 `vue.esm-browser.prod.js`（约 150KB）**本地托管**在 `static/`，用
  `<script type="module">` 引入；`createApp({...}).mount('#game-screen')` **直接拿现有 HTML 当模板**
  （browser 版自带编译器），于是：
  - **id 全保留** → 12 个无头工具不用重标定；
  - **脚本顺序不变** → 顺序契约测试照样绿；
  - **不引入 node_modules、不加构建步骤** → `deploy.sh` / `push.sh` / eventlet 生产全不动；
  - 顺序问题也有了先例：`static/socket.io.js`（191KB）本来就是**本地托管**的，同一个模式。
- **一次性**：**一屏一屏搬**。先搬一屏（建议**结算屏**或**图鉴**这类新增/独立屏），
  用 Vue 写新代码；老屏保持原样。搬完一屏跑那一屏的 `tools/*_check.mjs`。
- **限制（要接受的）**：
  - **不能用 `.vue` 单文件组件**（那需要构建）→ 模板用现有 HTML（带 `v-` 指令）或 JS 里的模板字符串；
  - 体积：browser 版含编译器，比 runtime 版大（~150KB vs ~35KB）——但项目本来就随包带 191KB 的 socket.io.js；
  - 仍然不能给 `.screen` / `.game-container` 等**含 `position:fixed` 后代的容器**加 `transform`/`filter`/`backdrop-filter`（Vue 的 `<Transition>` 默认用 transform，**用在这里会静默改浮窗基准**）。
- **代价**：约 3–5 天做第一屏的样板（含把该屏的源码正则测试改成行为断言），之后每屏 0.5–1 天。
- **一条能省事的发现**：Vue 的 browser 版在 `mount('#el')` 时**把该元素现有的 innerHTML 当模板**，
  所以只要**把现有 HTML 留在 `index.html` 里当模板**（而不是搬进 JS/`.vue` 文件），
  那批断言 `index.html` 文本的用例（如 `assert '你：剩余 <span id="your-ships">6</span> 艘战舰' in HTML`）
  **可以继续绿**。会红的只有断言 `game.js` 行文的那些（如 `assert "enterBattleBtn.style.display = 'inline-block';" in JS`）——
  Phase 0 的改造范围因此小一半。
  ⚠️ 但要注意：一旦某屏挂上 Vue，**该屏的 DOM 就必须整体交给 Vue 渲染**，
  不能让 `game.js` 继续往那些节点里 `innerHTML`（会被 Vue 的渲染覆盖）。所以搬迁单位是"整屏"，不是"半个屏"。

### C · 整站重写（Vite + Vue SFC + TS）
- **做法**：新前端工程，构建产物放 `static/dist/`。
- **必须重做**：9 个屏、101 处 `innerHTML`、601 处 `gameState` 裸引用、6 个源码正则测试、12 个无头工具、
  脚本顺序契约（`index.html` 的 script 标签全改）；服务端 60+ 事件契约要重对。
- **还要新增**：node_modules、构建步骤、CI 与部署多一步（`deploy.sh` 要加 `npm ci && npm run build`）、
  `asset_v` 缓存戳机制重做。
- **代价**：`UI_REBUILD_PROPOSAL` 估的是**"最现代，但这条路等于把三个月的既有契约重谈一遍"**。
- **适合**：确定要长期把前端当独立产品做，且接受一段"所有门禁暂时失效"的窗口期。

---

## 2. 并排对比

| 维度 | A 原生 ESM | **A′ Vue 无构建** | C Vue + Vite |
| --- | --- | --- | --- |
| 12 个无头工具能否继续用 | ✅ 原样 | ✅ 原样（id 不变） | ❌ 全部重标定 |
| 源码正则测试 | 要改（Phase 0 统一改） | 要改（同上） | 要改且要重写 |
| 构建步骤 / node_modules | 无 | **无** | 要 |
| 部署（eventlet / deploy.sh） | 不改 | **不改** | 要加一步 |
| 组件化程度 | 手写原语 | Vue 生态（无 SFC） | 完整 SFC + TS |
| 组装成本 | 自研 ~200 行 | 引一个文件 | 整套工程 |
| 一次性能搬完吗 | 一屏一屏 | **一屏一屏** | 否，必须一次性切换 |

**结论**：A′ 与 A 的差别只是"渲染原语自己写还是引 Vue"，两者对既有契约的破坏都等于零；
C 才是推翻契约的那条。所以"使用 Vue 重写"在 A′ 下是**可以做的**，而它的风险等同于 A。

---

## 3. A′ 的实施细节（如果走这条）

### 3.1 落地顺序（一屏一屏搬，每屏独立上线）

1. **Phase 0**（与旧方案相同，必须最先做）：把 6 个源码正则测试改成行为断言 + 契约文档。
   这批测试锁的是**行文**，任何搬迁都会让它们整片红。
2. **引入 Vue**：`static/vendor/vue.esm-browser.prod.js` + 一个 `static/vue/boot.js`，
   在 `index.html` 里用 `<script type="module">` 引；**先只挂一个空组件验证不破坏顺序契约**（跑全部门禁）。
3. **搬第一屏**：建议 **结算屏（`#game-over-screen`）** 或 **图鉴（新增）** ——
   它们依赖少、不参与对局时序，是风险最小的样板；把该屏的 `updateXxx` 渲染改成 Vue 组件，
   **id 一个不改**，跑该屏的 `tools/*_check.mjs` + `ui_layout_check`。
4. **逐屏下推**：布阵 → 猜拳 → 大厅 → 排行 → 名片 → 设置 → 首页 → **最后才是对局屏**。
   对局屏放最后，因为它是 601 处 `gameState` 与全部紧凑档断言的交汇处。
5. **对局屏的搬法**：先只搬"壳"（棋盘容器与 HUD 用 Vue 渲染，但**棋盘格子仍由现有逻辑生成**），
   再逐步把 `updateHandUI()` 之类搬进来；每搬一处跑一次 `ui_layout_check` 宽+紧凑两组。

### 3.2 三条红线（踩了就是静默故障）

1. **不许给 `.screen` / `.game-container` / `.game-content` / `.game-main-container` 加
   `transform` / `filter` / `backdrop-filter`** —— 它们有 `position:fixed` 后代（浮窗）。
   Vue 的 `<Transition>` 与 `<TransitionGroup>` **默认就加 transform**，
   所以要给这些容器用过渡时必须显式只动 `opacity`（或把过渡放在子元素上）。
2. **不许改 id、不许改脚本顺序** —— 这是 12 个无头工具与顺序断言的前提。
3. **改完必跑**：`ui_layout_check`（宽+紧凑两组）· `fluent_css_lint.py` · `fluent_css_metrics.mjs`
   （Vue 的 scoped 样式若用 `!important` 会撞 AC6 预算）· 该屏对应的 `tools/*_check.mjs`。

### 3.3 与 UI 方案的关系

**互不冲突**：`docs/IMPLEMENTATION_PLAN_2026_09_23.md` 的 C 化（紫金观感、真卡手牌、主次棋盘、
手机一屏一块）是**设计与样式层面**的；Vue 是**渲染机制层面**的。可以：
- 先做 C 化（M1：Phase 1 + 5.1，两天，不动盒模型），**再**引入 Vue；
- 或者反过来：Phase 0 → 引入 Vue → 搬第一屏 → 再在其中做 C 化。
**建议前者**：先把外观落定，Vue 搬迁时"哪里该长什么样"已经不用再想。

---

## 4. 我的建议

**走 A′，且先做 C 化的 M1**。理由：
- Vue 的实际收益（组件化、响应式）在 A′ 下能拿到，而**代价与 A 相同**（都是零契约破坏）；
- C 案那条"❌ 不建议"针对的是**构建链 + 一次性切换**，不是 Vue——这条区别值得写清楚，
  免得以后有人引用 §3.1 来说"Vue 不能上"；
- 先把外观定下来再做机制搬迁，两件事的验收标准不会互相干扰。

**要你确认的一件事**：走 A′ 还是 C？
- 选 **A′** → 我按 §3.1 从 Phase 0 开始（先出正则测试清单，不动代码）。
- 选 **C** → 需要先谈一件事：**谁承担"所有门禁暂时失效"的窗口期**，以及这段时间
  线上出问题怎么定位（现在那 12 个工具是主要手段）。
