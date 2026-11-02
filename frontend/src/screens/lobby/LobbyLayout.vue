<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { acquireLobbyChannel, getLobbySocket } from '../../realtime/lobby'
import { useLobbyStore } from '../../stores/lobby'
import { useGameStore } from '../../stores/game'
import { provideLobbyActions } from './useLobbyActions'
import { readInviteRoomId } from './inviteLink'
import MatchFoundOverlay from '../../components/MatchFoundOverlay.vue'
import AppOverlay from '../../components/AppOverlay.vue'
import './lobby-pages.css'
import './lobby-dashboard.css'

const route = useRoute()
const router = useRouter()
const lobby = useLobbyStore()
const game = useGameStore()
const actions = provideLobbyActions()
const joinOpen = ref(false)
const joinId = ref('')
let release: (() => void) | null = null
let inviteAttempt = ''
let restoring = ''

function enterMatch(): void {
  if (!lobby.startedRoomId || (lobby.matchFound && !game.state.card_bans?.enabled)) return
  lobby.clearMatchFound()
  lobby.takeStartedRoom()
  void router.push({ name: 'placement' })
}
function matchCountdownDone(): void {
  lobby.clearMatchFound()
  enterMatch()
}
watch([() => lobby.startedRoomId, () => lobby.matchFound], enterMatch)
watch([() => lobby.connected, () => route.query.room], async () => {
  const id = readInviteRoomId(route.query)
  if (!lobby.connected || !id || inviteAttempt === id) return
  inviteAttempt = id
  const storageKey = 'battleship.lobby.inviteJoined.' + id
  try { if (sessionStorage.getItem(storageKey) === '1') return } catch { /* 本次实例仍防重入。 */ }
  if (await actions.joinById(id)) {
    try { sessionStorage.setItem(storageKey, '1') } catch { /* 邀请仍已成功。 */ }
  } else inviteAttempt = ''
})
watch([() => lobby.connected, () => lobby.ownRoom], async () => {
  const own = lobby.ownRoom
  if (!lobby.connected || !own || own.seatConnected || !own.canRestore || restoring === own.roomId) return
  const current = getLobbySocket()
  if (!current) return
  restoring = own.roomId
  try {
    const ack = await current.emitEvent('join_room', { room_id: own.roomId })
    if (ack.status !== 'success') actions.fail(ack.message || '等待房间恢复失败，请刷新重试。')
    await actions.refresh()
  } catch (e) { actions.fail(e instanceof Error ? e.message : '等待房间恢复失败。') }
  finally { restoring = '' }
})
async function joinByNumber(): Promise<void> {
  if (await actions.joinById(joinId.value)) joinOpen.value = false
}
onMounted(() => {
  release = acquireLobbyChannel()
  void actions.loadFriends()
  enterMatch()
})
onBeforeUnmount(() => { release?.(); lobby.takeStartedRoom() })
</script>

<template>
  <MatchFoundOverlay v-if="lobby.matchFound && !game.state.card_bans?.enabled" :self-name="lobby.matchFound.playerName" :opponent-name="lobby.matchFound.opponentName" :mode="lobby.matchFound.mode" @done="matchCountdownDone" />
  <div class="lobby-pages" :class="{ 'lp-dashboard-shell': route.name === 'lobby' }">
    <p v-if="lobby.error" class="lp-feedback lp-feedback--error" role="alert" data-testid="lobby-error"><span :title="lobby.error">{{ lobby.error }}</span><button class="lp-link" @click="lobby.clearError()">关闭</button></p>
    <p v-else-if="lobby.activeInvite" class="lp-feedback" data-testid="lobby-invite-banner"><span>{{ lobby.activeInvite.fromUsername }} 邀请你进入房间 {{ lobby.activeInvite.roomId }}</span><button class="button" data-testid="lobby-invite-accept" :disabled="actions.acceptingInvite.value" @click="actions.acceptInvite()">接受邀请</button><button class="lp-link" data-testid="lobby-invite-dismiss" @click="lobby.clearInvite()">忽略</button></p>
    <p v-else-if="lobby.notice" class="lp-feedback" role="status" data-testid="lobby-notice"><span :title="lobby.notice">{{ lobby.notice }}</span></p>
    <router-view />
    <footer class="lp-footer"><button class="lp-link" data-testid="lobby-join-number" @click="joinOpen = true">凭房号加入</button><router-link :to="{ name: 'lobby' }">游戏大厅</router-link><router-link :to="{ name: 'start' }" data-testid="lobby-back-home">返回首页</router-link></footer>
  </div>
  <AppOverlay v-if="joinOpen" id="lobby-join-dialog" label="凭房号加入" @close="joinOpen = false"><form class="lp-dialog-small" @submit.prevent="joinByNumber"><h2>凭房号加入</h2><label for="lobby-join-id">房间号</label><input id="lobby-join-id" v-model="joinId" class="lp-input" maxlength="40" required autocomplete="off"><div class="lp-dialog-actions"><button type="button" class="button button--ghost" @click="joinOpen = false">取消</button><button class="button lp-primary" type="submit">加入房间</button></div></form></AppOverlay>
</template>
