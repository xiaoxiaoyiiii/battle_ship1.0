<script setup lang="ts">
import { computed } from 'vue'

type AvatarSize = 'sm' | 'md' | 'lg'

const props = withDefaults(defineProps<{
  src?: string
  frame?: string
  fallback?: string
  alt?: string
  size?: AvatarSize
  testid?: string
}>(), {
  src: '',
  frame: 'none',
  fallback: '⚓',
  alt: '',
  size: 'md',
  testid: undefined,
})

const emit = defineEmits<{ (event: 'error', error: Event): void }>()
const frameId = computed(() => props.frame || 'none')
const hasAnimatedFrame = computed(() => ['aurora', 'golden_wheel', 'mithril_ring', 'king_aura', 'season_tide_ring', 'abyssal_glow', 'tideglass', 'ember_wake', 'star_compass'].includes(frameId.value))
</script>

<template>
  <span
    class="avatar-stack"
    :class="['avatar-stack--' + size, { 'avatar-stack--animated': hasAnimatedFrame }]"
    :data-frame="frameId"
    :data-testid="testid"
  >
    <span class="avatar-stack__halo" aria-hidden="true"></span>
    <img
      v-if="src"
      class="avatar-stack__image"
      :src="src"
      :alt="alt"
      @error="emit('error', $event)"
    />
    <span v-else class="avatar-stack__image avatar-stack__image--empty" aria-hidden="true">{{ fallback }}</span>
    <span class="avatar-stack__ornament" aria-hidden="true"></span>
  </span>
</template>

