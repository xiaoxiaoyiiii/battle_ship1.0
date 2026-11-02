/** 两种录像适配到同一观看帧；所有牌效和随机结果由服务端记录决定。 */
import { normalizePayload, computeFrame, type ReplayPayload } from '../replay/model'
import type { BoardCell } from '../game/view'
import type { Json, Recording, Side, ViewBoard, ViewEvent, ViewFrame } from './types'

export const sides: readonly Side[] = ['p1', 'p2']
export const object = (v: unknown): v is Json => !!v && typeof v === 'object' && !Array.isArray(v)
export const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T
const emptyBoard = (): ViewBoard => ({ fleet: [], marks: [], shots: [], reveals: [], holes: [], frozen_area: null, last_stand: [] })

export function normalizeViewFrame(raw: unknown): ViewFrame | null {
  if (!object(raw) || raw.version !== 2 || !['replay', 'spectator'].includes(String(raw.audience))) return null
  if (!object(raw.context) || !object(raw.rules) || !object(raw.players) || !object(raw.boards)) return null
  for (const side of sides) {
    const p = raw.players[side], b = raw.boards[side]
    if (!object(p) || !object(b) || typeof p.name !== 'string' || !Number.isInteger(p.hand_count) || !Number.isInteger(p.remaining_ships)) return null
    if (!['fleet', 'marks', 'shots', 'reveals', 'holes', 'last_stand'].every(key => Array.isArray(b[key]))) return null
    if (p.cards !== null && !Array.isArray(p.cards)) return null
  }
  return copy(raw) as unknown as ViewFrame
}

function legacyFrame(payload: ReplayPayload, k: number): ViewFrame {
  const old = computeFrame(payload, k)
  const frame: ViewFrame = { version: 2, audience: 'replay',
    context: { phase: old.phase, round: old.round, current_side: null, attacks_remaining: null },
    rules: { ids: [], entries: [] }, players: {} as ViewFrame['players'], boards: {} as ViewFrame['boards'],
    chain: { chain: old.chain.map(c => ({ card: c.card, seat: c.side, negated: c.negated })) },
  }
  for (const side of sides) {
    frame.players[side] = { name: (side === 'p1' ? payload.p1Name : payload.p2Name) || side,
      remaining_ships: old.alive[side] ?? old.ships[side].filter(s => s.alive).length,
      hand_count: old.hand[side].length, cards: old.hand[side].map(name => ({ name })), effects: [] }
    const effect = old.effect[side]
    frame.boards[side] = { ...emptyBoard(), fleet: old.ships[side].map(c => ({ ...c, sunk: c.sunk === true && c.alive !== true,
      shielded: effect?.shield.some(([x, y]) => x === c.x && y === c.y) ?? false })),
      marks: Object.entries(old.marks[side]).map(([key, mark]) => { const [x, y] = key.split(',').map(Number); return { x, y, ...mark } }),
      holes: effect?.holes ?? [], frozen_area: effect?.frozen ?? null,
      last_stand: effect?.lastStand.map(([x, y]) => ({ x, y })) ?? [] }
  }
  return frame
}

export function decodeRecording(raw: unknown): Recording | null {
  if (!object(raw) || !Array.isArray(raw.steps) || !raw.steps.length) return null
  if (raw.version === 1) {
    const legacy = normalizePayload(raw)
    return legacy ? { version: 1, steps: legacy.steps, initial: legacyFrame(legacy, 0), events: [], checkpoints: [],
      nodes: legacy.nodes, truncated: legacy.truncated, legacy } : null
  }
  if (raw.version !== 2) return null
  const initial = normalizeViewFrame(raw.initial_state)
  if (!initial || !Array.isArray(raw.events) || !Array.isArray(raw.checkpoints)) return null
  let lastSeq = 0, lastStep = 0
  const events: ViewEvent[] = []
  for (const e of raw.events) {
    if (!object(e) || !Number.isInteger(e.seq) || Number(e.seq) <= lastSeq || !Number.isInteger(e.step) || Number(e.step) < lastStep) return null
    if (e.type !== 'state' && e.type !== 'presentation') return null
    if (e.type === 'state' && (!object(e.patch) || Object.keys(e.patch).some(key => !['context', 'rules', 'players', 'boards', 'chain'].includes(key)))) return null
    lastSeq = Number(e.seq); lastStep = Number(e.step); events.push(copy(e) as unknown as ViewEvent)
  }
  const checkpoints: Recording['checkpoints'] = []
  for (const c of raw.checkpoints) {
    if (!object(c)) return null
    const frame = normalizeViewFrame(c.frame)
    if (!frame || !Number.isInteger(c.seq) || !Number.isInteger(c.step) || Number(c.seq) > lastSeq) return null
    checkpoints.push({ seq: Number(c.seq), step: Number(c.step), frame })
  }
  const normalized = normalizePayload(raw)
  if (!normalized) return null
  return { version: 2, steps: normalized.steps, initial, events, checkpoints, nodes: normalized.nodes, truncated: normalized.truncated }
}

export function frameAt(recording: Recording, k: number): ViewFrame {
  if (recording.version === 1) return legacyFrame(recording.legacy as ReplayPayload, k)
  const target = recording.steps[Math.max(0, Math.min(recording.steps.length - 1, k))]?.i ?? 0
  const checkpoint = recording.checkpoints.filter(c => c.step <= target).at(-1)
  let frame = copy(checkpoint?.frame ?? recording.initial)
  for (const event of recording.events) {
    if (event.seq <= (checkpoint?.seq ?? 0)) continue
    if (event.step > target) break
    if (event.type === 'state') frame = { ...frame, ...copy(event.patch) }
  }
  return frame
}

export function boardCells(frame: ViewFrame, owner: Side): BoardCell[] {
  const board = frame.boards[owner]
  return Array.from({ length: 36 }, (_, i) => {
    const x = i % 6, y = Math.floor(i / 6)
    const ship = board.fleet.find(c => c.x === x && c.y === y)
    const mark = board.marks.find(c => c.x === x && c.y === y)
    const inArea = (a: { x1: number; y1: number; x2: number; y2: number } | null) => !!a && x >= a.x1 && x <= a.x2 && y >= a.y1 && y <= a.y2
    return { x, y, key: `${x}-${y}`, ship: !!ship, sunk: !!ship?.sunk || !!mark?.sunk,
      frozen: !!ship?.frozen, shielded: !!ship?.shielded, invincible: !!ship?.invincible, trap: !!ship?.trap,
      hit: !!ship?.hit || !!mark?.hit, miss: !!mark && !mark.hit, shieldBroken: false, revived: false,
      revealed: board.reveals.some(c => c.x === x && c.y === y), hole: board.holes.some(inArea),
      frozenArea: inArea(board.frozen_area), lastStand: board.last_stand.some(c => c.x === x && c.y === y),
      attackable: false, label: `${x + 1},${y + 1}` }
  })
}
