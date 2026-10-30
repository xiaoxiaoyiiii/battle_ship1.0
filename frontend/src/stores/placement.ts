import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * Ticket #23: the opening placement screen's local editing state.
 *
 * The server stays the only authority (P4 rule: the screen formats server
 * values, it never re-computes rules). This store owns exactly what the legacy
 * screen owned locally:
 *  * the draft cells the player clicked before submitting,
 *  * whether the current deploy phase was already accepted,
 *  * the ack wait/timeout state.
 *
 * Adopting a server snapshot (room_sync ships, or a reconnect) is an explicit
 * action: the screen calls adoptFromServer, so a random server push cannot
 * overwrite a board the player is editing.
 *
 * The legacy deploy state machine (static/game.js:11353-11683) is the parity
 * reference; the constants below are the same 6 ships and 6s ack wait.
 */

export const BOARD_SIZE = 6
export const DEFAULT_MAX_SHIPS = 6
export const DEFAULT_ACK_TIMEOUT_MS = 6000
export const DEFAULT_TICK_MS = 1000

export interface BoardCell {
  x: number
  y: number
}

export interface AckTiming {
  ackTimeoutMs?: number
  tickMs?: number
}

function cellKey(x: number, y: number): string {
  return x + ',' + y
}

function readCellNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isInteger(parsed) ? parsed : null
}

/** The legacy deployCellsValid rule, kept as one implementation for the UI. */
function normalizeCells(raw: unknown): BoardCell[] {
  const ships = Array.isArray(raw) ? raw : []
  const seen = new Set<string>()
  const cells: BoardCell[] = []
  for (const ship of ships) {
    if (!ship || typeof ship !== 'object') continue
    const positions = Array.isArray((ship as { positions?: unknown }).positions)
      ? ((ship as { positions: unknown[] }).positions)
      : []
    for (const position of positions) {
      if (!position || typeof position !== 'object') continue
      const x = readCellNumber((position as { x?: unknown }).x)
      const y = readCellNumber((position as { y?: unknown }).y)
      if (x === null || y === null) continue
      if (x < 0 || y < 0 || x >= BOARD_SIZE || y >= BOARD_SIZE) continue
      const key = cellKey(x, y)
      if (seen.has(key)) continue
      seen.add(key)
      cells.push({ x, y })
    }
  }
  return cells
}

