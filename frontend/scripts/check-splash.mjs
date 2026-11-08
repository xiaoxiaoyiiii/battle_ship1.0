/**
 * 开屏动画触发策略的回归检查（纯逻辑，不启动浏览器）。
 *
 * 用法：node scripts/check-splash.mjs
 * 退出码：0 = 全部通过；1 = 有失败项。
 *
 * 覆盖三件事：
 *  1. 什么情况下播（冷启动在开战页 → Logo + 拼接；非开战页 → 只播 Logo）。
 *  2. 什么情况下不播（本进程已播过、有重连座位、落在对局路由）。
 *  3. 记忆标记是内存、不是 storage；reconnect 的存储键与策略里的常量一致。
 */

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import {
  ASSEMBLE_MS,
  RECONNECT_SEAT_KEY,
  createSplashGate,
  decideSplash,
  hasReconnectSeat,
  isMatchRoute,
  logoDurationMs,
  shouldRedirectLobbyToStart,
} from '../src/splash/splashPolicy.ts'

const here = dirname(fileURLToPath(import.meta.url))
let failures = 0
let total = 0

function check(label, condition, detail = '') {
  total += 1
  if (condition) {
    console.log(`[PASS] ${label}`)
    return
  }
  failures += 1
  console.log(`[FAIL] ${label}${detail ? ' — ' + detail : ''}`)
}

function storageWith(value) {
  return {
    getItem(key) {
      return key === RECONNECT_SEAT_KEY ? value : null
    },
  }
}

// ---- 1. 对局路由判定 ------------------------------------------------
for (const name of ['placement', 'rps', 'game', 'game-over']) {
  check(`对局路由 ${name} 判定为对局`, isMatchRoute(name) === true)
}
for (const name of ['start', 'lobby', 'settings', 'mailbox', 'shop', 'welcome', undefined, null, '']) {
  check(`非对局路由 ${String(name)} 不判定为对局`, isMatchRoute(name) === false)
}

// ---- 2. 重连座位判定 ------------------------------------------------
check(
  '有合法重连座位 → 视为要回到对局',
  hasReconnectSeat(storageWith(JSON.stringify({ roomId: 'r1', playerId: 'p1', token: 't1' }))) === true,
)
check('没有存储 → 无重连座位', hasReconnectSeat(storageWith(null)) === false)
check('空串 → 无重连座位', hasReconnectSeat(storageWith('')) === false)
check('坏 JSON → 无重连座位', hasReconnectSeat(storageWith('{oops')) === false)
check('缺字段 → 无重连座位', hasReconnectSeat(storageWith(JSON.stringify({ roomId: 'r1' }))) === false)
check(
  'storage 抛错 → 当作没有（不崩）',
  hasReconnectSeat({
    getItem() {
      throw new Error('blocked')
    },
  }) === false,
)

// ---- 3. 决策矩阵 ----------------------------------------------------
const firstVisitStart = decideSplash({ alreadyPlayed: false, routeName: 'start', hasSeat: false })
check('首次冷启动落在开战 → 播 Logo', firstVisitStart.logo === true, JSON.stringify(firstVisitStart))
check('首次冷启动落在开战 → 播拼接', firstVisitStart.assemble === true, JSON.stringify(firstVisitStart))

const firstVisitLobby = decideSplash({ alreadyPlayed: false, routeName: 'lobby', hasSeat: false })
check('首次冷启动落在（无对局的）大厅 → 播 Logo', firstVisitLobby.logo === true, JSON.stringify(firstVisitLobby))
check('落在非开战页 → 不播拼接', firstVisitLobby.assemble === false, JSON.stringify(firstVisitLobby))

const firstVisitSettings = decideSplash({ alreadyPlayed: false, routeName: 'settings', hasSeat: false })
check('落在设置 → 播 Logo、不播拼接', firstVisitSettings.logo === true && firstVisitSettings.assemble === false)

const alreadyPlayed = decideSplash({ alreadyPlayed: true, routeName: 'start', hasSeat: false })
check(
  '本进程已播过 → 整段不播',
  alreadyPlayed.logo === false && alreadyPlayed.assemble === false && alreadyPlayed.reason === 'already-played',
  JSON.stringify(alreadyPlayed),
)

const seatAtStart = decideSplash({ alreadyPlayed: false, routeName: 'start', hasSeat: true })
check(
  '存在重连座位 → 整段不播（不挡重连）',
  seatAtStart.logo === false && seatAtStart.assemble === false && seatAtStart.reason === 'reconnect-seat',
  JSON.stringify(seatAtStart),
)

