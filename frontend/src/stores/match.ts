import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useUiStore } from './ui'
import type { CardLike, LastAttackLike, PendingPickLike, Point, PublicChainPreview } from '../screens/game/view'

/**
 * Live battle frames that are not part of the 45-key game-state schema
 * (ticket #27).
 *
 * The game store stays the single mirror of `room_sync`/`game_state` fields
 * (hand, chain, ships, attacks, effects...). This store only keeps what the
 * server sends as *event-only* data: the log, transient prompts (chain window,
 * ship pick), notices, quick-chat + free-text chat history and the effect
 * marks that have no schema field (revealed cells, shield-absorbed cells, last
 * shot).
 *
 * Everything here arrives over the real socket channel; the test build feeds
 * the exact production reducer, never this store directly.
 */
export interface LogEntry {
  ts: number
  type: string
  text: string
  detail?: unknown
}

export type NoticeKind = 'info' | 'warning' | 'error'

export interface Notice {
  id: number
  text: string
  kind: NoticeKind
}

export interface ChainWindowState {
  card: CardLike | null
  caster: string
  targetPreview: PublicChainPreview | null
  speed3Cards: CardLike[]
  countdown: number
  openedAt: number
}

export interface QuickChatMessage {
  playerId: string
  name: string
  text: string
  ts: number
}

export interface ChatMessage {
  username: string
  message: string
  ts: number
}

export interface PickRequest extends PendingPickLike {
  ships: Array<{ positions: Point[] }>
}

/** 仁王之盾: server says "pick up to three of your ships" after the chain resolves. */
export interface ShieldChoice {
  message: string
  caster: string
}

export interface DiceRollState {
  id: number
  card: string
  caster: string
  roll: number | null
  opponentRoll: number | null
  effectText: string
  durationMs: number
}

const LOG_LIMIT = 200
const NOTICE_LIMIT = 12
const QUICK_CHAT_LIMIT = 30
const CHAT_LIMIT = 50
const DICE_DEFAULT_DURATION_MS = 3200

function asCard(value: unknown): CardLike | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  if (typeof record.name !== 'string' || !record.name) return null
  return {
    name: record.name,
    speed: (record.speed as number | string) ?? 0,
    type: String(record.type ?? ''),
    description: String(record.description ?? ''),
  }
}

function parseTargetPreview(value: unknown): PublicChainPreview | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  if (record.board !== 'self' && record.board !== 'opponent') return null
  if (record.shape !== 'area' && record.shape !== 'line' && record.shape !== 'cells' && record.shape !== 'single') return null
  if (!Array.isArray(record.cells) || !record.cells.length) return null
  const cells = record.cells
    .map((cell) => {
      if (!cell || typeof cell !== 'object') return null
      const point = cell as Record<string, unknown>
      const x = Number(point.x)
      const y = Number(point.y)
      return Number.isInteger(x) && Number.isInteger(y) && x >= 0 && x < 6 && y >= 0 && y < 6 ? { x, y } : null
    })
    .filter((cell): cell is Point => cell !== null)
  if (!cells.length) return null
  return {
    card: String(record.card ?? ''),
    board: record.board,
    shape: record.shape,
    cells,
  }
}

function parseDiceRoll(value: unknown, id: number): DiceRollState | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  const card = String(record.card ?? '判定')
  const readRoll = (raw: unknown): number | null => {
    const roll = Number(raw)
    return Number.isInteger(roll) && roll >= 1 && roll <= 6 ? roll : null
  }
  const roll = readRoll(record.roll)
  if (roll === null) return null
  const duration = Number(record.duration_ms ?? DICE_DEFAULT_DURATION_MS)
  return {
    id,
    card,
    caster: String(record.caster ?? ''),
    roll,
    opponentRoll: readRoll(record.opponent_roll),
    effectText: String(record.effect_text ?? ''),
    durationMs: Number.isFinite(duration) ? Math.min(Math.max(duration, 2400), 5000) : DICE_DEFAULT_DURATION_MS,
  }
}

