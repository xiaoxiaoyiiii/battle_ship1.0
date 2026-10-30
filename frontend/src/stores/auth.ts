import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { readBoot } from '../boot'

/**
 * Identity store (ticket #44, spec section 3).
 *
 * First paint already knows who we are: the shell injects window.__BOOT__.user
 * from the signed session cookie (boot.ts), so this store never probes on mount.
 * Login and register reuse the frozen JSON contract of POST /login and POST
 * /register — no new route, no change to the backend. Success is only accepted
 * through a full page reload: the socket handshake reads identity from the
 * session cookie, and a reload keeps the current route (spec story 5/6).
 *
 * Guests get one persisted auto name — 舰长 + four digits — under the legacy
 * localStorage key battleship.playerName, which the lobby helper already reads.
 * Home, find_match, create_ai_room and the lobby therefore submit the same name
 * the screen shows; the old 「游客 / 玩家」 split is gone (spec story 9).
 */

export type AuthTab = 'login' | 'register'

export interface AuthUser {
  id: string
  username: string
  guest: boolean
}

export interface AuthResult {
  status: number
  body: unknown
}

/** The one guest-name shape: 舰长 followed by exactly four digits. */
export const GUEST_NAME_PATTERN = /^舰长\d{4}$/

/** Also the key the legacy lobby helper still reads (stores/lobby.ts). */
const GUEST_NAME_KEY = 'battleship.playerName'

/** Player-facing hints; never the server's technical code or raw message. */
const USERNAME_HINT = '用户名至少 3 位，只能包含字母、数字、点、下划线和短横线。'
const PASSWORD_HINT = '密码至少 6 位。'
const ERROR_UNKNOWN = '操作没有成功，请检查填写后再试。'
const ERROR_SERVER = '服务器暂时无法完成操作，请稍后重试。'

let ephemeralGuestName = ''

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

function generatedGuestName(): string {
  return '舰长' + String(Math.floor(1000 + Math.random() * 9000))
}

/** The persisted guest name, generated once and then stable across reloads. */
function readGuestName(): string {
  const store = storage()
  try {
    const stored = store?.getItem(GUEST_NAME_KEY) || ''
    if (GUEST_NAME_PATTERN.test(stored)) return stored
  } catch {
    // Private contexts may refuse storage; fall through to a session-only name.
  }
  const fresh = ephemeralGuestName || generatedGuestName()
  ephemeralGuestName = fresh
  try {
    store?.setItem(GUEST_NAME_KEY, fresh)
    // The legacy helper checks sessionStorage first; a stale name there would
    // split one guest into two identities, so a fresh name overwrites it.
    sessionStorage.removeItem(GUEST_NAME_KEY)
  } catch {
    // Best effort: the name still works for this page.
  }
  return fresh
}

function bootUser(): AuthUser | null {
  const user = readBoot()?.user
  if (!user || user.guest) return null
  return { id: user.id, username: user.username, guest: false }
}

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function errorCode(body: unknown): { code: string; field: string } {
  const error = asObject(asObject(body)?.error)
  return {
    code: typeof error?.code === 'string' ? error.code : '',
    field: typeof error?.field === 'string' ? error.field : '',
  }
}

/**
 * Map the structured failure ({error:{code,message,field}}) to player copy.
 * The server message is deliberately not shown: codes are the contract, and a
 * missing/unknown code still gets readable text (spec acceptance 3).
 */
export function failureText(status: number, body: unknown): string {
  const { code, field } = errorCode(body)
  if (code === 'validation_error') {
    if (field === 'password') return PASSWORD_HINT
    if (field === 'username') return USERNAME_HINT
    return '请填写用户名和密码后再试。'
  }
  if (code === 'invalid_credentials') return '用户名或密码错误。'
  if (code === 'username_taken') return '用户名已存在，换一个试试。'
  if (code === 'rate_limited' || status === 429) return '操作太频繁了，请等 1 分钟再试。'
  if (code === 'unauthorized') return '登录状态已失效，请重新登录。'
  if (status === 0) return '网络不稳定，登录请求没有送达，请检查连接后重试。'
  if (status >= 500) return ERROR_SERVER
  return ERROR_UNKNOWN
}

function validate(tab: AuthTab, username: string, password: string): string {
  if (!username) return '请填写用户名。'
  if (!password) return '请填写密码。'
  if (tab === 'register') {
    if (username.length < 3) return USERNAME_HINT
    if (password.length < 6) return PASSWORD_HINT
  }
  return ''
}

async function postAuth(tab: AuthTab, username: string, password: string): Promise<AuthResult> {
  try {
    const response = await fetch(tab === 'login' ? '/login' : '/register', {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ username, password }),
    })
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      body = null
    }
    return { status: response.status, body }
  } catch {
    return { status: 0, body: null }
  }
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(bootUser())
  const guestName = ref(readGuestName())

  const isGuest = computed(() => user.value === null)
  /** The one name this session shows and submits: account name or 舰长1234. */
  const displayName = computed(() => user.value?.username || guestName.value)

  // -------------------------------------------------------- overlay state ----
  const overlayOpen = ref(false)
  const tab = ref<AuthTab>('login')
  const reason = ref('')
  const busy = ref(false)
  const error = ref('')

  /**
   * Open the app-level overlay. Entry points: avatar menu first item, the home
   * 「去登录」 button, a guest ranked click, and the bs:auth-required window
   * event (#48 uses it for the spectate/replay guest CTA).
   */
  function open(next: AuthTab = 'login', why = ''): void {
    if (user.value !== null) return
    tab.value = next === 'register' ? 'register' : 'login'
    reason.value = why
    busy.value = false
    error.value = ''
    overlayOpen.value = true
  }

  function close(): void {
    // Closing never clears server state; the overlay is a view only.
    overlayOpen.value = false
  }

  function switchTab(next: AuthTab): void {
    tab.value = next === 'register' ? 'register' : 'login'
    error.value = ''
  }

  function clearError(): void {
    error.value = ''
  }

  /** Submit one login/register attempt; success reloads so the socket gets the session. */
  async function submit(username: string, password: string): Promise<void> {
    if (busy.value) return
    const name = username.trim()
    const validation = validate(tab.value, name, password)
    error.value = validation
    if (validation) return

    busy.value = true
    try {
      const result = await postAuth(tab.value, name, password)
      if (result.status === 200) {
        window.location.reload()
        return
      }
      error.value = failureText(result.status, result.body)
    } finally {
      busy.value = false
    }
  }

  /** Logout stays on the existing /logout redirect (frozen route, spec section 3). */
  function requestLogout(): void {
    window.location.assign('/logout')
  }

  return {
    user,
    guestName,
    isGuest,
    displayName,
    overlayOpen,
    tab,
    reason,
    busy,
    error,
    open,
    close,
    switchTab,
    clearError,
    submit,
    requestLogout,
  }
})
