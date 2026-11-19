<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  clampBoardTargetPosition,
  locateBoardTarget,
  saveBoardTargetPosition,
  type BoardTargetPositions,
  type BoardTargetSide,
} from './boardTargetPosition'
import type { Point } from './view'

const props = defineProps<{
  side: BoardTargetSide
  arena: HTMLElement | null
  positions: BoardTargetPositions
}>()

const panel = ref<HTMLElement | null>(null)
const position = ref<Point | null>(null)
const viewportSize = ref({ width: window.innerWidth, height: window.innerHeight })
const dragging = ref(false)
let animationFrame = 0
let observer: ResizeObserver | null = null
let anchor: HTMLElement | null = null
let drag: { id: number; start: Point; origin: Point; side: BoardTargetSide; moved: boolean } | null = null

const panelStyle = computed(() => ({
  left: position.value ? position.value.x + 'px' : '0px',
  top: position.value ? position.value.y + 'px' : '0px',
  visibility: position.value ? undefined : 'hidden' as const,
  '--board-target-available-width': viewportSize.value.width + 'px',
  '--board-target-available-height': viewportSize.value.height + 'px',
}))

function viewportBounds() {
  const viewport = window.visualViewport
  const left = (viewport?.offsetLeft ?? 0) + 8
  const top = (viewport?.offsetTop ?? 0) + 8
  const navBottom = document.querySelector<HTMLElement>('.app-nav')?.getBoundingClientRect().bottom ?? 0
  const right = left + (viewport?.width ?? window.innerWidth) - 16
  const bottom = top + (viewport?.height ?? window.innerHeight) - 16
  return { left, top: Math.max(top, Math.min(navBottom + 6, bottom - 100)), right, bottom }
}

function refreshPosition(): void {
  const viewport = viewportBounds()
  viewportSize.value = { width: viewport.right - viewport.left, height: viewport.bottom - viewport.top }
  const element = panel.value
  if (!element) return
  const measured = element.getBoundingClientRect()
  const size = { width: measured.width, height: measured.height }
  if (drag) {
    if (position.value) position.value = clampBoardTargetPosition(position.value, size, viewport)
    return
  }
  const desired = props.positions[props.side]
  const board = anchor?.getBoundingClientRect()
  position.value = desired
    ? clampBoardTargetPosition(desired, size, viewport)
    : locateBoardTarget(size, viewport, board && board.width > 0 ? board : undefined)
}

function scheduleRefresh(): void {
  if (animationFrame) return
  animationFrame = window.requestAnimationFrame(() => {
    animationFrame = 0
    refreshPosition()
  })
}

function observeBoard(): void {
  if (anchor) observer?.unobserve(anchor)
  anchor = props.arena?.querySelector<HTMLElement>('[data-board="' + props.side + '"] [role="grid"]') ?? null
  if (anchor) observer?.observe(anchor)
  scheduleRefresh()
}

function startDrag(event: PointerEvent): void {
  if (event.button !== 0 || drag || !position.value ||
    (event.target as HTMLElement | null)?.closest('button, a, input, textarea, select')) return
  const handle = event.currentTarget as HTMLElement
  handle.setPointerCapture(event.pointerId)
  drag = {
    id: event.pointerId,
    start: { x: event.clientX, y: event.clientY },
    origin: position.value,
    side: props.side,
    moved: false,
  }
  dragging.value = true
  event.preventDefault()
}

function moveDrag(event: PointerEvent): void {
  if (!drag || drag.id !== event.pointerId || !panel.value) return
  const { width, height } = panel.value.getBoundingClientRect()
  const x = event.clientX - drag.start.x
  const y = event.clientY - drag.start.y
  if (x !== 0 || y !== 0) drag.moved = true
  position.value = clampBoardTargetPosition({ x: drag.origin.x + x, y: drag.origin.y + y }, { width, height }, viewportBounds())
}

function endDrag(event?: PointerEvent): void {
  if (!drag || (event && drag.id !== event.pointerId)) return
  if (drag.moved && position.value) saveBoardTargetPosition(props.positions, drag.side, position.value)
  drag = null
  dragging.value = false
}

watch([() => props.side, () => props.arena], () => {
  endDrag()
  observeBoard()
}, { flush: 'post' })

onMounted(() => {
  observer = new ResizeObserver(scheduleRefresh)
  if (panel.value) observer.observe(panel.value)
  observeBoard()
  window.addEventListener('resize', scheduleRefresh)
  window.addEventListener('scroll', scheduleRefresh, true)
  window.visualViewport?.addEventListener('resize', scheduleRefresh)
  window.visualViewport?.addEventListener('scroll', scheduleRefresh)
})

onBeforeUnmount(() => {
  endDrag()
  window.cancelAnimationFrame(animationFrame)
  observer?.disconnect()
  window.removeEventListener('resize', scheduleRefresh)
  window.removeEventListener('scroll', scheduleRefresh, true)
  window.visualViewport?.removeEventListener('resize', scheduleRefresh)
  window.visualViewport?.removeEventListener('scroll', scheduleRefresh)
})
</script>

<template>
  <section ref="panel" class="board-target-window" :class="{ 'is-dragging': dragging }" :style="panelStyle" :data-target-side="side">
    <header class="battle-prompt__head battle-prompt__handle" @pointerdown="startDrag" @pointermove="moveDrag" @pointerup="endDrag" @pointercancel="endDrag" @lostpointercapture="endDrag">
      <slot name="head" />
    </header>
    <slot />
  </section>
</template>

<style scoped>
.board-target-window.board-target-window {
  position: fixed;
  right: auto;
  bottom: auto;
  width: min(var(--board-target-width, 460px), var(--board-target-available-width));
  max-height: var(--board-target-available-height);
  overflow: auto;
  margin: 0;
  transform: none;
  z-index: 80;
}
.board-target-window [class~='battle-prompt__handle'] { touch-action: none; }
</style>
