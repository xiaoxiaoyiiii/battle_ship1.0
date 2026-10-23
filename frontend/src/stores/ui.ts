import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { SOCKET_ERROR_CODES } from '../socket/events.gen'

/**
 * Shell-wide UI state (ticket #42): the three themes, the reduced-motion
 * preference, the single-overlay stack and the global notice queue.
 *
 * The store is the only place that touches localStorage and <html> attributes,
 * so a theme flip reaches every screen that uses the design tokens, and the
 * overlay contract (one layer at a time, match-found above everything) is
 * enforced in one place instead of by z-index guesses in each component.
 */

export type ThemeName = 'chart' | 'journal' | 'night'
export type MotionPreference = 'auto' | 'reduced'
export type ContrastPreference = 'auto' | 'high'
export type FontScale = 'normal' | 'large' | 'xlarge'
export type AuthRequestMode = 'login' | 'register'
export type ConnectionState = 'online' | 'offline'

const THEME_KEY = 'battleship.ui.theme'
const MOTION_KEY = 'battleship.ui.motion'
const CONTRAST_KEY = 'battleship.ui.contrast'
const FONT_SCALE_KEY = 'battleship.ui.fontScale'
const ACCENT_KEY = 'battleship.ui.accent'

export const FONT_SCALE_LABELS: Record<FontScale, string> = {
  normal: '标准',
  large: '大',
  xlarge: '特大',
}

const THEMES: ThemeName[] = ['chart', 'journal', 'night']

export const THEME_LABELS: Record<ThemeName, string> = {
  chart: '航图',
  journal: '航海日志',
  night: '夜航',
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

function readTheme(): ThemeName {
  try {
    const raw = storage()?.getItem(THEME_KEY)
    if (raw && (THEMES as string[]).includes(raw)) return raw as ThemeName
  } catch {
    // Private mode: fall through to the default.
  }
  // No stored choice: the system colour scheme decides the first default.
  try {
    if (typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: light)').matches) {
      return 'journal'
    }
  } catch {
    // Fall through to the chart theme.
  }
  return 'chart'
}

function readMotion(): MotionPreference {
  try {
    return storage()?.getItem(MOTION_KEY) === 'reduced' ? 'reduced' : 'auto'
  } catch {
    return 'auto'
  }
}

function readContrast(): ContrastPreference {
  try {
    return storage()?.getItem(CONTRAST_KEY) === 'high' ? 'high' : 'auto'
  } catch {
    return 'auto'
  }
}

function readFontScale(): FontScale {
  try {
    const raw = storage()?.getItem(FONT_SCALE_KEY)
    if (raw === 'large' || raw === 'xlarge') return raw
  } catch {
    // Private mode: fall through to the default.
  }
  return 'normal'
}

/** Apply every persisted appearance preference before the app mounts (main.ts). */
export function applyStoredTheme(): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.theme = readTheme()
  if (readMotion() === 'reduced') root.dataset.motion = 'reduced'
  else delete root.dataset.motion
  if (readContrast() === 'high') root.dataset.contrast = 'high'
  else delete root.dataset.contrast
  const scale = readFontScale()
  if (scale !== 'normal') root.dataset.fontScale = scale
  else delete root.dataset.fontScale
}

export interface NoticeInput {
  /** Stable code used for the 3-second dedupe and for the error mapping. */
  code: string
  message?: string
  tone?: 'info' | 'success' | 'warning' | 'error'
  /** What the player can do next; shown under the message for failures. */
  next?: string
  /** Milliseconds before the notice leaves the queue. */
  ttl?: number
}

export interface Notice {
  id: number
  code: string
  message: string
  next: string
  tone: 'info' | 'success' | 'warning' | 'error'
  createdAt: number
}

/**
 * Player language for the backend's stable socket codes (ticket #52).
 *
 * The keys are constrained to the generated catalog (`SOCKET_ERROR_CODES`), so
 * a code the backend does not define cannot be invented here. A missing mapping
 * — and any code outside the catalog — falls back to the server message, never
 * to a raw technical string.
 */
type SocketErrorCode = (typeof SOCKET_ERROR_CODES)[number]

const ERROR_LANGUAGE: Partial<Record<SocketErrorCode, { message: string; next?: string }>> = {
  already_queued: { message: '你已经在匹配队列里了。', next: '等待匹配，或先取消排队。' },
  room_not_found: { message: '房间已经不存在了。', next: '回到大厅看看其他房间。' },
  room_full: { message: '这个房间已经坐满了。', next: '换一桌，或自己开一间。' },
  identity_failed: { message: '登录状态已经失效。', next: '重新登录后再试。' },
  chat_too_fast: { message: '发言太快了。', next: '等一两秒再发。' },
  spectate_denied: { message: '这一局现在不能观战。', next: '回大厅看看其他进行中的对局。' },
}