export const useMatchStore = defineStore('match', () => {
  const logs = ref<LogEntry[]>([])
  const notices = ref<Notice[]>([])
  const chainWindow = ref<ChainWindowState | null>(null)
  /**
   * 面板是否被收起。收起只是本地面板可见性，待响应请求与倒计时仍在
   * `chainWindow` 里；真正的放弃必须走「不响应」协议。
   */
  const chainWindowCollapsed = ref(false)
  const lastAttack = ref<LastAttackLike | null>(null)
  const revealed = ref<Point[]>([])
  const shieldBrokenSelf = ref<Point[]>([])
  const shieldBrokenOpponent = ref<Point[]>([])
  const quickChat = ref<QuickChatMessage[]>([])
  const chat = ref<ChatMessage[]>([])
  const pickRequest = ref<PickRequest | null>(null)
  const shieldChoice = ref<ShieldChoice | null>(null)
  const diceRoll = ref<DiceRollState | null>(null)
  const diceRollQueue = ref<DiceRollState[]>([])
  const chainResolvedAt = ref(0)
  /** "超时，已自动…" banner: the server's fallback action is player-visible (#47). */
  const timeoutNote = ref('')
  let noticeSeq = 0
  let diceSeq = 0

  function appendLog(entry: LogEntry): void {
    if (!entry || typeof entry.text !== 'string') return
    logs.value.push(entry)
    if (logs.value.length > LOG_LIMIT) logs.value.splice(0, logs.value.length - LOG_LIMIT)
  }

  function pushNotice(text: string, kind: NoticeKind = 'info'): void {
    const trimmed = String(text ?? '').trim()
    if (!trimmed) return
    useUiStore().notify({ code: `battle-notice:${kind}:${trimmed}`, message: trimmed, tone: kind, ttl: 2000 })
    noticeSeq += 1
    notices.value.push({ id: noticeSeq, text: trimmed, kind })
    if (notices.value.length > NOTICE_LIMIT) notices.value.splice(0, notices.value.length - NOTICE_LIMIT)
  }

  /** Record the server's timeout fallback so the HUD can show what happened. */
  function setTimeoutNote(text: string): void {
    timeoutNote.value = String(text ?? '').trim()
  }

  function clearTimeoutNote(): void {
    timeoutNote.value = ''
  }

  function dismissNotice(id: number): void {
    notices.value = notices.value.filter((notice) => notice.id !== id)
  }

  function openChainWindow(payload: Record<string, unknown>): void {
    const speed3 = Array.isArray(payload.speed3_cards)
      ? payload.speed3_cards.map(asCard).filter((card): card is CardLike => card !== null)
      : []
    chainWindowCollapsed.value = false
    chainWindow.value = {
      card: asCard(payload.card),
      caster: String(payload.caster ?? ''),
      targetPreview: parseTargetPreview(payload.target_preview),
      speed3Cards: speed3,
      countdown: Number(payload.countdown ?? 10) || 10,
      openedAt: Date.now(),
    }
  }

  /**
   * 收起面板：保留待响应请求、已有连锁牌栈与倒计时，随时可以再打开。
   *
   * 审查 P2-2：只有链栈（magic_chain_updated.chain 非空、没有 chain_request）时
   * 原来什么都不做，因为条件写成了 `if (chainWindow.value)`。收起是**视图状态**，
   * 与协议里有没有请求无关 —— 只要面板上有内容就该能收起。
   */
  function collapseChainWindow(): void {
    // 收起是纯视图状态：面板上有内容（待响应请求或已有链栈）时调用方才给出入口。
    chainWindowCollapsed.value = true
  }

  /** 重新展开被收起的连锁面板。 */
  function expandChainWindow(): void {
    chainWindowCollapsed.value = false
  }

  /** 协议层清空：仅在连锁已结算/开局重置时调用，不能用于「收起」。 */
  function closeChainWindow(): void {
    chainWindow.value = null
    chainWindowCollapsed.value = false
  }

  function recordQuickChat(payload: Record<string, unknown>): void {
    const text = String(payload.text ?? '').trim()
    if (!text) return
    quickChat.value.push({
      playerId: String(payload.player_id ?? ''),
      name: String(payload.name ?? ''),
      text,
      ts: Number(payload.ts ?? 0) || 0,
    })
    if (quickChat.value.length > QUICK_CHAT_LIMIT) {
      quickChat.value.splice(0, quickChat.value.length - QUICK_CHAT_LIMIT)
    }
  }

  function recordChatMessage(payload: Record<string, unknown>): void {
    const message = String(payload.message ?? '').trim()
    if (!message) return
    chat.value.push({
      username: String(payload.username ?? '') || '玩家',
      message,
      ts: Number(payload.ts ?? 0) || 0,
    })
    if (chat.value.length > CHAT_LIMIT) {
      chat.value.splice(0, chat.value.length - CHAT_LIMIT)
    }
  }

  function setPickRequest(payload: Record<string, unknown>): void {
    const ships = Array.isArray(payload.ships)
      ? payload.ships.map((ship) => {
          const record = ship && typeof ship === 'object' ? (ship as Record<string, unknown>) : {}
          const positions = Array.isArray(record.positions) ? record.positions : []
          return {
            positions: positions
              .map((position) => {
                const cell = position && typeof position === 'object' ? (position as Record<string, unknown>) : null
                if (!cell) return null
                const x = Number(cell.x)
                const y = Number(cell.y)
                return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null
              })
              .filter((cell): cell is Point => cell !== null),
          }
        })
      : []
    pickRequest.value = {
      reason: String(payload.reason ?? ''),
      message: String(payload.message ?? '请点选一艘自己的战舰'),
      ships,
    }
  }

  function clearPickRequest(): void {
    pickRequest.value = null
  }

  function openShieldChoice(payload: Record<string, unknown>): void {
    shieldChoice.value = {
      message: String(payload.message ?? '仁王之盾：请选择要保护的战舰（至多 3 艘）'),
      caster: String(payload.caster ?? ''),
    }
  }

  function clearShieldChoice(): void {
    shieldChoice.value = null
  }

  function openDiceRoll(payload: Record<string, unknown>): void {
    const next = parseDiceRoll(payload, ++diceSeq)
    if (!next) return
    if (diceRoll.value) diceRollQueue.value.push(next)
    else diceRoll.value = next
  }

  function finishDiceRoll(): void {
    diceRoll.value = diceRollQueue.value.shift() ?? null
  }

  function markRevealed(points: Point[]): void {
    for (const point of points) {
      if (!revealed.value.some((cell) => cell.x === point.x && cell.y === point.y)) {
        revealed.value.push({ x: point.x, y: point.y })
      }
    }
  }

  function markShieldBroken(mine: boolean, points: Point[]): void {
    const target = mine ? shieldBrokenSelf : shieldBrokenOpponent
    for (const point of points) {
      if (!target.value.some((cell) => cell.x === point.x && cell.y === point.y)) {
        target.value.push({ x: point.x, y: point.y })
      }
    }
  }

  function clearShieldMarks(): void {
    shieldBrokenSelf.value = []
    shieldBrokenOpponent.value = []
  }

  /** A new match starts: no log/prompt from the previous room may leak in. */
  function reset(): void {
    logs.value = []
    chainWindowCollapsed.value = false
    notices.value = []
    chainWindow.value = null
    lastAttack.value = null
    revealed.value = []
    shieldBrokenSelf.value = []
    shieldBrokenOpponent.value = []
    quickChat.value = []
    chat.value = []
    pickRequest.value = null
    shieldChoice.value = null
    diceRoll.value = null
    diceRollQueue.value = []
    chainResolvedAt.value = 0
    timeoutNote.value = ''
  }

  function snapshot() {
    return {
      logs: logs.value.slice(),
      notices: notices.value.slice(),
      chainWindow: chainWindow.value ? { ...chainWindow.value } : null,
      chainWindowCollapsed: chainWindowCollapsed.value,
      timeoutNote: timeoutNote.value,
      lastAttack: lastAttack.value ? { ...lastAttack.value } : null,
      revealed: revealed.value.slice(),
      shieldBrokenSelf: shieldBrokenSelf.value.slice(),
      shieldBrokenOpponent: shieldBrokenOpponent.value.slice(),
      quickChat: quickChat.value.slice(),
      chat: chat.value.slice(),
      pickRequest: pickRequest.value ? { ...pickRequest.value } : null,
      shieldChoice: shieldChoice.value ? { ...shieldChoice.value } : null,
      diceRoll: diceRoll.value ? { ...diceRoll.value } : null,
    }
  }

  return {
    logs,
    notices,
    chainWindow,
    lastAttack,
    revealed,
    shieldBrokenSelf,
    shieldBrokenOpponent,
    quickChat,
    chat,
    pickRequest,
    shieldChoice,
    diceRoll,
    chainResolvedAt,
    timeoutNote,
    setTimeoutNote,
    clearTimeoutNote,
    appendLog,
    pushNotice,
    dismissNotice,
    openChainWindow,
    chainWindowCollapsed,
    collapseChainWindow,
    expandChainWindow,
    closeChainWindow,
    recordQuickChat,
    recordChatMessage,
    setPickRequest,
    clearPickRequest,
    openShieldChoice,
    clearShieldChoice,
    openDiceRoll,
    finishDiceRoll,
    markRevealed,
    markShieldBroken,
    clearShieldMarks,
    reset,
    snapshot,
  }
})
