<script setup lang="ts">
import type { MutationEntry } from '../stores/mutations'
defineProps<{ entries: MutationEntry[] }>()
</script>

<template>
  <ul class="mutation-list">
    <li v-for="entry in entries" :key="entry.id">
      <b>{{ entry.name }}</b>
      <p>{{ entry.description }}</p>
    </li>
  </ul>
</template>

<style scoped>
.mutation-list { display: grid; gap: 10px; margin: 12px 0; padding: 0; list-style: none; }
.mutation-list li { min-width: 0; border-left: 2px solid var(--role-action); padding-left: 10px; }
.mutation-list b { color: var(--text-primary); font-size: 14px; }
.mutation-list p { margin: 4px 0 0; color: var(--text-secondary); font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
</style>
