<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppOverlay from './AppOverlay.vue'
import { useGameStore } from '../stores/game'
import { BOARD_SIZE } from '../screens/game/view'

const emit = defineEmits<{ (event: 'close'): void }>()
const game = useGameStore()
interface Action { id: string; label: string; group: string }
interface Ship { positions: number[][]; hits: number[][]; shield: boolean; invincible: boolean }
interface Seat { ships: Ship[]; magic_hand: string[]; remaining_ships: number }
interface Snapshot { current_phase: string; current_attacker: string; attacks_remaining: number; round: number; players: Record<string, Seat>; chain: unknown[] }
const actions = ref<Action[]>([])
const cards = ref<Array<{ name: string }>>([])
const allowed = ref(false)
const busy = ref(false)
const notice = ref('')
const error = ref('')
const tab = ref('cards')
const cardName = ref('')
const cardCount = ref(1)
const shotCount = ref(1)
const ships = ref(6)
const attacks = ref(6)
const phase = ref('preparation')
const rps = ref('rock')
const normalAction = ref('use_magic_card')
const params = ref('{}')
const snapshot = ref<Snapshot | null>(null)
const normalActions = computed(() => actions.value.filter(item => item.group === 'normal' || item.id === 'priority_response'))
const roomId = computed(() => game.state.room_id)
const seats = computed(() => Object.entries(snapshot.value?.players || {}))

onMounted(async () => {
  try {
    const response = await fetch('/api/admin/console')
    if (!response.ok) throw new Error('当前账号无管理员测试权限')
    const payload = await response.json()
    actions.value = payload.actions; cards.value = payload.cards; allowed.value = true
    cardName.value = cards.value[0]?.name || ''
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '控制台暂不可用' }
})

async function run(action: string, values: Record<string, unknown> = {}): Promise<void> {
  if (busy.value || !allowed.value) return
  if (!roomId.value) { error.value = '请先进入自己的对局，再使用测试操作。'; return }
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const response = await fetch('/api/admin/console', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ room_id: roomId.value, action, params: values }) })
    const payload = await response.json()
    if (!response.ok || payload.status === 'error') throw new Error(payload.message || payload.error?.message || '操作未执行')
    notice.value = payload.message || '操作已执行；本局为测试局，不计战绩与奖励。'
    if (payload.game_state) snapshot.value = payload.game_state
    if (action === 'reset') snapshot.value = null
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '请求失败' }
  finally { busy.value = false }
}

function runNormal(): void {
  try {
    const value = JSON.parse(params.value)
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('请填写 JSON 对象')
    void run(normalAction.value, value)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'JSON 格式不正确' }
}

function shipAt(seat: Seat, cell: number): Ship | undefined {
  return seat.ships.find(ship => ship.positions.some(([x, y]) => x === cell % BOARD_SIZE && y === Math.floor(cell / BOARD_SIZE)))
}
</script>

