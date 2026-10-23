<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import MatchFoundOverlay from '../../components/MatchFoundOverlay.vue'
import StateSurface from '../../components/StateSurface.vue'
import { acquireLobbyChannel, getLobbySocket } from '../../realtime/lobby'
import { useHomeStore } from '../../stores/home'
import { useUiStore } from '../../stores/ui'
import {
  lobbyPlayerName,
  useLobbyStore,
  type LobbyFilter,
  type LobbyFriend,
  type LobbyMatch,
  type LobbyRoom,
} from '../../stores/lobby'
import {
  FILTERS,
  filterMatches,
  filterRooms,
  initial,
  inviteDisabledReason,
  levelText,
  matchNamesText,
  matchSpectateText,
  matchesEmptyText,
  queueModeText,
  rankText,
  roomJoinable,
  roomModeText,
  roomSeatsText,
  roomVisibilityText,
  roomsEmptyText,
  showsMatches,
  showsRooms,
  statusText,
  timeText,
} from './view'

/**
 * Ticket #24: the lobby screen.
 *
 * Data comes from the real lobby broadcast and the already-implemented friends
 * routes. This component only formats server values and keeps view state
 * (search text, active filter, drafts). "Me" is lobby_hello.key compared with
 * the broadcast keys — the server cannot add is_me to a broadcast.
 */
const router = useRouter()
const lobby = useLobbyStore()
const ui = useUiStore()
const home = useHomeStore()

const filter = ref<LobbyFilter>('all')
const query = ref('')
const roomName = ref('')
const roomPublic = ref(true)
const chatDraft = ref('')
const invitingUsername = ref('')
const acceptingInvite = ref(false)
const friendsBusy = ref(false)
const chatEl = ref<HTMLElement | null>(null)
/** Destructive room action asks once before it fires (issue #45 point 5). */
const confirmingClose = ref(false)
/** Fold state for the secondary live panels; all start open (point 5). */
const openFold = ref({ players: true, chat: true, matches: true })

let releaseChannel: (() => void) | null = null

const filteredRooms = computed(() => filterRooms(lobby.rooms, filter.value, query.value))
const filteredMatches = computed(() => filterMatches(lobby.matches, filter.value, query.value))
const roomsVisible = computed(() => showsRooms(filter.value))
const matchesVisible = computed(() => showsMatches(filter.value))
const roomsEmpty = computed(() => roomsEmptyText(lobby.rooms.length, filter.value, query.value))
const matchesEmpty = computed(() => matchesEmptyText(lobby.matches.length, query.value))
const friendListVisible = computed(
  () => lobby.friendsLoaded && !lobby.friendsGuest && !lobby.friendsError,
)
const queueLabel = computed(() => queueModeText(lobby.queueMode))
/** Loading / empty / error / ready for the room list (ticket #42). */
const roomsState = computed<'loading' | 'ready' | 'empty' | 'error'>(() => {
  if (lobby.error) return 'error'
  if (!lobby.hasSnapshot) return 'loading'
  return filteredRooms.value.length ? 'ready' : 'empty'
})

// Failures land in the global queue as well: reason + next step, one place.
watch(
  () => lobby.error,
  (message) => {
    if (message) ui.notifyError('lobby-error', message)
  },
)
watch(
  () => lobby.notice,
  (message) => {
    if (message) ui.notify({ code: 'lobby-notice', tone: 'info', message })
  },
)

function countText(value: number): string {
  return lobby.hasSnapshot ? String(value) : '—'
}

function isMePlayer(key: string): boolean {
  return Boolean(lobby.myKey) && key === lobby.myKey
}

function isMineChat(key: string): boolean {
  return Boolean(lobby.myKey) && key === lobby.myKey
}

function playerNameClass(style: string): string {
  return style === 'rainbow' ? 'lobby__player-name lobby__player-name--rainbow' : 'lobby__player-name'
}

