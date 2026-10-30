import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * Settlement view model (ticket #22).
 *
 * The store mirrors the wire payloads; it does not compute rank/XP rules.
 * game_over is the authoritative result frame, while xp_gained,
 * rank_changed, achievements_unlocked and recent_opponent are optional
 * follow-ups (rank arrives after game_over; a casual match never sends it).
 *
 * Keeping these outside the game-state schema is deliberate: they are
 * settlement-only frames, not RoomSync fields. The screen reads this store and
 * never re-derives the server's numbers.
 */
export type JsonObject = Record<string, unknown>

export interface GameOverRecord {
  /** Winning player id, or null for a draw. */
  winner: string | null
  /** Legacy free-form reason; empty means a normal sink-all ending. */
  reason: string
  /** Authoritative match id only when the server really persisted a replay. */
  matchId: string | null
  receivedAt: number
}

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export const useResultStore = defineStore('result', () => {
  const gameOver = ref<GameOverRecord | null>(null)
  const gameOverMatchId = computed(() => gameOver.value?.matchId ?? '')
  const xp = ref<JsonObject | null>(null)
  const rank = ref<JsonObject | null>(null)
  const achievements = ref<JsonObject[]>([])
  const recentOpponent = ref<JsonObject | null>(null)

  function recordGameOver(payload: JsonObject | null | undefined): void {
    if (!payload || typeof payload !== 'object') return
    const rawWinner = payload.winner
    const rawMatchId = payload.match_id
    gameOver.value = {
      winner: rawWinner == null || rawWinner === '' ? null : String(rawWinner),
      reason: asString(payload.reason) || asString(payload.game_over_reason),
      matchId: asString(rawMatchId) || null,
      receivedAt: Date.now(),
    }
  }

  function recordXp(payload: JsonObject | null | undefined): void {
    xp.value = asObject(payload)
  }

  function recordRank(payload: JsonObject | null | undefined): void {
    rank.value = asObject(payload)
  }

  function recordAchievements(payload: JsonObject | null | undefined): void {
    const items = payload && Array.isArray(payload.items) ? payload.items : []
    achievements.value = items.map(asObject).filter((item): item is JsonObject => item !== null)
  }

  function recordRecentOpponent(payload: JsonObject | null | undefined): void {
    recentOpponent.value = asObject(payload)
  }

  /** A new match starts: the previous settlement must not leak into it. */
  function beginMatch(): void {
    if (gameOver.value || xp.value || rank.value || achievements.value.length) reset()
  }

  function reset(): void {
    gameOver.value = null
    xp.value = null
    rank.value = null
    achievements.value = []
    recentOpponent.value = null
  }

  return {
    gameOver,
    gameOverMatchId,
    xp,
    rank,
    achievements,
    recentOpponent,
    recordGameOver,
    recordXp,
    recordRank,
    recordAchievements,
    recordRecentOpponent,
    beginMatch,
    reset,
  }
})
