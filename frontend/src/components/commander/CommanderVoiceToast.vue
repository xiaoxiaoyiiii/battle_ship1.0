<script setup lang="ts">
import { computed } from 'vue'
import { commanderAvatarUrl, useCommandersStore } from '../../stores/commanders'

const store = useCommandersStore()
const caption = computed(() => store.voiceCaption)
</script>

<template>
  <Transition name="cmd-voice-fade">
    <aside
      v-if="caption"
      class="cmd-voice-toast"
      data-testid="commander-voice-toast"
      role="status"
      aria-live="polite"
    >
      <img class="cmd-voice-toast__avatar" :src="commanderAvatarUrl(caption.commanderId)" :alt="caption.name" />
      <div class="cmd-voice-toast__body">
        <b>{{ caption.name }}</b>
        <p>{{ caption.line }}</p>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.cmd-voice-toast {
  position: fixed;
  left: 18px;
  bottom: 18px;
  z-index: 340;
  max-width: min(380px, calc(100vw - 36px));
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px 9px 10px;
  border-radius: 14px;
  border: 1px solid rgb(125 211 252 / 42%);
  background: linear-gradient(135deg, rgb(10 24 44 / 92%), rgb(12 18 32 / 94%));
  box-shadow: 0 12px 30px rgb(0 0 0 / 45%);
  pointer-events: none;
}
.cmd-voice-toast__avatar {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1.5px solid #7dd3fc;
  object-fit: cover;
  flex-shrink: 0;
}
.cmd-voice-toast__body {
  min-width: 0;
}
.cmd-voice-toast__body b {
  display: block;
  font-size: 12px;
  color: #fde68a;
  margin-bottom: 2px;
}
.cmd-voice-toast__body p {
  margin: 0;
  font-size: 12px;
  line-height: 1.4;
  color: #e6f2fc;
}
.cmd-voice-fade-enter-active,
.cmd-voice-fade-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.cmd-voice-fade-enter-from,
.cmd-voice-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