function avatarStyle(avatar: string): Record<string, string> {
  if (!avatar) return {}
  const safe = avatar.replace(/["\\]/g, '')
  return { backgroundImage: 'url("' + safe + '")' }
}

function chatKey(seq: number, key: string, ts: number): string {
  return seq > 0 ? 'seq-' + seq : 'line-' + key + '-' + ts
}

function friendStatus(friend: LobbyFriend): string {
  if (!friend.online) return '离线'
  return friend.inGame ? '对局中' : '在线'
}

function friendInviteReason(friend: LobbyFriend): string {
  return inviteDisabledReason(friend) || '邀请他打一局'
}

function setNotice(text: string): void {
  lobby.clearError()
  lobby.setNotice(text)
}

function fail(message: string): void {
  lobby.setError(message)
}

function socketOrFail() {
  const socket = getLobbySocket()
  if (!socket || !socket.socket.connected) {
    fail('连接尚未就绪，请稍后再试')
    return null
  }
  return socket
}

function ackField(ack: unknown, key: string): unknown {
  return (ack as Record<string, unknown>)[key]
}

function refresh(): void {
  const socket = socketOrFail()
  if (!socket) return
  void socket.emitEvent('lobby_refresh', {}).catch((error: unknown) => {
    fail(error instanceof Error ? error.message : String(error))
  })
}

function createRoom(): void {
  const socket = socketOrFail()
  if (!socket) return
  const name = roomName.value.trim()
  void socket
    .emitEvent('lobby_create_room', {
      name,
      public: roomPublic.value,
      player_name: lobbyPlayerName(),
    })
    .then((ack) => {
      if (ack.status !== 'success') {
        fail(ack.message || '创建房间失败')
        return
      }
      const roomId = String(ackField(ack, 'room_id') || '')
      if (!roomId) {
        fail('创建房间失败：服务端没有返回房号')
        return
      }
      const createdName = String(ackField(ack, 'name') || name)
      const isPublic = ackField(ack, 'public') !== false
      lobby.setOwnRoom(roomId, createdName, isPublic)
      roomName.value = ''
      setNotice('房间已创建：' + roomId + '，等待玩家加入')
    })
    .catch((error: unknown) => {
      fail(error instanceof Error ? error.message : String(error))
    })
}

function joinRoom(room: LobbyRoom): void {
  if (!roomJoinable(room)) return
  const socket = socketOrFail()
  if (!socket) return
  void socket
    .emitEvent('join_room', { room_id: room.roomId, player_name: lobbyPlayerName() })
    .then((ack) => {
      if (ack.status !== 'success') {
        fail(ack.message || '加入房间失败')
        return
      }
      setNotice('已加入房间 ' + room.roomId + '，对局即将开始')
    })
    .catch((error: unknown) => {
      fail(error instanceof Error ? error.message : String(error))
    })
}

function closeRoom(roomId: string): void {
  if (!roomId) return
  const socket = socketOrFail()
  if (!socket) return
  void socket
    .emitEvent('close_room', { room_id: roomId })
    .then((ack) => {
      if (ack.status !== 'success') {
        fail(ack.message || '解散房间失败')
        return
      }
      if (lobby.ownRoomId === roomId) lobby.clearOwnRoom()
      setNotice('房间已解散')
    })
    .catch((error: unknown) => {
      fail(error instanceof Error ? error.message : String(error))
    })
}

function requestCloseOwnRoom(): void {
  if (!lobby.ownRoomId) return
  confirmingClose.value = true
}

function confirmCloseOwnRoom(): void {
  confirmingClose.value = false
  closeRoom(lobby.ownRoomId)
}

function cancelCloseOwnRoom(): void {
  confirmingClose.value = false
}

/** Empty-state CTA: creating a room is the one action that fills the list. */
function createRoomFromEmpty(): void {
  createRoom()
}

function toggleFold(panel: 'players' | 'chat' | 'matches'): void {
  openFold.value[panel] = !openFold.value[panel]
}

function startMatch(mode: 'casual' | 'ranked'): void {
  const socket = socketOrFail()
  if (!socket) return
  void socket
    .emitEvent('find_match', { player_name: lobbyPlayerName(), mode })
    .then((ack) => {
      if (ack.status === 'error') fail(ack.message || '匹配失败')
    })
    .catch((error: unknown) => {
      fail(error instanceof Error ? error.message : String(error))
    })
}

function cancelMatch(): void {
  const socket = socketOrFail()
  if (!socket) return
  void socket.emitEvent('cancel_match', {}).catch((error: unknown) => {
    fail(error instanceof Error ? error.message : String(error))
  })
}

function sendChat(): void {
  const text = chatDraft.value.trim()
  if (!text) return
  const socket = socketOrFail()
  if (!socket) return
  void socket
    .emitEvent('lobby_chat_send', { message: text })
    .then((ack) => {
      if (ack.status === 'error') {
        fail(ack.message || '发送失败')
        return
      }
      chatDraft.value = ''
    })
    .catch((error: unknown) => {
      fail(error instanceof Error ? error.message : String(error))
    })
}

async function loadFriends(): Promise<void> {
  if (friendsBusy.value) return
  friendsBusy.value = true
  try {
    const response = await fetch('/api/friends', {
      credentials: 'same-origin',
      headers: { accept: 'application/json' },
    })
    if (response.status === 401) {
      lobby.recordFriendsGuest()
      return
    }
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>
    if (!response.ok) {
      const message = typeof body.error === 'string' ? body.error : '读取好友列表失败'
      lobby.recordFriendsError(message)
      return
    }
    lobby.recordFriends(body)
  } catch (error) {
    lobby.recordFriendsError(error instanceof Error ? error.message : '读取好友列表失败')
  } finally {
    friendsBusy.value = false
  }
}

async function inviteFriend(friend: LobbyFriend): Promise<void> {
  if (!friend.username || invitingUsername.value) return
  const reason = inviteDisabledReason(friend)
  if (reason) {
    fail(reason)
    return
  }
  invitingUsername.value = friend.username
  try {
    const response = await fetch('/api/friends/invite', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', accept: 'application/json' },
      body: JSON.stringify({ username: friend.username }),
    })
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>
    if (!response.ok || body.status !== 'ok' || !body.room_id) {
      const message =
        typeof body.error === 'string' ? body.error : '邀战失败，请稍后再试'
      fail(message)
      return
    }
    const roomId = String(body.room_id)
    const socket = socketOrFail()
    if (!socket) return
    const joined = await socket.emitEvent('join_room', {
      room_id: roomId,
      player_name: lobbyPlayerName(),
    })
    if (joined.status !== 'success') {
      fail(joined.message || '进入房间失败')
      return
    }
    lobby.setOwnRoom(roomId, '好友邀战', true)
    setNotice('已邀请 ' + friend.username + '，等待对方进入房间 ' + roomId)
  } catch (error) {
    fail(error instanceof Error ? error.message : '邀战失败，请稍后再试')
  } finally {
    invitingUsername.value = ''
  }
}

async function acceptInvite(): Promise<void> {
  const invite = lobby.activeInvite
  if (!invite || acceptingInvite.value) return
  const socket = socketOrFail()
  if (!socket) return
  acceptingInvite.value = true
  try {
    const ack = await socket.emitEvent('join_room', {
      room_id: invite.roomId,
      player_name: lobbyPlayerName(),
    })
    if (ack.status !== 'success') {
      fail(ack.message || '进入房间失败')
      return
    }
    lobby.clearInvite()
    setNotice('已进入房间 ' + invite.roomId + '，等待对局开始…')
  } catch (error) {
    fail(error instanceof Error ? error.message : '进入房间失败')
  } finally {
    acceptingInvite.value = false
  }
}

function dismissInvite(): void {
  lobby.clearInvite()
}

function openSpectate(match: LobbyMatch): void {
  void router.push({ name: 'spectate', query: { room_id: match.roomId } })
}

function backHome(): void {
  void router.push({ name: 'start' })
}

// A matchmaking pair shows the 匹配成功 overlay first (the legacy screen's five
// second countdown); only non-matchmaking room starts navigate immediately.
function maybeLeaveLobbyForMatch(): void {
  if (!lobby.startedRoomId) return
  if (lobby.matchFound) return
  const roomId = lobby.takeStartedRoom()
  if (roomId) void router.push({ name: 'placement' })
}

function onMatchFoundDone(): void {
  const roomId = lobby.takeStartedRoom() || lobby.matchFound?.roomId || ''
  lobby.clearMatchFound()
  if (roomId) void router.push({ name: 'placement' })
}

watch(() => lobby.startedRoomId, maybeLeaveLobbyForMatch)
watch(() => lobby.matchFound, maybeLeaveLobbyForMatch)

// Keep the newest line visible without ever clearing the frame (legacy
// behaviour). The draft lives in a separate input, so this cannot wipe it.
watch(
  () => lobby.chat.length,
  async () => {
    await nextTick()
    if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight
  },
)

// The announcement column is the same data the home screen already fetches
// (spec §4: one-line closable notice in the lobby too; no new endpoint).
const CHANGELOG_CLOSED_KEY = 'battleship.lobby.changelogClosed'
const changelogClosed = ref(false)
const changelogText = computed(() => {
  const latest = home.changelog[0]
  if (!latest || !Array.isArray(latest.items) || !latest.items.length) return ''
  return latest.items.join('；')
})

function closeChangelog(): void {
  changelogClosed.value = true
  try {
    window.localStorage.setItem(CHANGELOG_CLOSED_KEY, '1')
  } catch {
    // Storage is best effort; the line still closes for this visit.
  }
}

onMounted(() => {
  try {
    changelogClosed.value = window.localStorage.getItem(CHANGELOG_CLOSED_KEY) === '1'
  } catch {
    changelogClosed.value = false
  }
  if (!home.changelogLoaded) void home.loadChangelog(1)
  releaseChannel = acquireLobbyChannel()
  void loadFriends()
  maybeLeaveLobbyForMatch()
})

onBeforeUnmount(() => {
  // A late room_sync after the route change must not leave a stale "start a
  // match" flag for the next time this screen is mounted.
  lobby.takeStartedRoom()
  releaseChannel?.()
  releaseChannel = null
})
</script>

<template>
  <MatchFoundOverlay
    v-if="lobby.matchFound"
    :self-name="lobby.matchFound.playerName"
    :opponent-name="lobby.matchFound.opponentName"
    :mode="lobby.matchFound.mode"
    @done="onMatchFoundDone"
  />

  <section
    class="screen lobby"
    data-screen="lobby"
    data-testid="screen-lobby"
    :data-lobby-filter="filter"
    aria-labelledby="screen-lobby-title"
  >
    <header class="lobby__head">
      <div class="lobby__title-block">
        <p class="lobby__eyebrow">竞技场 · 大厅</p>
        <h1 id="screen-lobby-title" class="lobby__title" data-testid="lobby-heading">游戏大厅</h1>
        <p class="lobby__hint">匹配、房间、公屏与好友邀战都在这一页，状态由服务端实时推送。</p>
      </div>

      <div class="lobby__topbar" aria-label="大厅统计">
        <span class="lobby__stat">在线玩家 <b data-testid="lobby-online-count">{{ countText(lobby.onlineCount) }}</b></span>
        <span class="lobby__stat">大厅中 <b data-testid="lobby-lobby-count">{{ countText(lobby.lobbyCount) }}</b></span>
        <span class="lobby__stat">休闲队列 <b data-testid="lobby-queue-casual">{{ countText(lobby.queueCasual) }}</b></span>
        <span class="lobby__stat">排位队列 <b data-testid="lobby-queue-ranked">{{ countText(lobby.queueRanked) }}</b></span>
        <span v-if="queueLabel" class="lobby__queue" data-testid="lobby-queue-state">{{ queueLabel }}</span>
        <button type="button" class="button button--ghost" data-testid="lobby-refresh" @click="refresh">刷新</button>
      </div>
    </header>

    <p v-if="!changelogClosed && changelogText" class="lobby__changelog" data-testid="lobby-changelog" role="status">
      <span class="lobby__changelog-text">公告 · {{ changelogText }}</span>
      <button type="button" class="lobby__changelog-close" data-testid="lobby-changelog-close" aria-label="关闭公告" @click="closeChangelog">关闭</button>
    </p>

    <p v-if="lobby.notice" class="lobby__notice" data-testid="lobby-notice" role="status">{{ lobby.notice }}</p>
    <p v-if="lobby.error" class="lobby__error" data-testid="lobby-error" role="alert">
      {{ lobby.error }}
      <button type="button" class="lobby__dismiss" data-testid="lobby-error-dismiss" @click="lobby.clearError">知道了</button>
    </p>

    <section class="lobby__primary" aria-label="大厅主行动">
      <button
        type="button"
        class="lobby__primary-action"
        data-testid="lobby-match-casual"
        data-primary-action
        :disabled="lobby.queueMode === 'casual'"
        @click="startMatch('casual')"
      >
        <b>快速匹配</b>
        <span>随机找一位在线玩家，马上开局</span>
      </button>
      <button
        type="button"
        class="lobby__primary-action lobby__primary-action--room"
        data-testid="lobby-create-room"
        @click="createRoom"
      >
        <b>创建房间</b>
        <span>开一桌，等好友或大厅玩家加入</span>
      </button>
      <div class="lobby__primary-side">
        <button
          type="button"
          class="button button--ghost"
          data-testid="lobby-match-ranked"
          :disabled="lobby.queueMode === 'ranked'"
          @click="startMatch('ranked')"
        >排位匹配</button>
        <button
          v-if="lobby.queueMode"
          type="button"
          class="button button--danger"
          data-testid="lobby-match-cancel"
          @click="cancelMatch"
        >取消匹配</button>
        <button type="button" class="button button--ghost" data-testid="lobby-back-home" @click="backHome">返回首页</button>
      </div>
    </section>

    <div class="lobby__filterbar">
      <input
        v-model="query"
        type="search"
        class="lobby__search"
        data-testid="lobby-search"
        maxlength="20"
        placeholder="搜索房名、房主或对局玩家…"
        aria-label="搜索房间或对局"
      />
      <div class="lobby__seg" role="group" aria-label="大厅状态筛选">
        <button
          v-for="item in FILTERS"
          :key="item.value"
          type="button"
          class="lobby__seg-btn"
          :class="{ 'is-active': filter === item.value }"
          :aria-pressed="filter === item.value ? 'true' : 'false'"
          :data-testid="'lobby-filter-' + item.value"
          @click="filter = item.value"
        >
          {{ item.label }}
        </button>
      </div>
    </div>

    <div class="lobby__columns" :data-filter="filter">
      <section class="lobby__panel lobby__panel--rooms" aria-label="房间列表">
        <div class="lobby__panel-head">
          <h2 class="lobby__panel-title">房间列表</h2>
          <span class="lobby__panel-meta">{{ lobby.rooms.length }} 间在等</span>
        </div>

        <div v-if="lobby.ownRoomId" class="lobby__own" data-testid="lobby-own-room">
          <div class="lobby__own-main">
            <b>我的房间</b>
            <span class="lobby__own-name">{{ lobby.ownRoomName || '未命名房间' }}</span>
            <code data-testid="lobby-own-room-id">{{ lobby.ownRoomId }}</code>
            <span>{{ lobby.ownRoomPublic ? '公开' : '私密' }} · 等待玩家加入</span>
          </div>
          <template v-if="confirmingClose">
            <p class="lobby__own-confirm" data-testid="lobby-own-room-confirm-text" role="alert">
              解散后房间立刻从大厅消失，其他人不能再加入。确定解散？
            </p>
            <div class="lobby__own-actions">
              <button
                type="button"
                class="button button--danger"
                data-testid="lobby-own-room-close-confirm"
                @click="confirmCloseOwnRoom"
              >
                确认解散
              </button>
              <button
                type="button"
                class="button button--ghost"
                data-testid="lobby-own-room-close-cancel"
                @click="cancelCloseOwnRoom"
              >
                保留房间
              </button>
            </div>
          </template>
          <button
            v-else
            type="button"
            class="button button--danger"
            data-testid="lobby-own-room-close"
            @click="requestCloseOwnRoom"
          >
            解散房间
          </button>
        </div>

        <StateSurface v-if="roomsVisible" class="lobby__room-results" :state="roomsState" loading-text="房间列表载入中…" @retry="refresh">
        <ul class="lobby__list" data-testid="lobby-rooms">
          <li
            v-for="room in filteredRooms"
            :key="room.roomId"
            class="lobby__room"
            :class="{ 'is-full': !roomJoinable(room), 'is-own': room.roomId === lobby.ownRoomId }"
            :data-testid="'lobby-room-' + room.roomId"
          >
            <span class="lobby__room-main">
              <span class="lobby__room-state">{{ roomJoinable(room) ? '等待加入' : '已满' }}</span>
              <b class="lobby__room-name">{{ room.name }}</b>
              <span class="lobby__room-tags">
                <span class="lobby__tag" data-testid="lobby-room-mode">{{ roomModeText(room) }}</span>
                <span class="lobby__tag lobby__tag--muted" data-testid="lobby-room-visibility">
                  {{ roomVisibilityText(room) }}
                </span>
              </span>
              <span class="lobby__muted">房主 {{ room.host || '玩家' }}</span>
              <span class="lobby__muted">房号 {{ room.roomId }}</span>
            </span>
            <span class="lobby__room-seats">{{ roomSeatsText(room) }}</span>
            <button
              type="button"
              class="button button--small"
              :data-testid="'lobby-room-join-' + room.roomId"
              :disabled="!roomJoinable(room)"
              :title="roomJoinable(room) ? '加入这间房' : '这间房已经坐满了'"
              @click="joinRoom(room)"
            >
              加入
            </button>
            <button
              v-if="room.roomId === lobby.ownRoomId"
              type="button"
              class="button button--small button--danger"
              :data-testid="'lobby-room-close-' + room.roomId"
              @click="closeRoom(room.roomId)"
            >
              解散
            </button>
          </li>
        </ul>
        <template #empty>
          <p class="lobby__empty" data-testid="lobby-rooms-empty">{{ roomsEmpty }}</p>
          <button type="button" class="button lobby__empty-cta" data-testid="lobby-rooms-empty-cta" @click="createRoomFromEmpty">
            开一桌
          </button>
        </template>
        <template #error>
          <p class="lobby__empty" data-testid="lobby-rooms-empty">{{ roomsEmpty }}</p>
        </template>
        </StateSurface>

        <div class="lobby__create">
          <input
            v-model="roomName"
            type="text"
            class="lobby__input"
            data-testid="lobby-room-name"
            maxlength="20"
            placeholder="房间名（可留空）"
            aria-label="房间名"
          />
          <label class="lobby__checkbox" title="取消勾选 = 私密房，只能凭房号加入">
            <input v-model="roomPublic" type="checkbox" data-testid="lobby-room-public" />
            公开
          </label>

          <p class="lobby__create-hint">取消勾选「公开」= 私密房，只有拿到房号的人能加入。</p>
        </div>
      </section>

      <section v-if="matchesVisible" class="lobby__panel lobby__panel--matches" aria-label="进行中的对局">
        <div class="lobby__panel-head">
          <h2 class="lobby__panel-title">进行中的对局</h2>
          <span class="lobby__panel-meta">{{ lobby.matches.length }} 局</span>
          <button
            type="button"
            class="lobby__fold"
            data-testid="lobby-fold-matches"
            :aria-expanded="openFold.matches"
            @click="toggleFold('matches')"
          >
            {{ openFold.matches ? '收起' : '展开' }}
          </button>
        </div>
        <div v-show="openFold.matches" class="lobby__panel-body">
        <ul class="lobby__list" data-testid="lobby-matches">
          <li
            v-for="match in filteredMatches"
            :key="match.roomId"
            class="lobby__match"
            :data-testid="'lobby-match-' + match.roomId"
          >
            <span class="lobby__match-main">
              <b class="lobby__match-name">{{ matchNamesText(match) }}</b>
              <span v-if="match.ranked" class="lobby__tag">排位</span>
              <span class="lobby__muted">第 {{ match.round }} 回合 · {{ matchSpectateText(match) }}</span>
            </span>
            <button
              type="button"
              class="button button--small"
              :data-testid="'lobby-match-spectate-' + match.roomId"
              @click="openSpectate(match)"
            >
              观战
            </button>
          </li>
        </ul>
        <p v-if="!filteredMatches.length" class="lobby__empty" data-testid="lobby-matches-empty">{{ matchesEmpty }}</p>
        </div>
      </section>

      <section class="lobby__panel lobby__panel--players" aria-label="在线玩家">
        <div class="lobby__panel-head">
          <h2 class="lobby__panel-title">在线玩家</h2>
          <span class="lobby__panel-meta">{{ lobby.players.length }} 人</span>
          <button
            type="button"
            class="lobby__fold"
            data-testid="lobby-fold-players"
            :aria-expanded="openFold.players"
            @click="toggleFold('players')"
          >
            {{ openFold.players ? '收起' : '展开' }}
          </button>
        </div>
        <div v-show="openFold.players" class="lobby__panel-body">
        <ul class="lobby__list" data-testid="lobby-players">
          <li
            v-for="player in lobby.players"
            :key="player.key"
            class="lobby__player"
            :class="{ 'is-me': isMePlayer(player.key) }"
            :data-testid="'lobby-player-' + player.key"
          >
            <span class="lobby__avatar" :style="avatarStyle(player.avatar)">{{ player.avatar ? '' : initial(player.name) }}</span>
            <span class="lobby__player-main">
              <span class="lobby__player-line">
                <span :class="playerNameClass(player.nameStyle)">{{ player.name }}</span>
                <span v-if="isMePlayer(player.key)" class="lobby__tag" data-testid="lobby-player-me">我</span>
                <span v-if="player.guest" class="lobby__tag lobby__tag--muted">游客</span>
                <span v-if="player.title" class="lobby__player-title">{{ player.title }}</span>
              </span>
              <span class="lobby__player-meta">
                <span>{{ levelText(player) }}</span>
                <span v-if="rankText(player)">{{ rankText(player) }}</span>
                <span class="lobby__status" :data-status="player.status">{{ statusText(player) }}</span>
              </span>
            </span>
          </li>
        </ul>
        <p v-if="!lobby.players.length" class="lobby__empty" data-testid="lobby-players-empty">当前没有在线玩家</p>
        </div>
      </section>

      <details class="lobby__panel lobby__panel--friends" data-testid="lobby-friends" aria-label="好友邀战">
        <summary class="lobby__panel-head">
          <h2 class="lobby__panel-title">好友邀战</h2>
          <button type="button" class="button button--small button--ghost" data-testid="lobby-friends-refresh" @click="loadFriends">
            刷新
          </button>
        </summary>
        <p v-if="lobby.friendsGuest" class="lobby__empty" data-testid="lobby-friends-guest">登录后可以邀请好友对战。</p>
        <p v-else-if="lobby.friendsError" class="lobby__empty lobby__empty--error" data-testid="lobby-friends-error">{{ lobby.friendsError }}</p>
        <ul v-else-if="friendListVisible" class="lobby__list" data-testid="lobby-friend-list">
          <li
            v-for="friend in lobby.friends"
            :key="friend.userId"
            class="lobby__friend"
            :data-testid="'lobby-friend-' + friend.userId"
          >
            <span class="lobby__avatar lobby__avatar--small" :style="avatarStyle(friend.avatar)">{{ friend.avatar ? '' : initial(friend.username) }}</span>
            <span class="lobby__friend-main">
              <b>{{ friend.username || friend.userId }}</b>
              <span class="lobby__muted">{{ friendStatus(friend) }} · Lv.{{ friend.level }}</span>
            </span>
            <button
              type="button"
              class="button button--small"
              :data-testid="'lobby-friend-invite-' + friend.userId"
              :disabled="Boolean(inviteDisabledReason(friend)) || invitingUsername === friend.username"
              :title="friendInviteReason(friend)"
              @click="inviteFriend(friend)"
            >
              {{ invitingUsername === friend.username ? '邀战中…' : '邀战' }}
            </button>
          </li>
        </ul>
        <p v-if="friendListVisible && !lobby.friends.length" class="lobby__empty" data-testid="lobby-friends-empty">
          还没有好友。加好友后就能在这里直接邀战。
        </p>
        <p v-else-if="!lobby.friendsLoaded" class="lobby__empty">正在读取好友列表…</p>
      </details>

      <section class="lobby__panel lobby__panel--chat" :class="{ 'is-collapsed': !openFold.chat }" aria-label="大厅公屏">
        <div class="lobby__panel-head">
          <h2 class="lobby__panel-title">大厅公屏</h2>
          <span class="lobby__panel-meta">{{ lobby.chat.length }} 条</span>
          <button
            type="button"
            class="lobby__fold"
            data-testid="lobby-fold-chat"
            :aria-expanded="openFold.chat"
            @click="toggleFold('chat')"
          >
            {{ openFold.chat ? '收起' : '展开' }}
          </button>
        </div>
        <div v-show="openFold.chat" class="lobby__panel-body">
        <div ref="chatEl" class="lobby__chat" data-testid="lobby-chat" role="log" aria-live="polite">
          <div
            v-for="item in lobby.chat"
            :key="chatKey(item.seq, item.key, item.ts)"
            class="lobby__chat-item"
            :class="{ 'is-me': isMineChat(item.key) }"
            :data-testid="'lobby-chat-message-' + chatKey(item.seq, item.key, item.ts)"
          >
            <span class="lobby__chat-time">{{ timeText(item.ts) }}</span>
            <span class="lobby__chat-name">{{ item.name }}：</span>
            <span class="lobby__chat-text">{{ item.message }}</span>
          </div>
          <p v-if="!lobby.chat.length" class="lobby__empty" data-testid="lobby-chat-empty">还没有人说话，打个招呼吧。</p>
        </div>
        <div class="lobby__chat-row">
          <input
            v-model="chatDraft"
            type="text"
            class="lobby__input"
            data-testid="lobby-chat-input"
            maxlength="120"
            placeholder="说点什么…"
            aria-label="大厅聊天输入"
            @keydown.enter.prevent="sendChat"
          />
          <button type="button" class="button" data-testid="lobby-chat-send" @click="sendChat">发送</button>
        </div>
        </div>
      </section>
    </div>



    <div v-if="lobby.activeInvite" class="lobby__invite" data-testid="lobby-invite-banner" role="status">
      <span class="lobby__invite-text">
        <b>{{ lobby.activeInvite.fromUsername }}</b> 邀请你加入房间
        <code>{{ lobby.activeInvite.roomId }}</code>
      </span>
      <button type="button" class="button" data-testid="lobby-invite-accept" :disabled="acceptingInvite" @click="acceptInvite">
        进入房间
      </button>
      <button type="button" class="button button--ghost" data-testid="lobby-invite-dismiss" @click="dismissInvite">
        忽略
      </button>
    </div>

  </section>
</template>

<style scoped>
.lobby {
  width: 100%;
  max-width: 1120px;
  margin: 0 auto;
  gap: 12px;
  padding: 18px 22px 28px;
}

.lobby__head {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: stretch;
}

.lobby__title-block {
  min-width: 0;
}

.lobby__eyebrow {
  display: none;
}

.lobby__title {
  margin: 0;
  font-size: 26px;
  line-height: 1.2;
}

.lobby__hint {
  margin: 2px 0 0;
  max-width: 62ch;
  color: var(--text-muted);
  font-size: 12px;
}

.lobby__topbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 10px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--panel-line);
}

