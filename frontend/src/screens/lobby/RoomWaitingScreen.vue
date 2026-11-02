<script setup lang="ts">
import { ref } from 'vue'
import { useLobbyStore } from '../../stores/lobby'
import { useAuthStore } from '../../stores/auth'
import { useLobbyActions } from './useLobbyActions'
import AppOverlay from '../../components/AppOverlay.vue'
import FriendsRoomInvite from './FriendsRoomInvite.vue'
const lobby = useLobbyStore()
const auth = useAuthStore()
const actions = useLobbyActions()
const inviting = ref(false)
const confirmingClose = ref(false)
</script>
<template>
  <section class="lp-page lp-waiting-page" data-testid="screen-room-waiting" aria-labelledby="room-wait-title"><router-link :to="{ name: 'lobby' }" class="lp-back">‹ 返回游戏大厅</router-link><header class="lp-pagehead"><div><h1 id="room-wait-title">{{ lobby.ownRoomId ? '房间已创建' : '等待房间' }}</h1><p>邀请一位好友，或等一位玩家加入。</p></div></header>
    <div v-if="!lobby.hasSnapshot && !lobby.ownRoomId" class="lp-panel lp-empty" role="status">正在恢复你的房间…</div>
    <div v-else-if="!lobby.ownRoomId" class="lp-panel lp-empty"><p>你当前没有等待中的房间，房间可能已解散或已开始。</p><router-link class="button lp-primary" :to="{ name: 'lobby-create' }">创建房间</router-link></div>
    <section v-else class="lp-panel lp-waiting"><div class="lp-panelbody"><div class="lp-waiting-heading"><div><h2>{{ actions.ownRoomName.value }}</h2><p>房号 <b data-testid="room-wait-id">{{ lobby.ownRoomId }}</b></p></div><span class="lp-tag lp-tag--good">等待对手</span></div><div class="lp-duel"><div><span class="lp-avatar">{{ Array.from(auth.displayName)[0] }}</span><b>{{ lobby.ownRoom?.hostName || auth.displayName }}</b><small>你 · 房主</small></div><b class="lp-vs">VS</b><div><button type="button" class="lp-avatar lp-avatar--empty lp-invite-slot" data-testid="room-invite-slot" aria-label="邀请好友进入房间" @click="inviting = true">＋</button><b>邀请好友</b><small>或等待玩家加入</small></div></div><dl class="lp-rules lp-rules--grid"><div><dt>房间类型</dt><dd>{{ lobby.ownRoomPublic ? '公开房间' : '私密房间' }}</dd></div><div><dt>对战模式</dt><dd>自定义 · 不计排位分</dd></div><div><dt>赛前 Ban</dt><dd>{{ lobby.ownRoom?.banEnabled ? `每人 ${lobby.ownRoom.banQuota} 张` : '关闭' }}</dd></div><div><dt>突变</dt><dd>{{ lobby.ownRoom?.mutationEntries.map(e => e.name).join('、') || '无' }}</dd></div></dl><div class="lp-field"><h3>邀请对手</h3><div class="lp-invite-link"><span>房号 {{ lobby.ownRoomId }}</span><button class="button" data-testid="lobby-copy-invite" @click="actions.copyInviteLink()">复制邀请链接</button></div><p class="lp-help">{{ lobby.ownRoomPublic ? '房间也会出现在大厅，其他玩家可直接加入。' : '私密房不出现在公开列表，请分享房号或邀请链接。' }}</p><p v-if="actions.inviteCopyText.value" class="lp-help" role="status">{{ actions.inviteCopyText.value }}</p></div><div class="lp-waiting-actions"><router-link class="button button--ghost" data-testid="room-back-lobby" :to="{ name: 'lobby' }">返回大厅，保留房间</router-link><button class="lp-link lp-danger" data-testid="lobby-own-room-close" @click="confirmingClose = true">解散房间</button></div></div></section>
    <p v-if="lobby.ownRoom && !lobby.ownRoom.seatConnected && !lobby.ownRoom.canRestore" class="lp-feedback" role="status">房间正在你的另一个页面中，仍可在这里邀请好友。</p>
    <FriendsRoomInvite :open="inviting && !!lobby.ownRoomId" @close="inviting = false" />
    <AppOverlay v-if="confirmingClose && lobby.ownRoomId" id="room-close-confirm" label="解散房间" @close="confirmingClose = false"><div class="lp-dialog-small"><h2>解散这个房间？</h2><p>房间会从大厅消失，原邀请链接也将失效。</p><div class="lp-dialog-actions"><button class="button button--ghost" data-testid="lobby-own-room-close-cancel" @click="confirmingClose = false">保留房间</button><button class="button button--danger" data-testid="lobby-own-room-close-confirm" :disabled="actions.closePending.value" @click="actions.closeRoom(); confirmingClose = false">确认解散</button></div></div></AppOverlay>
  </section>
</template>
