<script setup lang="ts">
/**
 * 持续效果 + 场地魔法监视栏（原 main 的 `.field-magic-area` 位置）。
 *
 * 为什么合并成一条：场地魔法与多回合效果过去分散在「一行细提示」和两个 24px 小按钮里，
 * 信息密度低、还随数量变化撑高页面。这里固定高度、按数量等分（1/2/4），超出部分只在
 * 栏内横向滚动，永远不推动棋盘、手牌、日志与行动按钮。
 */
import { computed, ref } from 'vue'
import { cardArtUrl } from '../../cards/cardArt'
import AppOverlay from '../../components/AppOverlay.vue'

export interface MonitorCard {
  name: string
  speed?: number | null
  type?: string | null
  description?: string
}

export interface MonitorBadge {
  key: string
  label: string
  description: string
  expires: string
  card?: MonitorCard | null
}

const props = withDefaults(
  defineProps<{
    field?: MonitorCard | null
    fieldOwner?: string | null
    selfEffects?: MonitorBadge[]
    opponentEffects?: MonitorBadge[]
  }>(),
  { field: null, fieldOwner: null, selfEffects: () => [], opponentEffects: () => [] },
)

const hovered = ref<{ card: MonitorCard; label: string; tone: string; left: number; top: number } | null>(null)
const opened = ref<{ card: MonitorCard; label: string; tone: string } | null>(null)

interface Segment {
  id: string
  label: string
  card: MonitorCard
  tone: 'field' | 'self' | 'opponent'
  expires: string
}

// 横向监视栏只展示「双方都受影响」的持续效果。玩家个人状态仍然由头像旁的
// StatusMonitor 展示，避免把诸如无中生有、神机妙算这类单方效果误放进全局栏。
const SHARED_EFFECT_NAMES = new Set(['无暇圣心', '极限增援'])

function sharedBadgeCard(badge: MonitorBadge): MonitorCard {
  return badge.card ?? { name: badge.label, description: badge.description }
}

const segments = computed<Segment[]>(() => {
  const rows: Segment[] = []
  if (props.field?.name) {
    rows.push({
      id: `field:${props.field.name}`,
      label: '场地',
      card: props.field,
      tone: 'field',
      expires: props.fieldOwner ? '场地魔法' : '',
    })
  }
  // 长效全局效果由施放者一侧携带。两边都可能在重连/同步时携带同一项，
  // 因此按卡名去重，保证监视栏一个效果只占一个区块。
  const shared = new Map<string, { badge: MonitorBadge; tone: 'self' | 'opponent' }>()
  for (const [badges, tone] of [
    [props.selfEffects, 'self'] as const,
    [props.opponentEffects, 'opponent'] as const,
  ]) {
    for (const badge of badges) {
      const card = sharedBadgeCard(badge)
      if (SHARED_EFFECT_NAMES.has(card.name) && !shared.has(card.name)) {
        shared.set(card.name, { badge, tone })
      }
    }
  }
  for (const [name, { badge, tone }] of shared) {
    rows.push({
      id: `shared:${name}`,
      label: '全局',
      card: sharedBadgeCard(badge),
      tone,
      expires: badge.expires,
    })
  }
  return rows
})

const art = (card: MonitorCard): string | null => cardArtUrl(card.name)
const hasAny = computed(() => segments.value.length > 0)

function previewPosition(event: Event): { left: number; top: number } {
  const target = event.currentTarget as HTMLElement | null
  const bounds = target?.getBoundingClientRect()
  const x = event instanceof MouseEvent ? event.clientX : (bounds?.left ?? 0) + (bounds?.width ?? 0) / 2
  const y = event instanceof MouseEvent ? event.clientY : (bounds?.bottom ?? 0)
  const width = Math.min(560, Math.max(260, window.innerWidth - 24))
  const height = Math.min(290, Math.max(220, window.innerHeight * 0.42))
  const left = Math.max(12, Math.min(window.innerWidth - width - 12, x + 18))
  const above = y - height - 18
  const top = above >= 12
    ? above
    : Math.min(window.innerHeight - height - 12, y + 18)
  return { left, top: Math.max(12, top) }
}

function identityOf(segment: Segment, event: Event) {
  return { card: segment.card, label: segment.label, tone: segment.tone, ...previewPosition(event) }
}

function openedIdentityOf(segment: Segment) {
  return { card: segment.card, label: segment.label, tone: segment.tone }
}

function describe(card: MonitorCard): string {
  return card.description || '暂无效果描述'
}
</script>

