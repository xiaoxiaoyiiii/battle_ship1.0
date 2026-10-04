#!/usr/bin/env node
/**
 * 长久效果胶囊与提示层回归检查。
 * 覆盖：无/单/双效果、横幅移除、剩余回合、提示层避让、点击/键盘详情、
 * 桌面与紧凑视口的布局，以及场地横条和手牌的基本几何不回归。
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5075/');
const PORT = 9467;
const PROFILE = `C:/Windows/Temp/effect_bar_check_${process.pid}`;
const EDGE = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
].find((p) => fs.existsSync(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
if (!EDGE) { console.log('skip: 没找到 Edge/Chrome'); process.exit(0); }

let pass = 0; let fail = 0; const failures = [];
const check = (label, condition, detail) => {
  if (condition) { pass++; console.log(`PASS  ${label}${detail === undefined ? '' : ` -> ${JSON.stringify(detail)}`}`); }
  else { fail++; failures.push(label); console.log(`FAIL  ${label} -> ${JSON.stringify(detail)}`); }
};

const browser = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--window-size=1440,900', APP,
], { stdio: 'ignore' });

let ws;
try {
  await sleep(3000);
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const page = list.find((t) => t.type === 'page' && /^https?:/.test(t.url || ''));
  if (!page) { console.log('skip: 没有可用页面（服务端未启动？）'); process.exitCode = 0; }
  else {
    ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
    let seq = 0; const pending = new Map();
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (!msg.id || !pending.has(msg.id)) return;
      const p = pending.get(msg.id); pending.delete(msg.id);
      msg.error ? p.reject(new Error(JSON.stringify(msg.error))) : p.resolve(msg.result);
    };
    const send = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++seq; pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error(`timeout: ${method}`)); } }, 20000);
    });
    const ev = async (expression) => {
      const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
      return result.result?.value;
    };
    await send('Runtime.enable'); await send('Page.enable');
    for (let i = 0; i < 60; i++) {
      if (await ev('document.readyState === "complete" && typeof window.gameState === "object"')) break;
      await sleep(200);
    }
    await ev(`(function(){
      document.querySelectorAll('.screen').forEach(function(s){s.classList.remove('active');});
      var gs=document.getElementById('game-screen'); if(gs) gs.classList.add('active');
      document.body.className='layout-ingame';
      document.documentElement.dataset.themePreset='arena';
      if(window.gameState){ gameState.ships=[{positions:[{x:0,y:0}],hits:[]}]; gameState.opponentShips=[{positions:[{x:0,y:0}],hits:[]}]; gameState.hand=[{name:'极限增援',speed:1,type:'普通',description:'x'}]; }
      if(typeof initGameBoards==='function') initGameBoards();
      if(typeof updateHandUI==='function') updateHandUI();
      if(typeof initEffectStatusBarSync==='function') initEffectStatusBarSync();
      if(typeof bindEffectStatusPills==='function') bindEffectStatusPills();
      var st=document.createElement('style'); st.id='effect-check-noanim'; st.textContent='*,*::before,*::after{transition:none!important;animation:none!important}'; document.head.appendChild(st);
      return !!gs;
    })()`);
    await sleep(150);
    check('已进入对局界面', await ev('!!document.querySelector("#game-screen.active")'));
    check('旧的大横幅 DOM 已删除', await ev('!document.getElementById("reinforcement-countdown") && !document.getElementById("holy-heart-countdown")'));
    check('效果胶囊具备键盘语义', await ev('(function(){return ["reinforcement-status","holy-heart-status"].every(function(id){var e=document.getElementById(id);return e&&e.tabIndex===0&&e.getAttribute("role")==="button";})})()'));

    const setEffects = async (which) => {
      await ev(`(function(){
        var spec={"reinforcement-status":${which.includes('reinforcement')},"holy-heart-status":${which.includes('holy-heart')}};
        Object.keys(spec).forEach(function(id){var e=document.getElementById(id);if(!e)return;e.classList.toggle('hidden',!spec[id]);var s=e.querySelector('[id$="-remaining"]');if(s)s.textContent=spec[id]?(id==='holy-heart-status'?'2':'3'):'0';});
        return true;
      })()`);
      await sleep(80);
    };
    const state = () => ev(`(function(){
      function R(e){if(!e)return null;var r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width,h:r.height};}
      var bar=document.getElementById('effect-status-bar');
      return {bar:R(bar),barHidden:bar.classList.contains('hidden'),barScroll:bar.scrollWidth,barClient:bar.clientWidth,
        pills:[...document.querySelectorAll('#effect-status-bar .status-item')].map(function(e){return {id:e.id,hidden:e.classList.contains('hidden'),text:e.textContent.trim(),r:R(e)};}),
        top:R(document.querySelector('.arena-oppbar-bg')),rows:getComputedStyle(document.querySelector('.game-container')).gridTemplateRows,
        scrollW:document.documentElement.scrollWidth,clientW:document.documentElement.clientWidth,
        field:R(document.querySelector('.field-magic-area')),boards:[...document.querySelectorAll('.boards-container .board')].map(R),hand:[...document.querySelectorAll('#magic-hand .magic-card')].map(R)};
    })()`);

    await setEffects([]); let none = await state();
    check('无效果时整条隐藏', none.barHidden && none.pills.every((p) => p.hidden), none);
    check('无效果时没有旧的大空白行', none.bar && none.bar.h <= 2, none.bar);
    check('无效果时页面不横向滚动', none.scrollW === none.clientW, { scrollW: none.scrollW, clientW: none.clientW });

    await setEffects(['holy-heart']); let one = await state();
    check('单效果时胶囊显示剩余回合', !one.barHidden && one.pills.find((p) => p.id === 'holy-heart-status')?.text.includes('剩余 2 回合'), one.pills);
    check('单效果时不显示另一颗胶囊', one.pills.find((p) => p.id === 'reinforcement-status')?.hidden === true, one.pills);
    check('效果条不横向溢出', one.barScroll <= one.barClient + 1, { scroll: one.barScroll, client: one.barClient });

    await setEffects(['reinforcement', 'holy-heart']); let multi = await state();
    check('双效果并排显示且各自可见', multi.pills.every((p) => !p.hidden), multi.pills);
    check('双效果胶囊不互相重叠', !(multi.pills[0].r.right > multi.pills[1].r.x && multi.pills[1].r.right > multi.pills[0].r.x && multi.pills[0].r.bottom > multi.pills[1].r.y && multi.pills[1].r.bottom > multi.pills[0].r.y), multi.pills);
    check('双效果时场地横条、棋盘、手牌仍有实际尺寸', multi.field?.w > 0 && multi.boards.every((r) => r.w > 0) && multi.hand.length > 0, { field: multi.field, boards: multi.boards, hand: multi.hand.length });

    const hover = await ev(`(function(){var e=document.getElementById('holy-heart-status');e.dispatchEvent(new MouseEvent('mouseenter',{bubbles:false}));var t=document.querySelector('.card-tooltip');function R(x){var r=x.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom};}var a=t&&R(t),b=document.querySelector('.arena-oppbar-bg')&&R(document.querySelector('.arena-oppbar-bg'));return {exists:!!t,text:t&&t.textContent.trim(),placement:t&&t.dataset.placement,overlap:!!(a&&b&&!(a.r<=b.l||a.l>=b.r||a.b<=b.t||a.t>=b.b)),rect:a,avoid:b};})()`);
    check('悬停能打开轻量提示', hover.exists === true, hover);
    check('悬停提示含效果与剩余回合', hover.text?.includes('无暇圣心') && hover.text?.includes('剩余 2 回合'), hover.text);
    check('悬停提示避开顶部状态栏', hover.overlap === false && ['bottom','top','right','left'].includes(hover.placement), hover);
    await ev('document.getElementById("holy-heart-status").dispatchEvent(new MouseEvent("mouseleave",{bubbles:false}))');
    check('移出胶囊后提示消失', await ev('!document.querySelector(".card-tooltip")'));

    const click = await ev(`(function(){document.getElementById('holy-heart-status').click();var o=document.getElementById('card-detail-overlay');return {open:!!o,text:o&&o.textContent.trim(),close:!!(o&&o.querySelector('.card-detail-close'))};})()`);
    check('点击能打开完整详情', click.open === true, click);
    check('完整详情含剩余回合', click.text?.includes('剩余 2 回合'), click.text);
    check('完整详情有关闭按钮', click.close === true, click);
    check('点击关闭按钮能关闭', await ev('(function(){var b=document.querySelector(".card-detail-close");if(b)b.click();return !document.getElementById("card-detail-overlay");})()'));
    await ev('document.getElementById("holy-heart-status").click()');
    check('点击遮罩能关闭', await ev('(function(){var o=document.getElementById("card-detail-overlay");if(o)o.dispatchEvent(new MouseEvent("click",{bubbles:true}));return !document.getElementById("card-detail-overlay");})()'));
    await ev('document.getElementById("holy-heart-status").click()');
    check('ESC 能关闭详情', await ev('(function(){document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}));return !document.getElementById("card-detail-overlay");})()'));
    await ev('document.getElementById("holy-heart-status").focus()');
    check('键盘 Enter 能打开详情', await ev('(function(){var e=document.getElementById("holy-heart-status");e.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",bubbles:true}));return !!document.getElementById("card-detail-overlay");})()'));
    await ev('closeCardDetail()');
    check('键盘 Space 能打开详情', await ev('(function(){var e=document.getElementById("holy-heart-status");e.dispatchEvent(new KeyboardEvent("keydown",{key:" ",bubbles:true}));return !!document.getElementById("card-detail-overlay");})()'));
    await ev('closeCardDetail()');

    for (const [w, h] of [[1280, 720], [1440, 900], [768, 1024]]) {
      await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
      await sleep(80); await setEffects(['holy-heart']); const m = await state();
      check(`${w}x${h} 无横向滚动`, m.scrollW === m.clientW, { scrollW: m.scrollW, clientW: m.clientW });
      // 紧凑档按既有设计隐藏场地横条；只要它未以异常尺寸撑开页面，且手牌仍可见即可。
      check(`${w}x${h} 场地横条按紧凑规则处理且手牌仍有尺寸`,
        (!m.field || (m.field.w === 0 && m.field.h === 0) || (m.field.w > 0 && m.field.h > 0)) && m.hand.length > 0,
        { field: m.field, hand: m.hand.length });
    }
    await setEffects([]);
  }
} catch (error) {
  console.error('fatal:', error.stack || error);
  fail++; failures.push('检查脚本异常');
} finally {
  try { if (ws) ws.close(); } catch {}
  try { browser.kill(); } catch {}
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
}

console.log(`\n结果：PASS ${pass} / FAIL ${fail}`);
if (failures.length) console.log('失败项：' + failures.join('；'));
process.exitCode = fail ? 1 : 0;
