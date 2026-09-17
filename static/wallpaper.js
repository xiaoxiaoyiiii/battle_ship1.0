/**
 * 动态壁纸引擎（Wallpaper Engine / 本地视频 / 图片）
 * ============================================================
 * 目标：把玩家自己在 Wallpaper Engine 里买的动态壁纸，变成游戏界面的背景。
 *
 * 三条导入通道（能力不同，界面上分开写清楚）：
 *   1) 扫描本机壁纸库   —— 只有本机（localhost）访问时才可用
 *   2) 粘贴本机路径     —— 同上；可给壁纸文件夹、装壁纸的父目录，或单个视频文件
 *   3) 粘贴直链         —— 任何环境都能用（浏览器直接去取那个地址，不经服务端）
 *
 * 几个刻意的取舍：
 *   · 视频一律 muted。带声音的"壁纸"会盖住战斗音效，而且浏览器不允许
 *     未静音的自动播放。
 *   · 自动播放被浏览器拦下时不报错了事：等玩家第一次交互（点一下页面）再补播，
 *     同时在设置面板里写明发生了什么 —— 静默失败最难排查。
 *   · 页面切到后台就暂停视频。一张 4K 壁纸在后台空转，风扇会先抗议。
 *   · prefers-reduced-motion 的用户默认静止播放（暂停画面），仍可手动播放。
 *   · 状态存 localStorage，和主题 / 主色同一个套路，服务端不存任何偏好。
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'battleship_wallpaper';
    var LOCAL_HEADER = 'X-Battleship-Wallpaper';
    var OPTION_KEYS = ['opacity', 'dim', 'blur', 'fit', 'paused'];

    var DEFAULTS = {
        src: '',
        kind: '',
        title: '',
        id: '',
        opacity: 100,   // 壁纸整体不透明度（%）
        dim: 35,        // 压暗遮罩强度（%），文字可读性靠它
        blur: 0,        // 模糊半径（px）
        fit: 'cover',   // cover / contain / fill
        paused: false
    };

    var state = Object.assign({}, DEFAULTS);
    var els = {};
    var items = [];
    var listeners = [];
    var ready = false;
    var retryArmed = false;
    var lastError = '';

    function $(id) { return document.getElementById(id); }

    function snapshot() { return Object.assign({}, state); }

    function emit() {
        var snap = snapshot();
        listeners.forEach(function (fn) {
            try { fn(snap); } catch (e) { /* 单个订阅者出错不影响其他 */ }
        });
    }

    function readStore() {
        try {
            var raw = window.localStorage.getItem(STORAGE_KEY);
            if (!raw) return;
            var saved = JSON.parse(raw);
            if (saved && typeof saved === 'object') state = Object.assign({}, DEFAULTS, saved);
        } catch (e) {
            // 存储被禁用或数据损坏时静默回到默认值：背景不该让整页报错
            state = Object.assign({}, DEFAULTS);
        }
    }

    function writeStore() {
        try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        } catch (e) { /* 无痕模式：本次会话内仍然有效 */ }
    }

    function isActive() {
        return !!(state.src && (state.kind === 'video' || state.kind === 'image'));
    }

    function reduceMotion() {
        return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    }

    function wantsPlayback() {
        return isActive() && state.kind === 'video' && !state.paused
            && !document.hidden && !reduceMotion();
    }

    // ---------------- 渲染 ----------------

    function applyVars() {
        var root = document.documentElement;
        root.style.setProperty('--wp-opacity', String(state.opacity / 100));
        root.style.setProperty('--wp-dim', String(state.dim / 100));
        root.style.setProperty('--wp-blur', state.blur + 'px');
        root.style.setProperty('--wp-fit', state.fit === 'contain' ? 'contain'
            : (state.fit === 'fill' ? 'fill' : 'cover'));
    }

    function detachVideo() {
        if (!els.video.getAttribute('src')) return;
        try { els.video.pause(); } catch (e) { /* ignore */ }
        els.video.removeAttribute('src');
        // 不 load() 的话，卸掉 src 的视频仍会持有解码器
        try { els.video.load(); } catch (e) { /* ignore */ }
    }

    function bindMedia() {
        if (!els.video || !els.image) return;
        if (state.kind === 'video') {
            if (els.video.getAttribute('src') !== state.src) els.video.setAttribute('src', state.src);
            els.video.classList.remove('hidden');
        } else {
            els.video.classList.add('hidden');
            detachVideo();
        }
        if (state.kind === 'image') {
            if (els.image.getAttribute('src') !== state.src) els.image.setAttribute('src', state.src);
            els.image.classList.remove('hidden');
        } else {
            els.image.classList.add('hidden');
            // 这里用 removeAttribute 而不是 src = ''：后者会触发一次 error 事件
            if (els.image.getAttribute('src')) els.image.removeAttribute('src');
        }
    }

    function syncPlayback() {
        if (!els.video || state.kind !== 'video') return;
        if (wantsPlayback()) {
            var p = els.video.play();
            if (p && typeof p.catch === 'function') {
                p.catch(function (err) {
                    // play() 被拒有两种截然不同的原因，必须分开说：
                    //   NotSupportedError / 元素已带 MediaError → 文件根本解不了
                    //   NotAllowedError（自动播放策略）→ 文件没问题，等玩家点一下即可
                    // 以前一律当成"自动播放被拦"，于是壁纸文件坏掉时会让玩家
                    // 反复点击一个永远播不出来的东西。
                    if ((err && err.name === 'NotSupportedError') || (els.video && els.video.error)) {
                        onMediaError();
                        return;
                    }
                    lastError = '浏览器拦下了自动播放，点一下页面即可开始播放';
                    armRetry();
                    render();
                });
            }
        } else {
            try { els.video.pause(); } catch (e) { /* ignore */ }
        }
    }

    function armRetry() {
        if (retryArmed) return;
        retryArmed = true;
        var retry = function () {
            window.removeEventListener('pointerdown', retry);
            window.removeEventListener('keydown', retry);
            retryArmed = false;
            lastError = '';
            syncPlayback();
            render();
        };
        window.addEventListener('pointerdown', retry);
        window.addEventListener('keydown', retry);
    }

    // 壁纸文件被删了 / 直链打不开 —— 不处理的话玩家只会看到一片空白，
    // 完全不知道发生了什么
    function onMediaError() {
        if (!isActive()) return;
        lastError = '壁纸加载失败：文件可能已被删除，或这条直链不允许直接访问（跨域）';
        renderStatus();
    }

    function render() {
        var layer = els.layer;
        if (!layer) return;
        var active = isActive();
        layer.setAttribute('data-kind', active ? state.kind : 'none');
        document.documentElement.classList.toggle('has-wallpaper', active);
        applyVars();
        bindMedia();

        if (els.pauseBtn) {
            els.pauseBtn.textContent = state.paused ? '▶ 继续播放' : '⏸ 暂停播放';
            els.pauseBtn.disabled = !(active && state.kind === 'video');
        }
        if (els.clearBtn) els.clearBtn.disabled = !active;
        if (els.nowPlaying) {
            els.nowPlaying.textContent = active
                ? '当前壁纸：' + (state.title || '未命名') + (state.kind === 'video' ? '（视频）' : '（图片）')
                : '当前壁纸：无';
        }
        renderList();
        renderStatus();
        emit();
    }

    function renderStatus(extra) {
        if (!els.status) return;
        var parts = [];
        if (extra) parts.push(extra);
        if (lastError) parts.push('⚠️ ' + lastError);
        if (isActive() && state.kind === 'video' && reduceMotion()) {
            parts.push('系统开启了「减少动态效果」，视频默认静止；点「继续播放」可手动播放。');
        }
        els.status.textContent = parts.join('　');
        els.status.className = 'muted-hint wp-status' + (lastError ? ' wp-status-warn' : '');
    }

    function formatSize(bytes) {
        var n = Number(bytes) || 0;
        if (n <= 0) return '';
        if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' KB';
        return (n / 1024 / 1024).toFixed(1) + ' MB';
    }

    function renderList() {
        var box = els.list;
        if (!box) return;
        if (!items.length) {
            box.innerHTML = '';
            return;
        }
        box.innerHTML = '';
        items.forEach(function (item) {
            var card = document.createElement('button');
            card.type = 'button';
            card.className = 'wp-item' + (item.supported ? '' : ' wp-item-off')
                + (item.id === state.id ? ' active' : '');
            card.dataset.id = item.id;

            var thumb = document.createElement('div');
            thumb.className = 'wp-thumb';
            if (item.preview_url) {
                var img = document.createElement('img');
                img.loading = 'lazy';
                img.alt = item.title || '';
                img.src = item.preview_url;
                thumb.appendChild(img);
            } else {
                thumb.textContent = item.supported ? (item.kind === 'video' ? '🎬' : '🖼') : '🚫';
            }
            card.appendChild(thumb);

            var meta = document.createElement('div');
            meta.className = 'wp-meta';
            var name = document.createElement('span');
            name.className = 'wp-name';
            name.textContent = item.title || item.id;
            meta.appendChild(name);
            var note = document.createElement('span');
            note.className = 'wp-note';
            if (!item.supported) {
                note.textContent = item.reason || '无法在网页播放';
            } else {
                note.textContent = (item.kind === 'video' ? '视频' : '图片')
                    + (formatSize(item.size) ? ' · ' + formatSize(item.size) : '')
                    + (item.id === state.id ? ' · 使用中' : '');
            }
            meta.appendChild(note);
            card.appendChild(meta);

            if (!item.supported) {
                card.disabled = true;
                card.title = item.reason || '';
            } else {
                card.title = '点击设为背景壁纸';
                card.addEventListener('click', function () {
                    apply({ src: item.media_url, kind: item.kind, title: item.title, id: item.id, paused: false });
                    renderStatus('已应用「' + item.title + '」');
                });
            }
            box.appendChild(card);
        });
    }

    // ---------------- 对外接口 ----------------

    function apply(next) {
        state = Object.assign({}, state, next || {});
        writeStore();
        render();
        syncPlayback();
        return snapshot();
    }

    function setOption(key, value) {
        if (OPTION_KEYS.indexOf(key) < 0) return snapshot();
        var next = {};
        next[key] = value;
        return apply(next);
    }

    function clear() {
        state = Object.assign({}, state, { src: '', kind: '', title: '', id: '' });
        writeStore();
        render();
        syncPlayback();
        lastError = '';
        renderStatus('已恢复默认背景');
        return snapshot();
    }

    function togglePause() {
        if (!(isActive() && state.kind === 'video')) return snapshot();
        return apply({ paused: !state.paused });
    }

    function setItems(list, note) {
        items = Array.isArray(list) ? list.slice() : [];
        renderList();
        renderStatus(note);
    }

    function refreshList(force) {
        if (!els.list) return Promise.resolve([]);
        els.list.innerHTML = '';
        renderStatus('正在扫描本机壁纸库…');
        // force 只在玩家明确点「扫描」时用：每次打开面板都强制重扫，
        // 壁纸库大的机器会白等几秒（服务端本身有 20 秒缓存）。
        return fetch('/api/wallpapers' + (force ? '?refresh=1' : ''))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.available) {
                    items = [];
                    renderList();
                    renderStatus(data.reason || '本机扫描不可用');
                    return [];
                }
                var usable = (data.items || []).filter(function (it) { return it.supported; });
                setItems(data.items || [], data.reason
                    || ('找到 ' + usable.length + ' 张可用的壁纸' + (data.dirs ? '（来自 ' + data.dirs + ' 个创意工坊目录）' : '')));
                return items;
            })
            .catch(function () {
                renderStatus('扫描失败：无法连接到服务端');
                return [];
            });
    }

    function importPath(path) {
        if (!path) return Promise.resolve(false);
        renderStatus('正在读取 ' + path + ' …');
        return fetch('/api/wallpaper/scan_path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Battleship-Wallpaper': '1' },
            body: JSON.stringify({ path: path })
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (!res.ok || !res.data.success) {
                    renderStatus('导入失败：' + ((res.data && res.data.error) || '未知错误'));
                    return false;
                }
                setItems(res.data.items || [], '导入成功，共 ' + (res.data.items || []).length + ' 张，点一张试试');
                return true;
            })
            .catch(function () {
                renderStatus('导入失败：无法连接到服务端');
                return false;
            });
    }

    function importUrl(url) {
        var raw = String(url || '').trim();
        if (!raw) return false;
        if (!/^(https?:)?\/\//i.test(raw) && raw.charAt(0) !== '/') {
            renderStatus('直链需要以 http:// 或 https:// 开头');
            return false;
        }
        var path = raw.split('?')[0].split('#')[0].toLowerCase();
        var video = /\.(mp4|webm|m4v|ogv)$/.test(path);
        var image = /\.(gif|apng|png|jpg|jpeg|webp|bmp|avif)$/.test(path);
        if (!video && !image) {
            renderStatus('认不出这个地址的格式，请用 .mp4 / .webm / .gif / .png / .jpg 结尾的直链');
            return false;
        }
        var kind = video ? 'video' : 'image';
        apply({ src: raw, kind: kind, title: raw.split('/').pop() || raw, id: '', paused: false });
        renderStatus('已应用直链壁纸（格式判断为' + (video ? '视频' : '图片') + '）');
        return true;
    }

    function getStatus() {
        return {
            active: isActive(),
            kind: state.kind,
            src: state.src,
            title: state.title,
            paused: state.paused,
            playing: !!(els.video && !els.video.paused && isActive() && state.kind === 'video'),
            opacity: state.opacity,
            dim: state.dim,
            blur: state.blur,
            fit: state.fit,
            items: items.length,
            usableItems: items.filter(function (it) { return it.supported; }).length,
            lastError: lastError,
            reducedMotion: reduceMotion()
        };
    }

    // ---------------- 设置面板绑定 ----------------

    function bindRange(id, displayId, key, suffix) {
        var input = $(id);
        if (!input) return;
        var display = $(displayId);
        function paint() { if (display) display.textContent = input.value + suffix; }
        input.value = state[key];
        paint();
        input.addEventListener('input', function () {
            paint();
            setOption(key, Number(input.value));
        });
    }

    function bindUI() {
        bindRange('wp-opacity', 'wp-opacity-display', 'opacity', '%');
        bindRange('wp-dim', 'wp-dim-display', 'dim', '%');
        bindRange('wp-blur', 'wp-blur-display', 'blur', 'px');

        if (els.fit) {
            els.fit.value = state.fit;
            els.fit.addEventListener('change', function () { setOption('fit', els.fit.value); });
        }
        if (els.scanBtn) {
            els.scanBtn.addEventListener('click', function () { refreshList(true); });
        }
        if (els.pathBtn && els.pathInput) {
            els.pathBtn.addEventListener('click', function () { importPath(els.pathInput.value.trim()); });
            els.pathInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); importPath(els.pathInput.value.trim()); }
            });
        }
        if (els.urlBtn && els.urlInput) {
            els.urlBtn.addEventListener('click', function () { importUrl(els.urlInput.value); });
            els.urlInput.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); importUrl(els.urlInput.value); }
            });
        }
        if (els.pauseBtn) els.pauseBtn.addEventListener('click', function () { togglePause(); });
        if (els.clearBtn) els.clearBtn.addEventListener('click', function () { clear(); });

        // 导航栏的 🎬 按钮：打开设置并落在「动态壁纸」分区
        var navBtn = $('wallpaper-btn');
        if (navBtn) {
            navBtn.addEventListener('click', function () {
                // ⚠️ 2026-09-17 设置页改「左导航 + 分区」后，壁纸区块默认**不在文档流里**
                // （默认停在「外观与主题」）。只 remove('hidden') + scrollIntoView 的话，
                // 玩家点 🎬 会看到「外观与主题」、壁纸设置一个都看不见 ——
                // 表现是「点壁纸按钮什么也没发生」。
                // 切分区只由 game.js 的 openSettingsModal 那一份实现负责（它是顶层函数，
                // 本文件是普通脚本，能直接调）；取不到时才退回点它自己的导航项。
                if (typeof openSettingsModal === 'function') {
                    openSettingsModal('wp');
                } else {
                    var modal = $('settings-modal');
                    if (modal) modal.classList.remove('hidden');
                    var wpNav = document.querySelector('.settings-nav-item[data-pane="wp"]');
                    if (wpNav) wpNav.click();
                }
                var section = $('wp-section');
                if (section && section.scrollIntoView) section.scrollIntoView({ block: 'start' });
                refreshList();
            });
        }

        document.addEventListener('visibilitychange', function () { syncPlayback(); });
        window.addEventListener('resize', function () { /* 尺寸交给 CSS，这里只需重算播放状态 */ syncPlayback(); });
    }

    function init() {
        if (ready) return;
        ready = true;
        els = {
            layer: $('wallpaper-layer'),
            video: $('wallpaper-video'),
            image: $('wallpaper-image'),
            list: $('wp-list'),
            status: $('wp-status'),
            nowPlaying: $('wp-now-playing'),
            pauseBtn: $('wp-toggle-play'),
            clearBtn: $('wp-clear'),
            scanBtn: $('wp-scan'),
            fit: $('wp-fit'),
            pathInput: $('wp-path'),
            pathBtn: $('wp-path-import'),
            urlInput: $('wp-url'),
            urlBtn: $('wp-url-import')
        };
        readStore();
        if (els.video) {
            els.video.muted = true;
            els.video.loop = true;
            els.video.playsInline = true;
            els.video.setAttribute('muted', '');
            els.video.setAttribute('playsinline', '');
            els.video.setAttribute('webkit-playsinline', '');
            els.video.addEventListener('error', onMediaError);
        }
        if (els.image) els.image.addEventListener('error', onMediaError);
        bindUI();
        render();
        syncPlayback();
    }

    window.wallpaperEngine = {
        init: init,
        apply: apply,
        clear: clear,
        setOption: setOption,
        togglePause: togglePause,
        isActive: isActive,
        getStatus: getStatus,
        getItems: function () { return items.slice(); },
        refreshList: refreshList,
        importPath: importPath,
        importUrl: importUrl,
        onChange: function (fn) { if (typeof fn === 'function') listeners.push(fn); },
        get state() { return snapshot(); },
        DEFAULTS: DEFAULTS,
        STORAGE_KEY: STORAGE_KEY,
        LOCAL_HEADER: LOCAL_HEADER
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