<template>
  <div class="monitor" data-testid="game-field-magic" :data-count="segments.length">
    <span class="monitor__caption">持续效果 · 场地</span>

    <div v-if="!hasAny" class="monitor__empty" data-testid="effect-monitor-empty">本局暂无持续效果</div>

    <ul v-else class="monitor__list" :data-slots="Math.min(Math.max(segments.length, 1), 4)">
      <li
        v-for="segment in segments"
        :key="segment.id"
        class="monitor__slot"
        :class="`is-${segment.tone}`"
        :data-testid="`effect-slot-${segment.tone}-${segment.card.name}`"
        tabindex="0"
        @mouseenter="hovered = identityOf(segment, $event)"
        @mouseleave="hovered = null"
        @focus="hovered = identityOf(segment, $event)"
        @blur="hovered = null"
        @click="opened = openedIdentityOf(segment)"
        @keydown.enter.prevent="opened = openedIdentityOf(segment)"
        @keydown.space.prevent="opened = openedIdentityOf(segment)"
      >
        <img v-if="art(segment.card)" class="monitor__art" :src="art(segment.card)!" :alt="`${segment.card.name} 卡面`" />
        <span v-else class="monitor__art monitor__art--none" aria-hidden="true">{{ segment.card.name.slice(0, 1) }}</span>
        <span class="monitor__body">
          <span class="monitor__name">{{ segment.card.name }}</span>
          <span class="monitor__meta">
            <span class="monitor__tag">{{ segment.label === '场地' ? '场地' : '持续' }}</span>
            <span v-if="segment.expires" class="monitor__expires">{{ segment.expires }}</span>
          </span>
        </span>
      </li>
    </ul>

    <!-- 悬停预览：固定层，不参与布局 -->
    <Teleport to="body">
      <div
        v-if="hovered"
        class="monitor-preview"
        :class="`is-${hovered.tone}`"
        :style="{ left: hovered.left + 'px', top: hovered.top + 'px' }"
        role="tooltip"
        data-testid="effect-monitor-preview"
      >
        <img v-if="art(hovered.card)" class="monitor-preview__art" :src="art(hovered.card)!" :alt="`${hovered.card.name} 卡面`" />
        <div class="monitor-preview__body">
          <strong class="monitor-preview__name">{{ hovered.card.name }}</strong>
          <span class="monitor-preview__meta">
            {{ hovered.card.speed ? `速阶 ${hovered.card.speed}` : '' }}
            {{ hovered.card.type ? ` · ${hovered.card.type}` : '' }}
          </span>
          <p class="monitor-preview__text">{{ describe(hovered.card) }}</p>
        </div>
      </div>

    </Teleport>
    <AppOverlay v-if="opened" id="effect-monitor-dialog" :priority="120" labelledby="effect-monitor-dialog-title" @close="opened = null; hovered = null">
        <div class="monitor-dialog__card" :class="`is-${opened.tone}`">
          <header class="monitor-dialog__head">
            <strong id="effect-monitor-dialog-title" class="monitor-dialog__name">{{ opened.card.name }}</strong>
            <button type="button" class="monitor-dialog__close" data-testid="effect-monitor-close" @click="opened = null">
              关闭
            </button>
          </header>
          <div class="monitor-dialog__body">
            <img
              v-if="art(opened.card)"
              class="monitor-dialog__art"
              :src="art(opened.card)!"
              :alt="`${opened.card.name} 卡面`"
            />
            <div class="monitor-dialog__text">
              <span class="monitor-dialog__meta">
                {{ opened.card.speed ? `速阶 ${opened.card.speed}` : '' }}
                {{ opened.card.type ? ` · ${opened.card.type}` : '' }}
              </span>
              <p>{{ describe(opened.card) }}</p>
            </div>
          </div>
        </div>
    </AppOverlay>
  </div>
</template>

<style scoped>
.monitor {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  width: 100%;
  gap: 12px;
  height: 100%;
  min-height: 44px;
  padding: 4px 12px;
  border: 0;
  border-radius: 8px;
  background: var(--surface-chamber);
  overflow: hidden;
}

.monitor__caption {
  flex: 0 0 auto;
  font-size: 11px;
  letter-spacing: 0.02em;
  color: var(--text-muted);
  writing-mode: horizontal-tb;
}

.monitor__empty {
  flex: 1 1 auto;
  font-size: 12px;
  color: var(--text-muted);
}

.monitor__list {
  display: flex;
  align-items: stretch;
  gap: 0;
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}

/* 1 个占满、2 个二等分、4 个四等分；更多时保持四等分宽度、栏内滚动 */
.monitor__list[data-slots='1'] .monitor__slot { flex: 1 1 100%; min-width: 0; }
.monitor__list[data-slots='2'] .monitor__slot { flex: 1 1 calc(50% - 3px); }
.monitor__list[data-slots='3'] .monitor__slot { flex: 1 1 calc(33.333% - 4px); }
.monitor__list[data-slots='4'] .monitor__slot { flex: 1 1 calc(25% - 5px); }

