<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  commanderAvatarUrl,
  commanderEmojiUrl,
  commanderPalette,
  commanderTierOf,
} from '../../stores/commanders'
import CommanderPortraitStage from './CommanderPortraitStage.vue'
import CommanderSkillOverlay from './CommanderSkillOverlay.vue'
import CommanderSkillIcon from './CommanderSkillIcon.vue'

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

const props = withDefaults(
  defineProps<{
    commanderState: Record<string, unknown> | null
    playerId: string
    busy: boolean
    compact?: boolean
  }>(),
  {
    compact: false,
  },
)

const emit = defineEmits<{
  (event: 'activate', skillId?: string): void
  (event: 'sendEmoji', text: string): void
}>()

const detailOpen = ref(false)
const emojiOpen = ref(false)

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
const unlockedEmojis = computed(() => {
  const raw = selfSeat.value?.cosmetics?.unlocked_emojis
  return Array.isArray(raw) ? raw.map(String) : []
})

function isActiveEffect(seat: SeatCmd | null): boolean {
  if (!seat) return false
  return Boolean(seat.firepower_control_active || seat.dauntless_active)
}

function statusLabel(seat: SeatCmd | null): string {
  if (!seat) return ''
  if (!enabled.value) return '每日挑战禁用'
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

function primaryBtnLabel(seat: SeatCmd | null): string {
  if (!seat) return '指挥官技能'
  const skillName = seat.skill?.name || '指挥官技能'
  if (!enabled.value) return '每日挑战禁用'
  if (seat.firepower_control_active) return `${skillName}已展开`
  if (seat.dauntless_active) return `${skillName}展开中`
  if (canUseSkill.value) return `发动 ${skillName}`
  if (seat.skill?.kind === 'cooldown' && Number(seat.cooldown_remaining || 0) > 0) {
    return `冷却 ${seat.cooldown_remaining} 回合`
  }
  if (seat.skill?.kind === 'limited' && Number(seat.skill_used_count || 0) >= 1) {
    return `${skillName}已耗尽`
  }
  return skillName
}

function seatStyleVars(seat: SeatCmd | null): Record<string, string> {
  const pal = commanderPalette(seat?.commander_id || 'chichao')
  return {
    '--cmd-pri': pal.primary,
    '--cmd-acc': pal.accent,
    '--cmd-sec': pal.secondary,
    '--cmd-glow': pal.glow,
  }
}

function handleSkillClick(): void {
  if (!enabled.value || !canUseSkill.value || props.busy) return
  emit('activate', selfSeat.value?.skill?.id)
}

function onEscapeKey(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  if (emojiOpen.value) {
    emojiOpen.value = false
    event.preventDefault()
    event.stopPropagation()
    return
  }
  if (detailOpen.value) {
    detailOpen.value = false
    event.preventDefault()
    event.stopPropagation()
  }
}

onMounted(() => window.addEventListener('keydown', onEscapeKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onEscapeKey))
</script>

<template>
  <section
    v-if="commanderState && (selfSeat || oppSeat)"
    class="cmd-hud"
    :class="props.compact ? 'cmd-hud--compact' : 'cmd-hud--wide'"
    data-testid="game-commander-hud"
    aria-label="指挥官角色信息"
  >
    <!-- 宽屏：左右上角留白独立立绘窗（严禁压迫中央棋盘/手牌与顶部席位条） -->
    <template v-if="!props.compact">
      <div v-if="selfSeat" class="cmd-corner-wrap cmd-corner-wrap--self">
        <article
          class="cmd-corner-card cmd-corner-card--self"
          :class="{ 'is-active': isActiveEffect(selfSeat), 'is-ready': enabled && canUseSkill }"
          :style="seatStyleVars(selfSeat)"
          data-testid="commander-hud-self"
        >
          <div class="cmd-corner__portrait">
            <CommanderPortraitStage
              class="cmd-corner__stage"
              :commander-id="selfSeat.commander_id"
              :commander-name="selfSeat.commander_name"
              :level="selfSeat.commander_level || 1"
              :equipped="selfSeat.cosmetics"
              mode="bust"
              :active="isActiveEffect(selfSeat)"
            >
              <CommanderSkillOverlay
                side="self"
                :player-id="selfSeat.player_id || props.playerId"
                :commander-level="selfSeat.commander_level || 1"
                :cosmetics="selfSeat.cosmetics"
              />
            </CommanderPortraitStage>
          </div>

          <div class="cmd-corner__body">
            <div class="cmd-corner__top">
              <span class="cmd-corner__eyebrow">
                {{ isActiveEffect(selfSeat) ? '本回合技能已发动' : '己方指挥官' }}
              </span>
              <span class="cmd-corner__lvl">Lv.{{ selfSeat.commander_level || 1 }}</span>
            </div>
            <strong class="cmd-corner__name">{{ selfSeat.commander_name }}</strong>
            <button
              type="button"
              class="cmd-corner__skill-btn"
              :class="{
                'is-ready': enabled && canUseSkill && !busy,
                'is-active-fx': isActiveEffect(selfSeat),
              }"
              :disabled="!enabled || !canUseSkill || busy"
              :title="unavailableReason || selfSeat.skill?.description || ''"
              data-testid="commander-use-skill-btn"
              @click="handleSkillClick"
            >
              <CommanderSkillIcon v-if="selfSeat.skill" :skill-id="selfSeat.skill.id" class="cmd-skill-button-icon" />
              {{ primaryBtnLabel(selfSeat) }}
            </button>
            <div class="cmd-corner__foot">
              <span class="cmd-corner__status-pill" :class="{ 'is-ready': enabled && canUseSkill }">
                {{ statusLabel(selfSeat) }}
              </span>
              <div class="cmd-corner__links">
                <button
                  type="button"
                  class="cmd-hud__mini-btn"
                  data-testid="commander-skill-info-btn"
                  @click="detailOpen = !detailOpen; emojiOpen = false"
                >{{ detailOpen ? '收起' : '技能详情' }}</button>
                <button
                  v-if="unlockedEmojis.length"
                  type="button"
                  class="cmd-hud__mini-btn"
                  data-testid="commander-emoji-toggle"
                  @click="emojiOpen = !emojiOpen; detailOpen = false"
                >表情</button>
              </div>
            </div>
          </div>
        </article>

        <div
          v-if="myLockedIncoming.length"
          class="cmd-hud__lock-pill cmd-hud__lock-pill--danger"
          data-testid="commander-delayed-lock-incoming"
        >
          ⚠ 己方 {{ myLockedIncoming.length }} 艘战舰已被青瞳「延迟锁定」<template v-if="myLockedIncoming[0].cells.length">（{{ myLockedIncoming[0].cells.map(c => `(${c.x},${c.y})`).join('、') }} · 第 {{ myLockedIncoming[0].reveal_after_round }} 回合末揭晓）</template>
        </div>
        <div
          v-else-if="myOutgoingLocks.length"
          class="cmd-hud__lock-pill cmd-hud__lock-pill--intel"
          data-testid="commander-delayed-lock-outgoing"
        >
          ◈ 延迟锁定追踪中 · 第 {{ myOutgoingLocks[0].reveal_after_round }} 回合末揭晓目标
        </div>
      </div>

      <div v-if="oppSeat" class="cmd-corner-wrap cmd-corner-wrap--opp">
        <article
          class="cmd-corner-card cmd-corner-card--opp"
          :class="{ 'is-active': isActiveEffect(oppSeat) }"
          :style="seatStyleVars(oppSeat)"
          data-testid="commander-hud-opponent"
        >
          <div class="cmd-corner__body cmd-corner__body--opp">
            <div class="cmd-corner__top">
              <span class="cmd-corner__eyebrow">
                {{ isActiveEffect(oppSeat) ? '技能生效中' : '对方指挥官' }}
              </span>
              <span class="cmd-corner__lvl">Lv.{{ oppSeat.commander_level || 1 }}</span>
            </div>
            <strong class="cmd-corner__name">{{ oppSeat.commander_name }}</strong>
            <span class="cmd-corner__opp-skill">{{ oppSeat.skill?.name || '未知技能' }}</span>
            <span class="cmd-corner__status-pill" :class="{ 'is-ready': statusLabel(oppSeat) === '技能就绪' }">
              {{ statusLabel(oppSeat) }}
            </span>
          </div>
          <div class="cmd-corner__portrait">
            <CommanderPortraitStage
              class="cmd-corner__stage"
              :commander-id="oppSeat.commander_id"
              :commander-name="oppSeat.commander_name"
              :level="oppSeat.commander_level || 1"
              :equipped="oppSeat.cosmetics"
              mode="bust"
              :active="isActiveEffect(oppSeat)"
            >
              <CommanderSkillOverlay
                side="opponent"
                :player-id="oppSeat.player_id"
                :commander-level="oppSeat.commander_level || 1"
                :cosmetics="oppSeat.cosmetics"
              />
            </CommanderPortraitStage>
          </div>
        </article>
      </div>
    </template>

    <!-- 窄屏 / 无角落余量降级：收拢为紧贴席位条的独立按钮与小徽章，优先保住棋盘与手牌 -->
    <template v-else>
      <div class="cmd-compact-strip" :style="seatStyleVars(selfSeat)">
        <div v-if="selfSeat" class="cmd-compact-side cmd-compact-side--self" data-testid="commander-hud-self">
          <div class="cmd-compact__avatar-wrap">
            <img
              class="cmd-compact__avatar"
              :class="'cmd-hud__tier-' + commanderTierOf(selfSeat.commander_level || 1)"
              :src="commanderAvatarUrl(selfSeat.commander_id)"
              :alt="selfSeat.commander_name"
            />
            <CommanderSkillOverlay
              side="self"
              :player-id="selfSeat.player_id || props.playerId"
              :commander-level="selfSeat.commander_level || 1"
              :cosmetics="selfSeat.cosmetics"
            />
          </div>
          <span class="cmd-compact__meta">
            <b>{{ selfSeat.commander_name }}</b>
            <small>Lv.{{ selfSeat.commander_level || 1 }}</small>
          </span>
          <button
            type="button"
            class="cmd-compact__skill-btn"
            :class="{ 'is-ready': enabled && canUseSkill && !busy }"
            :disabled="!enabled || !canUseSkill || busy"
            :title="unavailableReason || selfSeat.skill?.description || ''"
            data-testid="commander-use-skill-btn"
            @click="handleSkillClick"
          >
            <CommanderSkillIcon v-if="selfSeat.skill" :skill-id="selfSeat.skill.id" class="cmd-skill-button-icon" />
            {{ primaryBtnLabel(selfSeat) }}
          </button>
          <button
            type="button"
            class="cmd-hud__mini-btn"
            data-testid="commander-skill-info-btn"
            @click="detailOpen = !detailOpen; emojiOpen = false"
          >详情</button>
          <button
            v-if="unlockedEmojis.length"
            type="button"
            class="cmd-hud__mini-btn"
            data-testid="commander-emoji-toggle"
            @click="emojiOpen = !emojiOpen; detailOpen = false"
          >表情</button>
        </div>

        <div v-if="oppSeat" class="cmd-compact-side cmd-compact-side--opp" data-testid="commander-hud-opponent">
          <span class="cmd-compact__opp-status">{{ oppSeat.commander_name }} · {{ statusLabel(oppSeat) }}</span>
          <span class="cmd-compact__avatar-wrap">
            <img
              class="cmd-compact__avatar"
              :class="'cmd-hud__tier-' + commanderTierOf(oppSeat.commander_level || 1)"
              :src="commanderAvatarUrl(oppSeat.commander_id)"
              :alt="oppSeat.commander_name"
            />
            <CommanderSkillOverlay
              side="opponent"
              :player-id="oppSeat.player_id"
              :commander-level="oppSeat.commander_level || 1"
              :cosmetics="oppSeat.cosmetics"
            />
          </span>
        </div>
      </div>

      <div
        v-if="myLockedIncoming.length"
        class="cmd-hud__lock-pill cmd-hud__lock-pill--danger"
        data-testid="commander-delayed-lock-incoming"
      >
        ⚠ 被青瞳「延迟锁定」<template v-if="myLockedIncoming[0].cells.length">（第 {{ myLockedIncoming[0].reveal_after_round }} 回合末揭晓）</template>
      </div>
      <div
        v-else-if="myOutgoingLocks.length"
        class="cmd-hud__lock-pill cmd-hud__lock-pill--intel"
        data-testid="commander-delayed-lock-outgoing"
      >
        ◈ 延迟锁定追踪中 · 第 {{ myOutgoingLocks[0].reveal_after_round }} 回合末揭晓
      </div>
    </template>

    <!-- 按需展开技能详情浮层 -->
    <div v-if="detailOpen && selfSeat?.skill" class="cmd-hud__popover" data-testid="commander-hud-skill-popover">
      <div class="cmd-hud__popover-head">
        <b>{{ selfSeat.commander_name }} · 【{{ selfSeat.skill.name }}】</b>
        <button type="button" class="cmd-hud__close-x" aria-label="关闭技能详情" @click="detailOpen = false">×</button>
      </div>
      <small>{{ selfSeat.skill.timing_label }} · {{ selfSeat.skill.limit_label }}</small>
      <p>{{ selfSeat.skill.description }}</p>
    </div>

    <!-- 按需展开角色表情包浮层 -->
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

  </section>
