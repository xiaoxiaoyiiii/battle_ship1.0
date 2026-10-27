<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import AppOverlay from '../../components/AppOverlay.vue'
import { cardArtUrl } from '../../cards/cardArt'
import { useUiStore } from '../../stores/ui'
import type { CardLike } from './view'

const props = defineProps<{ request: Record<string, unknown> | null; open: boolean; now: number; busy: boolean; error: string }>()
const emit = defineEmits<{ select: [card: CardLike]; pass: []; collapse: [] }>()
const ui = useUiStore()
// 关闭时保留最后一帧内容，避免淡出过程中标题和卡牌先被清空。
const lastRequest = shallowRef<Record<string, unknown>>({})
const selectedIndex = ref<number | null>(null)
const hoveredIndex = ref<number | null>(null)
const hoverPanel = ref<HTMLElement | null>(null)
const hoverPosition = ref({ left: '12px', top: '12px' })
const request = computed(() => props.request ?? lastRequest.value)
const cards = computed(() => Array.isArray(request.value.speed3_cards) ? request.value.speed3_cards as CardLike[] : [])
const selected = computed(() => selectedIndex.value === null ? null : cards.value[selectedIndex.value] ?? null)
const hovered = computed(() => hoveredIndex.value === null ? null : cards.value[hoveredIndex.value] ?? null)
const remaining = computed(() => Math.max(0, Math.ceil((Number(request.value.deadline) - props.now) / 1000)))
const countdown = computed(() => Number(request.value.countdown) || 10)
const action = computed(() => request.value.action === 'enter_end' ? '进入结束阶段' : '进入战斗阶段')

function hidePreview(): void { hoveredIndex.value = null }

async function showPreview(index: number, event: MouseEvent): Promise<void> {
  const anchor = (event.currentTarget as HTMLElement).getBoundingClientRect()
  hoveredIndex.value = index
  await nextTick()
  if (hoveredIndex.value !== index || !hoverPanel.value) return
  const { width, height } = hoverPanel.value.getBoundingClientRect()
  const gap = 14, pad = 12, vw = window.innerWidth, vh = window.innerHeight
  const candidates = [
    { x: anchor.right + gap, y: Math.max(pad, Math.min(anchor.top, vh - height - pad)) },
    { x: anchor.left - width - gap, y: Math.max(pad, Math.min(anchor.top, vh - height - pad)) },
    { x: (anchor.left + anchor.right - width) / 2, y: anchor.bottom + gap },
    { x: (anchor.left + anchor.right - width) / 2, y: anchor.top - height - gap },
  ]
  const fit = candidates.find(p => p.x >= pad && p.y >= pad && p.x + width <= vw - pad && p.y + height <= vh - pad) ?? candidates[2]
  hoverPosition.value = {
    left: Math.max(pad, Math.min(fit.x, vw - width - pad)) + 'px',
    top: Math.max(pad, Math.min(fit.y, vh - height - pad)) + 'px',
  }
}

function playSelected(): void {
  if (!selected.value || props.busy || remaining.value <= 0) return
  hidePreview()
  emit('select', selected.value)
}

function choose(index: number): void {
  if (props.busy || remaining.value <= 0) return
  if (selectedIndex.value === index) playSelected()
  else selectedIndex.value = index
}

watch(() => props.request, value => {
  if (!value) return
  if (value.token !== lastRequest.value.token) { selectedIndex.value = null; hidePreview() }
  lastRequest.value = value
}, { immediate: true })
watch(() => props.open, open => { hidePreview(); if (open) selectedIndex.value = null })
onMounted(() => window.addEventListener('resize', hidePreview))
onBeforeUnmount(() => window.removeEventListener('resize', hidePreview))
</script>

