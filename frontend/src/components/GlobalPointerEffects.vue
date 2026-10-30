<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useCosmeticStore, type PointerEffectId } from '../stores/cosmetics'
import { useProfileStore } from '../stores/profile'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'

type PointerFxKind = 'trail' | 'burst'
interface PointerFx {
  id: number
  kind: PointerFxKind
  effect: PointerEffectId
  x: number
  y: number
  angle: number
}

const ui = useUiStore()
const cosmetics = useCosmeticStore()
const profile = useProfileStore()
const auth = useAuthStore()
const effects = ref<PointerFx[]>([])
let effectId = 0
let rafId = 0
let lastTrailAt = 0
let lastTrailX = -Infinity
let lastTrailY = -Infinity
let queuedMove: PointerEvent | null = null
let dragging = false
let dragMoved = false
let activePointer = -1
let downX = 0
let downY = 0

function motionDisabled(): boolean {
  if (ui.motion === 'reduced') return true
  try { return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

function add(kind: PointerFxKind, event: PointerEvent, lifetime: number): void {
  if (motionDisabled() || cosmetics.pointerEffect === 'none') return
  const width = Math.max(1, window.innerWidth)
  const height = Math.max(1, window.innerHeight)
  const x = Math.max(0, Math.min(100, event.clientX / width * 100))
  const y = Math.max(0, Math.min(100, event.clientY / height * 100))
  const angle = Math.atan2(event.movementY || 0, event.movementX || 1) * 180 / Math.PI
  const item: PointerFx = { id: ++effectId, kind, effect: cosmetics.pointerEffect, x, y, angle }
  effects.value = [...effects.value.slice(-27), item]
  window.setTimeout(() => { effects.value = effects.value.filter(entry => entry.id !== item.id) }, lifetime)
}

function flushTrail(): void {
  rafId = 0
  const event = queuedMove
  queuedMove = null
  if (!event || !dragging || motionDisabled() || cosmetics.pointerEffect === 'none') return
  const now = performance.now()
  const dx = event.clientX - lastTrailX
  const dy = event.clientY - lastTrailY
  if (now - lastTrailAt < 34 || (lastTrailX > -Infinity && dx * dx + dy * dy < 14 * 14)) return
  lastTrailAt = now
  lastTrailX = event.clientX
  lastTrailY = event.clientY
  add('trail', event, 560)
}

function onPointerDown(event: PointerEvent): void {
  if (motionDisabled() || cosmetics.pointerEffect === 'none') return
  activePointer = event.pointerId
  dragging = true
  dragMoved = false
  downX = event.clientX
  downY = event.clientY
  lastTrailX = event.clientX
  lastTrailY = event.clientY
  lastTrailAt = performance.now()
  // Mouse/stylus feedback is immediate. Touch waits until pointerup so a swipe
  // does not produce a tap burst on the first frame.
  if (event.pointerType !== 'touch') add('burst', event, 720)
}

function onPointerMove(event: PointerEvent): void {
  if (!dragging || event.pointerId !== activePointer || motionDisabled()) return
  const dx = event.clientX - downX
  const dy = event.clientY - downY
  if (!dragMoved && dx * dx + dy * dy >= 12 * 12) dragMoved = true
  if (event.pointerType === 'touch' && !dragMoved) return
  if (event.pointerType !== 'touch' && event.buttons === 0) return
  queuedMove = event
  if (!rafId) rafId = requestAnimationFrame(flushTrail)
}

function onPointerUp(event: PointerEvent): void {
  if (event.pointerId !== activePointer) return
  if (event.pointerType === 'touch' && !dragMoved) add('burst', event, 720)
  dragging = false
  activePointer = -1
  queuedMove = null
  if (rafId) cancelAnimationFrame(rafId)
  rafId = 0
}

function onPointerCancel(event: PointerEvent): void {
  if (event.pointerId !== activePointer) return
  dragging = false
  activePointer = -1
  queuedMove = null
  if (rafId) cancelAnimationFrame(rafId)
  rafId = 0
}

function cancelActivePointer(): void {
  dragging = false
  dragMoved = false
  activePointer = -1
  queuedMove = null
  if (rafId) cancelAnimationFrame(rafId)
  rafId = 0
}

function refreshEffect(): void {
  // A preference change should not leave particles from the old paid effect on
  // screen; the next click/drag uses the new id immediately.
  effects.value = []
}

async function syncProfileEffect(): Promise<void> {
  if (auth.isGuest) {
    cosmetics.syncFromProfile(null)
    return
  }
  await profile.loadOwn()
  cosmetics.syncFromProfile(profile.own)
}

onMounted(() => {
  window.addEventListener('pointerdown', onPointerDown, { passive: true })
  window.addEventListener('pointermove', onPointerMove, { passive: true })
  window.addEventListener('pointerup', onPointerUp, { passive: true })
  window.addEventListener('pointercancel', onPointerCancel, { passive: true })
  window.addEventListener('blur', cancelActivePointer)
  document.addEventListener('visibilitychange', cancelActivePointer)
  window.addEventListener('bs:cosmetic-pointer', refreshEffect)
  void syncProfileEffect()
})

watch(() => auth.isGuest, () => { void syncProfileEffect() })
watch(() => profile.own?.pointer_effect_id, () => cosmetics.syncFromProfile(profile.own))

onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', onPointerDown)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerCancel)
  window.removeEventListener('blur', cancelActivePointer)
  document.removeEventListener('visibilitychange', cancelActivePointer)
  window.removeEventListener('bs:cosmetic-pointer', refreshEffect)
  if (rafId) cancelAnimationFrame(rafId)
})
</script>

