<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import BoardPanel from './BoardPanel.vue'
import { acquireBattleChannel, getBattleSocket, sendBattleEvent, syncHand } from '../../realtime/battle'
import { cardArtUrl } from '../../cards/cardArt'
import { useGameStore } from '../../stores/game'
import { useMatchStore } from '../../stores/match'
import { useResultStore } from '../../stores/result'
import { useUiStore } from '../../stores/ui'
import { turnClockView } from './turnClock'
import {
  areaFromAnchor,
  areaCells,
  buildOpponentBoard,
  buildSelfBoard,
  cardDisabledReason,
  cardSpeed,
  cardTestId,
  cardIdentity,
  chainCardTestId,
  chainItems,
  continuousLine,
  effectBadgeList,
  frozenAreaCells,
  hitCount,
  isMyTurn,
  lineFromCell,
  modeLabel,
  opponentId,
  phaseLabel,
  playRefusalReason,
  remainingShipText,
  speedGems,
  targetDescriptor,
  turnText,
  type CardLike,
  type Point,
  type TargetDescriptor,
  type PendingPickLike,
  type PlayabilityContext,
  type FrozenAreaLike,
} from './view'

/**
 * Ticket #47: the game HUD.
 *
 * One main board (the opponent sea — the only place a turn is spent), a status
 * band carrying the server-owned turn clock, a readable hand with an explicit
 * detail / use / cancel loop, one target banner, one chain overlay, and
 * drawers for the log, chat and piles. Refusals go through the global notice
 * queue so every click says why in player language.
 *
 * The screen still formats server values only: it never recomputes attack
 * counts, ship survival or card legality.
 */
const router = useRouter()
const game = useGameStore()
const match = useMatchStore()
const result = useResultStore()
const ui = useUiStore()

let releaseChannel: (() => void) | null = null
let ticker: number | null = null
const now = ref(Date.now())
const liveText = ref('')
/** Last refusal, rendered in a stable receipt element for 6s (#50 hook). */
const receiptText = ref('')
let receiptTimer: number | null = null

const state = computed(() => game.state)
const hand = computed<CardLike[]>(() =>
  Array.isArray(state.value.hand) ? (state.value.hand as unknown as CardLike[]) : [],
)
const selfName = computed(() => state.value.player_name || '你')
const opponentName = computed(() => state.value.opponent_name || '对手')
const myTurn = computed(() => isMyTurn(state.value))
const phaseText = computed(() => phaseLabel(state.value.current_phase))
const modeText = computed(() => modeLabel(Boolean(state.value.ranked), state.value.mode))
const fieldMagic = computed(() => state.value.field_magic || '无')
const hasRoom = computed(() => Boolean(state.value.room_id))
const turnLabel = computed(() => turnText(state.value, selfName.value, opponentName.value))

// ---- status band -----------------------------------------------------------
const clock = computed(() =>
  turnClockView(state.value.turn_deadline, state.value.turn_timeout_seconds, now.value),
)
const turnOrderText = computed(() => {
  const order = Array.isArray(state.value.attack_order) ? state.value.attack_order : []
  if (!order.length) return ''
  if (order[0] === state.value.player_id) return '你先手'
  return '对手先手'
})
const connectionText = computed(() => (ui.connection === 'online' ? '已连接' : '重连中…'))
const timeoutNote = computed(() => match.timeoutNote)

// ---- hand selection --------------------------------------------------------
const selectedCardIndex = ref(-1)
const selectedCardKey = ref('')
const detailOpen = computed(() => selectedCardIndex.value >= 0)

const shieldPicks = ref<number[]>([])
const shieldError = ref('')
const shieldOpen = computed(() => Boolean(match.shieldChoice))
const shieldSelectedKeys = computed<string[]>(() => {
  const ships = Array.isArray(state.value.ships) ? state.value.ships : []
  const keys: string[] = []
  for (const index of shieldPicks.value) {
    const ship = ships[index]
    for (const position of Array.isArray(ship?.positions) ? ship.positions : []) {
      keys.push(position.x + '-' + position.y)
    }
  }
  return keys
})

interface SelectionState {
  card: CardLike
  index: number
  descriptor: TargetDescriptor
  board: 'self' | 'opponent' | null
  anchor: Point | null
  lineDir: 'row' | 'col'
  picks: Point[]
  effectChoice: number | null
  error: string
}

const selection = ref<SelectionState | null>(null)
const chainBusy = computed(
  () => Boolean(state.value.chain_waiting) || chainItems(state.value.chain).length > 0,
)
const pendingPick = computed<PendingPickLike | null>(() => {
  if (match.pickRequest) {
    return { reason: match.pickRequest.reason, message: match.pickRequest.message }
  }
  const fallback = state.value.pending_sacrifice
  if (fallback && typeof fallback === 'object') {
    const record = fallback as Record<string, unknown>
    return { reason: String(record.reason ?? ''), message: String(record.message ?? '') }
  }
  return null
})
const playCtx = computed<PlayabilityContext>(() => ({
  lastAttack: match.lastAttack,
  pendingPick: pendingPick.value,
  chainBusy: chainBusy.value,
}))

const selfCells = computed(() =>
  buildSelfBoard(state.value, { shieldBroken: match.shieldBrokenSelf }),
)
const opponentCells = computed(() =>
  buildOpponentBoard(state.value, {
    revealed: match.revealed,
    shieldBroken: match.shieldBrokenOpponent,
  }),
)

/**
 * 紧凑档一次只显示一块棋盘：选目标时必须把可见棋盘切到目标那一侧，
 * 否则用户看得到格子但点的是另一块（原 main 双棋盘不存在这个问题）。
 */
const previewKeys = computed<string[]>(() => {
  const sel = selection.value
  if (!sel || !sel.anchor) return []
  const descriptor = sel.descriptor
  if (descriptor.kind === 'area' || descriptor.kind === 'shenwei') {
    return areaCells(areaFromAnchor(sel.anchor.x, sel.anchor.y, descriptor.size ?? 3))
  }
  if (descriptor.kind === 'line') {
    return areaCells(lineFromCell(sel.anchor.x, sel.anchor.y, sel.lineDir))
  }
  return []
})

/** Every cell the open target banner would accept (#47 legal-range highlight). */
const legalKeys = computed<string[]>(() => {
  const sel = selection.value
  if (!sel) return []
  const kind = sel.descriptor.kind
  const mine = selfCells.value
  const theirs = opponentCells.value
  if (kind === 'shenwei') return [...mine, ...theirs].map((cell) => cell.key)
  if (kind === 'single' || kind === 'own_ships') {
    return mine.filter((cell) => cell.ship && !cell.sunk).map((cell) => cell.key)
  }
  const board = sel.descriptor.board === 'self' ? mine : theirs
  return board.filter((cell) => !cell.hole).map((cell) => cell.key)
})

const selectedKeys = computed<string[]>(() =>
  selection.value ? selection.value.picks.map((pick) => pick.x + '-' + pick.y) : [],
)

const canConfirm = computed(() => {
  const sel = selection.value
  if (!sel) return false
  if (sel.error) return false
  const kind = sel.descriptor.kind
  if (kind === 'area' || kind === 'line') return sel.anchor !== null
  if (kind === 'continuous') return continuousLine(sel.picks) !== null
  if (kind === 'single') return sel.picks.length === 1
  if (kind === 'own_ships') return sel.picks.length === 2 && sel.effectChoice !== null
  if (kind === 'shenwei') return sel.board !== null && sel.anchor !== null
  return false
})

const pickCountText = computed(() => {
  const sel = selection.value
  if (!sel) return '尚未选中'
  const kind = sel.descriptor.kind
  if (kind === 'continuous') return String(sel.picks.length) + ' / ' + String(sel.descriptor.length ?? 6)
  if (kind === 'own_ships') return String(sel.picks.length) + ' / ' + String(sel.descriptor.count ?? 2)
  if (kind === 'single') return sel.picks.length ? '已选中 1 格' : '尚未选中'
  if (kind === 'area' || kind === 'line' || kind === 'shenwei') {
    if (!sel.anchor) return '尚未选中'
    if (kind === 'line') {
      return '第 ' + String((sel.lineDir === 'row' ? sel.anchor.y : sel.anchor.x) + 1) + (sel.lineDir === 'row' ? ' 行' : ' 列')
    }
    return '第 ' + String(sel.anchor.x + 1) + '-' + String(sel.anchor.x + (sel.descriptor.size ?? 3)) + ' 列，第 ' + String(sel.anchor.y + 1) + '-' + String(sel.anchor.y + (sel.descriptor.size ?? 3)) + ' 行'
  }
  return '尚未选中'
})