<template>
  <AppOverlay draggable id="game-phase-prompt" :open="open" transition-name="phase-window" :priority="210" :close-on-backdrop="false" labelledby="phase-prompt-title" @close="emit('pass')">
    <section class="phase-prompt battle-prompt" @scroll="hidePreview">
      <header class="battle-prompt__head" data-drag-handle>
        <div><p class="battle-prompt__context">阶段转换时点</p><h2 id="phase-prompt-title">对方即将{{ action }}</h2><span class="battle-prompt__drag-note">拖动标题可移动</span></div>
        <span class="phase-prompt__clock" :class="{ urgent: remaining <= 3 }" data-testid="game-phase-countdown"><strong>{{ remaining }}</strong> 秒</span>
      </header>
      <p class="phase-prompt__hint">你可以在此时打出速阶三卡牌。选择一张查看效果，再次点击或点击「打出」使用。</p>
      <div class="phase-prompt__cards" aria-label="可用速阶三卡牌">
        <button v-for="(card, index) in cards" :key="card.name + index" type="button" class="phase-prompt__card" :class="{ 'is-selected': selectedIndex === index }" :aria-pressed="selectedIndex === index" :data-testid="'game-phase-card-' + card.name" :disabled="busy || remaining <= 0" @mouseenter="showPreview(index, $event)" @mouseleave="hidePreview" @blur="hidePreview" @click="choose(index)">
          <img v-if="cardArtUrl(card.name)" :src="cardArtUrl(card.name)!" :alt="card.name + '卡面'" />
          <span><strong>{{ card.name }}</strong><small>速阶 {{ card.speed }}</small><small class="phase-prompt__card-state">{{ selectedIndex === index ? '已选中 · 再次点击打出' : '点击查看效果' }}</small></span>
        </button>
      </div>
      <div class="phase-prompt__effect" :class="{ 'is-empty': !selected }" data-testid="game-phase-card-effect" aria-live="polite">
        <template v-if="selected"><strong>{{ selected.name }}</strong><p>{{ selected.description }}</p></template>
        <p v-else>选择上方卡牌查看效果；不出牌可直接放行。</p>
      </div>
      <p v-if="error" class="phase-prompt__error" role="alert">{{ error }}</p>
      <button type="button" class="button button--ghost phase-prompt__collapse" data-testid="game-phase-collapse" :disabled="busy" @click="hidePreview(); emit('collapse')">暂时收起 · 查看棋盘</button>
      <footer>
        <label><input type="checkbox" data-testid="game-phase-disable" :checked="!ui.phasePrompts" @change="ui.setPhasePrompts(!(($event.target as HTMLInputElement).checked))" />以后自动放行<span>可在设置中恢复</span></label>
        <div class="phase-prompt__actions">
          <button type="button" class="button button--ghost" data-testid="game-phase-pass" :disabled="busy" @click="emit('pass')">不出牌</button>
          <button type="button" class="button button--primary" data-testid="game-phase-play" :disabled="!selected || busy || remaining <= 0" @click="playSelected">{{ busy ? '正在打出…' : '打出' }}</button>
        </div>
      </footer>
      <span class="phase-prompt__sr">本次询问共 {{ countdown }} 秒</span>
    </section>
  </AppOverlay>
  <Teleport to="body">
    <Transition name="card-inspect-fade">
      <aside v-if="open && hovered" ref="hoverPanel" class="game-card-inspect phase-prompt__hover" :style="hoverPosition" data-testid="game-phase-card-hover-preview" role="tooltip">
        <div class="game-card-inspect__art" :class="{ 'is-empty': !cardArtUrl(hovered.name) }">
          <img v-if="cardArtUrl(hovered.name)" :src="cardArtUrl(hovered.name)!" :alt="hovered.name + '卡面预览'" />
          <span v-else>{{ hovered.name }}</span>
        </div>
        <div class="game-card-inspect__body">
          <div class="game-card-inspect__head"><strong>{{ hovered.name }}</strong><span>速阶 {{ hovered.speed }} · {{ hovered.type }}</span></div>
          <p>{{ hovered.description }}</p>
          <small class="game-card-inspect__hint">单击选中，再次点击或点击「打出」使用</small>
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped src="./card-inspect.css"></style>