export const usePlacementStore = defineStore('placement', () => {
  const maxShips = ref(DEFAULT_MAX_SHIPS)
  const cells = ref<BoardCell[]>([])
  const allowed = ref<BoardCell[] | null>(null)
  function canPlace(x: number, y: number): boolean {
    return allowed.value === null || allowed.value.some(p => p.x === x && p.y === y)
  }
  function setAllowed(raw: unknown): void {
    allowed.value = Array.isArray(raw) ? normalizeCells([{ positions: raw }]) : null
    cells.value = cells.value.filter(p => canPlace(p.x, p.y))
  }
  const submitted = ref(false)
  const pending = ref(false)
  const countdown = ref(0)
  const error = ref('')
  const resetMessage = ref('')
  /** A mid-game redeploy (reset_gameboard) is in progress: the server still
   *  expects a place_ships even though room.state may already read attacking. */
  const resetPhase = ref(false)
  // Opponent seat state (contract #43). It only ever arrives in room_sync; until
  // one arrives the screen must not claim the opponent is offline.
  const opponentReady = ref(false)
  const opponentOnline = ref(false)
  const opponentStateKnown = ref(false)
  /** The single inline receipt for a refused click. */
  const receipt = ref('')

  let ackTimeoutMs = DEFAULT_ACK_TIMEOUT_MS
  let tickMs = DEFAULT_TICK_MS
  let timer: ReturnType<typeof setInterval> | null = null

  const placedCount = computed(() => cells.value.length)
  const total = computed(() => maxShips.value)
  const locked = computed(() => pending.value || submitted.value)
  const isComplete = computed(
    () => maxShips.value > 0 && placedCount.value === maxShips.value,
  )
  const canSubmit = computed(() => !locked.value && isComplete.value)

  /** The one status line; every reason "why the button is disabled" lives here. */
  const hint = computed(() => {
    if (pending.value) return '正在提交，等待确认…'
    if (submitted.value) return '已提交 · 等对手摆好就能开始猜拳'
    if (!isComplete.value) {
      const missing = Math.max(0, maxShips.value - placedCount.value)
      if (missing > 0) return '还差 ' + missing + ' 格就能提交'
      return '已放置超过 ' + maxShips.value + ' 格，请先撤销'
    }
    return maxShips.value + ' 格已就绪，可以提交'
  })

  function clearTimer(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  function isPlaced(x: number, y: number): boolean {
    return cells.value.some((cell) => cell.x === x && cell.y === y)
  }

  /**
   * Called when the screen mounts: clear transient notices of the previous
   * visit. resetMessage/resetPhase are deliberately kept: they describe an
   * active server phase (a redeploy may have started while another screen was
   * mounted) and are only cleared when that placement is accepted.
   */
  function resetForEntry(): void {
    clearTimer()
    pending.value = false
    countdown.value = 0
    error.value = ''
    receipt.value = ''
  }

  /** Adopt the authoritative board from a server snapshot. */
  function adoptFromServer(raw: unknown): void {
    cells.value = normalizeCells(raw)
    submitted.value = maxShips.value > 0 && cells.value.length === maxShips.value
  }

  function toggleCell(x: number, y: number): void {
    if (locked.value) return
    if (!canPlace(x, y)) { receipt.value = '只能选择这张魔法允许的原船位。'; return }
    const index = cells.value.findIndex((cell) => cell.x === x && cell.y === y)
    if (index >= 0) {
      cells.value.splice(index, 1)
      return
    }
    if (cells.value.length >= maxShips.value) return
    cells.value.push({ x, y })
  }

  function randomize(random: () => number = Math.random): void {
    if (locked.value) return
    const pool = Array.from({length:BOARD_SIZE*BOARD_SIZE}, (_,i) => ({x:i%BOARD_SIZE,y:Math.floor(i/BOARD_SIZE)})).filter(p => canPlace(p.x,p.y))
    for (let i=pool.length-1;i>0;i--) {
      const j=Math.floor(random()*(i+1))
      ;[pool[i],pool[j]]=[pool[j],pool[i]]
    }
    cells.value = pool.slice(0,maxShips.value)
  }

  function clearBoard(): void {
    if (locked.value) return
    cells.value = []
    submitted.value = false
  }

  function beginPending(): void {
    clearTimer()
    pending.value = true
    submitted.value = false
    error.value = ''
    countdown.value = Math.max(1, Math.ceil(ackTimeoutMs / 1000))
    const startedAt = Date.now()
    timer = setInterval(() => {
      const remaining = ackTimeoutMs - (Date.now() - startedAt)
      if (remaining <= 0) {
        clearTimer()
        pending.value = false
        countdown.value = 0
        error.value =
          '提交后 ' + Math.max(1, Math.round(ackTimeoutMs / 1000)) +
          ' 秒没有收到确认，已停止等待。可以重新提交。'
        return
      }
      countdown.value = Math.max(0, Math.ceil(remaining / 1000))
    }, tickMs)
  }

  /** Apply the place_ships ack. A rejection keeps the board editable. */
  function settleSubmit(ok: boolean, message = ''): void {
    clearTimer()
    pending.value = false
    countdown.value = 0
    if (ok) {
      submitted.value = true
      error.value = ''
      resetPhase.value = false
      resetMessage.value = ''
      return
    }
    submitted.value = false
    error.value = '放置战舰失败：' + (message || '原因未知') + '。可以调整后重试。'
  }

  /** reset_gameboard: a mid-game redeploy starts a fresh phase. */
  function applyReset(payload: Record<string, unknown> | null | undefined): void {
    if (!payload || typeof payload !== 'object') return
    clearTimer()
    pending.value = false
    countdown.value = 0
    error.value = ''
    const value = Number(payload.new_max_ships)
    maxShips.value = Number.isFinite(value) && value > 0 ? Math.floor(value) : DEFAULT_MAX_SHIPS
    cells.value = []
    submitted.value = false
    resetPhase.value = true
    resetMessage.value = typeof payload.message === 'string' ? payload.message : ''
  }

  /** Screens surface server refusals that arrive as events, not acks. */
  function noteNotice(message: string): void {
    error.value = message
  }

  /** One receipt for a refused click; the screen renders it in one place. */
  function noteReceipt(message: string): void {
    receipt.value = message
  }

  function clearReceipt(): void {
    receipt.value = ''
  }

  /** room_sync (#43) is the only frame that carries the opponent seat state. */
  function adoptOpponentState(payload: Record<string, unknown> | null | undefined): void {
    if (!payload || typeof payload !== 'object') return
    if (typeof payload.opponent_ready === 'boolean') {
      opponentReady.value = payload.opponent_ready
      opponentStateKnown.value = true
    }
    if (typeof payload.opponent_online === 'boolean') {
      opponentOnline.value = payload.opponent_online
      opponentStateKnown.value = true
    }
  }

  /** External browser gate only: shrink the ack wait so the timeout is testable. */
  function configureAckTiming(options: AckTiming = {}): void {
    if (typeof options.ackTimeoutMs === 'number' && options.ackTimeoutMs > 0) {
      ackTimeoutMs = options.ackTimeoutMs
    }
    if (typeof options.tickMs === 'number' && options.tickMs > 0) tickMs = options.tickMs
  }

  function reset(): void {
    allowed.value = null
    clearTimer()
    maxShips.value = DEFAULT_MAX_SHIPS
    cells.value = []
    submitted.value = false
    pending.value = false
    countdown.value = 0
    error.value = ''
    resetMessage.value = ''
    resetPhase.value = false
    receipt.value = ''
    opponentReady.value = false
    opponentOnline.value = false
    opponentStateKnown.value = false
  }

  return {
    canPlace,
    setAllowed,
    maxShips,
    cells,
    submitted,
    pending,
    countdown,
    error,
    resetMessage,
    resetPhase,
    receipt,
    opponentReady,
    opponentOnline,
    opponentStateKnown,
    placedCount,
    total,
    locked,
    isComplete,
    canSubmit,
    hint,
    isPlaced,
    resetForEntry,
    adoptFromServer,
    toggleCell,
    randomize,
    clearBoard,
    beginPending,
    settleSubmit,
    applyReset,
    noteNotice,
    noteReceipt,
    clearReceipt,
    adoptOpponentState,
    configureAckTiming,
    reset,
  }
})
