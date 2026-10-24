<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { acquireMatchChannel, emitMatchEvent, matchSocket } from '../../realtime/match'
import { useGameStore } from '../../stores/game'
import { useRpsStore } from '../../stores/rps'
import { choiceName, rpsResultView } from './view'
import AppOverlay from '../../components/AppOverlay.vue'
import { getSettlementSocket } from '../../realtime/settlement'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'
import { usePlayerCards } from '../game/usePlayerCards'

/**
 * Ticket #23: the rock-paper-scissors screen.
 *
 * Data flow (port map 10 section 0.2 / 14 section 1.5):
 *   game_state            -> useGameStore (round, names, seat, state)
 *   rps_result            -> useRpsStore.result (status/winner/choices)
 *   click                 -> rps_choice; the ack only means "received", so the
 *                            waiting state ends on rps_result (or its own 6s
 *                            ack timeout), exactly like static/game.js:11685.
 *   game_state{attacking} -> /game (route names frozen by #21)
 */
const router = useRouter()
const route = useRoute()
const game = useGameStore()
const rps = useRpsStore()
const ui = useUiStore()
const leaveOpen = ref(false)

let releaseChannel: (() => void) | null = null
let offError: (() => void) | null = null
let offMessage: (() => void) | null = null
let offRoomSync: (() => void) | null = null

const choices = [
  { value: 'rock', label: '石头', icon: '✊', counter: '克制剪刀' },
  { value: 'paper', label: '布', icon: '✋', counter: '克制石头' },
  { value: 'scissors', label: '剪刀', icon: '✌', counter: '克制布' },
] as const

const hasRoom = computed(() => Boolean(game.state.room_id))
const inRound = computed(() => game.state.state === 'rock_paper_scissors')
const canChoose = computed(() => hasRoom.value && inRound.value && !rps.waiting)

/** Player-language opponent status. Never guesses "offline" without a frame. */
const opponentStatus = computed(() => {
  if (!game.state.opponent_name) return { state: 'waiting', text: '等待对手加入房间' }
  if (!rps.opponentStateKnown) {
    return { state: 'unknown', text: '对手已入座 · 重新同步后才能看到对手状态' }
  }
  if (!rps.opponentOnline) return { state: 'offline', text: '对手已掉线，等待重连（不会判你负）' }
  if (rps.opponentReady) return { state: 'ready', text: '对手已摆好战舰，正在猜拳' }
  return { state: 'thinking', text: '对手在线' }
})
const selfName = computed(() => game.state.player_name || '你')
const opponentName = computed(() => game.state.opponent_name || '对手')
const auth = useAuthStore()
const cards = usePlayerCards({ selfName: computed(() => auth.user?.username || ''), opponentName, opponentIsAi: computed(() => Boolean(game.state.is_ai_room)), opponentRegistered: computed(() => game.state.opponent_registered === true) })
const roundText = computed(() => String(game.state.round || 1))
const resultView = computed(() => rpsResultView(rps.result, game.state.player_id))

function readText(payload: Record<string, unknown>, key: string): string {
  const value = payload[key]
  return typeof value === 'string' ? value : ''
}

function routeForState(state: string): void {
  if (route.name !== 'rps') return
  if (state === 'placing_ships') {
    void router.push({ name: 'placement' })
  } else if (state === 'attacking') {
    void router.push({ name: 'game' })
  } else if (state === 'game_over') {
    void router.push({ name: 'game-over' })
  }
}

onMounted(() => {
  releaseChannel = acquireMatchChannel()
  const socket = matchSocket()
  if (socket) {
    offError = socket.on('error', (payload) => rps.noteNotice(readText(payload, 'message')))
    offMessage = socket.on('message', (payload) => rps.noteNotice(readText(payload, 'message')))
    offRoomSync = socket.on('room_sync', (payload) => rps.adoptOpponentState(payload))
  }
  rps.resetForEntry()
})

onBeforeUnmount(() => {
  offError?.()
  offMessage?.()
  offRoomSync?.()
  offError = null
  offMessage = null
  offRoomSync = null
  releaseChannel?.()
  releaseChannel = null
})

