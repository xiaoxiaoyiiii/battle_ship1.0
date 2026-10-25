<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useMatchStore } from '../../stores/match'

const props = defineProps<{
  selfId: string
  selfName: string
  opponentName: string
}>()

const match = useMatchStore()
const roll = computed(() => match.diceRoll)
const displayRoll = ref(1)
const displayOpponentRoll = ref(6)
const revealed = ref(false)
const lockEl = ref<HTMLElement | null>(null)
let animationTimer: number | null = null
let revealTimer: number | null = null
let spinTimer: number | null = null

const casterName = computed(() => {
  if (!roll.value) return ''
  return roll.value.caster === props.selfId ? props.selfName : props.opponentName
})
const isDuel = computed(() => roll.value?.opponentRoll !== null)
const title = computed(() => isDuel.value ? '拼点判定' : '摇骰子判定')
const phaseText = computed(() => {
  if (revealed.value) return isDuel.value ? '点数已揭晓，正在结算效果' : '点数已揭晓，正在结算效果'
  return isDuel.value ? '双方同时摇骰，暂时无法操作' : '骰子滚动中，暂时无法操作'
})

function clearTimers(): void {
  if (animationTimer !== null) window.clearTimeout(animationTimer)
  if (revealTimer !== null) window.clearTimeout(revealTimer)
  if (spinTimer !== null) window.clearInterval(spinTimer)
  animationTimer = null
  revealTimer = null
  spinTimer = null
}

function startAnimation(next: NonNullable<typeof roll.value>): void {
  clearTimers()
  revealed.value = false
  displayRoll.value = 1
  displayOpponentRoll.value = 6
  spinTimer = window.setInterval(() => {
    displayRoll.value = 1 + Math.floor(Math.random() * 6)
    displayOpponentRoll.value = 1 + Math.floor(Math.random() * 6)
  }, 105)
  const revealAt = Math.max(1500, next.durationMs - 950)
  revealTimer = window.setTimeout(() => {
    revealed.value = true
    displayRoll.value = next.roll ?? 1
    displayOpponentRoll.value = next.opponentRoll ?? 6
    if (spinTimer !== null) window.clearInterval(spinTimer)
    spinTimer = null
  }, revealAt)
  animationTimer = window.setTimeout(() => {
    match.finishDiceRoll()
  }, next.durationMs)
}

watch(() => roll.value?.id, () => {
  if (roll.value) {
    startAnimation(roll.value)
    void nextTick(() => lockEl.value?.focus())
  } else clearTimers()
}, { immediate: true })

onBeforeUnmount(clearTimers)
</script>

<template>
  <Teleport to="body">
    <div
      v-if="roll"
      ref="lockEl"
      class="dice-lock"
      data-testid="dice-roll-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="判定动画进行中"
      tabindex="0"
      @click.stop
      @pointerdown.stop.prevent
      @contextmenu.stop.prevent
      @keydown.stop.prevent
    >
      <section :key="roll.id" class="dice-lock__panel" :class="{ 'is-revealed': revealed }" data-testid="dice-roll-panel">
        <p class="dice-lock__eyebrow">判定魔法 · {{ roll.card }}</p>
        <h2 class="dice-lock__title">{{ title }}</h2>
        <p class="dice-lock__caster">{{ casterName }} 发动判定</p>

        <div class="dice-lock__stage" :class="{ 'is-duel': isDuel }">
          <div class="dice-lock__player">
            <span class="dice-lock__player-name">{{ isDuel ? '打出者' : '判定结果' }}</span>
            <div class="dice-lock__die" :class="{ 'is-rolling': !revealed }" aria-live="polite" data-testid="dice-roll-value">
              <span>{{ displayRoll }}</span>
            </div>
            <strong v-if="revealed" class="dice-lock__result">{{ roll.roll }} 点</strong>
          </div>
          <span v-if="isDuel" class="dice-lock__versus">VS</span>
          <div v-if="isDuel" class="dice-lock__player">
            <span class="dice-lock__player-name">对手</span>
            <div class="dice-lock__die dice-lock__die--opponent" :class="{ 'is-rolling': !revealed }" aria-live="polite" data-testid="dice-roll-opponent-value">
              <span>{{ displayOpponentRoll }}</span>
            </div>
            <strong v-if="revealed" class="dice-lock__result">{{ roll.opponentRoll }} 点</strong>
          </div>
        </div>

        <p class="dice-lock__phase">{{ phaseText }}</p>
        <p v-if="revealed && roll.effectText" class="dice-lock__effect">{{ roll.effectText }}</p>
        <div class="dice-lock__progress" aria-hidden="true" :style="{ '--dice-duration': roll.durationMs + 'ms' }"><span /></div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dice-lock {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(3, 7, 18, 0.76);
  backdrop-filter: blur(8px) saturate(0.78);
  pointer-events: auto;
  touch-action: none;
  user-select: none;
}

