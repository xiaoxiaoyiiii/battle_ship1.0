#!/usr/bin/env node
/**
 * 卡牌图鉴回归检查（无头 Edge + CDP）
 *
 * 背景：41 张卡此前只有帮助弹窗里一段"平铺列表"（纯 <div>，没有检索/筛选）。
 * 本脚本验证新的图鉴：数量正确（失灵！×3 去重成 1 张）、按速阶/类型筛选、
 * 关键词搜索（卡名 + 效果文本），并且筛选后计数与实际渲染条数一致。
 *
 * 用法：node tools/card_compendium_check.mjs --url http://127.0.0.1:5000/
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const NL = String.fromCharCode(10);
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const APP = argOf('--url', 'http://127.0.0.1:5000/');
const PORT = 9340;
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));
const PROFILE = 'C:/Windows/Temp/card_compendium_profile';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!BROWSER) { console.error('找不到 Edge/Chrome，跳过图鉴检查'); process.exit(0); }

let browser = null, ws = null;
const pending = new Map();
const problems = [];
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
  if (r.exceptionDetails) throw new Error('page exception: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result && r.result.value;
}

async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (await fn()) return true; } catch (e) { /* keep polling */ }
    await sleep(150);
  }
  throw new Error('等待超时: ' + label);
}

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// 在页面里按"独立实现"算期望值，避免用被测代码自己的结果自我验证
const EXPECTED = '(function(){' +
  ' var seen = {}, uniq = [];' +
  ' (window.magicCards || []).forEach(function (c) { var k = c.name + "|" + c.type + "|" + c.speed + "|" + c.description; if (!seen[k]) { seen[k] = 1; uniq.push(c); } });' +
  ' function count(speed, type) { return uniq.filter(function (c) { if (speed && String(c.speed) !== speed) return false; if (type && c.type !== type) return false; return true; }).length; }' +
  ' return { unique: uniq.length, raw: (window.magicCards || []).length, speed1: count("1"), speed2: count("2"), speed3: count("3"), field: count("", "\u573a\u5730") }; })()';

function state() {
  return '(function(){ var grid = document.getElementById("help-magic-cards");' +
    ' var cards = grid ? grid.querySelectorAll(".magic-card-help") : [];' +
    ' var counter = document.getElementById("compendium-count");' +
    ' return { rendered: cards.length, names: [].slice.call(cards).map(function (c) { return c.getAttribute("data-card-name"); }),' +
    '   counter: counter ? counter.textContent.trim() : null }; })()';
}

function setFilter(selector, value) {
  return '(function(){ var el = document.querySelector("' + selector + '");' +
    ' if (!el) return "no-el"; el.value = ' + JSON.stringify(value) + ';' +
    ' el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); return "ok"; })()';
}

