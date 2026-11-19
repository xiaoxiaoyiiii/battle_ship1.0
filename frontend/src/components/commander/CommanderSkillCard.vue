<script setup lang="ts">
import { computed } from 'vue'
import CommanderSkillIcon from './CommanderSkillIcon.vue'
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
      <header><span>指挥官技能</span><b>{{ speed }}</b></header>
      <strong>{{ visual.name }}</strong>
      <span v-if="order" class="commander-skill-card__order">{{ order }}</span>
      <div class="commander-skill-card__mark"><CommanderSkillIcon :skill-id="skillId" /></div>
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
  display: grid;
  grid-template-rows: auto auto 1fr;
  gap: 6%;
  padding: 6% 7% 12%;
  border: 1px solid var(--skill-primary);
  border-radius: inherit;
  background:
    repeating-linear-gradient(141deg, transparent 0 22px, color-mix(in srgb, var(--skill-primary) 17%, transparent) 22px 23px),
    radial-gradient(ellipse at 50% 53%, color-mix(in srgb, var(--skill-primary) 31%, var(--skill-surface)), var(--skill-surface) 73%);
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 3px;
  font-size: clamp(7px, 9.4cqw, 13px);
  line-height: 1.1;
}
header b { padding: .18em .42em; border: 1px solid var(--skill-primary); border-radius: 4px; }
header span { white-space: nowrap; }
.commander-skill-card__mark { display: grid; place-items: center; min-height: 0; }
.commander-skill-card__mark .commander-skill-icon {
  width: 78%;
  height: auto;
  max-height: 90%;
  filter: drop-shadow(0 0 6px var(--skill-primary));
}
strong { font-size: clamp(10px, 15cqw, 20px); text-align: center; line-height: 1.15; }
.commander-skill-card__order {
  position: absolute;
  left: 8%;
  bottom: 8%;
  color: #fff5d4;
  font: italic 700 clamp(10px, 18cqw, 21px)/1 Georgia, serif;
  text-shadow: 0 0 5px #08121c;
}
.is-negated .commander-skill-card__face { filter: grayscale(1) brightness(.72); }
.commander-skill-card__negated {
  position: absolute;
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
