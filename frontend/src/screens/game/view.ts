import type { CellAttack, GameState, ShipSnapshot } from '../../stores/gameStateSchema'

/**
 * Pure view model for the game screen (ticket #27).
 *
 * Everything here only formats server-provided values or mirrors a *frozen*
 * legacy client rule that the server cannot express through data (the UI
 * graying/hints of D10). No game rule is recomputed: attack counts, ship
 * survival, phase transitions and card legality are all decided by the server;
 * the screen renders what the store already holds.
 */

export interface CardLike {
  name: string
  speed: number | string
  type: string
  description?: string
}

export interface Point {
  x: number
  y: number
}

export interface LastAttackLike {
  attacker: string
  x: number
  y: number
  hit: boolean
  shipSunk: boolean
}

export interface PendingPickLike {
  reason: string
  message: string
}

export const BOARD_SIZE = 6

/** Legacy END_PHASE_PLAYABLE_CARDS (server: END_PHASE_PLAYABLE). */
export const END_PHASE_PLAYABLE_CARDS = ['Freezing！']

/** Legacy MAGIC_TARGET_DESCRIPTORS: shape + board ownership, per card name. */
export type TargetKind = 'area' | 'line' | 'continuous' | 'single' | 'own_ships' | 'shenwei'

export interface TargetDescriptor {
  kind: TargetKind
  size?: number
  length?: number
  count?: number
  board?: 'self' | 'opponent'
}

export const MAGIC_TARGET_DESCRIPTORS: Record<string, TargetDescriptor> = {
  '冻结': { kind: 'area', size: 3, board: 'opponent' },
  '探测雷达': { kind: 'area', size: 2, board: 'opponent' },
  '轰炸': { kind: 'line', board: 'opponent' },
  '硫磺火焰': { kind: 'continuous', length: 6, board: 'opponent' },
  '克苏鲁之眼': { kind: 'single', board: 'self' },
  '神之宣告': { kind: 'own_ships', count: 2 },
  '神威！': { kind: 'shenwei' },
}

/** Server SHIP_PICK_PRIORITY / SHIP_PICK_CARDS mirror (graying only). */
const SHIP_PICK_PRIORITIES: Record<string, number> = {
  demon_contract: 100,
  divine_decree: 80,
  trap_setup: 75,
  dice_sacrifice: 70,
  kraken_eye: 60,
  shield_choice: 40,
}

const SHIP_PICK_CARD_NAMES: Record<string, string> = {
  '克苏鲁之眼': 'kraken_eye',
  '神之宣告': 'divine_decree',
  '仁王之盾': 'shield_choice',
  '守株待兔': 'trap_setup',
  '命运骰子': 'dice_sacrifice',
}

const SHIP_PICK_LABELS: Record<string, string> = {
  demon_contract: '恶魔契约',
  divine_decree: '神之宣告',
  kraken_eye: '克苏鲁之眼',
  shield_choice: '仁王之盾',
  trap_setup: '守株待兔',
  trap_sacrifice: '守株待兔',
  dice_sacrifice: '命运骰子',
}

export function targetDescriptor(cardName: string): TargetDescriptor | null {
  return MAGIC_TARGET_DESCRIPTORS[cardName] ?? null
}

export function phaseLabel(phase: string | null | undefined): string {
  if (phase === 'preparation') return '准备阶段'
  if (phase === 'battle') return '战斗阶段'
  if (phase === 'end') return '结束阶段'
  return '未开始'
}

export function modeLabel(ranked: boolean, mode: string): string {
  if (ranked) return '排位赛'
  if (mode === 'ai') return '人机对战'
  if (mode === 'custom') return '自定义房间'
  if (mode === 'ranked') return '排位赛'
  return '休闲对战'
}

export function cardSpeed(card: CardLike | null | undefined): number {
  const value = Number(card?.speed)
  return Number.isFinite(value) ? value : 0
}

export function isMyTurn(state: GameState): boolean {
  return !!state.player_id && state.current_attacker === state.player_id
}

export function isFirstPlayer(state: GameState): boolean {
  const order = Array.isArray(state.attack_order) ? state.attack_order : []
  return order.length > 0 && order[0] === state.player_id
}

export function opponentId(state: GameState): string {
  const order = Array.isArray(state.attack_order) ? state.attack_order : []
  const other = order.find((id) => id && id !== state.player_id)
  if (other) return other
  const players = Array.isArray(state.rps_choices) ? [] : Object.keys(state.rps_choices || {})
  const fromRps = players.find((id) => id !== state.player_id)
  if (fromRps) return fromRps
  return state.current_attacker && state.current_attacker !== state.player_id ? state.current_attacker : ''
}