const targetTitle = computed(() => {
  const sel = selection.value
  return sel ? '使用「' + sel.card.name + '」：请选择目标' : ''
})

const targetHint = computed(() => {
  const sel = selection.value
  if (!sel) return ''
  const kind = sel.descriptor.kind
  if (kind === 'area') return '在对手海域点击一个格子，确定 ' + String(sel.descriptor.size ?? 3) + '×' + String(sel.descriptor.size ?? 3) + ' 区域的左上角'
  if (kind === 'line') return '选择行或列，再在对手海域点击一个格子'
  if (kind === 'continuous') return '依次点击 6 个连续格子（正好一整行或一整列）'
  if (kind === 'single') return '在自己海域点击一艘还活着的战舰'
  if (kind === 'own_ships') return '在自己海域选择两艘战舰，然后选择要发出的效果'
  if (kind === 'shenwei') return '先选择作用棋盘，再点击 3×3 区域的左上角'
  return ''
})

const chainList = computed(() => chainItems(state.value.chain))
const selfEffects = computed(() => effectBadgeList(state.value.effect_badges?.self))
const opponentEffects = computed(() => effectBadgeList(state.value.effect_badges?.opponent))
const frozenMine = computed(() =>
  frozenAreaCells(state.value.frozen_area as unknown as FrozenAreaLike | null, state.value.player_id),
)
const frozenTheirs = computed(() =>
  frozenAreaCells(state.value.frozen_area as unknown as FrozenAreaLike | null, opponentId(state.value)),
)

const hits = computed(() => hitCount(Array.isArray(state.value.attacks) ? state.value.attacks : []))
const shots = computed(() => (Array.isArray(state.value.attacks) ? state.value.attacks.length : 0))
const shipsText = computed(() => remainingShipText(state.value))

const chainWindow = computed(() => match.chainWindow)
/** 面板被收起（请求还在，倒计时还在跑） */
const chainCollapsed = computed(() => match.chainWindowCollapsed)
const speed3Hand = computed<CardLike[]>(() => chainWindow.value?.speed3Cards ?? [])
const chainRemaining = computed(() => {
  const window = chainWindow.value
  if (!window) return 0
  return Math.max(0, Math.ceil(window.countdown - (now.value - window.openedAt) / 1000))
})
const chainOrderText = computed(() => '第 ' + String(chainList.value.length) + ' 张')
/** 0..1 remaining share of the response window, for the ring (#52). */
const chainProgress = computed(() => {
  const window = chainWindow.value
  if (!window || !(window.countdown > 0)) return 0
  return Math.max(0, Math.min(1, chainRemaining.value / window.countdown))
})

const logs = computed(() => match.logs.slice().reverse())
const notices = computed(() => match.notices.slice(-4))
const latestLog = computed(() => (match.logs.length ? match.logs[match.logs.length - 1].text : ''))

// 左列日志：main 的日志窗是常驻的，这里取最近十几条，完整历史仍在日志抽屉里。
const gameLogLines = computed(() => match.logs.slice(-14))

const discardCountText = computed(() => (discardCards.value.length ? String(discardCards.value.length) : '—'))
const quickChatMessages = computed(() => match.quickChat.slice(-8).reverse())
const chatMessages = computed(() => match.chat.slice(-30))

// ---- drawers and overlays --------------------------------------------------
const quickChatOpen = ref(false)
const logOpen = ref(false)
const moreOpen = ref(false)
const discardOpen = ref(false)
const zoomOpen = ref(false)
const quickChatCatalog = ref<Array<{ id: string; text: string }>>([])
const chatDraft = ref('')
const chatError = ref('')
const CHAT_MAX_LENGTH = 100
const surrenderArmed = ref(false)
const busy = ref(false)

interface QuickChatItem {
  id: string
  text: string
}

// ---- self minimap, ship slots and piles ------------------------------------
const compact = ref(false)

watch(
  () => {
    const sel = selection.value
    // 「选自己两艘舰」这类没有棋盘开关的目标，棋盘就在自己这边。
    const board = !sel
      ? null
      : sel.descriptor.kind === 'own_ships'
        ? 'self'
        : sel.board ?? sel.descriptor.board ?? 'opponent'
    // compact 也要进依赖：选目标途中把窗口缩成手机尺寸（或手机横竖屏切换）
    // 时必须同步可见海域，否则目标在己方却只显示对方棋盘，格子点不动。
    return { board, compact: compact.value }
  },
  ({ board, compact: isCompact }) => {
    if (!board) return
    zoomOpen.value = isCompact && board === 'self'
  },
)


/**
 * 紧凑档没有常驻右列：连锁响应、卡牌详情、待选请求都必须能弹出成底部面板，
 * 否则手机上连锁/详情不可达（原 main 用 aux-dock + chain-prompt 保证可达）。
 */
const picking = computed(() => !!selection.value || !!match.pickRequest || !!match.shieldChoice)

const railSheet = computed(
  () =>
    compact.value &&
    // 选目标/待选期间绝不能让面板盖住棋盘：棋盘本身就是点击面。
    !picking.value &&
    detailOpen.value,
)
let mq: MediaQueryList | null = null

function syncCompact(): void {
  compact.value = mq ? mq.matches : false
  if (!compact.value) zoomOpen.value = false
}

const opponentHidden = computed(() => compact.value && zoomOpen.value)
const boardMode = computed(() => (compact.value ? 'tabs' : 'dual'))

const shipSlots = computed(() => {
  const ships = Array.isArray(state.value.ships) ? state.value.ships : []
  return ships.slice(0, 6).map((ship, index) => ({
    index,
    alive: ship?.alive !== false,
    frozen: Boolean(ship?.frozen),
    shielded: Boolean(ship?.shield),
  }))
})

const miniMapCells = computed(() => {
  const ships = new Map<string, boolean>()
  for (const ship of Array.isArray(state.value.ships) ? state.value.ships : []) {
    for (const position of Array.isArray(ship?.positions) ? ship.positions : []) {
      ships.set(position.x + '-' + position.y, ship?.alive !== false)
    }
  }
  const shots = new Map<string, boolean>()
  for (const cell of Array.isArray(state.value.opponent_attacks) ? state.value.opponent_attacks : []) {
    if (cell) shots.set(cell.x + '-' + cell.y, Boolean(cell.hit))
  }
  const cells: Array<{ key: string; ship: boolean; hit: boolean; miss: boolean }> = []
  for (let y = 0; y < 6; y += 1) {
    for (let x = 0; x < 6; x += 1) {
      const key = x + '-' + y
      cells.push({ key, ship: ships.get(key) === true, hit: shots.get(key) === true, miss: shots.get(key) === false })
    }
  }
  return cells
})

interface DiscardCard {
  name: string
  speed: number | string
  type: string
}
const discardCards = ref<DiscardCard[]>([])
const discardError = ref('')
const discardLoading = ref(false)

// ---- feedback helpers ------------------------------------------------------
function say(code: string, message: string, next = '', tone: 'info' | 'warning' = 'warning'): void {
  receiptText.value = next ? message + ' ' + next : message
  if (receiptTimer !== null) window.clearTimeout(receiptTimer)
  receiptTimer = window.setTimeout(() => {
    receiptText.value = ''
    receiptTimer = null
  }, 6000)
  ui.notify({ code, message, next, tone, ttl: tone === 'warning' ? 5000 : 3000 })
}

function announce(text: string): void {
  liveText.value = ''
  window.setTimeout(() => {
    liveText.value = text
  }, 30)
}

/** Why a click on the main board cannot fire. Empty string = it can. */
function fireRefusal(): string {
  if (!state.value.player_id) return '对局数据还没到，请稍候。'
  if (state.value.state !== 'attacking') return '对局还没进入战斗。'
  if (state.value.current_phase !== 'battle') return '现在不是战斗阶段，先点主行动进入战斗阶段。'
  if (!myTurn.value) return '还没轮到你，等对手结束这个回合。'
  if (!(state.value.attacks_remaining > 0)) return '本回合没有剩余攻击次数，点主行动进入结束阶段。'
  return ''
}

function refuseFire(reason: string): void {
  const code = !myTurn.value
    ? 'game-not-your-turn'
    : state.value.current_phase !== 'battle'
      ? 'game-wrong-phase'
      : !(state.value.attacks_remaining > 0)
        ? 'game-no-attacks'
        : 'game-cannot-fire'
  say(code, reason, '看状态带里的回合与剩余攻击数。')
}

// ---- the card loop: select -> detail -> use / second click -> target ---------
function clearCardSelection(): void {
  selectedCardIndex.value = -1
  selectedCardKey.value = ''
}

