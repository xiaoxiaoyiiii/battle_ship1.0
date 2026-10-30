import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * Settings view state (ticket #25).
 *
 * Only frozen routes are used:
 * * GET/POST /api/replay/setting and /api/spectate/setting are the two
 *   independent switches (they are deliberately NOT part of the card payload,
 *   because that route has "whole row, missing keys reset to defaults"
 *   semantics -- see DECISIONS D13 and port map 11 §3);
 * * POST /api/profile/card carries the 11-field whole-row payload, so every
 *   privacy toggle sends all eleven fields (missing any one is a 400);
 * * POST /api/change_password is the frozen form route;
 * * GET /api/wallpapers is the legacy wallpaper entry (local-only scan).
 *
 * A toggle is applied immediately: the POST result is authoritative, and a
 * failure restores the previous value and leaves a readable reason.
 */
export type JsonObject = Record<string, unknown>
export type LoadStatus = 'idle' | 'loading' | 'ready' | 'anonymous' | 'error'
export type PrivacyKey =
  | 'show_stats'
  | 'show_fav_cards'
  | 'show_history'
  | 'show_guestbook'
  | 'show_rank'
  | 'friend_requests_open'

export const PRIVACY_KEYS: PrivacyKey[] = [
  'show_stats',
  'show_fav_cards',
  'show_history',
  'show_guestbook',
  'show_rank',
  'friend_requests_open',
]

export interface ToggleState {
  status: LoadStatus
  value: boolean | null
  error: string
  saving: boolean
}

export interface WallpaperState {
  status: LoadStatus
  available: boolean | null
  dirs: number
  items: JsonObject[]
  reason: string
  error: string
}

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function asObjects(value: unknown): JsonObject[] {
  return Array.isArray(value)
    ? value.filter((item): item is JsonObject => asObject(item) !== null)
    : []
}

async function readJson(response: Response): Promise<JsonObject | null> {
  try {
    return asObject(await response.json())
  } catch {
    return null
  }
}

function emptyToggle(): ToggleState {
  return { status: 'idle', value: null, error: '', saving: false }
}

function defaultPrivacy(): Record<PrivacyKey, boolean> {
  // Legacy column defaults (port map 11 §3): history is opt-in, the rest on.
  return {
    show_stats: true,
    show_fav_cards: true,
    show_history: false,
    show_guestbook: true,
    show_rank: true,
    friend_requests_open: true,
  }
}

export const useSettingsStore = defineStore('settings', () => {
  const profile = ref<JsonObject | null>(null)
  const profileStatus = ref<LoadStatus>('idle')
  const profileError = ref('')
  const privacy = ref<Record<PrivacyKey, boolean>>(defaultPrivacy())
  const privacySaving = ref(false)
  const privacyMessage = ref('')
  const privacyError = ref(false)
  const cardSaving = ref(false)
  const cardMessage = ref('')
  const cardError = ref(false)
  const effectsSaving = ref(false)
  const effectsMessage = ref('')
  const effectsError = ref(false)

  const replay = ref<ToggleState>(emptyToggle())
  const spectate = ref<ToggleState>(emptyToggle())

  const passwordSaving = ref(false)
  const passwordMessage = ref('')
  const passwordError = ref(false)

  const wallpaper = ref<WallpaperState>({
    status: 'idle',
    available: null,
    dirs: 0,
    items: [],
    reason: '',
    error: '',
  })

  function syncPrivacy(source: JsonObject): void {
    const next = defaultPrivacy()
    for (const key of PRIVACY_KEYS) {
      const raw = source[key]
      if (raw !== undefined && raw !== null) next[key] = Number(raw) !== 0
    }
    privacy.value = next
  }

  async function loadOwn(): Promise<void> {
    profileStatus.value = 'loading'
    profileError.value = ''
    try {
      const response = await fetch('/api/profile', { headers: { accept: 'application/json' } })
      if (response.status === 401) {
        profile.value = null
        profileStatus.value = 'anonymous'
        return
      }
      if (!response.ok) throw new Error('网络错误 ' + response.status)
      const body = await readJson(response)
      const row = body ? asObject(body.profile) : null
      if (!row) throw new Error('服务端没有返回个人信息')
      profile.value = row
      profileStatus.value = 'ready'
      syncPrivacy(row)
    } catch (error) {
      profile.value = null
      profileStatus.value = 'error'
      profileError.value = error instanceof Error ? error.message : String(error)
    }
  }

  async function loadToggle(kind: 'replay' | 'spectate'): Promise<void> {
    const target = kind === 'replay' ? replay : spectate
    const endpoint = kind === 'replay' ? '/api/replay/setting' : '/api/spectate/setting'
    const field = kind === 'replay' ? 'allow_replay' : 'allow_spectate'
    target.value = { ...target.value, status: 'loading', error: '' }
    try {
      const response = await fetch(endpoint, { headers: { accept: 'application/json' } })
      if (response.status === 401) {
        target.value = { status: 'anonymous', value: null, error: '', saving: false }
        return
      }
      const body = await readJson(response)
      if (!response.ok || !body || body.success !== true) {
        throw new Error(String(body?.error || '读取设置失败'))
      }
      target.value = {
        status: 'ready',
        value: body[field] === true,
        error: '',
        saving: false,
      }
    } catch (error) {
      target.value = {
        status: 'error',
        value: null,
        error: error instanceof Error ? error.message : String(error),
        saving: false,
      }
    }
  }

  async function setToggle(kind: 'replay' | 'spectate', on: boolean): Promise<boolean> {
    const target = kind === 'replay' ? replay : spectate
    const endpoint = kind === 'replay' ? '/api/replay/setting' : '/api/spectate/setting'
    const field = kind === 'replay' ? 'allow_replay' : 'allow_spectate'
    if (target.value.saving) return false
    const previous = target.value.value
    target.value = { ...target.value, saving: true, error: '' }
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'content-type': 'application/json', accept: 'application/json' },
        body: JSON.stringify({ [field]: on }),
      })
      const body = await readJson(response)
      if (!response.ok || !body || body.success !== true) {
        throw new Error(String(body?.error || '保存失败'))
      }
      target.value = { status: 'ready', value: body[field] === true, error: '', saving: false }
      return true
    } catch (error) {
      target.value = {
        status: 'ready',
        value: previous,
        error: error instanceof Error ? error.message : String(error),
        saving: false,
      }
      return false
    }
  }

  function cardPayload(row: JsonObject, flags: Record<PrivacyKey, boolean>): JsonObject {
    const tags = Array.isArray(row.tags) ? row.tags.map((tag) => String(tag)) : []
    return {
      title_id: typeof row.title_id === 'string' ? row.title_id : '',
      tags,
      status_text: typeof row.status_text === 'string' ? row.status_text : '',
      frame_id: typeof row.frame_id === 'string' ? row.frame_id : 'none',
      card_bg_id: typeof row.card_bg_id === 'string' ? row.card_bg_id : 'deep',
      show_stats: flags.show_stats ? 1 : 0,
      show_fav_cards: flags.show_fav_cards ? 1 : 0,
      show_history: flags.show_history ? 1 : 0,
      show_guestbook: flags.show_guestbook ? 1 : 0,
      show_rank: flags.show_rank ? 1 : 0,
      friend_requests_open: flags.friend_requests_open ? 1 : 0,
    }
  }

  async function saveCard(changes: JsonObject): Promise<JsonObject | null> {
    const row = { ...(profile.value || {}), ...changes }
    if (cardSaving.value) return null
    if (!profile.value) {
      cardError.value = true
      cardMessage.value = '个人名片尚未加载'
      return null
    }
    cardSaving.value = true
    cardMessage.value = ''
    cardError.value = false
    try {
      const response = await fetch('/api/profile/card', {
        method: 'POST',
        headers: { 'content-type': 'application/json', accept: 'application/json' },
        body: JSON.stringify(cardPayload(row, privacy.value)),
      })
      const body = await readJson(response)
      if (!response.ok || !body || body.success !== true) {
        throw new Error(String(body?.error || '名片保存失败'))
      }
      const saved = body ? asObject(body.profile) : null
      if (!saved) throw new Error('服务端没有返回已保存的名片')
      profile.value = saved
      syncPrivacy(saved)
      cardMessage.value = '已保存'
      return saved
    } catch (error) {
      cardError.value = true
      cardMessage.value = error instanceof Error ? error.message : String(error)
      return null
    } finally {
      cardSaving.value = false
    }
  }

  async function saveEffects(changes: JsonObject): Promise<JsonObject | null> {
    if (effectsSaving.value) return null
    if (!profile.value) {
      effectsError.value = true
      effectsMessage.value = '个人名片尚未加载'
      return null
    }
    effectsSaving.value = true
    effectsMessage.value = ''
    effectsError.value = false
    try {
      const response = await fetch('/api/profile/effects', {
        method: 'POST',
        headers: { 'content-type': 'application/json', accept: 'application/json' },
        body: JSON.stringify(changes),
      })
      const body = await readJson(response)
      if (!response.ok || !body || body.success !== true) {
        throw new Error(String(body?.error || '特效保存失败'))
      }
      const saved = body ? asObject(body.profile) : null
      if (!saved) throw new Error('服务端没有返回已保存的特效')
      profile.value = saved
      effectsMessage.value = '已保存'
      return saved
    } catch (error) {
      effectsError.value = true
      effectsMessage.value = error instanceof Error ? error.message : String(error)
      return null
    } finally {
      effectsSaving.value = false
    }
  }

  async function setPrivacy(key: PrivacyKey, on: boolean): Promise<boolean> {
    const row = profile.value
    if (!row || privacySaving.value) return false
    const previous = { ...privacy.value }
    privacy.value = { ...privacy.value, [key]: on }
    privacySaving.value = true
    privacyMessage.value = ''
    privacyError.value = false
    try {
      const response = await fetch('/api/profile/card', {
        method: 'POST',
        headers: { 'content-type': 'application/json', accept: 'application/json' },
        body: JSON.stringify(cardPayload(row, privacy.value)),
      })
      const body = await readJson(response)
      if (!response.ok || !body || body.success !== true) {
        const reason = body && typeof body.error === 'string' ? body.error : '保存失败'
        throw new Error(reason)
      }
      const saved = body ? asObject(body.profile) : null
      if (saved) {
        profile.value = saved
        syncPrivacy(saved)
      }
      privacyMessage.value = '已保存'
      return true
    } catch (error) {
      privacy.value = previous
      privacyMessage.value = error instanceof Error ? error.message : String(error)
      privacyError.value = true
      return false
    } finally {
      privacySaving.value = false
    }
  }

  async function changePassword(oldPassword: string, newPassword: string): Promise<boolean> {
    if (passwordSaving.value) return false
    passwordSaving.value = true
    passwordMessage.value = ''
    passwordError.value = false
    try {
      const response = await fetch('/api/change_password', {
        method: 'POST',
        headers: {
          'content-type': 'application/x-www-form-urlencoded',
          accept: 'application/json',
        },
        body: new URLSearchParams({ old_password: oldPassword, new_password: newPassword }),
      })
      const body = await readJson(response)
      if (!response.ok || !body || body.success !== true) {
        const structured = body ? asObject(body.error) : null
        const reason = String(
          body?.msg || (structured ? structured.message : '') || body?.error || '修改失败',
        )
        throw new Error(reason)
      }
      passwordMessage.value = String(body.msg || '密码修改成功')
      return true
    } catch (error) {
      passwordMessage.value = error instanceof Error ? error.message : String(error)
      passwordError.value = true
      return false
    } finally {
      passwordSaving.value = false
    }
  }

  async function checkWallpapers(): Promise<void> {
    wallpaper.value = { ...wallpaper.value, status: 'loading', error: '' }
    try {
      const response = await fetch('/api/wallpapers', { headers: { accept: 'application/json' } })
      const body = await readJson(response)
      if (!response.ok || !body) throw new Error('网络错误 ' + response.status)
      wallpaper.value = {
        status: 'ready',
        available: body.available === true,
        dirs: Number(body.dirs) || 0,
        items: asObjects(body.items),
        reason: typeof body.reason === 'string' ? body.reason : '',
        error: '',
      }
    } catch (error) {
      wallpaper.value = {
        status: 'error',
        available: null,
        dirs: 0,
        items: [],
        reason: '',
        error: error instanceof Error ? error.message : String(error),
      }
    }
  }

  function reset(): void {
    profile.value = null
    profileStatus.value = 'idle'
    profileError.value = ''
    privacy.value = defaultPrivacy()
    privacySaving.value = false
    privacyMessage.value = ''
    privacyError.value = false
    cardSaving.value = false
    cardMessage.value = ''
    cardError.value = false
    effectsSaving.value = false
    effectsMessage.value = ''
    effectsError.value = false
    replay.value = emptyToggle()
    spectate.value = emptyToggle()
    passwordSaving.value = false
    passwordMessage.value = ''
    passwordError.value = false
    wallpaper.value = {
      status: 'idle', available: null, dirs: 0, items: [], reason: '', error: '',
    }
  }

  return {
    profile,
    profileStatus,
    profileError,
    privacy,
    privacySaving,
    privacyMessage,
    privacyError,
    cardSaving,
    cardMessage,
    cardError,
    effectsSaving,
    effectsMessage,
    effectsError,
    replay,
    spectate,
    passwordSaving,
    passwordMessage,
    passwordError,
    wallpaper,
    loadOwn,
    loadToggle,
    setToggle,
    saveCard,
    saveEffects,
    setPrivacy,
    changePassword,
    checkWallpapers,
    reset,
  }
})
