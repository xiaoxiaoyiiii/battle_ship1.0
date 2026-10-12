// Phase 8：从 game.js 原样迁出；作为经典脚本共享页面作用域。
// ==================== 首页面板（2026-09-27 首页 C 化） ====================
//
// 首页三栏里，除了模式入口，其余全是**只读展示位**：
//   左栏 = 指挥官名片（名字 / 段位 / 等级 / 战绩）
//   中栏 = 全服热门卡（5 张）
//   右栏 = 最近解锁 / 生涯数据 / 段位阶梯 / 在线情况
//
// 数据源**全部是既有接口**，本轮只新增了一个只读聚合 `/api/home_stats`（见 server.py）：
//   `/api/profile`        → profile.username / rank_info / level_info / wins / losses / *_streak
//   `/api/achievements`   → 12 枚徽章（unlocked / unlocked_at / requirement / group）
//   `/api/rank_constants` → tiers + start_points_of_tier（阶梯的顺序与阈值）
//   `/api/card_usage`     → 全服累计使用次数（热门卡排序；新库可能全 0）
//   `/api/home_stats`     → 在线 / 休闲队列 / 排位队列 / 大厅房间
//
// ⚠️ 四条规矩（每一条都对应本项目踩过的形状）：
//   ① **先给骨架、再填数据**：每个块在取数前就已经是占位（"—"），失败也保持占位 ——
//      首页布局绝不随接口成败变化（"取数失败 → 整块消失"的观感事故）。
//   ② **各块独立 catch**：一个接口挂了不许拖累别的块。
//   ③ **首页不许 `lobby_subscribe`**：队列/房间数走只读的 `/api/home_stats` ——
//      订阅会把停在首页的人算进"在大厅"（详细理由写在 server.py 那个路由的注释里）。
//   ④ **前端不重算段位/等级**：`label` / `points` / `to_next` / `level_info` 一律照抄
//      服务端（曲线只有那一边一份实现）。这里只做"取哪个字段、怎么排版"。
const HOME_ACH_ROWS = 4;          // 「最近解锁」显示几行
const HOME_HOT_ROWS = 5;          // 「热门卡」显示几张
const HOME_LADDER_ROWS = 4;       // 「段位阶梯」开几档（当前档居中；示意稿 C 是 4 行）

let homeRankConstants = null;     // 段位表（/api/rank_constants 的原样返回）
let homeStaticLoaded = false;     // 段位表 + 卡表只拉一次（它们几乎不变）

/** 首页用的小工具：安全写文本（元素不存在就直接跳过 —— 游客态少几个节点也不许报错）。 */
function homeText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

/** 首页用的取数：任何失败都退成 null（调用方一律按"没有数据"处理，不抛不报错）。 */
function homeFetchJSON(url) {
    return fetch(url, { headers: { 'Accept': 'application/json' } })
        .then(r => (r.ok ? r.json() : null))
        .catch(() => null);
}

/** 左栏指挥官名片。游客（没有 profile.username）= "登录后记录…"态，不是空卡。 */
function renderHomeCommander(profile) {
    const card = document.getElementById('home-commander');
    const btn = document.getElementById('cmdr-card-btn');
    if (!card) return;
    const p = profile || {};
    if (!p.username) {
        homeText('cmdr-name', '游客');
        homeText('cmdr-sub', '登录后记录段位 · 等级 · 战绩');
        card.setAttribute('data-guest', '1');
        if (btn) btn.classList.add('hidden');
        return;
    }
    card.removeAttribute('data-guest');
    homeText('cmdr-name', p.username);

    const rank = p.rank_info || null;
    const tierEl = document.getElementById('cmdr-tier');
    if (tierEl) {
        // 段位文案由服务端给（tier_name + subs 的 sub）—— 前端不自己拼罗马数字
        const text = rank && rank.tier_name ? (rank.tier_name + (rank.sub || '')) : '';
        if (text) { tierEl.textContent = text; tierEl.classList.remove('hidden'); }
        else tierEl.classList.add('hidden');
    }
    const sub = [];
    if (rank && isFinite(Number(rank.points))) {
        sub.push(Number(rank.points) + ' 分');
        if (rank.to_next != null && isFinite(Number(rank.to_next))) {
            sub.push('距下一小段 ' + Number(rank.to_next) + ' 分');
        } else {
            sub.push(rank.is_admiral ? '大舰长' : '已到顶段');
        }
    }
    if (p.level_info && p.level_info.level) sub.push('Lv.' + p.level_info.level);
    homeText('cmdr-sub', sub.length ? sub.join(' · ') : '登录后记录段位 · 等级 · 战绩');

    const w = Number(p.wins || 0), l = Number(p.losses || 0);
    homeText('cmdr-record', w + ' 胜 ' + l + ' 负');
    homeText('cmdr-streak', Number(p.longest_streak || 0) + ' 场');
    // 累计击沉：来自 /api/profile 的 counters.sunk_total（库里一直在记，本轮才随名片下发）。
    // 拿不到就"—" —— 不拿胜率去凑这一行（示意稿 C 的第三行就是累计击沉）。
    const counters = p.counters || null;
    homeText('cmdr-winrate',
        (counters && isFinite(Number(counters.sunk_total))) ? (Number(counters.sunk_total) + ' 艘') : '—');
    if (btn) btn.classList.remove('hidden');
}