try {
  browser = spawn(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE, '--window-size=1600,1000', '--force-device-scale-factor=1',
    'about:blank',
  ], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find((t) => t.type === 'page');
      if (target) break;
    } catch (e) { /* browser still starting */ }
    await sleep(500);
  }
  if (!target) throw new Error('无法连接无头浏览器调试端口');

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('websocket 连接失败')); });
  const jsProblems = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result); return; }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: APP });
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');

  const expect = await ev(EXPECTED);
  check(expect && expect.unique === 41 && expect.raw === 43, '卡池数据：43 条目 / 41 唯一（失灵！×3 为设计）', expect);

  // 装一个受控的使用次数响应：必须在**第一次打开图鉴之前**装好，
  // 因为 game.js 里 /api/card_usage 只拉一次就缓存，晚了就再也替换不掉。
  await ev('(function(){ var orig = window.fetch; window.fetch = function (url) {' +
    ' if (String(url).indexOf("/api/card_usage") >= 0) {' +
    '   return Promise.resolve({ ok: true, json: function () {' +
    '     return Promise.resolve({ usage: { "冻结": 7, "无中生有": 3 }, total: 10 }); } }); }' +
    ' return orig.apply(window, arguments); }; return 1; })()');

  await ev('document.getElementById("help-btn").click()');
  await waitFor(async () => await ev('(function(){ var m = document.getElementById("help-modal"); return m && !m.classList.contains("hidden"); })()'), 5000, '帮助弹窗打开');
  await sleep(300);

  const all = await ev(state());
  check(all.rendered === expect.unique, '图鉴默认渲染全部唯一卡（' + expect.unique + ' 张）', { rendered: all.rendered });
  check(all.names.filter((n) => n === '失灵！').length === 1, '重复的「失灵！」只展示一张', all.names.filter((n) => n === '失灵！').length);
  check(all.counter && all.counter.indexOf(String(expect.unique)) >= 0, '计数文案与实际一致', all.counter);

  // ---------- 使用次数（图鉴的"这张卡有多常用"） ----------
  const usageState = await ev('(function(){' +
    ' var cards = [].slice.call(document.querySelectorAll("#help-magic-cards .magic-card-help"));' +
    ' var marked = {};' +
    ' cards.forEach(function (c) { var u = c.getAttribute("data-card-uses"); if (u && u !== "0") marked[c.getAttribute("data-card-name")] = u; });' +
    ' var badge = document.querySelector("#help-magic-cards .compendium-uses");' +
    ' return { marked: marked, badge: badge ? badge.textContent.trim() : null }; })()');
  check(usageState.marked['冻结'] === '7' && usageState.marked['无中生有'] === '3',
    '卡面带上使用次数（来自 /api/card_usage）', usageState.marked);
  check(/使用 7 次/.test(usageState.badge || ''), '使用次数有可见角标', usageState.badge);

  await ev(setFilter('#compendium-sort', 'uses'));
  await sleep(250);
  const topTwo = await ev('(function(){ return [].slice.call(document.querySelectorAll("#help-magic-cards .magic-card-help"))' +
    '.slice(0, 2).map(function (c) { return c.getAttribute("data-card-name"); }); })()');
  check(topTwo[0] === '冻结', '按使用次数排序后最常用的排最前', topTwo);
  await ev(setFilter('#compendium-sort', ''));

  for (const [label, expected] of [['1', expect.speed1], ['2', expect.speed2], ['3', expect.speed3]]) {
    await ev(setFilter('#compendium-speed', label));
    await sleep(150);
    const st = await ev(state());
    check(st.rendered === expected, '速阶 ' + label + ' 筛选命中 ' + expected + ' 张', { rendered: st.rendered });
    const speeds = await ev('(function(){ return [].slice.call(document.querySelectorAll("#help-magic-cards .magic-card-help")).map(function(c){return c.getAttribute("data-card-speed");}); })()');
    check(speeds.every((v) => v === label), '筛选结果速阶全是 ' + label, speeds.slice(0, 5));
  }

  await ev(setFilter('#compendium-speed', ''));
  await ev(setFilter('#compendium-type', '场地'));
  await sleep(150);
  const field = await ev(state());
  check(field.rendered === expect.field && field.rendered === 4, '场地魔法筛选命中 4 张', { rendered: field.rendered, expected: expect.field });

  await ev(setFilter('#compendium-type', ''));
  await ev(setFilter('#compendium-search', '冻结'));
  await sleep(150);
  const search = await ev(state());
  check(search.rendered >= 1 && search.names.indexOf('冻结') >= 0, '按卡名搜索「冻结」命中', search.names);

  await ev(setFilter('#compendium-search', '无敌'));
  await sleep(150);
  const byDesc = await ev(state());
  check(byDesc.rendered >= 1, '按效果文本搜索「无敌」也有命中', { rendered: byDesc.rendered });

  await ev(setFilter('#compendium-search', 'zzz-not-a-card'));
  await sleep(150);
  const empty = await ev(state());
  check(empty.rendered === 0 && /没有符合条件/.test(await ev('document.getElementById("help-magic-cards").textContent')), '无命中时给出空状态提示', empty);

  await ev(setFilter('#compendium-search', ''));
  await sleep(150);
  await ev('document.getElementById("help-modal-close").click()');
  await sleep(200);
  check(await ev('document.getElementById("help-modal").classList.contains("hidden")'), '关闭帮助后弹窗隐藏');

  check(jsProblems.length === 0, '页面无 JS 异常/报错', jsProblems);
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
  console.log(NL + (problems.length ? '结果: ' + problems.length + ' 项不通过' + NL + problems.map((p) => '  - ' + p).join(NL) : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
}
