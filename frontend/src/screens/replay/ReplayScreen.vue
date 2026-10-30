<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useReplayStore } from '../../stores/replay'
import {
  cellClass,
  cellGlyph,
  cellOf,
  chainText,
  handChips,
  nodeEntries,
  nodePercent,
  nodeTipText,
  phaseText,
  shipsAlive,
  stepKindText,
  type Side,
} from './model'

/**
 * Ticket #28: the replay screen.
 *
 * Data comes exclusively from GET /api/replay/<match_id> (the store); this
 * component never opens a socket, never joins a room and never re-derives a
 * game rule. The frame model lives in ./model.ts (one implementation; the
 * external gate recomputes it from the raw payload).
 *
 * The playback timer is a setTimeout chain (pausing clears it). The unmount
 * hook clears it too: leaving through the nav (not the exit button) must not
 * leave a timer running behind another screen.
 */
const route = useRoute()
const router = useRouter()
const store = useReplayStore()

const SPEEDS = [1, 2, 4]
const SIDES: readonly Side[] = ['p1', 'p2']
const STEP_MS = 900

const matchId = computed(() => {
  const raw = route.query.match_id
  return Array.isArray(raw) ? String(raw[0] ?? '') : String(raw ?? '')
})

const ready = computed(() => store.status === 'ready' && store.payload !== null)
const frame = computed(() => store.frame)
const stepTotal = computed(() => store.stepCount)
const stepIndex = computed(() => (stepTotal.value ? store.k + 1 : 0))
const percent = computed(() =>
  stepTotal.value > 1 ? (store.k / (stepTotal.value - 1)) * 100 : 0,
)

const playersTitle = computed(() => {
  const payload = store.payload
  if (!payload) return '—'
  return (payload.p1Name || '先手') + ' vs ' + (payload.p2Name || '后手')
})

const truncated = computed(() => store.payload?.truncated ?? '')

const statusText = computed(() => {
  if (store.status === 'idle') return '缺少对局编号，无法回放。'
  if (store.status === 'loading') return '正在加载回放…'
  if (store.status === 'error') return store.error
  return truncated.value
    ? '回放已加载（' + truncated.value + '）'
    : '回放已加载，可以拖动进度条或点下一步。'
})

// Phase / big-round / chain of the current frame. The server recorder stamps
// them on the steps and exports the timelines; the screen only formats.
const contextPhase = computed(() => phaseText(frame.value?.phase ?? ''))
const contextRound = computed(() =>
  typeof frame.value?.round === 'number' ? String(frame.value.round) : '—',
)
const contextChain = computed(() => chainText(frame.value?.chain ?? []))

const currentStep = computed(() => store.currentStep)
const stepKind = computed(() => (currentStep.value ? stepKindText(currentStep.value.kind) : '—'))
const stepActor = computed(() => (currentStep.value?.actor ? currentStep.value.actor : '—'))
const stepText = computed(() => {
  const step = currentStep.value
  if (!step) return '—'
  const who = step.actor ? step.actor + '：' : ''
  return '第 ' + (store.k + 1) + ' 步 · ' + stepKindText(step.kind) + ' · ' + who + step.text
})

function nameOf(side: Side): string {
  const payload = store.payload
  if (!payload) return side === 'p1' ? '先手' : '后手'
  return (side === 'p1' ? payload.p1Name : payload.p2Name) || (side === 'p1' ? '先手' : '后手')
}

function boardTitle(side: Side): string {
  return nameOf(side) + ' 的棋盘'
}

function boardLabel(side: Side): string {
  return nameOf(side) + ' 的棋盘（全透视）'
}

function shipsOf(side: Side): number {
  return frame.value ? shipsAlive(frame.value, side) : 0
}

interface CellView {
  key: string
  testid: string
  x: number
  y: number
  className: string
  glyph: string
  label: string
}

