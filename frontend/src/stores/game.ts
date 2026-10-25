import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useMatchStore } from './match'
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
    // 在接收新房间的第一帧时清理，不能依赖尚未挂载的对局页 watcher。
    const newRoom = typeof next.room_id === 'string' && next.room_id !== state.value.room_id
    const restarted = state.value.state === 'game_over' && next.state === 'placing_ships' && !next.needs_reset
    if (newRoom || restarted) {
      useMatchStore().reset()
      state.value = defaultGameState()
    }
    if ('opponent_name' in next && !('opponent_registered' in next)) next.opponent_registered = false
    // `active_effects` and `room_sync` are two valid sources for the same
    // monitor. Keep a complete shape when an older snapshot omits the public
    // field keys, so a reconnect frame cannot hide a still-active long effect
    // or field card that was just rendered from the live event.
    if ('effect_badges' in next && next.effect_badges && typeof next.effect_badges === 'object') {
      const incoming = next.effect_badges as Record<string, unknown>
      const current = state.value.effect_badges
      next.effect_badges = {
        self: Array.isArray(incoming.self) ? incoming.self : current.self,
        opponent: Array.isArray(incoming.opponent) ? incoming.opponent : current.opponent,
        field: Object.prototype.hasOwnProperty.call(incoming, 'field') ? incoming.field : (current.field ?? null),
        field_owner: Object.prototype.hasOwnProperty.call(incoming, 'field_owner')
          ? incoming.field_owner
          : (current.field_owner ?? null),
      }
    }
    Object.assign(state.value, next)
    unknownFields.value = unknown
    revision.value += 1
    if (unknown.length && import.meta.env.DEV) {
      console.warn('[game-store] unknown game_state fields', unknown)
    }
    return unknown
  }

  function reset(): void {
    useMatchStore().reset()
    state.value = defaultGameState()
    unknownFields.value = []
    revision.value += 1
  }

  return { state, unknownFields, revision, applyServerState, reset }
})

export { GAME_STATE_SCHEMA }
export type { GameState }