.dice-lock__panel {
  width: min(620px, calc(100vw - 32px));
  min-height: 390px;
  padding: 28px 32px 24px;
  border: 1px solid color-mix(in srgb, var(--gold-strong) 68%, var(--panel-line));
  border-radius: 18px;
  background: radial-gradient(circle at 50% 0%, rgba(124, 92, 240, 0.2), transparent 56%), var(--surface-chamber, #151a30);
  box-shadow: 0 30px 90px rgba(0, 0, 0, 0.62), 0 0 0 1px rgba(201, 162, 76, 0.12);
  text-align: center;
}

.dice-lock__eyebrow { margin: 0; color: var(--gold-strong); font-size: 12px; letter-spacing: .16em; }
.dice-lock__title { margin: 8px 0 4px; color: var(--text-primary); font-size: clamp(24px, 4vw, 34px); }
.dice-lock__caster { margin: 0; color: var(--text-secondary); font-size: 13px; }

.dice-lock__stage {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 36px;
  min-height: 215px;
  margin: 12px 0 8px;
}
.dice-lock__stage.is-duel { gap: 26px; }
.dice-lock__player { display: flex; flex-direction: column; align-items: center; gap: 9px; min-width: 150px; }
.dice-lock__player-name { color: var(--text-secondary); font-size: 13px; }
.dice-lock__die {
  display: grid;
  place-items: center;
  width: 112px;
  height: 112px;
  border: 2px solid var(--gold-strong);
  border-radius: 22px;
  background: linear-gradient(145deg, #26366a, #121a37 74%);
  box-shadow: 0 0 0 7px rgba(201, 162, 76, 0.12), 0 16px 30px rgba(0, 0, 0, 0.42);
  transform: rotate(-3deg);
}
.dice-lock__die.is-rolling { animation: dice-shake 140ms linear infinite alternate, dice-glow 900ms ease-in-out infinite; }
.dice-lock__die--opponent { border-color: var(--role-enemy); box-shadow: 0 0 0 7px rgba(255, 107, 120, 0.12), 0 16px 30px rgba(0, 0, 0, 0.42); }
.dice-lock__die span { color: var(--text-primary); font-size: 58px; font-weight: 800; font-variant-numeric: tabular-nums; }
.dice-lock__versus { color: var(--gold-strong); font-size: 18px; font-weight: 800; letter-spacing: .12em; }
.dice-lock__result { color: var(--gold-strong); font-size: 16px; }
.dice-lock__phase { margin: 0; color: var(--text-secondary); font-size: 13px; }
.dice-lock__effect { min-height: 24px; margin: 10px 0 0; color: var(--text-primary); font-size: 14px; line-height: 1.55; }
.dice-lock__progress { height: 3px; margin-top: 22px; overflow: hidden; border-radius: 99px; background: rgba(255, 255, 255, 0.1); }
.dice-lock__progress span { display: block; height: 100%; width: 100%; transform-origin: left; background: linear-gradient(90deg, var(--role-action), var(--gold-strong)); animation: dice-progress var(--dice-duration, 3200ms) linear both; }

@keyframes dice-shake { from { transform: translateX(-5px) rotate(-7deg); } to { transform: translateX(5px) rotate(7deg); } }
@keyframes dice-glow { 50% { box-shadow: 0 0 0 12px rgba(201, 162, 76, 0.08), 0 16px 34px rgba(0, 0, 0, 0.52); } }
@keyframes dice-progress { from { transform: scaleX(1); } to { transform: scaleX(0); } }

@media (max-width: 600px) {
  .dice-lock { padding: 12px; }
  .dice-lock__panel { min-height: 350px; padding: 22px 16px 18px; }
  .dice-lock__stage { gap: 12px; }
  .dice-lock__stage.is-duel { gap: 6px; }
  .dice-lock__player { min-width: 0; flex: 1 1 0; }
  .dice-lock__die { width: 86px; height: 86px; border-radius: 16px; }
  .dice-lock__die span { font-size: 44px; }
  .dice-lock__versus { font-size: 13px; }
}

@media (prefers-reduced-motion: reduce) {
  .dice-lock__die.is-rolling, .dice-lock__progress span { animation: none; }
}
</style>