/** The ONE reason function: the card face and the click guard both call it. */
function cardDisabled(card: CardLike): string {
  if (selection.value) return '正在选目标：先完成或取消当前选择'
  return cardDisabledReason(card, state.value, playCtx.value)
}

function cardTestIdFor(card: CardLike, index: number): string {
  return cardTestId(card, index, hand.value)
}

function typeLabel(card: CardLike): string {
  return '速阶 ' + String(card.speed) + ' · ' + String(card.type)
}

function onCardClick(index: number): void {
  const card = hand.value[index]
  if (!card) return
  if (selection.value) {
    say('game-target-open', '先完成或取消当前的目标选择，再打出另一张卡。')
    return
  }
  const key = cardTestId(card, index, hand.value)
  if (selectedCardIndex.value === index && selectedCardKey.value === key) {
    void playCard(index)
    return
  }
  selectedCardIndex.value = index
  selectedCardKey.value = key
  const disabled = cardDisabledReason(card, state.value, playCtx.value)
  if (disabled) {
    say('game-card-disabled', disabled, '点卡片看限制条件，换个阶段或用别的卡。')
  } else {
    // Every click gets a receipt, including a successful selection (spec §5).
    say('game-card-selected', '已选中「' + card.name + '」：再点一次或点「使用此卡」出牌。', '', 'info')
    announce('已选中' + card.name + '。再点一次或点「使用此卡」出牌。')
  }
}

function useSelectedCard(): void {
  const index = selectedCardIndex.value
  if (index < 0) return
  clearCardSelection()
  void playCard(index)
}

function cancelCardSelection(): void {
  if (!detailOpen.value) return
  clearCardSelection()
  ui.notify({ code: 'game-card-deselected', message: '已取消选中的卡', tone: 'info', ttl: 2000 })
}

async function playCard(index: number): Promise<void> {
  const card = hand.value[index]
  if (!card) return
  const refusal = playRefusalReason(card, state.value, playCtx.value)
  if (refusal) {
    say('game-card-refused', refusal, '看卡面上的限制说明。')
    clearCardSelection()
    return
  }
  const descriptor = targetDescriptor(card.name)
  if (!descriptor) {
    await dispatchCard(card, {})
    clearCardSelection()
    return
  }
  selection.value = {
    card,
    index,
    descriptor,
    board: descriptor.board ?? null,
    anchor: null,
    lineDir: 'row',
    picks: [],
    effectChoice: null,
    error: '',
  }
  announce('使用' + card.name + '：请选择目标')
  clearCardSelection()
}

async function dispatchCard(card: CardLike, targets: Record<string, unknown>): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const ack = await sendBattleEvent('use_magic_card', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
      card: { name: card.name, speed: card.speed, type: card.type, description: card.description ?? '' },
      targets,
    })
    selection.value = null
    if (ack.status !== 'success') {
      const message = '使用魔法卡失败：' + (ack.message || '未知错误')
      ui.notifyError('game-card-failed', message)
      return
    }
    ui.notify({ code: 'game-card-used', message: '已使用「' + card.name + '」', tone: 'success' })
    announce('已使用' + card.name)
    if (hand.value.some((item) => cardIdentity(item) === cardIdentity(card))) {
      // Self-healing like the legacy client: the server is authoritative.
      await sendBattleEvent('request_hand_sync', {
        room_id: state.value.room_id,
        player_id: state.value.player_id,
      })
    }
  } catch (error) {
    const message = '使用魔法卡失败：' + String(error)
    ui.notifyError('game-card-failed', message)
  } finally {
    busy.value = false
  }
}

function setSelectionError(message: string): void {
  const sel = selection.value
  if (!sel) return
  sel.error = message
  say('game-target-invalid', message, '按横幅里的提示重新点。')
}

function pickCell(board: 'self' | 'opponent', x: number, y: number): void {
  const sel = selection.value
  if (!sel) return
  const kind = sel.descriptor.kind
  if (kind === 'area' || kind === 'shenwei') {
    if (kind === 'shenwei' && !sel.board) {
      setSelectionError('请先选择目标棋盘（自己或对方）')
      return
    }
    const targetBoard = kind === 'shenwei' ? sel.board : sel.descriptor.board
    const expected = targetBoard === 'self' ? 'self' : 'opponent'
    if (board !== expected) {
      setSelectionError(expected === 'self' ? '请在自己海域选择区域' : '请在对手海域选择区域')
      return
    }
    sel.anchor = { x, y }
    sel.error = ''
    return
  }
  if (kind === 'line') {
    if (board !== 'opponent') {
      setSelectionError('请在对手海域选择行列')
      return
    }
    sel.anchor = { x, y }
    sel.error = ''
    return
  }
  if (kind === 'continuous') {
    if (board !== 'opponent') {
      setSelectionError('请在对手海域选择格子')
      return
    }
    const existing = sel.picks.findIndex((cell) => cell.x === x && cell.y === y)
    if (existing >= 0) sel.picks.splice(existing, 1)
    else if (sel.picks.length < (sel.descriptor.length ?? 6)) sel.picks.push({ x, y })
    if (!continuousLine(sel.picks)) sel.error = ''
    return
  }
  if (kind === 'single' || kind === 'own_ships') {
    if (board !== 'self') {
      setSelectionError('请在自己海域选择战舰')
      return
    }
    const cell = selfCells.value.find((item) => item.x === x && item.y === y)
    if (!cell || !cell.ship || cell.sunk) {
      setSelectionError('请选择一艘还活着的战舰所在的格子')
      return
    }
    if (kind === 'single') {
      sel.picks = [{ x, y }]
      sel.error = ''
      return
    }
    const existing = sel.picks.findIndex((item) => item.x === x && item.y === y)
    if (existing >= 0) sel.picks.splice(existing, 1)
    else if (sel.picks.length < (sel.descriptor.count ?? 2)) sel.picks.push({ x, y })
    sel.error = ''
    return
  }
}

function setLineDir(direction: 'row' | 'col'): void {
  const sel = selection.value
  if (!sel) return
  sel.lineDir = direction
  sel.error = ''
}

function setBoardSide(side: 'self' | 'opponent'): void {
  const sel = selection.value
  if (!sel) return
  sel.board = side
  sel.anchor = null
  sel.error = ''
}

function setEffectChoice(choice: number): void {
  const sel = selection.value
  if (!sel) return
  sel.effectChoice = choice
  sel.error = ''
}

function cancelSelection(): void {
  const sel = selection.value
  selection.value = null
  clearCardSelection()
  if (sel) {
    const message = '已取消「' + sel.card.name + '」的目标选择'
    ui.notify({ code: 'game-target-cancelled', message, tone: 'info' })
  }
}

function buildTargets(sel: SelectionState): Record<string, unknown> {
  const descriptor = sel.descriptor
  const kind = descriptor.kind
  if (kind === 'area' && sel.anchor) {
    return { target_area: areaFromAnchor(sel.anchor.x, sel.anchor.y, descriptor.size ?? 3) }
  }
  if (kind === 'line' && sel.anchor) {
    return { target_line: { type: sel.lineDir, index: sel.lineDir === 'row' ? sel.anchor.y : sel.anchor.x } }
  }
  if (kind === 'continuous') return { target_cells: sel.picks }
  if (kind === 'single' && sel.picks.length === 1) {
    const cell = sel.picks[0]
    return { target_area: { x1: cell.x, y1: cell.y, x2: cell.x, y2: cell.y } }
  }
  if (kind === 'own_ships') return { selected_cells: sel.picks, effect_choice: sel.effectChoice }
  if (kind === 'shenwei' && sel.anchor && sel.board) {
    return { board: sel.board, target_area: areaFromAnchor(sel.anchor.x, sel.anchor.y, 3) }
  }
  return {}
}

async function confirmSelection(): Promise<void> {
  const sel = selection.value
  if (!sel) return
  if (!canConfirm.value) {
    // Ticket #53: a native disabled button ate this click silently. The guard
    // now says what is missing instead of doing nothing.
    say('game-target-not-ready', '还不能确认：' + (sel.error || targetHint.value), '按横幅提示先选好目标。')
    return
  }
  await dispatchCard(sel.card, buildTargets(sel))
}

// ---- board clicks ----------------------------------------------------------
async function fire(x: number, y: number): Promise<void> {
  const refusal = fireRefusal()
  if (refusal) {
    refuseFire(refusal)
    return
  }
  const existing = (Array.isArray(state.value.attacks) ? state.value.attacks : []).some(
    (cell) => cell && cell.x === x && cell.y === y,
  )
  if (existing) {
    say('game-cell-already-shot', '这一格已经打过了，换一格试试。', '已经打过的格子不会再消耗攻击次数。')
    return
  }
  try {
    const ack = await sendBattleEvent('attack', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
      x,
      y,
    })
    if (ack.status !== 'success') {
      ui.notifyError('game-attack-failed', ack.message || '')
    }
  } catch (error) {
    const message = '攻击失败：' + String(error)
    ui.notifyError('game-attack-failed', message)
  }
}

