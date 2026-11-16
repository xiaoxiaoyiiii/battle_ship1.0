/**
 * 神秘科技界面的纯展示与解析辅助。倒计时优先使用服务端绝对期限；
 * 测试时钟（deadline 不像 Unix 毫秒）则按收到快照时的 remaining_ms 递减。
 */
import type {
  MysteryTechCell,
  MysteryTechInfo,
  MysteryTechOption,
  MysteryTechSelected,
  MysteryTechStage,
  MysteryTechState,
  MysteryTechTarget,
  MysteryTechTargetKind,
  MysteryTechTargetShip,
  MysteryTechTier,
  MysteryTechTiming,
} from '../../stores/mysteryTechTypes'
import { EMPTY_MYSTERY_TECH_STATE } from '../../stores/mysteryTechTypes'
import type { MotionPreference } from '../../stores/ui'

const UNIX_MS_FLOOR = 1e12

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function asNumberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asBoolean(value: unknown): boolean {
  return value === true
}

function parseTier(value: unknown): MysteryTechTier {
  return value === 'legendary' || value === 'mythic' ? value : 'quality'
}

function parseTiming(value: unknown): MysteryTechTiming {
  return value === 'persistent' ? 'persistent' : 'instant'
}

function parseStage(value: unknown): MysteryTechStage {
  if (
    value === 'selecting'
    || value === 'locked'
    || value === 'resolving'
    || value === 'targeting'
    || value === 'effect_waiting'
    || value === 'ended'
  ) return value
  return 'idle'
}

function parseKind(value: unknown): MysteryTechTargetKind | null {
  if (value === 'revive' || value === 'fleet_rebirth' || value === 'sonar_pulse' || value === 'spacetime_fold') return value
  return null
}

export function parseTechnology(value: unknown, fallbackId = ''): MysteryTechInfo {
  const row = asObject(value)
  const id = asString(row?.id, fallbackId)
  return {
    id,
    name: asString(row?.name, id),
    tier: parseTier(row?.tier),
    timing: parseTiming(row?.timing),
    description: asString(row?.description),
  }
}

function parseOption(value: unknown): MysteryTechOption | null {
  const row = asObject(value)
  if (!row) return null
  const techId = asString(row.tech_id) || asString(asObject(row.technology)?.id)
  if (!techId) return null
  return {
    tech_id: techId,
    refresh_used: asBoolean(row.refresh_used),
    technology: parseTechnology(row.technology, techId),
  }
}

function parseSelected(value: unknown): MysteryTechSelected | null {
  const row = asObject(value)
  if (!row) return null
  const techId = asString(row.tech_id)
  if (!techId) return null
  return {
    player_id: asString(row.player_id),
    seat: asString(row.seat),
    tech_id: techId,
    round: asNumber(row.round),
    technology: parseTechnology(row.technology, techId),
  }
}

export function parseCell(value: unknown): MysteryTechCell | null {
  const row = asObject(value)
  if (!row) return null
  const x = asNumber(row.x, NaN)
  const y = asNumber(row.y, NaN)
  if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0 || x > 5 || y > 5) return null
  return { x, y }
}

function parseTargetShip(value: unknown): MysteryTechTargetShip | null {
  const row = asObject(value)
  if (!row) return null
  const shipIndex = asNumber(row.ship_index, NaN)
  if (!Number.isInteger(shipIndex) || shipIndex < 0) return null
  const positions = Array.isArray(row.positions)
    ? row.positions.map(parseCell).filter((cell): cell is MysteryTechCell => cell !== null)
    : []
  return { ship_index: shipIndex, positions }
}

function parseTarget(value: unknown): MysteryTechTarget | null {
  const row = asObject(value)
  if (!row) return null
  const kind = parseKind(row.kind)
  const requestId = asString(row.request_id)
  if (!kind || !requestId) return null
  return {
    request_id: requestId,
    player_id: asString(row.player_id),
    tech_id: asString(row.tech_id),
    kind,
    deadline: asNumberOrNull(row.deadline),
    remaining: asNumber(row.remaining, 0),
    legal_cells: Array.isArray(row.legal_cells)
      ? row.legal_cells.map(parseCell).filter((cell): cell is MysteryTechCell => cell !== null)
      : [],
    ship_indices: Array.isArray(row.ship_indices)
      ? row.ship_indices.map((item) => asNumber(item, NaN)).filter((item) => Number.isInteger(item) && item >= 0)
      : [],
    ships: Array.isArray(row.ships)
      ? row.ships.map(parseTargetShip).filter((ship): ship is MysteryTechTargetShip => ship !== null)
      : [],
  }
}

/** 解析私有 mystery_tech_state；缺字段用安全默认，不臆造选项或目标。 */
export function parseMysteryTechState(value: unknown): MysteryTechState | null {
  const row = asObject(value)
  if (!row) return null
  const options = Array.isArray(row.options)
    ? row.options.map(parseOption).filter((item): item is MysteryTechOption => item !== null)
    : []
  const selected = Array.isArray(row.selected)
    ? row.selected.map(parseSelected).filter((item): item is MysteryTechSelected => item !== null)
    : []
  const lockedPlayers = Array.isArray(row.locked_players)
    ? row.locked_players.map((item) => asString(item)).filter(Boolean)
    : []
  const pending: Record<string, number> = {}
  const rawPending = asObject(row.pending_extra_attacks)
  if (rawPending) {
    for (const [key, item] of Object.entries(rawPending)) {
      const count = asNumber(item, NaN)
      if (Number.isInteger(count) && count > 0) pending[key] = count
    }
  }
  return {
    room_id: asString(row.room_id) || undefined,
    enabled: row.enabled !== false,
    stage: parseStage(row.stage),
    selection_round: asNumber(row.selection_round, 0),
    deadline: asNumberOrNull(row.deadline),
    remaining_ms: Math.max(0, asNumber(row.remaining_ms, 0)),
    options,
    locked_tech_id: asString(row.locked_tech_id) || null,
    target: parseTarget(row.target),
    selected,
    locked_players: lockedPlayers,
    resolving_player: asString(row.resolving_player) || null,
    pending_extra_attacks: pending,
  }
}

