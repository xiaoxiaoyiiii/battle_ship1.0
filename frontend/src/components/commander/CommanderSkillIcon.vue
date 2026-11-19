<script setup lang="ts">
import { computed } from 'vue'
import { commanderSkillVisual } from './commanderSkillVisuals'

const props = defineProps<{ skillId: string }>()
const visual = computed(() => commanderSkillVisual(props.skillId))
</script>

<template>
  <svg
    v-if="visual"
    class="commander-skill-icon"
    :data-skill-id="visual.id"
    viewBox="0 0 64 64"
    fill="none"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="visual.path" stroke="currentColor" stroke-width="3.25" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
</template>

<style scoped>
.commander-skill-icon { display: inline-block; inline-size: 1.35em; block-size: 1.35em; flex: none; vertical-align: middle; }
</style>
