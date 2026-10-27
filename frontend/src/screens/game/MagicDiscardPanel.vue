<script setup lang="ts">
import { ref, watch } from 'vue'
import AppOverlay from '../../components/AppOverlay.vue'
import { cardArtUrl } from '../../cards/cardArt'
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
  <AppOverlay draggable v-if="game.state.dice_discard_pending" id="magic-discard-panel" :priority="190" :close-on-backdrop="false" labelledby="magic-discard-title">
    <section class="magic-discard battle-prompt">
      <header class="battle-prompt__head" data-drag-handle><div><p class="battle-prompt__context">弃牌选择</p><h2 id="magic-discard-title">{{ game.state.dice_discard_card || '魔法效果' }} · 弃置一张手牌</h2><span class="battle-prompt__drag-note">拖动标题可移动</span></div></header>
      <p class="magic-discard__hint">{{ match.diceDiscardMessage || '请选择要弃置的卡牌；确认后才会移入弃牌堆。' }}</p>
      <div class="magic-discard__cards">
        <button v-for="(card,index) in game.state.hand" :key="index" type="button" :data-testid="'magic-discard-card-' + index" :aria-pressed="selected===index" :disabled="busy" @click="selected=index">
          <img v-if="cardArtUrl(String(card.name))" :src="cardArtUrl(String(card.name))!" :alt="card.name + '卡面'" draggable="false" />
          <span class="magic-discard__copy"><b>{{ card.name }}</b><small>{{ selected === index ? '已选中 · 确认后弃置' : '点击选择这张手牌' }}</small><span>{{ card.description }}</span></span>
        </button>
      </div>
      <p v-if="!game.state.hand.length">没有可弃置的手牌，点击确认同步结果。</p>
      <p v-if="error" class="battle-prompt__error" role="alert" data-testid="magic-discard-error">{{ error }}</p>
      <p class="battle-prompt__status" :class="{ 'is-ready': selected >= 0 }" role="status">{{ selected >= 0 ? '将弃置「' + game.state.hand[selected]?.name + '」。' : '先选一张手牌，再确认弃置。' }}</p>
      <button class="button button--primary" type="button" data-testid="magic-discard-confirm" :disabled="busy || (game.state.hand.length > 0 && selected < 0)" @click="confirm">{{ busy ? '正在弃牌…' : '确认弃牌' }}</button>
    </section>
  </AppOverlay>
</template>
<style src="./battle-prompt.css"></style>
<style scoped>
.magic-discard { padding:26px; max-height:calc(100dvh - 24px); overflow-y:auto; }.magic-discard p { font-size:16px; line-height:1.7; }.magic-discard__hint { color:var(--prompt-muted); }
.magic-discard__cards { display:grid; gap:12px; max-height:50dvh; overflow:auto; margin:18px 0; padding:3px; }
.magic-discard__cards button { display:flex; align-items:flex-start; gap:18px; padding:14px; text-align:left; color:var(--prompt-text); background:var(--prompt-deck); border:1px solid var(--prompt-line); border-radius:10px; cursor:pointer; }
.magic-discard__cards button:hover,.magic-discard__cards button:focus-visible { border-color:var(--prompt-cyan); outline:2px solid rgb(116 215 233 / 18%); outline-offset:1px; }.magic-discard__cards button[aria-pressed='true'] { border-color:var(--prompt-gold); background:rgb(224 190 112 / 8%); }
.magic-discard__cards img { flex:0 0 82px; width:82px; height:120px; object-fit:contain; filter:drop-shadow(0 5px 8px #0007); }.magic-discard__copy { display:grid; gap:8px; min-width:0; }.magic-discard__copy b { font-size:18px; }.magic-discard__copy small { font-size:14px; color:var(--prompt-cyan); }.magic-discard__copy>span { font-size:15px; line-height:1.75; color:var(--prompt-muted); }.magic-discard__cards button[aria-pressed='true'] small { color:var(--prompt-gold); }
.magic-discard>.button { width:100%; margin-top:16px; }
:global(.app-overlay__panel[data-testid='magic-discard-panel']) { width:min(700px,calc(100vw - 24px)); }
@media(max-width:540px) { .magic-discard { padding:18px; }.magic-discard__cards button { padding:12px; gap:12px; }.magic-discard__cards img { width:68px; height:98px; flex-basis:68px; } }
</style>
