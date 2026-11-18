<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  commanderAvatarUrl,
  commanderTierOf,
  portraitForLevelAndEquipped,
  useCommandersStore,
  type CommanderSpecView,
} from '../../stores/commanders'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'

const props = withDefaults(
  defineProps<{
    compact?: boolean
    title?: string
  }>(),
  {
    compact: false,
    title: '出战指挥官',
  },
)

const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()
const store = useCommandersStore()
const detailOpen = ref(false)
const actionNote = ref('')

onMounted(() => {
  void store.load()
})

const current = computed<CommanderSpecView | null>(() => store.selectedCommander)
const list = computed(() => store.commanders)

async function pickCommander(cmd: CommanderSpecView): Promise<void> {
  actionNote.value = ''
  if (store.freeInitialAvailable && !cmd.owned) {
    const res = await store.unlock(cmd.id)
    actionNote.value = res.message || (res.ok ? `已免费解锁并出战「${cmd.name}」` : '')
    if (res.ok) store.playVoice(cmd.id, 'voice_greet')
    return
  }
  if (auth.isGuest || cmd.owned) {
    const res = await store.select(cmd.id)
    if (res.ok) {
      actionNote.value = `已切换为「${cmd.name}」`
      store.playVoice(cmd.id, 'voice_greet')
    } else if (res.message) {
      actionNote.value = res.message
    }
    return
  }
  // 已登录但未拥有：提示或直接前往指挥官殿堂解锁
  actionNote.value = `「${cmd.name}」尚未解锁（需 ${cmd.unlock_cost} 潮汐徽记），请前往指挥官页解锁`
}

async function claimFree(cmd: CommanderSpecView): Promise<void> {
  const res = await store.unlock(cmd.id)
  if (res.ok) {
    ui.notify({ code: 'cmd-free-unlock', message: res.message || `已免费解锁「${cmd.name}」`, tone: 'success' })
    store.playVoice(cmd.id, 'voice_greet')
  } else if (res.message) {
    ui.notifyError('cmd-free-unlock-err', res.message)
  }
}

function goCommanders(): void {
  void router.push({ name: 'commanders' })
}
</script>

