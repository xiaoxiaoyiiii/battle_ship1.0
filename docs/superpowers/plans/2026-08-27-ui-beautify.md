# 战舰游戏前端 UI 美化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将战舰游戏前端整体升级为海洋军事风视觉体系（全局改造），保留主题切换与自定义主色功能。

**Architecture:** 设计令牌（CSS 变量）驱动的单文件 `style.css` 重写 + `index.html` 结构清理（内联样式迁移、弹窗移出导航）+ `game.js` 两处最小视觉改动（粒子气泡化、主色派生补全）。所有元素 id 与功能 class 不变，保证 game.js 与测试零破坏。

**Tech Stack:** 原生 HTML/CSS/JS、Flask（服务端不动）、Socket.IO

**规格文档:** `docs/superpowers/specs/2026-08-27-ui-beautify-design.md`

**绝对约束（所有任务生效）：**
- 不得改动任何元素 `id`；不得改动功能 class：`screen`、`active`、`hidden`、`cell`、`ship`、`hit`、`miss`、`revealed`、`modal-overlay`、`modal-close`、`rps-choice`、`in-game-chat-message`（及 `me`/`opponent`）、`splash-effect`、`cool-float`/`ripple`/`cool-flash`、`magic-card`、`selected`、`theme-dark`
- 不改 `magic_cards.js`、`music_player.js`、`test_magic.js`、服务端代码
- `index.html` 内联 `<script>` 块（在线人数、主题切换）逻辑不动

---

### Task 1: 重写 style.css —— 设计令牌与基础层

**Files:**
- Overwrite: `static/style.css`（整体重写，本任务写第一段：令牌 + 基础重置 + 背景 + 通用按钮/输入/导航）

- [ ] **Step 1: 写入令牌段**

`:root`（浅海主题）必须保留全部现有令牌名并采用以下取值（新增令牌追加）：

```css
:root {
    /* 基础面 */
    --surface: #dbeafe;                 /* 页面底色（渐变起点） */
    --surface-strong: #ffffff;
    --surface-muted: #eff6ff;
    --surface-elevated: #e0edfb;
    --text: #0f172a;
    --text-subtle: #334155;
    --muted: #64748b;
    --muted-strong: #64748b;
    --muted-strong-600: #475569;
    --border: #cbd5e1;
    --border-strong: #94a3b8;
    /* 主色（可被用户自定义覆盖） */
    --primary: #1565c0;
    --primary-600: #0d47a1;
    --primary-rgb: 21, 101, 192;
    --primary-50: #e3f2fd;
    --primary-gradient: linear-gradient(135deg, #1565c0, #1e88e5);
    --shadow-glow: 0 0 15px rgba(21, 101, 192, 0.5);
    /* 海洋点缀 */
    --accent: #e8a33d;                  /* 黄铜橙 */
    --secondary: #7b6cf6;
    --secondary-dark: #5a4dd0;
    --danger: #e53935;
    --success: #0e9f6e;
    --warning: #f59e0b;
    --info: #0ea5e9;
    /* 棋盘 */
    --board-bg: #cfe8fb;
    --board-border: #8fbfe8;
    --cell-bg: #f0f8ff;
    --cell-water: linear-gradient(160deg, #e8f4fd, #cfe6f8);
    --ship-metal: linear-gradient(145deg, #8d7b64, #6d5c46);
    --hit-fire: linear-gradient(145deg, #ff6b35, #d32f2f);
    --miss-dot: #9db4c8;
    /* 面板与层次 */
    --glass: rgba(255, 255, 255, 0.82);
    --panel: rgba(255, 255, 255, 0.72);
    --panel-border: rgba(21, 101, 192, 0.18);
    --overlay: rgba(8, 15, 35, 0.55);
    --shadow-panel: 0 8px 30px rgba(13, 71, 161, 0.12);
    --bg-page: linear-gradient(180deg, #bfdcf5 0%, #e3f2fd 45%, #f5faff 100%);
}

html.theme-dark {
    --surface: #0a1428;
    --surface-strong: #12233f;
    --surface-muted: #0e1c33;
    --surface-elevated: #16294a;
    --text: #dbe7f5;
    --text-subtle: #b7c7dc;
    --muted: #7e93ad;
    --muted-strong: #7e93ad;
    --muted-strong-600: #9db2ca;
    --border: #24406a;
    --border-strong: #3a5a8c;
    --primary: #2f8fdd;
    --primary-600: #1f6fb8;
    --primary-rgb: 47, 143, 221;
    --primary-50: rgba(47, 143, 221, 0.12);
    --primary-gradient: linear-gradient(135deg, #1f6fb8, #38a3f0);
    --shadow-glow: 0 0 18px rgba(56, 163, 240, 0.45);
    --accent: #f0b25a;
    --secondary: #8d80f8;
    --secondary-dark: #6f61e0;
    --danger: #ef5350;
    --success: #34d399;
    --warning: #fbbf24;
    --info: #38bdf8;
    --board-bg: #0f2242;
    --board-border: #2c4d7f;
    --cell-bg: #14294d;
    --cell-water: linear-gradient(160deg, #16305a, #102444);
    --ship-metal: linear-gradient(145deg, #a08a6b, #7a6647);
    --hit-fire: linear-gradient(145deg, #ff7043, #c62828);
    --miss-dot: #46617f;
    --glass: rgba(14, 26, 48, 0.85);
    --panel: rgba(16, 30, 55, 0.75);
    --panel-border: rgba(56, 163, 240, 0.22);
    --overlay: rgba(2, 6, 16, 0.72);
    --shadow-panel: 0 10px 34px rgba(0, 0, 0, 0.45);
    --bg-page: radial-gradient(1200px 500px at 70% -10%, rgba(56, 163, 240, 0.16), transparent 60%),
               linear-gradient(180deg, #0a1428 0%, #0e1f3c 55%, #102544 100%);
}
```

