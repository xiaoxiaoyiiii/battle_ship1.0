<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import {
  commanderPortraitUrl,
  commanderTierOf,
  useCommandersStore,
  type CommanderSkillCastEvent,
} from '../../stores/commanders'

const store = useCommandersStore()
const activeCutin = ref<CommanderSkillCastEvent | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null

const PALETTE: Record<string, { pri: string; acc: string }> = {
  chichao: { pri: '#e84855', acc: '#ff9e7d' },
  qingtong: { pri: '#4ea8de', acc: '#9be7ff' },
  tieanchor: { pri: '#3b76f6', acc: '#7dd3fc' },
  guihang: { pri: '#eab354', acc: '#fef08a' },
}

watch(
  () => store.lastSkillEvent,
  (ev) => {
    if (!ev) return
    activeCutin.value = ev
    if (timer !== null) clearTimeout(timer)
    timer = setTimeout(() => {
      activeCutin.value = null
    }, 2000)
  },
)

onBeforeUnmount(() => {
  if (timer !== null) clearTimeout(timer)
})

function stageText(ev: CommanderSkillCastEvent): string {
  if (ev.stage === 'negated') return `被 ${ev.negated_by || '对手'} 无效化`
  if (ev.stage === 'reveal') return '延迟锁定坐标揭晓！'
  if (ev.stage === 'chain_enter') return '速阶三连锁响应 · 发动！'
  return '指挥官技能 · 展开！'
}
</script>

<template>
  <Transition name="cmd-cutin">
    <div
      v-if="activeCutin"
      class="cmd-cutin"
      :class="[
        'cmd-cutin--tier-' + commanderTierOf(activeCutin.commander_level),
        { 'is-negated': activeCutin.negated },
      ]"
      :style="{
        '--cmd-pri': (PALETTE[activeCutin.commander_id] || PALETTE.chichao).pri,
        '--cmd-acc': (PALETTE[activeCutin.commander_id] || PALETTE.chichao).acc,
      }"
      data-testid="commander-skill-cutin"
      role="status"
      aria-live="polite"
    >
      <div class="cmd-cutin__banner">
        <img
          class="cmd-cutin__portrait"
          :src="commanderPortraitUrl(activeCutin.commander_id, activeCutin.commander_level >= 15 ? 'ultimate' : activeCutin.commander_level >= 10 ? 'ascended' : 'base')"
          :alt="activeCutin.commander_name"
        />
        <div class="cmd-cutin__copy">
          <small class="cmd-cutin__eyebrow">{{ activeCutin.commander_name }} · Lv.{{ activeCutin.commander_level }}</small>
          <strong class="cmd-cutin__skill">【{{ activeCutin.skill_name }}】</strong>
          <span class="cmd-cutin__stage">{{ stageText(activeCutin) }}</span>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.cmd-cutin {
  position: fixed;
  inset: 76px 0 auto 0;
  z-index: 330;
  display: flex;
  justify-content: center;
  pointer-events: none;
  padding: 0 16px;
}
.cmd-cutin__banner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 22px 10px 12px;
  border-radius: 18px;
  border: 1.5px solid var(--cmd-acc);
  background: linear-gradient(120deg, color-mix(in srgb, var(--cmd-pri) 26%, #091324), rgb(7 14 26 / 94%));
  box-shadow: 0 14px 38px rgb(0 0 0 / 50%), 0 0 28px color-mix(in srgb, var(--cmd-pri) 36%, transparent);
}
.cmd-cutin--tier-3 .cmd-cutin__banner,
.cmd-cutin--tier-4 .cmd-cutin__banner {
  border-width: 2px;
  box-shadow: 0 16px 46px rgb(0 0 0 / 55%), 0 0 42px color-mix(in srgb, var(--cmd-acc) 48%, transparent);
}
.cmd-cutin.is-negated .cmd-cutin__banner {
  filter: grayscale(0.45);
  border-color: #f87171;
}
.cmd-cutin__portrait {
  width: 56px;
  height: 72px;
  border-radius: 10px;
  border: 1px solid var(--cmd-acc);
  object-fit: cover;
}
.cmd-cutin__copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cmd-cutin__eyebrow {
  font-size: 11px;
  color: var(--cmd-acc);
  letter-spacing: 0.08em;
}
.cmd-cutin__skill {
  font-size: 18px;
  color: #ffffff;
}
.cmd-cutin__stage {
  font-size: 12px;
  color: #dcebf7;
}
.cmd-cutin-enter-active,
.cmd-cutin-leave-active {
  transition: opacity 0.28s ease, transform 0.28s ease;
}
.cmd-cutin-enter-from {
  opacity: 0;
  transform: translateY(-14px) scale(0.95);
}
.cmd-cutin-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(0.98);
}
</style>
