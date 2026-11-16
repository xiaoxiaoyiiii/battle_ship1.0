<script setup lang="ts">
/**
 * 神秘科技选择（20 秒三选一）与结算瞄准（15 秒）界面。
 * 倒计时按服务端绝对期限；锁定后只提示「对方已锁定」，不展示名字。
 * 神话全屏闪光、传说流光描边、优质淡边光；减弱动效时全部改为静态。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import BoardPanel from './BoardPanel.vue'
import { useGameStore } from '../../stores/game'
import { useMysteryTechStore } from '../../stores/mysteryTech'
import { useUiStore } from '../../stores/ui'
import { getSettlementSocket } from '../../realtime/settlement'
import { emitMysteryTechChoose, emitMysteryTechRefresh, emitMysteryTechTarget } from '../../realtime/mysteryTech'
import { buildOpponentBoard, buildSelfBoard, cellKey } from './view'
import {
  cellKeyOf,
  formatCountdown,
  mysteryTechReducedMotion,
  opponentLocked,
  remainingMsUntil,
  shipByCell,
  sonarPreview,
  targetKindHint,
  targetKindTitle,
  tierLabel,
  timingLabel,
  waitingText,
} from './mysteryTechView'
import type { MysteryTechCell, MysteryTechTargetShip } from '../../stores/mysteryTechTypes'
import './mysteryTech.css'

const game = useGameStore()
const tech = useMysteryTechStore()
const ui = useUiStore()
const route = useRoute()

/** 选择/瞄准层只给本局入座玩家看；观战与回放只用对局台上的公开徽章。 */
const seated = computed(() => {
  const name = String(route.name || '')
  return (name === 'game' || name === 'placement' || name === 'rps' || name === 'start')
    && Boolean(game.state.room_id && game.state.player_id)
})

const now = ref(Date.now())
const pickedId = ref('')
const pickedShip = ref<number | null>(null)
const hoverCell = ref<MysteryTechCell | null>(null)
const flashing = ref(false)
let tick: number | null = null
let flashTimer: number | null = null

const reduced = computed(() => mysteryTechReducedMotion(ui.motion))
const snapshot = computed(() => tech.state)
const selfSeat = computed(() => game.state.player_seat || '')
const selfId = computed(() => game.state.player_id)
const roomState = computed(() => game.state.state)
const enabled = computed(() => tech.enabled || game.state.mystery_tech === true || snapshot.value.enabled)

const selectionOpen = computed(() => {
  if (!seated.value || !enabled.value) return false
  const stage = snapshot.value.stage
  const inSelection = roomState.value === 'mystery_tech_selection' || stage === 'selecting' || stage === 'locked'
  return inSelection && (snapshot.value.options.length > 0 || Boolean(snapshot.value.locked_tech_id) || stage === 'selecting' || stage === 'locked')
})

const hasPrivateChoice = computed(() => snapshot.value.options.length > 0 || Boolean(snapshot.value.locked_tech_id))

const targetMine = computed(() => {
  const target = snapshot.value.target
  return Boolean(target && selfId.value && target.player_id === selfId.value)
})

const targetingOpen = computed(() => seated.value && enabled.value && snapshot.value.stage === 'targeting' && targetMine.value)

const waitingOpen = computed(() => {
  if (!seated.value || !enabled.value || selectionOpen.value || targetingOpen.value) return false
  const stage = snapshot.value.stage
  return stage === 'effect_waiting' || stage === 'resolving' || (stage === 'targeting' && !targetMine.value) || (roomState.value === 'mystery_tech_resolution' && stage !== 'idle')
})

const isSelfResolving = computed(() => {
  const who = snapshot.value.resolving_player
  return Boolean(who && selfId.value && who === selfId.value)
})

const selectionDeadlineMs = computed(() => remainingMsUntil(snapshot.value.deadline, snapshot.value.remaining_ms, tech.receivedAt, now.value))
const targetDeadlineMs = computed(() => {
  const target = snapshot.value.target
  if (!target) return 0
  return remainingMsUntil(target.deadline, null, tech.targetReceivedAt || tech.receivedAt, now.value)
})
const selectionSeconds = computed(() => formatCountdown(selectionDeadlineMs.value))
const targetSeconds = computed(() => formatCountdown(targetDeadlineMs.value))

