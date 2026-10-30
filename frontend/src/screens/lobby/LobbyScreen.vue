<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
  buildInviteUrl,
  inviteFeedback,
  inviteManualPrompt,
  readInviteRoomId,
} from './inviteLink'
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
const route = useRoute()
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

const INVITE_JOINED_PREFIX = 'battleship.lobby.inviteJoined.'
const inviteCopyText = ref('')
/** 邀请链接的自动加入只允许发生一次：组件实例内的布尔 + sessionStorage 双保险。 */
let inviteJoinAttempted = false
let inviteJoinTimer: number | null = null

function inviteJoinedKey(roomId: string): string {
  return INVITE_JOINED_PREFIX + roomId
}

function inviteAlreadyJoined(roomId: string): boolean {
  try {
    return window.sessionStorage.getItem(inviteJoinedKey(roomId)) === '1'
  } catch {
    return false
  }
}

function rememberInviteJoined(roomId: string): void {
  try {
    window.sessionStorage.setItem(inviteJoinedKey(roomId), '1')
  } catch {
    // 存储不可用时仍靠实例内的布尔标志保证本次不重复加入。
  }
}

function clearInviteJoinTimer(): void {
  if (inviteJoinTimer !== null) {
    window.clearInterval(inviteJoinTimer)
    inviteJoinTimer = null
  }
}

/**
 * 等待同一个大厅 socket 连上（不注册额外监听，避免重连时反复触发）。
 * 连接迟迟不就绪就返回 null，由调用方给出「连接尚未就绪」的反馈。
 */
function waitForLobbyReady(timeoutMs = 8000): Promise<ReturnType<typeof getLobbySocket>> {
  const socket = getLobbySocket()
  if (socket && socket.socket.connected) return Promise.resolve(socket)
  return new Promise((resolve) => {
    const startedAt = Date.now()
    clearInviteJoinTimer()
    inviteJoinTimer = window.setInterval(() => {
      const next = getLobbySocket()
      if (next && next.socket.connected) {
        clearInviteJoinTimer()
        resolve(next)
        return
      }
      if (Date.now() - startedAt > timeoutMs) {
        clearInviteJoinTimer()
        resolve(null)
      }
    }, 120)
  })
}

/** 邀请链接带入的房间号：只在合法时才值得动作。 */
const inviteRoomId = computed(() => readInviteRoomId(route.query))

function copyInviteLink(): void {
  const roomId = lobby.ownRoomId
  if (!roomId) {
    inviteCopyText.value = '还没有房间，先创建房间再复制邀请链接'
    return
  }
  const url = buildInviteUrl(window.location.origin, '/lobby', roomId)
  const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : undefined
  if (clipboard && typeof clipboard.writeText === 'function') {
    void clipboard
      .writeText(url)
      .then(() => {
        inviteCopyText.value = inviteFeedback(true)
      })
      .catch(() => {
        window.prompt(inviteManualPrompt(url), url)
        inviteCopyText.value = inviteFeedback(false)
      })
    return
  }
  window.prompt(inviteManualPrompt(url), url)
  inviteCopyText.value = inviteFeedback(false)
}

/** 打开 `/lobby?room=xxx` 时自动加入一次；失败保留服务端文案，不静默跳转。 */
function tryJoinFromInvite(): void {
  const roomId = inviteRoomId.value
  if (!roomId || inviteJoinAttempted) return
  inviteJoinAttempted = true
  if (inviteAlreadyJoined(roomId)) {
    setNotice('已在房间 ' + roomId + ' 中，无需重复加入')
    return
  }
  void waitForLobbyReady().then((socket) => {
    if (!socket) {
      // 连接没起来不算「已加入」，允许用户刷新后再试一次。
      inviteJoinAttempted = false
      fail('连接尚未就绪，请稍后再试')
      return
    }
    rememberInviteJoined(roomId)
    void socket
      .emitEvent('join_room', { room_id: roomId, player_name: lobbyPlayerName() })
      .then((ack) => {
        if (ack.status !== 'success') {
          fail(ack.message || '加入房间失败')
          return
        }
        setNotice('已通过邀请链接加入房间 ' + roomId + '，对局即将开始')
      })
      .catch((error: unknown) => {
        fail(error instanceof Error ? error.message : String(error))
      })
  })
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
  tryJoinFromInvite()
  void loadFriends()
  maybeLeaveLobbyForMatch()
})