function onCell(board: 'self' | 'opponent', x: number, y: number): void {
  if (selection.value) {
    pickCell(board, x, y)
    return
  }
  if (match.shieldChoice) {
    // 双棋盘常驻后点对方海域也会走到这里；护盾只能保护自己的战舰。
    if (board !== 'self') {
      shieldError.value = '请在自己海域点击高亮的战舰格（对方海域不能加盾）'
      return
    }
    toggleShieldShip(x, y)
    return
  }
  if (match.pickRequest) {
    void choosePickCell(board, x, y)
    return
  }
  if (board === 'self') {
    // 桌面双棋盘常驻：点己方海域不再需要放大浮层，只有手机档才切到己方格。
    if (compact.value) openZoom()
    return
  }
  void fire(x, y)
}

// ---- minimap / zoom --------------------------------------------------------
function openZoom(): void {
  zoomOpen.value = true
  announce('已放大我自己的海域')
}

function closeZoom(): void {
  zoomOpen.value = false
}

// ---- one primary action per turn ------------------------------------------
interface PrimaryAction {
  label: string
  event: 'enter_battle_phase' | 'enter_end_phase' | 'end_turn'
  enabled: boolean
  reason: string
}

const primaryAction = computed<PrimaryAction>(() => {
  const phase = state.value.current_phase
  if (phase === 'preparation') {
    return {
      label: '进入战斗阶段',
      event: 'enter_battle_phase',
      enabled: myTurn.value,
      reason: myTurn.value ? '' : '还没轮到你',
    }
  }
  if (phase === 'battle') {
    return {
      label: '进入结束阶段',
      event: 'enter_end_phase',
      enabled: myTurn.value,
      reason: myTurn.value ? '' : '还没轮到你',
    }
  }
  if (phase === 'end') {
    return {
      label: '结束回合',
      event: 'end_turn',
      enabled: myTurn.value,
      reason: myTurn.value ? '' : '还没轮到你',
    }
  }
  return { label: '等待开局', event: 'enter_battle_phase', enabled: false, reason: '对局还没开始' }
})

async function turnAction(event: 'enter_battle_phase' | 'enter_end_phase' | 'end_turn'): Promise<void> {
  try {
    const ack = await sendBattleEvent(event, {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
    })
    if (ack.status !== 'success') {
      ui.notifyError('game-phase-failed', ack.message || '')
    }
  } catch (error) {
    const message = '操作失败：' + String(error)
    ui.notifyError('game-phase-failed', message)
  }
}

function runPrimary(): void {
  const action = primaryAction.value
  if (!action.enabled) {
    say('game-primary-disabled', action.label + '现在还不能点：' + (action.reason || '条件不满足'))
    return
  }
  moreOpen.value = false
  void turnAction(action.event)
}

// ---- surrender: two clicks, consequence written out ------------------------
function armSurrender(): void {
  if (!surrenderArmed.value) {
    surrenderArmed.value = true
    window.setTimeout(() => {
      surrenderArmed.value = false
    }, 5000)
    ui.notify({
      code: 'game-surrender-armed',
      message: '再点一次「确认投降」即判负。',
      next: surrenderConsequence.value,
      tone: 'warning',
      ttl: 6000,
    })
    return
  }
  surrenderArmed.value = false
  void sendSurrender()
}

const surrenderConsequence = computed(() => {
  const ranked = Boolean(state.value.ranked)
  return ranked
    ? '本局立即判负；排位赛会按失败结算并扣段位分。'
    : '本局立即判负；休闲对人机对局不计段位分。'
})

async function sendSurrender(): Promise<void> {
  try {
    const ack = await sendBattleEvent('surrender', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
    })
    if (ack.status !== 'success') {
      ui.notifyError('game-surrender-failed', ack.message || '')
    }
  } catch (error) {
    ui.notifyError('game-surrender-failed', String(error))
  }
}

// ---- shield choice / sacrifice pick (server-driven dialogs) ----------------
function toggleShieldShip(x: number, y: number): void {
  if (!match.shieldChoice) return
  const ships = Array.isArray(state.value.ships) ? state.value.ships : []
  const index = ships.findIndex((ship) => {
    if (!ship || ship.alive === false) return false
    return (Array.isArray(ship.positions) ? ship.positions : []).some(
      (position) => position.x === x && position.y === y,
    )
  })
  if (index < 0) {
    shieldError.value = '请在自己海域选择一艘还活着的战舰'
    return
  }
  const at = shieldPicks.value.indexOf(index)
  if (at >= 0) shieldPicks.value.splice(at, 1)
  else if (shieldPicks.value.length >= 3) {
    shieldError.value = '最多选择 3 艘战舰'
    return
  } else shieldPicks.value.push(index)
  shieldError.value = ''
}

async function confirmShieldChoice(): Promise<void> {
  if (!match.shieldChoice || !shieldPicks.value.length) return
  const picks = shieldPicks.value.slice(0, 3)
  try {
    const ack = await sendBattleEvent('confirm_magic_target', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
      temp_data_id: 'shield_choice',
      target_data: { ship_indices: picks },
    })
    if (ack.status !== 'success') {
      shieldError.value = ack.message || '加盾失败，请重新选择'
      return
    }
    match.clearShieldChoice()
    shieldPicks.value = []
    shieldError.value = ''
  } catch (error) {
    shieldError.value = '加盾失败：' + String(error)
  }
}

async function cancelShieldChoice(): Promise<void> {
  try {
    const ack = await sendBattleEvent('cancel_magic_selection', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
    })
    match.clearShieldChoice()
    shieldPicks.value = []
    shieldError.value = ''
  } catch (error) {
    shieldError.value = '取消失败：' + String(error)
  }
}

async function choosePickCell(board: 'self' | 'opponent', x: number, y: number): Promise<void> {
  const pick = match.pickRequest
  if (!pick || board !== 'self') return
  const offered = pick.ships.some((ship) => ship.positions.some((cell) => cell.x === x && cell.y === y))
  if (!offered) {
    say('game-pick-invalid', '请选择面板中列出的战舰格子')
    return
  }
  const ack = await sendBattleEvent('confirm_sacrifice', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
    position: { x, y },
  })
  if (ack.status === 'success') {
    match.clearPickRequest()
  } else {
  }
}

// ---- chain -----------------------------------------------------------------
async function respondChain(card: CardLike): Promise<void> {
  const ack = await sendBattleEvent('chain_response', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
    chain: true,
    card: { name: card.name, speed: card.speed, type: card.type, description: card.description ?? '' },
    targets: [],
  })
  match.closeChainWindow()
  if (ack.status !== 'success') ui.notifyError('game-chain-failed', ack.message || '')
}

async function passChain(): Promise<void> {
  const ack = await sendBattleEvent('chain_response', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
    chain: false,
  })
  match.closeChainWindow()
  if (ack.status !== 'success') ui.notifyError('game-chain-failed', ack.message || '')
}

// ---- chat / piles ----------------------------------------------------------
async function loadQuickChatCatalog(): Promise<void> {
  try {
    const response = await fetch('/api/quick_chat', {
      headers: { accept: 'application/json' },
      credentials: 'same-origin',
    })
    if (!response.ok) return
    const body = (await response.json()) as { items?: unknown }
    const items = Array.isArray(body.items) ? body.items : []
    quickChatCatalog.value = items
      .map((item) => {
        if (!item || typeof item !== 'object') return null
        const record = item as Record<string, unknown>
        const id = String(record.id ?? '')
        const text = String(record.text ?? '')
        return id && text ? { id, text } : null
      })
      .filter((item): item is QuickChatItem => item !== null)
  } catch {
    // The catalog is optional: a missing one only hides the phrase list.
  }
}

async function sendQuickChat(item: QuickChatItem): Promise<void> {
  const ack = await sendBattleEvent('quick_chat', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
    msg_id: item.id,
  })
  if (ack.status === 'success') quickChatOpen.value = false
  else ui.notifyError('game-chat-failed', ack.message || '')
}

