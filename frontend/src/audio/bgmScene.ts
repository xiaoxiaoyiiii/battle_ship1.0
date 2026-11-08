/**
 * 背景音乐场景。只做判断，不创建音频节点。
 *
 * 签到弹窗、好友层和其他浮层没有自己的路由，调用方不要把它们传进来，
 * 否则会把正在循环的曲子切掉。未来如果单独做了开屏路由，名字用 `splash`，
 * 这里会保持静音，避免开屏误播。
 */

export const BGM_LOOP_SECONDS = 80
export const BGM_CROSSFADE_SECONDS = 2
/** 任一方未沉舰数达到这个值（含）时叠入终局层。 */
export const ENDGAME_SHIP_LIMIT = 3

export type BgmBed = 'silent' | 'standby' | 'match' | 'hold'

const MATCH_ROUTE_NAMES = new Set(['placement', 'rps', 'game'])
const SILENT_ROUTE_NAMES = new Set(['splash'])

/**
 * 开屏静音；胜负页保持当前曲子；布船、猜拳、战斗用对局曲；其余页面用待命曲。
 * Ban、每日挑战和人机都落在上述对局路由上，不另开曲子。
 */
export function bgmBedForRoute(routeName: string | null | undefined, splashActive: boolean): BgmBed {
  if (splashActive) return 'silent'
  if (typeof routeName === 'string' && SILENT_ROUTE_NAMES.has(routeName)) return 'silent'
  if (routeName === 'game-over') return 'hold'
  if (typeof routeName === 'string' && MATCH_ROUTE_NAMES.has(routeName)) return 'match'
  return 'standby'
}

/**
 * 终局层是否该响。
 * 返回 null 表示这一帧不要改层（开屏、胜负页）。
 * 舰数是还没被击沉的船，不是剩余格子。双方都是 0 时布船默认值，不当作终局。
 * 只在炮击阶段判断；双方都多于 3 艘时关掉，掉到 2 或 1 时仍保持打开。
 */
export function endgameLayerForBattle(
  bed: BgmBed,
  roomState: string,
  selfShips: number,
  opponentShips: number,
): boolean | null {
  if (bed === 'hold' || bed === 'silent') return null
  if (bed !== 'match') return false
  if (roomState !== 'attacking') return false
  const self = Number.isFinite(selfShips) ? selfShips : 0
  const opponent = Number.isFinite(opponentShips) ? opponentShips : 0
  if (!(self > 0 || opponent > 0)) return false
  return self <= ENDGAME_SHIP_LIMIT || opponent <= ENDGAME_SHIP_LIMIT
}

/** 裁到母带的 80.000 秒。解码多出来的 Opus 填充留在尾部，不参与循环。 */
export function trimFrameCount(decodedFrames: number, sampleRate: number): number {
  if (!Number.isFinite(decodedFrames) || decodedFrames <= 0) return 0
  if (!Number.isFinite(sampleRate) || sampleRate <= 0) return Math.floor(decodedFrames)
  const frames = Math.floor(decodedFrames)
  const target = Math.round(BGM_LOOP_SECONDS * sampleRate)
  return Math.min(frames, target)
}

/**
 * 循环内的起点。用同一条对局时钟的 elapsed 来对齐终局层，
 * 这样终局文件不会从 0 单独开播。
 */
export function loopOffsetSeconds(elapsedSeconds: number, loopSeconds: number): number {
  if (!(loopSeconds > 0) || !Number.isFinite(elapsedSeconds)) return 0
  let offset = elapsedSeconds % loopSeconds
  if (offset < 0) offset += loopSeconds
  const epsilon = 1e-4
  if (offset > loopSeconds - epsilon) return 0
  return offset
}

/** 两条循环相差多少秒（取短的那一边）。 */
export function loopDistanceSeconds(a: number, b: number, loopSeconds: number): number {
  if (!(loopSeconds > 0) || !Number.isFinite(a) || !Number.isFinite(b)) return 0
  const delta = Math.abs(a - b) % loopSeconds
  return Math.min(delta, loopSeconds - delta)
}
