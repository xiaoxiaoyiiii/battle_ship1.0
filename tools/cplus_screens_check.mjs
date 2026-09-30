#!/usr/bin/env node
/**
 * C+ 周边屏幕验收（无头 Edge/Chrome + CDP）
 *
 * 覆盖 docs/C_PLUS_SCREENS_IMPLEMENTATION_2026_09_29.md 的十屏：
 *   lobby · room · placement · collection · leaderboard · profile
 *   result · spectate · replay · settings
 *
 * 每一屏 × 三个视口断言：
 *   ① 这一屏真的能进（屏幕 active / 弹窗可见）
 *   ② 页面**没有水平溢出** —— 而且**这块屏自己的容器**也没有局部溢出
 *   ③ 门控命中：`data-arena-screens === 'v2'` **且**逐屏清单里真有这个 token
 *   ④ C+ 标记物真的拿到了样式（面板圆角 / 屏头 eyebrow / 可见且不被挡）
 *   ⑤ 关屏后收尾干净（没有残留浮层、焦点没留在已关的容器里）
 * 外加：全程零 JS 异常；图鉴在窄屏要能"点卡 → 详情页 → 返回列表"。
 *
 * ⚠️ 本工具**不替代**那几支按真实数据跑的工具（lobby_check / replay_check /
 *    spectate_check / ranked_check / profile_card_check / codex_realcard_check）：
 *    它管的是"十屏的公共外观契约"，数据正确性仍由各自那支守。
 *    进入需要真实对局的屏（布船 / 结算 / 回放 / 观战）时，本工具按
 *    tools/acceptance_shots.mjs 的既有手法**直接切屏**（不伪造数据），
 *    所以它断言的只是外壳与布局，不碰任何数值 —— 因此截图清单里这些屏
 *    一律标注 `state: shell`，**不能**当作"这一屏有数据时的样子"的验收。
 *
 * ---- 2026-09-29（W0）修掉的三处，以及它们为什么必须一起修 ----------------
 *   · **门控断言恒真**：原来写的是
 *         hit: !!(list.split(/\s+/).indexOf(key) >= 0) || !!(mode === 'v2')
 *     两处都错：`indexOf` 的结果先 `!!` 成 boolean 再 `>= 0`，**boolean 与 0
 *     比较恒为 true**（false >= 0 也是 true）；而且两道门被 `||` 连起来，
 *     等于"只要总开关开着，屏清单里写什么都算命中"。实测的总关配置下
 *     工具照样打印 `hit=true`。正确语义只有一条：
 *         mode === 'v2' && list 的空白切分里有这个 key
 *   · **半径断言被静默跳过**：判据写的是 `screen.markerRadius`，而探针返回的
 *     字段叫 `r.markerRadius` —— `screen` 上根本没这个属性，于是
 *     `if (r && screen.markerRadius)` 永远不进、十屏一次都没验过圆角。
 *   · **无浏览器被算成 PASS**：原来 `process.exit(0)` 走的是"跳过"，但汇总方
 *     只看退出码就会把它当成通过。现在无浏览器打印 `SKIP` 并以退出码 2 结束。
 *
 * ---- 自校准（`--self-test`）--------------------------------------------
 * 上面三条都是"断言自己不生效"类缺陷，光靠跑一遍绿是抓不到的。所以本工具
 * 内置 `--self-test`：把门控谓词、半径判据、可见性判据拿**同一份实现**去喂
 * 一批"必须判 FAIL"的合成输入，并证明**旧表达式**在同一批输入上至少错一个。
 * 这个模式不起浏览器、不连服务器。
 *
 * 用法：
 *   node tools/cplus_screens_check.mjs --url http://127.0.0.1:5097/ [--shots <dir>]
 *   node tools/cplus_screens_check.mjs --self-test
 * 参数：
 *   --url     目标站点（默认 http://127.0.0.1:5000/）
 *   --shots   截图目录（省略则不出图）
 *   --port    CDP 调试端口（默认 9357）
 *   --browser 指定浏览器可执行文件（默认按 Edge → Chrome 顺序探测）
 *   --profile 浏览器 profile 目录（默认 <repo>/.tmp/cplus-screens/profile）
 *   --label   写进截图清单的实例标签（例如 "5097 独立测试库"）
 * 退出码：0 = 全部通过；1 = 有 FAIL；2 = SKIP（没找到浏览器，**不是通过**）。
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
const SHOTS = argOf('--shots', '');
const PORT = Number(argOf('--port', '9357'));
const LABEL = argOf('--label', '');
const SELF_TEST = argv.includes('--self-test');
const KNOWN_BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const EDGE_EXPLICIT = argOf('--browser', '');
/* 显式给的路径也要**存在性检查**：直接拿一个不存在的路径去 spawn，报的是
   Node 的 ENOENT 栈，看着像"工具坏了"，而不是"这台机器上没有浏览器"。
   两种情况结论都是 SKIP（未验收），但必须说清是哪一种。 */
const EDGE = EDGE_EXPLICIT ? (fs.existsSync(EDGE_EXPLICIT) ? EDGE_EXPLICIT : null)
  : KNOWN_BROWSERS.find((p) => fs.existsSync(p));
/* profile 一律落在项目 `.tmp` 里：放 C:/Windows/Temp 出现过 ACL 损坏 →
   Edge 起不来、调试端口连不上（见 .gitignore 里那段注释）。
   用独立目录是为了不和别人的浏览器抢 profile。 */