<template>
  <section
    class="cmd-strip"
    :class="{ 'cmd-strip--compact': props.compact }"
    data-testid="commander-selector-strip"
    aria-label="指挥官选择"
  >
    <header class="cmd-strip__head">
      <div class="cmd-strip__title-wrap">
        <span class="cmd-strip__kicker">{{ props.title }}</span>
        <span v-if="store.freeInitialAvailable" class="cmd-strip__free-pill" data-testid="commander-free-starter-badge">
          首领免费任选 1 位
        </span>
      </div>
      <button
        type="button"
        class="cmd-strip__hall-btn"
        data-testid="commander-open-hall"
        @click="goCommanders"
      >
        指挥官殿堂<small v-if="store.totalClaimableCount > 0" class="cmd-strip__red-dot">{{ store.totalClaimableCount }}</small> ›
      </button>
    </header>

    <div v-if="list.length" class="cmd-strip__roster" role="radiogroup" aria-label="切换指挥官">
      <button
        v-for="cmd in list"
        :key="cmd.id"
        type="button"
        class="cmd-chip"
        :class="{
          'is-selected': current?.id === cmd.id,
          'is-locked': !auth.isGuest && !cmd.owned && !store.freeInitialAvailable,
          ['cmd-tier-' + commanderTierOf(cmd.progress.level)]: true,
        }"
        :style="{ '--cmd-pri': cmd.palette.primary, '--cmd-acc': cmd.palette.accent }"
        :data-testid="'commander-pick-' + cmd.id"
        :aria-checked="current?.id === cmd.id"
        role="radio"
        @click="pickCommander(cmd)"
      >
        <img class="cmd-chip__avatar" :src="commanderAvatarUrl(cmd.id)" :alt="cmd.name" />
        <span class="cmd-chip__meta">
          <b>{{ cmd.name }}</b>
          <small v-if="auth.isGuest">体验 · {{ cmd.skill.name }}</small>
          <small v-else-if="cmd.owned">Lv.{{ cmd.progress.level }} · {{ cmd.skill.name }}</small>
          <small v-else-if="store.freeInitialAvailable">免费首领</small>
          <small v-else>{{ cmd.unlock_cost }} 潮汐徽记</small>
        </span>
      </button>
    </div>

    <div v-if="current" class="cmd-strip__active" :style="{ '--cmd-pri': current.palette.primary, '--cmd-acc': current.palette.accent }">
      <img
        class="cmd-strip__portrait"
        :src="portraitForLevelAndEquipped(current.id, current.progress.level, current.equipped)"
        :alt="current.name + ' 立绘'"
      />
      <div class="cmd-strip__info">
        <div class="cmd-strip__name-row">
          <strong data-testid="commander-active-name">{{ current.name }}</strong>
          <span class="cmd-strip__tag">{{ current.title_tagline }}</span>
          <span v-if="current.owned" class="cmd-strip__lvl">Lv.{{ current.progress.level }}</span>
          <button
            v-if="store.freeInitialAvailable && !current.owned"
            type="button"
            class="cmd-strip__claim-btn"
            data-testid="commander-free-unlock-now"
            @click="claimFree(current)"
          >免费领取并出战</button>
        </div>
        <div class="cmd-strip__skill">
          <span class="cmd-strip__skill-name">【{{ current.skill.name }}】</span>
          <span class="cmd-strip__skill-badge">{{ current.skill.limit_label }}</span>
          <button
            type="button"
            class="cmd-strip__toggle-desc"
            data-testid="commander-skill-preview-toggle"
            @click="detailOpen = !detailOpen"
          >{{ detailOpen ? '收起' : '技能详情' }}</button>
        </div>
        <p class="cmd-strip__desc" :class="{ 'is-expanded': detailOpen || !props.compact }" data-testid="commander-active-skill-desc">
          {{ current.skill.timing_label }}：{{ current.skill.description }}
        </p>
        <p v-if="actionNote" class="cmd-strip__note" role="status">{{ actionNote }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.cmd-strip {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgb(120 200 235 / 26%);
  background: linear-gradient(145deg, rgb(10 26 44 / 86%), rgb(6 15 28 / 92%));
  box-shadow: 0 10px 26px rgb(0 0 0 / 28%);
}
.cmd-strip--compact {
  padding: 10px 12px;
  gap: 8px;
}
.cmd-strip__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.cmd-strip__title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cmd-strip__kicker {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #8fdcff;
}
.cmd-strip__free-pill {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  color: #161005;
  background: linear-gradient(90deg, #facc15, #f59e0b);
}
.cmd-strip__hall-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgb(120 200 235 / 35%);
  background: rgb(14 38 62 / 75%);
  color: #cdeeff;
  font-size: 12px;
  cursor: pointer;
}
.cmd-strip__hall-btn:hover {
  border-color: #7dd3fc;
  color: #ffffff;
}
.cmd-strip__red-dot {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: #ef4444;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
}
.cmd-strip__roster {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
@media (max-width: 640px) {
  .cmd-strip__roster {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.cmd-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 12px;
  border: 1px solid rgb(148 163 184 / 24%);
  background: rgb(11 22 38 / 76%);
  color: #dce9f5;
  text-align: left;
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}
.cmd-chip:hover {
  transform: translateY(-1px);
  border-color: var(--cmd-pri);
}
.cmd-chip.is-selected {
  border-color: var(--cmd-acc);
  background: linear-gradient(140deg, color-mix(in srgb, var(--cmd-pri) 22%, #0c192b), rgb(9 20 36 / 90%));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--cmd-acc) 45%, transparent), 0 6px 16px rgb(0 0 0 / 28%);
}
.cmd-chip.is-locked {
  opacity: 0.72;
}
.cmd-chip__avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: 1.5px solid var(--cmd-pri);
  object-fit: cover;
  flex-shrink: 0;
}
.cmd-chip__meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cmd-chip__meta b {
  font-size: 13px;
  line-height: 1.15;
}
.cmd-chip__meta small {
  font-size: 11px;
  color: #9bb8d3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-strip__active {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--cmd-pri) 36%, transparent);
  background: linear-gradient(135deg, color-mix(in srgb, var(--cmd-pri) 14%, #091525), rgb(7 16 29 / 88%));
}
.cmd-strip__portrait {
  width: 64px;
  height: 84px;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--cmd-acc) 42%, transparent);
  object-fit: cover;
  flex-shrink: 0;
}
.cmd-strip--compact .cmd-strip__portrait {
  width: 50px;
  height: 66px;
}
.cmd-strip__info {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.cmd-strip__name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cmd-strip__name-row strong {
  font-size: 15px;
  color: #f3f9ff;
}
.cmd-strip__tag {
  font-size: 11px;
  color: var(--cmd-acc);
}
.cmd-strip__lvl {
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  background: rgb(255 255 255 / 10%);
  color: #e6f4ff;
}
.cmd-strip__claim-btn {
  margin-left: auto;
  padding: 3px 10px;
  border-radius: 999px;
  border: 0;
  background: linear-gradient(90deg, #facc15, #f59e0b);
  color: #161005;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}
.cmd-strip__skill {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.cmd-strip__skill-name {
  font-size: 12px;
  font-weight: 700;
  color: #fde68a;
}
.cmd-strip__skill-badge {
  font-size: 11px;
  color: #a5cbe3;
}
.cmd-strip__toggle-desc {
  margin-left: auto;
  border: 0;
  background: transparent;
  color: #7dd3fc;
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}
.cmd-strip__desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: #bfd6ea;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.cmd-strip__desc.is-expanded {
  display: block;
  -webkit-line-clamp: unset;
}
.cmd-strip__note {
  margin: 0;
  font-size: 11px;
  color: #fde68a;
}
</style>