const alreadyLocked = computed(() => Boolean(snapshot.value.locked_tech_id))
const peerLocked = computed(() => opponentLocked(snapshot.value.locked_players, selfSeat.value))
const canAct = computed(() => !alreadyLocked.value && snapshot.value.stage === 'selecting' && !tech.pending)

watch(
  () => snapshot.value.locked_tech_id,
  (id) => {
    if (id) pickedId.value = id
  },
  { immediate: true },
)

watch(
  () => snapshot.value.options.map((item) => item.tech_id).join(','),
  () => {
    if (!pickedId.value || snapshot.value.options.some((item) => item.tech_id === pickedId.value)) return
    pickedId.value = ''
  },
)

watch(
  () => snapshot.value.target?.request_id,
  () => {
    pickedShip.value = null
    hoverCell.value = null
  },
)

watch(
  () => tech.flashTechIds.slice(),
  (ids) => {
    if (!ids.length || reduced.value) {
      if (ids.length) tech.consumeFlash()
      return
    }
    tech.consumeFlash()
    flashing.value = true
    if (flashTimer) window.clearTimeout(flashTimer)
    flashTimer = window.setTimeout(() => {
      flashing.value = false
      flashTimer = null
    }, 700)
  },
)

onMounted(() => {
  tick = window.setInterval(() => {
    now.value = Date.now()
  }, 200)
})
onBeforeUnmount(() => {
  if (tick) window.clearInterval(tick)
  if (flashTimer) window.clearTimeout(flashTimer)
})

async function refreshSlot(slot: number, event: Event): Promise<void> {
  event.stopPropagation()
  if (!canAct.value) return
  const option = snapshot.value.options[slot]
  if (!option || option.refresh_used) return
  const socket = getSettlementSocket()
  if (!socket) {
    tech.setError('还没有连上对局连接')
    return
  }
  await emitMysteryTechRefresh(socket, slot)
}

async function lockChoice(): Promise<void> {
  if (!canAct.value || !pickedId.value) return
  const socket = getSettlementSocket()
  if (!socket) {
    tech.setError('还没有连上对局连接')
    return
  }
  await emitMysteryTechChoose(socket, pickedId.value)
}

function pickCard(techId: string): void {
  if (!canAct.value) return
  pickedId.value = techId
}

const target = computed(() => snapshot.value.target)
const targetTechName = computed(() => {
  const id = target.value?.tech_id
  const found = snapshot.value.selected.find((item) => item.tech_id === id)
  return found?.technology.name || id || ''
})

const targetBoard = computed(() => {
  const kind = target.value?.kind
  return kind === 'sonar_pulse' || kind === 'spacetime_fold' ? 'opponent' : 'self'
})

const legalKeys = computed(() => (target.value?.legal_cells ?? []).map((cell) => cellKey(cell.x, cell.y)))

const previewKeys = computed(() => {
  if (target.value?.kind !== 'sonar_pulse' || !hoverCell.value) return []
  const legal = new Set(legalKeys.value)
  if (!legal.has(cellKeyOf(hoverCell.value))) return []
  return sonarPreview(hoverCell.value).map((cell) => cellKey(cell.x, cell.y))
})

const boardCells = computed(() => {
  const kind = target.value?.kind
  const cells = targetBoard.value === 'opponent' ? buildOpponentBoard(game.state) : buildSelfBoard(game.state)
  if (kind === 'spacetime_fold' || kind === 'revive') {
    for (const ship of target.value?.ships ?? []) {
      for (const pos of ship.positions) {
        const cell = cells.find((item) => item.x === pos.x && item.y === pos.y)
        if (!cell) continue
        cell.ship = true
        if (kind === 'spacetime_fold') cell.revealed = true
        if (kind === 'revive') cell.sunk = true
      }
    }
  }
  return cells
})

const selectedKeys = computed(() => {
  if (pickedShip.value == null) return []
  const ship = target.value?.ships.find((item) => item.ship_index === pickedShip.value)
  return (ship?.positions ?? []).map((cell) => cellKey(cell.x, cell.y))
})

