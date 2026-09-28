/* =============================================================================
 * 移动端自适应布局（紧凑模式）
 * -----------------------------------------------------------------------------
 * 解决的问题：对局界面原本是"桌面多浮窗"范式（日志/聊天/卡牌三个 position:fixed
 * 窗口盖在一条长文档上），等比压到手机上就会出现：棋盘被挤出首屏、浮窗互相叠压、
 * 毛玻璃互相采样糊成一片、手牌在最底下够不着。
 *
 * 本模块的做法：按【可用空间】而不是设备类型选择布局。
 *   wide    宽 >= 1200 且 高 >= 700  —— 维持原有浮窗布局，一行不动
 *   compact 其余情况                —— 一屏网格：HUD / 棋盘舞台 / 手牌 / 面板槽
 *   tight   compact 且 高 <= 480    —— 横屏手机，进一步压缩 chrome
 *
 * 紧凑模式下三个浮窗被搬进 #aux-dock 的面板槽（三选一），因此在物理上不可能互相叠压；
 * 棋盘尺寸由舞台实际可用空间反推；舞台放不下两块棋盘时切成「我的/对手」切换。
 * 详见 static/style.css 第 22 节。
 * ========================================================================== */
(function () {
    'use strict';
    if (window.__adaptiveLayoutReady) return;
    window.__adaptiveLayoutReady = true;

    var WIDE_MIN_W = 1200;   // >= 此宽度且高度也够，才保留桌面浮窗布局
    var WIDE_MIN_H = 700;
    var TIGHT_MAX_H = 480;   // 更矮的视口（横屏手机）走紧凑压缩档
    var MIN_CELL = 40;       // 触摸目标下限（格子）
    var MIN_BOARD = MIN_CELL * 6 + 38;  // 6 格 + 格间距 + 棋盘内边距（保守估计）

    function $(sel, root) { return (root || document).querySelector(sel); }
    function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

    var gameScreen = document.getElementById('game-screen');
    if (!gameScreen) return;
    var body = document.body;

    var origin = {};          // 各面板在"宽屏原位"的父母/后继，用于还原
    var activeBoard = 'me';   // tabs 模式下当前显示哪块棋盘
    var userPickedBoard = false;
    var rafId = 0;

    /* ---------- 原位记录与还原 ---------- */
    function pinOnce(key, selector) {
        if (origin[key]) return;
        var node = $(selector);
        if (!node) return;
        // 已经被搬进面板槽的节点不能当"原位"记录
        if (node.closest && node.closest('#aux-dock')) return;
        origin[key] = { node: node, parent: node.parentNode, next: node.nextSibling };
    }

    function rememberOrigin() {
        pinOnce('preview', '#magic-card-preview');
        pinOnce('chat', '#in-game-chat-container');
        pinOnce('log', '.log-container');
        pinOnce('magicSystem', '#magic-system');
        pinOnce('corner', '#avatar-corner');
        pinOnce('oppCorner', '#opponent-avatar-corner');
        pinOnce('discard', '.discard-pile-btn-row');
        pinOnce('oppStats', '#show-opponent-stats');
        // 连锁叠牌（#chain-display，game.js 的 createMagicCardUI 建的）：arena 三区档要把它
        // 从手牌条搬进中场右列那条轨道（示意稿 C 的 .chain-stack），其余档位留在手牌条里。
        pinOnce('chainDisplay', '#chain-display');
    }

    function restoreNode(entry) {
        if (!entry || !entry.node || !entry.parent || !entry.parent.isConnected) return;
        if (entry.node.parentNode === entry.parent) return;
        var next = entry.next && entry.next.parentNode === entry.parent ? entry.next : null;
        entry.parent.insertBefore(entry.node, next);
    }

    function moveTo(node, parent, before) {
        if (!node || !parent) return;
        if (before && before.parentNode === parent) {
            if (node.parentNode !== parent || node.nextSibling !== before) parent.insertBefore(node, before);
        } else if (node.parentNode !== parent) {
            parent.appendChild(node);
        }
    }

    /* ---------- 面板搬家 ---------- */
    // 对局屏三区（示意稿 C，style.css 第 37 节）只在 arena 预设 + 非紧凑档生效。
    // 判据与 CSS 完全一致：`html[data-theme-preset="arena"] body:not(.layout-compact)`。
    function arenaThreeZone(compact) {
        return !compact && document.documentElement.dataset.themePreset === 'arena';
    }

    // 两个角落头像 chip（#avatar-corner / #opponent-avatar-corner）进【局内名片行】：
    // 紧凑档早就这么干（HUD 的 chip 行）；arena 三区档同理 —— 对手条最左边那颗 42px
    // 圆牌就是它，底排「你的舰队」卡里的头像也是它。其它档位仍是屏幕角落的浮标。
    function chipsIntoPlayerRows() {
        var rows = $$('.players-info .player-flex-row');
        if (rows[0]) moveTo(origin.corner && origin.corner.node, rows[0], rows[0].firstChild);
        if (rows[1]) moveTo(origin.oppCorner && origin.oppCorner.node, rows[1], rows[1].firstChild);
    }

    function applyPlacement(compact, tight) {
        var dock = document.getElementById('aux-dock');
        if (!dock) return;
        // 面板槽展开时手牌也收进卡牌页：此时用户在看面板，棋盘仍要保住尺寸
        var handInDock = tight || dock.dataset.open === 'true';
        rememberOrigin();
        var content = $('.game-content');
        var cardPanel = $('.dock-panel[data-dock-panel="card"]', dock);
        var logPanel = $('.dock-panel[data-dock-panel="log"]', dock);
        var chatPanel = $('.dock-panel[data-dock-panel="chat"]', dock);

        if (compact) {
            moveTo(origin.preview && origin.preview.node, cardPanel);
            moveTo(origin.discard && origin.discard.node, cardPanel);
            // 手牌：竖屏常驻在舞台下方；矮屏（横屏）收进卡牌面板，把高度让给棋盘
            if (handInDock) moveTo(origin.magicSystem && origin.magicSystem.node, cardPanel);
            else moveTo(origin.magicSystem && origin.magicSystem.node, content, dock);
            moveTo(origin.log && origin.log.node, logPanel);
            // "查看对手战绩"在 HUD 里会把对手 chip 挤成两行（文字叠字），
            // 又是个低频入口——挪进日志页，腾出的一行高度全给棋盘
            moveTo(origin.oppStats && origin.oppStats.node, logPanel);
            moveTo(origin.chat && origin.chat.node, chatPanel);
            // 角落头像并入 HUD 的玩家 chip，不再浮在内容上
            chipsIntoPlayerRows();
            // 连锁叠牌回到手牌条：紧凑档的条在流内、尺寸由 --board-size 反推，
            // 轨道（#arena-chain-slot）在紧凑档是 display:none，留在里面就看不见了。
            restoreNode(origin.chainDisplay);
        } else if (arenaThreeZone(false)) {
            // arena 三区：叠牌进中场右列轨道，两个头像 chip 进对手条 / 舰队卡
            moveTo(origin.chainDisplay && origin.chainDisplay.node, document.getElementById('arena-chain-slot'));
            chipsIntoPlayerRows();
            restoreNode(origin.preview);
            restoreNode(origin.chat);
            restoreNode(origin.log);
            restoreNode(origin.magicSystem);
            restoreNode(origin.discard);
            restoreNode(origin.oppStats);
        } else {
            restoreNode(origin.preview);
            restoreNode(origin.chat);
            restoreNode(origin.log);
            restoreNode(origin.magicSystem);
            restoreNode(origin.corner);
            restoreNode(origin.oppCorner);
            restoreNode(origin.discard);
            restoreNode(origin.oppStats);
            restoreNode(origin.chainDisplay);
        }
    }

    /* ---------- 舞台高度：用 visualViewport（软键盘/地址栏）而不是 100vh ---------- */
    function syncStageHeight() {
        var content = $('.game-content');
        if (!content) return;
        var vv = window.visualViewport;
        var vh = vv ? vv.height : window.innerHeight;
        var top = content.getBoundingClientRect().top;
        var h = Math.max(220, Math.round(vh - top));
        document.documentElement.style.setProperty('--stage-vh', h + 'px');
    }

    /* ---------- 棋盘：由舞台可用空间反推尺寸；放不下两块时切成切换模式 ---------- */
    function updateBoardMode() {
        var stage = $('.boards-container');
        if (!stage) return;
        var W = stage.clientWidth, H = stage.clientHeight;
        if (!W || !H) return;
        var mode;
        if (W >= MIN_BOARD * 2 + 4) mode = 'side';
        else if (H >= MIN_BOARD * 2 + 4) mode = 'stack';
        else mode = 'tabs';
        if (stage.dataset.mode !== mode) stage.dataset.mode = mode;
        if (gameScreen.dataset.boards !== mode) gameScreen.dataset.boards = mode;

        var size;
        if (mode === 'side') size = Math.min((W - 4) / 2, H) - 26;
        else if (mode === 'stack') size = Math.min(W, (H - 4) / 2) - 26;
        else size = Math.min(W, H) - 26;
        size = Math.max(140, Math.floor(size));
        document.documentElement.style.setProperty('--board-size', size + 'px');

        if (mode === 'tabs') applyActiveBoard();
    }

    function applyActiveBoard() {
        var wrappers = $$('.boards-container > .board-wrapper');
        wrappers.forEach(function (w, i) {
            w.classList.toggle('active', activeBoard === 'me' ? i === 0 : i === 1);
        });
        $$('.board-tab').forEach(function (b) {
            b.classList.toggle('active', b.dataset.boardTab === activeBoard);
        });
    }

    function setActiveBoard(which, byUser) {
        activeBoard = which === 'opp' ? 'opp' : 'me';
        userPickedBoard = !!byUser;
        applyActiveBoard();
    }

    /* ---------- 面板槽 ---------- */
    function setDockOpen(open) {
        var dock = document.getElementById('aux-dock');
        if (!dock || !document.body.classList.contains('layout-compact')) return;
        dock.dataset.open = open ? 'true' : 'false';
        var t = document.getElementById('dock-toggle');
        if (t) {
            t.textContent = open ? '▼' : '▲';
            t.setAttribute('aria-expanded', open ? 'true' : 'false');
        }
        // 展开/收起会改变手牌的归属（流内条 vs 卡牌页），需要重排
        applyPlacement(true, document.body.classList.contains('layout-tight'));
        clampDockHeight();
        updateBoardMode();
        applyActiveBoard();
    }

    function openDockPanel(name) {
        var dock = document.getElementById('aux-dock');
        if (!dock) return;
        dock.dataset.tab = name;
        $$('.dock-tab', dock).forEach(function (b) {
            b.classList.toggle('active', b.dataset.dockTab === name);
        });
        setDockOpen(true);
    }

    function bindDock() {
        var dock = document.getElementById('aux-dock');
        if (!dock || dock.dataset.bound === '1') return;
        dock.dataset.bound = '1';
        $$('.dock-tab', dock).forEach(function (btn) {
            btn.addEventListener('click', function () {
                var name = btn.dataset.dockTab;
                var sameOpen = dock.dataset.open === 'true' && dock.dataset.tab === name;
                dock.dataset.tab = name;
                $$('.dock-tab', dock).forEach(function (b) { b.classList.toggle('active', b === btn); });
                setDockOpen(!sameOpen);
            });
        });
        var toggle = document.getElementById('dock-toggle');
        if (toggle) {
            toggle.addEventListener('click', function () {
                setDockOpen(dock.dataset.open !== 'true');
            });
        }
        // 默认展开一次卡牌页，让新玩家知道面板槽在哪。
        // ⚠️ 这里只做「视觉初值」——能不能点到手牌不靠它：bindDock() 只在页面初始化时调用
        // 一次，那时 body 上还没有 layout-tight（apply() 在那之后才跑），
        // 所以「横屏默认展开」必须写在 layoutCompact() 里。
        var first = $$('.dock-tab', dock)[0];
        if (first) first.classList.add('active');
    }

    function bindBoardTabs() {
        var tabs = document.getElementById('board-tabs');
        if (!tabs || tabs.dataset.bound === '1') return;
        tabs.dataset.bound = '1';
        $$('.board-tab', tabs).forEach(function (btn) {
            btn.addEventListener('click', function () {
                setActiveBoard(btn.dataset.boardTab, true);
            });
        });
    }

    /* ---------- 状态同步 ---------- */
    function observeScreen() {
        var sync = function () {
            var inGame = gameScreen.classList.contains('active');
            body.classList.toggle('layout-ingame', inGame);
            if (inGame) schedule();
        };
        new MutationObserver(sync).observe(gameScreen, { attributes: true, attributeFilter: ['class'] });
        sync();
    }

    function observeGameChildren() {
        var sync = function () {
            var box = document.getElementById('magic-system');
            if (box && !box.dataset.adaptiveBound) {
                box.dataset.adaptiveBound = '1';
                observeHand();
                schedule();
            }
            if (document.getElementById('avatar-corner') && !origin.corner) schedule();
        };
        new MutationObserver(sync).observe(gameScreen, { childList: true });
        sync();
    }

    function observeHand() {
        var hand = document.getElementById('magic-hand');
        var box = document.getElementById('magic-system');
        if (!hand || !box) return;
        var sync = function () {
            var has = hand.querySelectorAll('.magic-card').length > 0;
            box.classList.toggle('hand-empty', !has);
        };
        new MutationObserver(sync).observe(hand, { childList: true, subtree: true });
        sync();
    }

    // 选卡后自动把卡牌详情面板推到前面（空状态不再白占首屏）
    function observeCardPreview() {
        var preview = document.getElementById('magic-card-preview');
        var nameEl = preview && preview.querySelector('.card-name');
        if (!nameEl) return;
        var sync = function () {
            var text = (nameEl.textContent || '').trim();
            var empty = !text || text.indexOf('未选择') >= 0;
            preview.dataset.empty = empty ? 'true' : 'false';
            if (!empty && body.classList.contains('layout-compact')) openDockPanel('card');
        };
        new MutationObserver(sync).observe(nameEl, { childList: true, characterData: true, subtree: true });
        sync();
    }

    // 没有生效的场地魔法时不显示"当前生效的场地魔法：无"——纯噪音，还占一整行
    function observeFieldMagic() {
        var el = document.getElementById('current-field-magic');
        if (!el) return;
        var sync = function () {
            gameScreen.dataset.fieldMagic = el.querySelector('.no-magic') ? 'none' : 'has';
        };
        new MutationObserver(sync).observe(el, { childList: true, subtree: true });
        sync();
    }

    // 轮次变化时自动切到"该看的"那块棋盘（用户手动切过也只保持到下一次轮次变化）
    function observeTurn() {
        var el = document.getElementById('current-player');
        if (!el) return;
        new MutationObserver(function () {
            var stage = $('.boards-container');
            if (!stage || stage.dataset.mode !== 'tabs') return;
            var mine = (el.textContent || '').indexOf('你') >= 0;
            setActiveBoard(mine ? 'opp' : 'me', false);
        }).observe(el, { childList: true, characterData: true, subtree: true });
    }

    /* ---------- 面板槽展开时的最大高度：棋盘优先 ---------- */
    // 面板槽展开会吃掉舞台高度。上限按"展开后棋盘仍拿得到最小尺寸"反推，
    // 否则点开日志就会把棋盘压成芝麻。
    function clampDockHeight() {
        var content = $('.game-content');
        var dock = document.getElementById('aux-dock');
        if (!content || !dock) return;
        if (dock.dataset.open !== 'true') {
            document.documentElement.style.removeProperty('--dock-max');
            return;
        }
        var stage = $('.boards-container');
        var contentH = content.clientHeight;
        var others = 0;
        $$('.game-content > *').forEach(function (el) {
            if (el === dock || el === stage || !el.offsetHeight) return;
            others += el.getBoundingClientRect().height;
        });
        // 竖屏：给棋盘留出最小尺寸；实在放不下再让步到 150px。
        // 横屏（tight）：棋盘在左列、面板槽在右列，两者不抢同一份高度，只需卡住本列剩余空间。
        var tight = body.classList.contains('layout-tight');
        var gaps = 4 * 5;
        var max;
        if (tight) {
            max = contentH - others - gaps - 8;
        } else {
            max = contentH - others - (MIN_BOARD - 26) - gaps - 20;
            if (max < 130) max = contentH - others - 150 - gaps - 20;
        }
        max = Math.max(96, Math.min(max, contentH * 0.6));
        document.documentElement.style.setProperty('--dock-max', Math.round(max) + 'px');
    }

    /* ---------- 主流程 ---------- */
    function isCompact() {
        return !(window.innerWidth >= WIDE_MIN_W && window.innerHeight >= WIDE_MIN_H);
    }

    function boardSizePx() {
        var n = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--board-size'));
        return n > 0 ? n : 0;
    }

    // tight：视口本身就矮（横屏手机）——布局翻成"棋盘左列 + HUD/面板右列"
    // dense：视口不矮但舞台塞不进最小棋盘——压缩 HUD 与手牌高度。
    // ⚠️ 这两档以前把手牌**搬进面板槽**（applyPlacement 第二参 true），而面板槽默认收起
    // （.dock-body 是 display:none）→ 实测 320x568 与 664x336 的 clickableCards = 0：
    // 手牌在 DOM 里、玩家一张都点不到（旧判据 handInDock 只看祖先节点，照样 PASS）。
    // 现在改为「手牌常驻流内」，只有玩家主动展开面板槽时才收进卡牌页（那是他自己的选择）。
    function layoutCompact(tight, dense) {
        body.classList.toggle('layout-tight', tight);
        body.classList.toggle('layout-dense', !tight && dense);
        // 手牌归属：不再把手牌搬进面板槽。
        // 以前 dense/tight 会把 #magic-system 搬进卡牌页省高度，但面板槽默认收起
        // （.dock-body display:none）→ 320x568 / 664x336 实测 clickableCards = 0；
        // 而把槽默认展开后，clampDockHeight 为了保住棋盘只给槽 149px，手牌又被挤出槽外。
        // 两难说明「把手牌藏进槽」在 320x568 上不成立 → 手牌常驻流内（CSS 压卡片高度腾空间）。
        // 例外：横屏（tight）336px 高确实放不下常驻手牌条（实测棋盘单格从 48px 掉到 18.5px），
        // 那里维持「手牌收进卡牌页」，并在此处**默认展开卡牌页**保证可点。
        applyPlacement(true, false);
        if (tight) {
            var dockEl = document.getElementById('aux-dock');
            if (dockEl && dockEl.dataset.open !== 'true') {
                dockEl.dataset.tab = 'card';
                setDockOpen(true);
            }
        }
        syncStageHeight();
        updateBoardMode();
        applyActiveBoard();
        clampDockHeight();
        updateBoardMode();
    }

    function apply() {
        var compact = isCompact();
        body.classList.toggle('layout-compact', compact);
        // 同时在屏幕元素上标记布局模式：既方便调试/回归读取，也给后续 CSS 留统一钩子
        gameScreen.dataset.layout = compact ? 'compact' : 'wide';
        // 紧凑模式下禁用"拖动浮窗"——触屏拖一个贴边的窗口只会和页面滚动抢手势
        window.__adaptiveDragDisabled = compact;

        if (compact) {
            var tight = window.innerHeight <= TIGHT_MAX_H;
            layoutCompact(tight, false);
            // 竖屏档放不下最小棋盘时再降一档：把常驻手牌收进面板槽，把高度让给棋盘
            if (!tight && boardSizePx() < MIN_BOARD - 26) layoutCompact(false, true);
        } else {
            body.classList.remove('layout-tight');
            body.classList.remove('layout-dense');
            applyPlacement(false, false);
            document.documentElement.style.removeProperty('--stage-vh');
            document.documentElement.style.removeProperty('--board-size');
            document.documentElement.style.removeProperty('--dock-max');
            gameScreen.removeAttribute('data-boards');
            var stage = $('.boards-container');
            if (stage) stage.removeAttribute('data-mode');
            /* 桌面档保持 CSS 的"堆叠 + 按 100vh 反推"（见 style.css 第 40 节）。
               试过让桌面也走 updateBoardMode() 并排两块：宽屏"两块同尺寸且 >=280"与
               并排所需的横向空间在 1280/1366 档互相打架（右侧预览浮窗吃掉一截），
               改 tabs 又受纵向预算（~267px）限制 —— 要动就得连门禁契约一起改。
               ⚠️ 已知未解：高度 <=800px 的桌面档，堆叠的第二块棋盘会被贴底手牌压住
               （1366x768 实测 30/36 格点不到，见 docs/FLUENT_UI_2026_09_21.md §10）。 */
        }
    }

    function schedule() {
        if (rafId) return;
        rafId = requestAnimationFrame(function () { rafId = 0; apply(); });
    }

    function boot() {
        bindDock();
        bindBoardTabs();
        observeScreen();
        observeGameChildren();
        observeCardPreview();
        observeFieldMagic();
        observeTurn();
        observeHand();
        window.addEventListener('resize', schedule);
        window.addEventListener('orientationchange', schedule);
        if (window.visualViewport) window.visualViewport.addEventListener('resize', schedule);
        var stage = $('.boards-container');
        if (stage && window.ResizeObserver) {
            new ResizeObserver(function () {
                if (body.classList.contains('layout-compact')) updateBoardMode();
            }).observe(stage);
        }
        apply();
    }

    window.AdaptiveLayout = { apply: apply, schedule: schedule, openDockPanel: openDockPanel, setActiveBoard: setActiveBoard };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 0); });
    } else {
        setTimeout(boot, 0);
    }
})();
