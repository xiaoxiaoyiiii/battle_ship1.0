import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from './auth'
import { useWalletStore } from './wallet'
import { readResponse } from './shop'
import {
  applyExchangeToPool,
  applyPullToPool,
  createRequestId,
  gachaErrorMessage,
  isValidRequestId,
  mapExchangeResult,
  mapGachaPool,
  mapGachaPullResult,
  readApiError,
} from './gachaMap'
import type { GachaActionResult, GachaPool, GachaPullResult, GachaStatus } from './gachaTypes'

export type { GachaActionResult, GachaPool, GachaPull, GachaPullResult, GachaStatus } from './gachaTypes'

const jsonHeaders = { accept: 'application/json', 'content-type': 'application/json' }

export const useGachaStore = defineStore('gacha', () => {
  const status = ref<GachaStatus>('idle')
  const error = ref('')
  const pool = ref<GachaPool | null>(null)
  const pulling = ref<1 | 10 | null>(null)
  const exchanging = ref<string | null>(null)
  const lastPull = ref<GachaPullResult | null>(null)
  let requestToken = 0
  let pendingPull: { count: 1 | 10; requestId: string } | null = null
  let pullInFlight = false

  const balance = computed(() => useWalletStore().balance)
  const shards = computed(() => pool.value?.shards ?? 0)
  const prices = computed(() => pool.value?.prices ?? { single: 80, ten: 800 })
  const busy = computed(() => pulling.value !== null || exchanging.value !== null)

  function fail(code: string, message: string, extra: Partial<GachaActionResult> = {}): GachaActionResult {
    error.value = message
    return { ok: false, code, message, ...extra }
  }

  function applyBalance(value: number): void {
    const wallet = useWalletStore()
    wallet.apply({
      balance: value,
      dailyMatchGranted: wallet.dailyMatchGranted,
      dailyCap: wallet.dailyCap,
    }, 'api')
  }

  function publishPool(next: GachaPool): void {
    pool.value = next
    applyBalance(next.balance)
  }

  async function load(force = false): Promise<void> {
    const auth = useAuthStore()
    if (auth.isGuest) {
      requestToken += 1
      pool.value = null
      error.value = ''
      lastPull.value = null
      status.value = 'anonymous'
      return
    }
    if (!force && (status.value === 'loading' || status.value === 'ready' || status.value === 'anonymous')) return
    const token = ++requestToken
    status.value = 'loading'
    error.value = ''
    try {
      const response = await fetch('/api/shop/gacha', {
        credentials: 'same-origin',
        headers: { accept: 'application/json' },
        cache: 'no-store',
      })
      const parsed = await readResponse(response)
      if (token !== requestToken) return
      if (response.status === 401) {
        pool.value = null
        status.value = 'anonymous'
        useWalletStore().markAnonymous()
        return
      }
      if (!response.ok || !parsed.json || parsed.json.ok === false) {
        throw new Error(gachaErrorMessage(parsed.json, '卡池暂时无法读取'))
      }
      publishPool(mapGachaPool(parsed.json))
      status.value = 'ready'
    } catch (cause) {
      if (token !== requestToken) return
      status.value = 'error'
      error.value = cause instanceof Error ? cause.message : '卡池暂时无法读取'
    }
  }

  async function refreshPool(): Promise<void> {
    const token = requestToken
    try {
      const response = await fetch('/api/shop/gacha', {
        credentials: 'same-origin',
        headers: { accept: 'application/json' },
        cache: 'no-store',
      })
      const parsed = await readResponse(response)
      if (token !== requestToken) return
      if (response.status === 401) {
        status.value = 'anonymous'
        pool.value = null
        useWalletStore().markAnonymous()
        return
      }
      if (response.ok && parsed.json && parsed.json.ok !== false) {
        publishPool(mapGachaPool(parsed.json))
        if (status.value === 'error') status.value = 'ready'
      }
    } catch {
      /* keep the last successful snapshot */
    }
  }

  function requestIdFor(count: 1 | 10): string {
    if (pendingPull && pendingPull.count === count && isValidRequestId(pendingPull.requestId)) {
      return pendingPull.requestId
    }
    const requestId = createRequestId()
    pendingPull = { count, requestId }
    return requestId
  }

  async function pull(count: 1 | 10): Promise<GachaActionResult> {
    const auth = useAuthStore()
    if (auth.isGuest || status.value === 'anonymous') return fail('unauthorized', gachaErrorMessage({ error: { code: 'unauthorized' } }))
    if (count !== 1 && count !== 10) return fail('invalid_count', gachaErrorMessage({ error: { code: 'invalid_count' } }))
    if (pullInFlight) return fail('', '抽卡进行中')
    pullInFlight = true
    pulling.value = count
    error.value = ''
    const requestId = requestIdFor(count)
    try {
      const response = await fetch('/api/shop/gacha/pull', {
        method: 'POST',
        credentials: 'same-origin',
        headers: jsonHeaders,
        cache: 'no-store',
        body: JSON.stringify({ count, request_id: requestId }),
      })
      const parsed = await readResponse(response)
      if (response.status === 401) {
        pendingPull = null
        status.value = 'anonymous'
        pool.value = null
        useWalletStore().markAnonymous()
        return fail('unauthorized', gachaErrorMessage(parsed.json, '请先登录后再抽卡'))
      }
      if (!response.ok || !parsed.json || parsed.json.ok === false) {
        const { code } = readApiError(parsed.json)
        // request_id is spent or unusable; next click gets a new id
        if (code === 'request_id_conflict' || code === 'invalid_request_id') pendingPull = null
        if (code === 'insufficient_tide_ash' || code === 'invalid_count' || code === 'invalid_payload') pendingPull = null
        return fail(code, gachaErrorMessage(parsed.json, '抽卡没有完成，请稍后再试'))
      }
      const result = mapGachaPullResult(parsed.json)
      lastPull.value = result
      applyBalance(result.balance)
      pool.value = applyPullToPool(pool.value, result)
      pendingPull = null
      // Replayed snapshots carry first-draw balances; always refresh live state.
      // Fresh pulls also refresh so owned / progress / shards stay in sync.
      await refreshPool()
      return { ok: true, code: '', message: '', replayed: result.replayed, result }
    } catch (cause) {
      // Keep request_id so a retry of this click stays idempotent.
      return fail('', cause instanceof Error ? cause.message : '抽卡没有完成，请稍后再试')
    } finally {
      pullInFlight = false
      pulling.value = null
    }
  }

  async function exchange(skinId: string): Promise<GachaActionResult> {
    const auth = useAuthStore()
    if (auth.isGuest || status.value === 'anonymous') return fail('unauthorized', gachaErrorMessage({ error: { code: 'unauthorized' } }))
    if (!skinId || exchanging.value) return fail('invalid_payload', '请选择要兑换的皮肤')
    exchanging.value = skinId
    error.value = ''
    try {
      const response = await fetch('/api/shop/gacha/exchange', {
        method: 'POST',
        credentials: 'same-origin',
        headers: jsonHeaders,
        cache: 'no-store',
        body: JSON.stringify({ skin_id: skinId }),
      })
      const parsed = await readResponse(response)
      if (response.status === 401) {
        status.value = 'anonymous'
        pool.value = null
        useWalletStore().markAnonymous()
        return fail('unauthorized', gachaErrorMessage(parsed.json, '请先登录后再兑换'))
      }
      const { code } = readApiError(parsed.json)
      if (response.status === 409 && code === 'skin_already_owned') {
        await refreshPool()
        return { ok: true, code, message: gachaErrorMessage(parsed.json, '已经拥有这张皮肤'), alreadyOwned: true }
      }
      if (!response.ok || !parsed.json || parsed.json.ok === false) {
        return fail(code, gachaErrorMessage(parsed.json, '兑换没有完成，请稍后再试'))
      }
      const result = mapExchangeResult(parsed.json)
      pool.value = applyExchangeToPool(pool.value, result.skin, result.shards, result.progress, result.balance)
      applyBalance(result.balance)
      await refreshPool()
      return { ok: true, code: '', message: '' }
    } catch (cause) {
      return fail('', cause instanceof Error ? cause.message : '兑换没有完成，请稍后再试')
    } finally {
      exchanging.value = null
    }
  }

  function reset(): void {
    requestToken += 1
    status.value = 'idle'
    error.value = ''
    pool.value = null
    pulling.value = null
    exchanging.value = null
    lastPull.value = null
    pendingPull = null
    pullInFlight = false
  }

  return {
    status,
    error,
    pool,
    pulling,
    exchanging,
    lastPull,
    balance,
    shards,
    prices,
    busy,
    load,
    pull,
    exchange,
    reset,
  }
})
