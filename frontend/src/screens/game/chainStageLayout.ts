/**
 * 连锁演出的构图规划（纯几何，不含绘制与时间轴）。
 *
 * 原实现把 650/1100 宽的横向舞台整体等比缩到手机视口，竖屏时当前卡只有
 * 约 147px 宽；这里改成按「可用宽高 + 安全区」直接给出像素级构图：
 * - 竖屏：当前卡居中放大，上一张与下一张沿斜向错落排在它上方；
 * - 横屏：保留横向接链舞台，陪衬卡在左右两侧展开。
 * 既有的时间轴、音效、结算顺序仍由 chainAnimation.ts / store 决定。
 */

export interface ChainStageInsets {
  top?: number
  right?: number
  bottom?: number
  left?: number
}

export interface ChainStageCard {
  x: number
  y: number
  w: number
  angle: number
}

export interface ChainStagePlan {
  mode: 'portrait' | 'landscape'
  width: number
  height: number
  /** 相对桌面基准（260px 主卡）的缩放，用于线宽/字号。 */
  scale: number
  safe: { top: number; right: number; bottom: number; left: number }
  /** 实际参与绘制的卡牌数（当前卡 + 陪衬卡）。 */
  shown: number
  current: ChainStageCard
  companions: ChainStageCard[]
  number: { x: number; y: number; size: number }
  title: { x: number; y: number; size: number }
  /** 入场飞行的起点：p2 从上方、p1 从下方飞入。 */
  entry: { p1: ChainStageCard; p2: ChainStageCard }
}

const clamp = (value: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, value))

const safeNumber = (value: number | undefined): number =>
  Number.isFinite(value) ? Math.max(0, value as number) : 0

export function planChainStage(input: {
  width: number
  height: number
  count: number
  insets?: ChainStageInsets
}): ChainStagePlan {
  const width = Math.max(1, input.width)
  const height = Math.max(1, input.height)
  const insets = input.insets ?? {}
  const safe = {
    top: safeNumber(insets.top),
    right: safeNumber(insets.right),
    bottom: safeNumber(insets.bottom),
    left: safeNumber(insets.left),
  }
  const availW = Math.max(120, width - safe.left - safe.right)
  const availH = Math.max(120, height - safe.top - safe.bottom)
  // 竖屏以「高度明显大于宽度」判定，横屏手机与桌面都走横向舞台。
  const mode: ChainStagePlan['mode'] = availH > availW * 1.05 ? 'portrait' : 'landscape'
  const count = Math.max(1, Math.floor(input.count))

  if (mode === 'portrait') {
    const cardW = clamp(availW * 0.62, 150, 300)
    const cardH = cardW * 1.5
    const topMargin = safe.top + 8
    const centerX = safe.left + availW / 2
    const centerY = topMargin + (availH - 8) * 0.58
    const companionW = cardW * 0.42
    const companionH = companionW * 1.5
    // 只在上方空余里安排陪衬卡，装不下就少画几张，保证当前卡与编号不被挤。
    const topSpace = Math.max(0, centerY - cardH / 2 - topMargin - 6)
    const maxCompanions = Math.max(
      0,
      Math.min(3, count - 1, Math.floor((topSpace - companionH * 0.5) / (companionH * 0.42)) + 1),
    )
    const step = maxCompanions > 0 ? Math.min(companionH * 0.42, topSpace / maxCompanions) : 0
    const companions: ChainStageCard[] = []
    for (let i = 1; i <= maxCompanions; i += 1) {
      const y = clamp(
        centerY - cardH * 0.5 - step * i + companionH * 0.25,
        topMargin + companionH / 2,
        safe.top + availH,
      )
      const x = clamp(
        centerX + (i % 2 ? 1 : -1) * cardW * 0.34,
        safe.left + companionW / 2,
        width - safe.right - companionW / 2,
      )
      companions.push({ x, y, w: companionW, angle: (i % 2 ? 1 : -1) * 0.12 })
    }
    return {
      mode,
      width,
      height,
      scale: cardW / 260,
      safe,
      shown: 1 + companions.length,
      current: { x: centerX, y: centerY, w: cardW, angle: 0 },
      companions,
      number: {
        x: centerX + cardW * 0.42,
        y: centerY + cardH * 0.34,
        size: cardW * 0.4,
      },
      title: { x: centerX, y: centerY - cardH * 0.62, size: cardW * 0.3 },
      entry: {
        p1: { x: centerX - availW * 0.5, y: height + cardH, w: cardW * 0.7, angle: 0.45 },
        p2: { x: centerX + availW * 0.5, y: -cardH, w: cardW * 0.7, angle: -0.5 },
      },
    }
  }

  const cardW = clamp(Math.min(availH * 0.42, availW / (4 * 0.95)), 130, 260)
  const topMargin = safe.top + 8
  const centerX = safe.left + availW / 2
  const centerY = topMargin + (availH - 8) * 0.54
  const gap = cardW * 0.92
  const companionW = cardW * 0.48
  const maxCompanions = Math.max(0, Math.min(4, count - 1))
  const companions: ChainStageCard[] = []
  for (let i = 1; i <= maxCompanions; i += 1) {
    const side = i % 2 ? 1 : -1
    const ring = Math.ceil(i / 2)
    const x = clamp(
      centerX + side * gap * ring,
      safe.left + companionW / 2,
      width - safe.right - companionW / 2,
    )
    companions.push({ x, y: centerY - cardW * 0.1, w: companionW, angle: side * -0.08 })
  }
  return {
    mode,
    width,
    height,
    scale: cardW / 260,
    safe,
    shown: 1 + companions.length,
    current: { x: centerX, y: centerY, w: cardW, angle: 0 },
    companions,
    number: { x: centerX + cardW * 0.62, y: centerY + cardW * 0.55, size: cardW * 0.34 },
    title: { x: centerX, y: centerY - cardW * 0.62, size: cardW * 0.26 },
    entry: {
      p1: { x: centerX - availW * 0.45, y: height + cardW * 1.5, w: cardW, angle: 0.45 },
      p2: { x: centerX + availW * 0.45, y: -cardW * 1.5, w: cardW, angle: -0.5 },
    },
  }
}
