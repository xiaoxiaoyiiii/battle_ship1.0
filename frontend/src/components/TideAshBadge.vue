<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useWalletStore } from '../stores/wallet'

withDefaults(defineProps<{ linked?: boolean }>(), { linked: true })

const auth = useAuthStore()
const wallet = useWalletStore()

const visible = computed(() => !auth.isGuest && wallet.status !== 'anonymous')
const text = computed(() => {
  if (wallet.balance !== null) return wallet.balance.toLocaleString()
  return '…'
})
const title = computed(() => {
  if (wallet.dailyCap !== null && wallet.dailyMatchGranted !== null) {
    return `潮汐徽记 · 今日对局 ${wallet.dailyMatchGranted}/${wallet.dailyCap}`
  }
  return '潮汐徽记'
})
</script>

<template>
  <component
    :is="linked ? 'router-link' : 'span'"
    v-if="visible"
    class="tide-badge"
    :to="linked ? { name: 'shop' } : undefined"
    data-testid="tide-ash-badge"
    :title="title"
    :aria-label="`潮汐徽记 ${text}`"
  >
    <span class="tide-badge__mark" aria-hidden="true">潮</span>
    <span class="tide-badge__value" data-testid="tide-ash-balance">{{ text }}</span>
  </component>
</template>

<style scoped>
.tide-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 0 10px 0 5px;
  border: 1px solid color-mix(in srgb, var(--gold) 48%, var(--border-subtle));
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--gold) 14%, var(--surface-deck));
  color: var(--text-primary);
  text-decoration: none;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.tide-badge:hover { border-color: var(--gold); }
.tide-badge__mark {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--gold-soft);
  color: var(--gold-strong);
  font-size: 11px;
  font-weight: 700;
}
.tide-badge__value { font-weight: 650; }
</style>
