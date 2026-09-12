# UI 审查修复记录（2026-09-12 截图审查批）

> 依据：对局截图（2537×1401，按 DPR≈1.43 折算约 1770×978 CSS px）的**像素级**审查 + 源码逐条核对。
> 修复文件：`templates/index.html`、`static/style.css`、`static/game.js`、`static/avatars/default.png`
> 新增：`tests/test_ui_review_fixes.py`（9 条契约回归）、`tools/ui_layout_check.mjs`（无头浏览器布局回归）

---

## 一、截图审查确认的问题（已全部修复）

| # | 截图现象 | 根因 | 修复 | 验证 |
|---|---|---|---|---|
| A1 | 「第1回合」下方多出一条**纯空白圆角横条** | `index.html` 里 `#effect-status-bar` 没有 `hidden`，两个子项默认隐藏，而 JS 只切换子项、从不隐藏容器 → 容器只剩 padding+border | 容器默认 `hidden`；新增 `initEffectStatusBarSync()`（MutationObserver 监听子项 class，自动收起/展开） | 修复前像素扫描 y=209/231 有两条边框线；修复后 `display:none`（`ui_layout_check` PASS） |
| A2 | 「进入战斗阶段」按钮**贴左**，与居中的状态文字错位（按钮 x 620–840，卡片 590–1975） | `updatePhaseUI()` 用 `style.display = 'block'`；block 级 `<button>` 不再受 `#turn-indicator{text-align:center}` 影响 | 三处改为 `'inline-block'` | 按钮中心与卡片中心偏差 **-1px**（原来偏 -362px） |
| A3 | 两块棋盘**一大一小**（124×126 vs 154×156 设备像素，格距 16.8 vs 22）且都很小 | `.board{width:100%;max-width:340px}` 放在没有基准宽的 flex 项里 → 各按内容自适应 | `.board-wrapper{flex:0 1 340px}` | 两块均为 **300×300**、单格 **42×42**（原 ≈12–15 CSS px） |
| B2 | 「投降」按钮比标题低约 30 设备像素 | `h1,h2,h3,p{margin-bottom:1rem}` 参与 flex 的 `align-items:center` 对齐 | `.turn-indicator-inner h2{margin-bottom:0}` | 标题/按钮垂直中线均为 **92** |
| B3 | 游戏日志开局是**一片空白**的大白框 | 服务端只在攻击/出牌/胜负时发 `game_log`，前端没有空状态 | 新增 `.log-empty` 占位 + `ensureGameLogEmptyState()`（`addGameLog` 时移除占位，`switchScreen` 进对局兜底） | 开局 `logEmptyAtStart=true`，出日志后占位消失且两者不共存 |
| B5 | 「你: 6艘战舰剩余」断句别扭（"剩余"悬空） | 文案模板 | 改为「你：剩余 6 艘战舰」/「对手：剩余 6 艘战舰」 | 端到端读取 DOM 文本核对 |
| C1 | 中文界面普遍用半角冒号 + 空格 | 文案 | `index.html` 20 行、`game.js` 17 类文案统一改全角冒号 | `tests/test_ui_review_fixes.py` |
| C2 | 未上传头像的用户只显示一个**空圆环** | `static/avatars/default.png` 是 1×1 全透明 PNG | 重新生成 **96×96** 占位头像（浅蓝圆 + 白色人形，透明圆角） | PNG 头解析为 96×96；像素取样确认 |

## 二、审查发现但**有意不改**

- **B4 用户名重复**（左上角 HUD 胶囊 + 玩家信息卡第二行同时显示名字）：两处都在局内可见，删掉任一处都会让「谁是谁」更难读，属设计取舍，保留。
- **B6 预览框离手牌远**：试过把「待使用魔法卡」浮窗挪到 `bottom:24px`，实测与局内聊天浮窗（`.in-game-chat-container` 默认 `right:24px;bottom:24px`）**重叠 296×213**，已回退到右上角，并在 CSS 注释 + 测试里锁死。
- **B7 手牌贴底**：像素核对确认卡牌下边框完整可见（y≈1380，面板底 y≈1396），只是余量小，没有裁切，不加改动。
- **B8 页面留白过多**：浮窗式布局的整体设计，仅通过放大棋盘（A3）缓解。

## 三、验证方式（可复跑）

```powershell
# 1) 起服务：必须放行来源，否则 socket.io 会拒绝握手（“xxx is not an accepted origin”）
$env:PORT='5000'; $env:CORS_ORIGINS='http://127.0.0.1:5000'
.venv\Scripts\python.exe server.py

# 2) 布局回归（无头 Edge 自动打一局人机，断言 9 项布局不变量）
node tools/ui_layout_check.mjs --url http://127.0.0.1:5000/ --shot out.png

# 3) 静态契约 + 全量测试
.venv\Scripts\python.exe -m pytest tests -q
```

**实测结果**

- `pytest`：原 4 个测试文件 **191 passed**；加 `tests/test_ui_review_fixes.py` 共 **200 passed**。
- `tools/ui_layout_check.mjs`：9 项全部 PASS（连续两次运行稳定），退出码 0。
- **反向验证**（证明回归脚本真的会红）：临时把 `inline-block` 改回 `block`、去掉 `.board-wrapper` 的 flex 基准宽后重跑 → 棋盘变成 215×215 vs 104×104、按钮偏移 -362px，脚本退出码 1；还原后恢复 PASS。

## 四、遗留（不在本次范围）

- `tests/test_review_fixes_2026_09_12.py`、`tests/test_review_fixes_batch2.py` 是 **2026-09-12 另一批（后端/魔法卡/安全）审查**留下的未提交测试，当前 35 条失败（对应修复未落到代码），与本次 UI 修复无关，未改动。
- `docs/FIXES_2026-09-12.md` 同上，属那一批的产物。
