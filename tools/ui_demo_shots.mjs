#!/usr/bin/env node
/**
 * UI 方案示意稿（docs/ui_demos/*.html）截图工具 —— 无头 Edge + CDP。
 *
 * 这些 demo 是**独立的静态 HTML**（不依赖 Flask / socket.io / 任何外部资源），
 * 所以不需要起服务端，直接 file:// 导航即可 —— 比 ui_layout_check.mjs 那套简单得多。
 *
 * 用法：
 *   node tools/ui_demo_shots.mjs                      # 全部 demo × 全部视口 × 全部视图
 *   node tools/ui_demo_shots.mjs --only a-tactical     # 只渲染一个 demo
 *   node tools/ui_demo_shots.mjs --view home           # 只渲染首页视图
 *
 * 依赖 demo 页面的约定（见 docs/ui_demos/README 段的「示意稿契约」）：
 *   window.__demoViews  = ['home','game']  视图名数组
 *   window.setDemoView(name)               切换视图（同步生效，无需等动画）
 *   #demo-switcher                         页内切换条，截图前会被隐藏
 *
 * ⚠️ 与 ui_layout_check.mjs 同一套教训：
 *   - 持久 profile 会带着上一轮状态 → 每次跑之前清掉；
 *   - 残留无头进程会让新浏览器静默起不来 → 用不同的调试端口，跑完 kill 掉。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DEMO_DIR = path.join(ROOT, 'docs', 'ui_demos');
const OUT_DIR = path.join(DEMO_DIR, 'shots');

const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const ONLY = argOf('--only', '');
const ONLY_VIEW = argOf('--view', '');
// --probe "sel1,sel2" 打印这些选择器的矩形（示意稿也会排版溢出，猜数字不如量一遍）
const PROBE = argOf('--probe', '');
const PORT = Number(argOf('--port', '9344'));
const PROFILE = path.join(ROOT, '.tmp', 'ui_demo_shots_profile_' + PORT);

const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过 demo 截图'); process.exit(0); }

/** 每个 demo 的视图名与视口。视口宽高取自本项目真正在意的档位（宽屏 1440/1280、手机 390）。 */
const DEMOS = [
  { file: 'arena-suite.html', views: ['lobby','room','placement','collection','leaderboard','profile','result','spectate','replay','settings'], viewports: [[1440, 900, 1], [1280, 720, 1], [390, 844, 1]] },
  { file: 'x-arena-evolved.html', views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1], [390, 844, 1]] },
  { file: 'y-bridge.html', views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1], [390, 844, 1]] },
  { file: 'z-focus.html', views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1], [390, 844, 1]] },
  { file: 'a-tactical.html',  views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'b-tabletop.html',  views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'c-arena.html',     views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'd-mobile.html',    views: ['home', 'game'], viewports: [[1440, 900, 1], [390, 844, 2]] },
  // 汇总页额外出一张「整页」长图，便于一次看完所有方向
  { file: 'e-sonar.html',     views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'f-minimal.html',   views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'g-neon.html',      views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  // 新方案（产品级重设计）：同一个文件在手机与桌面各出一套图，用来证明"两端同一套设计"
  // 第四批（按用户反馈精修：以 C 为底、双盘等大、实体手牌两级预览、去商业化）
  // 移动端调优：按项目自己的紧凑档三档视口渲染（与 ui_layout_check 的 COMPACT_VIEWPORTS 对齐）
  { file: 'v-result.html',     views: ['win', 'lose'],   viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'w-collection.html', views: ['collection'],    viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'u-mine-hero.html',  views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 't-targeting.html', views: ['pick', 'confirm', 'invalid'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 's-mobile.html',    views: ['game', 'sheet', 'spec'], viewports: [[390, 844, 2], [320, 568, 2], [664, 336, 2]] },
  { file: 'r-real-cards.html', views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'o-hand.html',      views: ['game', 'fan', 'flows'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'p-arena-min.html', views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'm-arena-pro.html', views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'l-route.html',     views: ['home', 'game'], viewports: [[1440, 900, 1], [390, 844, 2]] },
  { file: 'k-widgets.html',   views: ['home', 'game'], viewports: [[1440, 900, 1], [390, 844, 2]] },
  { file: 'j-workbench.html', views: ['home', 'game'], viewports: [[1440, 900, 1], [390, 844, 2]] },
  { file: 'i-one-sea.html',   views: ['home', 'game'], viewports: [[1440, 900, 1], [390, 844, 2]] },
  { file: 'h-pixel.html',     views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'f-minimal.html',   views: ['home', 'game'], viewports: [[1440, 900, 1], [1280, 720, 1]] },
  { file: 'index.html',       views: ['gallery'],     viewports: [[1440, 900, 1], [1440, 5200, 1]] },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let browser = null, ws = null;
const pending = new Map();
let seq = 0;

function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error('timeout ' + method)); } }, 20000);
  });
}

