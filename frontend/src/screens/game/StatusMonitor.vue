<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

interface Badge { key: string; label: string; description: string; expires: string }
const props = defineProps<{ side: 'self' | 'opponent'; badges: Badge[] }>()
const root = ref<HTMLElement | null>(null)
const detail = ref<HTMLElement | null>(null)
const active = ref<Badge | null>(null)
const pinned = ref(false)
const position = ref({ left: '0px', top: '0px' })
function show(badge: Badge, event: Event, pin = false): void {
  if (pin && pinned.value && active.value?.key === badge.key) { close(); return }
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  position.value = { left: Math.max(8, Math.min(rect.left, window.innerWidth - 288)) + 'px', top: Math.min(rect.bottom + 8, window.innerHeight - 160) + 'px' }
  active.value = badge
  pinned.value = pin
}
function close(): void { active.value = null; pinned.value = false }
watch(() => props.badges, badges => {
  if (!active.value) return
  const current = badges.find(badge => badge.key === active.value?.key)
  if (current) active.value = current
  else close()
})
function outside(event: PointerEvent): void {
  if (!root.value?.contains(event.target as Node) && !detail.value?.contains(event.target as Node)) close()
}
function escape(event: KeyboardEvent): void { if (event.key === 'Escape') close() }
onMounted(() => { document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape) })
onBeforeUnmount(() => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) })
</script>

<template>
  <div ref="root" class="captain-effects" :aria-label="side === 'self' ? '己方持续效果' : '对方持续效果'">
    <button v-for="badge in props.badges" :key="badge.key" type="button" class="captain-effects__icon"
      :data-testid="'game-effect-' + side + '-' + badge.key" :aria-label="badge.label + '：' + badge.description"
      :aria-expanded="active?.key === badge.key" @mouseenter="show(badge, $event)" @mouseleave="!pinned && close()"
      @focus="show(badge, $event)" @blur="!pinned && close()" @click="show(badge, $event, true)">
      {{ badge.label.slice(0, 2) }}
    </button>
    <span v-if="!badges.length" class="captain-effects__empty">暂无持续效果</span>
  </div>
  <Teleport to="body">
    <section v-if="active" ref="detail" class="captain-effect-detail" :style="position" role="tooltip" :data-testid="'game-effect-detail-' + side">
      <strong>{{ active.label }}</strong><p>{{ active.description }}</p><small v-if="active.expires">{{ active.expires }}</small>
    </section>
  </Teleport>
</template>

<style scoped>
.captain-effects { display:flex; align-items:center; gap:4px; width:100%; height:24px; min-height:24px; overflow-x:auto; overflow-y:hidden; scrollbar-width:thin; }
.captain-effects__icon { flex:0 0 30px; height:23px; padding:0; border:1px solid color-mix(in srgb,var(--role-self) 45%,transparent); border-radius:6px; background:var(--surface-deck); color:var(--text-primary); font:inherit; font-size:10px; cursor:pointer; }
.captain-effects__icon:hover,.captain-effects__icon:focus-visible { outline:1px solid var(--gold-strong); outline-offset:-1px; }
.captain-effects__empty { color:var(--text-tertiary); font-size:10px; white-space:nowrap; }
.captain-effect-detail { position:fixed; width:min(280px,calc(100vw - 16px)); max-height:150px; overflow:auto; z-index:9100; padding:12px 14px; border:1px solid var(--border-strong); border-radius:10px; background:var(--surface-chamber); color:var(--text-primary); box-shadow:var(--shadow-panel); font-size:13px; }
.captain-effect-detail p { margin:6px 0; line-height:1.6; }.captain-effect-detail small { color:var(--gold-strong); }
</style>