</template>

<style scoped>
.cmd-skill-button-icon { margin-inline-end: .35em; color: var(--cmd-acc, currentColor); }
/* 宽屏角落容器：依托父舞台两侧上角留白，绝对不侵入中央棋盘与手牌区域 */
.cmd-hud--wide {
  position: absolute;
  top: 10px;
  left: 18px;
  right: 18px;
  z-index: 32;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  pointer-events: none;
}
.cmd-corner-wrap {
  display: flex;
  flex-direction: column;
  gap: 5px;
  pointer-events: auto;
  width: clamp(214px, calc((100vw - (min(1560px, 100vw - 40px) - var(--dock-left, 240px) - var(--dock-right, 258px))) / 2 - 28px), 390px);
  max-width: 390px;
}
.cmd-corner-wrap--opp {
  align-items: flex-end;
}
.cmd-corner-card {
  position: relative;
  display: flex;
  align-items: stretch;
  gap: 10px;
  width: 100%;
  height: clamp(134px, calc(clamp(168px, 18dvh, 190px) - 24px), 156px);
  padding: 8px;
  border-radius: 14px;
  border: 1px solid color-mix(in srgb, var(--cmd-pri) 42%, rgb(125 211 252 / 24%));
  background: linear-gradient(
    130deg,
    rgb(10 20 36 / 94%),
    color-mix(in srgb, var(--cmd-pri) 14%, rgb(11 21 38 / 96%))
  );
  box-shadow: 0 10px 28px rgb(0 0 0 / 38%);
  overflow: hidden;
}
.cmd-corner-card.is-active {
  border-color: var(--cmd-acc);
  box-shadow: 0 0 18px color-mix(in srgb, var(--cmd-pri) 36%, transparent), 0 10px 28px rgb(0 0 0 / 42%);
}
.cmd-corner-card--opp {
  justify-content: space-between;
}
.cmd-corner__portrait {
  position: relative;
  flex: 0 0 112px;
  height: 100%;
  border-radius: 10px;
  overflow: hidden;
}
.cmd-corner__stage {
  width: 100%;
  height: 100%;
  border-radius: 10px;
}
.cmd-corner__body {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 5px;
  justify-content: center;
}
.cmd-corner__body--opp {
  align-items: flex-start;
}
.cmd-corner__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  width: 100%;
}
.cmd-corner__eyebrow {
  font-size: 11px;
  color: #a9c6e0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-corner__lvl {
  padding: 1px 6px;
  border-radius: 5px;
  border: 1px solid color-mix(in srgb, var(--cmd-acc) 55%, transparent);
  background: rgb(11 22 40 / 85%);
  color: var(--cmd-acc);
  font-size: 10.5px;
  font-weight: 700;
  white-space: nowrap;
}
.cmd-corner__name {
  font-size: 20px;
  line-height: 1.1;
  color: #ffffff;
  font-weight: 800;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-corner__opp-skill {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--cmd-acc);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-corner__skill-btn {
  width: 100%;
  min-height: 30px;
  padding: 4px 8px;
  border-radius: 8px;
  border: 1px solid rgb(148 163 184 / 32%);
  background: rgb(15 29 52 / 86%);
  color: #dbeafe;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, background 0.16s ease;
}
.cmd-corner__skill-btn.is-ready {
  border-color: var(--cmd-acc);
  background: linear-gradient(95deg, color-mix(in srgb, var(--cmd-pri) 26%, #13223a), rgb(16 30 52 / 96%));
  color: #ffffff;
  box-shadow: 0 0 14px color-mix(in srgb, var(--cmd-pri) 28%, transparent);
}
.cmd-corner__skill-btn.is-ready:hover {
  border-color: #fde68a;
  box-shadow: 0 0 18px color-mix(in srgb, var(--cmd-acc) 40%, transparent);
}
.cmd-corner__skill-btn.is-active-fx {
  border-color: var(--cmd-acc);
  background: color-mix(in srgb, var(--cmd-pri) 20%, #0f1b2e);
  color: var(--cmd-acc);
}
.cmd-corner__skill-btn:disabled {
  opacity: 0.72;
  cursor: not-allowed;
}
.cmd-corner__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex-wrap: wrap;
}
.cmd-corner__status-pill {
  padding: 2px 6px;
  border-radius: 5px;
  border: 1px solid rgb(148 163 184 / 24%);
  background: rgb(9 19 34 / 78%);
  color: #9bb8d3;
  font-size: 10.5px;
  white-space: nowrap;
}
.cmd-corner__status-pill.is-ready {
  color: #86efac;
  border-color: rgb(34 197 94 / 45%);
  background: rgb(20 83 45 / 32%);
}
.cmd-corner__links {
  display: flex;
  align-items: center;
  gap: 6px;
}

@media (max-width: 1680px) {
  .cmd-corner-card {
    padding: 6px 7px;
    gap: 7px;
  }
  .cmd-corner__portrait {
    flex-basis: 78px;
  }
  .cmd-corner__name {
    font-size: 16px;
  }
  .cmd-corner__skill-btn {
    min-height: 27px;
    font-size: 11px;
  }
  .cmd-corner__eyebrow {
    font-size: 10px;
  }
}

/* 窄屏 / 无角落余量：收成席位外侧单条紧凑条 */
.cmd-hud--compact {
  position: relative;
  grid-area: cmd;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
  z-index: 30;
}
.cmd-compact-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 3px 6px;
  min-height: 36px;
  border-radius: 9px;
  border: 1px solid rgb(125 211 252 / 24%);
  background: rgb(10 22 39 / 90%);
  overflow: hidden;
}
.cmd-compact-side {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}
.cmd-compact-side--self {
  flex: 1 1 auto;
}
.cmd-compact-side--opp {
  flex: 0 1 auto;
}
.cmd-compact__avatar-wrap {
  position: relative;
  display: inline-flex;
  padding: 0;
  border: 0;
  background: transparent;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
}
.cmd-compact__avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 1.5px solid #60a5fa;
  object-fit: cover;
  display: block;
}
.cmd-hud__tier-2 { border-color: #38bdf8; box-shadow: 0 0 8px rgb(56 189 248 / 45%); }
.cmd-hud__tier-3 { border-color: #f59e0b; box-shadow: 0 0 10px rgb(245 158 11 / 52%); }
.cmd-hud__tier-4 { border-color: #fde047; box-shadow: 0 0 12px rgb(253 224 71 / 72%); }
.cmd-compact__meta {
  display: flex;
  align-items: baseline;
  gap: 3px;
  font-size: 11px;
  color: #f0f9ff;
  white-space: nowrap;
}
.cmd-compact__meta small {
  font-size: 9.5px;
  color: #93c5fd;
}
.cmd-compact__skill-btn {
  padding: 3px 8px;
  min-height: 26px;
  border-radius: 6px;
  border: 1px solid rgb(148 163 184 / 30%);
  background: rgb(16 32 56 / 86%);
  color: #dbeafe;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
  cursor: pointer;
}
.cmd-compact__skill-btn.is-ready {
  border-color: var(--cmd-acc, #facc15);
  color: #fff;
  background: color-mix(in srgb, var(--cmd-pri, #eab354) 30%, #10243d);
}
.cmd-compact__skill-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}
.cmd-compact__opp-status {
  font-size: 10px;
  color: #9bb8d3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 116px;
}

.cmd-hud__mini-btn {
  padding: 2px 5px;
  border-radius: 5px;
  border: 1px solid rgb(148 163 184 / 26%);
  background: rgb(15 28 48 / 85%);
  color: #bae6fd;
  font-size: 10.5px;
  cursor: pointer;
  white-space: nowrap;
}
.cmd-hud__mini-btn:hover {
  border-color: #7dd3fc;
  color: #fff;
}

.cmd-hud__lock-pill {
  padding: 3px 9px;
  border-radius: 8px;
  font-size: 10.5px;
  line-height: 1.35;
}
.cmd-hud__lock-pill--danger {
  background: rgb(127 29 29 / 86%);
  border: 1px solid rgb(248 113 113 / 65%);
  color: #fecaca;
}
.cmd-hud__lock-pill--intel {
  background: rgb(12 74 110 / 82%);
  border: 1px solid rgb(56 189 248 / 60%);
  color: #bae6fd;
}

.cmd-hud__popover,
.cmd-hud__emojis {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 90;
  width: min(360px, calc(100vw - 24px));
  padding: 11px 13px;
  border-radius: 12px;
  border: 1px solid rgb(125 211 252 / 42%);
  background: rgb(8 19 36 / 96%);
  box-shadow: 0 16px 36px rgb(0 0 0 / 56%);
  pointer-events: auto;
}
.cmd-hud__popover-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.cmd-hud__popover b {
  font-size: 13px;
  color: #fde68a;
}
.cmd-hud__close-x {
  border: 0;
  background: transparent;
  color: #94a3b8;
  font-size: 17px;
  cursor: pointer;
}
.cmd-hud__popover small {
  display: block;
  margin-top: 2px;
  font-size: 10.5px;
  color: #7dd3fc;
}
.cmd-hud__popover p {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: #e2e8f0;
}
.cmd-hud__emojis {
  width: auto;
  max-width: min(340px, calc(100vw - 24px));
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.cmd-hud__emoji-btn {
  padding: 4px;
  border-radius: 10px;
  border: 1px solid rgb(148 163 184 / 28%);
  background: rgb(15 29 52 / 90%);
  cursor: pointer;
}
.cmd-hud__emoji-btn img {
  width: 52px;
  height: 52px;
  display: block;
}

</style>
