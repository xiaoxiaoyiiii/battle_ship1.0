import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { mobileBattleLayout } from './mobileBattleLayout'

export const WIDE_MIN_W = 1200
export const WIDE_MIN_H = 700
export const TIGHT_MAX_H = 600
export const MIN_CELL = 40
export const MIN_BOARD = MIN_CELL * 6 + 38
export type BoardMode = 'side' | 'stack' | 'tabs'

export function useAdaptiveGameLayout() {
  const width = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
  const height = ref(typeof window === 'undefined' ? 900 : window.innerHeight)
  const navHeight = ref(width.value > height.value ? 36 : 44)
  const compact = computed(() => !(width.value >= WIDE_MIN_W && height.value >= WIDE_MIN_H))
  // 保留调用接口；内容量测不能再改变手机棋盘，避免点击后发生布局反馈。
  const chrome = ref(0)
  function setChrome(px: number) { chrome.value = Math.max(0, Math.round(px)) }
  function read() {
    width.value = window.innerWidth
    height.value = window.innerHeight
    const shell = document.querySelector('.app-shell')
    const value = shell ? Number.parseFloat(getComputedStyle(shell).getPropertyValue('--app-nav-h')) : NaN
    const actual = document.querySelector('.app-nav')?.getBoundingClientRect().height || 0
    // 实际栏高包含刘海安全区；壳层尚未提供变量时也能按现有导航留出空间。
    navHeight.value = Math.max(actual, Number.isFinite(value) ? value : 56)
  }
  const mobile = computed(() => mobileBattleLayout(width.value, height.value, navHeight.value))
  const tight = computed(() => compact.value && mobile.value.landscape)
  const mode = computed<BoardMode>(() => compact.value ? mobile.value.mode : 'side')
  const boardSize = computed(() => compact.value ? mobile.value.boardSize : 0)
  const dense = computed(() => compact.value && !tight.value && height.value < 740)
  onMounted(() => {
    read()
    window.addEventListener('resize', read)
    window.addEventListener('orientationchange', read)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('resize', read)
    window.removeEventListener('orientationchange', read)
  })
  return { width, height, chrome, setChrome, compact, tight, dense, mode, boardSize, mobile }
}
export type AdaptiveGameLayout = ReturnType<typeof useAdaptiveGameLayout>
