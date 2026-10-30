/**
 * Replay view model (ticket #28).
 *
 * The wire payload is the contract (docs/REPLAY_2026_09_23.md section 2-6):
 * sparse + incremental timelines for ships / hands / effects / attacks /
 * remaining, a list of board resets and server-computed progress nodes. This
 * module is the one implementation of "what does frame k look like"; the screen
 * renders it and the external gate recomputes the same frame from the raw
 * payload.
 *
 * It only formats server values. No game rule (hit / damage / remaining ships)
 * is re-derived here: the remaining timeline is the authoritative counter, and
 * the cell glyphs are the legacy convention (sunk/hit = X, ship = boat, miss = O).
 */

export type Side = 'p1' | 'p2'
export type JsonObject = Record<string, unknown>

export interface ReplayShipCell {
  x: number
  y: number
  alive?: boolean
  sunk?: boolean
}

export interface ReplayMark {
  hit: boolean
  sunk: boolean
  /** Struck by an area card (轰炸 / 硫磺火焰) rather than by a single shot. */
  area: boolean
}

export interface ReplayHole {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface ReplayArea {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface ReplayEffect {
  shield: Array<[number, number]>
  holes: ReplayHole[]
  frozen: ReplayArea | null
  lastStand: Array<[number, number]>
  lastStandOwner: string | null
}

export interface ReplayNode {
  step: number
  kind: string
  label: string
}

/** One card on the chain stack when a step happened (public rows only). */
export interface ReplayChainItem {
  card: string
  side: 'p1' | 'p2' | null
  negated: boolean
}

export interface ReplayStep {
  i: number
  kind: string
  actor: string | null
  text: string
  detail: JsonObject
  /** Sparse context stamped by the server recorder (carry-forward wins). */
  phase?: string
  round?: number
  chain?: ReplayChainItem[]
}

export interface ReplayPayload {
  version: number
  p1Name: string
  p2Name: string
  startedAt: number
  steps: ReplayStep[]
  ships: JsonObject[]
  hands: JsonObject[]
  attacks: JsonObject[]
  effects: JsonObject[]
  remaining: JsonObject[]
  boardResets: JsonObject[]
  /** Server-side phase / big-round / chain timelines (ticket #18 recorder). */
  phases: JsonObject[]
  rounds: JsonObject[]
  chains: JsonObject[]
  nodes: ReplayNode[]
  truncated: string
}

export interface ReplayFrame {
  ships: Record<Side, ReplayShipCell[]>
  hand: Record<Side, string[]>
  effect: Record<Side, ReplayEffect | null>
  marks: Record<Side, Record<string, ReplayMark>>
  resetAt: Record<Side, number[]>
  alive: Record<Side, number | null>
  /** Context of step k: phase text, big-round number, current chain stack. */
  phase: string
  round: number | null
  chain: ReplayChainItem[]
}

export type CellEffect = 'shield' | 'hole' | 'frozen' | 'laststand' | null

export interface ReplayCell {
  hasShip: boolean
  sunk: boolean
  hit: boolean
  miss: boolean
  /** Area strike (轰炸 / 硫磺火焰): one card that hit several cells at once. */
  area: boolean
  effect: CellEffect
  label: string
}

/**
 * Cards that strike a whole row/column (轰炸) or six linked cells (硫磺火焰).
 *
 * The payload has no per-cell "this was area damage" field and the recorder
 * cannot add one without a protocol change, so the same-step rule is used: an
 * attack row stamped with the step of one of these cards *is* that strike. The
 * step's detail carries the played card (note_card_played) on every path,
 * chained plays included.
 */
export const AREA_STRIKE_CARDS = ['轰炸', '硫磺火焰'] as const

export function isAreaStrikeCard(name: string): boolean {
  return (AREA_STRIKE_CARDS as readonly string[]).includes(name)
}

export function isObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function asInt(value: unknown, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10)
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function emptyEffect(): ReplayEffect {
  return { shield: [], holes: [], frozen: null, lastStand: [], lastStandOwner: null }
}

function xyPairs(value: unknown): Array<[number, number]> {
  const out: Array<[number, number]> = []
  for (const item of asArray(value)) {
    let x = -1
    let y = -1
    if (Array.isArray(item) && item.length >= 2) {
      x = asInt(item[0], -1)
      y = asInt(item[1], -1)
    } else if (isObject(item)) {
      x = asInt(item.x, -1)
      y = asInt(item.y, -1)
    }
    if (x >= 0 && y >= 0) out.push([x, y])
  }
  return out
}

function area(value: unknown): ReplayArea | null {
  if (!isObject(value)) return null
  const x1 = asInt(value.x1, -1)
  const y1 = asInt(value.y1, -1)
  const x2 = asInt(value.x2, -1)
  const y2 = asInt(value.y2, -1)
  if (x1 < 0 || y1 < 0 || x2 < 0 || y2 < 0) return null
  return { x1, y1, x2, y2 }
}

function normalizeEffect(value: unknown): ReplayEffect {
  if (!isObject(value)) return emptyEffect()
  const holes: ReplayHole[] = []
  for (const raw of asArray(value.shenwei_holes)) {
    const parsed = area(raw)
    if (parsed) holes.push(parsed)
  }
  return {
    shield: xyPairs(value.shield),
    holes,
    frozen: area(value.frozen_area),
    lastStand: xyPairs(value.last_stand_cells),
    lastStandOwner: asString(value.last_stand_owner) || null,
  }
}

function normalizeSteps(value: unknown): ReplayStep[] {
  const out: ReplayStep[] = []
  for (const raw of asArray(value)) {
    if (!isObject(raw)) continue
    out.push({
      i: asInt(raw.i, out.length),
      kind: asString(raw.kind) || 'system',
      actor: asString(raw.actor) || null,
      text: asString(raw.text),
      detail: isObject(raw.detail) ? raw.detail : {},
    })
  }
  return out
}

function normalizeNodes(value: unknown): ReplayNode[] {
  const out: ReplayNode[] = []
  for (const raw of asArray(value)) {
    if (!isObject(raw)) continue
    out.push({
      step: asInt(raw.step, 0),
      kind: asString(raw.kind) || 'phase',
      label: asString(raw.label),
    })
  }
  return out
}

/** Normalise one served GET /api/replay/<id> payload (never trusts shapes). */
export function normalizePayload(raw: unknown): ReplayPayload | null {
  if (!isObject(raw) || !Array.isArray(raw.steps)) return null
  const steps = normalizeSteps(raw.steps)
  if (!steps.length) return null
  return {
    version: asInt(raw.version, 0),
    p1Name: asString(raw.p1_name),
    p2Name: asString(raw.p2_name),
    startedAt: asInt(raw.started_at, 0),
    steps,
    ships: asArray(raw.ships).filter(isObject),
    hands: asArray(raw.hands).filter(isObject),
    attacks: asArray(raw.attacks).filter(isObject),
    effects: asArray(raw.effects).filter(isObject),
    remaining: asArray(raw.remaining).filter(isObject),
    boardResets: asArray(raw.board_resets).filter(isObject),
    phases: asArray(raw.phases).filter(isObject),
    rounds: asArray(raw.rounds).filter(isObject),
    chains: asArray(raw.chains).filter(isObject),
    nodes: normalizeNodes(raw.nodes),
    truncated: asString(raw.truncated),
  }
}

/** Public chain rows; an unreadable item is dropped, never invented. */
export function normalizeChain(value: unknown): ReplayChainItem[] {
  const out: ReplayChainItem[] = []
  for (const raw of asArray(value)) {
    if (!isObject(raw)) continue
    const card = asString(raw.card)
    if (!card) continue
    out.push({
      card,
      side: raw.side === 'p1' || raw.side === 'p2' ? raw.side : null,
      negated: raw.negated === true,
    })
  }
  return out
}

export function phaseText(phase: string): string {
  if (phase === 'preparation') return '准备阶段'
  if (phase === 'battle') return '战斗阶段'
  if (phase === 'end') return '结束阶段'
  return phase || '—'
}

export function chainText(chain: ReplayChainItem[]): string {
  if (!chain.length) return '无'
  return chain
    .map((item) => {
      const owner = item.side === 'p1' ? '先手' : item.side === 'p2' ? '后手' : ''
      const negated = item.negated ? '（已无效）' : ''
      return (owner ? owner + '·' : '') + item.card + negated
    })
    .join(' → ')
}

const SIDES: readonly Side[] = ['p1', 'p2']

/**
 * Fold a replacement timeline (ships / hands / effects): a row occurrence
 * replaces that side's whole value, so the last row with step <= k wins.
 */
function foldReplacement<T>(rows: JsonObject[], k: number, target: Record<Side, T | null>): void {
  for (const row of rows) {
    if (asInt(row.step, -1) > k) break
    for (const side of SIDES) {
      if (row[side] !== undefined && row[side] !== null) target[side] = row[side] as T
    }
  }
}

function normalizeShips(value: unknown): ReplayShipCell[] {
  const out: ReplayShipCell[] = []
  for (const raw of asArray(value)) {
    if (!isObject(raw)) continue
    const x = asInt(raw.x, -1)
    const y = asInt(raw.y, -1)
    if (x < 0 || y < 0) continue
    const cell: ReplayShipCell = { x, y }
    if (raw.alive === true) cell.alive = true
    if (raw.sunk === true) cell.sunk = true
    out.push(cell)
  }
  return out
}

function normalizeHand(value: unknown): string[] {
  const out: string[] = []
  for (const raw of asArray(value)) {
    if (typeof raw === 'string') out.push(raw)
    else if (isObject(raw)) out.push(asString(raw.name) || JSON.stringify(raw))
    else if (raw !== null && raw !== undefined) out.push(String(raw))
  }
  return out
}

/**
 * Compute frame k.
 *
 * Ships / hands / effects are replacement timelines (a row carries the whole
 * side); attacks are incremental (each row carries only the new cells) and are
 * filtered by the last board reset of that side, because a reset wipes the
 * marks on that board. The remaining timeline is the authoritative ship
 * counter; a missing timeline (old blob) stays null and the caller falls back
 * to counting ship cells.
 */
export function computeFrame(payload: ReplayPayload | null, k: number): ReplayFrame {
  const frame: ReplayFrame = {
    ships: { p1: [], p2: [] },
    hand: { p1: [], p2: [] },
    effect: { p1: null, p2: null },
    marks: { p1: {}, p2: {} },
    resetAt: { p1: [], p2: [] },
    alive: { p1: null, p2: null },
    phase: '',
    round: null,
    chain: [],
  }
  if (!payload) return frame
  const last = Math.max(0, payload.steps.length - 1)
  const target = Math.min(Math.max(asInt(k, 0), 0), last)

  const ships: Record<Side, ReplayShipCell[] | null> = { p1: null, p2: null }
  const hands: Record<Side, string[] | null> = { p1: null, p2: null }
  const effects: Record<Side, ReplayEffect | null> = { p1: null, p2: null }
  foldReplacement(payload.ships, target, ships)
  foldReplacement(payload.hands, target, hands)
  foldReplacement(payload.effects, target, effects)
  for (const side of SIDES) {
    frame.ships[side] = normalizeShips(ships[side] ?? [])
    frame.hand[side] = normalizeHand(hands[side] ?? [])
    frame.effect[side] = effects[side] ? normalizeEffect(effects[side]) : null
  }

  for (const row of payload.remaining) {
    if (asInt(row.step, -1) > target) break
    for (const side of SIDES) {
      const value = row[side]
      if (typeof value === 'number' && Number.isFinite(value)) frame.alive[side] = Math.trunc(value)
    }
  }

  for (const row of payload.boardResets) {
    const side = row.side
    const step = asInt(row.step, -1)
    if ((side === 'p1' || side === 'p2') && step >= 0 && step <= target) {
      frame.resetAt[side].push(step)
    }
  }
  const lastReset: Record<Side, number> = { p1: -1, p2: -1 }
  for (const side of SIDES) {
    for (const step of frame.resetAt[side]) {
      if (step > lastReset[side]) lastReset[side] = step
    }
  }

  // Steps that played an area card, so their attack row can be drawn as such.
  const areaSteps = new Set<number>()
  for (const step of payload.steps) {
    if (isAreaStrikeCard(asString(step.detail.card))) areaSteps.add(step.i)
  }

  const hits: Record<Side, Array<{ step: number; cell: JsonObject }>> = { p1: [], p2: [] }
  for (const row of payload.attacks) {
    const step = asInt(row.step, -1)
    if (step < 0) continue
    if (step > target) break
    for (const side of SIDES) {
      const cells = row[side]
      if (!Array.isArray(cells)) continue
      for (const cell of cells) if (isObject(cell)) hits[side].push({ step, cell })
    }
  }
  frame.phase = foldContextText(payload, 'phases', 'phase', target)
  frame.round = foldContextRound(payload, target)
  frame.chain = foldContextChain(payload, target)

  for (const side of SIDES) {
    for (const hit of hits[side]) {
      const x = asInt(hit.cell.x, -1)
      const y = asInt(hit.cell.y, -1)
      if (x < 0 || y < 0 || x > 5 || y > 5) continue
      if (hit.step <= lastReset[side]) continue
      frame.marks[side][x + ',' + y] = {
        hit: hit.cell.hit === true,
        sunk: hit.cell.sunk === true,
        area: areaSteps.has(hit.step),
      }
    }
  }
  return frame
}

/**
 * Context of frame k. The recorder writes phase/round/chain timelines *and*
 * sparse stamps on the steps; the timelines are authoritative when present (an
 * old blob without them falls back to the step stamps). Carry-forward means the
 * top bar shows the last known value, not an empty bar mid-replay.
 */
function foldContextText(payload: ReplayPayload, rowsKey: 'phases', field: string, k: number): string {
  let value = ''
  for (const row of payload[rowsKey]) {
    if (asInt(row.step, -1) > k) break
    const text = asString(row[field])
    if (text) value = text
  }
  if (value) return value
  for (const step of payload.steps) {
    if (step.i > k) break
    const stamped = asString(step.phase)
    if (stamped) value = stamped
  }
  return value
}

function foldContextRound(payload: ReplayPayload, k: number): number | null {
  let value: number | null = null
  for (const row of payload.rounds) {
    if (asInt(row.step, -1) > k) break
    const number = asInt(row.round, -1)
    if (number >= 0) value = number
  }
  if (value !== null) return value
  for (const step of payload.steps) {
    if (step.i > k) break
    if (typeof step.round === 'number' && Number.isFinite(step.round)) {
      value = Math.trunc(step.round)
    }
  }
  return value
}

function foldContextChain(payload: ReplayPayload, k: number): ReplayChainItem[] {
  let value: ReplayChainItem[] = []
  for (const row of payload.chains) {
    if (asInt(row.step, -1) > k) break
    value = normalizeChain(row.items)
  }
  if (value.length) return value
  for (const step of payload.steps) {
    if (step.i > k) break
    if (Array.isArray(step.chain) && step.chain.length) value = step.chain
  }
  return value
}

function effectOf(frame: ReplayFrame, side: Side, x: number, y: number): { kind: CellEffect; label: string } | null {
  const effect = frame.effect[side]
  if (!effect) return null
  if (effect.shield.some(([sx, sy]) => sx === x && sy === y)) {
    return { kind: 'shield', label: '护盾：这一格有战舰护盾，能挡下下一炮' }
  }
  if (effect.holes.some((hole) => x >= hole.x1 && x <= hole.x2 && y >= hole.y1 && y <= hole.y2)) {
    return { kind: 'hole', label: '神威：这一格被扣掉，暂时打不到' }
  }
  if (effect.frozen && x >= effect.frozen.x1 && x <= effect.frozen.x2 && y >= effect.frozen.y1 && y <= effect.frozen.y2) {
    return { kind: 'frozen', label: '冻结区：这一格的战舰本回合不能开火' }
  }
  if (effect.lastStand.some(([sx, sy]) => sx === x && sy === y)) {
    return { kind: 'laststand', label: '绝处逢生：新战舰可能出现在这一格' }
  }
  return null
}

/** One cell at frame k (glyph + accessible label; same convention as legacy). */
export function cellOf(frame: ReplayFrame, side: Side, x: number, y: number): ReplayCell {
  const ship = frame.ships[side].find((cell) => cell.x === x && cell.y === y) ?? null
  const mark = frame.marks[side][x + ',' + y] ?? null
  const sunk = Boolean(ship && ship.sunk === true && ship.alive !== true)
  const effect = effectOf(frame, side, x, y)
  const cell: ReplayCell = {
    hasShip: Boolean(ship),
    sunk,
    hit: Boolean(mark && mark.hit),
    miss: Boolean(mark && !mark.hit),
    area: Boolean(mark && mark.area),
    effect: effect ? effect.kind : null,
    label: '',
  }
  let base: string
  if (cell.sunk) base = '击沉：这一格的战舰已被打沉'
  else if (ship && cell.hit) base = '命中：这一格有战舰'
  else if (ship) base = '战舰：这一格有船，还没被打到'
  else if (cell.hit) base = '命中：这一格已经空了'
  else if (cell.miss) base = '落空：这一格打空了'
  else base = '海面：没有船，也没被打过'
  if (cell.sunk && effect && effect.kind === 'hole') {
    base += '（神威把这一格从棋盘上扣掉了，这一格的战舰不会再回来）'
  }
  if (cell.area) base = '轰炸/硫磺火焰：这一格是被范围魔法打掉的。' + base
  cell.label = effect ? effect.label + '（' + base + '）' : base
  return cell
}

/** Cell glyph: only a cell that was shot at is X; an untouched ship is a boat. */
export function cellGlyph(cell: ReplayCell): string {
  if (cell.sunk || cell.hit) return '✕'
  if (cell.hasShip) return '⛴'
  if (cell.miss) return '○'
  return ''
}

export function cellClass(cell: ReplayCell): string {
  let classes = 'cell'
  if (cell.sunk) classes += ' ship sunk hit'
  else if (cell.hasShip && cell.hit) classes += ' ship hit'
  else if (cell.hasShip) classes += ' ship'
  else if (cell.hit) classes += ' hit'
  else if (cell.miss) classes += ' miss'
  else classes += ' replay-water'
  if (cell.area) classes += ' area-strike'
  if (!cell.sunk) {
    if (cell.effect === 'shield') classes += ' shielded'
    else if (cell.effect === 'hole') classes += ' shenwei-hole'
    else if (cell.effect === 'frozen') classes += ' frozen-area'
    else if (cell.effect === 'laststand') classes += ' last-stand-candidate'
  }
  return classes
}

/** Alive ships: the authoritative remaining timeline, else count ship cells. */
export function shipsAlive(frame: ReplayFrame, side: Side): number {
  const counted = frame.alive[side]
  if (counted !== null && counted !== undefined && Number.isFinite(counted)) return Math.trunc(counted)
  const seen = new Set<string>()
  let alive = 0
  for (const cell of frame.ships[side]) {
    const key = cell.x + ',' + cell.y
    if (seen.has(key)) continue
    seen.add(key)
    if (cell.alive === true || cell.sunk !== true) alive += 1
  }
  return alive
}

export const STEP_KIND_TEXT: Record<string, string> = {
  attack: '炮击',
  magic: '魔法卡',
  quick_chat: '快捷消息',
  game_over: '对局结束',
  system: '系统',
  place_ships: '摆放战舰',
  rps_choice: '猜拳',
  enter_battle: '进攻阶段',
  enter_end: '结束阶段',
  end_turn: '结束回合',
  surrender: '投降',
  result: '对局结束',
}

export function stepKindText(kind: string): string {
  return STEP_KIND_TEXT[kind] || kind || '—'
}

/** Node position on the track: its real step (the same ruler as k / (n - 1)). */
export function nodePercent(step: number, totalSteps: number): number {
  const total = asInt(totalSteps, 0)
  if (total <= 1) return 0
  let at = asInt(step, 0)
  if (at < 0) at = 0
  if (at > total - 1) at = total - 1
  return (at / (total - 1)) * 100
}

export function nodeTipText(payload: ReplayPayload | null, node: ReplayNode | null): string {
  if (!payload || !node) return ''
  const step = payload.steps[asInt(node.step, -1)] ?? null
  const label = node.label
  const parts = ['第 ' + (asInt(node.step, 0) + 1) + ' 步']
  const actor = step && step.actor ? step.actor : ''
  if (actor && label.indexOf(actor) < 0) parts.push(actor)
  parts.push(label)
  let text = parts.join(' · ')
  if (step && step.text && step.text !== label && step.text.indexOf(label) < 0) {
    text += '\n' + step.text
  }
  return text
}

/** One human-readable sentence per HTTP status (docs section D2 / legacy wording). */
export function errorTextForStatus(status: number): string {
  switch (status) {
    case 401:
      return '请先登录后再查看对局回放。'
    case 403:
      return '你没有权限查看这一局的回放。'
    case 404:
      return '这局没有可回放的行动。'
    case 409:
      return '这条回放的格式版本不支持，无法播放。'
    case 500:
      return '这条回放已损坏或体积异常，无法播放。'
    case 503:
      return '服务暂时无法读取回放，请稍后重试。'
    default:
      return '加载回放失败，请稍后重试。'
  }
}

export interface HandChip {
  key: string
  testid: string
  name: string
}

/** Read-only hand chips. Duplicate names (the x3 card) get a stable suffix. */
export function handChips(side: Side, hand: string[]): HandChip[] {
  const seen = new Map<string, number>()
  const chips: HandChip[] = []
  for (const name of hand) {
    const count = (seen.get(name) ?? 0) + 1
    seen.set(name, count)
    const safe = name.replace(/"/g, "'").replace(/\s+/g, '_') || 'card'
    const suffix = count > 1 ? '-' + count : ''
    chips.push({
      key: name + '#' + count,
      testid: 'replay-hand-card-' + side + '-' + safe + suffix,
      name,
    })
  }
  return chips
}

/** Deterministic testid per node; duplicate step nodes get a stable suffix. */
export function nodeEntries(payload: ReplayPayload): Array<{ node: ReplayNode; testid: string }> {
  const seen = new Map<string, number>()
  return payload.nodes.map((node) => {
    const base = 'replay-node-' + node.step
    const count = (seen.get(base) ?? 0) + 1
    seen.set(base, count)
    return { node, testid: count > 1 ? base + '-' + count : base }
  })
}
