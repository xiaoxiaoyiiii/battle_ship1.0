<script setup lang="ts">
import { computed } from 'vue'
import { commanderPalette } from '../../stores/commanders'

export type CommanderVfxStage =
  | ''
  | 'resolve'
  | 'chain_enter'
  | 'reveal'
  | 'negated'
  | 'intro'
  | 'victory'

const props = withDefaults(
  defineProps<{
    commanderId: string
    stage: CommanderVfxStage
    exclusive?: boolean
    negatedBy?: string | null
    tier?: number
  }>(),
  {
    exclusive: true,
    negatedBy: null,
    tier: 4,
  },
)

const palette = computed(() => commanderPalette(props.commanderId))
const isDimmed = computed(() => !props.exclusive && props.tier < 3)

const stageBadgeText = computed(() => {
  if (props.stage === 'negated') {
    return props.negatedBy ? `被${props.negatedBy}无效` : '无效'
  }
  if (props.stage === 'chain_enter') {
    return props.commanderId === 'tieanchor'
      ? '护幕响应 · 速阶 3'
      : props.commanderId === 'guihang'
        ? '星盘启链 · 速阶 3'
        : '入链响应'
  }
  if (props.stage === 'reveal') return '延迟锁定揭晓'
  if (props.stage === 'intro') {
    return props.tier >= 4 ? '终阶统帅登场' : props.tier >= 3 ? '强化登场' : '出击亮相'
  }
  if (props.stage === 'victory') return '凯旋致意'
  if (props.stage === 'resolve') {
    if (props.commanderId === 'chichao') return '火力统制 · 齐射'
    if (props.commanderId === 'qingtong') return '声呐偏移 · 待揭晓'
    if (props.commanderId === 'tieanchor') return '无畏护幕合拢'
    if (props.commanderId === 'guihang') return '双幻牌入阵'
    return '技能生效'
  }
  return ''
})
</script>

<template>
  <div
    v-if="stage"
    class="cmd-vfx"
    :class="[
      `cmd-vfx--${commanderId}`,
      `cmd-vfx--stage-${stage}`,
      { 'is-subdued': isDimmed, 'is-tier-4': tier >= 4, 'is-tier-3': tier === 3 },
    ]"
    :style="{
      '--cmd-pri': palette.primary,
      '--cmd-acc': palette.accent,
      '--cmd-glow': palette.glow,
    }"
    aria-hidden="true"
  >
    <!-- 赤潮：六道 -18deg 火控光迹（未及 Lv.15 或未装独占特效时呈现 3 道基础光迹） -->
    <template v-if="commanderId === 'chichao'">
      <span
        v-for="idx in (stage === 'resolve' && isDimmed ? 3 : 6)"
        :key="'laser-' + idx"
        class="cmd-vfx__mark cmd-vfx__laser"
        :style="{ '--i': idx - 1 }"
      ></span>
      <span v-if="stage === 'resolve' || stage === 'intro' || stage === 'victory'" class="cmd-vfx__visor-flash"></span>
      <span v-if="stage === 'intro' || stage === 'victory'" class="cmd-vfx__crest cmd-vfx__crest--chichao"></span>
    </template>

    <!-- 青瞳：resolve 仅发声呐脉冲；reveal 展开双环 + 虚线准星 -->
    <template v-else-if="commanderId === 'qingtong'">
      <span
        v-for="idx in 3"
        :key="'sonar-' + idx"
        class="cmd-vfx__mark cmd-vfx__sonar"
        :style="{ '--i': idx - 1 }"
      ></span>
      <span v-if="stage === 'reveal'" class="cmd-vfx__reticle"></span>
      <span v-if="stage === 'intro' || stage === 'victory'" class="cmd-vfx__crest cmd-vfx__crest--qingtong"></span>
    </template>

    <!-- 铁锚：chain_enter 仅护幕轮廓；resolve 三块六边形蜂窝盾依次合拢 -->
    <template v-else-if="commanderId === 'tieanchor'">
      <span
        v-for="idx in 3"
        :key="'hex-' + idx"
        class="cmd-vfx__mark cmd-vfx__hex"
        :class="{ 'is-outline': stage === 'chain_enter' }"
        :style="{ '--i': idx - 1 }"
      ></span>
      <span v-if="stage === 'intro' || stage === 'victory'" class="cmd-vfx__crest cmd-vfx__crest--tieanchor"></span>
    </template>

    <!-- 归航：chain_enter 亮星盘；resolve 两张无牌面金色幻牌依次收进窗内 -->
    <template v-else-if="commanderId === 'guihang'">
      <span class="cmd-vfx__mark cmd-vfx__astrolabe"></span>
      <template v-if="stage === 'resolve'">
        <span
          v-for="idx in 2"
          :key="'phantom-' + idx"
          class="cmd-vfx__mark cmd-vfx__phantom"
          :style="{ '--i': idx - 1 }"
        ></span>
      </template>
      <span v-if="stage === 'intro' || stage === 'victory'" class="cmd-vfx__crest cmd-vfx__crest--guihang"></span>
    </template>

    <span
      v-if="stage === 'negated'"
      class="cmd-vfx__negated-stamp"
      data-testid="commander-vfx-negated-stamp"
    >{{ stageBadgeText }}</span>
    <span v-else-if="stageBadgeText" class="cmd-vfx__stage-badge">
      {{ stageBadgeText }}
    </span>
  </div>
