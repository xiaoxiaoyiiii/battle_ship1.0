<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { cardArtUrl } from '../../cards/cardArt'
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
const choiceStep = computed(() => kind.value !== 'taoyuan_choice' ? (kind.value === 'bury_choice' ? '选择需要埋葬的卡牌' : '选择要取得的卡牌') : chosen.value < 0 ? '第一步：选择一张卡牌给自己' : other.value < 0 && cards.value.length > 1 ? '第二步：选择一张卡牌给对方' : '确认双方取得的卡牌')
function chooseCard(index: number) {
  if (busy.value) return
  if (kind.value !== 'taoyuan_choice') { chosen.value = index; return }
  if (chosen.value < 0) chosen.value = index
  else if (index !== chosen.value) other.value = index
}
function resetChoice() { chosen.value = -1; other.value = -1 }
async function submit(cancel = false): Promise<void> {
  if (busy.value || (!cancel && !ready.value)) return
  busy.value=true;error.value=''
  try {
    const identity = { room_id:game.state.room_id, player_id:game.state.player_id }
    const card = cards.value[chosen.value]
    const target = kind.value === 'lingqi_choice' ? { target_ships:quantity.value }
      : kind.value === 'taoyuan_choice' ? { caster_choice:chosen.value, opponent_choice:other.value >= 0 ? other.value : null }
      : kind.value === 'bury_choice' ? { source:card?.source || 'deck', source_index:card?.index, card_index:chosen.value }
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
  <AppOverlay draggable v-if="visible" id="magic-choice-panel" :priority="170" :close-on-backdrop="false" labelledby="magic-choice-title">
    <section class="magic-choice battle-prompt">
      <header class="battle-prompt__head" data-drag-handle><div><p class="battle-prompt__context">卡牌效果</p><h2 id="magic-choice-title">{{ names[kind] }} · 选择效果</h2><span class="battle-prompt__drag-note">拖动标题可移动</span></div><img v-if="cardArtUrl(names[kind] || '')" class="battle-prompt__card-art" :src="cardArtUrl(names[kind] || '')!" alt="" draggable="false" /></header>
      <template v-if="numeric">
        <p>{{ kind === 'shenji_declare' ? '宣言对方回合结束时，你的战舰将减少多少艘（0–6）。' : '选择双方调整后的船数，随后各自在原船位重新部署。' }}</p>
        <label>选择数量 <input v-model.number="quantity" data-testid="magic-choice-number" type="number" :min="minimum" :max="maximum" step="1" :disabled="busy" /></label>
        <p v-if="maximum < minimum" role="alert">尚未收到可选数量，请重新同步。</p>
      </template>
      <template v-else>
        <p class="magic-choice__step" aria-live="polite">{{ choiceStep }}</p>
        <p class="magic-choice__help">{{ kind === 'taoyuan_choice' ? '先为自己选一张，再为对方选另一张；剩余卡牌放回牌堆。' : kind === 'bury_choice' ? '查看卡牌效果和来源，再确认要埋葬的卡牌。' : '查看卡牌效果，再确认要取得的卡牌。' }}</p>
        <div class="magic-choice__cards">
          <button v-for="(card,index) in cards" :key="index" class="magic-choice__card" :class="{ 'is-mine': chosen === index, 'is-other': other === index }" type="button" :data-testid="'magic-choice-card-' + index" :aria-pressed="chosen === index || other === index" :disabled="busy" @click="chooseCard(index)">
            <span v-if="kind === 'taoyuan_choice' && (chosen === index || other === index)" class="magic-choice__recipient">{{ chosen === index ? '给自己' : '给对方' }}</span>
            <img v-if="cardArtUrl(String(card.name))" :src="cardArtUrl(String(card.name))!" alt="" />
            <b>{{ card.name }}</b>
            <small>{{ card.type || '魔法卡' }} · 速阶 {{ card.speed ?? '—' }}<template v-if="kind === 'bury_choice'"> · {{ card.source === 'opponent_hand' ? '对方手牌' : '牌堆' }}</template></small>
            <span class="magic-choice__description" tabindex="0" :aria-label="String(card.name) + '完整效果'" @click.stop @keydown.stop>{{ card.description || '暂无效果说明' }}</span>
          </button>
        </div>
        <div v-if="kind === 'taoyuan_choice'" class="magic-choice__assignment" data-testid="magic-choice-other" aria-live="polite">
          <span>自己：{{ chosen < 0 ? '待选择' : cards[chosen]?.name }}</span>
          <span>对方：{{ cards.length < 2 ? '无可分配卡牌' : other < 0 ? '待选择' : cards[other]?.name }}</span>
          <button type="button" class="button button--ghost" :disabled="busy || chosen < 0" @click="resetChoice">重新选择</button>
        </div>
      </template>
      <p v-if="error" role="alert" data-testid="magic-choice-error">{{ error }}</p>
      <p class="battle-prompt__status" :class="{ 'is-ready': ready }" role="status">{{ ready ? '选择已就绪，请确认。' : numeric ? '请在范围内选择数量。' : choiceStep }}</p>
      <footer><button class="button button--primary" type="button" data-testid="magic-choice-confirm" :disabled="busy || !ready" @click="submit()">确认选择</button><button v-if="kind !== 'shenji_declare'" class="button button--ghost" type="button" data-testid="magic-choice-cancel" :disabled="busy" @click="submit(true)">{{ kind === 'taoyuan_choice' ? '取消 · 放回牌堆' : '取消本次选择' }}</button></footer>
    </section>
  </AppOverlay>
</template>

<style src="./battle-prompt.css"></style>
<style scoped>
.magic-choice { padding:26px; max-height:calc(100dvh - 24px); overflow-y:auto; }
.magic-choice p { font-size:16px; line-height:1.7; }
.magic-choice label { display:flex; align-items:center; gap:16px; margin:18px 0; font-size:17px; font-weight:700; }
.magic-choice input { padding:12px; width:110px; min-height:48px; color:var(--prompt-cyan); background:var(--prompt-deck); border:1px solid var(--prompt-line); border-radius:8px; font:inherit; font-size:22px; font-variant-numeric:tabular-nums; }
.magic-choice footer { display:flex; gap:12px; margin-top:18px; }
.magic-choice footer button { flex:1; }
.magic-choice__cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); grid-auto-rows:minmax(360px,1fr); gap:14px; max-height:56dvh; overflow:auto; padding:4px; align-items:stretch; }
.magic-choice__card { position:relative; display:flex; flex-direction:column; min-width:0; min-height:360px; max-height:430px; overflow:hidden; text-align:left; padding:14px; color:var(--prompt-text); background:var(--prompt-deck); border:1px solid var(--prompt-line); border-radius:10px; cursor:pointer; }
.magic-choice__card:hover,.magic-choice__card:focus-visible { border-color:var(--prompt-cyan); outline:2px solid rgb(116 215 233 / 18%); outline-offset:1px; }
.magic-choice__card img { display:block; flex:0 0 178px; width:124px; height:178px; object-fit:contain; margin:0 auto 12px; filter:drop-shadow(0 5px 9px #0006); }
.magic-choice__card b { font-size:18px; }.magic-choice__card small { margin-top:7px; font-size:14px; color:var(--prompt-muted); }
.magic-choice__card span { display:block; margin-top:8px; font-size:15px; line-height:1.75; }
.magic-choice__description { flex:1; min-height:0; overflow-y:auto; overscroll-behavior:contain; scrollbar-width:thin; }
.magic-choice__description:focus-visible { outline:2px solid var(--prompt-cyan); outline-offset:2px; }
.magic-choice__step { color:var(--prompt-cyan); font-weight:700; }.magic-choice__help { color:var(--prompt-muted); }
.magic-choice__card.is-mine { border-color:var(--prompt-cyan); background:rgb(116 215 233 / 8%); box-shadow:inset 0 0 0 1px rgb(116 215 233 / 18%); }
.magic-choice__card.is-other { border-color:var(--prompt-gold); background:rgb(224 190 112 / 8%); }
.magic-choice__card .magic-choice__recipient { position:absolute; top:10px; left:10px; margin:0; padding:5px 9px; border-radius:6px; background:#102231; color:var(--prompt-text); font-size:14px; font-weight:700; }
.magic-choice__assignment { display:flex; flex-wrap:wrap; gap:12px 20px; align-items:center; margin-top:18px; padding:14px; border:1px solid var(--prompt-line); border-radius:8px; font-size:16px; }
:global(.app-overlay__panel[data-testid='magic-choice-panel']) { width:min(1000px,calc(100vw - 24px)); }
@media(max-width:540px) { .magic-choice { padding:18px; }.magic-choice__cards { grid-template-columns:repeat(2,minmax(0,1fr)); grid-auto-rows:minmax(310px,1fr); gap:10px; max-height:47dvh; }.magic-choice__card { padding:10px; min-height:310px; max-height:360px; }.magic-choice__card img { flex-basis:136px; width:94px; height:136px; }.magic-choice__card b { font-size:16px; }.magic-choice__card small { font-size:13px; }.magic-choice__card span { font-size:15px; }.magic-choice footer { flex-wrap:wrap; } }
</style>
