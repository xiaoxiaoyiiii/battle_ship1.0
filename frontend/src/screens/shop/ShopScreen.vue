<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import TideAshBadge from '../../components/TideAshBadge.vue'
import { useAuthStore } from '../../stores/auth'
import { shopKindLabel, useShopStore, type ShopItem } from '../../stores/shop'
import { useUiStore } from '../../stores/ui'
import ShopItemPreview from './ShopItemPreview.vue'

const auth = useAuthStore()
const store = useShopStore()
const ui = useUiStore()
const feedback = ref('')
const feedbackOk = ref(false)
const pinnedId = ref<string | null>(null)
const hoverId = ref<string | null>(null)
const previewRoot = ref<HTMLElement | null>(null)
const fineHover = ref(false)
let hoverMedia: MediaQueryList | null = null

const previewItem = computed(() => {
  const id = pinnedId.value || hoverId.value
  if (!id) return null
  return store.items.find((item) => item.id === id) ?? null
})

function shortOf(item: ShopItem): boolean {
  return !item.owned && item.purchasable && store.balance !== null && item.price > store.balance
}
function buyDisabled(item: ShopItem): boolean {
  return item.owned || !item.purchasable || store.purchasing !== null
}
function buyLabel(item: ShopItem): string {
  if (item.owned) return '已拥有'
  if (!item.purchasable) return '暂不可购'
  if (store.purchasing === item.id) return '购买中…'
  if (shortOf(item)) return '徽记不足'
  return '购买'
}
async function buy(item: ShopItem): Promise<void> {
  if (item.owned || !item.purchasable) return
  const result = await store.purchase(item.id)
  feedbackOk.value = result.ok
  feedback.value = result.ok ? `已购入${item.name}` : result.message
  ui.notify({
    code: `shop-buy-${item.id}-${result.reason || 'fail'}`,
    tone: result.ok ? 'success' : 'warning',
    message: feedback.value,
    ttl: 2600,
  })
}
function load(): void { feedback.value = ''; void store.load(true) }

function syncHoverMedia(): void {
  fineHover.value = Boolean(hoverMedia?.matches)
}
function toggle(item: ShopItem): void {
  const next = pinnedId.value === item.id ? null : item.id
  pinnedId.value = next
  if (!next || !window.matchMedia('(max-width: 720px)').matches) return
  void nextTick(() => {
    previewRoot.value?.scrollIntoView({
      block: 'start',
      behavior: ui.motion === 'reduced' ? 'auto' : 'smooth',
    })
  })
}
function previewHover(item: ShopItem): void {
  if (!fineHover.value) return
  hoverId.value = item.id
}
function clearHover(item: ShopItem): void {
  if (hoverId.value === item.id) hoverId.value = null
}

onMounted(() => {
  hoverMedia = window.matchMedia('(hover: hover) and (pointer: fine)')
  syncHoverMedia()
  hoverMedia.addEventListener('change', syncHoverMedia)
  void store.load(true)
})
onBeforeUnmount(() => {
  hoverMedia?.removeEventListener('change', syncHoverMedia)
})
watch(() => auth.isGuest, (guest) => {
  if (guest) {
    pinnedId.value = null
    hoverId.value = null
    store.reset()
  }
  void store.load(true)
})
watch(() => store.items, (items) => {
  if (pinnedId.value && !items.some((item) => item.id === pinnedId.value)) pinnedId.value = null
  if (hoverId.value && !items.some((item) => item.id === hoverId.value)) hoverId.value = null
})
</script>

<template>
  <section class="screen shop" data-screen="shop" data-testid="screen-shop" aria-labelledby="shop-title">
    <div class="shop__shell">
      <header class="shop__hero">
        <div>
          <p class="shop__eyebrow">潮汐徽记 · 常驻外观</p>
          <h1 id="shop-title">商店</h1>
          <p class="shop__subtitle">常驻外观以潮汐徽记标价。已拥有的外观会留在这里，不能再买一次。</p>
        </div>
        <div data-testid="shop-balance">
          <TideAshBadge :linked="false" />
        </div>
      </header>

      <div v-if="auth.isGuest || store.status === 'anonymous'" class="shop__login" data-testid="shop-login">
        <h2>登录后使用潮汐徽记</h2>
        <p>商店与徽记余额都绑定账号。</p>
        <button type="button" class="button button--primary" @click="auth.open('login', '登录后查看商店')">登录 / 注册</button>
      </div>
      <div v-else-if="store.status === 'loading'" class="shop__state" role="status">正在读取商店…</div>
      <div v-else-if="store.status === 'error'" class="shop__state shop__state--error" role="alert">
        {{ store.error || '商店暂时无法读取。' }}
        <button type="button" class="button button--ghost" @click="load">重试</button>
      </div>
      <div v-else-if="!store.items.length" class="shop__state">货架暂时是空的。</div>
      <template v-else>
        <p v-if="feedback" class="shop__feedback" :class="{ 'is-error': !feedbackOk }" data-testid="shop-feedback" role="status">{{ feedback }}</p>
        <div class="shop__layout">
          <div class="shop__grid">
            <article
              v-for="item in store.items"
              :key="item.id"
              class="shop-card"
              :class="{ 'is-owned': item.owned, 'is-selected': pinnedId === item.id, 'is-previewing': previewItem?.id === item.id && pinnedId !== item.id }"
              :data-testid="'shop-item-' + item.id"
              @pointerenter="previewHover(item)"
              @pointerleave="clearHover(item)"
            >
              <button
                type="button"
                class="shop-card__select"
                :aria-pressed="pinnedId === item.id"
                :data-testid="'shop-select-' + item.id"
                @click="toggle(item)"
              >
                <p class="shop-card__kind">{{ shopKindLabel(item.kind) }}</p>
                <h2>{{ item.name }}</h2>
                <p class="shop-card__price">{{ item.price.toLocaleString() }} 潮汐徽记</p>
              </button>
              <button
                type="button"
                class="shop-card__buy"
                :class="{ 'is-short': shortOf(item), 'is-owned': item.owned }"
                :data-testid="'shop-buy-' + item.id"
                :disabled="buyDisabled(item)"
                @click.stop="buy(item)"
              >{{ buyLabel(item) }}</button>
            </article>
          </div>
          <aside ref="previewRoot" class="shop-preview" data-testid="shop-preview" aria-live="polite" aria-label="效果预览">
            <p class="shop-preview__eyebrow">效果预览</p>
            <template v-if="previewItem">
              <p class="shop-preview__kind">{{ shopKindLabel(previewItem.kind) }}</p>
              <h2>{{ previewItem.name }}</h2>
              <ShopItemPreview :item="previewItem" />
              <p class="shop-preview__hint" data-testid="shop-preview-hint">
                {{ pinnedId === previewItem.id ? '已选中，再点一次取消' : '悬停预览，点一下选中' }}
              </p>
            </template>
            <p v-else class="shop-preview__empty" data-testid="shop-preview-empty">点一张商品，这里会显示它的效果。鼠标悬停也能先看一眼。</p>
          </aside>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.shop { padding: 28px clamp(18px, 5vw, 72px) 42px; align-items: stretch; }
