import type { SkinTier } from './skinManifest'
import type { SkinFaceContext, SkinMotionLevel } from './skinMotion'

export interface SkinAnimationOptions {
  element: HTMLElement
  tier: SkinTier
  context?: SkinFaceContext
  reducedMotion?: boolean
  /** Canvas中单张牌是否仍在可见区域；默认还会观察element的屏幕可见性。 */
  visible?: boolean
  onFrame(timeMs: number, level: SkinMotionLevel): void
  onLevelChange?(level: SkinMotionLevel): void
}
type Update = Partial<Pick<SkinAnimationOptions, 'context' | 'reducedMotion' | 'visible'>>
interface Entry {
  options: SkinAnimationOptions
  id: number
  visible: boolean
  hover: number
  focus: number
  level: SkinMotionLevel
  elapsed: number
  last?: number
  paint?: number
  observer?: IntersectionObserver
  clean(): void
}

const entries = new Set<Entry>()
let order = 0, attention = 0
let frameId: number | undefined
let media: MediaQueryList | undefined
let mutation: MutationObserver | undefined
let listening = false
const FRAME_MS = 1000 / 30

function motionOff() {
  return media?.matches === true || document.documentElement?.dataset.motion === 'reduced'
}
function active(entry: Entry) {
  return entry.visible && entry.options.visible !== false && !entry.options.reducedMotion && !motionOff() && !document.hidden
}
function rank(entry: Entry) {
  return (entry.hover || entry.focus ? 1e9 + Math.max(entry.hover, entry.focus) * 1000 : 0)
    + (entry.options.context === 'reveal' ? 1e6 : 0) + entry.id
}

function refresh() {
  const candidates = [...entries].filter((entry) => active(entry) && entry.options.tier === 'limited')
  const full = candidates.sort((a, b) => rank(b) - rank(a))[0]
  entries.forEach((entry) => {
    const next: SkinMotionLevel = !active(entry) ? 'static' : entry === full ? 'full' : 'subtle'
    if (next !== entry.level) {
      entry.level = next
      if (next === 'static') entry.last = undefined
      entry.options.onLevelChange?.(next)
      if (next === 'static' && entry.visible && entry.options.visible !== false && !document.hidden) entry.options.onFrame(entry.elapsed, 'static')
    }
  })
  schedule()
}

function schedule() {
  const running = [...entries].some((entry) => entry.level !== 'static')
  if (!running && frameId !== undefined) {
    cancelAnimationFrame(frameId); frameId = undefined
  } else if (running && frameId === undefined) frameId = requestAnimationFrame(tick)
}
function tick(now: number) {
  frameId = undefined
  entries.forEach((entry) => {
    if (entry.level === 'static') return
    if (entry.paint !== undefined && now - entry.paint < FRAME_MS - .3) return
    entry.elapsed += entry.last === undefined ? 0 : Math.max(0, Math.min(100, now - entry.last))
    entry.last = now; entry.paint = now
    entry.options.onFrame(entry.elapsed, entry.level)
  })
  schedule()
}

function install() {
  if (listening || typeof document === 'undefined' || typeof window === 'undefined') return
  listening = true
  media = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  media?.addEventListener('change', refresh)
  document.addEventListener('visibilitychange', refresh)
  if (typeof MutationObserver !== 'undefined' && document.documentElement) {
    mutation = new MutationObserver(refresh)
    mutation.observe(document.documentElement, { attributes: true, attributeFilter: ['data-motion'] })
  }
}
function uninstall() {
  if (!listening || entries.size) return
  if (frameId !== undefined) cancelAnimationFrame(frameId)
  frameId = undefined
  media?.removeEventListener('change', refresh); media = undefined
  mutation?.disconnect(); mutation = undefined
  document.removeEventListener('visibilitychange', refresh)
  listening = false
}

/** 所有DOM和Canvas宿主共享一个30fps时钟；悬停/聚焦优先，其次揭示、最新限定。 */
export function registerSkinAnimation(options: SkinAnimationOptions) {
  if (typeof document === 'undefined' || typeof requestAnimationFrame === 'undefined') {
    options.onLevelChange?.('static')
    return { update(_next: Update) {}, dispose() {} }
  }
  install()
  const element = options.element
  const entry: Entry = { options: { ...options }, id: ++order, visible: typeof IntersectionObserver === 'undefined', hover: 0, focus: 0, level: 'static', elapsed: 0, clean() {} }
  const enter = () => { entry.hover = ++attention; refresh() }
  const leave = () => { entry.hover = 0; refresh() }
  const focus = () => { entry.focus = ++attention; refresh() }
  const blur = (event: FocusEvent) => { if (!element.contains(event.relatedTarget as Node | null)) { entry.focus = 0; refresh() } }
  element.addEventListener('pointerenter', enter); element.addEventListener('pointerleave', leave)
  element.addEventListener('focusin', focus); element.addEventListener('focusout', blur)
  entry.clean = () => {
    entry.observer?.disconnect()
    element.removeEventListener('pointerenter', enter); element.removeEventListener('pointerleave', leave)
    element.removeEventListener('focusin', focus); element.removeEventListener('focusout', blur)
  }
  entries.add(entry)
  if (typeof IntersectionObserver !== 'undefined') {
    entry.observer = new IntersectionObserver((changes) => {
      entry.visible = changes.some((change) => change.isIntersecting && change.intersectionRatio > 0)
      refresh()
    }, { threshold: [0, .01] })
    entry.observer.observe(element)
  }
  // 初始静态也通知宿主，避免沿用上一张牌的画布。
  options.onLevelChange?.('static')
  refresh()
  let disposed = false
  return {
    update(next: Update) {
      if (disposed) return
      Object.assign(entry.options, next); refresh()
    },
    dispose() {
      if (disposed) return
      disposed = true; entry.clean(); entries.delete(entry); refresh(); uninstall()
    },
  }
}
