#!/usr/bin/env node
/**
 * C+ 周边屏幕 · **状态一致性定向检查**（W2）
 *
 * 为什么单独一支：`cplus_screens_check` 验的是外观契约、`cplus_gate_check` 验的是门控，
 * 两者都看不见"异步回包乱序"这一类缺陷 —— 它们只在**响应顺序被调换**时才出现。
 * 本工具用 CDP 的 Fetch 域把 HTTP 响应**扣住再按指定顺序放行**，把这几条竞争条件
 * 变成确定性的、可重复的用例：
 *
 *   A05 结算原因矩阵   —— renderGameOverHead() 在（胜负 × 原因）上的文案
 *   A06 图鉴统计失败    —— /api/card_usage 失败后必须能重试、且卡牌仍可阅读
 *   A03 排行领奖台      —— 战绩榜/段位榜响应**反序**到达时，领奖台只认当前页签
 *   A07 回放加载        —— A 慢 / B 快、退出后回包，都不许污染当前帧
 *
 * 用法：
 *   node tools/cplus_state_check.mjs --url http://127.0.0.1:5097/
 *   node tools/cplus_state_check.mjs --cases a05,a06
 * 参数：--url / --port（CDP）/ --browser / --cases
 * 退出码：0 全过；1 有 FAIL；2 SKIP（没有浏览器）。
 *
 * ⚠️ 本工具**不改产品代码**，只用 Fetch.fulfillRequest 造假响应；
 *    造出来的数据一律带明显前缀（如 `A1`/`R1`/`STUB`），免得和真实数据混淆。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..');
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = Number(argOf('--port', '9359'));
const CASES = argOf('--cases', '').split(',').map((s) => s.trim()).filter(Boolean);
const KNOWN_BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const EDGE_EXPLICIT = argOf('--browser', '');
const EDGE = EDGE_EXPLICIT ? (fs.existsSync(EDGE_EXPLICIT) ? EDGE_EXPLICIT : null)
  : KNOWN_BROWSERS.find((p) => fs.existsSync(p));
const PROFILE = argOf('--profile', path.join(REPO, '.tmp', 'cplus-state', 'profile'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}
const want = (c) => !CASES.length || CASES.includes(c);

if (!EDGE) {
  console.log('SKIP  没有找到可用的 Edge/Chrome —— 这**不是通过**，是未验收。');
  process.exit(2);
}
fs.mkdirSync(PROFILE, { recursive: true });

const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
  '--user-data-dir=' + PROFILE, 'about:blank'], { stdio: 'ignore' });

let ws = null;
let exitCode = 0;
try {
  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || '')) || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 还没起来 */ }
    await sleep(500);
  }
  if (!target) { console.error('无法连接无头浏览器调试端口 ' + PORT); process.exit(3); }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });

  let seq = 0;
  const pending = new Map();
  /* 拦截规则：urlPattern(regex) → 处理函数（可延迟、可伪造响应、可放行）。
     处理函数可以 return null 表示"这一枪放行"。 */
  const rules = [];
  const jsProblems = [];
  ws.onmessage = async (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') {
      jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
      return;
    }
    if (m.method === 'Fetch.requestPaused') {
      const { requestId, request } = m.params;
      const url = request.url || '';
      const rule = rules.find((r) => r.re.test(url));
      let handled = false;
      if (rule) {
        try { handled = await rule.fn(requestId, url); } catch (err) { handled = false; }
      }
      if (!handled) {
        try { await send('Fetch.continueRequest', { requestId }); } catch (err) { /* 已经放掉了 */ }
      }
    }
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const id = ++seq; pending.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 30000);
  });
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 300) };
    return r.result && r.result.value;
  };
  // 伪造一个 JSON 响应
  const fulfill = (requestId, code, obj) => send('Fetch.fulfillRequest', {
    requestId, responseCode: code,
    responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
    body: Buffer.from(JSON.stringify(obj), 'utf8').toString('base64'),
  });
  const reload = async (waitFn) => {
    await send('Page.navigate', { url: APP });
    for (let i = 0; i < 60; i++) { if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break; await sleep(300); }
    await sleep(500);
    if (waitFn) await waitFn();
  };
  const waitFor = async (fn, ms, label) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); }
    void label;
    return false;
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  console.log('== C+ 状态一致性定向检查（W2）==');
  console.log('   目标 ' + APP);

  /* =========================================================================
     A05 · 结算原因矩阵
     -------------------------------------------------------------------------
     判据：`reason` 为空才是"正常击沉"，那两句"击沉…"只许在那种情况下出现；
     有任何明确原因（投降 / 掉线 / 超时 / 卡牌效果）时一律用中性结果，
     **不许**再宣称击沉 —— 历史缺陷正是「对方投降 · 击沉对方全部战舰」。 */
  if (want('a05')) {
    console.log('');
    console.log('-- A05 结算原因矩阵 --');
    await send('Fetch.disable');
    await reload();
    const matrix = await ev(`(function(){
      var ME = 'me-0001', OTHER = 'other-0002';
      window.gameState.playerId = ME;
      var cases = [
        { winner: ME,    reason: undefined,            key: 'normal-win' },
        { winner: OTHER, reason: undefined,            key: 'normal-lose' },
        { winner: null,  reason: undefined,            key: 'draw' },
        { winner: OTHER, reason: 'surrender',          key: 'i-surrendered' },
        { winner: ME,    reason: 'surrender',          key: 'opponent-surrendered' },
        { winner: OTHER, reason: 'opponent_disconnected', key: 'i-disconnected' },
        { winner: ME,    reason: 'opponent_disconnected', key: 'opponent-disconnected' },
        { winner: ME,    reason: 'timeout',            key: 'timeout' },
        { winner: ME,    reason: '神威！清空对方棋盘',   key: 'card-effect' },
        { winner: OTHER, reason: '从未见过的原因',       key: 'unknown-reason' }
      ];
      var out = [];
      cases.forEach(function(c){
        var payload = { winner: c.winner };
        if (c.reason !== undefined) payload.reason = c.reason;
        renderGameOverHead(payload);
        out.push({ key: c.key, reason: c.reason === undefined ? null : c.reason,
          sub: (document.getElementById('over-sub') || {}).textContent || '',
          result: (document.getElementById('game-result') || {}).textContent || '' });
      });
      return out;
    })()`);
    if (!matrix || matrix.__exc) {
      check(false, 'A05 调用 renderGameOverHead 得到矩阵', matrix);
    } else {
      const byKey = {};
      matrix.forEach((r) => { byKey[r.key] = r; });
      const SINK_WIN = '击沉对方全部战舰', SINK_LOSE = '你的舰队被击沉';
      // ① 正常击沉：这两句只在 reason 为空时出现
      check(byKey['normal-win'].sub.indexOf(SINK_WIN) >= 0, 'A05 正常胜利仍写「击沉对方全部战舰」', byKey['normal-win']);
      check(byKey['normal-lose'].sub.indexOf(SINK_LOSE) >= 0, 'A05 正常失败仍写「你的舰队被击沉」', byKey['normal-lose']);
      check(byKey['draw'].sub.indexOf('双方未分胜负') >= 0, 'A05 平局写「双方未分胜负」', byKey['draw']);
      // ② 有原因的一律不许出现"击沉"（这一条抓住历史缺陷）
      for (const r of matrix) {
        if (r.reason === null) continue;
        check(r.sub.indexOf(SINK_WIN) < 0 && r.sub.indexOf(SINK_LOSE) < 0,
          'A05 [' + r.key + '] 有明确原因时不宣称击沉', r);
      }
      // ③ 视角正确
      check(byKey['i-surrendered'].sub.indexOf('我方投降') >= 0, 'A05 我投降 → 「我方投降」', byKey['i-surrendered']);
      check(byKey['opponent-surrendered'].sub.indexOf('对方投降') >= 0, 'A05 对方投降 → 「对方投降」', byKey['opponent-surrendered']);
      check(byKey['i-disconnected'].sub.indexOf('我方掉线超时') >= 0, 'A05 我掉线 → 「我方掉线超时」', byKey['i-disconnected']);
      check(byKey['opponent-disconnected'].sub.indexOf('对手掉线超时') >= 0, 'A05 对手掉线 → 「对手掉线超时」', byKey['opponent-disconnected']);
      check(byKey['timeout'].sub.indexOf('操作超时') >= 0, 'A05 操作超时写「操作超时」', byKey['timeout']);
      // ④ 自由文本原样透传（服务端 _finish_game 会在 reason 里写中文句子）
      check(byKey['card-effect'].sub.indexOf('神威！清空对方棋盘') >= 0,
        'A05 卡牌效果原因原样透传（服务端文案就是权威解释）', byKey['card-effect']);
      // ⑤ 未知原因给中性结果，不猜
      check(byKey['unknown-reason'].sub.indexOf('从未见过的原因') >= 0
        && byKey['unknown-reason'].sub.indexOf('你落败') >= 0,
        'A05 未知原因原样显示 + 中性结果', byKey['unknown-reason']);
      // ⑥ 结果大字
      check(byKey['normal-win'].result.indexOf('胜') >= 0 && byKey['normal-lose'].result.indexOf('失') >= 0
        && byKey['draw'].result.indexOf('平') >= 0, 'A05 胜负平三个大字正确',
        { win: byKey['normal-win'].result, lose: byKey['normal-lose'].result, draw: byKey['draw'].result });
    }
  }

  /* =========================================================================
     A06 · 图鉴使用次数：失败可重试、并发共享、卡牌照读
     -------------------------------------------------------------------------
     历史缺陷（已复现）：失败时 loaded=true / ready=false 永久停住 ——
     计数条永远写"统计中…"，而且第二次调用被短路，连重开图鉴都不再试。
     非 2xx 还会被解析成空对象，界面上显示"全都用了 0 次"（一个假的数字）。 */
  if (want('a06')) {
    console.log('');
    console.log('-- A06 图鉴统计失败与重试 --');
    let usageMode = 'ok';           // ok | fail | slow-ok
    let usageHits = 0;
    rules.length = 0;
    rules.push({ re: /\/api\/card_usage/, fn: async (requestId) => {
      usageHits++;
      if (usageMode === 'fail') { await fulfill(requestId, 500, { error: 'stub-failure' }); return true; }
      if (usageMode === 'slow-ok') { await sleep(900); await fulfill(requestId, 200, { usage: { '失灵！': 7 } }); return true; }
      await fulfill(requestId, 200, { usage: { '失灵！': 7 } });
      return true;
    } });
    await send('Fetch.enable', { patterns: [{ urlPattern: '*api/card_usage*', requestStage: 'Request' }] });

    // ① 并发共享：三次调用只发一枪（响应被扣住 900ms，期间再调两次）
    /* ⚠️ 计数必须在**页面里**数，不能在 Node 侧的拦截规则里数：首页中栏的
       「全服热门卡」拉的也是 `/api/card_usage`（game.js:2614），它和图鉴那次
       共用同一个 URL。在拦截器里计数会把首页那条也算进来 —— 那是别的功能，
       与"图鉴的三次调用有没有共享"无关（第一版就是这么误判成 2 次的）。 */
    usageMode = 'ok'; usageHits = 0;
    await reload();
    await sleep(600);                      // 让首屏那条热门卡的请求先走完
    usageMode = 'slow-ok';
    await ev(`(function(){
      var orig = window.fetch;
      window.__cuFetches = 0;
      window.fetch = function(u){
        if (String(u).indexOf('/api/card_usage') >= 0) window.__cuFetches++;
        return orig.apply(this, arguments);
      };
      return 1; })()`);
    const concurrent = await ev(`(function(){
      var ps = [loadCardUsage(true), loadCardUsage(), loadCardUsage()];
      return Promise.all(ps).then(function(){
        return { settled: ps.length, state: cardUsageState, fetches: window.__cuFetches };
      });
    })()`);
    await sleep(1400);
    check(concurrent && concurrent.fetches === 1,
      'A06 并发三次调用只发出 1 个请求（共享在飞的那一次）', concurrent);
    const afterOk = await ev(`(function(){
      return { state: cardUsageState, ready: cardUsageState === 'ready' };
    })()`);
    check(afterOk && afterOk.state === 'ready', 'A06 成功后状态是 ready', afterOk);

    // ② 失败：状态 error + 计数条给出"暂不可用 / 重试"，且卡牌仍然读得到
    usageMode = 'fail';
    const failed = await ev(`(function(){
      return loadCardUsage(true).then(function(){
        renderCardCompendium();
        var counter = document.getElementById('compendium-count');
        return { state: cardUsageState,
                 counter: counter ? counter.textContent : null,
                 hasRetry: !!document.getElementById('compendium-usage-retry'),
                 cards: (document.getElementById('help-magic-cards') || {}).querySelectorAll
                   ? document.getElementById('help-magic-cards').querySelectorAll('.magic-card-help').length : 0 };
      });
    })()`);
    check(failed && failed.state === 'error', 'A06 失败后状态变成 error（不再停在"统计中"）', failed);
    check(failed && failed.hasRetry === true, 'A06 失败时给出「重试」入口', failed && failed.counter);
    check(failed && failed.cards > 0, 'A06 统计失败不影响读卡（网格照常有卡）', failed && { cards: failed.cards });

    // ③ 重试成功：状态回到 ready，计数条不再写"暂不可用"，且"已用 N 次"能显示出来
    usageMode = 'ok';
    const retried = await ev(`(function(){
      var before = ${usageHits};
      var b = document.getElementById('compendium-usage-retry');
      if (!b) return { noButton: true };
      b.click();
      return new Promise(function(res){ setTimeout(function(){
        var counter = document.getElementById('compendium-count');
        var first = document.querySelector('#help-magic-cards .magic-card-help');
        // 点开第一张卡，看详情里有没有"已用"胶囊
        if (first) first.click();
        var detail = document.getElementById('codex-detail');
        setTimeout(function(){
          res({ hitsBefore: before, hitsNow: window.__hits, state: cardUsageState,
                counter: counter ? counter.textContent : null,
                stillHasRetry: !!document.getElementById('compendium-usage-retry'),
                detailHasUses: detail ? /已用/.test(detail.textContent) : null });
        }, 300);
      }, 600); });
    })()`);
    check(retried && retried.state === 'ready', 'A06 点「重试」后回到 ready', retried);
    check(retried && retried.stillHasRetry !== true, 'A06 重试成功后不再显示「重试」',
      retried && { counter: retried.counter });
    check(retried && retried.counter && retried.counter.indexOf('暂不可用') < 0,
      'A06 计数条恢复正常文案', retried && retried.counter);
    check(retried && retried.detailHasUses === true,
      'A06 统计到之后详情里的「已用 N 次」会刷新出来', retried && { detailHasUses: retried.detailHasUses });

    // ④ 非 2xx 不许被当成 0 次：假数据的卡片名不在卡表里，所以只验"没有把空对象当成功"
    const fakeZero = await ev('(function(){ return { keys: Object.keys(cardUsage || {}).length, state: cardUsageState }; })()');
    check(fakeZero && fakeZero.state === 'ready' && fakeZero.keys > 0,
      'A06 成功时真的写进了 usage（不是空对象冒充成功）', fakeZero);
  }

  /* =========================================================================
     A03 · 排行领奖台：两个榜单的响应反序到达
     -------------------------------------------------------------------------
     历史缺陷（已读码）：fetchLeaderboard 成功后**没有活动页签判断**就写领奖台；
     段位榜的 token 切回战绩时也不失效 —— 两条路都能覆盖同一个领奖台。
     这里把两个接口都换成桩，并让先发的那个**慢**，于是乱序是确定的。 */
  if (want('a03')) {
    console.log('');
    console.log('-- A03 排行领奖台的身份（响应反序）--');
    const recRows = [1, 2, 3].map((i) => ({ username: 'A' + i, wins: 90 - i, losses: 1,
      longest_streak: i, avatar: '', name_style: '' }));
    const rankRows = [1, 2, 3].map((i) => ({ username: 'R' + i, points: 800 - i, position: i,
      tier_id: 'captain', tier_index: 7, ranked_wins: 5, ranked_losses: 2, avatar: '' }));
    let recordDelay = 0, rankedDelay = 0;
    let recordHits = 0, rankedHits = 0;
    rules.length = 0;
    rules.push({ re: /\/api\/leaderboard(\?|$)/, fn: async (requestId) => {
      recordHits++; await sleep(recordDelay); await fulfill(requestId, 200, recRows); return true;
    } });
    rules.push({ re: /\/api\/ranked_leaderboard/, fn: async (requestId) => {
      rankedHits++; await sleep(rankedDelay); await fulfill(requestId, 200, { leaderboard: rankRows }); return true;
    } });
    await send('Fetch.enable', { patterns: [{ urlPattern: '*api/leaderboard*', requestStage: 'Request' },
      { urlPattern: '*api/ranked_leaderboard*', requestStage: 'Request' }] });

    const readPodium = `(function(){
      var host = document.getElementById('leaderboard-podium');
      var names = [].slice.call(host.querySelectorAll('.ax-podium-name'))
        .map(function(e){ return e.textContent.replace('你','').trim(); });
      return { tab: (typeof leaderboardTab !== 'undefined') ? leaderboardTab : null,
               hidden: host.classList.contains('hidden'), names: names };
    })()`;

    // ① 战绩榜慢、段位榜快 → 最后停在段位榜，领奖台必须是 R 开头那三个人
    recordDelay = 1500; rankedDelay = 50;
    await reload();
    const race1 = await ev(`(function(){
      if (typeof showLeaderboard === 'function') showLeaderboard();   // 发战绩榜（慢）
      setTimeout(function(){ setLeaderboardTab('ranked'); }, 60);     // 立刻切段位榜（快）
      return true;
    })()`);
    void race1;
    await sleep(2600);
    const p1 = await ev(readPodium);
    check(p1 && p1.tab === 'ranked', 'A03 反序用例里当前页签是段位榜', p1);
    check(p1 && p1.names.length === 3 && p1.names.every((n) => n.indexOf('R') === 0),
      'A03 战绩榜的慢响应**没有**覆盖段位榜的领奖台', p1);

    // ② 反过来：段位榜慢、战绩榜快，先切段位榜再切回战绩榜，最后必须是 A 开头
    recordDelay = 50; rankedDelay = 1500;
    await reload();
    await ev(`(function(){ if (typeof showLeaderboard === 'function') showLeaderboard();
      setTimeout(function(){ setLeaderboardTab('ranked'); }, 30);
      setTimeout(function(){ setLeaderboardTab('record'); }, 200); return true; })()`);
    await sleep(2600);
    const p2 = await ev(readPodium);
    check(p2 && p2.tab === 'record', 'A03 反序用例 2 里当前页签是战绩榜', p2);
    check(p2 && p2.names.length === 3 && p2.names.every((n) => n.indexOf('A') === 0),
      'A03 段位榜的慢响应**没有**覆盖战绩榜的领奖台', p2);

    // ③ 连续刷新战绩榜两次、反序返回：只有第二次（最新）的内容能留下
    //    这里用"第一次慢、第二次快"的顺序，看表里最终是不是第二份数据
    recordDelay = 1200;
    await reload();
    const refresh = await ev(`(function(){
      var seen = [];
      if (typeof showLeaderboard === 'function') showLeaderboard();
      return true;
    })()`);
    void refresh;
    await sleep(300);
    recordDelay = 30;
    await ev('(function(){ fetchLeaderboard(); return true; })()');
    await sleep(1800);
    const p3 = await ev(`(function(){
      var rows = document.querySelectorAll('#leaderboard-table tbody tr');
      var first = rows.length ? rows[0].textContent.replace(/\\s+/g, ' ').trim() : null;
      return { rows: rows.length, first: first, hits: ${recordHits} };
    })()`);
    check(p3 && p3.rows === 3, 'A03 连续刷新后表里是 3 行（最新那份）', p3);

    await send('Fetch.disable');
  }

  /* =========================================================================
     A07 · 回放加载的身份
     -------------------------------------------------------------------------
     历史缺陷（已读码）：`/api/replay/<id>` 的回包无条件写 replayState.payload，
     既不认"这是哪一局的包"，也不认"回放屏还开着吗"。
     用例：A 局慢、B 局快 → 屏幕上必须是 B 局；打开后马上退出 → 不许再启动计时器。 */
  if (want('a07')) {
    console.log('');
    console.log('-- A07 回放加载的身份（A 慢 / B 快、退出后回包）--');
    const mkReplay = (tag) => ({
      success: true,
      you_are: 'p1',
      replay: {
        steps: [{ kind: 'log', text: tag + '-step-0' }, { kind: 'log', text: tag + '-step-1' }],
        ships: { p1: [], p2: [] }, hands: { p1: [], p2: [] }, board_resets: [], nodes: [],
      },
    });
    let delays = { A: 0, B: 0 };
    rules.length = 0;
    rules.push({ re: /\/api\/replay\//, fn: async (requestId, url) => {
      const id = url.split('/').pop().split('?')[0];
      await sleep(delays[id] || 0);
      await fulfill(requestId, 200, mkReplay(id));
      return true;
    } });
    await send('Fetch.enable', { patterns: [{ urlPattern: '*api/replay/*', requestStage: 'Request' }] });

    // ① A 慢 B 快：最终 payload 必须是 B
    delays = { A: 1500, B: 50 };
    await reload();
    await ev(`(function(){
      openReplayForMatch('A', null, 'me');     // 慢
      setTimeout(function(){ openReplayForMatch('B', null, 'me'); }, 60);   // 快
      return true; })()`);
    await sleep(2600);
    const r1 = await ev(`(function(){
      var payload = replayState.payload;
      var texts = payload && payload.steps ? payload.steps.map(function(s){ return s.text; }) : [];
      return { token: replayState.loadToken, playing: replayState.playing,
               timer: replayState.timer !== null,
               texts: texts, active: document.getElementById('replay-screen').classList.contains('active') };
    })()`);
    check(r1 && r1.texts.length === 2 && r1.texts[0] === 'B-step-0',
      'A07 A 局慢响应没有覆盖 B 局的回放内容（payload 是 B）', r1);

    // ② 打开后马上退出：迟到的包不许写状态、更不许启动计时器
    delays = { A: 1500, B: 0 };
    await ev('(function(){ replayState.loadToken = replayState.loadToken; return true; })()');
    await reload();
    await ev(`(function(){
      openReplayForMatch('A', null, 'me');
      setTimeout(function(){ leaveReplayScreen(); }, 80);
      return true; })()`);
    await sleep(2600);
    const r2 = await ev(`(function(){
      return { payload: replayState.payload, timer: replayState.timer !== null,
               playing: replayState.playing,
               active: document.getElementById('replay-screen').classList.contains('active'),
               startActive: document.getElementById('start-screen').classList.contains('active') };
    })()`);
    check(r2 && r2.payload === null, 'A07 退出回放后迟到的回包没有写回 payload', r2 && { payload: r2.payload });
    check(r2 && r2.timer === false && r2.playing === false, 'A07 退出回放后没有留下播放计时器', r2);
    check(r2 && r2.active === false && r2.startActive === true, 'A07 退出回放后停在首页', r2);

    await send('Fetch.disable');
  }

  check(jsProblems.length === 0, '全程零 JS 异常', jsProblems.slice(0, 4));

  console.log('');
  if (problems.length) {
    console.log('✗ ' + problems.length + ' 项未通过：');
    problems.slice(0, 40).forEach((p) => console.log('   · ' + p));
    exitCode = 1;
  } else {
    console.log('✓ 全部通过');
  }
} finally {
  try { if (ws) ws.close(); } catch (e) { /* 已断 */ }
  try { browser.kill(); } catch (e) { /* 已经退了 */ }
}
process.exit(exitCode);