/** Legacy isLastStandActive: the lock lasts one turn; last_stand_win does not lock. */
export function isLastStandActive(state: GameState): boolean {
  if (state.last_stand_lock === true) return true
  const effects = Array.isArray(state.active_effects) ? state.active_effects : []
  return effects.includes('last_stand')
}

/** Legacy canPlayCard, copied as-is (D10: the frontend mirror is not "fixed"). */
export function canPlayCard(card: CardLike, state: GameState): boolean {
  if (isLastStandActive(state)) return false
  if (END_PHASE_PLAYABLE_CARDS.includes(card.name)) {
    return isFirstPlayer(state) && state.current_phase === 'end' && isMyTurn(state)
  }
  const speed = cardSpeed(card)
  if (speed === 1) return state.current_phase === 'preparation' && isMyTurn(state)
  if (speed === 2) {
    return (state.current_phase === 'preparation' || state.current_phase === 'battle') && isMyTurn(state)
  }
  if (speed === 3) return true
  return true
}

/** Legacy afterHitBlockReason (饮血 / 溅射 / 雷达子弹 only, D10 parity). */
export function afterHitBlockReason(card: CardLike | null, lastAttack: LastAttackLike | null, playerId: string): string {
  if (!card) return ''
  if (!['饮血', '溅射', '雷达子弹'].includes(card.name)) return ''
  if (!lastAttack || lastAttack.attacker !== playerId) return '你这一局还没有攻击过'
  if (card.name === '饮血') return lastAttack.shipSunk ? '' : '需要你先击沉对方一艘战舰'
  return lastAttack.hit ? '' : '需要你上一发攻击命中对方'
}

/** Legacy shipPickBlockedFor: only a *higher* priority pending pick blocks. */
export function shipPickBlockedReason(cardName: string, pendingPick: PendingPickLike | null): string {
  const want = SHIP_PICK_CARD_NAMES[cardName]
  if (!want || !pendingPick) return ''
  const current = SHIP_PICK_PRIORITIES[pendingPick.reason] ?? 0
  const wanted = SHIP_PICK_PRIORITIES[want] ?? 0
  if (current <= wanted) return ''
  const label = SHIP_PICK_LABELS[pendingPick.reason] ?? '战舰点选'
  return `请先完成「${label}」的选船，再使用这张卡`
}

export interface PlayabilityContext {
  lastAttack: LastAttackLike | null
  pendingPick: PendingPickLike | null
  chainBusy?: boolean
}

/** Why the card is grayed out (empty string = playable). */
export function cardDisabledReason(card: CardLike, state: GameState, ctx: PlayabilityContext): string {
  if (!canPlayCard(card, state)) {
    if (isLastStandActive(state)) {
      return `无法使用${card.name}：绝处逢生生效中，本回合你的其余魔法卡全部无效`
    }
    if (END_PHASE_PLAYABLE_CARDS.includes(card.name)) {
      const reasons: string[] = []
      if (!isFirstPlayer(state)) reasons.push('你这一局是后手')
      if (!isMyTurn(state)) reasons.push('不是你的回合')
      if (state.current_phase !== 'end') reasons.push('不是结束阶段')
      return `${card.name}只能在自己先手回合的结束阶段发动（${reasons.join('；') || '条件不满足'}）`
    }
    if (!isMyTurn(state)) return `无法使用${card.name}：现在不是你的回合`
    const phase = state.current_phase || '未开始'
    return `无法使用${card.name}：当前阶段${phase}不允许使用速阶${card.speed}的魔法卡`
  }
  const afterHit = afterHitBlockReason(card, ctx.lastAttack, state.player_id)
  if (afterHit) return `无法使用${card.name}：${afterHit}`
  const pickBlocked = shipPickBlockedReason(card.name, ctx.pendingPick)
  if (pickBlocked) return pickBlocked
  if (ctx.chainBusy) return `无法使用${card.name}：连锁响应中，请先响应连锁`
  return ''
}

/**
 * Refusal shown when the player actually clicks a card. Legacy also refuses
 * 禁忌果实 here (the field-magic check lives in playMagicCard, not canPlayCard),
 * so that card is not grayed but still explains itself on click.
 */
export function playRefusalReason(card: CardLike, state: GameState, ctx: PlayabilityContext): string {
  const disabled = cardDisabledReason(card, state, ctx)
  if (disabled) return disabled
  if (state.field_magic === '禁忌果实' && !['失灵！', '加百列之光'].includes(card.name) && card.type !== '场地') {
    return `无法使用${card.name}：场地魔法“禁忌果实”生效，非场地及失灵类魔法卡无法使用`
  }
  if (state.magic_blocked) return '你的魔法卡已被看破，本回合无法使用'
  return ''
}

