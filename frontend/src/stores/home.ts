import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { bootHomeStats, readBoot } from '../boot'

/**
 * Home-screen view model (ticket #26).
 *
 * Every number on the home screen comes from a server read or a server frame:
 *
 * * `/api/home_stats`   online / casual queue / ranked queue / joinable rooms
 * * `/api/online_count` the header pill (same presence table, CLAUDE #17)
 * * `/api/profile`      the commander card (rank / level / record)
 * * `/api/changelog`    the announcements column
 * * `match_queued` / `match_canceled` / `error` socket frames
 *
 * The store only shapes payloads (nulls stay null, arrays are copied); it never
 * recomputes a rank, a level or a queue rule. Missing values stay `null` and the
 * screen renders an em dash instead of inventing a zero.
 */
export type JsonObject = Record<string, unknown>

export interface HomeStats {
  onlineCount: number | null
  queueCasual: number | null
  queueRanked: number | null
  lobbyRooms: number | null
}

export interface ChangelogEntry {
  /** Server date string; also the stable business id (unique by contract). */
  date: string
  items: string[]
}

export type HomeMode = 'casual' | 'ranked'

/** A real match the server has already seated us into (匹配成功 overlay). */
export interface MatchFoundInfo {
  playerName: string
  opponentName: string
  mode: HomeMode
  roomId: string
}

export interface HomeFetchResult {
  ok: boolean
  status: number
  body: unknown
}

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function emptyStats(): HomeStats {
  return { onlineCount: null, queueCasual: null, queueRanked: null, lobbyRooms: null }
}

async function getJson(url: string): Promise<HomeFetchResult> {
  try {
    const response = await fetch(url, {
      headers: { accept: 'application/json' },
      credentials: 'same-origin',
    })
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      body = null
    }
    return { ok: response.ok, status: response.status, body }
  } catch {
    return { ok: false, status: 0, body: null }
  }
}