.shop__shell { width: min(1480px, 100%); margin: 0 auto; }
.shop__hero { display: flex; align-items: end; justify-content: space-between; gap: 24px; padding-bottom: 22px; }
.shop__hero h1 { margin: 0 0 8px; color: var(--text-primary); font-size: 32px; letter-spacing: -0.03em; }
.shop__eyebrow { margin: 0 0 5px; color: var(--gold-strong); font-size: 10px; letter-spacing: 0.16em; }
.shop__subtitle, .shop__state, .shop__login p { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.shop__login, .shop__state { padding: 24px; border: 1px solid var(--border-strong); border-radius: 12px; background: var(--surface-deck); }
.shop__login h2 { margin: 0 0 8px; color: var(--text-primary); font-size: 19px; }
.shop__login .button { margin-top: 16px; }
.shop__state--error { color: var(--role-warning); }
.shop__feedback { margin: 0 0 14px; padding: 10px 12px; border-radius: 8px; color: var(--role-success); background: var(--role-success-soft); font-size: 13px; }
.shop__feedback.is-error { color: var(--role-warning); background: var(--gold-soft); }
.shop__layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 300px); gap: 16px; align-items: start; }
.shop__grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 12px; align-content: start; }
.shop-preview { position: sticky; top: 16px; display: grid; align-content: start; gap: 8px; min-height: 220px; padding: 16px; border: 1px solid var(--border-strong); border-radius: 12px; background: var(--surface-deck); scroll-margin-top: 12px; }
.shop-preview h2 { margin: 0; color: var(--text-primary); font-size: 18px; }
.shop-preview__eyebrow { margin: 0; color: var(--gold-strong); font-size: 10px; letter-spacing: 0.16em; }
.shop-preview__kind { margin: 0; color: var(--role-action); font-size: 11px; letter-spacing: 0.08em; }
.shop-preview__hint, .shop-preview__empty { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.shop-card { display: grid; align-content: start; gap: 8px; min-width: 0; padding: 16px; border: 1px solid var(--border-subtle); border-radius: 12px; background: var(--surface-sea); }
.shop-card.is-previewing { border-color: color-mix(in srgb, var(--role-action) 55%, var(--border-subtle)); }
.shop-card.is-selected { border-color: var(--role-action); box-shadow: inset 0 0 0 1px var(--role-action); }
.shop-card.is-owned.is-selected { opacity: 0.92; filter: none; }
.shop-card__select { display: grid; gap: 8px; width: 100%; margin: 0; padding: 0; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.shop-card__select:focus-visible { outline: 2px solid var(--role-action); outline-offset: 3px; border-radius: 4px; }
.shop-card h2 { margin: 0; color: var(--text-primary); font-size: 18px; }
.shop-card__kind { margin: 0; color: var(--role-action); font-size: 11px; letter-spacing: 0.08em; }
.shop-card__price { margin: 0; color: var(--gold-strong); font-size: 14px; font-variant-numeric: tabular-nums; }
.shop-card__buy { justify-self: start; padding: 6px 12px; border: 1px solid var(--border-strong); border-radius: 6px; color: var(--role-action); background: transparent; font: inherit; font-size: 13px; cursor: pointer; }
.shop-card__buy:hover:not(:disabled) { border-color: var(--role-action); background: var(--role-action-soft); }
.shop-card__buy:focus-visible { outline: 2px solid var(--role-action); outline-offset: 2px; }
.shop-card__buy:disabled { color: var(--text-muted); cursor: default; }
.shop-card__buy.is-short { color: var(--role-warning); border-color: color-mix(in srgb, var(--role-warning) 55%, var(--border-subtle)); }
.shop-card.is-owned { opacity: 0.58; filter: grayscale(0.45); }
.shop-card.is-owned .shop-card__buy { color: var(--text-secondary); }
@media (max-width: 720px) {
  .shop { padding: 18px 14px 28px; }
  .shop__hero { align-items: flex-start; flex-direction: column; }
  .shop__hero h1 { font-size: 27px; }
  .shop__layout { grid-template-columns: 1fr; }
  .shop__grid { grid-template-columns: 1fr; }
  .shop__preview { position: static; order: 2; }
}
</style>
