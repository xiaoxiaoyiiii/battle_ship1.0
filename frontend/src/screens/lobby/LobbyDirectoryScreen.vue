<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useLobbyStore, type LobbyMatch } from '../../stores/lobby'
import { filterRooms, filterMatches } from './view'
import { useLobbyActions } from './useLobbyActions'
import RoomCard from './RoomCard.vue'
const props = defineProps<{ kind: 'rooms' | 'matches' }>()
const lobby = useLobbyStore()
const actions = useLobbyActions()
const router = useRouter()
const query = ref('')
const filter = ref('all')
const isRooms = computed(() => props.kind === 'rooms')
const rooms = computed(() => filterRooms(lobby.rooms, filter.value === 'joinable' ? 'joinable' : 'all', query.value))
const matches = computed(() => filterMatches(lobby.matches, 'all', query.value).filter(m => filter.value === 'all' || (m.ranked ? filter.value === 'ranked' : filter.value === 'casual')))
watch(() => props.kind, () => { query.value = ''; filter.value = 'all' })
function spectate(match: LobbyMatch): void { void router.push({ name: 'spectate', query: { room_id: match.roomId } }) }
</script>
<template>
  <section class="lp-page" :data-testid="isRooms ? 'screen-lobby-rooms' : 'screen-lobby-matches'" aria-labelledby="directory-title"><router-link class="lp-back" :to="{ name: 'lobby' }">‹ 返回游戏大厅</router-link><header class="lp-pagehead"><div><h1 id="directory-title">{{ isRooms ? '所有房间' : '进行中的对局' }}</h1><p>{{ isRooms ? '找一间合适的房间，加入下一场较量。' : '选择一场对局，看看这片海域的较量。' }}</p></div><router-link v-if="isRooms" class="button lp-primary" :to="{ name: lobby.ownRoomId ? 'lobby-room' : 'lobby-create' }">{{ lobby.ownRoomId ? '我的房间' : '创建房间' }}</router-link><button v-else class="button" @click="actions.refresh()">刷新</button></header><div class="lp-directory-tools"><div class="lp-segments" :aria-label="isRooms ? '房间筛选' : '对局筛选'"><button :class="{ 'is-selected': filter === 'all' }" @click="filter = 'all'">{{ isRooms ? '全部房间' : '全部对局' }}</button><template v-if="isRooms"><button :class="{ 'is-selected': filter === 'joinable' }" @click="filter = 'joinable'">可加入</button></template><template v-else><button :class="{ 'is-selected': filter === 'ranked' }" @click="filter = 'ranked'">排位</button><button :class="{ 'is-selected': filter === 'casual' }" @click="filter = 'casual'">休闲</button></template></div><input v-model="query" type="search" class="lp-input" data-testid="directory-search" :placeholder="isRooms ? '搜索房名、房主或房号' : '搜索对局玩家'" :aria-label="isRooms ? '搜索房间' : '搜索对局'"></div><div class="lp-directory-meta"><span>{{ isRooms ? rooms.length + ' 间房间' : matches.length + ' 场对局' }}</span><span>{{ lobby.connected ? '列表实时更新' : '连接中断，正在重连…' }}</span></div><div v-if="isRooms" class="lp-card-grid" data-testid="room-directory"><RoomCard v-for="room in rooms" :key="room.roomId" :room="room" @join="actions.joinRoom" /></div><div v-else class="lp-card-grid" data-testid="match-directory"><RoomCard v-for="match in matches" :key="match.roomId" :match="match" @watch="spectate" /></div><div v-if="!lobby.hasSnapshot" class="lp-empty" role="status">正在读取列表…</div><div v-else-if="isRooms ? !rooms.length : !matches.length" class="lp-empty" role="status"><p>{{ query ? '没有符合搜索条件的结果，试试其他关键词。' : isRooms ? '暂无可见的等待房间，你可以先创建一间。' : '暂无可观战的对局，稍后再来看看。' }}</p><router-link v-if="isRooms && !query" class="button" :to="{ name: 'lobby-create' }">创建房间</router-link></div></section>
</template>