export function errorLanguage(code: string, fallback = ''): { message: string; next: string } {
  if ((SOCKET_ERROR_CODES as readonly string[]).includes(code)) {
    const mapped = ERROR_LANGUAGE[code as SocketErrorCode]
    if (mapped) return { message: mapped.message, next: mapped.next || '' }
  }
  return { message: fallback || '操作没有成功。', next: fallback ? '' : '稍后重试，或刷新页面。' }
}

interface DialogEntry {
  id: string
  priority: number
}

function readAccent(): string {
  try {
    const value = storage()?.getItem(ACCENT_KEY) || ''
    return /^#[0-9a-fA-F]{6}$/.test(value) ? value.toLowerCase() : ''
  } catch {
    return ''
  }
}

export const useUiStore = defineStore('ui', () => {
  // ------------------------------------------------------------- theme ----
  const theme = ref<ThemeName>(readTheme())
  const motion = ref<MotionPreference>(readMotion())
  const contrast = ref<ContrastPreference>(readContrast())
  const fontScale = ref<FontScale>(readFontScale())

  function setTheme(next: ThemeName): void {
    theme.value = THEMES.includes(next) ? next : 'chart'
    if (typeof document !== 'undefined') document.documentElement.dataset.theme = theme.value
    try {
      storage()?.setItem(THEME_KEY, theme.value)
    } catch {
      // Preferences are best effort; the theme still applies for this session.
    }
  }

  function setMotion(next: MotionPreference): void {
    motion.value = next === 'reduced' ? 'reduced' : 'auto'
    if (typeof document !== 'undefined') {
      if (motion.value === 'reduced') document.documentElement.dataset.motion = 'reduced'
      else delete document.documentElement.dataset.motion
    }
    try {
      storage()?.setItem(MOTION_KEY, motion.value)
    } catch {
      // Best effort, same as the theme.
    }
  }

  function setContrast(next: ContrastPreference): void {
    contrast.value = next === 'high' ? 'high' : 'auto'
    if (typeof document !== 'undefined') {
      if (contrast.value === 'high') document.documentElement.dataset.contrast = 'high'
      else delete document.documentElement.dataset.contrast
    }
    try {
      storage()?.setItem(CONTRAST_KEY, contrast.value)
    } catch {
      // Best effort, same as the theme.
    }
  }

  function setFontScale(next: FontScale): void {
    fontScale.value = next === 'large' || next === 'xlarge' ? next : 'normal'
    if (typeof document !== 'undefined') {
      if (fontScale.value !== 'normal') document.documentElement.dataset.fontScale = fontScale.value
      else delete document.documentElement.dataset.fontScale
    }
    try {
      storage()?.setItem(FONT_SCALE_KEY, fontScale.value)
    } catch {
      // Best effort, same as the theme.
    }
  }

  /**
   * Ask for the app-level login overlay (ticket #44 listens for the window
   * event). Screens use this instead of linking to the dead /login route.
   */
  function requestLogin(mode: AuthRequestMode = 'login', reason = ''): void {
    if (typeof window === 'undefined') return
    window.dispatchEvent(new CustomEvent('bs:auth-required', { detail: { mode, reason } }))
  }

  // --------------------------------------------------------- connection ----
  // The one connection flag for the whole shell (spec §5). Every realtime
  // channel reports its socket here; the App banner and disable rules read it.
  const connection = ref<ConnectionState>('online')
  /** A reconnect that could not restore the seat keeps a persistent banner. */
  const connectionIssue = ref('')
  let droppedOnce = false

  function setConnection(online: boolean): void {
    const next: ConnectionState = online ? 'online' : 'offline'
    if (connection.value === next) return
    connection.value = next
    if (next === 'offline') {
      droppedOnce = true
      notify({ code: 'connection-offline', message: '连接中断，正在重连…', tone: 'warning', ttl: 15000 })
      return
    }
    if (droppedOnce) {
      droppedOnce = false
      notify({ code: 'connection-restored', message: '已恢复连接', tone: 'success' })
    }
  }

  function setConnectionIssue(message: string): void {
    connectionIssue.value = String(message ?? '').trim()
  }

  function clearConnectionIssue(): void {
    connectionIssue.value = ''
  }

  // ----------------------------------------------------------- overlays ----
  // Exactly one dialog is open. A new dialog may only replace one of a strictly
  // lower priority, so the match-found result can never be covered by the card
  // archive opened during matchmaking.
  const activeDialog = ref<DialogEntry | null>(null)
  const closeHandlers = new Map<string, () => void>()

  function registerDialogClose(id: string, close: () => void): void {
    closeHandlers.set(id, close)
  }

  function unregisterDialogClose(id: string): void {
    closeHandlers.delete(id)
  }

  function claimDialog(id: string, priority: number): boolean {
    const current = activeDialog.value
    if (!current) {
      activeDialog.value = { id, priority }
      return true
    }
    if (current.id === id) {
      current.priority = priority
      return true
    }
    if (priority <= current.priority) return false
    closeHandlers.get(current.id)?.()
    activeDialog.value = { id, priority }
    return true
  }

  function releaseDialog(id: string): void {
    if (activeDialog.value?.id === id) activeDialog.value = null
  }

  /** Route switches close every overlay: nothing stacks on the next screen. */
  function closeAllDialogs(): void {
    const ids = [...closeHandlers.keys()]
    for (const id of ids) closeHandlers.get(id)?.()
    activeDialog.value = null
  }

  /**
   * 主色（原 main 设置页的「主色选择器」）。空值表示跟随主题自带的强调色；
   * 选了具体颜色就写 `--role-action` 与它的柔和底，立刻在整站生效。
   */
  const accent = ref<string>(readAccent())
  function setAccent(next: string | null): void {
    const value = next && /^#[0-9a-fA-F]{6}$/.test(next) ? next.toLowerCase() : ''
    accent.value = value
    if (typeof document !== 'undefined') {
      const root = document.documentElement
      if (value) {
        root.style.setProperty('--role-action', value)
        root.style.setProperty('--role-action-soft', `color-mix(in srgb, ${value} 22%, transparent)`)
        root.dataset.accent = 'custom'
      } else {
        root.style.removeProperty('--role-action')
        root.style.removeProperty('--role-action-soft')
        delete root.dataset.accent
      }
    }
    try {
      if (value) storage()?.setItem(ACCENT_KEY, value)
      else storage()?.removeItem(ACCENT_KEY)
    } catch {
      // 主色只是外观偏好，存不下也不影响本次会话。
    }
  }

  // 恢复上次选的主色（首次进入时把存储值写回 CSS 变量）
  if (accent.value) setAccent(accent.value)

  /** 帮助弹层（玩法与段位）：导航「帮助」和头像菜单共用同一入口。 */
  const helpOpen = ref(false)
  function openHelp(): void {
    helpOpen.value = true
  }
  function closeHelp(): void {
    helpOpen.value = false
  }

  /** 好友面板（好友列表/申请/私聊）。 */
  const adminOpen = ref(false)
  const friendsOpen = ref(false)
  function openAdmin(): void {
    adminOpen.value = true
  }

  function closeAdmin(): void {
    adminOpen.value = false
  }

  function openFriends(): void {
    friendsOpen.value = true
  }
  function closeFriends(): void {
    friendsOpen.value = false
  }

  /** Exit confirmation for the immersive match screens. */
  const exitConfirmOpen = ref(false)
  function requestExit(): void {
    exitConfirmOpen.value = true
  }
  function cancelExit(): void {
    exitConfirmOpen.value = false
  }

  // ------------------------------------------------------------ notices ----
  const notices = ref<Notice[]>([])
  const lastByCode = new Map<string, number>()
  let noticeId = 0
  const timers = new Map<number, ReturnType<typeof setTimeout>>()

  function dismissNotice(id: number): void {
    notices.value = notices.value.filter((item) => item.id !== id)
    const timer = timers.get(id)
    if (timer) timers.delete(id)
    clearTimeout(timer)
  }

  function notify(input: NoticeInput): void {
    const now = Date.now()
    const dedupeWindow = 3000
    const last = lastByCode.get(input.code)
    if (last !== undefined && now - last < dedupeWindow) return
    lastByCode.set(input.code, now)

    const tone = input.tone || (input.code.startsWith('error') ? 'error' : 'info')
    const notice: Notice = {
      id: ++noticeId,
      code: input.code,
      message: input.message || input.code,
      next: input.next || '',
      tone,
      createdAt: now,
    }
    notices.value = [...notices.value.slice(-2), notice]
    noticeId += 0
    timers.set(notice.id, setTimeout(() => dismissNotice(notice.id), input.ttl ?? 4000))
  }

  function notifyError(code: string, fallback = ''): void {
    const language = errorLanguage(code, fallback)
    notify({ code, message: language.message, next: language.next, tone: 'error', ttl: 6000 })
  }

  function clearNotices(): void {
    for (const timer of timers.values()) clearTimeout(timer)
    timers.clear()
    notices.value = []
    lastByCode.clear()
  }

  const hasNotices = computed(() => notices.value.length > 0)

  return {
    connection,
    connectionIssue,
    setConnection,
    setConnectionIssue,
    clearConnectionIssue,
    theme,
    motion,
    contrast,
    fontScale,
    setTheme,
    setMotion,
    setContrast,
    setFontScale,
    accent,
    setAccent,
    helpOpen,
    openHelp,
    closeHelp,
    adminOpen,
    openAdmin,
    closeAdmin,
    friendsOpen,
    openFriends,
    closeFriends,
    requestLogin,
    activeDialog,
    claimDialog,
    releaseDialog,
    registerDialogClose,
    unregisterDialogClose,
    closeAllDialogs,
    exitConfirmOpen,
    requestExit,
    cancelExit,
    notices,
    hasNotices,
    notify,
    notifyError,
    dismissNotice,
    clearNotices,
  }
})
