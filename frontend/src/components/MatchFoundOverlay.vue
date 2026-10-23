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
const modeLabel = computed(() => (props.opponentName === 'AI' ? '人机对战' : props.mode === 'ranked' ? '排位对战' : '休闲对战'))
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
      <h2 id="match-found-title" class="match-found__title">匹配成功！</h2>
      <p class="match-found__countdown" data-testid="match-found-countdown" role="status" aria-live="polite">
        {{ countdownText }}
      </p>

      <div class="match-found__sides">
        <article class="match-found__side" data-testid="match-found-self">
          <p class="match-found__designation">PLAYER 01 / 你</p><svg class="match-found__ship" viewBox="0 0 200 120" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M10 80h180l-30 25H40z M56 80V58h88v22 M82 58V38h32v20 M98 38V20h25 M44 68h12 M144 68h16 M24 112h39m10 0h58m10 0h35"/></svg><h3>我方舰队</h3>
          <p class="match-found__name" data-testid="match-found-self-name">{{ selfName }}</p>
        </article>

        <span class="match-found__versus" aria-hidden="true">VS</span>

        <article class="match-found__side match-found__side--rival" data-testid="match-found-opponent">
          <p class="match-found__designation">PLAYER 02 / 对手</p><svg class="match-found__ship" viewBox="0 0 200 120" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M10 80h180l-30 25H40z M56 80V58h88v22 M82 58V38h32v20 M98 38V20h25 M44 68h12 M144 68h16 M24 112h39m10 0h58m10 0h35"/></svg><p>你的对手是：</p>
          <p class="match-found__name" data-testid="match-found-opponent-name">{{ opponentName }}</p>
        </article>
      </div>

      <div class="match-found__progress"><i :style="{ width: (remaining / Math.max(1, seconds) * 100) + '%' }"></i></div>
      <button type="button" class="match-found__skip" data-primary-action="true" data-testid="match-found-skip" @click="finish">
        立即进入布船
      </button>
    </div>
  </AppOverlay>
</template>

<style scoped>
.match-found__panel { width:min(930px,calc(100vw - 40px)); padding:34px; text-align:center; background:linear-gradient(125deg,#0c2234dd,#1b192ddd); border:1px solid #366781; border-radius:20px; }
.match-found__eyebrow { color:#7cdbfa; letter-spacing:.22em; font-size:12px; margin:0; }
.match-found__title { font-size:clamp(28px,4vw,48px); margin:8px 0; color:#e9f7ff; text-shadow:0 0 24px #4ec8e066; }
.match-found__countdown { color:var(--gold); margin:0 0 24px; }
.match-found__sides { display:grid; grid-template-columns:minmax(0,1fr) 110px minmax(0,1fr); gap:24px; align-items:center; }
.match-found__side { color:#4ec8e0; border:1px solid #2586a4; border-radius:14px; padding:24px 12px; background:radial-gradient(circle at 50% 40%,#20789555,transparent 70%); animation:fleet-enter .7s ease-out both; }
.match-found__side--rival { color:#edb765; border-color:#967449; background:radial-gradient(circle at 50% 40%,#91734144,transparent 70%); animation-name:rival-enter; }
.match-found__designation { font-size:11px; font-weight:700; letter-spacing:.16em; }
.match-found__ship { display:block; width:180px; max-width:90%; height:120px; margin:auto; filter:drop-shadow(0 0 12px currentColor); }
h3 { font-size:28px; margin:12px 0; color:#e9f7ff; }.match-found__name { font-size:20px; font-weight:700; margin:12px 0 0; }
.match-found__versus { display:grid; place-items:center; width:110px; height:110px; border:4px double #397591; border-radius:50%; color:var(--gold); font-size:30px; font-weight:800; box-shadow:0 0 35px #4ec8e066; animation:versus-lock .8s ease-out both; }
.match-found__progress { height:8px; border:1px solid #366781; border-radius:20px; margin:28px auto 12px; width:75%; overflow:hidden; }
.match-found__progress i { display:block; height:100%; background:linear-gradient(90deg,#357bdb,#4ec8e0,#ffe3a0); transition:width 1s linear; }
.match-found__skip { padding:8px 20px; border:1px solid #366781; background:transparent; color:#b9cfdf; border-radius:20px; cursor:pointer; }
@keyframes fleet-enter { from {opacity:0;transform:translateX(-40px)} to {opacity:1;transform:none} }
@keyframes rival-enter { from {opacity:0;transform:translateX(40px)} to {opacity:1;transform:none} }
@keyframes versus-lock { from {opacity:0;transform:scale(1.5)} to {opacity:1;transform:none} }
@media(max-width:600px) { .match-found__panel { padding:20px 12px; }.match-found__sides { grid-template-columns:minmax(0,1fr) 44px minmax(0,1fr);gap:6px; }.match-found__versus { width:44px;height:44px;font-size:20px; }.match-found__side { padding:12px 5px; }.match-found__ship { height:85px; }h3 { font-size:18px; }.match-found__name { font-size:14px; }.match-found__designation { font-size:9px; } }
@media(prefers-reduced-motion:reduce) { .match-found__side,.match-found__versus { animation:none; }.match-found__progress i { transition:none; } }
</style>