watch(
  () => game.state.state,
  (state) => routeForState(state),
  { immediate: true },
)

async function choose(choice: string): Promise<void> {
  if (!canChoose.value) return
  const socket = matchSocket()
  if (!socket || !socket.socket.connected) {
    rps.noteNotice('连接已断开，正在重连。稍后会自动同步房间状态，再试一次即可。')
    return
  }
  const roomId = game.state.room_id
  const playerId = game.state.player_id
  if (!roomId || !playerId) {
    rps.noteNotice('还没进入房间，请重新创建或加入房间。')
    return
  }
  rps.beginChoice(choice)
  try {
    const ack = await emitMatchEvent(socket, 'rps_choice', {
      room_id: roomId,
      player_id: playerId,
      choice,
    })
    if (!rps.waiting) return
    rps.settleAck(ack?.status === 'success', typeof ack?.message === 'string' ? ack.message : '')
  } catch (error) {
    if (!rps.waiting) return
    rps.settleAck(false, error instanceof Error ? error.message : '')
  }
}

/** A refused gesture still answers once; it never goes silent. */
function pick(choice: string): void {
  if (!canChoose.value) {
    rps.noteNotice(rps.waiting ? '已经出过拳，等对手出拳后会显示结果' : '现在还不能出拳，等对局进入猜拳阶段')
    return
  }
  void choose(choice)
}

/** Leave the waiting room through the existing surrender event (no new protocol). */
async function leaveRoom(): Promise<void> {
  const socket = getSettlementSocket()
  const roomId = game.state.room_id
  const playerId = game.state.player_id
  if (!socket || !roomId || !playerId) {
    leaveOpen.value = false
    ui.notify({ code: 'leave-room-not-ready', tone: 'error', message: '连接还没就绪，稍后再试一次' })
    return
  }
  try {
    const ack = await socket.emitEvent('surrender', { room_id: roomId, player_id: playerId })
    leaveOpen.value = false
    if (ack?.status === 'success') {
      rps.reset()
      void router.push({ name: 'lobby' })
      return
    }
    rps.noteNotice(
      typeof ack?.message === 'string' && ack.message ? ack.message : '离开房间没有成功，请稍后再试',
    )
  } catch (error) {
    leaveOpen.value = false
    rps.noteNotice('离开房间没有成功：' + (error instanceof Error ? error.message : '网络不稳定'))
  }
}

function returnHome(): void {
  void router.push({ name: 'start' })
}
</script>