onBeforeUnmount(() => {
  // A late room_sync after the route change must not leave a stale "start a
  // match" flag for the next time this screen is mounted.
  lobby.takeStartedRoom()
  clearInviteJoinTimer()
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
        <h1 id="screen-lobby-title" class="lobby__title" data-testid="lobby-heading">游戏大厅</h1>
        <p class="lobby__hint">找一位对手，或与好友开一桌。</p>
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
      <div class="lobby__primary-copy">
        <span class="lobby__primary-mark" aria-hidden="true">✦</span>
        <div>
          <h2>随时开始一场对局</h2>
          <p>休闲随机匹配，也可以创建房间邀请好友。</p>
        </div>
      </div>
      <div class="lobby__primary-actions">
      <button
        type="button"
        class="lobby__primary-action"
        data-testid="lobby-match-casual"
        data-primary-action
        :disabled="lobby.queueMode === 'casual'"
        @click="startMatch('casual')"
      >
        快速匹配
      </button>
      <button
        type="button"
        class="lobby__primary-action lobby__primary-action--room"
        data-testid="lobby-create-room"
        @click="createRoom"
      >
        创建房间
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
      </div>
      </div>
    </section>

    <div class="lobby__columns" :data-filter="filter">
      <div class="lobby__directory">
    <div class="lobby__filterbar">
      <input
        v-model="query"
        type="search"
        class="lobby__search"
        data-testid="lobby-search"
        maxlength="20"
        placeholder="搜索房名、房主、房号或玩家"
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
          <button
            type="button"
            class="button button--ghost button--small"
            data-testid="lobby-copy-invite"
            title="复制可直接加入这间房的邀请链接"
            @click="copyInviteLink"
          >
            复制邀请链接
          </button>
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
        <p v-if="inviteCopyText" class="lobby__own-hint" data-testid="lobby-invite-feedback" role="status">
          {{ inviteCopyText }}
        </p>

        <div v-if="roomsVisible && filteredRooms.length" class="lobby__directory-head" aria-hidden="true">
          <span>房间</span><span>模式</span><span>人数</span><span>加入</span>
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
              <span class="lobby__room-symbol" aria-hidden="true">⚓</span>
              <span class="lobby__room-info">
              <b class="lobby__room-name">{{ room.name }}</b>
                <span class="lobby__room-meta">
                  <span>房主 {{ room.host || '玩家' }}</span>
                  <span data-testid="lobby-room-visibility">{{ roomVisibilityText(room) }}房间</span>
                  <span>房号 {{ room.roomId }}</span>
                </span>
              </span>
            </span>
            <span class="lobby__tag lobby__room-mode" data-testid="lobby-room-mode">{{ roomModeText(room) }}</span>
            <span class="lobby__room-seats">{{ roomSeatsText(room) }}</span>
            <span class="lobby__room-actions">
            <button
              type="button"
              class="button button--small"
              :data-testid="'lobby-room-join-' + room.roomId"
              :disabled="!roomJoinable(room)"
              :title="roomJoinable(room) ? '加入这间房' : '这间房已经坐满了'"
              @click="joinRoom(room)"
            >
              {{ roomJoinable(room) ? '加入房间' : '房间已满' }}
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
            </span>
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
      </div>

      <aside class="lobby__social" aria-label="大厅社交">
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
      </aside>
    </div>

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

    <footer class="lobby__footer">
      <button type="button" class="button button--ghost" data-testid="lobby-back-home" @click="backHome">返回首页</button>
    </footer>

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
  width: min(1490px, 100%);
  margin: 0 auto;
  gap: 16px;
  padding: 24px 28px 28px;
}
.lobby__head { display: flex; align-items: center; justify-content: space-between; gap: 16px 24px; }
.lobby__title-block { min-width: 0; }
.lobby__title { margin: 0; color: var(--text-primary); font-size: 30px; line-height: 1.25; }
.lobby__hint { margin: 6px 0 0; color: var(--text-secondary); font-size: 14px; }
.lobby__topbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px 16px; }
.lobby__stat { color: var(--text-secondary); font-size: 12px; white-space: nowrap; }
.lobby__stat b { margin-left: 4px; color: var(--text-primary); font-variant-numeric: tabular-nums; }
.lobby__stat:first-child::before { content: ''; display: inline-block; width: 6px; height: 6px; margin-right: 7px; border-radius: 50%; background: var(--role-success); vertical-align: middle; }
.lobby__queue { padding: 4px 8px; border-radius: 5px; background: var(--role-action-soft); color: var(--accent-strong); font-size: 12px; }
.lobby__changelog { display: flex; align-items: center; gap: 12px; margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.lobby__changelog-text { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.lobby__changelog-close, .lobby__dismiss { flex-shrink: 0; min-width: 44px; min-height: 32px; padding: 4px 9px; border: 1px solid var(--border-subtle); border-radius: 5px; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.lobby__notice, .lobby__error { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 0; padding: 10px 14px; border: 1px solid var(--border-subtle); border-radius: 8px; font-size: 14px; overflow-wrap: anywhere; }
.lobby__notice { color: var(--text-primary); background: var(--role-self-soft); }
.lobby__error { color: var(--role-enemy); border-color: color-mix(in srgb, var(--role-enemy) 38%, transparent); background: var(--role-enemy-soft); }
.lobby__dismiss { margin-left: auto; }
.lobby__primary { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 16px 24px; min-height: 84px; padding: 18px 22px; border: 1px solid var(--border-strong); border-radius: 11px; background: linear-gradient(110deg, color-mix(in srgb, var(--surface-raised) 88%, var(--role-action) 12%), var(--surface-deck)); }
.lobby__primary-copy { display: flex; flex: 1 1 290px; align-items: center; gap: 16px; min-width: 0; }
.lobby__primary-mark { display: grid; flex: 0 0 44px; place-items: center; height: 44px; border-radius: 9px; background: var(--role-action-soft); color: var(--role-action); font-size: 26px; }
.lobby__primary-copy h2 { margin: 0; color: var(--text-primary); font-size: 18px; }
.lobby__primary-copy p { margin: 5px 0 0; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.lobby__primary-actions, .lobby__primary-side { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.lobby__primary-action { min-height: 42px; padding: 9px 18px; border: 1px solid var(--hero-border); border-radius: 6px; background: var(--hero-grad); color: var(--on-accent); font: inherit; font-size: 14px; font-weight: 650; white-space: nowrap; cursor: pointer; transition: background var(--duration-fast) var(--ease), border-color var(--duration-fast) var(--ease); }
.lobby__primary-action--room { border-color: var(--border-strong); background: var(--surface-chamber); color: var(--text-primary); }
.lobby__primary-action:hover:not(:disabled) { border-color: var(--accent-strong); filter: brightness(1.06); }
.lobby__columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(286px, 330px); gap: 20px 24px; align-items: stretch; min-width: 0; }
.lobby__directory { display: flex; flex-direction: column; min-width: 0; min-height: 480px; border: 1px solid var(--border-subtle); border-radius: 11px; background: var(--panel); overflow: hidden; }
.lobby__filterbar { display: flex; flex: 0 0 auto; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 18px; border-bottom: 1px solid var(--border-subtle); }
.lobby__search, .lobby__input { min-width: 0; min-height: 40px; padding: 8px 11px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface-deck); color: var(--text-primary); font: inherit; font-size: 13px; }
.lobby__search { order: 2; flex: 0 1 290px; width: 100%; }
.lobby__search::placeholder, .lobby__input::placeholder { color: var(--text-tertiary); opacity: 1; }
.lobby__seg { display: flex; flex-wrap: wrap; align-items: stretch; gap: 3px; min-width: 0; }
.lobby__seg-btn { min-height: 38px; padding: 8px 10px; border: 0; border-radius: 5px; background: transparent; color: var(--text-secondary); font: inherit; font-size: 13px; cursor: pointer; }
.lobby__seg-btn:hover { background: var(--role-self-soft); color: var(--text-primary); }
.lobby__seg-btn.is-active { background: var(--role-action-soft); color: var(--text-primary); box-shadow: inset 0 -2px var(--role-action); }
.lobby__panel { display: flex; flex-direction: column; min-width: 0; min-height: 0; padding: 17px 20px; border: 1px solid var(--border-subtle); border-radius: 11px; background: var(--panel); }
.lobby__panel-head { display: flex; flex: 0 0 auto; flex-wrap: wrap; align-items: center; gap: 8px 12px; min-height: 32px; margin-bottom: 10px; }
.lobby__panel-title { flex: 1; min-width: 0; margin: 0; color: var(--text-primary); font-size: 17px; font-weight: 650; }
.lobby__panel-meta { color: var(--text-secondary); font-size: 12px; font-variant-numeric: tabular-nums; }
.lobby__fold { min-height: 32px; padding: 4px 7px; border: 0; border-radius: 5px; background: transparent; color: var(--text-secondary); font: inherit; font-size: 12px; cursor: pointer; }
.lobby__fold:hover { color: var(--text-primary); background: var(--role-self-soft); }
.lobby__panel--rooms { flex: 1 0 auto; min-height: 0; padding: 12px 0 0; border: 0; border-radius: 0; background: transparent; }
.lobby__panel--rooms > .lobby__panel-head { padding: 0 20px; margin-bottom: 6px; }
.lobby__directory-head, .lobby__room { display: grid; grid-template-columns: minmax(0, 1fr) 72px 64px 108px; align-items: center; gap: 14px; }
.lobby__directory-head { flex: 0 0 auto; min-height: 32px; padding: 6px 20px; color: var(--text-tertiary); font-size: 12px; border-bottom: 1px solid var(--border-subtle); }
.lobby__directory-head > :last-child { text-align: center; }
.lobby__room-results { flex: 1 1 auto; min-height: 100px; max-height: 280px; overflow-y: auto; overscroll-behavior: contain; }
.lobby__room-results :deep(.state-surface__empty), .lobby__room-results :deep(.state-surface__loading), .lobby__room-results :deep(.state-surface__error) { padding: 18px 20px; }
.lobby__list { margin: 0; padding: 0; list-style: none; }
.lobby__room { padding: 14px 20px; min-height: 78px; border-bottom: 1px solid var(--border-subtle); transition: background var(--duration-fast) var(--ease); }
.lobby__room:last-child { border-bottom: 0; }
.lobby__room:hover { background: var(--role-self-soft); }
.lobby__room.is-own { background: color-mix(in srgb, var(--role-self-soft) 60%, transparent); }
.lobby__room-main { display: flex; align-items: center; gap: 13px; min-width: 0; }
.lobby__room-symbol { display: grid; flex: 0 0 42px; place-items: center; height: 42px; border-radius: 8px; background: var(--role-self-soft); color: var(--text-secondary); font-size: 22px; }
.lobby__room-info { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.lobby__room-name, .lobby__match-name { color: var(--text-primary); font-size: 14px; font-weight: 650; overflow-wrap: anywhere; }
.lobby__room-meta { display: flex; flex-wrap: wrap; gap: 3px 10px; color: var(--text-secondary); font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.lobby__room-seats { color: var(--text-primary); font-size: 14px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.lobby__room-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
.lobby__room-actions .button { width: 100%; min-height: 36px; padding: 6px 8px; background: var(--surface-raised); color: var(--text-primary); border-color: var(--border-strong); }
.lobby__room-actions .button--danger { color: var(--role-enemy); background: var(--role-enemy-soft); border-color: color-mix(in srgb, var(--role-enemy) 36%, transparent); }
.lobby__tag { display: inline-flex; align-items: center; align-self: center; justify-self: start; width: fit-content; max-width: 100%; padding: 2px 6px; border: 1px solid var(--border-strong); border-radius: 4px; color: var(--text-secondary); font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
.lobby__tag--muted { border-color: var(--border-subtle); color: var(--text-secondary); }
.lobby__create { display: flex; flex: 0 0 auto; flex-wrap: wrap; align-items: center; gap: 7px 12px; padding: 12px 20px; border-top: 1px solid var(--border-subtle); }
.lobby__create .lobby__input { flex: 1 1 180px; min-height: 36px; }
.lobby__create-hint { flex-basis: 100%; margin: 0; color: var(--text-tertiary); font-size: 12px; line-height: 1.5; }
.lobby__checkbox { display: flex; align-items: center; gap: 7px; min-height: 36px; color: var(--text-secondary); font-size: 13px; cursor: pointer; }
.lobby__checkbox input { width: 16px; height: 16px; min-height: 0; margin: 0; accent-color: var(--role-action); }
.lobby__own { display: flex; flex: 0 0 auto; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin: 4px 20px 10px; padding: 12px; border: 1px solid color-mix(in srgb, var(--role-self) 34%, transparent); border-radius: 7px; background: var(--role-self-soft); }
.lobby__own-main { display: flex; flex: 1 1 240px; flex-wrap: wrap; gap: 4px 9px; min-width: 0; color: var(--text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.lobby__own-name { color: var(--text-primary); }
.lobby__own code, .lobby__invite code { padding: 1px 5px; border: 1px solid var(--border-subtle); border-radius: 4px; color: var(--text-primary); }
.lobby__own-confirm { flex-basis: 100%; margin: 0; color: var(--role-warning); font-size: 13px; line-height: 1.6; }
.lobby__own-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.lobby__own-hint { flex-basis: 100%; margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.lobby__panel--matches { flex: 0 0 auto; max-height: 180px; padding: 13px 20px; border: 0; border-top: 1px solid var(--border-subtle); border-radius: 0; background: color-mix(in srgb, var(--surface-deck) 75%, transparent); }
.lobby__panel--matches .lobby__panel-head { margin-bottom: 4px; }
.lobby__panel-body { display: flex; flex: 1 1 0; flex-direction: column; min-width: 0; min-height: 0; }
.lobby__panel-body > .lobby__list { min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
.lobby__match { display: flex; align-items: center; gap: 16px; min-width: 0; padding: 9px 0; border-bottom: 1px solid var(--border-subtle); }
.lobby__match:last-child { border-bottom: 0; }
.lobby__match-main { display: flex; flex: 1; flex-wrap: wrap; align-items: center; gap: 4px 10px; min-width: 0; }
.lobby__muted { color: var(--text-secondary); font-size: 12px; line-height: 1.5; }
.lobby__social { display: flex; flex-direction: column; min-width: 0; min-height: 0; gap: 16px; }
.lobby__panel--players { flex: 1 1 0; min-height: 196px; max-height: 340px; }
.lobby__player, .lobby__friend { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 11px 0; border-bottom: 1px solid var(--border-subtle); }
.lobby__player:last-child, .lobby__friend:last-child { border-bottom: 0; }
.lobby__player.is-me .lobby__player-name { color: var(--role-self); }
.lobby__avatar { display: grid; flex: 0 0 34px; place-items: center; height: 34px; border: 1px solid color-mix(in srgb, var(--role-self) 55%, transparent); border-radius: 50%; background-color: var(--role-self-soft); background-position: center; background-size: cover; color: var(--role-self); font-size: 14px; font-weight: 650; }
.lobby__avatar--small { flex-basis: 30px; height: 30px; font-size: 13px; }
.lobby__player-main, .lobby__friend-main { display: flex; flex: 1; flex-direction: column; min-width: 0; gap: 4px; }
.lobby__player-line, .lobby__player-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; min-width: 0; }
.lobby__player-name { color: var(--text-primary); font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.lobby__player-name--rainbow { background: linear-gradient(90deg, var(--role-self), var(--gold-strong), var(--role-enemy)); background-clip: text; color: transparent; }
.lobby__player-meta { color: var(--text-secondary); font-size: 12px; }
.lobby__player-title { color: var(--gold-strong); font-size: 12px; overflow-wrap: anywhere; }
.lobby__status { margin-left: auto; color: var(--text-secondary); }
.lobby__status[data-status='idle'] { color: var(--role-success); }
.lobby__status[data-status='matching'] { color: var(--gold-strong); }
.lobby__status[data-status='in_room'] { color: var(--role-action); }
.lobby__status[data-status='in_game'] { color: var(--role-enemy); }
.lobby__panel--chat { flex: 1 1 0; min-height: 240px; }
.lobby__chat { display: flex; flex: 1 1 0; flex-direction: column; gap: 12px; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding-right: 4px; }
.lobby__chat-item { display: grid; flex: 0 0 auto; grid-template-columns: minmax(0, 1fr) auto; gap: 3px 9px; min-width: 0; font-size: 13px; }
.lobby__chat-time { grid-column: 2; grid-row: 1; color: var(--text-tertiary); font-size: 11px; font-variant-numeric: tabular-nums; }
.lobby__chat-name { grid-column: 1; grid-row: 1; min-width: 0; color: var(--text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.lobby__chat-item.is-me .lobby__chat-name { color: var(--role-self); }
.lobby__chat-text { grid-column: 1 / -1; color: var(--text-primary); line-height: 1.65; overflow-wrap: anywhere; }
.lobby__chat-row { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; min-width: 0; margin-top: 14px; }
.lobby__chat-row .lobby__input { flex: 1 1 0; width: 0; }
.lobby__panel--friends { display: block; padding: 12px 20px; }
.lobby__panel--friends > summary { margin: 0; cursor: pointer; list-style: none; }
.lobby__panel--friends > summary::-webkit-details-marker { display: none; }
.lobby__panel--friends > summary::after { content: '展开'; color: var(--role-self); font-size: 12px; }
.lobby__panel--friends[open] > summary::after { content: '收起'; }
.lobby__panel--friends[open] > summary { margin-bottom: 12px; }
.lobby__panel--friends .lobby__list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 28px; max-height: 240px; overflow-y: auto; }
.lobby__friend-main b { color: var(--text-primary); font-size: 14px; overflow-wrap: anywhere; }
.lobby__empty { margin: 0; padding: 14px 0; color: var(--text-secondary); font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.lobby__empty--error { color: var(--role-enemy); }
.lobby__empty-cta { align-self: flex-start; margin-top: 8px; }
.lobby__invite { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 14px 18px; border: 1px solid color-mix(in srgb, var(--role-self) 40%, transparent); border-radius: 9px; background: var(--role-self-soft); }
.lobby__invite-text { flex: 1 1 260px; min-width: 0; color: var(--text-primary); font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; }
.lobby__footer { display: flex; justify-content: center; }
.lobby .button { font-size: 13px; }
.lobby .button--small { flex-shrink: 0; min-height: 34px; padding: 6px 10px; }
.lobby .button--ghost { background: transparent; color: var(--text-secondary); border-color: var(--border-strong); }
.lobby .button--ghost:hover { background: var(--role-self-soft); color: var(--text-primary); }
.lobby .button--danger { color: var(--role-enemy); background: var(--role-enemy-soft); border-color: color-mix(in srgb, var(--role-enemy) 38%, transparent); }
.lobby button:disabled { opacity: 0.64; cursor: not-allowed; }
@media (min-width: 980px) and (max-height: 920px) {
  .lobby { gap: 12px; padding-top: 18px; padding-bottom: 20px; }
  .lobby__primary { padding: 14px 18px; }
  .lobby__create-hint { display: none; }
}
@media (max-width: 1179px) {
  .lobby__head { align-items: flex-start; flex-wrap: wrap; }
  .lobby__topbar { justify-content: flex-start; }
  .lobby__columns { grid-template-columns: minmax(0, 1fr) 286px; gap: 18px; }
  .lobby__filterbar { padding: 12px; }
  .lobby__search { flex-basis: 100%; }
  .lobby__directory-head, .lobby__room { grid-template-columns: minmax(0, 1fr) 54px 52px 88px; gap: 9px; padding-left: 14px; padding-right: 14px; }
  .lobby__room-symbol { display: none; }
}
@media (max-width: 979px) {
  .lobby { padding: 20px 18px 24px; }
  .lobby__columns { grid-template-columns: minmax(0, 1fr); }
  .lobby__directory { height: auto; min-height: 420px; overflow: visible; }
  .lobby__room-results { flex: 1 1 auto; max-height: 360px; min-height: 100px; }
  .lobby__panel--rooms { flex: 1 1 auto; min-height: 0; }
  .lobby__panel--matches { max-height: 240px; }
  .lobby__panel--matches .lobby__panel-body { flex: 0 1 auto; }
  .lobby__social { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; }
  .lobby__panel--players, .lobby__panel--chat { height: 320px; min-height: 0; max-height: none; }
  .lobby__panel--players .lobby__panel-body { min-height: 0; }
  .lobby__primary-actions { flex: 1 1 100%; }
  .lobby__primary-action { flex: 1; }
  .lobby__primary-side { flex: 1; }
  .lobby__primary-side .button { flex: 1; }
}
@media (max-width: 599px) {
  .lobby { gap: 14px; padding: 18px 12px 24px; }
  .lobby__title { font-size: 26px; }
  .lobby__head { gap: 14px; }
  .lobby__topbar { gap: 8px 12px; }
  .lobby__stat { font-size: 12px; }
  .lobby__primary { padding: 16px; gap: 16px; }
  .lobby__primary-copy { flex-basis: 100%; gap: 12px; }
  .lobby__primary-copy h2 { font-size: 17px; }
  .lobby__primary-mark { flex-basis: 36px; height: 36px; font-size: 22px; }
  .lobby__primary-actions { gap: 8px; }
  .lobby__primary-side { flex-basis: 100%; }
  .lobby__primary-action { min-height: 44px; padding: 10px 12px; }
  .lobby__filterbar { gap: 10px; }
  .lobby__seg { justify-content: space-between; flex: 1; }
  .lobby__seg-btn { min-height: 44px; padding: 8px; }
  .lobby__search { min-height: 44px; }
  .lobby__directory-head { display: none; }
  .lobby__room { grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px 12px; padding: 14px; }
  .lobby__room-main { grid-column: 1 / -1; }
  .lobby__room-symbol { display: grid; flex-basis: 34px; height: 34px; font-size: 18px; }
  .lobby__room-mode { grid-column: 1; }
  .lobby__room-seats { grid-column: 2; font-size: 13px; }
  .lobby__room-actions { grid-column: 3; }
  .lobby__room-actions .button { min-height: 44px; }
  .lobby__room-meta { gap: 3px 8px; font-size: 12px; }
  .lobby__panel--rooms > .lobby__panel-head { padding: 0 14px; }
  .lobby__create { padding: 12px 14px; }
  .lobby__create .lobby__input { min-height: 44px; }
  .lobby__checkbox { min-height: 44px; }
  .lobby__own { margin-left: 14px; margin-right: 14px; }
  .lobby__social { grid-template-columns: minmax(0, 1fr); gap: 14px; }
  .lobby__panel { padding: 16px; }
  .lobby__panel--rooms { padding: 12px 0 0; }
  .lobby__panel--matches { padding: 12px 14px; }
  .lobby__panel--players { height: 300px; }
  .lobby__panel--chat { height: 330px; }
  .lobby__panel-title { font-size: 16px; }
  .lobby__panel--friends .lobby__list { grid-template-columns: minmax(0, 1fr); }
  .lobby .button, .lobby__fold, .lobby__changelog-close, .lobby__dismiss { min-height: 44px; }
}
</style>
