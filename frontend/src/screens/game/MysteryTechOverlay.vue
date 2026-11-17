<script setup lang="ts">
/**
 * 神秘科技选择（20 秒三选一）界面与等待横幅。
 * 结算瞄准（15 秒）已移到对局真实战斗棋盘上（GameScreen + useMysteryTechTargeting），这里不再画映射小棋盘。
 * 倒计时按服务端绝对期限；锁定后只提示「对方已锁定」，不展示名字。
 * 神话全屏闪光、传说流光描边、优质淡边光；减弱动效时全部改为静态。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useGameStore } from '../../stores/game'
import { useMysteryTechStore } from '../../stores/mysteryTech'
import { useUiStore } from '../../stores/ui'
import { getSettlementSocket } from '../../realtime/settlement'
import { emitMysteryTechChoose, emitMysteryTechRefresh } from '../../realtime/mysteryTech'
import {
  formatCountdown,
  mysteryTechReducedMotion,
  opponentLocked,
  remainingMsUntil,
  tierLabel,
  timingLabel,
  waitingText,
} from './mysteryTechView'
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
  // locked表示双方均已锁定，后台已进入猜拳；本人先锁时仍为selecting。
  if (stage === 'locked') return false
  const inSelection = roomState.value === 'mystery_tech_selection' || stage === 'selecting'
  return inSelection && (snapshot.value.options.length > 0 || Boolean(snapshot.value.locked_tech_id) || stage === 'selecting')
})

const hasPrivateChoice = computed(() => snapshot.value.options.length > 0 || Boolean(snapshot.value.locked_tech_id))

const targetMine = computed(() => {
  const target = snapshot.value.target
  return Boolean(target && selfId.value && target.player_id === selfId.value)
})

/** 本人瞄准时由对局棋盘上的提示条接管（GameScreen），这里只负责不再弹等待横幅。 */
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
const selectionSeconds = computed(() => formatCountdown(selectionDeadlineMs.value))

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
            <h2 id="mystery-tech-selection-title" class="mt-panel__title">三选一 · 第 {{ snapshot.selection_round || 1 }} 大回合</h2>
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
            <div class="mt-card__fx" aria-hidden="true">
              <span class="mt-card__orbit"></span>
              <span v-if="option.technology.tier === 'mythic'" class="mt-card__orbit mt-card__orbit--outer"></span>
              <i v-for="n in (option.technology.tier === 'mythic' ? 18 : option.technology.tier === 'legendary' ? 7 : 0)"
                :key="n" class="mt-card__spark"
                :style="{ '--spark-x': `${(n * 37) % 96}%`, '--spark-y': `${(n * 23) % 88}%`, '--spark-delay': `${-n * .29}s`, '--spark-size': `${n % 3 + 2}px` }"></i>
            </div>
            <button type="button" class="mt-card__pick" :disabled="alreadyLocked" :aria-pressed="pickedId === option.tech_id" @click="pickCard(option.tech_id)">
              <span class="mt-card__crest" aria-hidden="true">{{ option.technology.tier === 'mythic' ? '✺' : option.technology.tier === 'legendary' ? '✦' : '◇' }}</span>
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
      v-else-if="waitingOpen"
      class="mt-banner"
      data-testid="mystery-tech-waiting"
      role="status"
    >
      {{ waitingText(snapshot.stage, isSelfResolving) }}
    </div>
  </Teleport>
</template>
