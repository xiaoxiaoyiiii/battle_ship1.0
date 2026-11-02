<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useGameStore } from '../stores/game'
import { banSelectionError } from '../stores/cardBans'
import { useUiStore } from '../stores/ui'
import { emitMatchEvent, matchSocket } from '../realtime/match'
import BanCardPicker from './BanCardPicker.vue'
const emit = defineEmits<{ (event: 'continue'): void; (event: 'leave'): void }>()
const game = useGameStore()
const ui = useUiStore()
const bans = computed(() => game.state.card_bans)
const selection = ref<string[]>([])
const error = ref('')
const saving = ref(false)
const confirming = ref(false)
const confirmSent = ref(false)
const clock = ref(Date.now())
let ticker: ReturnType<typeof setInterval> | null = null
let draftVersion = 0
let savedVersion = 0
let roomEpoch = 0
let saveTask: Promise<boolean> | null = null
const deadline = computed(() => bans.value?.phase === 'countdown' ? bans.value.countdown_deadline : bans.value?.selection_deadline)
const seconds = computed(() => Math.max(0, Math.ceil(((deadline.value || clock.value) - clock.value) / 1000)))
const editable = computed(() => Boolean(bans.value?.phase === 'selecting' && !bans.value.confirmed && !confirming.value && !confirmSent.value && seconds.value > 0))
const revealedLists = computed(() => Object.entries(bans.value?.revealed || {}).map(([id, names]) => ({ id, names, own: id === game.state.player_id || id === game.state.player_seat })))

watch(() => game.state.room_id, () => {
  roomEpoch += 1; draftVersion = 0; savedVersion = 0; saveTask = null
  saving.value = false; confirming.value = false; confirmSent.value = false; error.value = ''
  selection.value = [...(bans.value?.own_selection || [])]
}, { immediate: true })
watch(bans, value => {
  if (!value) return
  if (value.confirmed || value.phase !== 'selecting' || (!saving.value && draftVersion === savedVersion)) selection.value = [...value.own_selection]
  if (value.confirmed) confirmSent.value = true
}, { immediate: true, deep: true })
onMounted(() => { ticker = setInterval(() => { clock.value = Date.now() }, 200) })
onBeforeUnmount(() => { if (ticker) clearInterval(ticker); roomEpoch += 1 })

