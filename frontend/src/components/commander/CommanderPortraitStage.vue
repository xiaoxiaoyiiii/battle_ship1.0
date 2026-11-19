<script setup lang="ts">
import { computed } from 'vue'
import {
  commanderFaceFocus,
  commanderPalette,
  commanderPortraitUrl,
  commanderSkillVfxForEquipped,
  commanderTierOf,
  portraitForLevelAndEquipped,
  portraitVariantFor,
  type CommanderEquippedLike,
} from '../../stores/commanders'
import { useUiStore } from '../../stores/ui'
import CommanderVfxLayer, { type CommanderVfxStage } from './CommanderVfxLayer.vue'

const props = withDefaults(
  defineProps<{
    commanderId: string
    commanderName?: string
    level?: number
    equipped?: CommanderEquippedLike | null
    portraitOverride?: string
    mode?: 'strip' | 'bust' | 'full'
    active?: boolean
    muted?: boolean
    previewStage?: CommanderVfxStage
    previewTier?: number | null
  }>(),
  {
    commanderName: '',
    level: 1,
    equipped: null,
    portraitOverride: '',
    mode: 'bust',
    active: false,
    muted: false,
    previewStage: '',
    previewTier: null,
  },
)

const effectiveTier = computed(() =>
  typeof props.previewTier === 'number' ? props.previewTier : commanderTierOf(props.level),
)

const ui = useUiStore()
const palette = computed(() => commanderPalette(props.commanderId))

const activeVariant = computed(() => {
  if (
    props.portraitOverride === 'base' ||
    props.portraitOverride === 'ascended' ||
    props.portraitOverride === 'alt' ||
    props.portraitOverride === 'ultimate'
  ) {
    return props.portraitOverride
  }
  return portraitVariantFor(props.level, props.equipped)
})

const portraitSrc = computed(() => {
  if (props.portraitOverride) {
    return commanderPortraitUrl(props.commanderId, props.portraitOverride)
  }
  return portraitForLevelAndEquipped(props.commanderId, props.level, props.equipped)
})

// 原图用于缩略图或减少动画。分层动作沿用玩家实际装备的立绘。
const artMotion = computed(() => {
  if (ui.motion === 'reduced' || activeVariant.value === 'base' || effectiveTier.value < 2) return ''
  if (effectiveTier.value >= 4 && activeVariant.value === 'ultimate') return 'ultimate'
  return effectiveTier.value >= 3 ? 'surge' : 'flow'
})

const imgSrc = computed(() => artMotion.value ? `${portraitSrc.value}#${artMotion.value}` : portraitSrc.value)
const facePos = computed(() => commanderFaceFocus(props.commanderId, activeVariant.value))

const isExclusiveVfx = computed(() => {
  if (typeof props.previewTier === 'number') return props.previewTier >= 3
  return commanderSkillVfxForEquipped(props.level, props.equipped) === 'exclusive'
})
</script>

<template>
  <div
    class="cmd-portrait-stage"
    :class="[
      `cmd-portrait-stage--${mode}`,
      `cmd-portrait-stage--tier-${effectiveTier}`,
      {
        'is-active': active,
        'is-muted': muted,
        'is-entering': previewStage === 'intro' || previewStage === 'victory',
      },
    ]"
    :style="{
      '--cmd-pri': palette.primary,
      '--cmd-acc': palette.accent,
      '--cmd-sec': palette.secondary,
      '--cmd-glow': palette.glow,
      '--cmd-face-pos': facePos,
    }"
  >
    <img
      class="cmd-portrait-stage__img"
      :class="{ 'cmd-portrait-stage__img--art-motion': artMotion }"
      :src="imgSrc"
      :alt="commanderName || commanderId"
      decoding="async"
    />
    <div class="cmd-portrait-stage__vignette" aria-hidden="true"></div>
    <div class="cmd-portrait-stage__sweep" aria-hidden="true"></div>
    <div class="cmd-portrait-stage__halo" aria-hidden="true"></div>
    <div v-if="effectiveTier >= 4" class="cmd-portrait-stage__halo-outer" aria-hidden="true"></div>
    <div class="cmd-portrait-stage__motes" aria-hidden="true">
      <i v-for="n in 8" :key="n" :style="{ '--n': n - 1 }"></i>
    </div>
    <div class="cmd-portrait-stage__frame" aria-hidden="true"></div>
    <CommanderVfxLayer
      v-if="previewStage"
      :commander-id="commanderId"
      :stage="previewStage"
      :exclusive="isExclusiveVfx"
      :tier="effectiveTier"
    />
    <slot />
  </div>
</template>

<style scoped>
.cmd-portrait-stage {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  background: var(--cmd-sec, #111c2d);
  transform: translateZ(0);
}
.cmd-portrait-stage__img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: var(--cmd-face-pos, 50% 28%);
  animation: cmd-stage-breathe 7s ease-in-out infinite alternate;
  will-change: transform;
}
.cmd-portrait-stage--full .cmd-portrait-stage__img {
  object-position: 50% 20%;
}
.cmd-portrait-stage__img--art-motion {
  animation: none;
  will-change: auto;
}
.cmd-portrait-stage.is-muted .cmd-portrait-stage__img {
  filter: saturate(0.68) brightness(0.84);
}
.cmd-portrait-stage.is-entering .cmd-portrait-stage__img {
  animation: cmd-stage-entrance 850ms cubic-bezier(0.18, 0.8, 0.25, 1) both;
}