<template>
  <AppOverlay id="admin-console" :priority="300" labelledby="admin-console-title" @close="emit('close')">
    <section class="console" data-testid="admin-console-content">
      <header><div><span class="console__eyebrow">仅管理员 · 测试工具</span><h2 id="admin-console-title">对局控制台 <kbd>F8</kbd></h2></div><button class="button button--ghost" aria-label="关闭管理员控制台" @click="emit('close')">关闭</button></header>
      <p class="console__warning">仅可操作本人参与的房间。查看隐藏信息或执行任意测试动作后，本局不计战绩、排位、任务及奖励。</p>
      <p class="console__room">当前房间：{{ roomId || '尚未进入对局' }}</p>
      <nav class="console__tabs" aria-label="控制台分类"><button v-for="item in [['cards','卡牌'],['battle','对局'],['intel','局面情报'],['advanced','全部局内动作']]" :key="item[0]" class="button button--ghost" :aria-pressed="tab === item[0]" @click="tab = item[0]">{{ item[1] }}</button></nav>
      <p v-if="error" class="console__error" role="alert" data-testid="console-error">{{ error }}</p><p v-if="notice" role="status" data-testid="console-result">{{ notice }}</p>
      <fieldset :disabled="busy || !allowed">
        <div v-if="tab === 'cards'" class="console__body">
          <h3>准备手牌</h3><label>指定卡牌<input v-model="cardName" list="console-card-list" data-testid="console-card-name" /><datalist id="console-card-list"><option v-for="card in cards" :key="card.name" :value="card.name" /></datalist></label>
          <label>张数<input v-model.number="cardCount" type="number" min="1" max="50" /></label>
          <div class="console__buttons"><button class="button button--primary" data-testid="console-draw" @click="run('draw_card', {card_name: cardName, count: cardCount})">获得指定牌</button><button class="button" @click="run('all_cards')">获得全部 {{ cards.length }} 种牌</button><button class="button button--ghost" @click="run('clear_effects')">清空效果与双方手牌</button><button class="button button--ghost" @click="run('chain_demo')">演示多区域连锁</button></div>
        </div>
        <div v-else-if="tab === 'battle'" class="console__body">
          <h3>胜负与攻击</h3><div class="console__buttons"><button class="button button--primary" data-testid="console-win" @click="run('win')">判自己胜利</button><button class="button" @click="run('lose')">判自己失败</button></div>
          <div class="console__grid"><label>自动攻击次数<input v-model.number="shotCount" type="number" min="1" max="100" /><button class="button" @click="run('auto_attack', {count:shotCount})">按真实规则自动攻击</button></label><label>剩余攻击额度<input v-model.number="attacks" type="number" min="0" max="100" /><button class="button" @click="run('set_attacks', {count:attacks})">设置攻击次数</button></label></div>
          <h3>棋盘与阶段</h3><label>舰船数量<input v-model.number="ships" type="number" min="1" max="6" /></label><div class="console__buttons"><button class="button" @click="run('own_ships', {count:ships})">重建己方舰队</button><button class="button" @click="run('opponent_ships', {count:ships})">重建对方舰队</button></div>
          <label>阶段<select v-model="phase"><option value="preparation">准备阶段</option><option value="battle">战斗阶段</option><option value="end">结束阶段</option></select></label><div class="console__buttons"><button class="button" @click="run('set_phase', {phase})">设置阶段</button><button class="button" @click="run('next_phase')">推进到下一阶段</button><button class="button button--ghost" @click="run('reset')">重置对局至布船</button></div>
          <label>AI 猜拳<select v-model="rps"><option value="rock">石头</option><option value="paper">布</option><option value="scissors">剪刀</option></select></label><button class="button" @click="run('ai_rps', {choice:rps})">指定 AI 下一次出拳</button>
        </div>
        <div v-else-if="tab === 'intel'" class="console__body">
          <button class="button button--primary" data-testid="console-inspect" @click="run('inspect')">读取 / 刷新双方船位与手牌</button>
          <template v-if="snapshot"><p>第 {{ snapshot.round }} 回合 · {{ snapshot.current_phase }} · 攻击 {{ snapshot.attacks_remaining }} 次</p><div class="console__grid"><article v-for="[id, seat] in seats" :key="id"><h3>{{ id === game.state.player_id ? '自己' : '对手' }} · 存活 {{ seat.remaining_ships }} 舰</h3><div class="console__board" role="img" :aria-label="`${id} 的完整船位`"><span v-for="cell in BOARD_SIZE * BOARD_SIZE" :key="cell" :class="{'is-ship':shipAt(seat,cell-1)}" :title="`${String.fromCharCode(65+(cell-1)%BOARD_SIZE)}${Math.floor((cell-1)/BOARD_SIZE)+1}`">{{ shipAt(seat,cell-1) ? '◆' : '·' }}</span></div><p class="console__hand">{{ seat.magic_hand.join('、') || '无手牌' }}</p></article></div><details><summary>完整权威局面 JSON</summary><pre>{{ JSON.stringify(snapshot, null, 2) }}</pre></details></template>
        </div>
        <div v-else class="console__body"><h3>全部正常局内行为</h3><p>从真实玩法入口执行，遵守卡牌、阶段及目标校验。房间和座位由服务器确定，无需填写。</p><label>行为<select v-model="normalAction"><option v-for="action in normalActions" :key="action.id" :value="action.id">{{ action.label }} · {{ action.id }}</option></select></label><label>行为参数 JSON<textarea v-model="params" rows="7" spellcheck="false" data-testid="console-params" /></label><p>例如炮击：{"x":0,"y":0}；出牌：{"card":{"name":"轰炸"},"targets":{"x":0,"y":0}}。复杂选牌、数字、重摆、连锁响应使用对应动作及其原始参数。</p><button class="button button--primary" @click="runNormal">执行所选行为</button></div>
      </fieldset>
    </section>
  </AppOverlay>
</template>

<style scoped>
.console{width:100%;box-sizing:border-box;padding:24px;color:var(--text-primary)}.console header{display:flex;justify-content:space-between;align-items:center;gap:12px}.console h2{margin:7px 0}.console h3{margin:5px 0}.console__eyebrow{font-size:12px;letter-spacing:.08em;color:var(--accent)}.console kbd{font:12px monospace;border:1px solid var(--border-subtle);padding:3px 6px;border-radius:4px}.console__warning{padding:12px;border:1px solid var(--border-subtle);border-left:3px solid var(--role-warning);line-height:1.7}.console__room,.console p{font-size:13px;line-height:1.7;overflow-wrap:anywhere}.console__tabs,.console__buttons{display:flex;flex-wrap:wrap;gap:8px}.console__tabs [aria-pressed=true]{background:var(--surface-raised);border-color:var(--accent)}.console fieldset{border:0;min-width:0;padding:0;margin:18px 0 0}.console__body{display:grid;gap:14px}.console label{display:grid;gap:7px;font-size:13px}.console input,.console select,.console textarea{box-sizing:border-box;min-width:0;width:100%;padding:10px;border:1px solid var(--border-subtle);background:var(--surface-sea);color:var(--text-primary);border-radius:6px;font:inherit}.console__grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.console__board{display:grid;grid-template-columns:repeat(6,1fr);gap:2px;max-width:300px;margin:12px 0}.console__board span{aspect-ratio:1;display:grid;place-items:center;background:var(--surface-sea);font-size:12px}.console__board .is-ship{background:var(--accent);color:var(--surface-deep)}.console pre{max-height:240px;overflow:auto;font-size:11px;white-space:pre-wrap;overflow-wrap:anywhere}.console__error{color:var(--role-danger)}.console button{white-space:normal}.console__hand{overflow-wrap:anywhere}@media(max-width:600px){.console{padding:16px}.console__grid{grid-template-columns:1fr}}
</style>