async function sendChat(): Promise<void> {
  const message = chatDraft.value.trim()
  if (!message) {
    chatError.value = '说点什么再发送吧'
    return
  }
  if (Array.from(message).length > CHAT_MAX_LENGTH) {
    chatError.value = '消息太长了，最多 ' + CHAT_MAX_LENGTH + ' 个字'
    return
  }
  try {
    const ack = await sendBattleEvent('chat_message', {
      room_id: state.value.room_id,
      message,
    })
    if (ack?.status === 'success') {
      chatDraft.value = ''
      chatError.value = ''
    } else {
      chatError.value = ack?.message || '消息发送失败，请稍后再试'
    }
  } catch (error) {
    chatError.value = '消息发送失败：' + String(error)
  }
}

async function openDiscard(): Promise<void> {
  discardOpen.value = true
  discardLoading.value = true
  discardError.value = ''
  try {
    const ack = (await sendBattleEvent('get_discard_pile', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
    })) as { status?: string; discard_pile?: unknown }
    const list = Array.isArray(ack?.discard_pile) ? ack.discard_pile : []
    discardCards.value = list.map((item) => {
      const record = (item && typeof item === 'object' ? item : {}) as Record<string, unknown>
      return {
        name: String(record.name ?? ''),
        speed: (record.speed as number | string) ?? 0,
        type: String(record.type ?? ''),
      }
    }).filter((card) => Boolean(card.name))
    if (ack?.status !== 'success') discardError.value = '弃牌堆读取失败'
  } catch (error) {
    discardError.value = '弃牌堆读取失败：' + String(error)
  } finally {
    discardLoading.value = false
  }
}

// ---- keyboard: Esc closes the top layer (#47) ------------------------------
function closeTopLayer(): boolean {
  if (zoomOpen.value) {
    closeZoom()
    return true
  }
  if (discardOpen.value) {
    discardOpen.value = false
    return true
  }
  if (quickChatOpen.value) {
    quickChatOpen.value = false
    return true
  }
  if (logOpen.value) {
    logOpen.value = false
    return true
  }
  if (moreOpen.value) {
    moreOpen.value = false
    return true
  }
  if (selection.value) {
    cancelSelection()
    return true
  }
  if (detailOpen.value) {
    cancelCardSelection()
    return true
  }
  return false
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    if (closeTopLayer()) {
      event.preventDefault()
    }
  }
}

// ---- lifecycle -------------------------------------------------------------
let seenGameOverAt = 0
let seenRoom = ''
let navigating = false

function maybeGoToSettlement(): void {
  const record = result.gameOver
  if (!record || navigating) return
  if (record.receivedAt === seenGameOverAt) return
  seenGameOverAt = record.receivedAt
  navigating = true
  void router.push({ name: 'game-over' })
}

watch(
  () => result.gameOver?.receivedAt,
  () => maybeGoToSettlement(),
)

watch(
  () => state.value.room_id,
  (room) => {
    if (!room || room === seenRoom) return
    seenRoom = room
    match.reset()
    selection.value = null
    shieldPicks.value = []
    shieldError.value = ''
    zoomOpen.value = false
    quickChatOpen.value = false
    logOpen.value = false
    moreOpen.value = false
    discardOpen.value = false
    clearCardSelection()
  },
)

watch(
  () => state.value.current_attacker,
  (attacker) => {
    if (!attacker) return
    announce(myTurn.value ? '轮到你行动' : '轮到' + opponentName.value + '行动')
  },
)

watch(
  () => match.lastAttack,
  (attack) => {
    if (!attack) return
    const owner = attack.attacker === state.value.player_id ? '你的炮击' : '对手的炮击'
    const resultText = attack.shipSunk ? '击沉一艘战舰' : attack.hit ? '命中' : '未命中'
    announce(owner + '：第 ' + (attack.x + 1) + ' 列第 ' + (attack.y + 1) + ' 行，' + resultText)
  },
)

watch(
  () => match.chainWindow,
  (window) => {
    if (!window) return
    announce('连锁响应窗口：剩余 ' + String(window.countdown) + ' 秒，可以用速阶 3 的卡响应')
  },
)

onMounted(() => {
  releaseChannel = acquireBattleChannel()
  // Ticket #53: the RPS draw frame was emitted before this channel existed;
  // ask for the authoritative hand once, so the screen never opens with 0 cards.
  void syncHand(getBattleSocket())
  seenGameOverAt = result.gameOver ? result.gameOver.receivedAt : 0
  seenRoom = state.value.room_id
  ticker = window.setInterval(() => {
    now.value = Date.now()
  }, 250)
  void loadQuickChatCatalog()
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    // 手机竖屏与手机横屏都走紧凑档：宽度 <=719 或 高度 <=520（原 main 的横屏单棋盘档）。
    mq = window.matchMedia('(max-width: 719px), (max-height: 520px)')
    mq.addEventListener('change', syncCompact)
    syncCompact()
  }
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  releaseChannel?.()
  releaseChannel = null
  if (ticker !== null) window.clearInterval(ticker)
  ticker = null
  if (mq) mq.removeEventListener('change', syncCompact)
  mq = null
  window.removeEventListener('keydown', onKeydown)
})

