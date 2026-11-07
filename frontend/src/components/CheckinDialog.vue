<script setup lang="ts">
import { computed, ref } from 'vue'
import AppOverlay from './AppOverlay.vue'
import { checkinCellState, mondayOffset, useCheckinStore, type CheckinCellState } from '../stores/checkin'
import { useUiStore } from '../stores/ui'

defineProps<{ returnFocus?: () => HTMLElement | null }>()
const emit = defineEmits<{ close: [] }>()

const checkin = useCheckinStore()
const ui = useUiStore()
const note = ref('')
const weekdays = ['一', '二', '三', '四', '五', '六', '日']

const view = computed(() => checkin.status)
const blanks = computed(() => {
  const current = view.value
  if (!current || current.year === null || current.month === null) return 0
  return mondayOffset(current.year, current.month)
})
const days = computed(() => {
  const count = view.value?.daysInMonth ?? 0
  return Array.from({ length: count }, (_, index) => index + 1)
})
const monthLabel = computed(() => {
  const current = view.value
  if (!current) return ''
  if (current.year !== null && current.month !== null) return `${current.year}年${current.month}月`
  return current.today
})
const trackScale = computed(() => Math.max(30, ...(view.value?.milestones.map((item) => item.days) ?? [30])))
const trackWidth = computed(() => {
  const count = view.value?.monthCount ?? 0
  return `${Math.max(0, Math.min(100, (count / trackScale.value) * 100))}%`
})

function stateOf(day: number): CheckinCellState {
  const current = view.value
  return current ? checkinCellState(day, current) : 'unchecked'
}

function cellLabel(day: number, state: CheckinCellState): string {
  const month = view.value?.month
  const prefix = month ? `${month}月${day}日` : `${day}日`
  if (state === 'checked') return `${prefix}，已签到`
  if (state === 'today') return `${prefix}，今日可签`
  return `${prefix}，未签到`
}

async function onClaim(): Promise<void> {
  note.value = ''
  const result = await checkin.claim()
  if (result.needsLogin) {
    ui.requestLogin('login', '登录后即可每日签到。')
    return
  }
  if (!result.ok) return
  if (result.alreadyChecked) {
    note.value = '今天已经签过了。'
    return
  }
  const reward = result.gained !== null && result.gained > 0 ? `，潮汐徽记 +${result.gained}` : ''
  const title = result.titleName ? `，获得「${result.titleName}」` : ''
  ui.notify({
    code: 'checkin-claimed',
    tone: 'success',
    message: `签到成功${reward}${title}`,
  })
}
</script>

<template>
  <AppOverlay
    id="checkin-dialog"
    :priority="110"
    labelledby="checkin-heading"
    :return-focus="returnFocus"
    @close="emit('close')"
  >
    <section class="checkin" data-testid="checkin-dialog-body">
      <header class="checkin__head">
        <div>
          <p class="checkin__eyebrow">潮汐航迹</p>
          <h2 id="checkin-heading">每日签到</h2>
          <p v-if="monthLabel" class="checkin__month" data-testid="checkin-month">{{ monthLabel }}</p>
        </div>
        <button type="button" class="button button--ghost" data-testid="checkin-close" @click="emit('close')">关闭</button>
      </header>

      <p v-if="checkin.loading && !view" class="checkin__status" role="status">正在读取签到…</p>
      <p v-if="checkin.error" class="checkin__error" role="alert" data-testid="checkin-error">{{ checkin.error }}</p>
      <button v-if="checkin.error" type="button" class="button button--ghost" data-testid="checkin-retry" @click="checkin.load()">重试</button>

      <template v-if="view">
        <p class="checkin__count" data-testid="checkin-month-count">本月已签 {{ view.monthCount }} 天</p>
        <div
          v-if="view.year !== null"
          class="checkin__grid"
          role="grid"
          aria-label="本月签到"
          data-testid="checkin-calendar"
        >
          <span v-for="label in weekdays" :key="label" class="checkin__dow" role="columnheader">{{ label }}</span>
          <span v-for="blank in blanks" :key="'blank-' + blank" class="checkin__day is-blank" role="presentation"></span>
          <span
            v-for="day in days"
            :key="day"
            class="checkin__day"
            :class="'is-' + stateOf(day)"
            :data-state="stateOf(day)"
            :data-testid="'checkin-day-' + day"
            role="gridcell"
            :aria-current="view.day === day ? 'date' : undefined"
            :aria-label="cellLabel(day, stateOf(day))"
          >
            <span>{{ day }}</span>
            <span v-if="stateOf(day) === 'checked'" class="checkin__tick" aria-hidden="true">✓</span>
          </span>
        </div>
        <p v-else class="checkin__status">本月已签 {{ view.monthCount }} 天。</p>
        <ul class="checkin__legend">
          <li><i class="is-checked"></i>已签</li>
          <li><i class="is-today"></i>今日可领</li>
          <li><i class="is-unchecked"></i>未签</li>
        </ul>

        <div class="checkin__track" data-testid="checkin-progress">
          <span class="checkin__track-fill" :style="{ width: trackWidth }"></span>
          <span
            v-for="item in view.milestones"
            :key="'mark-' + item.days"
            class="checkin__track-mark"
            :class="{ 'is-reached': item.reached }"
            :style="{ left: `${(item.days / trackScale) * 100}%` }"
          ></span>
        </div>

        <ul class="checkin__rewards">
          <li data-testid="checkin-daily">
            <span>每日</span>
            <b>+{{ view.dailyAmount }}</b>
          </li>
          <li
            v-for="item in view.milestones"
            :key="item.days"
            :data-testid="'checkin-milestone-' + item.days"
            :class="{ 'is-reached': item.reached }"
          >
            <span>满 {{ item.days }} 天</span>
            <b>+{{ item.amount }}</b>
            <small v-if="item.days === 30 && view.title" data-testid="checkin-title">{{ view.title }}</small>
            <small v-if="item.claimed">已领取</small>
            <small v-else-if="item.reached">已达成</small>
            <small v-else>还差 {{ item.days - view.monthCount }} 天</small>
          </li>
        </ul>

        <div class="checkin__actions">
          <button
            type="button"
            class="button button--primary"
            data-testid="checkin-claim"
            :disabled="view.todayChecked || checkin.claiming"
            @click="onClaim"
          >
            {{ checkin.claiming ? '签到中…' : view.todayChecked ? '今日已签到' : `签到领取 +${view.dailyAmount}` }}
          </button>
          <p v-if="note" class="checkin__note" role="status" data-testid="checkin-note">{{ note }}</p>
        </div>
      </template>
    </section>
  </AppOverlay>