- [ ] **Step 2: 基础重置与背景**

```css
* { margin: 0; padding: 0; box-sizing: border-box;
    font-family: "Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei", sans-serif; }

body {
    background: var(--bg-page) fixed;
    color: var(--text);
    min-height: 100vh;
    display: flex; justify-content: center; align-items: flex-start;
    padding: 24px 16px;
    animation: fadeIn 0.6s ease-in-out;
}

#particle-canvas { position: fixed; inset: 0; width: 100%; height: 100%; z-index: 0; pointer-events: none; }
.game-container { position: relative; z-index: 1; }

@keyframes fadeIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
@keyframes slideUp { from { transform: translateY(50px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
@keyframes pulse { 0%,100% { box-shadow: 0 4px 15px rgba(220,53,69,0.3); } 50% { box-shadow: 0 4px 25px rgba(220,53,69,0.6); } }
@keyframes breathGlow { 0%,100% { box-shadow: 0 0 8px rgba(var(--primary-rgb),0.35); } 50% { box-shadow: 0 0 22px rgba(var(--primary-rgb),0.65); } }
@keyframes hitFlash { 0% { transform: scale(1.35); filter: brightness(1.8); } 100% { transform: scale(1); filter: brightness(1); } }
@keyframes waveFlow { 0% { background-position: 0 0; } 100% { background-position: 60px 0; } }

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
}
```

- [ ] **Step 3: 容器、标题、屏幕、按钮、输入、导航基础**

