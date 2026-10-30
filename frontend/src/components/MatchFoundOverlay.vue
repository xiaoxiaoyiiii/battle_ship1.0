<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppOverlay from './AppOverlay.vue'
import AvatarStack from './AvatarStack.vue'
import TitleBadge from './TitleBadge.vue'
import { useProfileStore, type JsonObject } from '../stores/profile'
import { useAudioStore } from '../stores/audio'

/**
 * 匹配成功身份预览：沿用冻结的五秒确认流程，只把已经存在的公开资料
 * 投影到赛前卡片里。资料读取失败时仍然保留名字和 AI/对手的基础身份。
 */
const props = withDefaults(
  defineProps<{
    selfName?: string
    opponentName?: string
    mode?: string
    seconds?: number
  }>(),
  { selfName: '', opponentName: '', mode: 'casual', seconds: 5 },
)

const emit = defineEmits<{ (event: 'done'): void }>()
const profile = useProfileStore()
const audio = useAudioStore()

function stringValue(source: JsonObject | null, key: string): string {
  const value = source?.[key]
  return typeof value === 'string' ? value : ''
}

function objectValue(source: JsonObject | null, key: string): JsonObject | null {
  const value = source?.[key]
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : null
}

function numberValue(source: JsonObject | null, key: string): number | null {
  const value = source?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

interface MatchPlayerView {
  name: string
  avatar: string
  frame: string
  title: string
  titleId: string
  titleFxId: string
  rank: string
  level: string
  fallback: string
}

function playerView(source: JsonObject | null, fallbackName: string, ai = false): MatchPlayerView {
  const rank = objectValue(source, 'rank_info')
  const level = objectValue(source, 'level_info')
  const name = stringValue(source, 'username') || fallbackName || (ai ? 'AI' : '指挥官')
  const levelNumber = numberValue(level, 'level')
  return {
    name,
    avatar: stringValue(source, 'avatar'),
    frame: stringValue(source, 'frame_id') || 'none',
    title: stringValue(source, 'title_name') || (ai ? '训练对手' : ''),
    titleId: stringValue(source, 'title_id'),
    titleFxId: stringValue(source, 'title_effect_id'),
    rank: stringValue(rank, 'label') || (ai ? 'AI 对战' : '段位资料加载中'),
    level: levelNumber === null ? (ai ? 'AI' : 'Lv.--') : 'Lv.' + levelNumber,
    fallback: name.slice(0, 1).toUpperCase() || (ai ? 'A' : '⚓'),
  }
}

const totalMs = Math.max(0, Math.floor(props.seconds * 1000))
const remaining = ref(Math.ceil(totalMs / 1000))
watch(remaining, (value, previous) => {
  if (value !== previous && value > 0 && value <= 3) audio.playUi('countdown')
})
const progress = ref(1)
const profilesLoading = ref(true)
const selfProfile = ref<JsonObject | null>(null)
const opponentProfile = ref<JsonObject | null>(null)
const selfName = computed(() => props.selfName || '你')
const opponentName = computed(() => props.opponentName || '对手')
const opponentIsAi = computed(() => opponentName.value.trim().toUpperCase() === 'AI')
const modeLabel = computed(() => (opponentIsAi.value ? '人机对战' : props.mode === 'ranked' ? '排位对战' : '休闲对战'))
const countdownText = computed(() => (remaining.value > 0 ? remaining.value + ' 秒' : '即将进入'))
const selfView = computed(() => playerView(selfProfile.value, selfName.value))
const opponentView = computed(() => playerView(opponentProfile.value, opponentName.value, opponentIsAi.value))

async function loadIdentity(): Promise<void> {
  profilesLoading.value = true
  const ownTask = profile.loadOwn().then(async () => {
    selfProfile.value = profile.own
    const username = stringValue(profile.own, 'username')
    if (!username) return
    try {
      const response = await fetch('/user_stats?username=' + encodeURIComponent(username), { headers: { accept: 'application/json' } })
      if (!response.ok) return
      const body = await response.json().catch(() => null) as { stats?: JsonObject } | null
      if (body?.stats && typeof body.stats === 'object') selfProfile.value = { ...profile.own, ...body.stats }
    } catch {
      // /api/profile 仍然足够提供头像和基础身份，公开卡片失败不阻塞倒计时。
    }
  }).catch(() => undefined)
  const opponentTask = opponentIsAi.value
    ? Promise.resolve()
    : fetch('/user_stats?username=' + encodeURIComponent(opponentName.value), { headers: { accept: 'application/json' } })
      .then(async response => {
        if (!response.ok) return
        const body = await response.json().catch(() => null) as { stats?: JsonObject } | null
        opponentProfile.value = body?.stats && typeof body.stats === 'object' ? body.stats : null
      })
      .catch(() => undefined)
  await Promise.all([ownTask, opponentTask])
  profilesLoading.value = false
}

let frame = 0
let deadline = 0

function stop(): void {
  if (frame) cancelAnimationFrame(frame)
  frame = 0
}

function finish(): void {
  stop()
  emit('done')
}

onMounted(() => {
  audio.playUi('match')
  void loadIdentity()
  deadline = performance.now() + totalMs
  const tick = () => {
    const left = Math.max(0, deadline - performance.now())
    progress.value = totalMs > 0 ? left / totalMs : 0
    remaining.value = Math.ceil(left / 1000)
    if (left <= 0) { remaining.value = 0; progress.value = 0; finish(); return }
    frame = requestAnimationFrame(tick)
  }
  tick()
})

onBeforeUnmount(stop)
</script>

<template>
  <AppOverlay
    id="match-found-overlay"
    layer="match-found"
    :priority="250"
    labelledby="match-found-title"
    @close="finish"
  >
    <div class="match-found__panel" :class="{ 'match-found__panel--loading': profilesLoading }">
      <div class="match-found__shock" aria-hidden="true"><i></i><i></i><i></i></div>
      <p class="match-found__eyebrow">{{ modeLabel }} · 对战确认</p>
      <h2 id="match-found-title" class="match-found__title">匹配成功！</h2>
      <p class="match-found__subline">双方身份已锁定 · 即将进入布船阶段</p>
      <div class="match-found__countdown-clock" :style="{ '--countdown-progress': String(progress) }">
        <span class="match-found__countdown-ring" aria-hidden="true"></span>
        <span class="match-found__countdown" data-testid="match-found-countdown" role="status" aria-live="polite">{{ countdownText }}</span>
      </div>

      <div class="match-found__sides">
        <article class="match-found__side" data-testid="match-found-self">
          <div class="match-found__side-sheen" aria-hidden="true"></div>
          <p class="match-found__designation">PLAYER 01 / 你</p>
          <AvatarStack class="match-found__avatar" :src="selfView.avatar" :frame="selfView.frame" :fallback="selfView.fallback" :alt="selfView.name" size="lg" testid="match-found-self-avatar" />
          <div class="match-found__identity">
            <h3>{{ selfView.name }}</h3>
            <TitleBadge v-if="selfView.title" :name="selfView.title" :title-id="selfView.titleId" :title-fx-id="selfView.titleFxId" compact />
            <div class="match-found__chips">
              <span data-testid="match-found-self-rank">{{ selfView.rank }}</span>
              <span data-testid="match-found-self-level">{{ selfView.level }}</span>
            </div>
          </div>
        </article>

        <div class="match-found__versus-wrap" aria-hidden="true">
          <span class="match-found__versus-pulse"></span>
          <span class="match-found__versus">VS</span>
        </div>

        <article class="match-found__side match-found__side--rival" data-testid="match-found-opponent">
          <div class="match-found__side-sheen" aria-hidden="true"></div>
          <p class="match-found__designation">PLAYER 02 / 对手</p>
          <AvatarStack class="match-found__avatar" :src="opponentView.avatar" :frame="opponentView.frame" :fallback="opponentView.fallback" :alt="opponentView.name" size="lg" testid="match-found-opponent-avatar" />
          <div class="match-found__identity">
            <h3>{{ opponentView.name }}</h3>
            <TitleBadge v-if="opponentView.title" :name="opponentView.title" :title-id="opponentView.titleId" :title-fx-id="opponentView.titleFxId" compact />
            <div class="match-found__chips">
              <span data-testid="match-found-opponent-rank">{{ opponentView.rank }}</span>
              <span data-testid="match-found-opponent-level">{{ opponentView.level }}</span>
            </div>
          </div>
        </article>
      </div>

      <div class="match-found__progress"><i :style="{ width: (progress * 100) + '%' }"></i></div>
      <button type="button" class="match-found__skip" data-primary-action="true" data-testid="match-found-skip" @click="finish">立即进入布船</button>
    </div>
  </AppOverlay>
</template>

<style scoped>
.match-found__panel { position:relative; width:min(980px,calc(100vw - 40px)); overflow:hidden; padding:34px 38px 28px; text-align:center; background:radial-gradient(circle at 50% 0%,rgb(57 137 169 / 22%),transparent 43%),linear-gradient(125deg,#091d31f2,#17152cf2 80%); border:1px solid rgb(89 187 224 / 48%); border-radius:22px; box-shadow:0 30px 90px rgb(0 0 0 / 48%),inset 0 0 0 1px rgb(255 255 255 / 5%); }
.match-found__panel::before { content:''; position:absolute; inset:12px; border:1px solid rgb(117 215 242 / 16%); border-radius:15px; pointer-events:none; }
.match-found__panel::after { content:''; position:absolute; inset:0; background:linear-gradient(110deg,transparent 0 36%,rgb(112 225 255 / 8%) 48%,transparent 60%); transform:translateX(-120%); animation:match-found-sweep 1.8s .18s ease-out forwards; pointer-events:none; }
.match-found__shock { position:absolute; top:76px; left:50%; width:440px; height:240px; transform:translateX(-50%); pointer-events:none; opacity:.6; }
.match-found__shock i { position:absolute; inset:0; border:1px solid rgb(119 221 255 / 18%); border-radius:50%; transform:scale(.28); animation:match-found-shock 1.4s cubic-bezier(.15,.65,.3,1) both; }
.match-found__shock i:nth-child(2) { animation-delay:.12s; }.match-found__shock i:nth-child(3) { animation-delay:.24s; }
.match-found__eyebrow { position:relative; z-index:1; color:#7cdbfa; letter-spacing:.22em; font-size:12px; margin:0; }
.match-found__title { position:relative; z-index:1; font-size:clamp(30px,4vw,52px); margin:7px 0 0; color:#e9f7ff; letter-spacing:.06em; text-shadow:0 0 24px #4ec8e099; animation:match-found-title-in .7s ease-out both; }
.match-found__subline { position:relative; z-index:1; margin:4px 0 8px; color:#9bb6c9; font-size:12px; letter-spacing:.08em; }
.match-found__countdown { color:var(--gold); margin:0 0 24px; }
.match-found__countdown-clock { position:relative; z-index:1; display:grid; place-items:center; width:76px; height:76px; margin:4px auto 20px; }
.match-found__countdown-ring { position:absolute; inset:0; border-radius:50%; background:conic-gradient(var(--gold) calc(var(--countdown-progress) * 1turn),rgb(255 255 255 / 12%) 0); -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 6px),#000 calc(100% - 5px)); mask:radial-gradient(farthest-side,transparent calc(100% - 6px),#000 calc(100% - 5px)); filter:drop-shadow(0 0 10px rgb(246 215 122 / 42%)); }
.match-found__countdown-clock .match-found__countdown { position:relative; margin:0; font-size:20px; font-weight:700; font-variant-numeric:tabular-nums; }
.match-found__sides { position:relative; z-index:1; display:grid; grid-template-columns:minmax(0,1fr) 110px minmax(0,1fr); gap:22px; align-items:center; }
.match-found__side { position:relative; overflow:hidden; min-height:310px; color:#4ec8e0; border:1px solid #2586a4; border-radius:16px; padding:20px 16px 18px; background:radial-gradient(circle at 50% 25%,#20789566,transparent 70%),linear-gradient(160deg,rgb(14 54 75 / 76%),rgb(7 20 36 / 82%)); box-shadow:inset 0 0 30px rgb(78 200 224 / 7%),0 10px 30px rgb(0 0 0 / 20%); animation:fleet-enter .7s cubic-bezier(.16,.8,.25,1) both; }
.match-found__side--rival { color:#edb765; border-color:#967449; background:radial-gradient(circle at 50% 25%,#91734155,transparent 70%),linear-gradient(160deg,rgb(57 43 27 / 75%),rgb(20 17 25 / 82%)); animation-name:rival-enter; animation-delay:.08s; }
.match-found__side-sheen { position:absolute; top:0; bottom:0; left:-24%; width:20%; background:linear-gradient(90deg,transparent,rgb(255 255 255 / 28%),transparent); transform:skewX(-18deg); animation:match-found-card-sheen 1.8s .55s ease-out both; pointer-events:none; }
.match-found__designation { position:relative; margin:0 0 14px; font-size:11px; font-weight:700; letter-spacing:.16em; }
.match-found__avatar { position:relative; z-index:1; filter:drop-shadow(0 0 18px color-mix(in srgb,currentColor 44%,transparent)); animation:match-found-avatar-in .72s .16s cubic-bezier(.16,.8,.25,1) both; }
.match-found__identity { position:relative; z-index:1; display:flex; align-items:center; flex-direction:column; gap:8px; margin-top:12px; }
.match-found__identity h3 { font-size:27px; line-height:1.15; margin:0; color:#e9f7ff; text-shadow:0 0 14px rgb(78 200 224 / 28%); }
.match-found__side--rival .match-found__identity h3 { text-shadow:0 0 14px rgb(237 183 101 / 26%); }
.match-found__chips { display:flex; flex-wrap:wrap; justify-content:center; gap:6px; margin-top:2px; }
.match-found__chips span { min-height:24px; padding:4px 9px; border:1px solid color-mix(in srgb,currentColor 44%,transparent); border-radius:999px; background:rgb(4 13 25 / 42%); color:#c9e9f2; font-size:11px; line-height:1.2; }
.match-found__side--rival .match-found__chips span { color:#f6d7a0; }
.match-found__versus-wrap { position:relative; display:grid; place-items:center; width:110px; height:110px; }
.match-found__versus-pulse { position:absolute; inset:0; border:1px solid rgb(117 213 241 / 45%); border-radius:50%; box-shadow:0 0 30px rgb(78 200 224 / 30%); animation:versus-pulse 1.8s ease-out infinite; }
.match-found__versus { position:relative; display:grid; place-items:center; width:88px; height:88px; border:3px double #397591; border-radius:50%; color:var(--gold); font-size:29px; font-weight:800; background:rgb(5 15 29 / 82%); box-shadow:0 0 35px #4ec8e066,inset 0 0 18px rgb(78 200 224 / 12%); animation:versus-lock .8s .22s cubic-bezier(.16,.8,.25,1) both; }
.match-found__progress { position:relative; z-index:1; height:8px; border:1px solid #366781; border-radius:20px; margin:26px auto 12px; width:75%; overflow:hidden; background:rgb(5 15 27 / 60%); }
.match-found__progress i { display:block; height:100%; background:linear-gradient(90deg,#357bdb,#4ec8e0,#ffe3a0); box-shadow:0 0 12px rgb(78 200 224 / 70%); transition:none; }
.match-found__skip { position:relative; z-index:1; padding:8px 20px; border:1px solid #366781; background:rgb(9 25 42 / 72%); color:#b9cfdf; border-radius:20px; cursor:pointer; transition:transform .2s ease,border-color .2s ease,color .2s ease; }
.match-found__skip:hover { transform:translateY(-1px); border-color:var(--gold); color:#fff2c5; }
@keyframes match-found-sweep { to { transform:translateX(120%); } }
@keyframes match-found-shock { 0% { opacity:0; transform:scale(.22); } 24% { opacity:.8; } 100% { opacity:0; transform:scale(1); } }
@keyframes match-found-title-in { from { opacity:0; transform:translateY(12px) scale(.96); } to { opacity:1; transform:none; } }
@keyframes match-found-card-sheen { 0% { left:-24%; opacity:0; } 20% { opacity:1; } 100% { left:130%; opacity:0; } }
@keyframes match-found-avatar-in { from { opacity:0; transform:scale(.72); } to { opacity:1; transform:none; } }
@keyframes fleet-enter { from { opacity:0; transform:translateX(-48px) scale(.96); } to { opacity:1; transform:none; } }
@keyframes rival-enter { from { opacity:0; transform:translateX(48px) scale(.96); } to { opacity:1; transform:none; } }
@keyframes versus-lock { from { opacity:0; transform:scale(1.5) rotate(-12deg); } to { opacity:1; transform:none; } }
@keyframes versus-pulse { 0% { opacity:.75; transform:scale(.82); } 75%,100% { opacity:0; transform:scale(1.3); } }
@media(max-width:700px) { .match-found__panel { padding:26px 14px 22px; }.match-found__sides { grid-template-columns:minmax(0,1fr) 48px minmax(0,1fr); gap:6px; }.match-found__versus-wrap { width:48px; height:48px; }.match-found__versus { width:46px; height:46px; font-size:16px; }.match-found__side { min-height:250px; padding:14px 6px 12px; }.match-found__avatar { --avatar-size:84px; }.match-found__identity h3 { font-size:18px; }.match-found__chips span { padding:3px 6px; font-size:9px; }.match-found__designation { font-size:9px; letter-spacing:.08em; }.match-found__progress { width:88%; } }
@media(prefers-reduced-motion:reduce) { .match-found__panel::after,.match-found__shock i,.match-found__title,.match-found__side,.match-found__side-sheen,.match-found__avatar,.match-found__versus,.match-found__versus-pulse { animation:none; }.match-found__progress i { transition:none; } }
</style>
