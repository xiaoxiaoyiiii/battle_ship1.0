<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import BoardPanel from './BoardPanel.vue'
import StatusMonitor from './StatusMonitor.vue'
import EffectMonitor from './EffectMonitor.vue'
import { useAdaptiveGameLayout } from './useAdaptiveGameLayout'
import { useHandFan } from './useHandFan'
import { useFloatingDrag } from './useFloatingDrag'
import PlayerCardDialog from './PlayerCardDialog.vue'
import MagicPlacementPanel from './MagicPlacementPanel.vue'
import MagicChoicePanel from './MagicChoicePanel.vue'
import MagicDiscardPanel from './MagicDiscardPanel.vue'
import DiceRollOverlay from './DiceRollOverlay.vue'
import PhasePriorityPrompt from './PhasePriorityPrompt.vue'
import { CARDS } from '../../cards/cardData'
import { usePlayerCards } from './usePlayerCards'
import { acquireBattleChannel, getBattleSocket, refreshMagicState, sendBattleEvent, syncHand } from '../../realtime/battle'
import { acquireMatchChannel } from '../../realtime/match'
import { cardArtUrl } from '../../cards/cardArt'
import { useAuthStore } from '../../stores/auth'
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
  type PublicChainPreview,
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
const auth = useAuthStore()
const game = useGameStore()
const match = useMatchStore()
const result = useResultStore()
const ui = useUiStore()

let releaseChannel: (() => void) | null = null
let releaseMatchChannel: (() => void) | null = null
let ticker: number | null = null
const now = ref(Date.now())
const liveText = ref('')
/** Last refusal, rendered in a stable receipt element for 6s (#50 hook). */

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

// ---- hand selection --------------------------------------------------------
const selectedCardIndex = ref(-1)
const hoveredCardIndex = ref(-1)
const hoveredCard = computed(() => hoveredCardIndex.value >= 0 ? hand.value[hoveredCardIndex.value] ?? null : null)
let hoverCloseTimer = 0
function showCardPreview(index: number): void { window.clearTimeout(hoverCloseTimer); hoveredCardIndex.value = index }
function hideCardPreview(): void { window.clearTimeout(hoverCloseTimer); hoverCloseTimer = window.setTimeout(() => { hoveredCardIndex.value = -1 }, 90) }
const selectedCardKey = ref('')
const detailOpen = computed(() => selectedCardIndex.value >= 0)

const shieldPicks = ref<number[]>([])
const shieldError = ref('')
const shieldOpen = computed(() => Boolean(match.shieldChoice) && !match.pickRequest)
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
  isChain?: boolean
  priorityToken?: number
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
const priorityError = ref('')
const priorityCollapsed = ref(false)
const priorityRequest = computed(() =>
  state.value.state === 'attacking' && state.value.priority_waiting?.role === 'responder'
    ? state.value.priority_waiting : null,
)
const priorityRemaining = computed(() => Math.max(0, Math.ceil((Number(priorityRequest.value?.deadline ?? 0) - now.value) / 1000)))
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
  buildSelfBoard(state.value, { shieldBroken: match.shieldBrokenSelf, revived: match.revivedSelf }),
)
const opponentCells = computed(() =>
  buildOpponentBoard(state.value, {
    revealed: match.revealed,
    shieldBroken: match.shieldBrokenOpponent,
    revived: match.revivedOpponent,
  }),
)

/**
 * 紧凑档一次只显示一块棋盘：选目标时必须把可见棋盘切到目标那一侧，
 * 否则用户看得到格子但点的是另一块（原 main 双棋盘不存在这个问题）。
 */
const hoveredTarget = ref<{ x: number; y: number } | null>(null)
function previewTarget(board: 'self' | 'opponent', point: { x: number; y: number } | null) {
  const sel = selection.value
  const expected = sel?.descriptor.kind === 'shenwei' ? sel.board : sel?.descriptor.board ?? 'opponent'
  hoveredTarget.value = sel && board === expected ? point : null
}
watch(() => [selection.value, selection.value?.board], () => { hoveredTarget.value = null })
const previewKeys = computed<string[]>(() => {
  const sel = selection.value
  if (!sel) return []
  const anchor = hoveredTarget.value ?? sel.anchor
  if (!anchor) return []
  const descriptor = sel.descriptor
  if (descriptor.kind === 'area' || descriptor.kind === 'shenwei') {
    return areaCells(areaFromAnchor(anchor.x, anchor.y, descriptor.size ?? 3))
  }
  if (descriptor.kind === 'line') {
    return areaCells(lineFromCell(anchor.x, anchor.y, sel.lineDir))
  }
  return []
})

/** Every cell the open target banner would accept (#47 legal-range highlight). */
const legalKeys = computed<string[]>(() => {
  const sel = selection.value
  if (!sel) {
    return match.pickRequest || shieldOpen.value
      ? selfCells.value.filter(cell => cell.ship && !cell.sunk).map(cell => cell.key)
      : []
  }
  const kind = sel.descriptor.kind
  const mine = selfCells.value
  const theirs = opponentCells.value
  if (kind === 'own_sunken') return mine.filter(cell => cell.sunk || (!cell.ship && cell.hit)).map(cell => cell.key)
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
  if (kind === 'own_sunken') return sel.picks.length >= 1 && sel.picks.length <= (sel.descriptor.count ?? 2)
  if (kind === 'shenwei') return sel.board !== null && sel.anchor !== null
  return false
})

const pickCountText = computed(() => {
  const sel = selection.value
  if (!sel) return '尚未选中'
  const kind = sel.descriptor.kind
  if (kind === 'continuous') return String(sel.picks.length) + ' / ' + String(sel.descriptor.length ?? 6)
  if (kind === 'own_ships' || kind === 'own_sunken') return String(sel.picks.length) + ' / ' + String(sel.descriptor.count ?? 2)
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
  if (kind === 'continuous') return '选择 6 个四邻接连通格，可以转弯；再次点击可撤销'
  if (kind === 'single') return '在自己海域点击一艘还活着的战舰'
  if (kind === 'own_ships') return '在自己海域选择两艘战舰，然后选择要发出的效果'
  if (kind === 'own_sunken') return '在自己海域选择一艘或两艘沉船原地复活；再次点击可取消选择'
  if (kind === 'shenwei') return '先选择作用棋盘，再点击 3×3 区域的左上角'
  return ''
})

/** A＋D 区域预览：卡牌主题色档位（不引入新视觉体系，只借用既有主题色）。 */
const TARGET_TONES: Record<string, 'freeze' | 'fire' | 'divine' | 'radar'> = {
  '冻结': 'freeze',
  '硫磺火焰': 'fire',
  '轰炸': 'fire',
  '神威！': 'divine',
  '探测雷达': 'radar',
}

const selectionTone = computed(() => {
  const sel = selection.value
  if (!sel) return 'default' as const
  return TARGET_TONES[sel.card.name] ?? ('default' as const)
})

/** 区域类目标画整片轮廓；点船/加盾类保持逐格轻量标记。 */
const selectionKind = computed<'area' | 'line' | 'continuous' | 'ships' | null>(() => {
  const sel = selection.value
  if (!sel) {
    if (match.pickRequest || shieldOpen.value) return 'ships'
    return null
  }
  const kind = sel.descriptor.kind
  if (kind === 'area' || kind === 'line' || kind === 'continuous') return kind
  if (kind === 'shenwei') return 'area'
  return 'ships'
})

/** 角落标记：3×3 / 2×2 / 行 6 格 / 已选 n 格。 */
const selectionBadge = computed(() => {
  const sel = selection.value
  if (!sel || !sel.anchor) return ''
  const kind = sel.descriptor.kind
  if (kind === 'area' || kind === 'shenwei') {
    const size = sel.descriptor.size ?? 3
    return String(size) + '×' + String(size)
  }
  if (kind === 'line') return sel.lineDir === 'row' ? '行 6 格' : '列 6 格'
  if (kind === 'continuous') return String(sel.picks.length) + ' 格'
  return ''
})

const chainList = computed(() => chainItems(state.value.chain))
const fieldEffectCard = computed(() => {
  const stored = state.value.effect_badges?.field
  if (stored && typeof stored === 'object') return stored as unknown as { name: string; speed?: number; type?: string; description?: string }
  const name = fieldMagic.value && fieldMagic.value !== '无' ? fieldMagic.value : ''
  if (!name) return null
  return CARDS.find((card) => card.name === name) ?? { name }
})
const fieldEffectOwner = computed(() => state.value.effect_badges?.field_owner ?? null)
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
const moveOrderLabel = computed(() => {
  const order = Array.isArray(state.value.attack_order) ? state.value.attack_order : []
  if (!state.value.player_id || order.length < 2) return ''
  return order[0] === state.value.player_id ? '先手' : '后手'
})