.lobby__topbar [data-testid='lobby-refresh'] {
  margin-left: auto;
}

.lobby__stat {
  padding: 5px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--surface-deck);
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.lobby__stat b {
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.lobby__queue {
  color: var(--accent);
  font-size: 12px;
}

.lobby__changelog {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  padding: 2px 0;
  border: 0;
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 12px;
}

.lobby__changelog-text {
  flex: 1;
  min-width: 0;
}

.lobby__changelog-close {
  min-width: 44px;
  min-height: 32px;
  padding: 2px 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-deck);
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.lobby__notice,
.lobby__error {
  margin: 0;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
}

.lobby__notice {
  color: var(--accent-strong);
  background: var(--accent-soft);
}

.lobby__error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: var(--role-enemy);
  background: #2a1414;
  border-color: #6a2a2a;
}

.lobby__dismiss {
  margin-left: auto;
  padding: 2px 8px;
  border: 1px solid #6a2a2a;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.lobby__filterbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.lobby__search,
.lobby__input {
  min-width: 0;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-sunken);
  color: var(--text);
  font: inherit;
}

.lobby__search {
  flex: 0 1 320px;
  width: 100%;
}

.lobby__seg {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-left: auto;
  padding: 3px;
  border: 1px solid var(--panel-line);
  border-radius: 999px;
  background: var(--surface-deck);
}

