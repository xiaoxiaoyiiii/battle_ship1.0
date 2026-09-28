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
const PROFILE = path.join(ROOT, '.tmp', 'ui_demo_shots_profile');

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
