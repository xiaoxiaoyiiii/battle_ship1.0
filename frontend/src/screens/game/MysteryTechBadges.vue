<script setup lang="ts">
import { computed } from 'vue'
import { parseTechnology, tierLabel } from './mysteryTechView'
import './mysteryTech.css'

const props = defineProps<{
  effects: unknown
  side?: string
  testid?: string
}>()

interface Chip {
  key: string
  name: string
  description: string
  tier: 'quality' | 'legendary' | 'mythic'
  timing: string
}

const chips = computed<Chip[]>(() => {
  if (!Array.isArray(props.effects)) return []
  const rows: Chip[] = []
  for (const item of props.effects) {
    if (!item || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const key = String(record.key ?? '')
    if (!key.startsWith('mystery_tech:')) continue
    const technology = parseTechnology(record, String(record.tech_id ?? key.slice('mystery_tech:'.length)))
    rows.push({
      key,
      name: String(record.label ?? record.name ?? technology.name),
      description: String(record.description ?? technology.description),
      tier: technology.tier,
      timing: technology.timing,
    })
  }
  return rows
})
</script>

<template>
  <div v-if="chips.length" class="mt-tech-rack" :data-testid="testid || (side ? 'mystery-tech-badges-' + side : 'mystery-tech-badges')" :aria-label="side === 'opponent' ? '对方已公开神秘科技' : side === 'self' ? '己方已公开神秘科技' : '已公开神秘科技'">
    <span
      v-for="chip in chips"
      :key="chip.key"
      class="mt-tech-chip"
      :class="'is-' + chip.tier"
      :data-testid="'mystery-tech-badge-' + chip.key"
      :title="chip.description"
    >
      {{ tierLabel(chip.tier) }} · {{ chip.name }}
    </span>
  </div>
</template>
