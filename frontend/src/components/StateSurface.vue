<script setup lang="ts">
/**
 * The shared loading / empty / error surface (spec story 90-91, ticket #42).
 *
 * A single component so the three states never blur together: loading says
 * "载入中", empty says what is missing, error names the reason and always offers
 * a retry. Screens keep their own testids inside the slots.
 */
withDefaults(
  defineProps<{
    state: 'loading' | 'ready' | 'empty' | 'error'
    loadingText?: string
    emptyText?: string
    errorText?: string
    retryLabel?: string
  }>(),
  {
    loadingText: '载入中…',
    emptyText: '暂无内容。',
    errorText: '读取失败，请重试。',
    retryLabel: '重试',
  },
)

const emit = defineEmits<{ (event: 'retry'): void }>()
</script>

<template>
  <div class="state-surface" data-testid="state-surface" :data-state="state">
    <slot v-if="state === 'ready'" />
    <div v-else-if="state === 'loading'" class="state-surface__loading" role="status" aria-live="polite">
      <span class="state-surface__skeleton" aria-hidden="true"></span>
      <span class="state-surface__label">{{ loadingText }}</span>
    </div>
    <div v-else-if="state === 'empty'" class="state-surface__empty">
      <slot name="empty">
        <p class="state-surface__label">{{ emptyText }}</p>
      </slot>
    </div>
    <div v-else class="state-surface__error" role="alert">
      <slot name="error">
        <p class="state-surface__label">{{ errorText }}</p>
      </slot>
      <button
        type="button"
        class="button state-surface__retry"
        data-testid="state-surface-retry"
        @click="emit('retry')"
      >
        {{ retryLabel }}
      </button>
    </div>
  </div>
</template>