/** Stable business identity of a hand card (name+speed), plus its occurrence. */
export function cardIdentity(card: CardLike): string {
  return `${card.name}-${card.speed}`
}

export function cardOccurrence(hand: CardLike[], index: number): number {
  const key = cardIdentity(hand[index])
  let seen = 0
  for (let i = 0; i < index; i += 1) {
    if (hand[i] && cardIdentity(hand[i]) === key) seen += 1
  }
  return seen
}

export function cardTestId(card: CardLike, index: number, hand: CardLike[]): string {
  return `game-card-${cardIdentity(card)}-${cardOccurrence(hand, index)}`
}

export function chainCardTestId(card: CardLike, index: number, hand: CardLike[]): string {
  return `game-chain-respond-${cardIdentity(card)}-${cardOccurrence(hand, index)}`
}

export function signedNumber(value: number): string {
  return value > 0 ? `+${value}` : String(value)
}

export function hitCount(attacks: CellAttack[]): number {
  return attacks.filter((cell) => cell && cell.hit).length
}

export function attackAt(attacks: CellAttack[], x: number, y: number): CellAttack | null {
  for (const cell of attacks) {
    if (cell && cell.x === x && cell.y === y) return cell
  }
  return null
}

export function shipCellSet(ships: ShipSnapshot[]): Map<string, ShipSnapshot> {
  const map = new Map<string, ShipSnapshot>()
  for (const ship of Array.isArray(ships) ? ships : []) {
    for (const position of Array.isArray(ship?.positions) ? ship.positions : []) {
      map.set(cellKey(position.x, position.y), ship)
    }
  }
  return map
}

export function cellKey(x: number, y: number): string {
  return `${x}-${y}`
}

export function holeCells(holes: unknown[], playerId: string): Set<string> {
  const cells = new Set<string>()
  for (const hole of Array.isArray(holes) ? holes : []) {
    if (!hole || typeof hole !== 'object') continue
    const record = hole as Record<string, unknown>
    if (playerId && record.player && record.player !== playerId) continue
    const x1 = Number(record.x1)
    const y1 = Number(record.y1)
    const x2 = Number(record.x2)
    const y2 = Number(record.y2)
    if (![x1, y1, x2, y2].every((value) => Number.isFinite(value))) continue
    for (let x = x1; x <= x2; x += 1) {
      for (let y = y1; y <= y2; y += 1) cells.add(cellKey(x, y))
    }
  }
  return cells
}

export interface FrozenAreaLike {
  x1: number
  y1: number
  x2: number
  y2: number
  owner?: string
  frozen?: number
}

export function frozenAreaCells(area: FrozenAreaLike | null, owner: string): Set<string> {
  const cells = new Set<string>()
  if (!area) return cells
  if (owner && area.owner && area.owner !== owner) return cells
  for (let x = Number(area.x1); x <= Number(area.x2); x += 1) {
    for (let y = Number(area.y1); y <= Number(area.y2); y += 1) cells.add(cellKey(x, y))
  }
  return cells
}

export interface BoardMarks {
  reversed?: boolean
  revealed?: Point[]
  shieldBroken?: Point[]
}

export interface BoardCell {
  x: number
  y: number
  key: string
  ship: boolean
  sunk: boolean
  frozen: boolean
  shielded: boolean
  trap: boolean
  invincible: boolean
  hit: boolean
  miss: boolean
  shieldBroken: boolean
  revealed: boolean
  hole: boolean
  frozenArea: boolean
  lastStand: boolean
  attackable: boolean
  label: string
}

function baseCell(x: number, y: number): BoardCell {
  return {
    x,
    y,
    key: cellKey(x, y),
    ship: false,
    sunk: false,
    frozen: false,
    shielded: false,
    trap: false,
    invincible: false,
    hit: false,
    miss: false,
    shieldBroken: false,
    revealed: false,
    hole: false,
    frozenArea: false,
    lastStand: false,
    attackable: false,
    label: `第 ${x + 1} 列 第 ${y + 1} 行`,
  }
}

function pointSet(points: Point[] | undefined): Set<string> {
  const set = new Set<string>()
  for (const point of points ?? []) {
    if (point && Number.isFinite(point.x) && Number.isFinite(point.y)) set.add(cellKey(point.x, point.y))
  }
  return set
}

