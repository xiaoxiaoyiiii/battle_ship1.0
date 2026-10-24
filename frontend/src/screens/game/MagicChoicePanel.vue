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
  <AppOverlay v-if="visible" id="magic-choice-panel" :priority="170" :close-on-backdrop="false" labelledby="magic-choice-title">
    <section class="magic-choice">
      <h2 id="magic-choice-title">{{ names[kind] }} · 选择效果</h2>
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
            <span>{{ card.description || '暂无效果说明' }}</span>
          </button>
        </div>
        <div v-if="kind === 'taoyuan_choice'" class="magic-choice__assignment" data-testid="magic-choice-other" aria-live="polite">
          <span>自己：{{ chosen < 0 ? '待选择' : cards[chosen]?.name }}</span>
          <span>对方：{{ cards.length < 2 ? '无可分配卡牌' : other < 0 ? '待选择' : cards[other]?.name }}</span>
          <button type="button" class="button button--ghost" :disabled="busy || chosen < 0" @click="resetChoice">重新选择</button>
        </div>
      </template>
      <p v-if="error" role="alert" data-testid="magic-choice-error">{{ error }}</p>
      <footer><button class="button" type="button" data-testid="magic-choice-confirm" :disabled="busy || !ready" @click="submit()">确认选择</button><button v-if="kind !== 'shenji_declare'" class="button button--ghost" type="button" data-testid="magic-choice-cancel" :disabled="busy" @click="submit(true)">{{ kind === 'taoyuan_choice' ? '取消 · 放回牌堆' : '取消本次选择' }}</button></footer>
    </section>
  </AppOverlay>
</template>

<style scoped>
.magic-choice { padding:20px; }
.magic-choice h2 { margin:0 0 16px; font-size:20px; }
.magic-choice p { font-size:15px; line-height:1.7; }
.magic-choice label { display:flex; align-items:center; gap:12px; margin:16px 0; }
.magic-choice input,.magic-choice select { padding:10px; color:var(--text-primary); background:var(--surface); border:1px solid var(--border); border-radius:6px; min-width:80px; }
.magic-choice footer { display:flex; gap:10px; margin-top:20px; }
.magic-choice footer button { flex:1; min-height:42px; }
.magic-choice__cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); grid-auto-rows:minmax(320px,1fr); gap:14px; max-height:58dvh; overflow:auto; padding:4px; align-items:stretch; }
.magic-choice__card { position:relative; display:flex; flex-direction:column; min-height:320px; max-height:380px; overflow:hidden; text-align:left; padding:12px; color:var(--text-primary); background:var(--surface); border:1px solid var(--border); border-radius:8px; transition:background 150ms ease,border-color 150ms ease,box-shadow 150ms ease,transform 150ms ease; }
.magic-choice__card:hover,.magic-choice__card:focus-visible { z-index:2; border-color:var(--accent); background:color-mix(in srgb,var(--accent) 12%,var(--surface)); box-shadow:0 10px 28px rgb(0 0 0 / 30%), inset 0 0 0 1px color-mix(in srgb,var(--accent) 30%,transparent); transform:translateY(-3px); outline:none; }
.magic-choice__card[aria-pressed='true'] { border-color:var(--accent); }
.magic-choice__card span { display:block; margin-top:6px; font-size:14px; line-height:1.6; }
:global(.app-overlay__panel[data-testid='magic-choice-panel']) { width:min(960px,calc(100vw - 24px)); max-height:calc(100dvh - 24px); }
</style>

<style scoped>
.magic-choice__step { color:var(--accent); font-weight:700; }
.magic-choice__help { color:var(--text-secondary); }
.magic-choice__card img { display:block; flex:0 0 154px; width:110px; height:154px; aspect-ratio:2/3; object-fit:contain; margin:0 auto 10px; transition:filter 150ms ease,transform 150ms ease; }
.magic-choice__card:hover img,.magic-choice__card:focus-visible img { filter:saturate(1.12) brightness(1.06); transform:scale(1.03); }
.magic-choice__card b { display:block; font-size:17px; }
.magic-choice__card small { display:block; margin-top:6px; color:var(--text-secondary); }
.magic-choice__card > span:not(.magic-choice__recipient) { flex:1; min-height:0; overflow:hidden; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:4; line-clamp:4; }
.magic-choice__card.is-mine { border-color:#64d4e9; background:rgb(78 200 224 / 10%); }
.magic-choice__card.is-other { border-color:#e0bd70; background:rgb(224 189 112 / 9%); }
.magic-choice__recipient { position:absolute; top:8px; left:8px; padding:4px 8px; border-radius:6px; background:var(--surface); font-weight:700; }
.magic-choice__assignment { display:flex; flex-wrap:wrap; gap:10px 20px; align-items:center; margin-top:16px; }
@media(max-width:540px) { .magic-choice { padding:14px; } .magic-choice__cards { grid-template-columns:repeat(2,minmax(0,1fr)); grid-auto-rows:minmax(252px,1fr); gap:8px; max-height:50dvh; } .magic-choice__card { min-height:252px; max-height:290px; padding:10px; } .magic-choice__card img { flex-basis:104px; width:min(100%,76px); height:104px; } .magic-choice__card span { font-size:13px; } .magic-choice footer { flex-wrap:wrap; } }
</style>
