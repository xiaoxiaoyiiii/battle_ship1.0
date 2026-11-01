import { ref } from 'vue'
import { defineStore } from 'pinia'

/**
 * Shared tide-ash balance cache.
 *
 * Shop purchases and battle-pass claims both write here so the HUD, the shop
 * header and the pass screen show one number. The value is whatever the last
 * authoritative payload said — the live wallet object, or the session fixture
 * while `/api/shop` is not deployed.
 */
export type WalletSource = 'api' | 'fixture'
export type WalletStatus = 'idle' | 'loading' | 'ready' | 'anonymous'

export interface WalletSnapshot {
  balance: number
  dailyMatchGranted?: number | null
  dailyCap?: number | null
}

export const useWalletStore = defineStore('wallet', () => {
  const balance = ref<number | null>(null)
  const currency = ref<'tide_ash'>('tide_ash')
  const dailyMatchGranted = ref<number | null>(null)
  const dailyCap = ref<number | null>(null)
  const status = ref<WalletStatus>('idle')
  const source = ref<WalletSource | null>(null)

  function apply(next: WalletSnapshot, from: WalletSource): void {
    balance.value = Math.max(0, Math.floor(next.balance))
    currency.value = 'tide_ash'
    if (next.dailyMatchGranted !== undefined) dailyMatchGranted.value = next.dailyMatchGranted
    if (next.dailyCap !== undefined) dailyCap.value = next.dailyCap
    status.value = 'ready'
    source.value = from
  }

  function markLoading(): void {
    if (status.value !== 'ready') status.value = 'loading'
  }

  function markAnonymous(): void {
    balance.value = null
    dailyMatchGranted.value = null
    dailyCap.value = null
    status.value = 'anonymous'
    source.value = null
  }

  function reset(): void {
    balance.value = null
    dailyMatchGranted.value = null
    dailyCap.value = null
    status.value = 'idle'
    source.value = null
  }

  return {
    balance,
    currency,
    dailyMatchGranted,
    dailyCap,
    status,
    source,
    apply,
    markLoading,
    markAnonymous,
    reset,
  }
})
