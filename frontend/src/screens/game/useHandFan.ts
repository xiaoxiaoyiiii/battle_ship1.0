import { computed, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/**
 * 手牌扇形布局（移植原 `static/game.js` 的 `layoutHand`）。
 *
 * 原实现在窗口尺寸/张数变化时直接写行内样式；这里用「测量可用宽 → 计算 → 由模板绑定」
 * 的同一套算术，常量与原文件一致：
 * - 卡高 186（不低于 136），卡间距 10，旋转安全边距 20
 * - 每张至少露 44px 可点，空间不足时只在手牌条内横向滚动
 * - 张角上限 0.1rad，重叠排布不旋转（`hand-tight`），只做下沉
 */
export const HAND_CARD_W_MAX = 132
export const HAND_CARD_W_MIN = 96
export const HAND_CARD_H = 186
export const HAND_CARD_H_MIN = 136
export const HAND_TAP_MIN = 44
export const HAND_GAP = 10
export const HAND_SAFE = 20
export const HAND_FAN_MAX_RAD = 0.1
const HAND_DESC_LINE_PX = 0.62 * 16 * 1.35

export interface HandCardLayout {
  marginLeft: string
  rot: string
  drop: string
}

export interface HandLayout {
  cardW: number
  cardH: number
  descLines: number
  fan: boolean
  tight: boolean
  scrollable: boolean
  cards: HandCardLayout[]
}

export function useHandFan(options: {
  target: Ref<HTMLElement | null>
  count: Ref<number>
  selectedIndex: Ref<number>
  enabled: Ref<boolean>
}) {
  const available = ref(0)
  let observer: ResizeObserver | null = null

  function measure(): void {
    const el = options.target.value
    available.value = el ? el.getBoundingClientRect().width : 0
  }

  onMounted(() => {
    measure()
    if (typeof ResizeObserver !== 'undefined' && options.target.value) {
      observer = new ResizeObserver(measure)
      observer.observe(options.target.value)
    }
    window.addEventListener('resize', measure)
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
    window.removeEventListener('resize', measure)
  })

  const layout = computed<HandLayout>(() => {
    const n = options.count.value
    const empty: HandLayout = {
      cardW: HAND_CARD_W_MAX,
      cardH: HAND_CARD_H,
      descLines: 5,
      fan: false,
      tight: false,
      scrollable: false,
      cards: [],
    }
    // 紧凑档交给 CSS 的固定小卡（原实现同样“compact 时不插手”）。
    if (!options.enabled.value || n === 0) return empty
    const width = available.value
    if (!Number.isFinite(width) || width < HAND_CARD_W_MIN + HAND_SAFE) return empty

    const avail = Math.max(0, width - HAND_SAFE)
    let w = Math.min(HAND_CARD_W_MAX, (avail - HAND_GAP * (n - 1)) / n)
    let step: number
    if (w >= HAND_CARD_W_MIN) {
      step = w + HAND_GAP
    } else {
      w = HAND_CARD_W_MIN
      step = n > 1 ? (avail - w) / (n - 1) : w
      if (step < HAND_TAP_MIN) {
        step = HAND_TAP_MIN
      }
    }
    w = Math.floor(Math.max(HAND_CARD_W_MIN, w))
    step = Math.floor(step)
    const overlapping = step < w + HAND_GAP - 1
    const h = HAND_CARD_H

    // 张数过多时保留可点宽度，让手牌条内部滚动，不再把卡压成细缝。
    const pitches = new Array<number>(Math.max(0, n - 1)).fill(step)
    let total = w
    for (const pitch of pitches) total += pitch
    const scrollable = total > avail

    const mid = (n - 1) / 2
    const cards: HandCardLayout[] = []
    for (let i = 0; i < n; i += 1) {
      const norm = mid > 0 ? Math.abs(i - mid) / mid : 0
      const drop = `${Math.round(norm * (overlapping ? 4 : 6))}px`
      if (overlapping || n <= 1) {
        cards.push({ marginLeft: i === 0 ? '' : `${pitches[i - 1] - w}px`, rot: '', drop })
      } else {
        const spread = Math.min(0.2 / Math.max(n, 1), (HAND_FAN_MAX_RAD * 2) / Math.max(n - 1, 1))
        cards.push({
          marginLeft: i === 0 ? '' : `${pitches[i - 1] - w}px`,
          rot: `${(i - mid) * spread}rad`,
          drop,
        })
      }
    }

    return {
      cardW: w,
      cardH: h,
      descLines: Math.max(3, Math.min(7, Math.floor((h - 72) / HAND_DESC_LINE_PX))),
      fan: n > 1,
      tight: overlapping,
      scrollable,
      cards,
    }
  })

  return { layout, measure }
}