function shipLabel(ship: MysteryTechTargetShip, index: number): string {
  if (ship.positions.length) {
    const cells = ship.positions.map((cell) => `${cell.x + 1},${cell.y + 1}`).join(' / ')
    return `残骸 ${index + 1}（格 ${cells}）`
  }
  return `残骸 ${index + 1}（已离开棋盘）`
}

async function submitTarget(fields: Record<string, unknown>): Promise<void> {
  const current = target.value
  if (!current || tech.pending) return
  const socket = getSettlementSocket()
  if (!socket) {
    tech.setError('还没有连上对局连接')
    return
  }
  await emitMysteryTechTarget(socket, current.request_id, fields)
}

async function onTargetCell(x: number, y: number): Promise<void> {
  const current = target.value
  if (!current || tech.pending) return
  const key = cellKey(x, y)
  if (current.kind === 'spacetime_fold') {
    const ship = shipByCell(current.ships, x, y)
    if (!ship) return
    pickedShip.value = ship.ship_index
    await submitTarget({ ship_index: ship.ship_index })
    return
  }
  if (!legalKeys.value.includes(key)) return
  if (current.kind === 'sonar_pulse' || current.kind === 'fleet_rebirth') {
    await submitTarget({ x, y })
    return
  }
  if (current.kind === 'revive') {
    if (pickedShip.value == null) {
      tech.setError('请先选择一艘可复活的沉船')
      return
    }
    await submitTarget({ ship_index: pickedShip.value, x, y })
  }
}

function onTargetHover(point: { x: number; y: number } | null): void {
  hoverCell.value = point
}
</script>

