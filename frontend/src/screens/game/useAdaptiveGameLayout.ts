import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 对局界面自适应布局（移植原 main `static/adaptive_layout.js` 的判据）。
 *
 * 原实现跑在 Flask 模板上，用 MutationObserver + rAF 反复测量 `.boards-container`
 * 再写 `--board-size`。这里改成纯计算：模式与棋盘尺寸都由视口预算推出，不读取自己
 * 刚写下的结果，避免“量测 → 写入 → 再量测”的反馈环（原实现靠 rAF 抖动把环压住）。
 *
 * 判据与原文件保持一致：
 * - 宽屏：`innerWidth >= 1200 && innerHeight >= 700`
 * - `MIN_CELL = 40`（触摸目标下限），`MIN_BOARD = 6 * 40 + 38 = 278`
 * - 舞台宽 >= 2 * MIN_BOARD + 4 → 两块并排；否则舞台高够 2 块 → 上下叠；否则标签切换
 * - 棋盘边长：并排 `min((W-4)/2, H) - 26`，叠放 `min(W, (H-4)/2) - 26`，标签 `min(W, H) - 26`
 */
export const WIDE_MIN_W = 1200
export const WIDE_MIN_H = 700
export const TIGHT_MAX_H = 480
export const MIN_CELL = 40
export const MIN_BOARD = MIN_CELL * 6 + 38

export type BoardMode = 'side' | 'stack' | 'tabs'

/** 内容列最大宽度（对应原 `.game-content { max-width: 900px }`）。 */
const CONTENT_MAX_W = 900
/** 并排两块棋盘之间的间距。 */
const BOARD_GAP = 32
/** 棋盘容器内边距 + 棋盘自身内边距的保守合计（原实现里的 `- 26` 与 `+38` 同源）。 */
const BOARD_CHROME = 26
/** HUD + 场地条 + 手牌条 + 主行动条 + 页面内边距的保守合计（紧凑档垂直预算）。 */
const COMPACT_CHROME = 404
const TIGHT_CHROME = 300
/** 顶部导航高度（与 main-ui.css 的 `.app-nav` 一致）。 */
const NAV_H = 64
/** 横屏紧凑档右列宽度（HUD / 场地条 / 手牌 / 主行动条）。 */
const TIGHT_PANEL_W = 300

export function useAdaptiveGameLayout() {
  const width = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
  const height = ref(typeof window === 'undefined' ? 900 : window.innerHeight)
  /**
   * HUD / 场地条 / 标签 / 手牌 / 主行动条的实测高度合计（由调用方量好传进来）。
   * 这几块的高度与棋盘尺寸无关，所以“量它们、算棋盘”不会形成反馈环；
   * 比写死预算更准，也是原 main 用 clientHeight 实测的等价做法。
   */
  const chrome = ref(0)
  function setChrome(px: number): void {
    chrome.value = Math.max(0, Math.round(px))
  }

  function read(): void {
    if (typeof window === 'undefined') return
    width.value = window.innerWidth
    height.value = window.innerHeight
  }

  const compact = computed(() => !(width.value >= WIDE_MIN_W && height.value >= WIDE_MIN_H))
  const tight = computed(() => compact.value && height.value <= TIGHT_MAX_H)

  /** 舞台（两块棋盘所在的那一列）可用的宽高预算。 */
  const stage = computed(() => {
    // 横屏紧凑档是「棋盘左列 + 信息右列」的两列布局，宽度要扣掉右列。
    const panelW = tight.value ? TIGHT_PANEL_W : 0
    const w = Math.min(width.value, CONTENT_MAX_W) - 32 - panelW
    const used = chrome.value || (tight.value ? TIGHT_CHROME : COMPACT_CHROME)
    return { w: Math.max(0, w), h: Math.max(0, height.value - NAV_H - used) }
  })

  const mode = computed<BoardMode>(() => {
    if (!compact.value) return 'side'
    // 横屏矮视口由网格布局把棋盘放进左列，棋盘本身是单块。
    if (tight.value) return 'tabs'
    const { w, h } = stage.value
    if (w >= MIN_BOARD * 2 + 4) return 'side'
    if (h >= MIN_BOARD * 2 + 4) return 'stack'
    return 'tabs'
  })

  const boardSize = computed(() => {
    if (!compact.value) return 0 // 宽屏由 CSS 的 clamp 决定，和原 main 一样不写死
    if (tight.value) {
      // 横屏紧凑档：棋盘独占左列，高度预算 = 视口高 - 导航 - 内边距。
      const leftW = width.value - TIGHT_PANEL_W - 20
      const avail = Math.min(leftW, height.value - NAV_H - 20)
      return Math.max(MIN_BOARD, Math.floor(avail - BOARD_CHROME))
    }
    const { w, h } = stage.value
    const raw =
      mode.value === 'side'
        ? Math.min((w - BOARD_GAP) / 2, h)
        : mode.value === 'stack'
          ? Math.min(w, (h - 4) / 2)
          : Math.min(w, h)
    // 装不下就保 main 的最小可点棋盘（278px），超出部分交给屏内滚动——
    // 宁可滚动，也不把格子缩到点不准（原 adaptive_layout.js 的 MIN_CELL = 40 同口径）。
    return Math.max(MIN_BOARD, Math.floor(raw - BOARD_CHROME))
  })

  /** 紧凑档里棋盘小于最小可点尺寸时，说明这一档得压缩 HUD 并允许屏内滚动。 */
  /** 紧凑档装不下最小棋盘时：压缩 HUD 并允许屏内滚动（原 main 的 layout-dense）。 */
  const dense = computed(() => {
    if (!compact.value || tight.value) return false
    const { w, h } = stage.value
    const raw = mode.value === 'side' ? Math.min((w - BOARD_GAP) / 2, h) : Math.min(w, h)
    return raw - BOARD_CHROME < MIN_BOARD
  })

  onMounted(() => {
    read()
    window.addEventListener('resize', read)
    window.addEventListener('orientationchange', read)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', read)
    window.removeEventListener('orientationchange', read)
  })

  return { width, height, chrome, setChrome, compact, tight, dense, mode, boardSize }
}

export type AdaptiveGameLayout = ReturnType<typeof useAdaptiveGameLayout>
