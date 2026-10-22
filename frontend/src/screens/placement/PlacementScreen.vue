<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { acquireMatchChannel, emitMatchEvent, matchSocket } from '../../realtime/match'
import { useGameStore } from '../../stores/game'
import { BOARD_SIZE, usePlacementStore } from '../../stores/placement'
import AppOverlay from '../../components/AppOverlay.vue'
import { getSettlementSocket } from '../../realtime/settlement'
import { useUiStore } from '../../stores/ui'

/**
 * Ticket #23: the opening placement screen.
 *
 * Data flow (port map 14 section 1.4):
 *   game_state / room_sync -> useGameStore (state, room, names, ships)
 *   reset_gameboard        -> usePlacementStore.applyReset (new_max_ships)
 *   clicks                 -> usePlacementStore draft cells
 *   confirm                -> place_ships ack -> submitted | verbatim rejection
 *   game_state{rock_paper_scissors} -> /rps (route name is frozen by #21)
 *
 * The screen never decides legality: it only counts the six single-cell ships
 * the legacy screen counted (the server validates the submission).
 */
const router = useRouter()
const route = useRoute()
const game = useGameStore()
const placement = usePlacementStore()
const ui = useUiStore()
const leaveOpen = ref(false)

let releaseChannel: (() => void) | null = null
let offError: (() => void) | null = null
let offMessage: (() => void) | null = null
let submitToken = 0
let offRoomSync: (() => void) | null = null

const hasRoom = computed(() => Boolean(game.state.room_id))
const selfName = computed(() => game.state.player_name || '你')
const opponentName = computed(() => game.state.opponent_name || '对手')
const seatLabel = computed(() => game.state.player_seat || '—')
const canEdit = computed(() => hasRoom.value && !placement.locked)

/** Player-language opponent status. Never guesses "offline" without a frame. */
const opponentStatus = computed(() => {
  if (!game.state.opponent_name) return { state: 'waiting', text: '等待对手加入房间' }
  if (!placement.opponentStateKnown) {
    return { state: 'unknown', text: '对手已入座 · 重新同步后才能看到对手的准备状态' }
  }
  if (!placement.opponentOnline) return { state: 'offline', text: '对手已掉线，等待重连（不会判你负）' }
  if (placement.opponentReady) return { state: 'ready', text: '对手已摆好战舰，等你确认' }
  return { state: 'thinking', text: '对手在线，正在摆战舰' }
})

interface BoardCellView {
  key: string
  x: number
  y: number
  ship: boolean
}

const boardCells = computed<BoardCellView[]>(() => {
  const cells: BoardCellView[] = []
  for (let y = 0; y < BOARD_SIZE; y += 1) {
    for (let x = 0; x < BOARD_SIZE; x += 1) {
      cells.push({ key: x + '-' + y, x, y, ship: placement.isPlaced(x, y) })
    }
  }
  return cells
})

const emptySlots = computed(() => {
  const missing = Math.max(0, placement.maxShips - placement.placedCount)
  return Array.from({ length: missing }, (_, index) => index)
})

function readText(payload: Record<string, unknown>, key: string): string {
  const value = payload[key]
  return typeof value === 'string' ? value : ''
}

function routeForState(state: string): void {
  if (route.name !== 'placement') return
  if (state === 'rock_paper_scissors') {
    void router.push({ name: 'rps' })
  } else if (state === 'attacking') {
    // A mid-game redeploy (回光返照 / 灵气复苏 / 败者食尘) sets room.state back
    // to placing_ships while the client may still see attacking; resetPhase
    // keeps this screen mounted until the server accepts the new board.
    if (!placement.resetPhase) void router.push({ name: 'game' })
  } else if (state === 'game_over') {
    void router.push({ name: 'game-over' })
  }
}

