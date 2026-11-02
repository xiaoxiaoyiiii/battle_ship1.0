<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSpectateStore } from '../../stores/spectate'
import { useAudioStore } from '../../stores/audio'
import { acquireSpectateChannel, joinSpectate, leaveSpectate, sendSpectateChat } from '../../realtime/spectate'
import BattleStage from '../viewing/BattleStage.vue'
import ViewingRules from '../viewing/ViewingRules.vue'
import ViewingAnimationLayer from '../viewing/ViewingAnimationLayer.vue'
import { useViewingPlayback } from '../viewing/useViewingPlayback'
import { phaseText } from '../replay/model'
import type { Json } from '../viewing/types'
import '../viewing/viewing.css'

const route = useRoute(), router = useRouter(), store = useSpectateStore()
const audio = useAudioStore()
const roomId = computed(() => String(route.query.room_id ?? ''))
const playback = useViewingPlayback()
const frame = computed(() => playback.snapshot.value.frame ?? store.viewFrame)
const chain = computed(() => frame.value?.context.state !== 'game_over' && Array.isArray(frame.value?.chain.chain) ? frame.value!.chain.chain as Json[] : [])
const draft = ref(''), wide = ref(innerWidth > 800)
let release: (() => void) | null = null
watch(() => store.viewPacket, packet => {
  if (!packet) return
  if (packet.baseline) { playback.player.dispose(); playback.sync() }
  playback.player.enqueue(packet); playback.sync(false)
}, { flush: 'sync' })
onMounted(() => { release = acquireSpectateChannel(); void joinSpectate(roomId.value) })
watch(roomId, async (id, old) => { if (id !== old) { await leaveSpectate(); playback.player.dispose(); await joinSpectate(id) } })
onBeforeUnmount(() => { const stop = release; release = null; void leaveSpectate().finally(() => stop?.()) })
async function exit(): Promise<void> { await leaveSpectate(); void router.push('/lobby') }
async function chat(): Promise<void> { if ((await sendSpectateChat(draft.value)).ok) draft.value = '' }
</script>

<template>
  <section class="viewing" data-testid="screen-spectate" aria-labelledby="spectate-title">
    <header class="viewing__header"><h1 id="spectate-title">实时观战</h1><small>{{ store.count }}/{{ store.limit || 20 }} 位观众</small><button type="button" class="button button--ghost" data-testid="spectate-exit" @click="exit">退出观战</button></header>
    <div v-if="store.error" class="viewing__error" role="alert" data-testid="spectate-error"><p>{{ store.error }}</p><button class="button" @click="joinSpectate(roomId)">重新加入</button></div>
    <template v-else-if="frame">
      <div class="viewing__status"><span>第 <b>{{ frame.context.round }}</b> 回合</span><span>{{ phaseText(String(frame.context.phase ?? '')) }}</span><span>剩余额度 <b>{{ frame.context.attacks_remaining }}</b></span><span v-if="frame.context.field_magic">场地 {{ frame.context.field_magic }}</span><button type="button" class="button button--ghost" data-testid="viewing-sound" :aria-pressed="!audio.sfxMuted" @click="audio.toggleSfxMute()">音效{{ audio.sfxMuted ? '关' : '开' }}</button><ViewingRules :frame="frame" /></div>
      <p v-if="store.phase === 'ended'" class="viewing__notice" data-testid="spectate-ended">对局已结束{{ store.winnerLabel ? '，获胜方：' + store.winnerLabel : '' }}{{ store.endedReason ? ' · ' + store.endedReason : '' }}</p>
      <div class="viewing__layout">
        <main class="viewing__main"><BattleStage :frame="frame" mode="spectate" /><p class="viewing__notice">只显示本局允许公开的信息。词条公开的手牌和舰位也会在这里显示。</p></main>
        <aside class="viewing__aside">
          <section class="viewing__panel"><h2>当前连锁</h2><div class="view-chain" data-testid="spectate-chain"><span v-for="(item,i) in chain" :key="i">{{ i + 1 }} · {{ item.card }}{{ item.negated ? ' · 已无效' : '' }}</span><small v-if="!chain.length">当前没有连锁</small></div></section>
          <details class="viewing__panel" :open="wide"><summary>观战席 {{ store.count }} 人</summary><p v-for="(person,i) in store.roster" :key="i">{{ person.name }}{{ person.name === store.me ? ' · 你' : '' }}</p><small v-if="!store.roster.length">还没有其他观众</small></details>
          <details class="viewing__panel" :open="wide"><summary>观战席聊天</summary><div class="view-chat"><div class="view-chat__lines" data-testid="spectate-chat"><p v-for="line in store.chat" :key="line.seq"><b>{{ line.name }}</b> {{ line.text }}</p><small v-if="!store.chat.length">和其他观众聊聊这场较量</small></div><form @submit.prevent="chat"><input v-model="draft" maxlength="200" placeholder="和观众说点什么…" aria-label="观战聊天内容" data-testid="spectate-chat-input" /><button class="button" type="submit" data-testid="spectate-chat-send">发送</button></form><small>这里的聊天仅观众可见。</small></div></details>
          <details class="viewing__panel" :open="wide"><summary>对局记录</summary><ol class="viewing__logs"><li v-for="(log,i) in store.logs" :key="i">{{ log.text }}</li></ol></details>
        </aside>
      </div>
      <ViewingAnimationLayer :cue="playback.snapshot.value.cue" :progress="playback.snapshot.value.progress" />
    </template>
    <p v-else class="viewing__error" role="status">{{ store.phase === 'ended' ? '本场对局已结束。' : '正在连接观战席…' }}</p>
  </section>
</template>
