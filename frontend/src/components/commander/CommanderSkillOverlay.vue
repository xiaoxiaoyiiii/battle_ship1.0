<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  commanderPalette,
  commanderSkillVfxForEquipped,
  commanderTierOf,
  useCommandersStore,
  type CommanderEquippedLike,
  type CommanderSkillCastEvent,
} from '../../stores/commanders'
import CommanderVfxLayer, { type CommanderVfxStage } from './CommanderVfxLayer.vue'
import CommanderSkillIcon from './CommanderSkillIcon.vue'

const props = withDefaults(
  defineProps<{
    side?: 'self' | 'opponent'
    playerId?: string
    cosmetics?: CommanderEquippedLike | null
    commanderLevel?: number
  }>(),
  {
    side: 'self',
    playerId: '',
    cosmetics: null,
    commanderLevel: 1,
  },
)

const store = useCommandersStore()
const activeCutin = ref<CommanderSkillCastEvent | null>(null)
const activeSeq = ref(0)
let timer: ReturnType<typeof setTimeout> | null = null

function matchesSide(ev: CommanderSkillCastEvent): boolean {
  if (!props.playerId) return props.side === 'self'
  if (ev.player_id) return ev.player_id === props.playerId
  return props.side === 'self'
}

watch(
  () => store.lastSkillEvent,
  (ev) => {
    if (!ev || !matchesSide(ev)) return
    if (!store.isSkillEventFresh(ev)) return
    store.consumeSkillEvent(ev.id)

    activeCutin.value = ev
    activeSeq.value += 1
    if (timer !== null) clearTimeout(timer)
    const durationMs =
      ev.negated || ev.stage === 'negated' || ev.stage === 'chain_enter' ? 440 : 820
    timer = setTimeout(() => {
      activeCutin.value = null
    }, durationMs)
  },
  { flush: 'sync' },
)

onBeforeUnmount(() => {
  if (timer !== null) clearTimeout(timer)
})

const effectiveStage = computed<CommanderVfxStage>(() => {
  const ev = activeCutin.value
  if (!ev) return ''
  if (ev.negated || ev.stage === 'negated') return 'negated'
  return ev.stage
})

const isExclusive = computed(() => {
  const ev = activeCutin.value
  if (!ev) return false
  const lvl = ev.commander_level || props.commanderLevel || 1
  return commanderSkillVfxForEquipped(lvl, props.cosmetics) === 'exclusive'
})

const palette = computed(() =>
  commanderPalette(activeCutin.value?.commander_id || 'chichao'),
)
</script>

<template>
  <div
    v-if="activeCutin && effectiveStage"
    :key="activeCutin.id + '-' + activeSeq"
    class="cmd-corner-cutin"
    :class="[
      `cmd-corner-cutin--${props.side}`,
      `cmd-corner-cutin--stage-${effectiveStage}`,
      { 'is-negated': activeCutin.negated || effectiveStage === 'negated' },
    ]"
    :style="{
      '--cmd-pri': palette.primary,
      '--cmd-acc': palette.accent,
      '--cmd-glow': palette.glow,
    }"
    data-testid="commander-skill-cutin"
    :data-side="props.side"
    :data-commander="activeCutin.commander_id"
    :data-stage="effectiveStage"
    role="status"
    aria-live="polite"
  >
    <CommanderVfxLayer
      :commander-id="activeCutin.commander_id"
      :stage="effectiveStage"
      :exclusive="isExclusive"
      :negated-by="activeCutin.negated_by"
      :tier="commanderTierOf(activeCutin.commander_level || 1)"
    />
    <span class="cmd-corner-cutin__badge" aria-hidden="true">
      <CommanderSkillIcon :skill-id="activeCutin.skill_id" />
      <b>{{ activeCutin.skill_name }}</b>
      <small v-if="activeCutin.draw_count">摸牌 +{{ activeCutin.draw_count }}</small>
      <small v-else-if="activeCutin.success === false && effectiveStage !== 'negated'">未生效</small>
    </span>
    <span class="sr-only">
      {{ activeCutin.commander_name }} 【{{ activeCutin.skill_name }}】
      {{ effectiveStage === 'negated' ? `被 ${activeCutin.negated_by || '对手'} 无效化` : effectiveStage === 'chain_enter' ? '入链响应' : effectiveStage === 'reveal' ? '揭晓坐标' : activeCutin.success === false ? '未生效' : '发动成功' }}
    </span>
  </div>
</template>

<style scoped>
.cmd-corner-cutin {
  position: absolute;
  inset: 0;
  z-index: 6;
  overflow: hidden;
  border-radius: inherit;
  pointer-events: none;
  container-type: inline-size;
}
.cmd-corner-cutin__badge {
  position: absolute;
  bottom: 5px;
  left: 5px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: calc(100% - 10px);
  padding: 4px 7px;
  border: 1px solid var(--cmd-pri);
  border-radius: 6px;
  color: var(--cmd-acc);
  background: #101a2ce8;
  font-size: 12px;
  white-space: nowrap;
}
.cmd-corner-cutin__badge .commander-skill-icon { width: 21px; height: 21px; }
.cmd-corner-cutin__badge small { color: #fff2cf; }
@container (max-width: 90px) {
  .cmd-corner-cutin__badge { inset: 2px; justify-content: center; padding: 0; }
  .cmd-corner-cutin__badge :is(b, small) { display: none; }
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}
</style>
