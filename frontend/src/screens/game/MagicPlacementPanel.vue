<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppOverlay from '../../components/AppOverlay.vue'
import { useGameStore } from '../../stores/game'
import { sendBattleEvent } from '../../realtime/battle'
import type { Point } from './view'

// 逐艘放置与开局整盘布船是两个协议；这里仅消费服务端的局内放置请求。
const game = useGameStore()
const request = computed(() => game.state.pending_placement)
const selected = ref<Point | null>(null)
const busy = ref(false)
const error = ref('')
const names: Record<string, string> = { reinforce: '增援', revive: '死者苏生', last_stand: '绝处逢生', lanyu: '滥竽充数', shenji_redeploy: '神机妙算重部署' }
const kind = computed(() => String(request.value?.kind ?? ''))
const title = computed(() => names[kind.value] || '部署战舰')
function coordinates(value: unknown): Point | null {
  const raw = Array.isArray(value) ? { x: value[0], y: value[1] } : value as Record<string, unknown> | null
  if (!raw || !Number.isInteger(raw.x) || !Number.isInteger(raw.y)) return null
  return { x: Number(raw.x), y: Number(raw.y) }
}
function keys(values: unknown[]): Set<string> {
  return new Set(values.map(coordinates).filter((p): p is Point => p !== null).map(p => `${p.x}-${p.y}`))
}
const blocked = computed(() => keys(game.state.pending_placement_blocked))
const allowed = computed(() => keys(game.state.pending_placement_allowed))
const cells = computed(() => Array.from({ length: 36 }, (_, index) => {
  const x = index % 6, y = Math.floor(index / 6), key = `${x}-${y}`
  // 绝处逢生限定原船位；其他模式的 allowed 是服务端例外信息，不是通用白名单。
  return { x, y, key, blocked: kind.value === 'last_stand' ? !allowed.value.has(key) : blocked.value.has(key) }
}))
watch(() => [game.state.room_id, kind.value, request.value?.remaining, request.value?.placed], () => {
  selected.value = null
  error.value = ''
})
function choose(cell: typeof cells.value[number]): void {
  if (busy.value) return
  if (cell.blocked) { error.value = '这个位置不能部署，请选择高亮的合法格。'; return }
  selected.value = { x: cell.x, y: cell.y }
  error.value = ''
}
async function submit(cancel = false): Promise<void> {
  if (busy.value || !request.value || (!cancel && !selected.value)) return
  busy.value = true
  error.value = ''
  try {
    const ack = await sendBattleEvent(cancel ? 'cancel_placement' : 'confirm_reinforcement_position', {
      room_id: game.state.room_id, player_id: game.state.player_id,
      ...(cancel ? {} : { position: { ...selected.value! } }),
    })
    if (ack.status !== 'success') error.value = ack.message || '部署失败，请调整位置后重试。'
    // 只让 placement_request / placement_done 或 room_sync 改进度，拒绝时保留请求。
  } catch { error.value = '连接不稳定，放置请求仍保留，请重试。' }
  finally { busy.value = false }
}
</script>

<template>
  <AppOverlay v-if="request && !game.state.dice_discard_pending" id="magic-placement-panel" :priority="180" :close-on-backdrop="false" labelledby="magic-placement-title">
    <section class="magic-placement">
      <h2 id="magic-placement-title">{{ title }} · 选择部署位置</h2>
      <p>{{ request.message || (kind === 'last_stand' ? '只能选择原本有自己战舰的位置。' : '在自己的海域选择一个合法位置，每次部署一艘。') }}</p>
      <p data-testid="magic-placement-progress" role="status">已放置 {{ request.placed ?? 0 }} / {{ request.total ?? request.remaining }}，剩余 {{ request.remaining }} 艘</p>
      <div class="magic-placement__board" role="group" aria-label="自己的海域部署格">
        <button v-for="cell in cells" :key="cell.key" type="button" :data-testid="'magic-place-cell-' + cell.x + '-' + cell.y"
          :aria-label="'第' + (cell.x + 1) + '列第' + (cell.y + 1) + '行，' + (cell.blocked ? '不可部署' : '可部署')"
          :aria-disabled="cell.blocked || busy" :aria-pressed="selected?.x === cell.x && selected?.y === cell.y"
          :class="{ 'is-blocked': cell.blocked, 'is-selected': selected?.x === cell.x && selected?.y === cell.y }" @click="choose(cell)">
          <span aria-hidden="true">{{ cell.blocked ? '×' : selected?.x === cell.x && selected?.y === cell.y ? '■' : '' }}</span>
        </button>
      </div>
      <p v-if="error" class="magic-placement__error" data-testid="magic-placement-error" role="alert">{{ error }}</p>
      <p v-if="kind === 'last_stand'">交给系统放置时，服务端会从合法位置自动选定最后一艘。</p>
      <footer>
        <button type="button" class="button" data-testid="magic-placement-confirm" :disabled="busy || !selected" @click="submit()">{{ busy ? '正在提交…' : '确认部署' }}</button>
        <button type="button" class="button button--ghost" data-testid="magic-placement-cancel" :disabled="busy" @click="submit(true)">{{ kind === 'last_stand' ? '交给系统放置' : '放弃剩余放置' }}</button>
      </footer>
    </section>
  </AppOverlay>
</template>

<style scoped>
.magic-placement { padding:20px; }.magic-placement h2 { margin:0 0 12px; font-size:18px; }.magic-placement p { margin:8px 0; font-size:13px; line-height:1.6; color:var(--text-secondary); }
.magic-placement__board { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:4px; margin:12px 0; }
.magic-placement__board button { min-width:0; aspect-ratio:1; border:1px solid var(--board-border); border-radius:6px; background:var(--cell-bg); color:var(--text-primary); cursor:pointer; }
.magic-placement__board .is-blocked { opacity:.4; cursor:not-allowed; }.magic-placement__board .is-selected { outline:2px solid var(--role-self); background:var(--role-self-soft); }
.magic-placement footer { display:flex; gap:8px; }.magic-placement footer button { flex:1; min-height:40px; }.magic-placement .magic-placement__error { color:var(--role-warning); }
:global(.app-overlay__panel[data-testid='magic-placement-panel']) { width:min(420px,calc(100vw - 24px)); max-height:calc(100dvh - 24px); }
@media(max-height:480px) and (min-width:640px) { .magic-placement { display:grid; grid-template-columns:1fr 230px; gap:4px 16px; padding:12px; }.magic-placement__board { grid-column:2; grid-row:1 / span 6; margin:0; }.magic-placement footer { grid-column:1; }:global(.app-overlay__panel[data-testid='magic-placement-panel']) { width:min(720px,calc(100vw - 24px)); } }
</style>
