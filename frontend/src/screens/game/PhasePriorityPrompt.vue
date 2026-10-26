<script setup lang="ts">
import { computed, ref } from 'vue'
import AppOverlay from '../../components/AppOverlay.vue'
import { cardArtUrl } from '../../cards/cardArt'
import { useUiStore } from '../../stores/ui'
import type { CardLike } from './view'

const props = defineProps<{ request: Record<string, unknown>; now: number; busy: boolean; error: string }>()
const emit = defineEmits<{ select: [card: CardLike]; pass: [] }>()
const ui = useUiStore()
const inspected = ref<CardLike | null>(null)
const cards = computed(() => Array.isArray(props.request.speed3_cards) ? props.request.speed3_cards as CardLike[] : [])
const remaining = computed(() => Math.max(0, Math.ceil((Number(props.request.deadline) - props.now) / 1000)))
const countdown = computed(() => Number(props.request.countdown) || 10)
const action = computed(() => props.request.action === 'enter_end' ? '进入结束阶段' : '进入战斗阶段')
</script>

<template>
  <AppOverlay id="game-phase-prompt" :priority="210" :close-on-backdrop="false" labelledby="phase-prompt-title" @close="emit('pass')">
    <section class="phase-prompt">
      <header><span class="phase-prompt__eyebrow">阶段转换时点</span><span class="phase-prompt__clock" :class="{ urgent: remaining <= 3 }" data-testid="game-phase-countdown">{{ remaining }} 秒</span></header>
      <h2 id="phase-prompt-title">对方即将{{ action }}</h2>
      <p class="phase-prompt__hint">选择一张速阶三先行出牌，或让对方继续。对方正在等待你的决定。</p>
      <div class="phase-prompt__cards" aria-label="可用速阶三卡牌">
        <button v-for="(card, index) in cards" :key="card.name + index" type="button" class="phase-prompt__card" :data-testid="'game-phase-card-' + card.name" :disabled="busy || remaining <= 0" @mouseenter="inspected = card" @focus="inspected = card" @click="emit('select', card)">
          <img v-if="cardArtUrl(card.name)" :src="cardArtUrl(card.name)!" :alt="card.name + '卡面'" />
          <span><strong>{{ card.name }}</strong><small>速阶 {{ card.speed }}</small></span>
        </button>
      </div>
      <div v-if="inspected" class="phase-prompt__effect" data-testid="game-phase-card-effect"><strong>{{ inspected.name }}</strong><p>{{ inspected.description }}</p></div>
      <p v-if="error" class="phase-prompt__error" role="alert">{{ error }}</p>
      <footer>
        <label><input type="checkbox" data-testid="game-phase-disable" :checked="!ui.phasePrompts" @change="ui.setPhasePrompts(!(($event.target as HTMLInputElement).checked))" />以后自动放行<span>可在设置中恢复</span></label>
        <button type="button" class="button button--ghost" data-testid="game-phase-pass" :disabled="busy" @click="emit('pass')">不出牌</button>
      </footer>
      <span class="phase-prompt__sr">本次询问共 {{ countdown }} 秒</span>
    </section>
  </AppOverlay>
</template>

<style scoped>
:global(.app-overlay[data-overlay='game-phase-prompt']) { --z-overlay: 9500; }
:global(.app-overlay[data-overlay='game-phase-prompt'] .app-overlay__panel) { width: min(640px, calc(100vw - 32px)); padding: 0; }
.phase-prompt { box-sizing: border-box; width: 100%; max-height: calc(100dvh - 64px); overflow-y: auto; padding: 26px; color: var(--text-primary, #e8eaf6); }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.phase-prompt__eyebrow { color: #dac484; letter-spacing: .12em; font-size: 12px; }
.phase-prompt__clock { color: var(--text-muted, #b4bad4); font-variant-numeric: tabular-nums; }
.phase-prompt__clock.urgent { color: #ff8d97; }
h2 { margin: 14px 0 10px; font-size: 22px; }
.phase-prompt__hint { color: var(--text-muted, #b4bad4); font-size: 14px; line-height: 1.7; margin: 0 0 20px; }
.phase-prompt__cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.phase-prompt__card { display: flex; align-items: center; gap: 12px; padding: 10px; border: 1px solid var(--line-dash, #4a466e); border-radius: 10px; background: var(--surface-deck, #15192e); color: var(--text-primary); text-align: left; cursor: pointer; transition: border-color .15s, background .15s; }
.phase-prompt__card:hover, .phase-prompt__card:focus-visible { border-color: var(--role-action); background: color-mix(in srgb, var(--role-action) 12%, var(--surface-deck)); outline: 2px solid #8a6bda44; }
.phase-prompt__card img { width: 46px; height: 66px; object-fit: contain; }
.phase-prompt__card span { display: grid; gap: 6px; }
.phase-prompt__card strong { font-size: 15px; }
.phase-prompt__card small { color: var(--text-muted, #b4bad4); }
.phase-prompt__card:disabled { opacity: .5; cursor: wait; }
.phase-prompt__effect { border-left: 2px solid #b6a1ff; padding: 10px 14px; margin-top: 14px; background: #8771d512; font-size: 14px; line-height: 1.7; }
.phase-prompt__effect p { margin: 5px 0 0; }
footer { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--line-dash, #4a466e); }
footer label { font-size: 13px; display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
footer input[type='checkbox'] { width: 16px; height: 16px; min-height: 0; flex: 0 0 16px; margin: 0; padding: 0; }
footer .button { white-space: nowrap; flex-shrink: 0; }
footer label span { color: var(--text-muted, #b4bad4); font-size: 12px; }
.phase-prompt__error { color: #ff8d97; font-size: 13px; }
.phase-prompt__sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
@media (max-width: 520px) { .phase-prompt { padding: 18px; } h2 { font-size: 19px; } footer { align-items: flex-start; } footer label span { width: 100%; margin-left: 23px; } }
</style>
