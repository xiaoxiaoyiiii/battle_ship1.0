<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useLobbyStore, type LobbyMatch } from '../../stores/lobby'
import { useHomeStore } from '../../stores/home'
import { useLobbyActions } from './useLobbyActions'
import AppOverlay from '../../components/AppOverlay.vue'
import ActivityCalendar from '../../components/ActivityCalendar.vue'
import MutationList from '../../components/MutationList.vue'
import BanPreselection from '../../components/BanPreselection.vue'
import LobbyPreviewCard from './LobbyPreviewCard.vue'
import LobbySocial from './LobbySocial.vue'
import DailyChallengePanel from './DailyChallengePanel.vue'
import { useDailyChallenge } from './useDailyChallenge'

const lobby = useLobbyStore()
const home = useHomeStore()
const router = useRouter()
const actions = useLobbyActions()
const daily = useDailyChallenge()
const root = ref<HTMLElement | null>(null)
const size = ref({ width: 1200, height: 700 })
const socialOpen = ref(false)
const socialView = ref<'players' | 'chat' | 'friends'>('players')
const weeklyOpen = ref(false)
const announcementOpen = ref(false)
const calendarOpen = ref(false)
const activePreview = ref<'rooms' | 'matches'>('rooms')
const paged = computed(() => size.value.height < 550 && size.value.width < 500)
const compact = computed(() => size.value.width < 1000 || size.value.height < 520)
const sideways = computed(() => size.value.height < 420 && size.value.width >= 620)
const previewCount = computed(() => {
  const width = (size.value.width - (compact.value ? 0 : 284)) / (sideways.value ? 2 : 1)
  return width >= 840 ? 3 : width >= 520 ? 2 : 1
})
const rooms = computed(() => lobby.rooms.slice(0, previewCount.value))
const matches = computed(() => lobby.matches.slice(0, previewCount.value))
const weekly = computed(() => lobby.snapshot?.weeklyMutations ?? null)
const changelog = computed(() => home.changelog[0]?.items?.join('；') || '')
let observer: ResizeObserver | null = null
function count(value: number): string { return lobby.hasSnapshot ? String(value) : '—' }
function spectate(match: LobbyMatch): void { void router.push({ name: 'spectate', query: { room_id: match.roomId } }) }
function openSocial(view: 'players' | 'chat' | 'friends'): void {
  socialView.value = view
  socialOpen.value = true
  if (view === 'friends') void actions.loadFriends()
}
onMounted(() => {
  observer = new ResizeObserver(([entry]) => { if (entry) size.value = { width: entry.contentRect.width, height: entry.contentRect.height } })
  if (root.value) observer.observe(root.value)
  if (!home.changelogLoaded) void home.loadChangelog(1)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <section ref="root" class="lp-page ld-dashboard" :class="{ 'ld-dashboard--compact': compact, 'ld-dashboard--paged': paged, 'ld-dashboard--short': size.height < 550, 'ld-dashboard--sideways': sideways }" data-screen="lobby" data-testid="screen-lobby" aria-labelledby="lobby-title" :style="{ '--ld-slots': previewCount }">
    <header class="ld-heading"><div><h1 id="lobby-title" data-testid="lobby-heading">游戏大厅</h1><p>选择一位对手，开始下一场较量。</p></div><div class="ld-heading-actions"><button class="lp-link" data-testid="lobby-calendar" @click="calendarOpen = true">活动日历</button><div v-if="lobby.ownRoomId && paged" data-testid="lobby-own-room"><router-link class="button button--ghost" data-testid="lobby-own-room-return" :to="{ name: 'lobby-room' }" :title="actions.ownRoomName.value">返回房间</router-link><span class="sr-only" data-testid="lobby-own-room-id">{{ lobby.ownRoomId }}</span></div><button v-if="changelog" class="lp-link" data-testid="lobby-changelog" @click="announcementOpen = true">公告</button><button class="button button--ghost" data-testid="lobby-refresh" @click="actions.refresh()">刷新</button></div></header>
    <section v-if="lobby.ownRoomId && !paged" class="ld-own-room" data-testid="lobby-own-room"><div><b :title="actions.ownRoomName.value">{{ actions.ownRoomName.value }}</b><small>我的房间 · <span data-testid="lobby-own-room-id">{{ lobby.ownRoomId }}</span> · {{ lobby.ownRoomPublic ? '公开' : '私密' }}</small></div><router-link class="button button--ghost" :to="{ name: 'lobby-room' }" data-testid="lobby-own-room-return">返回房间</router-link></section>
    <nav class="ld-actions" aria-label="大厅主行动"><button class="button lp-primary" data-testid="lobby-match-casual" :disabled="!!lobby.queueMode || !!lobby.ownRoomId" @click="actions.startMatch('casual')">快速匹配</button><router-link class="button" data-testid="lobby-create-room" :to="{ name: lobby.ownRoomId ? 'lobby-room' : 'lobby-create' }">{{ lobby.ownRoomId ? '我的房间' : '创建房间' }}</router-link><button v-if="!lobby.queueMode" class="button button--ghost" data-testid="lobby-match-ranked" :disabled="!!lobby.ownRoomId" @click="actions.startMatch('ranked')">排位匹配</button><button v-else class="button button--danger" data-testid="lobby-match-cancel" @click="actions.cancelMatch()">取消匹配</button><span v-if="lobby.queueMode" class="ld-queue" data-testid="lobby-queue-state" role="status">{{ lobby.queueMode === 'ranked' ? '排位' : '休闲' }}匹配中…</span><span v-else class="ld-actions-hint">1v1 海战 · 自定义房不计排位分</span></nav>
    <div class="ld-main"><div class="ld-previews">
      <section class="lp-panel ld-preview-panel" :class="{ 'is-collapsed': paged && activePreview !== 'rooms' }"><header class="lp-panelhead"><h2><button class="ld-group-toggle" data-testid="lobby-rooms-toggle" :aria-expanded="!paged || activePreview === 'rooms'" @click="activePreview = 'rooms'">房间列表</button> <small>{{ count(lobby.rooms.length) }} 间等待中</small></h2><router-link class="lp-link" :to="{ name: 'lobby-rooms' }" data-testid="lobby-all-rooms">查看所有</router-link></header><ul class="ld-card-strip" data-testid="lobby-rooms"><li v-for="n in previewCount" :key="n" :aria-hidden="!rooms[n-1] && n > 1"><LobbyPreviewCard v-if="rooms[n-1] || n === 1" kind="room" :room="rooms[n-1]" :first="n === 1" :loading="!lobby.hasSnapshot" @join="actions.joinRoom" /></li></ul></section>
      <section class="lp-panel ld-preview-panel" :class="{ 'is-collapsed': paged && activePreview !== 'matches' }"><header class="lp-panelhead"><h2><button class="ld-group-toggle" data-testid="lobby-matches-toggle" :aria-expanded="!paged || activePreview === 'matches'" @click="activePreview = 'matches'">进行中的对局</button> <small>{{ count(lobby.matches.length) }} 局</small></h2><router-link class="lp-link" :to="{ name: 'lobby-matches' }" data-testid="lobby-all-matches">查看所有</router-link></header><ul class="ld-card-strip" data-testid="lobby-matches"><li v-for="n in previewCount" :key="n" :aria-hidden="!matches[n-1] && n > 1"><LobbyPreviewCard v-if="matches[n-1] || n === 1" kind="match" :match="matches[n-1]" :first="n === 1" :loading="!lobby.hasSnapshot" @watch="spectate" /></li></ul></section>
    </div><aside v-if="!compact" class="ld-sidebar"><LobbySocial view="all" /></aside></div>
    <div class="ld-stats"><span>在线 <b data-testid="lobby-online-count">{{ count(lobby.onlineCount) }}</b></span><span>大厅 <b data-testid="lobby-lobby-count">{{ count(lobby.lobbyCount) }}</b></span><span>休闲队列 <b data-testid="lobby-queue-casual">{{ count(lobby.queueCasual) }}</b></span><span>排位队列 <b data-testid="lobby-queue-ranked">{{ count(lobby.queueRanked) }}</b></span></div>
    <nav class="ld-tools" aria-label="大厅工具"><button class="button button--ghost ld-daily-entry" data-testid="lobby-daily-challenge" :title="`${daily.view.value?.puzzle?.name || '每日挑战'} · ${daily.label.value}`" @click="daily.show()">{{ paged ? '挑战' : '每日挑战' }}<small v-if="!paged"> · {{ daily.label.value }}</small></button><BanPreselection :compact="paged" /><button v-if="weekly" class="button button--ghost" data-testid="lobby-weekly-details" :title="weekly.entries.map(e => e.name).join('、')" @click="weeklyOpen = true">{{ paged ? '突变' : '本周突变' }}</button><button class="button button--ghost" data-testid="lobby-fold-friends" @click="openSocial('friends')">{{ paged ? '好友' : '好友邀战' }}</button><button v-if="compact" class="button button--ghost" data-testid="lobby-social-open" @click="openSocial('players')">{{ paged ? '公屏' : '玩家 / 公屏' }}</button></nav>
    <AppOverlay v-if="socialOpen" id="lobby-social-dialog" label="大厅社交" @close="socialOpen = false"><div class="ld-social-dialog"><header><nav class="lp-segments" aria-label="社交内容"><button v-for="item in [{id:'players' as const,label:'在线玩家'},{id:'chat' as const,label:'大厅公屏'},{id:'friends' as const,label:'好友邀战'}]" :key="item.id" :class="{ 'is-selected': socialView === item.id }" @click="socialView = item.id">{{ item.label }}</button></nav><button class="lp-link" data-testid="lobby-social-close" @click="socialOpen = false">关闭</button></header><LobbySocial :view="socialView" /></div></AppOverlay>
    <AppOverlay v-if="weeklyOpen && weekly" id="lobby-weekly-preview" labelledby="lobby-weekly-title" @close="weeklyOpen = false"><section class="lp-dialog-small ld-detail-dialog"><h2 id="lobby-weekly-title">本周突变 · {{ weekly.name }}</h2><p>休闲每局随机遇见词条，自定义可自由配置；排位不生效。</p><MutationList :entries="weekly.entries" /><button class="button" data-testid="lobby-weekly-close" @click="weeklyOpen = false">知道了</button></section></AppOverlay>
    <AppOverlay v-if="announcementOpen" id="lobby-announcement" label="更新公告" @close="announcementOpen = false"><section class="lp-dialog-small ld-detail-dialog"><h2>更新公告</h2><p>{{ changelog }}</p><button class="button" data-testid="lobby-changelog-close" @click="announcementOpen = false">知道了</button></section></AppOverlay>
    <AppOverlay v-if="daily.open.value" id="daily-challenge-dialog" label="每日挑战" @close="daily.open.value = false"><DailyChallengePanel :view="daily.view.value" :busy="daily.busy.value" :error="daily.error.value" @start="daily.start" @refresh="daily.load" /></AppOverlay>
  </section>
  <ActivityCalendar v-if="calendarOpen" @close="calendarOpen = false" />
</template>