function message(text: string): void {
  error.value = text
  ui.notify({ code: 'card-ban-selection', tone: 'warning', message: text })
}
async function send(selectionValue: string[], confirm: boolean): Promise<boolean> {
  if (!bans.value || bans.value.phase !== 'selecting' || bans.value.confirmed || !bans.value.selection_deadline || bans.value.selection_deadline <= Date.now()) {
    message('时间已到，等待服务器同步 Ban 结果。')
    return false
  }
  const socket = matchSocket()
  if (!socket?.socket.connected) { message('连接已断开，请等待重连后再试。选择已保留。'); return false }
  const epoch = roomEpoch
  try {
    const ack = await emitMatchEvent(socket, 'place_ships', { room_id: game.state.room_id, player_id: game.state.player_id, ban_selection: [...selectionValue], ban_confirm: confirm })
    if (epoch !== roomEpoch) return false
    if (ack.status !== 'success') { message(ack.message || '保存 Ban 选择失败，请重试。'); return false }
    return true
  } catch (cause) {
    if (epoch === roomEpoch) message(cause instanceof Error ? cause.message : '请求未送达，选择已保留，请重试。')
    return false
  }
}
function saveDraft(): Promise<boolean> {
  if (saveTask) return saveTask
  const epoch = roomEpoch
  saving.value = true
  saveTask = (async () => {
    while (savedVersion < draftVersion && epoch === roomEpoch) {
      const version = draftVersion
      if (!await send(selection.value, false)) return false
      savedVersion = version
    }
    return epoch === roomEpoch
  })().finally(() => { if (epoch === roomEpoch) { saving.value = false; saveTask = null } })
  return saveTask
}
function changeSelection(value: string[]): void {
  if (!editable.value || !bans.value || !bans.value.selection_deadline || bans.value.selection_deadline <= Date.now()) return
  const problem = banSelectionError(value, bans.value.pool, bans.value.quota)
  if (problem) { message(problem); return }
  selection.value = [...value]; draftVersion += 1; error.value = ''
  void saveDraft()
}
async function confirm(): Promise<void> {
  if (!editable.value || !bans.value || !bans.value.selection_deadline || bans.value.selection_deadline <= Date.now()) return
  if (selection.value.length !== bans.value.quota) { message('请先选满 ' + bans.value.quota + ' 张卡，再确认 Ban。'); return }
  const problem = banSelectionError(selection.value, bans.value.pool, bans.value.quota)
  if (problem) { message(problem); return }
  confirming.value = true; error.value = ''
  const epoch = roomEpoch
  try {
    if (saveTask && !await saveTask) return
    if (draftVersion > savedVersion && !await saveDraft()) return
    if (!bans.value || bans.value.phase !== 'selecting' || bans.value.confirmed || !bans.value.selection_deadline || bans.value.selection_deadline <= Date.now()) return
    if (await send(selection.value, true)) confirmSent.value = true
  } finally { if (epoch === roomEpoch) confirming.value = false }
}
</script>
<template>
  <section v-if="bans" class="ban-stage" data-testid="ban-stage" :data-phase="bans.phase" aria-labelledby="ban-stage-title">
    <header class="ban-stage__head"><div><p class="ban-stage__eyebrow">{{ bans.ranked ? '排位对战' : '自定义对战' }} · 开局 Ban</p><h2 id="ban-stage-title">{{ bans.phase === 'countdown' ? '匹配成功' : bans.phase === 'selecting' ? '双方暗 Ban' : '双方 Ban 已公开' }}</h2></div><strong v-if="bans.phase !== 'revealed'" class="ban-stage__timer" data-testid="ban-countdown" aria-live="off">{{ seconds }}<small>秒</small></strong></header>
    <template v-if="bans.phase === 'countdown'">
      <p>{{ game.state.player_name || '你' }} <span aria-hidden="true">VS</span> {{ game.state.opponent_name || '对手' }}</p>
      <p data-testid="ban-countdown-note">{{ bans.quota ? '倒计时后进入 20 秒暗 Ban，每人可选 ' + bans.quota + ' 张。' : '本局双方名额均为 0，倒计时后直接布船。' }}</p>
      <p v-if="!seconds" role="status">倒计时结束，等待服务器同步下一阶段…</p>
    </template>
    <template v-else-if="bans.phase === 'selecting'">
      <p>每人 {{ bans.quota }} 张，双方确认后同时亮牌。跨档名额取高，空位需补选。</p>
      <p class="ban-stage__opponent" data-testid="ban-opponent-status">对手{{ bans.opponent_confirmed ? '已确认' : '尚未确认' }} · 亮牌前仅自己可见所选卡牌</p>
      <div data-testid="ban-selection"><BanCardPicker :pool="bans.pool" :selection="selection" :quota="bans.quota" :disabled="!editable" @change="changeSelection" /></div>
      <p v-if="bans.confirmed || confirmSent" role="status" data-testid="ban-confirmed">你已确认，等待双方亮牌。选择已冻结。</p>
      <p v-else-if="!seconds" role="status" data-testid="ban-authority-wait">时间已到，等待服务器补位并同步结果…</p>
      <p v-else class="ban-stage__hint">请选满后确认；超时按「硫磺火焰 → 绝处逢生」补空，跳过已选，剩余空位保留。</p>
      <p v-if="saving" role="status" data-testid="ban-saving">正在保存选择…</p>
      <p v-if="error" role="alert" data-testid="ban-error">{{ error }}</p>
      <button v-if="!bans.confirmed && !confirmSent" type="button" class="button" data-testid="ban-confirm" :disabled="!editable" @click="confirm">{{ confirming ? '正在确认…' : '确认 Ban（' + selection.length + '/' + bans.quota + '）' }}</button>
    </template>
    <template v-else>
      <div class="ban-stage__revealed" data-testid="ban-revealed"><section v-for="list in revealedLists" :key="list.id"><h3>{{ list.own ? '你的 Ban' : '对手的 Ban' }}</h3><ul v-if="list.names.length"><li v-for="name in list.names" :key="name">{{ name }}</li></ul><p v-else>未 Ban 卡牌</p></section></div>
      <p>本局共享牌堆已移除：{{ bans.banned_names.join('、') || '无' }}。双方同 Ban 不顺延。</p>
      <p v-if="bans.ranked" class="ban-stage__hint">从现在起，整个布船阶段离开或掉线均按逃跑判负扣分；对手不获得收益。</p>
      <button type="button" class="button" data-testid="ban-continue" @click="emit('continue')">{{ game.state.mutations?.confirmation_required ? '继续确认本局突变' : '继续布船' }}</button>
    </template>
    <button type="button" class="button button--ghost" data-testid="ban-leave" @click="emit('leave')">离开房间</button>
  </section>
</template>
<style scoped>
.ban-stage { width: min(720px,100%); margin: 0 auto; padding: 18px; box-sizing: border-box; display: grid; gap: 12px; border: 1px solid var(--border-strong); border-radius: 12px; background: var(--surface-chamber); box-shadow: var(--shadow-panel); }
.ban-stage :deep(.ban-picker__grid) { max-height: min(32dvh,260px); }
.ban-stage__head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.ban-stage h2 { margin: 5px 0 0; color: var(--gold-strong); font-size: 24px; }
.ban-stage p { margin: 0; color: var(--text-muted); font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.ban-stage .ban-stage__eyebrow { color: var(--gold-strong); font-size: 11px; letter-spacing: .1em; }
.ban-stage__timer { color: var(--gold-strong); font-size: 38px; font-variant-numeric: tabular-nums; }.ban-stage__timer small { font-size: 12px; margin-left: 4px; }
.ban-stage__opponent { padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; }
.ban-stage .ban-stage__hint { color: var(--gold-strong); font-size: 12px; }
.ban-stage__revealed { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
.ban-stage__revealed section { min-width: 0; padding: 12px; background: var(--surface-deck); border: 1px solid var(--border); border-radius: 8px; }
.ban-stage h3 { margin: 0 0 10px; font-size: 14px; color: var(--text); }.ban-stage ul { margin: 0; padding-left: 20px; color: var(--gold-strong); font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
@media(max-width:600px) { .ban-stage { padding: 15px; gap: 12px; margin: 0 auto; }.ban-stage h2 { font-size: 21px; }.ban-stage :deep(.ban-picker__grid) { max-height: min(34dvh,280px); } }
</style>
