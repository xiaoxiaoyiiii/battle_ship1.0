import { nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

export interface FloatingDragState {
  x: number
  y: number
  dragging: boolean
}

function readSaved(key?: string): { x: number; y: number } | null {
  if (!key) return null
  try {
    const raw = JSON.parse(window.localStorage.getItem(key) || 'null') as { left?: unknown; top?: unknown } | null
    if (raw && Number.isFinite(raw.left) && Number.isFinite(raw.top)) {
      return { x: Number(raw.left), y: Number(raw.top) }
    }
  } catch {
    // 存档损坏就当没有
  }
  return null
}

function writeSaved(key: string | undefined, x: number, y: number): void {
  if (!key) return
  try {
    window.localStorage.setItem(key, JSON.stringify({ left: x, top: y }))
  } catch {
    // 隐私模式写不了就算了，位置只在本次有效
  }
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
  /** 位置记在 localStorage（原 main 的 game_log_pos / in_game_chat_pos）；没给就只在内存里。 */
  storageKey?: string
}) {
  const state = ref<FloatingDragState>({ x: options.initial.x, y: options.initial.y, dragging: false })
  const saved = readSaved(options.storageKey)
  if (saved) state.value = { x: saved.x, y: saved.y, dragging: false }
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
    writeSaved(options.storageKey, state.value.x, state.value.y)
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
  }

  function reset(): void {
    const next = clamp(options.initial.x, options.initial.y)
    state.value = { x: next.x, y: next.y, dragging: false }
  }

  /** 视口变化不是用户的意图：越界就拉回屏内，屏内的位置原样保留。 */
  function reclamp(): void {
    if (state.value.dragging) return
    const next = clamp(state.value.x, state.value.y)
    if (next.x !== state.value.x || next.y !== state.value.y) {
      state.value = { ...state.value, x: next.x, y: next.y }
    }
  }

  onMounted(() => {
    window.addEventListener('resize', reclamp)
    window.addEventListener('orientationchange', reclamp)
    void nextTick(reclamp)
  })
  // 面板按布局档位挂载/卸载：重新出现时按它真实尺寸再夹一次
  watch(options.panel, (el) => {
    if (el) void nextTick(reclamp)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', reclamp)
    window.removeEventListener('orientationchange', reclamp)
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', onPointerUp)
  })

  return { state, onPointerDown, reset }
}
