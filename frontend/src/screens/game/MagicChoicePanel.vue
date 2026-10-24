<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppOverlay from '../../components/AppOverlay.vue'
import { useGameStore } from '../../stores/game'
import { refreshMagicState, sendBattleEvent } from '../../realtime/battle'

const game = useGameStore()
const temp = computed(() => game.state.magic_temp)
const kind = computed(() => String(temp.value?.type || (temp.value?.pending_shenji ? 'shenji_declare' : '')))
const names: Record<string, string> = { lingqi_choice:'灵气复苏', shenji_declare:'神机妙算', taoyuan_choice:'桃园结义', bury_choice:'明智埋葬', wangyang_choice:'亡羊补牢' }
const visible = computed(() => Boolean(names[kind.value]) && !game.state.pending_placement && !game.state.dice_discard_pending)
const numeric = computed(() => ['lingqi_choice', 'shenji_declare'].includes(kind.value))
const minimum = computed(() => kind.value === 'shenji_declare' ? 0 : 1)
const maximum = computed(() => kind.value === 'shenji_declare' ? 6 : Number(temp.value?.max_ships) || 0)
const quantity = ref(1), chosen = ref(-1), other = ref(-1), busy = ref(false), error = ref('')
const cards = computed<Record<string, unknown>[]>(() => {
  const values = temp.value?.candidates ?? temp.value?.cards
  return Array.isArray(values) ? values.filter((c): c is Record<string, unknown> => !!c && typeof c === 'object') : []
})
watch(() => temp.value, () => { quantity.value=minimum.value; chosen.value=-1; other.value=-1; error.value='' })
const ready = computed(() => numeric.value
  ? Number.isInteger(quantity.value) && quantity.value >= minimum.value && quantity.value <= maximum.value
  : chosen.value >= 0 && chosen.value < cards.value.length && (kind.value !== 'taoyuan_choice' || cards.value.length < 2 || (other.value >= 0 && other.value !== chosen.value)))
async function submit(cancel = false): Promise<void> {
  if (busy.value || (!cancel && !ready.value)) return
  busy.value=true;error.value=''
  try {
    const identity = { room_id:game.state.room_id, player_id:game.state.player_id }
    const card = cards.value[chosen.value]
    const target = kind.value === 'lingqi_choice' ? { target_ships:quantity.value }
      : kind.value === 'taoyuan_choice' ? { caster_choice:chosen.value, opponent_choice:other.value }
      : kind.value === 'bury_choice' ? { source:card?.source, source_index:card?.index }
      : { chosen_index:chosen.value }
    const ack = await sendBattleEvent(cancel ? 'cancel_magic_selection' : kind.value === 'shenji_declare' ? 'confirm_shenji_declare' : 'confirm_magic_target', {
      ...identity, ...(cancel ? {} : kind.value === 'shenji_declare' ? { prediction:quantity.value } : { temp_data_id:kind.value, target_data:target }),
    })
    if (ack.status !== 'success') { error.value=ack.message || '选择未被接受，请重试。';return }
    await refreshMagicState()
  } catch { error.value='连接不稳定，当前选择仍保留，请重试。' }
  finally { busy.value=false }
}
</script>

<template>
  <AppOverlay v-if="visible" id="magic-choice-panel" :priority="170" :close-on-backdrop="false" labelledby="magic-choice-title">
    <section class="magic-choice">
      <h2 id="magic-choice-title">{{ names[kind] }} · 选择效果</h2>
      <template v-if="numeric">
        <p>{{ kind === 'shenji_declare' ? '宣言对方回合结束时，你的战舰将减少多少艘（0–6）。' : '选择双方调整后的船数，随后各自在原船位重新部署。' }}</p>
        <label>选择数量 <input v-model.number="quantity" data-testid="magic-choice-number" type="number" :min="minimum" :max="maximum" step="1" :disabled="busy" /></label>
        <p v-if="maximum < minimum" role="alert">尚未收到可选数量，请重新同步。</p>
      </template>
      <template v-else>
        <p>选择{{ kind === 'taoyuan_choice' ? '自己取得的' : '需要处理的' }}卡牌。</p>
        <div class="magic-choice__cards">
          <button v-for="(card,index) in cards" :key="index" class="magic-choice__card" type="button" :data-testid="'magic-choice-card-' + index" :aria-pressed="chosen === index" :disabled="busy" @click="chosen=index">
            <b>{{ card.name }}</b><span>{{ card.description }}</span>
          </button>
        </div>
        <label v-if="kind === 'taoyuan_choice' && cards.length > 1">分给对方
          <select v-model.number="other" data-testid="magic-choice-other" :disabled="busy"><option :value="-1" disabled>请选择另一张</option><option v-for="(card,index) in cards" :key="index" :value="index" :disabled="index===chosen">{{ card.name }}</option></select>
        </label>
      </template>
      <p v-if="error" role="alert" data-testid="magic-choice-error">{{ error }}</p>
      <footer><button class="button" type="button" data-testid="magic-choice-confirm" :disabled="busy || !ready" @click="submit()">确认选择</button><button v-if="kind !== 'shenji_declare'" class="button button--ghost" type="button" data-testid="magic-choice-cancel" :disabled="busy" @click="submit(true)">取消本次选择</button></footer>
    </section>
  </AppOverlay>
</template>

<style scoped>
.magic-choice { padding:20px; }.magic-choice h2 { margin:0 0 16px; font-size:20px; }.magic-choice p { font-size:15px; line-height:1.7; }.magic-choice label { display:flex; align-items:center; gap:12px; margin:16px 0; }.magic-choice input,.magic-choice select { padding:10px; color:var(--text-primary); background:var(--surface); border:1px solid var(--border); border-radius:6px; min-width:80px; }.magic-choice footer { display:flex; gap:10px; margin-top:20px; }.magic-choice footer button { flex:1; min-height:42px; }.magic-choice__cards { display:grid; gap:8px; max-height:42dvh; overflow:auto; }.magic-choice__card { text-align:left; padding:12px; color:var(--text-primary); background:var(--surface); border:1px solid var(--border); border-radius:8px; }.magic-choice__card[aria-pressed='true'] { border-color:var(--accent); }.magic-choice__card span { display:block; margin-top:6px; font-size:14px; line-height:1.6; }:global(.app-overlay__panel[data-testid='magic-choice-panel']) { width:min(500px,calc(100vw - 24px)); max-height:calc(100dvh - 24px); }
</style>