async function ev(expression) {
  const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error('页面异常: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
}

async function setViewport(width, height, deviceScaleFactor, mobile) {
  // deviceScaleFactor 必须是 number（传 boolean 会被 CDP 拒收）。
  // dsf=1 得 1:1 截图；手机档用 dsf=2 看清真机观感。
  await send('Emulation.setDeviceMetricsOverride', {
    width, height, deviceScaleFactor, mobile: !!mobile, screenWidth: width, screenHeight: height,
  });
}

const problems = [];

async function renderDemo(demo) {
  const abs = path.join(DEMO_DIR, demo.file);
  if (!fs.existsSync(abs)) { problems.push('缺少文件: ' + demo.file); return; }
  const url = pathToFileURL(abs).href;
  for (const [w, h, dsf] of demo.viewports) {
    await setViewport(w, h, dsf, false);
    await send('Page.navigate', { url });
    await sleep(450);
    const views = await ev('Array.isArray(window.__demoViews) ? window.__demoViews : []');
    if (!views.length) { problems.push(demo.file + ' 未声明 window.__demoViews'); continue; }
    for (const view of views) {
      if (ONLY_VIEW && view !== ONLY_VIEW) continue;
      await ev('(function(){ var s = document.getElementById("demo-switcher"); if (s) s.style.display = "none"; window.setDemoView(' + JSON.stringify(view) + '); return true; })()');
      await sleep(320);
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      const name = demo.file.replace(/\.html$/, '') + '-' + view + '-' + w + 'x' + h + '.png';
      fs.writeFileSync(path.join(OUT_DIR, name), Buffer.from(shot.data, 'base64'));
      console.log('已截图 ' + name);
      if (demo.file === 'arena-suite.html') {
        const suiteChecks = await ev(`(async () => {
          const errors = [];
          const check = (ok, message) => { if (!ok) errors.push(message); };
          const click = selector => document.querySelector(selector).click();
          const input = (selector, value, event = 'input') => {
            const el = document.querySelector(selector); el.value = value;
            el.dispatchEvent(new Event(event, { bubbles: true }));
          };
          check(document.documentElement.scrollWidth <= innerWidth, '页面横向溢出');
          check(document.querySelector('.suite-nav [aria-current="page"]')?.dataset.go === ${JSON.stringify(view)}, '导航当前页错误');
          switch (${JSON.stringify(view)}) {
            case 'lobby':
              click('[data-room-filter="等待加入"]');
              check(document.querySelectorAll('.room-card').length === 2, '房间状态筛选错误');
              input('#room-search', '不存在的房间');
              check(!!document.querySelector('#room-list .empty'), '搜索空态缺失');
              input('#room-search', '');
              input('#room-code', 'xyz'); click('[data-action="join"]');
              check(document.querySelector('#room-code').getAttribute('aria-invalid') === 'true', '无效房间号未标记');
              input('#room-code', 'a7c2e1'); click('[data-action="join"]');
              check(document.body.dataset.screen === 'room', '加入房间未跳转');
              window.setDemoView('lobby'); click('[data-room-filter="全部房间"]'); break;
            case 'room':
              if (document.querySelector('[data-action="ready"]')) click('[data-action="ready"]');
              check(!!document.querySelector('.ready-footer [data-go="placement"]'), '准备后无部署入口'); break;
            case 'placement':
              if (innerWidth >= 1000) check(document.querySelector('#confirm-deployment').getBoundingClientRect().bottom <= innerHeight, '桌面部署确认按钮超出视口');
              click('[data-action="clear"]');
              check(document.querySelector('#confirm-deployment').disabled, '未部署时按钮可用');
              click('[data-action="random"]');
              check(document.querySelectorAll('.s-cell.placed').length === 6 && !document.querySelector('#confirm-deployment').disabled, '随机部署不是6个独立格子');
              click('.s-cell:not(.placed)');
              check(document.querySelectorAll('.s-cell.placed').length === 6, '允许部署第7艘');
              click('[data-action="deploy"]');
              check(document.querySelector('#suite-dialog').open, '部署确认没有反馈');
              document.querySelector('#suite-dialog').close();
              click('.s-cell.placed');
              check(document.querySelectorAll('.s-cell.placed').length === 5 && document.querySelector('#confirm-deployment').disabled, '撤回舰船失败'); break;
            case 'collection':
              input('#card-search', '硫磺火焰');
              check(document.querySelectorAll('#codex-grid [data-card]').length === 1, '卡名搜索失败');
              click('#codex-grid [data-card]');
              check(document.querySelector('#card-inspector').textContent.includes('连续连接的6个格子'), '卡牌规则详情错误');
              if (document.querySelector('#suite-dialog').open) document.querySelector('#suite-dialog').close();
              input('#card-search', ''); click('[data-type="场地"]');
              check(document.querySelectorAll('#codex-grid [data-card]').length === 4, '场地筛选错误');
              input('#speed-filter', '1', 'change');
              check([...document.querySelectorAll('#codex-grid .card-bottom')].every(el=>el.textContent.includes('速阶 1')), '速阶筛选错误');
              input('#card-search', '完全不存在'); check(!!document.querySelector('#codex-grid .empty'), '图鉴无空态');
              input('#card-search', ''); input('#speed-filter', '全部速阶', 'change'); click('[data-type="全部"]'); break;
            case 'leaderboard':
              click('[data-rank="胜率"]');
              check(document.querySelector('.podium-score').textContent.includes('%'), '排行指标未切换');
              click('[data-player="舰长阿 7"]');
              check(document.querySelector('#suite-dialog').open && document.querySelector('#suite-dialog-content').textContent.includes('1240'), '排行档案未打开');
              document.querySelector('#suite-dialog').close(); click('[data-rank="积分"]'); break;
            case 'profile':
              click('[data-badge="1"]'); check(document.querySelector('#equipped-name').textContent === '五连胜', '徽章佩戴预览失败');
              click('[data-badge="0"]'); break;
            case 'result':
              click('[data-result="lose"]'); check(!!document.querySelector('.defeat') && document.querySelector('.points-gain').textContent.includes('−16'), '败方结算状态错误');
              click('[data-result="win"]'); break;
            case 'spectate':
              check(document.querySelectorAll('.s-cell').length === 72 && !document.querySelector('.s-cell.placed'), '观战存在非公开船位或棋盘缺失');
              check([...document.querySelectorAll('.s-cell')].every(el=>el.disabled), '观战棋盘可操作'); break;
            case 'replay':
              input('#timeline', '0'); check(!document.querySelector('.s-cell.hit,.s-cell.miss'), '回放零时刻仍有攻击');
              click('[data-action="next"]'); check(document.querySelector('#timeline').value === '1', '回放下一步失败');
              input('#timeline', '8'); click('[data-action="play"]');
              await new Promise(resolve=>setTimeout(resolve,1150));
              check(Number(document.querySelector('#timeline').value) > 0 && Number(document.querySelector('#timeline').value) < 8, '回放播放未从头推进');
              click('[data-action="play"]'); input('#timeline', '4'); break;
            case 'settings':
              click('[data-theme="teal"]'); check(document.body.style.getPropertyValue('--accent') === '#69cfce', '强调色预览失败');
              input('#music-volume', '70'); check(document.querySelector('output').textContent === '70%', '音量值不同步');
              click('#high-contrast'); check(document.body.classList.contains('contrast-preview'), '高对比未应用');
              window.setDemoView('lobby'); window.setDemoView('settings');
              check(document.querySelector('[data-theme="teal"]').getAttribute('aria-pressed') === 'true' && document.querySelector('#music-volume').value === '70' && document.querySelector('#high-contrast').checked, '返回设置页状态不一致');
              click('#high-contrast'); click('[data-theme="violet"]'); input('#music-volume', '45'); break;
          }
          window.setDemoView(${JSON.stringify(view)});
          return errors;
        })()`);
        suiteChecks.forEach(message => problems.push(demo.file + ' ' + w + 'x' + h + ' ' + view + ': ' + message));
        console.log('  全流程布局 / 交互: ' + (suiteChecks.length ? suiteChecks.join('；') : '通过'));
      }
      if (/^[xyz]-/.test(demo.file)) {
        const checks = await ev(`(() => {
          const errors = [];
          if (document.documentElement.scrollWidth > innerWidth) errors.push('页面横向溢出');
          if (${JSON.stringify(view)} === 'game') {
            const hand = document.querySelector('.hand-zone').getBoundingClientRect();
            if (innerWidth >= 901 && hand.bottom > innerHeight) errors.push('桌面手牌超出视口: ' + hand.bottom);
            const sea = document.querySelector('.enemy');
            sea.querySelector('.cell:not(.hit):not(.miss)').click();
            if (document.querySelector('#fire').disabled || !sea.querySelector('.selected')) errors.push('选格失败');
            const cell = sea.querySelector('.selected');
            document.querySelector('#fire').click();
            if (!cell.classList.contains('miss') || !document.querySelector('#fire').disabled) errors.push('攻击确认失败');
          } else {
            document.querySelector('[data-difficulty="困难"]').click();
            if (document.querySelector('[data-difficulty="困难"]').getAttribute('aria-pressed') !== 'true') errors.push('难度切换失败');
          }
          document.querySelector('.screen:not([hidden]) [data-card="0"]').click();
          const modal = document.querySelector('#detail');
          if (!modal.open || !modal.textContent.includes('硫磺火焰')) errors.push('卡牌详情失败');
          modal.close();
          return errors;
        })()`);
        checks.forEach(message => problems.push(demo.file + ' ' + w + 'x' + h + ' ' + view + ': ' + message));
        console.log('  布局 / 交互检查: ' + (checks.length ? checks.join('；') : '通过'));
      }
      if (PROBE) {
        const out = await ev('(function(){' +
          'var sels=' + JSON.stringify(PROBE) + '.split(",");var o={};' +
          'sels.forEach(function(s){s=s.trim();var e=document.querySelector(s);' +
          'if(!e){o[s]="missing";return;}var b=e.getBoundingClientRect();' +
          'o[s]=[Math.round(b.x),Math.round(b.y),Math.round(b.width),Math.round(b.height),Math.round(b.bottom)];});' +
          'o.__vh=window.innerHeight;o.__vw=window.innerWidth;return JSON.stringify(o);})()');
        console.log('  PROBE ' + w + 'x' + h + ' ' + view + ' -> ' + out);
      }
    }
  }
  // 顺手查一遍页面有没有报错（示意稿是静态页，有 JS 异常就是真问题）
  const errs = await ev('window.__demoErrors || []');
  if (errs.length) problems.push(demo.file + ' 有 JS 异常: ' + JSON.stringify(errs.slice(0, 3)));
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  // 清 profile：持久 profile 会带上一轮的 localStorage / 视图状态
  if (path.dirname(PROFILE) !== path.join(ROOT, '.tmp')) throw new Error('Profile escaped workspace .tmp');
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) { /* 无所谓 */ }

  browser = spawn(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE, '--window-size=1440,900', '--force-device-scale-factor=1',
    '--allow-file-access-from-files', 'about:blank',
  ], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page' && /^(https?|file):/.test(t.url || ''))
        || list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* 还在启动 */ }
    await sleep(500);
  }
  if (!target) { console.error('无法连接无头浏览器调试端口'); process.exit(1); }

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
    if (m.method === 'Runtime.exceptionThrown') problems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });

  const targets = ONLY ? DEMOS.filter((d) => d.file.startsWith(ONLY)) : DEMOS;
  for (const d of targets) await renderDemo(d);

  console.log('\n' + (problems.length ? '有问题：\n  ' + problems.join('\n  ') : '全部截图完成，无页面异常'));
  console.log('输出目录: ' + OUT_DIR);

  try { ws.close(); } catch (e) { /* 忽略 */ }
  try { browser.kill(); } catch (e) { /* 忽略 */ }
  process.exit(problems.length ? 1 : 0);
})().catch((e) => {
  console.error('失败: ' + e.message);
  try { browser && browser.kill(); } catch (_) { /* 忽略 */ }
  process.exit(1);
});