<template>
  <Teleport to="body">
    <div v-if="flashing && !reduced" class="mt-flash" data-testid="mystery-tech-mythic-flash" aria-hidden="true"></div>

    <div
      v-if="selectionOpen"
      class="mt-overlay"
      data-testid="mystery-tech-selection"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mystery-tech-selection-title"
    >
      <section class="mt-panel">
        <header class="mt-panel__head">
          <div>
            <p class="mt-panel__context">神秘科技大乱斗</p>
            <h2 id="mystery-tech-selection-title" class="mt-panel__title">三选一 · 第 {{ snapshot.selection_round || 1 }} 次选择</h2>
            <p class="mt-panel__lead">
              {{ alreadyLocked ? '已锁定，等待对方确认。超时由服务器从当前选项中随机锁定。' : '限时内选择一项锁定。每张只能刷新一次，刷新不延长倒计时。' }}
            </p>
          </div>
          <div class="mt-countdown" :class="{ 'is-urgent': selectionDeadlineMs <= 5000 }" data-testid="mystery-tech-selection-countdown" role="timer">
            <b>{{ selectionSeconds }}</b>
            <span>秒后超时</span>
          </div>
        </header>

        <div v-if="hasPrivateChoice && snapshot.options.length" class="mt-cards">
          <article
            v-for="(option, slot) in snapshot.options"
            :key="option.tech_id"
            class="mt-card"
            :class="[
              `is-${option.technology.tier}`,
              { 'is-picked': pickedId === option.tech_id, 'is-locked': alreadyLocked, 'is-static': reduced },
            ]"
            :data-testid="`mystery-tech-card-${option.tech_id}`"
            :data-tier="option.technology.tier"
          >
            <button type="button" class="mt-card" style="all:unset;display:flex;flex-direction:column;flex:1;cursor:inherit" :disabled="alreadyLocked" @click="pickCard(option.tech_id)">
              <p class="mt-card__tier">{{ tierLabel(option.technology.tier) }}</p>
              <h3 class="mt-card__name">{{ option.technology.name }}</h3>
              <p class="mt-card__timing">{{ timingLabel(option.technology.timing) }}</p>
              <p class="mt-card__desc">{{ option.technology.description }}</p>
            </button>
            <button
              type="button"
              class="mt-refresh"
              :data-testid="`mystery-tech-refresh-${slot}`"
              :disabled="alreadyLocked || option.refresh_used || !!tech.pending || snapshot.stage !== 'selecting'"
              @click="refreshSlot(slot, $event)"
            >
              {{ option.refresh_used ? '已刷新' : '刷新这张' }}
            </button>
          </article>
        </div>
        <p v-else class="mt-status" data-testid="mystery-tech-selection-hidden">双方正在选择神秘科技。选项不对观众或对手公开。</p>

        <div class="mt-actions">
          <p class="mt-status" :class="{ 'is-peer': peerLocked }" data-testid="mystery-tech-lock-status">
            <template v-if="alreadyLocked">已锁定{{ snapshot.locked_tech_id ? '「' + (snapshot.options.find(item => item.tech_id === snapshot.locked_tech_id)?.technology.name || snapshot.locked_tech_id) + '」' : '' }}，等待对方选择。</template>
            <template v-else>点选一张后锁定。超时将由系统随机锁定。</template>
            <template v-if="peerLocked"> 对方已锁定。</template>
          </p>
          <button
            v-if="hasPrivateChoice"
            type="button"
            class="mt-lock"
            data-testid="mystery-tech-lock"
            :disabled="!canAct || !pickedId"
            @click="lockChoice"
          >
            {{ alreadyLocked ? '已锁定' : '锁定选择' }}
          </button>
        </div>
        <p v-if="tech.error" class="mt-error" data-testid="mystery-tech-error" role="alert">{{ tech.error }}</p>
      </section>
    </div>

    <div
      v-else-if="targetingOpen && target"
      class="mt-overlay"
      data-testid="mystery-tech-target"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mystery-tech-target-title"
    >
      <section class="mt-panel">
        <header class="mt-panel__head">
          <div>
            <p class="mt-panel__context">神秘科技结算</p>
            <h2 id="mystery-tech-target-title" class="mt-panel__title">{{ targetKindTitle(target.kind, targetTechName) }}</h2>
            <p class="mt-panel__lead">{{ targetKindHint(target.kind, target.remaining) }}</p>
          </div>
          <div class="mt-countdown" :class="{ 'is-urgent': targetDeadlineMs <= 5000 }" data-testid="mystery-tech-target-countdown" role="timer">
            <b>{{ targetSeconds }}</b>
            <span>秒后超时</span>
          </div>
        </header>

        <div class="mt-target__body">
          <div class="mt-board">
            <BoardPanel
              :board="targetBoard"
              board-testid="mystery-tech-target-board"
              title-testid="mystery-tech-target-board-title"
              :title="targetBoard === 'self' ? '己方海域 · 选择落点' : '对方海域 · 选择目标'"
              :cells="boardCells"
              :legal="legalKeys"
              :preview="previewKeys"
              :selected="selectedKeys"
              :picking="true"
              :selection-board="targetBoard"
              :selection-kind="target.kind === 'sonar_pulse' ? 'area' : (target.kind === 'spacetime_fold' || target.kind === 'revive' ? 'ships' : null)"
              selection-tone="radar"
              :selection-label="targetTechName"
              :interactive="!tech.pending"
              cell-prefix="mystery-tech-cell"
              @cell="onTargetCell"
              @hover="onTargetHover"
            />
          </div>
          <aside v-if="target.kind === 'revive' || target.kind === 'spacetime_fold'" class="mt-ships">
            <button
              v-for="(ship, index) in target.ships"
              :key="ship.ship_index"
              type="button"
              class="mt-ship"
              :class="{ 'is-picked': pickedShip === ship.ship_index }"
              :data-testid="`mystery-tech-ship-${ship.ship_index}`"
              :disabled="!!tech.pending"
              @click="target.kind === 'spacetime_fold' ? submitTarget({ ship_index: ship.ship_index }) : (pickedShip = ship.ship_index, tech.setError(''))"
            >
              {{ target.kind === 'revive' ? shipLabel(ship, index) : `目标舰 ${index + 1}` }}
            </button>
            <p v-if="!target.ships.length" class="mt-status">当前没有可选的船。</p>
          </aside>
        </div>
        <p v-if="tech.error" class="mt-error" data-testid="mystery-tech-error" role="alert">{{ tech.error }}</p>
      </section>
    </div>

    <div
      v-else-if="waitingOpen"
      class="mt-banner"
      data-testid="mystery-tech-waiting"
      role="status"
    >
      {{ waitingText(snapshot.stage, isSelfResolving) }}
    </div>
  </Teleport>
</template>
