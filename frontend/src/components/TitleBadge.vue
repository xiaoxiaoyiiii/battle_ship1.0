<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  name?: string
  titleId?: string
  titleFxId?: string
  compact?: boolean
}>(), {
  name: '',
  titleId: '',
  titleFxId: '',
  compact: false,
})

/**
 * 称号的动态等级由服务端解锁池的 id 决定：普通称号保持轻微流光，
 * 赛季/高段位称号使用更明显的金色棱镜，但仍不改变文字本身的可读性。
 */
const tier = computed<'plain' | 'rare' | 'epic'>(() => {
  if (['season_deep_1', 'sea_emperor', 'unsinkable', 'immortal', 'deep_navigator', 'iron_soul'].includes(props.titleId)) return 'epic'
  if (['hunter', 'streak10', 'veteran', 'cardmaster', 'storm_helmsman', 'tide_watcher', 'storm_cartographer'].includes(props.titleId)) return 'rare'
  return 'plain'
})

const effect = computed<'none' | 'pulse' | 'spark' | 'prism'>(() => {
  if (props.titleFxId === 'none') return 'none'
  if (props.titleFxId === 'pulse' || props.titleFxId === 'spark' || props.titleFxId === 'prism') return props.titleFxId
  // 当前服务端槽位叫 title_effect_id，默认值 glint；兼容未来直接下发的 fx id。
  if (props.titleFxId === 'glint') return 'spark'
  if (props.titleFxId === 'orbit') return 'prism'
  if (tier.value === 'epic') return 'prism'
  if (tier.value === 'rare') return 'spark'
  return 'pulse'
})
</script>

<template>
  <span
    v-if="name"
    class="title-badge"
    :class="[`title-badge--${tier}`, `title-badge--fx-${effect}`, { 'title-badge--compact': compact }]"
    :data-title-id="titleId || undefined"
    :aria-label="'称号：' + name"
  >
    <span class="title-badge__crest" aria-hidden="true">✦</span>
    <span class="title-badge__label">{{ name }}</span>
    <span class="title-badge__shine" aria-hidden="true"></span>
  </span>
</template>

<style>
.title-badge {
  --title-color: var(--gold-strong, #f3c85f);
  --title-soft: var(--gold-soft, rgb(243 200 95 / 16%));
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 28px;
  max-width: 100%;
  overflow: hidden;
  padding: 4px 11px 4px 8px;
  border: 1px solid color-mix(in srgb, var(--title-color) 58%, transparent);
  border-radius: 999px;
  background: linear-gradient(120deg, color-mix(in srgb, var(--title-soft) 90%, transparent), rgb(5 12 25 / 72%));
  color: var(--title-color);
  font-size: 13px;
  font-weight: 720;
  letter-spacing: .03em;
  line-height: 1.1;
  text-shadow: 0 0 12px color-mix(in srgb, var(--title-color) 48%, transparent);
  white-space: nowrap;
}

.title-badge__crest {
  display: inline-grid;
  place-items: center;
  width: 16px;
  height: 16px;
  color: var(--title-color);
  font-size: 11px;
  animation: title-badge-pulse 2.8s ease-in-out infinite;
}

.title-badge__label {
  overflow: hidden;
  text-overflow: ellipsis;
}

.title-badge__shine {
  position: absolute;
  inset: -40% auto -40% -38%;
  width: 24%;
  background: linear-gradient(90deg, transparent, rgb(255 255 255 / 60%), transparent);
  transform: skewX(-18deg);
  animation: title-badge-shine 5.2s ease-in-out infinite;
  pointer-events: none;
}

.title-badge--compact {
  min-height: 22px;
  padding: 3px 8px 3px 6px;
  font-size: 11px;
}

.title-badge--compact .title-badge__crest { width: 13px; height: 13px; font-size: 9px; }

.title-badge--rare {
  --title-color: #8fe5f4;
  --title-soft: rgb(78 200 224 / 20%);
  border-radius: 9px;
  box-shadow: 0 0 15px rgb(78 200 224 / 18%), inset 0 0 12px rgb(78 200 224 / 10%);
}

.title-badge--rare .title-badge__crest { animation-duration: 2.2s; }

.title-badge--epic {
  --title-color: #f7d477;
  --title-soft: rgb(240 153 72 / 24%);
  border-width: 1px;
  border-radius: 8px 14px 8px 14px;
  box-shadow: 0 0 20px rgb(244 167 106 / 22%), inset 0 0 16px rgb(247 212 119 / 12%);
}

.title-badge--epic::before,
.title-badge--epic::after {
  position: absolute;
  content: '';
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--title-color);
  box-shadow: 0 0 8px var(--title-color);
  animation: title-badge-orbit 3.2s linear infinite;
}

.title-badge--epic::before { top: -2px; left: 32%; }
.title-badge--epic::after { right: 25%; bottom: -2px; animation-delay: -1.6s; }

.title-badge--fx-pulse .title-badge__label { animation: title-badge-label-pulse 2.7s ease-in-out infinite; }
.title-badge--fx-spark .title-badge__shine { animation-duration: 3.4s; }
.title-badge--fx-none .title-badge__crest,
.title-badge--fx-none .title-badge__shine,
.title-badge--fx-none::before,
.title-badge--fx-none::after { animation: none; }
.title-badge--fx-prism {
  background: linear-gradient(110deg, rgb(128 92 240 / 22%), rgb(78 200 224 / 18%), rgb(243 200 95 / 22%));
  background-size: 220% 100%;
  animation: title-badge-prism 4.8s ease-in-out infinite;
}

@keyframes title-badge-shine {
  0%, 58% { left: -38%; opacity: 0; }
  68% { opacity: .8; }
  82%, 100% { left: 128%; opacity: 0; }
}

@keyframes title-badge-pulse {
  0%, 100% { opacity: .72; transform: scale(.92) rotate(0deg); }
  50% { opacity: 1; transform: scale(1.13) rotate(12deg); }
}

@keyframes title-badge-orbit {
  0% { transform: translate(0, 0) scale(.7); opacity: .4; }
  50% { transform: translate(12px, -4px) scale(1); opacity: 1; }
  100% { transform: translate(0, 0) scale(.7); opacity: .4; }
}

@keyframes title-badge-label-pulse {
  0%, 100% { opacity: .8; }
  50% { opacity: 1; text-shadow: 0 0 16px color-mix(in srgb, var(--title-color) 72%, transparent); }
}

@keyframes title-badge-prism {
  0%, 100% { background-position: 0% 50%; filter: saturate(1); }
  50% { background-position: 100% 50%; filter: saturate(1.25); }
}

html[data-motion='reduced'] .title-badge__crest,
html[data-motion='reduced'] .title-badge__shine,
html[data-motion='reduced'] .title-badge__label,
html[data-motion='reduced'] .title-badge--fx-prism,
html[data-motion='reduced'] .title-badge--epic::before,
html[data-motion='reduced'] .title-badge--epic::after {
  animation: none;
}

@media (prefers-reduced-motion: reduce) {
  .title-badge__crest,
  .title-badge__shine,
  .title-badge__label,
  .title-badge--fx-prism,
  .title-badge--epic::before,
  .title-badge--epic::after { animation: none; }
}
</style>
