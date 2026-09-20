#!/usr/bin/env node
/**
 * 「绝处逢生：击杀即胜要活到对局结束」的真 socket 端到端检查。
 *
 * 作者反馈（2026-09-19）：
 *   「他的击中对方的船自己直接获胜的效果只会在绝处逢生生效的那一个回合有效
 *     到了下一个回合就没有这个效果了
 *     我的本意是只要绝处逢生通过了 接下来所有回合只要自己的攻击打死了对方的船
 *     那就直接判定自己获胜」
 *
 * 根因：服务端只有一个标记 `last_stand`，同时表示"发动回合锁卡"（该过期）
 * 和"击杀即胜"（作者裁定该永久）。换小回合清理时两者一起被清掉。
 * 更隐蔽的是换小回合的清理另有一份**写死的内联白名单**，与常量
 * `FLAGS_KEEP_ACROSS_TURN` 各自为政 —— 任何新标记都会无声消失。
 *
 * 这个脚本**不用浏览器**，直接开两个真实 socket.io 连接打完一局：
 * 它验证的是"换回合之后服务端到底还认不认这个效果"，这是纯前端工具
 * 和纯 pytest 都覆盖不到的那一段（pytest 测的是函数，这里测的是真协议）。
 *
 * ⚠️ 需要服务端带 ENABLE_TEST_EVENTS=1（脚本靠 test_* 事件读服务端真相、造卡）。
 *    生产环境这个开关是关的，所以本脚本只对本地/测试环境有意义。
 *
 * 用法：
 *   node tools/last_stand_win_e2e.mjs --url http://127.0.0.1:5000/
 */

const argv = process.argv.slice(2);
const argOf = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const APP = argOf('--url', 'http://127.0.0.1:5000/').replace(/\/+$/, '');
const WS_URL = APP.replace(/^http/, 'ws') + '/socket.io/?EIO=4&transport=websocket';
const DEBUG = argv.includes('--debug');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const problems = [];
function check(ok, label, detail) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label
    + (detail === undefined ? '' : '  ->  ' + JSON.stringify(detail)));
  if (!ok) problems.push(label);
}

// ---------------------------------------------------------------------------
// 最小 socket.io 客户端（Engine.IO v4 + Socket.IO v5 帧格式）
//
// 为什么不装 socket.io-client：本仓库刻意不在 tools/ 里引第三方依赖，
// 而协议本身只要认几个前缀就够了 —— 这样脚本在任何机器上都能直接跑。
//   0{...}        Engine.IO 握手（sid / pingInterval）
//   40            连上默认 namespace
//   42["事件",{}) 一条事件；客户端发出的带 ack 编号时是 42<id>[...]
//   3<id>[...]    ack 回包
//   2 / 3         心跳 ping / pong
// ---------------------------------------------------------------------------
class MiniSocket {
  constructor(name) {
    this.name = name;
    this.handlers = new Map();
    this.acks = new Map();
    this.ackSeq = 0;
    this.log = [];
    this.codes = [];   // 收到的帧前缀，排查协议用（--debug 时打印）
  }

  on(event, fn) {
    if (!this.handlers.has(event)) this.handlers.set(event, []);
    this.handlers.get(event).push(fn);
    return this;
  }

  async connect() {
    this.ws = new WebSocket(WS_URL);
    await new Promise((res, rej) => {
      this.ws.onopen = res;
      this.ws.onerror = (e) => rej(new Error(this.name + ' websocket error: ' + (e && e.message)));
    });
    this.ws.onmessage = (m) => this._frame(String(m.data));
    // 等 40（namespace 连上）
    const t0 = Date.now();
    while (!this.ready && Date.now() - t0 < 8000) await sleep(50);
    if (!this.ready) throw new Error(this.name + ' 没能连上 socket.io namespace');
    return this;
  }

