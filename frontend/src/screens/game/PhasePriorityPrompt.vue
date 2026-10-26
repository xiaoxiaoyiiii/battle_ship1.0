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
  <AppOverlay id="game-phase-prompt" :open="open" transition-name="phase-window" :priority="210" :close-on-backdrop="false" labelledby="phase-prompt-title" @close="emit('pass')">
    <section class="phase-prompt" @scroll="hidePreview">
      <header><span class="phase-prompt__eyebrow">阶段转换时点</span><span class="phase-prompt__clock" :class="{ urgent: remaining <= 3 }" data-testid="game-phase-countdown">{{ remaining }} 秒</span></header>
      <h2 id="phase-prompt-title">对方即将{{ action }}</h2>
      <p class="phase-prompt__hint">单击选择速阶三，再次点击或点击「打出」使用。对方正在等待你的决定。</p>
      <div class="phase-prompt__cards" aria-label="可用速阶三卡牌">
        <button v-for="(card, index) in cards" :key="card.name + index" type="button" class="phase-prompt__card" :class="{ 'is-selected': selectedIndex === index }" :aria-pressed="selectedIndex === index" :data-testid="'game-phase-card-' + card.name" :disabled="busy || remaining <= 0" @mouseenter="showPreview(index, $event)" @mouseleave="hidePreview" @blur="hidePreview" @click="choose(index)">
          <img v-if="cardArtUrl(card.name)" :src="cardArtUrl(card.name)!" :alt="card.name + '卡面'" />
          <span><strong>{{ card.name }}</strong><small>速阶 {{ card.speed }}</small></span>
        </button>
      </div>
      <div class="phase-prompt__effect" :class="{ 'is-empty': !selected }" data-testid="game-phase-card-effect" aria-live="polite">
        <template v-if="selected"><strong>{{ selected.name }}</strong><p>{{ selected.description }}</p></template>
        <p v-else>单击卡牌后此处会出现效果预览，再次点击那张牌或点击下方「打出」按钮就会打出。</p>
      </div>
      <p v-if="error" class="phase-prompt__error" role="alert">{{ error }}</p>
      <button type="button" class="button button--ghost phase-prompt__collapse" data-testid="game-phase-collapse" :disabled="busy" @click="hidePreview(); emit('collapse')">暂时收起 · 查看棋盘</button>
      <footer>
        <label><input type="checkbox" data-testid="game-phase-disable" :checked="!ui.phasePrompts" @change="ui.setPhasePrompts(!(($event.target as HTMLInputElement).checked))" />以后自动放行<span>可在设置中恢复</span></label>
        <div class="phase-prompt__actions">
          <button type="button" class="button button--ghost" data-testid="game-phase-pass" :disabled="busy" @click="emit('pass')">不出牌</button>
          <button type="button" class="button button--primary" data-testid="game-phase-play" :disabled="!selected || busy || remaining <= 0" @click="playSelected">打出</button>
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