onMounted(() => {
  releaseChannel = acquireMatchChannel()
  const socket = matchSocket()
  if (socket) {
    offError = socket.on('error', (payload) => placement.noteNotice(readText(payload, 'message')))
    offMessage = socket.on('message', (payload) => placement.noteNotice(readText(payload, 'message')))
    offRoomSync = socket.on('room_sync', (payload) => placement.adoptOpponentState(payload))
  }
  placement.resetForEntry()
  if (game.state.state === 'placing_ships') placement.adoptFromServer(game.state.ships)
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
  () => game.state.ships,
  (ships) => {
    if (game.state.state !== 'placing_ships') return
    if (placement.pending) return
    placement.adoptFromServer(ships)
  },
  { deep: true },
)

watch(
  () => game.state.state,
  (state) => routeForState(state),
  { immediate: true },
)

function randomize(): void {
  placement.randomize()
}

function clearBoard(): void {
  placement.clearBoard()
  placement.clearReceipt()
}

/** A refused click still answers once: the board never goes silent. */
function toggleCell(x: number, y: number): void {
  if (!canEdit.value) {
    placement.noteReceipt(
      placement.submitted || placement.pending
        ? '已提交 · 等对手摆好就能开始猜拳；要退出可以点「离开房间」'
        : '还没进入房间，先创建或加入房间再布船',
    )
    return
  }
  placement.clearReceipt()
  placement.toggleCell(x, y)
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
      placement.reset()
      void router.push({ name: 'lobby' })
      return
    }
    placement.noteReceipt(
      typeof ack?.message === 'string' && ack.message ? ack.message : '离开房间没有成功，请稍后再试',
    )
  } catch (error) {
    leaveOpen.value = false
    placement.noteReceipt('离开房间没有成功：' + (error instanceof Error ? error.message : '网络不稳定'))
  }
}

async function confirm(): Promise<void> {
  if (!canEdit.value || !placement.canSubmit) return
  const socket = matchSocket()
  if (!socket || !socket.socket.connected) {
    placement.noteNotice('连接已断开，正在重连。稍后会自动同步房间状态，再试一次即可。')
    return
  }
  const roomId = game.state.room_id
  const playerId = game.state.player_id
  if (!roomId || !playerId) {
    placement.noteNotice('还没进入房间，请重新创建或加入房间。')
    return
  }
  const token = ++submitToken
  placement.beginPending()
  const ships = placement.cells.map((cell) => ({ positions: [{ x: cell.x, y: cell.y }] }))
  try {
    const ack = await emitMatchEvent(socket, 'place_ships', {
      room_id: roomId,
      player_id: playerId,
      ships,
    })
    if (token !== submitToken || !placement.pending) return
    placement.settleSubmit(ack?.status === 'success', typeof ack?.message === 'string' ? ack.message : '')
  } catch (error) {
    if (token !== submitToken || !placement.pending) return
    placement.settleSubmit(false, error instanceof Error ? error.message : '')
  }
}

function returnHome(): void {
  void router.push({ name: 'start' })
}
</script>