<template>
  <section
    class="screen rps"
    data-screen="rps"
    data-testid="screen-rps"
    aria-labelledby="screen-rps-title"
  >
    <div class="rps__identities" aria-label="对阵双方">
      <div class="rps__identity"><span class="rps__avatar"><img v-if="cards.selfAvatar.value" :src="cards.selfAvatar.value" alt="" /><span v-else>{{ selfName.slice(0,1) }}</span></span><b data-testid="rps-self">{{ selfName }}</b></div>
      <div class="rps__identity rps__identity--opponent"><b data-testid="rps-opponent">{{ opponentName }}</b><span class="rps__avatar"><img v-if="cards.opponentAvatar.value" :src="cards.opponentAvatar.value" alt="" /><span v-else>{{ opponentName.slice(0,1) }}</span></span></div>
    </div>
    <header class="rps__head">
      <p class="rps__eyebrow">第 <b data-testid="rps-round">{{ roundText }}</b> 回合 · 猜拳</p>
      <h1 id="screen-rps-title" class="rps__title" data-testid="rps-heading">猜拳决定攻击顺序</h1>
      <p class="rps__round">选择一种手势，争取本回合的先手。</p>
      <p class="rps__rules" data-testid="rps-rules">
        <span><b>先手 · 先开炮</b><i aria-hidden="true"></i>抽 1 张</span>
        <span><b>后手 · 后开炮</b><i aria-hidden="true"></i>抽 2 张</span>
      </p>
    </header>

    <p v-if="!hasRoom" class="rps__empty" data-testid="rps-empty" role="status">
      还没进入房间，先创建或加入房间再猜拳。
    </p>

    <div class="rps__choices" role="group" aria-label="选择手势">
      <button
        v-for="choice in choices"
        :key="choice.value"
        type="button"
        class="rps__choice"
        :class="{ 'is-picked': rps.pendingChoice === choice.value }"
        :data-testid="'rps-choice-' + choice.value"
        :aria-pressed="rps.pendingChoice === choice.value ? 'true' : 'false'"
        :aria-disabled="!canChoose"
        @click="pick(choice.value)"
      >
        <span class="rps__icon" aria-hidden="true">{{ choice.icon }}</span>
        <span class="rps__label">{{ choice.label }}</span>
        <span class="rps__counter">{{ choice.counter }}</span>
      </button>
    </div>

    <p class="rps__hint">点击手势直接出拳，双方出拳后揭晓结果。</p>

    <p
      class="rps__opponent-state"
      data-testid="rps-opponent-status"
      :data-state="opponentStatus.state"
      role="status"
      aria-live="polite"
    >
      {{ opponentStatus.text }}
    </p>

    <p
      v-if="rps.waiting"
      class="rps__waiting"
      data-testid="rps-waiting"
      role="status"
      aria-live="polite"
    >
      已出拳，等待对手… 你选择了
      <b data-testid="rps-waiting-choice">{{ choiceName(rps.pendingChoice) }}</b>
      <b class="rps__countdown" data-testid="rps-waiting-countdown">{{ rps.countdown }}s</b>
    </p>

    <p v-if="rps.error" class="rps__error" data-testid="rps-error" role="alert">
      {{ rps.error }}
    </p>

    <p
      v-if="!canChoose && rps.waiting"
      class="rps__receipt"
      data-testid="rps-receipt"
      role="status"
      aria-live="polite"
    >
      已出拳，等对手出拳后会显示结果。
    </p>

    <div
      v-if="resultView"
      class="rps__result"
      :class="{ 'is-tie': resultView.tie }"
      data-testid="rps-result"
      role="status"
      aria-live="polite"
    >
      <p class="rps__verdict" data-testid="rps-result-verdict">{{ resultView.verdict }}</p>
      <p v-if="resultView.hasChoices" class="rps__reveal">
        <span class="rps__reveal-item">
          你 <b data-testid="rps-result-self">{{ resultView.self }}</b>
        </span>
        <span class="rps__reveal-item">
          对手 <b data-testid="rps-result-opponent">{{ resultView.opponent }}</b>
        </span>
      </p>
    </div>

    <button
      v-if="hasRoom"
      type="button"
      class="button button--ghost rps__leave"
      data-testid="rps-leave"
      @click="leaveOpen = true"
    >
      离开房间
    </button>

    <button
      v-if="!hasRoom"
      type="button"
      class="button button--ghost rps__home"
      data-testid="rps-return-home"
      @click="returnHome"
    >
      返回首页
    </button>

    <AppOverlay
      v-if="leaveOpen"
      id="rps-leave-overlay"
      :priority="140"
      label="离开房间确认"
      @close="leaveOpen = false"
    >
      <section class="rps__confirm" data-testid="rps-leave-confirm">
        <h2 class="rps__confirm-title">离开房间？</h2>
        <p class="rps__confirm-text">
          猜拳阶段离开会按认输处理：本局判负并结算{{ game.state.ranked ? '，排位会扣分' : '' }}。留在房间里可以继续等对手。
        </p>
        <div class="rps__confirm-actions">
          <button type="button" class="button button--ghost" data-testid="rps-leave-cancel" @click="leaveOpen = false">
            继续等待
          </button>
          <button type="button" class="button" data-testid="rps-leave-confirm-ok" @click="leaveRoom">
            确认离开（判负）
          </button>
        </div>
      </section>
    </AppOverlay>
  </section>
</template>