</template>

<style scoped>
.cmd-vfx {
  position: absolute;
  inset: 0;
  z-index: 4;
  overflow: hidden;
  pointer-events: none;
  opacity: 0;
  animation: vfx-window 820ms ease-out both;
}
.cmd-vfx--stage-chain_enter,
.cmd-vfx--stage-negated {
  animation-duration: 440ms;
}
.cmd-vfx--stage-intro {
  animation-duration: 1000ms;
}
.cmd-vfx--stage-victory {
  animation-duration: 1100ms;
}
.cmd-vfx--stage-negated {
  filter: grayscale(1);
  background: rgb(15 23 42 / 46%);
}
.cmd-vfx--stage-negated .cmd-vfx__mark,
.cmd-vfx--stage-negated .cmd-vfx__reticle,
.cmd-vfx--stage-negated .cmd-vfx__visor-flash {
  display: none;
}
.cmd-vfx.is-subdued {
  filter: brightness(0.76);
}
.cmd-vfx__mark {
  position: absolute;
  display: block;
}

/* 赤潮：六道 -18deg 火控光迹（首束 120ms，逐束 +30ms） */
.cmd-vfx__laser {
  top: calc(16% + 11% * var(--i));
  inset-inline: -22%;
  height: 2.5px;
  rotate: -18deg;
  background: linear-gradient(90deg, transparent 8%, var(--cmd-acc) 52%, transparent 94%);
  box-shadow: 0 0 11px var(--cmd-pri);
  opacity: 0;
}
.cmd-vfx--stage-resolve .cmd-vfx__laser {
  animation: vfx-volley 520ms calc(120ms + 30ms * var(--i)) cubic-bezier(0.18, 0.8, 0.25, 1) both;
}
.cmd-vfx__visor-flash {
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 52% 34%, color-mix(in srgb, var(--cmd-pri) 42%, transparent), transparent 60%);
  opacity: 0;
  animation: vfx-visor-glow 660ms 120ms ease-out both;
}

/* 青瞳：声呐波纹 + reveal 揭晓双层环与抽象准星 */
.cmd-vfx__sonar {
  inset: 14% 22%;
  border: 2px solid var(--cmd-acc);
  border-radius: 50%;
  box-shadow: 0 0 12px var(--cmd-pri);
  transform: scale(calc(0.45 + 0.22 * var(--i)));
  opacity: 0;
}
.cmd-vfx--stage-resolve .cmd-vfx__sonar,
.cmd-vfx--stage-reveal .cmd-vfx__sonar {
  animation: vfx-sonar 650ms calc(55ms * var(--i)) ease-out both;
}
.cmd-vfx__reticle {
  position: absolute;
  inset: 22% 24%;
  border: 1.8px dashed var(--cmd-acc);
  border-radius: 6px;
  box-shadow: inset 0 0 12px color-mix(in srgb, var(--cmd-pri) 45%, transparent);
  opacity: 0;
  animation: vfx-reticle 680ms 90ms ease-out both;
}
.cmd-vfx__reticle::before,
.cmd-vfx__reticle::after {
  content: '';
  position: absolute;
  background: var(--cmd-acc);
}
.cmd-vfx__reticle::before {
  left: 50%;
  top: -6px;
  bottom: -6px;
  width: 1.5px;
  transform: translateX(-50%);
}
.cmd-vfx__reticle::after {
  top: 50%;
  left: -6px;
  right: -6px;
  height: 1.5px;
  transform: translateY(-50%);
}

/* 铁锚：chain_enter 护幕轮廓；resolve 三块蜂窝盾 200-620ms 合拢 */
.cmd-vfx__hex {
  inset-block: 22%;
  width: 42%;
  left: calc(7% + var(--i) * 22%);
  clip-path: polygon(25% 0, 75% 0, 100% 50%, 75% 100%, 25% 100%, 0 50%);
  background: color-mix(in srgb, var(--cmd-pri) 52%, transparent);
  opacity: 0;
}
.cmd-vfx__hex::before {
  content: '';
  position: absolute;
  inset: 6px;
  clip-path: inherit;
  background: rgb(173 242 255 / 24%);
}
.cmd-vfx__hex.is-outline {
  background: rgb(87 166 255 / 22%);
  border: 1.5px solid var(--cmd-acc);
  animation: vfx-guard-outline 360ms ease-out both;
}
.cmd-vfx--stage-resolve .cmd-vfx__hex {
  animation: vfx-guard 420ms calc(160ms + 70ms * var(--i)) cubic-bezier(0.16, 0.8, 0.25, 1) both;
}

