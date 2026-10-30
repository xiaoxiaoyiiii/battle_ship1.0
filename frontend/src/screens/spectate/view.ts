/**
 * Spectate view helpers (ticket #28).
 *
 * The spectator screen is a deliberately separate screen: its boards are
 * rebuilt from "cells this seat already shot at" only, and no ship position is
 * ever part of the data it receives (the server whitelist is the guarantee; this
 * module is the second line of defence -- it does not even have a code path that
 * reads a fleet).
 *
 * Everything here formats server values; no game rule is recomputed.
 */

export type SeatLabel = 'p1' | 'p2'
export type JsonObject = Record<string, unknown>

export interface SpectateCell {
  x: number
  y: number
  hit: boolean
  ship_sunk: boolean
}

export interface SpectateSide {
  seatId: string
  name: string
  remainingShips: number
  handCount: number
}

export interface SpectateLog {
  ts: number
  type: string
  text: string
}

export type ChatKind = 'msg' | 'player' | 'notice' | 'error'

export interface SpectateChatLine {
  seq: number
  kind: ChatKind
  name: string
  text: string
}

export interface SpectateRosterRow {
  name: string
  joinedAt: number
}

export function isObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function asObject(value: unknown): JsonObject | null {
  return isObject(value) ? value : null
}

export function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function asInt(value: unknown, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10)
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/** Raw seat key (matching rooms: the socket id) -> p1/p2, never guessed. */
export function seatOf(labels: Record<string, string>, rawKey: unknown): SeatLabel | null {
  const key = typeof rawKey === 'string' ? rawKey : ''
  if (!key) return null
  const label = labels[key]
  return label === 'p1' || label === 'p2' ? label : null
}

/** One public board cell: only the four fields the spectator may see. */
export function normalizeCell(raw: unknown): SpectateCell | null {
  if (!isObject(raw)) return null
  const x = asInt(raw.x, -1)
  const y = asInt(raw.y, -1)
  if (x < 0 || y < 0 || x > 5 || y > 5) return null
  return { x, y, hit: raw.hit === true, ship_sunk: raw.ship_sunk === true }
}

export function attackCells(raw: unknown): SpectateCell[] {
  const cells: SpectateCell[] = []
  for (const item of asArray(raw)) {
    const cell = normalizeCell(item)
    if (cell) cells.push(cell)
  }
  return cells
}

/**
 * Cells drawn on one board = the cells the OTHER seat shot at.
 *
 * The state keeps one list per seat ("cells this seat shot at"); the board is
 * the single transpose of that list. Server board frames use the same seat
 * direction, so they are folded into the same list and never transposed twice
 * (the legacy batch 6 bug swapped both boards silently).
 */
export function boardCells(
  attacks: { p1: SpectateCell[]; p2: SpectateCell[] },
  board: SeatLabel,
): Map<string, SpectateCell> {
  const source = board === 'p1' ? attacks.p2 : attacks.p1
  const map = new Map<string, SpectateCell>()
  for (const cell of source) map.set(cell.x + ',' + cell.y, cell)
  return map
}

export const PHASE_TEXT: Record<string, string> = {
  preparation: '准备阶段',
  battle: '战斗阶段',
  end: '结束阶段',
}

export function phaseText(value: string): string {
  return PHASE_TEXT[value] || value || '—'
}

export function displayName(value: unknown): string {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || '某位观众'
}

export function seatName(
  sides: { p1: SpectateSide | null; p2: SpectateSide | null },
  label: SeatLabel | null,
): string {
  if (!label) return '玩家'
  const side = sides[label]
  return side && side.name ? side.name : '玩家'
}

/** "who is acting" / first-or-second, using only seat labels and names. */
export function turnText(
  labels: Record<string, string>,
  sides: { p1: SpectateSide | null; p2: SpectateSide | null },
  currentAttacker: string,
): string {
  const label = seatOf(labels, currentAttacker)
  if (!label) return '—'
  return seatName(sides, label) + (label === 'p1' ? '（先手）' : '（后手）')
}

export interface StatusInput {
  phase: 'idle' | 'joining' | 'joined' | 'error' | 'ended'
  error: string
  stateValue: string
  ranked: boolean
  endedReason: string
  winnerLabel: string
}

export function statusText(input: StatusInput): string {
  if (input.phase === 'idle') return '正在连接观战…'
  if (input.phase === 'joining') return '正在进入观战…'
  if (input.phase === 'error') return input.error
  if (input.phase === 'ended') {
    if (input.winnerLabel) return '对局已结束 · ' + input.winnerLabel + ' 获胜，可以退出观战了'
    if (input.endedReason) return '观战已结束：' + input.endedReason
    return '对局已结束，可以退出观战了'
  }
  const parts: string[] = []
  if (input.ranked) parts.push('排位局')
  if (input.stateValue === 'placing_ships') parts.push('双方正在布置战舰')
  else if (input.stateValue === 'rock_paper_scissors') parts.push('猜拳定先手')
  parts.push('画面随每一步动作实时更新')
  return parts.join(' · ')
}

function safeToken(value: string): string {
  const text = value.replace(/"/g, "'").replace(/\s+/g, '_')
  return text || 'item'
}

/** Stable per-spectator testid (names are unique per seat list in practice). */
export function rosterTestid(name: string): string {
  return 'spectate-roster-item-' + safeToken(name)
}

export function chatTestid(seq: number): string {
  return 'spectate-chat-line-' + seq
}

/** Chain stack (LIFO display; the served item shape is the sanitised one). */
export interface ChainRow {
  key: string
  seat: string
  card: string
  negated: boolean
}

export function chainRows(chain: JsonObject | null): ChainRow[] {
  const items = chain && Array.isArray(chain.chain) ? chain.chain : []
  const rows: ChainRow[] = []
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = isObject(items[index]) ? (items[index] as JsonObject) : null
    if (!item) continue
    let card = ''
    if (typeof item.card === 'string') card = item.card
    else if (isObject(item.card)) card = asString(item.card.name)
    else card = asString(item.card_name)
    rows.push({
      key: 'chain-' + index,
      seat: asString(item.seat) || 'unknown',
      card: card || '（未知卡牌）',
      negated: item.negated === true,
    })
  }
  return rows
}