/**
 * 开屏（Logo → 开战模块拼接）的触发策略。
 *
 * 这里只放**纯判断**，不碰 DOM、不碰路由实例，方便单测
 * （`node scripts/check-splash.mjs`）。真正的播放由 `App.vue` 驱动。
 *
 * 规则（与派单一致）：
 *  - 只有「本进程第一次冷启动」才播；标记放在内存里，所以刷新会重播，
 *    同标签内 router.push 切页不会重播。
 *  - 有重连座位、或当前/即将进入对局路由时整段跳过——开屏不能挡住重连。
 *  - 拼接只在目标是开战页（`start`）时播；其它页面只播 Logo 段。
 */

/** 与 `frontend/src/realtime/reconnect.ts` 的 STORAGE_KEY 必须一致（有单测守着）。 */
export const RECONNECT_SEAT_KEY = 'battleship.reconnect.seat'

/** 需要「立刻进对局、不播开屏」的路由名。 */
export const MATCH_ROUTE_NAMES = ['placement', 'rps', 'game', 'game-over'] as const

/** Logo 段默认时长：约 3 秒，可点击跳过。 */
export const LOGO_MS = 3000

/** `prefers-reduced-motion: reduce` 时缩短的 Logo 段（仍可跳过）。 */
export const LOGO_REDUCED_MS = 900

/** 拼接段时长：所有模块同时开始、同时落地。 */
export const ASSEMBLE_MS = 760

export type SplashSkipReason = '' | 'already-played' | 'reconnect-seat' | 'match-route'

export interface SplashDecision {
  /** 是否播 Logo 段。 */
  logo: boolean
  /** 是否播开战页模块拼接。 */
  assemble: boolean
  /** 不播的原因（空串表示确实要播）。 */
  reason: SplashSkipReason
}

export interface SplashInput {
  /** 本进程内是否已经播过（内存标记）。 */
  alreadyPlayed: boolean
  /** 冷启动落点路由名。 */
  routeName?: string | null
  /** sessionStorage 里是否有可恢复的座位。 */
  hasSeat: boolean
}

type ReadableStorage = { getItem(key: string): string | null }

/** 路由名是否属于「进行中的对局」。 */
export function isMatchRoute(name?: string | null): boolean {
  return typeof name === 'string' && (MATCH_ROUTE_NAMES as readonly string[]).includes(name)
}

/**
 * sessionStorage 里是否有可用的重连座位。
 * 座位结构见 `realtime/reconnect.ts` 的 `StoredSeat`；坏数据一律当作没有。
 */
export function hasReconnectSeat(storage?: ReadableStorage | null): boolean {
  if (!storage) return false
  let raw: string | null = null
  try {
    raw = storage.getItem(RECONNECT_SEAT_KEY)
  } catch {
    return false
  }
  if (!raw) return false
  try {
    const parsed = JSON.parse(raw) as { roomId?: unknown; playerId?: unknown; token?: unknown }
    return Boolean(parsed && parsed.roomId && parsed.playerId && parsed.token)
  } catch {
    return false
  }
}

/** 决定这次冷启动播什么。 */
export function decideSplash(input: SplashInput): SplashDecision {
  if (input.alreadyPlayed) return { logo: false, assemble: false, reason: 'already-played' }
  if (input.hasSeat) return { logo: false, assemble: false, reason: 'reconnect-seat' }
  if (isMatchRoute(input.routeName)) return { logo: false, assemble: false, reason: 'match-route' }
  return { logo: true, assemble: input.routeName === 'start', reason: '' }
}

/** Logo 段时长；减少动效时缩短。 */
export function logoDurationMs(reducedMotion: boolean): number {
  return reducedMotion ? LOGO_REDUCED_MS : LOGO_MS
}

export interface SplashGate {
  /** 现在是否还该播（同一进程只播一次）。 */
  shouldPlay(): boolean
  /** 标记本进程已经播过。 */
  markPlayed(): void
}

/**
 * 进程内的「播过没有」标记。
 * 刻意不写 sessionStorage/localStorage：刷新要能重播。
 */
export function createSplashGate(): SplashGate {
  let played = false
  return {
    shouldPlay: () => !played,
    markPlayed: () => {
      played = true
    },
  }
}

/**
 * 本进程的全局标记（模块级单例）。
 * `App.vue` 只读它，所以组件重新挂载（HMR、恢复）不会重播；
 * 真正刷新页面时模块会重新求值，标记自然清空 → 大厅刷新会再播。
 */
export const processSplashGate: SplashGate = createSplashGate()