function cellsOf(side: Side): CellView[] {
  const current = frame.value
  if (!current) return []
  const cells: CellView[] = []
  for (let y = 0; y < 6; y += 1) {
    for (let x = 0; x < 6; x += 1) {
      const cell = cellOf(current, side, x, y)
      cells.push({
        key: side + '-' + x + '-' + y,
        testid: 'replay-cell-' + side + '-' + x + '-' + y,
        x,
        y,
        className: cellClass(cell),
        glyph: cellGlyph(cell),
        label: cell.label,
      })
    }
  }
  return cells
}

function chipsOf(side: Side) {
  return frame.value ? handChips(side, frame.value.hand[side]) : []
}

const nodes = computed(() => (store.payload ? nodeEntries(store.payload) : []))

interface LogRow {
  step: number
  text: string
}

const logRows = computed<LogRow[]>(() => {
  const payload = store.payload
  if (!payload) return []
  const rows: LogRow[] = []
  const upto = Math.min(store.k, payload.steps.length - 1)
  for (let index = 0; index <= upto; index += 1) {
    const step = payload.steps[index]
    rows.push({
      step: index,
      text: '第' + (index + 1) + '步 · ' + (step.actor ? step.actor + '：' : '') + step.text,
    })
  }
  return rows
})

const tip = ref('')
const tipVisible = ref(false)

function tipOf(node: { step: number; kind: string; label: string }): string {
  return nodeTipText(store.payload, node)
}

function showTip(node: { step: number; kind: string; label: string }): void {
  tip.value = tipOf(node)
  tipVisible.value = true
}

function hideTip(): void {
  tipVisible.value = false
}

let timer: ReturnType<typeof setTimeout> | null = null

function stopTimer(): void {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
}

function scheduleNext(): void {
  stopTimer()
  if (!store.playing) return
  if (store.stepCount === 0 || store.k >= store.stepCount - 1) {
    store.setPlaying(false)
    return
  }
  const delay = Math.max(1, Math.round(STEP_MS / store.speed))
  timer = setTimeout(() => {
    timer = null
    if (!store.playing) return
    if (store.k >= store.stepCount - 1) {
      store.setPlaying(false)
      return
    }
    store.setK(store.k + 1)
    scheduleNext()
  }, delay)
}

function togglePlay(): void {
  if (store.playing) {
    store.setPlaying(false)
    return
  }
  if (store.stepCount === 0) return
  if (store.k >= store.stepCount - 1) store.setK(0)
  store.setPlaying(true)
}

function pauseAndStep(delta: number): void {
  store.setPlaying(false)
  store.setK(store.k + delta)
}

function setSpeed(option: number): void {
  store.setSpeed(option)
  if (store.playing) scheduleNext()
}

function jumpTo(step: number): void {
  store.setPlaying(false)
  store.setK(step)
  hideTip()
}

const scrubbing = ref(false)
const trackEl = ref<HTMLElement | null>(null)

function seekFromClientX(clientX: number): void {
  const element = trackEl.value
  if (!element || store.stepCount === 0) return
  const rect = element.getBoundingClientRect()
  if (rect.width <= 0) return
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  store.setK(Math.round(ratio * (store.stepCount - 1)))
}

function onPointerDown(event: PointerEvent): void {
  store.setPlaying(false)
  scrubbing.value = true
  const element = event.currentTarget as HTMLElement | null
  try {
    element?.setPointerCapture(event.pointerId)
  } catch {
    // Older engines: capture is a nicety, seeking still works.
  }
  seekFromClientX(event.clientX)
}

function onPointerMove(event: PointerEvent): void {
  if (!scrubbing.value) return
  seekFromClientX(event.clientX)
}

function onPointerUp(event: PointerEvent): void {
  if (!scrubbing.value) return
  scrubbing.value = false
  const element = event.currentTarget as HTMLElement | null
  try {
    element?.releasePointerCapture(event.pointerId)
  } catch {
    // ignore
  }
}

