/**
 * 战斗音效（SFX）—— 全部用 Web Audio **现场合成**，不依赖任何音频文件。
 *
 * 背景：项目此前全站零音效（唯一的 new Audio() 是 BGM，而 static/music/ 目录
 * 根本不存在，6 条预设路径全 404）。这里用振荡器 + 噪声缓冲合成 9 个音，
 * 既不需要素材，也不会像 BGM 那样静默失败。
 *
 * 用法：window.sfx.play('hit') / setMuted(true) / isMuted()
 * 浏览器自动播放策略：AudioContext 在首次用户手势（pointerdown/keydown/touchstart）
 * 时才创建/恢复，之后所有 play() 都会自动 resume。
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'sfx_muted';
    var ctx = null;
    var muted = false;
    try { muted = localStorage.getItem(STORAGE_KEY) === 'true'; } catch (e) { muted = false; }

    function ensureContext() {
        if (ctx) {
            if (ctx.state === 'suspended' && ctx.resume) { try { ctx.resume(); } catch (e) { /* ignore */ } }
            return ctx;
        }
        var AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return null;
        try { ctx = new AC(); } catch (e) { ctx = null; }
        return ctx;
    }

    function envelope(c, t0, peak, dur) {
        var g = c.createGain();
        var attack = Math.min(0.02, dur / 4);
        g.gain.setValueAtTime(0.0001, t0);
        g.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), t0 + attack);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
        g.connect(c.destination);
        return g;
    }

    function tone(c, t0, o) {
        var osc = c.createOscillator();
        osc.type = o.type || 'sine';
        osc.frequency.setValueAtTime(o.freq, t0);
        if (o.to) osc.frequency.exponentialRampToValueAtTime(o.to, t0 + o.dur);
        osc.connect(envelope(c, t0, o.gain, o.dur));
        osc.start(t0);
        osc.stop(t0 + o.dur + 0.03);
    }

    function noise(c, t0, o) {
        var len = Math.max(1, Math.floor(c.sampleRate * o.dur));
        var buf = c.createBuffer(1, len, c.sampleRate);
        var data = buf.getChannelData(0);
        for (var i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
        var src = c.createBufferSource();
        src.buffer = buf;
        var filt = c.createBiquadFilter();
        filt.type = o.filter || 'lowpass';
        filt.frequency.setValueAtTime(o.from || 1200, t0);
        if (o.to) filt.frequency.exponentialRampToValueAtTime(o.to, t0 + o.dur);
        src.connect(filt);
        filt.connect(envelope(c, t0, o.gain, o.dur));
        src.start(t0);
        src.stop(t0 + o.dur + 0.03);
    }

    var RECIPES = {
        hit: function (c, t) {
            noise(c, t, { dur: 0.22, gain: 0.5, from: 1800, to: 200 });
            tone(c, t, { freq: 140, to: 60, type: 'square', dur: 0.18, gain: 0.32 });
        },
        miss: function (c, t) {
            noise(c, t, { dur: 0.16, gain: 0.22, filter: 'highpass', from: 900, to: 2400 });
            tone(c, t, { freq: 900, to: 500, type: 'sine', dur: 0.12, gain: 0.12 });
        },
        sunk: function (c, t) {
            noise(c, t, { dur: 0.5, gain: 0.5, from: 1200, to: 80 });
            tone(c, t, { freq: 220, to: 55, type: 'sawtooth', dur: 0.45, gain: 0.28 });
        },
        draw: function (c, t) { tone(c, t, { freq: 660, to: 990, type: 'triangle', dur: 0.14, gain: 0.16 }); },
        play_card: function (c, t) {
            noise(c, t, { dur: 0.28, gain: 0.28, filter: 'bandpass', from: 400, to: 2600 });
            tone(c, t, { freq: 520, to: 880, type: 'triangle', dur: 0.2, gain: 0.14 });
        },
        chain: function (c, t) {
            tone(c, t, { freq: 740, type: 'square', dur: 0.1, gain: 0.15 });
            tone(c, t + 0.13, { freq: 990, type: 'square', dur: 0.14, gain: 0.15 });
        },
        turn: function (c, t) {
            tone(c, t, { freq: 520, type: 'sine', dur: 0.18, gain: 0.15 });
            tone(c, t + 0.1, { freq: 780, type: 'sine', dur: 0.22, gain: 0.12 });
        },
        win: function (c, t) {
            [523, 659, 784, 1047].forEach(function (f, i) {
                tone(c, t + i * 0.12, { freq: f, type: 'triangle', dur: 0.26, gain: 0.17 });
            });
        },
        lose: function (c, t) {
            [440, 349, 262].forEach(function (f, i) {
                tone(c, t + i * 0.16, { freq: f, type: 'sawtooth', dur: 0.34, gain: 0.13 });
            });
        }
    };

    function play(name) {
        if (muted) return false;
        var recipe = RECIPES[name];
        if (!recipe) return false;
        var c = ensureContext();
        if (!c) return false;
        try {
            recipe(c, c.currentTime + 0.001);
            return true;
        } catch (e) {
            return false;
        }
    }

    function setMuted(value) {
        muted = !!value;
        try { localStorage.setItem(STORAGE_KEY, muted ? 'true' : 'false'); } catch (e) { /* ignore */ }
        var el = document.getElementById('sfx-muted');
        if (el && el.checked !== muted) el.checked = muted;
    }

    function bindUI() {
        var el = document.getElementById('sfx-muted');
        if (!el) return;
        el.checked = muted;
        el.addEventListener('change', function () { setMuted(el.checked); });
    }

    window.sfx = {
        play: play,
        sounds: Object.keys(RECIPES),
        setMuted: setMuted,
        isMuted: function () { return muted; },
        toggle: function () { setMuted(!muted); return muted; },
        unlock: function () { return !!ensureContext(); }
    };

    ['pointerdown', 'keydown', 'touchstart'].forEach(function (evt) {
        window.addEventListener(evt, function once() {
            ensureContext();
            window.removeEventListener(evt, once);
        }, { once: true });
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindUI);
    } else {
        bindUI();
    }
})();