<style>
.avatar-stack {
  --avatar-size: 56px;
  --avatar-ring: var(--border-strong, #63758e);
  --avatar-glow: transparent;
  position: relative;
  display: inline-grid;
  place-items: center;
  width: var(--avatar-size);
  height: var(--avatar-size);
  flex: 0 0 var(--avatar-size);
  border-radius: 50%;
  isolation: isolate;
  color: var(--role-action, #8fdcff);
  background: var(--surface-deck, #162438);
  box-shadow: 0 4px 14px rgb(0 0 0 / 26%);
}

.avatar-stack--sm { --avatar-size: 34px; }
.avatar-stack--md { --avatar-size: 56px; }
.avatar-stack--lg { --avatar-size: 128px; }

.avatar-stack::before,
.avatar-stack::after,
.avatar-stack__halo,
.avatar-stack__ornament {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
}

.avatar-stack::before {
  content: '';
  z-index: 0;
  inset: -2px;
  border: 2px solid var(--avatar-ring);
  box-shadow: 0 0 0 2px rgb(5 10 20 / 62%), 0 0 18px var(--avatar-glow);
}

.avatar-stack::after {
  content: '';
  z-index: 2;
  inset: 3px;
  border: 1px solid rgb(255 255 255 / 20%);
  opacity: .7;
}

.avatar-stack__image {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  border: 0;
  border-radius: 50%;
  object-fit: cover;
  background: radial-gradient(circle at 35% 30%, rgb(123 219 255 / 36%), transparent 70%), var(--surface-deck, #162438);
  color: inherit;
  font-size: 22px;
  font-weight: 700;
}

.avatar-stack--lg .avatar-stack__image { font-size: 34px; }
.avatar-stack__halo { z-index: -2; inset: -7px; opacity: 0; }
.avatar-stack__ornament { z-index: 3; opacity: 0; }

.avatar-stack[data-frame='none']::before { border-color: var(--border-strong, #63758e); box-shadow: 0 0 0 2px rgb(5 10 20 / 62%); }
.avatar-stack[data-frame='silver']::before { --avatar-ring: #c6d3dd; --avatar-glow: rgb(198 211 221 / 34%); }
.avatar-stack[data-frame='gold']::before { --avatar-ring: #f3c85f; --avatar-glow: rgb(243 200 95 / 46%); border-width: 3px; }
.avatar-stack[data-frame='crimson']::before { --avatar-ring: #dd6b72; --avatar-glow: rgb(221 107 114 / 38%); border-width: 3px; box-shadow: 0 0 0 5px rgb(221 107 114 / 13%), 0 0 24px var(--avatar-glow); }
.avatar-stack[data-frame='aurora'] { --avatar-ring: #70e5a2; --avatar-glow: rgb(112 229 162 / 46%); }
.avatar-stack[data-frame='aurora']::before { border-style: double; border-width: 4px; }
.avatar-stack[data-frame='bronze_compass']::before { --avatar-ring: #c58a55; --avatar-glow: rgb(197 138 85 / 32%); }
.avatar-stack[data-frame='silver_chain']::before { --avatar-ring: #b7c9d8; --avatar-glow: rgb(183 201 216 / 32%); border-width: 3px; border-style: dotted; }
.avatar-stack[data-frame='golden_wheel'] { --avatar-ring: #f3c85f; --avatar-glow: rgb(243 200 95 / 48%); }
.avatar-stack[data-frame='golden_wheel']::before { border-width: 4px; border-style: double; animation: avatar-stack-wheel 4s linear infinite; }
.avatar-stack[data-frame='mithril_ring'] { --avatar-ring: #cde8f3; --avatar-glow: rgb(170 230 255 / 54%); }
.avatar-stack[data-frame='mithril_ring']::before { border-width: 3px; animation: avatar-stack-pulse 2.8s ease-in-out infinite; }
.avatar-stack[data-frame='king_aura'] { --avatar-ring: #f6d77a; --avatar-glow: rgb(246 215 122 / 62%); }
.avatar-stack[data-frame='king_aura']::before { border-width: 4px; box-shadow: 0 0 0 5px rgb(246 215 122 / 20%), 0 0 0 10px rgb(246 215 122 / 9%), 0 0 38px var(--avatar-glow); animation: avatar-stack-king 2.6s ease-in-out infinite; }
.avatar-stack[data-frame='season_tide_ring'] { --avatar-ring: #8ee0ef; --avatar-glow: rgb(78 200 224 / 58%); }
.avatar-stack[data-frame='season_tide_ring']::before { border-width: 3px; border-style: double; animation: avatar-stack-pulse 3s ease-in-out infinite; }
.avatar-stack[data-frame='abyssal_glow'] { --avatar-ring: #58d5ed; --avatar-glow: rgb(88 213 237 / 52%); }
.avatar-stack[data-frame='abyssal_glow']::before { border-width: 3px; animation: avatar-stack-pulse 3.2s ease-in-out infinite; }
.avatar-stack[data-frame='tideglass'] { --avatar-ring: #9bd8e7; --avatar-glow: rgb(155 216 231 / 46%); }
.avatar-stack[data-frame='tideglass']::before { border-width: 3px; background: linear-gradient(135deg, transparent 38%, rgb(155 216 231 / 26%) 50%, transparent 62%); animation: avatar-stack-shimmer 3.6s linear infinite; }
.avatar-stack[data-frame='ember_wake'] { --avatar-ring: #e78353; --avatar-glow: rgb(231 131 83 / 48%); }
.avatar-stack[data-frame='ember_wake']::before { border-width: 3px; animation: avatar-stack-pulse 2.3s ease-in-out infinite; }
.avatar-stack[data-frame='star_compass'] { --avatar-ring: #e7c36a; --avatar-glow: rgb(231 195 106 / 52%); }
.avatar-stack[data-frame='star_compass']::before { border-width: 3px; border-style: dashed; animation: avatar-stack-wheel 9s linear infinite; }

@keyframes avatar-stack-wheel { to { transform: rotate(360deg); } }
@keyframes avatar-stack-pulse { 0%, 100% { transform: scale(1); box-shadow: 0 0 0 3px rgb(255 255 255 / 8%), 0 0 20px var(--avatar-glow); } 50% { transform: scale(1.035); box-shadow: 0 0 0 5px rgb(255 255 255 / 13%), 0 0 34px var(--avatar-glow); } }
@keyframes avatar-stack-king { 0%, 100% { box-shadow: 0 0 0 5px rgb(246 215 122 / 20%), 0 0 0 10px rgb(246 215 122 / 9%), 0 0 30px var(--avatar-glow); } 50% { box-shadow: 0 0 0 7px rgb(246 215 122 / 28%), 0 0 0 13px rgb(246 215 122 / 13%), 0 0 48px var(--avatar-glow); } }
@keyframes avatar-stack-shimmer { 0% { filter: brightness(1); } 50% { filter: brightness(1.22); } 100% { filter: brightness(1); } }

@media (prefers-reduced-motion: reduce) {
  .avatar-stack--animated::before,
  .avatar-stack--animated::after,
  .avatar-stack--animated .avatar-stack__halo,
  .avatar-stack--animated .avatar-stack__ornament { animation: none !important; }
}
</style>