.lobby__seg-btn {
  padding: 6px 11px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.lobby__seg-btn.is-active {
  border-color: var(--accent-strong);
  background: var(--accent-soft);
  color: var(--text);
}

.lobby__columns {
  --lobby-panel-height: 300px;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
}

/* 四个主面板共用硬尺寸，内容的最小高度不能反过来撑大网格。 */
.lobby__columns > section.lobby__panel {
  box-sizing: border-box;
  height: var(--lobby-panel-height);
  min-height: 0;
  max-height: var(--lobby-panel-height);
  overflow: hidden;
  contain: size;
}

.lobby__room-results {
  flex: 1 1 0;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.lobby__panel--rooms > .lobby__create {
  flex: 0 0 auto;
}

.lobby__panel--rooms > .lobby__own {
  flex: 0 1 auto;
  min-height: 0;
  max-height: 100px;
  overflow-y: auto;
}

.lobby__panel-body > .lobby__list {
  flex: 1 1 0;
  min-height: 0;
  max-height: none;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.lobby__panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: var(--panel);
  box-shadow: var(--shadow-panel);
}

.lobby__panel-head {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--line-dash);
}

.lobby__panel-head .lobby__panel-title {
  flex: 1;
}

.lobby__panel--friends {
  display: block;
  max-height: 300px;
  overflow-y: auto;
}

.lobby__panel--friends > summary {
  cursor: pointer;
  list-style: none;
}

.lobby__panel--friends > summary::-webkit-details-marker {
  display: none;
}

.lobby__panel--friends > summary::after {
  content: '展开';
  color: var(--text-secondary);
  font-size: 12px;
}

.lobby__panel--friends[open] > summary::after {
  content: '收起';
}

.lobby__panel--friends:not([open]) > summary {
  border: 0;
  padding-bottom: 0;
}

.lobby__panel--friends[open] > summary {
  margin-bottom: 12px;
}

.lobby__panel-title {
  margin: 0;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.1em;
}

.lobby__panel-meta {
  color: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.lobby__list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 280px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

/* Waiting rooms are a two-column card grid in the C+ lobby. */
.lobby__panel--rooms .lobby__list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  max-height: none;
  overflow: visible;
}

.lobby__player,
.lobby__room,
.lobby__match,
.lobby__friend {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-deck);
}

