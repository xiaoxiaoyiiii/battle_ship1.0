<script setup lang="ts">
import { ref, watch } from 'vue'
import AppOverlay from '../../components/AppOverlay.vue'
import { useGameStore } from '../../stores/game'
import { useMatchStore } from '../../stores/match'
import { sendBattleEvent } from '../../realtime/battle'
const game=useGameStore()
const match=useMatchStore()
const selected=ref(-1), busy=ref(false), error=ref('')
watch(() => game.state.hand, () => { selected.value=-1 })
async function confirm(): Promise<void> {
  if(busy.value || (game.state.hand.length && selected.value < 0))return
  busy.value=true;error.value=''
  try {
    const ack=await sendBattleEvent('dice_discard_choose',{room_id:game.state.room_id,player_id:game.state.player_id,card_index:selected.value})
    if(ack.status!=='success'){error.value=ack.message || '弃牌失败，请重新选择。';return}
    // 服务端可能已经推送下一次弃牌义务，不能用旧请求的 ack 把它关闭。
  }catch{error.value='连接不稳定，弃牌请求仍保留。'}finally{busy.value=false}
}
</script>
<template>
  <AppOverlay v-if="game.state.dice_discard_pending" id="magic-discard-panel" :priority="190" :close-on-backdrop="false" labelledby="magic-discard-title">
    <section class="magic-discard"><h2 id="magic-discard-title">{{ game.state.dice_discard_card || '魔法效果' }} · 弃置一张手牌</h2><p>{{ match.diceDiscardMessage || '请选择要弃置的卡牌；确认后才会移入弃牌堆。' }}</p>
      <div class="magic-discard__cards"><button v-for="(card,index) in game.state.hand" :key="index" type="button" :data-testid="'magic-discard-card-' + index" :aria-pressed="selected===index" :disabled="busy" @click="selected=index"><b>{{ card.name }}</b><span>{{ card.description }}</span></button></div>
      <p v-if="!game.state.hand.length">没有可弃置的手牌，点击确认同步结果。</p><p v-if="error" role="alert" data-testid="magic-discard-error">{{ error }}</p><button class="button" type="button" data-testid="magic-discard-confirm" :disabled="busy || (game.state.hand.length > 0 && selected < 0)" @click="confirm">确认弃牌</button>
    </section>
  </AppOverlay>
</template>
<style scoped>
.magic-discard { padding:20px; }.magic-discard h2 { margin-top:0; font-size:20px; }.magic-discard p { line-height:1.7; }.magic-discard__cards { display:grid; gap:8px; max-height:45dvh; overflow:auto; margin:16px 0; }.magic-discard__cards button { padding:12px; text-align:left; color:var(--text-primary); background:var(--surface); border:1px solid var(--border); border-radius:6px; }.magic-discard__cards button[aria-pressed='true'] { border-color:var(--accent); }.magic-discard__cards span { display:block; margin-top:6px; font-size:14px; line-height:1.6; }:global(.app-overlay__panel[data-testid='magic-discard-panel']) { width:min(500px,calc(100vw - 24px)); max-height:calc(100dvh - 24px); }
</style>
