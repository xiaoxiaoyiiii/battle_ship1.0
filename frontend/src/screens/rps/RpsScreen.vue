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
  { value: 'rock', label: '石头', icon: '✊' },
  { value: 'paper', label: '布', icon: '✋' },
  { value: 'scissors', label: '剪刀', icon: '✌' },
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
      <p class="rps__eyebrow">开局 · 猜拳</p>
      <h1 id="screen-rps-title" class="rps__title" data-testid="rps-heading">猜拳决定攻击顺序</h1>
      <p class="rps__round">
        第 <b data-testid="rps-round">{{ roundText }}</b> 回合 · 选择一种手势
      </p>
      <p class="rps__rules" data-testid="rps-rules">
        先手先开炮、只抽 1 张魔法卡；后手后开炮、抽 2 张。猜拳只决定这一大回合的出手顺序。
      </p>
    </header>



    <p
      class="rps__opponent-state"
      data-testid="rps-opponent-status"
      :data-state="opponentStatus.state"
      role="status"
      aria-live="polite"
    >
      {{ opponentStatus.text }}
    </p>

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
      </button>
    </div>

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
.rps {
  gap: 12px;
}

.rps__head {
  display: grid;
  gap: 2px;
}

.rps__eyebrow {
  margin: 0;
  color: var(--accent);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.rps__title {
  margin: 0;
  font-size: 26px;
}

.rps__round {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 13px;
}

.rps__round b {
  color: var(--text);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.rps__players {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
  font-size: 14px;
}

.rps__player--opponent {
  margin-left: auto;
}

.rps__seat {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 12px;
}

.rps__vs {
  color: var(--text-muted);
  font-size: 11px;
  letter-spacing: 0.12em;
}

.rps__empty {
  margin: 0;
  padding: 10px 14px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 13px;
}

.rps__choices {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  width: min(100%, 720px);
}

.rps__choice {
  display: grid;
  place-items: center;
  gap: 8px;
  min-height: 128px;
  padding: 20px 10px;
  border: 1px solid color-mix(in srgb, var(--role-action) 28%, transparent);
  border-radius: var(--radius);
  background: linear-gradient(
    160deg,
    color-mix(in srgb, var(--role-action) 14%, var(--surface-deck)),
    var(--surface-deck) 78%
  );
  color: var(--text);
  font: inherit;
  cursor: pointer;
  transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
}

/* Hover on a pointer device; touch devices keep the plain surface. */
@media (hover: hover) {
  .rps__choice:hover:not(:disabled) {
    border-color: color-mix(in srgb, var(--role-action) 62%, transparent);
    transform: translateY(-2px);
  }
}

.rps__choice:hover:not(:disabled) {
  border-color: var(--accent);
  background: #113140;
  transform: translateY(-2px);
}

.rps__choice.is-picked {
  border-color: var(--accent);
  background: linear-gradient(160deg, #1c5f78, #14414f);
  box-shadow: 0 0 0 1px rgb(120 220 240 / 35%), 0 8px 22px rgb(0 0 0 / 35%);
}

.rps__choice:disabled {
  cursor: default;
  opacity: 0.62;
}

.rps__choice:disabled.is-picked {
  opacity: 1;
}

.rps__icon {
  font-size: 30px;
  line-height: 1;
}

.rps__label {
  font-size: 14px;
}

.rps__waiting {
  margin: 0;
  padding: 8px 12px;
  border: 1px solid #2a5568;
  border-radius: 8px;
  background: var(--surface-deck);
  color: var(--accent);
  font-size: 13px;
}

.rps__waiting b {
  color: var(--text);
}

.rps__countdown {
  margin-left: 6px;
  font-variant-numeric: tabular-nums;
}

.rps__error {
  margin: 0;
  padding: 8px 12px;
  border: 1px solid #7a2f2a;
  border-radius: 8px;
  background: #2a1414;
  color: var(--role-enemy);
  font-size: 13px;
}

.rps__result {
  display: grid;
  gap: 6px;
  padding: 12px 16px;
  border: 1px solid var(--role-success);
  border-radius: var(--radius);
  background: linear-gradient(160deg, rgb(42 143 104 / 20%), rgb(42 143 104 / 6%));
  animation: rps-reveal 220ms ease-out;
}

.rps__result.is-tie {
  border-color: #7a6a2a;
  background: linear-gradient(160deg, rgb(122 106 42 / 22%), rgb(122 106 42 / 6%));
}

.rps__verdict {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
}

.rps__result.is-tie .rps__verdict {
  color: var(--gold-strong);
}

.rps__reveal {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.rps__reveal b {
  color: var(--text);
  font-size: 15px;
}

.rps__home {
  align-self: flex-start;
}

@keyframes rps-reveal {
  from {
    opacity: 0;
    transform: translateY(6px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.button--ghost {
  border-color: var(--border);
  background: transparent;
  color: var(--text-muted);
}

.button--ghost:hover {
  background: #14303f;
  color: var(--text);
}

@media (max-width: 520px) {
  .rps {
    gap: 10px;
    padding: 12px;
  }

  .rps__title {
    font-size: 22px;
  }

  .rps__choice {
    padding: 12px 6px;
  }

  .rps__icon {
    font-size: 26px;
  }
}

@media (max-height: 680px) {
  .rps__eyebrow {
    display: none;
  }

  .rps__title {
    font-size: 20px;
  }

  .rps__choice {
    padding: 10px 6px;
  }

  .rps__icon {
    font-size: 24px;
  }
}
.rps__rules {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.rps__opponent-state {
  margin: 0;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: 12px;
}

.rps__opponent-state[data-state='ready'] {
  border-color: color-mix(in srgb, var(--role-success) 45%, transparent);
  color: var(--success);
}

.rps__opponent-state[data-state='offline'] {
  border-color: color-mix(in srgb, var(--role-enemy) 45%, transparent);
  color: var(--role-enemy);
}

.rps__receipt {
  margin: 0;
  padding: 6px 10px;
  border: 1px solid color-mix(in srgb, var(--gold-strong) 45%, transparent);
  border-radius: 8px;
  background: var(--gold-soft);
  color: var(--gold-strong);
  font-size: 12px;
}

.rps__confirm {
  display: grid;
  gap: 10px;
  padding: 20px 22px;
  text-align: left;
}

.rps__confirm-title {
  margin: 0;
  font-size: 20px;
}

.rps__confirm-text {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.6;
}

.rps__confirm-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}


.rps__identities { display:flex; justify-content:space-between; gap:16px; width:100%; }
.rps__identity { display:flex; align-items:center; gap:10px; min-width:0; }
.rps__identity b { overflow:hidden; text-overflow:ellipsis; }
.rps__avatar { display:grid; place-items:center; width:44px; height:44px; flex:0 0 44px; border:1px solid var(--role-self); border-radius:50%; overflow:hidden; background:var(--panel); }
.rps__avatar img { width:100%; height:100%; object-fit:cover; }
.rps__identity--opponent .rps__avatar { border-color:var(--gold); }
</style>