const chainWindow = computed(() => match.chainWindow)
const remoteTargetPreview = computed<{
  card: string
  board: 'self' | 'opponent'
  shape: PublicChainPreview['shape']
  cells: Point[]
} | null>(() => {
  const chainItem = chainList.value[chainList.value.length - 1]
  const candidate = chainItem?.preview ?? chainWindow.value?.targetPreview ?? null
  if (!candidate) return null
  const caster = chainItem?.caster || chainWindow.value?.caster || ''
  const mine = new Set([state.value.player_id, state.value.player_seat])
  if (!caster || mine.has(caster)) return null

  const card = candidate.card || chainItem?.name || chainWindow.value?.card?.name || ''
  // 轰炸/冻结/硫磺火焰只公开对手（也就是我方）棋盘上的范围；
  // 神威！是唯一例外，选择对方自己的棋盘也公开，便于判断是否失灵。
  if (card === '神威！') {
    return { ...candidate, card, board: candidate.board === 'opponent' ? 'self' : 'opponent' }
  }
  if (!['轰炸', '冻结', '硫磺火焰', '探测雷达'].includes(card) || candidate.board !== 'opponent') return null
  return { ...candidate, card, board: 'self' }
})
const remotePreviewKeys = computed(() => remoteTargetPreview.value?.cells.map((cell) => `${cell.x}-${cell.y}`) ?? [])
const remotePreviewKind = computed<'area' | 'line' | 'continuous' | null>(() => {
  const preview = remoteTargetPreview.value
  if (!preview) return null
  if (preview.shape === 'area') return 'area'
  if (preview.shape === 'line') return 'line'
  if (preview.shape === 'cells' && preview.cells.length > 1) return 'continuous'
  return null
})
const remotePreviewTone = computed<'freeze' | 'fire' | 'divine' | 'radar' | 'default'>(() => {
  const card = remoteTargetPreview.value?.card
  if (card === '冻结') return 'freeze'
  if (card === '轰炸' || card === '硫磺火焰') return 'fire'
  if (card === '神威！') return 'divine'
  if (card === '探测雷达') return 'radar'
  return 'default'
})
const remotePreviewBadge = computed(() => remoteTargetPreview.value ? '对方选择 · ' + remoteTargetPreview.value.card : '')
const boardPreviewKind = computed(() => selectionKind.value ?? remotePreviewKind.value)
const boardPreviewTone = computed(() => selection.value ? selectionTone.value : remotePreviewTone.value)
const boardPreviewBadge = computed(() => selection.value ? selectionBadge.value : remotePreviewBadge.value)
const selfBoardPreviewKeys = computed(() => {
  if (selection.value) return selection.value.board === 'self' ? previewKeys.value : []
  return remoteTargetPreview.value?.board === 'self' ? remotePreviewKeys.value : []
})
const opponentBoardPreviewKeys = computed(() => {
  if (selection.value) return selection.value.board === 'self' ? [] : previewKeys.value
  return remoteTargetPreview.value?.board === 'opponent' ? remotePreviewKeys.value : []
})
/** 面板被收起（请求还在，倒计时还在跑） */
const chainCollapsed = computed(() => match.chainWindowCollapsed)
// 只有待响应请求使用弹窗；结算中的卡牌始终只展示在右侧竖栏。
const chainHasContent = computed(() => !!chainWindow.value)
const chainPanelOpen = computed(() => chainHasContent.value && !chainCollapsed.value)
const speed3Hand = computed<CardLike[]>(() => chainWindow.value?.speed3Cards ?? [])
const chainRemaining = computed(() => {
  const window = chainWindow.value
  if (!window) return 0
  return Math.max(0, Math.ceil(window.countdown - (now.value - window.openedAt) / 1000))
})
// 连锁里「看效果」：悬停/键盘聚焦直接显示；触屏没有 hover，第一次点只看、第二次点才打出。
const canHover = typeof window.matchMedia !== 'function' || window.matchMedia('(hover: hover)').matches
const chainInspect = ref<CardLike | null>(null)
const chainPreviewSource = ref('')
const chainTouchArmed = ref('')
function fullCard(card: { name: string; speed?: number | string; type?: string; description?: string } | null | undefined): CardLike | null {
  if (!card) return null
  const known = CARDS.find((item) => item.name === card.name)
  return {
    ...card,
    speed: card.speed === '' || card.speed === undefined ? (known?.speed ?? '') : card.speed,
    type: card.type || known?.type || '',
    description: card.description || known?.description || '',
  }
}
function inspectChain(card: { name: string; speed?: number | string; type?: string; description?: string } | null | undefined, source = ''): void {
  chainInspect.value = fullCard(card ? { speed: '', type: '', ...card } : null)
  chainPreviewSource.value = source
}
function onChainCardClick(card: CardLike): void {
  if (!canHover && chainTouchArmed.value !== card.name) {
    chainTouchArmed.value = card.name
    inspectChain(card)
    return
  }
  void respondChain(card)
}
watch(
  () => chainWindow.value?.openedAt,
  () => {
    chainInspect.value = null
    chainPreviewSource.value = ''
    chainTouchArmed.value = ''
  },
)
const chainOrderText = computed(() => '第 ' + String(chainList.value.length) + ' 张')
/** 0..1 remaining share of the response window, for the ring (#52). */
const chainProgress = computed(() => {
  const window = chainWindow.value
  if (!window || !(window.countdown > 0)) return 0
  return Math.max(0, Math.min(1, chainRemaining.value / window.countdown))
})

const logs = computed(() => match.logs.slice().reverse())

// 左列日志：main 的日志窗是常驻的，这里取最近十几条，完整历史仍在日志抽屉里。
const gameLogLines = computed(() => match.logs.slice(-14))

const discardCountText = computed(() => (discardCards.value.length ? String(discardCards.value.length) : '—'))
const quickChatMessages = computed(() => match.quickChat.slice(-8).reverse())
const chatMessages = computed(() => match.chat.slice(-30))

// ---- drawers and overlays --------------------------------------------------
const quickChatOpen = ref(false)
/** 快捷语目录按需展开（原 main 的 #quick-chat-btn 在输入行里），默认只留消息与输入。 */
const quickPhrasesOpen = ref(false)
/** 宽屏的聊天浮窗默认常驻；用户点 × 收起后由 HUD 的「聊天」重新打开。 */
const chatDismissed = ref(false)
const logOpen = ref(false)
const moreOpen = ref(false)
const discardOpen = ref(false)
const zoomOpen = ref(false)
const quickChatCatalog = ref<Array<{ id: string; text: string }>>([])
const chatDraft = ref('')
const chatError = ref('')
const CHAT_MAX_LENGTH = 100
const surrenderArmed = ref(false)
const surrenderError = ref('')
const busy = ref(false)

interface QuickChatItem {
  id: string
  text: string
}

// ---- self minimap, ship slots and piles ------------------------------------
// 布局判据移植自原 main 的 static/adaptive_layout.js（宽 >=1200 且高 >=700 才算宽屏）。
const layout = useAdaptiveGameLayout()
const compact = layout.compact

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
const boardMode = layout.mode
const tight = layout.tight
const dense = layout.dense
const boardSize = layout.boardSize
const gameEl = ref<HTMLElement | null>(null)
const handWrapEl = ref<HTMLElement | null>(null)
const chatPanelEl = ref<HTMLElement | null>(null)
const chatHeadEl = ref<HTMLElement | null>(null)
// 宽屏保留原 main 的浮动聊天窗（可拖），紧凑档仍用底部抽屉。
// 默认位置对齐原 main：聊天在左上、日志在其下方。
const chatDrag = useFloatingDrag({
  handle: chatHeadEl,
  panel: chatPanelEl,
  initial: { x: 20, y: 96 },
  storageKey: 'in_game_chat_pos',
})

// 宽屏卡牌详情恢复原 main 的可拖动窗；手机仍是底部 sheet，不挂拖动。
const detailPanelEl = ref<HTMLElement | null>(null)
const detailHeadEl = ref<HTMLElement | null>(null)
const detailDrag = useFloatingDrag({
  handle: detailHeadEl,
  panel: detailPanelEl,
  initial: { x: Math.max(0, window.innerWidth - 272), y: 158 },
  minY: 72,
})

