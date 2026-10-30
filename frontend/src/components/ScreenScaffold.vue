<script setup lang="ts">
import { computed } from 'vue'

/**
 * Shared placeholder frame for the eleven shell screens (ticket #21).
 * Business UI replaces the inner content in #22–#28; the selector contract
 * (section[data-testid="screen-<name>"] plus `<name>-*` for interactive
 * children) is what the external tools bind to.
 */
const props = defineProps<{
  screen: string
  title: string
  eyebrow?: string
  hint?: string
}>()

const headingId = computed(() => `screen-${props.screen}-title`)
</script>

<template>
  <section
    class="screen"
    :data-screen="screen"
    :data-testid="'screen-' + screen"
    :aria-labelledby="headingId"
  >
    <header class="screen__header">
      <p class="screen__eyebrow">{{ eyebrow || 'P3 · 应用壳占位' }}</p>
      <h1 :id="headingId" class="screen__title">{{ title }}</h1>
      <p v-if="hint" class="screen__hint">{{ hint }}</p>
    </header>

    <div class="screen__body">
      <slot />
    </div>

    <footer class="screen__contract">
      <span>选择器契约</span>
      <code>data-testid="screen-{{ screen }}"</code>
      <code>{{ screen }}-*</code>
    </footer>
  </section>
</template>
