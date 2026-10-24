<script setup lang="ts">
import { useUiStore } from '../stores/ui'

/**
 * One notice queue for the whole app (spec story 87-89, ticket #42).
 *
 * Results of every action land here: the store dedupes the same code for three
 * seconds, positions the notice in one place, and the container is an
 * aria-live region that never takes focus. Failures carry the reason plus the
 * next step instead of a raw technical string.
 */
const ui = useUiStore()
</script>

<template>
  <Teleport to="body">
    <div
      class="app-toasts"
      data-testid="toast-host"
      role="status"
      aria-live="polite"
      aria-atomic="false"
      :style="{ zIndex: 'var(--z-toast)' }"
    >
      <article
        v-for="notice in ui.notices"
        :key="notice.id"
        class="app-toast"
        :class="'app-toast--' + notice.tone"
        data-testid="toast-item"
        :data-code="notice.code"
        :style="{ '--toast-duration': notice.ttl + 'ms' }"
      >
        <p class="app-toast__message">{{ notice.message }}</p>
        <p v-if="notice.next" class="app-toast__next">{{ notice.next }}</p>
        <button
          type="button"
          class="app-toast__dismiss"
          data-testid="toast-dismiss"
          aria-label="关闭提示"
          @click="ui.dismissNotice(notice.id)"
        >
          ×
        </button>
        <span class="app-toast__progress" data-testid="toast-progress" aria-hidden="true"></span>
      </article>
    </div>
  </Teleport>
</template>
