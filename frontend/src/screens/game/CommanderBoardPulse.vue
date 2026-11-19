<script setup lang="ts">
defineProps<{ kind: 'sonar' | 'sacrifice' | 'shield' }>()
</script>

<template>
  <span class="commander-board-pulse" :class="'commander-board-pulse--' + kind" :data-testid="'commander-board-cue-' + kind" aria-hidden="true" />
</template>

<style scoped>
.commander-board-pulse {
  position: absolute;
  z-index: 3;
  inset: 1px;
  border-radius: inherit;
  pointer-events: none;
}
.commander-board-pulse--sonar {
  inset: 8%;
  border: 2px solid #b9f5ff;
  border-radius: 50%;
  box-shadow: 0 0 12px #56dbff, inset 0 0 9px #56dbff77;
  animation: board-sonar .88s ease-out both;
}
.commander-board-pulse--sacrifice {
  background: radial-gradient(ellipse at 50% 62%, #dda94090 0%, #993e3866 37%, transparent 70%);
  box-shadow: inset 0 0 0 2px #ffbc7777;
  animation: board-sacrifice .83s ease-out both;
}
.commander-board-pulse--shield {
  inset: 0;
  border: 2px solid #91c2ff;
  box-shadow: 0 0 15px #619dffb8, inset 0 0 20px #6091ffaa;
  animation: board-shield .9s ease-out both;
}
@keyframes board-sonar { 0% { transform: scale(.45); opacity: .95; } 78% { opacity: .65; } 100% { transform: scale(1.03); opacity: 0; } }
@keyframes board-sacrifice { 0% { opacity: .8; transform: translateY(-6%); } 30% { opacity: 1; } 100% { transform: translateY(8%); opacity: 0; } }
@keyframes board-shield { 0% { opacity: .3; } 34% { opacity: 1; } 100% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .commander-board-pulse { animation: none; opacity: .7; } }
:global(html[data-motion='reduced']) .commander-board-pulse { animation: none; opacity: .7; }
</style>
