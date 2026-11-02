<script setup lang="ts">
import type { LobbyMatch, LobbyRoom } from '../../stores/lobby'
import { initial, roomModeText } from './view'
defineProps<{ room?: LobbyRoom; match?: LobbyMatch; kind: 'room' | 'match'; loading?: boolean; first?: boolean }>()
defineEmits<{ (event: 'join', room: LobbyRoom): void; (event: 'watch', match: LobbyMatch): void }>()
</script>
<template>
  <article v-if="room" class="ld-preview-card" :data-testid="'lobby-room-' + room.roomId">
    <div class="ld-card-meta"><span>{{ roomModeText(room) }} · {{ room.public ? '公开' : '私密' }}</span><span>{{ room.players < room.capacity ? '等待对手' : '已满' }}</span></div>
    <h3 :title="room.name">{{ room.name }}</h3>
    <div class="ld-card-people"><span class="lp-avatar">{{ initial(room.host) }}</span><b :title="room.host">{{ room.host }}</b><span class="ld-card-vs">VS</span><span class="lp-avatar lp-avatar--empty" aria-label="对手席位">{{ room.players < room.capacity ? '＋' : '●' }}</span></div>
    <footer><small>{{ room.players }} / {{ room.capacity }} 人</small><button class="button button--ghost" :data-testid="'lobby-room-join-' + room.roomId" :disabled="room.players >= room.capacity" @click="$emit('join', room)">{{ room.players < room.capacity ? '加入房间' : '房间已满' }}</button></footer>
  </article>
  <article v-else-if="match" class="ld-preview-card" :data-testid="'lobby-match-' + match.roomId">
    <div class="ld-card-meta"><span>{{ match.ranked ? '排位对战' : '休闲对战' }}</span><span>第 {{ match.round }} 回合</span></div>
    <h3>海上交锋 <span class="ld-live-dot">进行中</span></h3>
    <div class="ld-card-people ld-card-people--match"><b :title="match.names[0]">{{ match.names[0] || '玩家' }}</b><span class="ld-card-vs">VS</span><b :title="match.names[1]">{{ match.names[1] || '玩家' }}</b></div>
    <footer><small>{{ match.spectators }} 人观战</small><button class="button button--ghost" :data-testid="'lobby-match-spectate-' + match.roomId" @click="$emit('watch', match)">观战</button></footer>
  </article>
  <article v-else class="ld-preview-card ld-preview-card--empty" :aria-busy="loading || undefined" :data-testid="first ? `lobby-${kind === 'room' ? 'rooms' : 'matches'}-empty` : undefined">
    <div class="ld-card-meta"><span>{{ kind === 'room' ? '房间席位' : '对局席位' }}</span><span>{{ loading ? '载入中' : '待命' }}</span></div>
    <div class="ld-empty-art" aria-hidden="true">{{ kind === 'room' ? '⚓' : '⚑' }}</div>
    <h3>{{ loading ? '正在读取…' : kind === 'room' ? (first ? '还没有公开房间' : '等待新房间') : '等待对局开始' }}</h3>
    <p>{{ kind === 'room' ? '新房间会自动出现在这里。' : '对局开始后会自动出现在这里。' }}</p>
    <footer><router-link v-if="kind === 'room' && first && !loading" class="button button--ghost" :to="{ name: 'lobby-create' }" data-testid="lobby-rooms-empty-cta">创建房间</router-link><small v-else>{{ loading ? '正在同步海域状态' : '当前暂无玩家' }}</small></footer>
  </article>
</template>