/* 归航：chain_enter 星盘；resolve 双无牌面金色幻牌依次入窗 */
.cmd-vfx__astrolabe {
  inset: 14% 24%;
  border: 4px double var(--cmd-acc);
  border-radius: 50%;
  box-shadow: 0 0 14px var(--cmd-pri);
  opacity: 0;
  animation: vfx-astrolabe 680ms ease-out both;
}
.cmd-vfx--stage-chain_enter .cmd-vfx__astrolabe {
  animation-duration: 380ms;
}
.cmd-vfx__phantom {
  width: 22%;
  aspect-ratio: 3 / 4;
  left: calc(36% + var(--i) * 16%);
  top: 22%;
  border-radius: 5px;
  border: 1.5px solid var(--cmd-acc);
  background: linear-gradient(155deg, rgb(254 240 138 / 55%), rgb(129 84 26 / 82%));
  box-shadow: 0 4px 14px color-mix(in srgb, var(--cmd-pri) 55%, transparent);
  rotate: calc(-14deg + 22deg * var(--i));
  opacity: 0;
  animation: vfx-deal 520ms calc(110ms + 90ms * var(--i)) cubic-bezier(0.2, 0.85, 0.3, 1) both;
}

/* 登场 / 胜利专属纹章层 */
.cmd-vfx__crest {
  position: absolute;
  inset: 10%;
  border-radius: 12px;
  border: 1.5px solid var(--cmd-acc);
  box-shadow: inset 0 0 22px color-mix(in srgb, var(--cmd-pri) 36%, transparent);
  opacity: 0;
  animation: vfx-crest-pop 860ms ease-out both;
}
.cmd-vfx__crest--qingtong,
.cmd-vfx__crest--guihang {
  border-radius: 50%;
  border-style: dashed;
}

/* 状态角标 */
.cmd-vfx__negated-stamp {
  position: absolute;
  right: 8px;
  bottom: 8px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #20232b;
  border: 1px solid rgb(248 113 113 / 75%);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}
.cmd-vfx__stage-badge {
  position: absolute;
  left: 8px;
  bottom: 8px;
  max-width: calc(100% - 16px);
  padding: 2px 7px;
  border-radius: 999px;
  background: rgb(6 14 26 / 86%);
  border: 1px solid var(--cmd-acc);
  color: var(--cmd-acc);
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@keyframes vfx-window {
  0%, 100% { opacity: 0; }
  14%, 78% { opacity: 1; }
}
@keyframes vfx-volley {
  0% { transform: translate(-72%, 14%); opacity: 0; }
  45% { opacity: 1; }
  100% { transform: translate(34%, -6%); opacity: 0.16; }
}
@keyframes vfx-visor-glow {
  0%, 100% { opacity: 0; }
  35% { opacity: 0.85; }
}
@keyframes vfx-sonar {
  0% { transform: scale(0.25); opacity: 0; }
  34% { opacity: 1; }
  100% { transform: scale(1.65); opacity: 0.14; }
}
@keyframes vfx-reticle {
  0% { transform: scale(1.32) rotate(-14deg); opacity: 0; }
  40% { opacity: 0.95; }
  100% { transform: scale(0.95) rotate(0deg); opacity: 0.28; }
}
@keyframes vfx-guard-outline {
  0% { transform: scale(0.75); opacity: 0; }
  50% { opacity: 0.85; }
  100% { transform: scale(1); opacity: 0.55; }
}
@keyframes vfx-guard {
  0% { transform: scale(0.45); opacity: 0; }
  65% { transform: scale(1.04); opacity: 1; }
  100% { transform: scale(1); opacity: 0.85; }
}
@keyframes vfx-astrolabe {
  0% { transform: scale(0.55) rotate(-35deg); opacity: 0; }
  45% { opacity: 0.92; }
  100% { transform: scale(1.05) rotate(22deg); opacity: 0.25; }
}
@keyframes vfx-deal {
  0% { transform: translate(-12px, 34px) scale(0.84); opacity: 0; }
  75% { transform: translate(0, -3px) scale(1.03); opacity: 1; }
  100% { transform: translate(0, 0) scale(1); opacity: 0.9; }
}
@keyframes vfx-crest-pop {
  0% { transform: scale(0.84); opacity: 0; }
  35% { opacity: 0.88; }
  100% { transform: scale(1.05); opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .cmd-vfx,
  .cmd-vfx__mark,
  .cmd-vfx__visor-flash,
  .cmd-vfx__reticle,
  .cmd-vfx__crest {
    animation: none !important;
    opacity: 0.9 !important;
    transform: none !important;
  }
}
</style>
