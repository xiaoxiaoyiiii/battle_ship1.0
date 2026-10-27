<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppOverlay from '../../components/AppOverlay.vue'
import { cardArtUrl } from '../../cards/cardArt'
import { useGameStore } from '../../stores/game'
import { sendBattleEvent } from '../../realtime/battle'
import type { Point } from './view'

// 逐艘放置与开局整盘布船是两个协议；这里仅消费服务端的局内放置请求。
const game = useGameStore()
const request = computed(() => game.state.pending_placement)
const selected = ref<Point | null>(null)
const busy = ref(false)
const error = ref('')
const names: Record<string, string> = { reinforce: '增援', revive: '死者苏生', last_stand: '绝处逢生', lanyu: '滥竽充数', shenji_redeploy: '神机妙算重部署', contract_gain: '恶魔契约' }
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
  <AppOverlay draggable v-if="request && !game.state.dice_discard_pending" id="magic-placement-panel" :priority="180" :close-on-backdrop="false" labelledby="magic-placement-title">
    <section class="magic-placement battle-prompt">
      <header class="battle-prompt__head" data-drag-handle><div><p class="battle-prompt__context">部署战舰</p><h2 id="magic-placement-title">{{ title }} · 选择部署位置</h2><span class="battle-prompt__drag-note">拖动标题可移动</span></div><img v-if="cardArtUrl(title)" class="battle-prompt__card-art" :src="cardArtUrl(title)!" alt="" draggable="false" /></header>
      <p>{{ request.message || (kind === 'last_stand' ? '只能选择原本有自己战舰的位置。' : '在自己的海域选择一个合法位置，每次部署一艘。') }}</p>
      <p class="battle-prompt__progress" data-testid="magic-placement-progress" role="status">已放置 {{ request.placed ?? 0 }} / {{ request.total ?? request.remaining }}，剩余 {{ request.remaining }} 艘</p>
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
      <p class="battle-prompt__status" :class="{ 'is-ready': selected }" role="status">{{ selected ? '已选 ' + String.fromCharCode(65 + selected.x) + (selected.y + 1) + '，确认后部署一艘。' : '请选择下方海域中可部署的格子。' }}</p>
      <footer>
        <button type="button" class="button button--primary" data-testid="magic-placement-confirm" :disabled="busy || !selected" @click="submit()">{{ busy ? '正在提交…' : '确认部署' }}</button>
        <button type="button" class="button button--ghost" data-testid="magic-placement-cancel" :disabled="busy" @click="submit(true)">{{ kind === 'last_stand' ? '交给系统放置' : '放弃剩余放置' }}</button>
      </footer>
    </section>
  </AppOverlay>
</template>

<style src="./battle-prompt.css"></style>
<style scoped>
.magic-placement { padding:24px; max-height:calc(100dvh - 24px); overflow-y:auto; }
.magic-placement p { margin:12px 0; font-size:16px; line-height:1.7; color:var(--prompt-muted); }
.magic-placement__board { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:6px; margin:18px 0; }
.magic-placement__board button { min-width:0; aspect-ratio:1; border:1px solid #365d72; border-radius:8px; background:#142e40; color:var(--prompt-cyan); cursor:pointer; font-size:24px; }
.magic-placement__board button:hover,.magic-placement__board button:focus-visible { border-color:var(--prompt-cyan); outline:2px solid rgb(116 215 233 / 20%); outline-offset:1px; }
.magic-placement__board .is-blocked { opacity:.3; cursor:not-allowed; background:#0e1b29; }
.magic-placement__board .is-selected { border-color:var(--prompt-gold); outline:2px solid var(--prompt-gold); background:rgb(224 190 112 / 14%); color:var(--prompt-gold); }
.magic-placement footer { display:flex; flex-wrap:wrap; gap:10px; margin-top:18px; }.magic-placement footer button { flex:1; }
.magic-placement .magic-placement__error { color:#ff9b9f; }
:global(.app-overlay__panel[data-testid='magic-placement-panel']) { width:min(520px,calc(100vw - 24px)); }
@media(max-width:540px) { .magic-placement { padding:18px; }.magic-placement__board { gap:5px; } }
@media(max-height:600px) and (min-width:700px) { .magic-placement { display:grid; grid-template-columns:1fr 270px; gap:8px 24px; }.magic-placement .battle-prompt__head { grid-column:1; }.magic-placement__board { grid-column:2; grid-row:1 / span 7; margin:0; align-self:center; }.magic-placement p { margin:3px 0; }.magic-placement footer { grid-column:1; margin-top:4px; }:global(.app-overlay__panel[data-testid='magic-placement-panel']) { width:min(900px,calc(100vw - 24px)); } }
</style>