function onTrackKeydown(event: KeyboardEvent): void {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  event.stopPropagation()
  pauseAndStep(event.key === 'ArrowRight' ? 1 : -1)
}

/**
 * Exit goes back to where the player came from (spec story 105): the settlement
 * or profile entry passes ?from=, and a deep link with no marker still lands on
 * the home screen (the browser history may lead out of the app entirely).
 */
const exitFrom = computed(() => {
  const raw = route.query.from
  return Array.isArray(raw) ? String(raw[0] ?? '') : String(raw ?? '')
})

const exitLabel = computed(() => (exitFrom.value === 'game-over' ? '回结算' : '退出回放'))

function leave(): void {
  stopTimer()
  store.setPlaying(false)
  store.reset()
  if (exitFrom.value === 'game-over') {
    void router.push({ name: 'game-over' })
    return
  }
  if (exitFrom.value === 'lobby') {
    void router.push({ name: 'lobby' })
    return
  }
  if (exitFrom.value === 'profile') {
    const raw = route.query.username
    const username = Array.isArray(raw) ? String(raw[0] ?? '') : String(raw ?? '')
    if (username) {
      void router.push({ name: 'profile', query: { username } })
      return
    }
    void router.push({ name: 'leaderboard' })
    return
  }
  void router.push({ name: 'start' })
}

/** One main board with a 我的 / 对手 viewpoint switch (spec stories 101-102). */
const view = ref<Side>(store.youAre === 'p2' ? 'p2' : 'p1')

watch(
  () => store.youAre,
  (value) => {
    if (value === 'p1' || value === 'p2') view.value = value
  },
)

watch(
  () => store.playing,
  (value) => {
    if (value) scheduleNext()
    else stopTimer()
  },
)

onMounted(() => {
  void store.load(matchId.value)
})

watch(matchId, (id) => {
  stopTimer()
  void store.load(id)
})

onBeforeUnmount(() => {
  stopTimer()
  store.setPlaying(false)
})
</script>

