<script setup lang="ts">
import type { CellVisual } from './cellPresentation'
defineProps<{ kind: CellVisual }>()
</script>
<template>
  <svg class="cell__art" viewBox="0 0 32 32" fill="none" aria-hidden="true" focusable="false">
    <g v-if="kind === 'miss'" stroke="currentColor">
      <ellipse cx="16" cy="25" rx="12" ry="3" opacity=".32" stroke-width="1.5" />
      <ellipse cx="16" cy="25" rx="8" ry="1.8" opacity=".2" />
      <circle cx="16" cy="13" r="8" stroke-width="2.3" />
    </g>
    <g v-else-if="kind === 'shielded' || kind === 'shield-blocked'">
      <path d="M16 3 28 8 26 19Q24 25 16 29 8 25 6 19L4 8Z" fill="currentColor" fill-opacity=".15" stroke="currentColor" stroke-width="2.3" />
      <path v-if="kind === 'shield-blocked'" d="m18 4-4 9 6 2-7 14m8-22 3 3m0-4 3 1" stroke="currentColor" stroke-width="2.7" stroke-linejoin="round" />
      <path v-else d="M8 18h16l-4 5H12Zm5-5h7v5h-7Zm3-4h2v4h-2Z" fill="currentColor" />
    </g>
    <g v-else-if="kind === 'trap'" stroke="currentColor" stroke-width="2.3" stroke-linejoin="round">
      <path d="m16 4 13 23H3Z" fill="currentColor" fill-opacity=".1" />
      <path d="m16 12 4 5-4 5-4-5Z" fill="currentColor" stroke="none" />
    </g>
    <g v-else-if="kind === 'ship-hit'">
      <path d="M2 19h28l-6 8H8Zm9-9h11v9H11Zm4-7h3v7h-3Z" fill="currentColor" opacity=".24" />
      <path d="m7 6 19 20M26 6 7 26" stroke="currentColor" stroke-width="4.4" />
    </g>
    <g v-else-if="kind === 'revived'" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M16 4v24M4 16h24" opacity=".9" />
      <path d="m10 9 6-5 6 5M10 23l6 5 6-5" opacity=".45" />
    </g>
    <path v-else-if="kind === 'ship'" d="M2 19h28l-6 8H8Zm9-9h11v9H11Zm4-7h3v7h-3Z" fill="currentColor" />
  </svg>
</template>
