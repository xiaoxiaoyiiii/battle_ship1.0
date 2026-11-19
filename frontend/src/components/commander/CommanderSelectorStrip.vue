<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  commanderPalette,
  useCommandersStore,
  type CommanderSpecView,
} from '../../stores/commanders'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'
import CommanderPortraitStage from './CommanderPortraitStage.vue'

const props = withDefaults(
  defineProps<{
    compact?: boolean
    headerSlot?: boolean
    title?: string
  }>(),
  {
    compact: false,
    headerSlot: false,
    title: '出战指挥官',
  },
)

const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()
const store = useCommandersStore()

const drawerOpen = ref(false)
const skillPopoverOpen = ref(false)
const actionNote = ref('')
const inspectedDrawerId = ref('')
const drawerToggleBtn = ref<HTMLButtonElement | null>(null)
const skillToggleBtn = ref<HTMLButtonElement | null>(null)
const drawerCloseBtn = ref<HTMLButtonElement | null>(null)

onMounted(() => {
  void store.load()
  window.addEventListener('keydown', onWindowKeydown, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeydown, true)
})

const current = computed<CommanderSpecView | null>(() => store.selectedCommander)
const list = computed(() => store.commanders)
const drawerDetailCommander = computed<CommanderSpecView | null>(() => {
  if (!list.value.length) return null
  return list.value.find((c) => c.id === inspectedDrawerId.value) ?? current.value ?? list.value[0]
})

watch(current, (val) => {
  if (val && !drawerOpen.value) inspectedDrawerId.value = val.id
})

function conciseLimitTag(cmd: CommanderSpecView): string {
  const s = cmd.skill
  if (s.kind === 'limited') {
    return s.enters_chain ? `限定 · 速阶 ${s.speed || 3}` : '限定 · 不入链'
  }
  if (s.kind === 'cooldown') {
    return `冷却 ${s.cooldown_rounds} 大回合 · 不入链`
  }
  return `每链 1 次 · 速阶 ${s.speed || 3}`
}

function shortSummary(cmd: CommanderSpecView): string {
  switch (cmd.id) {
    case 'chichao':
      return '本大回合总攻击额度为 6，扣除已用次数。'
    case 'qingtong':
      return '标记一艘敌舰，下一大回合结束时揭晓。'
    case 'tieanchor':
      return '本大回合己方舰队抵挡普通炮击击沉。'
    case 'guihang':
      return '牺牲一艘己方舰，技能结算时摸 2 张牌。'
    default:
      return cmd.skill.description
  }
}

function tierBadgeText(cmd: CommanderSpecView): string {
  if (auth.isGuest) return 'Lv.1 体验'
  const lv = cmd.progress.level
  if (lv >= 20) return 'Lv.20 终阶'
  if (lv >= 15) return `Lv.${lv} 统帅`
  if (lv >= 10) return `Lv.${lv} 进阶`
  return `Lv.${lv} 初始`
}

async function openDrawer(): Promise<void> {
  if (!list.value.length) await store.load(true)
  skillPopoverOpen.value = false
  inspectedDrawerId.value = current.value?.id || list.value[0]?.id || 'chichao'
  drawerOpen.value = true
  await nextTick()
  const activeEl = document.querySelector<HTMLButtonElement>(`[data-testid="commander-pick-${inspectedDrawerId.value}"]`)
  ;(activeEl || drawerCloseBtn.value)?.focus()
}

function closeDrawer(restoreFocus = true): void {
  if (!drawerOpen.value) return
  drawerOpen.value = false
  if (restoreFocus) {
    void nextTick(() => drawerToggleBtn.value?.focus())
  }
}

function closeSkillPopover(restoreFocus = true): void {
  if (!skillPopoverOpen.value) return
  skillPopoverOpen.value = false
  if (restoreFocus) {
    void nextTick(() => skillToggleBtn.value?.focus())
  }
}

function onWindowKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  if (drawerOpen.value) {
    event.preventDefault()
    event.stopPropagation()
    closeDrawer(true)
    return
  }
  if (skillPopoverOpen.value) {
    event.preventDefault()
    event.stopPropagation()
    closeSkillPopover(true)
  }
}

async function pickCommander(cmd: CommanderSpecView): Promise<void> {
  actionNote.value = ''
  inspectedDrawerId.value = cmd.id
  if (store.freeInitialAvailable && !cmd.owned) {
    const res = await store.unlock(cmd.id)
    actionNote.value = res.message || (res.ok ? `已免费解锁并出战「${cmd.name}」` : '')
    return
  }
  if (auth.isGuest || cmd.owned) {
    const res = await store.select(cmd.id)
    if (res.ok) {
      actionNote.value = `已切换为「${cmd.name}」`
    } else if (res.message) {
      actionNote.value = res.message
    }
    return
  }
  actionNote.value = `「${cmd.name}」尚未解锁（需 ${cmd.unlock_cost} 潮汐徽记），可前往指挥官殿堂解锁`
}

async function claimFree(cmd: CommanderSpecView): Promise<void> {
  const res = await store.unlock(cmd.id)
  if (res.ok) {
    ui.notify({ code: 'cmd-free-unlock', message: res.message || `已免费解锁「${cmd.name}」`, tone: 'success' })
  } else if (res.message) {
    ui.notifyError('cmd-free-unlock-err', res.message)
  }
}

function goCommanders(): void {
  closeDrawer(false)
  void router.push({ name: 'commanders' })
}

const activePalette = computed(() => commanderPalette(current.value?.id || 'chichao'))
</script>