</template>

<style>
.app-overlay[data-overlay='checkin-dialog'] .app-overlay__panel {
  width: min(440px, calc(100vw - 28px));
  max-height: calc(100dvh - 28px);
}
</style>

<style scoped>
.checkin {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: calc(100dvh - 28px);
  overflow: auto;
  padding: 18px 18px 16px;
  color: var(--text-primary);
}

.checkin__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.checkin__head h2 {
  margin: 0;
  font-size: 22px;
  letter-spacing: 0.04em;
}

.checkin__eyebrow,
.checkin__month,
.checkin__count,
.checkin__status,
.checkin__note {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.checkin__eyebrow {
  color: var(--gold);
  font-size: 11px;
  letter-spacing: 0.16em;
}

.checkin__error {
  margin: 0;
  color: var(--role-enemy);
  font-size: 13px;
}

.checkin__grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
}

.checkin__dow {
  text-align: center;
  color: var(--text-tertiary);
  font-size: 11px;
  letter-spacing: 0.08em;
}

.checkin__day {
  position: relative;
  display: grid;
  place-items: center;
  aspect-ratio: 1;
  min-height: 36px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: color-mix(in srgb, var(--surface-deck) 70%, transparent);
  color: var(--text-secondary);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.checkin__day.is-blank {
  border-color: transparent;
  background: transparent;
}

.checkin__day.is-checked {
  border-color: color-mix(in srgb, var(--gold) 55%, var(--border-subtle));
  background: color-mix(in srgb, var(--gold) 18%, var(--surface-deck));
  color: var(--text-primary);
}

.checkin__day.is-today {
  border-color: var(--gold);
  background: color-mix(in srgb, var(--role-action) 18%, var(--surface-deck));
  color: var(--text-primary);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--gold) 70%, transparent);
}

.checkin__tick {
  position: absolute;
  right: 3px;
  bottom: 1px;
  color: var(--gold);
  font-size: 10px;
  line-height: 1;
}

.checkin__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--text-tertiary);
  font-size: 12px;
}

.checkin__legend li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.checkin__legend i {
  width: 10px;
  height: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 3px;
}

.checkin__legend i.is-checked {
  border-color: var(--gold);
  background: color-mix(in srgb, var(--gold) 35%, transparent);
}

.checkin__legend i.is-today {
  border-color: var(--gold);
  box-shadow: inset 0 0 0 1px var(--gold);
}

.checkin__track {
  position: relative;
  height: 8px;
  border-radius: 99px;
  background: color-mix(in srgb, var(--surface-deck) 80%, var(--border-subtle));
  overflow: hidden;
}

.checkin__track-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, color-mix(in srgb, var(--role-action) 70%, var(--gold)), var(--gold));
}

.checkin__track-mark {
  position: absolute;
  top: 0;
  width: 2px;
  height: 100%;
  background: var(--text-tertiary);
  transform: translateX(-1px);
}

.checkin__track-mark.is-reached {
  background: var(--surface-deck);
}

.checkin__rewards {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.checkin__rewards li {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 2px 10px;
  align-items: baseline;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-deck) 65%, transparent);
  font-size: 13px;
}

.checkin__rewards li.is-reached,
.checkin__rewards li:first-child {
  border-color: color-mix(in srgb, var(--gold) 40%, var(--border-subtle));
}

.checkin__rewards b {
  color: var(--gold);
  font-variant-numeric: tabular-nums;
}

.checkin__rewards small {
  grid-column: 1 / -1;
  color: var(--text-tertiary);
  font-size: 12px;
}

.checkin__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.checkin__actions .button {
  min-width: 148px;
}
</style>