```css
.game-container {
    background: var(--panel);
    -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px);
    border: 1px solid var(--panel-border);
    padding: 1.5rem 2rem 2rem; border-radius: 16px;
    box-shadow: var(--shadow-panel);
    max-width: 1000px; width: 100%;
}
h1, h2, h3, p { text-align: center; margin-bottom: 1rem; }
h1 { font-size: 2.2rem; letter-spacing: 2px; }
.screen { display: none; }
.screen.active { display: block; animation: fadeIn 0.4s ease; }
.hidden { display: none !important; }

/* 按钮三级体系 */
button, .btn, .nav-btn, .modal-btn {
    padding: 0.55rem 1.2rem; font-size: 1rem; font-weight: 600;
    background: var(--primary-gradient); color: #fff;
    border: none; border-radius: 8px; cursor: pointer;
    transition: transform 0.15s ease, box-shadow 0.2s ease, filter 0.2s ease;
    box-shadow: 0 2px 8px rgba(var(--primary-rgb), 0.3);
}
button:hover, .btn:hover, .nav-btn:hover, .modal-btn:hover {
    transform: translateY(-2px); filter: brightness(1.08);
    box-shadow: 0 6px 18px rgba(var(--primary-rgb), 0.4);
}
button:active, .btn:active { transform: translateY(0); }
button.secondary, .btn.secondary, .btn-secondary {
    background: transparent; color: var(--primary);
    border: 1px solid var(--primary); box-shadow: none;
}
button.secondary:hover, .btn.secondary:hover, .btn-secondary:hover {
    background: var(--primary-50); box-shadow: 0 4px 12px rgba(var(--primary-rgb), 0.2);
}
button.danger, .btn-danger, .surrender-btn {
    background: linear-gradient(135deg, #e53935, #c62828); box-shadow: 0 2px 8px rgba(229,57,53,0.35);
}
button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

input, select {
    padding: 0.55rem 0.8rem; font-size: 1rem;
    border: 1px solid var(--border); border-radius: 8px;
    background: var(--surface-strong); color: var(--text);
    transition: border-color 0.18s, box-shadow 0.18s;
}
input:focus, select:focus {
    outline: none; border-color: var(--primary);
    box-shadow: 0 0 0 3px rgba(var(--primary-rgb), 0.18);
}
.input-group { margin-bottom: 1rem; text-align: center; }
.button-group { display: flex; justify-content: center; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
```

导航栏（替换原 `.nav` 样式）：

```css
.nav {
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 10px;
    padding: 0.6rem 0.9rem; margin-bottom: 1.2rem;
    background: var(--glass);
    border: 1px solid var(--panel-border); border-radius: 12px;
}
.nav-brand { font-weight: 700; font-size: 1.1rem; letter-spacing: 1px; color: var(--text); white-space: nowrap; }
.nav-menu { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.nav a {
    padding: 0.4rem 0.85rem; color: var(--text-subtle); text-decoration: none;
    border-radius: 999px; border: 1px solid transparent; font-weight: 500; font-size: 0.92rem;
    transition: all 0.18s ease;
}
.nav a:hover { background: var(--primary-50); color: var(--primary); border-color: rgba(var(--primary-rgb),0.35); }
.nav .nav-sep { display: none; } /* 旧竖线分隔符不再显示 */
.nav #help-btn, .nav #settings-btn, .nav #music-btn { padding: 0.4rem 0.85rem; font-size: 0.92rem; }
.nav-user { color: var(--muted); font-size: 0.92rem; }
```

- [ ] **Step 4: 浏览器打开页面确认首屏无样式崩溃（令牌与基础层生效）**

Run: `python start_server.py`（后台），浏览器打开首页目测导航与开始界面。
预期：浅海渐变背景、毛玻璃容器、胶囊导航链接可见。

- [ ] **Step 5: Commit**

```bash
git add static/style.css
git commit -m "style: 重写设计令牌与基础层（海洋军事风）"
```

---

### Task 2: 重写 style.css —— 布局与组件段

**Files:**
- Modify: `static/style.css`（在 Task 1 内容后追加以下各段；以下每段为完整规则，保留原有选择器名）

- [ ] **Step 1: 屏幕级布局**

```css
/* 开始界面英雄区 */
#start-screen { text-align: center; padding: 1.5rem 0; }
#start-screen h1 {
    background: linear-gradient(135deg, var(--primary), var(--info));
    -webkit-background-clip: text; background-clip: text; color: transparent;
    margin-bottom: 0.4rem;
}
#start-screen .button-group { flex-direction: column; align-items: center; gap: 0.8rem; }
#start-screen .button-group button { width: min(320px, 80%); }
#find-match { font-size: 1.1rem; padding: 0.8rem 1.4rem; }
#online-count-container {
    display: inline-flex; align-items: center; gap: 6px;
    margin-top: 1.4rem; padding: 6px 16px; border-radius: 999px;
    background: var(--glass); border: 1px solid var(--panel-border);
    color: var(--muted); font-size: 0.88rem;
}

/* 通用面板（屏幕区块卡片） */
.panel, .board-wrapper, .lobby-info, #leaderboard-container {
    background: var(--panel); border: 1px solid var(--panel-border);
    border-radius: 12px; box-shadow: var(--shadow-panel);
}
```

- [ ] **Step 2: 游戏主界面布局（去除硬编码偏移）**