const PROFILE = argOf('--profile', path.join(REPO, '.tmp', 'cplus-screens', 'profile'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}
function contrastRatio(foreground, background) {
  const rgb = (value) => (String(value).match(/[\d.]+/g) || []).slice(0, 3).map(Number);
  const luminance = (value) => {
    const channels = rgb(value).map((v) => {
      const s = v / 255;
      return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
    return channels.length === 3 ? channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722 : NaN;
  };
  const a = luminance(foreground), b = luminance(background);
  return Number.isFinite(a) && Number.isFinite(b) ? (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) : 0;
}

/* ===========================================================================
   1. 门控谓词 —— **唯一定义**，Node 侧与页面侧共用同一份源码
   ---------------------------------------------------------------------------
   写法要点：不要手写第二份"页面里用的"字符串。下面这个函数的 `toString()`
   会被插进探针里执行，于是"工具自己判"和"页面里判"不可能不一致。
   ⚠️ 空白切分必须在生成后仍然正确 —— 用 `/\s+/` 字面量（不是字符串拼的
      `new RegExp('\\s+')`），并且 `--self-test` 里带空格/制表/换行的用例
      就是专门盯这一条的。 */
function gateHit(mode, list, key) {
  if (mode !== 'v2') return false;
  var tokens = String(list == null ? '' : list).split(/\s+/);
  for (var i = 0; i < tokens.length; i++) if (tokens[i] === key) return true;
  return false;
}

/* 旧表达式（**故意留在这里**，只给 --self-test 当反例用）。
   恒真：`false >= 0` 为 true；且 `||` 让总开关一开就无视屏清单。 */
function gateHitLegacy(mode, list, key) {
  return !!(String(list == null ? '' : list).split(/\s+/).indexOf(key) >= 0)
    || !!(mode === 'v2');
}

/* 半径判据：返回 true 才算合格。**不做"量不到就跳过"** ——
   量不到（null/空串）本身就是不合格：那说明 marker 压根没匹配上，
   或者这条规则没生效（历史缺陷就是这么被跳过去的）。 */
function radiusOk(value, allowed) {
  if (typeof value !== 'string' || !value) return false;
  return allowed.indexOf(value) >= 0;
}

/* 标记物可见性：display/visibility/opacity + 非零宽高 + 真的落在视口里。 */
function visibleOk(v) {
  if (!v) return false;
  if (v.display === 'none' || v.visibility === 'hidden') return false;
  if (typeof v.opacity === 'number' && v.opacity <= 0.05) return false;
  if (!(v.w > 0) || !(v.h > 0)) return false;
  if (v.inViewport === false) return false;
  return true;
}

const VIEWPORTS = [
  ['1440x900', 1440, 900],
  ['1280x720', 1280, 720],
  ['390x844', 390, 844],
];

/* ===========================================================================
   2. --self-test：证明这批断言**有牙**
   ---------------------------------------------------------------------------
   每条用例 = 输入 + "应当判什么"。任何一条断言恒真/恒假，这里立刻红。 */
function selfTest(probeSrc) {
  console.log('== cplus_screens_check 自校准（--self-test）==');
  const gateCases = [
    // [mode, list, key, 期望]
    ['v2', 'lobby room replay', 'lobby', true],
    ['v2', 'lobby room replay', 'replay', true],
    ['v2', 'lobby room', 'replay', false, '清单里没有这一屏'],
    ['off', 'lobby room replay', 'lobby', false, '总关 → 任何屏都不该命中'],
    ['off', '', 'lobby', false, '总关 + 空清单'],
    ['v2', '', 'lobby', false, '空清单'],
    ['v2', null, 'lobby', false, '属性缺失（null）'],
    ['v2', '   ', 'lobby', false, '只有空白'],
    ['v2', '  lobby   room  ', 'room', true, '多余空白不该切断 token'],
    ['v2', 'lobby\troom\nreplay', 'replay', true, '制表/换行也算分隔'],
    ['v2', 'replays', 'replay', false, '不能子串误命中'],
    ['v2', 'replay2', 'replay', false, '不能前缀误命中'],
    ['v1', 'lobby', 'lobby', false, '总开关只认 v2'],
    ['v2', 'LOBBY', 'lobby', false, '大小写敏感'],
  ];
  let gateBad = 0, legacyBad = 0;
  for (const [mode, list, key, want, why] of gateCases) {
    const got = gateHit(mode, list, key);
    const legacy = gateHitLegacy(mode, list, key);
    if (got !== want) { gateBad++; console.log('  ✗ 门控: ' + JSON.stringify({ mode, list, key }) + ' 应为 ' + want + ' 实为 ' + got + (why ? ' — ' + why : '')); }
    if (legacy !== want) legacyBad++;
  }
  check(gateBad === 0, '自校准 · 门控谓词 ' + gateCases.length + ' 条用例全部正确', { wrong: gateBad });
  check(legacyBad > 0, '自校准 · 错误的旧表达式在同一批用例上确实被判错（说明用例有区分力）',
    { legacyWrong: legacyBad + '/' + gateCases.length });

  /* 生成后测试：页面里拿到的是**字符串化之后**的那份谓词，所以"插入动作本身"
     也要验。从真正会发出去的探针文本里把那段函数抠出来重新求值 ——
     如果 `/\s+/` 在某次改写里被转义坏掉（写成 `split(/\\s+/)` 之类），
     或者拼接丢了大括号，这里会立刻红。 */
  if (probeSrc) {
    // 抠的范围：从 `var gateHit = ` 到探针正文里紧随其后的那条注释为止
    // （比"匹配到第一个右大括号"稳：函数体里将来多一层嵌套也不会截错）。
    // 末尾那个 `;` 是 `var gateHit = <函数>;` 这条语句自己的，求值前要去掉
    // —— 留着会得到 `(function …{};)` 这种语法错误，看着像"转义坏了"，其实是抠多了。
    const m = probeSrc.match(/var gateHit = ([\s\S]*?)\n\s*\/\//);
    let gen = null, genErr = null;
    if (!m) genErr = '探针里没找到插入的 gateHit 定义';
    else {
      const srcText = m[1].replace(/;\s*$/, '');
      try { gen = eval('(' + srcText + ')'); }
      catch (e) { genErr = String(e).slice(0, 160) + ' | 抠出的源码: ' + JSON.stringify(srcText).slice(0, 300); }
    }
    let genBad = 0;
    if (typeof gen === 'function') {
      for (const [mode, list, key, want, why] of gateCases) {
        if (gen(mode, list, key) !== want) { genBad++; console.log('  ✗ 生成后门控: ' + JSON.stringify({ mode, list, key }) + ' 应为 ' + want + (why ? ' — ' + why : '')); }
      }
    }
    check(!genErr && genBad === 0,
      '自校准 · 探针里那份**字符串化之后**的门控谓词行为一致（空白切分没被转义坏）',
      genErr || { wrong: genBad, cases: gateCases.length });
  }

  const radiusCases = [
    ['12px', ['12px', '14px'], true],
    ['14px', ['12px', '14px'], true],
    ['9px', ['12px', '14px'], false, '错误半径必须被抓到'],
    ['0px', ['12px', '14px'], false],
    ['', ['12px', '14px'], false, '量不到 = 不合格（不许静默跳过）'],
    [null, ['12px', '14px'], false, 'marker 没匹配上时计算样式为 null'],
    [undefined, ['12px', '14px'], false],
  ];
  let radiusBad = 0;
  for (const [v, allowed, want, why] of radiusCases) {
    if (radiusOk(v, allowed) !== want) { radiusBad++; console.log('  ✗ 半径: ' + JSON.stringify(v) + ' 应为 ' + want + (why ? ' — ' + why : '')); }
  }
  check(radiusBad === 0, '自校准 · 半径判据 ' + radiusCases.length + ' 条用例全部正确', { wrong: radiusBad });

  const visCases = [
    [{ display: 'block', visibility: 'visible', opacity: 1, w: 120, h: 40, inViewport: true }, true],
    [{ display: 'none', visibility: 'visible', opacity: 1, w: 120, h: 40, inViewport: true }, false, 'display:none'],
    [{ display: 'block', visibility: 'hidden', opacity: 1, w: 120, h: 40, inViewport: true }, false],
    [{ display: 'block', visibility: 'visible', opacity: 0, w: 120, h: 40, inViewport: true }, false, 'opacity:0（同帧截图的经典陷阱）'],
    [{ display: 'block', visibility: 'visible', opacity: 1, w: 0, h: 0, inViewport: true }, false, '零尺寸'],
    [{ display: 'block', visibility: 'visible', opacity: 1, w: 120, h: 40, inViewport: false }, false, '不在视口内'],
    [null, false, 'marker 不存在'],
  ];
  let visBad = 0;
  for (const [v, want, why] of visCases) {
    if (visibleOk(v) !== want) { visBad++; console.log('  ✗ 可见性: ' + JSON.stringify(v) + ' 应为 ' + want + (why ? ' — ' + why : '')); }
  }
  check(visBad === 0, '自校准 · 可见性判据 ' + visCases.length + ' 条用例全部正确', { wrong: visBad });

  console.log('');
  if (problems.length) {
    console.log('✗ 自校准未通过：');
    problems.forEach((p) => console.log('   · ' + p));
    process.exit(1);
  }
  console.log('✓ 自校准通过（门控/半径/可见性三类断言都能判 FAIL）');
}

/* 进入某一屏的最小必要动作。
   `root` = 屏幕根 id（切 active）；`modal` = 要打开的弹窗 id。
   `before` 是切屏前要补的"这一屏需要有东西可画"的准备（不伪造业务数据）。
   `radius` = 该屏标记物应有的圆角档位；`null` 表示这块标记物本身不是面板
              （例如页签条），此时**只打印实测值、不断言**。
   `keyButton` = 这一屏的主按钮，用来验"没被浮层/装饰挡住"。 */
const SCREENS = [
  { key: 'lobby', root: 'lobby-screen', marker: '#lobby-screen .lobby-panel:nth-child(2)',
    radius: ['12px', '14px'], keyButton: '#lobby-screen .lobby-panel button' },
  { key: 'room', root: 'custom-room-screen', marker: '#custom-room-info',
    radius: null, keyButton: '#copy-invite-link',
    before: `(function(){ var i = document.getElementById('custom-room-info'); if (i) i.classList.remove('hidden');
      var c = document.getElementById('custom-current-room-id'); if (c && !c.textContent.trim()) c.textContent = 'A7C2E1'; return 1; })()` },
  { key: 'placement', root: 'ship-placement-screen', marker: '.ax-deploy-side',
    radius: null, keyButton: '#random-ships',
    before: `(function(){ var b = document.getElementById('player-board'); if (b && !b.children.length && typeof initBoard === 'function') initBoard(b, true);
      var r = document.getElementById('random-ships'); if (r) r.click(); return 1; })()` },
  { key: 'collection', modal: 'help-modal', marker: '.ax-codex',
    radius: null, keyButton: '#codex-detail-back',
    before: `(function(){ document.getElementById('help-btn').click(); return 1; })()`, wantDetailPage: true,
    after: `(function(){ var h = document.getElementById('help-modal'); if (h) h.classList.add('hidden'); return 1; })()` },
  { key: 'leaderboard', root: 'leaderboard-screen', marker: '#leaderboard-tabs',
    radius: null, keyButton: '#lb-tab-ranked',
    before: `(function(){ if (typeof showLeaderboard === 'function') showLeaderboard(); return 1; })()`,
    extra: `(function(){ var card = document.querySelector('#leaderboard-podium .ax-podium-card');
      var name = card && card.querySelector('.ax-podium-name');
      if (!name) return { noPodium: true };
      return { cardColor: getComputedStyle(card).color, nameColor: getComputedStyle(name).color,
        cardBg: getComputedStyle(card).backgroundColor,
        theme: document.documentElement.className }; })()`,
    after: `(function(){ var s = document.getElementById('leaderboard-screen'); if (s) s.classList.remove('active'); return 1; })()` },
  { key: 'profile', modal: 'opponent-stats-modal', marker: '#opponent-stats-title',
    radius: null, keyButton: '#opponent-stats-modal .modal-close',
    before: `(function(){ var n = window.__USERNAME || ''; if (typeof window.showUserProfile === 'function') window.showUserProfile(n); return 1; })()`,
    after: `(function(){ var m = document.getElementById('opponent-stats-modal'); if (m) m.classList.add('hidden'); return 1; })()` },
  { key: 'result', root: 'game-over-screen', marker: '.over-verdict',
    radius: null, keyButton: '#game-over-screen button',
    before: `(function(){ var h = document.getElementById('over-head'); if (h) h.classList.add('win');
      var r = document.getElementById('game-result'); if (r && !r.textContent.trim()) r.textContent = '胜利';
      return 1; })()`,
    after: `(function(){ var s = document.getElementById('game-over-screen'); if (s) s.classList.remove('active'); return 1; })()` },
  { key: 'replay', root: 'replay-screen', marker: '.replay-topbar',
    radius: null, keyButton: '#replay-leave',
    after: `(function(){ var s = document.getElementById('replay-screen'); if (s) s.classList.remove('active'); return 1; })()`,
    /* 回放屏多量一组（W5 的布局验收项）：任务书要求「桌面双棋盘在主区，
       时间轴与播放控件**紧邻其下**，右侧安排事件列表」。判据用**几何关系**：
         · 宽屏：.replay-body 是两列 grid；
         · 两块棋盘并排（左边缘不同、上边缘相同）；
         · 时间轴在棋盘**下方**且间距小（< 80px）—— "紧邻"这件事只能靠间距量；
         · 事件侧栏在**主区右侧**（x 大于主区右边缘）。
       窄屏只要"主区在侧栏前面"（竖排）。 */
    extra: `(function(){
      function R(sel){ var e = document.querySelector(sel); if (!e) return null;
        var b = e.getBoundingClientRect();
        return { x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width),
                 h: Math.round(b.height), right: Math.round(b.right), bottom: Math.round(b.bottom) }; }
      var body = document.querySelector('.replay-body');
      var boards = R('.replay-boards');
      var b1 = R('#replay-board-1');
      var b2 = R('#replay-board-2');
      var ctl = R('.replay-controls');
      var track = R('#replay-track');
      var side = R('.replay-side');
      var main = R('.replay-main');
      var wide = window.innerWidth >= 861;
      return {
        wide: wide,
        display: body ? getComputedStyle(body).display : null,
        boardsSideBySide: !!(b1 && b2 && Math.abs(b1.y - b2.y) <= 2 && b2.x > b1.right - 2),
        controlsBelowBoards: !!(boards && ctl && ctl.y >= boards.bottom - 2),
        gapBoardsControls: (boards && ctl) ? (ctl.y - boards.bottom) : null,
        trackInControls: !!(ctl && track && track.y >= ctl.y - 2 && track.bottom <= ctl.bottom + 2),
        sideRightOfMain: !!(main && side && side.x >= main.right - 2),
        mainBeforeSide: !!(main && side && main.y <= side.y + 2),
        sideW: side ? side.w : null,
      };
    })()` },
  { key: 'spectate', root: 'spectate-screen', marker: '.spectate-topbar',
    radius: null, keyButton: '#spectate-leave',
    after: `(function(){ var s = document.getElementById('spectate-screen'); if (s) s.classList.remove('active'); return 1; })()`,
    /* 观战屏多量两条（W5 的"公开信息提示"验收项）：
       ① 图例**横跨整行** —— `.spectate-body` 是 flex-wrap，图例不写 flex-basis:100%
          就会跟两块棋盘挤同一行、把棋盘顶下去；
       ② 图例里的色块必须与棋盘**同一批令牌**（命中用 --hit-fire），
          否则换主题/开高对比时会出现"图例说红、棋盘上是别的颜色"。 */
    extra: `(function(){
      var lg = document.getElementById('spectate-legend');
      if (!lg) return { noLegend: true };
      var body = document.querySelector('.spectate-body');
      var b = lg.getBoundingClientRect();
      var bb = body ? body.getBoundingClientRect() : null;
      var hit = lg.querySelector('.lg-hit');
      var miss = lg.querySelector('.lg-miss');
      /* 与棋盘格子的**实际**观感比：直接读水色令牌（棋盘此刻可能是空的，
         量不到 .cell 就拿不到底色 —— 第一版就是这么得到 water:null 的，
         那条断言于是等于什么都没验）。这里改成读 CSS 变量本身。 */
      var root = getComputedStyle(document.documentElement);
      var water = root.getPropertyValue('--cell-water').trim();
      var hitFire = root.getPropertyValue('--hit-fire').trim();
      return {
        w: Math.round(b.width), h: Math.round(b.height),
        bodyW: bb ? Math.round(bb.width) : null,
        spansRow: !!(bb && Math.abs(b.width - bb.width) <= 2),
        items: lg.querySelectorAll('.spectate-legend-item').length,
        hitBg: hit ? getComputedStyle(hit).backgroundColor : null,
        missShadow: miss ? getComputedStyle(miss).boxShadow : null,
        waterVar: water, hitFireVar: hitFire,
        note: (lg.querySelector('.spectate-legend-note') || {}).textContent || '',
      };
    })()` },
  { key: 'settings', modal: 'settings-modal', marker: '.ax-preview',
    radius: ['12px', '14px'], keyButton: '#settings-modal .modal-close',
    before: `(function(){ if (typeof openSettingsModal === 'function') openSettingsModal('look'); else document.getElementById('settings-btn').click(); return 1; })()`,
    extra: `(function(){ var root = document.documentElement, motion = root.getAttribute('data-motion'),
      contrast = root.getAttribute('data-contrast'), sample = document.createElement('div');
      sample.style.cssText = 'background:var(--panel);transition:opacity 1s;animation:quickChatIn 1s infinite';
      document.body.appendChild(sample);
      root.setAttribute('data-motion', 'reduce'); root.setAttribute('data-contrast', 'high');
      var cs = getComputedStyle(sample);
      var result = { animation: cs.animationName, transition: cs.transitionDuration, panel: cs.backgroundColor };
      sample.remove();
      if (motion === null) root.removeAttribute('data-motion'); else root.setAttribute('data-motion', motion);
      if (contrast === null) root.removeAttribute('data-contrast'); else root.setAttribute('data-contrast', contrast);
      return result; })()`,
    after: `(function(){ var m = document.getElementById('settings-modal'); if (m) m.classList.add('hidden'); return 1; })()` },
];

/* 这些屏在本工具里是"直接切屏"的空壳（见文件头说明），截图清单照样标出来，
   免得下游把空壳图当成"有数据的完成态"。 */
const SHELL_ONLY = new Set(['placement', 'result', 'replay', 'spectate']);

/* ===========================================================================
   3. 探针：一次求值做完"进屏 + 量几何 + 量标记物 + 量收尾"
   ---------------------------------------------------------------------------
   整段在页面里同步执行，所以不存在"切了屏但还没绘制"的时序问题
   （样式在切类名的同一帧就生效）。

   ⚠️ 门控谓词**不是**在页面里另写一份：下面把 Node 侧那个 gateHit 的源码
      `toString()` 直接插进探针（${gateHit.toString()}），
      于是"工具自己判"和"页面里判"共用同一份实现，不可能漂移。 */
const PROBE = `(function(cfg){
  var gateHit = ${gateHit.toString()};
  // ① 先清干净：关掉所有浮层、退掉所有屏
  document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
  document.querySelectorAll('.modal-overlay').forEach(function(m){ m.classList.add('hidden'); });
  document.body.classList.remove('layout-compact', 'layout-ingame');
  var help = document.getElementById('help-content'); if (help) help.classList.remove('ax-show-detail');
  // ② 该屏需要的准备（不伪造业务数据，见文件头说明）
  if (cfg.before) { try { eval(cfg.before); } catch (e) { return { setupError: String(e).slice(0,200) }; } }
  // ③ 切屏
  if (cfg.root) {
    var el = document.getElementById(cfg.root);
    if (!el) return { missing: cfg.root };
    el.classList.add('active');
  }
  if (cfg.modal) {
    var m = document.getElementById(cfg.modal);
    if (!m || m.classList.contains('hidden')) return { modalNotOpen: cfg.modal };
  }
  // ④ 量
  function R(el){ if(!el) return null; var r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }; }
  function V(el){
    if (!el) return null;
    var cs = getComputedStyle(el), r = el.getBoundingClientRect();
    var vw = window.innerWidth, vh = window.innerHeight;
    return { display: cs.display, visibility: cs.visibility, opacity: parseFloat(cs.opacity),
      w: Math.round(r.width), h: Math.round(r.height),
      inViewport: r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw,
      z: cs.zIndex };
  }
  var marker = document.querySelector(cfg.marker);
  var de = document.documentElement;
  // ⚠️ eyebrow 必须**按当前这一屏**取：写成一条并联选择器会永远命中 DOM 里最靠前的
  //    那一个（实测十屏都报 "FRIEND ROOM"）。
  var EYEBROW = { lobby: '#lobby-screen > h2', room: '#custom-room-screen > h1',
    placement: '#ship-placement-screen > h2', collection: '#help-modal .modal-content > h2',
    leaderboard: '#leaderboard-screen > h2', profile: '#opponent-stats-modal .modal-content > h2',
    result: '#game-over-screen .over-verdict > h2', replay: '#replay-screen > .replay-title',
    spectate: '#spectate-screen > .spectate-title', settings: '#settings-modal .modal-content > h2' };
  var eyebrowHost = document.querySelector(EYEBROW[cfg.key] || '.__none__');
  var eb = eyebrowHost ? getComputedStyle(eyebrowHost, '::before') : null;
  // ---- 局部溢出：不只量 document，也量这一屏自己的容器（含带 overflow 的滚动容器）
  function OV(el){ if (!el) return null; return el.scrollWidth - el.clientWidth; }
  var localOverflow = {};
  [cfg.root, cfg.modal].forEach(function(id){
    if (!id) return;
    var host = document.getElementById(id);
    if (!host) return;
    localOverflow[id] = OV(host);
    var deep = host.querySelectorAll('*');
    var worst = null, worstVal = 0;
    for (var i = 0; i < deep.length; i++) {
      var e = deep[i];
      if (!e.clientWidth) continue;
      var d = e.scrollWidth - e.clientWidth;
      // 自身就是横向滚动容器（overflow-x:auto 之类）的，不算溢出
      var ox = getComputedStyle(e).overflowX;
      if (ox === 'auto' || ox === 'scroll') continue;
      if (d > worstVal) { worstVal = d; worst = e.id || e.className || e.tagName; }
    }
    localOverflow[id + '.__worst'] = { delta: worstVal, el: String(worst).slice(0, 60) };
  });
  // ---- 关键按钮有没有被挡住（浮层/装饰压在它上面）
  var kb = cfg.keyButton ? document.querySelector(cfg.keyButton) : null;
  var kbHit = null;
  if (kb) {
    var kr = kb.getBoundingClientRect();
    var cx = Math.round(kr.left + Math.min(kr.width, 8) / 2), cy = Math.round(kr.top + kr.height / 2);
    var top = (cx >= 0 && cy >= 0 && cx < window.innerWidth && cy < window.innerHeight)
      ? document.elementFromPoint(cx, cy) : null;
    kbHit = { found: true, visible: V(kb), blockedBy: (top && (top === kb || kb.contains(top))) ? null
      : (top ? (top.tagName + (top.id ? '#' + top.id : '') + (top.className ? '.' + String(top.className).split(' ')[0] : '')) : 'null') };
  } else { kbHit = { found: false }; }
  return {
    gate: { mode: de.getAttribute('data-arena-screens'), list: de.getAttribute('data-arena-screen-list') },
    __gateHit: gateHit(de.getAttribute('data-arena-screens'), de.getAttribute('data-arena-screen-list'), cfg.key),
    overflow: de.scrollWidth - de.clientWidth,
    vw: window.innerWidth,
    localOverflow: localOverflow,
    markerFound: !!marker,
    markerRect: R(marker),
    markerVisible: V(marker),
    markerRadius: marker ? getComputedStyle(marker).borderTopLeftRadius : null,
    eyebrow: eb && eb.content && eb.content !== 'none' ? eb.content : null,
    keyButton: kbHit,
    screenActiveCount: document.querySelectorAll('.screen.active').length,
    visibleOverlays: [].slice.call(document.querySelectorAll('.modal-overlay'))
      .filter(function(m){ return !m.classList.contains('hidden'); }).length,
    boardCells: document.querySelectorAll(cfg.root === 'ship-placement-screen' ? '#player-board .cell' : '.__none__').length
  };
})`;

/* 收尾探针：把这一屏关掉，再看有没有残留（浮层、焦点、还在 active 的屏、C+ 容器还占位）。 */
const TEARDOWN = `(function(cfg){
  if (cfg.after) { try { eval(cfg.after); } catch (e) { return { teardownError: String(e).slice(0,200) }; } }
  else {
    if (cfg.modal) { var m = document.getElementById(cfg.modal); if (m) m.classList.add('hidden'); }
    if (cfg.root) { var el = document.getElementById(cfg.root); if (el) el.classList.remove('active'); }
  }
  var act = document.activeElement;
  var leakFocus = null;
  var closed = [];
  if (cfg.modal) closed.push(document.getElementById(cfg.modal));
  if (cfg.root) closed.push(document.getElementById(cfg.root));
  for (var i = 0; i < closed.length; i++) {
    if (closed[i] && act && closed[i].contains(act)) leakFocus = act.id || act.tagName;
  }
  return {
    visibleOverlays: [].slice.call(document.querySelectorAll('.modal-overlay'))
      .filter(function(m){ return !m.classList.contains('hidden'); }).length,
    activeScreens: [].slice.call(document.querySelectorAll('.screen.active')).map(function(s){ return s.id; }),
    leakFocus: leakFocus,
    // 关掉之后，屏幕根不该还占着布局高度（display:none 的屏 clientHeight 为 0）
    closedHeight: closed.length && closed[0] ? closed[0].getBoundingClientRect().height : null
  };
})`;

console.log('== C+ 十屏验收 ==');

/* 这三道闸门必须排在探针定义**之后**：--self-test 要拿真正会发出去的
   探针文本去验"字符串化之后的门控谓词"，先退出的话那段就永远测不到。 */
if (SELF_TEST) { selfTest(PROBE); process.exit(0); }

if (!EDGE) {
  console.log('SKIP  没有找到可用的 Edge/Chrome —— 这**不是通过**，是未验收。');
  if (EDGE_EXPLICIT) console.log('      --browser 指定的路径不存在：' + EDGE_EXPLICIT);
  else console.log('      已探测：\n        ' + KNOWN_BROWSERS.join('\n        '));
  process.exit(2);
}
fs.mkdirSync(PROFILE, { recursive: true });

console.log('   目标 ' + APP + '   浏览器 ' + EDGE);
if (LABEL) console.log('   实例标签 ' + LABEL);
console.log('   profile ' + PROFILE + '   CDP 端口 ' + PORT);

/* ===========================================================================
   4. 浏览器：只起自己这一个实例，退出时只杀自己
   ---------------------------------------------------------------------------
   原来的 `process.exit(0)` 直接走人，finally 不执行 → 无头浏览器会留在后台；
   中途抛异常时更是只剩一个孤儿进程。这里把整段包进 try/finally，
   并且**只 kill 自己 spawn 出来的 pid**（不杀用户正在用的浏览器）。 */
const userDataArgs = ['--user-data-dir=' + PROFILE];
const browser = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT, ...userDataArgs,
  'about:blank'], { stdio: 'ignore' });

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
  if (!target) { console.error('无法连接无头浏览器调试端口 ' + PORT + '（profile: ' + PROFILE + '）'); process.exit(3); }

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  let seq = 0;
  const pending = new Map();
  const jsProblems = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
  };
  const send = (method, params = {}) => new Promise((res, rej) => {
    const id = ++seq; pending.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 25000);
  });
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) return { __exc: JSON.stringify(r.exceptionDetails).slice(0, 400) };
    return r.result && r.result.value;
  };

  await send('Page.enable');
  await send('Runtime.enable');

  const manifest = { url: APP, label: LABEL, browser: EDGE, viewports: {}, shots: [], notes: [] };
  // 页面头部的门控属性（每个视口都会重载，值一样；记一份即可）
  let gateSeen = null;

  for (const [vlabel, w, h] of VIEWPORTS) {
    if (SHOTS) fs.mkdirSync(path.join(SHOTS, vlabel), { recursive: true });
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: w < 600 });
    await send('Page.navigate', { url: APP });
    for (let i = 0; i < 60; i++) { if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break; await sleep(300); }
    await sleep(700);
    manifest.viewports[vlabel] = { w, h };

    const seen = await ev('(function(){ return { mode: document.documentElement.getAttribute("data-arena-screens"), list: document.documentElement.getAttribute("data-arena-screen-list"), user: (window.__USERNAME || null) }; })()');
    if (seen && !seen.__exc) gateSeen = gateSeen || seen;
    if (seen && seen.user === null) manifest.guest = true;

    for (const screen of SCREENS) {
      const cfg = JSON.stringify({ key: screen.key, root: screen.root || null, modal: screen.modal || null,
        marker: screen.marker, before: screen.before || null, after: screen.after || null });
      let r = await ev('(' + PROBE + ')(' + cfg + ')');
      if (r && (r.setupError || r.missing || r.modalNotOpen)) {
        check(false, '[' + vlabel + '] ' + screen.key + ' 能进入', r);
        continue;
      }
      // 弹窗/屏切换有 300ms 入场动画 —— 量完几何再等一次动画结束才好截图
      if (screen.key === 'profile' || screen.key === 'leaderboard') {
        await sleep(700);
        // The second geometry probe must not restart an asynchronous fetch.
        const settledCfg = screen.key === 'leaderboard'
          ? JSON.stringify({ key: screen.key, root: screen.root || null, modal: screen.modal || null,
            marker: screen.marker, before: null, after: screen.after || null }) : cfg;
        r = await ev('(' + PROBE + ')(' + settledCfg + ')');
      }
      const label = '[' + vlabel + '] ' + screen.key;
      check(r && r.markerFound === true, label + ' 的 C+ 标记物在页面里（' + screen.marker + '）', r && r.markerRect);
      check(r && r.overflow <= 1, label + ' 无水平溢出', r && { overflow: r.overflow, vw: r.vw });
      // 局部溢出：屏幕自己的容器（含后代里最宽的那个）也不能溢出
      if (r && r.localOverflow) {
        const bad = Object.keys(r.localOverflow)
          .filter((k) => k.endsWith('__worst'))
          .map((k) => ({ where: k.replace('.__worst', ''), delta: r.localOverflow[k].delta, el: r.localOverflow[k].el }))
          .filter((x) => x.delta > 1);
        check(bad.length === 0, label + ' 屏内容器无横向溢出', bad.length ? bad : undefined);
      }
      check(r && r.__gateHit === true, label + ' 门控命中（mode==="v2" 且清单含本屏 token）', r && r.gate);
      check(r && visibleOk(r.markerVisible), label + ' 的 C+ 标记物可见且宽高非零', r && r.markerVisible);
      // 面板圆角：C+ 的面板一律 12px（.ax-panel 与逐屏面板规则）
      if (r && screen.radius) {
        check(radiusOk(r.markerRadius, screen.radius),
          label + ' 的标记物用的是 C+ 面板圆角（' + screen.radius.join('/') + '）',
          { radius: r.markerRadius, marker: screen.marker });
      } else if (r) {
        console.log('   ' + label + ' 圆角实测 ' + JSON.stringify(r.markerRadius) + '（本标记物不是面板，只记录不断言）');
      }
      // 关键按钮没被挡住
      if (r && r.keyButton && r.keyButton.found) {
        check(r.keyButton.blockedBy === null, label + ' 的主按钮没被浮层/装饰挡住',
          { target: screen.keyButton, blockedBy: r.keyButton.blockedBy, visible: r.keyButton.visible });
      }
      if (r && r.eyebrow) console.log('   ' + label + ' eyebrow = ' + r.eyebrow);
      // 该屏自己的附加断言（观战屏的公开信息图例、回放屏的布局关系）
      if (screen.extra) {
        const x = await ev(screen.extra);
        if (x && !x.__exc && x.noLegend !== true) {
          if (screen.key === 'spectate') {
            check(x.spansRow === true, label + ' 的公开信息图例横跨整行（不跟棋盘挤同一行）',
              { w: x.w, bodyW: x.bodyW });
            check(x.items === 2, label + ' 的图例只有两档（命中/落空，与棋盘实际观感一致）', x && x.items);
            /* 色块必须来自棋盘用的同一批令牌：命中 = --hit-fire，落空 = --miss-dot。
               只断言"有颜色"是不够的 —— 图例说红、棋盘上是别的颜色才是真缺陷。 */
            check(!!x.hitFireVar && /#c22a3e|rgb\(194, 42, 62\)/.test(x.hitBg || ''),
              label + ' 的图例命中色就是棋盘命中用的 --hit-fire', { hitBg: x.hitBg, hitFireVar: x.hitFireVar });
            check(!!x.missShadow && x.missShadow !== 'none',
              label + ' 的图例落空块画出了 --miss-dot 的点（不是一块空底色）', x && x.missShadow);
            check(/没打过/.test(x.note || ''), label + ' 的图例写明了"没打过的格子看不出有没有船"',
              x && x.note);
          } else if (screen.key === 'replay') {
            if (x.wide) {
              check(x.display === 'grid', label + ' 的回放主体是两列 grid（主区 + 侧栏）', { display: x.display });
              check(x.boardsSideBySide === true, label + ' 两块棋盘**并排**在主区', x);
              check(x.controlsBelowBoards === true, label + ' 时间轴/播放控件在棋盘**下方**', x);
              check(x.gapBoardsControls !== null && x.gapBoardsControls < 80,
                label + ' 控件与棋盘**紧邻**（间距 < 80px）', { gap: x.gapBoardsControls });
              check(x.trackInControls === true, label + ' 进度条在播放控件那一行里', x);
              check(x.sideRightOfMain === true, label + ' 事件侧栏在主区**右侧**', x);
            } else {
              check(x.mainBeforeSide === true, label + ' 窄屏下主区（棋盘+控件）排在侧栏前面', x);
            }
          } else if (screen.key === 'leaderboard' && !x.noPodium) {
            const ratio = contrastRatio(x.nameColor, x.cardBg);
            check(ratio >= 4.5, label + ' 领奖台姓名与卡片底色对比度至少 4.5:1', { ...x, ratio });
          } else if (screen.key === 'settings') {
            check(x.animation === 'none' && x.transition === '0s',
              label + ' 减少动效实际关闭动画与过渡', x);
            check(/^rgb\(/.test(x.panel), label + ' 高对比把半透明面板换成实色', x);
          }
        } else if (x && x.noLegend === true) {
          check(false, label + ' 的公开信息图例存在', x);
        }
      }
      // 收尾：关掉这一屏，看有没有残留
      const t = await ev('(' + TEARDOWN + ')(' + cfg + ')');
      if (t && !t.__exc) {
        check(t.visibleOverlays === 0, label + ' 关屏后没有残留浮层', t);
        check(t.activeScreens.length === 0, label + ' 关屏后没有别的屏还 active', t.activeScreens);
        check(!t.leakFocus, label + ' 关屏后焦点没留在已关容器里', t.leakFocus);
        check(t.closedHeight === null || t.closedHeight <= 1, label + ' 关屏后本屏不再占布局高度', t.closedHeight);
      }
      manifest.shots.push({ viewport: vlabel, screen: screen.key,
        state: SHELL_ONLY.has(screen.key) ? 'shell' : 'entered',
        gate: r && r.gate, markerRadius: r && r.markerRadius });
    }

    // 结算屏的「居中主视觉」（W5 的验收项之一）：量的是几何居中，不是"看着像居中"
    if (w >= 861) {
      const hero = await ev(`(function(){
        document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
        document.querySelectorAll('.modal-overlay').forEach(function(m){ m.classList.add('hidden'); });
        var r = document.getElementById('game-result'); if (r) r.textContent = '胜利';
        var h = document.getElementById('over-head'); if (h) h.classList.add('win');
        document.getElementById('game-over-screen').classList.add('active');
        var head = document.getElementById('over-head');
        if (!head) return { noHead: true };
        var hb = head.getBoundingClientRect();
        var v = head.querySelector('.over-verdict');
        var vb = v ? v.getBoundingClientRect() : null;
        var meta = head.querySelector('.over-meta');
        var mb = meta ? meta.getBoundingClientRect() : null;
        var cs = getComputedStyle(head);
        return { dir: cs.flexDirection,
                 headCx: Math.round(hb.left + hb.width / 2),
                 verdictCx: vb ? Math.round(vb.left + vb.width / 2) : null,
                 metaCx: mb ? Math.round(mb.left + mb.width / 2) : null,
                 headW: Math.round(hb.width) };
      })()`);
      /* 判据：判定头立成**一列**，且胜负大字与元信息条的中心都落在判定头的中线上（±2px）。
         不这样写的话，"居中"只能靠人眼看截图 —— 而"看着差不多居中"在宽屏上差几十像素。 */
      check(hero && hero.dir === 'column', '[' + vlabel + '] 结算判定头在宽屏是**竖排**（居中主视觉）',
        hero && { dir: hero.dir });
      check(hero && hero.verdictCx !== null && Math.abs(hero.verdictCx - hero.headCx) <= 2,
        '[' + vlabel + '] 胜负大字**水平居中**在判定头中线上（±2px）',
        hero && { verdictCx: hero.verdictCx, headCx: hero.headCx });
      check(hero && hero.metaCx !== null && Math.abs(hero.metaCx - hero.headCx) <= 2,
        '[' + vlabel + '] 对手/段位/用时三枚胶囊也居中', hero && { metaCx: hero.metaCx, headCx: hero.headCx });
    }

    // 图鉴的窄屏详情页往返（这是 P1/W2 的验收项之一）
    if (w < 600) {
      const flow = await ev(`(function(){
        /* ⚠️ 先把帮助弹窗真的打开（2026-09-29 修工具）。
           这一段原来直接去点卡片 —— 而上一步的收尾刚把 #help-modal 关掉，
           于是整棵图鉴都是 display:none：
             · offsetParent === null 让"窄屏档"的判据**假成立**（隐藏元素也满足），
               于是 .ax-show-detail 照样被加上，看着像"切到了详情页"；
             · 但焦点**落不进不渲染的子树**，Esc 也不该被图鉴接管（弹窗是关着的）。
           所以断言"焦点进详情页 / Esc 回列表"必须先让图鉴真的开着，
           否则这几条永远红，而且红得像是产品坏了。
           （这段注释在模板字符串里，所以不能用反引号引用选择器名。） */
        document.querySelectorAll('.modal-overlay').forEach(function(m){ m.classList.add('hidden'); });
        document.getElementById('help-btn').click();
        var help = document.getElementById('help-content');
        var grid = document.getElementById('help-magic-cards');
        if (!grid || !grid.querySelector('.magic-card-help')) return { noCard: true };
        help.classList.remove('ax-show-detail');
        var first = grid.querySelector('.magic-card-help');
        if (!first) return { noCard: true };
        var helpOpen = !document.getElementById('help-modal').classList.contains('hidden');
        var name = first.getAttribute('data-card-name');
        first.click();
        var detailShown = help.classList.contains('ax-show-detail');
        var detail = document.getElementById('codex-detail');
        var txt = detail && detail.querySelector('.ax-detail-text');
        var clamp = txt ? getComputedStyle(txt).webkitLineClamp : null;
        var gridHidden = document.querySelector('.ax-codex-main') ? getComputedStyle(document.querySelector('.ax-codex-main')).display : null;
        var back = document.getElementById('codex-detail-back');
        var backVisible = back ? getComputedStyle(back).display !== 'none' : false;
        // 焦点有没有跟着进详情页（窄屏上网格被 display:none 收起，焦点留在原格等于消失）
        var focusInDetail = !!(detail && document.activeElement && detail.contains(document.activeElement));
        // 用**真实的键盘事件**走 Escape 那条路（不是直接调 codexShowList）
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        var escapedToList = !help.classList.contains('ax-show-detail');
        var focusBackOnCard = (function(){
          var a = document.activeElement;
          return !!(a && a.classList && a.classList.contains('magic-card-help')
                    && a.getAttribute('data-card-name') === name);
        })();
        // 再点一次并用按钮返回，验"焦点回到原卡"在按钮路径上也成立
        first.click();
        if (back) back.click();
        var backToGrid = !help.classList.contains('ax-show-detail');
        var focusAfterButton = (function(){
          var a = document.activeElement;
          return !!(a && a.classList && a.classList.contains('magic-card-help')
                    && a.getAttribute('data-card-name') === name);
        })();
        return { name: name, helpOpen: helpOpen, detailShown: detailShown, gridHidden: gridHidden, clamp: clamp,
                 backVisible: backVisible, focusInDetail: focusInDetail,
                 escapedToList: escapedToList, focusBackOnCard: focusBackOnCard,
                 backToGrid: backToGrid, focusAfterButton: focusAfterButton,
                 textFits: txt ? (txt.scrollHeight <= txt.clientHeight + 1) : null };
      })()`);
      check(flow && flow.helpOpen === true, '[390x844] 图鉴（帮助弹窗）在打开状态（后面几条断言的前提）', flow && { helpOpen: flow.helpOpen });
      check(flow && flow.detailShown === true, '[390x844] 图鉴点卡切到详情页', flow);
      check(flow && flow.gridHidden === 'none', '[390x844] 详情页把卡网格收起', flow && flow.gridHidden);
      check(flow && flow.clamp === 'none', '[390x844] 详情页的效果说明不截断（能读全）', flow && flow.clamp);
      check(flow && flow.textFits === true, '[390x844] 详情页效果说明完整放得下（无滚动裁切）', flow && flow.textFits);
      check(flow && flow.backVisible === true && flow.backToGrid === true, '[390x844] 「返回图鉴」可见且能回到列表', flow);
      check(flow && flow.focusInDetail === true, '[390x844] 点卡后焦点进入详情页', flow && { focusInDetail: flow.focusInDetail });
      check(flow && flow.escapedToList === true, '[390x844] Esc 从详情页回到列表', flow && { escapedToList: flow.escapedToList });
      check(flow && flow.focusBackOnCard === true, '[390x844] Esc 返回后焦点回到刚才那张卡', flow && { focusBackOnCard: flow.focusBackOnCard });
      check(flow && flow.focusAfterButton === true, '[390x844] 按钮返回后焦点也回到刚才那张卡', flow && { focusAfterButton: flow.focusAfterButton });
    }

    if (SHOTS) {
      for (const screen of SCREENS) {
        const cfg = JSON.stringify({ key: screen.key, root: screen.root || null, modal: screen.modal || null,
          marker: screen.marker, before: screen.before || null, after: null });
        await ev('(' + PROBE + ')(' + cfg + ')');
        await sleep(450);
        const shot = await send('Page.captureScreenshot', { format: 'png' });
        const file = path.join(SHOTS, vlabel, screen.key + '.png');
        fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
      }
      // 图鉴详情页也留一张（窄屏那半页是独立的验收项，没图说不清）
      if (w < 600) {
        await ev(`(function(){ document.querySelectorAll('.screen').forEach(function(s){ s.classList.remove('active'); });
          document.querySelectorAll('.modal-overlay').forEach(function(m){ m.classList.add('hidden'); });
          document.getElementById('help-btn').click();
          var g = document.getElementById('help-magic-cards'); var f = g && g.querySelector('.magic-card-help');
          if (f) f.click(); return 1; })()`);
        await sleep(450);
        const shot = await send('Page.captureScreenshot', { format: 'png' });
        fs.writeFileSync(path.join(SHOTS, vlabel, 'collection-detail.png'), Buffer.from(shot.data, 'base64'));
      }
    }
  }

  check(jsProblems.length === 0, '全程零 JS 异常', jsProblems.slice(0, 4));

  if (SHOTS) {
    manifest.gate = gateSeen;
    manifest.notes.push(SHELL_ONLY.size + ' 屏是"直接切屏"的空壳（' + [...SHELL_ONLY].join('/') +
      '）—— 它们只证明外壳与布局，不证明这一屏有数据时的样子；有数据态由 cplus_path_check / replay_check / spectate_check 覆盖。');
    manifest.notes.push('游客态（未登录）时 profile 屏是空档案；本工具在清单里记 guest 标志，不能当"本人档案"的验收。');
    fs.writeFileSync(path.join(SHOTS, 'MANIFEST.json'), JSON.stringify(manifest, null, 2));
    console.log('   截图清单 ' + path.join(SHOTS, 'MANIFEST.json') + '（含 shell/entered 标注，别把 shell 当完成态）');
  }

  console.log('');
  if (problems.length) {
    console.log('✗ ' + problems.length + ' 项未通过：');
    problems.forEach((p) => console.log('   · ' + p));
    exitCode = 1;
  } else {
    console.log('✓ 全部通过');
  }
} finally {
  // 只关自己起的这一个实例；失败路径同样要走这里（原来失败会把无头浏览器留成孤儿）
  try { if (ws) ws.close(); } catch (e) { /* 已断 */ }
  try { browser.kill(); } catch (e) { /* 已经退了 */ }
}
process.exit(exitCode);
