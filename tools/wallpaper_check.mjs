#!/usr/bin/env node
/**
 * 动态壁纸回归检查（无头 Edge + CDP）
 *
 * 验的是"整条链路真的通"：服务端扫到的壁纸 → 前端列表 → 点一张 → 壁纸层真的
 * 换成了它 → 四个参数真的写进了 CSS 变量 → 刷新后仍然记得。
 *
 * 为什么要连服务端一起起：
 *   "壁纸能不能用"有一半取决于服务端怎么解析创意工坊目录（project.json 的
 *   type/file、preview.* 的干扰、mkv 这种浏览器播不了的格式）。只测前端 DOM
 *   的话，恰好漏掉最容易出错的那一半。所以本脚本默认会：
 *     1) 造一个假的创意工坊目录（含 图片壁纸 / 视频壁纸 / 场景壁纸 / mkv 壁纸
 *        各一张），通过 BATTLESHIP_WALLPAPER_DIR 指给服务端；
 *     2) 起一个独立的服务端（端口随机、数据库指向临时文件，不碰正式库）；
 *     3) 跑无头浏览器断言。
 *   也可以用 --url 指到已经跑着的站点，此时只验前端（列表会依赖该站点的壁纸库）。
 *
 * 用法：
 *   node tools/wallpaper_check.mjs                      # 全自动（推荐）
 *   node tools/wallpaper_check.mjs --url http://127.0.0.1:5000/
 *   node tools/wallpaper_check.mjs --keep               # 失败时保留服务端日志
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath } from 'node:url';

const NL = String.fromCharCode(10);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const argv = process.argv.slice(2);
const argOf = (name, def) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : def; };
const KEEP = argv.includes('--keep');
const GIVEN_URL = argOf('--url', '');
const CDP_PORT = 9342;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- 假壁纸库

/** 造一张最小但**真正能显示**的 BMP（浏览器认 BMP，纯 Node 也能写）。 */
function bmp(width, height, rgb) {
  const rowSize = Math.ceil((width * 3) / 4) * 4;
  const pixelArraySize = rowSize * height;
  const fileSize = 54 + pixelArraySize;
  const buf = Buffer.alloc(fileSize);
  buf.write('BM', 0, 'ascii');
  buf.writeUInt32LE(fileSize, 2);
  buf.writeUInt32LE(54, 10);
  buf.writeUInt32LE(40, 14);
  buf.writeInt32LE(width, 18);
  buf.writeInt32LE(height, 22);
  buf.writeUInt16LE(1, 26);
  buf.writeUInt16LE(24, 28);
  buf.writeUInt32LE(pixelArraySize, 34);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const off = 54 + y * rowSize + x * 3;
      buf[off] = rgb[2]; buf[off + 1] = rgb[1]; buf[off + 2] = rgb[0];
    }
  }
  return buf;
}

const MP4_HEAD = Buffer.concat([Buffer.from([0, 0, 0, 0x18]), Buffer.from('ftypisom', 'ascii'), Buffer.alloc(200)]);
const WEBM_HEAD = Buffer.concat([Buffer.from([0x1a, 0x45, 0xdf, 0xa3]), Buffer.alloc(200)]);
const PKG_HEAD = Buffer.concat([Buffer.from('PK\x03\x04', 'binary'), Buffer.alloc(200)]);

