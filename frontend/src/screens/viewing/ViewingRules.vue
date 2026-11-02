<script setup lang="ts">
import type { ViewFrame } from './types'
defineProps<{ frame: ViewFrame }>()
</script>
<template>
  <details class="view-rules" data-testid="viewing-rules">
    <summary>本局规则 <span>{{ Array.isArray(frame.rules.entries) && frame.rules.entries.length ? frame.rules.entries.length + ' 条突变' : '标准对局' }}</span></summary>
    <div class="view-rules__body">
      <p v-if="!Array.isArray(frame.rules.entries) || !frame.rules.entries.length">本局没有突变词条。</p>
      <p v-for="entry in (frame.rules.entries as Array<{id: string; name: string; description: string}>)" :key="entry.id"><b>{{ entry.name }}</b><span>{{ entry.description }}</span></p>
      <p v-if="frame.context.storm_active"><b>暴雨已生效</b></p>
      <p v-if="Number(frame.rules.starting_ship_cap)">起始舰数 {{ frame.rules.starting_ship_cap }}</p>
      <p v-if="Array.isArray(frame.rules.banned_names) && frame.rules.banned_names.length">本局 Ban：{{ frame.rules.banned_names.join('、') }}</p>
    </div>
  </details>
</template>