// 选舰与加盾共用位置，桌面与触屏都可从标题拖动。
const pickPanelEl = ref<HTMLElement | null>(null)
const pickHeadEl = ref<HTMLElement | null>(null)
const pickDrag = useFloatingDrag({
  handle: pickHeadEl,
  panel: pickPanelEl,
  initial: { x: window.innerWidth * 0.22, y: window.innerHeight * 0.64 },
  minY: 72,
})
const pickPanelStyle = computed(() => ({
  left: pickDrag.state.value.x + 'px',
  top: pickDrag.state.value.y + 'px',
  maxHeight: `calc(100dvh - ${pickDrag.state.value.y + 8}px)`,
}))

const logPanelEl = ref<HTMLElement | null>(null)
const logHeadEl = ref<HTMLElement | null>(null)
const logCollapsed = ref(false)
const logDrag = useFloatingDrag({
  handle: logHeadEl,
  panel: logPanelEl,
  initial: { x: 20, y: 432 },
  storageKey: 'game_log_pos',
})

/** 头像来自 /user_stats 的公开资料；拿不到（游客、人机）就退回名字首字，不编造。 */
const selfInitial = computed(() => (selfName.value || '你').slice(0, 1))
const opponentInitial = computed(() => (opponentName.value || '对').slice(0, 1))
const playerCards = usePlayerCards({
  // 局内昵称可能是大厅里随手填的；公开资料只认登录账号的用户名，游客没有
  selfName: computed(() => auth.user?.username || ''),
  opponentName: computed(() => state.value.opponent_name || ''),
  opponentIsAi: computed(() => Boolean(state.value.is_ai_room)),
  opponentRegistered: computed(() => state.value.opponent_registered === true),
})
const brokenAvatars = ref({ self: '', opponent: '' })
const selfAvatarUrl = computed(() =>
  playerCards.selfAvatar.value && brokenAvatars.value.self !== playerCards.selfAvatar.value ? playerCards.selfAvatar.value : '',
)
const opponentAvatarUrl = computed(() =>
  playerCards.opponentAvatar.value && brokenAvatars.value.opponent !== playerCards.opponentAvatar.value
    ? playerCards.opponentAvatar.value
    : '',
)
const playerCardSide = ref<'self' | 'opponent' | null>(null)
const handFan = useHandFan({
  target: handWrapEl,
  count: computed(() => hand.value.length),
  selectedIndex: selectedCardIndex,
  // 只有宽屏才排扇形；紧凑档由 CSS 的 64×92 小卡接管
  enabled: computed(() => !compact.value),
})

/**
 * 量出「棋盘以外」的垂直占用（HUD、场地条、海域标签、手牌条、主行动条 + 间距），
 * 交给布局组合算棋盘边长。这几块的高度不随棋盘变化，所以不会和棋盘互相追着改。
 */
function measureGameChrome(): void {
  const root = gameEl.value
  if (!root) return
  if (!compact.value || tight.value) {
    layout.setChrome(0)
    return
  }
  const heightOf = (selector: string): number => {
    const node = root.querySelector<HTMLElement>(selector)
    return node ? node.getBoundingClientRect().height : 0
  }
  const tabs = boardMode.value === 'tabs' ? heightOf('.board-tabs') : 0
  const total =
    heightOf('.game-hud') +
    heightOf('.field-magic-area') +
    tabs +
    heightOf('.game-hand-wrap') +
    heightOf('.game-compact-bar')
  // .game 的 gap + 内边距（紧凑档 6px gap / 6-8px padding）
  layout.setChrome(total + 40)
}

function scheduleChromeMeasure(): void {
  if (typeof window === 'undefined') return
  void nextTick(() => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(measureGameChrome)
    })
  })
}

watch([compact, tight, boardMode, () => state.value, () => hand.value.length], scheduleChromeMeasure, {
  flush: 'post',
})
/** 标签档只显示一块棋盘；并排/叠放档两块都常驻。 */
const showSelfBoard = computed(() => boardMode.value !== 'tabs' || zoomOpen.value)
const showOpponentBoard = computed(() => !(boardMode.value === 'tabs' && zoomOpen.value))

// 点船和加盾都在己方海域完成，标签档收到请求时直接展示可操作的棋盘。
watch([() => match.pickRequest, shieldOpen, boardMode], ([pick, shield, mode]) => {
  if (mode === 'tabs' && (pick || shield)) zoomOpen.value = true
}, { immediate: true })

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
// 弃牌堆里的悬停预览复用普通手牌的预览层，点击再打开效果详情。
const discardHover = ref<DiscardCard | null>(null)
const discardDetail = ref<DiscardCard | null>(null)
type PreviewCard = { name: string; speed: number | string; type: string; description?: string }
const previewCard = computed<PreviewCard | null>(() => {
  if (discardDetail.value) return null
  const hovered = discardHover.value
  if (hovered) {
    const known = CARDS.find((item) => item.name === hovered.name)
    return {
      name: hovered.name,
      speed: known?.speed ?? hovered.speed ?? 0,
      type: known?.type ?? hovered.type ?? '普通',
      description: known?.description ?? '',
    }
  }
  const card = hoveredCard.value
  if (!card) return null
  return { name: card.name, speed: card.speed, type: card.type, description: card.description }
})
const discardDetailInfo = computed(() => (discardDetail.value ? CARDS.find((item) => item.name === discardDetail.value?.name) ?? null : null))
function showDiscardPreview(card: DiscardCard): void {
  discardHover.value = card
}
function hideDiscardPreview(): void {
  discardHover.value = null
}
function openDiscardDetail(card: DiscardCard): void {
  discardDetail.value = card
}
function closeDiscardDrawer(): void {
  discardOpen.value = false
  discardHover.value = null
  discardDetail.value = null
}

// ---- feedback helpers ------------------------------------------------------
function say(code: string, message: string, next = '', tone: 'info' | 'warning' = 'warning'): void {
  if (['game-not-your-turn', 'game-wrong-phase', 'game-no-attacks', 'game-cannot-fire', 'game-primary-disabled', 'game-card-refused'].includes(code)) {
    ui.notify({ code, message, next, tone, ttl: 2000 })
  }
}

function announce(text: string): void {
  liveText.value = ''
  window.setTimeout(() => {
    liveText.value = text
  }, 30)
}

/** Why a click on the main board cannot fire. Empty string = it can. */
function fireRefusal(): string {
  if (state.value.priority_waiting) return '阶段转换询问中，请等待响应完成。'
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
  if (state.value.priority_waiting) return '阶段转换询问中，请从询问框选择速阶三或等待对方响应'
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
}

