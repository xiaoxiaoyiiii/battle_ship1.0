import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * Lobby view model (ticket #24).
 *
 * The store mirrors the frozen wire payloads: lobby_state is a broadcast, so
 * "me" is decided by comparing its player/chat key with lobby_hello.key (the
 * server cannot personalise a broadcast). Chat history and live lines are
 * merged by the server's monotonic seq, never by clearing the list.
 *
 * Screen-only view state (search text, active filter) stays in the component;
 * everything here is server data plus the room this session created.
 */
export type JsonObject = Record<string, unknown>
export type LobbyFilter = 'all' | 'joinable' | 'watchable' | 'full'
export type LobbyQueueMode = 'casual' | 'ranked' | null

/** A real matchmaking pair the server already seated us into. */
export interface MatchFoundInfo {
  playerName: string
  opponentName: string
  mode: 'casual' | 'ranked'
  roomId: string
}

export interface LobbyHello {
  key: string
  name: string
  guest: boolean
}

export interface LobbyPlayer {
  key: string
  name: string
  guest: boolean
  inLobby: boolean
  status: string
  avatar: string
  level: number
  nameStyle: string
  title: string
  rankLabel: string
  rankTier: string
}

export interface LobbyRoom {
  roomId: string
  name: string
  host: string
  players: number
  capacity: number
  createdAt: number
  /** Ticket #43 additive fields: 'casual' | 'ranked' | 'custom' (or '' if absent). */
  mode: string
  /** Ticket #43: false = private room (join by room id only). */
  public: boolean
}

export interface LobbyMatch {
  roomId: string
  names: string[]
  round: number
  spectators: number
  spectatorLimit: number
  ranked: boolean
}

export interface LobbyChatItem {
  key: string
  name: string
  message: string
  ts: number
  seq: number
}

export interface LobbyFriend {
  userId: string
  username: string
  avatar: string
  level: number
  rankLabel: string
  online: boolean
  inGame: boolean
  unread: number
}

export interface LobbyInvite {
  roomId: string
  fromUserId: string
  fromUsername: string
}

export interface LobbySnapshot {
  ts: number
  onlineCount: number
  lobbyCount: number
  queueCasual: number
  queueRanked: number
  players: LobbyPlayer[]
  rooms: LobbyRoom[]
  matches: LobbyMatch[]
}

const CHAT_LIMIT = 200

function asObject(value: unknown): JsonObject | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonObject)
    : null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function asBoolean(value: unknown): boolean {
  return value === true
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function toObjects(value: unknown): JsonObject[] {
  return asArray(value).filter((item): item is JsonObject => {
    return Boolean(item) && typeof item === 'object' && !Array.isArray(item)
  })
}

function normalizePlayer(raw: JsonObject): LobbyPlayer {
  const rank = asObject(raw.rank)
  const key = asString(raw.key)
  return {
    key,
    name: asString(raw.name) || '游客',
    guest: asBoolean(raw.guest),
    inLobby: asBoolean(raw.in_lobby),
    status: asString(raw.status) || 'idle',
    avatar: asString(raw.avatar),
    level: asNumber(raw.level, 1) || 1,
    nameStyle: asString(raw.name_style),
    title: asString(raw.title),
    rankLabel: rank ? asString(rank.label) : '',
    rankTier: rank ? asString(rank.tier_id) : '',
  }
}

function normalizeRoom(raw: JsonObject): LobbyRoom {
  const roomId = asString(raw.room_id)
  return {
    roomId,
    name: asString(raw.name) || roomId,
    host: asString(raw.host),
    players: Math.max(1, asNumber(raw.players, 1)),
    capacity: Math.max(1, asNumber(raw.capacity, 2)),
    createdAt: asNumber(raw.created_at),
    mode: asString(raw.mode),
    // Older broadcasts omit the field; the server default is public.
    public: raw.public !== false,
  }
}

function normalizeMatch(raw: JsonObject): LobbyMatch {
  return {
    roomId: asString(raw.room_id),
    names: asArray(raw.names).map((name) => String(name ?? '')),
    round: asNumber(raw.round),
    spectators: asNumber(raw.spectators),
    spectatorLimit: asNumber(raw.spectator_limit),
    ranked: asBoolean(raw.ranked),
  }
}

function normalizeChat(raw: JsonObject): LobbyChatItem {
  return {
    key: asString(raw.key),
    name: asString(raw.name) || '游客',
    message: String(raw.message ?? ''),
    ts: asNumber(raw.ts),
    seq: asNumber(raw.seq),
  }
}

function normalizeSnapshot(raw: JsonObject): LobbySnapshot {
  const queue = asObject(raw.queue)
  return {
    ts: asNumber(raw.ts),
    onlineCount: asNumber(raw.online_count),
    lobbyCount: asNumber(raw.lobby_count),
    queueCasual: queue ? asNumber(queue.casual) : 0,
    queueRanked: queue ? asNumber(queue.ranked) : 0,
    players: toObjects(raw.players).map(normalizePlayer).filter((player) => player.key),
    rooms: toObjects(raw.rooms).map(normalizeRoom).filter((room) => room.roomId),
    matches: toObjects(raw.matches).map(normalizeMatch).filter((match) => match.roomId),
  }
}

function normalizeFriend(raw: JsonObject): LobbyFriend {
  const userId = asString(raw.user_id)
  return {
    userId,
    username: asString(raw.username),
    avatar: asString(raw.avatar),
    level: asNumber(raw.level, 1) || 1,
    rankLabel: asString(raw.rank_label),
    online: asBoolean(raw.online),
    inGame: asBoolean(raw.in_game),
    unread: asNumber(raw.unread),
  }
}

function chatIdentity(item: LobbyChatItem): string {
  return item.seq > 0 ? 'seq:' + item.seq : 'line:' + item.key + ':' + item.ts + ':' + item.message
}

/** Merge chat lines without wiping the frame already on screen. */
function mergeChat(existing: LobbyChatItem[], incoming: LobbyChatItem[]): LobbyChatItem[] {
  const seen = new Set(existing.map(chatIdentity))
  const merged = existing.slice()
  for (const item of incoming) {
    const identity = chatIdentity(item)
    if (seen.has(identity)) continue
    seen.add(identity)
    merged.push(item)
  }
  merged.sort((left, right) => {
    if (left.seq > 0 && right.seq > 0 && left.seq !== right.seq) return left.seq - right.seq
    return left.ts - right.ts
  })
  return merged.slice(-CHAT_LIMIT)
}

/** Guest display name: the legacy home input wrote these keys; fall back to 玩家. */
export function lobbyPlayerName(): string {
  try {
    const session = sessionStorage.getItem('battleship.playerName')
    if (session && session.trim()) return session.trim()
    const local = localStorage.getItem('battleship.playerName')
    if (local && local.trim()) return local.trim()
  } catch {
    // Storage can be unavailable in private contexts; the fallback is enough.
  }
  return '玩家'
}

export const useLobbyStore = defineStore('lobby', () => {
  const hello = ref<LobbyHello | null>(null)
  const snapshot = ref<LobbySnapshot | null>(null)
  const chat = ref<LobbyChatItem[]>([])
  const connected = ref(false)
  const subscribed = ref(false)
  const queueMode = ref<LobbyQueueMode>(null)
  const ownRoomId = ref('')
  const ownRoomName = ref('')
  const ownRoomPublic = ref(true)
  const activeInvite = ref<LobbyInvite | null>(null)
  const friends = ref<LobbyFriend[]>([])
  const friendsLoaded = ref(false)
  const friendsGuest = ref(false)
  const friendsError = ref('')
  const notice = ref('')
  const error = ref('')
  const startedRoomId = ref('')
  /** A queue hand-off that produced a real pair (匹配成功 overlay). */
  const matchFound = ref<MatchFoundInfo | null>(null)

  const onlineCount = computed(() => snapshot.value?.onlineCount ?? 0)
  const lobbyCount = computed(() => snapshot.value?.lobbyCount ?? 0)
  const queueCasual = computed(() => snapshot.value?.queueCasual ?? 0)
  const queueRanked = computed(() => snapshot.value?.queueRanked ?? 0)
  const players = computed(() => snapshot.value?.players ?? [])
  const rooms = computed(() => snapshot.value?.rooms ?? [])
  const matches = computed(() => snapshot.value?.matches ?? [])
  const hasSnapshot = computed(() => snapshot.value !== null)
  const myKey = computed(() => hello.value?.key ?? '')

  function recordHello(payload: JsonObject | null | undefined): void {
    if (!payload) return
    const key = asString(payload.key)
    if (!key) return
    hello.value = {
      key,
      name: asString(payload.name) || '游客',
      guest: asBoolean(payload.guest),
    }
    subscribed.value = true
  }

  function recordSnapshot(payload: JsonObject | null | undefined): void {
    if (!payload) return
    snapshot.value = normalizeSnapshot(payload)
    subscribed.value = true
  }

  function recordChatHistory(payload: JsonObject | null | undefined): void {
    if (!payload) return
    const lines = toObjects(payload.messages).map(normalizeChat)
    chat.value = mergeChat(chat.value, lines)
  }

  function recordChat(payload: JsonObject | null | undefined): void {
    if (!payload) return
    chat.value = mergeChat(chat.value, [normalizeChat(payload)])
  }

  function recordQueued(payload: JsonObject | null | undefined): void {
    const mode = asString(payload?.mode)
    queueMode.value = mode === 'ranked' ? 'ranked' : 'casual'
    notice.value = queueMode.value === 'ranked' ? '已加入排位匹配队列' : '已加入休闲匹配队列'
  }

  function recordCanceled(_payload?: JsonObject | null): void {
    queueMode.value = null
    notice.value = '已取消匹配'
  }

  function recordFriendInvite(payload: JsonObject | null | undefined): void {
    if (!payload) return
    const roomId = asString(payload.room_id)
    if (!roomId) return
    activeInvite.value = {
      roomId,
      fromUserId: asString(payload.from_user_id),
      fromUsername: asString(payload.from_username) || '好友',
    }
  }

  function recordFriends(payload: JsonObject | null | undefined): void {
    if (!payload) return
    friends.value = toObjects(payload.friends)
      .map((raw) => {
        const friend = normalizeFriend(raw)
        // Older projections may omit user_id; the username is still a stable
        // business key for this screen (and for the test selector).
        if (!friend.userId) friend.userId = friend.username
        return friend
      })
      .filter((friend) => Boolean(friend.userId))
    friendsLoaded.value = true
    friendsGuest.value = false
    friendsError.value = ''
  }

  function recordFriendsGuest(): void {
    friends.value = []
    friendsLoaded.value = true
    friendsGuest.value = true
    friendsError.value = ''
  }

  function recordFriendsError(message: string): void {
    friendsLoaded.value = true
    friendsGuest.value = false
    friendsError.value = message
  }

  function setOwnRoom(roomId: string, name = '', isPublic = true): void {
    ownRoomId.value = roomId
    ownRoomName.value = name
    ownRoomPublic.value = isPublic
  }

  function clearOwnRoom(): void {
    ownRoomId.value = ''
    ownRoomName.value = ''
    ownRoomPublic.value = true
  }

  function clearInvite(): void {
    activeInvite.value = null
  }

  function clearChat(): void {
    chat.value = []
  }

  function recordGameFrame(payload: JsonObject | null | undefined): void {
    if (!payload) return
    if (asString(payload.state) !== 'placing_ships') return
    const roomId = asString(payload.room_id)
    startedRoomId.value = roomId
    // Only a queue hand-off is a matchmaking pair; a custom room that fills up
    // goes straight to placement (legacy behaviour) and must not show the
    // 匹配成功 overlay.
    const queued = queueMode.value
    const opponentName = asString(payload.opponent_name)
    if (queued !== null && opponentName) {
      matchFound.value = {
        playerName: asString(payload.player_name) || '你',
        opponentName,
        mode: queued,
        roomId,
      }
    }
    queueMode.value = null
    if (roomId && roomId === ownRoomId.value) {
      // The room became a real match; the "waiting room" card is done.
      ownRoomId.value = ''
      ownRoomName.value = ''
    }
  }

  function clearMatchFound(): void {
    matchFound.value = null
  }

  function takeStartedRoom(): string {
    const roomId = startedRoomId.value
    startedRoomId.value = ''
    return roomId
  }

  function setNotice(text: string): void {
    notice.value = text
  }

  function setError(text: string): void {
    error.value = text
  }

  function clearError(): void {
    error.value = ''
  }

  function markConnected(value: boolean): void {
    connected.value = value
    if (!value) {
      subscribed.value = false
      hello.value = null
      queueMode.value = null
    }
  }

  function reset(): void {
    hello.value = null
    snapshot.value = null
    chat.value = []
    connected.value = false
    subscribed.value = false
    queueMode.value = null
    ownRoomId.value = ''
    ownRoomName.value = ''
    activeInvite.value = null
    friends.value = []
    friendsLoaded.value = false
    friendsGuest.value = false
    friendsError.value = ''
    notice.value = ''
    error.value = ''
    startedRoomId.value = ''
    matchFound.value = null
  }

  return {
    hello,
    snapshot,
    chat,
    connected,
    subscribed,
    queueMode,
    ownRoomId,
    ownRoomName,
    ownRoomPublic,
    activeInvite,
    friends,
    friendsLoaded,
    friendsGuest,
    friendsError,
    notice,
    error,
    startedRoomId,
    matchFound,
    onlineCount,
    lobbyCount,
    queueCasual,
    queueRanked,
    players,
    rooms,
    matches,
    hasSnapshot,
    myKey,
    recordHello,
    recordSnapshot,
    recordChatHistory,
    recordChat,
    recordQueued,
    recordCanceled,
    recordFriendInvite,
    recordFriends,
    recordFriendsGuest,
    recordFriendsError,
    setOwnRoom,
    clearOwnRoom,
    clearInvite,
    clearChat,
    recordGameFrame,
    clearMatchFound,
    takeStartedRoom,
    setNotice,
    setError,
    clearError,
    markConnected,
    reset,
  }
})