/** 右栏「生涯数据」：只用 profile 里现成的四个数，不做任何推算。
    游客态**不许显示 0** —— 0 胜 0 负对游客是"假数据"（他根本没打过），一律"—"。 */
function renderHomeStats(profile) {
    const p = profile || {};
    if (!p.username) {
        ['home-stat-winrate', 'home-stat-matches', 'home-stat-streak', 'home-stat-best']
            .forEach(id => homeText(id, '—'));
        return;
    }
    const w = Number(p.wins || 0), l = Number(p.losses || 0);
    homeText('home-stat-winrate', (w + l) > 0 ? Math.round(w * 100 / (w + l)) + '%' : '—');
    homeText('home-stat-matches', String(w + l));
    homeText('home-stat-streak', String(Number(p.current_streak || 0)));
    homeText('home-stat-best', String(Number(p.longest_streak || 0)));
}

/** 右栏「最近解锁」：已解锁按时间倒序，不够 4 行时用"离得最近的未解锁"补齐。 */
function renderHomeAchievements(data) {
    const box = document.getElementById('home-ach-list');
    if (!box) return;
    const list = (data && data.achievements) || [];
    // 游客（/api/achievements 401）不是"故障"，别写成"暂不可用" —— 那是给接口挂了用的文案
    if (!list.length) {
        box.innerHTML = '<div class="ach-empty">'
            + (window.__USERNAME ? '徽章暂不可用' : '登录后显示徽章') + '</div>';
        return;
    }
    const unlocked = list.filter(a => a.unlocked)
        .sort((a, b) => Number(b.unlocked_at || 0) - Number(a.unlocked_at || 0));
    const rows = unlocked.slice(0, HOME_ACH_ROWS);
    for (const a of list) {           // 补齐：未解锁的按服务端给的顺序取（= 由易到难）
        if (rows.length >= HOME_ACH_ROWS) break;
        if (!a.unlocked) rows.push(a);
    }
    box.innerHTML = rows.map(a => {
        // demo 的写法：**未解锁也画这个徽章自己的图标**（灰一档），不用锁头 ——
        // 锁头会把四行变成四个一样的图标，看的人认不出是哪几枚。
        const glyph = PROFILE_BADGE_GLYPH[a.group] || '🏅';
        const tip = escapeHtml(a.requirement || a.desc || '');
        return '<div class="ach-row' + (a.unlocked ? '' : ' locked') + '">'
            + '<span class="ach-badge" aria-hidden="true">' + glyph + '</span>'
            + '<div class="ach-txt">'
            + '<div class="ach-name">' + escapeHtml(a.name) + '</div>'
            + '<div class="ach-desc" title="' + tip + '">' + tip + '</div>'
            + '</div>'
            + '<span class="ach-when">' + (a.unlocked ? '已解锁' : '未解锁') + '</span>'
            + '</div>';
    }).join('');
}

