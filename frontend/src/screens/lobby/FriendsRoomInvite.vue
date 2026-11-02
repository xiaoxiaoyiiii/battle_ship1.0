<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import AppOverlay from '../../components/AppOverlay.vue'
import { useLobbyStore } from '../../stores/lobby'
import { useAuthStore } from '../../stores/auth'
import { useLobbyActions } from './useLobbyActions'
import { initial, inviteDisabledReason } from './view'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (event: 'close'): void }>()
const lobby = useLobbyStore()
const auth = useAuthStore()
const actions = useLobbyActions()
const query = ref('')
const friends = computed(() => lobby.friends.filter(f => f.username.toLowerCase().includes(query.value.trim().toLowerCase())))
watch(() => props.open, open => { if (open) { query.value = ''; void actions.loadFriends() } })
</script>
<template>
  <AppOverlay id="room-friend-picker" :open="open" transition-name="lp-picker" labelledby="room-friend-title" @close="emit('close')">
    <section class="lp-picker lp-friend-picker"><header class="lp-picker__head"><div><h2 id="room-friend-title">邀请好友进入房间</h2><p>好友接受后进入当前房间，保留你设置的玩法。</p></div><button class="lp-link" data-testid="room-friend-picker-close" @click="emit('close')">关闭</button></header>
      <div class="lp-picker__options"><template v-if="lobby.friendsGuest"><p class="lp-empty">登录后可邀请好友，也可以直接复制房间邀请链接。</p><button class="button" @click="emit('close'); auth.open('login', '登录后邀请好友。')">登录账号</button></template><template v-else><input v-model="query" class="lp-input" placeholder="搜索好友" aria-label="搜索好友"><p v-if="lobby.friendsError" class="lp-conflict" role="alert">{{ lobby.friendsError }}</p><p v-if="actions.friendsBusy.value" role="status">正在读取好友…</p><ul class="lp-friend-list"><li v-for="friend in friends" :key="friend.userId"><span class="lp-avatar">{{ initial(friend.username) }}</span><span class="lp-friend-name"><b>{{ friend.username }}</b><small>{{ !friend.online ? '离线' : friend.inGame ? '正在房间或对局中' : '在线 · 可邀请' }}</small></span><button class="button" :data-testid="'room-friend-invite-' + friend.userId" :disabled="!!inviteDisabledReason(friend) || !!actions.invitingUsername.value || !lobby.ownRoomId" :title="inviteDisabledReason(friend)" @click="actions.inviteFriend(friend)">{{ actions.invitingUsername.value === friend.username ? '发送中…' : '邀请' }}</button></li></ul><p v-if="!friends.length && !actions.friendsBusy.value" class="lp-empty">{{ query ? '没有符合条件的好友。' : '还没有可邀请的好友，可复制邀请链接分享。' }}</p></template></div>
      <footer class="lp-picker__foot"><button class="button button--ghost" :disabled="actions.friendsBusy.value" @click="actions.loadFriends()">刷新好友</button><button class="button lp-primary" @click="actions.copyInviteLink()">复制邀请链接</button><p v-if="actions.inviteCopyText.value" role="status">{{ actions.inviteCopyText.value }}</p></footer>
    </section>
  </AppOverlay>
</template>