```css
.game-main-container { display: flex; gap: 1rem; margin-top: 1rem; align-items: flex-start; justify-content: center; }
.game-content { position: relative; width: 100%; max-width: 900px; margin: 0 auto; }
.boards-container { display: flex; justify-content: center; gap: 2rem; margin-top: 2rem; flex-wrap: wrap; }
.board-container { display: flex; justify-content: center; margin-bottom: 1rem; }
.board-wrapper { padding: 1rem 1.2rem 1.2rem; }
.board-wrapper h3 { margin-bottom: 0.6rem; color: var(--text-subtle); }
```

- [ ] **Step 3: 浮窗面板（日志 / 魔法预览 / 聊天）**

```css
.log-container {
    position: fixed; top: 80px; left: 20px; width: 250px;
    background: var(--glass); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
    border: 1px solid var(--panel-border); border-radius: 12px;
    display: flex; flex-direction: column;
    height: calc(100vh - 200px); max-height: 600px;
    transition: width 0.3s ease, box-shadow 0.2s ease;
    flex-shrink: 0; z-index: 999; cursor: grab;
    box-shadow: var(--shadow-panel); overflow: hidden;
}
.log-container:active { cursor: grabbing; }
.log-container.collapsed { width: 40px; }
.log-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.5rem 0.7rem; background: var(--primary-gradient); color: #fff; flex-shrink: 0;
}
.log-header h3 { margin: 0; font-size: 1rem; text-align: left; }
.toggle-log-btn { background: none; border: none; color: #fff; font-size: 0.8rem; cursor: pointer; padding: 0; box-shadow: none; }
.log-container.collapsed .toggle-log-btn { transform: rotate(180deg); }
.log-content { padding: 0.5rem; overflow-y: auto; flex: 1; font-size: 0.9rem; line-height: 1.4; }
.log-content::-webkit-scrollbar { width: 6px; }
.log-content::-webkit-scrollbar-track { background: transparent; }
.log-content::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }
.log-container.collapsed .log-content, .log-container.collapsed h3 { display: none; }
.log-entry { margin-bottom: 0.5rem; padding: 0.35rem 0.5rem; border-radius: 6px;
    background: var(--surface-strong); border: 1px solid var(--panel-border);
    box-shadow: 0 1px 3px rgba(0,0,0,0.08); word-wrap: break-word; }
.log-player { color: var(--danger); font-weight: bold; }
.log-card { color: var(--accent); font-weight: bold; }
.log-coordinate { font-weight: bold; }

.magic-preview-container {
    position: fixed; top: 80px; right: 20px; width: 300px;
    background: var(--glass); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
    border: 1px solid var(--panel-border); border-radius: 12px;
    box-shadow: var(--shadow-panel); z-index: 1000;
    padding: 15px; max-height: calc(100vh - 100px); overflow-y: auto; cursor: grab;
}
.preview-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.preview-header h3 { margin: 0; font-size: 1.1rem; color: var(--text); text-align: left; }
.cancel-btn { padding: 5px 10px; background: var(--muted-strong); color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 0.8rem; box-shadow: none; }
.cancel-btn:hover { background: var(--muted-strong-600); transform: none; }
.preview-content { font-size: 0.9rem; color: var(--text-subtle); }
.card-stats { display: flex; justify-content: space-around; margin-bottom: 15px; padding: 10px; background: var(--surface-muted); border-radius: 8px; }
.stat-item { text-align: center; }
.stat-item span { font-weight: bold; color: var(--primary); }
.card-description { margin-bottom: 15px; }
.card-description h4 { margin: 0 0 8px 0; font-size: 1rem; color: var(--text); }
.card-description p { line-height: 1.5; margin: 0; }
.preview-instructions { margin-top: 15px; padding: 10px; background: var(--primary-50); border-radius: 8px; font-size: 0.85rem; color: var(--primary); text-align: center; }

.in-game-chat-container {
    position: fixed; right: 32px; bottom: 32px; width: 320px; max-width: 90vw;
    background: var(--glass); -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
    border: 1px solid var(--panel-border); border-radius: 12px;
    box-shadow: var(--shadow-panel); z-index: 1200;
    display: flex; flex-direction: column; overflow: hidden;
}
.in-game-chat-header { user-select: none; cursor: move; padding: 8px 10px; background: var(--primary-gradient); color: #fff; font-weight: 600; }
.in-game-chat-messages { flex: 1; min-height: 120px; max-height: 220px; overflow-y: auto; padding: 12px 10px 6px; font-size: 0.95em; color: var(--text); }
.in-game-chat-message { margin-bottom: 6px; word-break: break-all; line-height: 1.5; }
.in-game-chat-message.me { color: var(--primary); font-weight: bold; }
.in-game-chat-message.opponent { color: var(--accent); }
.in-game-chat-input-row { display: flex; border-top: 1px solid var(--border); background: var(--surface-muted); padding: 6px 8px; gap: 6px; }
#in-game-chat-input { flex: 1; margin: 0; }
#in-game-chat-send { min-width: 56px; }
```

