import { computed, inject, provide, ref, type InjectionKey } from 'vue'
import { useRouter } from 'vue-router'
import { getLobbySocket } from '../../realtime/lobby'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'
import { lobbyPlayerName, useLobbyStore, type LobbyFriend, type LobbyRoom } from '../../stores/lobby'
import { useRoomDraftStore } from '../../stores/roomDraft'
import { mutationSelectionError } from '../../stores/mutations'
import { useCardBansStore } from '../../stores/cardBans'
import { inviteDisabledReason, roomJoinable } from './view'
import { buildInviteUrl, inviteFeedback, inviteManualPrompt } from './inviteLink'

function createActions() {
  const router = useRouter()
  const lobby = useLobbyStore()
  const auth = useAuthStore()
  const ui = useUiStore()
  const draft = useRoomDraftStore()
  const bans = useCardBansStore()
  const createPending = ref(false)
  const closePending = ref(false)
  const friendsBusy = ref(false)
  const invitingUsername = ref('')
  const acceptingInvite = ref(false)
  const inviteCopyText = ref('')
  const creationError = computed(() => mutationSelectionError(draft.mutationIds, lobby.snapshot?.weeklyMutations ?? null)
    || (draft.banEnabled && (!Number.isInteger(draft.banQuota) || draft.banQuota < 1 || draft.banQuota > 10) ? '每人 Ban 名额须为 1～10。' : ''))
  const ownRoomName = computed(() => lobby.ownRoomName || `${lobby.ownRoom?.hostName || auth.displayName}的房间`)

  function fail(text: string): void { lobby.setError(text); ui.notifyError('lobby-action', text) }
  function notice(text: string): void { lobby.clearError(); lobby.setNotice(text) }
  function socket() {
    const current = getLobbySocket()
    if (!current?.socket.connected) { fail('连接尚未就绪，请稍后重试。'); return null }
    return current
  }
  async function refresh(): Promise<void> {
    const current = socket()
    if (!current) return
    try { await current.emitEvent('lobby_refresh', {}) }
    catch (e) { fail(e instanceof Error ? e.message : '刷新失败，请重试。') }
  }
  async function createRoom(): Promise<void> {
    if (createPending.value) return
    if (lobby.ownRoomId) { notice('你已有等待中的房间，可返回房间或先解散。'); return }
    if (creationError.value) { fail(creationError.value); return }
    const current = socket()
    if (!current) return
    createPending.value = true
    try {
      const ack = await current.emitEvent('lobby_create_room', {
        name: draft.name.trim(), public: draft.isPublic, player_name: lobbyPlayerName(),
        mutation_ids: [...draft.mutationIds], ban_enabled: draft.banEnabled,
        ban_quota: draft.banEnabled ? draft.banQuota : 1,
      })
      const result = ack as unknown as Record<string, unknown>
      if (ack.status !== 'success' || !result.room_id) { fail(ack.message || '创建失败，请重试。'); return }
      lobby.recordOwnRoom(result.own_room ?? {
        room_id: result.room_id, name: result.name ?? draft.name, public: result.public ?? draft.isPublic,
        invite_token: result.invite_token,
        host_name: auth.displayName, ban_enabled: draft.banEnabled, ban_quota: draft.banQuota,
        mutation_ids: [...draft.mutationIds], mutation_entries: lobby.snapshot?.weeklyMutations?.catalog.filter(e => draft.mutationIds.includes(e.id)) ?? [],
      })
      draft.reset()
      notice('房间已创建，等待对手加入。')
      await router.push({ name: 'lobby-room' })
    } catch (e) { fail(e instanceof Error ? e.message : '创建失败，请重试。') }
    finally { createPending.value = false }
  }
  async function joinRoom(room: Pick<LobbyRoom, 'roomId' | 'players' | 'capacity'>): Promise<void> {
    if (!roomJoinable(room as LobbyRoom)) return
    if (room.roomId === lobby.ownRoomId) { await router.push({ name: 'lobby-room' }); return }
    await joinById(room.roomId)
  }
  async function joinById(roomId: string, inviteToken = ''): Promise<boolean> {
    const current = socket()
    if (!current || !roomId.trim()) return false
    try {
      const ack = await current.emitEvent('join_room', { room_id: roomId.trim(), player_name: lobbyPlayerName(),
        ...(inviteToken ? { invite_token: inviteToken } : {}) })
      if (ack.status !== 'success') { fail(ack.message || '加入失败，请重试。'); return false }
      notice('已加入房间，等待对局开始。')
      return true
    } catch (e) { fail(e instanceof Error ? e.message : '加入失败，请重试。'); return false }
  }
  async function closeRoom(): Promise<void> {
    if (closePending.value || !lobby.ownRoomId) return
    const current = socket()
    if (!current) return
    closePending.value = true
    try {
      const ack = await current.emitEvent('close_room', { room_id: lobby.ownRoomId })
      if (ack.status !== 'success') { fail(ack.message || '解散失败，请重试。'); return }
      lobby.clearOwnRoom()
      notice('房间已解散。')
      await router.push({ name: 'lobby' })
    } catch (e) { fail(e instanceof Error ? e.message : '解散失败，请重试。') }
    finally { closePending.value = false }
  }
  function copyInviteLink(): void {
    if (!lobby.ownRoomId) return
    const token = lobby.ownRoom?.inviteToken || ''
    if (!lobby.ownRoomPublic && !token) { fail('邀请链接暂未就绪，请刷新房间后再复制。'); return }
    const url = buildInviteUrl(location.origin, '/lobby', lobby.ownRoomId, token)
    const fallback = () => { window.prompt(inviteManualPrompt(url), url); inviteCopyText.value = inviteFeedback(false) }
    if (!navigator.clipboard?.writeText) { fallback(); return }
    void navigator.clipboard.writeText(url).then(() => { inviteCopyText.value = inviteFeedback(true) }).catch(fallback)
  }
  async function loadFriends(): Promise<void> {
    if (friendsBusy.value) return
    if (auth.isGuest) { lobby.recordFriendsGuest(); return }
    friendsBusy.value = true
    try {
      const response = await fetch('/api/friends', { credentials: 'same-origin', headers: { accept: 'application/json' } })
      if (response.status === 401) { lobby.recordFriendsGuest(); return }
      const body = await response.json()
      if (!response.ok) { lobby.recordFriendsError(typeof body.error === 'string' ? body.error : '好友读取失败，请重试。'); return }
      lobby.recordFriends(body)
    } catch (e) { lobby.recordFriendsError(e instanceof Error ? e.message : '好友读取失败，请重试。') }
    finally { friendsBusy.value = false }
  }
  async function inviteFriend(friend: LobbyFriend, roomId = lobby.ownRoomId): Promise<void> {
    if (invitingUsername.value) return
    const reason = inviteDisabledReason(friend)
    if (reason) { fail(reason); return }
    if (!socket()) return
    invitingUsername.value = friend.username
    try {
      const response = await fetch('/api/friends/invite', {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', accept: 'application/json' },
        body: JSON.stringify({ username: friend.username, ...(roomId ? { room_id: roomId } : {}) }),
      })
      const body = await response.json()
      if (!response.ok || body.status !== 'ok' || !body.room_id) { fail(typeof body.error === 'string' ? body.error : '邀请失败，请重试。'); return }
      if (!roomId) {
        if (!await joinById(String(body.room_id), String(body.invite_token || ''))) return
        lobby.recordOwnRoom({ room_id: String(body.room_id), name: '好友邀战', public: body.public,
          invite_token: body.invite_token })
        await refresh()
        await router.push({ name: 'lobby-room' })
      }
      notice(`已邀请 ${friend.username} 进入房间。`)
    } catch (e) { fail(e instanceof Error ? e.message : '邀请失败，请重试。') }
    finally { invitingUsername.value = '' }
  }
  async function acceptInvite(): Promise<void> {
    if (!lobby.activeInvite || acceptingInvite.value) return
    acceptingInvite.value = true
    try { if (await joinById(lobby.activeInvite.roomId, lobby.activeInvite.inviteToken)) lobby.clearInvite() }
    finally { acceptingInvite.value = false }
  }
  async function startMatch(mode: 'casual' | 'ranked'): Promise<void> {
    if (lobby.ownRoomId) { notice('你有等待中的房间，请先返回或解散。'); return }
    if (mode === 'ranked' && auth.isGuest) { auth.open('login', '排位对战需要先登录。'); return }
    if (mode === 'ranked' && bans.selectionError) { fail(bans.selectionError); return }
    const current = socket()
    if (!current) return
    try {
      const ack = await current.emitEvent('find_match', { player_name: auth.displayName, mode, ...(mode === 'ranked' ? { ban_preselection: [...bans.preselection] } : {}) })
      if (ack.status !== 'success') fail(ack.message || '匹配失败，请重试。')
    } catch (e) { fail(e instanceof Error ? e.message : '匹配失败，请重试。') }
  }
  async function cancelMatch(): Promise<void> {
    const current = socket()
    if (!current) return
    try { await current.emitEvent('cancel_match', {}) }
    catch (e) { fail(e instanceof Error ? e.message : '取消失败，请重试。') }
  }
  return { createPending, closePending, friendsBusy, invitingUsername, acceptingInvite, inviteCopyText,
    creationError, ownRoomName, fail, notice, refresh, createRoom, joinRoom, joinById, closeRoom,
    copyInviteLink, loadFriends, inviteFriend, acceptInvite, startMatch, cancelMatch }
}

const key: InjectionKey<ReturnType<typeof createActions>> = Symbol('大厅动作')
export function provideLobbyActions() { const actions = createActions(); provide(key, actions); return actions }
export function useLobbyActions() {
  const actions = inject(key)
  if (!actions) throw new Error('大厅页面缺少共享布局')
  return actions
}
