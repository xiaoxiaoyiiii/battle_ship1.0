<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  commanderAvatarUrl,
  commanderEmojiUrl,
  commanderTierOf,
  useCommandersStore,
} from '../../stores/commanders'

interface SeatCmd {
  player_id: string
  commander_id: string
  commander_name: string
  commander_level: number
  cosmetics?: Record<string, unknown>
  skill?: {
    id: string
    name: string
    kind: string
    enters_chain: boolean
    speed: number | null
    limit_label: string
    timing_label: string
    description: string
  } | null
  skill_used_count?: number
  cooldown_remaining?: number
  firepower_control_active?: boolean
  dauntless_active?: boolean
  shots_used_this_round?: number
}

interface DelayedLockRow {
  id: string
  caster_id: string
  target_player_id: string
  used_round: number
  reveal_after_round: number
  ship_id?: string
  cells: Array<{ x: number; y: number }>
}

const props = defineProps<{
  commanderState: Record<string, unknown> | null
  playerId: string
  ships: Array<{ positions: Array<{ x: number; y: number }>; alive: boolean }>
  busy: boolean
}>()

const emit = defineEmits<{
  (event: 'activate', selectedCells?: Array<{ x: number; y: number }>): void
  (event: 'interact'): void
  (event: 'sendEmoji', text: string): void
}>()

const store = useCommandersStore()
const detailOpen = ref(false)
const emojiOpen = ref(false)
const pickModalOpen = ref(false)
const selectedShipIdx = ref<number | null>(null)

const enabled = computed(() => Boolean(props.commanderState?.enabled))
const selfSeat = computed(() => (props.commanderState?.self as SeatCmd | null) ?? null)
const oppSeat = computed(() => (props.commanderState?.opponent as SeatCmd | null) ?? null)
const canUseSkill = computed(() => Boolean(props.commanderState?.can_use_skill))
const unavailableReason = computed(() => String(props.commanderState?.unavailable_reason ?? ''))

const delayedLocks = computed<DelayedLockRow[]>(() =>
  Array.isArray(props.commanderState?.delayed_locks)
    ? (props.commanderState?.delayed_locks as DelayedLockRow[])
    : [],
)
const myLockedIncoming = computed(() =>
  delayedLocks.value.filter((row) => row.target_player_id === props.playerId),
)
const myOutgoingLocks = computed(() =>
  delayedLocks.value.filter((row) => row.caster_id === props.playerId),
)
const livingShips = computed(() =>
  props.ships
    .map((ship, idx) => ({ ...ship, idx }))
    .filter((ship) => ship.alive && ship.positions.length > 0),
)

const unlockedEmojis = computed(() => {
  const raw = selfSeat.value?.cosmetics?.unlocked_emojis
  return Array.isArray(raw) ? raw.map(String) : []
})

function statusLabel(seat: SeatCmd | null): string {
  if (!seat) return ''
  if (seat.firepower_control_active) {
    const left = Math.max(0, 6 - Number(seat.shots_used_this_round || 0))
    return `火力统制中 · 剩 ${left}/6`
  }
  if (seat.dauntless_active) return '无畏舰队展开中'
  if (seat.skill?.kind === 'cooldown' && Number(seat.cooldown_remaining || 0) > 0) {
    return `冷却 ${seat.cooldown_remaining} 回合`
  }
  if (seat.skill?.kind === 'limited' && Number(seat.skill_used_count || 0) >= 1) {
    return '限定技已使用'
  }
  return '技能就绪'
}

function handleSkillClick(): void {
  if (!enabled.value || !canUseSkill.value || props.busy) return
  if (selfSeat.value?.skill?.id === 'sacrifice_gambit') {
    selectedShipIdx.value = null
    pickModalOpen.value = true
    return
  }
  emit('activate')
}

function confirmGuihangSacrifice(): void {
  if (selectedShipIdx.value === null) return
  const target = livingShips.value.find((s) => s.idx === selectedShipIdx.value)
  if (!target || !target.positions.length) return
  pickModalOpen.value = false
  emit('activate', [{ x: target.positions[0].x, y: target.positions[0].y }])
}