.monitor__slot {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 10px;
  min-width: 120px;
  max-width: 100%;
  padding: 3px 14px;
  border: 1px solid transparent;
  border-left-color: var(--border-subtle);
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease;
}

.monitor__slot:hover,
.monitor__slot:focus-visible {
  background: color-mix(in srgb, var(--role-action, #9d84f5) 18%, transparent);
  border-color: color-mix(in srgb, var(--role-action, #9d84f5) 60%, transparent);
  outline: none;
}

.monitor__slot.is-field .monitor__name { color:var(--gold-strong); }
.monitor__slot.is-opponent .monitor__tag { border-color:color-mix(in srgb,var(--role-enemy) 50%,transparent); }

.monitor__art {
  flex: 0 0 auto;
  width: 26px;
  height: 38px;
  border-radius: 4px;
  object-fit: cover;
  background: #0f1729;
}

.monitor__art--none {
  display: grid;
  place-items: center;
  font-size: 14px;
  color: var(--text-muted);
}

.monitor__body { display: flex; flex-direction: column; gap: 1px; min-width: 0; }

.monitor__name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.monitor__meta { display: flex; align-items: center; gap: 6px; min-width: 0; }

.monitor__tag {
  flex: 0 0 auto;
  padding: 0 4px;
  border-radius: 4px;
  font-size: 11px;
  color: var(--text-muted);
  border: 1px solid color-mix(in srgb, var(--text-muted) 40%, transparent);
}

.monitor__expires {
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.monitor-preview {
  position: fixed;
  z-index: 70;
  display: flex;
  gap: 14px;
  width: min(560px, calc(100vw - 24px));
  padding: 14px;
  border-radius: 14px;
  border: 1px solid color-mix(in srgb, var(--gold-strong, #e6c778) 60%, var(--line-dash));
  background: var(--surface-chamber, #101a2e);
  box-shadow: 0 22px 54px rgba(0, 0, 0, 0.58), 0 0 0 1px rgba(124, 92, 240, 0.14);
  pointer-events: none;
}

.monitor-preview__art { width: 142px; height: 208px; flex: 0 0 auto; border-radius: 8px; object-fit: cover; box-shadow: 0 8px 20px rgba(0, 0, 0, 0.36); }
.monitor-preview__body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.monitor-preview__name { font-size: 18px; color: var(--text-primary); }
.monitor-preview__meta { font-size: 13px; color: var(--text-muted); }
.monitor-preview__text { margin: 4px 0 0; font-size: 14px; line-height: 1.7; color: var(--text-secondary); max-height: 168px; overflow: hidden; }

:global(.app-overlay__panel[data-testid='effect-monitor-dialog']) { width:min(520px,90vw); max-height:min(70vh,620px); }
.monitor-dialog__card {
  position: relative;
  width: 100%;
  max-height: min(70vh, 620px);
  overflow-y: auto;
  padding: 14px 16px 16px;
  border-radius: 14px;
  border: 1px solid var(--line-dash);
  background: var(--surface-chamber, #101a2e);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}

.monitor-dialog__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.monitor-dialog__name { font-size: 15px; color: var(--text-primary); }
.monitor-dialog__close {
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid var(--line-dash);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.monitor-dialog__body { display: flex; gap: 14px; margin-top: 12px; }
.monitor-dialog__art { width: 132px; height: 192px; border-radius: 8px; object-fit: cover; flex: 0 0 auto; }
.monitor-dialog__text { min-width: 0; }
.monitor-dialog__meta { font-size: 11px; color: var(--text-muted); }
.monitor-dialog__text p { margin: 6px 0 0; font-size: 12px; line-height: 1.65; color: var(--text-secondary); }

@media (max-width: 719px) {
  .monitor { padding: 3px 6px; gap: 6px; }
  .monitor__caption { display: none; }
  .monitor__slot { min-width: 96px; padding: 2px 6px; }
  .monitor__art { width: 20px; height: 30px; }
  .monitor__name { font-size: 12px; }
  .monitor-preview { width: min(420px, calc(100vw - 24px)); gap: 10px; padding: 10px; }
  .monitor-preview__art { width: 104px; height: 152px; }
  .monitor-preview__name { font-size: 15px; }
  .monitor-preview__meta { font-size: 11px; }
  .monitor-preview__text { font-size: 12px; line-height: 1.55; max-height: 132px; }
  .monitor-dialog__body { flex-direction: column; }
  .monitor-dialog__art { width: 96px; height: 140px; }
}

@media (prefers-reduced-motion: reduce) {
  .monitor__slot { transition: none; }
}
</style>