  _frame(raw) {
    this.codes.push(raw.slice(0, 2));
    if (DEBUG) console.log(`   [${this.name} <<<] ${JSON.stringify(raw.slice(0, 160))}`);
    if (raw === '2') { this._raw('3'); return; }              // 心跳
    if (raw.startsWith('0')) { this._raw('40'); return; }      // 握手完成 → 连 namespace
    if (raw.startsWith('40')) { this.ready = true; return; }

    // ⚠️ ack 帧是 `43<ackId><JSON>`：`43` + **ackId 数字** + 负载数组，
    // 中间**没有长度位**。所以 `431[{...}]` = ackId 1 + `[{...}]`。
    //
    // 这里踩过两个坑，症状都是"客户端超时"（看着像服务端不响应，极易误判）：
    //   ① 把 `43` 当普通事件解析 → 直接漏掉回包；
    //   ② 看到 `431` 就以为是 Engine.IO 的"长度前缀 1"，于是把负载截成 `"["`，
    //      JSON.parse 静默失败 → 所有带 ack 的请求全部超时。
    // 正确做法：只吃开头连续的数字当 ackId，**剩下全部**交给 JSON.parse。
    if (raw.startsWith('43')) {
      const m = /^43(\d+)/.exec(raw);
      if (!m) return;
      const id = Number(m[1]);
      let arr;
      try { arr = JSON.parse(raw.slice(2 + m[1].length)); } catch (e) {
        if (DEBUG) console.log('   [ACK] JSON.parse 失败: ' + e.message
          + ' rest=' + JSON.stringify(raw.slice(2 + m[1].length).slice(0, 80)));
        return;
      }
      // 负载可能是对象也可能是数组（服务端 handler 返回什么就是什么）
      const payload = Array.isArray(arr) && arr.length === 1 ? arr[0] : arr;
      const slot = this.acks.get(id);
      if (DEBUG) console.log(`   [${this.name} ack#${id}] ${slot ? 'matched' : 'NO WAITER'}`);
      if (slot) { this.acks.delete(id); slot.res(payload); }
      return;
    }

    if (raw.startsWith('42')) {
      let payload;
      try { payload = JSON.parse(raw.slice(2)); } catch (e) { return; }
      const [event, data] = payload;
      this.log.push({ dir: 'in', event, data });
      (this.handlers.get(event) || []).forEach((fn) => fn(data));
    }
  }

  _raw(s) { this.ws.send(s); }

  emit(event, data) {
    this.log.push({ dir: 'out', event, data });
    this._raw('42' + JSON.stringify([event, data]));
  }

  /** 带 ack 的 emit：服务端 handler 的返回值就是 ack 负载。
   *
   * ⚠️ 帧格式是 `42<ackId>[事件, 负载]` —— **ackId 必须紧凑地贴在 42 后面**，
   * 写成 `42[事件, 负载]`（无 ackId）服务端会当成"不需要回包"。
   * 而且这个 ackId 必须和 Promise 里登记的键**是同一个值**，否则回包会
   * 找不到等待者 —— 表现是"服务端明明回了、客户端却超时"，很容易误判成
   * 服务端没响应（这个脚本自己就栽过一次）。
   */
  request(event, data, timeoutMs = 10000) {
    const id = ++this.ackSeq;
    this.log.push({ dir: 'out', event, data });
    return new Promise((res, rej) => {
      const timer = setTimeout(() => {
        this.acks.delete(id);
        rej(new Error(`${this.name} 等 ${event} 的 ack 超时（ackId=${id}）`));
      }, timeoutMs);
      this.acks.set(id, { res: (v) => { clearTimeout(timer); res(v); } });
      this._raw('42' + id + JSON.stringify([event, data]));
    });
  }

  close() { try { this.ws.close(); } catch (e) { /* 关不掉也无所谓 */ } }
}