.lobby__room {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 56px;
  grid-template-areas:
    'main seats'
    'main join'
    'main close';
  gap: 4px 8px;
  align-items: end;
  padding: 10px;
  border-radius: 10px;
}

.lobby__room .lobby__room-main {
  grid-area: main;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.lobby__room-state {
  padding: 2px 9px;
  border: 1px solid rgba(78, 200, 224, 0.5);
  border-radius: 999px;
  color: var(--accent-cyan);
  font-size: 11px;
  order: -1;
}

.lobby__room.is-full .lobby__room-state {
  border-color: color-mix(in srgb, var(--gold) 55%, transparent);
  color: var(--gold-strong);
}

.lobby__room-seats {
  grid-area: seats;
}

.lobby__room [data-testid^='lobby-room-join-'] {
  grid-area: join;
}

.lobby__room [data-testid^='lobby-room-close-'] {
  grid-area: close;
}

.lobby__room .button {
  min-height: 32px;
  padding: 4px 6px;
}

.lobby__player.is-me {
  border-color: color-mix(in srgb, var(--role-action) 60%, transparent);
  background: var(--role-action-soft);
}

.lobby__avatar {
  display: grid;
  flex: none;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background-color: var(--surface-elevated);
  background-position: center;
  background-size: cover;
  color: var(--role-action);
  font-size: 14px;
  font-weight: 700;
}

.lobby__avatar--small {
  width: 26px;
  height: 26px;
  font-size: 12px;
}

.lobby__player-main,
.lobby__friend-main,
.lobby__room-main,
.lobby__match-main {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 8px;
  min-width: 0;
}

.lobby__friend-main {
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
}

.lobby__player-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.lobby__player-name {
  overflow-wrap: anywhere;
}

.lobby__player-name--rainbow {
  background: linear-gradient(90deg, #7ee8fa, var(--gold-strong), var(--role-enemy), #7ee8fa);
  background-clip: text;
  color: transparent;
}

.lobby__player-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 12px;
}

.lobby__player-title {
  color: var(--gold-strong);
  font-size: 11px;
}

.lobby__tag {
  padding: 1px 6px;
  border: 1px solid color-mix(in srgb, var(--role-action) 60%, transparent);
  border-radius: 999px;
  color: var(--accent-strong);
  font-size: 10px;
}

.lobby__tag--muted {
  border-color: var(--border);
  color: var(--text-muted);
}

.lobby__status[data-status='idle'] {
  color: #9ad7b0;
}

.lobby__status[data-status='matching'] {
  color: var(--gold-strong);
}

.lobby__status[data-status='in_room'] {
  color: var(--accent);
}

.lobby__status[data-status='in_game'] {
  color: #ff9d8f;
}

.lobby__room-seats {
  flex: none;
  color: var(--text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.lobby__room-name,
.lobby__match-name {
  overflow-wrap: anywhere;
}

.lobby__room.is-full {
  opacity: 0.72;
}

.lobby__room.is-own {
  border-color: #3d6b4c;
}

.lobby__muted {
  color: var(--text-muted);
  font-size: 12px;
}

.lobby__empty {
  margin: 0;
  padding: 10px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.lobby__empty--error {
  color: var(--role-enemy);
}

.lobby__empty--error {
  color: var(--role-enemy);
}

.lobby__own {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--role-success) 40%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--role-success) 14%, transparent);
}

.lobby__own-main {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  min-width: 0;
  font-size: 12px;
}

.lobby__own-name {
  font-weight: 700;
}

.lobby__own code,
.lobby__invite code {
  padding: 1px 5px;
  border: 1px solid var(--border);
  border-radius: 5px;
}

.lobby__create {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px dashed var(--line-dash);
}

.lobby__create .lobby__input {
  flex: 1 1 150px;
}

.lobby__create-hint {
  flex-basis: 100%;
  margin: 0;
  color: var(--text-tertiary);
  font-size: 11px;
}

/* 两个主行动置于四个面板上方，沿用现有匹配与创建事件。 */
.lobby__primary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr)) auto;
  gap: 10px;
  align-items: stretch;
}