const gameRoute = decideSplash({ alreadyPlayed: false, routeName: 'game', hasSeat: false })
check(
  '刷新落在对局路由 → 整段不播',
  gameRoute.logo === false && gameRoute.assemble === false && gameRoute.reason === 'match-route',
  JSON.stringify(gameRoute),
)

const rpsRoute = decideSplash({ alreadyPlayed: false, routeName: 'rps', hasSeat: true })
check('对局路由 + 重连座位 → 仍不播', rpsRoute.logo === false && rpsRoute.assemble === false)

// ---- 4. 时长 --------------------------------------------------------
check('默认 Logo 段约 3 秒', logoDurationMs(false) === 3000, String(logoDurationMs(false)))
check(
  '减少动效时 Logo 段缩短',
  logoDurationMs(true) >= 400 && logoDurationMs(true) <= 1600,
  String(logoDurationMs(true)),
)
check('拼接段时长在可感知区间内', ASSEMBLE_MS >= 400 && ASSEMBLE_MS <= 1200, String(ASSEMBLE_MS))

// ---- 5. 进程内记忆 --------------------------------------------------
const gate = createSplashGate()
check('新进程第一次允许播', gate.shouldPlay() === true)
gate.markPlayed()
check('标记之后不再播', gate.shouldPlay() === false)
const otherGate = createSplashGate()
check('另一个进程（新建 gate）重新允许播', otherGate.shouldPlay() === true)

// ---- 6. 与 reconnect.ts 的存储键保持一致 -----------------------------
const reconnectSource = readFileSync(join(here, '..', 'src', 'realtime', 'reconnect.ts'), 'utf8')
check(
  '策略里的重连键与 reconnect.ts 一致',
  reconnectSource.includes(`'${RECONNECT_SEAT_KEY}'`),
  RECONNECT_SEAT_KEY,
)

// ---- 7. 冷启动落在大厅是否改写到开战 --------------------------------
// 现状：桌面壳 1.0.1 写死打开 /lobby，所以进程第一次导航落在大厅时，
// 只要没有邀请、没有重连座位，就 replace 到开战页，好让拼接能播。
const redirectCase = (input) => shouldRedirectLobbyToStart(input)

check(
  '初次落在大厅、无邀请无座位 → 改写',
  redirectCase({ routeName: 'lobby', hasInvite: false, hasSeat: false, isInitialNavigation: true }) === true,
)
check(
  '初次落在开战 → 不改写',
  redirectCase({ routeName: 'start', hasInvite: false, hasSeat: false, isInitialNavigation: true }) === false,
)
check(
  '初次落在大厅但有邀请 → 不改写（邀请优先）',
  redirectCase({ routeName: 'lobby', hasInvite: true, hasSeat: false, isInitialNavigation: true }) === false,
)
check(
  '初次落在大厅但有重连座位 → 不改写',
  redirectCase({ routeName: 'lobby', hasInvite: false, hasSeat: true, isInitialNavigation: true }) === false,
)
check(
  '同进程后进大厅（非初次导航）→ 不改写',
  redirectCase({ routeName: 'lobby', hasInvite: false, hasSeat: false, isInitialNavigation: false }) === false,
)
check(
  '非大厅的其它页面（设置/邮箱等）→ 不改写',
  ['settings', 'mailbox', 'shop', 'battle-pass', 'leaderboard'].every(
    (routeName) =>
      redirectCase({ routeName, hasInvite: false, hasSeat: false, isInitialNavigation: true }) === false,
  ),
)
const afterRedirect = decideSplash({ alreadyPlayed: false, routeName: 'start', hasSeat: false })
check(
  '改写后的路由能拿到 Logo + 拼接',
  afterRedirect.logo === true && afterRedirect.assemble === true,
  JSON.stringify(afterRedirect),
)

// 接线检查：真跳转必须发生在路由守卫里，否则 App.vue 早就按 lobby 决策完了。
const routerSource = readFileSync(join(here, '..', 'src', 'router', 'index.ts'), 'utf8')
check('router 守卫里调用了改写判断', routerSource.includes('shouldRedirectLobbyToStart'))
check('改写用 replace，不是 push', /replace:\s*true/.test(routerSource))

console.log(`\nRESULT: ${total - failures}/${total} PASS`)
process.exit(failures === 0 ? 0 : 1)
