import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * Profile view state (ticket #25).
 *
 * Two reads, both server-authoritative:
 * * GET /api/profile  -> the owner's full row (used by the settings screen and
 *   to learn "who am I" so the leaderboard can mark the player's own row);
 * * GET /user_stats?username= -> the public card, including the privacy-filtered
 *   history. The server already removed what must not be shown; this store never
 *   "fills in" the missing parts.
 */
export type JsonObject = Record<string, unknown>
export type LoadStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'error' | 'anonymous'

export interface ViewedProfile {
  username: string
  status: LoadStatus
  stats: JsonObject | null
  history: JsonObject[]
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

export const useProfileStore = defineStore('profile', () => {
  const own = ref<JsonObject | null>(null)
  const ownStatus = ref<LoadStatus>('idle')
  const ownError = ref('')
  const viewed = ref<ViewedProfile>({
    username: '',
    status: 'idle',
    stats: null,
    history: [],
    error: '',
  })
  // The owner's full badge catalogue (unlocked + locked). /user_stats only ever
  // sends unlocked badges; /api/profile and /api/achievements are the owner-only
  // sources for the collection view.
  const achievements = ref<JsonObject[]>([])
  const achievementCount = ref<JsonObject | null>(null)

  let ownToken = 0
  let viewedToken = 0

  const viewerName = computed(() => {
    const name = own.value?.username
    return typeof name === 'string' ? name : ''
  })

  async function loadOwn(force = false): Promise<void> {
    if (!force && (ownStatus.value === 'ready' || ownStatus.value === 'anonymous')) return
    const token = ++ownToken
    ownStatus.value = 'loading'
    ownError.value = ''
    try {
      const response = await fetch('/api/profile', { headers: { accept: 'application/json' } })
      if (token !== ownToken) return
      if (response.status === 401) {
        own.value = null
        ownStatus.value = 'anonymous'
        return
      }
      if (!response.ok) throw new Error('网络错误 ' + response.status)
      const body = await readJson(response)
      const profile = body ? asObject(body.profile) : null
      own.value = profile
      ownStatus.value = profile ? 'ready' : 'error'
      if (!profile) ownError.value = '服务端没有返回个人信息'
    } catch (error) {
      if (token !== ownToken) return
      own.value = null
      ownStatus.value = 'error'
      ownError.value = error instanceof Error ? error.message : String(error)
    }
  }

  async function loadPublic(username: string): Promise<void> {
    const name = String(username || '').trim()
    if (!name) {
      viewed.value = { username: '', status: 'empty', stats: null, history: [], error: '' }
      return
    }
    const token = ++viewedToken
    viewed.value = { ...viewed.value, username: name, status: 'loading', error: '' }
    try {
      const url = '/user_stats?username=' + encodeURIComponent(name)
      const response = await fetch(url, { headers: { accept: 'application/json' } })
      if (token !== viewedToken) return
      if (!response.ok) throw new Error('网络错误 ' + response.status)
      const body = await readJson(response)
      const stats = body ? asObject(body.stats) : null
      if (!stats) {
        viewed.value = { username: name, status: 'empty', stats: null, history: [], error: '' }
        return
      }
      viewed.value = {
        username: name,
        status: 'ready',
        stats,
        history: body ? asObjects(body.history) : [],
        error: '',
      }
      if (name === viewerName.value) await loadAchievements()
      else {
        achievements.value = []
        achievementCount.value = null
      }
    } catch (error) {
      if (token !== viewedToken) return
      viewed.value = {
        username: name,
        status: 'error',
        stats: null,
        history: [],
        error: error instanceof Error ? error.message : String(error),
      }
    }
  }

  /** Drop the currently viewed card (e.g. leaving /profile?username=...). */
  function clearViewed(): void {
    viewedToken += 1
    viewed.value = { username: '', status: 'idle', stats: null, history: [], error: '' }
    achievements.value = []
    achievementCount.value = null
  }

  async function loadAchievements(): Promise<void> {
    try {
      const response = await fetch('/api/achievements', { headers: { accept: 'application/json' } })
      if (!response.ok) return
      const body = await readJson(response)
      if (!body) return
      achievements.value = asObjects(body.achievements)
      achievementCount.value = asObject(body.badge_count)
    } catch {
      // The card still renders from /user_stats; the catalogue is an enhancement.
    }
  }

  function reset(): void {
    own.value = null
    ownStatus.value = 'idle'
    ownError.value = ''
    viewed.value = { username: '', status: 'idle', stats: null, history: [], error: '' }
  }

  return {
    own,
    ownStatus,
    ownError,
    viewerName,
    viewed,
    achievements,
    achievementCount,
    loadOwn,
    loadPublic,
    clearViewed,
    reset,
  }
})