.cmd-portrait-stage__vignette {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background: linear-gradient(0deg, rgb(7 14 26 / 68%), transparent 46%);
}
.cmd-portrait-stage__frame {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  border-radius: inherit;
  border: 1px solid rgb(148 163 184 / 22%);
}

/* Tier 1+ (Lv.5–9): 专属金属框 + 弱主题内光 */
.cmd-portrait-stage--tier-1 .cmd-portrait-stage__frame,
.cmd-portrait-stage--tier-2 .cmd-portrait-stage__frame,
.cmd-portrait-stage--tier-3 .cmd-portrait-stage__frame,
.cmd-portrait-stage--tier-4 .cmd-portrait-stage__frame,
.cmd-portrait-stage.is-active .cmd-portrait-stage__frame {
  border-color: color-mix(in srgb, var(--cmd-acc) 72%, transparent);
  box-shadow: inset 0 0 14px color-mix(in srgb, var(--cmd-pri) 34%, transparent);
}

/* Tier 2+ (Lv.10–14): 沿框扫光 + 3 颗上浮光尘 */
.cmd-portrait-stage__sweep,
.cmd-portrait-stage__halo,
.cmd-portrait-stage__halo-outer,
.cmd-portrait-stage__motes {
  position: absolute;
  pointer-events: none;
}
.cmd-portrait-stage__sweep {
  inset: -25% 0;
  z-index: 2;
  background: linear-gradient(108deg, transparent 42%, var(--cmd-acc) 49%, transparent 54%);
  opacity: 0;
}
.cmd-portrait-stage--tier-2 .cmd-portrait-stage__sweep,
.cmd-portrait-stage--tier-3 .cmd-portrait-stage__sweep,
.cmd-portrait-stage--tier-4 .cmd-portrait-stage__sweep {
  animation: cmd-stage-sweep 6s 1s ease-in-out infinite;
}

.cmd-portrait-stage__motes {
  inset: 0;
  z-index: 2;
}
.cmd-portrait-stage--tier-0 .cmd-portrait-stage__motes,
.cmd-portrait-stage--tier-1 .cmd-portrait-stage__motes {
  display: none;
}
.cmd-portrait-stage:not(.cmd-portrait-stage--tier-4) .cmd-portrait-stage__motes i:nth-child(n + 4) {
  display: none;
}
.cmd-portrait-stage__motes i {
  position: absolute;
  bottom: 10%;
  left: calc(8% + 12% * var(--n));
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--cmd-acc);
  box-shadow: 0 0 7px 1px var(--cmd-pri);
  opacity: 0;
  animation: cmd-stage-drift 4s calc(-0.6s * var(--n)) ease-out infinite;
}

/* Tier 3 (Lv.15–19): 4.8s 扩散环迹 */
.cmd-portrait-stage__halo {
  width: 47%;
  aspect-ratio: 1;
  right: -6%;
  top: -13%;
  z-index: 2;
  border: 1px solid var(--cmd-acc);
  border-radius: 50%;
  opacity: 0;
  box-shadow: 0 0 13px var(--cmd-pri);
}
.cmd-portrait-stage--tier-3 .cmd-portrait-stage__halo,
.cmd-portrait-stage--tier-4 .cmd-portrait-stage__halo {
  animation: cmd-stage-halo 4.8s ease-out infinite;
}

/* Tier 4 (Lv.20): 分层外环光晕 + 高亮双层描边 */
.cmd-portrait-stage__halo-outer {
  width: 68%;
  aspect-ratio: 1;
  left: -14%;
  bottom: -22%;
  z-index: 2;
  border: 1px dashed var(--cmd-acc);
  border-radius: 50%;
  opacity: 0;
  animation: cmd-stage-halo 6.2s 1.4s ease-out infinite;
}
.cmd-portrait-stage--tier-4 .cmd-portrait-stage__frame {
  border-width: 1.5px;
  border-color: var(--cmd-acc);
  box-shadow:
    inset 0 0 18px color-mix(in srgb, var(--cmd-pri) 42%, transparent),
    0 0 14px color-mix(in srgb, var(--cmd-acc) 28%, transparent);
}

@keyframes cmd-stage-breathe {
  from {
    transform: scale(1) translateY(0px);
  }
  to {
    transform: scale(1.028) translateY(1.5px);
  }
}
@keyframes cmd-stage-sweep {
  0%, 20% { transform: translateX(-100%); opacity: 0; }
  39% { opacity: 0.24; }
  65%, 100% { transform: translateX(100%); opacity: 0; }
}
@keyframes cmd-stage-halo {
  0% { transform: scale(0.75); opacity: 0.3; }
  100% { transform: scale(2); opacity: 0; }
}
@keyframes cmd-stage-drift {
  0% { transform: translate(0, 0); opacity: 0; }
  28% { opacity: 0.72; }
  100% { transform: translate(16px, -68px); opacity: 0; }
}
@keyframes cmd-stage-entrance {
  from { transform: translateX(5px) scale(1.09); }
  to { transform: scale(1) translateX(0); }
}

@media (prefers-reduced-motion: reduce) {
  .cmd-portrait-stage__img,
  .cmd-portrait-stage__sweep,
  .cmd-portrait-stage__halo,
  .cmd-portrait-stage__halo-outer,
  .cmd-portrait-stage__motes i {
    animation: none !important;
    transform: none !important;
  }
  .cmd-portrait-stage__sweep,
  .cmd-portrait-stage__halo,
  .cmd-portrait-stage__halo-outer {
    display: none;
  }
  .cmd-portrait-stage__motes i {
    opacity: 0.55;
  }
}
</style>
