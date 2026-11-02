<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useReplayStore } from '../../stores/replay'
import BattleStage from '../viewing/BattleStage.vue'
import ViewingRules from '../viewing/ViewingRules.vue'
import ViewingAnimationLayer from '../viewing/ViewingAnimationLayer.vue'
import { useViewingPlayback } from '../viewing/useViewingPlayback'
import { phaseText } from './model'
import type { Json } from '../viewing/types'
import '../viewing/viewing.css'

const route = useRoute(), router = useRouter(), store = useReplayStore()
const wide = ref(innerWidth > 800)
let internal = false
const playback = useViewingPlayback(snapshot => {
  if (!snapshot.frame || store.status !== 'ready') return
  internal = true
  store.setK(snapshot.step); store.setPlaying(snapshot.playing)
  internal = false
})
const frame = computed(() => playback.snapshot.value.frame ?? store.viewFrame)
const current = computed(() => store.recording?.steps[store.k])
const matchId = computed(() => String(route.query.match_id ?? ''))
const chain = computed(() => Array.isArray(frame.value?.chain.chain) ? frame.value!.chain.chain as Json[] : [])
watch(matchId, id => void store.load(id), { immediate: true })
watch(() => store.recording, recording => { if (recording) { playback.player.load(recording); playback.sync() } }, { immediate: true })
watch(() => store.k, k => { if (!internal) { playback.player.seek(k); playback.sync() } }, { flush: 'sync' })
watch(() => store.playing, playing => { if (!internal) { if (playing) playback.player.play(); else playback.player.pause(); playback.sync() } }, { flush: 'sync' })
watch(() => store.speed, speed => playback.player.setSpeed(speed), { immediate: true })
onBeforeUnmount(() => store.reset())
function exit(): void { void router.push('/lobby') }
</script>

<template>
  <section class="viewing" data-testid="screen-replay" aria-labelledby="viewing-title">
    <header class="viewing__header"><h1 id="viewing-title">对局回放</h1><small>重返这片交战海域</small><button type="button" class="button button--ghost" data-testid="replay-exit" @click="exit">退出回放</button></header>
    <div v-if="store.status === 'loading'" class="viewing__error" role="status">正在读取录像…</div>
    <div v-else-if="store.status === 'error'" class="viewing__error" role="alert" data-testid="replay-error"><p>{{ store.error }}</p><button class="button" @click="store.load(matchId)">重新加载</button></div>
    <template v-else-if="frame && store.recording">
      <div class="viewing__status">
        <span>第 <b>{{ frame.context.round ?? '—' }}</b> 回合</span><span>{{ phaseText(String(frame.context.phase ?? '')) }}</span>
        <span v-if="frame.context.current_side">{{ frame.players[frame.context.current_side as 'p1' | 'p2']?.name }} 行动</span>
        <span v-if="frame.context.attacks_remaining !== null">剩余额度 <b>{{ frame.context.attacks_remaining }}</b></span>
        <ViewingRules :frame="frame" />
      </div>
      <p v-if="store.recording.version === 1" class="viewing__notice" data-testid="replay-legacy-notice">旧版录像，部分状态或演出可能缺失。</p>
      <p v-if="store.recording.truncated" class="viewing__notice" data-testid="replay-truncated">{{ store.recording.truncated }}</p>
      <div class="viewing__layout">
        <main class="viewing__main">
          <BattleStage :frame="frame" mode="replay" />
          <div class="viewing__toolbar">
            <button type="button" class="button button--ghost" data-testid="replay-prev" :disabled="store.k <= 0" @click="store.setK(store.k - 1)">上一步</button>
            <button type="button" class="button" data-testid="replay-play" :aria-pressed="store.playing" @click="store.setPlaying(!store.playing)">{{ store.playing ? '暂停' : '播放' }}</button>
            <button type="button" class="button button--ghost" data-testid="replay-next" :disabled="store.k >= store.stepCount - 1" @click="store.setK(store.k + 1)">下一步</button>
            <input type="range" min="0" :max="Math.max(0, store.stepCount - 1)" :value="store.k" aria-label="回放进度" data-testid="replay-progress" @input="store.setK(Number(($event.target as HTMLInputElement).value))" />
            <span>{{ store.k + 1 }}/{{ store.stepCount }}</span>
            <div class="viewing__speed"><button v-for="speed in [1,2,4]" :key="speed" :class="{ 'is-active': store.speed === speed }" @click="store.setSpeed(speed)">{{ speed }}×</button></div>
          </div>
          <p class="viewing__notice" data-testid="replay-step-text">第 {{ store.k + 1 }} 步 · {{ current?.text }}</p>
        </main>
        <aside class="viewing__aside">
          <section class="viewing__panel"><h2>当前连锁</h2><div class="view-chain" data-testid="replay-chain"><span v-for="(item, i) in chain" :key="i">{{ i + 1 }} · {{ item.card }}{{ item.negated ? ' · 已无效' : '' }}</span><small v-if="!chain.length">当前没有连锁</small></div></section>
          <details class="viewing__panel" :open="wide"><summary>关键节点</summary><div class="viewing__nodes"><button v-for="(node,i) in store.recording.nodes" :key="i" class="button button--ghost" @click="store.setK(node.step)">{{ node.label }}</button></div></details>
          <details class="viewing__panel" :open="wide"><summary>对局记录</summary><ol class="viewing__logs"><li v-for="(step, i) in store.recording.steps" :key="i" :class="{ 'is-current': i === store.k }"><button class="view-log-button" @click="store.setK(i)">{{ step.text }}</button></li></ol></details>
        </aside>
      </div>
      <ViewingAnimationLayer :cue="playback.snapshot.value.cue" :progress="playback.snapshot.value.progress" />
    </template>
    <p v-else class="viewing__error">请从对局记录选择一场录像。</p>
  </section>
</template>