/** My own sea: my ships, the opponent's shots on me, and the effect marks. */
export function buildSelfBoard(state: GameState, marks: BoardMarks = {}): BoardCell[] {
  const ships = shipCellSet(state.ships)
  const shots = Array.isArray(state.opponent_attacks) ? state.opponent_attacks : []
  const broken = pointSet(marks.shieldBroken)
  const holes = holeCells(state.shenwei_holes, state.player_id)
  const frozen = frozenAreaCells(state.frozen_area as unknown as FrozenAreaLike | null, state.player_id)
  const lastStand = pointSet(
    state.last_stand_owner === state.player_id ? (state.last_stand_cells as Point[]) : [],
  )
  const cells: BoardCell[] = []
  for (let y = 0; y < BOARD_SIZE; y += 1) {
    for (let x = 0; x < BOARD_SIZE; x += 1) {
      const cell = baseCell(x, y)
      const ship = ships.get(cell.key)
      if (ship) {
        cell.ship = true
        cell.sunk = ship.alive === false
        cell.frozen = Boolean(ship.frozen)
        cell.shielded = Boolean(ship.shield)
        cell.trap = Boolean(ship.trap) && !cell.sunk
        cell.invincible = Boolean(ship.invincible)
      }
      const shot = attackAt(shots, x, y)
      if (shot) {
        cell.hit = Boolean(shot.hit)
        cell.miss = !shot.hit
      }
      cell.shieldBroken = broken.has(cell.key)
      cell.hole = holes.has(cell.key)
      cell.frozenArea = frozen.has(cell.key)
      cell.lastStand = lastStand.has(cell.key)
      cells.push(cell)
    }
  }
  return cells
}

/** The opponent's sea: only public information (my shots, reveals, effect marks). */
export function buildOpponentBoard(state: GameState, marks: BoardMarks = {}): BoardCell[] {
  const shots = Array.isArray(state.attacks) ? state.attacks : []
  const revealed = pointSet(marks.revealed)
  const broken = pointSet(marks.shieldBroken)
  const other = opponentId(state)
  const holes = holeCells(state.shenwei_holes, other)
  const frozen = frozenAreaCells(state.frozen_area as unknown as FrozenAreaLike | null, other)
  const lastStand = pointSet(state.last_stand_owner && state.last_stand_owner === other ? (state.last_stand_cells as Point[]) : [])
  const canFire = isMyTurn(state) && state.current_phase === 'battle' && state.attacks_remaining > 0
  const cells: BoardCell[] = []
  for (let y = 0; y < BOARD_SIZE; y += 1) {
    for (let x = 0; x < BOARD_SIZE; x += 1) {
      const cell = baseCell(x, y)
      const shot = attackAt(shots, x, y)
      if (shot) {
        cell.hit = Boolean(shot.hit)
        cell.miss = !shot.hit
      }
      cell.revealed = revealed.has(cell.key)
      cell.shieldBroken = broken.has(cell.key)
      cell.hole = holes.has(cell.key)
      cell.frozenArea = frozen.has(cell.key)
      cell.lastStand = lastStand.has(cell.key)
      cell.attackable = canFire && !shot && !cell.hole
      cells.push(cell)
    }
  }
  return cells
}

export interface AreaSelection {
  x1: number
  y1: number
  x2: number
  y2: number
}

export function areaFromAnchor(x: number, y: number, size: number): AreaSelection {
  const x1 = Math.max(0, Math.min(BOARD_SIZE - size, x))
  const y1 = Math.max(0, Math.min(BOARD_SIZE - size, y))
  return { x1, y1, x2: x1 + size - 1, y2: y1 + size - 1 }
}

export function areaCells(area: AreaSelection | null): string[] {
  if (!area) return []
  const cells: string[] = []
  for (let y = area.y1; y <= area.y2; y += 1) {
    for (let x = area.x1; x <= area.x2; x += 1) cells.push(cellKey(x, y))
  }
  return cells
}

export function lineFromCell(x: number, y: number, direction: 'row' | 'col'): AreaSelection {
  return direction === 'row'
    ? { x1: 0, y1: y, x2: BOARD_SIZE - 1, y2: y }
    : { x1: x, y1: 0, x2: x, y2: BOARD_SIZE - 1 }
}

