<script setup lang="ts">
import { computed } from 'vue'
import { commanderSkillArt } from './commanderSkillArt'
import { commanderSkillVisual } from './commanderSkillVisuals'

const props = withDefaults(defineProps<{
  skillId: string
  order?: number
  speed?: number
  negated?: boolean
  entering?: boolean
}>(), { speed: 3 })
const visual = computed(() => commanderSkillVisual(props.skillId))
</script>

<template>
  <div
    v-if="visual"
    class="commander-skill-card"
    :class="{ 'is-entering': entering, 'is-negated': negated }"
    :style="{ '--skill-primary': visual.primary, '--skill-accent': visual.accent, '--skill-surface': visual.surface }"
    :aria-label="`${visual.name}，速阶 ${speed}${order ? '，连锁 ' + order : ''}${negated ? '，无效' : ''}`"
    data-testid="commander-skill-card"
    :data-skill-id="visual.id"
  >
    <div class="commander-skill-card__face">
      <img class="commander-skill-card__art" :src="commanderSkillArt[visual.id]" alt="" draggable="false" />
      <header><span>指挥官技能</span><b>{{ speed }}</b></header>
      <strong>{{ visual.name }}</strong>
      <span v-if="order" class="commander-skill-card__order">{{ order }}</span>
    </div>
    <span v-if="negated" class="commander-skill-card__negated">无效</span>
  </div>
</template>

<style scoped>
.commander-skill-card {
  position: relative;
  display: block;
  width: 100%;
  height: 100%;
  aspect-ratio: 2 / 3;
  container-type: inline-size;
  isolation: isolate;
  overflow: hidden;
  border-radius: inherit;
  color: var(--skill-accent);
  background: var(--skill-surface);
}
.commander-skill-card__face {
  box-sizing: border-box;
  position: absolute;
  inset: 0;
  border: 1px solid var(--skill-primary);
  border-radius: inherit;
  overflow: hidden;
  background: radial-gradient(at 50% 40%, var(--skill-primary), var(--skill-surface) 76%);
}
.commander-skill-card__art {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.commander-skill-card__face::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(#07101be8, transparent 24% 65%, #07101bea 100%);
  box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--skill-primary) 30%, transparent);
  pointer-events: none;
}
header {
  position: absolute;
  z-index: 1;
  inset: 4% 6% auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 3px;
  font-size: clamp(7px, 10cqw, 13px);
  font-weight: 700;
  line-height: 1.1;
  text-shadow: 0 1px 2px #03070d;
}
header b {
  padding: .12em .37em;
  border: 1px solid var(--skill-primary);
  border-radius: 3px;
  background: #08121dda;
}
header span { white-space: nowrap; }
strong {
  position: absolute;
  z-index: 1;
  inset: auto 4% 5%;
  color: #fff7ee;
  font-size: clamp(10px, 16cqw, 20px);
  text-align: center;
  line-height: 1.15;
  white-space: nowrap;
  text-shadow: 0 1px 2px #03070d, 0 0 6px var(--skill-surface);
}
.commander-skill-card__order {
  position: absolute;
  z-index: 1;
  left: 7%;
  bottom: 21%;
  color: #fff5d4;
  font: italic 700 clamp(10px, 18cqw, 21px)/1 Georgia, serif;
  text-shadow: 0 0 5px #08121c;
}
.is-negated .commander-skill-card__face { filter: grayscale(1) brightness(.72); }
.commander-skill-card__negated {
  position: absolute;
  z-index: 2;
  inset: 44% 0 auto;
  padding: .1em;
  transform: rotate(-9deg);
  background: #49212bea;
  border-block: 1px solid #e9a0aa;
  color: #ffdedc;
  text-align: center;
  font-size: clamp(10px, 16cqw, 20px);
  font-weight: 800;
}
.is-entering::after {
  content: '';
  position: absolute;
  z-index: 3;
  inset: 0;
  background: linear-gradient(132deg, transparent 18%, var(--skill-accent) 48%, transparent 71%);
  animation: skill-stack-flash 420ms ease-out both;
  pointer-events: none;
}
@keyframes skill-stack-flash {
  0% { opacity: .78; transform: translateX(-78%); }
  100% { opacity: 0; transform: translateX(80%); }
}
@media (prefers-reduced-motion: reduce) { .is-entering::after { display: none; } }
</style>