async function playCard(index: number): Promise<void> {
  if (state.value.priority_waiting) return
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

async function dispatchCard(card: CardLike, targets: Record<string, unknown>, isChain = false, priorityToken?: number): Promise<void> {
  if (busy.value) return
  // 服务端可能在本次回执前就交回响应权，只能关闭这次实际回答的窗口。
  const answeredWindow = isChain ? match.chainWindow : null
  busy.value = true
  try {
    const ack = await sendBattleEvent(priorityToken !== undefined ? 'priority_response' : isChain ? 'chain_response' : 'use_magic_card', {
      room_id: state.value.room_id,
      player_id: state.value.player_id,
      card: { name: card.name, speed: card.speed, type: card.type, description: card.description ?? '' },
      targets,
      ...(isChain ? { chain: true } : {}),
      ...(priorityToken !== undefined ? { respond: true, token: priorityToken } : {}),
    })
    if (ack.status !== 'success') {
      const message = '使用魔法卡失败：' + (ack.message || '未知错误')
      if (selection.value) selection.value.error = ack.message || '服务端未接受目标，请调整后重试'
      if (priorityToken !== undefined) priorityError.value = ack.message || '出牌失败，可在剩余时间内重新选择'
      ui.notifyError('game-card-failed', message)
      return
    }
    selection.value = null
    if (priorityToken !== undefined && state.value.priority_waiting?.token === priorityToken) {
      game.applyServerState({ priority_waiting: null })
    }
    if (isChain && match.chainWindow === answeredWindow) match.closeChainWindow()
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
    sel.error = ''
    return
  }
  if (kind === 'single' || kind === 'own_ships' || kind === 'own_sunken') {
    if (board !== 'self') {
      setSelectionError('请在自己海域选择战舰')
      return
    }
    const cell = selfCells.value.find((item) => item.x === x && item.y === y)
    const valid = cell && (kind === 'own_sunken' ? cell.sunk || (!cell.ship && cell.hit) : cell.ship && !cell.sunk)
    if (!valid) {
      setSelectionError(kind === 'own_sunken' ? '请选择自己已经沉没的战舰' : '请选择一艘还活着的战舰所在的格子')
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
  if (sel?.isChain && match.chainWindow) match.expandChainWindow()

}

function buildTargets(sel: SelectionState): Record<string, unknown> {
  const descriptor = sel.descriptor
  const kind = descriptor.kind
  if (kind === 'area' && sel.anchor) {
    return { board: descriptor.board, target_area: areaFromAnchor(sel.anchor.x, sel.anchor.y, descriptor.size ?? 3) }
  }
  if (kind === 'line' && sel.anchor) {
    return { board: 'opponent', target_line: { type: sel.lineDir, index: sel.lineDir === 'row' ? sel.anchor.y : sel.anchor.x } }
  }
  if (kind === 'continuous') return { board: 'opponent', target_cells: sel.picks }
  if (kind === 'single' && sel.picks.length === 1) {
    const cell = sel.picks[0]
    return { board: 'self', target_area: { x1: cell.x, y1: cell.y, x2: cell.x, y2: cell.y } }
  }
  if (kind === 'own_ships') return { board: 'self', selected_cells: sel.picks, effect_choice: sel.effectChoice }
  if (kind === 'own_sunken') return { board: 'self', selected_cells: sel.picks }
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
  await dispatchCard(sel.card, buildTargets(sel), sel.isChain, sel.priorityToken)
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
  if (shieldOpen.value) {
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
    // 标签档只显示一块棋盘：点己方格先切到己方棋盘；并排/叠放档两块都在，直接选。
    if (boardMode.value === 'tabs') openZoom()
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
  if (state.value.priority_waiting) return { label:'等待阶段响应', event:'enter_battle_phase', enabled:false, reason:'对方正在决定是否响应阶段转换' }
  if (state.value.interaction_waiting) return { label:'等待完成魔法效果', event:'enter_battle_phase', enabled:false, reason:state.value.interaction_waiting }
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
  if (state.value.priority_waiting) return
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
  surrenderError.value = ''
  if (!surrenderArmed.value) {
    surrenderArmed.value = true
    window.setTimeout(() => {
      surrenderArmed.value = false
    }, 5000)
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
    if (ack.status !== 'success') surrenderError.value = ack.message || '投降请求未被接受，请重试。'
  } catch {
    surrenderError.value = '连接不稳定，投降未确认，请重试。'
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
  const request = match.shieldChoice
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
    if (match.shieldChoice === request) match.clearShieldChoice()
    shieldPicks.value = []
    shieldError.value = ''
    await refreshMagicState()
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
    if (ack.status !== 'success') { shieldError.value = ack.message || '当前不能取消，请先处理待选效果'; return }
    match.clearShieldChoice()
    shieldPicks.value = []
    shieldError.value = ''
    await refreshMagicState()
  } catch (error) {
    shieldError.value = '取消失败：' + String(error)
  }
}

const pickSubmitting = ref(false)
async function choosePickCell(board: 'self' | 'opponent', x: number, y: number): Promise<void> {
  const pick = match.pickRequest
  if (!pick || board !== 'self' || pickSubmitting.value) return
  const offered = pick.ships.some((ship) => ship.positions.some((cell) => cell.x === x && cell.y === y))
  if (!offered) {
    say('game-pick-invalid', '请选择面板中列出的战舰格子')
    return
  }
  pickSubmitting.value = true
  try {
  const ack = await sendBattleEvent('confirm_sacrifice', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
    position: { x, y },
  })
  if (ack.status === 'success') {
    // 下一项可能先于旧确认的回执到达，不可把新请求一并清掉。
    if (match.pickRequest === pick) match.clearPickRequest()
  } else {
    say('game-pick-rejected', ack.message || '选舰未被接受，请重试')
  }
  } catch { say('game-pick-connection', '连接不稳定，选舰请求仍保留，请重试') }
  finally { pickSubmitting.value = false }
}

// ---- chain -----------------------------------------------------------------
async function respondPriority(card: CardLike): Promise<void> {
  const request = priorityRequest.value
  if (!request || busy.value || priorityRemaining.value <= 0) return
  priorityError.value = ''
  clearCardSelection()
  const token = Number(request.token)
  const descriptor = targetDescriptor(card.name)
  if (descriptor) {
    selection.value = { priorityToken: token, card, index: hand.value.findIndex(c => c.name === card.name), descriptor, board: descriptor.board ?? null, anchor: null, lineDir: 'row', picks: [], effectChoice: null, error: '' }
    return
  }
  await dispatchCard(card, {}, false, token)
}

async function passPriority(): Promise<void> {
  const request = priorityRequest.value
  if (!request || busy.value) return
  busy.value = true
  try {
    const ack = await sendBattleEvent('priority_response', {
      room_id: state.value.room_id, player_id: state.value.player_id,
      token: request.token, respond: false,
    })
    if (ack.status === 'success' && state.value.priority_waiting?.token === request.token) {
      game.applyServerState({ priority_waiting: null })
    } else if (ack.status !== 'success') priorityError.value = ack.message || '响应失败，请重试'
  } catch { priorityError.value = '连接不稳定，请重试；超时将自动放行' }
  finally { busy.value = false }
}

watch(() => state.value.priority_waiting?.token, (token) => {
  priorityCollapsed.value = false
  priorityError.value = ''
  if (selection.value?.priorityToken !== undefined && selection.value.priorityToken !== token) selection.value = null
})
watch([priorityRequest, () => ui.phasePrompts], ([request, enabled]) => {
  if (request && !enabled) void passPriority()
}, { immediate: true })

async function respondChain(card: CardLike): Promise<void> {
  const descriptor = targetDescriptor(card.name)
  if (descriptor) {
    selection.value = { isChain:true, card, index:hand.value.findIndex(c => c.name === card.name), descriptor, board:descriptor.board ?? null, anchor:null, lineDir:'row', picks:[], effectChoice:null, error:'' }
    match.collapseChainWindow()
    return
  }
  await dispatchCard(card, {}, true)
}

async function passChain(): Promise<void> {
  if (busy.value) return
  const answeredWindow = match.chainWindow
  busy.value = true
  try {
  const ack = await sendBattleEvent('chain_response', {
    room_id: state.value.room_id,
    player_id: state.value.player_id,
    chain: false,
  })
  if (ack.status === 'success') {
    if (match.chainWindow === answeredWindow) match.closeChainWindow()
  } else ui.notifyError('game-chain-failed', ack.message || '')
  } catch (error) {
    ui.notifyError('game-chain-failed', '连锁响应发送失败：' + String(error))
  } finally { busy.value = false }
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
  if (ack.status === 'success') {
    quickChatOpen.value = false
    quickPhrasesOpen.value = false
  } else ui.notifyError('game-chat-failed', ack.message || '')
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
  if (playerCardSide.value) {
    playerCardSide.value = null
    return true
  }
  if (discardOpen.value) {
    discardOpen.value = false
    return true
  }
  if (quickPhrasesOpen.value) {
    quickPhrasesOpen.value = false
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

// 后手结束后服务端进入新一轮猜拳；旧结束阶段视图必须随状态离开。
watch(
  () => [state.value.state, state.value.needs_reset],
  ([next, needsReset]) => {
    if (next === 'rock_paper_scissors') void router.replace({ name: 'rps' })
    if (next === 'placing_ships' && needsReset) void router.replace({ name: 'placement' })
  },
  { immediate: true },
)

watch(() => [state.value.pending_sacrifice, state.value.pending_sacrifice_ships], () => {
  const pick = state.value.pending_sacrifice
  if (pick && pick.reason !== 'shield_choice') match.setPickRequest({ ...pick, ships: state.value.pending_sacrifice_ships })
  else match.clearPickRequest()
}, { deep: true, immediate: true })
watch(() => state.value.magic_temp, (temp) => {
  if (temp?.type === 'shield_choice') match.openShieldChoice({ caster: state.value.player_id })
  else match.clearShieldChoice()
}, { immediate: true })

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
    // 对局数据由 game store 在接收新房间首帧时清空。
    selection.value = null
    shieldPicks.value = []
    shieldError.value = ''
    zoomOpen.value = false
    quickChatOpen.value = false
    quickPhrasesOpen.value = false
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
    if (!window) { if (selection.value?.isChain) selection.value = null; return }
    announce('连锁响应窗口：剩余 ' + String(window.countdown) + ' 秒，可以用速阶 3 的卡响应')
  },
)

onMounted(() => {
  releaseMatchChannel = acquireMatchChannel()
  releaseChannel = acquireBattleChannel()
  // Ticket #53: the RPS draw frame was emitted before this channel existed;
  // ask for the authoritative hand once, so the screen never opens with 0 cards.
  void syncHand(getBattleSocket())
  void refreshMagicState()
  seenGameOverAt = result.gameOver ? result.gameOver.receivedAt : 0
  seenRoom = state.value.room_id
  ticker = window.setInterval(() => {
    now.value = Date.now()
  }, 250)
  void loadQuickChatCatalog()
  window.addEventListener('keydown', onKeydown)
  scheduleChromeMeasure()
  window.addEventListener('resize', scheduleChromeMeasure)
})

onBeforeUnmount(() => {
  releaseChannel?.()
  releaseChannel = null
  releaseMatchChannel?.()
  releaseMatchChannel = null
  if (ticker !== null) window.clearInterval(ticker)
  ticker = null
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', scheduleChromeMeasure)
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
    :data-layout="compact ? 'compact' : 'wide'"
    :data-boards="boardMode"
    :data-tight="tight ? 'true' : 'false'"
    :data-dense="dense ? 'true' : 'false'"
    :class="{ 'is-picking': picking, 'is-sheet': railSheet }"
    :style="boardSize ? { '--board-size': boardSize + 'px' } : undefined"
    aria-labelledby="screen-game-title"
    ref="gameEl"
  >
    <h1 id="screen-game-title" class="visually-hidden">对局</h1>

    <p class="visually-hidden" role="status" aria-live="polite" aria-atomic="true" data-testid="game-live">{{ liveText }}</p>

    <p v-if="!hasRoom" class="game-empty" data-testid="game-empty">
      还没有收到对局数据。进对局时会自动显示双方海域、手牌与本回合状态；刷新后请从大厅或布船重新进入。
    </p>

    <div class="game-main-container">
      <!-- 左列：对局日志（原 main 的浮动日志窗，常驻在左列；手机上收进日志抽屉） -->
      <!-- 游戏日志：原 main 的浮动日志窗（可拖、可收起），不再占一整根左列 -->
      <aside
        v-if="!compact"
        ref="logPanelEl"
        class="log-container game-float"
        :class="{ 'is-collapsed': logCollapsed }"
        :style="{ left: logDrag.state.value.x + 'px', top: logDrag.state.value.y + 'px' }"
        aria-label="游戏日志"
        data-testid="game-log-panel"
      >
        <header class="log-header game-float__head" ref="logHeadEl" @pointerdown="logDrag.onPointerDown($event)">
          <h3>游戏日志</h3>
          <span class="log-header__actions">
            <button
              type="button"
              class="hud-btn"
              data-testid="game-log-collapse"
              @click="logCollapsed = !logCollapsed"
            >{{ logCollapsed ? '展开' : '收起' }}</button>
            <button type="button" class="log-expand" data-testid="game-log-open" @click="logOpen = true">放大</button>
          </span>
        </header>
        <ol v-show="!logCollapsed" class="log-content" data-testid="game-log-lines">
          <li v-for="(line, index) in gameLogLines" :key="'log-' + index" class="log-line">{{ line.text }}</li>
        </ol>
        <p v-if="!logCollapsed && !gameLogLines.length" class="log-empty">还没有日志</p>
      </aside>

      <div class="game-content">
        <!-- 顶部状态条：回合 / 阶段 / 攻击 / 计时 / 连接 + 双方名（原 main 的 .turn-indicator + .arena-turn-chips） -->
        <header class="game-hud" data-testid="game-hud">
          <h2 class="hud-round">第<span class="hud-round__num" data-testid="game-round">{{ state.round }}</span>回合</h2>
          <div class="hud-chips">
            <div class="hud-primary-chips">
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
            </div>
            <span v-if="moveOrderLabel" class="hud-chip hud-chip--order" data-testid="game-move-order">{{ moveOrderLabel }}</span>
            <span v-if="turnOrderText" class="hud-chip hud-chip--muted" data-testid="game-turn-order">{{ turnOrderText }}</span>
            <span class="hud-chip hud-chip--muted" data-testid="game-mode">{{ modeText }}</span>
            <span
              class="hud-chip"
              :class="ui.connection === 'online' ? 'is-online' : 'is-offline'"
              data-testid="game-connection"
            >{{ connectionText }}</span>
          </div>
          <button
          type="button"
          class="button button--ghost hud-btn"
          data-testid="game-hud-chat"
          @click="chatDismissed = false; quickChatOpen = true"
        >聊天</button>
        <!-- 身份条（原 main 的 .players-info / arena-oppbar-bg）：头像 + 名称 + 剩余舰 + pips -->
        <div class="hud-players">
          <div class="arena-player arena-player--opponent" data-testid="game-opponent-card">
            <button
              type="button"
              class="arena-avatar arena-avatar--opponent arena-avatar--btn"
              data-testid="game-opponent-avatar"
              aria-label="查看对手战绩"
              @click="playerCardSide = 'opponent'"
            ><img v-if="opponentAvatarUrl" :src="opponentAvatarUrl" alt="" @error="brokenAvatars.opponent = opponentAvatarUrl" /><template v-else>{{ opponentInitial }}</template></button>
            <div class="arena-player__meta">
              <b class="hud-name" data-testid="game-opponent-name">{{ opponentName }}</b>
              <span class="arena-player__line">
                <span class="hud-pips" data-testid="game-ships">{{ shipsText }}</span>
                <button type="button" class="arena-stats-btn" data-testid="game-opponent-stats-open" @click="playerCardSide = 'opponent'">战绩</button>
                <span class="arena-player__pips" aria-hidden="true">
                  <i
                    v-for="index in 6"
                    :key="'opp-pip-' + index"
                    :class="{ 'is-lost': index > state.opponent_remaining_ships }"
                  ></i>
                </span>
              </span>
              <StatusMonitor side="opponent" :badges="opponentEffects" />
            </div>
          </div>

          <span class="hud-vs" aria-hidden="true">VS</span>

          <div class="arena-player arena-player--self" data-testid="game-self-card">
            <button
              type="button"
              class="arena-avatar arena-avatar--self arena-avatar--btn"
              data-testid="game-self-avatar"
              aria-label="查看我的资料"
              @click="playerCardSide = 'self'"
            ><img v-if="selfAvatarUrl" :src="selfAvatarUrl" alt="" @error="brokenAvatars.self = selfAvatarUrl" /><template v-else>{{ selfInitial }}</template></button>
            <div class="arena-player__meta">
              <b class="hud-name" data-testid="game-self-name">{{ selfName }}</b>
              <span class="arena-player__line">
                <span class="arena-player__ships">剩余 {{ state.remaining_ships }} 艘</span>
                <span class="arena-player__pips" aria-hidden="true">
                  <i
                    v-for="slot in shipSlots"
                    :key="'self-pip-' + slot.index"
                    :class="{ 'is-lost': !slot.alive, 'is-frozen': slot.frozen }"
                  ></i>
                </span>
              </span>
              <StatusMonitor side="self" :badges="selfEffects" />
            </div>
          </div>
        </div>
        </header>

        <!-- 全宽场地魔法条（原 main 的 .field-magic-area） -->
        <div class="field-magic-area">
          <EffectMonitor
            :field="fieldEffectCard"
            :field-owner="fieldEffectOwner"
            :self-effects="selfEffects"
            :opponent-effects="opponentEffects"
          />
        </div>

        <!-- 手机档：单块棋盘 + 海域切换标签（标题与提交的棋盘同源） -->
        <div v-if="boardMode === 'tabs' && !selection" class="board-tabs" :class="{ 'has-chain-reminder': (priorityCollapsed && priorityRequest) || (chainCollapsed && chainHasContent) }" role="tablist" aria-label="切换棋盘">
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
          <button
            v-if="priorityCollapsed && priorityRequest && ui.phasePrompts && (!compact || !selection)"
            type="button" class="game-chain-reopen"
            :class="{ 'is-counting': priorityRemaining > 0 }"
            data-testid="game-phase-reopen" @click="priorityCollapsed = false"
          >
            <span class="game-chain-reopen__dot" aria-hidden="true"></span>
            <template v-if="compact">阶段 · {{ priorityRemaining }} 秒 · 打开</template>
            <template v-else>阶段转换待响应 · 剩余 {{ priorityRemaining }} 秒 · 打开</template>
          </button>
          <button
            v-if="chainCollapsed && chainHasContent && !(priorityCollapsed && priorityRequest && ui.phasePrompts) && (!compact || !selection)"
            type="button"
            class="game-chain-reopen"
            :class="{ 'is-counting': !!chainWindow && chainRemaining > 0 }"
            data-testid="game-chain-reopen"
            @click="match.expandChainWindow()"
          >
            <span class="game-chain-reopen__dot" aria-hidden="true"></span>
            <template v-if="chainWindow">
              <template v-if="compact">连锁 · {{ chainRemaining }} 秒 · 打开</template>
              <template v-else>连锁待响应：{{ chainWindow.card ? chainWindow.card.name : '魔法卡' }} · 剩余 {{ chainRemaining }} 秒 · 打开</template>
            </template>
            <template v-else>展开连锁结算 · 打开</template>
          </button>
          <div v-show="showSelfBoard" class="board-wrapper">
            <BoardPanel
              board="self"
              board-testid="game-board-self"
              title-testid="game-board-title-self"
              :title="'你的海域 · ' + selfName"
              :subtitle="'存活 ' + state.remaining_ships + ' 艘' + (frozenMine.size ? ' · 你的 3×3 区域被冻结' : '')"
              :cells="selfCells"
              :selected="(selection?.descriptor.board === 'opponent' ? [] : selectedKeys).concat(shieldSelectedKeys)"
              :preview="selfBoardPreviewKeys"
              :legal="legalKeys"
              :selection-board="selection ? (selection.board || selection.descriptor.board || (selection.descriptor.kind === 'own_ships' ? 'self' : null)) : 'self'"
              :selection-label="selection?.card.name || (shieldOpen ? '仁王之盾' : '')"
              :selection-hint="selection ? targetHint : (pendingPick?.message || '点击己方战舰选择目标。')"
              :selection-kind="boardPreviewKind"
              :selection-tone="boardPreviewTone"
              :selection-badge="boardPreviewBadge"
              :hidden="!showSelfBoard"
              :picking="!!selection || !!match.pickRequest || shieldOpen"
              @hover="point => previewTarget('self', point)"
              @cell="(x: number, y: number) => onCell('self', x, y)"
            />
          </div>
          <div v-show="showOpponentBoard" class="board-wrapper">
            <BoardPanel
              board="opponent"
              board-testid="game-board-opponent"
              title-testid="game-board-title-opponent"
              :title="'对手海域 · ' + opponentName"
              :subtitle="'已探明 ' + shots + ' / 36 格 · 命中 ' + hits + (frozenTheirs.size ? ' · 对方 3×3 区域被冻结' : '')"
              :cells="opponentCells"
              :preview="opponentBoardPreviewKeys"
              :selected="selection?.descriptor.board === 'self' ? [] : selectedKeys"
              :legal="legalKeys"
              :selection-board="selection ? (selection.board || selection.descriptor.board || (selection.descriptor.kind === 'own_ships' ? 'self' : null)) : 'self'"
              :selection-label="selection?.card.name || (shieldOpen ? '仁王之盾' : '')"
              :selection-hint="selection ? targetHint : (pendingPick?.message || '点击己方战舰选择目标。')"
              :selection-kind="boardPreviewKind"
              :selection-tone="boardPreviewTone"
              :selection-badge="boardPreviewBadge"
              :hidden="!showOpponentBoard"
              :picking="!!selection"
              @hover="point => previewTarget('opponent', point)"
              @cell="(x: number, y: number) => onCell('opponent', x, y)"
            />
          </div>
        </div>

      </div>

      <!-- 右列：连锁结算 / 卡牌详情 / 计数与主行动（原 main 的 .arena-rail + 详情列） -->
      <aside class="arena-rail" :class="{ 'arena-rail--sheet': railSheet }" aria-label="连锁、卡牌与操作">
        <section class="arena-rail-panel arena-chain-slot" data-testid="game-chain-rail">
          <header class="arena-rail-head">连锁结算</header>
          <!-- 原 main 的 .chain-stack：104×156 卡面竖向叠放，相邻压住约 1/3 -->
          <ol v-if="chainList.length" class="chain-stack" data-testid="game-chain-stack">
            <li
              v-for="(item, index) in chainList"
              :key="'chain-rail-' + index"
              class="chain-stack__item"
              :class="{ 'is-spent': item.negated }"
              :data-testid="'game-chain-item-' + index"
              :title="item.name"
            >
              <img
                v-if="cardArtUrl(item.name)"
                :src="cardArtUrl(item.name) || ''"
                :alt="item.name + ' 卡面'"
                loading="lazy"
              />
              <span v-else class="chain-stack__name" :data-testid="'game-chain-item-' + index + '-name'">{{ item.name }}</span>
              <span v-if="item.negated" class="arena-chain-negated">已无效</span>
            </li>
          </ol>
          <p v-else class="arena-rail-empty" data-testid="game-chain-empty">暂无连锁</p>
          <button
            v-if="chainHasContent && !chainCollapsed"
            type="button"
            class="button button--ghost arena-rail-wide"
            data-testid="game-chain-open"
            @click="match.collapseChainWindow()"
          >收起连锁窗口</button>
        </section>

        <!-- 卡牌详情 / 待使用：选中后原位展开，未选中时给出占位（原 main 的 .magic-preview-container） -->
        <section
          v-if="detailOpen && hand[selectedCardIndex]"
          ref="detailPanelEl"
          class="game-detail"
          :class="{ 'game-detail--float': !compact }"
          :style="compact ? undefined : { left: detailDrag.state.value.x + 'px', top: detailDrag.state.value.y + 'px', right: 'auto', bottom: 'auto', maxHeight: 'calc(100vh - ' + (detailDrag.state.value.y + 8) + 'px)' }"
          data-testid="game-card-detail"
          aria-label="卡牌详情"
        >
          <header
            ref="detailHeadEl"
            class="game-detail__head"
            :class="{ 'game-float__head': !compact }"
            :title="compact ? undefined : '拖动标题栏移动'"
            @pointerdown="compact ? undefined : detailDrag.onPointerDown($event)"
          >
            <h2 class="game-detail__name">{{ hand[selectedCardIndex].name }}</h2>
            <button type="button" class="game-close" data-testid="game-card-detail-close" aria-label="关闭卡牌详情" @click="cancelCardSelection">×</button>
          </header>
          <!-- 原 main 的三段式：卡名 → 完整卡面（156px 宽、2:3）→ 可读规则 -->
          <figure v-if="cardArtUrl(hand[selectedCardIndex].name)" class="game-detail__face">
            <img
              class="game-detail__art"
              :src="cardArtUrl(hand[selectedCardIndex].name) || ''"
              :alt="hand[selectedCardIndex].name + ' 卡面'"
              loading="eager"
            />
          </figure>
          <p class="game-detail__meta">{{ typeLabel(hand[selectedCardIndex]) }}</p>
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
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-enter-battle" :disabled="!!state.priority_waiting || !myTurn || state.current_phase !== 'preparation'" @click="turnAction('enter_battle_phase')">进入战斗阶段</button>
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-enter-end" :disabled="!!state.priority_waiting || !myTurn || state.current_phase !== 'battle'" @click="turnAction('enter_end_phase')">进入结束阶段</button>
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-end-turn" :disabled="!!state.priority_waiting || !myTurn || state.current_phase !== 'end'" @click="turnAction('end_turn')">结束回合</button>
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-log-toggle" @click="moreOpen = false; logOpen = true">对局日志</button>
            <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-more-opponent-stats" @click="moreOpen = false; playerCardSide = 'opponent'">对手战绩</button>
            <button
              type="button"
              class="button button--danger game-more__item"
              role="menuitem"
              data-testid="game-surrender"
              :class="{ 'is-armed': surrenderArmed }"
              @click="armSurrender"
            >{{ surrenderArmed ? '确认投降（判负）' : '投降' }}</button>
            <p class="game-more__note" data-testid="game-surrender-consequence">{{ surrenderConsequence }}</p>
            <p v-if="surrenderError" class="game-more__note" role="alert">{{ surrenderError }}</p>
          </div>
        </div>
      </aside>
    </div>

    <!-- 底部手牌条（原 main 的底部手牌） -->

    <section class="game-hand-wrap" aria-label="手牌" ref="handWrapEl">
      <div class="game-hand-head">
        <span class="game-hand-stats" data-testid="game-stats">命中 {{ hits }} · 开火 {{ shots }}</span>
        <span class="game-hand-count" data-testid="game-hand-counter">手牌 {{ hand.length }} 张</span>
      </div>
      <div
        class="game-hand"
        :class="{ 'game-hand--fan': handFan.layout.value.fan, 'game-hand--tight': handFan.layout.value.tight }"
        data-testid="game-hand"
        :style="{
          '--hand-card-w': handFan.layout.value.cardW + 'px',
          '--hand-card-h': handFan.layout.value.cardH + 'px',
          '--hand-desc-lines': String(handFan.layout.value.descLines),
        }"
      >
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
          :style="{
            marginLeft: handFan.layout.value.cards[index]?.marginLeft,
            '--fan-rot': handFan.layout.value.cards[index]?.rot,
            '--fan-drop': handFan.layout.value.cards[index]?.drop,
          }"
          @click="onCardClick(index)"
          @mouseenter="showCardPreview(index)"
          @mouseleave="hideCardPreview()"
          @focus="showCardPreview(index)"
          @blur="hideCardPreview()"
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
      <Transition name="card-inspect-fade">
        <aside v-if="previewCard" class="game-card-inspect" data-testid="game-card-hover-preview" aria-live="polite" @mouseenter="showCardPreview(hoveredCardIndex)" @mouseleave="hideCardPreview()">
          <div class="game-card-inspect__art" :class="{ 'is-empty': !cardArtUrl(previewCard.name) }">
            <img v-if="cardArtUrl(previewCard.name)" :src="cardArtUrl(previewCard.name) || ''" :alt="previewCard.name + ' 卡面预览'" />
            <span v-else>{{ previewCard.name }}</span>
          </div>
          <div class="game-card-inspect__body">
            <div class="game-card-inspect__head"><strong>{{ previewCard.name }}</strong><span>{{ typeLabel(previewCard) }}</span></div>
            <p>{{ previewCard.description || '暂无效果说明' }}</p>
            <small v-if="discardHover" class="game-card-inspect__hint">点击这张牌查看完整效果详情</small>
            <small v-else-if="cardDisabled(previewCard)" class="game-card-inspect__reason">{{ cardDisabled(previewCard) }}</small>
            <small v-else class="game-card-inspect__hint">再次点击使用 · 详情可用键盘 Enter 打开</small>
          </div>
        </aside>
      </Transition>
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
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-enter-battle" :disabled="!!state.priority_waiting || !myTurn || state.current_phase !== 'preparation'" @click="turnAction('enter_battle_phase')">进入战斗阶段</button>
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-enter-end" :disabled="!!state.priority_waiting || !myTurn || state.current_phase !== 'battle'" @click="turnAction('enter_end_phase')">进入结束阶段</button>
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-end-turn" :disabled="!!state.priority_waiting || !myTurn || state.current_phase !== 'end'" @click="turnAction('end_turn')">结束回合</button>
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-log-toggle" @click="moreOpen = false; logOpen = true">对局日志</button>
        <button type="button" class="button button--ghost game-more__item" role="menuitem" data-testid="game-more-opponent-stats" @click="moreOpen = false; playerCardSide = 'opponent'">对手战绩</button>
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
        <p v-if="selection.priorityToken !== undefined" class="game-target__hint" data-testid="game-phase-target-countdown">阶段响应剩余 {{ priorityRemaining }} 秒，超时自动放行。</p>
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

    <Transition name="chain-fade">
    <div
      v-if="chainPanelOpen"
      class="game-chain-scrim"
      :class="{ 'game-chain-scrim--modal': !!chainWindow }"
      data-testid="game-chain-scrim"
    >
    <section
      class="game-chain-panel"
      data-testid="game-chain-overlay"
      role="dialog"
      :aria-modal="chainWindow ? 'true' : undefined"
      aria-label="连锁"
    >
      <header class="game-chain-panel__head">
        <h2 class="game-chain-panel__title">连锁</h2>
      </header>
      <section v-if="chainWindow" class="game-chain-window" data-testid="game-chain-window">
        <p class="game-chain-window__card">
          {{ chainWindow.caster === state.player_id ? '你发动了魔法卡' : '对方发动了魔法卡' }}
          <span class="chain-preview-anchor" @mouseleave="chainPreviewSource = ''">
            <button type="button" class="game-chain-ref" data-testid="game-chain-window-card" :aria-describedby="chainPreviewSource === 'trigger' ? 'chain-trigger-preview' : undefined"
              @mouseenter="inspectChain(chainWindow.card, 'trigger')" @focus="inspectChain(chainWindow.card, 'trigger')" @blur="chainPreviewSource = ''" @click="inspectChain(chainWindow.card, 'trigger')">【{{ chainWindow.card?.name || '魔法卡' }}】</button>
            <span v-if="chainInspect && chainPreviewSource === 'trigger'" id="chain-trigger-preview" class="chain-effect-preview" data-testid="game-chain-inspect" role="tooltip">
              <b data-testid="game-chain-inspect-name">{{ chainInspect.name }}</b><small>速阶 {{ chainInspect.speed }}</small><span data-testid="game-chain-inspect-desc">{{ chainInspect.description || '暂无效果描述' }}</span>
            </span>
          </span>
        </p>
        <span class="visually-hidden" data-testid="game-chain-window-caster">{{ chainWindow.caster === state.player_id ? selfName : opponentName }}</span>
        <div class="game-chain-clock">
          <div class="game-chain-ring" :style="{ '--chain-progress': String(chainProgress) }" aria-hidden="true"></div>
          <p class="game-chain-countdown" data-testid="game-chain-window-countdown" :aria-label="'剩余 ' + chainRemaining + ' 秒'">{{ chainRemaining }}</p>
        </div>
        <p class="game-chain-window__hint" data-testid="game-chain-hint">{{ canHover ? '把鼠标移到卡上可以看效果，点一下即打出；上面的卡名也能看对方那张卡。' : '点一下卡牌先看完整效果，再点一下打出；点上面的卡名可看触发卡。' }}不响应请点「不响应」。</p>
        <div class="game-chain-options">
          <div v-for="(card, index) in speed3Hand" :key="chainCardTestId(card, index, speed3Hand)" class="chain-preview-anchor" @mouseleave="chainPreviewSource = ''">
            <button type="button" class="game-chain-option" :class="{ 'is-inspected': chainInspect?.name === card.name }" :data-testid="chainCardTestId(card, index, speed3Hand)"
              :aria-describedby="chainPreviewSource === 'hand-' + index ? 'chain-hand-preview-' + index : undefined"
              @mouseenter="canHover && inspectChain(card, 'hand-' + index)" @focus="inspectChain(card, 'hand-' + index)" @blur="chainPreviewSource = ''" @click="onChainCardClick(card); if (!canHover) chainPreviewSource = 'hand-' + index">
              <b>{{ card.name }}</b><small>速阶 {{ fullCard(card)?.speed }}</small><span class="game-chain-option__desc">{{ fullCard(card)?.description || '暂无效果描述' }}</span>
            </button>
            <span v-if="chainInspect && chainPreviewSource === 'hand-' + index" :id="'chain-hand-preview-' + index" class="chain-effect-preview" data-testid="game-chain-inspect" role="tooltip"><b data-testid="game-chain-inspect-name">{{ chainInspect.name }}</b><small>速阶 {{ chainInspect.speed }}</small><span data-testid="game-chain-inspect-desc">{{ chainInspect.description || '暂无效果描述' }}</span></span>
          </div>
          <p v-if="!speed3Hand.length" class="game-chain-no-options">手中没有可响应的速阶 3 魔法卡。</p>
        </div>
        <div class="game-chain-window__actions">
          <button type="button" class="button button--ghost" data-testid="game-chain-collapse" @click="chainPreviewSource = ''; match.collapseChainWindow()">暂时收起 · 查看棋盘</button>
          <button type="button" class="button button--ghost" data-testid="game-chain-pass" @click="passChain">不响应</button>
        </div>
        <span class="visually-hidden" data-testid="game-chain-window-consequence">不响应将放弃本次连锁机会，对方卡牌继续结算。</span>
      </section>
    </section>
    </div>
    </Transition>

    <section v-if="shieldOpen" ref="pickPanelEl" :style="pickPanelStyle" class="game-dialog game-shield-choice game-pick-float" :class="{ 'is-dragging': pickDrag.state.value.dragging }" data-testid="game-shield-choice" role="dialog" aria-label="仁王之盾选择">
      <h2 ref="pickHeadEl" class="game-dialog__title game-pick-float__handle" data-testid="game-shield-choice-title" @pointerdown="pickDrag.onPointerDown">「仁王之盾」：请选择要保护的战舰</h2>
      <p class="game-dialog__hint" data-testid="game-shield-choice-hint">在自己海域点击高亮的战舰格；再点一次取消选择。</p>
      <p class="game-dialog__hint" data-testid="game-shield-choice-count">已选 {{ shieldPicks.length }} / 3 艘</p>
      <p v-if="shieldError" class="game-dialog__error" data-testid="game-shield-choice-error">{{ shieldError }}</p>
      <p class="game-dialog__hint" data-testid="game-shield-choice-status">超过本局思考时限会自动选择；点「取消选择」可放弃本次加盾。</p>
      <div class="game-dialog__actions">
        <button type="button" class="button" data-testid="game-shield-choice-confirm" :disabled="shieldPicks.length === 0" @click="confirmShieldChoice">确认加盾</button>
        <button type="button" class="button button--ghost" data-testid="game-shield-choice-cancel" @click="cancelShieldChoice">取消选择</button>
      </div>
    </section>

    <section v-if="match.pickRequest" ref="pickPanelEl" :style="pickPanelStyle" class="game-dialog game-pick game-pick-float" :class="{ 'is-dragging': pickDrag.state.value.dragging }" data-testid="game-ship-pick" role="alertdialog" aria-label="选船">
      <h2 ref="pickHeadEl" class="game-dialog__title game-pick-float__handle" @pointerdown="pickDrag.onPointerDown">请选择一艘自己的战舰</h2>
      <p class="game-dialog__hint" data-testid="game-ship-pick-message">{{ match.pickRequest.message }}</p>
      <p class="game-dialog__hint">在自己海域点击高亮的战舰格子。</p>
    </section>


    <PlayerCardDialog
      v-if="playerCardSide"
      :side="playerCardSide"
      :name="playerCardSide === 'opponent' ? opponentName : selfName"
      :card="playerCardSide === 'opponent' ? playerCards.opponent.value : playerCards.self.value"
      :is-ai="Boolean(state.is_ai_room)"
      @close="playerCardSide = null"
    />

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

    <section
      v-if="quickChatOpen || (!compact && !chatDismissed)"
      class="game-drawer game-drawer--chat"
      :class="{ 'game-float': !compact }"
      :style="compact ? undefined : { left: chatDrag.state.value.x + 'px', top: chatDrag.state.value.y + 'px' }"
      data-testid="game-quick-chat"
      aria-label="局内聊天"
      ref="chatPanelEl"
    >
      <header
        class="game-drawer__head"
        :class="{ 'game-float__head': !compact }"
        @pointerdown="compact ? undefined : chatDrag.onPointerDown($event)"
      >
        <h2 class="game-drawer__title" ref="chatHeadEl">局内聊天{{ compact ? '' : '（可拖动）' }}</h2>
        <button
          type="button"
          class="game-close"
          data-testid="game-quick-chat-close"
          aria-label="关闭聊天"
          @click="quickPhrasesOpen = false; quickChatOpen = false; if (!compact) chatDismissed = true"
        >×</button>
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
      <ol class="game-chat-log" data-testid="game-quick-chat-messages">
        <li v-for="(message, index) in quickChatMessages" :key="'qc-' + index" class="game-chat-line" :data-testid="'game-quick-chat-message-' + index">
          <b>{{ message.name }}</b>：{{ message.text }}
        </li>
      </ol>
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
          <button
            type="button"
            class="button button--ghost game-chat-quick-toggle"
            :class="{ 'is-open': quickPhrasesOpen }"
            :aria-expanded="quickPhrasesOpen ? 'true' : 'false'"
            aria-controls="game-quick-phrases"
            data-testid="game-quick-chat-toggle"
            @click="quickPhrasesOpen = !quickPhrasesOpen"
          >快捷语</button>
          <button type="button" class="button" data-testid="game-chat-send" @click="sendChat">发送</button>
        </div>
        <div v-if="quickPhrasesOpen" id="game-quick-phrases" class="game-chat-phrases" data-testid="game-quick-phrases">
          <ul class="game-chat-items">
            <li v-for="item in quickChatCatalog" :key="item.id">
              <button type="button" class="button button--ghost game-chat-item" :data-testid="'game-quick-chat-item-' + item.id" @click="sendQuickChat(item)">{{ item.text }}</button>
            </li>
          </ul>
          <p v-if="!quickChatCatalog.length" class="game-drawer__empty">快捷语目录暂不可用</p>
        </div>
      </section>

    </section>

    <Transition name="drawer">
      <section v-if="discardOpen" class="game-drawer game-drawer--discard" data-testid="game-discard-drawer" role="dialog" aria-label="弃牌堆">
        <header class="game-drawer__head">
          <h2 class="game-drawer__title">弃牌堆</h2>
          <button type="button" class="game-close" data-testid="game-discard-close" aria-label="关闭弃牌堆" @click="closeDiscardDrawer">×</button>
        </header>
        <p v-if="discardLoading" class="game-drawer__empty">正在读取弃牌堆…</p>
        <p v-if="discardError" class="game-dialog__error" data-testid="game-discard-error">{{ discardError }}</p>
        <p v-if="!discardLoading && !discardCards.length && !discardError" class="game-drawer__empty" data-testid="game-discard-empty">弃牌堆还是空的</p>
        <div class="game-discard-grid" data-testid="game-discard-grid">
          <button
            v-for="(card, index) in discardCards"
            :key="'discard-' + index + '-' + card.name"
            type="button"
            class="game-discard-card"
            :data-testid="'game-discard-card-' + index"
            :aria-label="card.name + '（查看效果详情）'"
            @mouseenter="showDiscardPreview(card)"
            @mouseleave="hideDiscardPreview()"
            @focus="showDiscardPreview(card)"
            @blur="hideDiscardPreview()"
            @click="openDiscardDetail(card)"
          >
            <img v-if="cardArtUrl(card.name)" class="game-discard-card__art" :src="cardArtUrl(card.name) || ''" :alt="card.name" draggable="false" />
            <span v-else class="game-discard-card__fallback">{{ card.name }}</span>
            <span class="game-discard-card__name">{{ card.name }}</span>
          </button>
        </div>
        <p class="game-drawer__empty">点牌看效果详情；牌堆剩余数量服务端没有下发，这里只显示已经进弃牌堆的卡，不猜数字。</p>
      </section>
    </Transition>
    <div v-if="discardDetail" class="game-discard-detail" data-testid="game-discard-detail" role="dialog" :aria-label="discardDetail.name + ' 效果详情'">
      <header class="game-discard-detail__head">
        <h3 class="game-discard-detail__title">{{ discardDetail.name }}</h3>
        <button type="button" class="game-close" data-testid="game-discard-detail-close" aria-label="关闭效果详情" @click="discardDetail = null">×</button>
      </header>
      <p class="game-discard-detail__meta">{{ typeLabel(discardDetail) }}</p>
      <p class="game-discard-detail__desc">{{ discardDetailInfo?.description || '服务端没有下发这张卡的效果描述。' }}</p>
    </div>
    <MagicPlacementPanel />
    <MagicChoicePanel />
    <MagicDiscardPanel />
    <PhasePriorityPrompt :open="Boolean(priorityRequest && ui.phasePrompts && !priorityCollapsed && selection?.priorityToken === undefined)" :request="priorityRequest" :now="now" :busy="busy" :error="priorityError" @select="respondPriority" @pass="passPriority" @collapse="priorityCollapsed = true" />

    <DiceRollOverlay
      :self-id="state.player_id"
      :self-name="selfName"
      :opponent-name="opponentName"
    />
  </section>
</template>

<style scoped src="./game-screen.css"></style>
<style scoped src="./card-inspect.css"></style>

<style scoped>
/* 只改变响应窗口的呈现，不改变连锁计时和响应状态。 */
.chain-fade-enter-active { transition:opacity 160ms ease-out; }
.chain-fade-leave-active { transition:opacity 120ms ease-in; pointer-events:none; }
.chain-fade-enter-from,.chain-fade-leave-to { opacity:0; }
@media(prefers-reduced-motion:reduce) {
  .chain-fade-enter-active,.chain-fade-leave-active { transition:none; }
}
</style>
