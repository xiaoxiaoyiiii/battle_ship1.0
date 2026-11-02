<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useLobbyStore } from '../../stores/lobby'
import { useAuthStore } from '../../stores/auth'
import { getLobbySocket } from '../../realtime/lobby'
import { useLobbyActions } from './useLobbyActions'
import { initial, statusText, levelText, rankText, timeText, inviteDisabledReason } from './view'
defineProps<{ view: 'all' | 'players' | 'chat' | 'friends' }>()
const lobby = useLobbyStore()
const auth = useAuthStore()
const actions = useLobbyActions()
const chatDraft = ref('')
const chatEl = ref<HTMLElement | null>(null)
watch(() => lobby.chat.length, async () => { await nextTick(); if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight })
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
</script>
<template>
  <div class="ld-social-view" :class="{ 'ld-social-view--all': view === 'all' }">
    <section v-if="view === 'all' || view === 'players'" class="lp-panel ld-social-panel"><header class="lp-panelhead"><h2>在线玩家 <small>{{ lobby.players.length }} 人</small></h2></header><ul v-if="lobby.players.length" class="lp-player-list" data-testid="lobby-players"><li v-for="player in lobby.players" :key="player.key" :data-testid="'lobby-player-' + player.key"><span class="lp-avatar lp-avatar--small" :style="player.avatar ? { backgroundImage: `url(${JSON.stringify(player.avatar)})`, backgroundSize: 'cover' } : undefined">{{ player.avatar ? '' : initial(player.name) }}</span><div><b :class="{ 'lp-player-rainbow': player.nameStyle === 'rainbow' }">{{ player.name }}</b><span v-if="player.guest" class="lp-tag">游客</span><span v-if="player.title" class="lp-player-title">{{ player.title }}</span><small>{{ levelText(player) }} {{ rankText(player) }} · {{ statusText(player) }} <span v-if="player.key === lobby.myKey" data-testid="lobby-player-me"> · 你</span></small></div></li></ul><p v-else class="lp-empty" data-testid="lobby-players-empty">{{ lobby.hasSnapshot ? '暂时没有其他玩家。' : '正在读取玩家…' }}</p></section>
    <section v-if="view === 'all' || view === 'chat'" class="lp-panel ld-social-panel"><header class="lp-panelhead"><h2>大厅公屏</h2><span class="lp-tag lp-tag--cyan">实时</span></header><div ref="chatEl" class="lp-chat" data-testid="lobby-chat"><p v-if="!lobby.chat.length" class="lp-empty" data-testid="lobby-chat-empty">还没有人说话，打个招呼吧。</p><p v-for="(line,index) in lobby.chat" :key="line.seq || index" :data-testid="'lobby-chat-message-' + line.seq"><small>{{ line.name }} · {{ timeText(line.ts) }}</small><span>{{ line.message }}</span></p></div><form class="lp-chat-form" @submit.prevent="sendChat"><input v-model="chatDraft" class="lp-input" data-testid="lobby-chat-input" maxlength="120" aria-label="大厅公屏消息" placeholder="说点什么…"><button class="button" type="submit" data-testid="lobby-chat-send" :disabled="!lobby.connected || !chatDraft.trim()">发送</button></form></section>
    <section v-if="view === 'friends'" class="lp-panel ld-social-panel"><header class="lp-panelhead"><h2>好友邀战</h2><button class="lp-link" data-testid="lobby-friends-refresh" :disabled="actions.friendsBusy.value" @click="actions.loadFriends()">刷新</button></header><div class="ld-friends-body"><p v-if="lobby.friendsGuest || auth.isGuest" class="lp-empty" data-testid="lobby-friends-guest">登录后可以邀请好友。<button class="lp-link" @click="auth.open('login', '登录后邀请好友。')">登录</button></p><template v-else><p v-if="lobby.friendsError" class="lp-conflict">{{ lobby.friendsError }}</p><ul class="lp-friend-list" data-testid="lobby-friends"><li v-for="friend in lobby.friends" :key="friend.userId" :data-testid="'lobby-friend-' + friend.userId"><span class="lp-avatar lp-avatar--small">{{ initial(friend.username) }}</span><span class="lp-friend-name"><b>{{ friend.username }}</b><small>{{ !friend.online ? '离线' : friend.inGame ? '对局中' : '在线' }}</small></span><button class="button" :disabled="!!inviteDisabledReason(friend) || !!actions.invitingUsername.value" :data-testid="'lobby-friend-invite-' + friend.userId" @click="actions.inviteFriend(friend)">邀请</button></li></ul><p v-if="!lobby.friends.length && !actions.friendsBusy.value" class="lp-empty" data-testid="lobby-friends-empty">还没有可邀请的好友。</p></template></div></section>
  </div>
</template>