- [ ] **Step 4: 棋盘与格子**

```css
.board { display: grid; grid-template-columns: repeat(6, 40px); gap: 5px;
    background: var(--board-bg); padding: 10px; border-radius: 10px;
    border: 1px solid var(--board-border); }
.cell {
    width: 40px; height: 40px; background: var(--cell-water);
    border: 1px solid var(--board-border); border-radius: 5px;
    cursor: pointer; display: flex; justify-content: center; align-items: center;
    font-size: 20px; position: relative;
    transition: background 0.15s ease, transform 0.12s ease, box-shadow 0.2s ease;
}
.cell:hover { box-shadow: 0 0 0 2px rgba(var(--primary-rgb), 0.45); transform: translateY(-1px); }
.cell .splash-effect { position: absolute; width: 36px; height: 36px; border-radius: 50%;
    pointer-events: none; box-shadow: 0 0 0 0 rgba(var(--primary-rgb),0.35);
    animation: splash-ripple 0.8s ease-out forwards; top: 2px; left: 2px; }
@keyframes splash-ripple {
    0% { box-shadow: 0 0 0 0 rgba(var(--primary-rgb),0.35); opacity: 1; }
    70% { box-shadow: 0 0 0 8px rgba(var(--primary-rgb),0.12); opacity: 0.6; }
    100% { box-shadow: 0 0 0 12px rgba(var(--primary-rgb),0); opacity: 0; }
}
.cell.ship { background: var(--ship-metal) !important; border-color: #5d4f3c;
    box-shadow: inset 0 2px 3px rgba(255,255,255,0.35), inset 0 -2px 3px rgba(0,0,0,0.3); }
.cell.hit { background: var(--hit-fire) !important; color: #fff; animation: hitFlash 0.4s ease-out; }
.cell.miss { background: var(--cell-bg); }
.cell.miss::after { content: ''; width: 10px; height: 10px; border-radius: 50%; background: var(--miss-dot); }
.cell.revealed { box-shadow: 0 0 10px 3px rgba(255,235,59,0.45) inset; border-color: var(--warning); }
```

- [ ] **Step 5: 魔法卡、猜拳、回合指示、玩家信息、场地魔法**

```css
.magic-hand-container { margin: 10px 0; padding: 10px; border: 1px solid var(--panel-border); border-radius: 10px; background: var(--glass); }
.magic-hand { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; justify-content: center; }
.magic-card { width: 100px; height: 150px; border: 2px solid var(--border-strong);
    background: linear-gradient(165deg, var(--surface-strong), var(--surface-muted));
    border-radius: 8px; cursor: pointer; padding: 6px;
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease; }
.magic-card:hover { transform: translateY(-6px) scale(1.03); border-color: var(--primary);
    box-shadow: 0 8px 20px rgba(var(--primary-rgb), 0.3); }
.magic-card.selected { border: 2px solid var(--warning); box-shadow: 0 0 10px rgba(255,193,7,0.5); transform: scale(1.05); }
.magic-card .card-name { font-size: 0.85rem; font-weight: bold; margin-bottom: 5px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }
.card-speed { font-size: 0.8em; color: var(--muted); }
.magic-card .card-description { font-size: 0.7em; height: 60px; overflow-y: auto; margin: 0; text-align: left; }
.card-type { font-size: 0.8em; margin-top: 5px; color: var(--primary); }

.rps-choices { display: flex; justify-content: center; gap: 1rem; margin-bottom: 1rem; }
.rps-choice { padding: 1rem 1.6rem; font-size: 1.2rem; }
.game-info { margin-bottom: 1rem; }
.players-info { display: flex; justify-content: space-around; margin-bottom: 1rem; flex-wrap: wrap; gap: 10px; }
.player-info { background: var(--glass); border: 1px solid var(--panel-border); border-radius: 10px; padding: 8px 14px; }
#turn-indicator { background: var(--surface-muted); border: 1px solid var(--panel-border);
    padding: 1rem; border-radius: 10px; text-align: center; animation: breathGlow 2.6s ease-in-out infinite; }
.phase-btn { margin: 4px; }

.field-magic-area { display: block; margin: 10px 0; padding: 10px; background: var(--glass); border: 1px solid var(--panel-border); border-radius: 10px; text-align: center; }
.field-magic { padding: 8px 15px; border-radius: 20px; font-weight: bold; display: inline-block; }
.field-magic.active { background: rgba(255,235,59,0.18); border: 1px solid #FFEB3B; box-shadow: 0 0 10px rgba(255,235,59,0.5); }
.field-magic-card { display: inline-block; color: var(--accent); font-weight: bold; margin-left: 5px;
    text-shadow: 0 0 3px rgba(240,178,90,0.5); padding: 3px 8px; background: var(--surface-strong); border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
.no-magic { color: var(--muted); font-style: italic; }
```

