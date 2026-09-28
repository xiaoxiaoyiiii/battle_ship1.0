/* =====================================================================
 * 反作弊管理后台（2026-09-20）—— 站长专用运营面板
 * =====================================================================
 * 定位：看全服嫌疑度、逐个玩家查战绩与违规记录、手动解封/加封。
 *
 * ⚠️ **前端隐藏不是安全措施**。真正的门禁在服务端（`api._admin_required()`，
 *    非管理员一律 403）。这里只是"别让普通玩家看到一个点不动的按钮"。
 *
 * ⚠️ 本文件必须能在**没有后端**时静默降级：`/api/admin/me` 拿不到或返回 false
 *    就什么都不做 —— 绝不能在普通玩家页面上弹错。
 * ===================================================================== */

(function () {
    'use strict';

    var modal, listEl, detailEl, searchEl, tabList, tabDetail;
    var allPlayers = [];
    var isAdmin = false;
    var bound = false;

    function $(id) { return document.getElementById(id); }

    function esc(s) {
        // 统一转义：用户名/理由都是**玩家可控输入**，直接拼进 innerHTML 会 XSS
        return String(s === null || s === undefined ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function fmtTime(ts) {
        if (!ts) return '-';
        try {
            var d = new Date(Number(ts) * 1000);
            var p = function (n) { return (n < 10 ? '0' : '') + n; };
            return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
                + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
        } catch (e) { return '-'; }
    }

    function api(path, opts) {
        return fetch(path, Object.assign({
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' }
        }, opts || {})).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) {
                if (!r.ok) { j.__httpError = r.status; }
                return j;
            });
        });
    }

    function levelClass(level) {
        var lv = Number(level) || 0;
        if (lv >= 3) return 'lvl-red';
        if (lv === 2) return 'lvl-orange';
        if (lv === 1) return 'lvl-yellow';
        return 'lvl-green';
    }

    // ---------------------------------------------------------------
    // 列表视图
    // ---------------------------------------------------------------
    function renderList(players) {
        if (!listEl) return;
        if (!players || !players.length) {
            listEl.innerHTML = '<p class="admin-empty">暂无数据。</p>';
            return;
        }
        var html = '<table class="admin-table"><thead><tr>'
            + '<th>玩家</th><th>嫌疑度</th><th>状态</th><th>违规局</th><th></th>'
            + '</tr></thead><tbody>';
        players.forEach(function (p, i) {
            html += '<tr>'
                + '<td>' + esc(p.username || '(已删除)') + '</td>'
                + '<td><b>' + esc(p.suspicion) + '</b></td>'
                + '<td><span class="admin-badge ' + levelClass(p.level) + '">'
                + esc(p.level_name) + '</span>'
                + (p.overridden ? ' <span class="admin-badge lvl-blue">已干预</span>' : '')
                + '</td>'
                + '<td>' + esc(p.match_count || 0) + '</td>'
                + '<td><button type="button" class="btn secondary admin-detail-btn" '
                + 'data-idx="' + i + '">详情</button></td>'
                + '</tr>';
        });
        html += '</tbody></table>';
        listEl.innerHTML = html;

        Array.prototype.forEach.call(
            listEl.querySelectorAll('.admin-detail-btn'),
            function (btn) {
                btn.onclick = function () {
                    var p = players[Number(btn.getAttribute('data-idx'))];
                    if (p) { showDetail(p.user_id, p.username); }
                };
            });
    }

    function applyFilter() {
        var q = (searchEl && searchEl.value || '').trim().toLowerCase();
        if (!q) { renderList(allPlayers); return; }
        renderList(allPlayers.filter(function (p) {
            return String(p.username || '').toLowerCase().indexOf(q) >= 0;
        }));
    }

    function loadList() {
        if (!listEl) return;
        listEl.innerHTML = '<p>加载中…</p>';
        api('/api/admin/suspicion?limit=300').then(function (j) {
            if (!j || j.success !== true) {
                listEl.innerHTML = '<p class="admin-empty">读取失败'
                    + (j && j.error ? '：' + esc(j.error) : '') + '</p>';
                return;
            }
            allPlayers = j.players || [];
            applyFilter();
        }).catch(function () {
            listEl.innerHTML = '<p class="admin-empty">读取失败（网络）。</p>';
        });
    }

    // ---------------------------------------------------------------
    // 详情视图
    // ---------------------------------------------------------------
    function renderDetail(p) {
        if (!detailEl) return;
        if (!p) { detailEl.innerHTML = '<p>没找到这个玩家。</p>'; return; }

        var st = p.stats || {};
        var html = '';

        html += '<div class="admin-head">'
            + '<div class="admin-name">' + esc(p.username || '(已删除)')
            + ' <span class="admin-badge ' + levelClass(p.level) + '">'
            + esc(p.level_name) + '</span></div>'
            + '<div class="admin-sub">嫌疑度 <b>' + esc(p.suspicion) + '</b>'
            + (p.next_threshold > 0 ? '（距下一档还差 ' + esc(p.next_threshold) + '）' : '（已最高档）')
            + '</div></div>';

        // 战绩
        html += '<h4>战绩</h4><div class="admin-stats">'
            + '<span>总胜 ' + esc(st.wins) + '</span>'
            + '<span>总负 ' + esc(st.losses) + '</span>'
            + '<span>胜率 ' + (st.win_rate !== undefined
                ? Math.round(Number(st.win_rate) * 100) + '%' : '-') + '</span>'
            + '<span>排位分 ' + esc(st.rank_points) + '</span>'
            + '<span>排位 ' + esc(st.ranked_wins) + '胜'
            + esc(st.ranked_losses) + '负</span>'
            + '</div>';

        // 当前被禁的能力
        var blocked = p.blocked || [];
        html += '<h4>当前限制</h4>';
        html += blocked.length
            ? '<div class="admin-blocked">' + blocked.map(function (c) {
                var name = { ranked: '排位赛', match: '匹配', room: '房间' }[c] || c;
                return '<span class="admin-badge lvl-red">禁' + esc(name) + '</span>';
            }).join('') + '</div>'
            : '<p class="admin-ok">无限制</p>';

        // 手动处置
        html += '<h4>手动处置</h4><div class="admin-actions">'
            + '<input type="text" id="admin-reason" placeholder="理由（会记入审计日志）" autocomplete="off">'
            + '<div class="admin-btnrow">'
            + '<button type="button" class="btn secondary" id="admin-clear">解除限制</button>'
            + '<button type="button" class="btn secondary" id="admin-set1">禁排位</button>'
            + '<button type="button" class="btn secondary" id="admin-set2">禁匹配</button>'
            + '<button type="button" class="btn secondary" id="admin-set3">禁房间</button>'
            + '</div></div>';

        // 违规记录
        var flags = p.flagged_matches || [];
        html += '<h4>违规记录（' + flags.length + '）</h4>';
        if (flags.length) {
            html += '<div class="admin-flags">';
            flags.slice(0, 30).forEach(function (f) {
                html += '<div class="admin-flag">'
                    + '<span class="admin-badge lvl-orange">' + esc(f.severity) + '</span> '
                    + '<span class="admin-flag-rule">' + esc(f.rule) + '</span>'
                    + '<div class="admin-flag-detail">' + esc(f.detail) + '</div>'
                    + '</div>';
            });
            html += '</div>';
        } else {
            html += '<p class="admin-ok">没有可疑对局记录。</p>';
        }

        // 干预历史（审计）
        var hist = p.override_history || [];
        html += '<h4>干预历史（' + hist.length + '）</h4>';
        if (hist.length) {
            html += '<div class="admin-history">';
            hist.forEach(function (h) {
                var what = h.cleared ? '解除限制'
                    : ('设为 ' + ({ 0: '正常', 1: '禁排位', 2: '禁匹配', 3: '禁房间' }[h.level] || h.level));
                html += '<div class="admin-hist-row">'
                    + '<span>' + esc(fmtTime(h.created_at)) + '</span>'
                    + '<span>' + esc(what) + '</span>'
                    + '<span>' + esc(h.reason || '-') + '</span>'
                    + '<span>' + esc(h.actor || '-') + '</span>'
                    + '</div>';
            });
            html += '</div>';
        } else {
            html += '<p class="admin-ok">没有干预记录。</p>';
        }

        detailEl.innerHTML = html;
        bindDetailActions(p.user_id);
    }

    function bindDetailActions(uid) {
        function override(payload) {
            var reasonEl = $('admin-reason');
            payload.reason = (reasonEl && reasonEl.value || '').trim();
            api('/api/admin/player/' + encodeURIComponent(uid) + '/override', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(function (j) {
                if (j && j.success === true) {
                    renderDetail(j.player);
                    loadList();              // 列表也要跟着变
                } else {
                    alert('操作失败：' + ((j && j.error) || '未知错误'));
                }
            }).catch(function () { alert('操作失败（网络）'); });
        }

        var c = $('admin-clear'); if (c) c.onclick = function () { override({ cleared: true }); };
        var s1 = $('admin-set1'); if (s1) s1.onclick = function () { override({ level: 1 }); };
        var s2 = $('admin-set2'); if (s2) s2.onclick = function () { override({ level: 2 }); };
        var s3 = $('admin-set3'); if (s3) s3.onclick = function () { override({ level: 3 }); };
    }

    function showDetail(uid, username) {
        if (!modal) return;
        modal.classList.remove('hidden');
        switchTab('detail');
        if (detailEl) {
            detailEl.innerHTML = '<p>加载中…</p>';
            if (username) { /* 标题已有名字，无需额外处理 */ }
        }
        if (!uid) { renderDetail(null); return; }
        api('/api/admin/player/' + encodeURIComponent(uid)).then(function (j) {
            if (j && j.success === true) { renderDetail(j.player); }
            else {
                detailEl.innerHTML = '<p class="admin-empty">读取失败：'
                    + esc((j && j.error) || '未知错误') + '</p>';
            }
        }).catch(function () {
            detailEl.innerHTML = '<p class="admin-empty">读取失败（网络）。</p>';
        });
    }

    function switchTab(which) {
        var isList = (which === 'list');
        if (tabList) tabList.classList.toggle('active', isList);
        if (tabDetail) tabDetail.classList.toggle('active', !isList);
        var vList = $('admin-view-list'), vDetail = $('admin-view-detail');
        if (vList) vList.classList.toggle('hidden', !isList);
        if (vDetail) vDetail.classList.toggle('hidden', isList);
        if (isList) { loadList(); }
    }

    // ---------------------------------------------------------------
    // 初始化
    // ---------------------------------------------------------------
    function bind() {
        if (bound) return;
        bound = true;
        modal = $('admin-modal');
        listEl = $('admin-list');
        detailEl = $('admin-detail');
        searchEl = $('admin-search');
        tabList = $('admin-tab-list');
        tabDetail = $('admin-tab-detail');
        if (!modal) return;

        var close = $('admin-modal-close');
        if (close) close.onclick = function () { modal.classList.add('hidden'); };
        modal.addEventListener('click', function (e) {
            if (e.target === modal) modal.classList.add('hidden');
        });
        if (tabList) tabList.onclick = function () { switchTab('list'); };
        if (tabDetail) tabDetail.onclick = function () { switchTab('detail'); };
        if (searchEl) searchEl.oninput = applyFilter;
        var refresh = $('admin-refresh');
        if (refresh) refresh.onclick = loadList;
    }

    function injectEntry() {
        // 在设置里加一个入口按钮（不给普通玩家看）
        if ($('admin-open-btn')) return;
        var host = document.querySelector('.settings-nav') || document.querySelector('#settings-modal .modal-content');
        if (!host) return;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.id = 'admin-open-btn';
        btn.className = 'settings-nav-item';
        btn.innerHTML = '<span class="pf-nav-ic">🛡️</span>反作弊管理';
        btn.onclick = function () {
            var sm = $('settings-modal');
            if (sm) sm.classList.add('hidden');
            modal.classList.remove('hidden');
            switchTab('list');
        };
        host.appendChild(btn);
    }

    function init() {
        // 先问服务端"我是不是管理员" —— 拿不到就整个隐藏（普通玩家路径零开销）
        api('/api/admin/me').then(function (j) {
            if (!j || j.is_admin !== true) return;   // 静默退出，不报错
            isAdmin = true;
            bind();
            injectEntry();
        }).catch(function () { /* 静默：普通玩家这里会 401/403，不该弹错 */ });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // 供 game.js 调用：在"别人/自己的个人信息卡"上点头像时跳到管理详情
    window.battleshipAdmin = {
        isAdmin: function () { return isAdmin; },
        openPlayer: function (uid) { if (isAdmin) showDetail(uid); }
    };
})();