/** 右栏「段位阶梯」：以当前档居中开窗（高段在上、已过的在下标绿点）。 */
function renderHomeLadder(constants, rankInfo) {
    const box = document.getElementById('home-ladder');
    if (!box) return;
    const tiers = (constants && constants.tiers) || [];
    if (!tiers.length) { box.innerHTML = '<div class="li">段位表暂不可用</div>'; return; }
    const start = (constants && constants.start_points_of_tier) || {};
    const curIdx = (rankInfo && isFinite(Number(rankInfo.tier_index))) ? Number(rankInfo.tier_index) : -1;
    const center = curIdx >= 0 ? curIdx : 0;
    let to = Math.min(tiers.length, center + Math.ceil(HOME_LADDER_ROWS / 2));
    let from = Math.max(0, to - HOME_LADDER_ROWS);
    to = Math.min(tiers.length, from + HOME_LADDER_ROWS);
    const rows = [];
    for (let i = to - 1; i >= from; i--) {              // 高段在上
        const t = tiers[i];
        const isNow = i === curIdx;
        const cls = isNow ? ' now' : (curIdx >= 0 && i < curIdx ? ' done' : '');
        let pts = '';
        if (isNow && rankInfo && isFinite(Number(rankInfo.points))) pts = String(Number(rankInfo.points));
        else if (start[t.id] != null) pts = Number(start[t.id]) + '+';
        rows.push('<div class="li' + cls + '"><i></i>' + escapeHtml(t.name || t.id)
            + '<span class="n">' + (pts || '—') + '</span></div>');
    }
    box.innerHTML = rows.join('');
}

/** 右栏「在线情况」：只读聚合接口。取不到就保持"—"（不消失）。 */
function renderHomeOnline(data) {
    const d = data || {};
    const q = d.queue || null;
    homeText('home-queue-casual', (q && isFinite(Number(q.casual))) ? Number(q.casual) + ' 人' : '—');
    homeText('home-queue-ranked', (q && isFinite(Number(q.ranked))) ? Number(q.ranked) + ' 人' : '—');
    homeText('home-lobby-rooms', isFinite(Number(d.lobby_rooms)) ? Number(d.lobby_rooms) + ' 间' : '—');
    // 在线人数那一格平时由页面尾部的内联脚本每 10 秒刷（它带数字滚动动画）；
    // 这里只是让首次进入**立刻**有值，不等那 10 秒的第一次定时。
    // 顶栏那颗胶囊也一起写（同一份数字，不加第二个接口）。
    if (isFinite(Number(d.online_count))) {
        homeText('online-count', String(Number(d.online_count)));
        homeText('online-count-nav', String(Number(d.online_count)));
    }
}

// 热门卡的小徽记作为图片加载失败时的占位。
const HOME_CARD_GLYPH = {
    '神威！': '🌀', '失灵！': '⛔', '轰炸': '💥', '硫磺火焰': '🔥', '增援': '⚓',
    '桃园结义': '🌿', '恶魔契约': '🎲', '看破！': '👁', '冻结！': '❄', '八方来财': '🧧',
    '探测雷达': '📡', '仁王之盾': '🛡', '死者苏生': '⚰', '绝处逢生': '🕯', '平等条约': '⚖',
};

