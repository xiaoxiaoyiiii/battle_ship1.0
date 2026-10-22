<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppOverlay from './AppOverlay.vue'

/**
 * 匹配成功（spec 的 11 屏之一，但没有独立路由）。
 *
 * The server announces a real match with a game_state frame that already
 * carries both seat names; the legacy screen then counted five seconds down and
 * entered placement. Keeping it as an overlay preserves the frozen 11-route
 * contract while restoring the screen: the home/lobby screen owns the timer and
 * only navigates after this component emits done.
 *
 * Rank/level/aura are not part of the game_state contract, so the overlay renders
 * only the fields it really has (names, mode, countdown) instead of a row of
 * placeholder dashes.
 */
const props = withDefaults(
  defineProps<{
    selfName?: string
    opponentName?: string
    mode?: string
    seconds?: number
  }>(),
  { selfName: '', opponentName: '', mode: 'casual', seconds: 5 },
)

const emit = defineEmits<{ (event: 'done'): void }>()

const remaining = ref(Math.max(0, Math.floor(props.seconds)))
const selfName = computed(() => props.selfName || '你')
const opponentName = computed(() => props.opponentName || '对手')
const modeLabel = computed(() => (props.mode === 'ranked' ? '排位对战' : '休闲对战'))
const countdownText = computed(() => (remaining.value > 0 ? remaining.value + ' 秒' : '即将进入'))

let timer: ReturnType<typeof setInterval> | null = null

function stop(): void {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

function finish(): void {
  stop()
  emit('done')
}

onMounted(() => {
  timer = setInterval(() => {
    remaining.value -= 1
    if (remaining.value <= 0) {
      remaining.value = 0
      finish()
    }
  }, 1000)
})

onBeforeUnmount(stop)
</script>

<template>
  <!-- Highest layer of the app: the archive or settings can never cover it. -->
  <AppOverlay
    id="match-found-overlay"
    layer="match-found"
    :priority="250"
    labelledby="match-found-title"
    @close="finish"
  >
    <div class="match-found__panel">
      <p class="match-found__eyebrow">{{ modeLabel }} · 对战确认</p>
      <h2 id="match-found-title" class="match-found__title">匹 配 成 功</h2>
      <p class="match-found__countdown" data-testid="match-found-countdown" role="status" aria-live="polite">
        {{ countdownText }}
      </p>

      <div class="match-found__sides">
        <article class="match-found__side" data-testid="match-found-self">
          <span class="match-found__badge" aria-hidden="true">我</span>
          <p class="match-found__name" data-testid="match-found-self-name">{{ selfName }}</p>
        </article>

        <span class="match-found__versus" aria-hidden="true">VS</span>

        <article class="match-found__side match-found__side--rival" data-testid="match-found-opponent">
          <span class="match-found__badge match-found__badge--rival" aria-hidden="true">敌</span>
          <p class="match-found__name" data-testid="match-found-opponent-name">{{ opponentName }}</p>
        </article>
      </div>

      <button type="button" class="match-found__skip" data-primary-action="true" data-testid="match-found-skip" @click="finish">
        立即进入布船
      </button>
    </div>
  </AppOverlay>
</template>

<style scoped>
.match-found__panel {
  width: min(560px, 100%);
  padding: 26px 30px 22px;
  text-align: center;
}

.match-found__eyebrow {
  margin: 0;
  color: #9c8fe0;
  font-size: 10px;
  letter-spacing: 0.24em;
  text-transform: uppercase;
}

.match-found__title {
  margin: 6px 0 2px;
  color: var(--text, var(--text-primary));
  font-size: 24px;
  letter-spacing: 0.3em;
}

.match-found__countdown {
  margin: 0 0 18px;
  color: var(--text-muted, var(--text-tertiary));
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.match-found__sides {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 10px;
  align-items: center;
}

.match-found__side {
  padding: 14px 12px;
  border: 1px solid var(--border-strong, color-mix(in srgb, var(--role-action) 40%, transparent));
  border-radius: 12px;
  background: rgba(10, 14, 30, 0.7);
}

.match-found__side--rival {
  border-color: rgba(214, 160, 92, 0.45);
}

.match-found__badge {
  display: inline-grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(160deg, #6f5bd4, #382a72);
  color: #f4f1ff;
  font-size: 13px;
  font-weight: 700;
}

.match-found__badge--rival {
  background: linear-gradient(160deg, var(--gold), #7a4f20);
}

.match-found__name {
  margin: 8px 0 10px;
  color: var(--text, var(--text-primary));
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.match-found__stats {
  display: grid;
  gap: 4px;
  margin: 0;
  font-size: 12px;
}

.match-found__stats div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.match-found__stats dt {
  color: var(--text-dim, var(--text-secondary));
}

.match-found__stats dd {
  margin: 0;
  color: var(--text, var(--text-primary));
  font-variant-numeric: tabular-nums;
}

.match-found__versus {
  color: var(--gold);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.match-found__skip {
  margin-top: 20px;
  padding: 9px 22px;
  border: 1px solid color-mix(in srgb, var(--role-action) 50%, transparent);
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted, var(--text-tertiary));
  font-size: 12px;
  cursor: pointer;
}

.match-found__skip:hover {
  border-color: color-mix(in srgb, var(--gold) 70%, transparent);
  color: var(--text, var(--text-primary));
}

@media (max-width: 560px) {
  .match-found__sides {
    grid-template-columns: minmax(0, 1fr);
  }

  .match-found__versus {
    justify-self: center;
  }
}
</style>
