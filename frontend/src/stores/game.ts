import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  GAME_STATE_SCHEMA,
  defaultGameState,
  isKnownGameStateField,
  type GameState,
} from './gameStateSchema'

/**
 * The single owner of mirrored server state (ticket #21).
 *
 * Screens read `store.state` and call `applyServerState` for game_state /
 * room_sync payloads. There is deliberately no `window.gameState`: the legacy
 * bare global let any module write any field without a schema, which is the
 * class of bug the rewrite is removing.
 */
export const useGameStore = defineStore('game', () => {
  const state = ref<GameState>(defaultGameState())
  const unknownFields = ref<string[]>([])
  const revision = ref(0)

  /**
   * Merge a server snapshot. Only schema fields are adopted; unknown keys are
   * reported (the external gate and dev console surface them) instead of being
   * silently written into application state.
   */
  function applyServerState(payload: Record<string, unknown> | null | undefined): string[] {
    if (!payload || typeof payload !== 'object') return []
    const next: Record<string, unknown> = {}
    const unknown: string[] = []
    for (const [key, value] of Object.entries(payload)) {
      if (isKnownGameStateField(key)) next[key] = value
      else unknown.push(key)
    }
    if ('opponent_name' in next && !('opponent_registered' in next)) next.opponent_registered = false
    Object.assign(state.value, next)
    unknownFields.value = unknown
    revision.value += 1
    if (unknown.length && import.meta.env.DEV) {
      console.warn('[game-store] unknown game_state fields', unknown)
    }
    return unknown
  }

  function reset(): void {
    state.value = defaultGameState()
    unknownFields.value = []
    revision.value += 1
  }

  return { state, unknownFields, revision, applyServerState, reset }
})

export { GAME_STATE_SCHEMA }
export type { GameState }
