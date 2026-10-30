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
  drag: boolean
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
let tapFxId: number | null = null

function motionDisabled(): boolean {
  if (ui.motion === 'reduced') return true
  try { return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

function add(kind: PointerFxKind, event: PointerEvent, lifetime: number, drag = false): number | null {
  if (motionDisabled() || cosmetics.pointerEffect === 'none') return null
  const width = Math.max(1, window.innerWidth)
  const height = Math.max(1, window.innerHeight)
  const x = Math.max(0, Math.min(100, event.clientX / width * 100))
  const y = Math.max(0, Math.min(100, event.clientY / height * 100))
  const angle = Math.atan2(event.movementY || 0, event.movementX || 1) * 180 / Math.PI
  const item: PointerFx = { id: ++effectId, kind, effect: cosmetics.pointerEffect, x, y, angle, drag }
  effects.value = [...effects.value.slice(-31), item]
  window.setTimeout(() => { effects.value = effects.value.filter(entry => entry.id !== item.id) }, lifetime)
  return item.id
}

function removeTapFx(): void {
  if (tapFxId === null) return
  effects.value = effects.value.filter(entry => entry.id !== tapFxId)
  tapFxId = null
}

function flushTrail(): void {
  rafId = 0
  const event = queuedMove
  queuedMove = null
  if (!event || motionDisabled() || cosmetics.pointerEffect === 'none') return
  const now = performance.now()
  const dx = event.clientX - lastTrailX
  const dy = event.clientY - lastTrailY
  if (now - lastTrailAt < 34 || (lastTrailX > -Infinity && dx * dx + dy * dy < 14 * 14)) return
  lastTrailAt = now
  lastTrailX = event.clientX
  lastTrailY = event.clientY
  const isDrag = dragging && activePointer === event.pointerId && (event.buttons !== 0 || event.pointerType === 'touch')
  add('trail', event, isDrag ? 620 : 480, isDrag)
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
  // Every pointer gets immediate feedback. A touch burst is removed when the
  // gesture crosses the slop threshold, so scrolling does not leave a stale tap.
  tapFxId = add('burst', event, 360)
}

function onPointerMove(event: PointerEvent): void {
  if (motionDisabled() || cosmetics.pointerEffect === 'none') return
  if (event.pointerType === 'touch') {
    if (!dragging || event.pointerId !== activePointer) return
    const dx = event.clientX - downX
    const dy = event.clientY - downY
    if (!dragMoved && dx * dx + dy * dy >= 12 * 12) {
      dragMoved = true
      removeTapFx()
    }
    if (!dragMoved) return
  }
  queuedMove = event
  if (!rafId) rafId = requestAnimationFrame(flushTrail)
}

function onPointerUp(event: PointerEvent): void {
  if (event.pointerId !== activePointer) return
  tapFxId = null
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
  removeTapFx()
  queuedMove = null
  if (rafId) cancelAnimationFrame(rafId)
  rafId = 0
}

function cancelActivePointer(): void {
  dragging = false
  dragMoved = false
  activePointer = -1
  removeTapFx()
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
      :class="[
        `global-pointer-effects__fx--${item.kind}`,
        `global-pointer-effects__fx--${item.effect}`,
        { 'global-pointer-effects__fx--drag': item.drag },
      ]"
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
  --pointer-duration: 340ms;
  position: absolute;
  display: block;
  pointer-events: none;
  transform: translate(-50%, -50%) rotate(var(--pointer-angle, 0deg));
  will-change: transform, opacity;
}

.global-pointer-effects__fx--trail {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: radial-gradient(circle, #fff 0 16%, var(--pointer-color) 40%, transparent 72%);
  box-shadow: 0 0 6px var(--pointer-glow), 0 0 18px var(--pointer-glow);
  animation: global-pointer-trail 480ms cubic-bezier(.2,.6,.3,1) both;
}

.global-pointer-effects__fx--trail.global-pointer-effects__fx--drag {
  width: 10px;
  height: 10px;
  filter: brightness(1.18);
  animation-duration: 620ms;
}

.global-pointer-effects__fx--burst {
  width: 14px;
  height: 14px;
  border: 0;
  border-radius: 50%;
  box-shadow: 0 0 8px var(--pointer-glow);
  animation: global-pointer-burst var(--pointer-duration) cubic-bezier(.2,.72,.2,1) both;
}

.global-pointer-effects__fx--burst::before,
.global-pointer-effects__fx--burst::after {
  position: absolute;
  content: '';
  pointer-events: none;
}

.global-pointer-effects__fx--ripple {
  --pointer-color: #71e0f4;
  --pointer-glow: rgb(113 224 244 / 68%);
}

.global-pointer-effects__fx--ripple.global-pointer-effects__fx--trail {
  width: 6px;
  height: 6px;
  background: radial-gradient(circle, #effcff 0 20%, var(--pointer-color) 42%, transparent 72%);
}

.global-pointer-effects__fx--ripple.global-pointer-effects__fx--burst {
  background: radial-gradient(circle, #fff 0 10%, var(--pointer-color) 17%, transparent 22%);
  animation-name: global-pointer-ripple;
}

.global-pointer-effects__fx--ripple.global-pointer-effects__fx--burst::before,
.global-pointer-effects__fx--ripple.global-pointer-effects__fx--burst::after {
  inset: 50%;
  border: 1px solid var(--pointer-color);
  border-radius: 50%;
  transform: translate(-50%, -50%) scale(.15);
  box-shadow: 0 0 8px var(--pointer-glow);
}

.global-pointer-effects__fx--ripple.global-pointer-effects__fx--burst::before {
  animation: global-pointer-ripple-ring 300ms cubic-bezier(.12,.7,.26,1) both;
}

.global-pointer-effects__fx--ripple.global-pointer-effects__fx--burst::after {
  animation: global-pointer-ripple-ring 300ms 28ms cubic-bezier(.12,.7,.26,1) both;
}

.global-pointer-effects__fx--comet {
  --pointer-color: #f6d77a;
  --pointer-glow: rgb(246 215 122 / 70%);
}

.global-pointer-effects__fx--comet.global-pointer-effects__fx--trail {
  width: 28px;
  height: 4px;
  border-radius: 99px;
  transform-origin: 82% 50%;
  background: linear-gradient(90deg, transparent, rgb(246 215 122 / 8%), var(--pointer-color));
  filter: blur(.15px) drop-shadow(0 0 5px var(--pointer-glow));
}

.global-pointer-effects__fx--comet.global-pointer-effects__fx--drag {
  width: 40px;
  height: 5px;
}

.global-pointer-effects__fx--comet.global-pointer-effects__fx--burst {
  width: 12px;
  height: 12px;
  background: radial-gradient(circle, #fff 0 16%, var(--pointer-color) 35%, transparent 72%);
  animation-name: global-pointer-comet;
}

.global-pointer-effects__fx--comet.global-pointer-effects__fx--burst::before {
  left: -42px;
  top: 50%;
  width: 50px;
  height: 3px;
  border-radius: 99px;
  transform: translateY(-50%);
  background: linear-gradient(90deg, transparent, var(--pointer-color));
  box-shadow: 0 0 8px var(--pointer-glow);
  animation: global-pointer-comet-tail 320ms cubic-bezier(.12,.72,.2,1) both;
}

.global-pointer-effects__fx--comet.global-pointer-effects__fx--burst::after {
  inset: -11px;
  border: 1px solid rgb(246 215 122 / 55%);
  border-radius: 50%;
  transform: scale(.25);
  animation: global-pointer-comet-ring 300ms cubic-bezier(.12,.72,.2,1) both;
}

.global-pointer-effects__fx--stardust {
  --pointer-color: #c5a0ff;
  --pointer-glow: rgb(197 160 255 / 72%);
}

.global-pointer-effects__fx--stardust.global-pointer-effects__fx--trail {
  width: 5px;
  height: 5px;
  background: radial-gradient(circle, #fff 0 12%, var(--pointer-color) 40%, transparent 75%);
  box-shadow: 0 0 5px var(--pointer-glow), 8px -3px 0 -1px rgb(197 160 255 / 56%);
}

.global-pointer-effects__fx--stardust.global-pointer-effects__fx--burst {
  width: 10px;
  height: 10px;
  background: radial-gradient(circle, #fff 0 18%, var(--pointer-color) 38%, transparent 74%);
  animation-name: global-pointer-stardust;
}

.global-pointer-effects__fx--stardust.global-pointer-effects__fx--burst::before {
  inset: 50%;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--pointer-color);
  box-shadow: 22px 0 0 -1px var(--pointer-color), -22px 0 0 -1px var(--pointer-color), 0 22px 0 -1px var(--pointer-color), 0 -22px 0 -1px var(--pointer-color);
  transform: translate(-50%, -50%);
  animation: global-pointer-stardust-particles 340ms cubic-bezier(.1,.7,.2,1) both;
}

.global-pointer-effects__fx--stardust.global-pointer-effects__fx--burst::after {
  inset: 50%;
  width: 7px;
  height: 7px;
  border: 1px solid var(--pointer-color);
  transform: translate(-50%, -50%) rotate(45deg) scale(.2);
  animation: global-pointer-stardust-star 340ms cubic-bezier(.1,.7,.2,1) both;
}

.global-pointer-effects__fx--eclipse {
  --pointer-color: #f4a76a;
  --pointer-glow: rgb(244 167 106 / 72%);
}

.global-pointer-effects__fx--eclipse.global-pointer-effects__fx--trail {
  width: 13px;
  height: 4px;
  border-radius: 99px;
  background: linear-gradient(90deg, transparent, var(--pointer-color));
  box-shadow: 0 0 8px var(--pointer-glow);
}

.global-pointer-effects__fx--eclipse.global-pointer-effects__fx--burst {
  width: 18px;
  height: 18px;
  background: radial-gradient(circle, #130f18 0 42%, var(--pointer-color) 44% 50%, transparent 52%);
  box-shadow: 0 0 14px var(--pointer-glow), inset 0 0 5px var(--pointer-glow);
  animation-name: global-pointer-eclipse;
}

.global-pointer-effects__fx--eclipse.global-pointer-effects__fx--burst::before {
  inset: -8px;
  border: 1px solid var(--pointer-color);
  border-radius: 50%;
  opacity: .7;
  animation: global-pointer-eclipse-ring 330ms cubic-bezier(.14,.7,.22,1) both;
}

.global-pointer-effects__fx--eclipse.global-pointer-effects__fx--burst::after {
  inset: -18px -8px 8px -18px;
  border: 2px solid transparent;
  border-top-color: var(--pointer-color);
  border-radius: 50%;
  transform: rotate(-28deg) scale(.2);
  animation: global-pointer-eclipse-arc 340ms cubic-bezier(.14,.7,.22,1) both;
}

@keyframes global-pointer-trail {
  0% { opacity: .9; transform: translate(-50%, -50%) rotate(var(--pointer-angle, 0deg)) scale(1); }
  100% { opacity: 0; transform: translate(-50%, -50%) rotate(var(--pointer-angle, 0deg)) scale(.16) translateX(-18px); }
}

@keyframes global-pointer-burst {
  0% { opacity: .98; transform: translate(-50%, -50%) scale(.45); }
  22% { opacity: .94; transform: translate(-50%, -50%) scale(1); }
  100% { opacity: 0; transform: translate(-50%, -50%) scale(1.7); }
}

@keyframes global-pointer-ripple {
  0% { opacity: 1; transform: translate(-50%, -50%) scale(.55); }
  18% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
  100% { opacity: 0; transform: translate(-50%, -50%) scale(1.25); }
}

@keyframes global-pointer-ripple-ring {
  0% { opacity: .85; width: 18px; height: 18px; transform: translate(-50%, -50%) scale(.2); }
  100% { opacity: 0; width: 62px; height: 62px; transform: translate(-50%, -50%) scale(1); }
}

@keyframes global-pointer-comet {
  0% { opacity: 1; transform: translate(-50%, -50%) scale(.4) rotate(var(--pointer-angle, 0deg)); }
  26% { opacity: 1; transform: translate(-50%, -50%) scale(1.05) rotate(var(--pointer-angle, 0deg)); }
  100% { opacity: 0; transform: translate(-50%, -50%) scale(.35) rotate(var(--pointer-angle, 0deg)) translateX(16px); }
}

@keyframes global-pointer-comet-tail {
  0% { opacity: .9; transform: translateY(-50%) scaleX(.1); transform-origin: 100% 50%; }
  100% { opacity: 0; transform: translateY(-50%) scaleX(1); transform-origin: 100% 50%; }
}

@keyframes global-pointer-comet-ring {
  0% { opacity: .75; transform: scale(.2); }
  100% { opacity: 0; transform: scale(1.8); }
}

@keyframes global-pointer-stardust {
  0% { opacity: 1; transform: translate(-50%, -50%) scale(.3) rotate(0deg); }
  25% { opacity: 1; transform: translate(-50%, -50%) scale(1) rotate(35deg); }
  100% { opacity: 0; transform: translate(-50%, -50%) scale(.55) rotate(125deg); }
}

@keyframes global-pointer-stardust-particles {
  0% { opacity: 0; transform: translate(-50%, -50%) scale(.1); }
  18% { opacity: 1; transform: translate(-50%, -50%) scale(.4); }
  100% { opacity: 0; transform: translate(-50%, -50%) scale(1.18); }
}

@keyframes global-pointer-stardust-star {
  0% { opacity: 0; transform: translate(-50%, -50%) rotate(45deg) scale(.2); }
  30% { opacity: 1; transform: translate(-50%, -50%) rotate(135deg) scale(1.2); }
  100% { opacity: 0; transform: translate(-50%, -50%) rotate(225deg) scale(.2); }
}

@keyframes global-pointer-eclipse {
  0% { opacity: 1; transform: translate(-50%, -50%) scale(.45) rotate(var(--pointer-angle, 0deg)); }
  20% { opacity: 1; transform: translate(-50%, -50%) scale(1) rotate(var(--pointer-angle, 0deg)); }
  100% { opacity: 0; transform: translate(-50%, -50%) scale(1.25) rotate(var(--pointer-angle, 0deg)); }
}

@keyframes global-pointer-eclipse-ring {
  0% { opacity: .8; transform: scale(.2) rotate(-20deg); }
  100% { opacity: 0; transform: scale(1.65) rotate(28deg); }
}

@keyframes global-pointer-eclipse-arc {
  0% { opacity: 0; transform: rotate(-28deg) scale(.2); }
  35% { opacity: .9; transform: rotate(12deg) scale(.85); }
  100% { opacity: 0; transform: rotate(42deg) scale(1.1); }
}

html[data-motion='reduced'] .global-pointer-effects { display: none; }

@media (prefers-reduced-motion: reduce) {
  .global-pointer-effects { display: none; }
}
</style>