<style src="./battle-prompt.css"></style>
<style scoped>
:global(.app-overlay[data-overlay='game-phase-prompt']) { --z-overlay: 9500; }
:global(.app-overlay[data-overlay='game-phase-prompt'] .app-overlay__panel) { width:min(740px,calc(100vw - 24px)); padding:0; }
:global(.phase-window-enter-active), :global(.phase-window-leave-active) { transition:opacity 180ms ease; }
:global(.phase-window-leave-active) { pointer-events:none; }
:global(.phase-window-enter-from), :global(.phase-window-leave-to) { opacity:0; }
.phase-prompt { max-height:calc(100dvh - 24px); overflow-y:auto; padding:26px; }
.phase-prompt .battle-prompt__head { margin-bottom:18px; }
.phase-prompt__clock { display:flex; align-items:baseline; justify-content:center; gap:4px; min-width:74px; padding:9px 12px; border:1px solid rgb(224 190 112 / 45%); border-radius:12px; color:#e8cc8a; background:rgb(224 190 112 / 8%); white-space:nowrap; font-size:14px; font-variant-numeric:tabular-nums; }
.phase-prompt__clock strong { font-size:30px; line-height:1; }
.phase-prompt__clock.urgent { color:#ff9b9f; border-color:#ff9b9f; background:rgb(255 155 159 / 10%); }
.phase-prompt__hint { margin:0 0 18px; color:var(--prompt-muted); font-size:16px; line-height:1.7; }
.phase-prompt__cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; }
.phase-prompt__card { display:flex; align-items:center; gap:18px; padding:14px; min-width:0; border:1px solid var(--prompt-line); border-radius:12px; background:var(--prompt-deck); color:var(--prompt-text); text-align:left; cursor:pointer; }
.phase-prompt__card:hover,.phase-prompt__card:focus-visible { border-color:var(--prompt-cyan); outline:2px solid rgb(116 215 233 / 18%); outline-offset:2px; }
.phase-prompt__card.is-selected { border-color:var(--prompt-gold); background:rgb(224 190 112 / 9%); box-shadow:inset 0 0 0 1px rgb(224 190 112 / 25%); }
.phase-prompt__card img { width:90px; height:130px; object-fit:contain; flex:0 0 90px; filter:drop-shadow(0 5px 9px #0008); }
.phase-prompt__card span { display:grid; gap:9px; }
.phase-prompt__card strong { font-size:19px; }
.phase-prompt__card small { font-size:14px; color:var(--prompt-muted); }
.phase-prompt__card .phase-prompt__card-state { color:var(--prompt-cyan); line-height:1.6; }
.phase-prompt__card.is-selected .phase-prompt__card-state { color:var(--prompt-gold); }
.phase-prompt__card:disabled { opacity:.5; cursor:wait; }
.phase-prompt__effect { padding:14px 16px; margin-top:16px; border:1px solid rgb(224 190 112 / 30%); border-left:3px solid var(--prompt-gold); border-radius:8px; background:rgb(224 190 112 / 5%); font-size:16px; line-height:1.75; max-height:190px; overflow:auto; }
.phase-prompt__effect.is-empty { border-color:var(--prompt-line); border-left-color:var(--prompt-line); background:transparent; color:var(--prompt-muted); font-size:15px; }
.phase-prompt__effect p { margin:4px 0 0; }
.phase-prompt__effect.is-empty p { margin:0; }
footer { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:18px; margin-top:20px; padding-top:18px; border-top:1px solid var(--prompt-line); }
footer label { display:flex; flex-wrap:wrap; align-items:center; gap:8px; font-size:15px; }
footer input[type='checkbox'] { width:18px; height:18px; min-height:0; flex:0 0 18px; margin:0; padding:0; accent-color:var(--prompt-cyan); }
footer label span { width:100%; padding-left:26px; color:var(--prompt-muted); font-size:13px; }
.phase-prompt__actions { display:flex; gap:10px; margin-left:auto; }
.phase-prompt__actions .button { min-width:94px; }
.phase-prompt__collapse { width:100%; margin-top:16px; }
.phase-prompt__error { color:#ff9b9f; font-size:15px; }
.phase-prompt__sr { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
.phase-prompt__hover { position:fixed; z-index:9600; bottom:auto; box-sizing:border-box; max-height:calc(100dvh - 24px); overflow:hidden; transform:none; pointer-events:none; }
.phase-prompt__hover.card-inspect-fade-enter-from,.phase-prompt__hover.card-inspect-fade-leave-to { transform:translateY(8px); }
@media(max-width:520px) { .phase-prompt { padding:18px; }.phase-prompt__cards { grid-template-columns:1fr; }.phase-prompt__card img { width:76px; height:110px; flex-basis:76px; }.phase-prompt__clock { min-width:62px; padding:8px; }.phase-prompt__clock strong { font-size:26px; }.phase-prompt__actions { width:100%; }.phase-prompt__actions .button { flex:1; } }
@media(prefers-reduced-motion:reduce) { :global(.phase-window-enter-active),:global(.phase-window-leave-active) { transition:none; } }
</style>