function buildLibrary() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bs-wallpaper-lib-'));
  const put = (name, meta, files) => {
    const dir = path.join(root, name);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'project.json'), JSON.stringify(meta), 'utf8');
    for (const [file, data] of Object.entries(files)) fs.writeFileSync(path.join(dir, file), data);
  };
  // 图片壁纸（可播）
  put('101', { type: 'image', title: '珊瑚海', file: 'wall.bmp', preview: 'preview.bmp' },
    { 'wall.bmp': bmp(96, 60, [20, 120, 190]), 'preview.bmp': bmp(48, 30, [20, 120, 190]) });
  // 视频壁纸（可播：容器头是合法 ftyp，内容不是真视频 —— 端上会走到"加载失败"提示，
  // 这正好用来验错误提示有没有出现）
  put('102', { type: 'video', title: '星轨', file: 'wall.mp4', preview: 'preview.bmp' },
    { 'wall.mp4': MP4_HEAD, 'preview.bmp': bmp(48, 30, [30, 30, 60]) });
  // 场景型壁纸（不可播，必须说明原因）
  put('103', { type: 'scene', title: '樱花场景', file: 'scene.pkg', preview: 'preview.bmp' },
    { 'scene.pkg': PKG_HEAD, 'preview.bmp': bmp(48, 30, [220, 160, 190]) });
  // mkv 视频（浏览器播不了）
  put('104', { type: 'video', title: '猎户座', file: 'wall.mkv', preview: 'preview.bmp' },
    { 'wall.mkv': WEBM_HEAD, 'preview.bmp': bmp(48, 30, [40, 40, 40]) });
  return root;
}

// ---------------------------------------------------------------- 起服务端

function freePort() {
  return new Promise((res, rej) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', rej);
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => res(port));
    });
  });
}

function pythonExe() {
  const venv = path.join(ROOT, '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(venv)) return venv;
  const posix = path.join(ROOT, '.venv', 'bin', 'python');
  return fs.existsSync(posix) ? posix : 'python';
}

async function reachable(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(2500) });
    return res.ok;
  } catch (e) {
    return false;
  }
}

async function startServer(libDir) {
  const port = await freePort();
  const url = 'http://127.0.0.1:' + port + '/';
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bs-wallpaper-srv-'));
  const logPath = path.join(tmp, 'server.log');
  const logFd = fs.openSync(logPath, 'w');
  const env = Object.assign({}, process.env, {
    FLASK_APP: 'server.py',
    PORT: String(port),
    // 隔离数据库：跑一次检查不该往正式库里写对局
    BATTLESHIP_DB_PATH: path.join(tmp, 'check.db'),
    BATTLESHIP_WALLPAPER_DIR: libDir,
  });
  const proc = spawn(pythonExe(), ['-m', 'flask', 'run', '--host=127.0.0.1', '--port=' + port],
    { cwd: ROOT, env, stdio: ['ignore', logFd, logFd] });
  const deadline = Date.now() + 40000;
  while (Date.now() < deadline) {
    if (await reachable(url)) return { proc, url, logPath };
    if (proc.exitCode !== null) break;
    await sleep(400);
  }
  const log = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8').slice(-800) : '(无日志)';
  try { proc.kill(); } catch (e) { /* ignore */ }
  throw new Error('服务端没起来。日志尾部：' + NL + log);
}

// ---------------------------------------------------------------- CDP

function pickPage(list) {
  const isApp = (t) => t.type === 'page' && /^(https?|file):/.test(t.url || '');
  return list.find(isApp) || list.find((t) => t.type === 'page' && t.url !== 'about:blank'
    && !/^(edge|chrome|devtools):/.test(t.url || '')) || list.find((t) => t.type === 'page');
}

const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
];
const BROWSER = EDGE_CANDIDATES.find((p) => fs.existsSync(p));

let browser = null;
let server = null;
let ws = null;
const pending = new Map();
const problems = [];
let seq = 0;

function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

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

async function waitFor(fn, timeout, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (await fn()) return true; } catch (e) { /* keep polling */ }
    await sleep(150);
  }
  throw new Error('等待超时: ' + label);
}

