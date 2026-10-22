<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  acquireSpectateChannel,
  joinSpectate,
  leaveSpectate,
  sendSpectateChat,
} from '../../realtime/spectate'
import { useSpectateStore } from '../../stores/spectate'
import {
  boardCells,
  chainRows,
  chatTestid,
  displayName,
  phaseText,
  rosterTestid,
  seatName,
  statusText,
  turnText,
  type SeatLabel,
  type SpectateCell,
  type SpectateChatLine,
  type SpectateRosterRow,
} from './view'

/**
 * Ticket #28: the spectate screen.
 *
 * A separate screen by design (never the game screen): the boards are rebuilt
 * from "cells this seat shot at", so there is no code path that could draw a
 * fleet. Counts / roster / chat / the ending come from the spectator channel;
 * the two players only ever see a count.
 */
const route = useRoute()
const router = useRouter()
const store = useSpectateStore()

const SIDES: readonly SeatLabel[] = ['p1', 'p2']

const roomId = computed(() => {
  const raw = route.query.room_id
  return Array.isArray(raw) ? String(raw[0] ?? '') : String(raw ?? '')
})

// A deep link carries room_id; a lobby entry may also join from the store (the
// test hook and future in-app entries use that path). One gate for both.
const activeRoom = computed(() => roomId.value || store.roomId)
const joined = computed(() => store.phase === 'joined' || store.phase === 'ended')
const hasSnapshot = computed(
  () => Boolean(store.sides.p1 || store.sides.p2) || Object.keys(store.seatLabels).length > 0,
)

const status = computed(() =>
  statusText({
    phase: store.phase,
    error: store.error,
    stateValue: store.stateValue,
    ranked: store.ranked,
    endedReason: store.endedReason,
    winnerLabel: store.winnerLabel,
  }),
)

function nameOf(side: SeatLabel): string {
  return seatName(store.sides, side)
}

function boardTitle(side: SeatLabel): string {
  return nameOf(side) + ' 的棋盘'
}

function boardLabel(side: SeatLabel): string {
  return nameOf(side) + ' 的棋盘（只显示已轰过的格）'
}

