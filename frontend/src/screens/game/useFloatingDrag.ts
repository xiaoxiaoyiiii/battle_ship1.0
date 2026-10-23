import { onBeforeUnmount, ref, type Ref } from 'vue'

export interface FloatingDragState {
  x: number
  y: number
  dragging: boolean
}

/**
 * 浮动窗拖动（对应原 main `static/game.js` 的 `makeFloatingDraggable`）。
 *
 * 原实现用 mousedown/mousemove 直接改 style.left/top，并在紧凑档整体禁用拖动
 * （`window.__adaptiveDragDisabled`，触屏拖一个贴边窗口只会和页面滚动抢手势）。
 * 这里保持同样的边界处理：不拖出视口、不覆盖顶部导航，紧凑档由调用方不挂载。
 */
export function useFloatingDrag(options: {
  handle: Ref<HTMLElement | null>
  panel: Ref<HTMLElement | null>
  initial: { x: number; y: number }
  minY?: number
}) {
  const state = ref<FloatingDragState>({ x: options.initial.x, y: options.initial.y, dragging: false })
  let startX = 0
  let startY = 0
  let originX = 0
  let originY = 0

  function clamp(nextX: number, nextY: number): { x: number; y: number } {
    const panel = options.panel.value
    const width = panel?.offsetWidth ?? 280
    const height = panel?.offsetHeight ?? 200
    const maxX = Math.max(0, window.innerWidth - width - 8)
    const maxY = Math.max(0, window.innerHeight - height - 8)
    const minY = options.minY ?? 72
    return {
      x: Math.min(Math.max(0, nextX), maxX),
      y: Math.min(Math.max(minY, nextY), maxY),
    }
  }

  function onPointerDown(event: PointerEvent): void {
    if (event.button !== 0) return
    const target = event.target as HTMLElement | null
    // 标题栏上的按钮（关闭等）不应触发拖动
    if (target?.closest('button, a, input, textarea, select')) return
    state.value.dragging = true
    startX = event.clientX
    startY = event.clientY
    originX = state.value.x
    originY = state.value.y
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    event.preventDefault()
  }

  function onPointerMove(event: PointerEvent): void {
    if (!state.value.dragging) return
    const next = clamp(originX + (event.clientX - startX), originY + (event.clientY - startY))
    state.value = { ...state.value, x: next.x, y: next.y }
  }

  function onPointerUp(): void {
    state.value = { ...state.value, dragging: false }
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
  }

  function reset(): void {
    const next = clamp(options.initial.x, options.initial.y)
    state.value = { x: next.x, y: next.y, dragging: false }
  }

  onBeforeUnmount(() => {
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
  })

  return { state, onPointerDown, reset }
}