/** 硫磺火焰：六个不同的四邻接连通格，可以转弯。返回范围仅供预览。 */
export function continuousLine(cells: Point[]): AreaSelection | null {
  if (!Array.isArray(cells) || cells.length !== BOARD_SIZE) return null
  if (cells.some(p => !Number.isInteger(p.x) || !Number.isInteger(p.y) || p.x < 0 || p.y < 0 || p.x >= BOARD_SIZE || p.y >= BOARD_SIZE)) return null
  const remaining = new Set(cells.map(p => cellKey(p.x, p.y)))
  if (remaining.size !== BOARD_SIZE) return null
  const stack = [cells[0]]
  remaining.delete(cellKey(cells[0].x, cells[0].y))
  while (stack.length) {
    const p = stack.pop()!
    for (const [x, y] of [[p.x - 1, p.y], [p.x + 1, p.y], [p.x, p.y - 1], [p.x, p.y + 1]]) {
      if (remaining.delete(cellKey(x, y))) stack.push({ x, y })
    }
  }
  if (remaining.size) return null
  return { x1: Math.min(...cells.map(p => p.x)), y1: Math.min(...cells.map(p => p.y)), x2: Math.max(...cells.map(p => p.x)), y2: Math.max(...cells.map(p => p.y)) }
}

export function turnText(state: GameState, selfName: string, opponentName: string): string {
  if (isMyTurn(state)) return `轮到你 · ${selfName}`
  if (state.current_attacker) return `等待 ${opponentName} 行动`
  return '等待对手就位'
}

export function remainingShipText(state: GameState): string {
  return `${state.remaining_ships} / ${state.opponent_remaining_ships}`
}

export function speedGems(speed: number): string {
  const count = Math.min(Math.max(speed, 0), 3)
  return '●'.repeat(count)
}

export interface EffectMonitorCard { name: string; speed?: number | null; type?: string | null; description?: string }

export function effectBadgeList(source: unknown): Array<{
  key: string
  label: string
  description: string
  expires: string
  card?: EffectMonitorCard | null
}> {
  if (!Array.isArray(source)) return []
  return source
    .map((item) => {
      if (!item || typeof item !== 'object') return null
      const record = item as Record<string, unknown>
      const key = String(record.key ?? record.name ?? '')
      if (!key) return null
      const card = record.card && typeof record.card === 'object' ? (record.card as Record<string, unknown>) : null
      return {
        key,
        label: String(record.label ?? record.name ?? key),
        description: String(record.description ?? ''),
        expires: String(record.expires ?? ''),
        card: card
          ? ({
              name: String(card.name ?? record.name ?? key),
              speed: card.speed === null || card.speed === undefined ? null : Number(card.speed),
              type: card.type === null || card.type === undefined ? null : String(card.type),
              description: String(card.description ?? record.description ?? ''),
            } satisfies EffectMonitorCard)
          : null,
      }
    })
    .filter((item): item is NonNullable<typeof item> => item !== null)
}

export interface PublicChainPreview {
  card: string
  board: 'self' | 'opponent'
  shape: 'area' | 'line' | 'cells' | 'single'
  cells: Point[]
}

export interface ChainItemView {
  name: string
  caster: string
  negated: boolean
  negatedBy: string
  preview: PublicChainPreview | null
}

export function chainItems(source: unknown): ChainItemView[] {
  const record = source && typeof source === 'object' ? (source as Record<string, unknown>) : {}
  const list = Array.isArray(record.chain) ? record.chain : []
  return list
    .map((item) => {
      if (!item || typeof item !== 'object') return null
      const entry = item as Record<string, unknown>
      const card = entry.card && typeof entry.card === 'object' ? (entry.card as Record<string, unknown>) : null
      const name = card ? String(card.name ?? '') : typeof entry.card === 'string' ? entry.card : ''
      const rawPreview = entry.preview && typeof entry.preview === 'object' ? entry.preview as Record<string, unknown> : null
      const rawCells = rawPreview && Array.isArray(rawPreview.cells) ? rawPreview.cells : []
      const previewCells = rawCells
        .map((cell) => {
          if (!cell || typeof cell !== 'object') return null
          const point = cell as Record<string, unknown>
          const x = Number(point.x)
          const y = Number(point.y)
          return Number.isInteger(x) && Number.isInteger(y) && x >= 0 && x < 6 && y >= 0 && y < 6 ? { x, y } : null
        })
        .filter((cell): cell is Point => cell !== null)
      const preview = rawPreview
        && (rawPreview.board === 'self' || rawPreview.board === 'opponent')
        && (rawPreview.shape === 'area' || rawPreview.shape === 'line' || rawPreview.shape === 'cells' || rawPreview.shape === 'single')
        && previewCells.length
        ? {
            card: String(rawPreview.card ?? name),
            board: rawPreview.board,
            shape: rawPreview.shape,
            cells: previewCells,
          } satisfies PublicChainPreview
        : null
      return {
        name,
        caster: String(entry.player_id ?? entry.seat ?? ''),
        negated: Boolean(entry.negated),
        negatedBy: entry.negated_by ? String(entry.negated_by) : '',
        preview,
      }
    })
    .filter((item): item is ChainItemView => !!item && !!item.name)
}
