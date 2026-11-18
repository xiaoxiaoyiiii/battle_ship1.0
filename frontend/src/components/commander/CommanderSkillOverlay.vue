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
    <span class="sr-only">
      {{ activeCutin.commander_name }} 【{{ activeCutin.skill_name }}】
      {{ effectiveStage === 'negated' ? `被 ${activeCutin.negated_by || '对手'} 无效化` : effectiveStage === 'chain_enter' ? '入链响应' : effectiveStage === 'reveal' ? '揭晓坐标' : '发动成功' }}
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