- [ ] **Step 6: 弹窗、消息、倒计时、排行榜、大厅、战绩、炫酷动效、响应式、滚动条**

保留并重写以下段（选择器名全部不变，取值换令牌）：
- `.modal-overlay` / `.modal-content` / `.modal-close`（现有样式已接近目标：遮罩 `var(--overlay)` + blur，内容 `var(--surface-strong)`、圆角 16、`slideUp` 入场；`h2` 加底部分隔线：`.modal-content h2 { border-bottom: 1px solid var(--border); padding-bottom: 8px; }`）
- `.modal-input`（现有样式保留，令牌化）
- `#game-message-container` / `.game-message`（success/warning/error 保留）
- `#match-success-screen` / `.match-info` / `#opponent-info` / `#countdown-timer`
- `.countdown-bar`：背景 `var(--surface-muted)`；`.countdown-fill`：`background: repeating-linear-gradient(90deg, var(--success), var(--success) 20px, #34d399 20px, #34d399 40px); animation: waveFlow 1.2s linear infinite;`
- `#leaderboard-container`（保留滚动）、`#leaderboard-table`：表头 `background: var(--primary-gradient); color:#fff;`，行 `tr:hover { background: var(--primary-50); }`，前三名 td:first-child 由 JS 决定不做特殊样式（保持现状，不加名次徽章，避免依赖后端数据）
- `.lobby-info` / `#lobby-players-list`
- `.chain-prompt-container` 全段（令牌化：背景 `var(--glass)` + blur，边框 `var(--primary)`）
- `.taoyuan-*` 全段保留结构，硬编码白色/浅色改为令牌（`rgba(255,255,255,*)` → `var(--glass)`/`var(--surface-strong)`）
- `.discard-pile-*` 全段令牌化
- `.reinforcement-countdown` / `.holy-heart-countdown`（与 `.reinforcement-countdown` 相同规则，新增 `.holy-heart-countdown`：紫色调 `background: rgba(124,58,237,0.95)`，同结构）
- `.effect-status-bar` / `.status-item` / `.status-label` / `.status-value`（令牌化，去掉独立的 dark 覆写）
- `.match-history-btn` / `.match-detail-*`（令牌化）
- `body.cool-effects-enabled` 动效段保留原样
- 响应式断点：

```css
@media (max-width: 1200px) { .magic-preview-container { width: 250px; right: 10px; } }
@media (max-width: 992px) {
    .magic-preview-container { position: static; width: 100%; margin-bottom: 20px; max-height: 300px; }
    .log-container { position: static; width: 100%; height: auto; max-height: 260px; margin-bottom: 1rem; }
}
@media (max-width: 768px) {
    .nav a { padding: 0.3rem 0.6rem; font-size: 0.9rem; }
    .modal-input { width: 95%; padding: 0.6rem; }
    .chain-prompt { min-width: 90%; padding: 10px 15px; }
    .chain-prompt-container { bottom: 120px; }
}
@media (max-width: 600px) { .in-game-chat-container { right: 2vw; bottom: 2vw; width: 96vw; max-width: 96vw; } }
```