<template>
  <section
    class="cmd-strip"
    :class="{
      'cmd-strip--compact': props.compact,
      'cmd-strip--header': props.headerSlot,
    }"
    :style="{
      '--cmd-pri': activePalette.primary,
      '--cmd-acc': activePalette.accent,
      '--cmd-sec': activePalette.secondary,
      '--cmd-glow': activePalette.glow,
    }"
    data-testid="commander-selector-strip"
    aria-label="指挥官选择"
  >
    <template v-if="current">
      <div class="cmd-card-bar">
        <div class="cmd-card-bar__bg" aria-hidden="true">
          <CommanderPortraitStage
            class="cmd-card-bar__stage"
            :commander-id="current.id"
            :commander-name="current.name"
            :level="current.progress.level"
            :equipped="current.equipped"
            mode="strip"
          />
        </div>

        <div class="cmd-card-bar__info">
          <div class="cmd-card-bar__kicker-row">
            <span class="cmd-card-bar__kicker">{{ props.title }}</span>
            <span class="cmd-card-bar__tier-pill">{{ tierBadgeText(current) }}</span>
            <span
              v-if="store.freeInitialAvailable"
              class="cmd-strip__free-pill"
              data-testid="commander-free-starter-badge"
            >首领免费任选 1 位</span>
            <button
              v-if="store.freeInitialAvailable && !current.owned"
              type="button"
              class="cmd-strip__claim-btn"
              data-testid="commander-free-unlock-now"
              @click="claimFree(current)"
            >免费领取并出战</button>
          </div>
          <div class="cmd-card-bar__title-row">
            <strong class="cmd-card-bar__name" data-testid="commander-active-name">{{ current.name }}</strong>
            <span class="cmd-card-bar__skill-name">{{ current.skill.name }}</span>
            <span v-if="actionNote" class="cmd-card-bar__inline-note" role="status">{{ actionNote }}</span>
          </div>
          <p class="cmd-card-bar__summary">
            <span>{{ shortSummary(current) }}</span>
            <small class="cmd-card-bar__limit">{{ conciseLimitTag(current) }}</small>
          </p>
        </div>

        <div class="cmd-card-bar__actions">
          <button
            ref="drawerToggleBtn"
            type="button"
            class="cmd-strip__drawer-btn"
            data-testid="commander-drawer-open"
            :aria-expanded="drawerOpen"
            aria-haspopup="dialog"
            @click="openDrawer"
          >切换指挥官</button>
          <div class="cmd-card-bar__sublinks">
            <button
              ref="skillToggleBtn"
              type="button"
              class="cmd-strip__link-btn"
              data-testid="commander-skill-preview-toggle"
              :aria-expanded="skillPopoverOpen"
              @click="skillPopoverOpen = !skillPopoverOpen"
            >{{ skillPopoverOpen ? '收起详情' : '技能详情' }}</button>
            <button
              type="button"
              class="cmd-strip__link-btn"
              data-testid="commander-open-hall"
              @click="goCommanders"
            >
              殿堂<small v-if="store.totalClaimableCount > 0" class="cmd-strip__red-dot">{{ store.totalClaimableCount }}</small> ›
            </button>
          </div>
        </div>
      </div>

      <!-- 轻量技能详情浮层：不撑高标题栏或中栏高度 -->
      <div
        v-show="skillPopoverOpen"
        class="cmd-skill-popover"
        data-testid="commander-skill-popover"
        role="region"
        aria-label="指挥官技能详情"
      >
        <div class="cmd-skill-popover__head">
          <strong>{{ current.name }} · 【{{ current.skill.name }}】</strong>
          <button type="button" class="cmd-skill-popover__close" aria-label="关闭技能详情" @click="closeSkillPopover(true)">×</button>
        </div>
        <small class="cmd-skill-popover__meta">{{ current.skill.limit_label }} · {{ current.skill.timing_label }}</small>
        <p class="cmd-skill-popover__desc" data-testid="commander-active-skill-desc">
          {{ current.skill.timing_label }}：{{ current.skill.description }}
        </p>
      </div>
    </template>

    <!-- 四角色切换抽屉（对齐 commander-header-drawer.png） -->
    <div
      class="cmd-drawer-scrim"
      :class="{ 'is-open': drawerOpen }"
      :aria-hidden="!drawerOpen"
      :inert="!drawerOpen || undefined"
      data-testid="commander-drawer"
      role="dialog"
      aria-modal="true"
      aria-label="切换出战指挥官"
      @click.self="closeDrawer(true)"
      @keydown.esc.stop.prevent="closeDrawer(true)"
    >
      <section class="cmd-drawer-panel">
        <header class="cmd-drawer-head">
          <div>
            <h2>切换出战指挥官</h2>
            <p>出战前可切换，本局保持所选指挥官。</p>
          </div>
          <div class="cmd-drawer-head__right">
            <button type="button" class="cmd-strip__hall-btn" @click="goCommanders">
              前往指挥官殿堂<small v-if="store.totalClaimableCount > 0" class="cmd-strip__red-dot">{{ store.totalClaimableCount }}</small> ›
            </button>
            <button
              ref="drawerCloseBtn"
              type="button"
              class="cmd-drawer-close"
              data-testid="commander-drawer-close"
              aria-label="关闭抽屉"
              @click="closeDrawer(true)"
            >×</button>
          </div>
        </header>

        <div class="cmd-drawer-grid" role="radiogroup" aria-label="四位指挥官选项">
          <button
            v-for="cmd in list"
            :key="cmd.id"
            type="button"
            class="cmd-drawer-card"
            :class="{
              'is-selected': current?.id === cmd.id,
              'is-inspected': drawerDetailCommander?.id === cmd.id,
              'is-locked': !auth.isGuest && !cmd.owned && !store.freeInitialAvailable,
            }"
            :style="{
              '--cmd-pri': cmd.palette.primary,
              '--cmd-acc': cmd.palette.accent,
              '--cmd-sec': cmd.palette.secondary,
            }"
            :data-testid="'commander-pick-' + cmd.id"
            :aria-checked="current?.id === cmd.id"
            role="radio"
            @click="pickCommander(cmd)"
          >
            <div class="cmd-drawer-card__portrait">
              <CommanderPortraitStage
                class="cmd-drawer-card__stage"
                :commander-id="cmd.id"
                :commander-name="cmd.name"
                :level="cmd.progress.level"
                :equipped="cmd.equipped"
                mode="bust"
                :active="current?.id === cmd.id"
                :muted="!auth.isGuest && !cmd.owned && !store.freeInitialAvailable"
              />
            </div>
            <div class="cmd-drawer-card__body">
              <div class="cmd-drawer-card__top">
                <b>{{ cmd.name }}</b>
                <span v-if="auth.isGuest" class="cmd-drawer-card__lv">Lv.1 体验</span>
                <span v-else-if="cmd.owned" class="cmd-drawer-card__lv">Lv.{{ cmd.progress.level }}</span>
                <span v-else-if="store.freeInitialAvailable" class="cmd-drawer-card__free">免费首领</span>
                <span v-else class="cmd-drawer-card__lock">{{ cmd.unlock_cost }} 徽记</span>
              </div>
              <span class="cmd-drawer-card__skill">{{ cmd.skill.name }}</span>
              <p class="cmd-drawer-card__summary">{{ shortSummary(cmd) }}</p>
              <small class="cmd-drawer-card__limit">{{ conciseLimitTag(cmd) }}</small>
            </div>
          </button>
        </div>

        <footer v-if="drawerDetailCommander" class="cmd-drawer-detail" data-testid="commander-drawer-detail">
          <p class="cmd-drawer-detail__text">
            <strong>{{ drawerDetailCommander.name }} · 【{{ drawerDetailCommander.skill.name }}】</strong>
            <span>{{ drawerDetailCommander.skill.timing_label }}：{{ drawerDetailCommander.skill.description }}</span>
          </p>
          <p v-if="actionNote" class="cmd-strip__note" role="status">{{ actionNote }}</p>
        </footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.cmd-strip {
  position: relative;
  width: 100%;
  min-width: 0;
}
.cmd-card-bar {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 76px;
  padding: 9px 14px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--cmd-pri) 42%, rgb(120 200 235 / 26%));
  background: linear-gradient(
    96deg,
    rgb(13 21 36 / 95%) 0%,
    color-mix(in srgb, var(--cmd-pri) 18%, #141c2f) 58%,
    rgb(14 23 39 / 96%) 100%
  );
  box-shadow: 0 8px 22px rgb(0 0 0 / 28%), inset 0 1px 0 rgb(255 255 255 / 6%);
  overflow: hidden;
}
.cmd-strip--header .cmd-card-bar {
  height: 76px;
  min-height: 76px;
  padding: 8px 14px;
}
.cmd-strip--compact .cmd-card-bar {
  min-height: 78px;
  padding: 10px 16px;
}
.cmd-card-bar__bg {
  position: absolute;
  top: 0;
  bottom: 0;
  right: 118px;
  width: 240px;
  pointer-events: none;
  z-index: 0;
  -webkit-mask-image: linear-gradient(90deg, transparent 0%, #000 24%, #000 76%, transparent 100%);
  mask-image: linear-gradient(90deg, transparent 0%, #000 24%, #000 76%, transparent 100%);
}
.cmd-strip--compact .cmd-card-bar__bg {
  right: 132px;
  width: 280px;
}
.cmd-card-bar__stage {
  width: 100%;
  height: 100%;
}
.cmd-card-bar__info {
  position: relative;
  z-index: 1;
  min-width: 0;
  flex: 1 1 auto;
  max-width: calc(100% - 210px);
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.cmd-card-bar__kicker-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  overflow: hidden;
}
.cmd-card-bar__kicker {
  font-size: 11px;
  font-weight: 600;
  color: #b7cde4;
  white-space: nowrap;
}
.cmd-card-bar__tier-pill {
  padding: 1px 7px;
  border-radius: 5px;
  border: 1px solid color-mix(in srgb, var(--cmd-acc) 55%, transparent);
  background: color-mix(in srgb, var(--cmd-pri) 20%, #10192b);
  color: var(--cmd-acc);
  font-size: 10.5px;
  font-weight: 700;
  white-space: nowrap;
}
.cmd-strip__free-pill {
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 700;
  color: #161005;
  background: linear-gradient(90deg, #facc15, #f59e0b);
  white-space: nowrap;
}
.cmd-strip__claim-btn {
  padding: 1px 8px;
  border-radius: 999px;
  border: 0;
  background: #22c55e;
  color: #052e16;
  font-size: 10.5px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}
.cmd-card-bar__title-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.cmd-card-bar__name {
  font-size: 18px;
  line-height: 1.15;
  color: #ffffff;
  font-weight: 750;
  white-space: nowrap;
}
.cmd-card-bar__skill-name {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--cmd-acc);
  white-space: nowrap;
}
.cmd-card-bar__inline-note {
  font-size: 11px;
  color: #7dd3fc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-card-bar__summary {
  margin: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 11.5px;
  line-height: 1.3;
  color: #cbd5e1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-card-bar__summary span {
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-card-bar__limit {
  font-size: 11px;
  color: var(--cmd-acc);
  opacity: 0.9;
  flex-shrink: 0;
}
.cmd-card-bar__actions {
  position: relative;
  z-index: 1;
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 5px;
}
.cmd-strip__drawer-btn {
  min-height: 30px;
  padding: 4px 12px;
  border-radius: 7px;
  border: 1px solid rgb(226 232 240 / 32%);
  background: rgb(14 23 39 / 84%);
  color: #f8fafc;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.16s ease, background 0.16s ease;
}
.cmd-strip__drawer-btn:hover {
  border-color: var(--cmd-acc);
  background: color-mix(in srgb, var(--cmd-pri) 22%, #0e1727);
}
.cmd-card-bar__sublinks {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cmd-strip__link-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #a9c7e4;
  font-size: 11.5px;
  cursor: pointer;
  white-space: nowrap;
}
.cmd-strip__link-btn:hover {
  color: #ffffff;
}
.cmd-strip__hall-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  border-radius: 999px;
  border: 1px solid rgb(120 200 235 / 35%);
  background: rgb(14 38 62 / 78%);
  color: #cdeeff;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}
.cmd-strip__hall-btn:hover {
  border-color: #7dd3fc;
  color: #fff;
}
.cmd-strip__red-dot {
  display: inline-grid;
  place-items: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: #ef4444;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
}

/* 技能详情轻浮层 */
.cmd-skill-popover {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 95;
  width: min(460px, calc(100vw - 32px));
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--cmd-acc) 48%, rgb(125 211 252 / 28%));
  background: rgb(10 21 38 / 96%);
  box-shadow: 0 18px 40px rgb(0 0 0 / 56%);
  backdrop-filter: blur(10px);
}
.cmd-skill-popover__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.cmd-skill-popover__head strong {
  font-size: 14px;
  color: var(--cmd-acc);
}
.cmd-skill-popover__close {
  border: 0;
  background: transparent;
  color: #94a3b8;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}
.cmd-skill-popover__meta {
  display: block;
  margin-top: 3px;
  font-size: 11px;
  color: #7dd3fc;
}
.cmd-skill-popover__desc {
  margin: 7px 0 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: #e2eefb;
}

/* 四角色切换抽屉 */
.cmd-drawer-scrim {
  position: fixed;
  inset: 0;
  z-index: 260;
  display: flex;
  justify-content: flex-end;
  background: rgb(4 10 20 / 68%);
  backdrop-filter: blur(4px);
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: opacity 0.2s ease, visibility 0.2s ease;
}
.cmd-drawer-scrim.is-open {
  opacity: 1;
  visibility: visible;
  pointer-events: auto;
}
.cmd-drawer-panel {
  width: min(650px, 95vw);
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 76px 24px 20px;
  background: linear-gradient(170deg, #0b182a, #091322);
  border-left: 1px solid rgb(125 211 252 / 24%);
  box-shadow: -20px 0 50px rgb(0 0 0 / 60%);
  overflow-y: auto;
  transform: translateX(22px);
  transition: transform 0.22s ease;
}
.cmd-drawer-scrim.is-open .cmd-drawer-panel {
  transform: translateX(0);
}
.cmd-drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.cmd-drawer-head h2 {
  margin: 0;
  font-size: 20px;
  color: #f8fafc;
}
.cmd-drawer-head p {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: #93b5d1;
}
.cmd-drawer-head__right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cmd-drawer-close {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid rgb(148 163 184 / 30%);
  background: rgb(15 28 48 / 88%);
  color: #e2e8f0;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}
.cmd-drawer-close:hover {
  border-color: #7dd3fc;
  color: #fff;
}
.cmd-drawer-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
@media (max-width: 600px) {
  .cmd-drawer-grid {
    grid-template-columns: 1fr;
  }
}
.cmd-drawer-card {
  display: flex;
  align-items: stretch;
  gap: 12px;
  padding: 10px;
  border-radius: 14px;
  border: 1px solid rgb(148 163 184 / 22%);
  background: rgb(12 24 42 / 86%);
  color: #e2eefb;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}
.cmd-drawer-card:hover {
  transform: translateY(-1px);
  border-color: var(--cmd-pri);
}
.cmd-drawer-card.is-selected {
  border-color: var(--cmd-acc);
  background: linear-gradient(145deg, color-mix(in srgb, var(--cmd-pri) 20%, #0d1d34), rgb(9 19 35 / 95%));
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--cmd-acc) 45%, transparent), 0 8px 22px rgb(0 0 0 / 35%);
}
.cmd-drawer-card.is-locked {
  opacity: 0.78;
}
.cmd-drawer-card__portrait {
  width: 90px;
  aspect-ratio: 3 / 4;
  border-radius: 10px;
  overflow: hidden;
  flex-shrink: 0;
}
.cmd-drawer-card__stage {
  width: 100%;
  height: 100%;
  border-radius: 10px;
}
.cmd-drawer-card__body {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.cmd-drawer-card__top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
}
.cmd-drawer-card__top b {
  font-size: 16px;
  color: #f8fafc;
}
.cmd-drawer-card__lv {
  font-size: 12px;
  font-weight: 700;
  color: var(--cmd-acc);
}
.cmd-drawer-card__free {
  padding: 1px 6px;
  border-radius: 999px;
  background: #22c55e;
  color: #052e16;
  font-size: 10.5px;
  font-weight: 700;
}
.cmd-drawer-card__lock {
  font-size: 11px;
  color: #94a3b8;
}
.cmd-drawer-card__skill {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--cmd-acc);
}
.cmd-drawer-card__summary {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: #cbd5e1;
  flex: 1;
}
.cmd-drawer-card__limit {
  font-size: 11px;
  color: #93b5d1;
}
.cmd-drawer-detail {
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgb(125 211 252 / 24%);
  background: rgb(14 27 46 / 86%);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cmd-drawer-detail__text {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: #dce9f5;
}
.cmd-drawer-detail__text strong {
  display: block;
  color: #fde68a;
  margin-bottom: 3px;
}
.cmd-strip__note {
  margin: 0;
  font-size: 12px;
  color: #7dd3fc;
}

@media (max-width: 700px) {
  .cmd-card-bar__bg {
    right: 92px;
    width: 150px;
    opacity: 0.72;
  }
  .cmd-card-bar__info {
    max-width: calc(100% - 116px);
  }
  .cmd-strip--header .cmd-card-bar {
    height: auto;
    min-height: 70px;
  }
  .cmd-card-bar__limit {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cmd-drawer-scrim,
  .cmd-drawer-panel,
  .cmd-drawer-card {
    transition: none;
  }
}
</style>