async function main() {
  if (!BROWSER) {
    console.error('找不到 Edge/Chrome，跳过壁纸检查');
    return;
  }

  const libDir = buildLibrary();
  let APP = GIVEN_URL;
  if (!APP || !(await reachable(APP))) {
    if (GIVEN_URL) console.log('提示：' + GIVEN_URL + ' 不可达，改为自起服务端');
    server = await startServer(libDir);
    APP = server.url;
    console.log('已起服务端：' + APP + '（壁纸库：' + libDir + '）');
  } else {
    console.log('使用已有站点：' + APP + '（按路径导入的用例会跳过）');
  }
  const selfHosted = !!server;

  // ⚠️ 无头 profile 放【项目内】的 .tmp/，不放 C:/Windows/Temp：
  // 本机该目录出现过 ACL 损坏（目录删不掉、Edge 起不来、调试端口连不上）。
  const tmpDir = path.join(ROOT, '.tmp');
  fs.mkdirSync(tmpDir, { recursive: true });
  browser = spawn(BROWSER, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--mute-audio', '--autoplay-policy=no-user-gesture-required',
    '--remote-debugging-port=' + CDP_PORT,
    '--user-data-dir=' + path.join(tmpDir, 'wallpaper_check_profile'),
    '--window-size=1440,900', '--force-device-scale-factor=1',
    'about:blank',
  ], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + CDP_PORT + '/json/list')).json();
      target = pickPage(list);
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
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      return;
    }
    if (m.method === 'Runtime.exceptionThrown') jsProblems.push('JS 异常: ' + JSON.stringify(m.params.exceptionDetails).slice(0, 200));
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      jsProblems.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 160));
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: APP });
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '页面加载');
  await waitFor(async () => await ev('!!window.wallpaperEngine'), 10000, '壁纸引擎实例');

  // profile 是复用的（放项目内便于排查），上一轮可能留下了壁纸偏好 ——
  // 无条件清一次再重新加载，否则"初始状态是关闭的"这条会假红。
  // （不写成"有才清"：Chromium 的 localStorage 落盘有延迟，被 kill 打断时
  //   上一轮的写入可能丢失，于是这一轮读到的是空的、下一轮又读到有值。）
  await ev('window.localStorage.removeItem(window.wallpaperEngine.STORAGE_KEY)');
  await send('Page.navigate', { url: APP });
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '清理后重新加载');
  await waitFor(async () => await ev('!!window.wallpaperEngine'), 10000, '清理后引擎实例');

  // 1) 初始状态
  const initial = await ev('(function(){ var s = window.wallpaperEngine.getStatus();' +
    ' return { active: s.active, kind: s.kind, layer: document.getElementById("wallpaper-layer").getAttribute("data-kind"),' +
    ' cls: document.documentElement.classList.contains("has-wallpaper"),' +
    ' containerBg: getComputedStyle(document.querySelector(".game-container")).backgroundColor, js: 1 }; })()');
  check(initial.active === false, '未设置时壁纸是关闭的', initial);
  check(initial.layer === 'none' && initial.cls === false, '壁纸层保持 none 且 html 未挂 has-wallpaper', initial);
  const bgOff = initial.containerBg;
  check(/rgba?\(/.test(bgOff), '容器背景色可读（用于对比壁纸开关后的差异）', bgOff);

  // 2) 打开设置面板 → 列表来自服务端扫描
  await ev('(function(){ document.getElementById("settings-btn").click(); return 1; })()');
  await waitFor(async () => await ev('!document.getElementById("settings-modal").classList.contains("hidden")'), 5000, '设置面板打开');
  const listed = await ev('window.wallpaperEngine.refreshList().then(function(){ return window.wallpaperEngine.getStatus(); })');
  check(listed.items === 4, '扫到 4 张壁纸（图片/视频/场景/mkv 各一）', listed);
  check(listed.usableItems === 2, '其中 2 张可用（场景型与 mkv 被判为不可用）', listed);

  // 缩略图带 loading=lazy，得先把这一段滚进可视区才会真的去取图
  await ev('(function(){ document.getElementById("wp-section").scrollIntoView({ block: "start" }); return 1; })()');
  try {
    await waitFor(async () => await ev(
      'Array.prototype.some.call(document.querySelectorAll("#wp-list .wp-thumb img"), function (i) { return i.naturalWidth > 0; })'
    ), 8000, '缩略图解码');
    check(true, '缩略图真的解码出来了（preview.bmp 生效）');
  } catch (e) {
    check(false, '缩略图真的解码出来了（preview.bmp 生效）', await ev(
      'Array.prototype.map.call(document.querySelectorAll("#wp-list .wp-thumb img"), function (i) {' +
      ' return { src: i.getAttribute("src"), w: i.naturalWidth, complete: i.complete }; })'));
  }

  const cards = await ev('(function(){' +
    ' var all = document.querySelectorAll("#wp-list .wp-item");' +
    ' var off = document.querySelectorAll("#wp-list .wp-item-off");' +
    ' var notes = Array.prototype.map.call(off, function (c) { return c.querySelector(".wp-note").textContent; });' +
    ' return { total: all.length, off: off.length, notes: notes,' +
    ' disabled: Array.prototype.every.call(off, function (c) { return c.disabled === true; }) }; })()');
  check(cards.total === 4 && cards.off === 2, '列表渲染出 4 张卡片，其中 2 张标为不可用', cards);
  check(cards.disabled === true, '不可用的壁纸卡片是 disabled（点了没反应，不是装作能点）', cards.disabled);
  check(cards.notes.some((n) => n.indexOf('场景') >= 0) && cards.notes.some((n) => n.indexOf('浏览器') >= 0),
    '不可用的卡片各自写明了原因', cards.notes);

  // 3) 点视频壁纸 —— 校验元素接线（src/muted/loop/playsinline）
  const appliedVideo = await ev('(function(){' +
    ' var card = Array.prototype.find.call(document.querySelectorAll("#wp-list .wp-item"), function (c) {' +
    '   return c.querySelector(".wp-name").textContent === "星轨"; });' +
    ' card.click();' +
    ' var v = document.getElementById("wallpaper-video");' +
    ' var s = window.wallpaperEngine.getStatus();' +
    ' return { kind: s.kind, title: s.title, src: v.getAttribute("src"), hidden: v.classList.contains("hidden"),' +
    '   muted: v.muted, loop: v.loop, inline: v.getAttribute("playsinline"),' +
    '   layer: document.getElementById("wallpaper-layer").getAttribute("data-kind"),' +
    '   cls: document.documentElement.classList.contains("has-wallpaper") }; })()');
  check(appliedVideo.kind === 'video' && appliedVideo.src && appliedVideo.src.indexOf('/api/wallpaper/media/') === 0,
    '点视频壁纸后 video 指向服务端注册的媒体地址', appliedVideo.src);
  check(appliedVideo.hidden === false && appliedVideo.layer === 'video' && appliedVideo.cls === true,
    '壁纸层切到 video 且 html 挂上 has-wallpaper', appliedVideo);
  check(appliedVideo.muted === true && appliedVideo.loop === true && appliedVideo.inline !== null,
    '视频壁纸强制静音 + 循环 + 内联播放（否则不是自动播放就是盖住音效）', appliedVideo);

  await sleep(1200);
  const videoErr = await ev('(function(){ var s = window.wallpaperEngine.getStatus();' +
    ' return { err: s.lastError, status: document.getElementById("wp-status").textContent }; })()');
  check(/加载失败/.test(videoErr.status), '视频文件坏掉时界面给出明确提示（不是一片空白）', videoErr.status);

  // 4) 点图片壁纸 —— 且必须把 video 卸干净
  const appliedImage = await ev('(function(){' +
    ' var card = Array.prototype.find.call(document.querySelectorAll("#wp-list .wp-item"), function (c) {' +
    '   return c.querySelector(".wp-name").textContent === "珊瑚海"; });' +
    ' card.click();' +
    ' var v = document.getElementById("wallpaper-video"), img = document.getElementById("wallpaper-image");' +
    ' var s = window.wallpaperEngine.getStatus();' +
    ' return { kind: s.kind, imgSrc: img.getAttribute("src"), imgHidden: img.classList.contains("hidden"),' +
    '   videoSrc: v.getAttribute("src"), videoHidden: v.classList.contains("hidden"),' +
    '   layer: document.getElementById("wallpaper-layer").getAttribute("data-kind") }; })()');
  check(appliedImage.kind === 'image' && appliedImage.layer === 'image' && appliedImage.imgHidden === false,
    '点图片壁纸后图片元素可见、层切到 image', appliedImage);
  check(appliedImage.videoSrc === null && appliedImage.videoHidden === true,
    '换回图片时视频被彻底卸掉（否则在后台空转解码）', appliedImage);

  await sleep(800);
  const imgLoaded = await ev('(function(){ var img = document.getElementById("wallpaper-image");' +
    ' return { w: img.naturalWidth, h: img.naturalHeight }; })()');
  check(imgLoaded.w > 0, '图片壁纸真的解码成功（BMP 96×60）', imgLoaded);

  // 5) 四个参数是否真的落到 CSS 上
  const vars = await ev('(function(){' +
    ' function setRange(id, value) { var el = document.getElementById(id); el.value = value;' +
    '   el.dispatchEvent(new Event("input", { bubbles: true })); }' +
    ' setRange("wp-opacity", 60); setRange("wp-dim", 0); setRange("wp-blur", 12);' +
    ' var fit = document.getElementById("wp-fit"); fit.value = "contain"; fit.dispatchEvent(new Event("change", { bubbles: true }));' +
    ' var root = document.documentElement.style;' +
    ' return { op: root.getPropertyValue("--wp-opacity").trim(), dim: root.getPropertyValue("--wp-dim").trim(),' +
    '   blur: root.getPropertyValue("--wp-blur").trim(), fit: root.getPropertyValue("--wp-fit").trim(),' +
    '   state: window.wallpaperEngine.state }; })()');
  check(vars.op === '0.6' && vars.dim === '0' && vars.blur === '12px' && vars.fit === 'contain',
    '四个滑杆分别写进 --wp-opacity / --wp-dim / --wp-blur / --wp-fit', vars);

  // 图层 opacity 有 0.35s 过渡，读计算值前必须让它跑完（否则读到的是过渡起点）
  await sleep(600);
  const computed = await ev('(function(){' +
    ' var layer = getComputedStyle(document.getElementById("wallpaper-layer"));' +
    ' var scrim = getComputedStyle(document.querySelector(".wallpaper-scrim"));' +
    ' var media = getComputedStyle(document.querySelector(".wallpaper-media:not(.hidden)"));' +
    ' return { layerOpacity: layer.opacity, scrimOpacity: scrim.opacity,' +
    '   mediaFilter: media.filter, mediaFit: media.objectFit }; })()');
  check(Math.abs(parseFloat(computed.layerOpacity) - 0.6) < 0.02,
    '不透明度真的作用到图层（不只是写了个变量）', computed.layerOpacity);
  check(parseFloat(computed.scrimOpacity) === 0, '压暗遮罩调到 0 时遮罩真的全透明', computed.scrimOpacity);
  check(/blur\(12px\)/.test(computed.mediaFilter), '模糊滑杆 → 媒体元素 filter 生效', computed.mediaFilter);
  check(computed.mediaFit === 'contain', '铺满方式 → object-fit 生效', computed.mediaFit);

  // 6) 有壁纸时容器要更透（否则壁纸被白底糊住）
  const bgOn = await ev('getComputedStyle(document.querySelector(".game-container")).backgroundColor');
  check(bgOn !== bgOff, '开启壁纸后容器背景透明度变了（壁纸能透出来）', { off: bgOff, on: bgOn });

  // 7) 持久化：刷新后仍然生效
  await send('Page.navigate', { url: APP });
  await waitFor(async () => await ev('document.readyState === "complete"'), 20000, '刷新后加载');
  await waitFor(async () => await ev('!!window.wallpaperEngine'), 10000, '刷新后引擎实例');
  const afterReload = await ev('(function(){ var s = window.wallpaperEngine.getStatus();' +
    ' return { active: s.active, kind: s.kind, opacity: s.opacity, dim: s.dim, blur: s.blur, fit: s.fit,' +
    '   layer: document.getElementById("wallpaper-layer").getAttribute("data-kind") }; })()');
  check(afterReload.active === true && afterReload.kind === 'image' && afterReload.layer === 'image',
    '刷新后壁纸自动恢复（localStorage 生效）', afterReload);
  check(afterReload.opacity === 60 && afterReload.blur === 12 && afterReload.fit === 'contain',
    '刷新后四个参数也一并恢复', afterReload);

  // 8) 直链导入（用仓库里真实存在的头像图）
  const urlImport = await ev('(function(){' +
    ' var ok = window.wallpaperEngine.importUrl("/static/avatars/default.png");' +
    ' var s = window.wallpaperEngine.getStatus();' +
    ' return { ok: ok, kind: s.kind, src: s.src }; })()');
  check(urlImport.ok === true && urlImport.kind === 'image' && urlImport.src === '/static/avatars/default.png',
    '直链导入图片可用（远端环境唯一的导入通道）', urlImport);
  const badUrl = await ev('window.wallpaperEngine.importUrl("ftp://nope/whatever")');
  check(badUrl === false, '认不出格式的直链被拒绝', badUrl);

  // 9) 按路径导入（仅自起服务端时）
  if (selfHosted) {
    const badPath = await ev('(function(){ document.getElementById("wp-path").value = "D:/definitely/not/here";' +
      ' document.getElementById("wp-path-import").click(); return 1; })()');
    void badPath;
    await waitFor(async () => /不存在/.test(await ev('document.getElementById("wp-status").textContent')), 8000, '导入失败提示');
    check(true, '填了不存在的路径会明确报错', await ev('document.getElementById("wp-status").textContent'));

    const goodPath = await ev('(function(){ document.getElementById("wp-path").value = ' +
      JSON.stringify(libDir) + '; document.getElementById("wp-path-import").click(); return 1; })()');
    void goodPath;
    await waitFor(async () => (await ev('document.querySelectorAll("#wp-list .wp-item").length')) >= 4, 10000, '路径导入列表');
    const byPath = await ev('(function(){ return { n: document.querySelectorAll("#wp-list .wp-item").length,' +
      ' status: document.getElementById("wp-status").textContent }; })()');
    check(byPath.n >= 4, '粘贴文件夹路径能导入（服务端直接读盘，不需要上传）', byPath);
  }

  // 10) 清空
  const cleared = await ev('(function(){ document.getElementById("wp-clear").click();' +
    ' var s = window.wallpaperEngine.getStatus();' +
    ' return { active: s.active, layer: document.getElementById("wallpaper-layer").getAttribute("data-kind"),' +
    '   cls: document.documentElement.classList.contains("has-wallpaper"),' +
    '   display: getComputedStyle(document.getElementById("wallpaper-layer")).display,' +
    '   stored: window.localStorage.getItem(window.wallpaperEngine.STORAGE_KEY) }; })()');
  check(cleared.active === false && cleared.layer === 'none' && cleared.cls === false,
    '「恢复默认背景」把壁纸层收起', cleared);
  check(cleared.display === 'none', '没有壁纸时整层不渲染（省一次全屏合成）', cleared.display);

  // 11) reduced-motion 下视频默认静止
  await send('Emulation.setEmulatedMedia', {
    features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
  });
  const reduced = await ev('(function(){' +
    ' window.wallpaperEngine.apply({ src: "/static/wallpaper/sample-not-real.mp4", kind: "video", title: "静止测试", id: "" });' +
    ' var s = window.wallpaperEngine.getStatus();' +
    ' return { reduced: s.reducedMotion, playing: s.playing, status: document.getElementById("wp-status").textContent }; })()');
  check(reduced.reduced === true && reduced.playing === false,
    '系统开启「减少动态效果」时视频不自动播放', reduced);
  check(/减少动态效果/.test(reduced.status), '并且界面写明了原因', reduced.status);
  await send('Emulation.setEmulatedMedia', { features: [] });

  // 12) 页面不该有 JS 异常
  check(jsProblems.length === 0, '页面无 JS 异常 / console.error', jsProblems);
}

try {
  await main();
} catch (err) {
  problems.push(err.message);
  console.error('检查中断: ' + err.message);
} finally {
  try { if (browser) browser.kill(); } catch (e) { /* ignore */ }
  try {
    if (server) {
      server.proc.kill();
      if (KEEP) console.log('服务端日志：' + server.logPath);
    }
  } catch (e) { /* ignore */ }
  console.log(NL + (problems.length
    ? '结果: ' + problems.length + ' 项不通过' + NL + problems.map((p) => '  - ' + p).join(NL)
    : '结果: 全部通过'));
  process.exit(problems.length ? 1 : 0);
}
