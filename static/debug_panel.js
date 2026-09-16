/* ============================================================================
 * 开发者调试面板（F8）—— 2026-09-16
 * ============================================================================
 * 按 F8 唤出，按钮都是既有的 @_test_event 调试事件（服务端两道门：
 *   ① ENABLE_TEST_EVENTS=1 开关     ② DEBUG_ADMIN_USER_IDS 账号白名单）
 * 面板只在服务端通过 debug_status 明确回复"你被允许"时才出现；否则只弹一句原因，
 * 所以未开启调试的环境（含线上默认配置）里，普通玩家按 F8 什么也看不到。
 *
 * ⚠️ 调试操作的胜负**照常计入战绩**（作者 2026-09-16 明确要求不豁免）。
 * ⚠️ 别把"允许"判断搬到前端：能发这些事件的永远是服务端，
 *    前端这份只是"别让不该看的人看到入口"。
 * ========================================================================== */
(function () {
    if (window.__devDebugPanelLoaded) return;
    window.__devDebugPanelLoaded = true;

    var panel = null;

    function toast(text) {
        if (typeof window.showMessage === 'function') {
            window.showMessage(text, { type: 'warning' });
        } else {
            console.log('[debug]', text);
        }
    }

    function gs() { return window.gameState || {}; }

    function payloadHome() {
        var g = gs();
        return { room_id: g.roomId, player_id: g.playerId };
    }

    // 每一项要么直接发事件，要么带一个输入框（船数 / 卡名 / 次数）
    var ACTIONS = [
        { label: '直接判我胜', ev: 'test_win_game', mode: 'self' },
        { label: '直接判我负', ev: 'test_lose_game', mode: 'self' },
        { label: '塞满全部魔法卡', ev: 'test_add_all_magic_cards', mode: 'self' },
        { label: '改我的船数', ev: 'test_set_player_ships', mode: 'self',
          input: { key: 'ship_count', label: '船数', def: '6' } },
        { label: '改对手船数', ev: 'test_set_opponent_ships', mode: 'self',
          input: { key: 'ship_count', label: '船数', def: '1' } },
        { label: '加一张指定卡', ev: 'test_add_specific_magic_card', mode: 'self',
          input: { key: 'card_name', label: '卡名', def: '失灵！' } },
        { label: '自动攻击 N 次', ev: 'test_auto_attack', mode: 'self',
          input: { key: 'count', label: '次数', def: '1' } },
        { label: '读取双方完整船位', ev: 'test_get_game_state', mode: 'room' },
        { label: '清空所有效果', ev: 'test_clear_all_effects', mode: 'room' },
        { label: '重置本局', ev: 'test_reset_game', mode: 'room' },
        { label: '强制结束回合', ev: 'test_end_turn', mode: 'room' },
        { label: '列出全部魔法卡', ev: 'test_get_magic_cards_list', mode: 'none' },
    ];

    function send(ev, extra, label) {
        var sock = gs().socket;
        if (!sock) { toast('还没连上服务器'); return; }
        var data = {};
        if (payloadHome().room_id) data.room_id = payloadHome().room_id;
        if (payloadHome().player_id) data.player_id = payloadHome().player_id;
        if (extra) { for (var k in extra) data[k] = extra[k]; }
        sock.emit(ev, data, function (res) {
            var msg = (res && (res.message || res.status)) || '无返回';
            console.log('[debug]', ev, res);
            if (ev === 'test_get_game_state') {
                toast('双方船位已打到控制台（F12）'); // 不把船位糊在屏幕上
            } else {
                toast(label + '：' + msg);
            }
        });
    }

    function build() {
        var box = document.createElement('div');
        box.id = 'dev-debug-panel';
        box.style.cssText = 'position:fixed;top:12px;left:12px;z-index:10001;width:250px;'
            + 'max-height:88vh;overflow-y:auto;padding:12px 14px;border-radius:12px;'
            + 'background:rgba(17,24,39,.94);color:#e5e7eb;font-size:13px;'
            + 'box-shadow:0 12px 40px rgba(0,0,0,.45);border:1px solid rgba(248,113,113,.6)';

        var head = document.createElement('div');
        head.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:4px';
        head.innerHTML = '<b style="color:#fca5a5">调试模式</b>';
        var close = document.createElement('button');
        close.textContent = '✕';
        close.style.cssText = 'background:none;border:none;color:#e5e7eb;cursor:pointer;font-size:14px';
        close.onclick = closePanel;
        head.appendChild(close);
        box.appendChild(head);

        var hint = document.createElement('div');
        hint.style.cssText = 'font-size:11px;color:#9ca3af;margin-bottom:10px;line-height:1.5';
        hint.textContent = 'F8 开关 · 结果会打到控制台。本局胜负照常计入战绩。';
        box.appendChild(hint);

        ACTIONS.forEach(function (a) {
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;gap:6px;margin-bottom:6px;align-items:center';
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = a.label;
            btn.style.cssText = 'flex:1;padding:6px 8px;border-radius:7px;cursor:pointer;'
                + 'border:1px solid rgba(148,163,184,.5);background:rgba(30,41,59,.9);color:#e5e7eb;'
                + 'text-align:left;font-size:12px';
            var inp = null;
            if (a.input) {
                inp = document.createElement('input');
                inp.value = a.input.def;
                inp.title = a.input.label;
                inp.style.cssText = 'width:56px;padding:5px;border-radius:6px;border:1px solid rgba(148,163,184,.5);'
                    + 'background:rgba(15,23,42,.9);color:#e5e7eb;font-size:12px';
            }
            btn.onclick = function () {
                var extra = null;
                if (a.input) {
                    extra = {};
                    extra[a.input.key] = (a.input.key === 'card_name')
                        ? String(inp.value || '').trim()
                        : (parseInt(inp.value, 10) || 0);
                }
                send(a.ev, extra, a.label);
            };
            row.appendChild(btn);
            if (inp) row.appendChild(inp);
            box.appendChild(row);
        });

        return box;
    }

    function openPanel() {
        if (panel) return;
        panel = build();
        document.body.appendChild(panel);
    }

    function closePanel() {
        if (panel && panel.parentNode) panel.parentNode.removeChild(panel);
        panel = null;
    }

    function askThenToggle() {
        var sock = gs().socket;
        if (!sock) { toast('还没连上服务器'); return; }
        sock.emit('debug_status', {}, function (res) {
            if (!res || !res.allowed) {
                toast(res && res.enabled
                    ? '调试事件未对你的账号开放（服务端 DEBUG_ADMIN_USER_IDS 白名单）'
                    : '调试事件未启用（服务端 ENABLE_TEST_EVENTS 未开）');
                return;
            }
            openPanel();
        });
    }

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'F8') return;
        e.preventDefault();
        if (panel) { closePanel(); return; }
        askThenToggle();
    });

    // 面板跟着对局走：换房 / 掉线后重连，旧面板里的 room_id 会失效
    window.addEventListener('beforeunload', closePanel);
})();