// ---------------------------------------------------------------------------
// 对局推进的小工具
// ---------------------------------------------------------------------------
// ⚠️ 布船负载必须是 `PlayerShip(**x)` 能直接构造的完整字段 —— 少了 `hits`
// 服务端 handler 会抛 TypeError，而 handler 抛异常时**连 ack 都不会回**：
// 客户端只看到"超时"，很容易误判成服务端卡死（本脚本栽过一次，最后靠
// 服务端日志里的 traceback 才定位到）。
const gridShips = () => [0, 1, 2, 3, 4, 5].map((x) => ({ positions: [{ x, y: 0 }], hits: [] }));
const gridShips2 = () => [0, 1, 2, 3, 4, 5].map((x) => ({ positions: [{ x, y: 5 }], hits: [] }));

async function stateOf(p1, roomId) {
  const r = await p1.request('test_get_game_state', { room_id: roomId });
  if (!r || r.status !== 'success') throw new Error('test_get_game_state 失败: ' + JSON.stringify(r));
  return r.game_state;
}

const p1conn = new MiniSocket('P1');
const p2conn = new MiniSocket('P2');
let roomId = null;

try {
  await p1conn.connect();
  await p2conn.connect();
  check(true, '（前提）两个真实 socket 都连上了', WS_URL);

  // ---- 建房 / 进房 ----
  // ⚠️ 别从 `Object.keys(state.players)` 里"猜"谁是建房者：
  // 两个 key 都是服务端分配的 sid，顺序不保证。而 create_room 的 ack
  // **不含** `player_id`（只有 room_id），所以要自己取 —— 用不了 ack 就退回
  // "谁的手牌在猜拳后是 1 张"之类更绕的判据。这里干脆两边都显式拿 id。
  const created = await p1conn.request('create_room', { player_name: 'P1测试' });
  roomId = created.room_id;
  check(created.status === 'success' && !!roomId, '建房成功', created);

  const joined = await p2conn.request('join_room', { room_id: roomId, player_name: 'P2测试' });
  check(joined.status === 'success', 'P2 进房成功', joined);

  // ⚠️ 阶段转换（进战斗 / 进结束）默认会向对方弹**优先权询问**，窗口不关就
  // 推进不下去：`enter_battle_phase` 会回 `awaiting_priority: true` 而阶段
  // 仍停在 preparation。E2E 不测优先权（另有专测），这里让双方都勾上
  // "拒绝所有阶段转换时点"，把对局推进变成确定性的。
  let st = await stateOf(p1conn, roomId);
  const ids = Object.keys(st.players);
  check(ids.length === 2, '两人都在房间里', ids);
  const p2Id = joined.player_id;
  const p1Id = ids.find((i) => i !== p2Id);
  check(!!p1Id && !!p2Id && p1Id !== p2Id,
    '两个玩家 id 能明确区分（不靠猜顺序）', { p1Id, p2Id });

  for (const [conn, who] of [[p1conn, p1Id], [p2conn, p2Id]]) {
    // ⚠️ 这个事件的字段名是 `decline`（`decline_all` 是 priority_response 的字段，
    // 两者不一样）。写错了不会报错 —— `bool(data.get('decline'))` 静默取到 False，
    // 接口照样回 success，于是"开关没打开"要到后面阶段推不动才暴露。
    const r = await conn.request('set_decline_priority',
      { room_id: roomId, player_id: who, decline: true });
    if (!r || r.status !== 'success' || r.decline !== true) {
      check(false, '（前提）关掉阶段转换优先权询问', { who, r });
    }
  }
  const declined = (await stateOf(p1conn, roomId)).decline_priority || {};
  check(declined[p1Id] === true && declined[p2Id] === true,
    '（前提）双方都已关闭优先权询问（否则阶段推不动）', declined);

  await p1conn.request('place_ships', { room_id: roomId, player_id: p1Id, ships: gridShips() });
  await p2conn.request('place_ships', { room_id: roomId, player_id: p2Id, ships: gridShips2() });
  await sleep(300);

  st = await stateOf(p1conn, roomId);
  check(st.state === 'rock_paper_scissors' || st.state === 'attacking',
    '摆船完成，进入猜拳', { state: st.state });

  if (st.state === 'rock_paper_scissors') {
    // p1Id 出石头、p2Id 出剪刀 → P1 先手（这样"先手"就是 p1Id）
    await p1conn.request('rps_choice', { room_id: roomId, player_id: p1Id, choice: 'rock' });
    await p2conn.request('rps_choice', { room_id: roomId, player_id: p2Id, choice: 'scissors' });
    await sleep(400);
    st = await stateOf(p1conn, roomId);
  }
  check(st.state === 'attacking', '进入攻击阶段', { state: st.state, round: st.round });

  // 谁先手就以谁为"施法者"，别假设是 p1Id
  const casterId = st.current_attacker;
  const casterConn = casterId === p1Id ? p1conn : p2conn;
  const victimId = casterId === p1Id ? p2Id : p1Id;
  const victimConn = casterId === p1Id ? p2conn : p1conn;
  check(!!casterId && !!victimId, '确定了先手方', { casterId, victimId });

  const roundBefore = st.round;

  // ---- 造一张绝处逢生并真的打出去 ----
  const added = await casterConn.request('test_add_specific_magic_card',
    { room_id: roomId, player_id: casterId, card_name: '绝处逢生' });
  check(added && added.status === 'success', '给先手方塞了一张绝处逢生', added);

  // ⚠️ `use_magic_card` 收的是**整张卡对象**（服务端 `MagicCard(**data['card'])`），
  // 只发 `{name}` 会缺 speed/type 直接报"魔法卡数据无效"。
  const cardList = await casterConn.request('test_get_magic_cards_list', {});
  const lsCard = (cardList.magic_cards || []).find((c) => c.name === '绝处逢生');
  check(!!lsCard, '（前提）从卡表取到绝处逢生的完整定义',
    lsCard && { name: lsCard.name, speed: lsCard.speed, type: lsCard.type });

  const playRes = await casterConn.request('use_magic_card', {
    room_id: roomId, player_id: casterId,
    card: { name: lsCard.name, speed: lsCard.speed, type: lsCard.type },
    targets: [],
  });
  check(playRes && playRes.status === 'success', '绝处逢生打出成功', playRes);
  await sleep(500);

  // ⚠️ 速阶3 出牌会开**连锁响应窗口**：窗口关掉之前，后续操作会被
  // "连锁结算中" 挡掉，而放置流程也还没真正开始（表现为"没有等待放置的战舰"）。
  // 窗口落在谁头上不确定（对方手里可能刚好有速阶3，也可能绕回施法者自己），
  // 所以统一按服务端下发的 chain_window 决定由谁来放弃，循环到窗口关闭。
  const connById = { [casterId]: casterConn, [victimId]: victimConn };
  async function settleChain(label) {
    for (let i = 0; i < 16; i++) {
      const s = await stateOf(casterConn, roomId);
      if (!s.chain_window) return true;
      const who = s.chain_window;
      const conn = connById[who];
      if (!conn) return false;   // 窗口落在别人头上（不该发生）
      await conn.request('chain_response', { room_id: roomId, player_id: who, chain: false });
      await sleep(400);
    }
    return false;
  }
  const chainClosed = await settleChain('play');
  check(chainClosed, '（前提）连锁响应窗口已关闭');

  // 放置"唯一一艘战舰"：必须放回原本有战舰的格子上
  const victimShipsCells = st.players[casterId].ships.flatMap((s) => s.positions);
  const placeCell = victimShipsCells[0];
  const placed = await casterConn.request('confirm_reinforcement_position', {
    room_id: roomId, player_id: casterId,
    position: { x: placeCell[0], y: placeCell[1] },
  });
  check(placed && placed.status === 'success', '唯一一艘战舰放置成功', placed);
  await sleep(300);

  st = await stateOf(casterConn, roomId);
  const flags = st.players[casterId].effect_flags || {};
  check(flags.last_stand === true, '★ 发动回合：锁卡标记已置位', flags);
  check(flags.last_stand_win === true, '★ 发动回合：击杀即胜标记已置位', flags);

  // ---- 关键：换一个回合（原实现就是在这里丢的效果）----
  //
  // ⚠️ 阶段推进是**两个不同的事件**，别混：
  //   · `enter_end_phase` : battle → end（进结束阶段）
  //   · `end_turn`        : end    → 换人（交回合）
  // `end_turn` 只在 `current_phase == 'end'` 时才做换人；在 battle 阶段发会
  // 一律被拒（`无法结束当前回合`）。所以"交一次回合"其实是两步。
  // 而且失败是静默的（只回 error、状态不变）—— 不能校验的话，后面所有
  // "换回合后"的断言其实还在测同一个回合，全是假绿。
  async function passTurn(conn, who, label) {
    let before = await stateOf(casterConn, roomId);
    if (before.current_phase === 'battle') {
      const e = await conn.request('enter_end_phase', { room_id: roomId, player_id: who });
      await sleep(400);
      before = await stateOf(casterConn, roomId);
      if (before.current_phase !== 'end') {
        check(false, `（前提）${label}：进结束阶段`, { entered: e, phase: before.current_phase });
        return false;
      }
    }
    const r = await conn.request('end_turn', { room_id: roomId, player_id: who });
    await sleep(500);
    const after = await stateOf(casterConn, roomId);
    if (!r || r.status !== 'success') {
      check(false, `（前提）${label}：end_turn 被拒`, {
        r, before: { phase: before.current_phase, attacker: before.current_attacker },
      });
      return false;
    }
    check(true, `（前提）${label}：交回合成功 → 攻击者`
      + `${after.current_attacker === who ? '仍是本人' : '已换人'}，阶段=${after.current_phase}，大回合=${after.round}`);
    return true;
  }

  // ⚠️ `end_turn` 只在 **battle 或 end** 阶段可用：停在 preparation 会一律被拒
  // （`无法结束当前回合`）。而绝处逢生是在 preparation 阶段打的（速阶3 随时可用），
  // 所以要先把阶段推进到 battle 再交回合。
  async function ensureBattle(conn, who, label) {
    let s = await stateOf(casterConn, roomId);
    if (s.current_phase === 'battle') return s;
    if (s.current_attacker !== who) {
      check(false, `（前提）${label}：不是 ${who === casterId ? '施法者' : '对方'}的回合，无法推进阶段`,
        { attacker: s.current_attacker, phase: s.current_phase });
      return s;
    }
    const r = await conn.request('enter_battle_phase', { room_id: roomId, player_id: who });
    await sleep(500);
    s = await stateOf(casterConn, roomId);
    check(s.current_phase === 'battle',
      `（前提）${label}：阶段推进到 battle`, { entered: r, phase: s.current_phase });
    return s;
  }

  /**
   * 把当前攻击者的剩余攻击次数打光。
   *
   * ⚠️ 服务端不让"带着剩余攻击次数"进结束阶段（`你还有剩余攻击次数，无法进入结束阶段`）——
   * 所以想交回合，必须先把次数用掉。这里**只打对方棋盘上确定没有船的格子**：
   * 打中船就可能触发击杀即胜（这次测试的主题），那会污染"换回合"这一步。
   */
  async function exhaustAttacks(conn, who, label) {
    const foe = who === casterId ? victimId : casterId;
    for (let i = 0; i < 10; i++) {
      const s = await stateOf(casterConn, roomId);
      if (s.current_attacker !== who) {
        check(false, `（前提）${label}：轮到别人了`, { attacker: s.current_attacker });
        return s;
      }
      if (s.attacks_remaining <= 0) return s;
      // 已知的对方船位（公开信息：开打之后双方棋盘上的命中都可见）
      const occupied = new Set();
      ((s.players[foe] || {}).ships || []).forEach((sh) => {
        (sh.positions || []).forEach(([x, y]) => occupied.add(`${x},${y}`));
      });
      const empties = [];
      for (let x = 0; x < 6; x++) {
        for (let y = 0; y < 6; y++) {
          if (!occupied.has(`${x},${y}`)) empties.push([x, y]);
        }
      }
      if (!empties.length) {
        check(false, `（前提）${label}：对方棋盘没有空格可打`, occupied.size);
        return s;
      }
      const [ex, ey] = empties[i % empties.length];
      const r = await conn.request('attack', { room_id: roomId, player_id: who, x: ex, y: ey });
      await sleep(300);
      if (!r || r.status !== 'success') {
        check(false, `（前提）${label}：打空格耗次数失败`, { r, at: [ex, ey] });
        return s;
      }
      if (r.game_over) {
        check(false, `（前提）${label}：打空格竟然结束了对局（不该发生）`, { r, at: [ex, ey] });
        return s;
      }
    }
    const s = await stateOf(casterConn, roomId);
    check(s.attacks_remaining <= 0, `（前提）${label}：攻击次数已用尽`, s.attacks_remaining);
    return s;
  }

  let cur = (await stateOf(casterConn, roomId)).current_attacker;
  if (cur !== casterId) throw new Error(`预期先手是施法者，实际 ${cur} != ${casterId}`);

  await ensureBattle(casterConn, casterId, '施法者交回合前');
  await exhaustAttacks(casterConn, casterId, '施法者交回合前');
  await passTurn(casterConn, casterId, '施法者交回合');   // battle → end → 交给对方
  await ensureBattle(victimConn, victimId, '对方交回合前');
  await exhaustAttacks(victimConn, victimId, '对方交回合前');
  await passTurn(victimConn, victimId, '对方交回合');     // battle → end → 轮回施法者

  st = await stateOf(casterConn, roomId);

  // ⚠️ 大回合（round +1）会**重新猜拳**：state 变成 rock_paper_scissors，
  // 不猜拳就永远进不了 attacking，后面 `enter_battle_phase` / `attack` 全都会
  // 撞在"当前不是你的战斗阶段"上。作者要验证的"接下来所有回合"正跨这个大回合边界，
  // 所以这一步必须走真流程（而不是用 test_end_turn 之类跳过）。
  async function resolveRpsIfNeeded() {
    const s = await stateOf(casterConn, roomId);
    if (s.state !== 'rock_paper_scissors') return s;
    const r1 = await p1conn.request('rps_choice',
      { room_id: roomId, player_id: p1Id, choice: 'rock' });
    const r2 = await p2conn.request('rps_choice',
      { room_id: roomId, player_id: p2Id, choice: 'scissors' });
    await sleep(600);
    const after = await stateOf(casterConn, roomId);
    check(after.state === 'attacking', '（前提）大回合重新猜拳后进入攻击阶段',
      { r1, r2, state: after.state, attacker: after.current_attacker, round: after.round });
    return after;
  }

  st = await resolveRpsIfNeeded();

  const flags2 = st.players[casterId].effect_flags || {};
  check(st.current_attacker === casterId && st.round > roundBefore,
    '（前提）确实换了回合（大回合 +1）、且轮回施法者', {
      roundBefore, round: st.round, attacker: st.current_attacker, state: st.state,
    });
  check(flags2.last_stand !== true, '换回合后锁卡标记已过期（这是对的）', flags2);
  check(flags2.last_stand_win === true,
    '★★ 核心：换回合后"击杀即胜"依然在 —— 原实现就是在这里被清掉的', flags2);

  // ---- 确保处于战斗阶段（新回合是 preparation）----
  await ensureBattle(casterConn, casterId, '进攻前');
  st = await stateOf(casterConn, roomId);

  // 观察 game_over 广播
  let gameOverPayload = null;
  casterConn.on('game_over', (d) => { gameOverPayload = d; });
  victimConn.on('game_over', (d) => { if (!gameOverPayload) gameOverPayload = d; });

  // 找一艘对方的**单格船**，一炮打沉（gridShips2 全是单格）
  const victimShip = st.players[victimId].ships.find((s) => s.positions.length === 1
    && s.hits.length < s.positions.length);
  check(!!victimShip, '（前提）对方有可击沉的单格战舰', victimShip);
  const [ax, ay] = victimShip.positions[0];

  const atk = await casterConn.request('attack', {
    room_id: roomId, player_id: casterId, x: ax, y: ay,
  });
  check(atk && atk.status === 'success', '换回合后的攻击被接受', atk);
  await sleep(600);

  st = await stateOf(casterConn, roomId);
  check(st.state === 'game_over',
    '★★★ 核心：换回合后击杀敌舰 → 直接获胜（state=game_over）',
    { state: st.state, round: st.round, roundBefore });
  check(gameOverPayload && gameOverPayload.winner === casterId,
    '★★★ 双方都收到了 game_over，胜者是施法者', gameOverPayload);
  check(st.players[victimId].remaining_ships < 6,
    '确实打沉了对方一艘船（不是误判胜利）', st.players[victimId].remaining_ships);

  // ---- 反证：没有这张卡时，同样的操作不该获胜 ----
  console.log('--- 反证：不带绝处逢生的对照局 ---');
  const r1 = new MiniSocket('R1');
  const r2 = new MiniSocket('R2');
  try {
    await r1.connect();
    await r2.connect();
    const c2 = await r1.request('create_room', { player_name: '对照P1' });
    const rid2 = c2.room_id;
    await r2.request('join_room', { room_id: rid2, player_name: '对照P2' });
    let s2 = await stateOf(r1, rid2);
    const ids2 = Object.keys(s2.players);
    await r1.request('place_ships', { room_id: rid2, player_id: ids2[0], ships: gridShips() });
    await r2.request('place_ships', { room_id: rid2, player_id: ids2[1], ships: gridShips2() });
    await sleep(300);
    s2 = await stateOf(r1, rid2);
    if (s2.state === 'rock_paper_scissors') {
      await r1.request('rps_choice', { room_id: rid2, player_id: ids2[0], choice: 'rock' });
      await r2.request('rps_choice', { room_id: rid2, player_id: ids2[1], choice: 'scissors' });
      await sleep(400);
      s2 = await stateOf(r1, rid2);
    }
    const att2 = s2.current_attacker;
    const vic2 = att2 === ids2[0] ? ids2[1] : ids2[0];
    const attConn = att2 === ids2[0] ? r1 : r2;
    if (s2.current_phase !== 'battle') {
      await attConn.request('enter_battle_phase', { room_id: rid2, player_id: att2 });
      await sleep(400);
      s2 = await stateOf(r1, rid2);
    }
    const ship2 = s2.players[vic2].ships.find((s) => s.positions.length === 1);
    const [bx, by] = ship2.positions[0];
    await attConn.request('attack', { room_id: rid2, player_id: att2, x: bx, y: by });
    await sleep(500);
    s2 = await stateOf(r1, rid2);
    check(s2.state !== 'game_over',
      '★ 反证：没打绝处逢生时，击沉一艘船不会直接获胜', { state: s2.state });
  } finally {
    r1.close(); r2.close();
  }
} catch (err) {
  check(false, '脚本异常中断', { error: String(err && err.message || err) });
} finally {
  p1conn.close();
  p2conn.close();
}

console.log('');
if (problems.length) {
  console.log(`✗ ${problems.length} 项未通过：`);
  problems.forEach((p) => console.log('   · ' + p));
} else {
  console.log('✓ 全部通过');
}
process.exit(problems.length ? 1 : 0);
