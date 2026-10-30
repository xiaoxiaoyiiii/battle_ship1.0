import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * Ticket #23: the rock-paper-scissors screen's local state.
 *
 * rps_choice's ack only means "the server took it"; the first move arrives in
 * rps_result (port map 10 section 0). The legacy screen therefore had two
 * independent arrivals to coordinate (static/game.js:11685-11770): a pending
 * choice with its own 6s ack timeout, and a result that clears it. The store
 * keeps that split so a late ack can never overwrite a newer round.
 */

export const DEFAULT_ACK_TIMEOUT_MS = 6000
export const DEFAULT_TICK_MS = 1000

export type RpsResultRecord = Record<string, unknown>

export interface AckTiming {
  ackTimeoutMs?: number
  tickMs?: number
}

export const useRpsStore = defineStore('rps', () => {
  const result = ref<RpsResultRecord | null>(null)
  const pendingChoice = ref('')
  const waiting = ref(false)
  const countdown = ref(0)
  const error = ref('')
  // Opponent seat state (contract #43); known only after a room_sync frame.
  const opponentReady = ref(false)
  const opponentOnline = ref(false)
  const opponentStateKnown = ref(false)

  let ackTimeoutMs = DEFAULT_ACK_TIMEOUT_MS
  let tickMs = DEFAULT_TICK_MS
  let timer: ReturnType<typeof setInterval> | null = null

  function clearTimer(): void {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  function resetForEntry(): void {
    clearTimer()
    waiting.value = false
    pendingChoice.value = ''
    countdown.value = 0
    error.value = ''
    result.value = null
  }

  /** Start one round: clears the previous result (a tie round starts over). */
  function beginChoice(choice: string): void {
    if (waiting.value) return
    clearTimer()
    waiting.value = true
    pendingChoice.value = choice
    error.value = ''
    result.value = null
    countdown.value = Math.max(1, Math.ceil(ackTimeoutMs / 1000))
    const startedAt = Date.now()
    timer = setInterval(() => {
      const remaining = ackTimeoutMs - (Date.now() - startedAt)
      if (remaining <= 0) {
        clearTimer()
        waiting.value = false
        pendingChoice.value = ''
        countdown.value = 0
        error.value = '出拳没有送到服务器，请重新选择'
        return
      }
      countdown.value = Math.max(0, Math.ceil(remaining / 1000))
    }, tickMs)
  }

  /** Ack only means "received"; waiting continues until rps_result. */
  function settleAck(ok: boolean, message = ''): void {
    if (!ok) {
      clearTimer()
      waiting.value = false
      pendingChoice.value = ''
      countdown.value = 0
      error.value = message || '出拳被服务器拒绝，请重新选择'
    }
  }

  function applyResult(payload: RpsResultRecord | null | undefined): void {
    if (!payload || typeof payload !== 'object') return
    clearTimer()
    waiting.value = false
    pendingChoice.value = ''
    countdown.value = 0
    error.value = ''
    result.value = payload
  }

  function noteNotice(message: string): void {
    error.value = message
  }

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
    clearTimer()
    result.value = null
    pendingChoice.value = ''
    waiting.value = false
    countdown.value = 0
    error.value = ''
    opponentReady.value = false
    opponentOnline.value = false
    opponentStateKnown.value = false
  }

  return {
    result,
    pendingChoice,
    waiting,
    countdown,
    error,
    opponentReady,
    opponentOnline,
    opponentStateKnown,
    resetForEntry,
    beginChoice,
    settleAck,
    applyResult,
    noteNotice,
    adoptOpponentState,
    configureAckTiming,
    reset,
  }
})