function interact(): void {
  if (selfSeat.value) {
    store.playVoice(selfSeat.value.commander_id, 'voice_interact')
  }
  emit('interact')
}
</script>

<template>
  <section
    v-if="commanderState && (selfSeat || oppSeat)"
    class="cmd-hud"
    data-testid="game-commander-hud"
    aria-label="指挥官角色信息"
  >
    <div v-if="oppSeat" class="cmd-hud__side cmd-hud__side--opp" data-testid="commander-hud-opponent">
      <img
        class="cmd-hud__avatar"
        :class="'cmd-hud__tier-' + commanderTierOf(oppSeat.commander_level || 1)"
        :src="commanderAvatarUrl(oppSeat.commander_id)"
        :alt="oppSeat.commander_name"
      />
      <div class="cmd-hud__meta">
        <div class="cmd-hud__name">
          <b>{{ oppSeat.commander_name }}</b>
          <small>Lv.{{ oppSeat.commander_level || 1 }}</small>
        </div>
        <span class="cmd-hud__status">{{ enabled ? statusLabel(oppSeat) : '技能已禁用（每日挑战）' }}</span>
      </div>
    </div>

    <div v-if="selfSeat" class="cmd-hud__center">
      <button
        type="button"
        class="cmd-hud__skill-btn"
        :class="{ 'is-ready': enabled && canUseSkill && !busy }"
        :disabled="!enabled || !canUseSkill || busy"
        :title="unavailableReason || selfSeat.skill?.description || ''"
        data-testid="commander-use-skill-btn"
        @click="handleSkillClick"
      >
        <b>【{{ selfSeat.skill?.name || '指挥官技能' }}】</b>
        <small v-if="!enabled">每日挑战禁用技能</small>
        <small v-else-if="canUseSkill">点击发动 · {{ selfSeat.skill?.enters_chain ? '速阶3入链' : '主动不入链' }}</small>
        <small v-else>{{ unavailableReason || statusLabel(selfSeat) }}</small>
      </button>
      <div class="cmd-hud__subactions">
        <button
          type="button"
          class="cmd-hud__mini-btn"
          data-testid="commander-skill-info-btn"
          @click="detailOpen = !detailOpen"
        >{{ detailOpen ? '收起说明' : '技能详情' }}</button>
        <button
          v-if="unlockedEmojis.length"
          type="button"
          class="cmd-hud__mini-btn"
          data-testid="commander-emoji-toggle"
          @click="emojiOpen = !emojiOpen"
        >角色表情</button>
      </div>
      <div v-if="myLockedIncoming.length" class="cmd-hud__lock-pill cmd-hud__lock-pill--danger" data-testid="commander-delayed-lock-incoming">
        ⚠ 己方 {{ myLockedIncoming.length }} 艘战舰已被青瞳「延迟锁定」<template v-if="myLockedIncoming[0].cells.length">（{{ myLockedIncoming[0].cells.map(c => `(${c.x},${c.y})`).join('、') }} · 第 {{ myLockedIncoming[0].reveal_after_round }} 回合末揭晓）</template>
      </div>
      <div v-else-if="myOutgoingLocks.length" class="cmd-hud__lock-pill cmd-hud__lock-pill--intel" data-testid="commander-delayed-lock-outgoing">
        ◈ 延迟锁定追踪中：将于第 {{ myOutgoingLocks[0].reveal_after_round }} 回合末揭晓目标坐标
      </div>
    </div>

    <div v-if="selfSeat" class="cmd-hud__side cmd-hud__side--self" data-testid="commander-hud-self">
      <div class="cmd-hud__meta cmd-hud__meta--right">
        <div class="cmd-hud__name">
          <small>Lv.{{ selfSeat.commander_level || 1 }}</small>
          <b>{{ selfSeat.commander_name }}</b>
        </div>
        <span class="cmd-hud__status">{{ enabled ? statusLabel(selfSeat) : '技能已禁用' }}</span>
      </div>
      <button
        type="button"
        class="cmd-hud__avatar-btn"
        title="点击触发指挥官语音互动"
        data-testid="commander-interact-btn"
        @click="interact"
      >
        <img
          class="cmd-hud__avatar"
          :class="'cmd-hud__tier-' + commanderTierOf(selfSeat.commander_level || 1)"
          :src="commanderAvatarUrl(selfSeat.commander_id)"
          :alt="selfSeat.commander_name"
        />
      </button>
    </div>

    <div v-if="detailOpen && selfSeat?.skill" class="cmd-hud__popover" data-testid="commander-hud-skill-popover">
      <b>{{ selfSeat.commander_name }} · 【{{ selfSeat.skill.name }}】</b>
      <small>{{ selfSeat.skill.timing_label }} · {{ selfSeat.skill.limit_label }}</small>
      <p>{{ selfSeat.skill.description }}</p>
    </div>

    <div v-if="emojiOpen && selfSeat" class="cmd-hud__emojis" data-testid="commander-hud-emojis">
      <button
        v-for="ekey in unlockedEmojis"
        :key="ekey"
        type="button"
        class="cmd-hud__emoji-btn"
        @click="emit('sendEmoji', `[${selfSeat.commander_name}·${ekey}]`); emojiOpen = false"
      >
        <img :src="commanderEmojiUrl(selfSeat.commander_id, ekey)" :alt="ekey" />
      </button>
    </div>

    <div v-if="pickModalOpen" class="cmd-hud__modal-backdrop" @click.self="pickModalOpen = false">
      <section class="cmd-hud__modal" data-testid="commander-sacrifice-picker" role="dialog" aria-label="弃舰筹谋选择牺牲战舰">
        <h3>「弃舰筹谋」· 选择 1 艘己方存活战舰牺牲</h3>
        <p>发动时立即明牌牺牲所选战舰并保留残骸（被无效不退还），结算成功后抽取 2 张魔法卡。</p>
        <div class="cmd-hud__ship-list">
          <button
            v-for="ship in livingShips"
            :key="ship.idx"
            type="button"
            class="cmd-hud__ship-opt"
            :class="{ 'is-picked': selectedShipIdx === ship.idx }"
            :data-testid="'commander-sacrifice-ship-' + ship.idx"
            @click="selectedShipIdx = ship.idx"
          >
            <b>战舰 #{{ ship.idx + 1 }}（{{ ship.positions.length }} 格）</b>
            <small>{{ ship.positions.map((p) => `(${p.x},${p.y})`).join(' · ') }}</small>
          </button>
        </div>
        <div class="cmd-hud__modal-actions">
          <button
            type="button"
            class="button button--primary"
            :disabled="selectedShipIdx === null"
            data-testid="commander-sacrifice-confirm"
            @click="confirmGuihangSacrifice"
          >确认发动并牺牲</button>
          <button type="button" class="button button--ghost" @click="pickModalOpen = false">取消</button>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.cmd-hud {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  margin-bottom: 8px;
  border-radius: 14px;
  border: 1px solid rgb(125 211 252 / 26%);
  background: linear-gradient(120deg, rgb(8 20 36 / 90%), rgb(13 24 44 / 90%));
}
@media (max-width: 720px) {
  .cmd-hud {
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    padding: 7px 9px;
  }
  .cmd-hud__center {
    grid-column: 1 / -1;
    order: 3;
  }
}
.cmd-hud__side {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cmd-hud__side--self {
  justify-content: flex-end;
}
.cmd-hud__avatar-btn {
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  border-radius: 50%;
}
.cmd-hud__avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 2px solid #60a5fa;
  object-fit: cover;
}
.cmd-hud__tier-2 {
  border-color: #38bdf8;
  box-shadow: 0 0 10px rgb(56 189 248 / 45%);
}
.cmd-hud__tier-3 {
  border-color: #f59e0b;
  box-shadow: 0 0 14px rgb(245 158 11 / 52%);
}
.cmd-hud__tier-4 {
  border-color: #fde047;
  box-shadow: 0 0 16px rgb(253 224 71 / 72%);
}
.cmd-hud__meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.cmd-hud__meta--right {
  text-align: right;
}
.cmd-hud__name {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #f0f9ff;
}
.cmd-hud__name small {
  color: #93c5fd;
  font-size: 10px;
}
.cmd-hud__status {
  font-size: 10px;
  color: #a5c4dd;
}
.cmd-hud__center {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.cmd-hud__skill-btn {
  width: 100%;
  max-width: 360px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 5px 12px;
  border-radius: 10px;
  border: 1px solid rgb(148 163 184 / 34%);
  background: rgb(15 28 48 / 82%);
  color: #cbd5e1;
  cursor: not-allowed;
}
.cmd-hud__skill-btn.is-ready {
  border-color: #fbbf24;
  background: linear-gradient(135deg, rgb(234 179 84 / 24%), rgb(19 42 74 / 92%));
  color: #fffbeb;
  cursor: pointer;
  box-shadow: 0 0 14px rgb(251 191 36 / 26%);
}
.cmd-hud__skill-btn b {
  font-size: 12px;
}
.cmd-hud__skill-btn small {
  font-size: 10px;
  opacity: 0.9;
}
.cmd-hud__subactions {
  display: flex;
  gap: 10px;
}
.cmd-hud__mini-btn {
  border: 0;
  background: transparent;
  color: #7dd3fc;
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}
.cmd-hud__lock-pill {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  text-align: center;
}
.cmd-hud__lock-pill--danger {
  background: rgb(239 68 68 / 20%);
  border: 1px solid rgb(248 113 113 / 50%);
  color: #fecaca;
}
.cmd-hud__lock-pill--intel {
  background: rgb(56 189 248 / 18%);
  border: 1px solid rgb(125 211 252 / 45%);
  color: #bae6fd;
}
.cmd-hud__popover {
  grid-column: 1 / -1;
  padding: 8px 12px;
  border-radius: 10px;
  background: rgb(7 15 28 / 96%);
  border: 1px solid rgb(125 211 252 / 35%);
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.cmd-hud__popover b {
  font-size: 13px;
  color: #fde68a;
}
.cmd-hud__popover small {
  font-size: 11px;
  color: #7dd3fc;
}
.cmd-hud__popover p {
  margin: 0;
  font-size: 12px;
  color: #dce9f5;
  line-height: 1.45;
}
.cmd-hud__emojis {
  grid-column: 1 / -1;
  display: flex;
  gap: 8px;
  justify-content: center;
  padding-top: 4px;
}
.cmd-hud__emoji-btn {
  padding: 3px;
  border-radius: 10px;
  border: 1px solid rgb(148 163 184 / 30%);
  background: rgb(11 22 40 / 90%);
  cursor: pointer;
}
.cmd-hud__emoji-btn img {
  width: 44px;
  height: 44px;
  display: block;
}
.cmd-hud__modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 360;
  background: rgb(3 8 18 / 72%);
  display: grid;
  place-items: center;
  padding: 16px;
}
.cmd-hud__modal {
  width: min(440px, 100%);
  padding: 18px;
  border-radius: 16px;
  border: 1px solid rgb(234 179 84 / 52%);
  background: linear-gradient(145deg, #0b192e, #121829);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cmd-hud__modal h3 {
  margin: 0;
  font-size: 16px;
  color: #fef08a;
}
.cmd-hud__modal p {
  margin: 0;
  font-size: 12px;
  color: #cbd5e1;
  line-height: 1.5;
}
.cmd-hud__ship-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cmd-hud__ship-opt {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 12px;
  border-radius: 10px;
  border: 1px solid rgb(148 163 184 / 30%);
  background: rgb(14 28 48 / 86%);
  color: #e2e8f0;
  text-align: left;
  cursor: pointer;
}
.cmd-hud__ship-opt.is-picked {
  border-color: #fbbf24;
  background: rgb(234 179 84 / 18%);
}
.cmd-hud__ship-opt small {
  color: #93c5fd;
  font-size: 11px;
}
.cmd-hud__modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