function backToLobby(): void {
  void router.push({ name: 'lobby' })
}
</script>
<template>
  <section
    class="screen game"
    data-screen="game"
    data-testid="screen-game"
    :data-board-mode="boardMode"
    :class="{ 'is-picking': picking }"
    aria-labelledby="screen-game-title"
  >
    <h1 id="screen-game-title" class="visually-hidden">对局</h1>

    <p class="visually-hidden" role="status" aria-live="polite" aria-atomic="true" data-testid="game-live">{{ liveText }}</p>

    <p v-if="timeoutNote" class="game-banner game-banner--warning" data-testid="game-timeout-note">
      {{ timeoutNote }}
    </p>
    <p v-if="!hasRoom" class="game-empty" data-testid="game-empty">
      还没有收到对局数据。进对局时会自动显示双方海域、手牌与本回合状态；刷新后请从大厅或布船重新进入。
    </p>

    <div class="game-main-container">
      <!-- 左列：对局日志（原 main 的浮动日志窗，常驻在左列；手机上收进日志抽屉） -->
      <aside v-if="!compact" class="log-container" aria-label="游戏日志">
        <header class="log-header">
          <h3>游戏日志</h3>
          <button type="button" class="log-expand" data-testid="game-log-open" @click="logOpen = true">放大</button>
        </header>
        <ol class="log-content" data-testid="game-log-lines">
          <li v-for="(line, index) in gameLogLines" :key="'log-' + index" class="log-line">{{ line.text }}</li>
        </ol>
        <p v-if="!gameLogLines.length" class="log-empty">还没有日志</p>
      </aside>

      <div class="game-content">
        <!-- 顶部状态条：回合 / 阶段 / 攻击 / 计时 / 连接 + 双方名（原 main 的 .turn-indicator + .arena-turn-chips） -->
        <header class="game-hud" data-testid="game-hud">
          <h2 class="hud-round">第<span class="hud-round__num" data-testid="game-round">{{ state.round }}</span>回合</h2>
          <div class="hud-chips">
            <span class="hud-chip" data-testid="game-phase">{{ phaseText }}</span>
            <span class="hud-chip hud-chip--turn" data-testid="game-attacker">{{ turnLabel }}</span>
            <span class="hud-chip" data-testid="game-attacks">攻击 <b>×{{ state.attacks_remaining }}</b></span>
            <span
              v-if="clock.visible"
              class="hud-chip hud-chip--clock"
              :class="{ 'is-warning': clock.warning, 'is-expired': clock.expired }"
              data-testid="game-turn-clock"
              :data-warning="clock.warning ? 'true' : 'false'"
              :data-remaining-ms="clock.remaining * 1000"
              :data-remaining="clock.remaining"
            >回合计时 {{ clock.label }}</span>
            <span v-if="turnOrderText" class="hud-chip hud-chip--muted" data-testid="game-turn-order">{{ turnOrderText }}</span>
            <span class="hud-chip hud-chip--muted" data-testid="game-mode">{{ modeText }}</span>
            <span
              class="hud-chip"
              :class="ui.connection === 'online' ? 'is-online' : 'is-offline'"
              data-testid="game-connection"
            >{{ connectionText }}</span>
          </div>
          <div class="hud-players">
            <span class="hud-name" data-testid="game-self-name">{{ selfName }}</span>
            <span class="hud-vs" aria-hidden="true">VS</span>
            <span class="hud-name" data-testid="game-opponent-name">{{ opponentName }}</span>
            <span class="hud-pips" data-testid="game-ships">{{ shipsText }}</span>
          </div>
        </header>

        <!-- 全宽场地魔法条（原 main 的 .field-magic-area） -->
        <div class="field-magic-area">
          <span class="fm-label">当前生效的场地魔法：</span>
          <span class="fm-value" data-testid="game-field-magic">{{ fieldMagic }}</span>
        </div>

        <!-- 长久效果胶囊（极限增援 / 无暇圣心 / 其它效果角标） -->
        <div v-if="selfEffects.length || opponentEffects.length" class="effect-status-bar" data-testid="game-effect-bar">
          <span
            v-for="badge in selfEffects"
            :key="'self-' + badge.key"
            class="status-item"
            :data-testid="'game-effect-self-' + badge.key"
            :title="badge.description + (badge.expires ? '（' + badge.expires + '）' : '')"
          >{{ badge.label }}</span>
          <span
            v-for="badge in opponentEffects"
            :key="'opp-' + badge.key"
            class="status-item status-item--opponent"
            :data-testid="'game-effect-opponent-' + badge.key"
            :title="badge.description + (badge.expires ? '（' + badge.expires + '）' : '')"
          >对方 · {{ badge.label }}</span>
        </div>

        <p v-if="receiptText" class="game-receipt" data-testid="game-receipt" role="status" aria-live="polite">{{ receiptText }}</p>

        <!-- 手机档：单块棋盘 + 海域切换标签（标题与提交的棋盘同源） -->
        <div v-if="compact && !selection" class="board-tabs" role="tablist" aria-label="切换棋盘">
          <button
            type="button"
            class="board-tab"
            role="tab"
            :aria-selected="!zoomOpen"
            data-testid="game-board-tab-opponent"
            @click="closeZoom"
          >对手海域</button>
          <button
            type="button"
            class="board-tab"
            role="tab"
            :aria-selected="zoomOpen"
            data-testid="game-board-tab-self"
            @click="openZoom"
          >你的海域</button>
        </div>

        <!-- 双棋盘：桌面并排常驻；手机档按标签只显示一块 -->
        <div class="boards-container" :data-board-mode="boardMode">
          <div v-show="!compact || zoomOpen" class="board-wrapper">
            <BoardPanel
              board="self"
              board-testid="game-board-self"
              title-testid="game-board-title-self"
              :title="'你的海域 · ' + selfName"
              :subtitle="'存活 ' + state.remaining_ships + ' 艘' + (frozenMine.size ? ' · 你的 3×3 区域被冻结' : '')"
              :cells="selfCells"
              :selected="selectedKeys.concat(shieldSelectedKeys)"
              :legal="legalKeys"
              :hidden="compact && !zoomOpen"
              :picking="!!selection || !!match.pickRequest || shieldOpen"
              @cell="(x: number, y: number) => onCell('self', x, y)"
            />
          </div>
          <div v-show="!opponentHidden" class="board-wrapper">
            <BoardPanel
              board="opponent"
              board-testid="game-board-opponent"
              title-testid="game-board-title-opponent"
              :title="'对手海域 · ' + opponentName"
              :subtitle="'已探明 ' + shots + ' / 36 格 · 命中 ' + hits + (frozenTheirs.size ? ' · 对方 3×3 区域被冻结' : '')"
              :cells="opponentCells"
              :preview="previewKeys"
              :legal="legalKeys"
              :hidden="opponentHidden"
              :picking="!!selection"
              @cell="(x: number, y: number) => onCell('opponent', x, y)"
            />
          </div>
        </div>

        <p class="game-latest" data-testid="game-latest-event">{{ latestLog }}</p>
        <ul v-if="notices.length" class="game-notices" data-testid="game-notices" aria-live="polite">
          <li v-for="notice in notices" :key="notice.id" class="game-notice" :class="'game-notice--' + notice.kind">
            {{ notice.text }}
          </li>
        </ul>
      </div>

      <!-- 右列：连锁结算 / 卡牌详情 / 计数与主行动（原 main 的 .arena-rail + 详情列） -->
      <aside class="arena-rail" :class="{ 'arena-rail--sheet': railSheet }" aria-label="连锁、卡牌与操作">
        <section class="arena-rail-panel" data-testid="game-chain-rail">
          <header class="arena-rail-head">连锁结算</header>
          <ol v-if="chainList.length" class="arena-chain-list" data-testid="game-chain-stack">
            <li
              v-for="(item, index) in chainList"
              :key="'chain-rail-' + index"
              class="arena-chain-item"
              :class="{ 'is-negated': item.negated }"
              :data-testid="'game-chain-item-' + index"
            >
              <b :data-testid="'game-chain-item-' + index + '-name'">{{ item.name }}</b>
              <span class="arena-chain-index">第 {{ index + 1 }} 张</span>
              <span v-if="item.negated" class="arena-chain-negated">已无效</span>
            </li>
          </ol>
          <p v-else class="arena-rail-empty" data-testid="game-chain-empty">暂无连锁</p>
          <button
            v-if="chainWindow && !chainCollapsed"
            type="button"
            class="button button--ghost arena-rail-wide"
            data-testid="game-chain-open"
            @click="match.collapseChainWindow()"
          >收起连锁窗口</button>
        </section>

        <!-- 卡牌详情 / 待使用：选中后原位展开，未选中时给出占位（原 main 的 .magic-preview-container） -->
        <section v-if="detailOpen && hand[selectedCardIndex]" class="game-detail" data-testid="game-card-detail" aria-label="卡牌详情">
          <header class="game-detail__head">
            <div class="game-detail__ident">
              <img
                v-if="cardArtUrl(hand[selectedCardIndex].name)"
                class="game-detail__art"
                :src="cardArtUrl(hand[selectedCardIndex].name) || ''"
                alt=""
                aria-hidden="true"
              />
              <div class="game-detail__ident-text">
                <h2 class="game-detail__name">{{ hand[selectedCardIndex].name }}</h2>
                <p class="game-detail__meta">{{ typeLabel(hand[selectedCardIndex]) }}</p>
              </div>
            </div>
            <button type="button" class="game-close" data-testid="game-card-detail-close" aria-label="关闭卡牌详情" @click="cancelCardSelection">×</button>
          </header>
          <p class="game-detail__desc">{{ hand[selectedCardIndex].description }}</p>
          <p v-if="cardDisabled(hand[selectedCardIndex])" class="game-detail__reason" data-testid="game-card-detail-reason">
            {{ cardDisabled(hand[selectedCardIndex]) }}
          </p>
          <div class="game-detail__actions">
            <button type="button" class="button game-detail__use" data-testid="game-card-detail-use" :disabled="!!cardDisabled(hand[selectedCardIndex])" @click="useSelectedCard">使用此卡</button>
            <button type="button" class="button button--ghost" data-testid="game-card-detail-cancel" @click="cancelCardSelection">取消选择</button>
          </div>
        </section>
        <section v-else class="arena-rail-panel arena-card-placeholder" data-testid="game-card-placeholder">
          <header class="arena-rail-head">卡牌详情</header>
          <p class="arena-rail-empty">点击一张手牌查看效果；再点一次「使用此卡」出牌。</p>
        </section>

        <section class="arena-rail-panel" data-testid="game-counts">
          <div class="arena-counts">
            <div class="fields"><span>手牌</span><b data-testid="game-hand-count">{{ hand.length }}</b></div>
            <div class="fields"><span>弃牌堆</span><b data-testid="game-discard-count">{{ discardCountText }}</b></div>
            <div class="fields"><span>剩余舰</span><b data-testid="game-self-ships">{{ state.remaining_ships }}</b></div>
          </div>
          <button type="button" class="button button--ghost arena-rail-wide" data-testid="game-piles" @click="openDiscard">查看弃牌堆</button>
        </section>

        <div v-if="!compact" class="arena-actions" data-testid="game-actions">
          <p class="arena-turn-hint" data-testid="game-turn-hint">{{ turnLabel }} · {{ phaseText }}</p>
          <button
            type="button"
            class="button game-primary"
            data-primary-action
            data-testid="game-primary"
            :disabled="!primaryAction.enabled"
            @click="runPrimary"
          >{{ primaryAction.label }}</button>
          <button
            type="button"
            class="button button--ghost"
            data-testid="game-more"
            :aria-expanded="moreOpen"
            aria-haspopup="true"
            @click="moreOpen = !moreOpen"
          >更多操作</button>
          <div v-show="moreOpen" class="game-more-menu" data-testid="game-more-menu" role="menu" aria-label="更多操作">
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-enter-battle" :disabled="!myTurn || state.current_phase !== 'preparation'" @click="turnAction('enter_battle_phase')">进入战斗阶段</button>
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-enter-end" :disabled="!myTurn || state.current_phase !== 'battle'" @click="turnAction('enter_end_phase')">进入结束阶段</button>
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-end-turn" :disabled="!myTurn || state.current_phase !== 'end'" @click="turnAction('end_turn')">结束回合</button>
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-log-toggle" @click="logOpen = true">对局日志</button>
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-chat-open" @click="quickChatOpen = true">聊天与快捷语</button>
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-more-piles" @click="openDiscard">弃牌堆</button>
            <button
              type="button"
              class="button button--danger game-more__item"
              role="menuitem"
              data-testid="game-surrender"
              :class="{ 'is-armed': surrenderArmed }"
              @click="armSurrender"
            >{{ surrenderArmed ? '确认投降（判负）' : '投降' }}</button>
            <p class="game-more__note" data-testid="game-surrender-consequence">{{ surrenderConsequence }}</p>
          </div>
          <p v-if="state.priority_waiting" class="game-banner" data-testid="game-priority-waiting">
            等待对方响应「{{ state.priority_waiting.action_text }}」
          </p>
          <p v-if="state.shenji_waiting" class="game-banner" data-testid="game-shenji-waiting">{{ state.shenji_waiting.text }}</p>
          <p v-if="pendingPick && !match.pickRequest" class="game-banner" data-testid="game-pending-pick">
            待处理：{{ pendingPick.message }}
          </p>
        </div>
      </aside>
    </div>

    <!-- 底部手牌条（原 main 的底部手牌） -->
    <button
      v-if="chainWindow && chainCollapsed"
      type="button"
      class="game-chain-reopen"
      data-testid="game-chain-reopen"
      @click="match.expandChainWindow()"
    >
      <span class="game-chain-reopen__dot" aria-hidden="true"></span>
      连锁待响应：{{ chainWindow.card ? chainWindow.card.name : '魔法卡' }} · 剩余 {{ chainRemaining }} 秒 · 打开
    </button>

    <section class="game-hand-wrap" aria-label="手牌">
      <div class="game-hand-head">
        <span class="game-hand-stats" data-testid="game-stats">命中 {{ hits }} · 开火 {{ shots }}</span>
        <span class="game-hand-count" data-testid="game-hand-counter">手牌 {{ hand.length }} 张</span>
      </div>
      <div class="game-hand" data-testid="game-hand">
        <p v-if="!hand.length" class="game-hand-empty" data-testid="game-hand-empty">手上没有魔法卡</p>
        <button
          v-for="(card, index) in hand"
          :key="cardTestIdFor(card, index)"
          type="button"
          class="card"
          :class="{
            'card--selected': selectedCardIndex === index,
            'card--disabled': !!cardDisabled(card),
            'card--art': !!cardArtUrl(card.name),
          }"
          :data-testid="cardTestIdFor(card, index)"
          :data-card-name="card.name"
          :data-card-speed="String(card.speed)"
          :data-type="String(card.type)"
          :aria-pressed="selectedCardIndex === index"
          :aria-label="card.name + '，' + typeLabel(card) + (cardDisabled(card) ? '，' + cardDisabled(card) : '，可以使用')"
          :title="cardDisabled(card) || card.description || card.name"
          @click="onCardClick(index)"
        >
          <img
            v-if="cardArtUrl(card.name)"
            class="card__art"
            :src="cardArtUrl(card.name) || ''"
            alt=""
            aria-hidden="true"
            loading="eager"
            decoding="async"
          />
          <span class="card__body">
            <span class="card__name">{{ card.name }}</span>
            <span class="card__gems" :title="'速阶 ' + String(card.speed)">
              {{ speedGems(cardSpeed(card)) }}<span class="card__speed">{{ card.speed }}</span>
            </span>
            <span class="card__type">{{ typeLabel(card) }}</span>
            <span class="card__desc">{{ card.description }}</span>
            <span v-if="cardDisabled(card)" class="card__reason">{{ cardDisabled(card) }}</span>
          </span>
        </button>
      </div>
    </section>

    <!-- 手机档：底部操作条 + 工具入口 -->
    <div v-if="compact" class="game-compact-bar" data-testid="game-actions">
      <div class="game-compact-top">
        <p class="arena-turn-hint" data-testid="game-turn-hint">{{ turnLabel }} · {{ phaseText }}</p>
        <div class="compact-dock" aria-label="日志与弃牌">
          <button type="button" class="button button--ghost" data-testid="game-compact-log" @click="logOpen = true">日志</button>
          <button type="button" class="button button--ghost" data-testid="game-compact-chat" @click="quickChatOpen = true">聊天</button>
          <button type="button" class="button button--ghost" data-testid="game-compact-piles" @click="openDiscard">弃牌</button>
        </div>
      </div>
      <div class="game-actions__row">
        <button
          type="button"
          class="button game-primary"
          data-primary-action
          data-testid="game-primary"
          :disabled="!primaryAction.enabled"
          @click="runPrimary"
        >{{ primaryAction.label }}</button>
        <button
          type="button"
          class="button button--ghost"
          data-testid="game-more"
          :aria-expanded="moreOpen"
          aria-haspopup="true"
          @click="moreOpen = !moreOpen"
        >更多操作</button>
      </div>
      <div v-show="moreOpen" class="game-more-menu" data-testid="game-more-menu" role="menu" aria-label="更多操作">
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-enter-battle" :disabled="!myTurn || state.current_phase !== 'preparation'" @click="turnAction('enter_battle_phase')">进入战斗阶段</button>
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-enter-end" :disabled="!myTurn || state.current_phase !== 'battle'" @click="turnAction('enter_end_phase')">进入结束阶段</button>
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-end-turn" :disabled="!myTurn || state.current_phase !== 'end'" @click="turnAction('end_turn')">结束回合</button>
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-log-toggle" @click="logOpen = true">对局日志</button>
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-chat-open" @click="quickChatOpen = true">聊天与快捷语</button>
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-more-piles" @click="openDiscard">弃牌堆</button>
        <button
          type="button"
          class="button button--danger game-more__item"
          role="menuitem"
          data-testid="game-surrender"
          :class="{ 'is-armed': surrenderArmed }"
          @click="armSurrender"
        >{{ surrenderArmed ? '确认投降（判负）' : '投降' }}</button>
        <p class="game-more__note" data-testid="game-surrender-consequence">{{ surrenderConsequence }}</p>
      </div>
    </div>

    <section v-if="selection" class="game-target" data-testid="game-target" aria-label="目标选择" role="region">
      <div class="game-target__main">
        <h2 class="game-target__title" data-testid="game-target-title">{{ targetTitle }}</h2>
        <p class="game-target__hint" data-testid="game-target-hint">{{ targetHint }}</p>
        <p class="game-target__selected" data-testid="game-target-selected">已选：{{ pickCountText }}</p>
        <p v-if="selection.error" class="game-target__error" data-testid="game-target-error" role="alert">{{ selection.error }}</p>
      </div>
      <div class="game-target__controls">
        <div v-if="selection.descriptor.kind === 'line'" class="game-target__row">
          <button type="button" class="button game-target__option" :class="{ 'game__action--active': selection.lineDir === 'row' }" data-testid="game-target-line-row" @click="setLineDir('row')">整行</button>
          <button type="button" class="button game-target__option" :class="{ 'game__action--active': selection.lineDir === 'col' }" data-testid="game-target-line-col" @click="setLineDir('col')">整列</button>
        </div>
        <div v-if="selection.descriptor.kind === 'shenwei'" class="game-target__row">
          <button type="button" class="button game-target__option" :class="{ 'game__action--active': selection.board === 'self' }" data-testid="game-target-board-self" @click="setBoardSide('self')">我的棋盘</button>
          <button type="button" class="button game-target__option" :class="{ 'game__action--active': selection.board === 'opponent' }" data-testid="game-target-board-opponent" @click="setBoardSide('opponent')">对手棋盘</button>
        </div>
        <div v-if="selection.descriptor.kind === 'own_ships'" class="game-target__row">
          <button type="button" class="button game-target__option" :class="{ 'game__action--active': selection.effectChoice === 1 }" data-testid="game-target-effect-destroy" @click="setEffectChoice(1)">摧毁对方一艘战舰</button>
          <button type="button" class="button game-target__option" :class="{ 'game__action--active': selection.effectChoice === 2 }" data-testid="game-target-effect-skip" @click="setEffectChoice(2)">跳过对方本回合</button>
        </div>
        <div class="game-target__row">
          <button
            type="button"
            class="button game-target__confirm"
            :class="{ 'is-disabled': !canConfirm }"
            data-testid="game-target-confirm"
            :aria-disabled="!canConfirm"
            @click="confirmSelection"
          >确认使用</button>
          <button type="button" class="button button--ghost" data-testid="game-target-cancel" @click="cancelSelection">取消</button>
        </div>
      </div>
    </section>

    <section
      v-if="chainList.length || (chainWindow && !chainCollapsed)"
      class="game-chain-panel"
      data-testid="game-chain-overlay"
      role="dialog"
      aria-label="连锁"
    >
      <header class="game-chain-panel__head">
        <h2 class="game-chain-panel__title">连锁 {{ chainOrderText }}</h2>
        <button type="button" class="game-close" data-testid="game-chain-close" aria-label="收起连锁" @click="match.collapseChainWindow()">×</button>
      </header>
      <ol v-if="chainList.length" class="game-chain-stack" data-testid="game-chain-stack">
        <li
          v-for="(item, index) in chainList"
          :key="'chain-' + index"
          class="game-chain-item"
          :class="{ 'game-chain-item--negated': item.negated }"
          :data-testid="'game-chain-item-' + index"
        >
          <b :data-testid="'game-chain-item-' + index + '-name'">{{ item.name }}</b>
          <span class="game-chain-index">第 {{ index + 1 }} 张</span>
          <span v-if="item.negated" class="game-chain-negated">已无效</span>
        </li>
      </ol>
      <section v-if="chainWindow" class="game-chain-window" data-testid="game-chain-window">
        <p class="game-chain-window__who">
          出牌者：<b data-testid="game-chain-window-caster">{{ chainWindow.caster === state.player_id ? selfName : opponentName }}</b>
        </p>
        <p class="game-chain-window__card">
          对方使用了
          <b data-testid="game-chain-window-card">{{ chainWindow.card ? chainWindow.card.name : '魔法卡' }}</b>
          ，你可以用速阶 3 的卡连锁它。
        </p>
        <div class="game-chain-clock">
          <div
            class="game-chain-ring"
            :style="{ '--chain-progress': String(chainProgress) }"
            aria-hidden="true"
          ></div>
          <p class="game-chain-countdown" data-testid="game-chain-window-countdown">剩余 {{ chainRemaining }} 秒</p>
        </div>
        <p class="game-chain-window__consequence" data-testid="game-chain-window-consequence">
          不响应：对方的卡直接生效，你放弃这次连锁机会（这一手不会退回来）。
        </p>
        <div class="game-chain-window__actions">
          <button
            v-for="(card, index) in speed3Hand"
            :key="chainCardTestId(card, index, speed3Hand)"
            type="button"
            class="button"
            :data-testid="chainCardTestId(card, index, speed3Hand)"
            @click="respondChain(card)"
          >连锁「{{ card.name }}」</button>
          <button type="button" class="button button--ghost" data-testid="game-chain-pass" @click="passChain">不响应</button>
        </div>
      </section>
    </section>

    <section v-if="shieldOpen" class="game-dialog game-shield-choice" data-testid="game-shield-choice" role="dialog" aria-label="仁王之盾选择">
      <h2 class="game-dialog__title" data-testid="game-shield-choice-title">「仁王之盾」：请选择要保护的战舰</h2>
      <p class="game-dialog__hint" data-testid="game-shield-choice-hint">在自己海域点击高亮的战舰格；再点一次取消选择。</p>
      <p class="game-dialog__hint" data-testid="game-shield-choice-count">已选 {{ shieldPicks.length }} / 3 艘</p>
      <p v-if="shieldError" class="game-dialog__error" data-testid="game-shield-choice-error">{{ shieldError }}</p>
      <p class="game-dialog__hint" data-testid="game-shield-choice-status">服务端没有选择倒计时；点「取消选择」可放弃本次加盾。</p>
      <div class="game-dialog__actions">
        <button type="button" class="button" data-testid="game-shield-choice-confirm" :disabled="shieldPicks.length === 0" @click="confirmShieldChoice">确认加盾</button>
        <button type="button" class="button button--ghost" data-testid="game-shield-choice-cancel" @click="cancelShieldChoice">取消选择</button>
      </div>
    </section>

    <section v-if="match.pickRequest" class="game-dialog game-pick" data-testid="game-ship-pick" role="alertdialog" aria-label="选船">
      <h2 class="game-dialog__title">请选择一艘自己的战舰</h2>
      <p class="game-dialog__hint" data-testid="game-ship-pick-message">{{ match.pickRequest.message }}</p>
      <p class="game-dialog__hint">在自己海域点击高亮的战舰格子。</p>
    </section>


    <section v-if="logOpen" class="game-drawer game-drawer--log" data-testid="game-log-drawer" role="dialog" aria-label="对局日志">
      <header class="game-drawer__head">
        <h2 class="game-drawer__title">对局日志</h2>
        <button type="button" class="game-close" data-testid="game-log-drawer-close" aria-label="关闭日志" @click="logOpen = false">×</button>
      </header>
      <p v-if="!logs.length" class="game-drawer__empty" data-testid="game-log-empty">暂无记录</p>
      <ol v-else class="game-log" data-testid="game-log">
        <li v-for="(entry, index) in logs" :key="'log-' + index" class="game-log__entry" :data-testid="'game-log-entry-' + index">
          {{ entry.text }}
        </li>
      </ol>
    </section>

    <section v-if="quickChatOpen" class="game-drawer game-drawer--chat" data-testid="game-quick-chat" aria-label="局内聊天">
      <header class="game-drawer__head">
        <h2 class="game-drawer__title">局内聊天</h2>
        <button type="button" class="game-close" data-testid="game-quick-chat-close" aria-label="关闭聊天" @click="quickChatOpen = false">×</button>
      </header>
      <section class="game-chat-text" data-testid="game-chat" aria-label="文字聊天">
        <ol class="game-chat-log" data-testid="game-chat-messages" aria-live="polite">
          <li
            v-for="(message, index) in chatMessages"
            :key="'chat-' + index"
            class="game-chat-line"
            :class="{ 'game-chat-line--mine': message.username === selfName }"
            :data-testid="'game-chat-message-' + index"
          >
            <b>{{ message.username }}</b>：{{ message.message }}
          </li>
        </ol>
        <p v-if="!chatMessages.length" class="game-drawer__empty" data-testid="game-chat-empty">还没有人说话</p>
        <p v-if="chatError" class="game-dialog__error" data-testid="game-chat-error">{{ chatError }}</p>
        <div class="game-chat-form">
          <input
            v-model="chatDraft"
            class="game-chat-input"
            type="text"
            :maxlength="CHAT_MAX_LENGTH"
            placeholder="说点什么…"
            aria-label="聊天内容"
            data-testid="game-chat-input"
            @keydown.enter.prevent="sendChat"
          />
          <button type="button" class="button" data-testid="game-chat-send" @click="sendChat">发送</button>
        </div>
      </section>
      <h3 class="game-drawer__subtitle">快捷语</h3>
      <ul class="game-chat-items">
        <li v-for="item in quickChatCatalog" :key="item.id">
          <button type="button" class="button button--ghost game-chat-item" :data-testid="'game-quick-chat-item-' + item.id" @click="sendQuickChat(item)">{{ item.text }}</button>
        </li>
      </ul>
      <p v-if="!quickChatCatalog.length" class="game-drawer__empty">快捷语目录暂不可用</p>
      <ol class="game-chat-log" data-testid="game-quick-chat-messages">
        <li v-for="(message, index) in quickChatMessages" :key="'qc-' + index" class="game-chat-line" :data-testid="'game-quick-chat-message-' + index">
          <b>{{ message.name }}</b>：{{ message.text }}
        </li>
      </ol>
    </section>

    <section v-if="discardOpen" class="game-drawer game-drawer--discard" data-testid="game-discard-drawer" role="dialog" aria-label="弃牌堆">
      <header class="game-drawer__head">
        <h2 class="game-drawer__title">弃牌堆</h2>
        <button type="button" class="game-close" data-testid="game-discard-close" aria-label="关闭弃牌堆" @click="discardOpen = false">×</button>
      </header>
      <p v-if="discardLoading" class="game-drawer__empty">正在读取弃牌堆…</p>
      <p v-if="discardError" class="game-dialog__error" data-testid="game-discard-error">{{ discardError }}</p>
      <p v-if="!discardLoading && !discardCards.length && !discardError" class="game-drawer__empty" data-testid="game-discard-empty">弃牌堆还是空的</p>
      <ul class="game-discard-list" data-testid="game-discard-list">
        <li v-for="(card, index) in discardCards" :key="'discard-' + index" class="game-discard-item" :data-testid="'game-discard-item-' + index">
          {{ card.name }}
        </li>
      </ul>
      <p class="game-drawer__empty">牌堆剩余数量服务端没有下发，这里只显示已经进弃牌堆的卡，不猜数字。</p>
    </section>
  </section>
</template>

<style scoped src="./game-screen.css"></style>