/** 公开投影没有 options / locked_tech_id / target，合并时保留已有私有字段。 */
export function mergePublicMysteryTech(current: MysteryTechState, incoming: MysteryTechState): MysteryTechState {
  return {
    ...current,
    enabled: incoming.enabled,
    stage: incoming.stage,
    selection_round: incoming.selection_round,
    deadline: incoming.deadline,
    remaining_ms: incoming.remaining_ms,
    selected: incoming.selected,
    locked_players: incoming.locked_players,
    resolving_player: incoming.resolving_player,
    pending_extra_attacks: incoming.pending_extra_attacks,
    room_id: incoming.room_id ?? current.room_id,
  }
}

export function isUnixDeadline(deadline: number | null | undefined): deadline is number {
  return typeof deadline === 'number' && deadline >= UNIX_MS_FLOOR
}

/**
 * 剩余毫秒。真实对局用绝对 Unix 期限；夹具/测试钟（deadline 过小）按快照 remaining_ms 从收到时刻起递减。
 */
export function remainingMsUntil(
  deadline: number | null | undefined,
  remainingMs: number | null | undefined,
  receivedAt: number,
  now: number,
): number {
  if (isUnixDeadline(deadline)) return Math.max(0, deadline - now)
  if (typeof remainingMs === 'number' && Number.isFinite(remainingMs)) {
    return Math.max(0, remainingMs - (now - receivedAt))
  }
  if (typeof deadline === 'number' && Number.isFinite(deadline)) return Math.max(0, deadline - now)
  return 0
}

export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000))
  return String(total)
}

export function tierLabel(tier: MysteryTechTier): string {
  if (tier === 'mythic') return '神话'
  if (tier === 'legendary') return '传说'
  return '优质'
}

export function timingLabel(timing: MysteryTechTiming): string {
  return timing === 'persistent' ? '长效' : '即时'
}

export function targetKindTitle(kind: MysteryTechTargetKind, techName?: string): string {
  const name = techName ? `「${techName}」` : '神秘科技'
  if (kind === 'revive') return `${name}：选择沉船与落点`
  if (kind === 'fleet_rebirth') return `${name}：选择落点`
  if (kind === 'sonar_pulse') return `${name}：选择 2×2 左上角`
  return `${name}：选择对方一艘仍存活的船`
}

export function targetKindHint(kind: MysteryTechTargetKind, remaining: number): string {
  if (kind === 'revive') return '先点下方残骸，再点对方没打过的空格。只能点高亮格子。'
  if (kind === 'fleet_rebirth') {
    return remaining > 0 ? `还需要补 ${remaining} 艘。点击高亮空格放置，格子不够或超时则停止。` : '点击高亮空格放置。'
  }
  if (kind === 'sonar_pulse') return '点击高亮格子作为 2×2 区域的左上角，将显形该区域。'
  return '点击高亮的对方船只。死亡不是永久击沉，之后仍可用疗愈救回。'
}

export function waitingText(stage: MysteryTechStage, isSelfResolving: boolean): string {
  if (stage === 'effect_waiting') {
    return isSelfResolving ? '效果已触发衍生义务，请先处理现有选择；完成后才会继续。' : '等待对方处理效果。'
  }
  if (stage === 'targeting' || stage === 'resolving') {
    return isSelfResolving ? '正在结算你的科技。' : '等待对方结算神秘科技。'
  }
  if (stage === 'locked' || stage === 'selecting') return '已锁定，等待对方选择。'
  return '等待对方。'
}

export function opponentLocked(lockedPlayers: string[], selfSeat: string): boolean {
  const mine = selfSeat === 'p2' ? 'p2' : selfSeat === 'p1' ? 'p1' : selfSeat
  return lockedPlayers.some((seat) => seat && seat !== mine)
}

export function mysteryTechReducedMotion(motion: MotionPreference | string | null | undefined): boolean {
  if (motion === 'reduced') return true
  try {
    return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

export function isMysteryTechRoomState(state: string | null | undefined): boolean {
  return state === 'mystery_tech_selection' || state === 'mystery_tech_resolution'
}

export function flowRouteForRoomState(state: string | null | undefined): 'placement' | 'rps' | 'game' | 'game-over' | null {
  if (state === 'placing_ships') return 'placement'
  if (state === 'rock_paper_scissors') return 'rps'
  if (state === 'attacking' || isMysteryTechRoomState(state)) return 'game'
  if (state === 'game_over') return 'game-over'
  return null
}

export function sonarPreview(origin: MysteryTechCell | null): MysteryTechCell[] {
  if (!origin) return []
  const cells: MysteryTechCell[] = []
  for (const dy of [0, 1]) {
    for (const dx of [0, 1]) {
      const x = origin.x + dx
      const y = origin.y + dy
      if (x <= 5 && y <= 5) cells.push({ x, y })
    }
  }
  return cells
}

export function cellKeyOf(cell: MysteryTechCell): string {
  return `${cell.x}-${cell.y}`
}

export function shipByCell(ships: MysteryTechTargetShip[], x: number, y: number): MysteryTechTargetShip | null {
  return ships.find((ship) => ship.positions.some((cell) => cell.x === x && cell.y === y)) ?? null
}

export { EMPTY_MYSTERY_TECH_STATE }