.lobby__primary-action {
  display: grid;
  gap: 3px;
  min-height: 88px;
  padding: 16px 20px;
  border: 1px solid color-mix(in srgb, var(--role-action) 55%, transparent);
  border-radius: var(--radius);
  background: var(--hero-grad);
  color: #fff;
  font: inherit;
  text-align: left;
  cursor: pointer;
  box-shadow: var(--shadow-accent);
  transition: border-color var(--duration-fast) var(--ease), filter var(--duration-fast) var(--ease);
}

.lobby__primary-action b {
  font-size: 18px;
  font-weight: 700;
}

.lobby__primary-action span {
  display: block;
  color: rgba(255, 255, 255, 0.78);
  font-size: 12px;
  line-height: 1.5;
}

.lobby__primary-action:hover:not(:disabled) {
  filter: brightness(1.07);
}

/* Secondary action stays on the panel surface so the purple hero wins. */
.lobby__primary-action--room {
  border-color: var(--panel-line);
  background: var(--surface-chamber);
  color: var(--text-primary);
  box-shadow: none;
}

.lobby__primary-action--room:hover:not(:disabled) {
  background: var(--surface-raised);
}

.lobby__primary-action--room span {
  color: var(--text-secondary);
}

.lobby__primary-action:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.lobby__primary-side {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 10px;
}