- [ ] **Step 7: Commit**

```bash
git add static/style.css
git commit -m "style: 布局与组件全面令牌化（浮窗/棋盘/卡牌/弹窗/响应式）"
```

---

### Task 3: 重构 templates/index.html —— 结构清理

**Files:**
- Modify: `templates/index.html`

**规则：** 所有 `id` 不变；所有功能 class 不变；Jinja 块 `{% if username %}...{% endif %}`、`{{ username|tojson }}` 不动；底部 `<script>` 块不动。

- [ ] **Step 1: 导航栏重构**

将 `.nav` 内除模态弹窗外的内容改为：

```html
    <div class="nav" id="game-nav">
        <div class="nav-brand">⚓ 战舰游戏</div>
        <div class="nav-menu">
            {% if username %}
                <span class="nav-user">已登录: {{ username }}</span>
                <a href="/logout">退出</a>
                <a href="/leaderboard" class="hide-in-game">排行榜</a>
                <a href="#" id="show-user-stats" class="hide-in-game">个人战绩</a>
                <a href="#" id="show-profile" class="hide-in-game">个人信息</a>
                <a href="#" id="toggle-theme" class="hide-in-game">深色模式</a>
            {% else %}
                <a href="/login" class="hide-in-game">登录</a>
                <a href="/register" class="hide-in-game">注册</a>
                <a href="/leaderboard" class="hide-in-game">排行榜</a>
                <a href="#" id="toggle-theme" class="hide-in-game">深色模式</a>
            {% endif %}
            <button id="help-btn" class="btn secondary">帮助</button>
            <button id="settings-btn" class="btn secondary">设置</button>
            <button id="music-btn" class="btn secondary">🎵</button>
        </div>
    </div>
```

注意：保留 `hide-in-game` class（game.js 依赖）。

- [ ] **Step 2: 模态弹窗移出 `.nav`**

把 6 个模态块（`#profile-modal`、`#settings-modal`、`#help-modal`、`#user-stats-modal`、`#match-detail-modal`、`#opponent-stats-modal`）整体移动到 `.game-container` 结束标签 `</div>` 之前（与 `.screen` 同级），结构内容不变。

- [ ] **Step 3: 清除全部内联 style**

逐处替换为 class（在 style.css 末尾按需追加小规则）：
- 头像 `style="width:80px;height:80px;border-radius:50%;object-fit:cover;border:1px solid #ccc;"` → class `avatar-lg`；游戏内 `40px` 头像 → class `avatar-sm`
- 追加：

```css
.avatar-lg, .avatar-sm { border-radius: 50%; object-fit: cover; border: 2px solid var(--panel-border); }
.avatar-lg { width: 80px; height: 80px; }
.avatar-sm { width: 40px; height: 40px; }
.profile-avatar-row { text-align: center; margin-bottom: 1em; }
.profile-label { display: block; margin-bottom: 1em; }
.profile-label-half { display: block; margin-bottom: 0.5em; }
.modal-scroll-content { text-align: left; max-height: 60vh; overflow-y: auto; }
.muted-hint { color: var(--muted); font-size: 0.9em; }
.username-info { font-size: 0.95em; color: var(--muted); }
.player-flex-row { display: flex; align-items: center; gap: 10px; }
.turn-indicator-inner { display: flex; justify-content: space-between; align-items: center; }
.placement-actions { display: flex; gap: 10px; margin-top: 15px; justify-content: center; }
.discard-pile-btn-row { text-align: center; margin-top: 10px; }
.leaderboard-back-row { text-align: center; margin-top: 12px; }
.settings-section-gap { margin: 1em 0; }
#profile-signature, #old-password, #new-password { width: 90%; }
#avatar-input { margin-top: 8px; }
#primary-color-picker { vertical-align: middle; margin-left: 8px; }
#music-volume { width: 200px; vertical-align: middle; }
#music-loop-mode { vertical-align: middle; }
#change-password-msg { margin-top: 8px; }
#change-password-form { margin-top: 1em; }
```

涉及位置（index.html 现有行号参考）：`#profile-modal` 内（头像、表单、密码表单）、`#settings-modal` 内（音量、循环、当前播放）、`#help-modal` 底部提示、`#match-detail-modal` 内容、`.players-info` 两个 `.player-info`（头像行 + 用户名行）、`#turn-indicator` 内 flex 行、布阵按钮行、弃牌堆按钮行、排行榜返回按钮行、`#reinforcement-countdown`/`#holy-heart-countdown`（仅保留 `hidden` class）。