<template>
  <div class="global-pointer-effects" aria-hidden="true">
    <span
      v-for="item in effects"
      :key="item.id"
      class="global-pointer-effects__fx"
      :class="[`global-pointer-effects__fx--${item.kind}`, `global-pointer-effects__fx--${item.effect}`]"
      :style="{ left: item.x + '%', top: item.y + '%', '--pointer-angle': item.angle + 'deg' }"
    ></span>
  </div>
</template>

<style>
.global-pointer-effects {
  position: fixed;
  z-index: 160;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  contain: layout paint;
}

.global-pointer-effects__fx {
  --pointer-color: #7de7ff;
  --pointer-glow: rgb(125 231 255 / 72%);
  position: absolute;
  display: block;
  pointer-events: none;
  transform: translate(-50%, -50%) rotate(var(--pointer-angle, 0deg));
  will-change: transform, opacity;
}

.global-pointer-effects__fx--trail {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--pointer-color);
  box-shadow: 0 0 6px var(--pointer-glow), 0 0 18px var(--pointer-glow);
  animation: global-pointer-trail 560ms cubic-bezier(.2,.6,.3,1) both;
}

.global-pointer-effects__fx--burst {
  width: 20px;
  height: 20px;
  border: 2px solid var(--pointer-color);
  border-radius: 50%;
  box-shadow: 0 0 7px var(--pointer-glow), inset 0 0 7px var(--pointer-glow);
  animation: global-pointer-burst 720ms cubic-bezier(.15,.72,.28,1) both;
}

.global-pointer-effects__fx--burst::before,
.global-pointer-effects__fx--burst::after {
  position: absolute;
  content: '';
  inset: 50%;
  width: 38px;
  height: 2px;
  border-radius: 99px;
  background: linear-gradient(90deg, transparent, var(--pointer-color), transparent);
  transform: translate(-50%, -50%) rotate(45deg);
}

.global-pointer-effects__fx--burst::after { transform: translate(-50%, -50%) rotate(-45deg); }
.global-pointer-effects__fx--ripple { --pointer-color: #71e0f4; --pointer-glow: rgb(113 224 244 / 68%); }
.global-pointer-effects__fx--comet { --pointer-color: #f6d77a; --pointer-glow: rgb(246 215 122 / 70%); }
.global-pointer-effects__fx--comet.global-pointer-effects__fx--trail { width: 11px; height: 5px; border-radius: 99px; }
.global-pointer-effects__fx--stardust { --pointer-color: #c5a0ff; --pointer-glow: rgb(197 160 255 / 72%); }
.global-pointer-effects__fx--stardust.global-pointer-effects__fx--trail { width: 5px; height: 5px; }
.global-pointer-effects__fx--eclipse { --pointer-color: #f4a76a; --pointer-glow: rgb(244 167 106 / 72%); }
.global-pointer-effects__fx--eclipse.global-pointer-effects__fx--burst { border-width: 3px; }

@keyframes global-pointer-trail {
  0% { opacity: .9; transform: translate(-50%, -50%) rotate(var(--pointer-angle, 0deg)) scale(1); }
  100% { opacity: 0; transform: translate(-50%, -50%) rotate(var(--pointer-angle, 0deg)) scale(.16) translateX(-18px); }
}

@keyframes global-pointer-burst {
  0% { opacity: .95; transform: translate(-50%, -50%) scale(.35); }
  42% { opacity: .8; transform: translate(-50%, -50%) scale(1); }
  100% { opacity: 0; transform: translate(-50%, -50%) scale(3.5); }
}

html[data-motion='reduced'] .global-pointer-effects { display: none; }

@media (prefers-reduced-motion: reduce) {
  .global-pointer-effects { display: none; }
}
</style>