.lobby__primary-side .button {
  min-height: 40px;
  white-space: nowrap;
}

.lobby__own-confirm {
  flex-basis: 100%;
  margin: 0;
  color: var(--role-warning);
  font-size: 12px;
}

.lobby__own-actions {
  display: flex;
  gap: 8px;
}

.lobby__room-tags {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 5px;
}

.lobby__fold {
  min-height: 40px;
  padding: 4px 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.lobby__fold:hover {
  border-color: var(--role-self);
  color: var(--text-primary);
}

.lobby__panel-body {
  display: flex;
  flex: 1 1 0;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

/* 面板高度不跟随消息数变化，标题与输入栏常驻，只有消息区滚动。 */
.lobby__panel--chat {
  overflow: hidden;
}

.lobby__panel--chat > .lobby__panel-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.lobby__panel--chat .lobby__chat {
  flex: 1;
  min-height: 0;
  max-height: none;
  overscroll-behavior: contain;
}

.lobby__panel--chat .lobby__chat-row {
  flex: 0 0 auto;
  min-width: 0;
}

.lobby__chat-row .lobby__input {
  min-width: 0;
}

.lobby__empty-cta {
  align-self: flex-start;
  margin-top: 8px;
}

.lobby__checkbox {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.lobby__checkbox input {
  width: 16px;
  height: 16px;
  min-height: 0;
  padding: 0;
}

.lobby__chat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 150px;
  max-height: 300px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-deck);
}

.lobby__chat-item {
  display: flex;
  flex: 0 0 auto;
  min-width: 0;
  overflow-wrap: anywhere;
  flex-wrap: wrap;
  gap: 2px 6px;
  color: var(--text);
  font-size: 13px;
}

.lobby__chat-item.is-me .lobby__chat-name {
  color: var(--accent);
}

.lobby__chat-time {
  color: var(--text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.lobby__chat-name {
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
  color: var(--gold-strong);
  font-size: 12px;
}

.lobby__chat-text {
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.lobby__chat-row {
  display: flex;
  gap: 8px;
}

.lobby__chat-row .lobby__input {
  flex: 1;
}

.lobby__invite {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--role-success) 40%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--role-success) 14%, transparent);
}

.lobby__invite-text {
  flex: 1 1 240px;
  min-width: 0;
  font-size: 13px;
}

.lobby__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: auto;
  padding-top: 4px;
}