export const useHomeStore = defineStore('home', () => {
  const stats = ref<HomeStats>(emptyStats())
  const statsLoaded = ref(false)
  const statsFailed = ref(false)
  const onlinePill = ref<number | null>(null)
  const profile = ref<JsonObject | null>(null)
  const profileLoaded = ref(false)
  const profileFailed = ref(false)
  const changelog = ref<ChangelogEntry[]>([])
  const changelogLatest = ref('')
  const changelogLoaded = ref(false)
  const changelogFailed = ref(false)
  /** Pending matchmaking mode announced by `match_queued`. */
  const queueMode = ref<HomeMode | null>(null)
  /** Epoch ms when the server confirmed the queue entry (waited-seconds label). */
  const queueStartedAt = ref(0)
  /** A find_match/create_ai_room hand-off is being prepared (client guard). */
  const pendingAction = ref<'casual' | 'ranked' | 'ai' | null>(null)
  /** Last user-facing server refusal (`error` frame or an error ack). */
  const notice = ref('')
  /** True once a match/room hand-off is expected to move us to placement. */
  const awaitingPlacement = ref(false)
  /** Set when a real matchmaking pair lands; the home screen shows the
   *  five-second 匹配成功 overlay before navigating to placement. AI/custom
   *  rooms never set it (they are not matchmaking pairs). */
  const matchFound = ref<MatchFoundInfo | null>(null)
  /**
   * Monotonic counter bumped by every `game_state{placing_ships}` frame. The
   * screen watches this instead of the state value: after one match the store
   * already says placing_ships, so a value watcher would never fire again.
   */
  const placementSignal = ref(0)
  const socketConnected = ref(false)

  const queuePending = computed(() => queueMode.value !== null)
  const busy = computed(() => queuePending.value || pendingAction.value !== null)

  function applyHomeStats(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    if (!data) {
      statsFailed.value = true
      statsLoaded.value = true
      return
    }
    const queue = asObject(data.queue)
    stats.value = {
      onlineCount: asNumber(data.online_count),
      queueCasual: asNumber(queue?.casual),
      queueRanked: asNumber(queue?.ranked),
      lobbyRooms: asNumber(data.lobby_rooms),
    }
    statsLoaded.value = true
    statsFailed.value = false
  }

  function applyOnlineCount(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    const value = asNumber(data?.online_count)
    if (value !== null) onlinePill.value = value
  }

  function applyProfile(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    const body = asObject(data?.profile)
    if (!body) {
      profile.value = null
      profileLoaded.value = true
      profileFailed.value = true
      return
    }
    profile.value = body
    profileLoaded.value = true
    profileFailed.value = false
  }

  function markGuest(): void {
    profile.value = null
    profileLoaded.value = true
    profileFailed.value = false
  }

  function applyChangelog(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    if (!data) {
      changelogFailed.value = true
      changelogLoaded.value = true
      return
    }
    const rows = Array.isArray(data.entries) ? data.entries : []
    const entries: ChangelogEntry[] = []
    for (const row of rows) {
      const item = asObject(row)
      if (!item) continue
      entries.push({
        date: asString(item.date),
        items: Array.isArray(item.items) ? item.items.map(asString) : [],
      })
    }
    changelog.value = entries
    changelogLatest.value = asString(data.latest) || entries[0]?.date || ''
    changelogLoaded.value = true
    changelogFailed.value = false
  }

  function applyMatchQueued(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    queueMode.value = data?.mode === 'ranked' ? 'ranked' : 'casual'
    queueStartedAt.value = Date.now()
    pendingAction.value = null
    // A pair may be announced at any moment while we wait in the queue, so the
    // placement hand-off stays armed until we leave or cancel.
    awaitingPlacement.value = true
  }

  function applyMatchCanceled(): void {
    queueMode.value = null
    queueStartedAt.value = 0
    pendingAction.value = null
    awaitingPlacement.value = false
  }

  function beginAction(action: 'casual' | 'ranked' | 'ai'): void {
    pendingAction.value = action
    notice.value = ''
  }

  function endAction(): void {
    pendingAction.value = null
  }

  function expectPlacement(): void {
    awaitingPlacement.value = true
    pendingAction.value = null
    queueMode.value = null
    queueStartedAt.value = 0
  }

  /** Record the placing_ships frame: matchmaking pairs open the overlay. */
  function recordPlacementFrame(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    if (!data) return
    const mode = queueMode.value
    const opponentName = asString(data.opponent_name)
    if (mode === null || !opponentName) return
    matchFound.value = {
      playerName: asString(data.player_name) || '你',
      opponentName,
      mode,
      roomId: asString(data.room_id),
    }
  }

  function clearMatchFound(): void {
    matchFound.value = null
  }

  function markPlacementFrame(): void {
    placementSignal.value += 1
  }

  function placementHandled(): void {
    awaitingPlacement.value = false
    queueMode.value = null
    queueStartedAt.value = 0
  }

  function notifyError(payload: JsonObject | null | undefined): void {
    const data = asObject(payload)
    const message = asString(data?.message) || asString(data?.error)
    if (message) notice.value = message
    pendingAction.value = null
  }

  function notifyMessage(message: string): void {
    if (message) notice.value = message
    pendingAction.value = null
  }

  function clearNotice(): void {
    notice.value = ''
  }

  function setSocketConnected(value: boolean): void {
    socketConnected.value = value
  }

  /**
   * Read the read-only aggregate; both requests belong to the same panel.
   * The shell's window.__BOOT__ already carries the same three counters, so the
   * first paint renders them without a round trip (spec: startup data JSON).
   * The force flag (used once the realtime socket is up) bypasses the boot
   * snapshot: the boot counters are the page-render moment, and presence
   * changes as soon as our own connection registers.
   */
  let bootConsumed = false
  async function loadStats(force = false): Promise<void> {
    if (!force && !bootConsumed) {
      const booted = bootHomeStats()
      if (booted) {
        bootConsumed = true
        applyHomeStats(booted)
        if (typeof booted.online_count === 'number') {
          applyOnlineCount({ online_count: booted.online_count })
        }
        return
      }
    }
    const [aggregate, counter] = await Promise.all([
      getJson('/api/home_stats'),
      getJson('/api/online_count'),
    ])
    if (aggregate.ok) applyHomeStats(asObject(aggregate.body))
    else applyHomeStats(null)
    if (counter.ok) applyOnlineCount(asObject(counter.body))
  }

  /** `/api/profile` answers 401 for guests; that is a state, not a failure. */
  async function loadProfile(): Promise<void> {
    const boot = readBoot()
    if (boot && boot.user === null) {
      // The shell already knows this request is anonymous; skip the 401 probe.
      markGuest()
      return
    }
    const result = await getJson('/api/profile')
    if (result.status === 401) {
      markGuest()
      return
    }
    if (!result.ok) {
      profile.value = null
      profileLoaded.value = true
      profileFailed.value = true
      return
    }
    applyProfile(asObject(result.body))
  }

  async function loadChangelog(limit = 3): Promise<void> {
    const result = await getJson('/api/changelog?limit=' + limit)
    if (!result.ok) {
      applyChangelog(null)
      return
    }
    applyChangelog(asObject(result.body))
  }

  function reset(): void {
    stats.value = emptyStats()
    statsLoaded.value = false
    statsFailed.value = false
    onlinePill.value = null
    profile.value = null
    profileLoaded.value = false
    profileFailed.value = false
    changelog.value = []
    changelogLatest.value = ''
    changelogLoaded.value = false
    changelogFailed.value = false
    queueMode.value = null
    queueStartedAt.value = 0
    pendingAction.value = null
    notice.value = ''
    awaitingPlacement.value = false
    matchFound.value = null
    placementSignal.value = 0
  }

  return {
    stats,
    statsLoaded,
    statsFailed,
    onlinePill,
    profile,
    profileLoaded,
    profileFailed,
    changelog,
    changelogLatest,
    changelogLoaded,
    changelogFailed,
    queueMode,
    queueStartedAt,
    queuePending,
    pendingAction,
    busy,
    notice,
    awaitingPlacement,
    matchFound,
    placementSignal,
    socketConnected,
    applyHomeStats,
    applyOnlineCount,
    applyProfile,
    markGuest,
    applyChangelog,
    applyMatchQueued,
    applyMatchCanceled,
    beginAction,
    endAction,
    expectPlacement,
    recordPlacementFrame,
    clearMatchFound,
    markPlacementFrame,
    placementHandled,
    notifyError,
    notifyMessage,
    clearNotice,
    setSocketConnected,
    loadStats,
    loadProfile,
    loadChangelog,
    reset,
  }
})