/** 中栏「全服热门卡」：按 /api/card_usage 排序；一次都没人用过时按速阶各取一张。 */
function renderHomeHotCards(usage) {
    const box = document.getElementById('home-hot-cards');
    const note = document.getElementById('home-hot-note');
    if (!box) return;
    const cards = Array.isArray(window.magicCards) ? window.magicCards : [];
    // 卡池中 `失灵！` 有重复条目，榜单按卡名去重。
    const unique = [];
    const seen = new Set();
    for (const c of cards) { if (c && c.name && !seen.has(c.name)) { seen.add(c.name); unique.push(c); } }
    if (!unique.length) { box.innerHTML = '<div class="ach-empty">卡表暂不可用</div>'; return; }
    if (note) {
        const field = unique.filter(c => c.type === '场地').length;
        note.textContent = unique.length + ' 张魔法卡 · 场地 ' + field + ' 张 · 普通 ' + (unique.length - field) + ' 张';
    }
    const uses = (usage && usage.usage) || {};
    const anyUse = unique.some(c => Number(uses[c.name] || 0) > 0);
    let picks;
    if (anyUse) {
        picks = unique.slice().sort((a, b) => {
            const d = Number(uses[b.name] || 0) - Number(uses[a.name] || 0);
            return d !== 0 ? d : String(a.name).localeCompare(String(b.name));
        }).slice(0, HOME_HOT_ROWS);
    } else {
        // 新库（或全服都没人用过卡）：按速阶 1/2/3 轮着取，页面不至于空着
        const bySpeed = { 1: [], 2: [], 3: [] };
        unique.forEach(c => { const s = Number(c.speed); if (bySpeed[s]) bySpeed[s].push(c); });
        picks = [];
        for (let i = 0; picks.length < HOME_HOT_ROWS && i < 3; i++) {
            [1, 2, 3].forEach(s => { if (bySpeed[s][i] && picks.length < HOME_HOT_ROWS) picks.push(bySpeed[s][i]); });
        }
    }
    box.innerHTML = picks.map(c => {
        const speed = Math.min(3, Math.max(0, Number(c.speed) || 0));
        const pips = [1, 2, 3].map(n => '<i class="' + (n <= speed ? 'f f' + speed : '') + '"></i>').join('');
        const glyph = HOME_CARD_GLYPH[c.name] || (c.type === '场地' ? '🌐' : '✦');
        const used = Number(uses[c.name] || 0);
        return '<div class="hcard" title="' + escapeHtml(c.name + (used ? ' · 全服使用 ' + used + ' 次' : '')) + '">'
            + '<div class="ha card-art" aria-hidden="true">' + glyph + '</div>'
            + '<div class="hn">' + escapeHtml(c.name) + '</div>'
            + '<div class="hs">' + pips + '</div>'
            + '</div>';
    }).join('');
    // 热门榜单与手牌共用同一套完整卡面资源；加载失败时保留徽记与卡名。
    box.querySelectorAll('.hcard').forEach((el, i) => {
        if (picks[i]) applyFullCardFace(el.querySelector('.ha'), picks[i].name, true);
    });
}

/** 拉静态件（段位表 / 卡表 + 热门榜）。失败会重置标志位，下次回首页再试。 */
function loadHomeStatic() {
    if (homeStaticLoaded) return;
    homeStaticLoaded = true;
    homeFetchJSON('/api/rank_constants').then(d => {
        if (!d || !Array.isArray(d.tiers) || !d.tiers.length) { homeStaticLoaded = false; return; }
        homeRankConstants = d;
        renderHomeLadder(homeRankConstants, myRankInfo);
    });
    homeFetchJSON('/api/card_usage').then(d => {
        if (d === null) { homeStaticLoaded = false; return; }   // 失败：下次重来
        renderHomeHotCards(d);
    });
}

/** 首页面板总入口：页面加载时调一次，每次回到首页再调一次（数字类的会刷新）。 */
function refreshHomePanels() {
    loadHomeStatic();
    homeFetchJSON('/api/profile').then(d => {
        const p = d && d.profile;
        renderHomeCommander(p);
        renderHomeStats(p);
        if (p && p.level_info) refreshMyLevelStrip(p.level_info);
        if (p && p.rank_info) {
            if (typeof p.rank_info === 'object') myRankInfo = p.rank_info;   // 与段位胶囊共用缓存
            if (homeRankConstants) renderHomeLadder(homeRankConstants, p.rank_info);
        }
    });
    homeFetchJSON('/api/achievements').then(renderHomeAchievements);
    homeFetchJSON('/api/home_stats').then(renderHomeOnline);
}

/** 名片上的「查看我的名片」：与导航「个人信息」同一条路（window.showUserProfile）。 */
function bindHomeCommanderCard() {
    const btn = document.getElementById('cmdr-card-btn');
    if (!btn || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => {
        if (typeof window.showUserProfile !== 'function') return;
        const myName = window.__USERNAME || '';
        if (!myName) { showMessage('未登录，无法查看个人信息', { type: 'warning' }); return; }
        window.showUserProfile(myName);
    });
}