<template>
  <section
    class="screen replay-screen"
    data-screen="replay"
    data-testid="screen-replay"
    aria-labelledby="screen-replay-title"
  >
    <header class="replay__head">
      <p class="replay__eyebrow">只读 · 逐帧回放</p>
      <h1 id="screen-replay-title" class="replay__title">
        <span data-testid="replay-heading">对局回放</span>
        <b class="replay__versus" data-testid="replay-players-title">{{ playersTitle }}</b>
      </h1>
      <p class="replay__status" data-testid="replay-status" role="status" aria-live="polite">{{ statusText }}</p>
      <p v-if="truncated" class="replay__warning" data-testid="replay-truncated">{{ truncated }}</p>
    </header>

    <section v-if="!matchId" class="replay__notice" data-testid="replay-empty">
      <h2>缺少对局编号</h2>
      <p>回放需要从战绩或结算页带 match_id 进入，例如 /replay?match_id=…。</p>
      <button type="button" class="button" data-testid="replay-leave" @click="leave">返回首页</button>
    </section>

    <section v-else-if="store.status === 'error'" class="replay__notice replay__notice--error" data-testid="replay-error" role="alert">
      <h2>无法播放这条回放</h2>
      <p>{{ store.error }}</p>
      <button type="button" class="button" data-testid="replay-leave" @click="leave">返回首页</button>
    </section>

    <template v-else-if="ready">
      <div class="replay__topbar">
        <span class="replay__stat">第 <b data-testid="replay-step-index">{{ stepIndex }}</b>/<b data-testid="replay-step-total">{{ stepTotal }}</b> 步</span>
        <span class="replay__stat">当前 <b data-testid="replay-step-kind">{{ stepKind }}</b></span>
        <span class="replay__stat">行动方 <b data-testid="replay-step-actor">{{ stepActor }}</b></span>
        <span class="replay__stat">阶段 <b data-testid="replay-phase">{{ contextPhase }}</b></span>
        <span class="replay__stat">大回合 <b data-testid="replay-round">{{ contextRound }}</b></span>
        <span class="replay__stat replay__stat--chain">当前连锁 <b data-testid="replay-chain">{{ contextChain }}</b></span>
        <span class="replay__speed" role="group" aria-label="播放倍速">
          <button
            v-for="option in SPEEDS"
            :key="option"
            type="button"
            class="replay__speed-btn"
            :class="{ active: store.speed === option }"
            :data-testid="'replay-speed-' + option"
            :data-replay-speed="option"
            @click="setSpeed(option)"
          >{{ option }}×</button>
        </span>
      </div>

      <section class="replay__players" aria-label="双方">
        <div v-for="side in SIDES" :key="side" class="replay__player">
          <span class="replay__name" :data-testid="'replay-name-' + side">{{ nameOf(side) }}</span>
          <span v-if="store.youAre === side" class="replay__you" :data-testid="'replay-mine-' + side">你</span>
          <span class="replay__meta">剩余战舰 <b :data-testid="'replay-ships-' + side">{{ shipsOf(side) }}</b></span>
        </div>
      </section>

      <div class="replay__body">
        <div class="replay__main">
          <div class="replay__views" role="tablist" aria-label="回放视角">
            <button
              type="button"
              class="replay__view"
              :class="{ 'is-active': view === 'p1' }"
              :aria-selected="view === 'p1' ? 'true' : 'false'"
              data-testid="replay-view-self"
              @click="view = store.youAre === 'p2' ? 'p2' : 'p1'"
            >
              我的视角
            </button>
            <button
              type="button"
              class="replay__view"
              :class="{ 'is-active': view === (store.youAre === 'p2' ? 'p1' : 'p2') }"
              :aria-selected="view === (store.youAre === 'p2' ? 'p1' : 'p2') ? 'true' : 'false'"
              data-testid="replay-view-opponent"
              @click="view = store.youAre === 'p2' ? 'p1' : 'p2'"
            >
              对手视角
            </button>
          </div>

          <div class="replay__boards">
            <div
              v-for="side in SIDES"
              :key="'board-' + side"
              class="replay__board-wrap"
              :class="{ 'is-inactive': side !== view }"
              :data-active="side === view ? 'true' : 'false'"
            >
              <h2 class="replay__board-title" :data-testid="'replay-board-title-' + side">{{ boardTitle(side) }}</h2>
              <div
                class="replay__board"
                :class="{ 'replay__board--mine': store.youAre === side }"
                :data-testid="'replay-board-' + side"
                role="img"
                :aria-label="boardLabel(side)"
              >
                <div
                  v-for="cell in cellsOf(side)"
                  :key="cell.key"
                  :class="cell.className"
                  :data-testid="cell.testid"
                  :data-x="cell.x"
                  :data-y="cell.y"
                  :title="cell.label"
                  :aria-label="cell.label"
                >{{ cell.glyph }}</div>
              </div>
            </div>
          </div>

          <div class="replay__controls">
            <button type="button" class="button button--ghost" data-testid="replay-prev" :disabled="store.k <= 0" @click="pauseAndStep(-1)">上一步</button>
            <button type="button" class="button" data-testid="replay-play" :disabled="stepTotal === 0" @click="togglePlay">
              {{ store.playing ? '暂停' : '播放' }}
            </button>
            <button type="button" class="button button--ghost" data-testid="replay-next" :disabled="stepTotal === 0 || store.k >= stepTotal - 1" @click="pauseAndStep(1)">下一步</button>
          </div>

          <div
            ref="trackEl"
            class="replay__track"
            data-testid="replay-track"
            role="slider"
            tabindex="0"
            aria-label="回放进度"
            :aria-valuemin="0"
            :aria-valuemax="Math.max(0, stepTotal - 1)"
            :aria-valuenow="store.k"
            :aria-valuetext="stepTotal ? '第 ' + (store.k + 1) + ' 步 / 共 ' + stepTotal + ' 步' : '没有可回放的行动'"
            @pointerdown="onPointerDown"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="onPointerUp"
            @keydown="onTrackKeydown"
          >
            <div class="replay__track-fill" data-testid="replay-track-fill" :style="{ width: percent + '%' }"></div>
            <div class="replay__track-nodes" data-testid="replay-track-nodes">
              <button
                v-for="entry in nodes"
                :key="entry.testid"
                type="button"
                class="replay__node"
                :class="['replay__node--' + entry.node.kind, { passed: entry.node.step <= store.k }]"
                :style="{ left: nodePercent(entry.node.step, stepTotal) + '%' }"
                :data-testid="entry.testid"
                :data-step="entry.node.step"
                :title="tipOf(entry.node)"
                :aria-label="tipOf(entry.node)"
                @click.stop="jumpTo(entry.node.step)"
                @mouseenter="showTip(entry.node)"
                @mouseleave="hideTip"
              ></button>
            </div>
            <div class="replay__track-thumb" data-testid="replay-track-thumb" :style="{ left: percent + '%' }"></div>
            <p v-if="tipVisible" class="replay__node-tip" role="tooltip">{{ tip }}</p>
          </div>
        </div>

        <aside class="replay__side">
          <h2 class="replay__side-title">双方手牌</h2>
          <div v-for="side in SIDES" :key="'hand-' + side" class="replay__hand-block">
            <h3 class="replay__hand-title">{{ nameOf(side) }} 的手牌</h3>
            <div class="replay__hand" :data-testid="'replay-hand-' + side">
              <template v-if="chipsOf(side).length">
                <span
                  v-for="chip in chipsOf(side)"
                  :key="chip.key"
                  class="replay__chip"
                  :data-testid="chip.testid"
                  aria-readonly="true"
                >{{ chip.name }}</span>
              </template>
              <span v-else class="replay__muted" :data-testid="'replay-hand-empty-' + side">（没有手牌）</span>
            </div>
          </div>

          <h2 class="replay__side-title">这一步</h2>
          <div class="replay__current" data-testid="replay-step-text">{{ stepText }}</div>

          <h2 class="replay__side-title">对局记录</h2>
          <div class="replay__logs" data-testid="replay-logs">
            <button
              v-for="row in logRows"
              :key="row.step"
              type="button"
              class="replay__log"
              :class="{ current: row.step === store.k }"
              :data-testid="'replay-log-item-' + row.step"
              :data-step="row.step"
              @click="jumpTo(row.step)"
            >{{ row.text }}</button>
            <p v-if="!logRows.length" class="replay__muted">暂无行动记录</p>
          </div>
        </aside>
      </div>

      <footer class="replay__actions">
        <button type="button" class="button button--ghost" data-testid="replay-leave" @click="leave">{{ exitLabel }}</button>
      </footer>
    </template>

    <section v-else class="replay__notice" data-testid="replay-loading">
      <p>{{ statusText }}</p>
    </section>
  </section>