.button--small {
  padding: 4px 9px;
  font-size: 12px;
}

.button--ghost {
  border-color: var(--border);
  background: transparent;
  color: var(--text-muted);
}

.button--ghost:hover {
  background: var(--accent-soft);
  color: var(--text);
}

.button--danger {
  border-color: #6a2a2a;
  background: #2a1414;
  color: var(--role-enemy);
}

.button--danger:hover {
  background: #3a1b1b;
}

.button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 对照原版大厅：居中两列，左侧房间/对局，右侧玩家/公屏。 */
@media (min-width: 980px) {
  /* 先给房间卡留完整一行，再让下排分享剩余视口；两列使用相同网格行。 */
  .lobby {
    flex: 0 0 auto;
    box-sizing: border-box;
    height: calc(100dvh - 64px);
    min-height: 0;
    gap: 8px;
    padding: 10px 22px 12px;
  }

  .lobby > :not(.lobby__columns) { flex-shrink: 0; }
  .lobby__head { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; }
  .lobby__title { font-size: 24px; }
  .lobby__hint { max-width: 42ch; font-size: 11px; }
  .lobby__topbar { padding: 0; border: 0; gap: 6px; }
  .lobby__stat { padding: 4px 8px; font-size: 11px; }
  .lobby__primary-action { min-height: 76px; padding: 12px 18px; }
  .lobby__primary-side .button { min-height: 32px; padding: 4px 12px; }
  .lobby__filterbar { min-height: 34px; }
  .lobby__panel-head { padding-bottom: 6px; gap: 6px; }
  .lobby__fold { min-height: 28px; padding: 2px 10px; }
  .lobby__own { padding: 6px 8px; gap: 6px; }
  .lobby__own .button { min-height: 30px; padding: 3px 8px; }
  .lobby__create { padding-top: 6px; gap: 6px; }
  .lobby__create-hint { display: none; }
  .lobby__create .lobby__input { min-height: 34px; }
  .lobby__panel--friends { padding: 8px 12px; max-height: 90px; }
  .lobby__panel--friends .button { min-height: 28px; padding: 2px 8px; }

  .lobby__columns {
    flex: 1 1 0;
    min-height: 0;
    grid-template-columns: minmax(0, 1fr) 294px;
    grid-template-rows: minmax(0, min(360px, calc((100% - 66px) * .69))) minmax(0, 1fr) auto;
    gap: 10px 14px;
    align-items: stretch;
  }

  .lobby__columns > section.lobby__panel {
    height: 100%;
    max-height: 100%;
    padding: 10px 12px;
    gap: 6px;
  }

  .lobby__columns > section.lobby__panel--matches,
  .lobby__columns > section.lobby__panel--chat {
    max-height: 300px;
  }

  .lobby__panel--rooms {
    grid-column: 1;
    grid-row: 1;
  }

  .lobby__panel--matches {
    grid-column: 1;
    grid-row: 2;
  }

  .lobby__panel--players {
    grid-column: 2;
    grid-row: 1;
  }

  .lobby__panel--chat {
    grid-column: 2;
    grid-row: 2;
  }

  .lobby__panel--chat > .lobby__panel-body {
    flex: 1;
  }

  .lobby__panel--chat .lobby__chat {
    flex: 1;
    min-height: 0;
    max-height: none;
    border: 0;
    background: transparent;
    padding: 0;
  }

  .lobby__chat-row {
    padding-top: 10px;
    border-top: 1px dashed var(--line-dash);
  }

  .lobby__panel--friends {
    grid-column: 1 / -1;
    grid-row: 3;
  }

  .lobby__columns[data-filter='watchable'] .lobby__panel--matches {
    grid-row: 2;
  }

  .lobby__columns[data-filter='joinable'] .lobby__panel--rooms,
  .lobby__columns[data-filter='full'] .lobby__panel--rooms {
    grid-row: 1;
  }
}

@media (max-width: 979px) {
  .lobby { padding: 14px 16px 24px; }
  .lobby__columns { gap: 14px; }
  .lobby__panel--rooms { order: 0; }
  .lobby__panel--players { order: 1; }
  .lobby__panel--matches { order: 2; }
  .lobby__panel--chat { order: 3; }
  .lobby__panel--friends { order: 4; }
  .lobby__primary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .lobby__primary-side { grid-column: 1 / -1; flex-direction: row; flex-wrap: wrap; }
  .lobby__columns > .lobby__panel--chat.is-collapsed { height: auto; contain: none; }
  .lobby__columns > section.lobby__panel--rooms { height: 420px; max-height: 420px; }
  .lobby__panel--rooms .lobby__list { grid-template-columns: minmax(0, 1fr); }
}

@media (max-width: 560px) {
  .lobby__primary { grid-template-columns: minmax(0, 1fr); }
}

@media (max-width: 520px) {
  .lobby__title {
    font-size: 23px;
  }

  .lobby__list,
  .lobby__chat {
    max-height: 240px;
  }

  .lobby__room,
  .lobby__match {
    flex-wrap: wrap;
  }
}
</style>