<template>
  <section
    class="screen placement"
    data-screen="placement"
    data-testid="screen-placement"
    aria-labelledby="screen-placement-title"
  >
    <header class="placement__head">
      <p class="placement__eyebrow">开局 · 布船</p>
      <h1 id="screen-placement-title" class="placement__title" data-testid="placement-heading">
        放置你的战舰
      </h1>
      <p class="placement__lead">6×6 棋盘各放 1 格，共 6 格 · 再点一次可取消</p>
    </header>

    <div class="placement__players">
      <span class="placement__player">你 <b data-testid="placement-self">{{ selfName }}</b></span>
      <span class="placement__seat" aria-label="座位">{{ seatLabel }}</span>
      <span class="placement__vs" aria-hidden="true">VS</span>
      <span class="placement__player placement__player--opponent">
        对手 <b data-testid="placement-opponent">{{ opponentName }}</b>
      </span>
    </div>

    <p
      class="placement__opponent-state"
      data-testid="placement-opponent-status"
      :data-state="opponentStatus.state"
      role="status"
      aria-live="polite"
    >
      {{ opponentStatus.text }}
    </p>

    <p v-if="!hasRoom" class="placement__empty" data-testid="placement-empty" role="status">
      还没进入房间，先创建或加入房间再布船。
    </p>

    <div class="placement__layout">
      <div class="placement__board-wrap">
        <div
          class="placement__board"
          data-testid="placement-board"
          role="grid"
          aria-label="布船棋盘，共 36 格"
        >
          <button
            v-for="cell in boardCells"
            :key="cell.key"
            type="button"
            class="placement__cell"
            :class="{ 'is-ship': cell.ship }"
            role="gridcell"
            :data-testid="'placement-cell-' + cell.x + '-' + cell.y"
            :aria-pressed="cell.ship ? 'true' : 'false'"
            :aria-label="
              '第 ' + (cell.x + 1) + ' 列第 ' + (cell.y + 1) + ' 行，' +
              (cell.ship ? '已放置战舰，点击撤销' : '空格，点击放置战舰')
            "
            :aria-disabled="!canEdit"
            @click="toggleCell(cell.x, cell.y)"
          >
            <span v-if="cell.ship" class="placement__mark" aria-hidden="true">◆</span>
          </button>
        </div>
      </div>

      <aside class="placement__side" aria-label="布船状态与操作">
        <p class="placement__count">
          已放置
          <b data-testid="placement-count">{{ placement.placedCount }}</b>
          <span class="placement__slash" aria-hidden="true">/</span>
          <span data-testid="placement-total">{{ placement.total }}</span>
        </p>

        <ol class="placement__ships" data-testid="placement-ships" aria-label="已放置的战舰格">
          <li
            v-for="cell in placement.cells"
            :key="cell.x + '-' + cell.y"
            class="placement__ship"
            :data-testid="'placement-ship-' + cell.x + '-' + cell.y"
          >
            {{ cell.x + 1 }},{{ cell.y + 1 }}
          </li>
          <li
            v-for="slot in emptySlots"
            :key="'empty-' + slot"
            class="placement__ship placement__ship--empty"
            aria-hidden="true"
          >
            空
          </li>
        </ol>

        <p
          v-if="placement.submitted"
          class="placement__submitted"
          data-testid="placement-submitted"
          role="status"
        >
          已提交
        </p>

        <p class="placement__hint" data-testid="placement-hint" role="status" aria-live="polite">
          {{ placement.hint }}
        </p>

        <p
          v-if="placement.receipt"
          class="placement__receipt"
          data-testid="placement-receipt"
          role="status"
          aria-live="polite"
        >
          {{ placement.receipt }}
        </p>

        <p
          v-if="placement.pending"
          class="placement__pending"
          data-testid="placement-pending"
          role="status"
          aria-live="polite"
        >
          正在提交，等待服务器回执…
          <b data-testid="placement-pending-countdown">{{ placement.countdown }}s</b>
        </p>

        <p
          v-if="placement.error"
          class="placement__error"
          data-testid="placement-error"
          role="alert"
        >
          {{ placement.error }}
        </p>

        <p
          v-if="placement.resetMessage"
          class="placement__reset"
          data-testid="placement-reset-note"
          role="status"
        >
          {{ placement.resetMessage }}
        </p>

        <div class="placement__actions">
          <button
            type="button"
            class="button button--ghost"
            data-testid="placement-clear"
            :disabled="!canEdit || placement.placedCount === 0"
            @click="clearBoard"
          >
            清空
          </button>
          <button
            type="button"
            class="button button--ghost"
            data-testid="placement-random"
            :disabled="!canEdit"
            @click="randomize"
          >
            随机摆放
          </button>
          <button
            type="button"
            class="button"
            data-primary-action="true"
            data-testid="placement-confirm"
            :disabled="!canEdit || !placement.canSubmit"
            @click="confirm"
          >
            确认放置
          </button>
          <button
            type="button"
            class="button button--ghost placement__leave"
            data-testid="placement-leave"
            @click="leaveOpen = true"
          >
            离开房间
          </button>
          <button
            v-if="!hasRoom"
            type="button"
            class="button button--ghost"
            data-testid="placement-return-home"
            @click="returnHome"
          >
            返回首页
          </button>
        </div>
      </aside>
    </div>

    <AppOverlay
      v-if="leaveOpen"
      id="placement-leave-overlay"
      :priority="140"
      label="离开房间确认"
      @close="leaveOpen = false"
    >
      <section class="placement__confirm" data-testid="placement-leave-confirm">
        <h2 class="placement__confirm-title">离开房间？</h2>
        <p class="placement__confirm-text">
          布船阶段离开会按认输处理：本局判负并结算{{ game.state.ranked ? '，排位会扣分' : '' }}。留在房间里可以等对手。
        </p>
        <div class="placement__confirm-actions">
          <button type="button" class="button button--ghost" data-testid="placement-leave-cancel" @click="leaveOpen = false">
            继续等待
          </button>
          <button type="button" class="button" data-testid="placement-leave-confirm-ok" @click="leaveRoom">
            确认离开（判负）
          </button>
        </div>
      </section>
    </AppOverlay>
  </section>
