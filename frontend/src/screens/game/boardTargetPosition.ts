import type { Point } from './view'

export type BoardTargetSide = 'self' | 'opponent'
export type BoardTargetPositions = Partial<Record<BoardTargetSide, Point>>
type Bounds = { left: number; top: number; right: number; bottom: number }
type Size = { width: number; height: number }

const SIDE_GAP = 12
const STORAGE_KEY = 'battle_board_target_positions'

export function createBoardTargetPositions(): BoardTargetPositions {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}')
    const positions: BoardTargetPositions = {}
    for (const side of ['self', 'opponent'] as const) {
      const point = saved?.[side]
      if (Number.isFinite(point?.x) && Number.isFinite(point?.y)) positions[side] = point
    }
    return positions
  } catch {
    return {}
  }
}

export function saveBoardTargetPosition(positions: BoardTargetPositions, side: BoardTargetSide, point: Point): void {
  positions[side] = point
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(positions))
  } catch {
    // 浏览器禁用存储时，同一局内仍保留拖动位置。
  }
}

export function clampBoardTargetPosition(point: Point, panel: Size, viewport: Bounds): Point {
  return {
    x: Math.max(viewport.left, Math.min(point.x, viewport.right - panel.width)),
    y: Math.max(viewport.top, Math.min(point.y, viewport.bottom - panel.height)),
  }
}

export function locateBoardTarget(panel: Size, viewport: Bounds, board?: Bounds): Point {
  if (!board) return { x: viewport.left, y: viewport.top }

  const centeredX = (board.left + board.right - panel.width) / 2
  const candidates = [
    { x: board.right + SIDE_GAP, y: board.top },
    { x: board.left - panel.width - SIDE_GAP, y: board.top },
    { x: centeredX, y: board.bottom + SIDE_GAP },
    { x: centeredX, y: board.top - panel.height - SIDE_GAP },
  ]
  let best = clampBoardTargetPosition(candidates[0], panel, viewport)
  let bestOverlap = Number.POSITIVE_INFINITY
  for (const candidate of candidates) {
    const point = clampBoardTargetPosition(candidate, panel, viewport)
    const overlapWidth = Math.max(0, Math.min(point.x + panel.width, board.right) - Math.max(point.x, board.left))
    const overlapHeight = Math.max(0, Math.min(point.y + panel.height, board.bottom) - Math.max(point.y, board.top))
    const overlap = overlapWidth * overlapHeight
    if (overlap < bestOverlap) {
      best = point
      bestOverlap = overlap
    }
    if (overlap === 0) break
  }
  return best
}