完成后 `index.html` 中不应再出现任何 `style="..."`（底部 `<script>` 除外）。

- [ ] **Step 4: 开始界面微调**

`#start-screen` 标题改为 `<h1>⚓ 战舰游戏</h1>`；`#online-count-container` 删除内联 style（class 已由 CSS 提供）。

- [ ] **Step 5: 本地打开页面验证（导航、弹窗开关、各屏幕切换）**

Run: `python start_server.py`，浏览器逐项点击：帮助/设置/音乐按钮、登录/注册链接、主题切换。
预期：弹窗正常开关（`.modal-overlay.hidden` 行为不变），主题切换生效。

- [ ] **Step 6: Commit**

```bash
git add templates/index.html static/style.css
git commit -m "refactor: 清理内联样式并重构导航/弹窗结构"
```

---

### Task 4: game.js 最小视觉改动

**Files:**
- Modify: `static/game.js:2-32`（initParticles）
- Modify: `static/game.js:438-442` 附近（主色选择器回调）

- [ ] **Step 1: 粒子改为上浮气泡**

将 `initParticles` 替换为：

```javascript
function initParticles() {
    const canvas = document.getElementById('particle-canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const primaryColor = getComputedStyle(document.documentElement).getPropertyValue('--primary-rgb').trim() || '21, 101, 192';
    const particles = [];
    for (let i = 0; i < 60; i++) {
        particles.push({
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
            radius: Math.random() * 3 + 1,
            speed: Math.random() * 0.6 + 0.2,
            sway: Math.random() * Math.PI * 2,
            swaySpeed: Math.random() * 0.02 + 0.005,
            alpha: Math.random() * 0.25 + 0.08
        });
    }

    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => {
            p.y -= p.speed;
            p.sway += p.swaySpeed;
            p.x += Math.sin(p.sway) * 0.3;
            if (p.y < -10) { p.y = canvas.height + 10; p.x = Math.random() * canvas.width; }
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
            ctx.strokeStyle = `rgba(${primaryColor}, ${p.alpha})`;
            ctx.lineWidth = 1;
            ctx.stroke();
        });
        requestAnimationFrame(animate);
    }
    animate();
}
```

- [ ] **Step 2: 主色回调补设 --primary-rgb**

在现有 `document.documentElement.style.setProperty('--primary', color);` 之后追加：

```javascript
document.documentElement.style.setProperty('--primary-rgb', hexToRgb(color));
```

并在该回调所在作用域外（文件顶层附近）添加工具函数：

```javascript
function hexToRgb(hex) {
    const h = hex.replace('#', '');
    const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
    const n = parseInt(full, 16);
    return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
}
```

（若现有代码已设置 `--primary-600` 为同色，保留不动。）

- [ ] **Step 3: 浏览器验证**：气泡上浮；设置→主色改红色→粒子、按钮、辉光随动。

- [ ] **Step 4: Commit**

```bash
git add static/game.js
git commit -m "feat: 粒子气泡化并补全自定义主色 RGB 派生"
```

---

### Task 5: 全量验证与收尾

- [ ] **Step 1: 启动服务器并浏览器逐屏检查**

Run: `python start_server.py`（后台），按规格第 8 节逐屏检查：开始界面、自定义房间、布阵、猜拳、对局界面（人机对战进入以观察棋盘/日志/浮窗）、大厅、排行榜、结算、各弹窗。

- [ ] **Step 2: 主题与主色验证**

切换深色模式检查全部界面无配色错乱；设置中更换主色确认按钮/高亮/辉光同步。

- [ ] **Step 3: 截图留档**（开始界面、对局界面、深色模式各一张，保存至 `tests/screenshots/`）

- [ ] **Step 4: 回归测试**

Run: `python -m pytest tests/ -x -q`
预期：与改造前基线一致（本次改动不涉及服务端与游戏逻辑）。若存在与 UI 无关的历史失败，记录并跳过。

- [ ] **Step 5: 最终 Commit**

```bash
git add tests/screenshots/
git commit -m "chore: UI 美化验收截图"
```