</template>

<style scoped>
.placement {
  position: relative;
  gap: 8px;
  padding-top: 8px;
}

.placement__head {
  display: grid;
  gap: 1px;
}

.placement__eyebrow {
  margin: 0;
  color: var(--text-secondary);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.placement__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.placement__lead {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

/* Seats ride on the header line instead of owning a strip: the C+ deployment
   screen gives the board the whole stage. Same data, no extra row. */
.placement__players {
  position: absolute;
  top: 16px;
  right: 24px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  max-width: 60%;
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-deck);
  font-size: 13px;
}

.placement__player b {
  color: var(--text);
  font-weight: 600;
}

.placement__player--opponent {
  margin-left: auto;
}

.placement__seat {
  padding: 1px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 11px;
}

.placement__vs {
  color: var(--text-dim);
  font-size: 10px;
  letter-spacing: 0.18em;
}

.placement__empty {
  margin: 0;
  padding: 10px 14px;
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 13px;
}

/* Board + side card are one centred pair, as in the C+ deployment screen. */
.placement__layout {
  display: grid;
  grid-template-columns: minmax(0, 420px) 272px;
  gap: 24px;
  justify-content: center;
  align-items: start;
  margin-top: 27px;
}

.placement__board-wrap {
  display: flex;
  justify-content: center;
  padding: 22px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.placement__board {
  display: grid;
  grid-template-columns: repeat(6, var(--placement-cell));
  grid-auto-rows: var(--placement-cell);
  gap: 4px;
  --placement-cell: 53px;
}

.placement__cell {
  display: grid;
  place-items: center;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--board-border) 70%, transparent);
  border-radius: 8px;
  background: var(--cell-bg);
  color: var(--role-action);
  font: inherit;
  cursor: pointer;
  transition: transform 120ms ease, background 120ms ease, border-color 120ms ease;
}

.placement__cell:hover:not(:disabled) {
  border-color: var(--role-action);
  background: color-mix(in srgb, var(--role-action) 26%, var(--cell-bg));
}

.placement__cell:disabled {
  cursor: default;
  opacity: 0.72;
}