<style scoped>
:global(.app-overlay[data-overlay='game-phase-prompt']) { --z-overlay: 9500; }
:global(.app-overlay[data-overlay='game-phase-prompt'] .app-overlay__panel) { width: min(640px, calc(100vw - 32px)); padding: 0; }
:global(.phase-window-enter-active), :global(.phase-window-leave-active) { transition: opacity 220ms ease; }
:global(.phase-window-leave-active) { pointer-events: none; }
:global(.phase-window-enter-active .app-overlay__panel), :global(.phase-window-leave-active .app-overlay__panel) { transition: transform 220ms ease; }
:global(.phase-window-enter-from), :global(.phase-window-leave-to) { opacity: 0; }
:global(.phase-window-enter-from .app-overlay__panel), :global(.phase-window-leave-to .app-overlay__panel) { transform: translateY(18px); }
.phase-prompt__hover { position: fixed; z-index: 9600; bottom: auto; box-sizing: border-box; max-height: calc(100dvh - 24px); overflow: hidden; transform: none; pointer-events: none; }
.phase-prompt__hover.card-inspect-fade-enter-from, .phase-prompt__hover.card-inspect-fade-leave-to { transform: translateY(8px); }
.phase-prompt { box-sizing: border-box; width: 100%; max-height: calc(100dvh - 64px); overflow-y: auto; padding: 26px; color: var(--text-primary, #e8eaf6); }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.phase-prompt__eyebrow { color: #dac484; letter-spacing: .12em; font-size: 12px; }
.phase-prompt__clock { color: var(--text-muted, #b4bad4); font-variant-numeric: tabular-nums; }
.phase-prompt__clock.urgent { color: #ff8d97; }
h2 { margin: 14px 0 10px; font-size: 22px; }
.phase-prompt__hint { color: var(--text-muted, #b4bad4); font-size: 14px; line-height: 1.7; margin: 0 0 20px; }
.phase-prompt__cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.phase-prompt__card { display: flex; align-items: center; gap: 12px; padding: 10px; border: 1px solid var(--line-dash, #4a466e); border-radius: 10px; background: var(--surface-deck, #15192e); color: var(--text-primary); text-align: left; cursor: pointer; transition: border-color .15s, background .15s; }
.phase-prompt__card:hover, .phase-prompt__card:focus-visible { border-color: #61b8ff; background: color-mix(in srgb, #61b8ff 12%, var(--surface-deck)); outline: 2px solid #61b8ff33; }
.phase-prompt__card.is-selected { border-color: #e5bc5c; background: color-mix(in srgb, #e5bc5c 12%, var(--surface-deck)); outline: 2px solid #e5bc5c33; }
.phase-prompt__card img { width: 46px; height: 66px; object-fit: contain; }
.phase-prompt__card span { display: grid; gap: 6px; }
.phase-prompt__card strong { font-size: 15px; }
.phase-prompt__card small { color: var(--text-muted, #b4bad4); }
.phase-prompt__card:disabled { opacity: .5; cursor: wait; }
.phase-prompt__effect { box-sizing: border-box; height: 144px; overflow-y: auto; border-left: 2px solid #e5bc5c; padding: 10px 14px; margin-top: 14px; background: #8771d512; font-size: 14px; line-height: 1.7; }
.phase-prompt__effect.is-empty { display: flex; align-items: center; border-left-color: var(--line-dash, #4a466e); color: var(--text-muted, #b4bad4); }
.phase-prompt__effect p { margin: 5px 0 0; }
footer { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--line-dash, #4a466e); }
footer label { font-size: 13px; display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
footer input[type='checkbox'] { width: 16px; height: 16px; min-height: 0; flex: 0 0 16px; margin: 0; padding: 0; }
footer .button { white-space: nowrap; flex-shrink: 0; }
.phase-prompt__actions { display: flex; gap: 8px; }
.phase-prompt__collapse { min-height: 46px; padding: 10px 14px; font-size: 15px; margin-top: 16px; width: 100%; }
footer label span { color: var(--text-muted, #b4bad4); font-size: 12px; }
.phase-prompt__error { color: #ff8d97; font-size: 13px; }
.phase-prompt__sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
@media (max-width: 520px) { .phase-prompt { padding: 18px; } h2 { font-size: 19px; } footer { align-items: flex-start; flex-wrap: wrap; } footer label span { width: 100%; margin-left: 23px; } .phase-prompt__actions { margin-left: auto; } }
@media (prefers-reduced-motion: reduce) {
  :global(.phase-window-enter-active), :global(.phase-window-leave-active),
  :global(.phase-window-enter-active .app-overlay__panel), :global(.phase-window-leave-active .app-overlay__panel) { transition: none; }
  :global(.phase-window-enter-from .app-overlay__panel), :global(.phase-window-leave-to .app-overlay__panel) { transform: none; }
}
</style>
