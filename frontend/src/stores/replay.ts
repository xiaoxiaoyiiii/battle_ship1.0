import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  computeFrame,
  errorTextForStatus,
  isObject,
  normalizePayload,
  type ReplayFrame,
  type ReplayPayload,
} from '../screens/replay/model'

/**
 * Replay view state (ticket #28).
 *
 * The payload arrives only from GET /api/replay/<match_id> (never Socket.IO).
 * This store owns the loaded payload, the current frame index and playback
 * flags; the frame itself is derived by the one pure implementation in
 * screens/replay/model.ts (the screen renders it, the external gate recomputes
 * it from the same raw payload).
 *
 * Loading has a generation token: a slow response for match A must never
 * overwrite match B, and leaving the screen must discard the response instead
 * of starting a timer behind the user's back.
 */
export type ReplayStatus = 'idle' | 'loading' | 'ready' | 'error'

export const useReplayStore = defineStore('replay', () => {
  const status = ref<ReplayStatus>('idle')
  const error = ref('')
  const matchId = ref('')
  const payload = ref<ReplayPayload | null>(null)
  const youAre = ref<'p1' | 'p2' | null>(null)
  const k = ref(0)
  const playing = ref(false)
  const speed = ref(1)

  const frame = computed<ReplayFrame | null>(() =>
    payload.value ? computeFrame(payload.value, k.value) : null,
  )
  const stepCount = computed(() => payload.value?.steps.length ?? 0)
  const currentStep = computed(() => payload.value?.steps[k.value] ?? null)

  let loadToken = 0

  async function load(id: string): Promise<void> {
    const token = ++loadToken
    matchId.value = id
    payload.value = null
    youAre.value = null
    k.value = 0
    playing.value = false
    speed.value = 1
    error.value = ''
    if (!id) {
      status.value = 'idle'
      return
    }
    status.value = 'loading'
    try {
      const response = await fetch('/api/replay/' + encodeURIComponent(id), {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      })
      if (token !== loadToken) return
      let body: unknown = null
      try {
        body = await response.json()
      } catch {
        body = null
      }
      if (token !== loadToken) return
      const record = isObject(body) ? body : null
      const normalised = record && record.success === true ? normalizePayload(record.replay) : null
      if (!response.ok || !normalised) {
        status.value = 'error'
        error.value = errorTextForStatus(response.ok ? 500 : response.status)
        return
      }
      payload.value = normalised
      youAre.value = record?.you_are === 'p1' || record?.you_are === 'p2' ? record.you_are : null
      k.value = 0
      status.value = 'ready'
    } catch {
      if (token !== loadToken) return
      status.value = 'error'
      error.value = '加载回放失败（网络问题），请稍后重试。'
    }
  }

  function reset(): void {
    loadToken += 1
    status.value = 'idle'
    error.value = ''
    matchId.value = ''
    payload.value = null
    youAre.value = null
    k.value = 0
    playing.value = false
    speed.value = 1
  }

  function setK(next: number): void {
    const last = Math.max(0, stepCount.value - 1)
    const value = Math.trunc(next)
    k.value = value < 0 ? 0 : value > last ? last : value
  }

  function setPlaying(value: boolean): void {
    playing.value = value
  }

  function setSpeed(value: number): void {
    if (value !== 1 && value !== 2 && value !== 4) return
    speed.value = value
  }

  return {
    status,
    error,
    matchId,
    payload,
    youAre,
    k,
    playing,
    speed,
    frame,
    stepCount,
    currentStep,
    load,
    reset,
    setK,
    setPlaying,
    setSpeed,
  }
})