.placement__cell.is-ship {
  border-color: var(--ship-metal);
  background: linear-gradient(160deg, var(--ship-metal), color-mix(in srgb, var(--ship-metal) 62%, #0b0d18));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ship-metal) 60%, #fff);
}

.placement__mark {
  color: #0b0d18;
  font-size: 16px;
  line-height: 1;
}

.placement__side {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 398px;
  padding: 20px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.placement__count {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.placement__count b {
  color: var(--text);
  font-size: 24px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.placement__slash {
  margin: 0 3px;
  color: var(--text-muted);
}

.placement__ships {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 30px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.placement__ship {
  flex: 0 0 calc((100% - 12px) / 3);
  min-width: 0;
  padding: 6px 10px;
  border: 1px solid color-mix(in srgb, var(--role-action) 50%, transparent);
  border-radius: 7px;
  background: var(--accent-soft);
  color: var(--text);
  font-size: 12px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.placement__ship--empty {
  border-style: dashed;
  border-color: var(--border);
  background: transparent;
  color: var(--text-dim);
}

.placement__submitted {
  margin: 0;
  padding: 4px 10px;
  justify-self: start;
  border: 1px solid color-mix(in srgb, var(--role-success) 40%, transparent);
  border-radius: 999px;
  background: rgba(42, 143, 104, 0.18);
  color: var(--success);
  font-size: 12px;
}

.placement__hint {
  margin: 0;
  color: var(--gold-strong);
  font-size: 12px;
  line-height: 1.6;
}

.placement__pending {
  margin: 0;
  padding: 6px 10px;
  border: 1px solid color-mix(in srgb, var(--role-action) 40%, transparent);
  border-radius: 8px;
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-size: 12px;
}

.placement__pending b {
  font-variant-numeric: tabular-nums;
}

.placement__error {
  margin: 0;
  padding: 6px 10px;
  border: 1px solid color-mix(in srgb, var(--role-enemy) 45%, transparent);
  border-radius: 8px;
  background: rgba(42, 20, 24, 0.8);
  color: var(--role-enemy);
  font-size: 12px;
}

.placement__reset {
  margin: 0;
  padding: 6px 10px;
  border: 1px dashed rgba(230, 199, 120, 0.5);
  border-radius: 8px;
  background: var(--gold-soft);
  color: var(--gold-strong);
  font-size: 12px;
}

.placement__actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: auto;
}

.placement__actions .button {
  width: 100%;
  min-height: 42px;
}

.placement__actions [data-testid='placement-confirm'] {
  min-height: 40px;
  border-color: var(--accent-strong);
  background: var(--hero-grad);
  box-shadow: var(--shadow-accent);
  color: #fff;
  font-weight: 600;
}

.button--ghost {
  border-color: var(--border-strong);
  background: var(--surface-deck);
  color: var(--text-muted);
}

.button--ghost:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--text);
}

.button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

@media (max-width: 980px) {
  .placement__layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
    justify-items: center;
    margin-top: 4px;
  }

  .placement__board-wrap {
    width: 100%;
    max-width: 420px;
    padding: 12px;
  }
}

@media (max-width: 760px) {
  .placement {
    gap: 4px;
    padding: 8px 12px;
  }

  .placement__title {
    font-size: 21px;
  }

  .placement__lead {
    font-size: 11px;
  }

  .placement__layout {
    gap: 6px;
    margin-top: 0;
  }

  .placement__board-wrap {
    padding: 10px;
  }

  .placement__board {
    --placement-cell: clamp(40px, min(12.5vw, 7vh), 52px);
  }

  .placement__side {
    width: 100%;
    max-width: 420px;
    min-height: 0;
    padding: 10px;
    gap: 5px;
  }

  .placement__actions {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .placement__actions .button {
    flex: 1 1 auto;
    width: auto;
  }

  .placement__players {
    position: static;
    max-width: none;
    padding: 4px 10px;
    font-size: 12px;
  }

  .placement__actions .button {
    min-height: 40px;
  }
}

@media (max-height: 720px) {
  .placement__eyebrow,
  .placement__lead {
    display: none;
  }

  .placement__title {
    font-size: 20px;
  }

  .placement__board {
    --placement-cell: clamp(40px, 6.4vh, 48px);
  }
}
.placement__opponent-state {
  margin: 0;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: 12px;
}

.placement__opponent-state[data-state='ready'] {
  border-color: color-mix(in srgb, var(--role-success) 45%, transparent);
  color: var(--success);
}

.placement__opponent-state[data-state='offline'] {
  border-color: color-mix(in srgb, var(--role-enemy) 45%, transparent);
  color: var(--role-enemy);
}

.placement__receipt {
  margin: 0;
  padding: 6px 10px;
  border: 1px solid color-mix(in srgb, var(--gold-strong) 45%, transparent);
  border-radius: 8px;
  background: var(--gold-soft);
  color: var(--gold-strong);
  font-size: 12px;
}

.placement__confirm {
  display: grid;
  gap: 10px;
  padding: 20px 22px;
  text-align: left;
}

.placement__confirm-title {
  margin: 0;
  font-size: 20px;
}

.placement__confirm-text {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.6;
}

.placement__confirm-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

</style>