</template>

<style scoped>
.replay-screen {
  gap: 12px;
  padding-top: 8px;
}

.replay__eyebrow {
  margin: 0 0 2px;
  color: var(--text-secondary);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.replay__title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 14px;
  margin: 0;
  font-size: 30px;
  line-height: 1.2;
}

.replay__versus {
  color: var(--gold-strong);
  font-size: 18px;
  font-weight: 700;
}

.replay__status {
  margin: 1px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.replay__warning {
  margin: 4px 0 0;
  color: var(--gold-strong);
  font-size: 12px;
}

.replay__notice {
  display: grid;
  gap: 8px;
  justify-items: start;
  padding: 20px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: var(--panel);
}

.replay__notice h2 {
  margin: 0;
  font-size: 18px;
}

.replay__notice p {
  margin: 0;
  max-width: 60ch;
  color: var(--text-muted);
  font-size: 13px;
}

.replay__notice--error {
  border-color: var(--danger);
}

.replay__notice--error h2 {
  color: var(--danger);
}

.replay__topbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 18px;
  padding: 10px 16px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: var(--panel);
  font-size: 13px;
  box-shadow: var(--shadow-panel);
}

.replay__stat {
  color: var(--text-muted);
}

.replay__stat b {
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.replay__speed {
  display: flex;
  gap: 4px;
  margin-left: auto;
}

.replay__speed-btn {
  min-width: 40px;
  padding: 4px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.replay__speed-btn.active {
  border-color: var(--accent-strong);
  background: var(--accent-soft);
  color: var(--text);
}

.replay__players {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.replay__player {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 14px 18px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: var(--panel);
}

.replay__name {
  font-size: 15px;
  font-weight: 700;
}

.replay__you {
  padding: 1px 7px;
  border: 1px solid var(--accent-strong);
  border-radius: 999px;
  color: var(--accent-strong);
  font-size: 11px;
}

.replay__meta {
  margin-left: auto;
  color: var(--text-muted);
  font-size: 12px;
}

.replay__meta b {
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.replay__body {
  display: grid;
  gap: 20px;
  margin-top: 14px;
}

.replay__main {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-areas:
    'boards boards'
    'controls track';
  gap: 12px 20px;
  align-items: center;
  min-width: 0;
}

/* Ticket #48: one main board; the other viewpoint stays in the DOM (hidden) so
   the arrows/tests can still count both fleets, but only one board is shown. */
.replay__boards {
  grid-area: boards;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 20px;
}

.replay__board-wrap.is-inactive {
  display: none;
}

.replay__views {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: -6px;
}

.replay__view {
  padding: 7px 16px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.replay__view.is-active {
  border-color: var(--accent-strong);
  background: var(--accent-soft);
  color: var(--text);
}

.replay__board-wrap {
  min-width: 0;
}

.replay__board-title {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
}

.replay__board {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 5px;
  width: min(100%, 304px);
  padding: 6px;
  border: 1px solid #2a3358;
  border-radius: 8px;
  background: radial-gradient(120% 120% at 50% 0%, #1d2a55, #101733 70%);
}

.replay__board--mine {
  border-color: rgba(124, 92, 240, 0.7);
  box-shadow: 0 0 0 1px rgba(124, 92, 240, 0.35);
}

.replay__board .cell {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 1;
  border: 1px solid color-mix(in srgb, var(--board-border) 70%, transparent);
  border-radius: 6px;
  background: var(--cell-bg);
  color: var(--text-tertiary);
  font-size: clamp(11px, 3.4vw, 15px);
  line-height: 1;
}

.replay__board .cell.ship {
  background: var(--ship-metal);
  color: var(--surface-elevated);
}

.replay__board .cell.hit {
  border-color: var(--role-enemy);
  background: #4a1d1d;
  color: var(--role-enemy);
}

.replay__board .cell.miss {
  color: var(--accent-cyan);
}

.replay__board .cell.sunk {
  border-color: var(--role-enemy);
  background: #611f1a;
  color: var(--role-enemy);
}

.replay__board .cell.shielded {
  outline: 1px solid #6fc9ff;
}

.replay__board .cell.shenwei-hole {
  background-image: repeating-linear-gradient(45deg, rgb(255 255 255 / 8%) 0 4px, transparent 4px 8px);
}

.replay__board .cell.frozen-area {
  outline: 1px solid #8fd7ff;
}

/* Area magic (轰炸 / 硫磺火焰): the whole row/area shares this marker so a
   one-card wipe cannot be mistaken for a lucky single shot. Glyph unchanged. */
.replay__board .cell.area-strike {
  outline: 2px dashed var(--gold-strong);
  outline-offset: -2px;
}

.replay__board .cell.last-stand-candidate {
  outline: 1px dashed var(--gold-strong);
}

.replay__controls {
  grid-area: controls;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.replay__controls .button {
  min-height: 40px;
  padding: 6px 16px;
}

.replay__controls .button:disabled {
  opacity: 0.45;
  cursor: default;
}

.replay__controls [data-testid='replay-play'] {
  border-color: var(--accent-strong);
  background: var(--hero-grad);
  color: #fff;
}

.replay__track {
  position: relative;
  grid-area: track;
  height: 30px;
  margin-top: 0;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--bg-sunken);
  cursor: pointer;
  touch-action: none;
}

.replay__track:focus-visible {
  outline: 2px solid var(--accent);
}

.replay__track-fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  background: linear-gradient(90deg, #5b3fd0, var(--accent-strong));
  opacity: 0.7;
}

.replay__track-thumb {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  margin-left: -6px;
  border-radius: 50%;
  background: #e8e3ff;
  transform: translateY(-50%);
  pointer-events: none;
}

.replay__track-nodes {
  position: absolute;
  inset: 0;
}

.replay__node {
  position: absolute;
  top: 50%;
  width: 9px;
  height: 9px;
  margin-left: -4.5px;
  padding: 0;
  border: 1px solid #0b0d18;
  border-radius: 50%;
  background: #5a6a9c;
  transform: translateY(-50%);
  cursor: pointer;
}

/* Ticket #33's phone-wide 40px control floor must not stretch the absolutely
   positioned timeline nodes (it caused a 21px horizontal overflow at 390px). */
.replay__node[data-testid] {
  width: 9px;
  min-width: 0;
  height: 9px;
  min-height: 0;
}

.replay__node.passed {
  background: var(--gold-strong);
}

.replay__node--magic {
  background: #b48cff;
}

.replay__node--sunk {
  background: #ff7a6b;
}

.replay__node--reset {
  background: var(--success);
}

.replay__node-tip {
  position: absolute;
  left: 8px;
  bottom: 34px;
  z-index: 2;
  max-width: 320px;
  margin: 0;
  padding: 6px 9px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-raised);
  color: var(--text);
  font-size: 12px;
}

.replay__side {
  display: grid;
  gap: 6px;
  padding: 14px 18px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: var(--panel);
  min-width: 0;
}

.replay__side-title {
  margin: 6px 0 2px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--line-dash);
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.replay__hand-title {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}

.replay__hand {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 24px;
}

.replay__chip {
  padding: 3px 8px;
  border: 1px solid color-mix(in srgb, var(--role-action) 50%, transparent);
  border-radius: 6px;
  background: var(--accent-soft);
  font-size: 12px;
}

.replay__muted {
  color: var(--text-muted);
  font-size: 12px;
}

.replay__current {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--surface-deck);
  font-size: 13px;
}

.replay__logs {
  display: grid;
  gap: 2px;
  max-height: 220px;
  overflow-y: auto;
}

.replay__log {
  padding: 3px 6px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.replay__log:hover {
  background: var(--accent-soft);
  color: var(--text);
}

.replay__log.current {
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.replay__actions {
  display: flex;
  justify-content: flex-start;
  padding-top: 4px;
}

.replay__actions .button {
  min-height: 40px;
  padding: 6px 18px;
}

.button--ghost {
  border-color: var(--border-strong);
  background: var(--surface-deck);
  color: var(--text-muted);
}

@media (min-width: 900px) {
  .replay__body {
    grid-template-columns: minmax(0, 1fr) 422px;
    align-items: start;
  }
}

@media (max-width: 899px) {
  .replay__main {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      'boards'
      'controls'
      'track';
  }

  .replay__players {
    gap: 12px;
  }

  .replay__side {
    width: 100%;
  }
}

@media (max-width: 640px) {
  .replay__boards {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }

  .replay__players {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }

  .replay__title {
    font-size: 24px;
  }

  .replay__speed {
    margin-left: 0;
  }
}
</style>
