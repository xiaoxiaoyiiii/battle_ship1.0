import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { EMPTY_MYSTERY_TECH_STATE, type MysteryTechState } from './mysteryTechTypes'
import {
  mergePublicMysteryTech,
  parseMysteryTechState,
} from '../screens/game/mysteryTechView'

/**
 * 本人私有选择/瞄准状态与公开投影。room_sync.mystery_tech_state 与
 * mystery_tech_state / mystery_tech_public 事件都汇入这里。
 */
export const useMysteryTechStore = defineStore('mysteryTech', () => {
  const state = ref<MysteryTechState>({ ...EMPTY_MYSTERY_TECH_STATE })
  const receivedAt = ref(0)
  const targetReceivedAt = ref(0)
  const enabled = ref(false)
  const error = ref('')
  const pending = ref<'refresh' | 'choose' | 'target' | null>(null)
  const flashTechIds = ref<string[]>([])

  const hasPrivateOptions = computed(() => state.value.options.length > 0)
  const locked = computed(() => Boolean(state.value.locked_tech_id))

  function markReceived(): void {
    receivedAt.value = Date.now()
  }

  function applyPrivate(payload: unknown): void {
    const parsed = parseMysteryTechState(payload)
    if (!parsed) return
    const previousIds = new Set(state.value.options.map((item) => item.tech_id))
    const previousRequest = state.value.target?.request_id
    state.value = parsed
    enabled.value = parsed.enabled
    markReceived()
    if (parsed.target && parsed.target.request_id !== previousRequest) targetReceivedAt.value = Date.now()
    if (!parsed.target) targetReceivedAt.value = 0
    const newcomers = parsed.options
      .filter((item) => item.technology.tier === 'mythic' && !previousIds.has(item.tech_id))
      .map((item) => item.tech_id)
    if (newcomers.length) flashTechIds.value = newcomers
    error.value = ''
  }

  function applyPublic(payload: unknown): void {
    const parsed = parseMysteryTechState(payload)
    if (!parsed) return
    state.value = mergePublicMysteryTech(state.value, parsed)
    enabled.value = parsed.enabled || enabled.value
    markReceived()
  }

  /** room_sync / game_state 恢复：有私有字段就整包替换，否则只合并公开部分。 */
  function hydrateFromSync(payload: unknown, flag?: unknown): void {
    if (flag === true) enabled.value = true
    if (flag === false && payload == null) {
      reset()
      return
    }
    const parsed = parseMysteryTechState(payload)
    if (!parsed) {
      if (flag === false) reset()
      return
    }
    const hasPrivate = parsed.options.length > 0 || parsed.locked_tech_id != null || parsed.target != null
    if (hasPrivate || !state.value.options.length) applyPrivate(payload)
    else applyPublic(payload)
  }

  function consumeFlash(): string[] {
    const ids = flashTechIds.value
    flashTechIds.value = []
    return ids
  }

  function setPending(action: 'refresh' | 'choose' | 'target' | null): void {
    pending.value = action
  }

  function setError(message: string): void {
    error.value = message
  }

  function reset(): void {
    state.value = { ...EMPTY_MYSTERY_TECH_STATE }
    receivedAt.value = 0
    targetReceivedAt.value = 0
    enabled.value = false
    error.value = ''
    pending.value = null
    flashTechIds.value = []
  }

  return {
    state,
    receivedAt,
    targetReceivedAt,
    enabled,
    error,
    pending,
    flashTechIds,
    hasPrivateOptions,
    locked,
    applyPrivate,
    applyPublic,
    hydrateFromSync,
    consumeFlash,
    setPending,
    setError,
    reset,
  }
})