function chainName(seat: string): string {
  return seat === 'p1' || seat === 'p2' ? nameOf(seat) : '未知座位'
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

function cellsFor(side: SeatLabel): CellView[] {
  const marks = boardCells(store.attacks, side)
  const cells: CellView[] = []
  for (let y = 0; y < 6; y += 1) {
    for (let x = 0; x < 6; x += 1) {
      const mark: SpectateCell | undefined = marks.get(x + ',' + y)
      let className = 'cell spectate-cell'
      let glyph = ''
      let label = '海面：没有船，也没被打过'
      if (mark) {
        if (mark.ship_sunk) {
          className += ' hit sunk'
          glyph = '✕'
          label = '已轰过：命中并击沉了战舰'
        } else if (mark.hit) {
          className += ' hit'
          glyph = '✕'
          label = '已轰过：命中'
        } else {
          className += ' miss'
          glyph = '○'
          label = '已轰过：未命中'
        }
      }
      cells.push({
        key: side + '-' + x + '-' + y,
        testid: 'spectate-cell-' + side + '-' + x + '-' + y,
        x,
        y,
        className,
        glyph,
        label,
      })
    }
  }
  return cells
}

const boardViews = computed(() => ({ p1: cellsFor('p1'), p2: cellsFor('p2') }))

const turn = computed(() => turnText(store.seatLabels, store.sides, store.currentAttacker))
const phaseLabel = computed(() => phaseText(store.currentPhase))
const fieldMagicText = computed(() => store.fieldMagic || '无')
const chain = computed(() => chainRows(store.chain))

interface RosterView {
  key: string
  testid: string
  name: string
  isMe: boolean
}

const rosterViews = computed<RosterView[]>(() => {
  const seen = new Map<string, number>()
  const rows: RosterView[] = []
  for (const row of store.roster as SpectateRosterRow[]) {
    const base = rosterTestid(row.name)
    const count = (seen.get(base) ?? 0) + 1
    seen.set(base, count)
    rows.push({
      key: base + '#' + count,
      testid: count > 1 ? base + '-' + count : base,
      name: row.name,
      isMe: Boolean(store.me) && row.name === store.me,
    })
  }
  return rows
})

const chatLines = computed(() => store.chat as SpectateChatLine[])

const chatDraft = ref('')

function submitChat(): void {
  const text = chatDraft.value
  void sendSpectateChat(text).then((result) => {
    if (result.ok) chatDraft.value = ''
  })
}

let releaseChannel: (() => void) | null = null

function startJoin(id: string): void {
  if (!id) {
    store.reset()
    return
  }
  void joinSpectate(id)
}

onMounted(() => {
  releaseChannel = acquireSpectateChannel()
  startJoin(roomId.value)
})

watch(roomId, (next, previous) => {
  if (next === previous) return
  void leaveSpectate().then(() => startJoin(next))
})

onBeforeUnmount(() => {
  const release = releaseChannel
  releaseChannel = null
  void leaveSpectate().finally(() => release?.())
})

function leaveScreen(): void {
  void leaveSpectate().finally(() => {
    void router.push({ name: 'lobby' })
  })
}

function startOver(): void {
  void router.push({ name: 'lobby' })
}

/**
 * Ticket #48: phones show one board with a viewpoint tab; desktops keep both
 * boards side by side. The hidden board stays mounted (display: none) so the
 * spectator snapshot and the sentinel cells are unchanged.
 */
const view = ref<SeatLabel>('p1')
/** A guest is refused by the server ("观战需要先登录"); that is a login CTA. */
const loginRequired = computed(() => store.phase === 'error' && /登录/.test(store.error))
const authRequested = ref(false)

function requestLogin(): void {
  authRequested.value = true
  // #44 owns the login overlay; this is the agreed cross-ticket entry point.
  window.dispatchEvent(
    new CustomEvent('bs:auth-required', { detail: { reason: '观战需要先登录' } }),
  )
}
</script>

<template>
  <section
    class="screen spectate-screen"
    data-screen="spectate"
    data-testid="screen-spectate"
    aria-labelledby="screen-spectate-title"
  >
    <header class="spectate__head">
      <p class="spectate__eyebrow">只读 · 实时观战</p>
      <h1 id="screen-spectate-title" class="spectate__title" data-testid="spectate-heading">观战</h1>
      <p class="spectate__status" data-testid="spectate-status" role="status" aria-live="polite">{{ status }}</p>
      <p v-if="store.phase === 'ended'" class="spectate__ended" data-testid="spectate-ended">{{ status }}</p>
    </header>

    <section v-if="!activeRoom" class="spectate__notice" data-testid="spectate-empty">
      <h2>还没有选择要观战的对局</h2>
      <p>请从大厅「进行中的对局」点观战进入；观战只限登录用户，且双方都开放观战。</p>
      <button type="button" class="button" data-testid="spectate-leave" @click="startOver">返回大厅</button>
    </section>

    <section v-else-if="store.phase === 'error'" class="spectate__notice spectate__notice--error" data-testid="spectate-error" role="alert">
      <h2>{{ loginRequired ? '登录后可以观战' : '进不去这一局' }}</h2>
      <p>{{ store.error }}</p>
      <div class="spectate__notice-actions">
        <button
          v-if="loginRequired"
          type="button"
          class="button"
          data-testid="spectate-login"
          @click="requestLogin"
        >
          去登录
        </button>
        <button type="button" class="button" data-testid="spectate-leave" @click="startOver">返回大厅</button>
      </div>
      <p v-if="authRequested" class="spectate__muted" data-testid="spectate-login-requested" role="status">
        已打开登录入口。
      </p>
    </section>

    <template v-else-if="joined && hasSnapshot">
      <div class="spectate__topbar">
        <span class="spectate__stat">第 <b data-testid="spectate-round">{{ store.round }}</b> 回合</span>
        <span class="spectate__stat">阶段 <b data-testid="spectate-phase">{{ phaseLabel }}</b></span>
        <span class="spectate__stat">当前 <b data-testid="spectate-turn">{{ turn }}</b></span>
        <span class="spectate__stat">剩余攻击 <b data-testid="spectate-attacks">{{ store.attacksRemaining }}</b></span>
        <span class="spectate__stat">场地魔法 <b data-testid="spectate-field-magic">{{ fieldMagicText }}</b></span>
        <span class="spectate__stat">观战 <b data-testid="spectate-count">{{ store.count }}</b>/<b data-testid="spectate-limit">{{ store.limit }}</b> 人</span>
        <button type="button" class="button button--ghost spectate__leave" data-testid="spectate-leave" @click="leaveScreen">退出观战</button>
      </div>

      <div class="spectate__body">
        <div class="spectate__main">
          <div class="spectate__views" role="tablist" aria-label="观战视角">
            <button
              type="button"
              class="spectate__view"
              :class="{ 'is-active': view === 'p1' }"
              :aria-selected="view === 'p1' ? 'true' : 'false'"
              data-testid="spectate-view-p1"
              @click="view = 'p1'"
            >
              {{ nameOf('p1') }} 的棋盘
            </button>
            <button
              type="button"
              class="spectate__view"
              :class="{ 'is-active': view === 'p2' }"
              :aria-selected="view === 'p2' ? 'true' : 'false'"
              data-testid="spectate-view-p2"
              @click="view = 'p2'"
            >
              {{ nameOf('p2') }} 的棋盘
            </button>
          </div>

          <div class="spectate__boards">
            <div
              v-for="side in SIDES"
              :key="'board-' + side"
              class="spectate__board-wrap"
              :class="{ 'is-inactive': side !== view }"
              :data-active="side === view ? 'true' : 'false'"
            >
              <h2 class="spectate__board-title" :data-testid="'spectate-board-title-' + side">{{ boardTitle(side) }}</h2>
              <p class="spectate__board-meta">
                <span :data-testid="'spectate-name-' + side">{{ nameOf(side) }}</span>
                · 剩余战舰 <b :data-testid="'spectate-ships-' + side">{{ store.sides[side] ? store.sides[side].remainingShips : 0 }}</b>
                · 手牌 <b :data-testid="'spectate-hand-' + side">{{ store.sides[side] ? store.sides[side].handCount : 0 }}</b> 张
              </p>
              <div
                class="spectate__board"
                :data-testid="'spectate-board-' + side"
                role="img"
                :aria-label="boardLabel(side)"
              >
                <div
                  v-for="cell in boardViews[side]"
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

          <p class="spectate__hint">观众只能看到已经轰过的格子；船位与手牌内容不会下发到这台设备。</p>

        </div>

        <aside class="spectate__side">
          <section class="spectate__panel" aria-label="观战席">
            <h2 class="spectate__panel-title">
              观战席 <span data-testid="spectate-roster-count">({{ store.count }}/{{ store.limit }})</span>
            </h2>
            <div class="spectate__roster" data-testid="spectate-roster">
              <span v-if="!rosterViews.length" class="spectate__muted" data-testid="spectate-roster-empty">还没有人来看</span>
              <div
                v-for="row in rosterViews"
                :key="row.key"
                class="spectate__roster-item"
                :class="{ me: row.isMe }"
                :data-testid="row.testid"
                :data-me="row.isMe ? 'true' : 'false'"
              >{{ row.name }}{{ row.isMe ? '（你）' : '' }}</div>
            </div>
          </section>

          <section class="spectate__panel" aria-label="观战席聊天">
            <h2 class="spectate__panel-title">观战席聊天</h2>
            <div class="spectate__chat" data-testid="spectate-chat">
              <p v-if="!chatLines.length" class="spectate__muted">还没有人说话</p>
              <div
                v-for="line in chatLines"
                :key="line.seq"
                class="spectate__chat-line"
                :class="'kind-' + line.kind"
                :data-testid="chatTestid(line.seq)"
              >{{ line.kind === 'notice' || line.kind === 'error' ? line.text : line.name + '：' + line.text }}</div>
            </div>
            <form class="spectate__chat-form" @submit.prevent="submitChat">
              <input
                v-model="chatDraft"
                class="spectate__chat-input"
                data-testid="spectate-chat-input"
                type="text"
                maxlength="100"
                placeholder="和观众说点什么…"
                aria-label="观战席发言"
              />
              <button type="submit" class="button" data-testid="spectate-chat-send">发送</button>
            </form>
            <p class="spectate__chat-note" data-testid="spectate-chat-notice">观战席的话只有观众看得到，对局双方听不见。</p>
          </section>

          <section class="spectate__panel" aria-label="当前连锁">
            <h2 class="spectate__panel-title">当前连锁</h2>
            <div class="spectate__chain" data-testid="spectate-chain">
              <span v-if="!chain.length" class="spectate__muted">当前没有连锁</span>
              <div
                v-for="row in chain"
                :key="row.key"
                class="spectate__chain-item"
                :class="{ negated: row.negated }"
              >{{ chainName(row.seat) }}：{{ row.card }}{{ row.negated ? '（已被康）' : '' }}</div>
            </div>
          </section>

          <section class="spectate__panel" aria-label="对局日志">
            <h2 class="spectate__panel-title">对局记录</h2>
            <div class="spectate__logs" data-testid="spectate-logs">
              <p v-if="!store.logs.length" class="spectate__muted">暂无日志</p>
              <div v-for="(entry, index) in store.logs" :key="index" class="spectate__log">{{ entry.text }}</div>
            </div>
          </section>
        </aside>
      </div>

    </template>

    <section v-else class="spectate__notice" data-testid="spectate-loading">
      <p>{{ status }}</p>
    </section>
  </section>
</template>

<style scoped>
.spectate-screen {
  gap: 14px;
  padding-top: 8px;
}

.spectate__eyebrow {
  margin: 0 0 2px;
  color: var(--text-secondary);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.spectate__title {
  margin: 0;
  font-size: 30px;
  line-height: 1.2;
}

.spectate__status {
  margin: 1px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.spectate__ended {
  margin: 8px 0 0;
  padding: 6px 10px;
  border: 1px solid color-mix(in srgb, var(--gold) 50%, transparent);
  border-radius: 8px;
  background: var(--gold-soft);
  color: var(--gold-strong);
  font-size: 13px;
}

.spectate__notice {
  display: grid;
  gap: 8px;
  justify-items: start;
  padding: 20px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  background: var(--panel);
}

.spectate__notice h2 {
  margin: 0;
  font-size: 18px;
}

.spectate__notice p {
  margin: 0;
  max-width: 60ch;
  color: var(--text-muted);
  font-size: 13px;
}

.spectate__notice--error {
  border-color: var(--danger);
}

.spectate__notice--error h2 {
  color: var(--danger);
}

/* Status rail with the exit action on the right, as in the C+ legend shot. */
.spectate__topbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 22px;
  padding: 10px 16px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: var(--panel);
  font-size: 13px;
  box-shadow: var(--shadow-panel);
}

.spectate__stat {
  color: var(--text-muted);
}

.spectate__stat b {
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.spectate__leave {
  min-height: 40px;
  margin-left: auto;
  padding: 6px 16px;
}

.spectate__body {
  display: grid;
  gap: 20px;
}

.spectate__main {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.spectate__boards {
  display: grid;
  gap: 20px;
  margin-top: 45px;
}

.spectate__notice-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* Phones (<900px): one board + a viewpoint tab, never two stacked boards. */
.spectate__views {
  display: none;
  gap: 6px;
}

.spectate__view {
  padding: 7px 14px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.spectate__view.is-active {
  border-color: var(--accent-strong);
  background: var(--accent-soft);
  color: var(--text);
}

@media (max-width: 899px) {
  .spectate__views {
    display: flex;
    flex-wrap: wrap;
    margin-top: 8px;
  }

  .spectate__boards {
    margin-top: 8px;
  }

  .spectate__board-wrap.is-inactive {
    display: none;
  }
}

.spectate__board-wrap {
  min-width: 0;
  padding: 12px 16px 16px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: var(--panel);
}

.spectate__board-title {
  margin: 0 0 8px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--line-dash);
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.spectate__board-meta {
  margin: 8px 0 10px;
  color: var(--text-muted);
  font-size: 12px;
}

.spectate__board-meta b {
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.spectate__board {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 5px;
  width: min(100%, 304px);
  padding: 6px;
  border: 1px solid #2a3358;
  border-radius: 8px;
  background: radial-gradient(120% 120% at 50% 0%, #1d2a55, #101733 70%);
}

.spectate__board .cell {
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

.spectate__board .cell.hit {
  border-color: var(--role-enemy);
  background: #4a1d1d;
  color: var(--role-enemy);
}

.spectate__board .cell.miss {
  color: var(--accent-cyan);
}

.spectate__board .cell.sunk {
  border-color: var(--role-enemy);
  background: #611f1a;
  color: var(--role-enemy);
}

.spectate__hint {
  order: -1;
  margin: 0;
  padding: 8px 14px;
  border: 1px solid var(--panel-line);
  border-radius: 8px;
  background: rgba(21, 26, 48, 0.6);
  color: var(--text-muted);
  font-size: 12px;
}

.spectate__panel {
  padding: 10px 14px;
  border: 1px solid var(--panel-line);
  border-radius: 10px;
  background: var(--panel);
  min-width: 0;
}

.spectate__panel-title {
  margin: 0 0 8px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--line-dash);
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.spectate__chain,
.spectate__logs,
.spectate__roster,
.spectate__chat {
  display: grid;
  gap: 4px;
  max-height: 110px;
  overflow-y: auto;
  font-size: 12px;
}

.spectate__chain-item,
.spectate__log,
.spectate__roster-item,
.spectate__chat-line {
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--surface-deck);
}

.spectate__chain-item.negated {
  color: var(--role-enemy);
  text-decoration: line-through;
}

.spectate__roster-item.me {
  border: 1px solid var(--accent-strong);
  color: var(--accent-strong);
}

.spectate__chat-line.kind-player {
  border-left: 2px solid var(--accent);
}

.spectate__chat-line.kind-notice,
.spectate__chat-line.kind-error {
  color: var(--text-muted);
  font-style: italic;
}

.spectate__chat-line.kind-error {
  color: var(--role-enemy);
  font-style: normal;
}

.spectate__muted {
  color: var(--text-dim);
  font-size: 12px;
}

.spectate__chat-form {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.spectate__chat-input {
  flex: 1;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-sunken);
  color: var(--text);
  font: inherit;
  font-size: 13px;
}

.spectate__chat-note {
  margin: 6px 0 0;
  color: var(--text-dim);
  font-size: 11px;
}

@media (min-width: 900px) {
  .spectate__boards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .spectate__body {
    grid-template-columns: minmax(0, 1fr) 422px;
    align-items: start;
  }

  .spectate__side {
    margin-top: 0;
  }

  .spectate__side {
    display: grid;
    gap: 8px;
  }
}

@media (max-width: 899px) {
  .spectate__side {
    display: grid;
    gap: 12px;
  }
}

@media (max-width: 520px) {
  .spectate__title {
    font-size: 22px;
  }

  .spectate__topbar {
    gap: 6px 12px;
    font-size: 12px;
  }

  .spectate__leave {
    margin-left: 0;
  }
}
</style>
