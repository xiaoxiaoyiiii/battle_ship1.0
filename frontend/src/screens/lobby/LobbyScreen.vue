<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useLobbyStore, type LobbyMatch } from '../../stores/lobby'
import { useHomeStore } from '../../stores/home'
import { useAuthStore } from '../../stores/auth'
import { getLobbySocket } from '../../realtime/lobby'
import { useLobbyActions } from './useLobbyActions'
import { initial, roomModeText, roomSeatsText, matchNamesText, matchSpectateText, statusText, levelText, rankText, timeText, inviteDisabledReason } from './view'
import AppOverlay from '../../components/AppOverlay.vue'
import MutationList from '../../components/MutationList.vue'
import BanPreselection from '../../components/BanPreselection.vue'
import StateSurface from '../../components/StateSurface.vue'

const lobby = useLobbyStore()
const home = useHomeStore()
const auth = useAuthStore()
const router = useRouter()
const actions = useLobbyActions()
const chatDraft = ref('')
const chatEl = ref<HTMLElement | null>(null)
const friendsOpen = ref(false)
const weeklyOpen = ref(false)
const changelogClosed = ref(false)
const media = window.matchMedia('(max-width: 540px)')
const narrow = ref(media.matches)
const updateNarrow = () => { narrow.value = media.matches }
const rooms = computed(() => lobby.rooms.slice(0, narrow.value ? 2 : 3))
const matches = computed(() => lobby.matches.slice(0, 2))
const weekly = computed(() => lobby.snapshot?.weeklyMutations ?? null)
const changelog = computed(() => home.changelog[0]?.items?.join('；') || '')
const roomsState = computed(() => lobby.error ? 'error' : !lobby.hasSnapshot ? 'loading' : rooms.value.length ? 'ready' : 'empty')
function count(value: number): string { return lobby.hasSnapshot ? String(value) : '—' }
function spectate(match: LobbyMatch): void { void router.push({ name: 'spectate', query: { room_id: match.roomId } }) }
async function sendChat(): Promise<void> {
  if (!chatDraft.value.trim()) return
  const socket = getLobbySocket()
  if (!socket?.socket.connected) { actions.fail('连接尚未就绪，请稍后重试。'); return }
  try {
    const ack = await socket.emitEvent('lobby_chat_send', { message: chatDraft.value.trim() })
    if (ack.status !== 'success') { actions.fail(ack.message || '发送失败，请重试。'); return }
    chatDraft.value = ''
  } catch (e) { actions.fail(e instanceof Error ? e.message : '发送失败，请重试。') }
}
function closeChangelog(): void {
  changelogClosed.value = true
  try { localStorage.setItem('battleship.lobby.changelogClosed', '1') } catch { /* 本次关闭仍生效。 */ }
}
watch(() => lobby.chat.length, async () => { await nextTick(); if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight })
onMounted(() => {
  media.addEventListener('change', updateNarrow)
  if (!home.changelogLoaded) void home.loadChangelog(1)
  try { changelogClosed.value = localStorage.getItem('battleship.lobby.changelogClosed') === '1' } catch { /* 继续显示。 */ }
})
onBeforeUnmount(() => media.removeEventListener('change', updateNarrow))
</script>
<template>
  <section class="lp-page" data-screen="lobby" data-testid="screen-lobby" aria-labelledby="lobby-title">
    <header class="lp-pagehead"><div><h1 id="lobby-title" data-testid="lobby-heading">游戏大厅</h1><p>找一位对手，或看看其他舰长的较量。</p></div><button class="button button--ghost" data-testid="lobby-refresh" @click="actions.refresh()">刷新</button></header>
    <p v-if="!changelogClosed && changelog" class="lp-announcement" data-testid="lobby-changelog"><span>公告 · {{ changelog }}</span><button class="lp-link" data-testid="lobby-changelog-close" aria-label="关闭公告" @click="closeChangelog">关闭</button></p>
    <section v-if="lobby.ownRoomId" class="lp-own-banner" data-testid="lobby-own-room"><div><span class="lp-tag lp-tag--cyan">我的房间</span><b>{{ actions.ownRoomName.value }}</b><small>房号 <span data-testid="lobby-own-room-id">{{ lobby.ownRoomId }}</span> · {{ lobby.ownRoomPublic ? '公开' : '私密' }} · 等待对手</small></div><router-link class="button lp-primary" :to="{ name: 'lobby-room' }" data-testid="lobby-own-room-return">返回房间</router-link></section>
    <section class="lp-launch" aria-label="大厅主行动"><div><h2>下一场较量，从这里开始</h2><p>快速匹配，或者开一间属于你的房间。</p></div><div class="lp-launch-actions"><button class="button lp-primary" data-testid="lobby-match-casual" :disabled="!!lobby.queueMode || !!lobby.ownRoomId" @click="actions.startMatch('casual')">快速匹配</button><router-link class="button" data-testid="lobby-create-room" :to="{ name: lobby.ownRoomId ? 'lobby-room' : 'lobby-create' }">{{ lobby.ownRoomId ? '我的房间' : '创建房间' }}</router-link><button class="button button--ghost" data-testid="lobby-match-ranked" :disabled="!!lobby.queueMode || !!lobby.ownRoomId" @click="actions.startMatch('ranked')">排位匹配</button><button v-if="lobby.queueMode" class="button button--danger" data-testid="lobby-match-cancel" @click="actions.cancelMatch()">取消匹配</button></div></section>
    <p v-if="lobby.queueMode" class="lp-feedback" data-testid="lobby-queue-state" role="status">{{ lobby.queueMode === 'ranked' ? '排位' : '休闲' }}匹配中，正在寻找对手…</p>
    <div class="lp-overview-layout"><div class="lp-stack">
      <section class="lp-panel"><header class="lp-panelhead"><h2>房间列表 <small>{{ count(lobby.rooms.length) }} 间等待中</small></h2><router-link class="lp-link" :to="{ name: 'lobby-rooms' }" data-testid="lobby-all-rooms">查看所有</router-link></header><StateSurface class="lp-preview-surface" :state="roomsState" loading-text="正在读取房间…" @retry="actions.refresh()"><ul class="lp-preview-list" data-testid="lobby-rooms"><li v-for="room in rooms" :key="room.roomId" :data-testid="'lobby-room-' + room.roomId"><span class="lp-avatar lp-avatar--small">{{ initial(room.host) }}</span><div class="lp-preview-info"><h3>{{ room.name }}</h3><p>{{ room.host }} · {{ roomModeText(room) }} · {{ room.public ? '公开' : '私密' }}</p></div><span class="lp-seats">{{ roomSeatsText(room) }}</span><button class="button button--ghost" :data-testid="'lobby-room-join-' + room.roomId" :disabled="room.players >= room.capacity" @click="actions.joinRoom(room)">{{ room.players < room.capacity ? '加入房间' : '房间已满' }}</button></li></ul><template #empty><div class="lp-empty" data-testid="lobby-rooms-empty"><p>暂无等待中的公开房间，你可以先开一间。</p><router-link class="button" :to="{ name: 'lobby-create' }" data-testid="lobby-rooms-empty-cta">创建房间</router-link></div></template></StateSurface><p v-if="lobby.rooms.length > rooms.length" class="lp-preview-more">更多房间请进入完整列表查看</p></section>
      <section class="lp-panel"><header class="lp-panelhead"><h2>进行中的对局 <small>{{ count(lobby.matches.length) }} 局</small></h2><router-link class="lp-link" :to="{ name: 'lobby-matches' }" data-testid="lobby-all-matches">查看所有</router-link></header><ul class="lp-preview-list lp-preview-list--matches" data-testid="lobby-matches"><li v-for="match in matches" :key="match.roomId" :data-testid="'lobby-match-' + match.roomId"><div class="lp-preview-info"><h3>{{ matchNamesText(match) }}</h3><p>{{ match.ranked ? '排位' : '休闲' }} · 第 {{ match.round }} 回合 · {{ matchSpectateText(match) }}</p></div><button class="button button--ghost" :data-testid="'lobby-match-spectate-' + match.roomId" @click="spectate(match)">观战</button></li></ul><p v-if="!matches.length" class="lp-empty" data-testid="lobby-matches-empty">{{ lobby.hasSnapshot ? '暂无可观战的对局，稍后再来看看。' : '正在读取对局…' }}</p></section>
      <div class="lp-stats"><span>在线 <b data-testid="lobby-online-count">{{ count(lobby.onlineCount) }}</b></span><span>大厅 <b data-testid="lobby-lobby-count">{{ count(lobby.lobbyCount) }}</b></span><span>休闲队列 <b data-testid="lobby-queue-casual">{{ count(lobby.queueCasual) }}</b></span><span>排位队列 <b data-testid="lobby-queue-ranked">{{ count(lobby.queueRanked) }}</b></span></div>
    </div><aside class="lp-stack lp-social"><section class="lp-panel"><header class="lp-panelhead"><h2>在线玩家 <small>{{ count(lobby.players.length) }} 人</small></h2></header><ul class="lp-player-list" data-testid="lobby-players"><li v-for="player in lobby.players" :key="player.key" :data-testid="'lobby-player-' + player.key"><span class="lp-avatar lp-avatar--small" :style="player.avatar ? { backgroundImage: `url(${JSON.stringify(player.avatar)})`, backgroundSize: 'cover' } : undefined">{{ player.avatar ? '' : initial(player.name) }}</span><div><b :class="{ 'lp-player-rainbow': player.nameStyle === 'rainbow' }">{{ player.name }}</b><span v-if="player.guest" class="lp-tag">游客</span><span v-if="player.title" class="lp-player-title">{{ player.title }}</span><small>{{ levelText(player) }} {{ rankText(player) }} · {{ statusText(player) }} <span v-if="player.key === lobby.myKey" data-testid="lobby-player-me"> · 你</span></small></div></li></ul><p v-if="!lobby.players.length" class="lp-empty" data-testid="lobby-players-empty">{{ lobby.hasSnapshot ? '暂时没有其他玩家。' : '正在读取玩家…' }}</p></section>
      <section class="lp-panel"><header class="lp-panelhead"><h2>大厅公屏</h2><span class="lp-tag lp-tag--cyan">实时</span></header><div ref="chatEl" class="lp-chat" data-testid="lobby-chat"><p v-if="!lobby.chat.length" class="lp-empty" data-testid="lobby-chat-empty">还没有人说话，打个招呼吧。</p><p v-for="(line,index) in lobby.chat" :key="line.seq || index" :data-testid="'lobby-chat-message-' + line.seq"><small>{{ line.name }} · {{ timeText(line.ts) }}</small><span>{{ line.message }}</span></p></div><form class="lp-chat-form" @submit.prevent="sendChat"><input v-model="chatDraft" class="lp-input" data-testid="lobby-chat-input" maxlength="120" aria-label="大厅公屏消息" placeholder="说点什么…"><button class="button" type="submit" data-testid="lobby-chat-send" :disabled="!lobby.connected || !chatDraft.trim()">发送</button></form></section></aside></div>
    <div class="lp-secondary-tools"><BanPreselection /><section v-if="weekly" class="lp-weekly" data-testid="lobby-weekly-mutations"><span><b>本周突变 · {{ weekly.name }}</b><small>{{ weekly.entries.map(e => e.name).join('、') }}</small></span><button class="lp-link" data-testid="lobby-weekly-details" @click="weeklyOpen = true">查看词条</button></section></div>
    <section class="lp-panel lp-friends-section"><header class="lp-panelhead"><h2>好友邀战</h2><button class="lp-link" data-testid="lobby-friends-refresh" :disabled="actions.friendsBusy.value" @click="actions.loadFriends()">刷新</button><button class="lp-link" data-testid="lobby-fold-friends" :aria-expanded="friendsOpen" @click="friendsOpen = !friendsOpen">{{ friendsOpen ? '收起' : '展开' }}</button></header><div v-if="friendsOpen" class="lp-panelbody"><p v-if="lobby.friendsGuest || auth.isGuest" class="lp-empty" data-testid="lobby-friends-guest">登录后可以邀请好友。<button class="lp-link" @click="auth.open('login', '登录后邀请好友。')">登录</button></p><template v-else><p v-if="lobby.friendsError" class="lp-conflict">{{ lobby.friendsError }}</p><ul class="lp-friend-list" data-testid="lobby-friends"><li v-for="friend in lobby.friends" :key="friend.userId" :data-testid="'lobby-friend-' + friend.userId"><span class="lp-avatar lp-avatar--small">{{ initial(friend.username) }}</span><span class="lp-friend-name"><b>{{ friend.username }}</b><small>{{ !friend.online ? '离线' : friend.inGame ? '对局中' : '在线' }}</small></span><button class="button" :disabled="!!inviteDisabledReason(friend) || !!actions.invitingUsername.value" :data-testid="'lobby-friend-invite-' + friend.userId" @click="actions.inviteFriend(friend)">邀请</button></li></ul><p v-if="!lobby.friends.length && !actions.friendsBusy.value" class="lp-empty" data-testid="lobby-friends-empty">还没有可邀请的好友。</p></template></div></section>
    <AppOverlay v-if="weeklyOpen && weekly" id="lobby-weekly-preview" labelledby="lobby-weekly-title" @close="weeklyOpen = false"><section class="lp-dialog-small"><h2 id="lobby-weekly-title">本周突变 · {{ weekly.name }}</h2><p>休闲每局随机遇见词条，自定义可自由配置；排位不生效。</p><MutationList :entries="weekly.entries" /><button class="button" data-testid="lobby-weekly-close" @click="weeklyOpen = false">知道了</button></section></AppOverlay>
  </section>
</template>