<style scoped>
/* 手势与说明围绕同一中轴，头像仍保留在页面两侧。 */
.rps { gap:18px; align-items:center; padding:24px 28px 32px; }
.rps__identities { display:flex; justify-content:space-between; gap:16px; width:100%; }
.rps__identity { display:flex; align-items:center; gap:10px; min-width:0; max-width:45%; }
.rps__identity b { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rps__avatar { display:grid; place-items:center; width:44px; height:44px; flex:0 0 44px; border:1px solid var(--role-self); border-radius:50%; overflow:hidden; background:var(--panel); }
.rps__avatar img { width:100%; height:100%; object-fit:cover; }
.rps__identity--opponent .rps__avatar { border-color:var(--gold); }
.rps__head { display:grid; justify-items:center; gap:12px; margin:16px 0 6px; text-align:center; max-width:100%; }
.rps__eyebrow { display:inline-flex; align-items:center; gap:4px; margin:0; padding:7px 18px; border:1px solid color-mix(in srgb,var(--role-action) 60%,transparent); border-radius:999px; color:var(--accent); background:color-mix(in srgb,var(--role-action) 9%,transparent); font-size:13px; }
.rps__eyebrow b { font-variant-numeric:tabular-nums; }
.rps__title { margin:0; font-size:clamp(24px,2.4vw,36px); line-height:1.3; letter-spacing:.02em; }
.rps__round { margin:0; font-size:15px; color:var(--text-muted); }
.rps__rules { display:flex; flex-wrap:wrap; justify-content:center; gap:12px; margin:4px 0 0; font-size:13px; color:var(--text-muted); }
.rps__rules>span { display:inline-flex; align-items:center; gap:12px; padding:10px 16px; border:1px solid var(--border); border-radius:9px; background:color-mix(in srgb,var(--panel) 70%,transparent); }
.rps__rules b { color:var(--accent); font-weight:500; }
.rps__rules i { height:14px; width:1px; background:var(--border); }
.rps__choices { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:20px; width:min(100%,800px); margin:0 auto; }
.rps__choice { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px; min-width:0; min-height:220px; padding:28px 14px; border:1px solid color-mix(in srgb,var(--role-action) 45%,var(--border)); border-radius:14px; background:linear-gradient(155deg,color-mix(in srgb,var(--role-action) 12%,var(--surface-deck)),var(--surface-deck) 85%); color:var(--text); font:inherit; cursor:pointer; transition:transform 140ms ease,border-color 140ms ease,box-shadow 140ms ease; }
.rps__choice:focus-visible { outline:2px solid var(--accent); outline-offset:4px; }
@media(hover:hover) {
  .rps__choice:hover:not([aria-disabled='true']) { transform:translateY(-3px); border-color:var(--accent); box-shadow:0 0 0 1px var(--accent),0 8px 24px color-mix(in srgb,var(--role-action) 12%,transparent); }
}
.rps__choice.is-picked { border-color:var(--accent); box-shadow:0 0 0 1px var(--accent); background:linear-gradient(155deg,color-mix(in srgb,var(--role-action) 22%,var(--surface-deck)),var(--surface-deck)); }
.rps__choice[aria-disabled='true'] { cursor:default; opacity:.6; }
.rps__choice[aria-disabled='true'].is-picked { opacity:1; }
.rps__icon { font-size:62px; line-height:1.2; margin-bottom:5px; }
.rps__label { font-size:20px; font-weight:650; }
.rps__counter { color:var(--text-muted); font-size:13px; }
.rps__hint { margin:2px 0 0; color:var(--text-muted); font-size:13px; text-align:center; }
.rps__opponent-state { display:inline-flex; align-items:center; justify-content:center; gap:8px; max-width:min(100%,600px); margin:0; padding:7px 14px; border:1px solid var(--border); border-radius:999px; background:var(--bg-elevated); color:var(--text-muted); font-size:12px; text-align:center; }
.rps__opponent-state::before { content:''; width:7px; height:7px; flex:0 0 7px; border-radius:50%; background:var(--text-muted); }
.rps__opponent-state[data-state='ready'],.rps__opponent-state[data-state='thinking'] { border-color:color-mix(in srgb,var(--role-success) 45%,transparent); color:var(--role-success); }
.rps__opponent-state[data-state='ready']::before,.rps__opponent-state[data-state='thinking']::before { background:var(--role-success); }
.rps__opponent-state[data-state='offline'] { color:var(--role-enemy); border-color:var(--role-enemy); }
.rps__opponent-state[data-state='offline']::before { background:var(--role-enemy); }
.rps__empty,.rps__waiting,.rps__error,.rps__receipt,.rps__result { max-width:min(100%,700px); margin:0; padding:10px 16px; border:1px solid var(--border); border-radius:9px; background:var(--surface-deck); font-size:13px; text-align:center; }
.rps__waiting { color:var(--accent); }
.rps__waiting b { color:var(--text); }
.rps__countdown { margin-left:6px; font-variant-numeric:tabular-nums; }
.rps__error { color:var(--role-enemy); border-color:var(--role-enemy); }
.rps__receipt { color:var(--gold-strong); border-color:var(--gold); }
.rps__result { display:grid; gap:6px; border-color:var(--role-success); animation:rps-reveal 220ms ease-out; }
.rps__result.is-tie { border-color:var(--gold); }
.rps__verdict { margin:0; font-size:20px; font-weight:700; }
.rps__result.is-tie .rps__verdict { color:var(--gold-strong); }
.rps__reveal { display:flex; flex-wrap:wrap; justify-content:center; gap:6px 18px; margin:0; color:var(--text-muted); font-size:13px; }
.rps__reveal b { color:var(--text); font-size:15px; }
.rps__leave,.rps__home { align-self:center; width:190px; max-width:100%; min-height:42px; margin-top:12px; border-color:var(--border); background:transparent; color:var(--text-muted); }
.rps__confirm { display:grid; gap:10px; padding:20px 22px; text-align:left; }
.rps__confirm-title { margin:0; font-size:20px; }
.rps__confirm-text { margin:0; color:var(--text-muted); font-size:13px; line-height:1.6; }
.rps__confirm-actions { display:flex; flex-wrap:wrap; gap:10px; justify-content:flex-end; }
@keyframes rps-reveal { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:none; } }
@media(max-width:520px) {
  .rps { gap:14px; padding:14px 12px 24px; }
  .rps__identity { font-size:12px; gap:7px; }
  .rps__avatar { width:34px; height:34px; flex-basis:34px; }
  .rps__head { margin-top:14px; gap:10px; }
  .rps__round { font-size:12px; }
  .rps__rules { gap:6px; font-size:11px; }
  .rps__rules>span { gap:7px; padding:8px; }
  .rps__choices { gap:9px; }
  .rps__choice { min-height:150px; padding:18px 5px; gap:10px; border-radius:10px; }
  .rps__icon { font-size:40px; }
  .rps__label { font-size:16px; }
  .rps__counter { font-size:11px; }
  .rps__hint { font-size:11px; }
}
@media(max-height:700px) {
  .rps { gap:10px; padding-top:12px; padding-bottom:18px; }
  .rps__head { margin:0; gap:8px; }
  .rps__title { font-size:24px; }
  .rps__eyebrow { padding:4px 14px; }
  .rps__choice { min-height:150px; padding:14px 8px; gap:8px; }
  .rps__icon { font-size:40px; margin:0; }
  .rps__leave,.rps__home { margin-top:0; }
}
@media(max-height:450px) and (min-width:521px) {
  .rps__identities { position:absolute; top:12px; left:20px; right:20px; width:auto; pointer-events:none; }
  .rps { position:relative; gap:6px; padding-top:8px; padding-bottom:10px; }
  .rps__head { padding:0 150px; }
  .rps__title { font-size:20px; }
  .rps__round { font-size:12px; }
  .rps__eyebrow { display:none; }
  .rps__rules { font-size:11px; margin:0; gap:8px; }
  .rps__rules>span { padding:5px 10px; }
  .rps__choices { max-width:540px; gap:12px; }
  .rps__choice { min-height:100px; padding:10px; gap:5px; }
  .rps__icon { font-size:30px; }
  .rps__label { font-size:15px; }
  .rps__counter,.rps__hint { font-size:11px; }
  .rps__opponent-state { padding:4px 12px; }
}
@media(prefers-reduced-motion:reduce) { .rps__choice { transition:none; } .rps__choice:hover { transform:none; } .rps__result { animation:none; } }
</style>
